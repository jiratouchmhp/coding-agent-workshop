# ADK Agent Architectures, Collaboration & Multi-Agent Patterns

Source-verified reference covering all 8 official ADK Simple Agent, Service Registration, Collaborative Team, Template Deprecation, Routing, and Multi-Agent Workflow Pattern guides (`adk.dev/agents/*`, `adk.dev/workflows/*`, and `adk.dev/2.0/`).

> **Model ID Note:** Upstream `adk.dev` snippets often use `"gemini-flash-latest"`, which can return `404` on regional Agent Platform endpoints (such as `us-central1`). The Python examples below use explicit versioned IDs (e.g., `"gemini-2.5-flash"`) for regional compatibility.

---

## 1. Single `LlmAgent` & When to Evolve into a Workflow

*Source: `https://adk.dev/agents/` (Supported: Python, TypeScript, Go, Java)*

A standalone **`Agent`** (alias for **`LlmAgent`**) combines an AI model, task instructions, and optional tools. In ADK, **any application with more than one agent or executable Node is a workflow**. Start with a single `LlmAgent` and evolve into a multi-agent or graph workflow when you hit one of **four concrete triggers**:

| Evolution Trigger | Failure Symptom in a Single Monolithic Agent | Recommended ADK 2.0 Target |
|---|---|---|
| **1. Instruction-following degradation** | Long multi-step procedures are skipped, reordered, or completed with inconsistent quality/latency. | **Graph-based `Workflow`** (explicit nodes/edges) or **Collaborative Team** (focused specialist subagents). |
| **2. Context window limits** | Files, logs, search results, or history required for the full task exceed model context capacity. | **Isolated subagent branches** (`mode="single_turn"` / `mode="task"`), **Artifacts**, or **Agent Skills** (`SkillToolset`). |
| **3. Agent code modularity** | Prompt and tool sprawl hinder testing, ownership, or cross-project reuse. | Reusable **nested `Workflow`s**, subagent factory functions, or `AgentTool`-wrapped specialists. |
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
8. **Service registration (`v1.34.0+`):** Plug custom backends for sessions, artifacts, memory, and A2A task stores via `services.yaml` / `services.py`.

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

# 3. Recommended composition: add with mode="single_turn" to sub_agents (preferred over AgentTool)
coordinator = LlmAgent(
    name="research_coordinator",
    model="gemini-2.5-flash",
    instruction="Use managed_search_agent and managed_code_execution_agent as needed.",
    sub_agents=[managed_search_agent, managed_code_agent],
)
```

### Verified `ManagedAgent` Hard Limitations

1. **Agent Platform `global`-Only:** Regional endpoints (e.g. `us-central1`) raise an error.
2. **Server-Side Tools Only (`NotImplementedError`):** Client-executed Python callables **and** raw `types.Tool(mcp_servers=...)` configs are unsupported and raise `NotImplementedError`. Declare server-side remote MCP servers exclusively with `google.adk.tools.RemoteMcpServer`.
3. **Streaming Only (`stream=True`):** Background-polling execution and strictly non-streaming connections are not yet fully supported.
4. **Backend Behavioral Variance:** Gemini API and Agent Platform backends exhibit slight behavioral differences — always test against the exact target backend.
5. **Preview Scope:** Pre-GA preview — choose `LlmAgent` + custom `BaseEnvironment` when you need custom Python tools, regional data residency, or production governance.

---

## 3. Service Registration (`services.yaml` & `services.py`)

*Source: `https://adk.dev/agents/service-registration/` (Supported: ADK Python **v1.34.0**)*

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
| **Template workflows** | `v0.1.0+` (**Deprecated** in Py/TS/Go/Kt) | `SequentialAgent`, `ParallelAgent`, `LoopAgent` | Legacy 1.x code only — migrate new code to Graph or Dynamic workflows |
| **Agent Routing (`RoutedAgent`)** | TypeScript `v1.0.0` (**Experimental**) | Code router fn selecting 1 agent + failover | TS failover, planning-mode toggle, classifier complexity routing |

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
    model="gemini-2.5-flash",
    mode="single_turn",          # No user interaction; can run in parallel; auto-returns result
    description="Checks weather for a destination.",
    tools=[get_weather],
)

flight_agent = Agent(
    name="flight_booker",
    model="gemini-2.5-flash",
    mode="task",                 # May ask user clarifying questions; auto-returns via finish_task
    description="Searches and books flights.",
    input_schema=FlightInput,
    output_schema=FlightResult,
    tools=[search_flights, book_flight],
)

