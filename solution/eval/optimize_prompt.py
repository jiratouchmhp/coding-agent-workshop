"""Closed-Loop Prompt & Skill Optimization Flywheel (Lab 6 — Solution).

Closes the Optimize Pillar loop across TWO tracks:
- **Track A — Root Prompt Optimization (Container Rebuild + Canary Rollout):**
  1. Pulls recent ``THUMBS_DOWN`` entries via
     ``agentplatform.Client.feedback_entries.list(...)`` to surface real user
     failure labels (``inaccurate``, ``hallucination``, ``tool_error``, etc.).
  2. Maps loss patterns from ``generate_loss_clusters`` or ``agents-cli eval analyze``
     onto targeted prompt, tool, or domain-skill fixes.
  3. Runs ADK optimization (``SimplePromptOptimizer``, ``GEPARootAgentPromptOptimizer``,
     or ``GEPARootAgentOptimizer``) without mutating ``root_agent`` in place.
  4. Saves the candidate instruction to ``artifacts/optimized_instruction.txt`` for
     holdout comparison (``agents-cli eval compare``) and ``v1beta1``
     ``trafficSplitManual`` canary rollout.

- **Track B — Skill Optimization & Zero-Redeploy Registry Update:**
  1. When ``--optimizer gepa-skills`` is selected, attaches the local skill directory
     via ``from google.adk.skills import load_skill_from_dir`` onto a cloned agent's
     ``SkillToolset(skills=[...])`` (critical ADK gotcha: ``GEPARootAgentOptimizer``
     reads local ``tool.skills``, not lazy remote ``GCPSkillRegistry`` handles).
  2. Extracts optimized skill instructions from ``SkillToolset.skills`` (or
     ``gepa_result["candidates"][best_idx]["skill_instructions:<name>"]``),
     preserves the original ``SKILL.md`` YAML frontmatter, diffs before/after, and
     writes candidate ``artifacts/optimized_skills/<skill_name>/SKILL.md``.
  3. Re-validates all 16 atomic Skill Registry ZIP checks via
     ``scripts/package_registry_skill.py`` and hot-updates Vertex AI Skill Registry
     with ``client.skills.update(...)`` (ZERO agent container rebuild!), plus prints
     exact Agent Registry immutable revision rollout (``revisions create v2`` ->
     ``skills update --default-revision=.../revisions/v2``) and 1-command rollback
     to ``v1``.
"""

from __future__ import annotations

import argparse
import asyncio
import difflib
import json
import logging
import os
import re
import subprocess
import sys
from collections import Counter
from pathlib import Path
from typing import Any, Literal

TRACK_ROOT = Path(__file__).resolve().parents[1]
REPO_ROOT = TRACK_ROOT.parent
if str(TRACK_ROOT) not in sys.path:
    sys.path.insert(0, str(TRACK_ROOT))

from coding_agent.config import get_settings  # noqa: E402

logger = logging.getLogger(__name__)

OptimizerChoice = Literal["simple", "gepa", "gepa-skills"]

_FRONTMATTER_RE = re.compile(r"\A(---\r?\n.*?\r?\n---\r?\n?)", re.DOTALL)

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
    "Constraint Violation": (
        "If domain audit rules (e.g. OWASP checks or file:line citations) were missed, "
        "refine `skills_to_register/secure-code-review/SKILL.md` with `--optimizer gepa-skills` "
        "and hot-update Skill Registry via `client.skills.update(...)` (zero container rebuild)."
    ),
    "hallucination": (
        "Constrain prompt to cite only observed stdout/stderr/file paths; add negative examples."
    ),
    "tool_error": (
        "Improve tool docstrings, argument validation, and error-recovery instructions."
    ),
    "inaccurate": (
        "Add unit-test verification rule, update domain skill instructions in Skill Registry, "
        "or add few-shot Example Store entries for recurring patterns."
    ),
    "incomplete": (
        "Require explicit checklist completion (ReadFile -> EditFile -> Execute -> report exit code)."
    ),
}


def _split_frontmatter(skill_md_text: str) -> tuple[str, str]:
    """Split a ``SKILL.md`` file into ``(yaml_frontmatter_block, markdown_body)``.

    Preserves the exact ``--- ... ---`` frontmatter block so GEPA-optimized
    Markdown instructions never drop required ``name``, ``description``, or
    ``license`` metadata needed by Skill Registry validation rules ``R12-R15``.
    """
    match = _FRONTMATTER_RE.match(skill_md_text)
    if not match:
        return "", skill_md_text
    frontmatter = match.group(1)
    body = skill_md_text[match.end() :]
    if not frontmatter.endswith("\n\n"):
        frontmatter = frontmatter.rstrip("\n") + "\n\n"
    return frontmatter, body


