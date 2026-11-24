"""Antigravity (``agy``) Headless CLI Coding Harness (starter track).

Complete the 2 crisp Lab 1 checkpoints in this module:
1. ``build_agy_command()`` — assemble the verified ``agy`` headless CLI flags.
2. ``parse_agy_stream_json()`` — parse NDJSON events, extract ``response_text``,
   ``conversation_id``, ``tool_calls``, ``token_usage``, ``agy_error``, and map
   the 4-tier ``AgyExitCode`` contract (setting ``should_retry_or_fallback``
   strictly for ``AgyExitCode.AGENT_ERROR`` = 3).

All dataclasses, local/sandbox execution runners, OTel instrumentation,
dry-run simulation, ADK tool wrapper, and CLI entrypoint are pre-filled.

Enterprise Auth & ToS Boundary:
- **NEVER proxy or relay a developer's personal ``agy`` OAuth credentials inside a
  multi-tenant service.**
- On **Agent Runtime**, authenticate with ``AGY_ADC_AUTH=true`` using the runtime's
  dedicated least-privilege Service Account (``coding-agent-runtime-sa``), OR use native
  ADK 2.0 ``LlmAgent`` / ``ManagedAgent`` / ``google-antigravity`` SDK.
- Inside **gVisor Managed Sandboxes** (zero IAM roles, metadata server blocked), either
  pass only scoped ephemeral credentials/API key from Secret Manager per-exec via the
  allowlisted ``POST /exec`` ``env`` field (when egress is explicitly permitted via PSC-I +
  Cloud NGFW/SWP), OR run ``agy`` inside the trusted Agent Runtime while routing untrusted
  ``pytest`` / ``ruff`` / ``bandit`` commands to the air-gapped gVisor Sandbox.
"""

from __future__ import annotations

import argparse
import asyncio
import contextlib
import json
import logging
import os
import re
import shlex
import shutil
import sys
import time
from collections.abc import Iterator, Mapping
from dataclasses import asdict, dataclass, field
from enum import IntEnum
from pathlib import Path
from typing import Any, Literal

from coding_agent.config import Settings, get_settings

try:
    from opentelemetry import trace as _otel_trace
except ImportError:  # pragma: no cover - allows stdlib-only dry-run CLI execution
    _otel_trace = None  # type: ignore[assignment]

__all__ = [
    "ALLOWED_SANDBOX_AGY_ENV_KEYS",
    "AgyExecutionMode",
    "AgyExitCode",
    "AgyHeadlessConfig",
    "AgyHeadlessHarness",
    "AgyRunResult",
    "FALLBACK_MODEL_MAP",
    "build_agy_command",
    "build_agy_headless_tool",
    "build_local_agy_env",
    "build_sandbox_agy_env",
    "parse_agy_stream_json",
]

logger = logging.getLogger(__name__)

AgyExecutionMode = Literal["local", "sandbox", "auto"]
AgyOutputFormat = Literal["stream-json", "json", "text"]

ALLOWED_SANDBOX_AGY_ENV_KEYS: frozenset[str] = frozenset(
    {
        "AGY_ADC_AUTH",
        "AGY_CLI_DISABLE_AUTO_UPDATE",
        "GOOGLE_CLOUD_PROJECT",
        "GOOGLE_CLOUD_LOCATION",
        "GOOGLE_CLOUD_QUOTA_PROJECT",
        "GEMINI_API_KEY",
    }
)

FALLBACK_MODEL_MAP: dict[str, str] = {
    "gemini-4-neon": "gemini-4-hydrogen",
}

_DURATION_PART_RE = re.compile(r"(\d+(?:\.\d+)?)\s*(ms|s|m|h)", re.IGNORECASE)
_AGY_ERROR_RE = re.compile(r"AGY_ERROR\s*[:=]\s*(.+)")


class AgyExitCode(IntEnum):
    """Verified 4-tier exit-code contract for the Antigravity (``agy``) headless CLI."""

    SUCCESS = 0
    FAILURE = 1
    UNSUPPORTED_COMMAND = 2
    AGENT_ERROR = 3


def _parse_duration_seconds(raw: str, default: float = 300.0) -> float:
    """Convert Go-style duration strings (e.g. ``5m``, ``90s``, ``1m30s``) to seconds."""
    text = (raw or "").strip()
    if not text:
        return default
    if text.isdigit():
        return max(1.0, float(text))
    total = 0.0
    matched = False
    for amount_str, unit in _DURATION_PART_RE.findall(text):
        matched = True
        amount = float(amount_str)
        unit_l = unit.lower()
        if unit_l == "ms":
            total += amount / 1000.0
        elif unit_l == "s":
            total += amount
        elif unit_l == "m":
            total += amount * 60.0
        elif unit_l == "h":
            total += amount * 3600.0
    return max(1.0, total) if matched else default


