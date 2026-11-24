# ADK 2.0 Graph & Dynamic Workflows Reference

Source-verified reference covering all 6 official ADK 2.0 Graph & Dynamic Workflow guides (`adk.dev/graphs/`, `routes`, `data-handling`, `human-input`, `retry`, `dynamic`) plus ADK 2.0 compatibility notes (`adk.dev/2.0/`).

> **Frontier Gemini 4 Model Note (Replacing Retired `gemini-2.5-flash` — Oct 20, 2026):** Default to **`gemini-4-hydrogen`** (fast coding/tool-calling) and **`gemini-4-neon`** (planning/review) routed via `Gemini(model=..., client_kwargs={auth_key: True, "project": ..., "location": "global"})` (`MODEL_LOCATION=global`, `google-genai>=2.34.0`), or use **`gemini-4-argon`** (`location="asia-southeast1"`) for strict Singapore regional residency. Short string model IDs below assume `GOOGLE_CLOUD_LOCATION=global` or wrapping with `build_gemini_model(...)`.

---

## 1. Graph-Based Workflows Overview

*Source: `https://adk.dev/graphs/` (Supported: Python v2.0.0 GA, TypeScript v2.0.0 GA, Go v2.0.0 GA, Kotlin v1.5.0 Experimental)*

Graph-based workflows compose non-deterministic AI agents and deterministic Python functions, tools, human-input pauses, and nested workflows into an explicit node-and-edge topology via **`Workflow(name=..., edges=[...])`**.

### Minimal End-to-End Python Graph (`Agent` + Function + `input_schema` + `Event`)

```python
from pydantic import BaseModel
from google.adk import Agent, Event, Workflow

city_generator = Agent(
    name="city_generator",
    model="gemini-4-hydrogen",
    instruction="Return the name of a random city. Return only the name.",
)

class CityTime(BaseModel):
    time_info: str
    city: str

def lookup_time(node_input: str) -> CityTime:
    """Deterministic Python function node (auto-wrapped as FunctionNode)."""
    return CityTime(time_info="10:10 AM", city=node_input.strip())

city_reporter = Agent(
    name="city_reporter",
    model="gemini-4-hydrogen",
    input_schema=CityTime,
    instruction="You receive a CityTime with time_info and city fields. Reply with one sentence stating the time in that city.",
)

def finish_message(node_input: str):
    return Event(message=f"{node_input}\nWORKFLOW COMPLETED.")

root_agent = Workflow(
    name="root_agent",
    edges=[("START", city_generator, lookup_time, city_reporter, finish_message)],
)
```

### Node Types, `LlmAgent` Mode Rules & Known Limitations

- **Supported Graph Nodes:** `LlmAgent`/`Agent`, Python callables (`FunctionNode` / `@node`), ADK `BaseTool`, human-input (`RequestInput`) nodes, `JoinNode`, and nested `Workflow` instances.
- **`LlmAgent` Default Mode in Graphs:** An `LlmAgent` placed inside a `Workflow` defaults to **`single_turn`** mode.
- **`chat` Mode Placement Rule:** A `chat` mode `LlmAgent` is **ONLY allowed directly after `"START"`**, because it consumes conversational history rather than a predecessor node's `node_input`.
- **Global Instructions:** Apply consistent instructions across all graph agents via `GlobalInstructionPlugin` on `App` (Python/TypeScript/Java) or `GlobalInstruction` on the agent (Go).
- **Third-Party Integrations Limitation:** Some third-party ADK integrations may not yet be compatible with graph-based workflows — test each integration inside a `Workflow` before production rollout.

### Cross-Language Graph API Quick Map

