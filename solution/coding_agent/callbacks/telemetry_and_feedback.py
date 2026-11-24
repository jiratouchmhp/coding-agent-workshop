"""ADK OTel Telemetry Callbacks, Sandbox Cloud Logging & Feedback Client (solution — Lab 3).

Addresses two critical Gemini Enterprise Agent Platform observability requirements:
1. **Parent-Runtime Structured Cloud Logging for Sandbox Outputs:**
   Cloud Logging is attached to the ``aiplatform.googleapis.com/ReasoningEngine``
   monitored resource and is **NOT supported for child resources** (Managed Sandboxes,
   Sessions, Memory Bank, Code Execution). Therefore, ``before_tool_callback`` and
   ``after_tool_callback`` emit OpenTelemetry span attributes and structured JSON
   Cloud Logs (with truncated, secret-redacted ``stdout`` and ``stderr`` previews)
   directly from the parent Agent Runtime.
2. **Feedback Service Linked to Managed Sessions & Cloud Trace:**
   ``FeedbackClient`` wraps all verified ``agentplatform.Client.feedback_entries`` and
   ``feedback_contexts`` operations. Linking ``event_id`` to the OTel span attribute
   ``gcp.vertex.agent.event_id`` (or ``raw_event.id``) surfaces feedback directly in
   the Console Traces UI and exports an **immutable** ``gcp.vertex.agent.feedback``
   Cloud Trace span.

Verified OTel Environment Variables (ADK Python):
- ``GOOGLE_CLOUD_AGENT_ENGINE_ENABLE_TELEMETRY="true"``
- ``OTEL_SEMCONV_STABILITY_OPT_IN="gen_ai_latest_experimental"``
- ``OTEL_INSTRUMENTATION_GENAI_CAPTURE_MESSAGE_CONTENT="EVENT_ONLY"``
  (Enum only in ADK Python: ``NO_CONTENT``, ``EVENT_ONLY``, ``SPAN_ONLY``,
  ``SPAN_AND_EVENT``. Passing ``"true"`` silently falls back to ``NO_CONTENT``!)
"""

from __future__ import annotations

import argparse
import functools
import json
import logging
import os
import re
import sys
import time
from collections.abc import Callable, Mapping
from typing import Any

from opentelemetry import trace

from coding_agent.config import Settings, get_settings

logger = logging.getLogger(__name__)

RECOMMENDED_OTEL_ENV_VARS: dict[str, str] = {
    "GOOGLE_CLOUD_AGENT_ENGINE_ENABLE_TELEMETRY": "true",
    "OTEL_SEMCONV_STABILITY_OPT_IN": "gen_ai_latest_experimental",
    "OTEL_INSTRUMENTATION_GENAI_CAPTURE_MESSAGE_CONTENT": "EVENT_ONLY",
}
VALID_PYTHON_CAPTURE_CONTENT_VALUES: frozenset[str] = frozenset(
    {"NO_CONTENT", "EVENT_ONLY", "SPAN_ONLY", "SPAN_AND_EVENT"}
)

VALID_FEEDBACK_TYPES: frozenset[str] = frozenset(
    {"THUMBS_UP", "THUMBS_DOWN", "FEEDBACK_TYPE_UNSPECIFIED"}
)
POSITIVE_FEEDBACK_LABELS: frozenset[str] = frozenset(
    {"accurate", "complete", "helpful", "on_topic", "fast", "safe", "factual", "tool_success"}
)
NEGATIVE_FEEDBACK_LABELS: frozenset[str] = frozenset(
    {
        "inaccurate",
        "incomplete",
        "unhelpful",
        "off_topic",
        "too_slow",
        "unsafe",
        "hallucination",
        "tool_error",
    }
)

DEFAULT_PREVIEW_MAX_CHARS = 1_000
DEFAULT_TOOL_LOG_ID = "coding-agent-tools"

