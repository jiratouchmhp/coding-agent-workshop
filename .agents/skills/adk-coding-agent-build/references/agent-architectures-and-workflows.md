# ADK Agent Architectures, Collaboration & Multi-Agent Patterns

Source-verified reference covering ADK 2.0+ Simple Agents, `ManagedAgent`, Service Registration, Collaborative Agent Teams, Deterministic & Dynamic Routing, and Multi-Agent Workflow Patterns (`adk.dev/agents/*`, `adk.dev/workflows/*`, `adk.dev/graphs/*`, and `adk.dev/2.0/`).

> **Frontier Gemini 4 Model Note (Replacing Retired `gemini-2.5-flash` — Oct 20, 2026):** Default to **`gemini-4-hydrogen`** (fast coding/tool-calling) and **`gemini-4-neon`** (planning, architecture & review) routed via `Gemini(model=..., client_kwargs={auth_key: True, "project": ..., "location": "global"})` (`MODEL_LOCATION=global`, `google-genai>=2.34.0`), or use **`gemini-4-argon`** (`location="asia-southeast1"`) for strict Singapore regional residency. Short string model IDs in snippets below assume `GOOGLE_CLOUD_LOCATION=global` or wrapping with `build_gemini_model(...)`.

---

## 1. Single `LlmAgent` & When to Evolve into a Workflow

*Source: `https://adk.dev/agents/` (Supported: Python, TypeScript, Go, Java)*

A standalone **`Agent`** (alias for **`LlmAgent`**) combines an AI model, task instructions, and optional tools. In ADK, **any application with more than one agent or executable Node is a workflow**. Start with a single `LlmAgent` and evolve into a multi-agent or graph workflow when you hit one of **four concrete triggers**:

| Evolution Trigger | Failure Symptom in a Single Monolithic Agent | Recommended ADK 2.0 Target |
|---|---|---|
| **1. Instruction-following degradation** | Long multi-step procedures are skipped, reordered, or completed with inconsistent quality/latency. | **Graph-based `Workflow`** (explicit nodes/edges) or **Collaborative Team** (focused specialist subagents). |
| **2. Context window limits** | Files, logs, search results, or history required for the full task exceed model context capacity. | **Isolated subagent branches** (`mode="single_turn"` / `mode="task"`), **Artifacts**, or **Agent Skills** (`SkillToolset`). |
| **3. Agent code modularity** | Prompt and tool sprawl hinder testing, ownership, or cross-project reuse. | Reusable **nested `Workflow`s**, subagent factory functions, or `mode="single_turn"` specialist subagents. |
| **4. Mixing deterministic & non-deterministic steps** | Prompting an LLM to enforce strict branching, retries, linting, or approval gates is brittle. | **Graph-based `Workflow`** or **Dynamic workflow** (`@node` + `ctx.run_node`) interleaving Python code with `LlmAgent` nodes. |

### Eight Official ADK Agent Feature Extensions

Extend a single agent *before* adding orchestration overhead whenever the bottleneck is capability rather than control flow:
1. **AI models:** Swap Gemini or third-party models (`LiteLlm`).
2. **Pre-built tools & integrations:** MCP tools, web search, databases, environment toolsets.
3. **Custom tools:** Precision task-specific Python functions (`FunctionTool`).
4. **Artifacts:** Persistent files, diffs, and binary outputs outside conversation context.
5. **Agent Skills (`agentskills.io`):** Progressive-disclosure instructions and scripts loaded within context budgets.
6. **Plugins:** Runner-wide cross-cutting behaviors (`BasePlugin`, `GlobalInstructionPlugin`).
7. **Callbacks:** Lifecycle hooks (`before/after_agent`, `before/after_model`, `before/after_tool`) for telemetry, guardrails, and state initialization.
8. **Service registration (ADK Python 2.0+):** Plug custom backends for sessions, artifacts, memory, and A2A task stores via `services.yaml` / `services.py`.

---

## 2. `ManagedAgent` — First-Party Server-Hosted Agents (Preview)

