---
name: agent-platform-governance-and-registries
description: >-
  Registers, consumes, and governs skills, MCP servers, and A2A agents on Agent
  Platform. Use when validating Skill Registry ZIPs (16 rules,
  gcp-skill-registry quirk, agentplatform SDK/REST), managing Agent Registry
  standalone skills (private-, revisions, LLM scanning, Org Policy),
  registering A2A/REST/MCP Services, Bindings, search/quotas/boundaries,
  consuming registries in ADK (GCPSkillRegistry, SkillToolset, AgentRegistry,
  RemoteA2aAgent, google-adk[a2a,agent-identity,mcp], httpx.Auth, Auth Manager
  2LO/3LO (GcpAuthProvider), header_provider, .clone(), sandbox egress), or
  configuring SPIFFE Agent Identity, Semantic Governance
  (load_skill/run_skill_script NLCs, non-streaming, CEL), Agent Gateway, IAM
  UAPs, Model Armor, dry-run audits, Topology, or Security Findings. Don't use
  for ADK (adk-coding-agent-build), sandboxes (agent-platform-sandbox-byoc),
  Runtime (agent-platform-runtime-and-state), evals
  (agent-platform-optimize-and-eval), GKE (agent-runtime-vs-gke-architecture),
  or google-agents-cli-publish.
---

# Agent Platform Governance, Registries & Policies

Author, validate, register, consume, and govern **Skills**, **MCP servers**, and **A2A agents** across the **Build & Govern pillars** of Google Cloud's **Gemini Enterprise Agent Platform**.

## Baseline Dependencies & Environment

```bash
# ADK consumption (MUST include a2a + agent-identity extras to avoid ImportError!)
# Use google-cloud-agentplatform>=2.0.1 (canonical Agent Platform SDK) + google-cloud-aiplatform>=1.154.0 (Skill Registry `skill_id` kwarg + re-export)
pip install --upgrade "google-adk[a2a,agent-identity,mcp]>=2.0.0" "google-cloud-agentplatform>=2.0.1" "google-cloud-aiplatform>=1.154.0"

# gcloud CLI & ADC
gcloud components update && gcloud components install alpha
gcloud auth application-default login
export GOOGLE_CLOUD_PROJECT="GOVERNANCE_PROJECT_ID"
export AGENT_REGISTRY_LOCATION="asia-southeast3"         # Bangkok default (A2A/MCP discovery)
export AGENT_REGISTRY_SKILLS_LOCATION="global"           # Standalone skills (`gcloud alpha agent-registry skills`; asia-southeast3 currently times out)
export GOOGLE_CLOUD_LOCATION="asia-southeast1"           # Singapore fallback (Agent Runtime & Agent Gateway — not yet in Bangkok)
export MODEL_LOCATION="global"                           # Frontier Gemini 4 Hydrogen/Neon (or asia-southeast1 with gemini-4-argon)
export SKILL_REGISTRY_LOCATION="us-central1"             # Vertex AI Skill Registry Preview (3 regions only: us-central1, europe-west4, us-east5)
```

---

## Quick Decision Tree: Choosing the Right Surface

```text
What do you need to do?
├── Package, validate (all 16 atomic ZIP/SKILL.md rules), or CRUD skills on Vertex AI Skill Registry
│   └── Use `import agentplatform` (`aiplatform.googleapis.com/v1beta1`, 10 MB ZIP / 500 MB unzipped)
│       -> See references/skill-registry-packaging.md
├── Centrally govern standalone skills (LLM security scanning, Org Policy, private- prefix, 1 MB ZIP)
│   OR register remote A2A/REST agents, MCP servers, endpoints, search, or Auth Manager Bindings
│   └── Use Agent Registry (`agentregistry.googleapis.com/v1`, gcloud / Terraform)
│       -> See references/agent-registry-and-discovery.md
├── Dynamically search/load skills or connect to A2A subagents / MCP servers from ADK code
│   ├── Skills -> `GCPSkillRegistry` + `SkillToolset` (6 built-in tools; mind sandbox egress!)
│   └── A2A / MCP -> `AgentRegistry` (`google-adk[a2a,agent-identity,mcp]>=2.0.0`)
│       -> See references/adk-consuming-registries.md
├── Govern runtime behavior (intercept `load_skill` / `run_skill_script` / supply chain via NLCs),
│   provision SPIFFE Agent Identity, or enforce Agent Gateway + IAM UAPs + Model Armor + Dry-Run
│   └── Configure Agent Identity + Agent Gateway + Semantic Governance + IAM UAPs
│       -> See references/semantic-governance-and-identity.md
└── Building local toolsets / BYOC sandboxes / Runtime Terraform / Evals / GKE comparison?
    └── Switch to sibling skill (`adk-coding-agent-build`, `agent-platform-sandbox-byoc`,
        `agent-platform-runtime-and-state`, `agent-platform-optimize-and-eval`, or
        `agent-runtime-vs-gke-architecture`).
```

