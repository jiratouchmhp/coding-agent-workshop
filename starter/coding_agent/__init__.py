"""Enterprise Coding Agent package (starter track).

Uses PEP 562 lazy attribute loading for ``agent``, ``root_agent``, and ``app``
so CLI utilities such as ``python -m coding_agent.tools.sandbox_lifecycle`` can
be executed cleanly without eagerly constructing the root ADK agent.
"""

from __future__ import annotations

import importlib
from typing import Any

from coding_agent.config import Settings, get_settings

__all__ = ["Settings", "agent", "app", "get_settings", "root_agent"]


def __getattr__(name: str) -> Any:
    if name == "agent":
        return importlib.import_module("coding_agent.agent")
    if name in {"root_agent", "app"}:
        agent_module = importlib.import_module("coding_agent.agent")
        return getattr(agent_module, name)
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