def _read_skill_metadata(skill_dir: Path) -> tuple[str, str]:
    """Extract display name and description from ``skill_dir/SKILL.md`` frontmatter."""
    skill_md = skill_dir / "SKILL.md"
    default_display = skill_dir.name.replace("-", " ").title()
    default_desc = f"Updated enterprise coding-agent skill package ({skill_dir.name})."
    if not skill_md.is_file():
        return default_display, default_desc

    frontmatter, _ = _split_frontmatter(skill_md.read_text(encoding="utf-8"))
    if not frontmatter:
        return default_display, default_desc

    try:
        import yaml

        raw_yaml = frontmatter.strip().strip("-").strip()
        parsed = yaml.safe_load(raw_yaml) or {}
        if isinstance(parsed, dict):
            name_val = str(parsed.get("name") or "").strip()
            desc_val = str(parsed.get("description") or "").strip()
            display = name_val.replace("-", " ").title() if name_val else default_display
            return display, (desc_val or default_desc)
    except Exception as exc:  # noqa: BLE001
        logger.debug("Falling back to default skill metadata (%s).", exc)
    return default_display, default_desc


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


def _attach_local_skill_for_gepa(root_agent: Any, skill_dir: Path | None) -> Any:
    """Clone ``root_agent`` with a local ``SkillToolset(skills=[...])`` for ``GEPARootAgentOptimizer``.

    Source-verified ADK gotcha: ``GEPARootAgentOptimizer`` inspects ``tool.skills``
    (local in-memory skills on ``SkillToolset``), NOT skills fetched lazily from a
    remote ``GCPSkillRegistry``. Loading ``skill_dir`` via ``load_skill_from_dir``
    lets GEPA optimize ``skill_instructions:<skill_name>`` cleanly offline before
    repackaging and publishing back to Skill Registry / Agent Registry.
    """
    if skill_dir is None or not (skill_dir / "SKILL.md").is_file():
        return root_agent

    from google.adk.skills import load_skill_from_dir
    from google.adk.tools.skill_toolset import SkillToolset

    local_skill = load_skill_from_dir(skill_dir)
    existing_tools = list(getattr(root_agent, "tools", []) or [])
    new_tools: list[Any] = []
    attached = False

    for tool in existing_tools:
        if isinstance(tool, SkillToolset):
            current_skills = list(getattr(tool, "skills", []) or [])
            if any(getattr(s, "name", "") == local_skill.name for s in current_skills):
                new_tools.append(tool)
            else:
                clone_fn = getattr(tool, "clone_with_updated_skills", None)
                if callable(clone_fn):
                    new_tools.append(clone_fn([*current_skills, local_skill]))
                else:
                    new_tools.append(SkillToolset(skills=[*current_skills, local_skill]))
            attached = True
        else:
            new_tools.append(tool)

    if not attached:
        new_tools.append(SkillToolset(skills=[local_skill]))

    clone_agent = getattr(root_agent, "clone", None)
    if callable(clone_agent):
        return clone_agent(update={"tools": new_tools})
    return root_agent


