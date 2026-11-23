"""Managed Sandbox Execution Paths & Custom ADK BaseEnvironment (complete solution — Lab 2).

Covers ALL FOUR verified execution adapters on Gemini Enterprise Agent Platform:
- **Path A — Shell Sandbox (`execute_bash()` via `/exec`):**
  Uses caller ADC/IAM automatically (`aiplatform.sandboxEnvironments.execute`).
  NOTE: ``execute_code()`` targets Code Execution sandboxes (Python/JS payloads),
  and ``send_command()`` + ``generate_access_token()`` is the Computer Use / BYOC
  HTTP data-plane API — Shell sandboxes use ``execute_bash()``. Each call
  runs as unprivileged ``appuser`` in a fresh stateless shell under ``/workspace``
  (chain ``cd ... && ...`` in a single call or persist files under ``/workspace``).
- **Path B — BYOC Custom Container (`/exec` runner):**
  Calls the custom container's HTTP ``/exec`` endpoint (port 8080) either through
  the managed data-plane proxy (``generate_access_token`` + ``send_command``) or
  directly over local Docker / private VPC PSC-E with short-lived access-token or
  IAM bearer auth, returning ``{stdout, stderr, returncode, duration_ms}``.
- **Path C — Code Execution Sandbox (`execute_code()` & ADK `AgentEngineSandboxCodeExecutor`):**
  Safe ``Chunk`` response parsing (avoiding the doc quickstart ``b64decode`` bug)
  plus ADK ``AgentEngineSandboxCodeExecutor(sandbox_resource_name=... | agent_engine_resource_name=...)``.
- **Path D — `AgentPlatformSandboxEnvironment(BaseEnvironment)` (ADK Python 2.0+):**
  Implements the 3 exact ``BaseEnvironment`` abstract methods (``execute``,
  ``read_file``, ``write_file``) with ``EnvironmentScope.SESSION`` and mandatory
  ``*, ctx: Context | None = None`` so ADK ``EnvironmentToolset`` (including
  ``EditFileTool``, which layers on top of ``read_file`` + ``write_file``) operates
  transparently inside a per-session gVisor Managed Sandbox.
"""

from __future__ import annotations

import argparse
import asyncio
import base64
import json
import logging
import posixpath
import shlex
import sys
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path, PurePosixPath
from typing import TYPE_CHECKING, Any, Literal

import httpx
from google.adk.environment import BaseEnvironment, EnvironmentScope, ExecutionResult
from typing_extensions import override

from coding_agent.config import get_settings
from coding_agent.tools.sandbox_lifecycle import (
    SandboxLifecycleManager,
    _infer_parent_instance,
    build_platform_client,
    get_sandboxes_namespace,
)

if TYPE_CHECKING:
    from google.adk.agents.context import Context

logger = logging.getLogger(__name__)

# Sentinel exit code used by read_file() helper script inside sandbox to signal FileNotFoundError
_MISSING_FILE_EXIT_CODE = 44
_WRITE_CHUNK_BYTES = 24_576  # Keeps base64 shell commands safely below OS ARG_MAX limits


# ---------------------------------------------------------------------------
# Structured Execution Outputs & Workspace Path Confinement
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class CommandExecutionOutput:
    """Structured response aligned with Managed Shell & BYOC ``/exec`` schema."""

    stdout: str
    stderr: str
    returncode: int
    duration_ms: int
    timed_out: bool = False

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class CodeExecutionOutput:
    """Structured output parsed safely from ``execute_code()`` ``Chunk`` outputs."""

    stdout: str
    stderr: str
    files: list[dict[str, Any]] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "stdout": self.stdout,
            "stderr": self.stderr,
            "files": [
                {
                    "name": f.get("name"),
                    "mime_type": f.get("mime_type"),
                    "size_bytes": len(f.get("content", b"")),
                }
                for f in self.files
            ],
        }


def resolve_sandbox_path(path: Path | str, working_dir: Path = Path("/workspace")) -> PurePosixPath:
    """Resolve ``path`` strictly inside ``working_dir`` and block path traversal."""
    root_str = posixpath.normpath(str(working_dir))
    raw_str = str(path)
    joined = raw_str if raw_str.startswith("/") else posixpath.join(root_str, raw_str)
    normalized = posixpath.normpath(joined)
    if normalized != root_str and not normalized.startswith(root_str.rstrip("/") + "/"):
        raise ValueError(
            f"Path {str(path)!r} resolves to {normalized!r}, which escapes sandbox "
            f"working directory {root_str!r}."
        )
    return PurePosixPath(normalized)


