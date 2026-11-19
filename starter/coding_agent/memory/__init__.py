"""Stateful persistence modules for the Enterprise Coding Agent (starter track).

Uses PEP 562 lazy attribute loading so CLI invocations such as
``python -m coding_agent.memory.session_manager`` or
``python -m coding_agent.memory.memory_bank_manager`` avoid importing optional
dependencies unnecessarily.
"""

from __future__ import annotations

import importlib
from typing import Any

__all__ = [
    "MemoryBankManager",
    "SessionLifecycleManager",
    "build_adk_memory_service",
    "build_adk_session_service",
    "memory_bank_manager",
    "persist_turn_to_memory_callback",
    "sanitize_for_memory_ingestion",
    "session_manager",
]

_SESSION_EXPORTS = frozenset({"SessionLifecycleManager", "build_adk_session_service"})
_MEMORY_EXPORTS = frozenset(
    {
        "MemoryBankManager",
        "build_adk_memory_service",
        "persist_turn_to_memory_callback",
        "sanitize_for_memory_ingestion",
    }
)


def __getattr__(name: str) -> Any:
    if name == "session_manager":
        return importlib.import_module("coding_agent.memory.session_manager")
    if name == "memory_bank_manager":
        return importlib.import_module("coding_agent.memory.memory_bank_manager")
    if name in _SESSION_EXPORTS:
        module = importlib.import_module("coding_agent.memory.session_manager")
        return getattr(module, name)
    if name in _MEMORY_EXPORTS:
        module = importlib.import_module("coding_agent.memory.memory_bank_manager")
        return getattr(module, name)
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
