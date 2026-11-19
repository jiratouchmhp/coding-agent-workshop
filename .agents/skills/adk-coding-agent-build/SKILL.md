---
name: adk-coding-agent-build
description: >-
  Builds ADK Python coding agents with agents-cli. Use when implementing
  EnvironmentToolset (ReadFile/EditFile/WriteFile/Execute), LocalEnvironment
  Path, BaseEnvironment (EnvironmentScope/Context/SkillToolset),
  ExecuteBashTool/BashToolPolicy, LlmAgent/App/AdkApp, FunctionTool
  (require_confirmation), McpToolset,
  callbacks/BasePlugin/GlobalInstructionPlugin, state/artifacts/.env,
  ManagedAgent, services.yaml/services.py, collaborative mode
  (chat/task/single_turn), deprecated template workflows, RoutedAgent, ADK 2.0
  Workflow/JoinNode/Event(route/output), RequestInput,
  RetryConfig/NodeTimeoutError, dynamic ctx.run_node/rerun_on_resume, 1.x
  migration, or agents-cli run/lint/extensions/adk-recipes. Don't use for
  sandboxes (agent-platform-sandbox-byoc), Runtime
  (agent-platform-runtime-and-state), registries
  (agent-platform-governance-and-registries), evals
  (agent-platform-optimize-and-eval), GKE (agent-runtime-vs-gke-architecture),
  or google-agents-cli-{scaffold,adk-code,deploy,eval,publish}.
---

# ADK Coding Agent Build Guide (`adk-coding-agent-build`)

Build reliable, confined **Google ADK Python** coding agents (`v1.29.0+` / `v2.0+`) and integrate them cleanly with **`google/agents-cli`** (`~= 1.15.0`). This skill owns coding-agent toolsets, verified source contracts, ADK 2.0 agent/workflow architectures (collaborative teams, static graphs, dynamic orchestrators), service registration, and build-time `agents-cli` boundaries—without duplicating the 7 global `google-agents-cli-*` built-in skills.

---

## Quick Decision Tree: Choosing the Right Execution Primitive, Architecture & Skill

```text
What are you building or configuring?
├── Single local dev coding agent (read/edit/write/exec in a workspace folder)
│   └── EnvironmentToolset(environment=LocalEnvironment(working_dir=Path(...)), max_output_chars=12_000)
│       [See references/coding-agent-toolsets.md]
├── Local interactive CLI assistant needing strict command allowlist + per-command approval (POSIX only)
│   └── ExecuteBashTool(workspace=Path(...), policy=BashToolPolicy(allowed_command_prefixes=(...), blocked_operators=(...)))
│       [See references/coding-agent-toolsets.md]
├── Production coding agent running untrusted code per session / per user
│   ├── Implement BaseEnvironment subclass here (scope=EnvironmentScope.SESSION, *, ctx: Context | None = None)
│   │   [See references/coding-agent-toolsets.md]
│   └── Provision BYOC Dockerfile, SandboxEnvironmentTemplate & egress -> `agent-platform-sandbox-byoc`
├── Multi-agent coordinator team, custom backend services, routing, or template migration
│   ├── Open-ended delegation -> LlmAgent coordinator + subagent mode="single_turn" / "task" + GlobalInstructionPlugin
│   ├── Custom session/artifact/memory/task_store backends -> services.yaml / services.py (v1.34.0+)
│   ├── Server-hosted zero-ops prototype (no client Python tools, global-only) -> ManagedAgent (v2.4.0 Preview) + RemoteMcpServer
│   └── Legacy SequentialAgent/ParallelAgent/LoopAgent or TS RoutedAgent -> migrate/map to ADK 2.0
│       [See references/agent-architectures-and-workflows.md]
├── Deterministic pipelines, conditional branches, parallel fan-out/JoinNode, HITL, or retries
│   └── ADK 2.0 Graph Workflow (`Workflow`, `Event(route/output)`, `JoinNode`, `RequestInput`, `RetryConfig`)
│       [See references/graph-and-dynamic-workflows.md]
├── Bounded edit -> lint/test -> fix loops, dynamic list fan-out, or durable checkpointing
│   └── ADK 2.0 Dynamic Workflow (`@node(rerun_on_resume=True)`, `await ctx.run_node(...)`, `asyncio.gather(..., use_sub_branch=True)`)
│       [See references/graph-and-dynamic-workflows.md]
└── Downstream lifecycle operations (hand off to specialized skills)
    ├── Generic project scaffolding / boilerplate -> `google-agents-cli-scaffold` / `google-agents-cli-adk-code`
    ├── Declarative Terraform, quotas, Managed Sessions, Memory Bank, Feedback -> `agent-platform-runtime-and-state`
    ├── Skill Registry (16 ZIP checks), Agent Registry, Semantic Governance -> `agent-platform-governance-and-registries`
    ├── Managed Online Eval Monitors, Quality Alerts, Optimize Flywheel -> `agent-platform-optimize-and-eval`
    └── Agent Runtime vs. Self-Hosted GKE Agent Sandbox trade-offs -> `agent-runtime-vs-gke-architecture`
```

