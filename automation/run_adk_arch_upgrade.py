"""4-to-6 round run-workflow script to integrate ADK Agent Architectures
(Simple Agents, Managed Agents, Service Registration, Multi-Agent Workflows,
and ADK 2.0 Graph & Dynamic Workflows) into the Gemini Enterprise Agent Platform
Coding Agent Workshop while guaranteeing whole-workshop alignment across Labs 0-7,
starter/, solution/, scripts/, and all 6 Antigravity skills.
"""

import ast
import json
import re
import shutil
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

from advanced import parallel as bounded_parallel
from advanced import retry

SCRATCH_DIR = Path(
    args.get(
        "scratch_dir",
        "./.workshop_scratch",
    )
)
OUTPUT_DIR = Path(
    args.get(
        "output_dir",
        ".",
    )
)
ADK_DOCS_DIR = SCRATCH_DIR / "adk_arch_docs"
UPGRADE_LEDGER = SCRATCH_DIR / "adk_arch_upgrade_ledger.json"

NEW_14_ADK_URLS = [
    "https://adk.dev/agents/",
    "https://adk.dev/agents/managed-agents/",
    "https://adk.dev/agents/service-registration/",
    "https://adk.dev/workflows/",
    "https://adk.dev/workflows/collaboration/",
    "https://adk.dev/agents/workflow-agents/",
    "https://adk.dev/agents/routing/",
    "https://adk.dev/workflows/patterns/",
    "https://adk.dev/graphs/",
    "https://adk.dev/graphs/routes/",
    "https://adk.dev/graphs/data-handling/",
    "https://adk.dev/graphs/human-input/",
    "https://adk.dev/graphs/retry/",
    "https://adk.dev/graphs/dynamic/",
]

ORIGINAL_20_SEED_URLS = [
    "https://docs.cloud.google.com/gemini-enterprise-agent-platform/build/skill-registry",
    "https://docs.cloud.google.com/gemini-enterprise-agent-platform/scale/runtime/use-terraform",
    "https://docs.cloud.google.com/gemini-enterprise-agent-platform/scale/runtime/manage-deployed-agents",
    "https://docs.cloud.google.com/gemini-enterprise-agent-platform/scale/runtime/tracing",
    "https://docs.cloud.google.com/gemini-enterprise-agent-platform/scale/runtime/logging",
    "https://docs.cloud.google.com/gemini-enterprise-agent-platform/scale/runtime/monitoring",
    "https://adk.dev/get-started/",
    "https://docs.cloud.google.com/gemini-enterprise-agent-platform/scale/feedback-service",
    "https://docs.cloud.google.com/gemini-enterprise-agent-platform/scale/sessions",
    "https://docs.cloud.google.com/gemini-enterprise-agent-platform/scale/memory-bank",
    "https://docs.cloud.google.com/gemini-enterprise-agent-platform/scale/sandbox",
    "https://docs.cloud.google.com/gemini-enterprise-agent-platform/optimize/observability/overview",
    "https://docs.cloud.google.com/gemini-enterprise-agent-platform/optimize/evaluation/agent-evaluation",
    "https://docs.cloud.google.com/gemini-enterprise-agent-platform/optimize/evaluation/evaluate-online",
    "https://docs.cloud.google.com/gemini-enterprise-agent-platform/optimize/evaluation/evaluate-offline",
    "https://docs.cloud.google.com/gemini-enterprise-agent-platform/optimize/evaluation/evaluate-simulated",
    "https://docs.cloud.google.com/gemini-enterprise-agent-platform/optimize/evaluation/view-results",
    "https://docs.cloud.google.com/gemini-enterprise-agent-platform/optimize/evaluation/quality-alerts",
    "https://docs.cloud.google.com/gemini-enterprise-agent-platform/optimize/evaluation/optimize-agent",
    "https://github.com/google/agents-cli",
]

SAFETY_BOUNDARY = f"""
CRITICAL RULES:
- ONLY create or modify files inside the designated output and scratch directories.
- ONLY edit files inside `{OUTPUT_DIR}` (and scratch logs inside `{SCRATCH_DIR}`).
- ALWAYS ground every ADK class, import, parameter, version, deprecation, and limitation strictly in the verified docs at `{ADK_DOCS_DIR}/`!
- Keep `AGENT_ARCHITECTURE=simple` as the default in `.env.example` and `config.py` so Labs 2-7 stay 100% backward compatible!
- Never leave `__pycache__` behind (set `PYTHONPYCACHEPREFIX=/tmp/pycache_chk` if running `py_compile`).
- ALWAYS call `finish` with the exact JSON schema requested.
""".strip()

WORK_SCHEMA = {
    "type": "object",
    "properties": {
        "track": {"type": "string"},
        "summary": {"type": "string"},
        "files_modified": {"type": "array", "items": {"type": "string"}},
    },
    "required": ["track", "summary", "files_modified"],
}

CRITIQUE_SCHEMA = {
    "type": "object",
    "properties": {
        "round": {"type": "integer"},
        "scores": {
            "type": "object",
            "properties": {
                "doc_coverage": {"type": "integer"},
                "api_code_accuracy": {"type": "integer"},
                "whole_workshop_alignment": {"type": "integer"},
                "skill_production_quality": {"type": "integer"},
            },
            "required": [
                "doc_coverage",
                "api_code_accuracy",
                "whole_workshop_alignment",
                "skill_production_quality",
            ],
        },
        "overall_score": {"type": "integer"},
        "blocking_issues": {"type": "array", "items": {"type": "string"}},
        "improvements": {"type": "array", "items": {"type": "string"}},
    },
    "required": ["round", "scores", "overall_score", "blocking_issues", "improvements"],
}