def _normalize_command_response(raw: Any, elapsed_ms: int) -> CommandExecutionOutput:
    """Convert a dict or HTTP/SDK response object into ``CommandExecutionOutput``."""
    data: dict[str, Any]
    if isinstance(raw, dict):
        data = raw
    else:
        status_code = getattr(raw, "status_code", None)
        body = getattr(raw, "body", None)
        if body is None:
            body = getattr(raw, "text", None)
        if isinstance(body, (bytes, bytearray)):
            body_text = body.decode("utf-8", errors="replace")
        elif isinstance(body, str):
            body_text = body
        else:
            body_text = None

        if isinstance(status_code, int) and status_code >= 400:
            preview = (body_text or repr(raw))[:400]
            raise RuntimeError(
                f"Sandbox runner returned HTTP {status_code}: {preview}"
            )

        if isinstance(body, dict):
            data = body
        elif body_text is not None:
            stripped = body_text.strip()
            if not stripped:
                raise RuntimeError(
                    f"Sandbox runner returned an empty response body "
                    f"(status_code={status_code!r}, raw={raw!r}). "
                    "Verify the BYOC sandbox access token (use generate_access_token with "
                    "service_account_email) and confirm port 8080 /exec is listening."
                )
            try:
                parsed = json.loads(stripped)
            except json.JSONDecodeError as exc:
                raise RuntimeError(
                    f"Sandbox runner returned non-JSON body (status_code={status_code!r}): "
                    f"{stripped[:400]!r}"
                ) from exc
            if not isinstance(parsed, dict):
                raise RuntimeError(f"Expected JSON object from sandbox runner, got {type(parsed).__name__}")
            data = parsed
        else:
            data = {
                "stdout": getattr(raw, "stdout", ""),
                "stderr": getattr(raw, "stderr", ""),
                "returncode": getattr(raw, "returncode", 0),
                "duration_ms": getattr(raw, "duration_ms", elapsed_ms),
            }
    returncode = int(data.get("returncode", 0))
    stderr = str(data.get("stderr", ""))
    timed_out = bool(data.get("timed_out", False)) or (
        returncode == 124 and "timed out" in stderr.lower()
    )
    return CommandExecutionOutput(
        stdout=str(data.get("stdout", "")),
        stderr=stderr,
        returncode=returncode,
        duration_ms=int(data.get("duration_ms", elapsed_ms)),
        timed_out=timed_out,
    )


# ---------------------------------------------------------------------------
# Path A: Managed Shell Sandbox Execution (`execute_bash` -> `/exec`)
# ---------------------------------------------------------------------------


def execute_shell_command(
    client: Any,
    sandbox_name: str,
    command: str,
    *,
    cwd: str = "/workspace",
    timeout: int | float | None = None,
) -> CommandExecutionOutput:
    """Execute a bash command inside a Managed Shell Sandbox via ``execute_bash()``.

    Why ``execute_bash()`` (and NOT ``execute_code()`` or Code-Exec/Computer-Use ``send_command()``):
    - Shell sandboxes expose IAM-authenticated ``/exec``; ``execute_code()`` targets
      Code Execution sandboxes (Python/JS), and ``send_command()`` + ``generate_access_token()``
      is the HTTP data-plane API used for Computer Use / BYOC containers (Path B).
    - ``execute_bash()`` uses caller ADC/IAM automatically (``roles/aiplatform.user``).
    - Runs as unprivileged ``appuser`` (no ``sudo``, no metadata server) in a fresh
      stateless shell per call under ``/workspace`` — chain ``cd`` & env vars in one
      command or write state to files under ``/workspace``.
    """
    sandboxes_ns = get_sandboxes_namespace(client)
    kwargs: dict[str, Any] = {
        "name": sandbox_name,
        "command": command,
        "cwd": cwd,
    }
    if timeout is not None:
        kwargs["timeout"] = max(1, int(timeout))

    start = time.monotonic()
    raw_result = sandboxes_ns.execute_bash(**kwargs)
    elapsed_ms = max(0, int((time.monotonic() - start) * 1000))
    return _normalize_command_response(raw_result, elapsed_ms)


