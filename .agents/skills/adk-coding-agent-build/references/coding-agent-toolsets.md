# Coding-Agent Toolsets: `EnvironmentToolset`, `BaseEnvironment`, `LocalEnvironment` & `ExecuteBashTool`

Source-verified reference extracted directly from `google/adk-python` (`src/google/adk/environment/`, `src/google/adk/tools/environment/`, `src/google/adk/tools/bash_tool.py`, `src/google/adk/tools/skill_toolset.py`) and official `adk.dev` integration guides.

---

## 1. Execution Toolset Decision Matrix

Choose the execution primitive that matches your trust boundary and target environment:

| Primitive | ADK Version | Tools / Interface | Isolation & Security Model | Best Used For |
|---|---|---|---|---|
| **`EnvironmentToolset(environment=LocalEnvironment(...))`** | `ADK Python 2.0+` | `Execute`, `ReadFile`, `EditFile`, `WriteFile` | Local `asyncio.create_subprocess_shell`; file I/O confined via `_resolve_path()`, **no OS/container isolation** for shell commands | Local dev & Lab prototyping inside a dedicated workspace directory |
| **`EnvironmentToolset(environment=CustomBaseEnvironment)`** | `ADK Python 2.0+` | `Execute`, `ReadFile`, `EditFile`, `WriteFile` | Custom remote isolation (e.g., Agent Platform Managed Shell or BYOC Sandbox) with `EnvironmentScope.SESSION` | **Production coding agents** running untrusted code/tests per user or per session |
| **`ExecuteBashTool(workspace=..., policy=BashToolPolicy(...))`** | `ADK Python 2.0+` | `execute_bash` only (no file tools) | **POSIX-only**, no-shell `create_subprocess_exec`, whole-token allowlist, `setrlimit` (`RLIMIT_AS`/`FSIZE`/`NPROC`/`CORE=0`), **mandatory HITL confirmation** | Local POSIX interactive CLI assistants needing strict command allowlists + per-command approval |
| **`ManagedAgent`** (Pre-GA Preview) | `v2.4.0+` | First-party server-hosted Antigravity harness (`antigravity-preview-05-2026`) | Google-managed sandbox (`global` only, default zero network, 4 GiB RAM); **client-side Python/MCP tools raise `NotImplementedError`** | Rapid non-confidential prototyping without operating your own runtime or sandbox |

---

## 2. `EnvironmentToolset` Internals & Contract (`ADK Python 2.0+`)

### Exact Constructor & Imports

```python
from pathlib import Path
from google.adk.environment import (
    BaseEnvironment,
    EnvironmentScope,
    ExecutionResult,
    LocalEnvironment,
)
from google.adk.tools.environment import EnvironmentToolset

toolset = EnvironmentToolset(
    environment=LocalEnvironment(working_dir=Path("/tmp/my_workspace")),
    max_output_chars=12_000,   # Belongs HERE, NOT on LocalEnvironment!
    # **kwargs forwarded to BaseToolset.__init__ (e.g., tool_filter, tool_name_prefix)
)
```

### Exposed Tools (`EnvironmentToolset.get_tools()`)

| Tool Class | Tool Name (LLM) | Behavior & Truncation |
|---|---|---|
| `ExecuteTool` | **`Execute`** | Executes shell commands via `environment.execute(...)`. Output truncated by `max_output_chars`. |
| `ReadFileTool` | **`ReadFile`** | Reads text files via `environment.read_file(...)`. Output truncated by `max_output_chars`. |
| `EditFileTool` | **`EditFile`** | Performs surgical text replacement built on top of `environment.read_file(...)` + `environment.write_file(...)`. |
| `WriteFileTool` | **`WriteFile`** | Creates or overwrites files via `environment.write_file(...)` (auto-creates parent dirs). |