*Source: `https://adk.dev/agents/managed-agents/` (Supported: ADK Python **v2.4.0 Preview**)*

`ManagedAgent` wraps Google's first-party server-hosted agents (such as Antigravity) backed by the Managed Agents API. Because `ManagedAgent` implements `BaseAgent`, you can run it standalone or compose it inside an ADK flow without provisioning sandboxes or declaring client-side functions.

### Architecture: Data Plane vs. Control Plane & Backends

- **Data Plane Only:** `ManagedAgent` does **not** create or register a managed agent resource. It connects to an *existing* backend agent (`agent_id`) over the **Interactions API** (data plane) and sends `tools` / `environment` as per-interaction overrides. Resource creation remains on the **Agents API** (control plane).
- **Local Session vs. Remote State:** `ManagedAgent` keeps almost no local state. ADK session events persist **only two IDs**: `interaction_id` and sandbox `environment_id`. On every subsequent turn, `ManagedAgent` scans prior session events to recover both IDs and sends them to the backend to continue the remote interaction and sandbox. ADK **never re-sends prior turns** — the remote interaction history is the source of truth.

| Backend | Authentication | Location Constraint | `agent_id` |
|---|---|---|---|
| **Gemini API** | `GEMINI_API_KEY` env var | Gemini API endpoint | Custom created agent or out-of-the-box ID (e.g. `antigravity-preview-05-2026`) |
| **Agent Platform** | Google Cloud ADC (`gcloud auth application-default login`) | **`global` ONLY** (`ManagedAgent` enforces `global`; regional endpoints raise an error) | Custom created agent or project-available out-of-the-box ID |

### Exact Usage: Built-In Tools, `RemoteMcpServer` & `mode='single_turn'` Composition

```python
import os
from google.adk.agents import LlmAgent, ManagedAgent
from google.adk.tools import RemoteMcpServer, google_search
from google.genai import types

AGENT_ID = os.environ.get("MANAGED_AGENT_ID", "antigravity-preview-05-2026")

# 1. Standalone server-hosted web search agent
managed_search_agent = ManagedAgent(
    name="managed_search_agent",
    description="Answers questions needing fresh web information.",
    agent_id=AGENT_ID,
    environment={"type": "remote"},
    tools=[google_search],
    mode="single_turn",  # Recommended: exposes as an inline tool on a parent LlmAgent
)

# 2. Server-side code execution + server-side RemoteMcpServer (NOT client-side McpToolset)
managed_code_agent = ManagedAgent(
    name="managed_code_execution_agent",
    description="Solves computational tasks in a server-hosted sandbox.",
    agent_id=AGENT_ID,
    environment={"type": "remote"},
    tools=[
        types.Tool(code_execution=types.ToolCodeExecution()),
        # RemoteMcpServer(name="...", url="https://..."),  # Supported server-side MCP spec
    ],
    mode="single_turn",
)

# 3. Recommended composition: add with mode="single_turn" to sub_agents
coordinator = LlmAgent(
    name="research_coordinator",
    model="gemini-4-hydrogen",
    instruction="Use managed_search_agent and managed_code_execution_agent as needed.",
    sub_agents=[managed_search_agent, managed_code_agent],
)
```

### Verified `ManagedAgent` Hard Limitations

1. **Agent Platform `global`-Only:** Regional endpoints (e.g., `asia-southeast1` or `us-central1`) raise an error.
2. **Server-Side Tools Only (`NotImplementedError`):** Client-executed Python callables **and** raw `types.Tool(mcp_servers=...)` configs are unsupported and raise `NotImplementedError`. Declare server-side remote MCP servers exclusively with `google.adk.tools.RemoteMcpServer`.
3. **Streaming Only (`stream=True`):** Background-polling execution and strictly non-streaming connections are not yet fully supported.
4. **Backend Behavioral Variance:** Gemini API and Agent Platform backends exhibit slight behavioral differences — always test against the exact target backend.
5. **Preview Scope:** Pre-GA preview — choose `LlmAgent` + custom `BaseEnvironment` when you need custom Python tools, regional data residency, or production governance.

