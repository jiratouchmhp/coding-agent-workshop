# Google ADK Python 2.0+ Core & Setup Reference

Deep-dive reference for building production coding agents in **Google ADK Python 2.0+**, covering SDK namespaces, authentication, `LlmAgent`/`App`/`AdkApp`, Gemini model configuration, tools, callbacks, state, artifacts, ADK 2.0 graph `Workflow`s, and the ADK 2.0 Native Design Contract.

---

## 1. Python Prerequisites, SDK Namespaces & Version Milestones

### Python & Package Prerequisites
- **ADK Python 2.0+ & `google/agents-cli`:** Python **3.11+**.
- **Canonical Install:** `pip install "google-adk[a2a,agent-identity,mcp]>=2.0.0"` (or `uv add "google-adk[a2a,agent-identity,mcp]>=2.0.0"`).

### SDK Namespace Divergence Matrix

Google Cloud and ADK documentation span **five Python package/import namespaces**. Never mix client APIs across namespaces without confirming version compatibility:

| Namespace / Package | Install Command | Canonical Imports / Client Init | Primary Use & Verified Gotchas |
|---|---|---|---|
| **`google.adk`** (`google-adk`) | `pip install "google-adk>=2.0.0"` (core)<br>`pip install "google-adk[a2a,agent-identity,mcp]>=2.0.0"` (recommended full coding-agent set) | `from google.adk import Agent, Workflow, Event`<br>`from google.adk.agents import Agent, LlmAgent`<br>`from google.adk.agents.context import Context`<br>`from google.adk.apps import App`<br>`from google.adk.models import Gemini`<br>`from google.adk.tools import ToolContext`<br>`from google.adk.environment import BaseEnvironment, EnvironmentScope, ExecutionResult, LocalEnvironment`<br>`from google.adk.tools.environment import EnvironmentToolset`<br>`from google.adk.tools.bash_tool import ExecuteBashTool, BashToolPolicy` | Core ADK 2.0+ framework. `Agent` and `LlmAgent` are interchangeable aliases. Scaffolded `agents-cli` projects ship `google-adk[gcp,otel-gcp]`; include the `mcp` extra before using `McpToolset`. |
| **`vertexai`** (`google-cloud-aiplatform`) | `pip install "google-cloud-aiplatform[agent_engines,adk,langchain,ag2,llama_index]>=1.154.0"` | `import vertexai`<br>`client = vertexai.Client(project="PROJECT_ID", location="LOCATION")` | Companion Reasoning Engine client (`google-cloud-aiplatform >= 1.154.0` re-exports `agentplatform`). **Known bug:** `google-cloud-aiplatform <= 1.128.0` causes `"Session not found"` after `publish gemini` registration — upgrade before deploying/publishing. |
| **`agentplatform`** (`google-cloud-agentplatform >= 2.0.1` / `google-cloud-aiplatform >= 1.154.0`) | `pip install "google-cloud-agentplatform>=2.0.1"` (canonical)<br>or `pip install "google-cloud-aiplatform>=1.154.0"` (re-export) | `import agentplatform`<br>`from agentplatform import types`<br>`from agentplatform.frameworks import AdkApp`<br>`client = agentplatform.Client(project="PROJECT_ID", location="LOCATION")` | Canonical Gemini Enterprise Agent Platform client & `AdkApp` runtime wrapper namespace: `google-cloud-agentplatform>=2.0.1` for `AdkApp`, Runtime, Sessions, Memory Bank, Feedback Service, and Scale Sandboxes; `google-cloud-aiplatform>=1.154.0` re-exports `agentplatform` and promotes Skill Registry `skill_id` to a top-level kwarg. |
| **`google.genai`** (`google-genai`) | Installed with `google-adk` / `google-cloud-aiplatform` | `from google import genai`<br>`from google.genai import types`<br>`client = genai.Client(vertexai=True, project="PROJECT_ID", location="global")` | `GenerateContentConfig`, `HttpOptions`, `HttpRetryOptions`, `SafetySetting`, `Part`/`Blob`, model discovery (`client.models.list()`), and Managed Agents API (`client.agents.*`). |
| **`google.cloud.*`** | e.g., `pip install google-cloud-secret-manager` | `from google.cloud import secretmanager, storage` | Direct GCP clients for Secret Manager, Cloud Storage, Cloud Monitoring (`monitoring_v3`), and Cloud Trace (`trace_v2`). |

