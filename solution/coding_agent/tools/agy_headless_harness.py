"""Antigravity (``agy``) Headless CLI Coding Harness (reference solution).

Integrates Google's native Go Antigravity CLI (``agy``) as a structured headless coding
harness across laptops, CI, Agent Runtime containers, and BYOC Managed Sandboxes — with
zero local Docker required.

Verified CLI flags:
- ``agy -p "<prompt>"`` (headless print mode)
- ``--output-format stream-json`` (or ``json`` / ``text``)
- ``--model <gemini-4-hydrogen|gemini-4-neon|...>``
- ``--effort <low|medium|high|xhigh>``
- ``--print-timeout <duration>`` (e.g. ``5m``)
- ``--conversation <conversation_id>`` (session continuation across fix rounds)
- ``--sandbox`` (OS terminal sandbox for local/CI execution)
- ``--dangerously-skip-permissions`` (unattended auto-approve inside isolated gVisor/CI)
- ``--json-schema <schema_json>`` (optional structured response schema)

Verified 4-tier exit-code contract (``AgyExitCode``):
- ``0`` (``SUCCESS``): Clean completion.
- ``1`` (``FAILURE``): CLI/auth/transport fault — fail fast with ``AGY_ADC_AUTH=true`` hint.
- ``2`` (``UNSUPPORTED_COMMAND``): Invalid flag/usage — NEVER retry automatically.
- ``3`` (``AGENT_ERROR``): Quota/model failure/timeout (``AGY_ERROR`` on stderr) — eligible
  for bounded retry or fallback (e.g., ``gemini-4-neon`` -> ``gemini-4-hydrogen``).

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
    """Build the verified ``agy`` headless argv list for ``prompt`` and ``config``."""
    cleaned_prompt = prompt.strip()
    if not cleaned_prompt:
        raise ValueError("Prompt passed to build_agy_command() must be non-empty.")

    cmd: list[str] = [
        config.agy_bin or "agy",
        "-p",
        cleaned_prompt,
        "--output-format",
        config.output_format,
        "--model",
        config.model,
        "--effort",
        config.effort,
        "--print-timeout",
        config.print_timeout,
    ]
    if config.conversation_id:
        cmd.extend(["--conversation", config.conversation_id])
    if config.enable_sandbox:
        cmd.append("--sandbox")
    if config.dangerously_skip_permissions:
        cmd.append("--dangerously-skip-permissions")
    if config.json_schema is not None:
        schema_json = (
            config.json_schema
            if isinstance(config.json_schema, str)
            else json.dumps(config.json_schema, separators=(",", ":"))
        )
        cmd.extend(["--json-schema", schema_json])
    return cmd


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


def _extract_content_text_and_tools(
    content: Any,
    text_parts: list[str],
    tool_calls: list[dict[str, Any]],
) -> None:
    """Extract text fragments and tool_use blocks from string or structured content arrays."""
    if isinstance(content, str):
        if content:
            text_parts.append(content)
        return
    if isinstance(content, list):
        for item in content:
            if isinstance(item, str):
                text_parts.append(item)
            elif isinstance(item, Mapping):
                item_type = str(item.get("type", "")).lower()
                if item_type in {"tool_use", "tool_call", "function_call"}:
                    tool_calls.append(
                        {
                            "name": str(item.get("name", item.get("tool", "unknown"))),
                            "id": str(item.get("id", "")),
                            "input": item.get("input", item.get("arguments", {})),
                        }
                    )
                else:
                    text = item.get("text")
                    if isinstance(text, str) and text:
                        text_parts.append(text)


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

    Supports BOTH flat dry-run/legacy events (``{"type": "session_start"|"tool_use"|"text_delta"|"result"|"error", ...}``)
    AND real ``agy 1.5+`` nested envelopes:
    - ``{"event": "init", "conversation_id": ..., "init": {"model": ...}}``
    - ``{"event": "step_update", "step_update": {"step_type": ..., "text_delta": ..., "usage": {...}}}``
    - ``{"event": "result", "result": {"conversation_id": ..., "status": "SUCCESS"|"ERROR", "response": ..., "error": ..., "usage": {...}}}``
    """
    events: list[dict[str, Any]] = []
    stream_text_parts: list[str] = []
    final_result_text: str | None = None
    plain_lines: list[str] = []
    conversation_id: str | None = None
    tool_calls: list[dict[str, Any]] = []
    token_usage: dict[str, int] = {}
    event_errors: list[str] = []
    detected_model = model

    def _record_error_val(err_val: Any) -> None:
        if isinstance(err_val, Mapping):
            err_val = err_val.get("message") or json.dumps(dict(err_val))
        if err_val:
            text_err = str(err_val).strip()
            if text_err and text_err not in event_errors:
                event_errors.append(text_err)

    for raw_line in (stdout or "").splitlines():
        line = raw_line.strip()
        if not line:
            continue
        try:
            obj = json.loads(line)
        except json.JSONDecodeError:
            plain_lines.append(raw_line)
            continue

        if not isinstance(obj, dict):
            plain_lines.append(raw_line)
            continue

        events.append(obj)

        # Unwrap optional `agy 1.5+` nested envelope payloads (`init`, `step_update`, `result`).
        nested_init = obj.get("init") if isinstance(obj.get("init"), Mapping) else None
        nested_step = (
            obj.get("step_update") if isinstance(obj.get("step_update"), Mapping) else None
        )
        nested_result = obj.get("result") if isinstance(obj.get("result"), Mapping) else None
        meta_obj = obj.get("metadata") if isinstance(obj.get("metadata"), Mapping) else None

        containers: list[Mapping[str, Any]] = [
            c for c in (obj, nested_result, nested_step, nested_init, meta_obj) if c is not None
        ]

        for container in containers:
            for conv_key in ("conversation_id", "conversationId", "session_id", "sessionId"):
                raw_cid = container.get(conv_key)
                if isinstance(raw_cid, str) and raw_cid.strip():
                    conversation_id = raw_cid.strip()
                    break

        if not detected_model:
            for container in containers:
                raw_model = container.get("model")
                if isinstance(raw_model, str) and raw_model.strip():
                    detected_model = raw_model.strip()
                    break

        for container in (obj, nested_step, nested_result):
            if container is None:
                continue
            for usage_key in ("usage", "token_usage", "usageMetadata"):
                raw_usage = container.get(usage_key)
                if isinstance(raw_usage, Mapping):
                    token_usage.update(_extract_usage_counts(raw_usage))

        event_type = str(obj.get("type") or obj.get("event") or "").lower()

        if event_type in {"tool_use", "tool_call", "function_call"}:
            tool_calls.append(
                {
                    "name": str(obj.get("name", obj.get("tool", "unknown"))),
                    "id": str(obj.get("id", "")),
                    "input": obj.get("input", obj.get("arguments", {})),
                }
            )
        elif nested_step is not None and str(nested_step.get("step_type", "")).lower() in {
            "tool_use",
            "tool_call",
            "function_call",
        }:
            tool_calls.append(
                {
                    "name": str(
                        nested_step.get("name", nested_step.get("tool_name", nested_step.get("tool", "unknown")))
                    ),
                    "id": str(nested_step.get("id", nested_step.get("call_id", ""))),
                    "input": nested_step.get("input", nested_step.get("arguments", {})),
                }
            )

        for container in (obj, nested_step, nested_result):
            if container is not None and isinstance(container.get("tool_calls"), list):
                for tc in container["tool_calls"]:
                    if isinstance(tc, Mapping):
                        tool_calls.append(
                            {
                                "name": str(tc.get("name", tc.get("tool", "unknown"))),
                                "id": str(tc.get("id", "")),
                                "input": tc.get("input", tc.get("arguments", {})),
                            }
                        )

        if event_type == "error" or obj.get("error"):
            _record_error_val(obj.get("error") or obj.get("message") or obj.get("detail"))
        if nested_step is not None and nested_step.get("error"):
            _record_error_val(nested_step.get("error"))
        if nested_result is not None:
            if nested_result.get("error"):
                _record_error_val(nested_result.get("error"))
            elif str(nested_result.get("status", "")).upper() == "ERROR":
                _record_error_val(
                    nested_result.get("message")
                    or nested_result.get("detail")
                    or "agy result status=ERROR"
                )

        if event_type in {"result", "final", "response"}:
            if nested_result is not None:
                candidate = (
                    nested_result.get("response")
                    or nested_result.get("result")
                    or nested_result.get("text")
                )
                if isinstance(candidate, str) and candidate.strip():
                    final_result_text = candidate.strip()
                elif "content" in nested_result:
                    nested_parts: list[str] = []
                    _extract_content_text_and_tools(
                        nested_result["content"], nested_parts, tool_calls
                    )
                    if nested_parts:
                        final_result_text = "".join(nested_parts).strip()
            else:
                candidate = obj.get("result") or obj.get("response") or obj.get("text")
                if isinstance(candidate, str) and candidate.strip():
                    final_result_text = candidate.strip()
                elif "content" in obj:
                    result_parts: list[str] = []
                    _extract_content_text_and_tools(obj["content"], result_parts, tool_calls)
                    if result_parts:
                        final_result_text = "".join(result_parts).strip()
        else:
            delta_source = nested_step if nested_step is not None else obj
            delta = (
                delta_source.get("text_delta")
                if delta_source.get("text_delta") is not None
                else delta_source.get("delta")
            )
            if isinstance(delta, str) and delta:
                stream_text_parts.append(delta)
            elif isinstance(delta, Mapping) and isinstance(delta.get("text"), str):
                stream_text_parts.append(delta["text"])
            elif isinstance(delta_source.get("text"), str) and delta_source["text"]:
                stream_text_parts.append(delta_source["text"])
            elif "content" in delta_source:
                _extract_content_text_and_tools(
                    delta_source["content"], stream_text_parts, tool_calls
                )
            elif isinstance(delta_source.get("message"), Mapping):
                _extract_content_text_and_tools(
                    delta_source["message"].get("content"),
                    stream_text_parts,
                    tool_calls,
                )

    if final_result_text is not None:
        response_text = final_result_text
    elif stream_text_parts:
        response_text = "".join(stream_text_parts).strip()
    else:
        response_text = "\n".join(plain_lines).strip()

    status, should_retry, hint = _classify_exit_code(exit_code)
    agy_error = _extract_agy_error(stderr or "", event_errors) if exit_code != 0 or event_errors else None

    return AgyRunResult(
        exit_code=int(exit_code),
        status=status,
        response_text=response_text,
        conversation_id=conversation_id,
        model=detected_model,
        execution_mode=execution_mode,
        tool_calls=tool_calls,
        token_usage=token_usage,
        events=events,
        agy_error=agy_error,
        stderr=(stderr or "").strip(),
        duration_ms=max(0, int(duration_ms)),
        should_retry_or_fallback=should_retry,
        actionable_hint=hint,
        command=list(command or []),
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

    # Always route Gemini 4 inference inside `agy` to `config.model_location` (default: `global`)
    # even when the host Agent Runtime container runs in `asia-southeast1`.
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

        # Auto mode:
        # 1. With ADC auth and no BYOC GEMINI_API_KEY override, prefer local/Agent Runtime
        #    `agy` (Custom SA ADC) over an air-gapped BYOC gVisor sandbox without metadata.
        has_sandbox_creds = bool(extra_sandbox_env and extra_sandbox_env.get("GEMINI_API_KEY"))
        if self.config.adc_auth and not has_sandbox_creds:
            if self._local_agy_available():
                return "local"
            return "unavailable"

        # 2. Otherwise prefer isolated BYOC Managed Sandbox when SANDBOX_MODE=byoc and /health reports agy.
        if (
            self._settings.sandbox_mode == "byoc"
            and self.sandbox_env is not None
            and await self._probe_sandbox_agy_available(ctx=ctx)
        ):
            return "sandbox"
        # 3. Otherwise use local/Agent Runtime `agy` when installed on PATH.
        if self._local_agy_available():
            return "local"
        # 4. Caller falls back gracefully to native ADK 2.0 LlmAgent + EnvironmentToolset.
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
        # Inside an isolated gVisor Managed Sandbox, disable nested CLI sandbox and enable
        # unattended approval (`--dangerously-skip-permissions`).
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
        """Execute with bounded retry/fallback strictly on ``AgyExitCode.AGENT_ERROR`` (3).

        - Exit code ``2`` (``UNSUPPORTED_COMMAND``): NEVER retried.
        - Exit code ``1`` (``FAILURE``): Fail fast with actionable auth/transport hint.
        - Exit code ``3`` (``AGENT_ERROR``): Retry up to ``max_retries`` times, stepping down
          ``gemini-4-neon`` -> ``gemini-4-hydrogen`` (or explicit ``fallback_model``).
        """
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
        """Delegate a scoped coding task to the Antigravity (``agy``) headless CLI harness.

        Args:
            prompt: Concrete engineering instruction with target files and acceptance criteria.
            conversation_id: Optional prior ``agy`` conversation ID to continue across fix rounds.
            model: Optional Gemini 4 model override (e.g. ``gemini-4-hydrogen`` or ``gemini-4-neon``).
            effort: Optional effort level (``low``, ``medium``, ``high``, or ``xhigh``).

        Returns:
            Structured JSON dictionary containing ``exit_code``, ``status``, ``response_text``,
            ``conversation_id``, ``tool_calls``, ``token_usage``, and ``should_retry_or_fallback``.
        """
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
