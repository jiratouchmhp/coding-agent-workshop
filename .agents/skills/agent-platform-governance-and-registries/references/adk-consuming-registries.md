# Consuming Skill Registry & Agent Registry from ADK

Source-verified ADK Python (`google-adk`) and Go (`google.golang.org/adk/v2`) reference for dynamically discovering, authenticating, and executing skills (`SkillToolset`, `GCPSkillRegistry`), remote A2A subagents (`RemoteA2aAgent`), and MCP toolsets (`McpToolset`) from Google Cloud registries.

---

## 1. Installation & Dependency Matrix (Avoid the `ImportError` Trap!)

| Integration | Minimum ADK Version | Install Command | Critical Dependency Note |
|---|---|---|---|
| Local `SkillToolset` | ADK Python 2.0+ (also supported in ADK TS/Go/Kotlin) | `pip install "google-adk>=2.0.0"` | Included in core `google-adk`. |
| `GCPSkillRegistry` | ADK Python 2.0+ (Preview) | `pip install "google-adk>=2.0.0"` | Included in core `google-adk`. |
| **`AgentRegistry` (Python)** | ADK Python 2.0+ (Preview; full Auth Manager + MCP) | `pip install --upgrade "google-adk[a2a,agent-identity,mcp]>=2.0.0"` *(or `uv add ...`)* | **Mandatory extras:** `google.adk.integrations.agent_registry` imports `a2a-sdk` AND `agent-identity` at **module scope**. Core-only `pip install google-adk` immediately raises **`ImportError`**! Minimum without MCP: `"google-adk[a2a,agent-identity]>=2.0.0"`. |
| **`agentregistry` (Go)** | Go `v2.1.0+` (Preview) | `go get google.golang.org/adk/v2` | Package `google.golang.org/adk/v2/agentregistry` ships in core module (no extras). |

**Environment Baseline:**
```bash
gcloud auth application-default login
export GOOGLE_CLOUD_PROJECT="GOVERNANCE_PROJECT_ID"
export AGENT_REGISTRY_LOCATION="asia-southeast3"   # Bangkok primary Agent Registry (also supports "global", "us", "eu", or regional)
export GOOGLE_CLOUD_LOCATION="asia-southeast1"     # Singapore Agent Runtime & Gemini 2.5 Flash region
```

---

## 2. Core ADK `SkillToolset` Contract (Source-Verified: `skill_toolset.py`)

`SkillToolset` implements **3-level progressive disclosure**:
- **L1 (Metadata):** YAML frontmatter `name` & `description` (discovered via `list_skills`/`search_skills` or injected in `EAGER` mode).
- **L2 (Instructions):** `SKILL.md` Markdown body loaded on demand via `load_skill`.
- **L3 (Resources & Scripts):** Files in `references/`, `assets/`, `scripts/` loaded via `load_skill_resource` or executed via `run_skill_script`.

### All 6 Built-in ADK Skill Tools
| Tool Name | When Exposed | Runtime Behavior |
|---|---|---|
| `list_skills` | Default `SkillDiscoveryMode.LAZY` (omitted in `EAGER`) | Lists available local skills without bloating the system prompt |
| `search_skills` | Whenever `registry=` is supplied | Calls `await registry.search_skills(query=...)` and filters out names colliding with local skills |
| `load_skill` | Always | Fetches/unpacks skill (local or remote ZIP) and caches instructions & resources in session state `_adk_activated_skill_{agent_name}` |
| `unload_skill` | Always | Releases active skill and removes its contributed tools |
| `load_skill_resource` | Always | Reads files under `references/`, `assets/`, or `scripts/` (binary files use content injection) |
| `run_skill_script` | When `code_executor` or `environment` is configured | Executes scripts from `scripts/` (default `script_timeout=300` seconds) |