### Verified ADK Python 2.0+ Version Milestones

| Version | Key Capability |
|---|---|
| `v2.0.0+` | Graph-based & Dynamic Workflow Runtime (`google.adk.workflow.Workflow`, `@node`, `JoinNode`, `RequestInput`, `RetryConfig`) — GA May 19, 2026 (Python), June 30, 2026 (Go), August 21, 2026 (TypeScript); collaborative subagent modes (`chat`/`task`/`single_turn`); `EnvironmentToolset`/`LocalEnvironment`/`BaseEnvironment`/`EnvironmentScope`; `ExecuteBashTool`/`BashToolPolicy`; `SkillToolset`/`GCPSkillRegistry`; `AgentRegistry`; Service Registration (`services.yaml`/`services.py`); Gemini Interactions API (`use_interactions_api=True`); and `AgentEngineSandboxCodeExecutor` |
| `v2.1.0+` / `v2.12.0+` | Agent Anomaly Detection (Preview): `2.1.0+` for GKE/Agent Runtime/Cloud Run; `2.12.0+` for multi-cloud OTel export via `telemetry.googleapis.com` |
| `v2.4.0+` | `ManagedAgent` (`from google.adk.agents import ManagedAgent`, Preview) wrapping Google's first-party server-hosted agents |

---

## 2. Authentication, `.env` Mapping & GCP Prerequisites

### Environment Variable Mapping

| Mode | Required Environment Variables | Notes & Gotchas |
|---|---|---|
| **Google Cloud / Agent Platform (ADC — Recommended)** | `GOOGLE_GENAI_USE_ENTERPRISE=TRUE`<br>`GOOGLE_CLOUD_PROJECT=<project-id>`<br>`GOOGLE_CLOUD_LOCATION=asia-southeast1` *(or `<region-or-global>`)* | Run `gcloud auth application-default login` locally. `GOOGLE_GENAI_USE_ENTERPRISE=TRUE` is the canonical ADK 2.0 enterprise authentication switch. ADC credentials expire after **1 hour** by default. |
| **Google AI Studio (Local Dev)** | `GEMINI_API_KEY=<key>` (or `GOOGLE_API_KEY=<key>`) | **Comment out** `GOOGLE_GENAI_USE_ENTERPRISE`, `GOOGLE_CLOUD_PROJECT`, and `GOOGLE_CLOUD_LOCATION` in `.env` so the SDK routes to Google AI Studio. |
| **Agent Platform Express Mode (Prototyping)** | `GOOGLE_GENAI_USE_ENTERPRISE=TRUE`<br>`GOOGLE_GENAI_API_KEY=<express-key>` | Rapid API-key prototyping only; standard GCP billing project is required for production runtime, IAM, and sandboxes. |
| **External Service Account** | `GOOGLE_APPLICATION_CREDENTIALS=/path/to/key.json` | Not needed on Agent Runtime, Cloud Run, or GKE (Workload Identity / runtime SA / Agent Identity provides credentials automatically). Never commit key files or `.env`. |

