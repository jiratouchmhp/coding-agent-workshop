"""Typed environment configuration for the Enterprise Coding Agent workshop.

Reads variables matching the repository-root ``.env.example`` file without
overwriting values already exported in the active shell environment.
"""

from __future__ import annotations

import functools
import os
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Literal

SandboxMode = Literal["local", "shell", "byoc", "code_execution"]
VALID_SANDBOX_MODES: frozenset[str] = frozenset({"local", "shell", "byoc", "code_execution"})

AgentArchitecture = Literal["simple", "collaborative", "graph", "dynamic"]
VALID_AGENT_ARCHITECTURES: frozenset[str] = frozenset(
    {"simple", "collaborative", "graph", "dynamic"}
)


def _parse_bool(value: str | None, default: bool = False) -> bool:
    if value is None or value.strip() == "":
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


def _parse_int(value: str | None, default: int) -> int:
    if value is None or value.strip() == "":
        return default
    try:
        return int(value.strip())
    except ValueError as exc:
        raise ValueError(f"Expected integer environment value, got {value!r}") from exc


def _load_dotenv_candidates() -> None:
    """Load ``.env`` from CWD or parent workshop root without overriding shell vars."""
    cwd = Path.cwd()
    candidates = [
        cwd / ".env",
        cwd.parent / ".env",
        Path(__file__).resolve().parents[2] / ".env",
    ]
    seen: set[Path] = set()
    for env_path in candidates:
        resolved = env_path.resolve()
        if resolved in seen or not resolved.is_file():
            continue
        seen.add(resolved)
        for raw_line in resolved.read_text(encoding="utf-8").splitlines():
            line = raw_line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            if line.startswith("export "):
                line = line[len("export ") :].strip()
            key, _, raw_val = line.partition("=")
            key = key.strip()
            if not key or key in os.environ:
                continue
            val = raw_val.strip()
            if len(val) >= 2 and val[0] == val[-1] and val[0] in {"'", '"'}:
                val = val[1:-1]
            os.environ[key] = val


@dataclass(frozen=True)
class Settings:
    """Typed runtime settings loaded from environment variables / ``.env``."""

    # Core Google Cloud project & region configuration
    google_cloud_project: str = ""
    google_cloud_project_number: str = ""
    google_cloud_location: str = "us-central1"

    # Agent Runtime & Managed Sandbox resources (populated in Lab 2 & Lab 5)
    reasoning_engine_name: str = ""
    sandbox_template_name: str = ""
    sandbox_image_uri: str = ""
    sandbox_mode: SandboxMode = "local"

    # Skill Registry (us-central1, europe-west4, or us-east5) & Agent Registry (Lab 4)
    # When AGENT_REGISTRY_LOCATION is unset, it falls back to skill_registry_location.
    skill_registry_location: str = "us-central1"
    agent_registry_location: str = ""

    # Explicit versioned Gemini model ID (avoid `gemini-flash-latest` on regional endpoints)
    model_name: str = "gemini-2.5-flash"

    # ADK 2.0 Architecture & Workflow Controls (Lab 1; default `simple` keeps Labs 2-8 unchanged)
    agent_architecture: AgentArchitecture = "simple"
    max_fix_rounds: int = 3
    enable_hitl_approval: bool = False
    managed_agent_id: str = ""

    # Additional workshop settings used progressively across Labs 1-6
    local_workspace_dir: str = "/tmp/coding_agent_workspace"
    agent_image_uri: str = ""
    sandbox_ttl: str = "3600s"
    sandbox_resource_name: str = ""
    sandbox_service_account_email: str = ""
    sandbox_runner_base_url: str = ""
    max_output_chars: int = 12_000
    enable_skill_registry: bool = False
    enable_telemetry_callbacks: bool = True
    enable_memory_bank: bool = False
    google_genai_use_enterprise: bool = True

    def __post_init__(self) -> None:
        normalized_mode = self.sandbox_mode.strip().lower()
        if normalized_mode not in VALID_SANDBOX_MODES:
            valid = ", ".join(sorted(VALID_SANDBOX_MODES))
            raise ValueError(
                f"Invalid SANDBOX_MODE={self.sandbox_mode!r}. Expected one of: {valid}."
            )
        object.__setattr__(self, "sandbox_mode", normalized_mode)
        normalized_arch = self.agent_architecture.strip().lower()
        if normalized_arch not in VALID_AGENT_ARCHITECTURES:
            valid_arch = ", ".join(sorted(VALID_AGENT_ARCHITECTURES))
            raise ValueError(
                f"Invalid AGENT_ARCHITECTURE={self.agent_architecture!r}. "
                f"Expected one of: {valid_arch}."
            )
        object.__setattr__(self, "agent_architecture", normalized_arch)
        if self.max_fix_rounds <= 0:
            raise ValueError(f"MAX_FIX_ROUNDS must be positive, got {self.max_fix_rounds}.")
        if self.max_output_chars <= 0:
            raise ValueError(f"MAX_OUTPUT_CHARS must be positive, got {self.max_output_chars}.")
        normalized_skill_loc = self.skill_registry_location.strip() or "us-central1"
        object.__setattr__(self, "skill_registry_location", normalized_skill_loc)
        normalized_agent_loc = self.agent_registry_location.strip() or normalized_skill_loc
        object.__setattr__(self, "agent_registry_location", normalized_agent_loc)

    @property
    def local_workspace_path(self) -> Path:
        """Return resolved ``pathlib.Path`` for ADK ``LocalEnvironment(working_dir=...)``."""
        return Path(self.local_workspace_dir).resolve()

    @property
    def reasoning_engine_id(self) -> str:
        """Extract trailing ReasoningEngine ID from ``REASONING_ENGINE_NAME`` or env fallbacks."""
        if self.reasoning_engine_name:
            return self.reasoning_engine_name.rstrip("/").split("/")[-1]
        return (
            os.environ.get("REASONING_ENGINE_ID", "").strip()
            or os.environ.get("GOOGLE_CLOUD_AGENT_ENGINE_ID", "").strip()
        )

    @property
    def sandbox_service_agent_email(self) -> str:
        """Agent Sandbox service agent email used for BYOC Artifact Registry pulls."""
        if not self.google_cloud_project_number:
            return ""
        return f"service-{self.google_cloud_project_number}@gcp-sa-vertex-sandbox.iam.gserviceaccount.com"

    @property
    def runtime_service_agent_email(self) -> str:
        """Agent Runtime service agent email used for Runtime pulls & CMEK."""
        if not self.google_cloud_project_number:
            return ""
        return f"service-{self.google_cloud_project_number}@gcp-sa-aiplatform-re.iam.gserviceaccount.com"

    def require_gcp_project(self) -> str:
        """Return ``GOOGLE_CLOUD_PROJECT`` or raise an actionable ``ValueError``."""
        if not self.google_cloud_project:
            raise ValueError(
                "GOOGLE_CLOUD_PROJECT is not set. Copy `.env.example` to `.env` "
                "and populate your GCP project ID before running cloud operations."
            )
        return self.google_cloud_project

    def to_dict(self) -> dict[str, Any]:
        """Serialize settings into a plain dictionary."""
        return asdict(self)


