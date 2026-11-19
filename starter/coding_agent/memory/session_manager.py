"""Managed Sessions integration & lifecycle CLI (starter track — Lab 4).

Complete the ``# TODO(lab-4)`` sections below to wire:
1. **ADK Integration (`build_adk_session_service`):**
   Return ``VertexAiSessionService`` when GCP project + ``agent_engine_id`` are
   configured, with fallback to ``InMemorySessionService`` for offline local runs.
2. **Direct Agent Platform SDK (`SessionLifecycleManager`):**
   Wrap ``agentplatform.Client.sessions.{create, get, list, delete}`` and
   ``agentplatform.Client.sessions.events.{append, list}`` with safe handling for
   both LRO (``.response.name``) and direct Session (``.name``) return types.

Verified Platform Rules & Gotchas:
- ``user_id`` max length is **128 characters**.
- Custom ``session_id`` starting with a letter: up to **63 chars** ``[a-z0-9-]``
  ending with a letter/digit; starting with a digit: up to **9 chars** ``[0-9]``
  with no leading zeros.
- Default TTL is **365 days** if neither ``ttl`` nor ``expire_time`` is set.
- IAM Conditions use ``api.getAttribute('aiplatform.googleapis.com/sessionUserId', '')``
  (max **1,500** unique principals; ``ListSessions`` does **not** support IAM Conditions).
- When running ``adk web --session_service_uri=agentengine://<ID>``, ADK ignores
  ``.env`` — export ``GOOGLE_CLOUD_PROJECT`` and ``GOOGLE_CLOUD_LOCATION`` in the shell.
"""

from __future__ import annotations

import argparse
import datetime
import json
import logging
import os
import re
import sys
import time
import uuid
from dataclasses import asdict, dataclass
from typing import Any

from coding_agent.config import Settings, get_settings

logger = logging.getLogger(__name__)

DEFAULT_SESSION_TTL_DAYS = 10
MAX_USER_ID_LENGTH = 128
_LETTER_SESSION_ID_RE = re.compile(r"^[a-z](?:[a-z0-9-]{0,61}[a-z0-9])?$")
_DIGIT_SESSION_ID_RE = re.compile(r"^[1-9][0-9]{0,8}$")

SESSION_IAM_ROLES: tuple[str, ...] = (
    "roles/aiplatform.sessionViewer",
    "roles/aiplatform.sessionEditor",
    "roles/aiplatform.sessionUser",
)


# ---------------------------------------------------------------------------
# Validation, IAM Condition & ADK Event Helpers (ready to use)
# ---------------------------------------------------------------------------


def validate_session_identifiers(user_id: str, session_id: str | None = None) -> None:
    """Validate ``user_id`` and optional custom ``session_id`` against platform limits."""
    if not user_id or not user_id.strip():
        raise ValueError("user_id must be a non-empty string.")
    if len(user_id) > MAX_USER_ID_LENGTH:
        raise ValueError(
            f"user_id length ({len(user_id)}) exceeds the {MAX_USER_ID_LENGTH}-character limit."
        )
    if session_id is not None:
        if not session_id:
            raise ValueError("Custom session_id cannot be an empty string (pass None instead).")
        if not (
            _LETTER_SESSION_ID_RE.match(session_id) or _DIGIT_SESSION_ID_RE.match(session_id)
        ):
            raise ValueError(
                f"Invalid custom session_id={session_id!r}. Must either start with a lowercase "
                "letter (up to 63 chars [a-z0-9-], ending with letter/digit) or start with a "
                "non-zero digit (up to 9 digits [0-9], no leading zeros)."
            )


def build_session_iam_condition(user_id: str) -> str:
    """Return a CEL IAM Condition expression isolating Managed Sessions to one ``user_id``."""
    validate_session_identifiers(user_id)
    escaped = user_id.replace("\\", "\\\\").replace("'", "\\'")
    return f"api.getAttribute('aiplatform.googleapis.com/sessionUserId', '') == '{escaped}'"