---

## 3. Service Registration (`services.yaml` & `services.py`)

*Source: `https://adk.dev/agents/service-registration/` (Supported: **ADK Python 2.0+**)*

Register custom runtime backends for **four service types** — `session`, `artifact`, `memory`, and `task_store` (Agent2Agent / A2A task stores) — automatically discovered by `adk run`, `adk web`, and `adk api_server`.

### Option A: Declarative `services.yaml` (or `services.yml`)

Best for services instantiated via a simple `MyService(uri="...")` constructor:

```yaml
services:
  - scheme: mysession
    type: session
    class: my_custom_package.modules.MyCustomSessionService
  - scheme: myartifact
    type: artifact
    class: my_custom_package.storage.MyCustomArtifactService
  - scheme: mymemory
    type: memory
    class: my_custom_package.modules.MyCustomMemoryService
  - scheme: mytaskstore
    type: task_store
    class: my_custom_package.tasks.MyCustomTaskStore
```

- `scheme`: URI scheme triggering the custom service (e.g., `mysession://...`).
- `type`: One of `session`, `artifact`, `memory`, or `task_store`.
- `class`: Fully qualified Python class path.

### Option B: Programmatic `services.py`

Use when factories need custom initialization, secrets lookup, or client configuration:

```python
from google.adk.cli.service_registry import get_service_registry
from my_custom_package.memory import MyCustomMemoryService
from my_custom_package.modules import MyCustomSessionService
from my_custom_package.storage import MyCustomArtifactService

def my_session_factory(uri: str, **kwargs):
    return MyCustomSessionService(uri=uri, **kwargs)

def my_artifact_factory(uri: str, **kwargs):
    return MyCustomArtifactService(uri=uri, **kwargs)

def my_memory_factory(uri: str, **kwargs):
    return MyCustomMemoryService(uri=uri, **kwargs)

registry = get_service_registry()
registry.register_session_service("mysession", my_session_factory)
registry.register_artifact_service("myartifact", my_artifact_factory)
registry.register_memory_service("mymemory", my_memory_factory)
```

### Discovery Locations, Loading Order & Precedence

| CLI Command | Where ADK Searches for `services.yaml` / `services.py` |
|---|---|
| **`adk run`** | Inside the **agent directory** itself (e.g., `coding_agent/services.yaml`). |
| **`adk web`** / **`adk api_server`** | Inside the **agents root directory** passed to the command (parent directory of agent folders). |

- **Loading Order:** ADK always loads `services.yaml` (or `services.yml`) **first**, then `services.py`.
- **Precedence:** If the same `scheme` is registered in both files, **`services.py` wins**.

---

## 4. Multi-Agent Workflows & Collaborative Agent Teams

*Sources: `https://adk.dev/workflows/` & `https://adk.dev/workflows/collaboration/` (Collaborative modes: ADK Python **v2.0.0**, ADK Go **v2.0.0**)*

### ADK Multi-Agent Architecture Selector

| Architecture | ADK Version | Control Mechanism | Best Fit |
|---|---|---|---|
| **Graph-based workflows** | Python/TS/Go `v2.0.0+` (Kotlin `v1.5.0` Exp.) | Declarative `Workflow(edges=[...])` | Deterministic pipelines, conditional branches, fan-out/`JoinNode`, retries, HITL |
| **Dynamic workflows** | Python/TS/Go `v2.0.0+` | `@node(rerun_on_resume=True)` + `ctx.run_node` | Bounded edit-test-fix loops, runtime-sized parallel fan-out, complex conditionals |
| **Collaborative workflows** | Python/Go `v2.0.0+` | Coordinator `LlmAgent` + subagent `mode` | Open-ended tasks where an LLM coordinator delegates dynamically to specialists |
| **`agy` Headless CLI Harness (`agy_harness`)** | ADK 2.0 + `agy` CLI | Outer ADK `Workflow` + Inner `AgyHeadlessHarness` (`auto\|local\|sandbox`) + independent `pytest`/`ruff` gates | Production coding harness with `--conversation` multi-round continuity, 4-tier exit codes (`0/1/2/3`), and `gemini-4-neon` review |