_LOG_SECRET_PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = (
    (
        "private_key",
        re.compile(
            r"-----BEGIN [A-Z0-9 ]+ PRIVATE KEY-----.*?-----END [A-Z0-9 ]+ PRIVATE KEY-----",
            re.DOTALL,
        ),
    ),
    ("gcp_api_key", re.compile(r"\bAIza[0-9A-Za-z\-_]{35}\b")),
    ("bearer_token", re.compile(r"(?i)\bBearer\s+[A-Za-z0-9\-._~+/]+=*")),
    ("token_prefix", re.compile(r"\b(?:sk-[A-Za-z0-9]{20,}|gh[pousr]_[A-Za-z0-9]{20,}|AKIA[0-9A-Z]{16})\b")),
    (
        "env_secret",
        re.compile(
            r"(?i)\b([A-Z0-9_]*(?:API_KEY|SECRET|TOKEN|PASSWORD|PRIVATE_KEY)[A-Z0-9_]*)"
            r"\s*=\s*['\"]?([^\s'\"]{6,})['\"]?"
        ),
    ),
)


# ---------------------------------------------------------------------------
# OTel Validation & Secret-Redacted Sandbox Output Helpers
# ---------------------------------------------------------------------------


def validate_otel_environment(env: Mapping[str, str] | None = None) -> list[str]:
    """Check ADK Python OTel environment variables and return actionable warnings."""
    source = os.environ if env is None else env
    warnings: list[str] = []

    if source.get("GOOGLE_CLOUD_AGENT_ENGINE_ENABLE_TELEMETRY", "").lower() != "true":
        warnings.append(
            "GOOGLE_CLOUD_AGENT_ENGINE_ENABLE_TELEMETRY is not set to 'true'; "
            "Agent Runtime OTel traces, logs, and GenAI metrics will not be exported."
        )

    semconv = source.get("OTEL_SEMCONV_STABILITY_OPT_IN", "")
    if semconv != "gen_ai_latest_experimental":
        warnings.append(
            "OTEL_SEMCONV_STABILITY_OPT_IN should be 'gen_ai_latest_experimental' for "
            f"latest OTel GenAI semantic conventions (current: {semconv!r})."
        )

    capture = source.get("OTEL_INSTRUMENTATION_GENAI_CAPTURE_MESSAGE_CONTENT", "")
    if capture and capture not in VALID_PYTHON_CAPTURE_CONTENT_VALUES:
        warnings.append(
            f"Invalid ADK Python OTEL_INSTRUMENTATION_GENAI_CAPTURE_MESSAGE_CONTENT={capture!r}. "
            "Must be one of NO_CONTENT, EVENT_ONLY, SPAN_ONLY, or SPAN_AND_EVENT "
            "(passing 'true' silently falls back to NO_CONTENT in ADK Python!)."
        )
    elif not capture:
        warnings.append(
            "OTEL_INSTRUMENTATION_GENAI_CAPTURE_MESSAGE_CONTENT is unset; set 'EVENT_ONLY' "
            "to capture prompt/response events and user.id (requires ADK >= 2.1)."
        )
    return warnings


def redact_and_truncate_preview(text: str, max_chars: int = DEFAULT_PREVIEW_MAX_CHARS) -> str:
    """Redact common credential patterns and truncate sandbox output previews safely."""
    if not text:
        return ""
    redacted = text
    for kind, pattern in _LOG_SECRET_PATTERNS:
        if kind == "env_secret":
            redacted = pattern.sub(r"\1=[REDACTED]", redacted)
        else:
            redacted = pattern.sub("[REDACTED]", redacted)
    if len(redacted) <= max_chars:
        return redacted
    return f"{redacted[:max_chars]}... [truncated {len(redacted) - max_chars} chars]"