# ---------------------------------------------------------------------------
# Path B: BYOC Custom Container Execution (`/exec` with Short-Lived / IAM Auth)
# ---------------------------------------------------------------------------


def generate_sandbox_access_token(client: Any, service_account_email: str) -> str:
    """Mint a short-lived sandbox data-plane JWT via ``generate_access_token()``.

    Requires:
    - Caller holds ``roles/aiplatform.user`` and ``roles/iam.serviceAccountTokenCreator``
      on ``service_account_email``.
    - Audited in Cloud Audit Logs (``DATA_WRITE``) as ``AuthorizeSandboxEnvironmentAccess``.
    """
    sandboxes_ns = get_sandboxes_namespace(client)
    token = sandboxes_ns.generate_access_token(service_account_email=service_account_email)
    return str(token)


def fetch_iam_bearer_token() -> str:
    """Fetch a short-lived Google Cloud OAuth 2.0 bearer token from ADC."""
    import google.auth
    from google.auth.transport.requests import Request

    credentials, _ = google.auth.default(
        scopes=["https://www.googleapis.com/auth/cloud-platform"]
    )
    if not credentials.valid:
        credentials.refresh(Request())
    return str(credentials.token)


def execute_byoc_command(
    *,
    command: str,
    cwd: str = "/workspace",
    timeout: int | float = 60,
    env: dict[str, str] | None = None,
    client: Any | None = None,
    sandbox_name: str | None = None,
    service_account_email: str | None = None,
    access_token: str | None = None,
    runner_base_url: str | None = None,
    use_iam_bearer: bool = False,
) -> CommandExecutionOutput:
    """Execute a command against a BYOC Custom Container's ``/exec`` runner endpoint.

    Supports two verified transports:
    1. **Direct HTTP `/exec`** (when ``runner_base_url`` is set — e.g. private VPC PSC-E
       forwarding rule or local Docker test ``http://127.0.0.1:8080``) with optional
       short-lived sandbox access token or ADC IAM ``Authorization: Bearer ...`` header.
    2. **Managed Sandbox Data-Plane Proxy** (when ``client`` and ``sandbox_name`` are set):
       mints a short-lived token via ``generate_sandbox_access_token()`` (if not passed)
       and invokes ``sandboxes.send_command(http_method="POST", path="exec",
       access_token=..., request_dict=..., sandbox_environment=...)``.

    Optional ``env`` forwards an allowlisted per-exec ephemeral env dict to the
    sandbox runner's child process (never logged or persisted to disk).
    """
    start = time.monotonic()
    payload: dict[str, Any] = {
        "command": command,
        "cwd": cwd,
        "timeout": max(1, int(timeout)),
    }
    if env:
        payload["env"] = dict(env)

    if runner_base_url:
        headers: dict[str, str] = {"Content-Type": "application/json"}
        bearer = access_token
        if not bearer and use_iam_bearer:
            bearer = fetch_iam_bearer_token()
        if bearer:
            headers["Authorization"] = f"Bearer {bearer}"

        endpoint = f"{runner_base_url.rstrip('/')}/exec"
        http_timeout = max(float(timeout) + 10.0, 15.0)
        with httpx.Client(timeout=http_timeout) as http_client:
            resp = http_client.post(endpoint, json=payload, headers=headers)
            resp.raise_for_status()
            elapsed_ms = max(0, int((time.monotonic() - start) * 1000))
            return _normalize_command_response(resp.json(), elapsed_ms)

    if client is None or not sandbox_name:
        raise ValueError(
            "execute_byoc_command() requires either `runner_base_url` OR both "
            "`client` and `sandbox_name`."
        )

    sandboxes_ns = get_sandboxes_namespace(client)
    sandbox_env = sandboxes_ns.get(name=sandbox_name)

    token = access_token
    if not token:
        if service_account_email:
            token = generate_sandbox_access_token(client, service_account_email)
        elif use_iam_bearer:
            token = fetch_iam_bearer_token()
        else:
            raise ValueError(
                "Managed BYOC data-plane execution requires `access_token`, "
                "`service_account_email` (for generate_access_token), or `use_iam_bearer=True`."
            )

    raw_response = sandboxes_ns.send_command(
        http_method="POST",
        path="exec",
        access_token=token,
        request_dict=payload,
        sandbox_environment=sandbox_env,
    )
    elapsed_ms = max(0, int((time.monotonic() - start) * 1000))
    return _normalize_command_response(raw_response, elapsed_ms)