def build_state_update_event(
    invocation_id: str,
    state_delta: dict[str, Any],
    *,
    author: str = "system",
    timestamp: float | None = None,
) -> Any:
    """Build an ADK ``Event`` carrying ``EventActions(state_delta=...)`` for out-of-band updates."""
    from google.adk.events import Event, EventActions

    return Event(
        invocation_id=invocation_id,
        author=author,
        actions=EventActions(state_delta=dict(state_delta)),
        timestamp=time.time() if timestamp is None else timestamp,
    )


def _build_agentplatform_client(project_id: str, location: str) -> Any:
    """Initialize ``agentplatform.Client`` with ``GOOGLE_GENAI_USE_ENTERPRISE=TRUE``."""
    os.environ.setdefault("GOOGLE_GENAI_USE_ENTERPRISE", "TRUE")
    import agentplatform

    return agentplatform.Client(project=project_id, location=location)


def _extract_session_name(operation_or_session: Any) -> str:
    """Safely extract session resource name from either an LRO or a direct Session object."""
    response = getattr(operation_or_session, "response", None)
    if response is not None and getattr(response, "name", None):
        return str(response.name)
    name = getattr(operation_or_session, "name", None)
    if name:
        return str(name)
    raise ValueError(
        f"Unable to extract session resource name from response object: {operation_or_session!r}"
    )


# ---------------------------------------------------------------------------
# ADK Session Service Builder
# ---------------------------------------------------------------------------


def build_adk_session_service(
    project_id: str | None = None,
    location: str = "us-central1",
    agent_engine_id: str | None = None,
) -> Any:
    """Return ``VertexAiSessionService`` when configured, else ``InMemorySessionService``.

    Falls back cleanly to ``InMemorySessionService`` for offline local runs when
    ``project_id`` or ``agent_engine_id`` is omitted.
    """
    # TODO(lab-4): Import ``InMemorySessionService`` and ``VertexAiSessionService`` from
    # ``google.adk.sessions``. When BOTH ``project_id`` and ``agent_engine_id`` are truthy,
    # set ``os.environ.setdefault("GOOGLE_GENAI_USE_ENTERPRISE", "TRUE")`` and return
    # ``VertexAiSessionService(project=project_id, location=location, agent_engine_id=agent_engine_id)``.
    # Otherwise return ``InMemorySessionService()``.
    _ = (project_id, location, agent_engine_id)
    raise NotImplementedError("Complete TODO(lab-4): build_adk_session_service()")


def build_adk_session_service_from_settings(settings: Settings | None = None) -> Any:
    """Build an ADK session service directly from environment ``Settings``."""
    cfg = settings or get_settings()
    return build_adk_session_service(
        project_id=cfg.google_cloud_project or None,
        location=cfg.google_cloud_location,
        agent_engine_id=cfg.reasoning_engine_id or None,
    )