### Collaborative Agent Teams (`mode` + Auto-Injected Delegation Tools)

When a coordinator `Agent` declares `sub_agents=[...]`, ADK automatically generates a delegation tool named after each subagent (`weather_checker`, `flight_booker`) and enforces the subagent's `mode`:

```python
from pydantic import BaseModel
from google.adk import Agent
from google.adk.apps import App
from google.adk.plugins.global_instruction_plugin import GlobalInstructionPlugin

class FlightInput(BaseModel):
    origin: str
    destination: str

class FlightResult(BaseModel):
    confirmation_code: str

weather_agent = Agent(
    name="weather_checker",
    model="gemini-4-hydrogen",
    mode="single_turn",          # No user interaction; can run in parallel; auto-returns result
    description="Checks weather for a destination.",
    tools=[get_weather],
)

flight_agent = Agent(
    name="flight_booker",
    model="gemini-4-hydrogen",
    mode="task",                 # May ask user clarifying questions; auto-returns via finish_task
    description="Searches and books flights.",
    input_schema=FlightInput,
    output_schema=FlightResult,
    tools=[search_flights, book_flight],
)

root_agent = Agent(
    name="travel_planner",       # NEVER set `mode` on the root agent!
    model="gemini-4-hydrogen",
    instruction="Coordinate travel planning using weather_checker and flight_booker.",
    sub_agents=[weather_agent, flight_agent],
    # Auto-injects delegation tools named `weather_checker` and `flight_booker`.
)

# Apply consistent cross-agent rules via GlobalInstructionPlugin on App
app = App(
    name="travel_planner",
    root_agent=root_agent,
    plugins=[GlobalInstructionPlugin(global_instruction="Always verify dates in ISO-8601 format.")],
)
```

*(Go v2.0.0 equivalent: `llmagent.Config{ Mode: llmagent.ModeSingleTurn | llmagent.ModeTask, SubAgents: [...] }` and `GlobalInstruction` on the agent; TypeScript/Java also provide `GlobalInstructionPlugin` on the app/runner.)*

### Subagent Collaboration Mode Matrix

| Dimension | `chat` (default) | `task` | `single_turn` |
|---|---|---|---|
| **Human-in-the-Loop** | Full interaction | Clarification questions only | Disallowed |
| **User interaction** | User chats freely with subagent | Subagent asks user as needed | None |
| **Control flow** | Subagent retains control until manual handoff | Subagent retains control until task finishes | Returns immediately after task |
| **Parallel execution** | Not supported | Not supported | **Supported** (multiple run concurrently) |
| **Return to parent** | Manual (`transfer_to_agent`) | Automatic (via `finish_task`) | Automatic (with result) |
| **Session context** | Shared conversation history | **Isolated session branch** | **Isolated session branch** |

### Transfer Behavior, Context Isolation & Hard Limitations

- **Reusable Across Invocation Contexts:**
  - *Invoked as a workflow node:* completing a `task` or `single_turn` agent advances automatically to the next node in the graph.
  - *Invoked via transfer from an `LlmAgent`:* completing a `task` (via `finish_task`) or `single_turn` agent returns control automatically to the originating `LlmAgent`.
- **Isolated Session Branches:** Every `task` and `single_turn` agent runs in its own isolated session branch. Parallel peers cannot see each other's events; once all parallel branches finish, the parent receives the collected results.
- **Hard Rules & Limitations:**
  1. **NEVER set `mode` on a root agent** — `mode` is exclusively for subagents invoked by a coordinator parent.
  2. **`task` mode agents MUST be leaf agents** — they cannot declare `sub_agents`.
  3. **`task` mode is DISABLED in graph-based workflows in ADK Python v2.0.0** — use `single_turn` inside Python v2.0.0 `Workflow` graphs until `task` mode is re-enabled in a future release.
  4. **`Workflow` as Root Graph:** A `Workflow` cannot yet be attached as an `LlmAgent` `sub_agent`. To combine conversational triage with deterministic multi-step pipelines, make `Workflow` the root graph (with a `chat`-mode `LlmAgent` immediately after `"START"` if needed) or orchestrate specialist agents from a Dynamic `@node(rerun_on_resume=True)` workflow.

