# Lab 1: Setup and Build the ADK Coding Agent

In this lab, you'll configure your workspace for Gemini 4, wire a local coding agent with Google ADK 2.0 and `EnvironmentToolset`, and verify it live in `adk web`. If you have extra time, the optional stretch steps walk through multi-agent teams, declarative graphs, dynamic workflows, and the Antigravity (`agy`) headless CLI harness.

**Duration:** 30 min Core (Part A, Steps 1-5) + 30 min Optional Stretch (Part B, Steps 6-8) | **Previous:** [Workshop Overview](./00-WORKSHOP-OVERVIEW.md) | **Next:** [Lab 2: Custom Sandbox (BYOC)](./02-LAB-CUSTOM-SANDBOX-BYOC.md)

## Files You Will Edit

| Step | File | Where to edit | What you're adding |
|---|---|---|---|
| Step 1 | `.env` (copy from [`.env.example`](../.env.example)) | Project ID & number | Set `GOOGLE_CLOUD_PROJECT` and `GOOGLE_CLOUD_PROJECT_NUMBER` |
| Step 2 | [`starter/coding_agent/models.py`](../starter/coding_agent/models.py) | `build_gemini_model()` (`# TODO(lab-1)`) | Gemini 4 `client_kwargs` routing to `MODEL_LOCATION=global` |
| Step 3 | [`starter/coding_agent/agent.py`](../starter/coding_agent/agent.py) | `build_local_environment_toolset()`, `_assemble_runtime_components()` (`# TODO(lab-1)`) | Confined `LocalEnvironment(working_dir=Path(...))` wrapped in `EnvironmentToolset` |
| Step 6 (Part B, Stretch) | [`starter/coding_agent/tools/agy_headless_harness.py`](../starter/coding_agent/tools/agy_headless_harness.py) | `build_agy_command()`, `parse_agy_stream_json()` (`# TODO(lab-1)`) | `agy` CLI flags, `agy 1.5.15` nested NDJSON parsing, and 4-tier exit codes |
| Step 7 (Part B, Stretch) | [`starter/coding_agent/architectures.py`](../starter/coding_agent/architectures.py) | `build_collaborative_coding_team()`, `build_graph_coding_workflow()`, `build_dynamic_coding_workflow()`, `build_agy_harness_workflow()` (`# TODO(lab-1)`) | Collaborative team, declarative graph, dynamic loop, and `agy` harness workflows |

**Already built for you (no edits needed):** [`starter/coding_agent/config.py`](../starter/coding_agent/config.py), [`starter/agents-cli-manifest.yaml`](../starter/agents-cli-manifest.yaml), [`starter/services.yaml`](../starter/services.yaml), [`starter/services.py`](../starter/services.py), plus validation and formatting helpers inside `models.py`, `agy_headless_harness.py`, and `architectures.py`.

**Need help or running behind?** Point Antigravity at [`.agents/skills/adk-coding-agent-build`](../.agents/skills/adk-coding-agent-build/SKILL.md), or run `make fast-forward LAB=1` to sync only Lab 1 without touching Labs 2-8.

---

## Step 1: Configure `.env`, Install Dependencies, and Validate Skills

Run these from the repo root. You do not need local Docker or `python3-venv`; standalone `uv` manages Python 3.11+ environments directly.

1. Copy `.env.example` to `.env` (never commit `.env`) and fill in `GOOGLE_CLOUD_PROJECT` and `GOOGLE_CLOUD_PROJECT_NUMBER`:
   ```bash
   cp .env.example .env
   ```
   Keep the regional defaults: Gemini 4 frontier models (`gemini-4-hydrogen` and `gemini-4-neon`) use `MODEL_LOCATION=global`, while Agent Platform runtime/sandboxes default to `asia-southeast1` and Artifact Registry/Cloud Build default to `asia-southeast3`. (For strict Singapore inference residency, switch to `MODEL_NAME=gemini-4-argon` with `MODEL_LOCATION=asia-southeast1`.)

2. Install standalone `uv` if missing, run pre-flight, sync dependencies, and validate the 6 bundled Antigravity skills:
   ```bash
   command -v uv >/dev/null 2>&1 || (curl -LsSf https://astral.sh/uv/install.sh -o /tmp/uv_install.sh && sh /tmp/uv_install.sh && rm -f /tmp/uv_install.sh)
   make preflight && make install && make validate-skills
   ```
   Installing `google/agents-cli` (`uvx google-agents-cli setup`) is optional; every lab works directly with `uv`, `gcloud`, and Terraform.