def run_static_checks():
    errors = []
    warnings = []
    metrics = {}

    # 1. Clean any stray __pycache__
    for d in list(OUTPUT_DIR.rglob("__pycache__")):
        if d.is_dir():
            shutil.rmtree(d)

    # 2. Check all new expected files exist in both starter/ and solution/
    expected_new = [
        "starter/coding_agent/architectures.py",
        "solution/coding_agent/architectures.py",
        "starter/services.yaml",
        "starter/services.py",
        "solution/services.yaml",
        "solution/services.py",
        ".agents/skills/adk-coding-agent-build/references/agent-architectures-and-workflows.md",
        ".agents/skills/adk-coding-agent-build/references/graph-and-dynamic-workflows.md",
    ]
    for rel in expected_new:
        if not (OUTPUT_DIR / rel).exists():
            errors.append(f"Missing required new file: {rel}")

    # 3. Python AST syntax check across ALL .py files
    py_files = []
    for sub in ["starter", "solution", "scripts"]:
        root = OUTPUT_DIR / sub
        if root.exists():
            py_files.extend(sorted(root.rglob("*.py")))
    metrics["python_files"] = len(py_files)
    for pf in py_files:
        try:
            ast.parse(pf.read_text(encoding="utf-8"), filename=str(pf))
        except SyntaxError as e:
            errors.append(f"Python syntax error in {pf.relative_to(OUTPUT_DIR)}: line {e.lineno}: {e.msg}")

    # 4. Starter architectures.py must have TODO(lab-1) markers; solution must have ZERO TODO(lab- markers
    st_arch = OUTPUT_DIR / "starter/coding_agent/architectures.py"
    if st_arch.exists():
        cnt = len(re.findall(r"TODO\(lab-1\)", st_arch.read_text(encoding="utf-8")))
        metrics["starter_arch_todos"] = cnt
        if cnt < 3:
            errors.append(f"starter/coding_agent/architectures.py has only {cnt} TODO(lab-1) markers (expected >=3)")

    for pf in (OUTPUT_DIR / "solution").rglob("*.py"):
        if re.search(r"TODO\(lab-", pf.read_text(encoding="utf-8")):
            errors.append(f"Solution file contains TODO(lab- marker: {pf.relative_to(OUTPUT_DIR)}")

    # 5. Validate skills (all 6/6 must pass)
    p_val = subprocess.run(
        [sys.executable, str(OUTPUT_DIR / "scripts/validate_skills.py"), str(OUTPUT_DIR / ".agents/skills")],
        capture_output=True,
        text=True,
        timeout=60,
    )
    metrics["validate_skills_exit"] = p_val.returncode
    if p_val.returncode != 0:
        errors.append(f"validate_skills.py failed:\n{(p_val.stdout + p_val.stderr).strip()[:1500]}")

    # 6. Validate Skill Registry 16-check ZIP packaging still passes
    p_pkg = subprocess.run(
        [
            sys.executable,
            str(OUTPUT_DIR / "scripts/package_registry_skill.py"),
            str(OUTPUT_DIR / "solution/skills_to_register/secure-code-review"),
            "--dry-run",
        ],
        capture_output=True,
        text=True,
        timeout=60,
    )
    metrics["package_skill_exit"] = p_pkg.returncode
    if p_pkg.returncode != 0:
        errors.append(f"package_registry_skill.py failed:\n{(p_pkg.stdout + p_pkg.stderr).strip()[:1000]}")

    # 7. Run verify_lab.sh syntax check + full solution track verification (Labs 1-6 + Lab 7)
    p_sh = subprocess.run(["bash", "-n", str(OUTPUT_DIR / "scripts/verify_lab.sh")], capture_output=True, text=True)
    if p_sh.returncode != 0:
        errors.append(f"bash -n scripts/verify_lab.sh failed: {p_sh.stderr}")
    else:
        p_vsol = subprocess.run(
            ["bash", str(OUTPUT_DIR / "scripts/verify_lab.sh"), "all", "--track", "solution"],
            capture_output=True,
            text=True,
            timeout=120,
        )
        metrics["verify_lab_solution_all_exit"] = p_vsol.returncode
        if p_vsol.returncode != 0:
            errors.append(
                f"verify_lab.sh all --track solution failed (exit {p_vsol.returncode}):\n"
                + (p_vsol.stdout + p_vsol.stderr)[-1500:]
            )

    # 8. Check 34/34 URL coverage (all 14 new ADK URLs + all 20 original seed URLs) in skills and workshop
    all_skill_text = "\n".join(
        md.read_text(encoding="utf-8") for md in (OUTPUT_DIR / ".agents/skills").rglob("*.md")
    )
    all_ws_text = "\n".join(
        md.read_text(encoding="utf-8") for md in (OUTPUT_DIR / "workshop").rglob("*.md")
    )
    all_34 = ORIGINAL_20_SEED_URLS + NEW_14_ADK_URLS
    miss_sk = [u for u in all_34 if u.rstrip("/") not in all_skill_text]
    miss_ws = [u for u in all_34 if u.rstrip("/") not in all_ws_text]
    metrics["urls_in_skills"] = f"{len(all_34) - len(miss_sk)}/{len(all_34)}"
    metrics["urls_in_workshop"] = f"{len(all_34) - len(miss_ws)}/{len(all_34)}"
    if miss_sk:
        errors.append(f"Missing URLs in .agents/skills/: {miss_sk}")
    if miss_ws:
        errors.append(f"Missing URLs in workshop/: {miss_ws}")

    # 9. Check YAML validity on services.yaml in starter & solution
    try:
        import yaml

        for track in ["starter", "solution"]:
            yp = OUTPUT_DIR / track / "services.yaml"
            if yp.exists():
                yaml.safe_load(yp.read_text(encoding="utf-8"))
    except Exception as e:
        errors.append(f"services.yaml parse error: {e}")

    # 10. Check AGENT_ARCHITECTURE default is 'simple' in .env.example
    env_ex = OUTPUT_DIR / ".env.example"
    if env_ex.exists():
        txt = env_ex.read_text(encoding="utf-8")
        if "AGENT_ARCHITECTURE=simple" not in txt:
            errors.append(".env.example must define AGENT_ARCHITECTURE=simple as default")

    # 11. Check broken relative markdown links in README.md and workshop/*.md
    md_files = [OUTPUT_DIR / "README.md"] + sorted((OUTPUT_DIR / "workshop").glob("*.md"))
    link_re = re.compile(r"\[[^\]]+\]\(([^)#\s]+)(?:#[^)]*)?\)")
    for mf in md_files:
        if not mf.exists():
            continue
        content = mf.read_text(encoding="utf-8")
        # Strip fenced code blocks to avoid false positives
        stripped = re.sub(r"```.*?```", "", content, flags=re.S)
        for target in link_re.findall(stripped):
            if target.startswith(("http://", "https://", "mailto:", "file://")):
                continue
            resolved = (mf.parent / target).resolve()
            if not resolved.exists():
                errors.append(f"Broken relative link in {mf.relative_to(OUTPUT_DIR)}: ({target})")

    return {"passed": len(errors) == 0, "errors": errors, "warnings": warnings, "metrics": metrics}