---

## 5. Python ADK 2.0 Deterministic & Dynamic Routing

*Sources: `https://adk.dev/graphs/routes/`, `https://adk.dev/graphs/dynamic/`, `https://adk.dev/graphs/retry/` (Supported: **ADK Python 2.0+**)*

In ADK Python 2.0+, express deterministic dispatch, complexity-based agent selection, and resilient failover natively with **Graph conditional `Event(route=...)`**, **Dynamic `@node` `if`/`elif` routing**, and **`RetryConfig` + narrow try/fallback** — keeping routing logic type-checked, testable, and checkpoint-safe.

### Pattern A: Graph Conditional Routing (`Event(route=...)` + `DEFAULT_ROUTE`)

Use a deterministic router function node with a routing dictionary `(router_node, {key: target, DEFAULT_ROUTE: fallback})` for mode toggles (such as read-only planning vs. read/write editing) or multi-branch dispatch without an extra LLM transfer call:

```python
from google.adk import Context, Event, Workflow
from google.adk.workflow import DEFAULT_ROUTE

def route_coding_mode(ctx: Context, node_input: str):
    mode = ctx.state.get("coding_mode", "basic")
    if mode == "planning":
        return Event(route="planning", output=node_input)
    if mode == "basic":
        return Event(route="basic", output=node_input)
    return Event(route="unknown", output=node_input)

coding_mode_workflow = Workflow(
    name="coding_mode_workflow",
    edges=[
        ("START", route_coding_mode),
        (
            route_coding_mode,
            {
                "planning": read_only_planner_agent,
                "basic": read_write_coder_agent,
                DEFAULT_ROUTE: read_only_planner_agent,
            },
        ),
    ],
)
```

### Pattern B: Dynamic `@node` `if`/`elif` Routing & Resilient Failover

Use `@node(rerun_on_resume=True)` when routing depends on an async classifier call or requires ordered failover after per-node `RetryConfig` retries are exhausted:

```python
from google.adk import Context, Event, Workflow
from google.adk.workflow import NodeTimeoutError, RetryConfig, node

class BackendUnavailableError(RuntimeError):
    """Transient model or tool backend failure."""

@node(
    retry_config=RetryConfig(
        max_attempts=3,
        initial_delay=1.0,
        exceptions=[BackendUnavailableError, NodeTimeoutError],
    ),
    timeout=20.0,
)
async def call_primary_specialist(ctx: Context, node_input: str) -> str:
    return await ctx.run_node(primary_complex_agent, node_input)

@node(rerun_on_resume=True)
async def dynamic_router_with_failover(ctx: Context, node_input: str):
    label = str(await ctx.run_node(classifier_agent, node_input)).strip().lower()
    if "complex" in label:
        try:
            result = await ctx.run_node(call_primary_specialist, node_input)
        except (BackendUnavailableError, NodeTimeoutError):
            # Catch ONLY narrow expected failures — NEVER catch BaseException (breaks HITL pauses)!
            yield Event(message="Primary specialist unavailable; switching to fallback agent.")
            result = await ctx.run_node(fallback_agent, node_input)
    elif "docs" in label:
        result = await ctx.run_node(docs_agent, node_input)
    else:
        result = await ctx.run_node(simple_agent, node_input)
    yield Event(output=result)

routed_workflow = Workflow(
    name="dynamic_routed_workflow",
    edges=[("START", dynamic_router_with_failover)],
)
```

