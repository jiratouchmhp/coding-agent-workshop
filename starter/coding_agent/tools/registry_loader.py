"""Skill Registry & Agent Registry ADK integration and publisher (starter — Lab 5).

Complete the ``# TODO(lab-5)`` sections below to wire:
1. ``build_skill_registry_toolset()``: ``GCPSkillRegistry`` + ``SkillToolset`` with
   graceful fallback to locally bundled skills when running inside an air-gapped
   sandbox without outbound Vertex AI / Agent Registry egress.
2. ``GoogleApiAuth`` (aliased as ``GoogleAuth``) + ``build_agent_registry_integrations()``:
   ``AgentRegistry`` discovery (``list_agents``, ``list_mcp_servers``),
   ``get_remote_a2a_agent`` with ``httpx.AsyncClient(auth=GoogleApiAuth(...))``,
   and ``get_mcp_toolset`` with ``GcpAuthProvider`` / ``header_provider``.
3. ``SkillRegistryPublisher``: create, update, search (``retrieve``), and list skills
   in Vertex AI Skill Registry, accounting for the built-in ``gcp-skill-registry``
   first-call async ingestion quirk.

Verified Gotchas:
- ``google.adk.integrations.agent_registry`` imports ``a2a-sdk`` and Agent Identity at
  module scope — requires ``pip install --upgrade "google-adk[a2a,agent-identity,mcp]>=2.0.0"``.
- ``SkillToolset`` accepts ``environment=`` OR ``code_executor=``, NEVER both.
- ``header_provider`` applies ONLY to ``McpToolset``, never to ``RemoteA2aAgent``.
- Built-in ``gcp-skill-registry`` begins async ingestion on the project's FIRST Skill
  Registry API call and appears starting on the SECOND call.
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
# Validation Helpers (ready to use)
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
    """Build ADK ``SkillToolset`` backed by ``GCPSkillRegistry`` with offline fallback."""
    if environment is not None and code_executor is not None:
        raise ValueError(
            "SkillToolset accepts either environment= or code_executor=, never both."
        )

    # TODO(lab-5):
    # 1. Load existing directories in ``local_skill_dirs`` with ``load_skill_from_dir(Path(d))``.
    # 2. If ``enable_remote_registry and project_id and location``, try instantiating
    #    ``GCPSkillRegistry(project_id=project_id, location=location)`` from
    #    ``google.adk.integrations.skill_registry`` (keyword-only args!). Catch ``Exception``
    #    and log a warning so air-gapped sandboxes without egress fall back to local skills.
    # 3. Return ``SkillToolset(skills=local_skills, registry=registry, environment=environment,
    #    discovery_mode=SkillDiscoveryMode.LAZY, lifecycle_config=SkillLifecycleConfig(
    #    default_mode=SkillLifecycleMode.BOUNDED, max_active_skills=max_active_skills))``
    #    (passing ``code_executor`` instead of ``environment`` when ``code_executor`` is set).
    _ = (
        project_id,
        location,
        local_skill_dirs,
        environment,
        code_executor,
        enable_remote_registry,
        discovery_mode,
        max_active_skills,
    )
    raise NotImplementedError("Complete TODO(lab-5): build_skill_registry_toolset()")


# ---------------------------------------------------------------------------
# Part 2: ADK AgentRegistry Authentication & Integrations
# ---------------------------------------------------------------------------


class GoogleApiAuth(httpx.Auth):
    """OAuth 2.0 Bearer + optional ``X-Goog-User-Project`` auth for ``*.googleapis.com`` A2A."""

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
        # TODO(lab-5): Refresh ``self._creds`` with ``google.auth.transport.requests.Request()``
        # when ``not self._creds.valid``, set ``Authorization: Bearer {token}`` and
        # (when ``self._quota_project_id`` is set) ``X-Goog-User-Project``, then ``yield request``.
        _ = request
        raise NotImplementedError("Complete TODO(lab-5): GoogleApiAuth.auth_flow()")
        yield request  # pragma: no cover


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
    """Build a ``header_provider(context: ReadonlyContext) -> dict[str, str]`` for ``AgentRegistry``."""

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
    location: str = "us-central1",
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
    """Configure ADK ``AgentRegistry`` with Auth Manager, MCP toolsets & Remote A2A agents."""
    # TODO(lab-5):
    # 1. Import ``AgentRegistry`` from ``google.adk.integrations.agent_registry`` (catching
    #    ``ImportError`` with an install hint for ``google-adk[a2a,agent-identity,mcp]>=2.0.0``).
    # 2. When ``register_auth_provider`` is True, call
    #    ``CredentialManager.register_auth_provider(GcpAuthProvider())``.
    # 3. Instantiate ``registry = AgentRegistry(project_id=project_id, location=location,
    #    header_provider=header_provider)``.
    # 4. When ``discover_catalog`` is True, call ``discover_agent_registry_catalog(registry)``.
    # 5. Resolve ``registry.get_mcp_toolset(mcp_server_name, ...)`` when ``mcp_server_name`` is set.
    # 6. Resolve ``registry.get_remote_a2a_agent(remote_a2a_agent_name, httpx_client=...)``
    #    using ``httpx.AsyncClient(auth=GoogleApiAuth(project_id), timeout=httpx.Timeout(...))``
    #    (or ``OidcIdTokenAuth(a2a_audience)`` for Cloud Run/IAP endpoints).
    # 7. Return ``{"registry": registry, "mcp_toolset": ..., "remote_agent": ...,
    #    "agents": ..., "mcp_servers": ...}``.
    _ = (
        project_id,
        location,
        mcp_server_name,
        remote_a2a_agent_name,
        continue_uri,
        header_provider,
        discover_catalog,
        register_auth_provider,
        httpx_timeout_seconds,
        a2a_audience,
    )
    raise NotImplementedError("Complete TODO(lab-5): build_agent_registry_integrations()")


# ---------------------------------------------------------------------------
# Part 3: Vertex AI / Agent Platform Skill Registry Publisher
# ---------------------------------------------------------------------------


class SkillRegistryPublisher:
    """Publish, update, search, and list skills in Vertex AI Skill Registry."""

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
        """List skills in Vertex AI Skill Registry (handling first-call ``gcp-skill-registry`` quirk)."""
        # TODO(lab-5): Call ``list(self.client.skills.list())``. Remember that the built-in
        # ``gcp-skill-registry`` skill starts ingesting asynchronously on the project's FIRST
        # API call and appears starting on call #2 — when ``trigger_builtin_warmup=True`` and
        # ``gcp-skill-registry`` is missing from the first response, sleep ``warmup_delay_seconds``
        # and issue a second ``list(self.client.skills.list())`` call.
        _ = (trigger_builtin_warmup, warmup_delay_seconds, time)
        raise NotImplementedError("Complete TODO(lab-5): SkillRegistryPublisher.list_skills()")

    def create_skill(
        self,
        skill_id: str,
        display_name: str,
        description: str,
        local_path: str | Path,
    ) -> Any:
        """Create a skill from a local directory (auto-zipped) or pre-validated ``.zip``."""
        validate_skill_id(skill_id)
        resolved = Path(local_path).resolve()
        if not resolved.exists():
            raise FileNotFoundError(f"Skill path does not exist: {resolved}")
        # TODO(lab-5): Call ``self.client.skills.create(skill_id=skill_id,
        # display_name=display_name, description=description,
        # config={"local_path": str(resolved)})`` (falling back to ``config={"skill_id": ...,
        # "local_path": ...}`` on ``TypeError`` for google-cloud-aiplatform < 1.154.0).
        _ = (display_name, description)
        raise NotImplementedError("Complete TODO(lab-5): SkillRegistryPublisher.create_skill()")

    def update_skill(
        self,
        skill_id: str,
        *,
        display_name: str | None = None,
        description: str | None = None,
        local_path: str | Path | None = None,
    ) -> Any:
        """Update an existing skill's metadata and/or upload a new skill payload revision."""
        validate_skill_id(skill_id)
        # TODO(lab-5): Build ``config`` containing non-None ``display_name``, ``description``,
        # and ``local_path`` and return ``self.client.skills.update(
        # name=self.skill_resource_name(skill_id), config=config)``.
        _ = (display_name, description, local_path)
        raise NotImplementedError("Complete TODO(lab-5): SkillRegistryPublisher.update_skill()")

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
        # TODO(lab-5): Call ``self.client.skills.retrieve(query=query, config={"top_k": top_k})``
        # and return ``list(getattr(response, "retrieved_skills", []) or [])``.
        _ = top_k
        raise NotImplementedError("Complete TODO(lab-5): SkillRegistryPublisher.search_skills()")

    def delete_skill(self, skill_id: str) -> None:
        """Delete a user-created skill (never built-in ``gcp-*`` skills)."""
        validate_skill_id(skill_id, allow_builtin_prefix=False)
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
    p_list.add_argument("--warmup", action="store_true")

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