ledger = {
    "started_at": datetime.now(timezone.utc).isoformat(),
    "output_dir": str(OUTPUT_DIR),
    "rounds": [],
}


def save_ledger():
    UPGRADE_LEDGER.write_text(json.dumps(ledger, indent=2), encoding="utf-8")


# ===========================================================================
# ROUND 1: Parallel 3-Track Implementation (Codebase, Antigravity Skill, Workshop Docs)
# ===========================================================================
phase("Round 1/6: Parallel Upgrade — Starter/Solution Code, Antigravity Skill & Workshop Curriculum")

TRACKS = [
    {
        "name": "Track 1: Codebase (architectures.py, agent.py, config.py, services.yaml/py, pyproject, verify_lab.sh)",
        "prompt": f"""
You are a Staff Python & Google ADK 2.0 Engineer executing **Round 1 — Track 1 (Codebase Upgrade)**.

First read the verified ADK docs in `{ADK_DOCS_DIR}/`:
- `agents.md`, `agents_managed-agents.md`, `agents_service-registration.md`
- `workflows.md`, `workflows_collaboration.md`, `agents_workflow-agents.md`, `agents_routing.md`, `workflows_patterns.md`
- `graphs.md`, `graphs_routes.md`, `graphs_data-handling.md`, `graphs_human-input.md`, `graphs_retry.md`, `graphs_dynamic.md`, `2.0.md`

Also read the existing files in `{OUTPUT_DIR}` so you preserve 100% compatibility with Labs 2-7:
- `.env.example`
- `starter/coding_agent/config.py` and `solution/coding_agent/config.py`
- `starter/coding_agent/agent.py` and `solution/coding_agent/agent.py`
- `starter/pyproject.toml`, `solution/pyproject.toml`, `starter/requirements.txt`, `solution/requirements.txt`
- `scripts/verify_lab.sh` (especially the Lab 1 verification section!)

Implement these exact upgrades cleanly across BOTH `starter/` and `solution/`:
1. **`.env.example` & `{OUTPUT_DIR}/{{starter,solution}}/coding_agent/config.py`**:
   - Add `AGENT_ARCHITECTURE=simple` (valid values: `simple`, `collaborative`, `graph`, `dynamic`; default `simple` so Labs 2-7 work unchanged!).
   - Add `MAX_FIX_ROUNDS=3` and `ENABLE_HITL_APPROVAL=false` (plus optional `MANAGED_AGENT_ID=antigravity-preview-05-2026` commented).
   - Expose typed fields (`agent_architecture`, `max_fix_rounds`, `enable_hitl_approval`) on `Settings` with validation.
2. **`{OUTPUT_DIR}/starter/coding_agent/architectures.py` (with clear `# TODO(lab-1)` checkpoints!) AND `{OUTPUT_DIR}/solution/coding_agent/architectures.py` (complete, ZERO `TODO(lab-` markers!)**:
   - Include a clear ADK 2.0 import guard helper (`_require_adk_v2()`) so `AGENT_ARCHITECTURE=simple` still works even on ADK `1.29.x`, while `collaborative`/`graph`/`dynamic` raise an informative upgrade hint if ADK `< 2.0.0`.
   - **`build_collaborative_coding_team(settings, tools, callbacks, code_executor)`**:
     - Builds a Coordinator `LlmAgent(name="coding_agent", ...)` delegating to specialized subagents with explicit ADK 2.0 `mode` (ONLY on subagents, NEVER on root!):
       - `code_implementer` (`mode="single_turn"` — receives the `EnvironmentToolset` + coding tools, returns automatically)
       - `code_reviewer` (`mode="single_turn"` — reviews code/tests in isolated session branch, parallel-capable)
       - `requirements_clarifier` (`mode="task"` — leaf agent only, asks clarifying questions & returns via `finish_task`; clearly document that `task` mode must be a leaf agent and is disabled inside Python v2.0.0 graph workflows!)
     - Provide `build_global_instruction_plugin()` returning `GlobalInstructionPlugin` (gracefully optional if import differs) for shared enterprise coding guardrails across all subagents.
   - **`build_graph_coding_workflow(settings, tools, callbacks, code_executor)`**:
     - Builds a declarative ADK 2.0 `Workflow(name="coding_agent", edges=[...])` combining:
       - `coder_agent` (`LlmAgent`, default `single_turn` in graph)
       - Parallel deterministic check nodes (`run_pytest_node`, `run_ruff_node`) decorated with `@node(retry_config=RetryConfig(max_attempts=3, initial_delay=1.0, exceptions=[TimeoutError, NodeTimeoutError]), timeout=30.0)`
       - `JoinNode(name="verify_join")` merging both parallel branches into a single dict keyed by predecessor node name (respecting single terminal output rule!)
       - `verdict_router` emitting `Event(route="PASS" | "NEEDS_FIX" | "NEEDS_APPROVAL", output=..., state={{"fix_attempts": ...}})` with explicit `max_fix_rounds` bound (because graph cycles are NOT bounded automatically!)
       - Optional `request_human_approval` node (`@node(rerun_on_resume=False)`) yielding `RequestInput(message=..., payload=..., response_schema=ApprovalDecision)` (Pydantic `BaseModel`)
       - `finalize_report` node emitting final `Event(message=..., output=...)` (strictly ONE `Event(output=...)` per node!)
   - **`build_dynamic_coding_workflow(settings, tools, callbacks, code_executor)`**:
     - Mirrors `adk.dev/graphs/dynamic/#loop-route`:
       - `@node(rerun_on_resume=True)` orchestrator `dynamic_coding_workflow(ctx: Context, node_input: str)`
       - Calls `await ctx.run_node(coder_agent, node_input)`
       - Runs a bounded `for attempt in range(max_fix_rounds):` loop executing parallel checks via `await asyncio.gather(ctx.run_node(run_pytest_node, ..., use_sub_branch=True), ctx.run_node(run_ruff_node, ..., use_sub_branch=True))`
       - Calls `await ctx.run_node(fixer_agent, ...)` when findings exist (writing `{{"code": ..., "findings": ...}}` to state via `Event(state=...)` because Python `{{key}}` templates read session state, not `node_input`!)
       - If `enable_hitl_approval` is true, awaits `await ctx.run_node(request_human_approval, ...)` (`rerun_on_resume=False`) leveraging automatic checkpointing!
       - Wraps in `Workflow(name="coding_agent", edges=[("START", dynamic_coding_workflow)])`.
   - **`build_optional_managed_agent(agent_id)`**:
     - Clean reference builder for `ManagedAgent(name="managed_research_agent", mode="single_turn", agent_id=..., environment={{"type": "remote"}}, tools=[google_search])` (ADK Python v2.4.0 Preview; clearly document `global`-only Agent Platform backend & server-side tools only!).
3. **`{OUTPUT_DIR}/{{starter,solution}}/coding_agent/agent.py`**:
   - Keep `build_coding_agent()` returning the single `LlmAgent` for `AGENT_ARCHITECTURE=simple` (100% preserving existing Lab 1-6 hooks, `build_local_environment_toolset`, `_build_remote_execution_components`, `_build_optional_skill_toolset`, `_build_optional_callbacks`!).
   - Add `build_root_agent(settings=None)` dispatching on `cfg.agent_architecture` (`simple` | `collaborative` | `graph` | `dynamic`) while preserving `root_agent = build_root_agent()` and `app = App(root_agent=root_agent, name="coding_agent", resumability_config=ResumabilityConfig(is_resumable=True))` (with optional `plugins=[GlobalInstructionPlugin(...)]` when collaborative).
   - Remember: Keep all existing `# TODO(lab-1)`, `# TODO(lab-2)`, `# TODO(lab-4)`, `# TODO(lab-5)` markers intact in `starter/coding_agent/agent.py`, and ZERO `TODO(lab-` markers in `solution/`!
4. **`{OUTPUT_DIR}/{{starter,solution}}/services.yaml` and `services.py`**:
   - ADK Python v1.34.0 Service Registration examples showing both declarative `services.yaml` (`scheme`, `type: session|artifact|memory|task_store`, `class`) and programmatic `services.py` (`get_service_registry().register_session_service(...)` with `services.py` overriding `services.yaml` on collision).
   - Keep the actual custom scheme entries commented out or guarded (`if os.environ.get("ENABLE_CUSTOM_SERVICE_REGISTRY") == "true":`) so `adk web` / `adk run` work out-of-the-box without requiring a non-existent third-party package!
5. **`{OUTPUT_DIR}/{{starter,solution}}/pyproject.toml` and `requirements.txt`**:
   - Update `google-adk[a2a,agent-identity,mcp]>=2.0.0` (with clear comment noting `~=1.29` works for `AGENT_ARCHITECTURE=simple`).
6. **`{OUTPUT_DIR}/scripts/verify_lab.sh`**:
   - Extend `verify_lab_1()` cleanly to compile & verify `coding_agent/architectures.py`, check `AGENT_ARCHITECTURE` in `config.py` / `agent.py`, check `services.yaml` / `services.py` presence, and verify `TODO(lab-1)` completion when running `--track solution` (while keeping `verify_lab.sh all --track solution` passing 100%!).

Verify with `PYTHONPYCACHEPREFIX=/tmp/pycache_chk python3 -m py_compile` on all touched `.py` files and `bash -n {OUTPUT_DIR}/scripts/verify_lab.sh`.

{SAFETY_BOUNDARY}
""",
    },
    {
        "name": "Track 2: Production Antigravity Skill (adk-coding-agent-build)",
        "prompt": f"""
You are a Staff Antigravity Skill Architect executing **Round 1 — Track 2 (Production Modular Skill Upgrade)**.

Read ALL 14 verified ADK Architecture docs + `2.0.md` in `{ADK_DOCS_DIR}/`, AND read existing files in `{OUTPUT_DIR}/.agents/skills/adk-coding-agent-build/`:
- `SKILL.md`
- `references/adk-core-and-setup.md`
- `references/maintenance.md`

Upgrade `{OUTPUT_DIR}/.agents/skills/adk-coding-agent-build/` with **two new separate, easy-to-maintain modular reference files** and updated `SKILL.md` + `references/maintenance.md`:

1. **`[NEW]` `{OUTPUT_DIR}/.agents/skills/adk-coding-agent-build/references/agent-architectures-and-workflows.md`**:
   - Covers all 8 Simple Agents & Multi-Agent Workflows docs thoroughly (exact code, versions, limitations, do-this-not-that):
     - `https://adk.dev/agents/` (single `LlmAgent`, 4 triggers to evolve into a workflow, feature extensions)
     - `https://adk.dev/agents/managed-agents/` (`ManagedAgent` Python v2.4.0 Preview, Gemini API vs Agent Platform backends, `global`-only limit, server-side tools + `RemoteMcpServer` only, `mode='single_turn'` inline subagent composition, remote state vs local `interaction_id`/`environment_id`, streaming-only limit)
     - `https://adk.dev/agents/service-registration/` (ADK Python v1.34.0 `services.yaml` vs `services.py`, discovery paths for `adk run` vs `adk web`/`adk api_server`, loading order & `services.py` precedence)
     - `https://adk.dev/workflows/` & `https://adk.dev/workflows/collaboration/` (ADK v2.0.0 collaborative teams, auto-injected delegation tools, `chat` vs `task` vs `single_turn` matrix, `GlobalInstructionPlugin`, isolated session branches, `task` must be leaf & disabled in Python v2.0.0 graph workflows, never set `mode` on root agent!)
     - `https://adk.dev/agents/workflow-agents/` (official deprecation of `SequentialAgent`, `ParallelAgent`, `LoopAgent` in Python & TypeScript 2.0, migration to Graph/Dynamic workflows, note that `Workflow` cannot yet be a `sub_agent` of `LlmAgent`)
     - `https://adk.dev/agents/routing/` (`RoutedAgent` TypeScript v1.0.0 Experimental ONLY: pre-event failover with `errorContext.failedKeys`, planning mode toggle, async classifier complexity routing — plus exact Python equivalents using Graph `Event(route=...)` or Dynamic `if`/`elif`)
     - `https://adk.dev/workflows/patterns/` (all 7 patterns: Coordinator/Dispatcher, Sequential Pipeline, Parallel Fan-Out & Gather, Hierarchical Task Decomposition with `AgentTool`, Generate & Review, Iterative Refinement, Human-in-the-Loop including TS `SecurityPlugin`/`BasePolicyEngine` — mapped cleanly to ADK 2.0 primitives!)
   - Strict 1-hop rule: Do NOT add relative links to other `references/*.md` files inside this reference file!

2. **`[NEW]` `{OUTPUT_DIR}/.agents/skills/adk-coding-agent-build/references/graph-and-dynamic-workflows.md`**:
   - Covers all 6 ADK 2.0 Graph & Dynamic Workflow docs thoroughly (exact Python APIs + key TS/Go/Kotlin contrasts + verified caveats):
     - `https://adk.dev/graphs/` (`Workflow(name=..., edges=[...])`, node types, `LlmAgent` defaults to `single_turn` in graphs, `chat` only after `"START"`, third-party integration caveat)
     - `https://adk.dev/graphs/routes/` (sequences, conditional `Event(route=...)` / multi-route list, `DEFAULT_ROUTE`, parallel fan-out + `JoinNode` where every predecessor MUST output, nested `Workflow` data bubbling & **single terminal output `ValueError` rule**, conditional back-edge loops requiring >=1 routed edge + **unbounded cycle warning**)
     - `https://adk.dev/graphs/data-handling/` (`Event(output=..., message=..., route=..., state=...)`, **strictly ONE `Event(output=...)` per node execution in Python**, state prefixes `app:`/`user:`/`temp:`/session, lightweight state rule vs Artifacts, Pydantic `input_schema`/`output_schema`, **Python `{{key}}` reads session state NOT `node_input`** vs TS `{{Class.field}}`/`<Class.field from node>`)
     - `https://adk.dev/graphs/human-input/` (`RequestInput(message, payload, response_schema)` — does NOT reformat user reply; `rerun_on_resume=False` leaf handoff vs `True` re-entry; vs LLM-level `FunctionTool(require_confirmation=True)` & `tool_context.request_confirmation()` checking both `tool_confirmation` and `tool_confirmation.confirmed`)
     - `https://adk.dev/graphs/retry/` (`@node(retry_config=RetryConfig(max_attempts=5, initial_delay=1.0, max_delay=60.0, backoff_factor=2.0, jitter=1.0, exceptions=[...]), timeout=...)`, per-attempt timeout, `NodeTimeoutError`, `ctx.attempt_count` NOT saved across pauses/restarts, idempotency & side-effect placement, never swallow `BaseException`)
     - `https://adk.dev/graphs/dynamic/` (`@node(rerun_on_resume=True)`, `FunctionNode`, `await ctx.run_node(...)`, bounded `for`/`while` coding agent loop pattern, `asyncio.gather(*[ctx.run_node(..., use_sub_branch=True)])`, automatic checkpointing on resume, custom `run_id` non-numeric char warning!)
   - Strict 1-hop rule: Do NOT add relative links to other `references/*.md` files!

3. **`[MODIFY]` `{OUTPUT_DIR}/.agents/skills/adk-coding-agent-build/SKILL.md`**:
   - Update YAML `description: >-` (MUST stay strictly `< 1024` characters!) to add trigger keywords for: `ManagedAgent`, `services.yaml`/`services.py`, collaborative `mode` (`chat`/`task`/`single_turn`), `GlobalInstructionPlugin`, deprecated template workflows, `RoutedAgent`, `Workflow`/`JoinNode`/`Event(route/output)`, `RequestInput`, `RetryConfig`/`NodeTimeoutError`, and dynamic `ctx.run_node`/`rerun_on_resume`. Preserve all existing `Don't use for:` anti-shadowing clauses!
   - Enhance the Quick Decision Tree & Gotchas table with the top ADK 2.0 architecture selection & pitfalls, and add both new reference files to the **Modular References** table.
   - Keep `SKILL.md` strictly `< 350` lines (well below 500-line ceiling!).

4. **`[MODIFY]` `{OUTPUT_DIR}/.agents/skills/adk-coding-agent-build/references/maintenance.md`**:
   - Add ALL 14 new canonical `https://adk.dev/...` URLs and their `index.md` refresh URLs, plus maintenance rows for the 2 new reference files.

Run `python3 {OUTPUT_DIR}/scripts/validate_skills.py {OUTPUT_DIR}/.agents/skills` via `run_command` to verify 6/6 PASS!

{SAFETY_BOUNDARY}
""",
    },
    {
        "name": "Track 3: Workshop Curriculum & Whole-Workshop Alignment (Labs 0, 1, 3, 4, Facilitator, README, Automation)",
        "prompt": f"""
You are a Principal Cloud Solutions Architect & Technical Curriculum Editor executing **Round 1 — Track 3 (Workshop Curriculum & Whole-Workshop Alignment)**.

First read the verified ADK docs in `{ADK_DOCS_DIR}/` AND read our existing workshop docs so every cross-reference, file path, env var, timing, and narrative flows seamlessly across the ENTIRE workshop:
- `{OUTPUT_DIR}/README.md`
- `{OUTPUT_DIR}/workshop/00-WORKSHOP-OVERVIEW.md`
- `{OUTPUT_DIR}/workshop/01-LAB-SETUP-AND-BUILD-ADK.md`
- `{OUTPUT_DIR}/workshop/03-LAB-DEPLOY-RUNTIME-TERRAFORM.md` (scan for env var / deployment alignment)
- `{OUTPUT_DIR}/workshop/04-LAB-SESSIONS-MEMORY-FEEDBACK.md` (scan for Sessions/Memory integration)
- `{OUTPUT_DIR}/workshop/FACILITATOR-GUIDE.md`
- `{OUTPUT_DIR}/automation/harvest_corpus.py`

Apply these coordinated, aligned updates:
1. **`{OUTPUT_DIR}/workshop/01-LAB-SETUP-AND-BUILD-ADK.md`** (Major Upgrade — Keep Lab 1 numbering, split cleanly into **Part A** and **Part B**):
   - Update header metadata: Duration `60 minutes (Full-Day Track) | 35 minutes (Half-Day Fast-Track — Part A hands-on, Part B walkthrough)`, Files You Will Inspect & Edit to include `starter/coding_agent/architectures.py`, `starter/services.yaml`, `starter/services.py`.
   - **Part A — Setup, Antigravity Skills & Simple Agent (30 min)**:
     - Keep Steps 1–3 (`agents-cli`, `.agents/skills/`, `.env` with `AGENT_ARCHITECTURE=simple`, `MAX_FIX_ROUNDS=3`, `ENABLE_HITL_APPROVAL=false`, and updated Starter Layout table listing `architectures.py` and `services.yaml`/`services.py`).
     - Add **Step 4: ADK Agent Architecture Spectrum & Design Decisions** BEFORE writing code! Include:
       - Mermaid architecture progression diagram (**Simple Agent → Collaborative Team → Declarative Graph Workflow → Dynamic Workflow**)
       - **Simple Agents**: Single `LlmAgent` + 4 official triggers to evolve to workflows; **`ManagedAgent`** (ADK Python v2.4.0 Preview, `global`-only, server-side tools only, inline `mode="single_turn"`) comparison table explaining why our enterprise Coding Agent builds on `LlmAgent`/Workflows for custom BYOC sandboxes; and **Service Registration** (`services.yaml` / `services.py`, v1.34.0) previewing how custom backends plug into `adk run`/`adk web`/`adk api_server`.
       - **Multi-Agent Workflows**: Collaborative Agent Teams (`chat` / `task` / `single_turn` mode table + `GlobalInstructionPlugin` + leaf/`task`-in-graph restrictions); **Deprecation callout** for `SequentialAgent`/`ParallelAgent`/`LoopAgent` in Python & TypeScript 2.0 (and note that `Workflow` cannot yet be a `sub_agent` of `LlmAgent`); **`RoutedAgent`** (TypeScript v1.0.0 Experimental only — failover/planning/complexity routing vs. Python Graph/Dynamic routing); and concise table mapping all **7 Multi-Agent Patterns** to ADK 2.0 primitives.
       - **ADK 2.0 Graph-Based & Dynamic Workflows**: Declarative `Workflow(edges=...)` (`JoinNode`, single terminal output rule, conditional `Event(route=...)`, unbounded cycle caution) vs. Dynamic `@node(rerun_on_resume=True)` + `ctx.run_node(...)` (automatic checkpointing, `use_sub_branch=True`, bounded coding loop, custom `run_id` rule); Data Handling (`Event(output/message/route/state)`, single `Event.output` rule, Python `{{key}}` state-vs-`node_input` trap, Pydantic schemas); HITL (`RequestInput` + `rerun_on_resume` vs. `FunctionTool(require_confirmation=True)`); and Retries/Timeouts (`@node(retry_config=RetryConfig(...), timeout=...)`, `NodeTimeoutError`, `ctx.attempt_count` not saved across pauses).
     - Keep `EnvironmentToolset` vs `ExecuteBashTool` + `TODO(lab-1)` in `starter/coding_agent/agent.py` (`AGENT_ARCHITECTURE=simple`).
   - **Part B — Evolving Your Coding Agent Across Multi-Agent, Graph & Dynamic Architectures (30 min Full-Day | 5 min Walkthrough Half-Day)**:
     - Walk through implementing `# TODO(lab-1)` in `starter/coding_agent/architectures.py` for:
       1. `AGENT_ARCHITECTURE=collaborative` (`coding_lead` + `code_implementer`/`code_reviewer` `single_turn` + `requirements_clarifier` `task`)
       2. `AGENT_ARCHITECTURE=graph` (parallel `pytest` + `ruff` `@node` with `RetryConfig`/timeout → `JoinNode` → `verdict_router` → bounded fix loop / `RequestInput` HITL)
       3. `AGENT_ARCHITECTURE=dynamic` (`@node(rerun_on_resume=True)` bounded edit-test-fix loop + `asyncio.gather(..., use_sub_branch=True)` + checkpointed HITL)
     - Inspect `starter/services.yaml` and `starter/services.py` (showing `services.py` precedence over `services.yaml` for custom session/memory/artifact/A2A stores).
     - Remind attendees to switch `.env` back to `AGENT_ARCHITECTURE=simple` (or keep their chosen mode!) before Lab 2, noting how `EnvironmentToolset` swaps cleanly from `LocalEnvironment` to `AgentPlatformSandboxEnvironment` across ALL four architectures!
   - Cite **ALL 14 newly provided ADK URLs** cleanly in Canonical References!
2. **`{OUTPUT_DIR}/workshop/00-WORKSHOP-OVERVIEW.md`**:
   - Add a crisp **ADK Agent Architecture Progression (Build Pillar)** callout/subsection explaining why Lab 1 covers Simple → Collaborative → Graph → Dynamic architectures before scaling to BYOC Sandboxes in Lab 2.
   - Update the schedule table cleanly so Lab 1 reflects 60 min Full-Day / 35 min Half-Day (rebalance buffer/break minutes so totals stay accurate and realistic!).
3. **`{OUTPUT_DIR}/workshop/03-LAB-DEPLOY-RUNTIME-TERRAFORM.md`**:
   - Add a concise callout noting that `AGENT_ARCHITECTURE` (`simple` default, or `collaborative`/`graph`/`dynamic`), `MAX_FIX_ROUNDS`, and `ENABLE_HITL_APPROVAL` can be passed via `env_variables` in Terraform / `agents-cli deploy` without changing the container contract!
4. **`{OUTPUT_DIR}/workshop/04-LAB-SESSIONS-MEMORY-FEEDBACK.md`**:
   - Add a concise callout linking Managed Sessions (`VertexAiSessionService`) & Memory Bank (`VertexAiMemoryBankService`) back to Lab 1's ADK v1.34.0 Service Registration (`services.yaml` / `services.py`) for teams combining Agent Platform services with custom enterprise stores.
5. **`{OUTPUT_DIR}/workshop/FACILITATOR-GUIDE.md`** & **`{OUTPUT_DIR}/README.md`**:
   - Update repository file tree (`coding_agent/architectures.py`, `services.yaml`, `services.py`, plus the 2 new `adk-coding-agent-build/references/*.md` files), Lab 1 timing/checkpoint cutoffs, and add 5 concise ADK 2.0 Agent Architecture troubleshooting entries to the Top Troubleshooting Table!
6. **`{OUTPUT_DIR}/automation/harvest_corpus.py`**:
   - Add all 14 new `https://adk.dev/...` URLs into `USER_SEED_URLS` so future refreshes include all 34 seed URLs!

{SAFETY_BOUNDARY}
""",
    },
]