def _extract_tool_execution_fields(tool_response: Any) -> dict[str, Any]:
    """Normalize stdout/stderr/exit_code from dict, ExecutionResult, or custom response objects."""
    stdout = ""
    stderr = ""
    exit_code: int | None = None
    timed_out = False

    if isinstance(tool_response, Mapping):
        stdout = str(tool_response.get("stdout") or "")
        stderr = str(tool_response.get("stderr") or "")
        raw_code = tool_response.get("exit_code")
        if raw_code is None:
            raw_code = tool_response.get("returncode")
        if raw_code is not None:
            try:
                exit_code = int(raw_code)
            except (TypeError, ValueError):
                exit_code = None
        timed_out = bool(tool_response.get("timed_out", False))
    elif tool_response is not None and not isinstance(tool_response, str | bytes):
        stdout = str(getattr(tool_response, "stdout", "") or "")
        stderr = str(getattr(tool_response, "stderr", "") or "")
        raw_code = getattr(tool_response, "exit_code", None)
        if raw_code is None:
            raw_code = getattr(tool_response, "returncode", None)
        if raw_code is not None:
            try:
                exit_code = int(raw_code)
            except (TypeError, ValueError):
                exit_code = None
        timed_out = bool(getattr(tool_response, "timed_out", False))
    elif isinstance(tool_response, str):
        stdout = tool_response

    return {
        "stdout": stdout,
        "stderr": stderr,
        "exit_code": exit_code,
        "timed_out": timed_out,
    }


def _current_trace_info(project_id: str) -> tuple[str | None, str | None]:
    """Return ``(hex_trace_id, cloud_logging_trace_resource)`` from the active OTel span."""
    span = trace.get_current_span()
    if span is None:
        return None, None
    span_ctx = span.get_span_context()
    if span_ctx is None or not getattr(span_ctx, "is_valid", False):
        return None, None
    trace_hex = f"{span_ctx.trace_id:032x}"
    trace_resource = f"projects/{project_id}/traces/{trace_hex}" if project_id else trace_hex
    return trace_hex, trace_resource


# ---------------------------------------------------------------------------
# Structured Cloud Logging Builder (`aiplatform.googleapis.com/ReasoningEngine`)
# ---------------------------------------------------------------------------


def build_reasoning_engine_logger(
    project_id: str,
    location: str,
    log_id: str = DEFAULT_TOOL_LOG_ID,
    reasoning_engine_id: str | None = None,
) -> Any:
    """Create a Cloud Logging logger bound to ``aiplatform.googleapis.com/ReasoningEngine``.

    Because Cloud Logging is NOT supported for child resources (Managed Sandboxes,
    Sessions, Memory Bank, Code Execution), parent-runtime tool callbacks write
    structured sandbox execution logs through this monitored resource.
    """
    import google.cloud.logging

    engine_id = (
        reasoning_engine_id
        or os.environ.get("GOOGLE_CLOUD_AGENT_ENGINE_ID")
        or get_settings().reasoning_engine_id
        or "local-dev"
    )
    logging_client = google.cloud.logging.Client(project=project_id)
    resource = google.cloud.logging.Resource(
        type="aiplatform.googleapis.com/ReasoningEngine",
        labels={
            "location": location,
            "resource_container": project_id,
            "reasoning_engine_id": engine_id,
        },
    )
    return logging_client.logger(name=log_id, resource=resource)


@functools.lru_cache(maxsize=8)
def _get_cached_cloud_logger(
    project_id: str,
    location: str,
    log_id: str,
    reasoning_engine_id: str | None = None,
) -> Any | None:
    """Lazily initialize Cloud Logging logger, falling back to ``None`` when offline."""
    if not project_id:
        return None
    try:
        return build_reasoning_engine_logger(
            project_id=project_id,
            location=location,
            log_id=log_id,
            reasoning_engine_id=reasoning_engine_id,
        )
    except Exception as exc:
        logger.debug("Cloud Logging unavailable (%s); emitting structured JSON locally.", exc)
        return None


def _emit_structured_tool_log(
    payload: dict[str, Any],
    *,
    severity: str,
    cloud_logger: Any | None,
    labels: dict[str, str],
    trace_resource: str | None,
) -> None:
    """Emit structured JSON log to Cloud Logging (or local stdlib JSON fallback)."""
    if cloud_logger is not None:
        try:
            kwargs: dict[str, Any] = {"severity": severity, "labels": labels}
            if trace_resource:
                kwargs["trace"] = trace_resource
            cloud_logger.log_struct(payload, **kwargs)
            return
        except Exception as exc:
            logger.debug("Cloud Logging log_struct failed (%s); falling back to stdlib logger.", exc)

    log_level = logging.WARNING if severity in {"WARNING", "ERROR", "CRITICAL"} else logging.INFO
    logger.log(log_level, "%s", json.dumps({"severity": severity, **payload}, default=str))


