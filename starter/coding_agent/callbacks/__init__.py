"""Telemetry and Feedback callback modules for the Enterprise Coding Agent (starter track)."""

from __future__ import annotations

import importlib
from typing import Any

__all__ = [
    "FeedbackClient",
    "after_tool_callback",
    "before_tool_callback",
    "build_reasoning_engine_logger",
    "make_telemetry_callbacks",
    "telemetry_and_feedback",
]

_CALLBACK_EXPORTS = frozenset(
    {
        "FeedbackClient",
        "after_tool_callback",
        "before_tool_callback",
        "build_reasoning_engine_logger",
        "make_telemetry_callbacks",
    }
)


def __getattr__(name: str) -> Any:
    if name == "telemetry_and_feedback":
        return importlib.import_module("coding_agent.callbacks.telemetry_and_feedback")
    if name in _CALLBACK_EXPORTS:
        module = importlib.import_module("coding_agent.callbacks.telemetry_and_feedback")
        return getattr(module, name)
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