### Baseline GCP Setup (APIs & Minimum Roles)
- **Required APIs:** `aiplatform.googleapis.com`, `cloudbuild.googleapis.com`, `secretmanager.googleapis.com`, `run.googleapis.com`, `artifactregistry.googleapis.com` (plus `telemetry.googleapis.com` for multi-cloud OTel anomaly export). Enabling APIs requires `roles/serviceusage.serviceUsageAdmin`.
- **Developer / Deployer Roles:** `roles/aiplatform.user` (minimum to use/deploy Agent Runtime & sandboxes) and `roles/iam.serviceAccountUser` (to attach a custom SA).
- **Agent Runtime Identities:**
  - **Agent Identity (Recommended):** Per-agent principal with default `roles/aiplatform.agentDefaultAccess` (logging + model calls) and `roles/aiplatform.agentContextEditor` (own sessions, memories, sandboxes).
  - **Reasoning Engine Service Agent:** `service-PROJECT_NUMBER@gcp-sa-aiplatform-re.iam.gserviceaccount.com` (`roles/aiplatform.reasoningEngineServiceAgent`). Pre-provision before granting AR/Secret Manager roles via:
    ```bash
    gcloud beta services identity create --service=aiplatform.googleapis.com --project=PROJECT_ID
    ```
  - **Agent Platform Service Agent:** `service-PROJECT_NUMBER@gcp-sa-aiplatform.iam.gserviceaccount.com` (used for CMEK, cross-project AR/GCS, and cross-project SA token creation).

---

## 3. Core Agent Definitions: `LlmAgent`, `App`, `AdkApp` & Models

### Standard Production `LlmAgent` + `App` Pattern

```python
from google.adk.agents import LlmAgent  # Alias: from google.adk.agents import Agent
from google.adk.apps import App, ResumabilityConfig
from google.adk.agents.context_cache_config import ContextCacheConfig
from google.adk.apps.app import EventsCompactionConfig
from google.adk.apps.llm_event_summarizer import LlmEventSummarizer
from google.adk.models import Gemini
from google.genai import types

root_agent = LlmAgent(
    name="coding_agent",
    model=Gemini(
        model="gemini-2.5-flash",  # Explicit versioned ID for regional endpoints!
        retry_options=types.HttpRetryOptions(initial_delay=1, attempts=2),
        # Optional: override GOOGLE_CLOUD_LOCATION for this agent only:
        # client_kwargs={"location": "global"},
    ),
    description="Autonomous coding assistant that inspects, edits, and tests code.",
    instruction="""You are a coding agent. Current repo: {repo_name}.
Inspect files before editing and verify changes with tests.""",
    tools=[...],
    sub_agents=[],
    generate_content_config=types.GenerateContentConfig(
        temperature=0.2,
        max_output_tokens=4096,
    ),
    before_agent_callback=init_state,  # Populate {repo_name} before turn 1
    output_key="last_response",        # Optional: saves final text/dict into session state
    include_contents="default",        # 'default' or 'none'
)

# CRITICAL: App.name MUST match the basename of the agent directory (e.g., "coding_agent" or "app")!
app = App(
    name="coding_agent",
    root_agent=root_agent,
    resumability_config=ResumabilityConfig(is_resumable=True),  # Enables HITL pause/resume
    context_cache_config=ContextCacheConfig(
        min_tokens=2048,
        ttl_seconds=1800,
        cache_intervals=10,
    ),
    events_compaction_config=EventsCompactionConfig(
        token_threshold=32000,   # Token-based compaction handles large tool outputs reliably
        event_retention_size=5,
        summarizer=LlmEventSummarizer(llm=Gemini(model="gemini-2.5-flash")),
    ),
)
```