# ---------------------------------------------------------------------------
# Direct Agent Platform Session Lifecycle Manager
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class SessionDemoReport:
    """Summary returned by ``SessionLifecycleManager.run_demo()``."""

    runtime_name: str
    session_name: str
    user_id: str
    appended_event_count: int
    listed_event_count: int
    listed_session_count: int
    deleted: bool
    iam_condition_example: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class SessionLifecycleManager:
    """Direct ``agentplatform.Client.sessions`` CRUD and event lifecycle wrapper."""

    def __init__(
        self,
        project_id: str,
        location: str = "us-central1",
        runtime_name: str = "",
        *,
        client: Any | None = None,
    ) -> None:
        self.project_id = project_id
        self.location = location
        self._runtime_name = runtime_name.strip()
        self._client = client

    @classmethod
    def from_settings(cls, settings: Settings | None = None) -> SessionLifecycleManager:
        """Create a ``SessionLifecycleManager`` initialized from environment ``Settings``."""
        cfg = settings or get_settings()
        return cls(
            project_id=cfg.require_gcp_project(),
            location=cfg.google_cloud_location,
            runtime_name=cfg.reasoning_engine_name,
        )

    @property
    def client(self) -> Any:
        if self._client is None:
            self._client = _build_agentplatform_client(self.project_id, self.location)
        return self._client

    @property
    def runtime_name(self) -> str:
        return self._runtime_name

    def ensure_parent_runtime(
        self,
        *,
        display_name: str = "Workshop Session Store",
        kms_key_name: str | None = None,
    ) -> str:
        """Return existing parent ``ReasoningEngine`` name or create a standalone parent."""
        if self._runtime_name:
            return self._runtime_name
        if kms_key_name and self.location == "global":
            raise ValueError("CMEK (kms_key_name) is not supported on location='global'.")

        config: dict[str, Any] = {"display_name": display_name}
        if kms_key_name:
            config["encryption_spec"] = {"kms_key_name": kms_key_name}

        remote_agent = self.client.runtimes.create(config=config)
        api_resource = getattr(remote_agent, "api_resource", remote_agent)
        self._runtime_name = str(api_resource.name)
        return self._runtime_name

    def _require_runtime_name(self) -> str:
        if not self._runtime_name:
            raise ValueError(
                "Parent runtime_name (REASONING_ENGINE_NAME) is not set. Set "
                "REASONING_ENGINE_NAME in `.env` or call ensure_parent_runtime()."
            )
        return self._runtime_name

    def create_session(
        self,
        user_id: str,
        session_id: str | None = None,
        ttl_days: int | None = DEFAULT_SESSION_TTL_DAYS,
        expire_time: datetime.datetime | None = None,
    ) -> str:
        """Create a Managed Session and return its canonical resource name."""
        validate_session_identifiers(user_id, session_id)
        if ttl_days is not None and expire_time is not None:
            raise ValueError("Specify either ttl_days or expire_time, not both.")
        if ttl_days is not None and ttl_days <= 0:
            raise ValueError(f"ttl_days must be positive, got {ttl_days}.")

        runtime_name = self._require_runtime_name()
        # TODO(lab-4): Build ``config`` with ``{"expire_time": expire_time}`` or
        # ``{"ttl": f"{ttl_days * 24 * 60 * 60}s"}``, call ``self.client.sessions.create(
        # name=runtime_name, user_id=user_id, ...)`` (passing ``session_id`` when provided),
        # and return ``_extract_session_name(session_op)`` so both LRO (.response.name)
        # and direct Session (.name) SDK responses work cleanly.
        _ = (runtime_name, session_id, ttl_days, expire_time)
        raise NotImplementedError("Complete TODO(lab-4): SessionLifecycleManager.create_session()")

    def get_session(self, session_name: str, user_id: str) -> Any:
        """Fetch a single Managed Session resource."""
        validate_session_identifiers(user_id)
        # TODO(lab-4): Return ``self.client.sessions.get(name=session_name, user_id=user_id)``.
        _ = (session_name, user_id)
        raise NotImplementedError("Complete TODO(lab-4): SessionLifecycleManager.get_session()")

    def list_sessions(self, user_id: str | None = None) -> list[Any]:
        """List Managed Sessions under the parent runtime (default order: ``create_time desc``)."""
        runtime_name = self._require_runtime_name()
        # TODO(lab-4): Call ``self.client.sessions.list(name=runtime_name, config={"filter": f"user_id={user_id}"})``
        # when ``user_id`` is provided (else omit ``config``) and return ``list(...)``.
        _ = (runtime_name, user_id)
        raise NotImplementedError("Complete TODO(lab-4): SessionLifecycleManager.list_sessions()")

    def append_event(
        self,
        session_name: str,
        author: str,
        invocation_id: str,
        *,
        text: str | None = None,
        role: str = "user",
        raw_event: dict[str, Any] | None = None,
        timestamp: datetime.datetime | None = None,
    ) -> Any:
        """Append either a structured ``content`` event or a custom ``raw_event`` payload."""
        if text is None and raw_event is None:
            raise ValueError("Provide either text or raw_event when appending a session event.")
        if text is not None and raw_event is not None:
            raise ValueError("Provide either text or raw_event, not both.")

        event_ts = timestamp or datetime.datetime.now(tz=datetime.timezone.utc)
        # TODO(lab-4): Build ``config={"raw_event": raw_event}`` or
        # ``config={"content": {"role": role, "parts": [{"text": text}]}}`` and return
        # ``self.client.sessions.events.append(name=session_name, author=author,
        # invocation_id=invocation_id, timestamp=event_ts, config=config)``.
        _ = (session_name, author, invocation_id, text, role, raw_event, event_ts)
        raise NotImplementedError("Complete TODO(lab-4): SessionLifecycleManager.append_event()")

    def append_text_event(
        self,
        session_name: str,
        author: str,
        invocation_id: str,
        text: str,
        role: str = "user",
    ) -> Any:
        """Append a standard conversational text event to a Managed Session."""
        return self.append_event(
            session_name=session_name,
            author=author,
            invocation_id=invocation_id,
            text=text,
            role=role,
        )

    def append_raw_event(
        self,
        session_name: str,
        author: str,
        invocation_id: str,
        raw_payload: dict[str, Any],
    ) -> Any:
        """Append a custom ``raw_event`` payload (useful for interop & Feedback ``raw_event.id``)."""
        return self.append_event(
            session_name=session_name,
            author=author,
            invocation_id=invocation_id,
            raw_event=raw_payload,
        )

    def list_events(self, session_name: str) -> list[Any]:
        """List all persisted events in a Managed Session."""
        # TODO(lab-4): Return ``list(self.client.sessions.events.list(name=session_name))``.
        _ = session_name
        raise NotImplementedError("Complete TODO(lab-4): SessionLifecycleManager.list_events()")

    def delete_session(self, session_name: str) -> None:
        """Delete a Managed Session by full resource name."""
        # TODO(lab-4): Call ``self.client.sessions.delete(name=session_name)``.
        _ = session_name
        raise NotImplementedError("Complete TODO(lab-4): SessionLifecycleManager.delete_session()")

    def run_demo(
        self,
        *,
        user_id: str = "workshop-dev",
        session_id: str | None = None,
        ttl_days: int = DEFAULT_SESSION_TTL_DAYS,
        keep_session: bool = False,
    ) -> SessionDemoReport:
        """Run an end-to-end Managed Sessions create -> append -> list -> get -> delete demo."""
        runtime_name = self.ensure_parent_runtime()
        effective_session_id = session_id or f"workshop-sess-{uuid.uuid4().hex[:8]}"
        session_name = self.create_session(
            user_id=user_id,
            session_id=effective_session_id,
            ttl_days=ttl_days,
        )

        event_uuid = str(uuid.uuid4())
        self.append_text_event(
            session_name=session_name,
            author="user",
            invocation_id="inv-demo-1",
            text="Audit coding_agent/agent.py and run pytest -q inside the sandbox.",
            role="user",
        )
        self.append_raw_event(
            session_name=session_name,
            author="coding_agent",
            invocation_id="inv-demo-1",
            raw_payload={
                "id": event_uuid,
                "content": "Sandbox tests passed (12 passed in 0.42s).",
                "sandbox_exit_code": 0,
            },
        )

        _ = self.get_session(session_name=session_name, user_id=user_id)
        events = self.list_events(session_name=session_name)
        sessions = self.list_sessions(user_id=user_id)

        deleted = False
        if not keep_session:
            self.delete_session(session_name=session_name)
            deleted = True

        return SessionDemoReport(
            runtime_name=runtime_name,
            session_name=session_name,
            user_id=user_id,
            appended_event_count=2,
            listed_event_count=len(events),
            listed_session_count=len(sessions),
            deleted=deleted,
            iam_condition_example=build_session_iam_condition(user_id),
        )