# ---------------------------------------------------------------------------
# ADK Tool Callbacks (before_tool_callback / after_tool_callback)
# ---------------------------------------------------------------------------


def before_tool_callback(
    tool: Any,
    args: dict[str, Any],
    tool_context: Any,
) -> dict[str, Any] | None:
    """Record tool start timestamp and annotate the active OpenTelemetry span.

    Returns ``None`` so ADK continues executing the tool normally.
    """
    tool_name = str(getattr(tool, "name", None) or getattr(tool, "__name__", "tool"))
    state = getattr(tool_context, "state", None)
    if state is not None:
        state[f"_tool_start_ts:{tool_name}"] = time.monotonic()

    span = trace.get_current_span()
    if span is not None and span.is_recording():
        span.set_attribute("coding_agent.tool.name", tool_name)
        if isinstance(args, Mapping):
            span.set_attribute("coding_agent.tool.arg_keys", ",".join(sorted(str(k) for k in args)))
    return None


def after_tool_callback(
    tool: Any,
    args: dict[str, Any],
    tool_context: Any,
    tool_response: Any,
    *,
    cloud_logger: Any | None = None,
    preview_max_chars: int = DEFAULT_PREVIEW_MAX_CHARS,
) -> dict[str, Any] | None:
    """Emit OTel tool attributes and parent-runtime structured Cloud Logs for sandbox output.

    Captures truncated, secret-redacted ``stdout`` / ``stderr`` previews and ``exit_code``
    under the parent ``aiplatform.googleapis.com/ReasoningEngine`` resource so sandbox
    activity remains auditable in Cloud Logging despite child-resource log limits.
    Returns ``None`` so ADK preserves the original ``tool_response``.
    """
    del args
    tool_name = str(getattr(tool, "name", None) or getattr(tool, "__name__", "tool"))
    state = getattr(tool_context, "state", None)
    start_key = f"_tool_start_ts:{tool_name}"
    start_ts = state.get(start_key, None) if state is not None else None
    if state is not None and start_ts is not None:
        state[start_key] = None
    duration_ms = int((time.monotonic() - start_ts) * 1000) if start_ts is not None else -1

    fields = _extract_tool_execution_fields(tool_response)
    stdout_text: str = fields["stdout"]
    stderr_text: str = fields["stderr"]
    exit_code: int | None = fields["exit_code"]
    timed_out: bool = fields["timed_out"]

    settings = get_settings()
    project_id = settings.google_cloud_project
    location = settings.google_cloud_location
    trace_hex, trace_resource = _current_trace_info(project_id)

    span = trace.get_current_span()
    if span is not None and span.is_recording():
        span.set_attribute("coding_agent.tool.name", tool_name)
        if duration_ms >= 0:
            span.set_attribute("coding_agent.tool.duration_ms", duration_ms)
        if exit_code is not None:
            span.set_attribute("coding_agent.sandbox.exit_code", exit_code)
        if stdout_text:
            span.set_attribute("coding_agent.sandbox.stdout_bytes", len(stdout_text.encode("utf-8")))
        if stderr_text:
            span.set_attribute("coding_agent.sandbox.stderr_bytes", len(stderr_text.encode("utf-8")))
        if timed_out:
            span.set_attribute("coding_agent.sandbox.timed_out", True)

    invocation_ctx = getattr(tool_context, "_invocation_context", None)
    session_obj = getattr(invocation_ctx, "session", None)
    session_id = str(
        getattr(tool_context, "session_id", None)
        or (getattr(session_obj, "id", "") if session_obj is not None else "")
    )
    invocation_id = str(getattr(tool_context, "invocation_id", "") or "")

    severity = "INFO" if exit_code in (None, 0) and not timed_out else "WARNING"
    payload: dict[str, Any] = {
        "event": "sandbox_tool_execution" if exit_code is not None else "tool_execution",
        "tool_name": tool_name,
        "duration_ms": duration_ms,
        "exit_code": exit_code,
        "timed_out": timed_out,
        "sandbox_mode": settings.sandbox_mode,
        "stdout_preview": redact_and_truncate_preview(stdout_text, max_chars=preview_max_chars),
        "stderr_preview": redact_and_truncate_preview(stderr_text, max_chars=preview_max_chars),
        "session_id": session_id,
        "invocation_id": invocation_id,
        "trace_id": trace_hex or "",
    }

    target_logger = (
        cloud_logger
        if cloud_logger is not None
        else _get_cached_cloud_logger(project_id, location, DEFAULT_TOOL_LOG_ID)
    )
    _emit_structured_tool_log(
        payload,
        severity=severity,
        cloud_logger=target_logger,
        labels={"tool_name": tool_name, "sandbox_mode": settings.sandbox_mode},
        trace_resource=trace_resource,
    )
    return None