| Concept | Python (`v2.0.0`) | TypeScript (`v2.0.0`) | Go (`v2.0.0`) | Kotlin (`v1.5.0` Exp.) |
|---|---|---|---|---|
| **Graph container** | `Workflow(name, edges=[...])` | `new Workflow({ name, edges })` | `workflowagent.New(Config{ Edges })` | `workflow("...") { ... }` (`@OptIn(ExperimentalWorkflowApi)`) |
| **Function node** | Plain fn / `@node` / `FunctionNode` | `node(fn, { name, ... })` / `new FunctionNode(...)` | `workflow.NewFunctionNode` / `NewEmittingFunctionNode` | `node<In, Out>("...") { ctx, in -> ... }` |
| **Agent node** | Direct `Agent` in `edges` | Direct `LlmAgent` or `node(agent, { inputSchema })` | `workflow.NewAgentNode` / `NewAgentNodeTyped[In, Out]` | Direct `LlmAgent` in DSL |
| **Routing edges** | `(router, {"K": n, ...})` | `[router, { K: n, [DEFAULT_ROUTE]: fb }]` | `workflow.StringRoute` / `IntRoute` / `BoolRoute` / `MultiRoute` / `Default` | `router.route { "K" then n; otherwise(fb) }` |
| **Fan-in barrier** | `JoinNode(name=...)` | `new JoinNode({ name })` | `workflow.NewJoinNode("...")` + `EdgeBuilder.AddFanOut/AddFanIn` | `JoinNode("...")` + `.joinTo(...)` |

---

## 2. Routes: Sequences, Branching, Fan-Out/`JoinNode`, Nesting & Back-Edges

*Source: `https://adk.dev/graphs/routes/` (Supported: Python v2.0.0, TypeScript v2.0.0, Go v2.0.0, Kotlin v1.5.0)*

### 2.1 Sequences & Multi-Route Conditional Dispatch

A router node returns `Event(route="KEY")` (single branch) or `Event(route=["KEY_1", "KEY_2"])` (fans out to **every** matching branch). Use `DEFAULT_ROUTE` (or `"__DEFAULT__"`) as the fallback edge when no branch matches.

```python
from google.adk import Agent, Event, Workflow
from google.adk.workflow import DEFAULT_ROUTE  # Fallback route sentinel

classifier = Agent(
    name="classify_issue",
    model="gemini-4-hydrogen",
    instruction='Classify into comma-separated labels from "BUG", "DOCS", "TESTS". Labels only.',
)

def route_categories(node_input: str):
    routes = [r.strip().upper() for r in node_input.split(",") if r.strip()]
    return Event(route=routes, output=node_input)  # One Event can emit both `route` and `output`

def handle_bug(node_input: str): return Event(message=f"Triaging bug: {node_input}")
def handle_docs(node_input: str): return Event(message=f"Updating docs: {node_input}")
def handle_unknown(node_input: str): return Event(message=f"Unclassified: {node_input}")

root_agent = Workflow(
    name="routing_workflow",
    edges=[
        ("START", classifier, route_categories),
        (route_categories, {"BUG": handle_bug, "DOCS": handle_docs, DEFAULT_ROUTE: handle_unknown}),
    ],
)
```

*(Route values support strings, integers, and booleans across TS, Go, and Kotlin; Go matches via `StringRoute`, `IntRoute`, `MultiRoute[int]`, `BoolRoute`, and `workflow.Default`.)*

### 2.2 Parallel Fan-Out & `JoinNode` Fan-In

Listing multiple edges from `"START"` (or any shared predecessor) fans out concurrently. **`JoinNode`** waits until **all** predecessor branches finish, then passes a `dict` keyed by predecessor node name to its successor:

```python
from google.adk import Workflow
from google.adk.workflow import JoinNode

join_checks = JoinNode(name="join_checks")
def run_ruff(node_input: str) -> dict: return {"tool": "ruff", "ok": True}
def run_pytest(node_input: str) -> dict: return {"tool": "pytest", "ok": True}
def summarize(node_input: dict) -> str:
    return f"ruff={node_input['run_ruff']['ok']}, pytest={node_input['run_pytest']['ok']}"

root_agent = Workflow(
    name="parallel_checks",
    edges=[
        ("START", run_ruff, join_checks),
        ("START", run_pytest, join_checks),
        (join_checks, summarize),
    ],
)
```

> **CRITICAL `JoinNode` Rule:** Every node feeding a `JoinNode` **MUST produce an output** of its own, and any fallible branch should attach a `RetryConfig`. If a predecessor finishes without output, `JoinNode` has no value for that branch and the failure surfaces confusingly downstream, far from the broken predecessor.

### 2.3 Nested `Workflow`s & the Single Terminal Output `ValueError` Rule

