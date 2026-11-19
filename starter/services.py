"""ADK Python 2.0+ Programmatic Service Registration (Starter Track).

Reference: https://adk.dev/agents/service-registration/

ADK CLI tools (``adk web``, ``adk api_server``, and ``adk run``) automatically
discover and load ``services.yaml`` first and ``services.py`` second:
- ``adk web`` / ``adk api_server`` discover service files in the agents root
  directory (``starter/``).
- ``adk run`` discovers service files in the agent directory.
- On URI ``scheme`` collision, registrations in ``services.py`` take precedence
  and override definitions loaded from ``services.yaml``.

Guarded behind ``ENABLE_CUSTOM_SERVICE_REGISTRY=true`` so ``adk web`` and
``adk run`` start cleanly out-of-the-box without requiring third-party backends.
"""

from __future__ import annotations

import logging
import os
from typing import Any

logger = logging.getLogger(__name__)


def custom_session_factory(uri: str, **kwargs: Any) -> Any:
    """Example custom session service factory for ``mysession://...`` URIs.

    Replace ``InMemorySessionService`` with your custom ``BaseSessionService``
    implementation (or wrap ``VertexAiSessionService`` with custom auth/routing).
    """
    from google.adk.sessions import InMemorySessionService

    logger.info("Initializing custom session service for uri=%s (kwargs=%s)", uri, sorted(kwargs))
    return InMemorySessionService()


def custom_artifact_factory(uri: str, **kwargs: Any) -> Any:
    """Example custom artifact service factory for ``myartifact://...`` URIs."""
    from google.adk.artifacts import InMemoryArtifactService

    logger.info("Initializing custom artifact service for uri=%s (kwargs=%s)", uri, sorted(kwargs))
    return InMemoryArtifactService()


def custom_memory_factory(uri: str, **kwargs: Any) -> Any:
    """Example custom memory service factory for ``mymemory://...`` URIs."""
    from google.adk.memory import InMemoryMemoryService

    logger.info("Initializing custom memory service for uri=%s (kwargs=%s)", uri, sorted(kwargs))
    return InMemoryMemoryService()


def register_custom_services() -> None:
    """Register custom URI schemes on the global ADK ``ServiceRegistry``.

    If ``services.yaml`` also defines ``mysession``, ``myartifact``, or
    ``mymemory``, these programmatic registrations override the YAML entries.
    """
    from google.adk.cli.service_registry import get_service_registry

    registry = get_service_registry()
    registry.register_session_service("mysession", custom_session_factory)
    registry.register_artifact_service("myartifact", custom_artifact_factory)
    registry.register_memory_service("mymemory", custom_memory_factory)


if os.environ.get("ENABLE_CUSTOM_SERVICE_REGISTRY") == "true":
    register_custom_services()