### Verified Runtime Lifecycle Mechanics
1. **Lazy Initialization per Tool Call:** `EnvironmentToolset` does **not** initialize the environment in `__init__` or `process_llm_request()`. It calls `await environment.initialize(ctx=...)` **before every tool call** with that call's `Context` so session-scoped environments can read/write `ctx.state`.
2. **Automatic Prompt Injection:** `process_llm_request()` appends `ENVIRONMENT_INSTRUCTION` (and `ENVIRONMENT_WORKING_DIR_INSTRUCTION` whenever `environment.working_dir` is non-`None`) to the LLM system instruction on every model call.
3. **Pickling Support:** `EnvironmentToolset.__getstate__` strips unpicklable cached prefixed tools, and `__setstate__` resets `self._environment.is_initialized = False` on unpickle so remote replicas re-initialize cleanly on first tool call.
4. **Cleanup:** `EnvironmentToolset.close()` invokes `environment.close()` only when no `initialize()` call is running in the same process.

---

## 3. `LocalEnvironment` Source-Verified Mechanics & Gotchas

### Exact Constructor

```python
from pathlib import Path
from google.adk.environment import LocalEnvironment

local_env = LocalEnvironment(
    working_dir=Path("/tmp/my_agent_workspace"),  # MUST be pathlib.Path, NEVER raw str!
    env_vars={"PORT": "8080", "LOG_LEVEL": "DEBUG"},
)
```

### Critical Gotchas (Verified in `_local_environment.py`)
1. **`working_dir` MUST Be a `pathlib.Path` (Doc vs. Source Bug!):**
   - Official `adk.dev` prose shows `working_dir="/tmp/my_agent_workspace"`, **but** `_local_environment.py` stores `self._working_dir = working_dir` verbatim and executes `self._working_dir.resolve()` inside `_resolve_path()`. Passing a `str` crashes with `AttributeError: 'str' object has no attribute 'resolve'`. Always wrap with `Path(...).resolve()`.
2. **Temporary vs. Persistent Workspace Cleanup:**
   - `working_dir=None` (default): `initialize()` creates `tempfile.mkdtemp(prefix="adk_workspace_")` and `close()` deletes it recursively via `shutil.rmtree(..., ignore_errors=True)`.
   - `working_dir=Path(...)`: `initialize()` runs `os.makedirs(self._working_dir, exist_ok=True)` and **persists files after shutdown**.
3. **Strict Path Confinement (`_resolve_path`):**
   - Both relative and absolute paths are resolved via `.resolve()`; any path where `not resolved.is_relative_to(working_dir)` raises `ValueError("Path escapes working directory: ...")`.
   - **Warning:** This protects `ReadFile`/`EditFile`/`WriteFile`, **not** arbitrary shell commands executed via `Execute` (`asyncio.create_subprocess_shell`), which can still access host files outside `working_dir`. Never expose `LocalEnvironment` to untrusted users in production.
4. **Subprocess Timeout & Process-Group Teardown:**
   - Runs `asyncio.create_subprocess_shell(..., cwd=self._working_dir, env=proc_env, start_new_session=True)` (merging `env_vars` on top of `os.environ.copy()`).
   - On timeout or `asyncio.CancelledError`, sends `SIGTERM` to the entire process group (`os.killpg`), waits **5 seconds** (`_TERMINATE_GRACE_SECONDS = 5`), then escalates unconditionally to `SIGKILL` (another 5s pipe drain grace before abandoning output).
   - `read_file_stream()` reads in **64 KiB** (`65536` byte) chunks via `asyncio.to_thread`.

---

## 4. Custom `BaseEnvironment` Complete Contract (`_base_environment.py`)

### Supporting Types

```python
import dataclasses
import enum

@dataclasses.dataclass
class ExecutionResult:
    exit_code: int = 0        # Process exit code
    stdout: str = ""          # Captured stdout (UTF-8 decoded)
    stderr: str = ""          # Captured stderr (UTF-8 decoded)
    timed_out: bool = False   # True if execution exceeded timeout

class EnvironmentScope(str, enum.Enum):
    SHARED = "shared"    # Default: all runs share one resource; initialize() serialized process-wide
    USER = "user"        # One resource per user; initialize() serialized per user
    SESSION = "session"  # One resource per session; ideal for Managed Sandboxes keyed off ctx.state
```