Place child `Workflow` instances directly inside a parent `Workflow`'s `edges`:

```python
root_agent = Workflow(
    name="parent_workflow",
    edges=[
        ("START", triage_node, router),
        (router, {"PATH_B": workflow_b, "PATH_C": workflow_c}),
    ],
)
```

- **Event Bubbling:** As an inner `Workflow` executes each internal node, its events bubble up to the parent workflow for full traceability; when the inner workflow finishes, the parent extracts the final leaf node's output as the nested workflow's output.
- **CRITICAL `ValueError` Rule:** Every `Workflow` must have **at most ONE terminal node that produces output**. If two or more terminal nodes emit output (for example, the unmerged ends of two parallel branches), the workflow fails with **`ValueError`**. Always merge parallel branches through a `JoinNode` so the graph ends in a single terminal output.

### 2.4 Conditional Back-Edge Loops & Unbounded Cycle Warning

Express graph loops by routing from a downstream router back to an earlier node (the engine re-activates the target node with a fresh lifecycle each iteration):

```python
def review_router(ctx, node_input: dict):
    attempts = ctx.state.get("loop_attempts", 0) + 1
    if node_input.get("passed") or attempts >= 3:
        return Event(route="DONE", output=node_input, state={"loop_attempts": attempts})
    return Event(route="RETRY", output=node_input, state={"loop_attempts": attempts})

looping_workflow = Workflow(
    name="looping_workflow",
    edges=[
        ("START", edit_node, test_node, review_router),
        (review_router, {"RETRY": edit_node, "DONE": final_node}),
    ],
)
```

- **Mandatory Routed Edge:** Every cycle in `edges` **must contain at least one conditional (routed) edge** — an unconditional cycle is rejected at `Workflow` construction time. Always include `DEFAULT_ROUTE` (`from google.adk.workflow import DEFAULT_ROUTE`) in partial routing maps.
- **CRITICAL Unbounded Cycle Warning:** ADK does **NOT** automatically bound graph cycles. You must enforce an explicit termination check (like `attempts >= 3` above) OR use a **Dynamic workflow** (Section 6) where your Python `for`/`while` loop controls the iteration cap directly.
- **Reset Per-Turn Loop Counters for Multi-Turn Sessions:** Session state persists across user turns in the same session. Always reset per-turn counters (e.g., `Event(output=..., state={"loop_attempts": 0, "fix_attempts": 0})`) in your terminal node so the next user message in the same session gets a fresh retry budget. (For workspace test checks using `pytest`, treat exit code `5` — *no tests collected* — as non-fatal when linting/testing new repositories without tests yet.)

---

## 3. Data Handling, State Scopes, Schemas & Instruction Templating

*Source: `https://adk.dev/graphs/data-handling/` (Supported: Python v2.0.0, TypeScript v2.0.0, Go v2.0.0)*

### 3.1 Python `Event` Fields & the Single `Event(output=...)` Rule

| `Event` Parameter (Python) | Purpose | Downstream Visibility |
|---|---|---|
| **`output`** | Structured or text data passed to the successor node (`node_input`). Plain `return val` auto-wraps into `Event(output=val)`; empty `return`/`yield` passes `None`. | Delivered as next node's `node_input`. |
| **`message`** | User-facing progress or response text (TS: `content`; Go: `Event.Content` via `emit`). | Rendered to user; **NOT** passed to next node's `node_input`. |
| **`route`** | Single route key or `list` of route keys for conditional edge dispatch (independent of `output`). | Evaluated by graph router edges. |
| **`state`** | Key-value dict of state deltas committed with the event (`Event(state={"attempts": 1})`). | Persisted in `session.state` across downstream nodes. |

```python
from google.adk import Context, Event

async def emit_progress_and_data(node_input: str):
    # Multiple yields are allowed ONLY if at most ONE carries `output=...`!
    yield Event(message="Running static analysis...")
    yield Event(state={"last_target": node_input})
    yield Event(output={"target": node_input, "status": "ok"})
```

