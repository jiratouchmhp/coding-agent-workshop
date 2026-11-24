"""Closed-Loop Prompt & Skill Optimization Flywheel (Lab 6 — Starter).

Core Lab 6 exercises (see ``workshop/06-LAB-OPTIMIZE-EVAL-AND-ALERTS.md``):
1. ``run_prompt_optimization()``: Run non-mutating ADK optimization (attaching local skills
   via ``_attach_local_skill_for_gepa()`` when ``--optimizer gepa-skills`` is chosen so
   ``GEPARootAgentOptimizer`` optimizes ``SkillToolset.skills``) and return candidate diffs
   for human review.
2. ``publish_updated_skill()``: Close the skill loop with zero container rebuild — re-validate
   all 16 atomic Skill Registry rules via ``scripts/package_registry_skill.py`` and hot-update
   Vertex AI Skill Registry via ``client.skills.update(...)`` passing the validated skill
   directory path (or promote an immutable Agent Registry ``rev-2`` revision).

Setup helpers (``fetch_negative_feedback()``, ``_attach_local_skill_for_gepa()``,
``build_adk_sampler_and_optimizer()``) are pre-filled so you can focus on the core
optimization and zero-redeploy skill publishing loop.
"""

from __future__ import annotations

import argparse
import asyncio
import difflib
import json
import logging
import os
import re
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
}


def _split_frontmatter(skill_md_text: str) -> tuple[str, str]:
    """Split ``SKILL.md`` into ``(yaml_frontmatter_block, markdown_body)``."""
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
    # Pre-filled boilerplate helper
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
    # Pre-filled boilerplate helper
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
            parent=runtime_name,
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


def _attach_local_skill_for_gepa(root_agent: Any, skill_dir: Path | None) -> Any:
    """Clone ``root_agent`` with a local ``SkillToolset(skills=[...])`` for ``GEPARootAgentOptimizer``.

    Source-verified ADK gotcha: ``GEPARootAgentOptimizer`` inspects ``tool.skills``
    (local in-memory skills on ``SkillToolset``), NOT skills fetched lazily from a
    remote ``GCPSkillRegistry``. Loading ``skill_dir`` via ``load_skill_from_dir``
    lets GEPA optimize ``skill_instructions:<skill_name>`` cleanly offline before
    repackaging and publishing back to Skill Registry / Agent Registry.
    """
    # Pre-filled boilerplate helper
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
    # Pre-filled boilerplate helper
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


def _make_routed_llm_factory(settings: Any) -> Any:
    """Return a factory matching ``optimizer._llm_class(model=...)`` routed to ``MODEL_LOCATION``."""
    from coding_agent.models import build_gemini_model

    def _factory(model: str, **_: Any) -> Any:
        return build_gemini_model(settings, model_override=model)

    return _factory


def _bind_optimizer_gemini4_routing(
    optimizer: Any,
    *,
    settings: Any,
    optimizer_model: str,
) -> Any:
    """Route ADK optimizer LLM calls to ``settings.model_location`` (e.g., ``global``).

    Without explicit ``client_kwargs`` routing, ADK's ``SimplePromptOptimizer`` and
    ``GEPARootAgent*Optimizer`` instantiate models via ``LLMRegistry`` using the process-wide
    ``GOOGLE_CLOUD_LOCATION`` (``asia-southeast1``), causing HTTP 404 for global-only
    Frontier Gemini 4 models (``gemini-4-hydrogen`` / ``gemini-4-neon``).
    """
    from coding_agent.models import build_gemini_model

    if hasattr(optimizer, "_llm"):
        optimizer._llm = build_gemini_model(settings, model_override=optimizer_model)
    if hasattr(optimizer, "_llm_class"):
        optimizer._llm_class = _make_routed_llm_factory(settings)
    return optimizer