def make_track_agent(t):
    return retry(
        lambda: agent(t["prompt"], schema=WORK_SCHEMA, role=t["name"][:44]),
        attempts=2,
    )


r1_results = await bounded_parallel(TRACKS, make_track_agent, max_concurrency=3)
ledger["rounds"].append({"round": 1, "tracks": r1_results})
save_ledger()

# ===========================================================================
# ROUNDS 2..6: Adversarial Whole-Workshop Alignment Critique & Convergence Loop
# ===========================================================================
final_static = None
final_critique = None

for rn in range(2, 7):
    phase(f"Round {rn}/6: Whole-Workshop Alignment Verification & Adversarial Audit")
    static_res = run_static_checks()
    final_static = static_res
    log(
        f"Round {rn} static checks: passed={static_res['passed']} errors={len(static_res['errors'])} "
        f"metrics={json.dumps(static_res['metrics'])}"
    )

    critique = await retry(
        lambda rnum=rn, sr=static_res: agent(
            f"""
You are a Principal Google ADK & Enterprise Workshop Auditor executing **Alignment Audit Round {rnum}/6** across `{OUTPUT_DIR}`.

Automated verification report:
{json.dumps(sr, indent=2)}

Perform a deep, ruthless audit inspecting:
1. **14-Document Fidelity (`{ADK_DOCS_DIR}/`)**: Cross-check `workshop/01-LAB-SETUP-AND-BUILD-ADK.md`, `starter/coding_agent/architectures.py`, `solution/coding_agent/architectures.py`, `starter/services.yaml`, `starter/services.py`, `.agents/skills/adk-coding-agent-build/SKILL.md`, and both new modular references (`agent-architectures-and-workflows.md`, `graph-and-dynamic-workflows.md`) against the raw ADK docs:
   - Are ALL 14 URLs accurately represented (no hallucinated classes/args, `RoutedAgent` accurately flagged TypeScript-only, `SequentialAgent`/`ParallelAgent`/`LoopAgent` accurately flagged deprecated in Python & TS 2.0, `task` mode leaf-only & disabled in Python v2.0.0 graph workflows, `ManagedAgent` v2.4.0 Preview & `global`-only & server-side tools only, `Workflow` not yet usable as `LlmAgent` sub-agent, single `Event(output=...)` limit, Python `{{key}}` state-vs-`node_input`, `JoinNode` single terminal output, `rerun_on_resume=True` on dynamic orchestrators, `ctx.attempt_count` not persisted across pauses)?
2. **Whole-Workshop Alignment (Labs 0–7 + `README.md` + `Makefile` + `.env.example` + `scripts/verify_lab.sh` + All 6 Skills)**:
   - Do schedule timings in `00-WORKSHOP-OVERVIEW.md`, `01-LAB-SETUP-AND-BUILD-ADK.md`, `FACILITATOR-GUIDE.md`, and `README.md` match identically (no math mismatches)?
   - Do env vars (`AGENT_ARCHITECTURE`, `MAX_FIX_ROUNDS`, `ENABLE_HITL_APPROVAL`) match across `.env.example`, `config.py`, `agent.py`, `architectures.py`, Lab 1, Lab 3, and `verify_lab.sh`?
   - Does `solution/coding_agent/agent.py` & `architectures.py` still interoperate cleanly with Labs 2–6 (`EnvironmentToolset` swapping `LocalEnvironment` -> `AgentPlatformSandboxEnvironment`, `SkillToolset`, callbacks, `main.py`, `eval/` scripts)?
   - Does `.agents/skills/adk-coding-agent-build/` maintain strict modularity (1-level-deep refs, `<400` lines `SKILL.md`, `<1024`-char `description` with zero Frontmatter Blindness & zero Co-Trigger Shadowing vs `google-agents-cli-*` and sibling skills)?

Any static error MUST be in `blocking_issues` and cap the affected score at `<= 88`.
Only award `>= 96` on all 4 scores when there are ZERO blocking issues and the whole workshop is seamlessly aligned.
Do NOT edit files in this critic turn.

{SAFETY_BOUNDARY}
""",
            schema=CRITIQUE_SCHEMA,
            role=f"Round {rnum}: Alignment Critic",
        ),
        attempts=2,
    )
    final_critique = critique
    scores = critique["scores"]
    min_score = min(scores.values())
    log(
        f"Round {rn} scores={scores} overall={critique['overall_score']} blocking={len(critique['blocking_issues'])}"
    )

    converged = (
        static_res["passed"]
        and min_score >= 96
        and critique["overall_score"] >= 96
        and len(critique["blocking_issues"]) == 0
    )

    if converged or rn == 6:
        ledger["rounds"].append(
            {"round": rn, "static_checks": static_res, "critique": critique, "converged": converged}
        )
        save_ledger()
        if converged:
            log(f"CONVERGED at Round {rn} with overall_score={critique['overall_score']}!")
            break
        if critique["blocking_issues"] or not static_res["passed"]:
            phase("Round 6b: Final Remediation")
            fix_last = await retry(
                lambda c=critique, sr=static_res: agent(
                    f"""
Apply surgical fixes for all remaining static errors and blocking issues in `{OUTPUT_DIR}`:
STATIC ERRORS: {json.dumps(sr['errors'], indent=2)}
BLOCKING ISSUES: {json.dumps(c['blocking_issues'], indent=2)}
{SAFETY_BOUNDARY}
""",
                    schema=WORK_SCHEMA,
                    role="Round 6b: Final Remediation",
                ),
                attempts=2,
            )
            final_static = run_static_checks()
            ledger["rounds"].append({"round": "6b", "fix": fix_last, "static_checks": final_static})
            save_ledger()
        break

    # Apply targeted refinement pass
    fix = await retry(
        lambda rnum=rn, c=critique, sr=static_res: agent(
            f"""
You are the Principal Workshop & Code Refinement Engineer executing **Round {rnum} Targeted Fix Pass** in `{OUTPUT_DIR}`.
Fix EVERY static error, blocking issue, and top alignment improvement reported below so the next audit scores >=96/100 across all 4 dimensions:

STATIC REPORT:
{json.dumps({"errors": sr["errors"], "warnings": sr["warnings"], "metrics": sr["metrics"]}, indent=2)}

CRITIQUE REPORT:
{json.dumps(c, indent=2)}

Verify fixes using `python3 {OUTPUT_DIR}/scripts/validate_skills.py {OUTPUT_DIR}/.agents/skills`, `bash {OUTPUT_DIR}/scripts/verify_lab.sh all --track solution`, and `PYTHONPYCACHEPREFIX=/tmp/pycache_chk python3 -m py_compile` on touched `.py` files.

{SAFETY_BOUNDARY}
""",
            schema=WORK_SCHEMA,
            role=f"Round {rnum}: Alignment Fix Pass",
        ),
        attempts=2,
    )
    ledger["rounds"].append(
        {"round": rn, "static_checks": static_res, "critique": critique, "fix": fix, "converged": False}
    )
    save_ledger()

# Export updated ledger & clean any __pycache__
for d in list(OUTPUT_DIR.rglob("__pycache__")):
    if d.is_dir():
        shutil.rmtree(d)

ledger["finished_at"] = datetime.now(timezone.utc).isoformat()
ledger["final_static_checks"] = final_static
ledger["final_critique"] = final_critique
save_ledger()
shutil.copy2(UPGRADE_LEDGER, OUTPUT_DIR / "automation/adk_arch_upgrade_ledger.json")
shutil.copy2(SCRATCH_DIR / "run_adk_arch_upgrade.py", OUTPUT_DIR / "automation/run_adk_arch_upgrade.py")

print(
    json.dumps(
        {
            "output_dir": str(OUTPUT_DIR),
            "rounds_completed": len(ledger["rounds"]),
            "final_static_checks": final_static,
            "final_scores": final_critique["scores"] if final_critique else None,
            "final_overall_score": final_critique["overall_score"] if final_critique else None,
        },
        indent=2,
    )
)
