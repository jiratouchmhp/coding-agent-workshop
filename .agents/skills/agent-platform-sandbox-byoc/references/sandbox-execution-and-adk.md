# Sandbox Execution Paths & Google ADK Integration

Authoritative guide for executing commands, scripts, browser actions, and file I/O across all four Gemini Enterprise Agent Platform Scale Sandbox execution paths — plus wiring remote sandboxes into Google ADK via `AgentEngineSandboxCodeExecutor` and custom `BaseEnvironment` subclasses.

---

## 1. Execution Path Comparison Matrix

| Path | Sandbox Type | SDK / Transport Method | Caller Auth | Stateful Across Calls? |
|---|---|---|---|---|
| **A. Shell Sandbox** | `shell_environment` / `DEFAULT_CONTAINER_CATEGORY_SHELL_SANDBOX` | `client.sandboxes.execute_bash(name, command, cwd, timeout)` -> container `/exec` | Caller ADC/IAM (`roles/aiplatform.user`) — **no JWT needed** | Files under `/workspace` persist; **shell cwd & env vars reset every call** |
| **B. BYOC Custom Container** | `custom_container_environment` (`ports`) | `generate_access_token` + `send_command(http_method="POST", path="exec", ...)` OR direct HTTP `/exec` over PSC-E / local Docker | Short-lived sandbox JWT (`roles/iam.serviceAccountTokenCreator` + `roles/aiplatform.user`) or IAM bearer | Container filesystem persists; runner spawns fresh child process per `/exec` |
| **C. Code Execution** | `code_execution_environment` | `client.sandboxes.execute_code(name, input_data)` or ADK `AgentEngineSandboxCodeExecutor` | Caller ADC/IAM (`roles/aiplatform.user`) | **Yes** — Python/JS variables, imported modules & files persist (TTL resets on each call) |
| **D. Computer Use** | `DEFAULT_CONTAINER_CATEGORY_COMPUTER_USE` | `send_command` (`/cdp`, `/tabs`, `/`) OR `generate_browser_ws_headers` + Playwright `connect_over_cdp` + noVNC | Short-lived JWT / browser WS headers (`roles/iam.serviceAccountTokenCreator` + `roles/aiplatform.user`) | Browser tabs, cookies, session & disk persist |
| **E. Custom ADK `BaseEnvironment`** | Shell or BYOC backing `EnvironmentToolset` | Subclass `google.adk.environment.BaseEnvironment` (`execute`, `read_file`, `write_file`) | Delegates to Path A or Path B | Per-session sandbox name stored in `ctx.state` (`EnvironmentScope.SESSION`) |

---

## 2. Path A — Shell Sandbox (`execute_bash()` -> `/exec`)

- **Hard Incompatibility:** `send_command()` and `execute_code()` **do NOT work** with Shell sandboxes (they send Python payloads targeting Code Execution sandboxes, which the shell container rejects). Always call `execute_bash()`.
- **Execution Semantics:**
  - Runs as unprivileged user **`appuser`** (no `sudo`, no metadata server, no ADC).
  - Default `cwd` is **`/workspace`**; default `timeout` is the sandbox's limit.
  - **Fresh stateless shell per call:** `cd` and `export VAR=...` do **not** persist across calls. Chain commands in one call (`cd /workspace/app && pytest -q`) or persist state to files under `/workspace`.
  - Outbound internet access is disabled unless enabled on the template.
- **Auth:** Uses caller ADC/IAM (`aiplatform.sandboxEnvironments.execute`, included in `roles/aiplatform.user`); no service account key or signed JWT required.