**Check it works:** `make validate-skills` prints `PASS` for all 6 directories under `.agents/skills/`.

---

## Step 2: Wire the Gemini 4 Model Factory

**File:** [`starter/coding_agent/models.py`](../starter/coding_agent/models.py), function `build_gemini_model()` (`# TODO(lab-1)`)

Your coding agent uses `gemini-4-hydrogen` for fast coding/tool calls and `gemini-4-neon` for deeper planning and review. Both run on `MODEL_LOCATION=global`, so you'll pass `client_kwargs` to ADK 2.0's `Gemini(...)` class to route model traffic to `global` while keeping `GOOGLE_CLOUD_LOCATION=asia-southeast1` for Agent Platform state and sandboxes.

What goes inside `build_gemini_model()`:
- Import `Gemini` from `google.adk.models` and `types` from `google.genai`.
- Resolve the model with pre-filled `resolve_model_name(cfg, role=role, model_override=model_override)` and check the region with `validate_model_location(resolved_model, cfg.model_location)`.
- When `cfg.google_genai_use_enterprise` is true, build `client_kwargs` using pre-filled `_detect_enterprise_client_kwarg()` (`"enterprise"` on `google-genai>=2.34.0` or `"vertexai"` on older builds), `"location": cfg.model_location`, and `"project": cfg.google_cloud_project` if set.
- Return `Gemini(model=resolved_model, client_kwargs=client_kwargs, retry_options=types.HttpRetryOptions(initial_delay=initial_retry_delay, attempts=retry_attempts))`.

> [!WARNING]
> **Two Gemini 4 / ADK 2.0 quirks that break calls:**
> 1. Never override `Gemini.api_client`: it breaks ADK's `@PerLoopCachedProperty` and leaks `aiohttp` sessions. Always use `client_kwargs`.
> 2. The pre-filled `build_gemini4_generate_config()` below your TODO sets `ThinkingConfig(thinking_level=...)` to strictly `LOW | MEDIUM | HIGH | XHIGH`. Passing `MINIMAL` or legacy `thinking_budget` returns HTTP 400, and custom `temperature`/`top_p`/`top_k` values are ignored.

<details>
<summary>Stuck? Peek at the code</summary>

```python
def build_gemini_model(
    settings: Settings | None = None, *, role: ModelRole = "coding",
    model_override: str | None = None, retry_attempts: int = 2, initial_retry_delay: float = 1.0,
) -> Gemini:
    from google.adk.models import Gemini
    from google.genai import types

    cfg = settings or get_settings()
    resolved_model = resolve_model_name(cfg, role=role, model_override=model_override)
    validate_model_location(resolved_model, cfg.model_location)

    client_kwargs: dict[str, Any] | None = None
    if cfg.google_genai_use_enterprise:
        client_kwargs = {_detect_enterprise_client_kwarg(): True, "location": cfg.model_location}
        if cfg.google_cloud_project:
            client_kwargs["project"] = cfg.google_cloud_project

    gemini_kwargs: dict[str, Any] = {
        "model": resolved_model,
        "retry_options": types.HttpRetryOptions(initial_delay=initial_retry_delay, attempts=retry_attempts),
    }
    if client_kwargs is not None:
        model_fields = getattr(Gemini, "model_fields", None)
        if model_fields is None or "client_kwargs" in model_fields:
            gemini_kwargs["client_kwargs"] = client_kwargs
    return Gemini(**gemini_kwargs)
```

</details>

**Check it works:**
```bash
(cd starter && uv run python -c "from coding_agent.models import build_gemini_model; m = build_gemini_model(); print(m.model, m.client_kwargs)")
```
Expected output: `gemini-4-hydrogen {'enterprise': True, 'location': 'global', 'project': '<your-project-id>'}` (or `'vertexai': True` on older SDKs).

---

## Step 3: Add `LocalEnvironment` and `EnvironmentToolset`

**File:** [`starter/coding_agent/agent.py`](../starter/coding_agent/agent.py), functions `build_local_environment_toolset()` and `_assemble_runtime_components()` (two `# TODO(lab-1)` markers)

ADK's `EnvironmentToolset` gives the agent `ReadFile`, `EditFile`, `WriteFile`, and `Execute` out of the box. You'll wire `LocalEnvironment` here now, then swap it for a remote gVisor Managed Sandbox in Lab 2 with zero changes to orchestration logic.