# ---------------------------------------------------------------------------
# Path C: Code Execution Sandbox (`execute_code` & ADK `AgentEngineSandboxCodeExecutor`)
# ---------------------------------------------------------------------------


def execute_code_snippet(
    client: Any,
    sandbox_name: str,
    code: str,
    *,
    files: list[dict[str, Any]] | None = None,
) -> CodeExecutionOutput:
    """Execute Python/JavaScript in a Code Execution sandbox and safely parse ``Chunk`` outputs.

    Avoids the documented quickstart bug (``output_file_content.b64decode(...)``):
    JSON chunks carry ``{"msg_out": "...", "msg_err": "..."}`` in UTF-8 ``chunk.data``,
    and output files arrive as separate ``Chunk`` items with ``chunk.attributes["file_name"]``
    and raw bytes in ``chunk.data``.
    """
    sandboxes_ns = get_sandboxes_namespace(client)
    input_data: dict[str, Any] = {"code": code}
    if files:
        input_data["files"] = files

    response = sandboxes_ns.execute_code(name=sandbox_name, input_data=input_data)

    stdout_parts: list[str] = []
    stderr_parts: list[str] = []
    output_files: list[dict[str, Any]] = []

    for chunk in getattr(response, "outputs", None) or []:
        mime_type = str(getattr(chunk, "mime_type", "") or "")
        raw_data = getattr(chunk, "data", b"") or b""
        if mime_type == "application/json":
            decoded = raw_data.decode("utf-8", errors="replace") if isinstance(raw_data, (bytes, bytearray)) else str(raw_data)
            status = json.loads(decoded)
            if status.get("msg_out"):
                stdout_parts.append(str(status["msg_out"]))
            if status.get("msg_err"):
                stderr_parts.append(str(status["msg_err"]))
        else:
            attrs = getattr(chunk, "attributes", None) or {}
            output_files.append(
                {
                    "name": attrs.get("file_name", ""),
                    "mime_type": mime_type,
                    "content": bytes(raw_data) if isinstance(raw_data, (bytes, bytearray)) else str(raw_data).encode("utf-8"),
                }
            )

    return CodeExecutionOutput(
        stdout="".join(stdout_parts),
        stderr="".join(stderr_parts),
        files=output_files,
    )


def build_code_execution_executor(
    *,
    sandbox_resource_name: str | None = None,
    agent_engine_resource_name: str | None = None,
) -> Any:
    """Build ADK's ``AgentEngineSandboxCodeExecutor`` (ADK Python 2.0+).

    Pass EITHER:
    - ``sandbox_resource_name``: reuse a specific pre-created Code Execution sandbox, OR
    - ``agent_engine_resource_name``: let ADK auto-create one persistent sandbox per session.
    """
    from google.adk.code_executors.agent_engine_sandbox_code_executor import (
        AgentEngineSandboxCodeExecutor,
    )

    if sandbox_resource_name:
        return AgentEngineSandboxCodeExecutor(sandbox_resource_name=sandbox_resource_name)
    if agent_engine_resource_name:
        return AgentEngineSandboxCodeExecutor(
            agent_engine_resource_name=agent_engine_resource_name
        )
    raise ValueError(
        "build_code_execution_executor() requires either `sandbox_resource_name` "
        "or `agent_engine_resource_name` (REASONING_ENGINE_NAME)."
    )


# ---------------------------------------------------------------------------
# Path D: Custom ADK BaseEnvironment for Remote Managed Sandboxes (ADK Python 2.0+)
# ---------------------------------------------------------------------------