### Exact `SkillToolset.__init__` Signature & Constraints
```python
from pathlib import Path
from google.adk.skills import load_skill_from_dir
from google.adk.tools.skill_toolset import (
    SkillDiscoveryMode,
    SkillLifecycleConfig,
    SkillLifecycleMode,
    SkillToolset,
)

local_skill = load_skill_from_dir(Path("./skills/local-linter"))

toolset = SkillToolset(
    skills=[local_skill],                     # Optional list[models.Skill]
    registry=registry,                        # Optional SkillRegistry (e.g. GCPSkillRegistry)
    code_executor=None,                       # BaseCodeExecutor — MUTUALLY EXCLUSIVE with environment!
    environment=None,                         # BaseEnvironment — passing BOTH raises ValueError!
    skills_folder=None,                       # Absolute Path/str inside environment (default: working_dir/'skills')
    script_timeout=300,                       # Seconds (default 300s)
    save_output_artifacts=False,              # ONLY supported with code_executor (NOT environment)
    additional_tools=None,                    # Tools dynamically activated with skills
    tool_name_prefix=None,
    tool_filter=None,
    discovery_mode=SkillDiscoveryMode.LAZY,   # LAZY (list_skills) vs EAGER (XML catalog in system prompt)
    lifecycle_config=SkillLifecycleConfig(
        enabled=True,
        default_mode=SkillLifecycleMode.PERSISTENT,  # PERSISTENT | BOUNDED | EPHEMERAL
        max_active_skills=5,                         # Applies ONLY to BOUNDED skills (LRU eviction)
        skill_overrides={"heavy-skill": SkillLifecycleMode.EPHEMERAL},
        revalidate_skills=False,                     # True re-checks registry per turn (breaks prompt cache!)
    ),
)
```

> **Lifecycle & Local Validation Traps:**
> - **`code_executor` vs `environment`:** Mutually exclusive (`ValueError` if both passed). `save_output_artifacts=True` works with `code_executor` only (caps: 5 MiB/file, 16 MiB total, 50 files).
> - **`EPHEMERAL` under `run_live`:** Not supported on bidi streams (no turn boundary) — degrades to `PERSISTENT`.
> - **Local ADK `load_skill_from_dir` validation:** Stricter than Vertex AI Skill Registry — rejects consecutive hyphens (`--`) and **requires parent directory name to exactly match frontmatter `name`**.

---

## 3. `GCPSkillRegistry` Deep Dive (Source-Verified: `gcp_skill_registry.py`)

### Constructor & Usage with `Agent`
All constructor and method arguments are **keyword-only** (`*`). Both `project_id` and `location` fall back to `GOOGLE_CLOUD_PROJECT` and `GOOGLE_CLOUD_LOCATION` (raises `ValueError` if either is missing):

```python
import os
from google.adk import Agent
from google.adk.integrations.skill_registry import GCPSkillRegistry
from google.adk.tools.skill_toolset import SkillToolset

registry = GCPSkillRegistry(
    project_id=os.environ.get("GOOGLE_CLOUD_PROJECT"),
    location=os.environ.get("AGENT_REGISTRY_LOCATION", "asia-southeast3"),
    # credentials=optional_google_auth_credentials,
)

skill_toolset = SkillToolset(
    skills=[],           # Optional local fallback skills (take precedence on name collision!)
    registry=registry,
)

agent = Agent(
    model="gemini-2.5-flash",
    name="registry_coding_agent",
    description="Dynamically discovers and executes enterprise skills.",
    instruction=(
        "Use search_skills to discover relevant skills and load_skill to "
        "activate instructions before executing specialized workflows."
    ),
    tools=[skill_toolset],
)

# Direct async API (keyword-only args):
# frontmatters = await registry.search_skills(query="secure code review")
# skill = await registry.get_skill(name="private-secure-code-review")
```