def _extract_optimized_skills(
    *,
    original_skill_dir: Path | None,
    optimized_agent: Any,
    gepa_candidate: dict[str, str] | None = None,
) -> dict[str, dict[str, str]]:
    """Extract optimized ``SkillToolset`` instructions and preserve YAML frontmatter."""
    extracted_bodies: dict[str, str] = {}

    try:
        from google.adk.tools.skill_toolset import SkillToolset
    except ImportError:
        SkillToolset = None  # type: ignore[assignment, misc]

    for tool in getattr(optimized_agent, "tools", []) or []:
        if SkillToolset is not None and isinstance(tool, SkillToolset):
            for skill in getattr(tool, "skills", []) or []:
                name = str(getattr(skill, "name", "")).strip()
                inst = str(getattr(skill, "instructions", "")).strip()
                if name and inst:
                    extracted_bodies[name] = inst

    if isinstance(gepa_candidate, dict):
        prefix = "skill_instructions:"
        for key, value in gepa_candidate.items():
            if key.startswith(prefix) and isinstance(value, str) and value.strip():
                skill_name = key[len(prefix) :].strip()
                extracted_bodies.setdefault(skill_name, value.strip())

    results: dict[str, dict[str, str]] = {}
    for skill_name, optimized_body in extracted_bodies.items():
        original_md = ""
        frontmatter = ""
        if original_skill_dir is not None and (original_skill_dir / "SKILL.md").is_file():
            if original_skill_dir.name == skill_name or len(extracted_bodies) == 1:
                original_md = (original_skill_dir / "SKILL.md").read_text(encoding="utf-8")
                frontmatter, _ = _split_frontmatter(original_md)

        candidate_md = f"{frontmatter}{optimized_body.rstrip()}\n"
        diff_lines = list(
            difflib.unified_diff(
                original_md.splitlines(keepends=True),
                candidate_md.splitlines(keepends=True),
                fromfile=f"skills_to_register/{skill_name}/SKILL.md (before)",
                tofile=f"artifacts/optimized_skills/{skill_name}/SKILL.md (candidate)",
            )
        )
        results[skill_name] = {
            "candidate_skill_md": candidate_md,
            "unified_diff": "".join(diff_lines),
        }
    return results


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
    skill_dir: Path | None = None,
) -> dict[str, Any]:
    """Run non-mutating ADK prompt (and optional skill) optimization and return best candidate."""
    from coding_agent.agent import root_agent

    original_instruction = _extract_root_instruction(
        root_agent,
        agent_architecture=get_settings().agent_architecture,
    )
    target_agent = (
        _attach_local_skill_for_gepa(root_agent, skill_dir)
        if optimizer_choice == "gepa-skills"
        else root_agent
    )

    sampler, optimizer = build_adk_sampler_and_optimizer(
        sampler_config_path=sampler_config_path,
        agents_dir=agents_dir,
        optimizer_choice=optimizer_choice,
        iterations=iterations,
        batch_size=batch_size,
        optimizer_model=optimizer_model,
    )

    result = await optimizer.optimize(target_agent, sampler)

    best_idx = 0
    gepa_result = getattr(result, "gepa_result", None)
    gepa_candidate: dict[str, str] | None = None
    if isinstance(gepa_result, dict) and "best_idx" in gepa_result:
        best_idx = int(gepa_result["best_idx"])
        candidates = gepa_result.get("candidates")
        if isinstance(candidates, list) and 0 <= best_idx < len(candidates):
            if isinstance(candidates[best_idx], dict):
                gepa_candidate = candidates[best_idx]
    elif getattr(result, "optimized_agents", None):
        scores = [
            float(getattr(item, "overall_score", 0.0) or 0.0)
            for item in result.optimized_agents
        ]
        best_idx = max(range(len(scores)), key=lambda i: scores[i])

    best_entry = result.optimized_agents[best_idx]
    optimized_instruction = str(getattr(best_entry.optimized_agent, "instruction", ""))
    overall_score = getattr(best_entry, "overall_score", None)

    optimized_skills = (
        _extract_optimized_skills(
            original_skill_dir=skill_dir,
            optimized_agent=best_entry.optimized_agent,
            gepa_candidate=gepa_candidate,
        )
        if optimizer_choice == "gepa-skills"
        else {}
    )

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
        "optimized_skills": optimized_skills,
    }


def publish_updated_skill(
    *,
    project_id: str,
    skill_location: str,
    skill_id: str,
    skill_dir: Path,
    display_name: str | None = None,
    description: str | None = None,
    zip_output_path: Path | None = None,
    dry_run: bool = False,
) -> dict[str, Any]:
    """Validate all 16 atomic Skill Registry rules and hot-update the skill via ``client.skills.update``.

    Updates the live skill package in Vertex AI Skill Registry (``aiplatform.googleapis.com/v1beta1``)
    with **zero agent container rebuild** because ``GCPSkillRegistry`` + ``SkillToolset``
    fetches skills dynamically at runtime.
    """
    if not (skill_dir / "SKILL.md").is_file():
        raise FileNotFoundError(f"Skill directory missing SKILL.md: {skill_dir}")

    packager = REPO_ROOT / "scripts" / "package_registry_skill.py"
    if not packager.is_file():
        raise FileNotFoundError(f"Skill packager script not found: {packager}")

    resolved_display, resolved_desc = _read_skill_metadata(skill_dir)
    final_display = display_name or resolved_display
    final_desc = description or resolved_desc
    target_project = project_id or "PROJECT_ID"
    resource_name = (
        f"projects/{target_project}/locations/{skill_location}/skills/{skill_id}"
    )

    zip_path = zip_output_path or (REPO_ROOT / "dist" / f"{skill_id}.zip")
    cmd = [sys.executable, str(packager), str(skill_dir)]
    if dry_run:
        cmd.append("--dry-run")
    else:
        zip_path.parent.mkdir(parents=True, exist_ok=True)
        cmd.extend(["--output", str(zip_path)])

    proc = subprocess.run(cmd, capture_output=True, text=True, check=False)
    if proc.returncode != 0:
        raise RuntimeError(
            f"Skill Registry 16-rule validation failed for {skill_dir}:\n"
            f"{proc.stdout}\n{proc.stderr}"
        )

    if dry_run:
        return {
            "dry_run": True,
            "validation_passed": True,
            "zero_agent_container_rebuild": True,
            "skill_resource_name": resource_name,
            "display_name": final_display,
            "description": final_desc,
            "local_path": str(skill_dir),
            "sdk_call": (
                f'client.skills.update(name="{resource_name}", '
                f'config={{"display_name": "{final_display}", '
                f'"description": "{final_desc}", "local_path": "{zip_path}"}})'
            ),
        }

    if not project_id:
        raise ValueError("GOOGLE_CLOUD_PROJECT (or --project) is required to publish skill updates.")

    os.environ["GOOGLE_GENAI_USE_ENTERPRISE"] = "TRUE"
    import agentplatform

    client = agentplatform.Client(project=project_id, location=skill_location)
    updated = client.skills.update(
        name=resource_name,
        config={
            "display_name": final_display,
            "description": final_desc,
            "local_path": str(zip_path),
        },
    )
    return {
        "dry_run": False,
        "validation_passed": True,
        "zero_agent_container_rebuild": True,
        "skill_resource_name": getattr(updated, "name", resource_name),
        "zip_path": str(zip_path),
    }


