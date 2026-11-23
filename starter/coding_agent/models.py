"""Frontier Gemini 4 model factory and GenerateContentConfig helpers (starter track).

Complete the focused Lab 1 checkpoint in ``build_gemini_model()`` to decouple
Vertex AI / Gemini Enterprise Gemini 4 inference (``MODEL_LOCATION=global`` for
``gemini-4-hydrogen`` and ``gemini-4-neon``) from regional Agent Platform resources
(``GOOGLE_CLOUD_LOCATION=asia-southeast1`` for Agent Runtime, Sandboxes, Sessions,
Memory Bank, and Feedback).

Supporting validation (``resolve_model_name``, ``validate_model_location``,
``_detect_enterprise_client_kwarg``) and ``build_gemini4_generate_config()`` are
pre-filled for the workshop.
"""

from __future__ import annotations

import inspect
import logging
from typing import TYPE_CHECKING, Any, Literal

from coding_agent.config import VALID_THINKING_LEVELS, Settings, get_settings

if TYPE_CHECKING:
    from google.adk.models import Gemini
    from google.genai import types

__all__ = [
    "GLOBAL_COMPATIBLE_MODEL_LOCATIONS",
    "GLOBAL_ONLY_GEMINI4_MODELS",
    "ModelRole",
    "REGIONAL_GEMINI4_ALTERNATIVE",
    "build_gemini4_generate_config",
    "build_gemini_model",
    "resolve_model_name",
    "validate_model_location",
]

logger = logging.getLogger(__name__)

ModelRole = Literal["coding", "reasoning"]

GLOBAL_ONLY_GEMINI4_MODELS: frozenset[str] = frozenset(
    {"gemini-4-hydrogen", "gemini-4-neon"}
)
REGIONAL_GEMINI4_ALTERNATIVE: str = "gemini-4-argon"
GLOBAL_COMPATIBLE_MODEL_LOCATIONS: frozenset[str] = frozenset({"global", "us", "eu"})


def resolve_model_name(
    settings: Settings,
    *,
    role: ModelRole = "coding",
    model_override: str | None = None,
) -> str:
    """Resolve the effective Gemini model ID for the requested agent role."""
    if model_override is not None and model_override.strip():
        return model_override.strip()
    if role == "coding":
        return settings.model_name
    if role == "reasoning":
        return settings.reasoning_model_name
    raise ValueError(f"Unsupported model role {role!r}. Expected 'coding' or 'reasoning'.")


def validate_model_location(model_name: str, model_location: str) -> str | None:
    """Warn if a global-only Gemini 4 model is paired with an incompatible regional endpoint."""
    normalized_model = model_name.strip().lower()
    normalized_loc = model_location.strip().lower() or "global"
    requires_global = normalized_model in GLOBAL_ONLY_GEMINI4_MODELS or any(
        normalized_model.startswith(f"{prefix}-") for prefix in GLOBAL_ONLY_GEMINI4_MODELS
    )
    if requires_global and normalized_loc not in GLOBAL_COMPATIBLE_MODEL_LOCATIONS:
        message = (
            f"Model {model_name!r} is paired with MODEL_LOCATION={model_location!r}, which is "
            "outside {'global', 'us', 'eu'}. Empirically, gemini-4-hydrogen and gemini-4-neon "
            "return HTTP 404 on asia-southeast1 and HTTP 501 on asia-southeast3. Set "
            "MODEL_LOCATION=global (keeping GOOGLE_CLOUD_LOCATION=asia-southeast1 for Agent "
            f"Runtime/Sandboxes), or switch to MODEL_NAME={REGIONAL_GEMINI4_ALTERNATIVE} for "
            "strict regional residency on asia-southeast1."
        )
        logger.warning("%s", message)
        return message
    return None


def _detect_enterprise_client_kwarg() -> Literal["enterprise", "vertexai"]:
    """Inspect ``google.genai.Client.__init__`` to select ``enterprise`` or ``vertexai`` safely."""
    from google import genai

    try:
        params = inspect.signature(genai.Client.__init__).parameters
    except (TypeError, ValueError):
        return "vertexai"
    return "enterprise" if "enterprise" in params else "vertexai"


def build_gemini_model(
    settings: Settings | None = None,
    *,
    role: ModelRole = "coding",
    model_override: str | None = None,
    retry_attempts: int = 2,
    initial_retry_delay: float = 1.0,
) -> Gemini:
    """Construct an ADK 2.0 ``Gemini`` model routed to ``settings.model_location``.

    Verified ADK 2.0 & Gemini 4 design rules:
    1. Resolve ``resolved_model = resolve_model_name(cfg, role=role, model_override=model_override)``
       and call ``validate_model_location(resolved_model, cfg.model_location)``.
    2. When ``cfg.google_genai_use_enterprise`` is True, build ``client_kwargs`` using
       ``_detect_enterprise_client_kwarg()`` (passes ``"enterprise": True`` on
       ``google-genai>=2.34.0``/3.x or ``"vertexai": True`` on older builds), plus
       ``"location": cfg.model_location`` and ``"project": cfg.google_cloud_project`` (when set).
    3. Return ``Gemini(model=resolved_model, client_kwargs=client_kwargs,
       retry_options=types.HttpRetryOptions(initial_delay=initial_retry_delay, attempts=retry_attempts))``.
       NEVER override the ``api_client`` property (preserves ADK's ``@PerLoopCachedProperty``).
    """
    _ = (settings, role, model_override, retry_attempts, initial_retry_delay)
    # TODO(lab-1): Implement build_gemini_model() following the docstring steps above
    # (compare against `solution/coding_agent/models.py`).
    raise NotImplementedError(
        "Complete TODO(lab-1) in starter/coding_agent/models.py: build_gemini_model()."
    )


def build_gemini4_generate_config(
    settings: Settings | None = None,
    *,
    thinking_level_override: str | None = None,
    include_thoughts: bool | None = None,
) -> types.GenerateContentConfig | None:
    """Build a Gemini 4 ``GenerateContentConfig`` using ``ThinkingConfig(thinking_level=...)``.

    Deliberately omits ``thinking_budget`` (returns HTTP 400 on Gemini 4) and omits
    custom ``temperature`` / ``top_p`` / ``top_k`` sampling parameters (ignored on Gemini 4).
    """
    from google.genai import types

    cfg = settings or get_settings()
    raw_level = thinking_level_override if thinking_level_override is not None else cfg.thinking_level
    normalized_level = raw_level.strip().upper()
    if normalized_level == "MINIMAL":
        raise ValueError(
            "Invalid THINKING_LEVEL='MINIMAL'. Gemini 4 rejects MINIMAL (and thinking_budget) "
            "with HTTP 400. Expected one of: HIGH, LOW, MEDIUM, XHIGH."
        )
    if normalized_level not in VALID_THINKING_LEVELS:
        valid = ", ".join(sorted(VALID_THINKING_LEVELS))
        raise ValueError(
            f"Invalid THINKING_LEVEL={raw_level!r}. Expected one of: {valid}."
        )

    thinking_kwargs: dict[str, Any] = {"thinking_level": normalized_level}
    if include_thoughts is not None:
        thinking_kwargs["include_thoughts"] = include_thoughts

    return types.GenerateContentConfig(
        thinking_config=types.ThinkingConfig(**thinking_kwargs),
    )