### Critical Model & Configuration Rules
1. **Regional Endpoints vs. `gemini-flash-latest`:** The alias `gemini-flash-latest` may fail with 404 on regional Agent Platform endpoints (such as `asia-southeast1`). Always pass an explicit versioned Gemini model ID (verify available models in your `GOOGLE_CLOUD_LOCATION` via `genai.Client(vertexai=True, location=...).models.list()`).
2. **`App.name` Directory Match:** `App(name=...)` **must** equal the basename of the folder holding `agent.py` (e.g., `app` for `app/`, `coding_agent` for `coding_agent/`, `my_agent` for `src/my_agent/`). Any mismatch triggers `"Session not found"` during `adk` / `agents-cli eval` execution.
3. **`output_schema` with `tools` (Python Behavior & Reliability Best Practice):** In ADK Python, `output_schema` and `tools` **can** be combined on the same `LlmAgent` — tools stay available while the agent works, and `output_schema` applies only to the final response. Gemini models on Google Cloud (and `LiteLlm` providers supporting response schemas) accept both in a single request, whereas other models fall back to an injected `set_model_response` function tool that may behave unreliably. For cross-model reliability, prefer separating tool execution from structured formatting in a dedicated sub-agent or downstream `Workflow` node.
4. **429 `RESOURCE_EXHAUSTED` Client Retries:** Configure `types.HttpRetryOptions(initial_delay=1, attempts=2)` either on `Gemini(retry_options=...)` (adapter object) OR via `GenerateContentConfig(http_options=types.HttpOptions(retry_options=...))` (when `model` is a string).
5. **Gemini Interactions API (ADK Python 2.0+):** `Gemini(model=..., use_interactions_api=True)` chains turns server-side via `previous_interaction_id`, but **cannot** mix custom function tools with built-in tools like `google_search` unless wrapped via `GoogleSearchTool(bypass_multi_tools_limit=True)`.
6. **Non-Gemini Models via LiteLLM:** `from google.adk.models.lite_llm import LiteLlm` supports `LiteLlm(model="anthropic/claude-sonnet-4-20250514")`, `LiteLlm(model="openai/gpt-4o")`, and `LiteLlm(model="ollama_chat/llama3:instruct")`.
7. **Sub-Agent Factory Functions:** Never reuse the same module-level `Agent` instance across multiple parents (raises `"agent already has a parent"`). Define factory functions (`def create_reviewer() -> Agent: ...`) and **call** them (`sub_agents=[create_reviewer()]`, not `[create_reviewer]`).

### `AdkApp` Wrapper for Agent Runtime (`agentplatform.frameworks`)

```python
from agentplatform.frameworks import AdkApp

adk_app = AdkApp(
    app=app,  # Preferred: preserves App.name, ResumabilityConfig, and plugins (e.g., GlobalInstructionPlugin)
    # Alternative when wrapping a standalone agent (do not pass both `app=` and `agent=`/`plugins=`):
    # agent=root_agent,
    # Optional overrides (omit in prod to use managed Sessions & Memory Bank):
    # session_service_builder=lambda: InMemorySessionService(),
    # memory_service_builder=lambda: InMemoryMemoryService(),
)

# Local async smoke test (user_id max 128 chars!)
session = await adk_app.async_create_session(user_id="dev-user-1")
async for event in adk_app.async_stream_query(
    user_id="dev-user-1",
    session_id=session.id,
    message="List files in the workspace.",
):
    print(event)
```
- Locally, `AdkApp` defaults to `InMemorySessionService` and `InMemoryMemoryService`; on Agent Runtime it binds managed Sessions and Memory Bank automatically (`:streamQuery` dispatches to `streaming_agent_run_with_events`).
- Other async methods: `async_list_sessions(user_id=...)`, `async_get_session(user_id=..., session_id=...)`, `async_add_session_to_memory(session=...)`, `async_search_memory(user_id=..., query=...)`.

---

## 4. Tools, Tool Confirmation & MCP Integration

### Custom Function Tool Rules
- Write clear Google-style docstrings (sent to the LLM as the tool schema).
- Add strict type hints and **avoid default parameter values** on LLM-exposed parameters.
- Return a JSON-serializable `dict` (e.g., `{"status": "success", ...}`).
- Accept `tool_context: ToolContext` as an optional parameter for state, artifacts, memory, and HITL — **do not document `tool_context` in the docstring**.

```python
from google.adk.tools import FunctionTool, ToolContext

async def run_linter(target_path: str, tool_context: ToolContext) -> dict:
    """Runs lint checks on a relative file path inside the workspace.

    Args:
        target_path: Workspace-relative path to lint.

    Returns:
        dict with status and lint findings.
    """
    tool_context.state["temp:last_lint_target"] = target_path
    return {"status": "success", "findings": []}

# Confirmation gate (requires ResumabilityConfig(is_resumable=True) on App)
safe_delete = FunctionTool(delete_branch, require_confirmation=True)
conditional_deploy = FunctionTool(
    trigger_release,
    require_confirmation=lambda env, **kwargs: env == "prod",
)
```