> **CRITICAL Single-Output Runtime Error (Python vs. TypeScript/Go):**
> - **Python:** A node may `yield` multiple events (for `message` or `state`), but **strictly ONE `Event(output=...)` per node execution** is permitted. Yielding two or more events with `output` raises a **runtime error**!
> - **TypeScript contrast:** Emitting multiple `output` events does *not* throw — each overwrites the previous one so downstream receives only the last value (still use `content` for progress).
> - **Go contrast:** `FunctionNode` returns one typed `(T, error)` value; `EmittingFunctionNode` emits intermediate events via `emit` and returns `nil, nil` to suppress the automatic terminal event.

### 3.2 Session State Scopes & Lightweight State Rule

| Prefix | Go Constant | Scope & Lifetime |
|---|---|---|
| `app:` | `session.KeyPrefixApp` | Shared across all users and sessions for the app |
| `user:` | `session.KeyPrefixUser` | Tied to one `user_id`, shared across all their sessions |
| `temp:` | `session.KeyPrefixTemp` | Discarded when the current invocation ends |
| *(none)* | — | Persists for the lifetime of the current session |

- **Lightweight Key-Value Store Only:** Never store large files, diffs, or binary payloads in `state` — use **ADK Artifacts** or external DB tools instead.
- **Prefer `Event(output=...)` Over State** for direct predecessor-to-successor data flow. Reserve `state` for values that must outlive a step, cross a `JoinNode` + `RequestInput` HITL boundary, be read by tools/callbacks, or populate `{key}` instruction templates.
- **ADK 2.0 `State` API Contract (`google.adk.sessions.state.State`):** `ctx.state` is a `State` object (not a plain `dict`). It supports `.get()`, `.setdefault()`, `.update()`, `.to_dict()`, `.has_delta()`, `in`, `[]`, and iteration, but does **NOT** implement `.pop()`, `.keys()`, `.items()`, `.values()`, `__delitem__`, or `__len__` (calling `ctx.state.pop(...)` raises `AttributeError`). Clear keys via `ctx.state[key] = None` or `Event(state={key: ""})`.

### 3.3 Pydantic Schemas & Instruction Templating (Critical Python vs. TS Contrast!)

```python
from datetime import date
from pydantic import BaseModel
from google.adk import Agent, Event, Workflow

class PatchRequest(BaseModel):
    file_path: str
    target_date: date

class PatchSummary(BaseModel):
    changed_lines: int
    summary: str

def build_request(node_input: str):
    return Event(
        output=PatchRequest(file_path=node_input.strip(), target_date=date(2026, 3, 15)),
        state={"active_file": node_input.strip()},  # Required ONLY if using {active_file} in instruction
    )

analyzer = Agent(
    name="patch_analyzer",
    model="gemini-4-hydrogen",
    input_schema=PatchRequest,
    output_schema=PatchSummary,
    # Python `{key}` reads SESSION STATE (not node_input!).
    # `input_schema` delivers PatchRequest as structured input; reference its fields in prose.
    instruction=(
        "Active file from state: {active_file}. "
        "You receive a PatchRequest with file_path and target_date fields; return a PatchSummary."
    ),
)
```