def make_telemetry_callbacks(
    *,
    cloud_logger: Any | None = None,
    preview_max_chars: int = DEFAULT_PREVIEW_MAX_CHARS,
) -> tuple[Callable[..., Any], Callable[..., Any]]:
    """Return a bound ``(before_tool_callback, after_tool_callback)`` pair for DI or testing."""

    def _after(
        tool: Any,
        args: dict[str, Any],
        tool_context: Any,
        tool_response: Any,
    ) -> dict[str, Any] | None:
        return after_tool_callback(
            tool,
            args,
            tool_context,
            tool_response,
            cloud_logger=cloud_logger,
            preview_max_chars=preview_max_chars,
        )

    return before_tool_callback, _after


def build_parent_sandbox_log_callbacks(
    project_id: str | None = None,
    location: str | None = None,
    *,
    cloud_logger: Any | None = None,
    log_id: str = DEFAULT_TOOL_LOG_ID,
    reasoning_engine_id: str | None = None,
    preview_max_chars: int = DEFAULT_PREVIEW_MAX_CHARS,
) -> tuple[Callable[..., Any], Callable[..., Any]]:
    """Build ``(before_tool_callback, after_tool_callback)`` for parent-runtime sandbox logs.

    Lazily resolves a cached ``aiplatform.googleapis.com/ReasoningEngine`` Cloud Logger when
    ``cloud_logger`` is ``None`` and ``project_id`` is provided (with safe offline fallback
    to local structured JSON logging), then delegates to ``make_telemetry_callbacks(...)``.
    """
    resolved_logger = cloud_logger
    normalized_project = (project_id or "").strip()
    if resolved_logger is None and normalized_project:
        resolved_location = (
            (location or "").strip()
            or get_settings().google_cloud_location
            or "asia-southeast1"
        )
        normalized_engine_id = (reasoning_engine_id or "").strip() or None
        resolved_logger = _get_cached_cloud_logger(
            normalized_project,
            resolved_location,
            log_id,
            normalized_engine_id,
        )
    return make_telemetry_callbacks(
        cloud_logger=resolved_logger,
        preview_max_chars=preview_max_chars,
    )


# ---------------------------------------------------------------------------
# Agent Platform Feedback Service Client
# ---------------------------------------------------------------------------


def _extract_entry_name(operation_or_entry: Any) -> str:
    """Return ``operation.response.name`` for LROs or ``entry.name`` directly."""
    resp = getattr(operation_or_entry, "response", None)
    if resp is not None and getattr(resp, "name", None):
        return str(resp.name)
    name = getattr(operation_or_entry, "name", None)
    if name:
        return str(name)
    raise ValueError(f"Unable to extract feedback entry name from: {operation_or_entry!r}")