### Built-In Tool & MCP Gotchas
- **`load_web_page` Import Precision:** Use `from google.adk.tools.load_web_page import load_web_page` (the tool instance), NOT `from google.adk.tools import load_web_page` (the module).
- **`google_search` + FunctionTools Conflict:** `google_search` is model-internal grounding; mixing it directly with custom `FunctionTool`s disables Automatic Function Calling (AFC). Isolate search in a sub-agent or use `GoogleSearchTool(bypass_multi_tools_limit=True)` (Interactions API).
- **MCP Tools (`McpToolset`, requires `mcp` extra):**
  - Local dev: `StdioConnectionParams(server_params=StdioServerParameters(command="npx", args=[...]))` — paths MUST be absolute, and agent definition MUST be synchronous for deployment.
  - Remote HTTP MCP (e.g., authenticated Cloud Run): use `StreamableHTTPConnectionParams(url=f"{URL}/mcp")` with `header_provider=lambda ctx: {"Authorization": f"Bearer {fetch_id_token(Request(), URL)}"}` (ID tokens expire in ~1h, so never pass a static `headers` dict; audience is the service root URL, not `/mcp`).

---

## 5. Callbacks, Plugins, State Prefixes & Artifacts

### Exact Callback Signatures (Invoked by Keyword!)

Parameter names **must match verbatim** because ADK dispatches callbacks by keyword argument:

```python
from google.adk.agents.callback_context import CallbackContext
from google.adk.models.llm_request import LlmRequest
from google.adk.models.llm_response import LlmResponse
from google.adk.tools import BaseTool, ToolContext
from google.genai import types

async def before_agent_callback(callback_context: CallbackContext) -> types.Content | None:
    callback_context.state.setdefault("repo_name", "workspace")
    return None  # Return Content to short-circuit agent execution

async def after_agent_callback(callback_context: CallbackContext) -> types.Content | None:
    return None  # Return Content to replace final agent output

async def before_model_callback(
    callback_context: CallbackContext, llm_request: LlmRequest
) -> LlmResponse | None:
    return None  # Return LlmResponse to skip LLM call (input guardrail)

async def after_model_callback(
    callback_context: CallbackContext, llm_response: LlmResponse
) -> LlmResponse | None:
    return None  # Return modified LlmResponse (output guardrail)

async def before_tool_callback(
    tool: BaseTool, args: dict, tool_context: ToolContext
) -> dict | None:
    return None  # Return dict to skip tool execution and return synthetic result

async def after_tool_callback(
    tool: BaseTool, args: dict, tool_context: ToolContext, tool_response: dict
) -> dict | None:
    return None  # Return modified dict to sanitize/truncate tool output
```

### Runner-Wide Plugins (`BasePlugin`)
- Register cross-cutting hooks once via `App(name=..., root_agent=..., plugins=[MyPlugin()])`. **Plugins run BEFORE agent-level callbacks** and cover all sub-agents automatically.
- Built-in plugins: `ReflectAndRetryToolPlugin`, `BigQueryAgentAnalyticsPlugin`, `ContextFilterPlugin`, `GlobalInstructionPlugin`, `SaveFilesAsArtifactsPlugin`, `LoggingPlugin`, `DebugLoggingPlugin`, `MultimodalToolResultsPlugin`.
- Additional plugin hooks beyond callbacks: `on_model_error_callback`, `on_tool_error_callback`, `on_user_message_callback`, `before/after_run_callback`, `on_event_callback`.

### Session State Prefixes & Session Rewind