What to update in `starter/coding_agent/agent.py`:
- Add `LocalEnvironment` to the top import: `from google.adk.environment import BaseEnvironment, LocalEnvironment`.
- In `build_local_environment_toolset()`: resolve `workspace_dir` as a `pathlib.Path` (a raw `str` crashes with `AttributeError: 'str' object has no attribute 'resolve'` on the first file call), call `.mkdir(parents=True, exist_ok=True)`, create `LocalEnvironment(working_dir=resolved_dir)`, and return `EnvironmentToolset(environment=local_env, max_output_chars=max_output_chars)` (`max_output_chars` belongs on `EnvironmentToolset`, not `LocalEnvironment`).
- In `_assemble_runtime_components()`: remove the `# TODO(lab-1)` comment and `try/except NotImplementedError` wrapper so `cfg.sandbox_mode == "local"` calls `build_local_environment_toolset()` directly.
- Keep `app = App(root_agent=root_agent, name="coding_agent", **_build_app_options())` unchanged: `App.name` must match the `coding_agent` directory name or ADK throws `"Session not found"`.

<details>
<summary>Stuck? Peek at the code</summary>

```python
# Top of starter/coding_agent/agent.py:
from google.adk.environment import BaseEnvironment, LocalEnvironment


def build_local_environment_toolset(workspace_dir: Path, max_output_chars: int = 12_000) -> EnvironmentToolset:
    resolved_dir = Path(workspace_dir).resolve()
    resolved_dir.mkdir(parents=True, exist_ok=True)
    return EnvironmentToolset(environment=LocalEnvironment(working_dir=resolved_dir), max_output_chars=max_output_chars)


# Inside _assemble_runtime_components(cfg: Settings):
    if cfg.sandbox_mode == "local":
        local_toolset = build_local_environment_toolset(workspace_dir=cfg.local_workspace_path, max_output_chars=cfg.max_output_chars)
        active_environment = getattr(local_toolset, "_environment", None)
        tools.append(local_toolset)
```

</details>

**Check it works:**
```bash
(cd starter && uv run python -c "from coding_agent.agent import app, root_agent; print(app.name, root_agent.name, len(root_agent.tools))")
```
Expected output: `coding_agent coding_agent 1`.

---

## Step 4: Test `simple` Mode Locally in `adk web`

Start the local ADK Dev UI and test file writes, surgical edits, and `pytest` runs.

> [!IMPORTANT]
> Always run `adk web` from `starter/` (the parent of `coding_agent/`), never from inside `starter/coding_agent/`.

```bash
(cd starter && uv run adk web --port 8000)
```

Open `http://localhost:8000`, pick **`coding_agent`**, and try two prompts:
1. *"Create `math_utils.py` with `safe_divide(a: float, b: float) -> float` raising `ValueError` on zero division, add `test_math_utils.py`, and run `pytest -v`."*
2. *"Use `EditFile` to add `moving_average(values: list[float], window: int)` to `math_utils.py`, add tests, and run `pytest -v`."*

**Check it works:** In the Events/Trace tab, Turn 1 calls `WriteFile` + `Execute` (`pytest` exit 0) and Turn 2 uses `EditFile` instead of rewriting the whole file. (An `Unclosed client session` message on shutdown is a benign `aiohttp` teardown warning.)

**Security reality check:** Ask the agent to run `whoami && ls -la ~/.config/gcloud`. `LocalEnvironment` confines file paths, but `Execute` still runs under your local OS user. Lab 2 fixes that with a gVisor Managed Sandbox.

---

## Step 5: Core Lab Checkpoint (Part A)

Run the Lab 1 verifier from the repo root:

```bash
make verify-lab LAB=1
```

All Core (Part A) checks (`models.py`, `agent.py`, `config.py`, `agents-cli-manifest.yaml`, `.agents/skills/`) should print `[PASS]`. If you skip Part B below, you'll see two expected `[FAIL]` lines for `# TODO(lab-1)` in `architectures.py` and `agy_headless_harness.py` (plus a harmless `[WARN]` if `agents-cli` isn't installed).

**Stopping after Part A?** Jump straight to **[Lab 2: Custom Sandbox (BYOC)](./02-LAB-CUSTOM-SANDBOX-BYOC.md)** (Labs 2-8 use `AGENT_ARCHITECTURE=simple`), or run `make fast-forward LAB=1` if you want those two Part B files filled in so `verify-lab LAB=1` and `LAB=all` are 100% green. Otherwise, continue to Part B (Steps 6-8).

---