### Runtime Behaviors & Critical Source Realities
1. **Collision Prevention:** Registry results matching any locally loaded skill name are automatically filtered out.
2. **Session State Caching:** `load_skill` downloads and unpacks the ZIP payload once per session and caches it in session state (`_adk_activated_skill_{agent_name}`), avoiding repeated network calls across turns.
3. **Sandbox Egress Caveat:** Agents running inside isolated sandboxes **without outbound network access to Google APIs** will fail to reach the registry and fall back to locally mounted filesystem skills. Either run `GCPSkillRegistry` inside the trusted orchestrator runtime (outside the isolated code sandbox) or configure VPC/PSC egress to Google APIs.
4. **CRITICAL Doc vs. `adk-python` `main` Endpoint Evolution:**
   - `adk.dev/integrations/skills-registry` describes `GCPSkillRegistry` as calling Vertex AI services via the Vertex AI SDK.
   - However, current `google/adk-python` `main` (`gcp_skill_registry.py`) calls **Agent Registry** (`https://agentregistry.googleapis.com/v1alpha`, mTLS `https://agentregistry.mtls.googleapis.com/v1alpha`), overridable via **`AGENT_REGISTRY_ENDPOINT`**:
     - `POST .../skills:search` with `{"search_string": query}` (falls back to `GET` on HTTP `404`/`405`).
     - `GET .../skills/{name}` -> reads `defaultRevision` -> `GET .../{defaultRevision}?alt=media` with `follow_redirects=True`.
   - **302 GCS Signed URL Header-Stripping Hook:** Agent Registry `?alt=media` returns a 302 redirect to a GCS signed URL. `httpx` automatically drops `Authorization` on cross-origin redirects but **retains `x-goog-user-project` and `x-goog-api-client`**, which invalidates GCS signatures! `GCPSkillRegistry` registers an `httpx` request hook that strips all `x-goog-*` headers when redirected off `base_host`. (Replicate this hook if writing custom `httpx` downloaders!)
   - **Registry Resource IDs Permit Dots:** Unlike `SKILL.md` frontmatter names, `get_skill(name=...)` accepts `^[a-z0-9]+(?:[._-][a-z0-9]+)*$` (<= 256 chars) so Google-published IDs like `cloud.google.com-agent-platform-eval-flywheel` work cleanly.

---

## 4. `AgentRegistry` Client & All 3 Auth Patterns (Source-Verified: `agent_registry.py`)

### Complete Python API Surface
```python
from google.adk.integrations.agent_registry import AgentRegistry

registry = AgentRegistry(
    project_id=project_id,        # Required (raises ValueError if missing)
    location=location,            # Required, e.g. os.environ.get("AGENT_REGISTRY_LOCATION", "asia-southeast3") or "global"
    header_provider=None,         # Optional Callable[[ReadonlyContext], dict[str, str]] — MCP ONLY!
)
```

Accepts **short relative names** (`"agents/AGENT_ID"`, `"mcpServers/SERVER_ID"`) or **full resource names** (`f"projects/{project_id}/locations/{location}/agents/AGENT_ID"`):
- **Agents:** `list_agents(filter_str, page_size, page_token)`, `search_agents(*, search_string, search_type, filter_str, order_by, page_size, page_token)`, `get_agent_info(name)`, `get_remote_a2a_agent(agent_name, auth_scheme=None, auth_credential=None, *, httpx_client=None, continue_uri=None) -> RemoteA2aAgent`
- **MCP Servers:** `list_mcp_servers(...)`, `search_mcp_servers(*, ...)`, `get_mcp_server(name)`, `get_mcp_toolset(mcp_server_name, auth_scheme=None, auth_credential=None, *, continue_uri=None) -> McpToolset`
- **Endpoints:** `list_endpoints(...)`, `get_endpoint(name)`, `get_model_name(endpoint_name) -> str`

### Pattern 1: Remote A2A Agents Without Auth Manager (`httpx.Auth` Mandatory!)
> **Critical Trap:** Calls to `RemoteA2aAgent` are **NOT** authenticated automatically and **ignore `header_provider`**. Pass an authenticated `httpx.AsyncClient` with a generous timeout (e.g., `60.0s`) and match the bearer token to the target endpoint!

| Target A2A Endpoint | Required Bearer Token | Required Extra Header / Audience |
|---|---|---|
| Google Cloud API (`https://*.googleapis.com`) | OAuth 2.0 access token (`cloud-platform` scope) | `X-Goog-User-Project: QUOTA_PROJECT_ID` |
| Cloud Run (`https://*.run.app`) or IAP HTTPS | **OIDC ID token** (`google.oauth2.id_token.fetch_id_token`) | `audience = f"https://{host}"` (or IAP OAuth client ID) |
| External/SaaS w/ Auth Manager Binding | 2LO / 3LO / API key brokered by Auth Manager | Automatic via `GcpAuthProvider` (Pattern 2) |