@dataclass(frozen=True)
class AgyHeadlessConfig:
    """Configuration for executing the Antigravity (``agy``) headless CLI."""

    agy_bin: str = "agy"
    model: str = "gemini-4-hydrogen"
    effort: str = "medium"
    print_timeout: str = "5m"
    output_format: AgyOutputFormat = "stream-json"
    conversation_id: str | None = None
    enable_sandbox: bool = True
    dangerously_skip_permissions: bool = False
    json_schema: str | dict[str, Any] | None = None
    execution_mode: AgyExecutionMode = "auto"
    adc_auth: bool = True
    disable_auto_update: bool = True
    google_cloud_project: str = ""
    model_location: str = "global"
    working_dir: str = ""
    timeout_seconds: float | None = None

    @property
    def effective_timeout_seconds(self) -> float:
        """Outer subprocess/HTTP timeout guarding ``--print-timeout``."""
        if self.timeout_seconds is not None and self.timeout_seconds > 0:
            return float(self.timeout_seconds)
        return _parse_duration_seconds(self.print_timeout, default=300.0) + 30.0

    @classmethod
    def from_settings(
        cls,
        settings: Settings | None = None,
        **overrides: Any,
    ) -> AgyHeadlessConfig:
        """Construct ``AgyHeadlessConfig`` from workshop ``Settings`` with optional overrides."""
        cfg = settings or get_settings()
        base: dict[str, Any] = {
            "agy_bin": cfg.agy_bin,
            "model": cfg.resolved_agy_model,
            "effort": cfg.agy_effort,
            "print_timeout": cfg.agy_print_timeout,
            "execution_mode": cfg.agy_execution_mode,
            "enable_sandbox": cfg.agy_enable_sandbox,
            "dangerously_skip_permissions": cfg.agy_skip_permissions,
            "adc_auth": cfg.agy_adc_auth,
            "google_cloud_project": cfg.resolved_agy_project_id,
            "model_location": cfg.model_location,
            "working_dir": str(cfg.local_workspace_path),
        }
        base.update({k: v for k, v in overrides.items() if v is not None})
        return cls(**base)