class AgentPlatformSandboxEnvironment(BaseEnvironment):
    """ADK ``BaseEnvironment`` backed by a per-session Agent Platform Managed Sandbox.

    Source-verified ``google/adk-python`` rules:
    1. Exactly **3 abstract methods**: ``execute``, ``read_file``, ``write_file``.
       (ADK ``EditFileTool`` implements surgical edits on top of ``read_file`` + ``write_file``.)
    2. Mandatory ``*, ctx: Context | None = None`` on ``initialize``, ``execute``,
       ``read_file``, and ``write_file`` to avoid ``DeprecationWarning`` and access ``ctx.state``.
    3. ``scope`` returns ``EnvironmentScope.SESSION``. NEVER short-circuit ``initialize()``
       on ``if self._is_initialized: return`` because a single instance serves many sessions!
    """

    STATE_KEY = "agent_platform:sandbox_name"

    def __init__(
        self,
        *,
        project_id: str,
        location: str,
        instance_name: str,
        template_name: str | None = None,
        sandbox_name: str | None = None,
        mode: Literal["shell", "byoc"] = "shell",
        working_dir: Path = Path("/workspace"),
        ttl: str = "3600s",
        service_account_email: str | None = None,
        runner_base_url: str | None = None,
        delete_on_close: bool = False,
        client: Any | None = None,
    ) -> None:
        self._project_id = project_id
        self._location = location
        self._instance_name = instance_name
        self._template_name = template_name
        self._fixed_sandbox_name = sandbox_name
        self._mode = mode
        self._working_dir = working_dir
        self._ttl = ttl
        self._service_account_email = service_account_email
        self._runner_base_url = runner_base_url
        self._delete_on_close = delete_on_close
        self._client = client
        self._fallback_sandbox_name: str | None = sandbox_name
        self._created_sandboxes: list[str] = []

    def _get_client(self) -> Any:
        if self._client is None:
            self._client = build_platform_client(
                project_id=self._project_id,
                location=self._location,
                api_version="v1beta1",
            )
        return self._client

    def _get_active_sandbox_name(self, ctx: Context | None) -> str | None:
        if ctx is not None:
            state = getattr(ctx, "state", None)
            if state is not None and state.get(self.STATE_KEY):
                return str(state[self.STATE_KEY])
        return self._fallback_sandbox_name

    def _store_active_sandbox_name(self, sandbox_name: str, ctx: Context | None) -> None:
        if ctx is not None:
            state = getattr(ctx, "state", None)
            if state is not None:
                state[self.STATE_KEY] = sandbox_name
                return
        self._fallback_sandbox_name = sandbox_name

    @property
    @override
    def scope(self) -> EnvironmentScope:
        return EnvironmentScope.SESSION

    @property
    @override
    def working_dir(self) -> Path | None:
        # Must return a fixed logical path without taking `ctx`
        return self._working_dir

    @override
    async def initialize(self, *, ctx: Context | None = None) -> None:
        """Ensure the current session has a live Managed Sandbox recorded in ``ctx.state``."""
        # CRITICAL: Do NOT short-circuit on `if self._is_initialized: return`!
        # Always check `ctx.state.get(self.STATE_KEY)` per session.
        if self._runner_base_url:
            self._is_initialized = True
            return

        if self._get_active_sandbox_name(ctx):
            self._is_initialized = True
            return

        if self._fixed_sandbox_name:
            self._store_active_sandbox_name(self._fixed_sandbox_name, ctx)
            self._is_initialized = True
            return

        if self._mode == "byoc" and not self._template_name:
            raise ValueError(
                "BYOC mode requires `template_name` (SANDBOX_TEMPLATE_NAME), "
                "a pre-created `sandbox_name`, or `runner_base_url`."
            )

        def _provision() -> str:
            resolved_parent = (
                (_infer_parent_instance(self._template_name) if self._template_name else "")
                or self._instance_name
                or None
            )
            manager = SandboxLifecycleManager(
                project_id=self._project_id,
                location=self._location,
                instance_name=resolved_parent,
                client=self._get_client(),
            )
            parent = manager.ensure_parent_instance(display_name="coding-agent-sandbox-parent")
            self._instance_name = parent
            # Only pass inline `spec` when no template is configured so an explicit template
            # never collides with an inline `spec`.
            spec = None if self._template_name else ({"shell_environment": {}} if self._mode == "shell" else None)
            created = manager.create_sandbox(
                display_name=f"coding-agent-{self._mode}-session",
                template_name=self._template_name,
                spec=spec,
                ttl=self._ttl,
                wait_for_completion=True,
                instance_name=parent,
            )
            return created.name

        sandbox_name = await asyncio.to_thread(_provision)
        self._created_sandboxes.append(sandbox_name)
        self._store_active_sandbox_name(sandbox_name, ctx)
        self._is_initialized = True
        logger.info("Bound session to Managed Sandbox: %s", sandbox_name)

    @override
    async def execute(
        self,
        command: str,
        *,
        timeout: float | None = None,
        ctx: Context | None = None,
    ) -> ExecutionResult:
        """Execute a shell command inside the session's Managed Sandbox."""
        await self.initialize(ctx=ctx)
        cwd_str = str(self._working_dir)

        if self._mode == "byoc" or self._runner_base_url:
            sandbox_name = self._get_active_sandbox_name(ctx)
            client = None if self._runner_base_url else self._get_client()
            out = await asyncio.to_thread(
                execute_byoc_command,
                command=command,
                cwd=cwd_str,
                timeout=timeout if timeout is not None else 60,
                client=client,
                sandbox_name=sandbox_name,
                service_account_email=self._service_account_email,
                runner_base_url=self._runner_base_url,
            )
        else:
            sandbox_name = self._get_active_sandbox_name(ctx)
            if not sandbox_name:
                raise RuntimeError("No active Managed Sandbox found after initialize().")
            out = await asyncio.to_thread(
                execute_shell_command,
                self._get_client(),
                sandbox_name,
                command,
                cwd=cwd_str,
                timeout=timeout,
            )

        return ExecutionResult(
            exit_code=out.returncode,
            stdout=out.stdout,
            stderr=out.stderr,
            timed_out=out.timed_out,
        )

    async def execute_with_env(
        self,
        command: str,
        *,
        env: dict[str, str] | None = None,
        timeout: float | None = None,
        ctx: Context | None = None,
    ) -> ExecutionResult:
        """Execute a command with optional allowlisted ephemeral ``env`` inside a BYOC sandbox.

        Keeps the ADK ``BaseEnvironment.execute(...)`` override signature untouched while
        allowing harnesses (such as ``AgyHeadlessHarness``) to forward scoped per-exec
        environment variables to the BYOC ``/exec`` runner without writing them to disk.
        """
        if not env:
            return await self.execute(command, timeout=timeout, ctx=ctx)

        if self._mode != "byoc" and not self._runner_base_url:
            raise ValueError(
                "Per-exec ephemeral env injection requires SANDBOX_MODE=byoc (custom /exec "
                "runner); Managed Shell sandboxes do not accept /exec env payloads."
            )

        await self.initialize(ctx=ctx)
        cwd_str = str(self._working_dir)
        sandbox_name = self._get_active_sandbox_name(ctx)
        client = None if self._runner_base_url else self._get_client()
        out = await asyncio.to_thread(
            execute_byoc_command,
            command=command,
            cwd=cwd_str,
            timeout=timeout if timeout is not None else 60,
            env=env,
            client=client,
            sandbox_name=sandbox_name,
            service_account_email=self._service_account_email,
            runner_base_url=self._runner_base_url,
        )
        return ExecutionResult(
            exit_code=out.returncode,
            stdout=out.stdout,
            stderr=out.stderr,
            timed_out=out.timed_out,
        )

    async def check_byoc_health(self, *, ctx: Context | None = None) -> dict[str, Any] | None:
        """Query the BYOC runner's ``GET /health`` metadata (including ``agy_cli_available``)."""
        if self._mode != "byoc" and not self._runner_base_url:
            return None

        if self._runner_base_url:
            endpoint = f"{self._runner_base_url.rstrip('/')}/health"

            def _fetch_direct() -> dict[str, Any]:
                with httpx.Client(timeout=5.0) as http_client:
                    resp = http_client.get(endpoint)
                    resp.raise_for_status()
                    data = resp.json()
                    return data if isinstance(data, dict) else {}

            try:
                return await asyncio.to_thread(_fetch_direct)
            except Exception as exc:
                logger.debug("Direct BYOC /health probe failed (%s).", exc)
                return None

        sandbox_name = self._get_active_sandbox_name(ctx)
        if not sandbox_name:
            return None

        def _fetch_proxied() -> dict[str, Any]:
            client = self._get_client()
            sandboxes_ns = get_sandboxes_namespace(client)
            sandbox_env = sandboxes_ns.get(name=sandbox_name)
            token = (
                generate_sandbox_access_token(client, self._service_account_email)
                if self._service_account_email
                else fetch_iam_bearer_token()
            )
            raw = sandboxes_ns.send_command(
                http_method="GET",
                path="health",
                access_token=token,
                sandbox_environment=sandbox_env,
            )
            body = getattr(raw, "body", raw)
            if isinstance(body, (bytes, bytearray)):
                return json.loads(body.decode("utf-8"))
            if isinstance(body, str):
                return json.loads(body)
            return dict(body) if isinstance(body, dict) else {}

        try:
            return await asyncio.to_thread(_fetch_proxied)
        except Exception as exc:
            logger.debug("Managed BYOC /health probe failed (%s).", exc)
            return None

    @override
    async def read_file(self, path: Path, *, ctx: Context | None = None) -> bytes:
        """Read raw bytes from ``path`` inside the sandbox (raises ``FileNotFoundError`` if missing)."""
        resolved = resolve_sandbox_path(path, self._working_dir)
        py_script = (
            "import base64, pathlib, sys; "
            "p = pathlib.Path(sys.argv[1]); "
            f"sys.exit({_MISSING_FILE_EXIT_CODE}) if not p.is_file() else None; "
            "sys.stdout.write(base64.b64encode(p.read_bytes()).decode('ascii'))"
        )
        cmd = f"python3 -c {shlex.quote(py_script)} {shlex.quote(str(resolved))}"
        res = await self.execute(cmd, ctx=ctx)
        if res.exit_code == _MISSING_FILE_EXIT_CODE:
            raise FileNotFoundError(str(resolved))
        if res.exit_code != 0:
            raise OSError(f"Failed to read {str(resolved)!r} inside sandbox: {res.stderr.strip()}")
        return base64.b64decode(res.stdout.encode("ascii"))

    @override
    async def write_file(
        self,
        path: Path,
        content: str | bytes,
        *,
        ctx: Context | None = None,
    ) -> None:
        """Create parent directories and write ``str`` (UTF-8) or ``bytes`` inside the sandbox."""
        resolved = resolve_sandbox_path(path, self._working_dir)
        raw_bytes = content.encode("utf-8") if isinstance(content, str) else bytes(content)

        # Split large writes into base64 chunks so OS ARG_MAX limits are never exceeded.
        chunks = [
            raw_bytes[i : i + _WRITE_CHUNK_BYTES]
            for i in range(0, len(raw_bytes), _WRITE_CHUNK_BYTES)
        ] or [b""]

        py_script = (
            "import base64, pathlib, sys; "
            "p = pathlib.Path(sys.argv[1]); "
            "mode = sys.argv[2]; "
            "data = base64.b64decode(sys.argv[3].encode('ascii')); "
            "p.parent.mkdir(parents=True, exist_ok=True); "
            "f = p.open(mode); f.write(data); f.close()"
        )

        for idx, chunk in enumerate(chunks):
            file_mode = "wb" if idx == 0 else "ab"
            b64_payload = base64.b64encode(chunk).decode("ascii")
            cmd = (
                f"python3 -c {shlex.quote(py_script)} "
                f"{shlex.quote(str(resolved))} {file_mode} {shlex.quote(b64_payload)}"
            )
            res = await self.execute(cmd, ctx=ctx)
            if res.exit_code != 0:
                raise OSError(
                    f"Failed to write {str(resolved)!r} inside sandbox: {res.stderr.strip()}"
                )

    @override
    async def close(self) -> None:
        """Idempotent cleanup; optionally deletes session sandboxes created by this instance."""
        if self._delete_on_close and self._created_sandboxes:
            manager = SandboxLifecycleManager(
                project_id=self._project_id,
                location=self._location,
                instance_name=self._instance_name,
                client=self._client,
            )
            for name in list(self._created_sandboxes):
                try:
                    await asyncio.to_thread(manager.delete_sandbox, name)
                except Exception as exc:
                    logger.warning("Failed deleting sandbox %s on close: %s", name, exc)
            self._created_sandboxes.clear()
        self._is_initialized = False