**Three ADK 2.0 Routing & Failover Rules:**
1. **Always Include `DEFAULT_ROUTE` on Partial Route Maps:** Prevents unmatched keys from silently stalling a conditional graph branch.
2. **Layer `RetryConfig` Before Fallback:** Attach `RetryConfig(..., exceptions=[..., NodeTimeoutError])` to the primary node first so brief transient glitches recover before invoking the fallback agent.
3. **Narrow `except` Clauses Only:** Never catch `BaseException` (which traps `NodeInterruptedError` and breaks HITL pauses) and avoid catching broad `Exception` inside nodes that rely on `RetryConfig`.

---

## 6. Seven Multi-Agent Workflow Patterns in ADK 2.0

*Source: `https://adk.dev/workflows/patterns/` (Python, TypeScript, Go, Java, Kotlin)*

Use these native ADK 2.0 implementations for all 7 canonical multi-agent patterns in Python:

| # | Pattern | Goal & Structure | ADK 2.0 Recommended Implementation |
|---|---|---|---|
| **1** | **Coordinator / Dispatcher** | Central `LlmAgent` routes incoming requests to specialist subagents. | Root `LlmAgent(sub_agents=[billing, support])` with subagent `mode="single_turn"` or `mode="task"` (ADK auto-injects delegation tools named after each subagent). |
| **2** | **Sequential Pipeline** | Fixed multi-step pipeline (`Validate -> Process -> Report`). | `Workflow(edges=[("START", validator, processor, reporter)])` passing typed `Event(output=...)` directly between nodes. |
| **3** | **Parallel Fan-Out & Gather** | Run independent workers concurrently, then synthesize results. | `Workflow` fan-out edges (`("START", w1, join)`, `("START", w2, join)`, `(join, synthesizer)`) with **`JoinNode`**, or dynamic `asyncio.gather(..., use_sub_branch=True)`. |
| **4** | **Hierarchical Task Decomposition** | Multi-level tree breaking complex goals into sub-tasks (`ReportWriter -> ResearchAssistant -> [WebSearch, Summarizer]`). | Multi-level `LlmAgent(sub_agents=[...])` hierarchy with `mode="single_turn"` on intermediate and leaf specialists so isolated results return cleanly up each tier, combined with nested `Workflow` composition for deterministic sub-pipelines. |
| **5** | **Generate & Review (Generator-Critic)** | Separate generator (`DraftWriter`) and evaluator (`FactChecker`). | `Workflow(edges=[("START", draft_writer, fact_checker)])` using typed `output_schema`/`input_schema` (or add a router after `fact_checker` to branch on pass/fail). |
| **6** | **Iterative Refinement** | Repeat refine + check until quality passes or max rounds reached. | Dynamic `@node(rerun_on_resume=True)` bounded `for`/`while` loop calling `ctx.run_node(refiner)` + `ctx.run_node(checker)`, or a conditional graph back-edge with an explicit state attempt cap. |
| **7** | **Human-in-the-Loop (HITL)** | Pause for human oversight, approval, or structured input. | ADK has **no "Human Agent" type**. Use (a) Graph `RequestInput` nodes, (b) `FunctionTool(require_confirmation=True)` / `tool_context.request_confirmation()`, or (c) **TypeScript Policy-Based HITL** (`SecurityPlugin` + `BasePolicyEngine`). |

### Pattern 4 Snippet: Hierarchical Task Decomposition (ADK 2.0 Multi-Level `sub_agents` + Nested `Workflow`)