@dataclass(frozen=True)
class AgyRunResult:
    """Structured result parsed from an Antigravity (``agy``) headless invocation."""

    exit_code: int
    status: str
    response_text: str
    conversation_id: str | None = None
    model: str = ""
    execution_mode: str = "local"
    tool_calls: list[dict[str, Any]] = field(default_factory=list)
    token_usage: dict[str, int] = field(default_factory=dict)
    events: list[dict[str, Any]] = field(default_factory=list)
    agy_error: str | None = None
    stderr: str = ""
    duration_ms: int = 0
    should_retry_or_fallback: bool = False
    actionable_hint: str = ""
    command: list[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return self.exit_code == AgyExitCode.SUCCESS

    def to_dict(self) -> dict[str, Any]:
        """Serialize run result into a plain JSON-safe dictionary."""
        return asdict(self)


def build_agy_command(prompt: str, config: AgyHeadlessConfig) -> list[str]:
    """Build the verified ``agy`` headless argv list for ``prompt`` and ``config``.

    Verified flags to emit:
    - ``[config.agy_bin, "-p", prompt.strip(), "--output-format", config.output_format,
      "--model", config.model, "--effort", config.effort, "--print-timeout", config.print_timeout]``
    - Optional ``--conversation <conversation_id>`` when ``config.conversation_id`` is set
    - Optional ``--sandbox`` when ``config.enable_sandbox`` is True
    - Optional ``--dangerously-skip-permissions`` when ``config.dangerously_skip_permissions`` is True
    - Optional ``--json-schema <json_str>`` when ``config.json_schema`` is set
    """
    _ = (prompt, config)
    # TODO(lab-1): Validate non-empty prompt and assemble the verified `agy` CLI argv
    # list described above (compare against `solution/coding_agent/tools/agy_headless_harness.py`).
    raise NotImplementedError(
        "Complete TODO(lab-1) in starter/coding_agent/tools/agy_headless_harness.py: "
        "build_agy_command()."
    )


def _extract_usage_counts(raw_usage: Mapping[str, Any]) -> dict[str, int]:
    """Normalize token usage dictionaries across CLI / Gemini event schemas."""
    key_aliases = {
        "input_tokens": ("input_tokens", "prompt_tokens", "promptTokenCount"),
        "output_tokens": ("output_tokens", "completion_tokens", "candidatesTokenCount"),
        "total_tokens": ("total_tokens", "totalTokenCount"),
        "cached_tokens": (
            "cached_tokens",
            "cache_read_tokens",
            "cache_read_input_tokens",
            "cachedContentTokenCount",
        ),
        "thought_tokens": (
            "thought_tokens",
            "thinking_tokens",
            "thoughtsTokenCount",
            "reasoning_tokens",
        ),
    }
    normalized: dict[str, int] = {}
    for canonical, aliases in key_aliases.items():
        for alias in aliases:
            val = raw_usage.get(alias)
            if isinstance(val, int | float) and not isinstance(val, bool):
                normalized[canonical] = int(val)
                break
    if "total_tokens" not in normalized and ("input_tokens" in normalized or "output_tokens" in normalized):
        normalized["total_tokens"] = normalized.get("input_tokens", 0) + normalized.get("output_tokens", 0)
    return normalized


def _extract_agy_error(stderr: str, event_errors: list[str]) -> str | None:
    """Extract structured ``AGY_ERROR`` detail from stderr or NDJSON error events."""
    for line in stderr.splitlines():
        match = _AGY_ERROR_RE.search(line)
        if match:
            return match.group(1).strip()
    if event_errors:
        return "; ".join(event_errors)
    cleaned = stderr.strip()
    return cleaned if cleaned else None


def _classify_exit_code(exit_code: int) -> tuple[str, bool, str]:
    """Map an ``agy`` exit code to ``(status, should_retry_or_fallback, actionable_hint)``."""
    if exit_code == AgyExitCode.SUCCESS:
        return "success", False, ""
    if exit_code == AgyExitCode.FAILURE:
        return (
            "failure",
            False,
            (
                "Antigravity CLI failed with exit code 1 (CLI/auth/transport fault). "
                "Verify Application Default Credentials with AGY_ADC_AUTH=true, a non-numeric "
                "string project ID (GOOGLE_CLOUD_PROJECT / AGY_PROJECT_ID on Agent Runtime), "
                "and GOOGLE_CLOUD_LOCATION=global (or run `gcloud auth application-default "
                "login` locally). Never proxy a developer's personal OAuth credentials in a "
                "multi-tenant service."
            ),
        )
    if exit_code == AgyExitCode.UNSUPPORTED_COMMAND:
        return (
            "unsupported_command",
            False,
            (
                "Antigravity CLI rejected arguments with exit code 2 (UNSUPPORTED_COMMAND). "
                "Do NOT retry automatically; verify CLI flags and `agy --version`."
            ),
        )
    if exit_code == AgyExitCode.AGENT_ERROR:
        return (
            "agent_error",
            True,
            (
                "Antigravity CLI returned exit code 3 (AGENT_ERROR: quota, model failure, "
                "or timeout). Eligible for bounded retry or model fallback "
                "(e.g., gemini-4-neon -> gemini-4-hydrogen)."
            ),
        )
    return (
        "failure",
        False,
        f"Antigravity CLI exited with unexpected code {exit_code}. Inspect stderr for details.",
    )


def parse_agy_stream_json(
    stdout: str,
    stderr: str,
    exit_code: int,
    *,
    model: str = "",
    execution_mode: str = "local",
    duration_ms: int = 0,
    command: list[str] | None = None,
) -> AgyRunResult:
    """Parse NDJSON (``--output-format stream-json``) or plain output into ``AgyRunResult``.

    Requirements:
    - Parse each NDJSON line in ``stdout`` (tolerating plain text fallback lines).
    - Support BOTH flat dry-run/legacy events (``{"type": "session_start"|"tool_use"|"text_delta"|"result"|"error", ...}``)
      AND real ``agy 1.5+`` nested ``event`` envelopes:
      - ``{"event": "init", "conversation_id": ..., "init": {"model": ...}}``
      - ``{"event": "step_update", "step_update": {"step_type": ..., "text_delta": ..., "usage": {...}}}``
      - ``{"event": "result", "result": {"conversation_id": ..., "status": "SUCCESS"|"ERROR", "response": ..., "error": ..., "usage": {...}}}``
    - Extract ``conversation_id``, ``response_text``, ``tool_calls``, ``token_usage``
      (via ``_extract_usage_counts``), and ``agy_error`` (via ``_extract_agy_error``).
    - Classify ``exit_code`` via ``_classify_exit_code(exit_code)`` so
      ``should_retry_or_fallback`` is True ONLY when ``exit_code == AgyExitCode.AGENT_ERROR`` (3).
    """
    _ = (stdout, stderr, exit_code, model, execution_mode, duration_ms, command)
    # TODO(lab-1): Parse NDJSON lines from `stdout` and return a populated `AgyRunResult`
    # (compare against `solution/coding_agent/tools/agy_headless_harness.py`).
    raise NotImplementedError(
        "Complete TODO(lab-1) in starter/coding_agent/tools/agy_headless_harness.py: "
        "parse_agy_stream_json()."
    )


def build_local_agy_env(
    config: AgyHeadlessConfig,
    base_env: Mapping[str, str] | None = None,
) -> dict[str, str]:
    """Build subprocess environment variables for local / Agent Runtime ``agy`` execution."""
    env = dict(os.environ if base_env is None else base_env)
    if config.disable_auto_update:
        env["AGY_CLI_DISABLE_AUTO_UPDATE"] = "true"
    if config.adc_auth:
        env["AGY_ADC_AUTH"] = "true"

    # Prefer non-numeric string project IDs: Agent Runtime auto-injects the numeric
    # project number into GOOGLE_CLOUD_PROJECT / GOOGLE_CLOUD_QUOTA_PROJECT, which
    # `agy` rejects with exit code 3 (`invalid project ID`).
    candidate_project = config.google_cloud_project.strip()
    if not candidate_project or candidate_project.isdigit():
        env_agy_project = env.get("AGY_PROJECT_ID", "").strip()
        if env_agy_project and not env_agy_project.isdigit():
            candidate_project = env_agy_project

    if candidate_project and not candidate_project.isdigit():
        env["GOOGLE_CLOUD_PROJECT"] = candidate_project
        env["GOOGLE_CLOUD_QUOTA_PROJECT"] = candidate_project
    elif env.get("GOOGLE_CLOUD_PROJECT", "").strip().isdigit():
        logger.warning(
            "GOOGLE_CLOUD_PROJECT=%r is numeric (Agent Runtime default); `agy` rejects "
            "numeric project IDs with exit code 3. Inject non-reserved `AGY_PROJECT_ID = var.project_id` "
            "in terraform/main.tf so `agy` receives the string project ID.",
            env.get("GOOGLE_CLOUD_PROJECT"),
        )

    if config.model_location:
        env["GOOGLE_CLOUD_LOCATION"] = config.model_location
    return env


def build_sandbox_agy_env(
    config: AgyHeadlessConfig,
    extra_env: Mapping[str, str] | None = None,
) -> dict[str, str]:
    """Build an allowlisted ephemeral env dict for BYOC sandbox ``POST /exec``.

    Values are injected into the single sandbox child process only and are NEVER
    logged or written to disk. Rejects any key outside ``ALLOWED_SANDBOX_AGY_ENV_KEYS``.
    """
    env: dict[str, str] = {}
    if config.disable_auto_update:
        env["AGY_CLI_DISABLE_AUTO_UPDATE"] = "true"
    if config.adc_auth:
        env["AGY_ADC_AUTH"] = "true"
    candidate_project = config.google_cloud_project.strip()
    if candidate_project and not candidate_project.isdigit():
        env["GOOGLE_CLOUD_PROJECT"] = candidate_project
        env["GOOGLE_CLOUD_QUOTA_PROJECT"] = candidate_project
    if config.model_location:
        env["GOOGLE_CLOUD_LOCATION"] = config.model_location

    if extra_env:
        disallowed = sorted(k for k in extra_env if k not in ALLOWED_SANDBOX_AGY_ENV_KEYS)
        if disallowed:
            allowed = ", ".join(sorted(ALLOWED_SANDBOX_AGY_ENV_KEYS))
            raise ValueError(
                f"Disallowed sandbox agy env key(s): {', '.join(disallowed)}. "
                f"Allowed keys: {allowed}."
            )
        for key, value in extra_env.items():
            if not isinstance(value, str):
                raise ValueError(f"Sandbox env value for {key!r} must be a string.")
            env[key] = value
    return env


@contextlib.contextmanager
def _otel_agy_span(name: str) -> Iterator[Any]:
    """Open an OTel span when ``opentelemetry-api`` is installed, else yield ``None``."""
    if _otel_trace is None:
        yield None
        return
    tracer = _otel_trace.get_tracer("coding_agent.agy_headless_harness")
    with tracer.start_as_current_span(name) as span:
        yield span


def _record_span_attributes(span: Any, result: AgyRunResult, config: AgyHeadlessConfig) -> None:
    """Attach structured NDJSON trace & token attributes to the active OTel span."""
    if span is None or not getattr(span, "is_recording", lambda: False)():
        return
    span.set_attribute("agy.execution_mode", result.execution_mode)
    span.set_attribute("agy.model", result.model or config.model)
    span.set_attribute("agy.effort", config.effort)
    span.set_attribute("agy.exit_code", int(result.exit_code))
    span.set_attribute("agy.status", result.status)
    span.set_attribute("agy.duration_ms", int(result.duration_ms))
    span.set_attribute("agy.tool_calls_count", len(result.tool_calls))
    if result.conversation_id:
        span.set_attribute("agy.conversation_id", result.conversation_id)
    if "input_tokens" in result.token_usage:
        span.set_attribute("gen_ai.usage.input_tokens", int(result.token_usage["input_tokens"]))
    if "output_tokens" in result.token_usage:
        span.set_attribute("gen_ai.usage.output_tokens", int(result.token_usage["output_tokens"]))


class AgyHeadlessHarness:
    """Executes Antigravity (``agy``) headlessly in local, BYOC sandbox, or auto mode."""

    def __init__(
        self,
        config: AgyHeadlessConfig | None = None,
        *,
        settings: Settings | None = None,
        sandbox_env: Any | None = None,
        dry_run: bool = False,
    ) -> None:
        self._settings = settings or get_settings()
        self.config = config or AgyHeadlessConfig.from_settings(self._settings)
        self.sandbox_env = sandbox_env
        self.dry_run = dry_run

    def _local_agy_available(self) -> bool:
        return shutil.which(self.config.agy_bin) is not None

    async def _probe_sandbox_agy_available(self, *, ctx: Any = None) -> bool:
        """Check whether the attached BYOC sandbox reports ``agy_cli_available=True``."""
        if self.sandbox_env is None:
            return False

        check_health = getattr(self.sandbox_env, "check_byoc_health", None)
        if callable(check_health):
            try:
                health = await check_health(ctx=ctx)
                if isinstance(health, Mapping) and "agy_cli_available" in health:
                    return bool(health["agy_cli_available"])
            except Exception as exc:
                logger.debug("Sandbox /health probe failed (%s); falling back to PATH check.", exc)

        execute_fn = getattr(self.sandbox_env, "execute", None)
        if callable(execute_fn):
            try:
                res = await execute_fn(
                    f"command -v {shlex.quote(self.config.agy_bin)} >/dev/null 2>&1",
                    timeout=10.0,
                    ctx=ctx,
                )
                return getattr(res, "exit_code", 1) == 0
            except Exception as exc:
                logger.debug("Sandbox agy PATH probe failed (%s).", exc)
        return False

    async def resolve_execution_mode(
        self,
        *,
        ctx: Any = None,
        extra_sandbox_env: Mapping[str, str] | None = None,
    ) -> Literal["sandbox", "local", "unavailable"]:
        """Resolve effective execution backend (``sandbox`` | ``local`` | ``unavailable``).

        In ``auto`` mode:
        - When ``adc_auth=True`` and no explicit sandbox credential override (such as
          ``GEMINI_API_KEY`` in ``extra_sandbox_env``) is supplied, prefer ``local``
          (Agent Runtime Custom SA ADC / workstation ADC) instead of routing ``agy``
          into an air-gapped gVisor BYOC sandbox (which blocks the metadata server and
          exits 1 with authentication required). Untrusted ``pytest`` / ``ruff`` checks
          still execute inside the isolated BYOC sandbox.
        - When explicit sandbox credentials are supplied (or ``adc_auth=False``), prefer
          the BYOC sandbox when ``SANDBOX_MODE=byoc`` and ``/health`` reports ``agy``.
        """
        requested = self.config.execution_mode
        if requested == "sandbox":
            if self.sandbox_env is not None and await self._probe_sandbox_agy_available(ctx=ctx):
                return "sandbox"
            return "unavailable"

        if requested == "local":
            return "local" if self._local_agy_available() else "unavailable"

        has_sandbox_creds = bool(extra_sandbox_env and extra_sandbox_env.get("GEMINI_API_KEY"))
        if self.config.adc_auth and not has_sandbox_creds:
            if self._local_agy_available():
                return "local"
            return "unavailable"

        if (
            self._settings.sandbox_mode == "byoc"
            and self.sandbox_env is not None
            and await self._probe_sandbox_agy_available(ctx=ctx)
        ):
            return "sandbox"
        if self._local_agy_available():
            return "local"
        return "unavailable"

    def simulate_dry_run(
        self,
        prompt: str,
        *,
        config: AgyHeadlessConfig | None = None,
    ) -> AgyRunResult:
        """Deterministically simulate an ``agy --output-format stream-json`` run offline."""
        run_cfg = config or self.config
        cmd = build_agy_command(prompt, run_cfg)
        conv_id = run_cfg.conversation_id or "conv-dry-run-0001"
        ndjson_events = [
            {
                "type": "session_start",
                "conversation_id": conv_id,
                "model": run_cfg.model,
                "effort": run_cfg.effort,
            },
            {
                "type": "tool_use",
                "id": "call_dry_run_1",
                "name": "ReadFile",
                "input": {"path": "README.md"},
            },
            {
                "type": "text_delta",
                "delta": f"[dry-run] Simulated Antigravity ({run_cfg.model}) response for prompt: ",
            },
            {
                "type": "text_delta",
                "delta": prompt.strip(),
            },
            {
                "type": "result",
                "conversation_id": conv_id,
                "model": run_cfg.model,
                "result": (
                    f"[dry-run] Simulated Antigravity ({run_cfg.model}, effort={run_cfg.effort}) "
                    f"execution completed for prompt: {prompt.strip()}"
                ),
                "usage": {
                    "input_tokens": 128,
                    "output_tokens": 64,
                    "total_tokens": 192,
                },
            },
        ]
        stdout = "\n".join(json.dumps(ev) for ev in ndjson_events) + "\n"
        return parse_agy_stream_json(
            stdout=stdout,
            stderr="",
            exit_code=int(AgyExitCode.SUCCESS),
            model=run_cfg.model,
            execution_mode="dry_run",
            duration_ms=1,
            command=cmd,
        )

    async def _run_local(self, prompt: str, run_cfg: AgyHeadlessConfig) -> AgyRunResult:
        cmd = build_agy_command(prompt, run_cfg)
        env = build_local_agy_env(run_cfg)
        cwd = run_cfg.working_dir or str(self._settings.local_workspace_path)
        Path(cwd).mkdir(parents=True, exist_ok=True)
        start = time.monotonic()

        try:
            proc = await asyncio.create_subprocess_exec(
                *cmd,
                cwd=cwd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                env=env,
            )
        except FileNotFoundError:
            return AgyRunResult(
                exit_code=int(AgyExitCode.FAILURE),
                status="unavailable",
                response_text="",
                model=run_cfg.model,
                execution_mode="fallback",
                actionable_hint=(
                    f"Antigravity binary {run_cfg.agy_bin!r} not found on PATH. "
                    "Install via https://antigravity.google/cli/install.sh or fall back "
                    "to native ADK 2.0 LlmAgent + EnvironmentToolset."
                ),
                command=cmd,
            )

        try:
            stdout_bytes, stderr_bytes = await asyncio.wait_for(
                proc.communicate(),
                timeout=run_cfg.effective_timeout_seconds,
            )
        except TimeoutError:
            if proc.returncode is None:
                try:
                    proc.kill()
                except ProcessLookupError:
                    pass
            await proc.wait()
            elapsed_ms = max(0, int((time.monotonic() - start) * 1000))
            return parse_agy_stream_json(
                stdout="",
                stderr=(
                    f"AGY_ERROR: local headless command timed out after "
                    f"{run_cfg.effective_timeout_seconds:.1f}s"
                ),
                exit_code=int(AgyExitCode.AGENT_ERROR),
                model=run_cfg.model,
                execution_mode="local",
                duration_ms=elapsed_ms,
                command=cmd,
            )
        except BaseException:
            if proc.returncode is None:
                try:
                    proc.kill()
                except ProcessLookupError:
                    pass
            await proc.wait()
            raise

        elapsed_ms = max(0, int((time.monotonic() - start) * 1000))
        return parse_agy_stream_json(
            stdout=stdout_bytes.decode("utf-8", errors="replace"),
            stderr=stderr_bytes.decode("utf-8", errors="replace"),
            exit_code=int(proc.returncode or 0),
            model=run_cfg.model,
            execution_mode="local",
            duration_ms=elapsed_ms,
            command=cmd,
        )

    async def _run_in_sandbox(
        self,
        prompt: str,
        run_cfg: AgyHeadlessConfig,
        *,
        ctx: Any = None,
        extra_sandbox_env: Mapping[str, str] | None = None,
    ) -> AgyRunResult:
        sandbox_cfg = AgyHeadlessConfig(
            **{
                **asdict(run_cfg),
                "enable_sandbox": False,
                "dangerously_skip_permissions": True,
            }
        )
        cmd = build_agy_command(prompt, sandbox_cfg)
        shell_cmd = shlex.join(cmd)
        ephemeral_env = build_sandbox_agy_env(sandbox_cfg, extra_env=extra_sandbox_env)

        start = time.monotonic()
        execute_with_env = getattr(self.sandbox_env, "execute_with_env", None)
        if callable(execute_with_env):
            exec_res = await execute_with_env(
                shell_cmd,
                env=ephemeral_env,
                timeout=sandbox_cfg.effective_timeout_seconds,
                ctx=ctx,
            )
        else:
            exec_res = await self.sandbox_env.execute(
                shell_cmd,
                timeout=sandbox_cfg.effective_timeout_seconds,
                ctx=ctx,
            )
        elapsed_ms = max(0, int((time.monotonic() - start) * 1000))

        exit_code = int(getattr(exec_res, "exit_code", 1))
        stdout = str(getattr(exec_res, "stdout", "") or "")
        stderr = str(getattr(exec_res, "stderr", "") or "")
        timed_out = bool(getattr(exec_res, "timed_out", False))
        if timed_out and exit_code != int(AgyExitCode.AGENT_ERROR):
            exit_code = int(AgyExitCode.AGENT_ERROR)
            stderr = f"{stderr}\nAGY_ERROR: sandbox execution timed out".strip()

        return parse_agy_stream_json(
            stdout=stdout,
            stderr=stderr,
            exit_code=exit_code,
            model=sandbox_cfg.model,
            execution_mode="sandbox",
            duration_ms=elapsed_ms,
            command=cmd,
        )

    async def run(
        self,
        prompt: str,
        *,
        conversation_id: str | None = None,
        model_override: str | None = None,
        effort_override: str | None = None,
        json_schema: str | dict[str, Any] | None = None,
        ctx: Any = None,
        extra_sandbox_env: Mapping[str, str] | None = None,
        dry_run: bool | None = None,
    ) -> AgyRunResult:
        """Run one headless Antigravity turn and emit structured OTel span metadata."""
        use_dry_run = self.dry_run if dry_run is None else dry_run
        run_cfg = AgyHeadlessConfig(
            **{
                **asdict(self.config),
                "conversation_id": conversation_id or self.config.conversation_id,
                "model": model_override or self.config.model,
                "effort": effort_override or self.config.effort,
                "json_schema": json_schema if json_schema is not None else self.config.json_schema,
            }
        )

        with _otel_agy_span("agy.headless.run") as span:
            if use_dry_run:
                result = self.simulate_dry_run(prompt, config=run_cfg)
                _record_span_attributes(span, result, run_cfg)
                return result

            mode = await self.resolve_execution_mode(
                ctx=ctx,
                extra_sandbox_env=extra_sandbox_env,
            )
            if mode == "sandbox":
                result = await self._run_in_sandbox(
                    prompt,
                    run_cfg,
                    ctx=ctx,
                    extra_sandbox_env=extra_sandbox_env,
                )
            elif mode == "local":
                result = await self._run_local(prompt, run_cfg)
            else:
                result = AgyRunResult(
                    exit_code=int(AgyExitCode.FAILURE),
                    status="unavailable",
                    response_text="",
                    model=run_cfg.model,
                    execution_mode="fallback",
                    actionable_hint=(
                        "Antigravity CLI ('agy') is unavailable locally and in the active "
                        "sandbox (or sandbox is air-gapped). Fall back to native ADK 2.0 "
                        "LlmAgent + EnvironmentToolset."
                    ),
                )

            _record_span_attributes(span, result, run_cfg)
            return result

    async def run_with_retry_and_fallback(
        self,
        prompt: str,
        *,
        conversation_id: str | None = None,
        model_override: str | None = None,
        effort_override: str | None = None,
        json_schema: str | dict[str, Any] | None = None,
        max_retries: int = 1,
        fallback_model: str | None = None,
        ctx: Any = None,
        extra_sandbox_env: Mapping[str, str] | None = None,
        dry_run: bool | None = None,
    ) -> AgyRunResult:
        """Execute with bounded retry/fallback strictly on ``AgyExitCode.AGENT_ERROR`` (3)."""
        current_model = model_override or self.config.model
        result = await self.run(
            prompt,
            conversation_id=conversation_id,
            model_override=current_model,
            effort_override=effort_override,
            json_schema=json_schema,
            ctx=ctx,
            extra_sandbox_env=extra_sandbox_env,
            dry_run=dry_run,
        )

        attempts = 0
        while result.should_retry_or_fallback and attempts < max(0, max_retries):
            attempts += 1
            next_model = fallback_model or FALLBACK_MODEL_MAP.get(current_model, current_model)
            logger.warning(
                "agy exited with AGENT_ERROR (3) on model=%s (%s); retry %d/%d using model=%s.",
                current_model,
                result.agy_error or "unknown error",
                attempts,
                max_retries,
                next_model,
            )
            current_model = next_model
            result = await self.run(
                prompt,
                conversation_id=result.conversation_id or conversation_id,
                model_override=current_model,
                effort_override=effort_override,
                json_schema=json_schema,
                ctx=ctx,
                extra_sandbox_env=extra_sandbox_env,
                dry_run=dry_run,
            )
        return result


def build_agy_headless_tool(
    settings: Settings | None = None,
    sandbox_env: Any | None = None,
    *,
    dry_run: bool = False,
) -> Any:
    """Create an ADK-compatible async tool wrapping ``AgyHeadlessHarness``."""
    cfg = settings or get_settings()
    harness = AgyHeadlessHarness(settings=cfg, sandbox_env=sandbox_env, dry_run=dry_run)

    async def run_agy_headless_task(
        prompt: str,
        conversation_id: str = "",
        model: str = "",
        effort: str = "",
    ) -> dict[str, Any]:
        """Delegate a scoped coding task to the Antigravity (``agy``) headless CLI harness."""
        result = await harness.run_with_retry_and_fallback(
            prompt=prompt,
            conversation_id=conversation_id.strip() or None,
            model_override=model.strip() or None,
            effort_override=effort.strip().lower() or None,
        )
        return result.to_dict()

    try:
        from google.adk.tools import FunctionTool

        return FunctionTool(func=run_agy_headless_task)
    except ImportError:
        return run_agy_headless_task


def _build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m coding_agent.tools.agy_headless_harness",
        description="Run or dry-run the Antigravity (agy) headless coding CLI harness.",
    )
    parser.add_argument("--prompt", required=True, help="Coding prompt to execute headlessly.")
    parser.add_argument("--model", default=None, help="Gemini 4 model override (default: AGY_MODEL/MODEL_NAME).")
    parser.add_argument(
        "--effort",
        choices=["low", "medium", "high", "xhigh"],
        default=None,
        help="Antigravity reasoning effort level.",
    )
    parser.add_argument(
        "--mode",
        choices=["auto", "local", "sandbox"],
        default=None,
        help="Execution backend mode (default: AGY_EXECUTION_MODE).",
    )
    parser.add_argument(
        "--output-format",
        choices=["stream-json", "json", "text"],
        default="stream-json",
        help="CLI output format (default: stream-json).",
    )
    parser.add_argument("--print-timeout", default=None, help="CLI --print-timeout value (default: 5m).")
    parser.add_argument("--conversation", default=None, help="Existing conversation ID to continue.")
    parser.add_argument(
        "--sandbox",
        dest="enable_sandbox",
        action="store_true",
        default=None,
        help="Pass --sandbox for OS-level terminal isolation in local/CI mode.",
    )
    parser.add_argument(
        "--no-sandbox",
        dest="enable_sandbox",
        action="store_false",
        help="Disable CLI --sandbox flag (e.g. inside an already isolated gVisor container).",
    )
    parser.add_argument(
        "--dangerously-skip-permissions",
        action="store_true",
        default=None,
        help="Pass --dangerously-skip-permissions (ONLY inside isolated gVisor sandboxes or CI).",
    )
    parser.add_argument("--json-schema", default=None, help="Optional JSON schema string for structured output.")
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Simulate deterministic stream-json NDJSON parsing without invoking `agy`.",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    args = _build_arg_parser().parse_args(argv)
    settings = get_settings()
    config = AgyHeadlessConfig.from_settings(
        settings,
        model=args.model,
        effort=args.effort,
        execution_mode=args.mode,
        output_format=args.output_format,
        print_timeout=args.print_timeout,
        conversation_id=args.conversation,
        enable_sandbox=args.enable_sandbox,
        dangerously_skip_permissions=args.dangerously_skip_permissions,
        json_schema=args.json_schema,
    )
    harness = AgyHeadlessHarness(config=config, settings=settings, dry_run=args.dry_run)
    result = asyncio.run(harness.run_with_retry_and_fallback(args.prompt))
    print(json.dumps(result.to_dict(), indent=2))
    return 0 if result.ok else (result.exit_code or 1)


if __name__ == "__main__":
    sys.exit(main())