### Critical Architecture Split: Two Distinct Skill Registry APIs

| Feature | Vertex AI Skill Registry (`aiplatform.../v1beta1`) | Agent Registry Standalone Skills (`agentregistry.../v1`) |
|---|---|---|
| **Max ZIP / Unzipped** | **10 MB** compressed / **500 MB** total | **1 MB** compressed / **10 MB** total & **1 MB**/file (when scanned) |
| **Locations** | `us-central1`, `europe-west4`, `us-east5` (`SKILL_REGISTRY_LOCATION`; `local_path` MUST be a directory, never `.zip`) | **`global`** (`AGENT_REGISTRY_SKILLS_LOCATION=global`, `gcloud alpha agent-registry skills`; standalone skills currently time out in `asia-southeast3`, while A2A/MCP stays in Bangkok `asia-southeast3`) |
| **Skill ID Behavior** | `SKILL_ID` immutable (no `gcp-` prefix; 24h+ reuse lockout) | Auto-prepends **`private-`** (`private-SKILL_ID`) on all user skills |
| **Security & Scanning** | Async 16-check ZIP/`SKILL.md` validation; project IAM | Auto LLM scanning (`ENABLED_BLOCKING`), `Finding` triage, Org Policy, resource IAM |
| **Built-in Skills** | `gcp-skill-registry` (async first-call ingestion quirk) | Google-managed `FIRST_PARTY` skills (`cloud.google.com`, `github.com/google/skills`) |

---

## Critical Gotchas ("Do This, Not That")

1. **Always validate all 16 ZIP/`SKILL.md` rules locally before uploading** — never wait for an async LRO failure.
   - *Why:* Vertex AI Skill Registry validates asynchronously (11 ZIP rules + 5 `SKILL.md` rules = 16 atomic checks; Agent Registry adds stricter `1 MB` ZIP / `10 MB` scanned caps and requires `SKILL.md` directly at ZIP root). Always `cd` inside the skill folder before zipping, or run `scripts/package_registry_skill.py`.