## Optional Stretch (Part B): Multi-Agent Workflows & `agy` Harness (~30 min)

Steps 6-8 build the Antigravity (`agy`) headless CLI harness and four ADK 2.0 multi-agent architectures (`collaborative`, `graph`, `dynamic`, `agy_harness`) on top of the same Gemini 4 factory and `EnvironmentToolset`.

## Step 6: Build the `agy` Headless CLI Harness

**File:** [`starter/coding_agent/tools/agy_headless_harness.py`](../starter/coding_agent/tools/agy_headless_harness.py), functions `build_agy_command()` and `parse_agy_stream_json()` (`# TODO(lab-1)`)

The `agy` CLI provides a native Go coding loop with streaming NDJSON telemetry (`--output-format stream-json`), session continuation (`--conversation`), and a 4-tier exit-code contract:
- `0` (`SUCCESS`): Clean run. Keep `agy_error=None` even if `stderr` has warnings.
- `1` (`FAILURE`): Auth, CLI, or transport fault. Fail fast (no retry).
- `2` (`UNSUPPORTED_COMMAND`): Bad CLI flag. Never retry.
- `3` (`AGENT_ERROR`): Model/quota error, timeout, or numeric project ID rejection. Safe for bounded retry and fallback (`gemini-4-neon` -> `gemini-4-hydrogen`).

What goes inside the two TODOs:
- **`build_agy_command(prompt, config)`**: Reject blank prompts, assemble `[config.agy_bin or "agy", "-p", cleaned_prompt, "--output-format", config.output_format, "--model", config.model, "--effort", config.effort, "--print-timeout", config.print_timeout]`, and conditionally append `--conversation`, `--sandbox`, `--dangerously-skip-permissions`, and `--json-schema`.
- **`parse_agy_stream_json(...)`**: Parse NDJSON lines (keeping non-JSON lines as plain-text fallback) across both real `agy 1.5.15` nested envelopes (`{"event": "init"|"step_update"|"result", ...}`) and flat `--dry-run` events (`{"type": "session_start"|"tool_use"|"text_delta"|"result"|"error"}`). Use pre-filled `_extract_usage_counts()`, `_extract_agy_error()`, and `_classify_exit_code()` so `should_retry_or_fallback` is `True` only on exit code `3`.

> [!WARNING]
> **Agent Runtime & Auth Boundary for `agy`:** On deployed Agent Runtime (Lab 5), GCP auto-injects your numeric project number into `GOOGLE_CLOUD_PROJECT`, which `agy 1.5.15` rejects with exit code `3`. Pre-filled `build_local_agy_env()` reads `AGY_PROJECT_ID` (set by Lab 5 Terraform) to pass your string project ID instead. Never relay a developer's personal `agy` OAuth credentials inside a shared service; always use `AGY_ADC_AUTH=true` with a least-privilege Service Account.

<details>
<summary>Stuck? Peek at the code</summary>