---

## Critical Gotchas ("Do This, Not That")

| Do This | Not That | Why (Source-Verified) |
|---|---|---|
| `LocalEnvironment(working_dir=Path("/tmp/ws").resolve())` | `LocalEnvironment(working_dir="/tmp/ws")` | `_local_environment.py` calls `self._working_dir.resolve()` without coercion; a raw `str` raises `AttributeError`. |
| `EnvironmentToolset(environment=env, max_output_chars=12_000)` | `LocalEnvironment(max_output_chars=12_000)` | `max_output_chars` belongs exclusively on `EnvironmentToolset` (truncates `Execute` & `ReadFile` output). |
| Implement **3** abstract methods on `BaseEnvironment`: `execute`, `read_file`, `write_file` + `*, ctx: Context \| None = None` | Implementing `edit_file` or omitting `ctx` | `EditFileTool` composes `read_file` + `write_file`; omitting `ctx` emits `DeprecationWarning` and drops `ctx`. |
| Set `scope = EnvironmentScope.SESSION` + fixed `working_dir = Path("/workspace")` | Default `SHARED` or reading `ctx` inside `working_dir` | `working_dir` takes no `ctx`; `SESSION` scope lets concurrent sessions initialize isolated sandboxes in parallel. |
| Pass `environment=shared_env` **OR** `code_executor=...` to `SkillToolset` | Passing both `environment=` and `code_executor=` | Passing both raises `ValueError`; `save_output_artifacts=True` works only with `code_executor`. |
| Set explicit `BashToolPolicy(allowed_command_prefixes=(...), blocked_operators=(...))` | Using default `BashToolPolicy()` | Default `allowed_command_prefixes=("*",)` permits **every** command; POSIX-only with mandatory HITL approval. |
| Set `App(name="<folder_basename>", root_agent=root_agent)` + explicit versioned model ID (`gemini-2.5-flash`) | Arbitrary `App.name` or `gemini-flash-latest` on regional endpoints | Name mismatch causes `"Session not found"`; `gemini-flash-latest` can 404 on regional endpoints like `us-central1`. |
| Isolate `output_schema` in a formatter subagent/node for non-Gemini models; never set `mode` on root agent | Assuming `output_schema` + `tools=[...]` works reliably on every model, setting `mode` on root, or using `mode="task"` in Python v2.0.0 graphs | Python ADK supports `output_schema` + `tools` directly on Gemini on GCP, but other models fall back to an unreliable `set_model_response` tool; `task` mode must be a leaf agent and is disabled in Python v2.0.0 graph `Workflow`s. |
| Migrate `SequentialAgent`/`ParallelAgent`/`LoopAgent` to `Workflow` / dynamic `ctx.run_node` | New orchestration on deprecated template agents, or nesting `Workflow` in `LlmAgent.sub_agents` | Template agents are deprecated in Py/TS/Go/Kt; `Workflow` cannot yet be used as an `LlmAgent` `sub_agent`. |
| Emit **at most ONE** `Event(output=...)` per Python node; merge parallel leaves with `JoinNode` | Multiple `Event(output=...)` yields, silent `JoinNode` feeders, or >=2 terminal outputs | Multiple `Event(output=...)` raises a Python runtime error; >=2 terminal outputs raise `ValueError`; every `JoinNode` feeder must output. |
| Put Python `{key}` templates in `state` first; bound graph cycles or use dynamic `for`/`while` | Writing `{Class.field}` in Python instructions or assuming graph cycles auto-bound | Python `{key}` reads session state only (not `node_input`); graph cycles require >=1 routed edge and are never auto-bounded. |
| Check **both** `tool_confirmation` & `.confirmed`; parse `RequestInput` via UI/post-node; set `@node(rerun_on_resume=True)` on `ctx.run_node` orchestrators | Expecting `RequestInput(response_schema=...)` to reformat text, skipping `.confirmed`, or numeric `run_id="1"` | `response_schema` does not reformat replies; manual `request_confirmation()` does not auto-reject; custom `run_id` needs >=1 non-numeric char. |
| Include `NodeTimeoutError` in explicit `RetryConfig(exceptions=[...])` and never swallow `BaseException` | Broad `except Exception:` / `except BaseException:` or trusting `ctx.attempt_count` across pauses | Broad `except` disables retries; `BaseException` traps `NodeInterruptedError` (breaks HITL); `attempt_count` resets to `1` after pauses/restarts. |
| Keep `ManagedAgent` on `global` + `RemoteMcpServer` + `mode="single_turn"`; run `agents-cli infra --apply` before first `deploy` | Local Python tools on `ManagedAgent`, or running Terraform after imperative `deploy` | Client tools/raw `types.Tool.mcp_servers` raise `NotImplementedError`; post-deploy Terraform breaks observability ownership. |

