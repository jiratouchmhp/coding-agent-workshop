"""ADK OTel Telemetry Callbacks, Sandbox Cloud Logging & Feedback Client (starter — Lab 4).

Complete the ``# TODO(lab-4)`` sections below to implement:
1. ``build_reasoning_engine_logger()`` bound to ``aiplatform.googleapis.com/ReasoningEngine``
   (mitigating the platform limitation that child resources — Managed Sandboxes, Sessions,
   Memory Bank, Code Execution — do NOT auto-stream logs to Cloud Logging).
2. ``before_tool_callback()`` and ``after_tool_callback()`` emitting OpenTelemetry tool
   span attributes and structured JSON Cloud Logs with secret-redacted sandbox
   ``stdout`` / ``stderr`` previews and ``exit_code``.
3. ``FeedbackClient`` submitting thumbs/score/comment feedback linked to ``session_id``
   and ``event_id`` (matching OTel ``gcp.vertex.agent.event_id`` / ``raw_event.id``) plus
   durable ``FeedbackContext`` transcript snapshots.
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
# OTel Validation & Secret-Redacted Sandbox Output Helpers (ready to use)
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
    elif tool_response is not None and not isinstance(tool_response, (str, bytes)):
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
    """Create a Cloud Logging logger bound to ``aiplatform.googleapis.com/ReasoningEngine``."""
    # TODO(lab-4): Import ``google.cloud.logging``, instantiate
    # ``google.cloud.logging.Client(project=project_id)`` and
    # ``google.cloud.logging.Resource(type="aiplatform.googleapis.com/ReasoningEngine",
    # labels={"location": location, "resource_container": project_id,
    # "reasoning_engine_id": reasoning_engine_id or os.environ.get("GOOGLE_CLOUD_AGENT_ENGINE_ID", "local-dev")})``,
    # and return ``logging_client.logger(name=log_id, resource=resource)``.
    _ = (project_id, location, log_id, reasoning_engine_id)
    raise NotImplementedError("Complete TODO(lab-4): build_reasoning_engine_logger()")


@functools.lru_cache(maxsize=4)
def _get_cached_cloud_logger(project_id: str, location: str, log_id: str) -> Any | None:
    if not project_id:
        return None
    try:
        return build_reasoning_engine_logger(
            project_id=project_id,
            location=location,
            log_id=log_id,
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
    """Record tool start timestamp and annotate the active OpenTelemetry span."""
    # TODO(lab-4): Store ``time.monotonic()`` in ``tool_context.state[f"_tool_start_ts:{tool_name}"]``,
    # set ``coding_agent.tool.name`` on ``trace.get_current_span()`` when recording, and return ``None``.
    _ = (tool, args, tool_context, time)
    raise NotImplementedError("Complete TODO(lab-4): before_tool_callback()")


def after_tool_callback(
    tool: Any,
    args: dict[str, Any],
    tool_context: Any,
    tool_response: Any,
    *,
    cloud_logger: Any | None = None,
    preview_max_chars: int = DEFAULT_PREVIEW_MAX_CHARS,
) -> dict[str, Any] | None:
    """Emit OTel tool attributes and parent-runtime structured Cloud Logs for sandbox output."""
    # TODO(lab-4):
    # 1. Pop start timestamp from ``tool_context.state`` and compute ``duration_ms``.
    # 2. Extract ``stdout``, ``stderr``, ``exit_code``, ``timed_out`` via ``_extract_tool_execution_fields``.
    # 3. Set OTel attributes (``coding_agent.tool.name``, ``coding_agent.tool.duration_ms``,
    #    ``coding_agent.sandbox.exit_code``) on ``trace.get_current_span()`` if recording.
    # 4. Call ``_emit_structured_tool_log(...)`` with ``redact_and_truncate_preview(stdout)`` and
    #    ``redact_and_truncate_preview(stderr)`` under severity ``INFO`` (exit_code in (None, 0))
    #    or ``WARNING`` so Managed Sandbox outputs are preserved in parent ReasoningEngine logs!
    # 5. Return ``None`` so ADK keeps the original ``tool_response``.
    _ = (tool, args, tool_context, tool_response, cloud_logger, preview_max_chars)
    raise NotImplementedError("Complete TODO(lab-4): after_tool_callback()")


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
    """Wrapper around ``agentplatform.Client.feedback_entries`` linked to sessions & traces."""

    def __init__(
        self,
        project_id: str,
        location: str = "us-central1",
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
        """Submit thumbs/comment/score feedback linked to ``session_id`` and ``event_id``."""
        if feedback_type not in VALID_FEEDBACK_TYPES:
            valid = ", ".join(sorted(VALID_FEEDBACK_TYPES))
            raise ValueError(f"Invalid feedback_type={feedback_type!r}. Expected one of: {valid}.")
        # TODO(lab-4): Merge optional ``score`` and ``trace_id`` (or active OTel trace ID)
        # into string-valued ``custom_metadata``, call ``self.client.feedback_entries.create(
        # name=self._require_runtime_name(), session_id=session_id, event_id=event_id,
        # feedback_type=feedback_type, config={...})``, and return ``_extract_entry_name(op)``.
        _ = (
            session_id,
            event_id,
            feedback_text,
            feedback_labels,
            user_id,
            source,
            custom_metadata,
            score,
            trace_id,
        )
        raise NotImplementedError("Complete TODO(lab-4): FeedbackClient.submit_feedback()")

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
        """Preserve transcript events in ``FeedbackContext`` even if the original session expires."""
        # TODO(lab-4): Call ``self.client.feedback_entries.feedback_contexts.update(
        # name=entry_name, context_events=context_events)``.
        # Verified SDK path quirk: pass ``entry_name`` (WITHOUT ``/feedbackContext``) to update!
        _ = (entry_name, context_events)
        raise NotImplementedError("Complete TODO(lab-4): FeedbackClient.attach_context_snapshot()")

    def get_context_snapshot(self, entry_name: str) -> Any:
        """Retrieve the persisted ``FeedbackContext`` for a feedback entry."""
        # TODO(lab-4): Call ``self.client.feedback_entries.feedback_contexts.get(
        # name=f"{entry_name}/feedbackContext")``.
        # Verified SDK path quirk: pass ``f"{entry_name}/feedbackContext"`` to get!
        _ = entry_name
        raise NotImplementedError("Complete TODO(lab-4): FeedbackClient.get_context_snapshot()")

    def list_session_feedback(
        self,
        session_id: str,
        *,
        order_by: str = "create_time desc",
    ) -> list[Any]:
        """List feedback entries filtered to a single ``session_id``."""
        # TODO(lab-4): Return ``list(self.client.feedback_entries.list(
        # name=self._require_runtime_name(),
        # config={"filter": f'session_id="{session_id}"', "order_by": order_by}))``.
        _ = (session_id, order_by)
        raise NotImplementedError("Complete TODO(lab-4): FeedbackClient.list_session_feedback()")

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
    if args.list_feedback:
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