```python
def build_agy_command(prompt: str, config: AgyHeadlessConfig) -> list[str]:
    cleaned_prompt = prompt.strip()
    if not cleaned_prompt:
        raise ValueError("Prompt passed to build_agy_command() must be non-empty.")
    cmd = [
        config.agy_bin or "agy", "-p", cleaned_prompt, "--output-format", config.output_format,
        "--model", config.model, "--effort", config.effort, "--print-timeout", config.print_timeout,
    ]
    if config.conversation_id:
        cmd.extend(["--conversation", config.conversation_id])
    if config.enable_sandbox:
        cmd.append("--sandbox")
    if config.dangerously_skip_permissions:
        cmd.append("--dangerously-skip-permissions")
    if config.json_schema is not None:
        schema_json = config.json_schema if isinstance(config.json_schema, str) else json.dumps(config.json_schema, separators=(",", ":"))
        cmd.extend(["--json-schema", schema_json])
    return cmd


def parse_agy_stream_json(
    stdout: str, stderr: str, exit_code: int, *, model: str = "",
    execution_mode: str = "local", duration_ms: int = 0, command: list[str] | None = None,
) -> AgyRunResult:
    events, stream_parts, plain_lines, tool_calls, event_errors = [], [], [], [], []
    final_text, conversation_id, token_usage, detected_model = None, None, {}, model
    for raw_line in (stdout or "").splitlines():
        line = raw_line.strip()
        if not line:
            continue
        try:
            obj = json.loads(line)
        except json.JSONDecodeError:
            plain_lines.append(raw_line)
            continue
        if not isinstance(obj, dict):
            plain_lines.append(raw_line)
            continue
        events.append(obj)
        n_init = obj.get("init") if isinstance(obj.get("init"), Mapping) else None
        n_step = obj.get("step_update") if isinstance(obj.get("step_update"), Mapping) else None
        n_res = obj.get("result") if isinstance(obj.get("result"), Mapping) else None
        for c in (x for x in (obj, n_res, n_step, n_init) if x is not None):
            for k in ("conversation_id", "conversationId", "session_id"):
                if isinstance(c.get(k), str) and c[k].strip():
                    conversation_id = c[k].strip()
                    break
            if not detected_model and isinstance(c.get("model"), str) and c["model"].strip():
                detected_model = c["model"].strip()
            for uk in ("usage", "token_usage", "usageMetadata"):
                if isinstance(c.get(uk), Mapping):
                    token_usage.update(_extract_usage_counts(c[uk]))
        ev = str(obj.get("type") or obj.get("event") or "").lower()
        if ev in {"tool_use", "tool_call", "function_call"}:
            tool_calls.append({"name": str(obj.get("name", "unknown")), "id": str(obj.get("id", "")), "input": obj.get("input", {})})
        elif n_step and str(n_step.get("step_type", "")).lower() in {"tool_use", "tool_call", "function_call"}:
            tool_calls.append({"name": str(n_step.get("name", n_step.get("tool_name", "unknown"))), "id": str(n_step.get("id", "")), "input": n_step.get("input", {})})
        err_val = obj.get("error") or (n_step.get("error") if n_step else None) or (n_res.get("error") if n_res else None)
        if ev == "error" or err_val:
            event_errors.append(str(err_val or obj.get("message") or "agy error").strip())
        if ev in {"result", "final", "response"}:
            src = n_res if n_res is not None else obj
            cand = src.get("response") or src.get("result") or src.get("text")
            if isinstance(cand, str) and cand.strip():
                final_text = cand.strip()
        else:
            src = n_step if n_step is not None else obj
            delta = src.get("text_delta") if src.get("text_delta") is not None else src.get("delta")
            if isinstance(delta, str) and delta:
                stream_parts.append(delta)
    response_text = final_text if final_text is not None else ("".join(stream_parts).strip() or "\n".join(plain_lines).strip())
    status, should_retry, hint = _classify_exit_code(exit_code)
    agy_error = _extract_agy_error(stderr or "", event_errors) if exit_code != 0 or event_errors else None
    return AgyRunResult(
        exit_code=int(exit_code), status=status, response_text=response_text, conversation_id=conversation_id,
        model=detected_model, execution_mode=execution_mode, tool_calls=tool_calls, token_usage=token_usage,
        events=events, agy_error=agy_error, stderr=(stderr or "").strip(), duration_ms=max(0, int(duration_ms)),
        should_retry_or_fallback=should_retry, actionable_hint=hint, command=list(command or []),
    )
```

For full structured content-block extraction, see [`solution/coding_agent/tools/agy_headless_harness.py`](../solution/coding_agent/tools/agy_headless_harness.py).

</details>

**Check it works:** Run the offline dry-run suite (works without Docker or a local `agy` binary):
```bash
make test-agy-harness
```
Expected output: `[PASS]` for `AgyExitCode` and checks `(1/4)` through `(3/4)` (NDJSON parsing, `--conversation` continuity, and retry matrix `{0: False, 1: False, 2: False, 3: True}`). Check `(4/4)` passes after Step 7.

---

## Step 7: Build the 4 Multi-Agent ADK 2.0 Workflows

**File:** [`starter/coding_agent/architectures.py`](../starter/coding_agent/architectures.py), functions `build_collaborative_coding_team()`, `build_graph_coding_workflow()`, `build_dynamic_coding_workflow()`, and `build_agy_harness_workflow()` (`# TODO(lab-1)`)

`starter/coding_agent/agent.py` already dispatches on `AGENT_ARCHITECTURE`, and all Pydantic schemas (`ApprovalDecision`, `CheckOutcome`, `CodeReviewReport`, `SpecPlan`) and check helpers (`_run_workspace_check`, `_format_check_findings`, `_format_approval_note`, `_build_final_report`, `_format_spec_brief`, `_format_review_section`) are pre-filled.