```python
import agentplatform

client = agentplatform.Client(project="PROJECT_ID", location="us-central1")
sandbox_name = (
    "projects/PROJECT_ID/locations/us-central1"
    "/reasoningEngines/INSTANCE_ID/sandboxEnvironments/SANDBOX_ID"
)

# Basic invocation
res = client.sandboxes.execute_bash(
    name=sandbox_name,
    command="echo hello && whoami && pwd",
)
# Verified return dict:
# {'stdout': 'hello\nappuser\n/workspace\n', 'stderr': '', 'returncode': 0, 'duration_ms': 8}

# With explicit cwd and timeout (seconds); chain stateful shell commands in one call
test_res = client.sandboxes.execute_bash(
    name=sandbox_name,
    command="cd /workspace/app && pytest -q",
    cwd="/workspace/app",
    timeout=120,
)
if test_res["returncode"] != 0:
    print("Command failed:", test_res["stderr"])
```

---

## 3. Path B — BYOC Custom Container (`/exec` Runner)

Expose a TCP port (e.g., `8080`) on `SandboxEnvironmentTemplate.config.custom_container_environment.ports` and invoke your container runner via either the managed data-plane proxy or private PSC-E ingress:

### Required IAM for `generate_access_token()`

- Caller holds `roles/aiplatform.user` on the project AND `roles/iam.serviceAccountTokenCreator` on `SERVICE_ACCOUNT_EMAIL`.
- `SERVICE_ACCOUNT_EMAIL` holds `roles/aiplatform.user` on the project.
- Audited in Cloud Audit Logs (`DATA_WRITE`) as `AuthorizeSandboxEnvironmentAccess`.

### Managed Data-Plane Proxy (`generate_access_token` + `send_command`)

```python
import json
import agentplatform

client = agentplatform.Client(
    project="PROJECT_ID",
    location="us-central1",
    http_options={"api_version": "v1beta1"},
)
sandbox = client.sandboxes.get(name=sandbox_name)

# Mint short-lived data-plane JWT
access_token = client.sandboxes.generate_access_token(
    service_account_email="sandbox-caller@PROJECT_ID.iam.gserviceaccount.com",
)

# POST /exec on the BYOC container's exposed port
response = client.sandboxes.send_command(
    http_method="POST",
    path="exec",
    access_token=access_token,
    request_dict={"command": "ruff check /workspace && pytest -q", "cwd": "/workspace", "timeout": 60},
    sandbox_environment=sandbox,
)
result = json.loads(response.body) if isinstance(response.body, (str, bytes)) else response.body
print(result["returncode"], result["stdout"], result["stderr"])
```

### Direct HTTP `/exec` (Private PSC-E Forwarding Rule or Local Docker Test)

When PSC-E private ingress is enabled (or when smoke-testing locally against `http://127.0.0.1:8080`), send `POST <BASE_URL>/exec` with JSON `{"command": ..., "cwd": "/workspace", "timeout": 60}` and a short-lived `Authorization: Bearer <token>` header when required by your ingress layer.

---

## 4. Path C — Code Execution Sandbox & ADK `AgentEngineSandboxCodeExecutor`

### Key Limits & Preinstalled Library Rules

- **Languages:** `LANGUAGE_PYTHON` or `LANGUAGE_JAVASCRIPT` only.
- **Compute:** Default `MACHINE_CONFIG_UNSPECIFIED` (**2 vCPU, 1.5 GiB RAM**); optional `MACHINE_CONFIG_VCPU4_RAM4GIB` (**4 vCPU, 4 GiB RAM**).
- **Limits:** Sub-second create + execute; **300-second** per-execution timeout; **100 MB** max total file payload per request or response; **14-day** max TTL (reset on every `execute_code()` call); **zero network access**; **no `pip install`**; **no snapshots**.
- **File I/O scope:** Code executes in the same working folder as uploaded `files` and cannot access arbitrary host directories.
- **Preinstalled Python highlights** (verified from `scale/sandbox/code-execution-overview`): `numpy 2.1.3`, `pandas 2.2.3`, `scipy 1.15.2`, `pyarrow 18.1.0`, `scikit-learn 1.6.1`, `tensorflow 2.20.0`, `keras 3.14.0`, `xgboost 3.2.0`, `nltk 3.9.1`, `spacy 3.8.14`, `sympy 1.13.3`, `networkx 3.6.1`, `numba 0.64.0`, `statsmodels 0.14.6`, `ortools 9.14.6206`, `matplotlib 3.10.1`, `seaborn 0.13.2`, `plotly 6.1.2`, `bokeh 3.8.2`, `opencv-python 4.11.0.86`, `pillow 11.1.0`, `openpyxl 3.1.5`, `PyPDF2 3.0.1`, `reportlab 4.3.1`, `python-docx 1.1.2`, `python-pptx 1.0.2`, `lxml 5.3.1`, `PyYAML 6.0.3`, `pydantic 2.13.1`, `jsonschema 4.23.0`, `geopandas 1.0.1`, `shapely 2.1.2`.