---

## Quick-Start Patterns

### 1. Confined ADK Coding Agent (`LlmAgent` + `EnvironmentToolset` + `App`)

```python
from pathlib import Path
from google.adk.agents import LlmAgent
from google.adk.agents.callback_context import CallbackContext
from google.adk.apps import App, ResumabilityConfig
from google.adk.environment import LocalEnvironment
from google.adk.models import Gemini
from google.adk.tools.environment import EnvironmentToolset
from google.genai import types

async def init_workspace_state(callback_context: CallbackContext) -> None:
    callback_context.state.setdefault("repo_name", "workspace")

workspace_dir = Path("/tmp/coding_agent_workspace").resolve()
workspace_dir.mkdir(parents=True, exist_ok=True)

env_toolset = EnvironmentToolset(
    environment=LocalEnvironment(working_dir=workspace_dir),  # MUST be pathlib.Path!
    max_output_chars=12_000,
)

root_agent = LlmAgent(
    name="coding_agent",
    model=Gemini(
        model="gemini-2.5-flash",  # Explicit versioned model ID for regional endpoints
        retry_options=types.HttpRetryOptions(initial_delay=1, attempts=2),
    ),
    description="Coding agent that reads, edits, writes, and tests code inside its workspace.",
    instruction="""You are a coding agent working in {repo_name}.
1. Inspect files with ReadFile before editing.
2. Prefer surgical EditFile updates over full-file rewrites.
3. Verify changes with pytest/ruff via Execute; never fabricate test results.""",
    tools=[env_toolset],
    before_agent_callback=init_workspace_state,
    generate_content_config=types.GenerateContentConfig(temperature=0.2),
)

# App.name MUST match the agent directory basename (e.g., "coding_agent" or "app")
app = App(
    name="coding_agent",
    root_agent=root_agent,
    resumability_config=ResumabilityConfig(is_resumable=True),
)
```

### 2. Custom `BaseEnvironment` ABC Contract (Per-Session Remote Sandbox)

```python
# Implement exactly 3 abstract methods (NO edit_file); ALWAYS accept `*, ctx: Context | None = None`
class RemoteSandboxEnvironment(BaseEnvironment):
    scope = EnvironmentScope.SESSION        # Fixed per-instance; parallel per-session sandboxes
    working_dir = Path("/workspace")        # Takes no ctx; mount same logical path per sandbox
    async def initialize(self, *, ctx: Context | None = None) -> None: ...  # Lazily store ID in ctx.state
    async def execute(self, command: str, *, timeout: float | None = None, ctx: Context | None = None) -> ExecutionResult: ...
    async def read_file(self, path: Path, *, ctx: Context | None = None) -> bytes: ...
    async def write_file(self, path: Path, content: str | bytes, *, ctx: Context | None = None) -> None: ...
# Full runnable subclass: see references/coding-agent-toolsets.md
```

### 3. ADK 2.0 Dynamic Edit -> Verify -> Fix Coding Loop

```python
from google.adk import Context, Event, Workflow
from google.adk.workflow import NodeTimeoutError, RetryConfig, node

@node(
    retry_config=RetryConfig(max_attempts=3, initial_delay=1.0, exceptions=[TimeoutError, NodeTimeoutError]),
    timeout=30.0,
)
async def run_checks(ctx: Context, node_input: str) -> dict:
    return {"passed": True, "findings": ""}

@node(rerun_on_resume=True)  # Mandatory on orchestrators calling ctx.run_node()
async def coding_loop(ctx: Context, node_input: str):
    code = await ctx.run_node(coder_agent, node_input)
    result = await ctx.run_node(run_checks, code)
    for _ in range(3):
        if result["passed"]:
            break
        yield Event(state={"code": code, "findings": result["findings"]})  # Populates {code}/{findings}
        code = await ctx.run_node(fixer_agent, {"code": code, "findings": result["findings"]})
        result = await ctx.run_node(run_checks, code)
    yield Event(output=code)

root_workflow = Workflow(name="coding_workflow", edges=[("START", coding_loop)])
```

### 4. `google/agents-cli` Build & Local Verification Loop