```python
import httpx
import google.auth
from urllib.parse import urlparse
from google.auth.transport.requests import Request
from google.oauth2 import id_token
from google.adk.agents.llm_agent import LlmAgent
from google.adk.integrations.agent_registry import AgentRegistry

class GoogleApiAuth(httpx.Auth):
    """For https://*.googleapis.com A2A agent endpoints."""
    def __init__(self, quota_project_id: str):
        self.quota_project_id = quota_project_id
        self.creds, _ = google.auth.default(
            scopes=["https://www.googleapis.com/auth/cloud-platform"]
        )

    def auth_flow(self, request):
        if not self.creds.valid:
            self.creds.refresh(Request())
        request.headers["Authorization"] = f"Bearer {self.creds.token}"
        request.headers["X-Goog-User-Project"] = self.quota_project_id
        yield request

class CloudRunOidcAuth(httpx.Auth):
    """For https://*.run.app or IAP A2A endpoints (requires SA / metadata server)."""
    def __init__(self, audience: str):
        self.audience = audience

    def auth_flow(self, request):
        token = id_token.fetch_id_token(Request(), self.audience)
        request.headers["Authorization"] = f"Bearer {token}"
        yield request

registry = AgentRegistry(project_id=project_id, location=location)
httpx_client = httpx.AsyncClient(auth=GoogleApiAuth(project_id), timeout=httpx.Timeout(60.0))

# Fetch ONCE at startup; use .clone() if attaching to multiple orchestrators!
base_remote = registry.get_remote_a2a_agent("agents/AGENT_ID", httpx_client=httpx_client)

orchestrator_a = LlmAgent(name="orch_a", model="gemini-2.5-flash", sub_agents=[base_remote.clone()])
orchestrator_b = LlmAgent(name="orch_b", model="gemini-2.5-flash", sub_agents=[base_remote.clone()])
```

> **Single-Parent Reuse Gotcha:** A `RemoteA2aAgent` instance can belong to **only one parent orchestrator** at a time. Fetch once at startup to save latency and call **`base_remote.clone()`** for every parent `LlmAgent`.

### Pattern 2: Auth Manager Bindings (2LO, API Key, 3LO User-Delegated)
```python
from google.adk.auth.credential_manager import CredentialManager
from google.adk.integrations.agent_identity import GcpAuthProvider
from google.adk.integrations.agent_registry import AgentRegistry

# Register once at startup so ADK resolves GcpAuthProviderScheme from Registry Bindings
CredentialManager.register_auth_provider(GcpAuthProvider())

registry = AgentRegistry(project_id=project_id, location=location)

# 2LO / API Key binding: resolved automatically from Agent Registry bindings
mcp_2lo = registry.get_mcp_toolset("mcpServers/SERVER_ID")

# 3LO User-Delegated binding: pass continue_uri (client UI must handle adk_request_credential)
mcp_3lo = registry.get_mcp_toolset(
    "mcpServers/USER_SCOPED_SERVER_ID",
    continue_uri="https://app.example.com/oauth/continue",
)
```

> **Runtime Security & Auto-Rebind (`agent_registry.py`):**
> - **Serialization Safety:** When an ADK app is serialized (`__getstate__`), `AgentRegistry.__getstate__` strips `_credentials` and `_session` so deployer credentials never leak.
> - **Automatic Deployment Rebind:** Inside Agent Runtime (`GOOGLE_CLOUD_AGENT_ENGINE_ID` set), `AgentRegistrySingleMcpToolset.get_auth_config()` automatically calls `bindings:fetchAvailable` (10s timeout) scoped to the deployed agent's `RuntimeReference` URI. Deleting a binding revokes access rather than falling back to the deploy-time scheme.
> - **Topology Span Metadata:** Every tool returned by `AgentRegistrySingleMcpToolset.get_tools()` attaches `gcp.mcp.server.destination.id` (`RuntimeReference.uri` preferred, fallback `mcpServerId`) for Agent Platform Topology tracing.

### Pattern 3: Custom MCP Headers (`header_provider`)
- Google MCP servers (`*.googleapis.com`) automatically receive ADC headers when no `auth_scheme`/`auth_credential` is configured.
- For external MCP servers without Auth Manager, pass `header_provider(context: ReadonlyContext) -> dict[str, str]` to `AgentRegistry(...)`.
- **Scope Limit:** `header_provider` applies **ONLY** to `McpToolset` requests — NEVER to Agent Registry API calls (always ADC) and NEVER to `RemoteA2aAgent`.