def load_settings() -> Settings:
    """Load fresh ``Settings`` from ``.env`` files and environment variables."""
    _load_dotenv_candidates()
    raw_mode = os.environ.get("SANDBOX_MODE", "local").strip().lower() or "local"
    raw_arch = os.environ.get("AGENT_ARCHITECTURE", "simple").strip().lower() or "simple"
    project = os.environ.get("GOOGLE_CLOUD_PROJECT", "").strip()
    location = os.environ.get("GOOGLE_CLOUD_LOCATION", "us-central1").strip()
    reasoning_engine_name = os.environ.get("REASONING_ENGINE_NAME", "").strip()
    if not reasoning_engine_name:
        engine_id = (
            os.environ.get("REASONING_ENGINE_ID", "").strip()
            or os.environ.get("GOOGLE_CLOUD_AGENT_ENGINE_ID", "").strip()
        )
        if project and location and engine_id:
            reasoning_engine_name = (
                engine_id
                if engine_id.startswith("projects/")
                else f"projects/{project}/locations/{location}/reasoningEngines/{engine_id}"
            )
    return Settings(
        google_cloud_project=project,
        google_cloud_project_number=os.environ.get("GOOGLE_CLOUD_PROJECT_NUMBER", "").strip(),
        google_cloud_location=location,
        reasoning_engine_name=reasoning_engine_name,
        sandbox_template_name=os.environ.get("SANDBOX_TEMPLATE_NAME", "").strip(),
        sandbox_image_uri=os.environ.get("SANDBOX_IMAGE_URI", "").strip(),
        sandbox_mode=raw_mode,  # type: ignore[arg-type]
        skill_registry_location=(
            os.environ.get("SKILL_REGISTRY_LOCATION", "").strip() or "us-central1"
        ),
        agent_registry_location=os.environ.get("AGENT_REGISTRY_LOCATION", "").strip(),
        model_name=os.environ.get("MODEL_NAME", "gemini-2.5-flash").strip(),
        agent_architecture=raw_arch,  # type: ignore[arg-type]
        max_fix_rounds=_parse_int(os.environ.get("MAX_FIX_ROUNDS"), 3),
        enable_hitl_approval=_parse_bool(os.environ.get("ENABLE_HITL_APPROVAL"), False),
        managed_agent_id=os.environ.get("MANAGED_AGENT_ID", "").strip(),
        local_workspace_dir=os.environ.get(
            "LOCAL_WORKSPACE_DIR", "/tmp/coding_agent_workspace"
        ).strip(),
        agent_image_uri=os.environ.get("AGENT_IMAGE_URI", "").strip(),
        sandbox_ttl=os.environ.get("SANDBOX_TTL", "3600s").strip(),
        sandbox_resource_name=os.environ.get("SANDBOX_RESOURCE_NAME", "").strip(),
        sandbox_service_account_email=os.environ.get(
            "SANDBOX_SERVICE_ACCOUNT_EMAIL", ""
        ).strip(),
        sandbox_runner_base_url=os.environ.get("SANDBOX_RUNNER_BASE_URL", "").strip(),
        max_output_chars=_parse_int(os.environ.get("MAX_OUTPUT_CHARS"), 12_000),
        enable_skill_registry=_parse_bool(os.environ.get("ENABLE_SKILL_REGISTRY"), False),
        enable_telemetry_callbacks=_parse_bool(
            os.environ.get("ENABLE_TELEMETRY_CALLBACKS"), True
        ),
        enable_memory_bank=_parse_bool(os.environ.get("ENABLE_MEMORY_BANK"), False),
        google_genai_use_enterprise=_parse_bool(
            os.environ.get("GOOGLE_GENAI_USE_ENTERPRISE"), True
        ),
    )


@functools.lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Return process-cached ``Settings`` (call ``get_settings.cache_clear()`` to reload)."""
    return load_settings()