### Direct SDK `execute_code()` with Safe `Chunk` Parsing

> **Doc Bug Warning:** Do **not** copy lines 307–310 of `code-execution-quickstart` (`output_file_content.b64decode(...)` on a `str`). `response.outputs` contains `Chunk` elements: JSON chunks hold `{"msg_out": "...", "msg_err": "..."}` in UTF-8 `chunk.data`, and generated files arrive as separate `Chunk` items with `chunk.attributes["file_name"]` and raw bytes in `chunk.data`.

```python
import json

input_data = {
    "code": (
        'with open("input.txt", "r") as f:\n'
        '    lines = f.readlines()\n'
        'with open("output.txt", "w") as out:\n'
        '    for line in lines:\n'
        '        print(line.strip())\n'
        '        out.write(line)\n'
    ),
    "files": [{"name": "input.txt", "content": b"Hello, world!\n"}],
}

response = client.sandboxes.execute_code(name=code_sandbox_name, input_data=input_data)

for chunk in response.outputs:
    if chunk.mime_type == "application/json":
        status = json.loads(chunk.data.decode("utf-8"))
        print("stdout:", status.get("msg_out", ""), "stderr:", status.get("msg_err", ""))
    else:
        file_name = (chunk.attributes or {}).get("file_name")
        print(f"output file={file_name} mime={chunk.mime_type} size={len(chunk.data)}B")
```

### ADK `AgentEngineSandboxCodeExecutor` (ADK Python `>= v1.17.0`)

Maintains **one persistent Code Execution sandbox** across all tool calls in an ADK session. Requires `roles/aiplatform.user` on the agent's service account. Agent can run locally, on Cloud Run, GKE, or Agent Runtime.

```python
from google.adk.agents.llm_agent import Agent
from google.adk.code_executors.agent_engine_sandbox_code_executor import (
    AgentEngineSandboxCodeExecutor,
)

root_agent = Agent(
    model="gemini-2.5-flash",  # Explicit versioned regional model ID (avoid gemini-flash-latest on us-central1)
    name="agent_engine_code_execution_agent",
    instruction=(
        "Execute Python code step-by-step in the stateful sandbox. "
        "Always print variables/results to inspect output. "
        "NEVER run pip install or assume column names without inspecting the data."
    ),
    code_executor=AgentEngineSandboxCodeExecutor(
        # Provide EITHER a pre-created sandbox resource name:
        sandbox_resource_name=(
            "projects/PROJECT_ID/locations/us-central1"
            "/reasoningEngines/INSTANCE_ID/sandboxEnvironments/SANDBOX_ID"
        ),
        # OR a parent ReasoningEngine resource name (auto-creates a default sandbox per session):
        # agent_engine_resource_name="projects/PROJECT_ID/locations/us-central1/reasoningEngines/INSTANCE_ID",
    ),
)
```

### Code Execution Troubleshooting Matrix (`troubleshooting/code-execution`)

| Issue | Cause | Fix |
|---|---|---|
| Execution timeout | Exceeded fixed **300-second** execution cap | Optimize code or split long workloads across multiple stateful `execute_code()` steps. |
| File not found | Referenced files outside current folder | Upload via `input_data["files"]`; code runs in the same folder and cannot read other directories. |
| Payload rejected | Request or response files exceed **100 MB** | Compress/chunk inputs or summarize outputs before returning. |
| Lost variables/state | Different `sandbox_name` used or sandbox TTL expired | Reuse the same `sandbox_name` across calls; set an explicit `ttl` (up to 14 days). |
| `429 Resource Exhausted` | Hit 1,000 execute req/min, 500 write req/min, or 1,000 entities quota | Reuse sandboxes, delete finished sandboxes, or request quota increase. |