What each builder adds:
- **`build_collaborative_coding_team()`**: Coordinator `LlmAgent(name="coding_agent", sub_agents=[...])` (never set `mode` on root) delegating to `code_implementer` (`mode="single_turn"`), `code_reviewer` (`mode="single_turn"`, `role="reasoning"`, `output_schema=CodeReviewReport`), and `requirements_clarifier` (`mode="task"`, leaf-only).
- **`build_graph_coding_workflow()`**: `Workflow(name="coding_agent", edges=[...])` wiring `coder_agent` (`output_key="latest_code_summary"`) -> parallel `run_pytest_node` (`allow_exit_codes=frozenset({0, 5})`) and `run_ruff_node` (`@node(retry_config=RetryConfig(..., exceptions=[TimeoutError, NodeTimeoutError]), timeout=30.0)`) -> `JoinNode(name="verify_join")` -> bounded `verdict_router` (`fix_attempts < settings.max_fix_rounds`) -> optional `@node(rerun_on_resume=False)` `request_human_approval` (`RequestInput`) -> single terminal `finalize_report` resetting `fix_attempts` to `0`.
- **`build_dynamic_coding_workflow()`**: `@node(rerun_on_resume=True)` orchestrator calling `ctx.run_node(coder_agent, ...)`, parallel checks via `asyncio.gather(ctx.run_node(..., use_sub_branch=True), ...)`, bounded `for` loop yielding `Event(state={"code": ..., "findings": ..., "fix_attempts": ...})` before calling `fixer_agent` (Python `{key}` templates read session state, not `node_input`), optional HITL, and one terminal `Event`.
- **`build_agy_harness_workflow()`**: 5-stage workflow pairing `spec_planner` (`gemini-4-neon`, `SpecPlan`), `run_agy_harness_node` (`AgyHeadlessHarness` with `fallback_coder_agent` fallback and fail-fast on exit 1/2), independent parallel `pytest`/`ruff` gates, bounded `--conversation` fix loop, and independent `code_reviewer` (`gemini-4-neon`) + optional HITL.

<details>
<summary>Stuck? Peek at the core patterns (complete builders in solution/coding_agent/architectures.py)</summary>

```python
# 1. Collaborative team (set mode ONLY on subagents, never on root):
coding_lead = LlmAgent(
    name="coding_agent", model=_build_gemini_model(settings, role="coding"),
    instruction="Delegate ambiguous specs to requirements_clarifier, edits to code_implementer, reviews to code_reviewer.",
    sub_agents=[code_implementer, code_reviewer, requirements_clarifier],
    generate_content_config=_build_generate_config(settings),
)

# 2. Declarative Graph Workflow edges (converge parallel checks via JoinNode -> single terminal node):
return Workflow(name="coding_agent", edges=[
    ("START", coder_agent),
    (coder_agent, run_pytest_node, verify_join),
    (coder_agent, run_ruff_node, verify_join),
    (verify_join, verdict_router),
    (verdict_router, {"NEEDS_FIX": coder_agent, "NEEDS_APPROVAL": request_human_approval, "PASS": finalize_report}),
    (request_human_approval, finalize_report),
])

# 3. Dynamic Workflow loop (@node(rerun_on_resume=True) + yield Event(state=...) before fixer_agent):
@node(name="dynamic_coding_workflow", rerun_on_resume=True)
async def dynamic_coding_workflow(ctx: Context, node_input: str):
    code_summary = await ctx.run_node(coder_agent, node_input)
    pytest_res, ruff_res = await asyncio.gather(
        ctx.run_node(run_pytest_node, code_summary, use_sub_branch=True),
        ctx.run_node(run_ruff_node, code_summary, use_sub_branch=True),
    )
    latest_findings = _format_check_findings(pytest_res, ruff_res)
    for attempt in range(settings.max_fix_rounds):
        if not latest_findings:
            break
        yield Event(state={"code": str(code_summary), "findings": latest_findings, "fix_attempts": attempt + 1})
        code_summary = await ctx.run_node(fixer_agent, {"code": str(code_summary), "findings": latest_findings})
        pytest_res, ruff_res = await asyncio.gather(
            ctx.run_node(run_pytest_node, code_summary, use_sub_branch=True),
            ctx.run_node(run_ruff_node, code_summary, use_sub_branch=True),
        )
        latest_findings = _format_check_findings(pytest_res, ruff_res)
```

Copy or compare the complete builders in [`solution/coding_agent/architectures.py`](../solution/coding_agent/architectures.py).

</details>