| Prefix | Scope & Persistence | Example |
|---|---|---|
| *(none)* | Current session only | `state["current_branch"] = "fix/auth"` |
| `user:` | Persists across all sessions for the same `user_id` | `state["user:coding_style"] = "ruff-strict"` |
| `app:` | Shared globally across all users of the app | `state["app:max_patch_lines"] = 500` |
| `temp:` | Current invocation only (discarded after turn) | `state["temp:raw_diff"] = diff_str` |

- **Session Rewind (Undo / Debug):** `await runner.rewind_async(user_id=uid, session_id=sid, rewind_before_invocation_id=inv_id)` restores session-scoped state and artifacts to before `inv_id`; `user:` and `app:` state are unaffected.

### Artifacts (Binary / Large File Storage)

Use `InMemoryArtifactService()` locally or `GcsArtifactService(bucket_name="...")` in production to persist generated diffs, test reports, or binary outputs without bloating LLM context:

```python
from google.adk.artifacts import GcsArtifactService, InMemoryArtifactService
from google.adk.runners import Runner
from google.genai import types

runner = Runner(
    app=app,
    session_service=session_service,
    artifact_service=InMemoryArtifactService(),  # Prod: GcsArtifactService(bucket_name="my-bucket")
)

async def save_patch_artifact(patch_bytes: bytes, tool_context: ToolContext) -> dict:
    part = types.Part(inline_data=types.Blob(mime_type="text/x-diff", data=patch_bytes))
    version = await tool_context.save_artifact("latest.patch", part)     # Session-scoped
    await tool_context.save_artifact("user:baseline.patch", part)        # User-scoped across sessions
    loaded = await tool_context.load_artifact("latest.patch", version=version)
    names = await tool_context.list_artifacts()
    return {"status": "saved", "version": version, "artifacts": names, "bytes": len(loaded.inline_data.data)}
```

---

## 6. ADK 2.0 Graph Workflows & Native Design Contract

### Minimal Graph-Based Coding Loop (`google-adk >= 2.0.0`, Python `3.11+`)

Use `Workflow` for deterministic edit-verify-fix pipelines, parallel `JoinNode` fan-out, and resumable `RequestInput` HITL pauses. For full graph/dynamic patterns and multi-agent architectures, see `references/graph-and-dynamic-workflows.md` and `references/agent-architectures-and-workflows.md`:

```python
from google.adk import Context, Event, Workflow
from google.adk.agents import LlmAgent
from google.adk.workflow import DEFAULT_ROUTE, NodeTimeoutError, RetryConfig, node

planner = LlmAgent(
    name="planner",
    model="gemini-2.5-flash",
    # `output_schema` is OPTIONAL in a Workflow: without it, an LlmAgent passes its text `str`
    # output as `node_input` to downstream FunctionNodes (add Pydantic schemas when typed I/O helps).
    instruction="Propose a concise patch plan for the requested code change.",
)

@node(
    retry_config=RetryConfig(
        max_attempts=3,
        initial_delay=1.0,
        exceptions=[TimeoutError, NodeTimeoutError],
    ),
    timeout=30.0,
)
def verify_tests(ctx: Context, node_input: str, fix_attempts: int = 0):
    # Track workflow loop iterations in session state (NOT `ctx.attempt_count`, which is
    # RetryConfig's per-node retry counter and resets to 1 after pauses or restarts).
    passed = bool(ctx.state.get("tests_passed", False))
    if passed:
        return Event(output=node_input, route="pass")
    if fix_attempts < 3:
        return Event(output=node_input, route="retry", state={"fix_attempts": fix_attempts + 1})
    return Event(output=node_input, route="escalate")

def finish_node(node_input: str):
    # Use `Event(message=...)` for user-facing output; emit at most ONE `Event(output=...)` per node.
    return Event(message=f"Verified plan:\n{node_input}", output=node_input)

def fallback_node(node_input: str):
    return Event(message=f"Needs human review:\n{node_input}", output=node_input)

coding_workflow = Workflow(
    name="edit_verify_workflow",
    edges=[
        ("START", planner, verify_tests),
        # Routed edges MUST use a routing dict `(source, {key: target, ...})` or explicit
        # `Edge(from_node=..., to_node=..., route=...)` — NEVER a 3-tuple with a string route!
        (
            verify_tests,
            {
                "retry": planner,
                "pass": finish_node,
                DEFAULT_ROUTE: fallback_node,
            },
        ),
    ],
    max_concurrency=4,
    timeout=300.0,
)
```