root_agent = Agent(
    name="travel_planner",       # NEVER set `mode` on the root agent!
    model="gemini-2.5-flash",
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

---

## 5. Template Workflow Agents: Official Deprecation & 2.0 Migration

*Sources: `https://adk.dev/agents/workflow-agents/`, `https://adk.dev/workflows/patterns/`, `https://adk.dev/2.0/`*

`SequentialAgent`, `ParallelAgent`, and `LoopAgent` are **deprecated / superseded** in ADK Python, TypeScript, Go, and Kotlin:
- In **Python and TypeScript 2.0**, constructing any of these three classes emits a deprecation warning (once per class per process in TS 2.0), and the classes are scheduled for removal in a future release.
- **Important 2.0 Interop Caveat:** A `Workflow` **cannot yet be used as an `LlmAgent` `sub_agent`**. If you need a deterministic multi-step pipeline alongside conversational triage, make `Workflow` the root graph (with a `chat` agent immediately after `"START"` if needed) or keep delegation inside a dynamic orchestrator / `AgentTool` boundary.

### Legacy Template -> ADK 2.0 Migration Matrix

| Deprecated Template Class | Legacy Mechanism & Quirks | ADK 2.0 Replacement |
|---|---|---|
| **`SequentialAgent`** | Fixed `sub_agents=[a, b, c]`; shares `InvocationContext` & `temp:` state; communicates via `output_key`. | `Workflow(edges=[("START", a, b, c)])` passing typed `Event(output=...)` directly. |
| **`ParallelAgent`** (+ outer `SequentialAgent`) | Concurrent branches with isolated history but shared state; interleaves events non-deterministically without collecting a list. | `Workflow` fan-out edges into **`JoinNode`** -> gather node, or Dynamic **`asyncio.gather(*[ctx.run_node(..., use_sub_branch=True)])`**. |
| **`LoopAgent`** | Repeats `sub_agents`; **`max_iterations` defaults to `None` in Python** (infinite unless `EventActions(escalate=True)` or `exit_loop` fires). | Dynamic **`@node(rerun_on_resume=True)`** bounded `for`/`while` loop with `ctx.run_node(...)`, or a conditional graph back-edge with explicit exit route. |

---

## 6. Agent Routing: `RoutedAgent` (TS Experimental) & Python Equivalents

*Source: `https://adk.dev/agents/routing/` (Supported: **ADK TypeScript v1.0.0 Experimental ONLY**)*

`RoutedAgent` (sharing its core utility with `RoutedLlm`) lets a TypeScript router function choose **one** agent per invocation without an LLM transfer call.

### TypeScript `RoutedAgent` Contract & Failover Semantics

```typescript
import { BaseAgent, Gemini, InvocationContext, LlmAgent, RoutedAgent } from '@google/adk';

type AgentRouter = (
  agents: Readonly<Record<string, BaseAgent>>,
  context: InvocationContext,
  errorContext?: { failedKeys: ReadonlySet<string>; lastError: unknown },
) => Promise<string | undefined> | string | undefined;

// 1. Pre-event failover using errorContext.failedKeys
const failoverAgent = new RoutedAgent({
  name: 'failover_router',
  agents: { primary: primaryAgent, fallback: fallbackAgent }, // Or array (keyed by agent.name)
  router: (_agents, _ctx, errorContext) => {
    if (!errorContext) return 'primary';
    if (errorContext.failedKeys.has('primary')) return 'fallback';
    return undefined; // Stop routing and rethrow lastError
  },
});

// 2. Planning-mode toggle (read-only planner vs. read/write executor)
let planningMode = false;
const modeRouted = new RoutedAgent({
  name: 'coding_mode_router',
  agents: { basic: readWriteAgent, planning: readOnlyPlannerAgent },
  router: () => (planningMode ? 'planning' : 'basic'),
});

// 3. Async classifier complexity routing (simple vs. complex)
const classifierModel = new Gemini({ model: 'gemini-2.5-flash' });
const complexityRouted = new RoutedAgent({
  name: 'complexity_router',
  agents: { simple: simpleAgent, complex: complexAgent },
  router: async (_agents, context) => {
    const text = context.userContent?.parts?.[0]?.text || '';
    if (!text) return 'simple';
    let label = '';
    for await (const resp of classifierModel.generateContentAsync({
      contents: [{ role: 'user', parts: [{ text: `Classify as 'simple' or 'complex': ${text}` }] }],
      toolsDict: {},
      liveConnectConfig: {},
    })) {
      label += resp.content?.parts?.[0]?.text ?? '';
    }
    return label.toLowerCase().includes('complex') ? 'complex' : 'simple';
  },
});
```

**Five Strict Failover Rules in `RoutedAgent`:**
1. Initial call omits `errorContext`.
2. If the selected agent throws **before yielding any events**, the router is invoked again with `{ failedKeys, lastError }`.
3. If the selected agent throws **after yielding events**, failover does **not** happen — the error propagates directly because partial output was already emitted.
4. Returning a key already in `errorContext.failedKeys` propagates the error immediately.
5. Returning `undefined` halts routing and throws `lastError`.

### Exact Python ADK 2.0 Equivalents (No `RoutedAgent` in ADK Python)

In ADK Python, implement the exact same routing patterns with **Graph `Event(route=...)`** or **Dynamic `if`/`elif`**:

```python
from google.adk import Context, Event, Workflow
from google.adk.workflow import node

# Pattern A: Static Graph Planning-Mode / Complexity Router
def route_mode(ctx: Context, node_input: str):
    if ctx.state.get("planning_mode", False):
        return Event(route="planning", output=node_input)
    return Event(route="basic", output=node_input)

graph_router = Workflow(
    name="coding_mode_workflow",
    edges=[
        ("START", route_mode),
        (route_mode, {"planning": read_only_planner, "basic": read_write_coder}),
    ],
)

# Pattern B: Dynamic Workflow Async Complexity Router + Explicit Failover
@node(rerun_on_resume=True)
async def dynamic_router(ctx: Context, node_input: str) -> str:
    label = await ctx.run_node(classifier_agent, node_input)
    target = complex_agent if "complex" in str(label).lower() else simple_agent
    try:
        return await ctx.run_node(target, node_input)
    except RuntimeError:  # Narrow transient error only — NEVER catch BaseException!
        return await ctx.run_node(fallback_agent, node_input)
```

---

## 7. Seven Multi-Agent Workflow Patterns Mapped to ADK 2.0

*Source: `https://adk.dev/workflows/patterns/` (Python, TypeScript, Go, Java, Kotlin)*

The official patterns page demonstrates all 7 canonical patterns (some snippets still show legacy template classes for backward compatibility). Use this ADK 2.0 mapping for all new Python code:

| # | Pattern | Goal & Structure | ADK 2.0 Recommended Implementation |
|---|---|---|---|
| **1** | **Coordinator / Dispatcher** | Central `LlmAgent` routes incoming requests to specialist subagents. | Root `LlmAgent(sub_agents=[billing, support])` with subagent `mode="single_turn"` or `mode="task"` (auto-injected delegation tools), or explicit `AgentTool` in `tools=[...]`. |
| **2** | **Sequential Pipeline** | Fixed multi-step pipeline (`Validate -> Process -> Report`). | `Workflow(edges=[("START", validator, processor, reporter)])` passing `Event(output=...)` directly (replaces `SequentialAgent` + `output_key`). |
| **3** | **Parallel Fan-Out & Gather** | Run independent workers concurrently, then synthesize results. | `Workflow` fan-out edges (`("START", w1, join)`, `("START", w2, join)`, `(join, synthesizer)`) with **`JoinNode`**, or dynamic `asyncio.gather(..., use_sub_branch=True)` (replaces `ParallelAgent` + `SequentialAgent`). |
| **4** | **Hierarchical Task Decomposition** | Multi-level tree breaking complex goals into sub-tasks (`ReportWriter -> ResearchAssistant -> [WebSearch, Summarizer]`). | Wrap child specialists with `agent_tool.AgentTool(agent=...)` in `tools=[...]` (or `mode="single_turn"` subagents) so results return up each tier cleanly. |
| **5** | **Generate & Review (Generator-Critic)** | Separate generator (`DraftWriter`) and evaluator (`FactChecker`). | `Workflow(edges=[("START", draft_writer, fact_checker)])` using typed `output_schema`/`input_schema` (or add a router after `fact_checker` to branch on pass/fail). |
| **6** | **Iterative Refinement** | Repeat refine + check until quality passes or max rounds reached. | Dynamic `@node(rerun_on_resume=True)` bounded `for` loop calling `ctx.run_node(refiner)` + `ctx.run_node(checker)` (replaces deprecated `LoopAgent` + custom `_run_async_impl` `EventActions(escalate=True)`). |
| **7** | **Human-in-the-Loop (HITL)** | Pause for human oversight, approval, or structured input. | ADK has **no "Human Agent" type**. Use (a) Graph `RequestInput` nodes, (b) `FunctionTool(require_confirmation=True)` / `tool_context.request_confirmation()`, or (c) **TypeScript Policy-Based HITL** (`SecurityPlugin` + `BasePolicyEngine`). |

### Pattern 4 Snippet: Hierarchical Task Decomposition (`AgentTool`)

```python
from google.adk.agents import LlmAgent
from google.adk.tools import agent_tool

web_searcher = LlmAgent(name="WebSearch", model="gemini-2.5-flash", description="Performs web searches.")
summarizer = LlmAgent(name="Summarizer", model="gemini-2.5-flash", description="Summarizes text.")

research_assistant = LlmAgent(
    name="ResearchAssistant",
    model="gemini-2.5-flash",
    description="Finds and summarizes information on a topic.",
    tools=[agent_tool.AgentTool(agent=web_searcher), agent_tool.AgentTool(agent=summarizer)],
)

report_writer = LlmAgent(
    name="ReportWriter",
    model="gemini-2.5-flash",
    instruction="Write a report using ResearchAssistant to gather evidence.",
    tools=[agent_tool.AgentTool(agent=research_assistant)],
)
```

### Pattern 7 Contrast: TypeScript Policy-Based HITL (`SecurityPlugin` + `BasePolicyEngine`)

In **ADK TypeScript**, policy-based HITL is the **recommended** governance pattern (support in other ADK languages is planned for future releases):
1. Attach `new SecurityPlugin({ policyEngine: new CustomPolicyEngine() })` to `Runner` / `InMemoryRunner`.
2. Implement `BasePolicyEngine.evaluate(context: ToolCallPolicyContext): Promise<PolicyCheckResult>`.
3. Returning `{ outcome: PolicyOutcome.CONFIRM, reason: '...' }` causes `SecurityPlugin` to pause tool execution and emit a confirmation `FunctionCall` (discoverable via `getAskUserConfirmationFunctionCalls`).
4. Once the app sends back the user's `FunctionResponse`, `SecurityPlugin` resumes the original tool call.

---

## 8. Architecture Pitfalls ("Do This, Not That")

| Do This | Not That | Why (Doc-Verified) |
|---|---|---|
| Set `mode="single_turn"` or `mode="task"` **only** on subagents | Setting `mode=...` on the root coordinator agent | `mode` is strictly for subagents invoked by a coordinator parent. |
| Keep `mode="task"` subagents as **leaf** agents outside Python v2.0.0 graph `Workflow`s | Giving a `task` agent `sub_agents` or using `mode="task"` inside a Python v2.0.0 `Workflow` | `task` agents cannot have subagents, and `task` mode is disabled in Python v2.0.0 graph workflows. |
| Compose `ManagedAgent` via `mode="single_turn"` in `sub_agents` + `RemoteMcpServer` | Passing local Python functions or `types.Tool(mcp_servers=...)` to `ManagedAgent` | Client-side tools and raw `types.Tool.mcp_servers` raise `NotImplementedError`; Agent Platform backend is `global`-only. |
| Place `services.yaml`/`services.py` in the agent dir for `adk run` and the agents root dir for `adk web`/`adk api_server` | Placing `services.yaml` in the wrong folder or expecting YAML to override Python | Wrong folder prevents auto-discovery; `services.yaml` loads first and `services.py` always takes precedence on colliding schemes. |
| Migrate `SequentialAgent`/`ParallelAgent`/`LoopAgent` to `Workflow` graphs or dynamic `ctx.run_node` | Building new Python/TS 2.0 orchestrations on template workflow agents | Template workflows are deprecated in Python/TS/Go/Kotlin and scheduled for removal; note `Workflow` cannot yet be an `LlmAgent` `sub_agent`. |
| Use Graph `Event(route=...)` or Dynamic `if`/`elif` in Python for runtime agent selection | Trying to import `RoutedAgent` in ADK Python | `RoutedAgent` is TypeScript v1.0.0 Experimental only; failover only triggers if failure occurs before any event is yielded. |