# ---------------------------------------------------------------------------
# Isolation Probe & Runnable CLI (`python -m coding_agent.tools.sandbox_execution`)
# ---------------------------------------------------------------------------


ISOLATION_PROBE_COMMAND = (
    "id && whoami && pwd && ls -la /workspace && "
    "(curl -sS --max-time 3 -H 'Metadata-Flavor: Google' "
    "http://169.254.169.254/computeMetadata/v1/instance/service-accounts/default/token "
    "&& echo 'FAIL:METADATA_REACHABLE' || echo 'PASS:METADATA_UNREACHABLE') && "
    "(sudo -n true 2>&1 && echo 'FAIL:SUDO_AVAILABLE' || echo 'PASS:NO_SUDO')"
)


def _build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m coding_agent.tools.sandbox_execution",
        description="Execute commands across Shell, BYOC, and Code Execution Managed Sandboxes.",
    )
    parser.add_argument("--project", help="GCP project ID.")
    parser.add_argument("--location", help="GCP region.")
    sub = parser.add_subparsers(dest="subcommand", required=True)

    p_shell = sub.add_parser("shell", help="Run a command in a Shell Sandbox via execute_bash().")
    p_shell.add_argument("--sandbox-name", required=True)
    p_shell.add_argument("--command", required=True)
    p_shell.add_argument("--cwd", default="/workspace")
    p_shell.add_argument("--timeout", type=int, default=60)

    p_byoc = sub.add_parser("byoc", help="Run a command in a BYOC sandbox /exec runner.")
    p_byoc.add_argument("--command", required=True)
    p_byoc.add_argument("--sandbox-name", default=None)
    p_byoc.add_argument("--service-account", default=None)
    p_byoc.add_argument("--runner-url", default=None)
    p_byoc.add_argument("--use-iam-bearer", action="store_true")
    p_byoc.add_argument("--cwd", default="/workspace")
    p_byoc.add_argument("--timeout", type=int, default=60)

    p_code = sub.add_parser("code", help="Run Python/JS code in a Code Execution sandbox.")
    p_code.add_argument("--sandbox-name", required=True)
    p_code.add_argument("--code", required=True)

    p_probe = sub.add_parser("probe-isolation", help="Verify non-root user & blocked metadata server.")
    p_probe.add_argument("--mode", choices=["shell", "byoc"], default="shell")
    p_probe.add_argument("--sandbox-name", default=None)
    p_probe.add_argument("--service-account", default=None)
    p_probe.add_argument("--runner-url", default=None)

    return parser