> **Multi-Replica Caveat:** `EnvironmentToolset` and `SkillToolset` serialize `initialize()` calls per `scope` **within a single Python process only**. Across multiple Agent Runtime / Cloud Run / GKE replicas, coordinate idempotent resource lookup via `ctx.state` or backend idempotency keys.

### Complete `BaseEnvironment(ABC)` Member Contract

| Member | Kind | Exact Signature | Required? | Lifecycle & Implementation Rules |
|---|---|---|---|---|
| **`execute`** | `@abstractmethod` `async def` | `async def execute(self, command: str, *, timeout: float \| None = None, ctx: Context \| None = None) -> ExecutionResult` | **REQUIRED** | Execute shell command in working directory; return `ExecutionResult`. `timeout=None` means unlimited. |
| **`read_file`** | `@abstractmethod` `async def` | `async def read_file(self, path: Path, *, ctx: Context \| None = None) -> bytes` | **REQUIRED** | Return raw bytes for absolute or `working_dir`-relative path. Raise `FileNotFoundError` if absent. |
| **`write_file`** | `@abstractmethod` `async def` | `async def write_file(self, path: Path, content: str \| bytes, *, ctx: Context \| None = None) -> None` | **REQUIRED** | Write UTF-8 `str` or raw `bytes`; MUST create missing parent directories automatically. |
| **`initialize`** | `async def` hook | `async def initialize(self, *, ctx: Context \| None = None) -> None` | Optional (no-op) | Called **before every tool call** with that call's `ctx`. Must be **fast and idempotent** once provisioned. Look up/create per-session sandbox and save its resource name in `ctx.state`. Raised exceptions propagate to `on_tool_error_callback`. |
| **`close`** | `async def` hook | `async def close(self) -> None` | Optional (no-op) | Idempotent cleanup; called by `EnvironmentToolset.close()` only while no `initialize()` is running. |
| **`read_file_stream`** | `async def` generator | `async def read_file_stream(self, path: Path, *, ctx: Context \| None = None) -> AsyncGenerator[bytes, None]` | Optional | Default yields `await self.read_file(path, ctx=ctx)` in one chunk; override for chunked streaming. |
| **`working_dir`** | `@property` | `def working_dir(self) -> Path \| None` | Optional (`None`) | Fixed absolute path (e.g. `Path("/workspace")`) or `None`. Takes **no `ctx`** — `USER`/`SESSION` environments MUST use the same logical mount path inside each isolated sandbox. |
| **`scope`** | `@property` | `def scope(self) -> EnvironmentScope` | Optional (`SHARED`) | Must remain constant for the object's lifetime. Return `EnvironmentScope.SESSION` for per-session sandboxes. |
| **`is_initialized`** | `@property` + setter | `def is_initialized(self) -> bool` | Inherited (`False`) | Whole-environment flag (`_is_initialized`). Reset to `False` by `EnvironmentToolset.__setstate__` on unpickle. |

### Two Mandatory `BaseEnvironment` Implementation Rules
1. **Only 3 Abstract Methods — NO `edit_file`:** Do **not** implement an abstract `edit_file` method on `BaseEnvironment`. `EditFileTool` performs surgical text replacement by composing `read_file` and `write_file`.
2. **Always Accept `*, ctx: Context | None = None`:** `BaseEnvironment.__init_subclass__` inspects overrides of `("initialize", "execute", "read_file", "read_file_stream", "write_file")`. Omitting `ctx` triggers a `DeprecationWarning` and wraps the method to **silently drop `ctx`**, breaking `ctx.state` sandbox lookup!

### Production Starter Subclass (Session-Scoped Sandbox Adapter)

