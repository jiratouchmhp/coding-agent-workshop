"""Closed-Loop Prompt & Skill Optimization Flywheel (Lab 6 — Solution).

Closes the Optimize Pillar loop by combining:
1. **Feedback Service Data:** Pulls recent ``THUMBS_DOWN`` entries via
   ``agentplatform.Client.feedback_entries.list(...)`` to surface real user
   failure labels (``inaccurate``, ``hallucination``, ``tool_error``, etc.).
2. **Failure Cluster Triage:** Maps loss patterns from ``generate_loss_clusters``
   or ``agents-cli eval analyze`` onto targeted prompt/tool/skill fixes.
3. **Automated ADK Prompt Optimization (``google-adk >= 1.24.0``, ``adk.dev/optimize/``):**
   Supports ``SimplePromptOptimizer`` (fast 4-stage Execute -> Evaluate -> Critique
   -> Rewrite loop), ``GEPARootAgentPromptOptimizer`` (default for ``adk optimize``,
   root instruction only), and ``GEPARootAgentOptimizer`` (root instruction +
   ``SkillToolset`` skill instructions) without mutating ``root_agent`` in place.
4. **CLI & Canary Rollout Guidance:** Prints exact ``adk optimize``,
   ``agents-cli eval optimize``, ``agents-cli eval compare``, Example Store
   (max 50/region/project), and ``v1beta1`` ``trafficSplitManual`` canary steps.
"""

from __future__ import annotations

import argparse
import asyncio
import difflib
import json
import logging
import os
import sys
from collections import Counter
from pathlib import Path
from typing import Any, Literal

TRACK_ROOT = Path(__file__).resolve().parents[1]
if str(TRACK_ROOT) not in sys.path:
    sys.path.insert(0, str(TRACK_ROOT))

from coding_agent.config import get_settings  # noqa: E402

logger = logging.getLogger(__name__)

OptimizerChoice = Literal["simple", "gepa", "gepa-skills"]

# Verified Failure-to-Fix Quick Map from `05_optimize` & `view-results`.
FAILURE_TO_FIX_MAP: dict[str, str] = {
    "Hallucination of Action": (
        "Strengthen system instruction: require Execute (`pytest`/`ruff`) tool call "
        "before claiming completion or citing pass counts."
    ),
    "Hallucination of Missing Information": (
        "Ground responses strictly in tool outputs; check `max_output_chars` truncation."
    ),
    "Incomplete Execution": (
        "Specify end-to-end verification steps so the agent finishes requested edits and tests."
    ),
    "Incorrect Parameter Mapping": (
        "Tighten tool parameter docstrings and JSON schemas; consider `tool_config` mode='ANY'."
    ),
    "Omission of Required Tool Call": (
        "Require inspecting files with ReadFile and verifying edits with Execute before replying."
    ),
    "Over-Punting": (
        "Clarify in-scope coding capabilities vs. out-of-scope production mutations."
    ),
    "hallucination": (
        "Constrain prompt to cite only observed stdout/stderr/file paths; add negative examples."
    ),
    "tool_error": (
        "Improve tool docstrings, argument validation, and error-recovery instructions."
    ),
    "inaccurate": (
        "Add unit-test verification rule and few-shot Example Store entries for recurring patterns."
    ),
    "incomplete": (
        "Require explicit checklist completion (ReadFile -> EditFile -> Execute -> report exit code)."
    ),
}


def fetch_negative_feedback(
    *,
    project_id: str,
    location: str,
    runtime_name: str,
    limit: int = 20,
) -> list[dict[str, Any]]:
    """Fetch recent ``THUMBS_DOWN`` entries from the Agent Platform Feedback Service."""
    if not project_id or not runtime_name:
        return []

    os.environ["GOOGLE_GENAI_USE_ENTERPRISE"] = "TRUE"
    try:
        import agentplatform

        client = agentplatform.Client(project=project_id, location=location)
    except ImportError:
        logger.warning("agentplatform SDK not installed; skipping remote Feedback Service query.")
        return []

    entries = list(
        client.feedback_entries.list(
            name=runtime_name,
            config={
                "filter": 'feedback_type="THUMBS_DOWN"',
                "order_by": "create_time desc",
            },
        )
    )[:limit]

    normalized: list[dict[str, Any]] = []
    for entry in entries:
        normalized.append(
            {
                "name": getattr(entry, "name", ""),
                "session_id": getattr(entry, "session_id", ""),
                "event_id": getattr(entry, "event_id", ""),
                "feedback_type": getattr(entry, "feedback_type", "THUMBS_DOWN"),
                "feedback_labels": list(getattr(entry, "feedback_labels", []) or []),
                "feedback_text": getattr(entry, "feedback_text", ""),
            }
        )
    return normalized