```bash
# 1. One-time install (Python 3.11+ and uv required); optional telemetry opt-out: export AGENTS_CLI_TELEMETRY=0
uvx google-agents-cli setup && agents-cli info

# 2a. Greenfield project (<=26 chars, NEVER mkdir first)
agents-cli scaffold create my-coding-agent -a adk_python -d agent_runtime --region us-central1 --prototype

# 2b. Or adopt an existing ADK repo with a custom package directory (writes agents-cli-manifest.yaml only)
agents-cli scaffold enhance . --from-adk-project --agent-directory coding_agent

# 3. Install, lint, smoke-test & open local hot-reload playground (http://localhost:8080)
agents-cli install && agents-cli lint
agents-cli run "Write hello.py and verify it with python3" -v
agents-cli playground

# 4. Evaluate behavior (never assert LLM prose in pytest!) before promoting/deploying
agents-cli eval run
# If Terraform-managed observability is needed, run infra BEFORE first deploy:
# agents-cli infra single-project --apply && agents-cli deploy --no-wait
```

---

## Modular References

Load the specific reference file matching your task (all references are 1-hop from this file):

| Reference File | Deep-Dive Contents |
|---|---|
| [references/adk-core-and-setup.md](references/adk-core-and-setup.md) | 5-namespace SDK divergence (`google.adk` / `vertexai` / `agentplatform` / `google.genai`), `.env` & auth modes (`GOOGLE_GENAI_USE_ENTERPRISE` vs `VERTEXAI`), ADK version milestones, `LlmAgent`/`App`/`AdkApp`, Gemini regional retries & Interactions API, `FunctionTool`/`McpToolset`, exact callback signatures, `BasePlugin`, state prefixes, Artifacts, and all 5 ADK 1.x->2.0 breaking changes. |
| [references/agent-architectures-and-workflows.md](references/agent-architectures-and-workflows.md) | Single-agent evolution triggers, `ManagedAgent` (Python v2.4.0 Preview: Gemini API vs Agent Platform `global`-only, `RemoteMcpServer`, `mode="single_turn"`, remote state vs `interaction_id`/`environment_id`), `services.yaml` vs `services.py` (v1.34.0 discovery & precedence), ADK 2.0 collaborative teams (`chat`/`task`/`single_turn`, `GlobalInstructionPlugin`, isolated branches), deprecated template workflows (`SequentialAgent`/`ParallelAgent`/`LoopAgent`), TS `RoutedAgent` + Python equivalents, and all 7 multi-agent patterns mapped to ADK 2.0. |
| [references/graph-and-dynamic-workflows.md](references/graph-and-dynamic-workflows.md) | Complete ADK 2.0 Graph & Dynamic Workflow deep dive: `Workflow(edges=[...])`, conditional/multi-route `Event(route=...)` & `DEFAULT_ROUTE`, `JoinNode` fan-out/fan-in & single terminal output `ValueError`, bounded back-edge cycles, `Event(output/message/state)` & Python single-output / `{key}`-from-state rules vs TS/Go/Kotlin, `RequestInput` HITL vs `FunctionTool` confirmation, `RetryConfig` / `NodeTimeoutError` / `ctx.attempt_count`, and dynamic `@node(rerun_on_resume=True)` / `ctx.run_node` / `asyncio.gather(..., use_sub_branch=True)` / custom `run_id` rules. |
| [references/coding-agent-toolsets.md](references/coding-agent-toolsets.md) | Source-verified `EnvironmentToolset` internals, `LocalEnvironment` `Path` bug & subprocess teardown, complete 9-member `BaseEnvironment` ABC contract (`EnvironmentScope`, `ExecutionResult`, `ctx` inspection), `SkillToolset` shared-environment rules, `ExecuteBashTool` + `BashToolPolicy` hardening (`RLIMIT_*`, whole-token matching, mandatory HITL), Pre-GA `ManagedAgent` contrast, and pytest verification harness. |
| [references/agents-cli-lifecycle.md](references/agents-cli-lifecycle.md) | Complete `google/agents-cli` (`~= 1.15.0`) command & flag matrices (`setup`, `create`, `scaffold enhance/upgrade`, `run`, `playground`, `lint`, `eval`, `infra`, `deploy`, `publish`), `agents-cli-extension.yaml` (`v1alpha1`) schema & override rules, all 11 curated `google/adk-recipes` (`long-horizon-harness`), and the 7-skill `google-agents-cli-*` anti-shadowing map. |
| [references/maintenance.md](references/maintenance.md) | Upstream seed URLs (`adk.dev/get-started/`, `github.com/google/agents-cli`), complete Tier-1/Tier-2 `.md`/`.md.txt`/raw GitHub refresh endpoints (including all 14 ADK architecture & graph docs), verification date (`2026-11-19`), and section-by-section refresh checklist. |

---

## Maintenance

Last verified against official ADK docs, `google/adk-python` source, and `google/agents-cli` v1.15.0 on **`2026-11-19`**. See [references/maintenance.md](references/maintenance.md) for all canonical upstream URLs, refresh endpoints, and update procedures.