def build_adk_sampler_and_optimizer(
    *,
    sampler_config_path: Path,
    agents_dir: Path,
    optimizer_choice: OptimizerChoice = "simple",
    iterations: int = 2,
    batch_size: int = 4,
    optimizer_model: str = "gemini-4-hydrogen",
) -> tuple[Any, Any]:
    """Instantiate ADK ``LocalEvalSampler`` and the selected ``google.adk.optimization`` optimizer."""
    # Pre-filled boilerplate helper
    from google.adk.evaluation.eval_config import EvalConfig
    from google.adk.evaluation.local_eval_sets_manager import LocalEvalSetsManager
    from google.adk.optimization.local_eval_sampler import (
        LocalEvalSampler,
        LocalEvalSamplerConfig,
    )

    from coding_agent.models import build_gemini4_generate_config

    cfg = get_settings()
    # ADK 2.15 optimizers default to `ThinkingConfig(thinking_budget=10240)`, which causes
    # HTTP 400 on Gemini 4; pass a Gemini 4 `thinking_level` GenerateContentConfig explicitly.
    gemini4_model_config = build_gemini4_generate_config(cfg, include_thoughts=True)

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
                model_configuration=gemini4_model_config,
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
                model_configuration=gemini4_model_config,
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
                model_configuration=gemini4_model_config,
                max_metric_calls=max(10, iterations * batch_size * 2),
                reflection_minibatch_size=min(3, max(1, batch_size)),
            )
        )
    else:
        raise ValueError(f"Unsupported optimizer_choice: {optimizer_choice!r}")

    _bind_optimizer_gemini4_routing(
        optimizer,
        settings=cfg,
        optimizer_model=optimizer_model,
    )
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
    optimizer_model: str = "gemini-4-hydrogen",
    skill_dir: Path | None = None,
) -> dict[str, Any]:
    """Run non-mutating ADK prompt (and optional skill) optimization and return best candidate."""
    # TODO(lab-6): Import `root_agent` from `coding_agent.agent`, verify its instruction via
    # `_extract_root_instruction(root_agent, agent_architecture=get_settings().agent_architecture)`.
    # If `optimizer_choice == "gepa-skills"`, attach local `skill_dir` via
    # `_attach_local_skill_for_gepa(root_agent, skill_dir)`. Then call
    # `build_adk_sampler_and_optimizer(...)`, await `optimizer.optimize(target_agent, sampler)`,
    # select `best_idx`, extract any optimized `SkillToolset.skills` via
    # `_extract_optimized_skills(...)` (preserving YAML frontmatter with `_split_frontmatter()`),
    # compute unified diff via `difflib.unified_diff(...)`, and return:
    # `{"optimizer": ..., "best_idx": ..., "overall_score": ..., "original_instruction": ...,
    #   "optimized_instruction": ..., "unified_diff": ..., "optimized_skills": {...}}`.
    raise NotImplementedError(
        f"TODO(lab-6): Run ADK optimization ({optimizer_choice}, iterations={iterations}, "
        f"batch_size={batch_size}, model={optimizer_model}, skill_dir={skill_dir}) "
        f"from {sampler_config_path} / {agents_dir}."
    )


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
    """Validate all 16 atomic Skill Registry rules and hot-update the skill via ``client.skills.update``."""
    # TODO(lab-6):
    # 1. Resolve defaults via `_read_skill_metadata(skill_dir)` and run
    #    `scripts/package_registry_skill.py <skill_dir>` via `subprocess.run(...)`
    #    (`--dry-run` when `dry_run=True`, else `--output dist/<skill_id>.zip`), failing fast
    #    if any of the 16 atomic rules fail (and producing the `.zip` for Agent Registry CLI).
    # 2. When `not dry_run`, set `os.environ["GOOGLE_GENAI_USE_ENTERPRISE"] = "TRUE"`,
    #    initialize `agentplatform.Client(project=project_id, location=skill_location)`, and call:
    #      `client.skills.update(name=f"projects/{project_id}/locations/{skill_location}/skills/{skill_id}",`
    #      `config={"display_name": ..., "description": ..., "local_path": str(skill_dir.resolve())})`
    #    IMPORTANT: Pass the validated skill directory (`str(skill_dir.resolve())`), NEVER `str(zip_path)` —
    #    `agentplatform` zips the directory directly and raises `ValueError: Path is not a directory` on `.zip`.
    #    Updating the skill in Skill Registry takes effect with ZERO agent container rebuild!
    raise NotImplementedError(
        f"TODO(lab-6): Validate {skill_dir} and hot-update Skill Registry skill "
        f"{skill_id!r} in {project_id!r}/{skill_location!r} (dry_run={dry_run})."
    )


