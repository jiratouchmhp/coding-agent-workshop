"""Lightweight non-root HTTP runner for the BYOC Coding Sandbox (port 8080).

Exposes:
- ``GET /health`` (and ``GET /``): liveness & runtime metadata probe.
- ``POST /exec``: executes a bash command confined to ``/workspace`` with
  strict timeout enforcement, process-group cleanup, stream truncation caps,
  and structured JSON output matching Agent Platform Shell Sandbox semantics:
  ``{"stdout": str, "stderr": str, "returncode": int, "duration_ms": int}``.

Security properties:
- Designed to run strictly as non-root ``USER appuser`` inside gVisor.
- Zero ``sudo``, zero hardcoded credentials, zero third-party web server deps.
- Rejects any ``cwd`` escaping ``SANDBOX_WORKSPACE`` (``/workspace``).
"""

from __future__ import annotations

import getpass
import json
import logging
import os
import platform
import signal
import subprocess
import time
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger("sandbox_runner")

WORKSPACE_ROOT = Path(os.environ.get("SANDBOX_WORKSPACE", "/workspace")).resolve()
HOST = os.environ.get("SANDBOX_HOST", "0.0.0.0")
PORT = int(os.environ.get("SANDBOX_PORT", os.environ.get("PORT", "8080")))
DEFAULT_TIMEOUT_SECONDS = float(os.environ.get("SANDBOX_DEFAULT_TIMEOUT", "60"))
MAX_TIMEOUT_SECONDS = float(os.environ.get("SANDBOX_MAX_TIMEOUT", "300"))
MAX_REQUEST_BYTES = int(os.environ.get("SANDBOX_MAX_REQUEST_BYTES", str(2 * 1024 * 1024)))
MAX_OUTPUT_BYTES = int(os.environ.get("SANDBOX_MAX_OUTPUT_BYTES", str(1024 * 1024)))

# Allowlist of safe non-credential environment variables forwarded to child shells.
SAFE_ENV_KEYS = (
    "PATH",
    "HOME",
    "USER",
    "LOGNAME",
    "SHELL",
    "LANG",
    "LC_ALL",
    "TERM",
    "TMPDIR",
    "PYTHONUNBUFFERED",
    "PYTHONDONTWRITEBYTECODE",
    "PYTHONPATH",
    "NODE_ENV",
)


def _resolve_confined_cwd(raw_cwd: str | None) -> Path:
    """Resolve ``raw_cwd`` and verify it stays strictly within ``WORKSPACE_ROOT``."""
    if not raw_cwd:
        return WORKSPACE_ROOT
    candidate = Path(raw_cwd)
    if not candidate.is_absolute():
        candidate = WORKSPACE_ROOT / candidate
    resolved = candidate.resolve()
    if not resolved.is_relative_to(WORKSPACE_ROOT):
        raise ValueError(
            f"Requested cwd {raw_cwd!r} escapes confined workspace {str(WORKSPACE_ROOT)!r}."
        )
    if not resolved.exists() or not resolved.is_dir():
        raise ValueError(f"Requested cwd {str(resolved)!r} does not exist or is not a directory.")
    return resolved


def _clamp_timeout(raw_timeout: Any) -> float:
    if raw_timeout is None:
        return DEFAULT_TIMEOUT_SECONDS
    try:
        value = float(raw_timeout)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"Invalid timeout value: {raw_timeout!r}") from exc
    if value <= 0:
        raise ValueError("timeout must be > 0 seconds.")
    return min(value, MAX_TIMEOUT_SECONDS)


def _truncate_text(text: str, max_bytes: int = MAX_OUTPUT_BYTES) -> str:
    encoded = text.encode("utf-8", errors="replace")
    if len(encoded) <= max_bytes:
        return text
    truncated = encoded[:max_bytes].decode("utf-8", errors="ignore")
    return f"{truncated}\n...[runner truncated output at {max_bytes} bytes]"


def _build_child_env() -> dict[str, str]:
    env = {k: os.environ[k] for k in SAFE_ENV_KEYS if k in os.environ}
    env.setdefault("HOME", f"/home/{getpass.getuser()}")
    env.setdefault("USER", getpass.getuser())
    env.setdefault("PATH", "/usr/local/bin:/usr/bin:/bin")
    return env