class FeedbackClient:
    """Wrapper around ``agentplatform.Client.feedback_entries`` linked to sessions & traces.

    Key Platform Rules:
    - Requires ``os.environ["GOOGLE_GENAI_USE_ENTERPRISE"] = "TRUE"`` and ``roles/aiplatform.user``.
    - ``event_id`` MUST match the OTel span attribute ``gcp.vertex.agent.event_id`` (or
      ``raw_event.id`` in Managed Sessions) to display alongside traces in Console UI.
    - Creating a feedback entry exports an **immutable** Cloud Trace span
      ``gcp.vertex.agent.feedback``. Updating or deleting feedback does not alter
      already-exported spans.
    - Verified SDK path quirk: ``feedback_contexts.update`` takes ``name=entry_name``
      (``.../feedbackEntries/ID``), whereas ``feedback_contexts.get`` takes
      ``name=f"{entry_name}/feedbackContext"``.
    """

    def __init__(
        self,
        project_id: str,
        location: str = "asia-southeast1",
        runtime_name: str = "",
        *,
        client: Any | None = None,
    ) -> None:
        os.environ["GOOGLE_GENAI_USE_ENTERPRISE"] = "TRUE"
        self.project_id = project_id
        self.location = location
        self._runtime_name = runtime_name.strip()
        self._client = client

    @classmethod
    def from_settings(cls, settings: Settings | None = None) -> FeedbackClient:
        """Create a ``FeedbackClient`` initialized from environment ``Settings``."""
        cfg = settings or get_settings()
        return cls(
            project_id=cfg.require_gcp_project(),
            location=cfg.google_cloud_location,
            runtime_name=cfg.reasoning_engine_name,
        )

    @property
    def client(self) -> Any:
        if self._client is None:
            os.environ["GOOGLE_GENAI_USE_ENTERPRISE"] = "TRUE"
            import agentplatform

            self._client = agentplatform.Client(project=self.project_id, location=self.location)
        return self._client

    @property
    def runtime_name(self) -> str:
        return self._runtime_name

    def _require_runtime_name(self) -> str:
        if not self._runtime_name:
            raise ValueError(
                "runtime_name (REASONING_ENGINE_NAME) is required for Feedback Service operations."
            )
        return self._runtime_name

    def submit_feedback(
        self,
        session_id: str,
        event_id: str,
        feedback_type: str = "THUMBS_UP",
        feedback_text: str = "",
        feedback_labels: list[str] | None = None,
        user_id: str = "",
        source: str = "Workshop IDE",
        custom_metadata: dict[str, str] | None = None,
        *,
        score: float | None = None,
        trace_id: str | None = None,
    ) -> str:
        """Submit thumbs/comment/score feedback linked to ``session_id`` and ``event_id``.

        Native Feedback Service fields are ``feedback_type`` (``THUMBS_UP`` /
        ``THUMBS_DOWN`` / ``FEEDBACK_TYPE_UNSPECIFIED``), ``feedback_labels``,
        ``feedback_text``, and string ``custom_metadata``. Optional numeric ``score``
        and OTel ``trace_id`` (auto-read from the active span if omitted) are attached
        inside ``custom_metadata`` as strings.
        """
        if feedback_type not in VALID_FEEDBACK_TYPES:
            valid = ", ".join(sorted(VALID_FEEDBACK_TYPES))
            raise ValueError(f"Invalid feedback_type={feedback_type!r}. Expected one of: {valid}.")
        if not session_id or not event_id:
            raise ValueError("Both session_id and event_id are required to submit feedback.")

        merged_metadata: dict[str, str] = {
            str(k): str(v) for k, v in (custom_metadata or {}).items()
        }
        if score is not None:
            merged_metadata["score"] = f"{float(score):.3f}"
        resolved_trace_id = trace_id
        if not resolved_trace_id:
            active_trace_hex, _ = _current_trace_info(self.project_id)
            resolved_trace_id = active_trace_hex
        if resolved_trace_id:
            merged_metadata["trace_id"] = resolved_trace_id

        config: dict[str, Any] = {
            "feedback_text": feedback_text,
            "feedback_labels": list(feedback_labels or []),
            "source": source,
            "custom_metadata": merged_metadata,
        }
        if user_id:
            config["user_id"] = user_id

        op = self.client.feedback_entries.create(
            name=self._require_runtime_name(),
            session_id=session_id,
            event_id=event_id,
            feedback_type=feedback_type,
            config=config,
        )
        return _extract_entry_name(op)

    def get_feedback(self, entry_name: str) -> Any:
        """Fetch a single feedback entry by full resource name."""
        return self.client.feedback_entries.get(name=entry_name)

    def update_feedback(
        self,
        entry_name: str,
        *,
        feedback_type: str,
        feedback_text: str | None = None,
        feedback_labels: list[str] | None = None,
    ) -> Any:
        """Update an existing feedback entry (note: exported Cloud Trace spans are immutable)."""
        if feedback_type not in VALID_FEEDBACK_TYPES:
            valid = ", ".join(sorted(VALID_FEEDBACK_TYPES))
            raise ValueError(f"Invalid feedback_type={feedback_type!r}. Expected one of: {valid}.")
        config: dict[str, Any] = {}
        if feedback_text is not None:
            config["feedback_text"] = feedback_text
        if feedback_labels is not None:
            config["feedback_labels"] = list(feedback_labels)
        return self.client.feedback_entries.update(
            name=entry_name,
            feedback_type=feedback_type,
            config=config,
        )

    def attach_context_snapshot(
        self,
        entry_name: str,
        context_events: list[dict[str, Any]],
    ) -> Any:
        """Preserve transcript events in ``FeedbackContext`` even if the original session expires.

        Verified SDK path quirk: ``feedback_contexts.update()`` takes ``name=entry_name``
        (``.../feedbackEntries/ID``), NOT ``.../feedbackContext``.
        """
        return self.client.feedback_entries.feedback_contexts.update(
            name=entry_name,
            context_events=context_events,
        )

    def get_context_snapshot(self, entry_name: str) -> Any:
        """Retrieve the persisted ``FeedbackContext`` for a feedback entry.

        Verified SDK path quirk: ``feedback_contexts.get()`` takes
        ``name=f"{entry_name}/feedbackContext"``.
        """
        target = (
            entry_name
            if entry_name.endswith("/feedbackContext")
            else f"{entry_name}/feedbackContext"
        )
        return self.client.feedback_entries.feedback_contexts.get(name=target)

    def list_session_feedback(
        self,
        session_id: str,
        *,
        order_by: str = "create_time desc",
    ) -> list[Any]:
        """List feedback entries filtered to a single ``session_id``."""
        escaped = session_id.replace("\\", "\\\\").replace('"', '\\"')
        return list(
            self.client.feedback_entries.list(
                parent=self._require_runtime_name(),
                config={
                    "filter": f'session_id="{escaped}"',
                    "order_by": order_by,
                },
            )
        )

    def delete_feedback(self, entry_name: str) -> None:
        """Delete a feedback entry (automatically deletes its child ``FeedbackContext``)."""
        self.client.feedback_entries.delete(name=entry_name)