```python
import os
from google.adk.agents.readonly_context import ReadonlyContext
from google.adk.integrations.agent_registry import AgentRegistry

def custom_mcp_headers(context: ReadonlyContext) -> dict[str, str]:
    return {
        "Authorization": f"Bearer {os.environ['EXTERNAL_API_KEY']}",
        "X-Tenant-Id": "enterprise-lab",
    }

registry = AgentRegistry(project_id=project_id, location=location, header_provider=custom_mcp_headers)
external_tools = registry.get_mcp_toolset("mcpServers/EXTERNAL_SERVER_ID")
```

---

## 5. Non-ADK A2A v1.0 & Go ADK Client Essentials

- **Non-ADK A2A v1.0 Call:** Set header `"A2A-Version": "1.0"`. Fetch `GET https://agentregistry.googleapis.com/v1/projects/{p}/locations/{loc}/agents/{id}`, inspect `card.content.supportedInterfaces` (fallback `protocols[0].interfaces`), attach OAuth+`X-Goog-User-Project` for `*.googleapis.com` or OIDC ID token (`id_token.fetch_id_token` / local `gcloud auth print-identity-token --audiences=...`) for Cloud Run/IAP, and POST `{"jsonrpc": "2.0", "id": "...", "method": "SendMessage", "params": {"message": ...}}` (for `JSONRPC`) or `POST {endpoint}/{tenant}/message:send` (for `HTTP+JSON`).
- **Go ADK (`google.golang.org/adk/v2/agentregistry`):**
  - `registry, err := agentregistry.New(ctx, agentregistry.Config{ProjectID: p, Location: loc})` (auto-mTLS for `*.googleapis.com` MCP, never A2A).
  - Discovery: `List*`, `Get*`, `All*` (`iter.Seq2` lazy pagination; non-2xx returns `*agentregistry.APIError`).
  - Execution: `registry.RemoteAgent(ctx, name, agentregistry.WithA2AHTTPClient(httpClient), agentregistry.WithA2AHeaders(...))` and `registry.MCPToolset(ctx, name, agentregistry.WithMCPHTTPClient(...), agentregistry.WithMCPHeaders(...))`.
  - **Go Timeout Gotcha:** Configure timeouts on `http.Client.Transport`, **NOT** `http.Client.Timeout` (which cancels long-running streaming responses!).

---

## 6. Troubleshooting & Verification

| Error / Symptom | Cause | Fix |
|---|---|---|
| `ImportError: AgentRegistry requires the 'a2a-sdk' package` | Core-only `google-adk` installed | Run `pip install --upgrade "google-adk[a2a,agent-identity,mcp]>=2.0.0"` |
| `ValueError` passing both `code_executor` and `environment` | `SkillToolset` allows only one execution backend | Remove one; use `environment` for coding agents (`BaseEnvironment`) |
| `401`/`403` calling `RemoteA2aAgent` even though `header_provider` is set | `header_provider` does NOT apply to `RemoteA2aAgent` | Pass `httpx_client=httpx.AsyncClient(auth=GoogleApiAuth(...))` or `CloudRunOidcAuth(...)` |
| `401` calling Cloud Run A2A agent with `GoogleApiAuth` | Cloud Run requires OIDC **ID token**, not OAuth access token | Switch to `id_token.fetch_id_token(Request(), f"https://{host}")` |
| `ValueError` attaching same `RemoteA2aAgent` to two `LlmAgent`s | Single-parent rule in ADK | Call `base_remote_agent.clone()` for each orchestrator |
| `GCPSkillRegistry` fails inside isolated sandbox | Sandbox blocks outbound Google API egress | Move `GCPSkillRegistry` to orchestrator runtime or configure PSC/SWP egress |
| `403 SignatureDoesNotMatch` downloading skill ZIP via custom `httpx` | `x-goog-*` headers leaked across 302 redirect to GCS signed URL | Strip `x-goog-*` headers on cross-origin redirect (or use `GCPSkillRegistry`) |

### Concrete Verification Steps
1. Verify extras: `python3 -c "from google.adk.integrations.agent_registry import AgentRegistry; from google.adk.integrations.skill_registry import GCPSkillRegistry; print('OK')"`.
2. Run `await registry.search_skills(query="...")` and `await registry.get_skill(name="private-...")` against your governance project; confirm `skill.instructions` loads cleanly.
3. Call `registry.list_agents()` and `registry.list_mcp_servers()`; verify `get_mcp_toolset(...)` returns tools with `gcp.mcp.server.destination.id` metadata and `get_remote_a2a_agent(...)` succeeds with an authenticated `httpx.AsyncClient`.