2. **Never assert `gcp-skill-registry` on your first Skill Registry call, and never delete-and-recreate the same `SKILL_ID`.**
   - *Why:* The first API call asynchronously triggers ingestion of `gcp-skill-registry` (it appears starting on call #2). Deleting a `SKILL_ID` locks reuse for at least 24 hours (and Create docs warn of permanent reservation) — always use `UpdateSkill` instead.
3. **Always use `private-SKILL_ID` after creating an Agent Registry standalone skill, and pass `-L` on REST downloads.**
   - *Why:* Agent Registry auto-assigns user skills to the `private` publisher and prepends `private-`. `?alt=media` returns a 302 redirect to a GCS signed URL (`curl -L` required; custom `httpx` clients must also strip `x-goog-*` headers on cross-origin redirect to avoid signature mismatch).
4. **Install `google-adk[a2a,agent-identity,mcp]>=2.0.0` — never core-only `google-adk` when importing `AgentRegistry`.**
   - *Why:* `google.adk.integrations.agent_registry` imports `a2a-sdk` and `agent-identity` at module scope and raises `ImportError` without both extras.
5. **Authenticate `RemoteA2aAgent` via `httpx.AsyncClient(auth=...)`, NEVER via `AgentRegistry(header_provider=...)`, and call `.clone()` for shared subagents.**
   - *Why:* `header_provider` applies **only** to `McpToolset` (never Agent Registry API or `RemoteA2aAgent`). Match the bearer token to the target: OAuth + `X-Goog-User-Project` for `*.googleapis.com`, **OIDC ID token** (`fetch_id_token`) for `*.run.app` / IAP. A `RemoteA2aAgent` can only have one parent `LlmAgent` unless cloned.
6. **Keep `GCPSkillRegistry` outside network-isolated sandboxes (or enable Google API egress) and check `AGENT_REGISTRY_ENDPOINT`.**
   - *Why:* Isolated sandboxes without outbound access to Google APIs fail remote registry calls and fall back to local skills. Note that `adk-python` `main` `GCPSkillRegistry` calls `agentregistry.googleapis.com/v1alpha` (overridable via `AGENT_REGISTRY_ENDPOINT`), whereas older docs reference Vertex AI SDK.
7. **Never confuse the 4 Identifier Layers: URNs (`urn:...`), Resource Names (`projects/...`), Agent Principals (`principal://...`), and Runtime References.**
   - *Why:* URNs are ONLY for discovery/search/`Binding` source & target (NEVER IAM/IAP/Gateway). IAM/UAP policies MUST use `principal://` or `principalSet://` (**passing `spiffe://` returns `INVALID_ARGUMENT`**). Gateway/IAP/Semantic Governance targets MUST use Resource Names.
8. **Disable model streaming for Semantic Governance, exclude gRPC in `AuthzPolicy` CEL, and deploy agents with BOTH `AGENT_IDENTITY` and `agent_gateway_config`.**
   - *Why:* Semantic Governance **does NOT support streaming** (`:streamGenerateContent` / `:streamRawPredict`) — streamed tool calls can bypass blocks! Omitting `!request.headers['content-type'].startsWith('application/grpc')` breaks Cloud Resource Manager gRPC calls and agent startup. Use `contains()` (not `endsWith()`) because `request.path` includes query strings. Both `AGENT_IDENTITY` and `agent_gateway_config` are immutable on `ReasoningEngine`.
9. **Enable IAP UAP enforcement by REMOVING `iamEnforcementMode` from `metadata` — NEVER set `"ENFORCED"` via CLI/Terraform/REST.**
   - *Why:* The IAP API validator rejects any explicit `iamEnforcementMode` value other than `"DRY_RUN"`. Also remember `updateMask=metadata` replaces the **entire** `metadata` map (retain sibling keys like `sgpUserIntentMatching`), and never blanket-deny `destination.is_registered == false` in UAPs (breaks `telemetry.mtls.googleapis.com`).

---

## Quick-Start Patterns

### 1. Validate & Package a Skill ZIP Pre-Upload
```bash
# Dry-run all 16 Skill Registry rules (add --agent-registry for 1 MB / 10 MB scanned caps)
# In this workshop repo, the ready-to-register sample lives at solution/skills_to_register/secure-code-review
python3 scripts/package_registry_skill.py solution/skills_to_register/secure-code-review --dry-run
python3 scripts/package_registry_skill.py ./skills/secure-code-review --agent-registry -o /tmp/skill.zip
```

### 2. Register a Standalone Skill & Check Scan Findings (Agent Registry — `gcloud alpha`, `--location=global`)
```bash
# Verified live (`gcloud 588.0.0 alpha`):
# - Standalone skills are alpha-only (`gcloud alpha agent-registry skills`) and run in `--location=global`
#   (A2A/MCP stays in Bangkok `asia-southeast3`; standalone skills currently time out in `asia-southeast3`).
# - 2-step flow: omit `--payload` on `skills create` (CLI bug drops `--payload` -> HTTP 400 `source is required`),
#   then upload `rev-1` (2-char `v1` fails format validation). Delete child revisions BEFORE `skills delete`!
export AGENT_REGISTRY_SKILLS_LOCATION="${AGENT_REGISTRY_SKILLS_LOCATION:-global}"

# Step 1: Create bare skill shell (auto-prefixes `private-`)
# Production default is `--scanning-policy=enabled-blocking` (for rapid workshop demos that skip
# waiting on async LLM scans, pass `--scanning-policy=enabled-nonblocking`).
gcloud alpha agent-registry skills create secure-code-review \
  --project="${GOOGLE_CLOUD_PROJECT}" --location="${AGENT_REGISTRY_SKILLS_LOCATION}" \
  --display-name="Secure Code Review" --description="Audits patches for security issues." \
  --target-state=disabled --scanning-policy=enabled-blocking

# Step 2: Upload validated ZIP as revision `rev-1`
gcloud alpha agent-registry skills revisions create rev-1 \
  --skill=private-secure-code-review \
  --project="${GOOGLE_CLOUD_PROJECT}" --location="${AGENT_REGISTRY_SKILLS_LOCATION}" \
  --payload="/tmp/skill.zip"

# Poll scan state BEFORE calling `skills update --default-revision`!
# Under ENABLED_BLOCKING, immediate promotion fails with:
#   FAILED_PRECONDITION: cannot set default revision to a revision with pending scan results
#   when scanning policy is ENABLED_BLOCKING
gcloud alpha agent-registry skills revisions describe rev-1 \
  --skill=private-secure-code-review --project="${GOOGLE_CLOUD_PROJECT}" --location="${AGENT_REGISTRY_SKILLS_LOCATION}"

# Promote & activate once scanResult.scanState=SUCCEEDED with 0 findings (set --default-revision for ADK GCPSkillRegistry)
gcloud alpha agent-registry skills update private-secure-code-review \
  --project="${GOOGLE_CLOUD_PROJECT}" --location="${AGENT_REGISTRY_SKILLS_LOCATION}" \
  --default-revision="projects/${GOOGLE_CLOUD_PROJECT}/locations/${AGENT_REGISTRY_SKILLS_LOCATION}/skills/private-secure-code-review/revisions/rev-1" \
  --target-state=ACTIVE

# Clean teardown order: delete child revision(s) BEFORE deleting the skill (no `--force` flag in CLI)
# gcloud alpha agent-registry skills revisions delete rev-1 --skill=private-secure-code-review --project="${GOOGLE_CLOUD_PROJECT}" --location="${AGENT_REGISTRY_SKILLS_LOCATION}" --quiet
# gcloud alpha agent-registry skills delete private-secure-code-review --project="${GOOGLE_CLOUD_PROJECT}" --location="${AGENT_REGISTRY_SKILLS_LOCATION}" --quiet
```

### 3. Consume Skill Registry + Agent Registry in ADK Python
```python
import os, httpx, google.auth
from google.auth.transport.requests import Request
from google.adk.agents.llm_agent import LlmAgent
from google.adk.auth.credential_manager import CredentialManager
from google.adk.integrations.agent_identity import GcpAuthProvider
from google.adk.integrations.agent_registry import AgentRegistry
from google.adk.integrations.skill_registry import GCPSkillRegistry
from google.adk.tools.skill_toolset import SkillToolset

project_id = os.environ["GOOGLE_CLOUD_PROJECT"]
registry_location = os.environ.get("AGENT_REGISTRY_LOCATION", "asia-southeast3")  # Bangkok default for A2A/MCP discovery
skills_location = os.environ.get("AGENT_REGISTRY_SKILLS_LOCATION", "global")      # global required for standalone skills (asia-southeast3 times out)

# 1. Dynamic skills via GCPSkillRegistry + SkillToolset
skill_toolset = SkillToolset(
    skills=[],  # Optional local fallback skills (take precedence on name collision)
    registry=GCPSkillRegistry(project_id=project_id, location=skills_location),
)

# 2. Governed MCP toolsets (Auth Manager) & remote A2A subagents (httpx.Auth)
CredentialManager.register_auth_provider(GcpAuthProvider())
registry = AgentRegistry(project_id=project_id, location=registry_location)
mcp_toolset = registry.get_mcp_toolset("mcpServers/SERVER_ID")

class GoogleApiAuth(httpx.Auth):
    def __init__(self, quota_project: str):
        self.quota_project = quota_project
        self.creds, _ = google.auth.default(scopes=["https://www.googleapis.com/auth/cloud-platform"])
    def auth_flow(self, request):
        if not self.creds.valid:
            self.creds.refresh(Request())
        request.headers["Authorization"] = f"Bearer {self.creds.token}"
        request.headers["X-Goog-User-Project"] = self.quota_project
        yield request

remote_agent = registry.get_remote_a2a_agent(
    "agents/AGENT_ID",
    httpx_client=httpx.AsyncClient(auth=GoogleApiAuth(project_id), timeout=httpx.Timeout(60.0)),
)

import inspect
from google import genai
from google.adk.models import Gemini

auth_key = "enterprise" if "enterprise" in inspect.signature(genai.Client.__init__).parameters else "vertexai"
root_agent = LlmAgent(
    model=Gemini(model="gemini-4-hydrogen", client_kwargs={auth_key: True, "project": project_id, "location": "global"}),
    name="governed_coding_agent",
    instruction="Discover skills with search_skills, load with load_skill, and delegate via subagents.",
    tools=[skill_toolset, mcp_toolset],
    sub_agents=[remote_agent.clone()],
)
```

### 4. Author a Semantic Governance Policy for ADK Skills (Start in `DRY_RUN`)
```bash
# Scope the regional endpoint override to this invocation (avoid sticky global
# `gcloud config set api_endpoint_overrides/aiplatform`, which breaks `global`/cross-region `gcloud ai` calls
# unless paired with `gcloud config unset api_endpoint_overrides/aiplatform`).
# Note: Semantic Governance Preview currently supports 8 US/EU regions (see references/semantic-governance-and-identity.md).
export SGP_LOCATION="${SGP_LOCATION:-us-central1}"
CLOUDSDK_API_ENDPOINT_OVERRIDES_AIPLATFORM="https://${SGP_LOCATION}-aiplatform.googleapis.com/" \
gcloud beta ai semantic-governance-policies create tainted-session-skill-guard \
  --location="${SGP_LOCATION}" --project="${GOOGLE_CLOUD_PROJECT}" \
  --display-name="Tainted Session Skill Guard" \
  --agent="projects/${GOOGLE_CLOUD_PROJECT}/locations/${SGP_LOCATION}/agents/AGENT_ID" \
  --natural-language-constraint="Do not load any skill that can send messages or write to external systems if the current chat history contains content fetched from inbound email, web pages, or uploaded documents." \
  --agent-response-denial-message="Blocked by enterprise skill governance policy."
```

---

## Modular References

Load **only** the specific reference file needed for your current task:

| Reference File | Deep-Dive Scope |
|---|---|
| [references/skill-registry-packaging.md](references/skill-registry-packaging.md) | Vertex AI Skill Registry (`v1beta1`) vs Agent Registry split, regions/compliance, **all 16 atomic ZIP/`SKILL.md` validation rules**, `SKILL_ID` reuse lockout, `gcp-skill-registry` first-call quirk, `agentplatform` Python/Node.js/REST CRUD & LRO polling |
| [references/agent-registry-and-discovery.md](references/agent-registry-and-discovery.md) | Management boundaries & cross-project scoping, 4 identifier layers, manual A2A/REST/MCP `Service` registration (`gcloud` & Terraform), standalone skills (`private-`, revisions, 5 lifecycle states), LLM security scanning, `Finding` triage, custom Org Policy YAML, keyword/semantic search, Auth Manager Bindings, and exact quotas/limits |
| [references/adk-consuming-registries.md](references/adk-consuming-registries.md) | `google-adk[a2a,agent-identity,mcp]` extras, `SkillToolset` 6 tools & lifecycle modes, `GCPSkillRegistry` source-verified behavior (`AGENT_REGISTRY_ENDPOINT`, 302 GCS hook, sandbox egress caveat), `AgentRegistry` API, all 3 auth patterns (`httpx.Auth` OAuth vs OIDC, Auth Manager 2LO/3LO, `header_provider`), `.clone()`, non-ADK A2A v1.0, and Go client |
| [references/semantic-governance-and-identity.md](references/semantic-governance-and-identity.md) | SPIFFE Agent Identity & 3-Identity Delegation, Semantic Governance engine provisioning & `AuthzPolicy` CEL (non-streaming, gRPC exclusion), skill lifecycle NLC examples & limits, 14-code error catalog, Agent Gateway & VPC-SC, IAM UAPs & CEL, `iamEnforcementMode` validator trap, Model Armor limits, cross-control dry-run audits, Topology & Security Findings |
| [references/maintenance.md](references/maintenance.md) | Canonical upstream URL manifest (seed + all 50 verified sub-links & ADK source files), `.md.txt`/`.md` refresh endpoints, verification date (`2026-11-23`), and section-by-section update checklist |

---

## Maintenance

Verified on `2026-11-23` against Google Cloud Docs, ADK Docs, and live `google/adk-python` source. See [references/maintenance.md](references/maintenance.md) for the complete upstream manifest and refresh checklist.