# ---------------------------------------------------------------------------
# Runnable CLI (`python -m coding_agent.callbacks.telemetry_and_feedback ...`)
# ---------------------------------------------------------------------------


def _run_offline_check() -> dict[str, Any]:
    """Verify OTel env validator, redaction preview, and callback execution offline."""

    class _DummyTool:
        name = "Execute"

    class _DummyToolContext:
        def __init__(self) -> None:
            self.state: dict[str, Any] = {}
            self.session_id = "offline-session-1"
            self.invocation_id = "inv-offline-1"

    captured_logs: list[dict[str, Any]] = []

    class _RecordingLogger:
        def log_struct(self, info: dict[str, Any], **kwargs: Any) -> None:
            captured_logs.append({"payload": info, **kwargs})

    before_cb, after_cb = make_telemetry_callbacks(cloud_logger=_RecordingLogger())
    ctx = _DummyToolContext()
    tool = _DummyTool()
    before_cb(tool, {"command": "pytest -q"}, ctx)
    after_cb(
        tool,
        {"command": "pytest -q"},
        ctx,
        {
            "stdout": "3 passed in 0.12s\nAPI_KEY=supersecretvalue12345",
            "stderr": "",
            "returncode": 0,
        },
    )
    return {
        "mode": "offline-check",
        "otel_warnings": validate_otel_environment(),
        "recorded_log_count": len(captured_logs),
        "recorded_log": captured_logs[0] if captured_logs else None,
    }