def _build_reference_commands(
    *,
    track_name: str,
    project_id: str,
    location: str,
    skill_location: str,
    agent_registry_skills_location: str = "global",
    runtime_name: str,
    skill_id: str,
) -> dict[str, Any]:
    proj = project_id or "PROJECT_ID"
    target_engine = (
        runtime_name
        or f"projects/{proj}/locations/{location}/reasoningEngines/ENGINE_ID"
    )
    private_skill_id = skill_id if skill_id.startswith("private-") else f"private-{skill_id}"
    skills_loc_expr = f"${{AGENT_REGISTRY_SKILLS_LOCATION:-{agent_registry_skills_location}}}"
    return {
        "working_directory": f"{track_name}/",
        "adk_optimize_cli": (
            "GOOGLE_CLOUD_LOCATION=${MODEL_LOCATION:-global} adk optimize coding_agent "
            "--sampler_config_file_path eval/sampler_config.json "
            "--print_detailed_results --log_level INFO"
        ),
        "adk_optimize_gemini4_note": (
            "Prefer `uv run python eval/optimize_prompt.py` (which overrides ADK 2.15's default "
            "`thinking_budget=10240` with Gemini 4 `thinking_level` and routes to MODEL_LOCATION=global); "
            "if invoking `adk optimize` directly with Gemini 4, pass `--optimizer_config_file_path` "
            "with a `thinking_level`-based `model_configuration`."
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
            f"--skill-dir skills_to_register/{skill_id} --skill-id {skill_id} "
            f"--skill-location {skill_location}"
        ),
        "skill_registry_update_rest": (
            f'curl -X PATCH -H "Authorization: Bearer $(gcloud auth application-default print-access-token)" '
            f'-H "Content-Type: application/json; charset=utf-8" '
            f'-d \'{{"displayName":"Secure Code Review","description":"Updated from Lab 6 eval flywheel",'
            f'"zippedFilesystem":"\'"$(base64 -w 0 ../dist/{skill_id}.zip)"\'"}} \' '
            f'"https://{skill_location}-aiplatform.googleapis.com/v1beta1/projects/{proj}/locations/{skill_location}/skills/{skill_id}?updateMask=displayName,description,zippedFilesystem"'
        ),
        "agent_registry_skill_create": (
            f"gcloud alpha agent-registry skills create {skill_id} "
            f'--project={proj} --location="{skills_loc_expr}" '
            "--target-state=active --scanning-policy=enabled-nonblocking"
        ),
        "agent_registry_revision_create_rev1": (
            f"gcloud alpha agent-registry skills revisions create rev-1 "
            f"--skill={private_skill_id} --project={proj} "
            f'--location="{skills_loc_expr}" --payload="../dist/{skill_id}.zip"'
        ),
        "agent_registry_revision_create_rev2": (
            f"gcloud alpha agent-registry skills revisions create rev-2 "
            f"--skill={private_skill_id} --project={proj} "
            f'--location="{skills_loc_expr}" --payload="../dist/{skill_id}.zip"'
        ),
        "agent_registry_revision_describe_rev2": (
            f"gcloud alpha agent-registry skills revisions describe rev-2 "
            f"--skill={private_skill_id} --project={proj} "
            f'--location="{skills_loc_expr}"'
        ),
        "agent_registry_scan_policy_note": (
            "Agent Registry skills default to `STATE_DRAFT` (which causes `GCPSkillRegistry.get_skill()` "
            "to return HTTP 400 FAILED_PRECONDITION) unless `--target-state=active` is passed. "
            "Under ENABLED_BLOCKING, promoting `--default-revision` also fails with FAILED_PRECONDITION "
            "until `revisions describe` shows `scanResult.scanState: SUCCEEDED` (or pass "
            "`--scanning-policy=enabled-nonblocking` when creating a rapid workshop demo skill)."
        ),
        "agent_registry_revision_promote_rev2": (
            f"gcloud alpha agent-registry skills update {private_skill_id} "
            f'--project={proj} --location="{skills_loc_expr}" --target-state=active '
            f'--default-revision="projects/{proj}/locations/{skills_loc_expr}/skills/{private_skill_id}/revisions/rev-2"'
        ),
        "agent_registry_revision_rollback_rev1": (
            f"gcloud alpha agent-registry skills update {private_skill_id} "
            f'--project={proj} --location="{skills_loc_expr}" --target-state=active '
            f'--default-revision="projects/{proj}/locations/{skills_loc_expr}/skills/{private_skill_id}/revisions/rev-1"'
        ),
        "agent_registry_cleanup": (
            f"gcloud alpha agent-registry skills update {private_skill_id} "
            f'--clear-default-revision --target-state=disabled --project={proj} --location="{skills_loc_expr}" && '
            f"gcloud alpha agent-registry skills revisions delete rev-2 "
            f'--skill={private_skill_id} --project={proj} --location="{skills_loc_expr}" --quiet && '
            f"gcloud alpha agent-registry skills revisions delete rev-1 "
            f'--skill={private_skill_id} --project={proj} --location="{skills_loc_expr}" --quiet && '
            f"gcloud alpha agent-registry skills delete {private_skill_id} "
            f'--project={proj} --location="{skills_loc_expr}" --quiet'
        ),
    }