def _build_reference_commands(
    *,
    track_name: str,
    project_id: str,
    location: str,
    skill_location: str,
    agent_registry_location: str,
    runtime_name: str,
    skill_id: str,
) -> dict[str, Any]:
    proj = project_id or "PROJECT_ID"
    target_engine = (
        runtime_name
        or f"projects/{proj}/locations/{location}/reasoningEngines/ENGINE_ID"
    )
    private_skill_id = skill_id if skill_id.startswith("private-") else f"private-{skill_id}"
    return {
        "working_directory": f"{track_name}/",
        "adk_optimize_cli": (
            "adk optimize coding_agent "
            "--sampler_config_file_path eval/sampler_config.json "
            "--print_detailed_results --log_level INFO"
        ),
        "gepa_skills_optimize_cmd": (
            f"uv run python eval/optimize_prompt.py --optimizer gepa-skills "
            f"--skill-dir skills_to_register/{skill_id} --iterations 2 --batch-size 4"
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
        "skill_registry_package_zip": (
            f"python3 ../scripts/package_registry_skill.py "
            f"skills_to_register/{skill_id} --output ../dist/{skill_id}.zip"
        ),
        "skill_registry_hot_update_cli": (
            f"uv run python eval/optimize_prompt.py --publish-skill "
            f"--skill-dir skills_to_register/{skill_id} --skill-id {skill_id}"
        ),
        "skill_registry_update_rest": (
            f'curl -X PATCH -H "Authorization: Bearer $(gcloud auth application-default print-access-token)" '
            f'-H "Content-Type: application/json; charset=utf-8" '
            f'-d \'{{"displayName":"Secure Code Review","description":"Updated from Lab 6 eval flywheel",'
            f'"zippedFilesystem":"\'"$(base64 -w 0 ../dist/{skill_id}.zip)"\'"}} \' '
            f'"https://{skill_location}-aiplatform.googleapis.com/v1beta1/projects/{proj}/locations/{skill_location}/skills/{skill_id}?updateMask=displayName,description,zippedFilesystem"'
        ),
        "agent_registry_revision_create_v2": (
            f"gcloud agent-registry skills revisions create v2 "
            f"--skill={private_skill_id} --project={proj} "
            f"--location={agent_registry_location} --payload=\"../dist/{skill_id}.zip\""
        ),
        "agent_registry_revision_promote_v2": (
            f"gcloud agent-registry skills update {private_skill_id} "
            f"--project={proj} --location={agent_registry_location} "
            f'--default-revision="projects/{proj}/locations/{agent_registry_location}/skills/{private_skill_id}/revisions/v2"'
        ),
        "agent_registry_revision_rollback_v1": (
            f"gcloud agent-registry skills update {private_skill_id} "
            f"--project={proj} --location={agent_registry_location} "
            f'--default-revision="projects/{proj}/locations/{agent_registry_location}/skills/{private_skill_id}/revisions/v1"'
        ),
    }


def _build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Closed-loop prompt & skill optimization from Feedback & Failure Clusters.",
    )
    parser.add_argument("--project", help="GCP project ID (defaults to GOOGLE_CLOUD_PROJECT).")
    parser.add_argument("--location", help="GCP region (defaults to GOOGLE_CLOUD_LOCATION).")
    parser.add_argument(
        "--optimizer",
        choices=["simple", "gepa", "gepa-skills"],
        default="simple",
        help="ADK optimizer: simple (SimplePromptOptimizer), gepa, or gepa-skills (GEPARootAgentOptimizer).",
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
        help="Destination path for candidate optimized root instruction.",
    )
    parser.add_argument(
        "--skill-dir",
        type=Path,
        default=Path("skills_to_register/secure-code-review"),
        help="Local skill directory loaded for --optimizer gepa-skills and --publish-skill.",
    )
    parser.add_argument(
        "--skill-id",
        default="secure-code-review",
        help="Skill ID in Vertex AI Skill Registry (default: secure-code-review).",
    )
    parser.add_argument(
        "--skill-output-dir",
        type=Path,
        default=Path("artifacts/optimized_skills"),
        help="Directory where candidate optimized SKILL.md files are saved for diff review.",
    )
    parser.add_argument(
        "--publish-skill",
        action="store_true",
        help="Validate (16 checks) and hot-update --skill-dir into Vertex AI Skill Registry via client.skills.update.",
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
        help="Validate sampler/evalset/skill files, summarize signals, and print CLI commands without LLM/network calls.",
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
    skill_location = settings.skill_registry_location or "us-central1"
    agent_registry_location = settings.agent_registry_location or "us-central1"
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

    skill_dir = (
        args.skill_dir
        if args.skill_dir.is_absolute() or args.skill_dir.exists()
        else TRACK_ROOT / args.skill_dir
    )

    feedback_entries: list[dict[str, Any]] = []
    if args.feedback_json is not None and args.feedback_json.is_file():
        loaded = json.loads(args.feedback_json.read_text(encoding="utf-8"))
        feedback_entries = loaded if isinstance(loaded, list) else loaded.get("feedback_entries", [])
    elif not args.skip_feedback and not args.dry_run and not args.publish_skill and project_id and runtime_name:
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
    reference_commands = _build_reference_commands(
        track_name=TRACK_ROOT.name,
        project_id=project_id,
        location=location,
        skill_location=skill_location,
        agent_registry_location=agent_registry_location,
        runtime_name=runtime_name,
        skill_id=args.skill_id,
    )

    if args.publish_skill:
        publish_result = publish_updated_skill(
            project_id=project_id,
            skill_location=skill_location,
            skill_id=args.skill_id,
            skill_dir=skill_dir,
            dry_run=args.dry_run,
        )
        print(
            json.dumps(
                {
                    "publish_skill_result": publish_result,
                    "reference_commands": reference_commands,
                },
                indent=2,
            )
        )
        return 0

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
                    "skill_dir": str(skill_dir),
                    "skill_dir_exists": (skill_dir / "SKILL.md").is_file(),
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
            skill_dir=skill_dir if (skill_dir / "SKILL.md").is_file() else None,
        )
    )

    output_path = args.output if args.output.is_absolute() else TRACK_ROOT / args.output
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(opt_result["optimized_instruction"] + "\n", encoding="utf-8")

    saved_skills: dict[str, str] = {}
    skill_out_root = (
        args.skill_output_dir
        if args.skill_output_dir.is_absolute()
        else TRACK_ROOT / args.skill_output_dir
    )
    for skill_name, skill_payload in (opt_result.get("optimized_skills") or {}).items():
        candidate_path = skill_out_root / skill_name / "SKILL.md"
        candidate_path.parent.mkdir(parents=True, exist_ok=True)
        candidate_path.write_text(skill_payload["candidate_skill_md"], encoding="utf-8")
        saved_skills[skill_name] = str(candidate_path)

    print(
        json.dumps(
            {
                "triage_summary": triage_summary,
                "optimization_summary": {
                    "optimizer": opt_result["optimizer"],
                    "overall_score": opt_result["overall_score"],
                    "saved_candidate_instruction": str(output_path),
                    "saved_candidate_skills": saved_skills,
                },
                "reference_commands": reference_commands,
            },
            indent=2,
            default=str,
        )
    )
    if opt_result["unified_diff"]:
        print("\n=== Candidate Root Instruction Diff ===")
        print(opt_result["unified_diff"])
    for skill_name, skill_payload in (opt_result.get("optimized_skills") or {}).items():
        if skill_payload.get("unified_diff"):
            print(f"\n=== Candidate Skill Diff ({skill_name}) ===")
            print(skill_payload["unified_diff"])
    return 0


if __name__ == "__main__":
    sys.exit(main())