def _build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m coding_agent.callbacks.telemetry_and_feedback",
        description="Verify OTel/Cloud Logging tool callbacks and submit Agent Platform feedback.",
    )
    parser.add_argument("--project", help="GCP project ID (defaults to GOOGLE_CLOUD_PROJECT).")
    parser.add_argument("--location", help="GCP location (defaults to GOOGLE_CLOUD_LOCATION).")
    parser.add_argument(
        "--runtime-name",
        help="ReasoningEngine resource name (defaults to REASONING_ENGINE_NAME).",
    )
    parser.add_argument("--offline-check", action="store_true", help="Run local callback & OTel check.")
    parser.add_argument("--session-id", default=None, help="Session ID for feedback submission/listing.")
    parser.add_argument(
        "--event-id",
        default=None,
        help="OTel gcp.vertex.agent.event_id / raw_event.id UUID for feedback linking.",
    )
    parser.add_argument(
        "--feedback-type",
        choices=sorted(VALID_FEEDBACK_TYPES),
        default="THUMBS_UP",
    )
    parser.add_argument("--feedback-text", default="Accurate sandbox verification.")
    parser.add_argument("--labels", default="accurate,tool_success", help="Comma-separated labels.")
    parser.add_argument("--score", type=float, default=None, help="Optional numeric score (0..1 or 1..5).")
    parser.add_argument("--trace-id", default=None, help="Optional OTel trace ID to record in metadata.")
    parser.add_argument("--user-id", default="workshop-dev")
    parser.add_argument("--list-feedback", action="store_true", help="List feedback for --session-id.")
    parser.add_argument(
        "--delete-feedback",
        action="store_true",
        help="Delete a feedback entry specified by --entry-name.",
    )
    parser.add_argument(
        "--entry-name",
        default=None,
        help="Full feedback entry resource name for --delete-feedback.",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    args = _build_arg_parser().parse_args(argv)

    if args.offline_check:
        print(json.dumps(_run_offline_check(), indent=2, default=str))
        return 0

    settings = get_settings()
    client = FeedbackClient(
        project_id=args.project or settings.require_gcp_project(),
        location=args.location or settings.google_cloud_location,
        runtime_name=args.runtime_name or settings.reasoning_engine_name,
    )

    output: Any
    if args.delete_feedback:
        if not args.entry_name:
            raise ValueError("--entry-name is required with --delete-feedback.")
        client.delete_feedback(args.entry_name)
        output = {"deleted_feedback_entry": args.entry_name}
    elif args.list_feedback:
        if not args.session_id:
            raise ValueError("--session-id is required with --list-feedback.")
        entries = client.list_session_feedback(args.session_id)
        output = [
            {
                "name": getattr(e, "name", str(e)),
                "feedback_type": getattr(e, "feedback_type", ""),
                "feedback_text": getattr(e, "feedback_text", ""),
            }
            for e in entries
        ]
    else:
        if not args.session_id or not args.event_id:
            raise ValueError("Provide --session-id and --event-id (or pass --offline-check).")
        labels = [item.strip() for item in args.labels.split(",") if item.strip()]
        entry_name = client.submit_feedback(
            session_id=args.session_id,
            event_id=args.event_id,
            feedback_type=args.feedback_type,
            feedback_text=args.feedback_text,
            feedback_labels=labels,
            user_id=args.user_id,
            score=args.score,
            trace_id=args.trace_id,
        )
        output = {"created_feedback_entry": entry_name}

    print(json.dumps(output, indent=2, default=str))
    return 0


if __name__ == "__main__":
    sys.exit(main())