---

## 5. Path D — Computer Use Sandbox (Browser API, Playwright CDP & VNC)

Create a template with `"default_container_category": "DEFAULT_CONTAINER_CATEGORY_COMPUTER_USE"` (and `"internet_access": True` or PSC-I egress if browsing external sites).

### Verified HTTP API Paths via `send_command()` + `generate_access_token()`

| Method | Path | Purpose |
|---|---|---|
| `GET` | `/` | Sandbox health check |
| `POST` | `/tabs` | Open a new browser tab and return details |
| `GET` | `/tabs` | List all open tabs |
| `POST` | `/tabs/{tab_id}/activate` | Bring a tab to the foreground |
| `DELETE` | `/tabs/{tab_id}` | Close a tab |
| `GET` | `/cdp_ws_endpoint` | Retrieve CDP WebSocket endpoint path |
| `POST` | `/cdp` | Run a single CDP command on the active tab (e.g., `{"command": "Page.navigate", "params": {"url": "https://example.com"}}`) |
| `POST` | `/cdps` | Run multiple CDP commands on the active tab |

### Playwright Over CDP (`generate_browser_ws_headers`) & Live VNC

> **SDK Namespace Note:** `generate_browser_ws_headers` is documented on **`vertexai.Client`** (`v_client.agent_engines.sandboxes`), whereas `send_command` and `generate_access_token` work directly on **`agentplatform.Client`** (`client.sandboxes`). Always initialize `vertexai.Client` explicitly before calling `.agent_engines.sandboxes` — calling `.agent_engines` on `agentplatform.Client` raises `AttributeError`.

```python
import asyncio
import vertexai
from playwright.async_api import async_playwright

v_client = vertexai.Client(
    project="PROJECT_ID",
    location="us-central1",
    http_options={"api_version": "v1beta1"},
)
v_sandbox = v_client.agent_engines.sandboxes.get(name=sandbox_name)
ws_url, ws_headers = v_client.agent_engines.sandboxes.generate_browser_ws_headers(
    sandbox_environment=v_sandbox,
    service_account_email="SERVICE_ACCOUNT_EMAIL",
)

async def browse():
    async with async_playwright() as p:
        browser = await p.chromium.connect_over_cdp(endpoint_url=ws_url, headers=ws_headers)
        page = browser.contexts[0].pages[0]
        await page.goto("https://www.example.com")
        print(await page.title())
        await browser.close()

asyncio.run(browse())
```

Computer Use sandboxes also support live visual streaming via **VNC / noVNC over WebSocket** for real-time debugging.

---

## 6. Path E — Custom ADK `BaseEnvironment` for `EnvironmentToolset` (ADK `>= v1.29.0`)

ADK's `EnvironmentToolset` exposes four tools to an LLM agent (`Execute`, `ReadFile`, `EditFile`, `WriteFile`) backed by any `BaseEnvironment`. While ADK ships `LocalEnvironment` (local `asyncio` subprocesses), production coding agents should subclass `BaseEnvironment` to route every command and file operation into a per-session gVisor Scale Sandbox.

### Source-Verified `BaseEnvironment` Contract (`google/adk-python`)

1. **Public Imports:**
   ```python
   from google.adk.environment import BaseEnvironment, EnvironmentScope, ExecutionResult
   from google.adk.tools.environment import EnvironmentToolset
   ```