# ---------------------------------------------------------------------------
# Runnable CLI (`python -m coding_agent.memory.session_manager ...`)
# ---------------------------------------------------------------------------


def _run_offline_check(user_id: str, session_id: str | None) -> dict[str, Any]:
    """Verify local ADK session fallback, ID validation, and state-delta event creation."""
    validate_session_identifiers(user_id, session_id)
    service = build_adk_session_service(project_id=None, location="us-central1", agent_engine_id=None)
    state_event = build_state_update_event(
        invocation_id="inv-offline-check",
        state_delta={"active_repo": "payments-service", "test_cmd": "pytest -q"},
    )
    return {
        "mode": "offline-check",
        "adk_session_service_class": type(service).__name__,
        "user_id_valid": True,
        "session_id_valid": True,
        "iam_condition": build_session_iam_condition(user_id),
        "state_delta": dict(state_event.actions.state_delta),
    }


def _build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m coding_agent.memory.session_manager",
        description="Managed Sessions ADK builder & direct Agent Platform lifecycle CLI.",
    )
    parser.add_argument("--project", help="GCP project ID (defaults to GOOGLE_CLOUD_PROJECT).")
    parser.add_argument("--location", help="GCP location (defaults to GOOGLE_CLOUD_LOCATION).")
    parser.add_argument(
        "--runtime-name",
        help="Parent ReasoningEngine resource name (defaults to REASONING_ENGINE_NAME).",
    )
    parser.add_argument("--user-id", default="workshop-dev", help="End-user identifier (<=128 chars).")
    parser.add_argument("--session-id", default=None, help="Optional custom session ID.")
    parser.add_argument("--session-name", default=None, help="Full session resource name for get/delete/list-events.")
    parser.add_argument("--ttl-days", type=int, default=DEFAULT_SESSION_TTL_DAYS, help="Session TTL in days.")
    parser.add_argument("--keep", action="store_true", help="Keep demo session instead of deleting it.")

    action_group = parser.add_mutually_exclusive_group()
    action_group.add_argument("--demo", action="store_true", help="Run full create/append/list/get/delete demo.")
    action_group.add_argument("--offline-check", action="store_true", help="Verify offline ADK fallback & validators.")
    action_group.add_argument("--list", action="store_true", help="List sessions for --user-id.")
    action_group.add_argument("--list-events", action="store_true", help="List events for --session-name.")
    action_group.add_argument("--delete", action="store_true", help="Delete --session-name.")
    return parser