def execute_command(command: str, cwd: Path, timeout_seconds: float) -> dict[str, Any]:
    """Run ``command`` in a fresh non-root bash process group with hard timeout cleanup."""
    start = time.monotonic()
    # Use non-login `-c` so Debian `/etc/profile` does not reset `_build_child_env()` PATH.
    proc = subprocess.Popen(
        ["/bin/bash", "-c", command],
        cwd=str(cwd),
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        encoding="utf-8",
        errors="replace",
        start_new_session=True,
        env=_build_child_env(),
    )
    try:
        stdout, stderr = proc.communicate(timeout=timeout_seconds)
        returncode = int(proc.returncode)
    except subprocess.TimeoutExpired:
        # Terminate entire process group cleanly, then escalate to SIGKILL.
        try:
            os.killpg(proc.pid, signal.SIGTERM)
        except ProcessLookupError:
            pass
        try:
            stdout, stderr = proc.communicate(timeout=3)
        except subprocess.TimeoutExpired:
            try:
                os.killpg(proc.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
            stdout, stderr = proc.communicate()
        timeout_note = f"\n[runner] command timed out after {timeout_seconds:.1f}s"
        stderr = f"{stderr or ''}{timeout_note}".lstrip("\n")
        returncode = 124

    duration_ms = max(0, int((time.monotonic() - start) * 1000))
    return {
        "stdout": _truncate_text(stdout or ""),
        "stderr": _truncate_text(stderr or ""),
        "returncode": returncode,
        "duration_ms": duration_ms,
    }


class SandboxRequestHandler(BaseHTTPRequestHandler):
    """Minimal HTTP handler exposing ``GET /health`` and ``POST /exec``."""

    server_version = "CodingSandboxRunner/1.0"

    def log_message(self, format: str, *args: Any) -> None:  # noqa: A002
        logger.info("%s - %s", self.address_string(), format % args)

    def _send_json(self, status: HTTPStatus, payload: dict[str, Any]) -> None:
        body = json.dumps(payload).encode("utf-8")
        self.send_response(int(status))
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self) -> None:  # noqa: N802
        path = self.path.split("?", 1)[0]
        if path in {"/health", "/"}:
            self._send_json(
                HTTPStatus.OK,
                {
                    "status": "ok",
                    "user": getpass.getuser(),
                    "uid": os.getuid(),
                    "workspace": str(WORKSPACE_ROOT),
                    "python": platform.python_version(),
                },
            )
            return
        self._send_json(HTTPStatus.NOT_FOUND, {"error": f"Unknown endpoint: {path}"})

    def do_POST(self) -> None:  # noqa: N802
        path = self.path.split("?", 1)[0]
        if path != "/exec":
            self._send_json(HTTPStatus.NOT_FOUND, {"error": f"Unknown endpoint: {path}"})
            return

        content_length_raw = self.headers.get("Content-Length", "0")
        try:
            content_length = int(content_length_raw)
        except ValueError:
            self._send_json(HTTPStatus.BAD_REQUEST, {"error": "Invalid Content-Length header."})
            return

        if content_length <= 0 or content_length > MAX_REQUEST_BYTES:
            self._send_json(
                HTTPStatus.BAD_REQUEST,
                {"error": f"Request body size must be between 1 and {MAX_REQUEST_BYTES} bytes."},
            )
            return

        raw_body = self.rfile.read(content_length)
        try:
            payload = json.loads(raw_body.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            self._send_json(HTTPStatus.BAD_REQUEST, {"error": f"Invalid JSON payload: {exc}"})
            return

        if not isinstance(payload, dict):
            self._send_json(HTTPStatus.BAD_REQUEST, {"error": "JSON payload must be an object."})
            return

        command = payload.get("command")
        if not isinstance(command, str) or not command.strip():
            self._send_json(
                HTTPStatus.BAD_REQUEST,
                {"error": "Field 'command' must be a non-empty string."},
            )
            return

        try:
            cwd = _resolve_confined_cwd(payload.get("cwd"))
            timeout_seconds = _clamp_timeout(payload.get("timeout"))
        except ValueError as exc:
            self._send_json(HTTPStatus.BAD_REQUEST, {"error": str(exc)})
            return

        result = execute_command(command=command, cwd=cwd, timeout_seconds=timeout_seconds)
        self._send_json(HTTPStatus.OK, result)


def serve() -> None:
    WORKSPACE_ROOT.mkdir(parents=True, exist_ok=True)
    if os.getuid() == 0:
        logger.warning("Runner detected UID 0 (root); production BYOC images must run as non-root appuser.")
    server = ThreadingHTTPServer((HOST, PORT), SandboxRequestHandler)
    logger.info(
        "BYOC sandbox runner listening on http://%s:%s (user=%s, workspace=%s)",
        HOST,
        PORT,
        getpass.getuser(),
        WORKSPACE_ROOT,
    )
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        logger.info("Shutting down BYOC sandbox runner.")
    finally:
        server.server_close()


if __name__ == "__main__":
    serve()