```python
from google.adk import Workflow
from google.adk.agents import LlmAgent

# 1. Dynamic multi-level collaborative hierarchy (never set `mode` on root_agent!)
web_searcher = LlmAgent(
    name="web_search",
    model="gemini-4-hydrogen",
    mode="single_turn",  # Isolated branch; can run concurrently with sibling specialists
    description="Searches documentation and returns raw findings.",
)
summarizer = LlmAgent(
    name="summarizer",
    model="gemini-4-hydrogen",
    mode="single_turn",
    description="Condenses evidence into structured bullet points.",
)

research_assistant = LlmAgent(
    name="research_assistant",
    model="gemini-4-hydrogen",
    mode="single_turn",  # Auto-returns synthesized findings up to report_writer
    description="Coordinates web_search and summarizer for a research sub-task.",
    instruction="Gather evidence with web_search and condense it with summarizer.",
    sub_agents=[web_searcher, summarizer],
)

report_writer = LlmAgent(
    name="report_writer",
    model="gemini-4-hydrogen",
    instruction="Write the final report using research_assistant to collect evidence.",
    sub_agents=[research_assistant],
)

# 2. Deterministic sub-pipeline composition via nested Workflow (use fresh agent instances per parent)
def build_deterministic_report_workflow() -> Workflow:
    search_node = LlmAgent(name="search_step", model="gemini-4-hydrogen", instruction="Collect source facts.")
    summarize_node = LlmAgent(name="summarize_step", model="gemini-4-hydrogen", instruction="Summarize source facts.")
    writer_node = LlmAgent(name="write_step", model="gemini-4-hydrogen", instruction="Draft final report from summary.")

    research_subworkflow = Workflow(
        name="research_subworkflow",
        edges=[("START", search_node, summarize_node)],
    )
    return Workflow(
        name="report_workflow",
        edges=[("START", research_subworkflow, writer_node)],
    )
```

### Pattern 7 Contrast: TypeScript Policy-Based HITL (`SecurityPlugin` + `BasePolicyEngine`)

In **ADK TypeScript**, policy-based HITL is the **recommended** governance pattern (support in other ADK languages is planned for future releases):
1. Attach `new SecurityPlugin({ policyEngine: new CustomPolicyEngine() })` to `Runner` / `InMemoryRunner`.
2. Implement `BasePolicyEngine.evaluate(context: ToolCallPolicyContext): Promise<PolicyCheckResult>`.
3. Returning `{ outcome: PolicyOutcome.CONFIRM, reason: '...' }` causes `SecurityPlugin` to pause tool execution and emit a confirmation `FunctionCall` (discoverable via `getAskUserConfirmationFunctionCalls`).
4. Once the app sends back the user's `FunctionResponse`, `SecurityPlugin` resumes the original tool call.

---

## 7. Architecture Pitfalls ("Do This, Not That")

| Do This | Not That | Why (Doc-Verified) |
|---|---|---|
| Set `mode="single_turn"` or `mode="task"` **only** on subagents | Setting `mode=...` on the root coordinator agent | `mode` is strictly for subagents invoked by a coordinator parent. |
| Keep `mode="task"` subagents as **leaf** agents outside Python v2.0.0 graph `Workflow`s | Giving a `task` agent `sub_agents` or using `mode="task"` inside a Python v2.0.0 `Workflow` | `task` agents cannot have subagents, and `task` mode is disabled in Python v2.0.0 graph workflows. |
| Compose `ManagedAgent` via `mode="single_turn"` in `sub_agents` + `RemoteMcpServer` | Passing local Python functions or `types.Tool(mcp_servers=...)` to `ManagedAgent` | Client-side tools and raw `types.Tool.mcp_servers` raise `NotImplementedError`; Agent Platform backend is `global`-only. |
| Place `services.yaml`/`services.py` in the agent dir for `adk run` and the agents root dir for `adk web`/`adk api_server` | Placing `services.yaml` in the wrong folder or expecting YAML to override Python | Wrong folder prevents auto-discovery; `services.yaml` loads first and `services.py` always takes precedence on colliding schemes. |
| Make `Workflow` the root graph (and nest child `Workflow`s in `edges`) | Passing a `Workflow` inside `LlmAgent.sub_agents` | A `Workflow` cannot yet be attached as an `LlmAgent` `sub_agent`; place a `chat` agent immediately after `"START"` or orchestrate from a Dynamic `@node(rerun_on_resume=True)`. |
| Use Graph `Event(route=...)` (+ `DEFAULT_ROUTE`) or Dynamic `@node` `if`/`elif` + narrow exception failover | Catching `BaseException` in a failover router or omitting `DEFAULT_ROUTE` on partial route maps | Catching `BaseException` traps `NodeInterruptedError` and breaks HITL pauses; omitting `DEFAULT_ROUTE` leaves unmatched keys unhandled. |