def _build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Closed-loop prompt & skill optimization from Feedback & Failure Clusters.",
    )
    parser.add_argument("--project", help="GCP project ID (defaults to GOOGLE_CLOUD_PROJECT).")
    parser.add_argument("--location", help="GCP region (defaults to GOOGLE_CLOUD_LOCATION).")
    parser.add_argument(
        "--skill-location",
        default=None,
        help="Vertex AI Skill Registry region (defaults to SKILL_REGISTRY_LOCATION / 'us-central1').",
    )
    parser.add_argument("--optimizer", choices=["simple", "gepa", "gepa-skills"], default="simple")
    parser.add_argument("--iterations", type=int, default=2)
    parser.add_argument("--batch-size", type=int, default=4)
    parser.add_argument("--optimizer-model", default=None)
    parser.add_argument("--sampler-config", type=Path, default=Path("eval/sampler_config.json"))
    parser.add_argument("--output", type=Path, default=Path("artifacts/optimized_instruction.txt"))
    parser.add_argument("--skill-dir", type=Path, default=Path("skills_to_register/secure-code-review"))
    parser.add_argument("--skill-id", default="secure-code-review")
    parser.add_argument("--skill-output-dir", type=Path, default=Path("artifacts/optimized_skills"))
    parser.add_argument("--publish-skill", action="store_true")
    parser.add_argument("--loss-clusters-json", type=Path, default=None)
    parser.add_argument("--feedback-json", type=Path, default=None)
    parser.add_argument("--skip-feedback", action="store_true")
    parser.add_argument("--dry-run", action="store_true")
    return parser


def main(argv: list[str] | None = None) -> int:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    args = _build_arg_parser().parse_args(argv)
    settings = get_settings()

    if settings.agent_architecture in {"graph", "dynamic", "agy_harness"}:
        logger.warning(
            "AGENT_ARCHITECTURE=%r exposes an ADK 2.0 Workflow root_agent with no top-level "
            "`.instruction`. Switch to AGENT_ARCHITECTURE=simple (or target an inner LlmAgent "
            "such as `coder_agent`) before running live prompt optimization.",
            settings.agent_architecture,
        )

    project_id = args.project or settings.google_cloud_project
    location = args.location or settings.google_cloud_location
    skill_location = (
        (args.skill_location or "").strip()
        or settings.skill_registry_location
        or "us-central1"
    )
    agent_registry_skills_location = settings.agent_registry_skills_location or "global"
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
        agent_registry_skills_location=agent_registry_skills_location,
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
        print(json.dumps({"publish_skill_result": publish_result, "reference_commands": reference_commands}, indent=2))
        return 0

    if args.dry_run:
        print(
            json.dumps(
                {
                    "dry_run": True,
                    "optimizer": args.optimizer,
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

    resolved_optimizer_model = args.optimizer_model or settings.model_name
    opt_result = asyncio.run(
        run_prompt_optimization(
            sampler_config_path=sampler_path,
            agents_dir=TRACK_ROOT,
            optimizer_choice=args.optimizer,
            iterations=args.iterations,
            batch_size=args.batch_size,
            optimizer_model=resolved_optimizer_model,
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
                "saved_candidate_instruction": str(output_path),
                "saved_candidate_skills": saved_skills,
                "overall_score": opt_result["overall_score"],
            },
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