| Language | How `{...}` Instruction Templates Resolve | How Node Schemas Are Attached |
|---|---|---|
| **Python** | **`{key}` reads ONLY session state, NEVER `node_input`!** Writing `{PatchRequest.file_path}` is left verbatim in the prompt. Either reference `input_schema` fields in prose, or write to state via `output_key`/`Event(state=...)` first. | Pydantic `BaseModel` on `Agent(input_schema=..., output_schema=...)`. |
| **TypeScript** | Supports **`{Class.field}`** (reads from this node's input; `Class.` is documentation only) and **`<Class.field from source_node>`** (disambiguates upstream node outputs), separate from `{state_key}`. | Zod or genai `Schema`; `LlmAgent.inputSchema` applies only when exposed as a tool — inside a graph, set `node(agent, { inputSchema })`. |
| **Go** | `AgentNode` receives predecessor struct inline as user content without `{key}` syntax (`{key}` is for session state). | `workflow.NewAgentNodeTyped[In, Out]` auto-reflects Go structs into `*jsonschema.Schema`. |

---

## 4. Human Input (HITL): Graph `RequestInput` vs. Tool Confirmation

*Source: `https://adk.dev/graphs/human-input/` (Supported: Python v2.0.0, TypeScript v2.0.0, Go v2.0.0)*

### 4.1 Graph-Level Deterministic HITL (`RequestInput`)

Graph HITL nodes pause execution deterministically **without invoking an LLM**:

```python
from pydantic import BaseModel
from google.adk import Workflow
from google.adk.events import RequestInput
from google.adk.workflow import node

class PatchPlan(BaseModel):
    files: list[str]
    risk: str

class ApprovalReply(BaseModel):
    approved: bool
    comment: str

# Leaf HITL node: rerun_on_resume=False (default handoff) -> user reply flows directly to apply_patch!
@node(rerun_on_resume=False)
async def request_patch_approval(node_input: PatchPlan):
    yield RequestInput(
        message=f"Approve edits to {node_input.files} (risk: {node_input.risk})?",
        payload=node_input,               # Structured context for client UI rendering
        response_schema=ApprovalReply,    # Expected reply structure (sent to client)
    )

def apply_patch(node_input):
    return f"Received approval payload: {node_input}"

root_agent = Workflow(
    name="gated_patch_workflow",
    edges=[("START", plan_node, request_patch_approval, apply_patch)],
)
```

**Four Essential Graph HITL Rules:**
1. **`response_schema` Does NOT Reformat Human Replies:** The user's reply **must already conform** to `response_schema`. For natural-language UX, either render a structured form in the client UI (in TS, the schema travels as `functionCall.args.response_schema`) OR place a downstream `LlmAgent` node after the pause to parse free-form text into the schema.
2. **`rerun_on_resume=False` vs. `rerun_on_resume=True`:**
   - **`False` (leaf default — handoff mode):** The interrupted node does **not** re-run on resume; the user's reply becomes its output and flows straight to the successor node.
   - **`True` (re-entry mode):** The node body re-runs from the top on resume. **Mandatory** for any dynamic orchestrator calling `ctx.run_node()` (so already-finished children replay from checkpoints) and in Go for nodes using `workflow.ResumeOrRequestInput`.
3. **Carrying Upstream Context Across `JoinNode` + `RequestInput` (`rerun_on_resume=False`):** Because handoff mode replaces the post-HITL node's `node_input` with the human's reply (discarding the pre-HITL summary payload from `node_input`), attach `output_key="coder_summary"` on your upstream `LlmAgent` and persist check findings in `Event(state={"latest_findings": ...})` before pausing. In the post-HITL terminal node, read the persisted summary/findings back from `ctx.state`, combine with the human reply (`node_input`), and reset per-turn loop counters in the terminal `Event(state={"fix_attempts": 0})`!
4. **Go Contrast:** Leaf handoff emits `workflow.NewRequestInputEvent(ctx, session.RequestInput{ InterruptID, Message, Payload, ResponseSchema })` and returns `workflow.ErrNodeInterrupted`. Re-entry sets `NodeConfig{ RerunOnResume: &true }` and calls `workflow.ResumeOrRequestInput(...)`.

### 4.2 LLM-Agent-Level Tool Confirmation (Separate Mechanism)

Use tool confirmation inside an `LlmAgent` when approval applies to a single tool invocation rather than a graph node:

```python
from google.adk.agents import Agent
from google.adk.tools import FunctionTool, ToolContext

def delete_branch(branch: str) -> str:
    """Deletes a git branch."""
    return f"Deleted {branch}"

def deploy_release(env: str, tool_context: ToolContext) -> str:
    """Deploys a release with a custom confirmation hint."""
    # CRITICAL: ADK only auto-rejects on `require_confirmation=True`.
    # Manual `request_confirmation()` MUST check BOTH `tool_confirmation` AND `.confirmed`!
    if not tool_context.tool_confirmation:
        tool_context.request_confirmation(hint=f"Approve deployment to {env}?")
        return "Waiting for approval."
    elif not tool_context.tool_confirmation.confirmed:
        return "Deployment rejected by user."
    return f"Deployed to {env}."

root_agent = Agent(
    name="release_agent",
    model="gemini-4-hydrogen",
    tools=[
        FunctionTool(delete_branch, require_confirmation=True),  # Static yes/no auto-gate
        deploy_release,                                           # Custom hint + explicit check
    ],
)
```

---

## 5. Node Retries & Per-Attempt Timeouts

*Source: `https://adk.dev/graphs/retry/` (GA: Python v2.0.0, Go v2.0.0; Experimental: TypeScript v2.0.0, Java v1.14.0, Kotlin v1.2.0)*

Attach `RetryConfig` and `timeout` directly to individual fallible nodes (prefer per-node policies over wrapping an entire nested workflow so healthy sibling nodes are not re-executed):

```python
from google.adk import Context, Event, Workflow
from google.adk.workflow import NodeTimeoutError, RetryConfig, node

class RegistryUnavailableError(Exception):
    """Transient remote failure."""

@node(
    retry_config=RetryConfig(
        max_attempts=3,         # 1 original attempt + 2 retries (0 or 1 disables retries)
        initial_delay=1.0,      # Seconds before first retry
        max_delay=60.0,         # Upper cap per retry wait
        backoff_factor=2.0,     # Exponential multiplier (1s, 2s, 4s, 8s...)
        jitter=1.0,             # Random ± fraction of wait (set 0.0 for deterministic tests)
        exceptions=[RegistryUnavailableError, NodeTimeoutError],  # MUST list NodeTimeoutError!
    ),
    timeout=10.0,               # Per-attempt limit in seconds (excludes backoff sleep)
)
async def fetch_package_metadata(ctx: Context, node_input: str):
    yield Event(message=f"Fetching metadata (attempt {ctx.attempt_count})...")
    # Let transient exceptions propagate — NEVER swallow Exception or BaseException!
    return await call_remote_registry(node_input)
```

### Complete `RetryConfig` Defaults & Cross-Language Rules

| Option | Default | Behavior & Caveats |
|---|---|---|
| **`max_attempts`** | `5` | Counts original attempt + retries (`0` or `1` disables retries). |
| **`initial_delay`** | `1.0` s | Wait before first retry. |
| **`max_delay`** | `60.0` s | Caps each retry wait (Go note: Go applies jitter *after* `MaxDelay`, so waits can exceed `MaxDelay` by up to the jitter fraction). |
| **`backoff_factor`** | `2.0` | Multiplier after each failed attempt (base waits: `1, 2, 4, 8...` s). |
| **`jitter`** | `1.0` | Spread fraction `±` around wait; set `0` in unit tests for fixed delays. |
| **`exceptions`** | All errors | Python matches listed classes **and subclasses** (or class names). TS matches exact class name / `error.name` only (no hierarchy check). Go uses `ShouldRetry(err) bool` (default retries all except `workflow.ErrInputValidation`). Java/Kotlin never retry `WorkflowConfigurationException`. |
| **`timeout`** | None | **Per-attempt** limit (wait sleeps do not count). Raises `NodeTimeoutError` (Py/TS/Kt), `context.DeadlineExceeded` (Go), `NodeTimeoutException` (Java). |

### Four Critical Retry & Timeout Pitfalls

1. **Include `NodeTimeoutError` in Explicit `exceptions=[...]`:** If you filter retries with `exceptions=[...]`, timed-out attempts are **not** retried unless `NodeTimeoutError` is explicitly listed.
2. **`ctx.attempt_count` Is NOT Saved Across Pauses/Restarts:** ADK keeps attempt count strictly in memory for the current node execution. After an HITL pause or process restart, a resumed node restarts at **attempt 1** with its full retry budget reset (`attempt_count` starts at 1 in Py/TS/Java/Kt; not present in Go).
3. **Idempotency & Side-Effect Isolation:** A retry re-runs the entire node body from the top. Make retried nodes idempotent or move external writes into a dedicated downstream node after the unreliable call succeeds.
4. **Never Swallow `BaseException` (or Broad `Exception`):** A broad `except Exception:` hides failures from `RetryConfig`; catching `BaseException` without re-raising traps `NodeInterruptedError` and **breaks HITL pauses**.
   - *Cross-language cancellation:* Go relies on passing `ctx` / checking `ctx.Done()`; TS requires passing `ctx.abortSignal` to HTTP calls; Kotlin cancels coroutines at suspension points. In Go, ALWAYS start from `workflow.DefaultRetryConfig()` (a struct literal leaves unset fields zero!).

---

## 6. Dynamic Workflows: Programmatic Durable Orchestration

*Source: `https://adk.dev/graphs/dynamic/` (Supported: Python v2.0.0, TypeScript v2.0.0, Go v2.0.0)*

When control flow requires bounded iterative loops, dynamic runtime fan-out, recursion, or complex branching, write a **Dynamic workflow** using `@node(rerun_on_resume=True)` and `await ctx.run_node(...)`. ADK **automatically checkpoints** every completed child node call so resuming after a pause or failure skips finished children.

### 6.1 Defining Nodes: `@node` vs. Explicit `FunctionNode`

Use `@node(name="...")` for concise decorators, or `FunctionNode(func=fn, name="...")` when wrapping external library callables, reusing one function with multiple configs, or building a node registry (`from google.adk.workflow import FunctionNode, node`).

### 6.2 Bounded Coding-Agent Edit -> Lint/Test -> Fix Loop

```python
from google.adk import Context, Event, Workflow
from google.adk.agents import LlmAgent
from google.adk.workflow import node

MAX_FIX_ROUNDS = 4
coder_agent = LlmAgent(name="generator_agent", model="gemini-4-hydrogen", instruction="Write Python code for the user request.")
fixer_agent = LlmAgent(name="fixer_agent", model="gemini-4-hydrogen", instruction="Refactor current code {code} to fix these review findings: {findings}")

@node(name="lint_reviewer")
async def compile_lint_check(ctx: Context, node_input: str) -> dict:
    return {"findings": ""}  # Deterministic lint/test runner; empty string means clean

@node(rerun_on_resume=True)  # REQUIRED for any orchestrator calling ctx.run_node()!
async def code_workflow(ctx: Context, node_input: str):
    code = await ctx.run_node(coder_agent, node_input)
    check = await ctx.run_node(compile_lint_check, code)
    rounds = 0
    while check["findings"] and rounds < MAX_FIX_ROUNDS:
        rounds += 1
        yield Event(state={"code": code, "findings": check["findings"]})  # Populates {code}/{findings}
        code = await ctx.run_node(fixer_agent, {"code": code, "findings": check["findings"]})
        check = await ctx.run_node(compile_lint_check, code)
    yield Event(output=code)

root_agent = Workflow(name="coding_dynamic_root", edges=[("START", code_workflow)])
```

### 6.3 Parallel Dynamic Fan-Out (`asyncio.gather` + `use_sub_branch=True`)

Append `ctx.run_node(...)` coroutines without awaiting immediately, pass **`use_sub_branch=True`** to isolate each worker's events, and gather them concurrently. On resume, **only failed or interrupted workers re-execute**:

```python
import asyncio
from typing import Any
from google.adk import Context
from google.adk.workflow import node

@node
def lint_single_file(node_input: str) -> dict:
    return {"file": node_input, "clean": True}

@node(rerun_on_resume=True)
async def parallel_linter(ctx: Context, node_input: list[str]) -> list[Any]:
    tasks = [ctx.run_node(lint_single_file, p, use_sub_branch=True) for p in node_input]
    return await asyncio.gather(*tasks)
```

*(Built-in list fan-out shortcuts in other SDKs: TypeScript `node(worker, { parallelWorker: true, maxParallelWorkers: 4 })` [default 8]; Go `workflow.NewParallelWorker("name", worker, maxConcurrency, cfg)` [0 = unlimited].)*

### 6.4 Human Input in Dynamic Workflows (Python vs. TypeScript/Go)

```python
from typing import Any
from google.adk import Context
from google.adk.events import RequestInput
from google.adk.workflow import node

@node(rerun_on_resume=False)  # Leaf pause node: user reply becomes return value of ctx.run_node
async def get_user_approval(ctx: Context, node_input: Any):
    yield RequestInput(message="Approve applying this patch? (Yes/No)")

@node(rerun_on_resume=True)   # Parent orchestrator MUST set rerun_on_resume=True!
async def handle_patch(ctx: Context, node_input: Any) -> str:
    reply = await ctx.run_node(get_user_approval)
    return "Approved" if str(reply).strip().lower() == "yes" else "Denied"
```

- **CRITICAL TypeScript Contrast:** In TS, `await ctx.runNode(...)` returns `{ output, interruptIds }` and **does NOT throw on interrupt**! You MUST guard immediately:
  ```typescript
  const approval = await ctx.runNode(getUserApproval, nodeInput);
  if (approval.interruptIds.length > 0) return undefined;
  ```
  Skipping this check treats `undefined` as the user's answer and runs downstream logic prematurely.
- **Go Contrast:** `workflow.NewDynamicNode` automatically defaults `RerunOnResume: nil -> &true`; use `workflow.ResumeOrRequestInput` inside emitting nodes.

### 6.5 Execution IDs & Custom `run_id` Non-Numeric Warning

ADK assigns deterministic sequential numeric string IDs (`"1"`, `"2"`, ...) based on parent ID + call order to power automatic checkpointing.
- **Default Recommendation:** **Avoid custom `run_id`s** unless iterating over a list whose order can change across resumes (e.g., live database orders). Keep dispatch loops deterministic so auto IDs stay aligned on resume.
- **CRITICAL Non-Numeric Character Rule:** If you *must* supply a custom `run_id` (Python `run_id=f"order-{order.id}"`, TS `{ runId: ... }`, Go `workflow.WithRunID(...)`), it **MUST contain at least one non-numeric character** so it never collides with auto-generated sequential numeric IDs (`"1"`, `"2"`, ...), and must be deterministic for the same logical input across resumes.

---

## 7. Graph & Dynamic Workflow Pitfalls ("Do This, Not That")

| Do This | Not That | Why (Doc-Verified) |
|---|---|---|
| Place `chat`-mode `LlmAgent`s **only** directly after `"START"` | Putting a `chat` agent mid-graph after another node | Graph `LlmAgent`s default to `single_turn`; `chat` consumes conversation history, not `node_input`. |
| Ensure every predecessor of a `JoinNode` emits output & merge parallel leaves with `JoinNode` | Letting a `JoinNode` feeder return empty or leaving >=2 terminal nodes emitting output | Missing feeder output breaks downstream steps; >=2 terminal outputs in a `Workflow` raise **`ValueError`**. |
| Emit **at most ONE** `Event(output=...)` per Python node; use `Event(message=...)` for progress | Yielding two `Event(output=...)` payloads in one Python node | Python raises a **runtime error** on multiple `Event(output=...)` emissions. |
| Reference `input_schema` fields in prose OR write to `state` before using `{key}` in Python instructions | Writing `{CityTime.time_info}` in a Python `LlmAgent` instruction | Python `{key}` substitutes **only from session state**, not `node_input` (leaving `{CityTime.time_info}` verbatim). |
| Bound loops via explicit state counter or Dynamic `@node(rerun_on_resume=True)` `for`/`while` | Relying on ADK to auto-bound a graph cycle | Graph cycles require >=1 routed edge and are **NOT bounded automatically**. |
| Collect structured replies in client UI or parse with a post-pause `LlmAgent` | Expecting `RequestInput(response_schema=...)` to reformat free-text user replies | `response_schema` does **not** reformat replies; user input must already match the schema. |
| Check **both** `tool_context.tool_confirmation` AND `.confirmed` when using `request_confirmation()` | Only checking `if not tool_context.tool_confirmation:` | ADK auto-rejects only on `FunctionTool(require_confirmation=True)`; manual calls execute on denial unless `.confirmed` is checked. |
| List `NodeTimeoutError` in explicit `RetryConfig(exceptions=[...])` & keep retried nodes idempotent | Omitting `NodeTimeoutError`, catching `BaseException`, or trusting `ctx.attempt_count` across pauses | Timeouts won't retry unless listed; `BaseException` breaks HITL pauses; `attempt_count` resets to `1` after pause/restart. |
| Set `@node(rerun_on_resume=True)` on `ctx.run_node` orchestrators & use `use_sub_branch=True` in `asyncio.gather` | Leaving `rerun_on_resume=False` on dynamic orchestrators or passing purely numeric `run_id="42"` | Orchestrators need re-entry to replay checkpoints; custom `run_id`s **must** contain >=1 non-numeric char to avoid collision with `"1"`, `"2"`, .... |