```python
from pathlib import Path
from typing import TYPE_CHECKING
from typing_extensions import override

from google.adk.environment import BaseEnvironment, EnvironmentScope, ExecutionResult

if TYPE_CHECKING:
    from google.adk.agents.context import Context

SANDBOX_STATE_KEY = "coding_agent:sandbox_resource_name"

class AgentPlatformSandboxEnvironment(BaseEnvironment):
    """Per-session remote sandbox adapter for EnvironmentToolset."""

    def __init__(
        self,
        *,
        project_id: str,
        location: str,
        template_name: str,
        working_dir: Path = Path("/workspace"),
    ) -> None:
        self._project_id = project_id
        self._location = location
        self._template_name = template_name
        self._working_dir = working_dir

    @property
    @override
    def scope(self) -> EnvironmentScope:
        return EnvironmentScope.SESSION

    @property
    @override
    def working_dir(self) -> Path | None:
        return self._working_dir

    @override
    async def initialize(self, *, ctx: Context | None = None) -> None:
        if ctx is not None and SANDBOX_STATE_KEY not in ctx.state:
            # Provision or attach per-session sandbox from self._template_name
            ctx.state[SANDBOX_STATE_KEY] = self._create_or_get_sandbox(ctx.session.id)
        self._is_initialized = True

    @override
    async def execute(
        self, command: str, *, timeout: float | None = None, ctx: Context | None = None
    ) -> ExecutionResult:
        sandbox_id = self._require_sandbox(ctx)
        # Dispatch command to remote sandbox runner and map response -> ExecutionResult
        ...

    @override
    async def read_file(self, path: Path, *, ctx: Context | None = None) -> bytes:
        sandbox_id = self._require_sandbox(ctx)
        ...

    @override
    async def write_file(
        self, path: Path, content: str | bytes, *, ctx: Context | None = None
    ) -> None:
        sandbox_id = self._require_sandbox(ctx)
        ...

    @override
    async def close(self) -> None:
        self._is_initialized = False

    def _require_sandbox(self, ctx: Context | None) -> str:
        if ctx is None or SANDBOX_STATE_KEY not in ctx.state:
            raise RuntimeError("Sandbox not initialized in session state.")
        return str(ctx.state[SANDBOX_STATE_KEY])

    def _create_or_get_sandbox(self, session_id: str) -> str:
        raise NotImplementedError("Wire to Agent Platform Sandbox SDK in sandbox layer.")
```

---

## 5. Sharing `BaseEnvironment` with `SkillToolset` (`ADK Python 2.0+`)

A coding agent can pass the **same** `BaseEnvironment` instance to both `EnvironmentToolset` and `SkillToolset` so `run_skill_script` runs inside the exact same confined workspace or remote sandbox:

```python
from pathlib import Path
from google.adk.environment import LocalEnvironment
from google.adk.tools.environment import EnvironmentToolset
from google.adk.tools.skill_toolset import SkillToolset

shared_env = LocalEnvironment(working_dir=Path("/tmp/coding_workspace"))

tools = [
    EnvironmentToolset(environment=shared_env, max_output_chars=12_000),
    SkillToolset(
        skills=[...],           # or registry=GCPSkillRegistry(...)
        environment=shared_env, # Shares workspace/sandbox with EnvironmentToolset!
        script_timeout=300,     # Default: 300s (shell scripts via subprocess; not exec())
    ),
]
```

### Verified `SkillToolset` + `environment` Constraints (`skill_toolset.py`)
- **Mutual Exclusion (`ValueError`):** `SkillToolset` accepts `environment=` **OR** `code_executor=`, **NEVER both** — passing both raises `ValueError`.
- **`skills_folder` Must Be Absolute:** If specifying `skills_folder`, pass an absolute `Path`/`str` (defaults to `'skills'` under `environment.working_dir`); a relative path raises `ValueError`.
- **`save_output_artifacts=True` Unsupported with `environment=`:** Auto-saving generated files as ADK artifacts is supported **only** with `code_executor`, not `environment`.