**Check it works:** Re-run `make test-agy-harness` (all 4/4 checks pass), then switch architectures in `adk web`:
```bash
make test-agy-harness
(cd starter && AGENT_ARCHITECTURE=graph MAX_FIX_ROUNDS=3 uv run adk web --port 8000)
# Also try: AGENT_ARCHITECTURE=collaborative | dynamic | agy_harness
```

---

## Step 8: Inspect Service Registration and Reset to `simple`

Skim [`starter/services.yaml`](../starter/services.yaml) and [`starter/services.py`](../starter/services.py) to see how ADK 2.0 auto-discovers custom session/artifact/memory URI schemes (both stay inactive until `ENABLE_CUSTOM_SERVICE_REGISTRY=true`). Keep `AGENT_ARCHITECTURE=simple` in `.env` before Lab 2 so your agent matches Lab 6's evaluation datasets.

---

## Lab 1 Checkpoint

Run the Lab 1 verifier from the repo root:

```bash
make verify-lab LAB=1
```

Confirm zero `[FAIL]` lines (`WARN: agents-cli not found on PATH` is benign if you skipped `agents-cli`), then continue to **[Lab 2: Custom Sandbox (BYOC), Lifecycle & Execution](./02-LAB-CUSTOM-SANDBOX-BYOC.md)**.

---

## Optional Reference & Deep Dive

<details>
<summary>Greenfield <code>google/agents-cli</code> rules &amp; Service Registration (<code>services.yaml</code> / <code>services.py</code>)</summary>

- **Greenfield `agents-cli`:** Scaffold new repos with `agents-cli create my-coding-agent --agent adk_python -d agent_runtime -y` (or `--adk`). Project names must be `<= 26` chars (`a-z`, `0-9`, `-`), never `mkdir <name>` first, and for non-`app/` layouts run `agents-cli scaffold enhance . --from-adk-project --agent-directory coding_agent` (already pre-configured in [`starter/agents-cli-manifest.yaml`](../starter/agents-cli-manifest.yaml)). Opt out of CLI telemetry with `AGENTS_CLI_TELEMETRY=0` or `DO_NOT_TRACK=1`.
- **Service Registration:** `adk run` scans `coding_agent/`; `adk web` and `adk api_server` scan `starter/`. ADK loads `services.yaml` first (`scheme`, `type: session|artifact|memory|task_store`, `class`) and `services.py` second via `get_service_registry()`. On duplicate schemes, `services.py` overrides `services.yaml`.

</details>

<details>
<summary><code>ManagedAgent</code> (Preview) &amp; <code>ExecuteBashTool</code> Comparisons</summary>

| Dimension | `ManagedAgent` (ADK Python v2.4.0 Preview) | Custom `LlmAgent` / Workflows (This Workshop) |
|---|---|---|
| Tools & execution | Server-side only (`google_search`, built-in code exec, `RemoteMcpServer`); Python callables raise `NotImplementedError`. | Custom Python tools, `EnvironmentToolset`, BYOC gVisor sandboxes (Lab 2), MCP, `SkillToolset` (Lab 4), callbacks (Lab 3). |
| Region & transport | `global`-only, streaming-only (`stream=True`), server-owned history/sandbox. | Regional (`asia-southeast1`), unary/streaming/async (7d), Managed Sessions & Memory Bank, CMEK/VPC-SC/PSC-I. |
| Composition | Attach in `LlmAgent.sub_agents` with `mode="single_turn"` (see `build_optional_managed_agent()` in `architectures.py`). | Core enterprise coding workflow with full egress and audit control. |

**`EnvironmentToolset` vs. `ExecuteBashTool`:** We use `EnvironmentToolset` because it exposes `ReadFile`/`EditFile`/`WriteFile`/`Execute`, swaps cleanly from `LocalEnvironment` to `AgentPlatformSandboxEnvironment`, and shares `environment=` with `SkillToolset` in Lab 4. For local dev CLIs where every shell call must prompt for HITL approval, ADK Python 2.0+ also offers `ExecuteBashTool(workspace=Path(...), policy=BashToolPolicy(...))` (POSIX-only; always replace its default `allowed_command_prefixes=("*",)` and set `blocked_operators` + `RLIMIT_*` bounds).

</details>

<details>
<summary>All 7 ADK 2.0 Multi-Agent Patterns, <code>State</code> API &amp; Retry/HITL Rules</summary>