def main(argv: list[str] | None = None) -> int:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    args = _build_arg_parser().parse_args(argv)
    settings = get_settings()

    def _get_client() -> Any:
        return build_platform_client(
            project_id=args.project or settings.require_gcp_project(),
            location=args.location or settings.google_cloud_location,
            api_version="v1beta1",
        )

    if args.subcommand == "shell":
        result = execute_shell_command(
            _get_client(),
            args.sandbox_name,
            args.command,
            cwd=args.cwd,
            timeout=args.timeout,
        )
        print(json.dumps(result.to_dict(), indent=2))
        return 0 if result.returncode == 0 else result.returncode

    if args.subcommand == "byoc":
        runner_url = args.runner_url or settings.sandbox_runner_base_url or None
        client = None if runner_url else _get_client()
        result = execute_byoc_command(
            command=args.command,
            cwd=args.cwd,
            timeout=args.timeout,
            client=client,
            sandbox_name=args.sandbox_name or settings.sandbox_resource_name or None,
            service_account_email=args.service_account or settings.sandbox_service_account_email or None,
            runner_base_url=runner_url,
            use_iam_bearer=args.use_iam_bearer,
        )
        print(json.dumps(result.to_dict(), indent=2))
        return 0 if result.returncode == 0 else result.returncode

    if args.subcommand == "code":
        code_res = execute_code_snippet(_get_client(), args.sandbox_name, args.code)
        print(json.dumps(code_res.to_dict(), indent=2))
        return 0

    if args.subcommand == "probe-isolation":
        if args.mode == "shell":
            sandbox_name = args.sandbox_name or settings.sandbox_resource_name
            if not sandbox_name:
                raise ValueError("--sandbox-name (or SANDBOX_RESOURCE_NAME) is required.")
            result = execute_shell_command(_get_client(), sandbox_name, ISOLATION_PROBE_COMMAND)
        else:
            runner_url = args.runner_url or settings.sandbox_runner_base_url or None
            client = None if runner_url else _get_client()
            result = execute_byoc_command(
                command=ISOLATION_PROBE_COMMAND,
                client=client,
                sandbox_name=args.sandbox_name or settings.sandbox_resource_name or None,
                service_account_email=args.service_account or settings.sandbox_service_account_email or None,
                runner_base_url=runner_url,
            )
        print(json.dumps(result.to_dict(), indent=2))
        passed = (
            "PASS:METADATA_UNREACHABLE" in result.stdout
            and "PASS:NO_SUDO" in result.stdout
            and "FAIL:" not in result.stdout
        )
        return 0 if passed else 1

    return 1


if __name__ == "__main__":
    sys.exit(main())