### Key ADK 2.0 Workflow & Collaboration Summary
- **Nodes, Data Flow & Rendering:** Place `LlmAgent` (defaults to `single_turn` in graphs; `chat` allowed only directly after `"START"`), `@node`/`FunctionNode`, `BaseTool`, `JoinNode`, and nested `Workflow`s directly in `edges`. Function parameter injection binds `ctx` -> `Context`, `node_input` -> predecessor output, and other params -> `ctx.state[name]`. Emit strictly **one** `Event(output=...)` per Python node and use `Event(message="...")` for user-facing progress/responses (see `references/graph-and-dynamic-workflows.md`).
- **Routing, Loops & Fan-In:** Routed edges use dict maps `(router, {"K": target, DEFAULT_ROUTE: fallback})` or explicit `Edge(from_node=..., to_node=..., route=...)`. Graph cycles need >=1 routed edge and are **not** auto-bounded (enforce explicit state counters or use a Dynamic `@node(rerun_on_resume=True)` loop). Merge parallel branches with `JoinNode` so at most one terminal node emits output (avoids `ValueError`).
- **HITL (`RequestInput`) & Checkpointing:** Leaf HITL nodes default to `rerun_on_resume=False` (handoff: the user's reply flows directly to the successor node), while dynamic orchestrators calling `await ctx.run_node(...)` must set `@node(rerun_on_resume=True)` to replay completed child checkpoints on resume (see `references/graph-and-dynamic-workflows.md`).
- **Collaborative Subagent Modes:** Attach `mode="single_turn"` or leaf-only `mode="task"` on subagents (never on the root agent; `mode="task"` is disabled inside Python v2.0.0 graph `Workflow`s). ADK auto-injects delegation tools **named directly after each subagent**, and `mode="task"` subagents return to the parent via `finish_task` (see `references/agent-architectures-and-workflows.md`).

### ADK 2.0 Native Design Contract

Follow these positive architectural invariants across all ADK Python 2.0+ agents and workflows:

| Contract Area | Native ADK 2.0 Rule | Why It Matters |
|---|---|---|
| **Lifecycle Callbacks & Plugins** | Implement cross-cutting telemetry, guardrails, and state initialization via typed lifecycle callbacks (`BeforeAgentCallback`, `AfterAgentCallback`, `before/after_model_callback`, `before/after_tool_callback`) or `BasePlugin` subclasses on `App`. | Keeps instrumentation and state hooks integrated natively with the ADK 2.0 Workflow Graph engine across all nodes and sub-agents. |
| **Explicit Event Yielding** | Emit node outputs, user-facing messages, routes, and state deltas exclusively by yielding `Event(...)` (e.g., `yield Event(output=..., message=..., route=..., state=...)`). | Allows the ADK 2.0 runtime to persist, stream, checkpoint, and route events deterministically across graph and dynamic execution. |
| **Exception Propagation (`RetryConfig`)** | Let transient errors propagate out of `@node` functions so `RetryConfig` handles exponential backoff and retries, and **never** swallow `BaseException`. | Broad `except Exception:` disables automatic retries; catching `BaseException` without re-raising traps `NodeInterruptedError` and breaks HITL pauses. |
| **Global Instructions (`GlobalInstructionPlugin`)** | Register shared system-level rules once via `GlobalInstructionPlugin(global_instruction=...)` on `App(plugins=[...])`. | Applies consistent behavior across coordinators, isolated sub-agent branches, and workflow graph agents without duplicating prompt text. |
| **Resumability (`ResumabilityConfig`)** | Enable `App(..., resumability_config=ResumabilityConfig(is_resumable=True))` whenever using `RequestInput` HITL pauses, `FunctionTool(require_confirmation=True)`, `ExecuteBashTool`, or dynamic `@node(rerun_on_resume=True)` orchestrators. | Guarantees durable pause/resume checkpoints across human approvals and replica restarts. |
| **`Event` Schema (`node_info` & `output`)** | Ensure custom `BaseSessionService` storage schemas and strict JSON validators permit ADK 2.0 `Event` fields `node_info` and `output` (standard JSON-blob stores accept them automatically). | Rigid SQL/NoSQL tables or `additionalProperties: false` validators reject workflow events unless both fields are supported. |
| **Workflow-First Orchestration** | Model deterministic pipelines, fan-out/`JoinNode` barriers, conditional branches, and bounded loops with ADK 2.0 Graph `Workflow(edges=[...])` and Dynamic `@node(rerun_on_resume=True)` (`ctx.run_node`). | Provides typed `Event(output=...)` passing, automatic child checkpointing, per-node `RetryConfig`/timeouts, and deterministic HITL pauses (note: make `Workflow` the root graph rather than an `LlmAgent` `sub_agent`). |

---

## 7. Common Error Modes & Verification Checklist

| Error / Symptom | Root Cause | Exact Fix |
|---|---|---|
| `Session not found` in eval or runtime | `App(name=...)` does not match agent directory name, OR `google-cloud-aiplatform <= 1.128.0` after Gemini publish | Set `App(name="<folder_basename>", root_agent=root_agent)` and upgrade `google-cloud-aiplatform`. |
| `404 Model not found` on regional endpoint (e.g., `asia-southeast1`) | Using `gemini-flash-latest` alias on a regional endpoint | Use explicit versioned ID (e.g., `gemini-2.5-flash`) verified via `genai.Client(...).models.list()`. |
| `KeyError: 'var_name'` on first turn | `{var_name}` in `instruction` is missing from `session.state` | Initialize all template variables in `before_agent_callback` with `callback_context.state.setdefault(...)`. |
| Unreliable tool calls or malformed JSON after adding `output_schema` | Model falls back to injected `set_model_response` tool when combining `output_schema` + `tools` (non-Gemini-on-GCP / unsupported `LiteLlm` providers) | Use Gemini on Google Cloud (supports both in one request) or separate tool execution (`LlmAgent` without `output_schema`) from structured formatting (`LlmAgent` with `output_schema` in a sub-agent or downstream `Workflow` node). |
| `ValidationError: Input should be a valid dictionary or instance of BaseAgent` | Passed sub-agent factory function reference instead of calling it | Call factory: `sub_agents=[create_sub_agent()]`. |
| `adk web` shows no agents | Launched `adk web` from *inside* `my_agent/` instead of its parent folder | `cd ..` to parent directory and run `adk web --port 8000` (dev only; never production). |

### Local Verification Steps
1. **Verify model availability in your target region:**
   ```bash
   uv run --with google-genai python -c "
   from google import genai
   client = genai.Client(vertexai=True, location='asia-southeast1')
   print([m.name for m in client.models.list() if 'gemini' in m.name][:10])
   "
   ```
2. **Programmatic smoke test (`InMemoryRunner` — tests wiring, not LLM prose):**
   ```python
   import pytest
   from google.adk.runners import InMemoryRunner
   from google.genai import types

   @pytest.mark.asyncio
   async def test_agent_wiring(app):
       runner = InMemoryRunner(app=app)
       session = await runner.session_service.create_session(app_name=app.name, user_id="test")
       events = [
           e async for e in runner.run_async(
               user_id="test",
               session_id=session.id,
               new_message=types.Content(role="user", parts=[types.Part.from_text(text="List files")]),
           )
       ]
       assert any(e.is_final_response() for e in events)
   ```
3. **Interactive verification:** Run `adk run my_agent` or `adk web --port 8000` from the parent folder of `my_agent/` (for scaffolded projects, prefer `agents-cli run` / `agents-cli playground`).