---

## 6. `ExecuteBashTool` & `BashToolPolicy` Hardening (`ADK Python 2.0+`)

### Exact Signatures & Dangerous Defaults (`bash_tool.py`)

```python
from pathlib import Path
from google.adk.tools.bash_tool import BashToolPolicy, ExecuteBashTool

# HARDENED POLICY — never rely on default BashToolPolicy()!
policy = BashToolPolicy(
    allowed_command_prefixes=("ls", "cat", "grep", "git status", "pytest"),  # Default: ("*",) !!
    blocked_operators=(";", "|", "&&", "||", "$(", "`", ">", "<"),           # Default: () !!
    timeout_seconds=30,                                                      # Default: 30
    max_memory_bytes=512 * 1024 * 1024,                                      # Default: None -> RLIMIT_AS
    max_file_size_bytes=10 * 1024 * 1024,                                    # Default: None -> RLIMIT_FSIZE (0 = read-only)
    max_child_processes=5,                                                   # Default: None -> RLIMIT_NPROC
)

bash_tool = ExecuteBashTool(
    workspace=Path("/tmp/coding_workspace"),  # Keyword-only; defaults to Path.cwd()
    policy=policy,
)
```

### Verified Security Mechanics
1. **Dangerous Default Allowlist:** `BashToolPolicy()` defaults to `allowed_command_prefixes=("*",)` (permits **all** commands) and `blocked_operators=()`. Always declare an explicit allowlist tuple and operator blocklist.
2. **Whole-Token Matching via `shlex.split`:** `("ls",)` permits `ls -la` while rejecting `lsof`, `./ls`, and `/bin/ls`. Multi-token entries like `("git status",)` restrict execution to that exact subcommand.
3. **No Shell Interpretation:** Commands run via `asyncio.create_subprocess_exec(*shlex.split(command), ...)` (not `shell=True`). Shell metacharacters reach the target binary as literal arguments unless explicitly rejected via `blocked_operators`.
4. **Mandatory HITL Approval (`adk_request_confirmation`):** `ExecuteBashTool.run_async()` **always** calls `tool_context.request_confirmation(...)` and sets `tool_context.actions.skip_summarization = True` on the first invocation. This gate cannot be disabled (ensure `App(..., resumability_config=ResumabilityConfig(is_resumable=True))`).
5. **POSIX-Only & OS `setrlimit` Enforcement:**
   - Returns `{"error": "ExecuteBashTool is only supported on POSIX systems."}` if `os.name != "posix"`.
   - Always disables core dumps: `RLIMIT_CORE = (0, 0)`.
   - Sets `RLIMIT_AS`, `RLIMIT_FSIZE` (`0` = zero bytes writable), and `RLIMIT_NPROC` in `preexec_fn`.
   - Runs in `start_new_session=True` and issues `os.killpg(pid, SIGKILL)` both on `asyncio.TimeoutError` and inside `finally:`.

---

## 7. Contrast: Managed Agents API (`ManagedAgent`, Pre-GA Preview)

When evaluating whether to build a custom ADK `LlmAgent` + `EnvironmentToolset` vs. Google's server-hosted **Managed Agents API**:

- **Backend:** Control plane (`Agents API`) + data plane (`Interactions API`) via `genai.Client(vertexai=True, project=..., location="global")` (**`global` location only**).
- **`base_agent`:** Only `antigravity-preview-05-2026` is supported (first agent in a project takes 2–3 min to provision; subsequent agents take 2–3 sec).
- **ADK Wrapper (`google-adk >= 2.4.0`):** `ManagedAgent(name=..., mode="single_turn", agent_id=..., environment={"type": "remote"}, tools=[google_search])` implements `BaseAgent` (usable standalone, in a `Workflow`, or added with `mode="single_turn"` directly to a parent `LlmAgent`'s `sub_agents` so ADK exposes it as an inline single-turn tool).
- **Hard Limitations:**
  - Pre-GA: **do NOT use with proprietary, confidential, or production data**.
  - Client-side tools (Python functions, client-side `McpToolset`) and raw `types.Tool.mcp_servers` configs raise **`NotImplementedError`** — only server-side built-in tools (e.g., `google_search`, `types.Tool(code_execution=...)`) and server-side remote MCP servers declared as **`google.adk.tools.RemoteMcpServer`** in `tools` (`Streamable HTTP`; `roles/mcp.toolUser`; deprecated HTTP+SSE `GET /sse` unsupported; Google-hosted MCPs require `X-Goog-User-Project`) work.
  - Default sandbox has **zero network access** (configure `base_environment.network.allowlist`); mounts Skill Registry (max **100** skills) or GCS (subject to **4 GiB RAM** limit).
  - Python/JS SDKs lack `agents.update()` (use REST `PATCH ...?update_mask=...`).

---

## 8. Error Modes & Verification Steps

| Error / Failure Mode | Cause | Verified Fix |
|---|---|---|
| `AttributeError: 'str' object has no attribute 'resolve'` | Passed string to `LocalEnvironment(working_dir="/tmp/...")` | Pass `working_dir=Path("/tmp/...").resolve()`. |
| `TypeError: LocalEnvironment.__init__() got an unexpected keyword argument 'max_output_chars'` | Placed `max_output_chars` on `LocalEnvironment` | Move `max_output_chars=12_000` to `EnvironmentToolset(...)`. |
| `DeprecationWarning: ... overrides execute without a 'ctx' keyword argument` | Custom `BaseEnvironment` omitted `ctx` | Add `*, ctx: Context \| None = None` to `initialize`, `execute`, `read_file`, `read_file_stream`, and `write_file`. |
| `ValueError: Path escapes working directory` | Agent attempted `../` or absolute path outside `working_dir` | Keep workspace files inside `working_dir`; expected confinement behavior. |
| `ValueError` constructing `SkillToolset` | Supplied both `environment=` and `code_executor=`, or relative `skills_folder` | Pass only `environment=` (not `code_executor=`) and use an absolute `skills_folder` if set. |
| `This tool call requires confirmation, please approve or reject.` | Expected `ExecuteBashTool` HITL pause without resumability handler | Enable `ResumabilityConfig(is_resumable=True)` on `App` and handle `adk_request_confirmation` in client/UI. |

### Concrete Verification Commands

```python
# Run with: uv run pytest -q
import warnings
from pathlib import Path
import pytest
from google.adk.environment import BaseEnvironment, EnvironmentScope, ExecutionResult, LocalEnvironment
from google.adk.tools.environment import EnvironmentToolset
from google.adk.tools.bash_tool import BashToolPolicy, _validate_command

@pytest.mark.asyncio
async def test_local_environment_confinement_and_io(tmp_path: Path):
    env = LocalEnvironment(working_dir=tmp_path)
    toolset = EnvironmentToolset(environment=env, max_output_chars=4096)
    tools = {t.name for t in await toolset.get_tools()}
    assert tools == {"Execute", "ReadFile", "EditFile", "WriteFile"}

    await env.initialize()
    await env.write_file(Path("hello.py"), "print('ok')\n")
    res = await env.execute("python3 hello.py", timeout=10)
    assert res.exit_code == 0 and "ok" in res.stdout
    with pytest.raises(ValueError, match="escapes working directory"):
        await env.read_file(Path("../outside.txt"))
    await toolset.close()

def test_bash_policy_whole_token_matching():
    policy = BashToolPolicy(
        allowed_command_prefixes=("ls", "git status"),
        blocked_operators=(";", "|", "&&", "$(", "`"),
    )
    assert _validate_command("ls -la", policy) is None
    assert _validate_command("lsof", policy) is not None
    assert _validate_command("git status --short", policy) is None
    assert _validate_command("git push", policy) is not None
    assert _validate_command("ls; rm -rf /", policy) is not None
```