2. **Exactly 3 Abstract Methods:**
   - `async def execute(self, command: str, *, timeout: float | None = None, ctx: Context | None = None) -> ExecutionResult`
   - `async def read_file(self, path: Path, *, ctx: Context | None = None) -> bytes` *(MUST raise `FileNotFoundError` if the file does not exist!)*
   - `async def write_file(self, path: Path, content: str | bytes, *, ctx: Context | None = None) -> None` *(MUST auto-create parent directories!)*
   - *(ADK's `EditFileTool` implements surgical edits automatically on top of `read_file` + `write_file`; `read_file_stream` defaults to yielding `await self.read_file(path, ctx=ctx)`.)*
3. **Mandatory `*, ctx: Context | None = None`:** `BaseEnvironment.__init_subclass__` inspects `initialize`, `execute`, `read_file`, `read_file_stream`, and `write_file` and emits `DeprecationWarning` if `ctx` is omitted.
4. **`EnvironmentScope.SESSION` Concurrency & Idempotency Trap:**
   - Return `EnvironmentScope.SESSION` from `@property def scope(self)` so each ADK session gets its own isolated sandbox (serialized per session inside a process).
   - `EnvironmentToolset` calls `await environment.initialize(ctx=ctx)` before **every** tool call. **NEVER** short-circuit on `if self._is_initialized: return` — a single `BaseEnvironment` instance serves multiple sessions! Always look up `ctx.state.get("agent_platform:sandbox_name")` and lazily provision when missing.
5. **`working_dir` Takes No `ctx`:** Return a fixed container path (e.g., `Path("/workspace")`) so `EnvironmentToolset.process_llm_request` injects the workspace path cleanly.

### Production Custom `BaseEnvironment` Pattern

```python
from __future__ import annotations

import asyncio
import base64
import posixpath
import shlex
from pathlib import Path, PurePosixPath
from typing import TYPE_CHECKING, Any

from google.adk.environment import BaseEnvironment, EnvironmentScope, ExecutionResult
from google.adk.tools.environment import EnvironmentToolset
from typing_extensions import override

if TYPE_CHECKING:
    from google.adk.agents.context import Context

_MISSING_EXIT_CODE = 44
_WRITE_CHUNK_BYTES = 24_576  # Stays safely below OS ARG_MAX limits


class AgentPlatformSandboxEnvironment(BaseEnvironment):
    """Per-session ADK BaseEnvironment backed by a Managed Shell Sandbox."""

    STATE_KEY = "agent_platform:sandbox_name"

    def __init__(self, *, client: Any, instance_name: str, template_name: str | None = None, ttl: str = "3600s"):
        self._client = client
        self._instance_name = instance_name
        self._template_name = template_name
        self._ttl = ttl
        self._working_dir = Path("/workspace")
        self._fallback_sandbox: str | None = None

    @property
    @override
    def scope(self) -> EnvironmentScope:
        return EnvironmentScope.SESSION

    @property
    @override
    def working_dir(self) -> Path | None:
        return self._working_dir

    def _confine(self, path: Path) -> PurePosixPath:
        root = posixpath.normpath(str(self._working_dir))
        raw = str(path)
        norm = posixpath.normpath(raw if raw.startswith("/") else posixpath.join(root, raw))
        if norm != root and not norm.startswith(root.rstrip("/") + "/"):
            raise ValueError(f"Path {raw!r} escapes sandbox workspace {root!r}")
        return PurePosixPath(norm)

    def _active_sandbox(self, ctx: Context | None) -> str | None:
        if ctx is not None and getattr(ctx, "state", None) is not None:
            return ctx.state.get(self.STATE_KEY)
        return self._fallback_sandbox

    @override
    async def initialize(self, *, ctx: Context | None = None) -> None:
        # NEVER short-circuit on self._is_initialized; check ctx.state per session!
        if self._active_sandbox(ctx):
            self._is_initialized = True
            return

        def _create() -> str:
            cfg = {"display_name": "adk-session-sandbox", "ttl": self._ttl, "wait_for_completion": True}
            if self._template_name:
                cfg["sandbox_environment_template"] = self._template_name
            op = self._client.sandboxes.create(
                name=self._instance_name, spec={"shell_environment": {}}, config=cfg
            )
            return op.response.name

        sandbox_name = await asyncio.to_thread(_create)
        if ctx is not None and getattr(ctx, "state", None) is not None:
            ctx.state[self.STATE_KEY] = sandbox_name
        else:
            self._fallback_sandbox = sandbox_name
        self._is_initialized = True

    @override
    async def execute(
        self, command: str, *, timeout: float | None = None, ctx: Context | None = None
    ) -> ExecutionResult:
        await self.initialize(ctx=ctx)
        sandbox_name = self._active_sandbox(ctx)
        kwargs: dict[str, Any] = {"name": sandbox_name, "command": command, "cwd": str(self._working_dir)}
        if timeout is not None:
            kwargs["timeout"] = max(1, int(timeout))
        res = await asyncio.to_thread(self._client.sandboxes.execute_bash, **kwargs)
        return ExecutionResult(
            exit_code=int(res.get("returncode", 0)),
            stdout=str(res.get("stdout", "")),
            stderr=str(res.get("stderr", "")),
            timed_out=res.get("returncode") == 124,
        )

    @override
    async def read_file(self, path: Path, *, ctx: Context | None = None) -> bytes:
        target = self._confine(path)
        script = (
            "import base64, pathlib, sys; p = pathlib.Path(sys.argv[1]); "
            f"sys.exit({_MISSING_EXIT_CODE}) if not p.is_file() else None; "
            "sys.stdout.write(base64.b64encode(p.read_bytes()).decode('ascii'))"
        )
        res = await self.execute(f"python3 -c {shlex.quote(script)} {shlex.quote(str(target))}", ctx=ctx)
        if res.exit_code == _MISSING_EXIT_CODE:
            raise FileNotFoundError(str(target))
        if res.exit_code != 0:
            raise OSError(res.stderr)
        return base64.b64decode(res.stdout.encode("ascii"))

    @override
    async def write_file(
        self, path: Path, content: str | bytes, *, ctx: Context | None = None
    ) -> None:
        target = self._confine(path)
        raw = content.encode("utf-8") if isinstance(content, str) else bytes(content)
        chunks = [raw[i : i + _WRITE_CHUNK_BYTES] for i in range(0, len(raw), _WRITE_CHUNK_BYTES)] or [b""]
        script = (
            "import base64, pathlib, sys; p = pathlib.Path(sys.argv[1]); "
            "p.parent.mkdir(parents=True, exist_ok=True); "
            "p.open(sys.argv[2]).write(base64.b64decode(sys.argv[3].encode('ascii')))"
        )
        for idx, chunk in enumerate(chunks):
            mode = "wb" if idx == 0 else "ab"
            b64 = base64.b64encode(chunk).decode("ascii")
            res = await self.execute(
                f"python3 -c {shlex.quote(script)} {shlex.quote(str(target))} {mode} {shlex.quote(b64)}",
                ctx=ctx,
            )
            if res.exit_code != 0:
                raise OSError(res.stderr)
```

Wire into an ADK agent with output truncation protection:
```python
tools = [EnvironmentToolset(environment=sandbox_env, max_output_chars=16_000)]
```

---

## 7. Verification Steps

1. **Shell check:** Run `execute_bash(command="whoami && pwd")` and assert `stdout == "appuser\n/workspace\n"` and `returncode == 0`. Confirm stateless shell by running `cd /tmp` followed by a second call `pwd` (must still report `/workspace`).
2. **Code Exec check:** Execute a two-step snippet where step 1 defines `x = 42` and writes `out.txt`, and step 2 reads `x` and writes `out2.txt`; verify both `application/json` status chunks and binary file `Chunk` outputs parse cleanly without calling `.b64decode()` on strings.
3. **Custom `BaseEnvironment` check:** Verify `write_file(Path("sub/hello.py"), "print('ok')")` auto-creates `sub/`, `read_file(Path("missing.txt"))` raises `FileNotFoundError`, and two distinct mock `ctx.state` dicts provision two independent sandboxes without emitting `DeprecationWarning`.