def summarize_failure_signals(
    feedback_entries: list[dict[str, Any]],
    loss_clusters: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Aggregate Feedback labels and Loss Cluster patterns into actionable recommendations."""
    label_counts: Counter[str] = Counter()
    for item in feedback_entries:
        for label in item.get("feedback_labels") or []:
            label_counts[str(label)] += 1

    pattern_counts: Counter[str] = Counter()
    if loss_clusters:
        clusters = loss_clusters.get("loss_clusters") or loss_clusters.get("clusters") or []
        for cluster in clusters:
            if isinstance(cluster, dict):
                name = str(cluster.get("loss_pattern") or cluster.get("name") or "Unknown")
                count = int(cluster.get("count", 1))
                pattern_counts[name] += count

    recommendations: list[dict[str, str]] = []
    for signal_name in list(pattern_counts.keys()) + list(label_counts.keys()):
        fix = FAILURE_TO_FIX_MAP.get(signal_name)
        if fix:
            recommendations.append({"signal": signal_name, "recommended_fix": fix})

    return {
        "negative_feedback_count": len(feedback_entries),
        "feedback_label_counts": dict(label_counts),
        "loss_pattern_counts": dict(pattern_counts),
        "targeted_recommendations": recommendations,
    }


def build_adk_sampler_and_optimizer(
    *,
    sampler_config_path: Path,
    agents_dir: Path,
    optimizer_choice: OptimizerChoice = "simple",
    iterations: int = 2,
    batch_size: int = 4,
    optimizer_model: str = "gemini-2.5-flash",
) -> tuple[Any, Any]:
    """Instantiate ADK ``LocalEvalSampler`` and the selected ``google.adk.optimization`` optimizer."""
    from google.adk.evaluation.eval_config import EvalConfig
    from google.adk.evaluation.local_eval_sets_manager import LocalEvalSetsManager
    from google.adk.optimization.local_eval_sampler import (
        LocalEvalSampler,
        LocalEvalSamplerConfig,
    )

    raw_cfg = json.loads(sampler_config_path.read_text(encoding="utf-8"))
    eval_cfg_dict = raw_cfg.get("eval_config") or {"criteria": {"response_match_score": 0.75}}

    sampler_config = LocalEvalSamplerConfig(
        eval_config=EvalConfig(**eval_cfg_dict),
        app_name=raw_cfg.get("app_name", "coding_agent"),
        train_eval_set=raw_cfg.get("train_eval_set", "train_eval_set"),
        validation_eval_set=raw_cfg.get("validation_eval_set"),
    )
    eval_sets_manager = LocalEvalSetsManager(agents_dir=str(agents_dir))
    sampler = LocalEvalSampler(sampler_config, eval_sets_manager)

    if optimizer_choice == "simple":
        from google.adk.optimization.simple_prompt_optimizer import (
            SimplePromptOptimizer,
            SimplePromptOptimizerConfig,
        )

        optimizer = SimplePromptOptimizer(
            config=SimplePromptOptimizerConfig(
                num_iterations=iterations,
                batch_size=batch_size,
                optimizer_model=optimizer_model,
            )
        )
    elif optimizer_choice == "gepa":
        from google.adk.optimization.gepa_root_agent_prompt_optimizer import (
            GEPARootAgentPromptOptimizer,
            GEPARootAgentPromptOptimizerConfig,
        )

        optimizer = GEPARootAgentPromptOptimizer(
            config=GEPARootAgentPromptOptimizerConfig(
                optimizer_model=optimizer_model,
                max_metric_calls=max(10, iterations * batch_size * 2),
                reflection_minibatch_size=min(3, max(1, batch_size)),
            )
        )
    elif optimizer_choice == "gepa-skills":
        from google.adk.optimization.gepa_root_agent_optimizer import (
            GEPARootAgentOptimizer,
            GEPARootAgentOptimizerConfig,
        )

        optimizer = GEPARootAgentOptimizer(
            config=GEPARootAgentOptimizerConfig(
                optimizer_model=optimizer_model,
                max_metric_calls=max(10, iterations * batch_size * 2),
                reflection_minibatch_size=min(3, max(1, batch_size)),
            )
        )
    else:
        raise ValueError(f"Unsupported optimizer_choice: {optimizer_choice!r}")

    return sampler, optimizer


def _extract_root_instruction(root_agent: Any, *, agent_architecture: str) -> str:
    """Validate that ``root_agent`` exposes a top-level string ``.instruction``."""
    raw_instruction = getattr(root_agent, "instruction", "")
    if isinstance(raw_instruction, str) and raw_instruction.strip():
        return raw_instruction
    hint = (
        f"root_agent ({type(root_agent).__name__}) has no top-level string `.instruction` "
        f"(AGENT_ARCHITECTURE={agent_architecture!r}). ADK root-agent prompt optimizers "
        "require an LlmAgent with an `.instruction` attribute — set AGENT_ARCHITECTURE=simple "
        "in `.env` (or target an inner LlmAgent such as `coder_agent`)."
    )
    logger.warning("%s", hint)
    raise ValueError(hint)


async def run_prompt_optimization(
    *,
    sampler_config_path: Path,
    agents_dir: Path,
    optimizer_choice: OptimizerChoice = "simple",
    iterations: int = 2,
    batch_size: int = 4,
    optimizer_model: str = "gemini-2.5-flash",
) -> dict[str, Any]:
    """Run non-mutating ADK prompt optimization and return best candidate + score."""
    from coding_agent.agent import root_agent

    original_instruction = _extract_root_instruction(
        root_agent,
        agent_architecture=get_settings().agent_architecture,
    )
    sampler, optimizer = build_adk_sampler_and_optimizer(
        sampler_config_path=sampler_config_path,
        agents_dir=agents_dir,
        optimizer_choice=optimizer_choice,
        iterations=iterations,
        batch_size=batch_size,
        optimizer_model=optimizer_model,
    )

    result = await optimizer.optimize(root_agent, sampler)

    best_idx = 0
    gepa_result = getattr(result, "gepa_result", None)
    if isinstance(gepa_result, dict) and "best_idx" in gepa_result:
        best_idx = int(gepa_result["best_idx"])
    elif getattr(result, "optimized_agents", None):
        scores = [
            float(getattr(item, "overall_score", 0.0) or 0.0)
            for item in result.optimized_agents
        ]
        best_idx = max(range(len(scores)), key=lambda i: scores[i])

    best_entry = result.optimized_agents[best_idx]
    optimized_instruction = str(getattr(best_entry.optimized_agent, "instruction", ""))
    overall_score = getattr(best_entry, "overall_score", None)

    diff_lines = list(
        difflib.unified_diff(
            original_instruction.splitlines(keepends=True),
            optimized_instruction.splitlines(keepends=True),
            fromfile="coding_agent/agent.py (before)",
            tofile="artifacts/optimized_instruction.txt (candidate)",
        )
    )
    return {
        "optimizer": optimizer_choice,
        "best_idx": best_idx,
        "overall_score": overall_score,
        "original_instruction": original_instruction,
        "optimized_instruction": optimized_instruction,
        "unified_diff": "".join(diff_lines),
    }


def _build_reference_commands(track_name: str, location: str, runtime_name: str) -> dict[str, Any]:
    target_engine = runtime_name or "projects/PROJECT_ID/locations/LOCATION/reasoningEngines/ENGINE_ID"
    return {
        "working_directory": f"{track_name}/",
        "adk_optimize_cli": (
            "adk optimize coding_agent "
            "--sampler_config_file_path eval/sampler_config.json "
            "--print_detailed_results --log_level INFO"
        ),
        "agents_cli_eval_optimize": (
            "agents-cli eval optimize --dataset eval/datasets/coding_agent_single_turn.json "
            "--target-metric final_response_quality"
        ),
        "agents_cli_eval_compare": (
            "agents-cli eval compare artifacts/grade_results/results_before.json "
            "artifacts/grade_results/results_after.json"
        ),
        "example_store_note": (
            "For recurring tool-call formatting fixes without redeploying code, pair with "
            "Vertex AI Example Store (cosine similarity retrieval; max 50 ExampleStores per region/project)."
        ),
        "canary_traffic_split_v1beta1": (
            f'curl -X PATCH -H "Authorization: Bearer $(gcloud auth print-access-token)" '
            f'-H "Content-Type: application/json" '
            f'"https://{location}-aiplatform.googleapis.com/v1beta1/{target_engine}?update_mask=traffic_config" '
            "-d '{\"trafficConfig\":{\"trafficSplitManual\":{\"targets\":["
            "{\"runtimeRevisionName\":\"STABLE_REV\",\"percent\":90},"
            "{\"runtimeRevisionName\":\"CANARY_REV\",\"percent\":10}]}}}'"
        ),
    }


def _build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Closed-loop prompt/skill optimization from Feedback & Failure Clusters.",
    )
    parser.add_argument("--project", help="GCP project ID (defaults to GOOGLE_CLOUD_PROJECT).")
    parser.add_argument("--location", help="GCP region (defaults to GOOGLE_CLOUD_LOCATION).")
    parser.add_argument(
        "--optimizer",
        choices=["simple", "gepa", "gepa-skills"],
        default="simple",
        help="ADK optimizer: simple (SimplePromptOptimizer), gepa, or gepa-skills.",
    )
    parser.add_argument("--iterations", type=int, default=2, help="Optimization iterations (default: 2).")
    parser.add_argument("--batch-size", type=int, default=4, help="Batch size per iteration (default: 4).")
    parser.add_argument(
        "--optimizer-model",
        default="gemini-2.5-flash",
        help="Model powering optimization critique/reflection.",
    )
    parser.add_argument(
        "--sampler-config",
        type=Path,
        default=Path("eval/sampler_config.json"),
        help="Path to ADK LocalEvalSamplerConfig JSON.",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("artifacts/optimized_instruction.txt"),
        help="Destination path for candidate optimized instruction.",
    )
    parser.add_argument(
        "--loss-clusters-json",
        type=Path,
        default=None,
        help="Optional JSON output from run_offline_eval.py / generate_loss_clusters.",
    )
    parser.add_argument(
        "--feedback-json",
        type=Path,
        default=None,
        help="Optional local JSON file containing sample Feedback Service entries.",
    )
    parser.add_argument(
        "--skip-feedback",
        action="store_true",
        help="Skip querying the live Agent Platform Feedback Service.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Validate sampler/evalset files, summarize signals, and print CLI commands without LLM calls.",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    args = _build_arg_parser().parse_args(argv)
    settings = get_settings()

    if settings.agent_architecture in {"graph", "dynamic"}:
        logger.warning(
            "AGENT_ARCHITECTURE=%r exposes an ADK 2.0 Workflow root_agent with no top-level "
            "`.instruction`. Switch to AGENT_ARCHITECTURE=simple (or target an inner LlmAgent "
            "such as `coder_agent`) before running live prompt optimization.",
            settings.agent_architecture,
        )

    project_id = args.project or settings.google_cloud_project
    location = args.location or settings.google_cloud_location
    runtime_name = settings.reasoning_engine_name

    sampler_path = (
        args.sampler_config
        if args.sampler_config.is_absolute() or args.sampler_config.exists()
        else TRACK_ROOT / args.sampler_config
    )
    if not sampler_path.is_file():
        raise FileNotFoundError(f"Sampler config not found: {sampler_path}")

    evalset_path = TRACK_ROOT / "coding_agent" / "train_eval_set.evalset.json"
    if not evalset_path.is_file():
        raise FileNotFoundError(f"ADK evalset not found: {evalset_path}")

    feedback_entries: list[dict[str, Any]] = []
    if args.feedback_json is not None and args.feedback_json.is_file():
        loaded = json.loads(args.feedback_json.read_text(encoding="utf-8"))
        feedback_entries = loaded if isinstance(loaded, list) else loaded.get("feedback_entries", [])
    elif not args.skip_feedback and not args.dry_run and project_id and runtime_name:
        feedback_entries = fetch_negative_feedback(
            project_id=project_id,
            location=location,
            runtime_name=runtime_name,
        )

    loss_clusters = (
        json.loads(args.loss_clusters_json.read_text(encoding="utf-8"))
        if args.loss_clusters_json is not None and args.loss_clusters_json.is_file()
        else None
    )
    triage_summary = summarize_failure_signals(feedback_entries, loss_clusters)
    reference_commands = _build_reference_commands(TRACK_ROOT.name, location, runtime_name)

    if args.dry_run:
        print(
            json.dumps(
                {
                    "dry_run": True,
                    "optimizer": args.optimizer,
                    "iterations": args.iterations,
                    "batch_size": args.batch_size,
                    "sampler_config": str(sampler_path),
                    "evalset_file": str(evalset_path),
                    "triage_summary": triage_summary,
                    "reference_commands": reference_commands,
                },
                indent=2,
            )
        )
        return 0

    opt_result = asyncio.run(
        run_prompt_optimization(
            sampler_config_path=sampler_path,
            agents_dir=TRACK_ROOT,
            optimizer_choice=args.optimizer,
            iterations=args.iterations,
            batch_size=args.batch_size,
            optimizer_model=args.optimizer_model,
        )
    )

    output_path = args.output if args.output.is_absolute() else TRACK_ROOT / args.output
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(opt_result["optimized_instruction"] + "\n", encoding="utf-8")

    print(
        json.dumps(
            {
                "triage_summary": triage_summary,
                "optimization_summary": {
                    "optimizer": opt_result["optimizer"],
                    "overall_score": opt_result["overall_score"],
                    "saved_candidate_instruction": str(output_path),
                },
                "reference_commands": reference_commands,
            },
            indent=2,
            default=str,
        )
    )
    if opt_result["unified_diff"]:
        print("\n=== Candidate Instruction Diff ===")
        print(opt_result["unified_diff"])
    return 0


if __name__ == "__main__":
    sys.exit(main())
