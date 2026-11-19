"""Closed-Loop Prompt & Skill Optimization Flywheel (Lab 6 — Starter).

Complete the ``# TODO(lab-6)`` blocks following ``workshop/06-LAB-OPTIMIZE-EVAL-AND-ALERTS.md``:
1. Query recent ``THUMBS_DOWN`` entries from the Feedback Service
   (``agentplatform.Client.feedback_entries.list(...)``).
2. Wire ADK's ``LocalEvalSampler`` + ``SimplePromptOptimizer`` /
   ``GEPARootAgentPromptOptimizer`` / ``GEPARootAgentOptimizer`` (``adk.dev/optimize/``).
3. Run non-mutating optimization and save the candidate instruction to
   ``artifacts/optimized_instruction.txt`` for human diff review & canary rollout.
"""

from __future__ import annotations

import argparse
import asyncio
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
    "hallucination": (
        "Constrain prompt to cite only observed stdout/stderr/file paths; add negative examples."
    ),
    "tool_error": (
        "Improve tool docstrings, argument validation, and error-recovery instructions."
    ),
    "inaccurate": (
        "Add unit-test verification rule and few-shot Example Store entries for recurring patterns."
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
    # TODO(lab-6): Set `os.environ["GOOGLE_GENAI_USE_ENTERPRISE"] = "TRUE"`, initialize
    # `agentplatform.Client(project=project_id, location=location)`, and call
    # `client.feedback_entries.list(name=runtime_name, config={"filter": 'feedback_type="THUMBS_DOWN"',
    # "order_by": "create_time desc"})`. Normalize up to `limit` entries into dicts.
    raise NotImplementedError(
        f"TODO(lab-6): Fetch up to {limit} THUMBS_DOWN entries for "
        f"project={project_id!r}, location={location!r}, runtime={runtime_name!r}."
    )


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
                pattern_counts[name] += int(cluster.get("count", 1))

    recommendations = [
        {"signal": sig, "recommended_fix": FAILURE_TO_FIX_MAP[sig]}
        for sig in list(pattern_counts.keys()) + list(label_counts.keys())
        if sig in FAILURE_TO_FIX_MAP
    ]
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
    # TODO(lab-6): Load `sampler_config_path`, construct:
    #   - `LocalEvalSamplerConfig(eval_config=EvalConfig(...), app_name="coding_agent", train_eval_set="train_eval_set")`
    #   - `LocalEvalSetsManager(agents_dir=str(agents_dir))`
    #   - `LocalEvalSampler(sampler_config, eval_sets_manager)`
    #   - Selected optimizer from `google.adk.optimization`:
    #       * "simple" -> `SimplePromptOptimizer(config=SimplePromptOptimizerConfig(...))`
    #       * "gepa" -> `GEPARootAgentPromptOptimizer(config=GEPARootAgentPromptOptimizerConfig(...))`
    #       * "gepa-skills" -> `GEPARootAgentOptimizer(config=GEPARootAgentOptimizerConfig(...))`
    # Return `(sampler, optimizer)`.
    raise NotImplementedError(
        f"TODO(lab-6): Build ADK sampler ({sampler_config_path}) + optimizer ({optimizer_choice}, "
        f"iterations={iterations}, batch_size={batch_size}, model={optimizer_model}, agents_dir={agents_dir})."
    )


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
    # TODO(lab-6): Import `root_agent` from `coding_agent.agent`, verify its instruction via
    # `_extract_root_instruction(root_agent, agent_architecture=get_settings().agent_architecture)`
    # (guards against ADK 2.0 `Workflow` roots in `graph`/`dynamic` modes), call
    # `build_adk_sampler_and_optimizer(...)`, await `optimizer.optimize(root_agent, sampler)`,
    # pick `best_idx` (from `result.gepa_result["best_idx"]` or highest `overall_score`),
    # compute a `difflib.unified_diff` against the original instruction, and return
    # `{"optimizer": ..., "best_idx": ..., "overall_score": ..., "original_instruction": ...,
    #   "optimized_instruction": ..., "unified_diff": ...}`.
    raise NotImplementedError(
        f"TODO(lab-6): Run ADK optimization ({optimizer_choice}, iterations={iterations}, "
        f"batch_size={batch_size}, model={optimizer_model}) from {sampler_config_path} / {agents_dir}."
    )


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
    parser.add_argument("--optimizer", choices=["simple", "gepa", "gepa-skills"], default="simple")
    parser.add_argument("--iterations", type=int, default=2)
    parser.add_argument("--batch-size", type=int, default=4)
    parser.add_argument("--optimizer-model", default="gemini-2.5-flash")
    parser.add_argument("--sampler-config", type=Path, default=Path("eval/sampler_config.json"))
    parser.add_argument("--output", type=Path, default=Path("artifacts/optimized_instruction.txt"))
    parser.add_argument("--loss-clusters-json", type=Path, default=None)
    parser.add_argument("--feedback-json", type=Path, default=None)
    parser.add_argument("--skip-feedback", action="store_true")
    parser.add_argument("--dry-run", action="store_true")
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
    runtime_name = settings.reasoning_engine_name or os.environ.get("REASONING_ENGINE_NAME", "")

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
    print(json.dumps({"saved_candidate_instruction": str(output_path), "overall_score": opt_result["overall_score"]}, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
