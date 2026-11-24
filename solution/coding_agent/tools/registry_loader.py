"""Skill Registry & Agent Registry ADK integration and publisher (solution — Lab 4).

Covers all three Lab 4 registry workflows:
1. **Dynamic ADK Skill Consumption (`build_skill_registry_toolset`):**
   Wires ``GCPSkillRegistry`` + ``SkillToolset`` with 3-level progressive disclosure
   and automatic fallback to locally bundled skills when executing in an air-gapped
   sandbox without outbound Vertex AI / Agent Registry network egress.
2. **ADK Agent Registry Integrations (`build_agent_registry_integrations`):**
   Configures ``AgentRegistry`` (``list_agents``, ``list_mcp_servers``,
   ``get_remote_a2a_agent`` with ``GoogleApiAuth`` / ``GoogleAuth``, and
   ``get_mcp_toolset`` with ``header_provider`` and Auth Manager ``GcpAuthProvider``).
3. **Skill Registry Publishing (`SkillRegistryPublisher`):**
   Wraps ``agentplatform.Client.skills.{create, update, list, get, retrieve, delete}``
   and ``revisions.{list, get}``, validating Skill Registry regions/IDs and handling
   the built-in ``gcp-skill-registry`` first-call async ingestion quirk.

Verified Architecture & SDK Rules:
- **Two Distinct Skill Registries:**
  - Vertex AI / Agent Platform Skill Registry (``aiplatform.googleapis.com/v1beta1``):
    regions ``us-central1``, ``europe-west4``, ``us-east5``; max **10 MB** ZIP / **500 MB**
    unzipped; Python ``agentplatform.Client.skills.*``; built-in ``gcp-skill-registry``
    ingested asynchronously on first API call (appears on call #2+).
  - Agent Registry Standalone Skills (``agentregistry.googleapis.com/v1``):
    ``global``, multi-region, or regional; max **1 MB** ZIP / **10 MB** scanned;
    auto-prepends ``private-``; automated LLM security scanning (``ENABLED_BLOCKING``).
  - Latest ``google/adk-python`` ``main`` ``GCPSkillRegistry`` targets
    ``https://agentregistry.googleapis.com/v1alpha`` (overridable via
    ``AGENT_REGISTRY_ENDPOINT``) and strips ``x-goog-*`` headers on 302 GCS redirects.
- **ImportError Trap:** ``google.adk.integrations.agent_registry`` imports ``a2a-sdk``
  and the Agent Identity provider at module scope — requires
  ``pip install --upgrade "google-adk[a2a,agent-identity,mcp]>=2.0.0"``.
- **Mutual Exclusivity:** ``SkillToolset`` accepts ``environment=`` OR ``code_executor=``,
  never both (passing both raises ``ValueError``).
- **Single-Parent Reuse:** Fetch ``RemoteA2aAgent`` once and call ``.clone()`` when
  attaching to multiple orchestrators.
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import re
import sys
import time
from collections.abc import Callable, Generator
from pathlib import Path
from typing import Any

import httpx

from coding_agent.config import Settings, get_settings

logger = logging.getLogger(__name__)

SKILL_REGISTRY_SUPPORTED_LOCATIONS: frozenset[str] = frozenset(
    {"us-central1", "europe-west4", "us-east5"}
)
_SKILL_ID_RE = re.compile(r"^[a-z](?:[a-z0-9-]{0,61}[a-z0-9])?$")
BUILTIN_SKILL_PREFIX = "gcp-"
BUILTIN_SKILL_ID = "gcp-skill-registry"


# ---------------------------------------------------------------------------
# Validation Helpers
# ---------------------------------------------------------------------------


def validate_skill_registry_location(location: str) -> None:
    """Validate that ``location`` is a supported Vertex AI Skill Registry region."""
    if location not in SKILL_REGISTRY_SUPPORTED_LOCATIONS:
        supported = ", ".join(sorted(SKILL_REGISTRY_SUPPORTED_LOCATIONS))
        raise ValueError(
            f"Unsupported Vertex AI Skill Registry location={location!r}. "
            f"Supported regions: {supported}."
        )


def validate_skill_id(skill_id: str, *, allow_builtin_prefix: bool = False) -> None:
    """Validate a Vertex AI Skill Registry ``SKILL_ID`` (1–63 chars, not ``gcp-*``)."""
    if not skill_id or not _SKILL_ID_RE.match(skill_id):
        raise ValueError(
            f"Invalid skill_id={skill_id!r}. Must be 1–63 chars [a-z0-9-], start with a "
            "lowercase letter, and end with a lowercase letter or digit."
        )
    if not allow_builtin_prefix and skill_id.startswith(BUILTIN_SKILL_PREFIX):
        raise ValueError(
            f"skill_id={skill_id!r} cannot start with reserved prefix {BUILTIN_SKILL_PREFIX!r}."
        )


# ---------------------------------------------------------------------------
# Part 1: ADK SkillToolset + GCPSkillRegistry (with Air-Gapped Fallback)
# ---------------------------------------------------------------------------


def build_skill_registry_toolset(
    project_id: str | None = None,
    location: str | None = None,
    local_skill_dirs: list[Path] | None = None,
    environment: Any | None = None,
    code_executor: Any | None = None,
    enable_remote_registry: bool = True,
    discovery_mode: Any | None = None,
    max_active_skills: int = 5,
) -> Any:
    """Build ADK ``SkillToolset`` backed by ``GCPSkillRegistry`` with offline fallback.

    - Local skills from ``local_skill_dirs`` are loaded via ``load_skill_from_dir()``
      and automatically shadow remote registry skills with identical names.
    - Always passes ``location=`` explicitly (e.g., ``AGENT_REGISTRY_SKILLS_LOCATION="global"``)
      because omitting ``location`` falls back to regional ``GOOGLE_CLOUD_LOCATION``.
      Note that ADK 2.15+ ``GCPSkillRegistry.__init__`` is lazy (no network/ADC call at init;
      air-gapped runtime failures surface inside ``SearchSkillsTool`` as ``REGISTRY_ERROR``
      while local skills remain usable), and standalone Agent Registry skills must be in
      ``ACTIVE`` state (``--target-state=active``) for ``get_skill()`` downloads to succeed.
    - Enforces ADK's mutual-exclusivity rule between ``environment`` and ``code_executor``.
    """
    if environment is not None and code_executor is not None:
        raise ValueError(
            "SkillToolset accepts either environment= or code_executor=, never both."
        )

    from google.adk.skills import load_skill_from_dir
    from google.adk.tools.skill_toolset import (
        SkillDiscoveryMode,
        SkillLifecycleConfig,
        SkillLifecycleMode,
        SkillToolset,
    )

    local_skills = [
        load_skill_from_dir(Path(skill_dir))
        for skill_dir in (local_skill_dirs or [])
        if Path(skill_dir).exists()
    ]

    registry: Any | None = None
    if enable_remote_registry and project_id and location:
        try:
            from google.adk.integrations.skill_registry import GCPSkillRegistry

            # Keyword-only constructor in ADK Python 2.0+
            registry = GCPSkillRegistry(project_id=project_id, location=location)
        except Exception as exc:
            # Isolated sandboxes without outbound Google API egress fall back to local skills
            logger.warning(
                "GCPSkillRegistry unavailable (%s); falling back to %d local skill(s).",
                exc,
                len(local_skills),
            )

    resolved_discovery = (
        discovery_mode if discovery_mode is not None else SkillDiscoveryMode.LAZY
    )
    toolset_kwargs: dict[str, Any] = {
        "skills": local_skills,
        "registry": registry,
        "discovery_mode": resolved_discovery,
        "lifecycle_config": SkillLifecycleConfig(
            default_mode=SkillLifecycleMode.BOUNDED,
            max_active_skills=max_active_skills,
        ),
    }
    if environment is not None:
        toolset_kwargs["environment"] = environment
    elif code_executor is not None:
        toolset_kwargs["code_executor"] = code_executor

    return SkillToolset(**toolset_kwargs)


# ---------------------------------------------------------------------------
# Part 2: ADK AgentRegistry Authentication & Integrations
# ---------------------------------------------------------------------------


class GoogleApiAuth(httpx.Auth):
    """OAuth 2.0 Bearer + optional ``X-Goog-User-Project`` auth for ``*.googleapis.com`` A2A.

    Aliased as ``GoogleAuth`` to match both ``adk.dev/integrations/agent-registry``
    (``GoogleAuth()``) and Cloud Docs ``resolve-endpoints-and-build-orchestrators``
    (``GoogleApiAuth(project_id)``).

    NOTE: For Cloud Run (``https://*.run.app``) or IAP-protected HTTPS A2A endpoints,
    use ``OidcIdTokenAuth`` (OIDC ID token) instead of an OAuth access token.
    """

    def __init__(
        self,
        quota_project_id: str | None = None,
        *,
        scopes: list[str] | None = None,
        credentials: Any | None = None,
    ) -> None:
        self._quota_project_id = quota_project_id
        if credentials is not None:
            self._creds = credentials
        else:
            import google.auth

            effective_scopes = scopes or ["https://www.googleapis.com/auth/cloud-platform"]
            self._creds, _ = google.auth.default(scopes=effective_scopes)

    def auth_flow(self, request: httpx.Request) -> Generator[httpx.Request, httpx.Response, None]:
        from google.auth.transport.requests import Request

        if not self._creds.valid:
            self._creds.refresh(Request())
        request.headers["Authorization"] = f"Bearer {self._creds.token}"
        if self._quota_project_id:
            request.headers["X-Goog-User-Project"] = self._quota_project_id
        yield request


# Alias matching `adk.dev/integrations/agent-registry` examples
GoogleAuth = GoogleApiAuth


class OidcIdTokenAuth(httpx.Auth):
    """OIDC ID token auth for Cloud Run (``*.run.app``) or IAP-protected A2A endpoints."""

    def __init__(self, audience: str) -> None:
        if not audience:
            raise ValueError("audience (e.g. 'https://service.run.app' or IAP client ID) is required.")
        self._audience = audience

    def auth_flow(self, request: httpx.Request) -> Generator[httpx.Request, httpx.Response, None]:
        from google.auth.transport.requests import Request
        from google.oauth2 import id_token

        token = id_token.fetch_id_token(Request(), self._audience)
        request.headers["Authorization"] = f"Bearer {token}"
        yield request


def make_google_auth_header_provider(
    *,
    quota_project_id: str | None = None,
    extra_headers: dict[str, str] | None = None,
    scopes: list[str] | None = None,
) -> Callable[[Any], dict[str, str]]:
    """Build a ``header_provider(context: ReadonlyContext) -> dict[str, str]`` for ``AgentRegistry``.

    IMPORTANT: ``header_provider`` applies ONLY to requests sent by ``McpToolset``
    returned from ``get_mcp_toolset()``. It does NOT apply to Agent Registry API calls
    or ``RemoteA2aAgent`` requests (which require ``httpx.AsyncClient(auth=...)``).
    """

    def _header_provider(context: Any) -> dict[str, str]:
        del context
        import google.auth
        from google.auth.transport.requests import Request

        creds, _ = google.auth.default(
            scopes=scopes or ["https://www.googleapis.com/auth/cloud-platform"]
        )
        if not creds.valid:
            creds.refresh(Request())
        headers: dict[str, str] = {"Authorization": f"Bearer {creds.token}"}
        if quota_project_id:
            headers["X-Goog-User-Project"] = quota_project_id
        if extra_headers:
            headers.update(extra_headers)
        return headers

    return _header_provider


def discover_agent_registry_catalog(
    registry: Any,
    *,
    agent_filter: str | None = None,
    mcp_filter: str | None = None,
    page_size: int | None = None,
) -> dict[str, list[dict[str, Any]]]:
    """List registered A2A agents and MCP servers from an ADK ``AgentRegistry`` client."""
    agent_kwargs: dict[str, Any] = {}
    if agent_filter:
        agent_kwargs["filter_str"] = agent_filter
    if page_size is not None:
        agent_kwargs["page_size"] = page_size

    mcp_kwargs: dict[str, Any] = {}
    if mcp_filter:
        mcp_kwargs["filter_str"] = mcp_filter
    if page_size is not None:
        mcp_kwargs["page_size"] = page_size

    agents_resp = registry.list_agents(**agent_kwargs)
    mcp_resp = registry.list_mcp_servers(**mcp_kwargs)
    return {
        "agents": list(agents_resp.get("agents", []) if isinstance(agents_resp, dict) else agents_resp),
        "mcp_servers": list(
            mcp_resp.get("mcpServers", []) if isinstance(mcp_resp, dict) else mcp_resp
        ),
    }


def build_agent_registry_integrations(
    project_id: str,
    location: str = "asia-southeast3",
    mcp_server_name: str | None = None,
    remote_a2a_agent_name: str | None = None,
    continue_uri: str | None = None,
    header_provider: Callable[[Any], dict[str, str]] | None = None,
    *,
    discover_catalog: bool = False,
    register_auth_provider: bool = True,
    httpx_timeout_seconds: float = 60.0,
    a2a_audience: str | None = None,
) -> dict[str, Any]:
    """Configure ADK ``AgentRegistry`` with Auth Manager, MCP toolsets & Remote A2A agents.

    Supports all three verified ADK authentication patterns:
    1. **Auth Manager bindings (2LO, API Key, 3LO):** registers ``GcpAuthProvider`` on
       ``CredentialManager``; Agent Runtime automatically re-resolves bindings via
       ``bindings:fetchAvailable`` and strips deployer credentials on pickle.
    2. **Custom MCP headers:** passes ``header_provider`` to ``AgentRegistry(...)``
       (applies to ``McpToolset`` only).
    3. **Authenticated Remote A2A HTTP client:** passes ``httpx.AsyncClient(auth=...)``
       using ``GoogleApiAuth(project_id)`` (or ``OidcIdTokenAuth(a2a_audience)`` for
       Cloud Run / IAP endpoints).

    Reminder: A ``RemoteA2aAgent`` can have only ONE parent orchestrator at a time —
    call ``result["remote_agent"].clone()`` when reusing it across multiple agents.
    """
    try:
        from google.adk.integrations.agent_registry import AgentRegistry
    except ImportError as exc:
        raise ImportError(
            "Importing google.adk.integrations.agent_registry requires the `a2a` and "
            "`agent-identity` extras (they are imported at module scope). Install with: "
            '`pip install --upgrade "google-adk[a2a,agent-identity,mcp]>=2.0.0"`.'
        ) from exc

    if register_auth_provider:
        from google.adk.auth.credential_manager import CredentialManager
        from google.adk.integrations.agent_identity import GcpAuthProvider

        CredentialManager.register_auth_provider(GcpAuthProvider())

    registry = AgentRegistry(
        project_id=project_id,
        location=location,
        header_provider=header_provider,
    )

    result: dict[str, Any] = {
        "registry": registry,
        "mcp_toolset": None,
        "remote_agent": None,
        "agents": [],
        "mcp_servers": [],
    }

    if discover_catalog:
        catalog = discover_agent_registry_catalog(registry)
        result["agents"] = catalog["agents"]
        result["mcp_servers"] = catalog["mcp_servers"]

    if mcp_server_name:
        mcp_kwargs: dict[str, Any] = {}
        if continue_uri is not None:
            mcp_kwargs["continue_uri"] = continue_uri
        result["mcp_toolset"] = registry.get_mcp_toolset(mcp_server_name, **mcp_kwargs)

    if remote_a2a_agent_name:
        auth_handler: httpx.Auth = (
            OidcIdTokenAuth(a2a_audience) if a2a_audience else GoogleApiAuth(project_id)
        )
        httpx_client = httpx.AsyncClient(
            auth=auth_handler,
            timeout=httpx.Timeout(httpx_timeout_seconds),
        )
        a2a_kwargs: dict[str, Any] = {"httpx_client": httpx_client}
        if continue_uri is not None:
            a2a_kwargs["continue_uri"] = continue_uri
        result["remote_agent"] = registry.get_remote_a2a_agent(
            remote_a2a_agent_name,
            **a2a_kwargs,
        )

    return result


# ---------------------------------------------------------------------------
# Part 3: Vertex AI / Agent Platform Skill Registry Publisher
# ---------------------------------------------------------------------------


class SkillRegistryPublisher:
    """Publish, update, search, and list skills in Vertex AI Skill Registry.

    Uses ``agentplatform.Client.skills.*`` (provided by ``google-cloud-aiplatform>=1.154.0``
    or ``google-cloud-agentplatform>=2.0.1``) targeting
    ``https://LOCATION-aiplatform.googleapis.com/v1beta1/projects/PROJECT/locations/LOCATION/skills``.

    Verified Operational Quirks:
    1. **First-Call ``gcp-skill-registry`` Ingestion Quirk:** The Skill Registry begins
       ingesting the built-in ``gcp-skill-registry`` skill asynchronously on the project's
       very first API call. Call #1 does NOT return ``gcp-skill-registry``; issue a second
       ``list_skills()`` call (or pass ``trigger_builtin_warmup=True``) to observe it.
    2. **``SKILL_ID`` Deletion Lockout:** Official Create docs state ``SKILL_ID`` remains
       permanently reserved, while Delete docs state a 24-hour reservation lockout — never
       delete and immediately recreate with the same ``SKILL_ID`` during a workshop!
    3. **Supported Regions:** ``us-central1``, ``europe-west4``, ``us-east5``.
    """

    def __init__(
        self,
        project_id: str,
        location: str = "us-central1",
        *,
        client: Any | None = None,
    ) -> None:
        validate_skill_registry_location(location)
        self.project_id = project_id
        self.location = location
        self._client = client

    @classmethod
    def from_settings(cls, settings: Settings | None = None) -> SkillRegistryPublisher:
        """Create a ``SkillRegistryPublisher`` initialized from environment ``Settings``."""
        cfg = settings or get_settings()
        return cls(
            project_id=cfg.require_gcp_project(),
            location=cfg.skill_registry_location,
        )

    @property
    def client(self) -> Any:
        if self._client is None:
            os.environ.setdefault("GOOGLE_GENAI_USE_ENTERPRISE", "TRUE")
            import agentplatform

            self._client = agentplatform.Client(project=self.project_id, location=self.location)
        return self._client

    def skill_resource_name(self, skill_id: str) -> str:
        """Return canonical Skill Registry resource name."""
        return f"projects/{self.project_id}/locations/{self.location}/skills/{skill_id}"

    def list_skills(
        self,
        *,
        trigger_builtin_warmup: bool = False,
        warmup_delay_seconds: float = 2.0,
    ) -> list[Any]:
        """List skills in Vertex AI Skill Registry.

        When ``trigger_builtin_warmup=True``, performs an initial list call to kick off
        async ingestion of the built-in ``gcp-skill-registry`` skill, waits briefly, and
        returns the second call's results.
        """
        first_result = list(self.client.skills.list())
        if not trigger_builtin_warmup:
            return first_result

        has_builtin = any(
            str(getattr(item, "name", "")).endswith(f"/{BUILTIN_SKILL_ID}")
            for item in first_result
        )
        if has_builtin:
            return first_result

        logger.info(
            "Built-in %s not present on first API call (expected async ingestion quirk); "
            "re-listing after %.1fs...",
            BUILTIN_SKILL_ID,
            warmup_delay_seconds,
        )
        if warmup_delay_seconds > 0:
            time.sleep(warmup_delay_seconds)
        return list(self.client.skills.list())

    def create_skill(
        self,
        skill_id: str,
        display_name: str,
        description: str,
        local_path: str | Path,
    ) -> Any:
        """Create a skill from a validated local skill directory (``SKILL.md`` at root).

        Vertex AI Skill Registry (``agentplatform.Client.skills.create``) zips the
        validated skill directory directly and rejects ``.zip`` file paths.
        Handles both ``google-cloud-aiplatform >= 1.154.0`` (top-level ``skill_id=`` arg)
        and ``< 1.154.0`` (``skill_id`` nested inside ``config={}``).
        """
        validate_skill_id(skill_id)
        resolved = Path(local_path).resolve()
        if not resolved.exists():
            raise FileNotFoundError(f"Skill path does not exist: {resolved}")
        if not resolved.is_dir():
            raise ValueError(
                "Vertex AI Skill Registry `local_path` must be a skill directory containing "
                f"`SKILL.md` at the directory root (not a `.zip` archive or file): {resolved}. "
                "The `agentplatform` SDK zips the validated skill directory directly."
            )

        try:
            return self.client.skills.create(
                skill_id=skill_id,
                display_name=display_name,
                description=description,
                config={"local_path": str(resolved)},
            )
        except TypeError:
            # Backward-compatible fallback for google-cloud-aiplatform < 1.154.0
            return self.client.skills.create(
                display_name=display_name,
                description=description,
                config={"skill_id": skill_id, "local_path": str(resolved)},
            )

    def update_skill(
        self,
        skill_id: str,
        *,
        display_name: str | None = None,
        description: str | None = None,
        local_path: str | Path | None = None,
    ) -> Any:
        """Update an existing skill's metadata and/or upload a new skill directory revision.

        When ``local_path`` is supplied, it must be a validated skill directory
        (``SKILL.md`` at directory root); ``agentplatform`` zips the directory directly
        and rejects ``.zip`` archives.
        """
        validate_skill_id(skill_id)
        config: dict[str, Any] = {}
        if display_name is not None:
            config["display_name"] = display_name
        if description is not None:
            config["description"] = description
        if local_path is not None:
            resolved = Path(local_path).resolve()
            if not resolved.exists():
                raise FileNotFoundError(f"Skill path does not exist: {resolved}")
            if not resolved.is_dir():
                raise ValueError(
                    "Vertex AI Skill Registry `local_path` must be a skill directory containing "
                    f"`SKILL.md` at the directory root (not a `.zip` archive or file): {resolved}. "
                    "The `agentplatform` SDK zips the validated skill directory directly."
                )
            config["local_path"] = str(resolved)
        if not config:
            raise ValueError("Specify at least one of display_name, description, or local_path.")

        return self.client.skills.update(
            name=self.skill_resource_name(skill_id),
            config=config,
        )

    def get_skill(self, skill_id: str) -> Any:
        """Fetch metadata for a single skill (including built-in ``gcp-skill-registry``)."""
        validate_skill_id(skill_id, allow_builtin_prefix=True)
        return self.client.skills.get(name=self.skill_resource_name(skill_id))

    def list_revisions(self, skill_id: str) -> list[Any]:
        """List immutable revisions for a skill."""
        validate_skill_id(skill_id, allow_builtin_prefix=True)
        resp = self.client.skills.revisions.list(name=self.skill_resource_name(skill_id))
        return list(getattr(resp, "skill_revisions", resp) or [])

    def get_revision(self, skill_id: str, revision_id: str) -> Any:
        """Fetch a single immutable skill revision."""
        validate_skill_id(skill_id, allow_builtin_prefix=True)
        rev_name = f"{self.skill_resource_name(skill_id)}/revisions/{revision_id}"
        return self.client.skills.revisions.get(name=rev_name)

    def search_skills(self, query: str, top_k: int = 5) -> list[Any]:
        """Run semantic skill retrieval via ``client.skills.retrieve(...)``."""
        if not query or not query.strip():
            raise ValueError("Search query must be non-empty.")
        response = self.client.skills.retrieve(query=query, config={"top_k": top_k})
        return list(getattr(response, "retrieved_skills", []) or [])

    def delete_skill(self, skill_id: str) -> None:
        """Delete a user-created skill.

        Refuses to delete built-in ``gcp-*`` skills and logs a reminder about the
        24h / permanent ``SKILL_ID`` reuse lockout.
        """
        validate_skill_id(skill_id, allow_builtin_prefix=False)
        logger.warning(
            "Deleting skill_id=%r: deleted SKILL_IDs are reserved (24h / permanently) "
            "and cannot be immediately reused.",
            skill_id,
        )
        self.client.skills.delete(name=self.skill_resource_name(skill_id))


# ---------------------------------------------------------------------------
# Runnable CLI (`python -m coding_agent.tools.registry_loader ...`)
# ---------------------------------------------------------------------------


def _default_local_skill_dir() -> Path:
    return Path(__file__).resolve().parents[2] / "skills_to_register" / "secure-code-review"


def _run_offline_check(local_skill_dir: Path) -> dict[str, Any]:
    """Verify local-only SkillToolset fallback and validator rules offline."""
    toolset = build_skill_registry_toolset(
        project_id=None,
        location=None,
        local_skill_dirs=[local_skill_dir],
        enable_remote_registry=False,
    )
    validate_skill_registry_location("us-central1")
    validate_skill_id("secure-code-review")
    return {
        "mode": "offline-check",
        "local_skill_dir": str(local_skill_dir),
        "local_skill_exists": local_skill_dir.exists(),
        "toolset_class": type(toolset).__name__,
        "supported_skill_registry_locations": sorted(SKILL_REGISTRY_SUPPORTED_LOCATIONS),
    }


def _build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m coding_agent.tools.registry_loader",
        description="Skill Registry publisher and Agent Registry ADK discovery CLI.",
    )
    parser.add_argument("--project", help="GCP project ID (defaults to GOOGLE_CLOUD_PROJECT).")
    parser.add_argument("--location", help="Registry region (defaults to SKILL/AGENT_REGISTRY_LOCATION).")
    sub = parser.add_subparsers(dest="command", required=True)

    p_off = sub.add_parser("offline-check", help="Verify offline SkillToolset fallback & validators.")
    p_off.add_argument("--skill-dir", default=str(_default_local_skill_dir()))

    p_list = sub.add_parser("list-skills", help="List skills in Vertex AI Skill Registry.")
    p_list.add_argument(
        "--warmup",
        action="store_true",
        help="Trigger second list call if built-in gcp-skill-registry is still ingesting.",
    )

    p_pub = sub.add_parser("publish-skill", help="Create a skill in Vertex AI Skill Registry.")
    p_pub.add_argument("--skill-id", default="secure-code-review")
    p_pub.add_argument("--display-name", default="Secure Code Review")
    p_pub.add_argument(
        "--description",
        default="Enterprise OWASP static security audit checklist for Python and TypeScript PRs.",
    )
    p_pub.add_argument("--path", default=str(_default_local_skill_dir()))

    p_upd = sub.add_parser("update-skill", help="Update an existing skill in Vertex AI Skill Registry.")
    p_upd.add_argument("--skill-id", default="secure-code-review")
    p_upd.add_argument("--display-name", default=None)
    p_upd.add_argument("--description", default=None)
    p_upd.add_argument("--path", default=None)

    p_search = sub.add_parser("search-skills", help="Semantic search in Vertex AI Skill Registry.")
    p_search.add_argument("--query", required=True)
    p_search.add_argument("--top-k", type=int, default=5)

    p_disc = sub.add_parser(
        "discover-agent-registry",
        help="List registered A2A agents and MCP servers via ADK AgentRegistry.",
    )
    p_disc.add_argument("--mcp-server", default=None)
    p_disc.add_argument("--remote-agent", default=None)
    return parser


def main(argv: list[str] | None = None) -> int:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    args = _build_arg_parser().parse_args(argv)

    if args.command == "offline-check":
        print(json.dumps(_run_offline_check(Path(args.skill_dir)), indent=2))
        return 0

    settings = get_settings()
    project_id = args.project or settings.require_gcp_project()

    output: Any
    if args.command == "discover-agent-registry":
        location = args.location or settings.agent_registry_location
        bundle = build_agent_registry_integrations(
            project_id=project_id,
            location=location,
            mcp_server_name=args.mcp_server,
            remote_a2a_agent_name=args.remote_agent,
            discover_catalog=True,
        )
        output = {
            "project_id": project_id,
            "location": location,
            "agents": bundle["agents"],
            "mcp_servers": bundle["mcp_servers"],
            "mcp_toolset_loaded": bundle["mcp_toolset"] is not None,
            "remote_agent_loaded": bundle["remote_agent"] is not None,
        }
    else:
        location = args.location or settings.skill_registry_location
        publisher = SkillRegistryPublisher(project_id=project_id, location=location)
        if args.command == "list-skills":
            skills = publisher.list_skills(trigger_builtin_warmup=args.warmup)
            output = [
                {"name": getattr(s, "name", str(s)), "display_name": getattr(s, "display_name", "")}
                for s in skills
            ]
        elif args.command == "publish-skill":
            skill = publisher.create_skill(
                skill_id=args.skill_id,
                display_name=args.display_name,
                description=args.description,
                local_path=args.path,
            )
            output = {"created_skill": getattr(skill, "name", str(skill))}
        elif args.command == "update-skill":
            skill = publisher.update_skill(
                skill_id=args.skill_id,
                display_name=args.display_name,
                description=args.description,
                local_path=args.path,
            )
            output = {"updated_skill": getattr(skill, "name", str(skill))}
        elif args.command == "search-skills":
            hits = publisher.search_skills(query=args.query, top_k=args.top_k)
            output = [
                {
                    "skill_name": getattr(h, "skill_name", str(h)),
                    "description": getattr(h, "description", ""),
                }
                for h in hits
            ]
        else:
            raise ValueError(f"Unknown command: {args.command}")

    print(json.dumps(output, indent=2, default=str))
    return 0


if __name__ == "__main__":
    sys.exit(main())