| # | Pattern | ADK 2.0 Python Primitive | Coding Agent Example |
|---|---|---|---|
| 1 | Coordinator & Dispatcher | `LlmAgent` with `sub_agents` (`single_turn` / `task`) | `coding_lead` -> implementer, reviewer, clarifier |
| 2 | Sequential Pipeline | `Workflow(edges=[("START", step1, step2, step3)])` | Write code -> run checks -> summarize |
| 3 | Parallel Fan-Out & Gather | Graph fan-out + `JoinNode`, or `asyncio.gather(ctx.run_node(..., use_sub_branch=True))` | Concurrent `pytest` + `ruff`, then merge |
| 4 | Hierarchical Decomposition | Multi-level `sub_agents` (`single_turn`; leaf-only for `task`) or nested `Workflow`s | Planner delegating to specialist teams |
| 5 | Generate & Review | `Workflow(edges=[("START", coder, reviewer)])` | Patch generation -> static + LLM review |
| 6 | Iterative Refinement | Dynamic `@node(rerun_on_resume=True)` loop or routed back-edge | Edit -> check -> fix capped at `MAX_FIX_ROUNDS` |
| 7 | Human-in-the-Loop (HITL) | `RequestInput` (`ResumabilityConfig(is_resumable=True)`) or `FunctionTool(require_confirmation=True)` | Sign-off before risky refactors or deploys |

- **Collaboration modes:** `chat` (manual `transfer_to_agent`), `task` (clarification questions, automatic `finish_task`, leaf-only, disabled in Python v2.0.0 graph `Workflow`s), `single_turn` (no user chat, parallel-safe, automatic return). Use `GlobalInstructionPlugin` on `App` for shared guardrails across isolated subagent branches.
- **Graph invariants:** Every branch feeding a `JoinNode` must produce output; at most one terminal node may produce output (two parallel leaf outputs raise `ValueError`). Graph cycles require a routed edge (`Event(route=...)`) and are not bounded automatically. Yield at most one `Event(output=...)` per node execution.
- **`State` API gotcha:** `ctx.state` supports `.get()`, `.setdefault()`, `.update()`, `.to_dict()`, `in`, `[]`, and iteration, NOT `.pop()`, `.keys()`, `.items()`, `.values()`, `del`, or `len()`. Clear keys with `state[key] = None` or `yield Event(state={key: ""})`.
- **Retries, timeouts, HITL & `output_schema`:** `@node(retry_config=RetryConfig(...), timeout=30.0)` applies `timeout` per attempt and raises `NodeTimeoutError` (include it in `exceptions` to retry timeouts). Never catch `BaseException` (traps `NodeInterruptedError`). `ctx.attempt_count` resets to 1 after HITL pauses/restarts. Leaf HITL nodes use `rerun_on_resume=False`; dynamic parents calling `ctx.run_node()` require `rerun_on_resume=True`. Keep `output_schema` on specialist agents (`code_reviewer`, `spec_planner`) rather than tool-heavy coders.

</details>

<details>
<summary><code>agy</code> CLI Install, Flags &amp; Execution Modes</summary>

Install the static Go `agy` binary locally (download, execute, delete):
```bash
curl -fsSL https://antigravity.google/cli/install.sh -o /tmp/agy_install.sh \
  && bash /tmp/agy_install.sh && rm -f /tmp/agy_install.sh
AGY_ADC_AUTH=true agy models
```

Flags: `-p "<prompt>"`, `--output-format stream-json|json|text`, `--model`, `--effort low|medium|high|xhigh`, `--print-timeout 5m`, `--conversation <id>`, `--sandbox`, `--dangerously-skip-permissions` (isolated gVisor/CI only), `--json-schema`.

`AGY_EXECUTION_MODE`: `local` runs in-host/Agent Runtime (`AGY_ADC_AUTH=true` + non-numeric `AGY_PROJECT_ID` + `GOOGLE_CLOUD_LOCATION=global`); `sandbox` delegates into BYOC gVisor via `execute_with_env()` (needs PSC-I egress + ephemeral creds); `auto` prefers `local` when ADC auth is on without a BYOC `GEMINI_API_KEY` (reserving air-gapped sandboxes for `pytest`/`ruff`/`bandit`) and falls back to native `LlmAgent` + `EnvironmentToolset` if `agy` isn't installed.

**Canonical docs:** [ADK 2.0](https://adk.dev/2.0/) | [EnvironmentToolset](https://adk.dev/integrations/environment-toolset/) | [Collaboration](https://adk.dev/workflows/collaboration/) | [Graphs](https://adk.dev/graphs/) | [Dynamic Workflows](https://adk.dev/graphs/dynamic/) | [google/agents-cli](https://github.com/google/agents-cli)

</details>