def main(argv: list[str] | None = None) -> int:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    args = _build_arg_parser().parse_args(argv)

    if args.offline_check:
        print(json.dumps(_run_offline_check(args.user_id, args.session_id), indent=2))
        return 0

    settings = get_settings()
    project_id = args.project or settings.require_gcp_project()
    location = args.location or settings.google_cloud_location
    runtime_name = args.runtime_name or settings.reasoning_engine_name

    manager = SessionLifecycleManager(
        project_id=project_id,
        location=location,
        runtime_name=runtime_name,
    )

    output: Any
    if args.list:
        sessions = manager.list_sessions(user_id=args.user_id)
        output = [str(getattr(s, "name", s)) for s in sessions]
    elif args.list_events:
        if not args.session_name:
            raise ValueError("--session-name is required with --list-events.")
        events = manager.list_events(session_name=args.session_name)
        output = [str(ev) for ev in events]
    elif args.delete:
        if not args.session_name:
            raise ValueError("--session-name is required with --delete.")
        manager.delete_session(session_name=args.session_name)
        output = {"deleted_session": args.session_name}
    else:
        report = manager.run_demo(
            user_id=args.user_id,
            session_id=args.session_id,
            ttl_days=args.ttl_days,
            keep_session=args.keep,
        )
        output = report.to_dict()

    print(json.dumps(output, indent=2, default=str))
    return 0


if __name__ == "__main__":
    sys.exit(main())
