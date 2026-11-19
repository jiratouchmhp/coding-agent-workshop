# Lab 5: Govern Skills, Agent Registry, Semantic Policies & SPIFFE Identity

> **Pillar:** Govern (Skill Registry, Agent Registry, Dynamic ADK Consumption, Semantic Governance Policies & SPIFFE Identity)  
> **Duration:** 50 minutes (Full-Day Track) | 35 minutes (Half-Day Fast-Track)  
> **Antigravity Skill Companion:** [`.agents/skills/agent-platform-governance-and-registries/SKILL.md`](../.agents/skills/agent-platform-governance-and-registries/SKILL.md) *(complements the built-in `google-agents-cli-publish` skill)*  
> **Files You Will Inspect & Edit:** [`starter/skills_to_register/secure-code-review/SKILL.md`](../starter/skills_to_register/secure-code-review/SKILL.md), [`starter/coding_agent/tools/registry_loader.py`](../starter/coding_agent/tools/registry_loader.py), [`starter/coding_agent/agent.py`](../starter/coding_agent/agent.py)  
> **Previous Lab:** [Lab 4: Managed Sessions, Memory Bank, Feedback & Telemetry](./04-LAB-SESSIONS-MEMORY-FEEDBACK.md) | **Next Lab:** [Lab 6: Optimize, Evaluate, Alert & Close the Flywheel](./06-LAB-OPTIMIZE-EVAL-AND-ALERTS.md)

---

## Learning Objectives

By the end of this lab, you will be able to:

1. Validate and package an enterprise coding skill (`starter/skills_to_register/secure-code-review/`) with `scripts/package_registry_skill.py` against **every Google Cloud Skill Registry ZIP and `SKILL.md` payload validation rule** prior to upload.
2. Distinguish **Vertex AI / Agent Platform Skill Registry (`aiplatform.googleapis.com/v1beta1`)** from **Agent Registry Standalone Skills (`agentregistry.googleapis.com/v1`)**, upload and publish `secure-code-review` (handling the built-in `gcp-skill-registry` first-call ingestion quirk and `private-` prefixing), and triage automated LLM security scan `Finding`s.
3. Implement `# TODO(lab-5)` in `starter/coding_agent/tools/registry_loader.py` to dynamically discover and load remote skills via **`GCPSkillRegistry` + `SkillToolset`** (with offline sandbox egress fallback) and connect to governed A2A agents & MCP servers via **`AgentRegistry`** (`google-adk[a2a,agent-identity,mcp]` + auth providers).
4. Author **Semantic Governance Policies** (Natural Language Constraints) enforced on an **Agent-to-Anywhere Egress Agent Gateway** to block unsafe `load_skill`, `run_skill_script`, and dependency-install (`npm_install`) tool calls in tainted sessions — including dry-run validation and the mandatory non-streaming constraint.
5. Apply **SPIFFE Agent Identity**, **3-Identity Delegation**, and **IAM Unified Access Policies (UAPs)** to enforce least-privilege enterprise boundaries.

---

## Half-Day Fast-Track Path (35 Minutes)

If you are running on the **3.5-hour Half-Day Fast-Track**:
- Complete **Part A** (validate all 16 atomic checks and package `secure-code-review` via `make package-skill`).
- Complete **BOTH Part B1** (publish to Vertex AI Skill Registry and observe the `gcp-skill-registry` second-call quirk) **AND Part B2** (register `private-secure-code-review` in Agent Registry and promote it with `--default-revision` and `--target-state=ACTIVE`). **Why both?** Latest `google/adk-python` `main` `GCPSkillRegistry` calls `https://agentregistry.googleapis.com/v1alpha` and resolves `private-secure-code-review`'s default revision! *(If your cohort skips Part B2 cloud upload, test Part C with `AGENT_REGISTRY_ENDPOINT` or local fallback `enable_remote_registry=False`.)*
- Complete **Part C** (implement `# TODO(lab-5)` in `starter/coding_agent/tools/registry_loader.py` and `starter/coding_agent/agent.py`).
- Walk through **Part D** (Semantic Governance NLC policies, Model Armor limits & SPIFFE 3-Identity Delegation) as an architecture exercise, then run `./scripts/verify_lab.sh 5`.

---

## Architecture Overview

```mermaid
flowchart LR
    SkillDir["starter/skills_to_register/secure-code-review/"] -->|"scripts/package_registry_skill.py (All ZIP/SKILL.md Rules)"| Zip["Validated skill.zip"]

    Zip -->|"agentplatform.Client.skills.create"| SkillReg["Skill Registry (aiplatform v1beta1, <=10MB ZIP)"]
    Zip -->|"gcloud agent-registry skills create"| AgentReg["Agent Registry (v1, private-* prefix, <=1MB ZIP, LLM Scanning)"]

    subgraph Runtime["ADK Coding Agent (Agent Runtime, SPIFFE AGENT_IDENTITY)"]
        Toolset["SkillToolset (list/search/load/run_skill_script)"]
        ADKSkillReg["GCPSkillRegistry (with Offline Sandbox Fallback)"]
        ADKAgentReg["AgentRegistry (A2A GoogleApiAuth & Auth Manager MCP)"]
        Toolset --> ADKSkillReg
    end

    ADKSkillReg -.->|"Dynamic Discovery & Caching"| AgentReg
    ADKSkillReg -.->|"Skill Retrieval"| SkillReg
    ADKAgentReg -.->|"Discover A2A / MCP"| AgentReg

    Runtime -->|"Non-Streaming LLM & Tool Egress"| GW["Agent Gateway (AGENT_TO_ANYWHERE Egress)"]
    GW --> SGP["Semantic Governance Policy Engine (NLC + User Intent Matching)"]
    GW --> UAP["IAM UAP (SPIFFE principal://)"]
    GW --> MA["Model Armor (PI / SDP Sanitization)"]
    SGP -->|"DENY unsafe load_skill / npm_install"| Block["Blocked Tool Call (Custom Denial Message)"]
```

---

## Architectural Distinction: Skill Registry vs. Agent Registry Standalone Skills

Google Cloud exposes **two distinct skill registry API surfaces** (see [Agent Registry Skills Architecture](https://docs.cloud.google.com/agent-registry/skills-architecture) and [Vertex AI Skill Registry](https://docs.cloud.google.com/gemini-enterprise-agent-platform/build/skill-registry)). Understanding how they differ prevents 404 errors, payload rejections, and IAM misconfigurations:

| Dimension | Vertex AI / Agent Platform **Skill Registry** (Preview) | **Agent Registry** Standalone Skills (Preview) |
|---|---|---|
| **API Endpoint** | `https://LOCATION-aiplatform.googleapis.com/v1beta1/projects/PROJECT_ID/locations/LOCATION/skills` | `https://agentregistry.googleapis.com/v1/projects/PROJECT_ID/locations/LOCATION/skills` |
| **CLI / SDK Surface** | Python `agentplatform.Client.skills.*` (`google-cloud-aiplatform`), Node.js `@google-cloud/agentplatform`, REST `v1beta1` | `gcloud agent-registry skills ...`, `skills revisions ...`, `findings ...`, REST `v1` |
| **Supported Regions** | `us-central1` (Iowa), `europe-west4` (Netherlands), `us-east5` (Columbus, Ohio) | `global`, multi-regions (`us`, `eu`), or regional (`us-central1`, `europe-west1`, etc.) |
| **Max Compressed ZIP** | **10 MB** | **1 MB** |
| **Max Uncompressed Size** | **500 MB** total | **10 MB** total & **1 MB** per individual file *(when security scanning is enabled)* |
| **Skill ID Naming** | `1–63` chars `[a-z0-9-]`, starts with letter, ends with letter/digit; cannot start with `gcp-` | Auto-assigned to `private` publisher -> registry prepends **`private-`** (`private-SKILL_ID`) |
| **Built-in / Managed Skills** | Built-in `gcp-skill-registry` *(ingested asynchronously on first API call)* | Google-managed `FIRST_PARTY` skills (`cloud.google.com`, `discoveryengine.googleapis.com`) |
| **Security Scanning & Compliance** | Async structural/ZIP validation (16 atomic checks); supports US/EU DRZ & Access Transparency; **no CMEK, HIPAA, or VPC-SC** | Automated LLM security scanning (`ENABLED_BLOCKING` default) + `Finding` triage + Custom Org Policy + resource-level IAM |
| **ADK `GCPSkillRegistry` Target** | Described in `adk.dev/integrations/skills-registry` as Vertex AI SDK | Latest `google/adk-python` `main` (`gcp_skill_registry.py`) calls `https://agentregistry.googleapis.com/v1alpha` (overridable via `AGENT_REGISTRY_ENDPOINT`) |

---

## Part A: Validate & Package `secure-code-review` (`scripts/package_registry_skill.py`)

### Step A1: Inspect the Enterprise Skill Package

Examine the starter skill files your Coding Agent will load on demand when auditing pull requests:
- [`starter/skills_to_register/secure-code-review/SKILL.md`](../starter/skills_to_register/secure-code-review/SKILL.md)
- [`starter/skills_to_register/secure-code-review/references/owasp-checklist.md`](../starter/skills_to_register/secure-code-review/references/owasp-checklist.md)

### Step A2: Complete Skill Registry ZIP & `SKILL.md` Validation Checklist

Skill Registry validates uploaded ZIP payloads **asynchronously** during `CreateSkill` / `UpdateSkill` long-running operations (LROs). Catching violations locally before upload saves minutes of failed LRO debugging.

> [!NOTE]
> **Exact Validation Scope (16 Atomic Checks):** The official `build/skill-registry` documentation presents **12 top-level bullets**, where bullet #11 expands into **5 individual `SKILL.md` frontmatter and body checks** — **16 atomic validation checks** in total (11 ZIP-level + 5 `SKILL.md`-level). `scripts/package_registry_skill.py` enforces **every single one of these 16 atomic checks** locally before emitting a `.zip`!

| # | Scope | Validation Rule Enforced by Skill Registry & `package_registry_skill.py` |
|---|---|---|
| 1 | ZIP | Valid, non-corrupt ZIP archive with complete header metadata |
| 2 | ZIP | Archive is **not empty** |
| 3 | ZIP | Contains **at most 10,000 items** |
| 4 | ZIP | No file or folder name contains `..` (path traversal) or starts with `/` or `\` |
| 5 | ZIP | Contains **zero symbolic links** |
| 6 | ZIP | Contains **zero duplicate file or folder names** |
| 7 | ZIP | Total unzipped size **<= 500 MB** *(note: keep **<= 10 MB** total and **<= 1 MB** per file for Agent Registry scanning compatibility)* |
| 8 | ZIP | Compression ratio **<= 100** (zip-bomb protection) |
| 9 | ZIP | Directory nesting depth **<= 8 levels** |
| 10 | ZIP | Contains a **`SKILL.md`** file *(place directly at ZIP root for Agent Registry compatibility)* |
| 11 | ZIP | Compressed ZIP archive size **<= 10 MB** *(keep **<= 1 MB** for Agent Registry compatibility)* |
| 12 | `SKILL.md` | Contains valid **YAML frontmatter** AND non-empty **Markdown instruction body** |
| 13 | `SKILL.md` | Frontmatter **`name`**: required, **<= 64 chars**, lowercase `a-z`, digits `0-9`, hyphens `-` only; cannot start or end with `-` *(ADK local loader also rejects consecutive `--` and requires parent folder name == `name`)* |
| 14 | `SKILL.md` | Frontmatter **`description`**: required and **<= 1,024 chars** |
| 15 | `SKILL.md` | Frontmatter **`license`** (if present): **<= 1,024 chars** |
| 16 | `SKILL.md` | Markdown instruction body: **<= 500,000 chars** |

### Step A3: Run Pre-Upload Validation & Build the Archive

```bash
# 1. Dry-run validation against all rules (zero output written)
python3 scripts/package_registry_skill.py starter/skills_to_register/secure-code-review --dry-run

# 2. Build the validated skill ZIP into a local build directory (or run via Makefile)
make package-skill
```

Confirm all validation checks pass (`0 errors`) and note the generated `.zip` path (for example, `dist/secure-code-review.zip`).

---

## Part B: Upload to Skill Registry & Govern in Agent Registry

### Step B1: Publish to Vertex AI / Agent Platform Skill Registry (`aiplatform.googleapis.com/v1beta1`)

Set your Skill Registry region (must be one of `us-central1`, `europe-west4`, or `us-east5`):

```bash
source .env
export SKILL_REGISTRY_LOCATION="${SKILL_REGISTRY_LOCATION:-us-central1}"
export SKILL_ID="secure-code-review"
```

> [!CAUTION]
> **Two Critical Skill Registry Quirks:**
> 1. **Built-in `gcp-skill-registry` First-Call Ingestion Quirk:** The Skill Registry begins ingesting the built-in `gcp-skill-registry` skill asynchronously **on your very first API call** to the service. Consequently, **your first `list()` response will NOT include `gcp-skill-registry`** — issue a **second** `list()` call to see it appear! Built-in `gcp-*` skills cannot be deleted.
> 2. **`SKILL_ID` Immutability & Reuse Lockout:** `SKILL_ID` (1–63 chars `[a-z0-9-]`, starts with a letter, ends with letter/digit, cannot start with `gcp-`) becomes the skill's folder name when attached to an agent. Official docs warn that deleting a skill reserves its `SKILL_ID` for **at least 24 hours** (and Create docs warn permanently reserved) — **never delete and immediately recreate with the same `SKILL_ID` during a workshop!** (If you need a fresh ID during testing, append a suffix like `secure-code-review-v2`.)

Publish and inspect via Python (`agentplatform.Client.skills`, provided by `google-cloud-aiplatform`):

```python
import os
import agentplatform

client = agentplatform.Client(
    project=os.environ["GOOGLE_CLOUD_PROJECT"],
    location=os.environ.get("SKILL_REGISTRY_LOCATION", "us-central1"),
)

# 1. Trigger first-call listing (initiates async ingestion of built-in gcp-skill-registry)
first_list = [s.name for s in client.skills.list()]
print("Call #1 skills (gcp-skill-registry not yet present on first project call):", first_list)

# 2. Upload validated skill
# SDK version note:
#   google-cloud-aiplatform >= 1.154.0 accepts skill_id as a top-level argument.
#   google-cloud-aiplatform < 1.154.0 passes {"skill_id": ..., "local_path": ...} inside config={}.
skill = client.skills.create(
    skill_id="secure-code-review",
    display_name="Secure Code Review",
    description="Enterprise OWASP static security audit checklist for Python and TypeScript PRs.",
    config={"local_path": "starter/skills_to_register/secure-code-review"},
)
print("Created skill:", skill.name)

# 3. Second list call — built-in gcp-skill-registry now appears alongside your skill
second_list = [s.name for s in client.skills.list()]
print("Call #2 skills:", second_list)

# 4. Semantic retrieval check
retrieved = client.skills.retrieve(query="audit Python code for OWASP injection flaws", config={"top_k": 3})
for item in retrieved.retrieved_skills:
    print(item.skill_name, "->", item.description)
```

*(Equivalent REST `v1beta1` upload: `POST https://${SKILL_REGISTRY_LOCATION}-aiplatform.googleapis.com/v1beta1/projects/${GOOGLE_CLOUD_PROJECT}/locations/${SKILL_REGISTRY_LOCATION}/skills?skillId=${SKILL_ID}` with JSON body `{"displayName": "...", "description": "...", "zippedFilesystem": "$(base64 -w 0 -i dist/secure-code-review.zip)"}`, then poll the returned LRO via `GET .../operations/OPERATION_ID`. Read-only IAM role: `roles/aiplatform.viewer`.)*

### Step B2: Register, Scan & Govern Standalone Skills in Agent Registry (`agentregistry.googleapis.com/v1`)

Enterprise governance centralizes agents, MCP servers, endpoints, and standalone skills inside **Agent Registry** for automated LLM security scanning, lifecycle state promotion, resource-level IAM, and semantic discovery.

#### Know the Four Agent Registry Identifier Layers

| Identifier Layer | Exact Syntax | Where to Use — and Where NEVER to Use |
|---|---|---|
| **1. Registry URN** | `urn:skill:projects-PROJECT_NUMBER:locations:LOCATION:private-SKILL_ID` | Discovery, search, and `Binding` source/target. **NEVER use URNs in IAM, IAP, or Agent Gateway route policies!** |
| **2. Resource Name** | `projects/PROJECT_NUMBER/locations/LOCATION/skills/private-SKILL_ID` | **Required** for IAM resource policies, IAP/UAP egress policies, Agent Gateway routes, and Semantic Governance `--agent` / `--mcp-tools`. |
| **3. Agent Principal** | `principal://agents.global.org-ORG_ID.system.id.goog/resources/aiplatform/projects/PROJECT_NUMBER/locations/REGION/reasoningEngines/ID` | Enforced by IAM Allow/Deny/UAP policies. **NEVER pass `spiffe://` URIs to IAM** (returns `INVALID_ARGUMENT`)! |
| **4. Runtime Reference** | `agentregistry.googleapis.com/system/RuntimeReference` (`uri`) | App Topology graph correlation and egress matching. |

#### Register, Scan, Triage Findings & Promote

1. Enable Agent Registry API and upload your validated ZIP (`<= 1 MB` compressed) starting in `disabled` state with blocking LLM security scanning enabled:

   ```bash
   gcloud services enable agentregistry.googleapis.com --project="${GOOGLE_CLOUD_PROJECT}"

   export AGENT_REGISTRY_LOCATION="${AGENT_REGISTRY_LOCATION:-us-central1}"

   gcloud agent-registry skills create secure-code-review \
     --project="${GOOGLE_CLOUD_PROJECT}" \
     --location="${AGENT_REGISTRY_LOCATION}" \
     --display-name="Secure Code Review" \
     --description="Enterprise OWASP security audit guidelines for Coding Agent." \
     --target-state=disabled \
     --scanning-policy=enabled-blocking \
     --payload="dist/secure-code-review.zip"
   ```

   > [!IMPORTANT]
   > **Automatic `private-` Prefixing & Auto-IAM:** Agent Registry assigns user-created skills to the `private` publisher and prepends **`private-`** to your ID (`private-secure-code-review`). You **MUST** use `private-secure-code-review` in all subsequent `describe`, `update`, `revisions`, `findings`, and IAM commands! On creation, Agent Registry automatically grants `roles/agentregistry.admin` to the creator and (in org-backed projects) `roles/agentregistry.viewer` to the project's agent workload `principalSet`.

2. Inspect the initial revision's LLM security scan status and triage any findings (`roles/agentregistry.admin`):

   ```bash
   gcloud agent-registry skills describe private-secure-code-review \
     --project="${GOOGLE_CLOUD_PROJECT}" \
     --location="${AGENT_REGISTRY_LOCATION}"

   # Inspect scan findings for a specific revision (VULNERABILITY or SECRET findings):
   # Replace ${REV_ID} with the revision ID printed by `skills describe` above.
   gcloud agent-registry findings list \
     --project="${GOOGLE_CLOUD_PROJECT}" \
     --location="${AGENT_REGISTRY_LOCATION}" \
     --filter="resource=\"projects/${GOOGLE_CLOUD_PROJECT}/locations/${AGENT_REGISTRY_LOCATION}/skills/private-secure-code-review/revisions/${REV_ID}\""
   ```

   - Under `ENABLED_BLOCKING` (default), Agent Registry scans `SKILL.md`, scripts, and assets via LLM for exfiltration, exposed secrets, and prompt injection, and **blocks** downloads or `defaultRevision` promotion with `FAILED_PRECONDITION` until the scan succeeds with zero findings.
   - **Non-retroactive rule:** Changing `scanningConfig.policy` (`ENABLED_BLOCKING` / `ENABLED_NONBLOCKING` / `DISABLED`) applies only to **future revisions**.
   - **5 Lifecycle States:** `DRAFT` -> `ACTIVE` <-> `DISABLED` -> `DEPRECATED` -> `DECOMMISSIONED` (**terminal** — can only transition from `DEPRECATED` and cannot revert!).

3. Once `scanResult.scanState` is `SUCCEEDED` with 0 findings, set the verified revision as the **`--default-revision`** AND promote the skill to **`ACTIVE`** (required so ADK `GCPSkillRegistry` resolves the skill revision cleanly — see [Manage Skills](https://docs.cloud.google.com/agent-registry/manage-skills)), then test semantic search (indexes full `SKILL.md` + scripts + assets):

   ```bash
   # Ensure REV_ID is set to the scanned revision ID returned by `skills describe` above
   gcloud agent-registry skills update private-secure-code-review \
     --project="${GOOGLE_CLOUD_PROJECT}" \
     --location="${AGENT_REGISTRY_LOCATION}" \
     --default-revision="projects/${GOOGLE_CLOUD_PROJECT}/locations/${AGENT_REGISTRY_LOCATION}/skills/private-secure-code-review/revisions/${REV_ID}" \
     --target-state=ACTIVE

   gcloud agent-registry skills search \
     --project="${GOOGLE_CLOUD_PROJECT}" \
     --location="${AGENT_REGISTRY_LOCATION}" \
     --query="find SQL injection and unsafe subprocess vulnerabilities" \
     --search-type=semantic
   ```

4. **Prevent Disabling Skill Scanning Organization-Wide (Custom Org Policy):** Because there is no built-in managed constraint, platform security teams deploy a custom Org Policy constraint on `agentregistry.googleapis.com/Skill`:

   ```yaml
   # skills-scan-constraint.yaml
   name: organizations/ORGANIZATION_ID/customConstraints/custom.skillsScanningEnforcement
   resourceTypes:
   - agentregistry.googleapis.com/Skill
   methodTypes: [CREATE, UPDATE]
   condition: resource.scanningConfig.policy == "DISABLED"
   actionType: DENY
   displayName: Prevent Disabling Skills Scanning
   description: Prevents creating or updating standalone skills with security scanning disabled.
   ```

   > [!NOTE]
   > **Cross-Project Management Boundary & Quotas ([Agent Registry Quotas](https://docs.cloud.google.com/agent-registry/quotas)):** In multi-project Management Boundaries (`agent-management` capability, up to 10,000 member projects), manually registered `Service`, `Binding`, and custom standalone `Skill` / `SkillRevision` / `Finding` resources are **scoped to the project where created** and are NOT aggregated from member projects — create enterprise skills directly in the **management project**. Default allocation quotas: **100** standalone skills and **500** skill revisions per project per location; **100** agents, **100** MCP servers, and **100** bindings per project.

---

## Part C: Dynamic ADK Consumption (`starter/coding_agent/tools/registry_loader.py`)

Open [`starter/coding_agent/tools/registry_loader.py`](../starter/coding_agent/tools/registry_loader.py) and complete the `# TODO(lab-5)` markers for `build_skill_registry_toolset()`, `build_agent_registry_integrations()`, and `SkillRegistryPublisher`.

### Step C1: Mandatory ADK Extras (`ImportError` Trap!)

> [!CAUTION]
> **Mandatory Install Extra for `AgentRegistry`:** `google.adk.integrations.agent_registry` imports `a2a-sdk` and the Agent Identity auth provider at **module scope**. Importing `AgentRegistry` on bare `pip install google-adk` immediately raises **`ImportError`**! Always install:
> ```bash
> pip install --upgrade "google-adk[a2a,agent-identity,mcp]"   # >= 1.29.0 recommended for Auth Manager MCP
> # Minimum required for AgentRegistry without MCP: "google-adk[a2a,agent-identity]"
> ```

### Step C2: Implement `build_skill_registry_toolset()` (`GCPSkillRegistry` + `SkillToolset`)

`SkillToolset` (ADK v1.25.0+) implements **3-level Progressive Disclosure** (L1 metadata -> L2 `SKILL.md` instructions via `load_skill` -> L3 `references/`/`assets/`/`scripts/` via `load_skill_resource` and `run_skill_script`), exposing up to 6 built-in tools: `list_skills`, `search_skills` (added when `registry=` is supplied), `load_skill`, `unload_skill`, `load_skill_resource`, and `run_skill_script`.

Key verified rules to implement in `build_skill_registry_toolset()`:
1. **Keyword-Only Constructor:** `GCPSkillRegistry(project_id=..., location=...)` (ADK v1.27.0+; falls back to `GOOGLE_CLOUD_PROJECT` / `GOOGLE_CLOUD_LOCATION` and raises `ValueError` if missing).
2. **Endpoint & Default-Revision Awareness:** Latest `google/adk-python` `main` (`gcp_skill_registry.py`) calls `https://agentregistry.googleapis.com/v1alpha` (overridable via the `AGENT_REGISTRY_ENDPOINT` environment variable) and automatically strips `x-goog-*` headers across 302 GCS signed-URL redirects. Ensure `private-secure-code-review` from **Part B2** has `--default-revision` and `--target-state=ACTIVE` configured—or pass `enable_remote_registry=False` to exercise local-only fallback cleanly without Agent Registry access.
3. **Collision Prevention & Session Caching:** Local skills in `skills=[...]` automatically shadow registry skills with identical names; `load_skill` caches unpacked skill instructions in session state (`_adk_activated_skill_{agent_name}`).
4. **Mutual Exclusivity:** `SkillToolset` accepts **`environment=`** OR **`code_executor=`**, **never both** (passing both raises `ValueError`!).
5. **CRITICAL Sandbox Egress Fallback:** If your Coding Agent runs inside an isolated network or air-gapped sandbox without outbound HTTPS egress to Google APIs, remote registry calls fail — wrap `GCPSkillRegistry` initialization so the toolset gracefully falls back to locally bundled skills (`load_skill_from_dir(...)`)!

```python
import logging
from pathlib import Path
from google.adk.environment import BaseEnvironment
from google.adk.skills import load_skill_from_dir
from google.adk.tools.skill_toolset import (
    SkillDiscoveryMode,
    SkillLifecycleConfig,
    SkillLifecycleMode,
    SkillToolset,
)

logger = logging.getLogger(__name__)


def build_skill_registry_toolset(
    project_id: str | None,
    location: str | None,
    local_skill_dirs: list[Path] | None = None,
    environment: BaseEnvironment | None = None,
    enable_remote_registry: bool = True,
) -> SkillToolset:
    """Build SkillToolset backed by GCPSkillRegistry with offline sandbox fallback."""
    local_skills = [load_skill_from_dir(d) for d in (local_skill_dirs or []) if d.exists()]
    registry = None

    if enable_remote_registry and project_id and location:
        try:
            from google.adk.integrations.skill_registry import GCPSkillRegistry

            registry = GCPSkillRegistry(project_id=project_id, location=location)
        except Exception as exc:
            # Isolated sandboxes without outbound Google API egress fall back to local skills
            logger.warning("GCPSkillRegistry unavailable (%s); falling back to local skills only.", exc)

    return SkillToolset(
        skills=local_skills,
        registry=registry,
        environment=environment,  # Do NOT also pass code_executor= (mutually exclusive!)
        discovery_mode=SkillDiscoveryMode.LAZY,
        lifecycle_config=SkillLifecycleConfig(
            default_mode=SkillLifecycleMode.BOUNDED,
            max_active_skills=5,
        ),
    )
```

### Step C3: Implement `build_agent_registry_integrations()` (`AgentRegistry` + Auth Providers)

`AgentRegistry` (ADK v1.26.0+) discovers registered A2A sub-agents, MCP servers, and endpoints using either short relative names (`"agents/AGENT_ID"`, `"mcpServers/SERVER_ID"`) or full resource names. Wire all **three verified authentication patterns** cleanly:

```python
import google.auth
import httpx
from google.auth.transport.requests import Request
from google.adk.auth.credential_manager import CredentialManager
from google.adk.integrations.agent_identity import GcpAuthProvider
from google.adk.integrations.agent_registry import AgentRegistry


class GoogleApiAuth(httpx.Auth):
    """OAuth 2.0 Bearer + X-Goog-User-Project auth for *.googleapis.com A2A endpoints."""

    def __init__(self, quota_project_id: str) -> None:
        self._quota_project_id = quota_project_id
        self._creds, _ = google.auth.default(
            scopes=["https://www.googleapis.com/auth/cloud-platform"]
        )

    def auth_flow(self, request: httpx.Request):
        if not self._creds.valid:
            self._creds.refresh(Request())
        request.headers["Authorization"] = f"Bearer {self._creds.token}"
        request.headers["X-Goog-User-Project"] = self._quota_project_id
        yield request


def build_agent_registry_integrations(
    project_id: str,
    location: str,
    mcp_server_name: str | None = None,
    remote_a2a_agent_name: str | None = None,
    continue_uri: str | None = None,
    header_provider=None,
) -> dict:
    """Register GcpAuthProvider and resolve governed MCP toolsets / remote A2A agents."""
    # Pattern 1: Register Auth Manager provider for 2LO, API Key & 3LO bindings.
    # On Agent Runtime, AgentRegistry automatically re-resolves bindings via
    # bindings:fetchAvailable and strips deployer credentials on pickle!
    CredentialManager.register_auth_provider(GcpAuthProvider())

    registry = AgentRegistry(
        project_id=project_id,
        location=location,
        # Pattern 2: Custom MCP headers ONLY (never applied to RemoteA2aAgent!)
        header_provider=header_provider,
    )

    result: dict = {"registry": registry, "mcp_toolset": None, "remote_agent": None}

    if mcp_server_name:
        # For 3LO user-delegated consent, pass continue_uri so clients handle adk_request_credential
        result["mcp_toolset"] = registry.get_mcp_toolset(
            mcp_server_name,
            continue_uri=continue_uri,
        )

    if remote_a2a_agent_name:
        # Pattern 3: httpx.Auth is required for RemoteA2aAgent without Auth Manager binding.
        # NOTE: For Cloud Run (*.run.app) or IAP A2A endpoints, attach an OIDC ID token
        # (google.oauth2.id_token.fetch_id_token(Request(), audience)), NOT an OAuth access token!
        httpx_client = httpx.AsyncClient(
            auth=GoogleApiAuth(project_id),
            timeout=httpx.Timeout(60.0),
        )
        result["remote_agent"] = registry.get_remote_a2a_agent(
            remote_a2a_agent_name,
            httpx_client=httpx_client,
            continue_uri=continue_uri,
        )

    return result
```

> [!WARNING]
> **Single-Parent Reuse Gotcha for `RemoteA2aAgent`:** An ADK `RemoteA2aAgent` instance can only have **one parent orchestrator** at a time. Fetch it once at startup and call **`remote_agent.clone()`** whenever attaching it to multiple `LlmAgent(sub_agents=[remote_agent.clone()])` instances!

Complete `# TODO(lab-5)` inside `_build_optional_skill_toolset()` in [`starter/coding_agent/agent.py`](../starter/coding_agent/agent.py) to wire your `build_skill_registry_toolset()` helper (when `ENABLE_SKILL_REGISTRY=true`) so the Coding Agent discovers `private-secure-code-review` (from Part B2 Agent Registry, or the local `secure-code-review` fallback) dynamically on demand.

---

## Part D: Semantic Governance Policies (NLC) & SPIFFE Agent Identity

### Step D1: How Semantic Governance Protects Skill & Tool Execution

Static IAM policies answer *"Can this agent call tool X at all?"* **Semantic Governance Policies** (Preview) answer *"Should this agent be allowed to invoke `load_skill`, `run_skill_script`, or `npm_install` **right now**, given the full conversation context?"*

Every intercepted LLM response containing a proposed tool call passes through **two runtime checks** (both must pass):
1. **Constraint Adherence:** Evaluates proposed tool calls against plain-English **Natural Language Constraints (NLCs)** (up to **5,000 characters**).
2. **User Intent Matching (ON by default):** Blocks injected tool calls that contradict the user's original intent *even if no explicit NLC covers the tool!* *(Only disable explicitly via `metadata: {"sgpUserIntentMatching": "DISABLED"}` on the `AuthzExtension`.)*

> [!CAUTION]
> **Five Mandatory Engineering Prerequisites & Constraints (`configure-semantic-governance`):**
> 1. **CRITICAL Non-Streaming Requirement:** The Semantic Governance Policy Engine **does NOT support streamed LLM responses** (`:streamGenerateContent`, `:streamRawPredict`, or `"stream": true`). A malicious tool call inside a streamed response might NOT be blocked — configure governed agents to invoke models **without streaming**!
> 2. **Immutable Agent Eligibility:** The Agent Runtime instance **MUST** be created with BOTH `identity_type = "AGENT_IDENTITY"` AND `agent_gateway_config` (verify `spec.effectiveIdentity` starts with `agents.global.`). You cannot patch Agent Identity onto an existing engine later.
> 3. **Gateway Placement Limit ([Set up Agent Gateway](https://docs.cloud.google.com/gemini-enterprise-agent-platform/govern/gateways/set-up-agent-gateway)):** Ingress (`CLIENT_TO_AGENT`) supports at most **1 `CONTENT_AUTHZ`** policy (you cannot combine Model Armor + Semantic Governance on ingress). Always place Semantic Governance + Model Armor + IAP on **Agent-to-Anywhere Egress (`AGENT_TO_ANYWHERE`)**, which supports up to **4** total authz policies (`REQUEST_AUTHZ` runs before `CONTENT_AUTHZ`).
> 4. **Mandatory gRPC-Exclusion CEL on `AuthzPolicy`:** Omitting `!request.headers['content-type'].startsWith('application/grpc')` intercepts Cloud Resource Manager gRPC traffic and **breaks agent startup**! Always use `contains()` (NOT `endsWith()`, since `request.path` may contain query strings):
>    ```yaml
>    when: "!request.headers['content-type'].startsWith('application/grpc') && (request.path.contains(':generateContent') || request.path.contains(':rawPredict') || request.path.contains('/v1/messages') || request.path.contains('/chat/completions'))"
>    ```
> 5. **Supported Regions (8) & Truncation Limits:** Available in `us-central1`, `us-east1`, `us-east4`, `us-west1`, `europe-southwest1`, `europe-west1`, `europe-west4`, `europe-west8`. Keep descriptions concise so the policy engine never truncates critical context: tool/MCP server description **<= 1,000 chars**, action/function description **<= 750 chars**, parameter description **<= 300 chars**. Always set `--agent-response-denial-message` (**<= 1,000 chars**) so proprietary NLC text is never leaked to end users!

### Step D2: Author Natural Language Constraints for Coding Agent Skills

*(If you have already provisioned an Egress Agent Gateway + `semanticGovernancePolicyEngine` + `AuthzExtension` / `AuthzPolicy` in a supported region, execute the commands below; otherwise review and stage them as part of your governance config.)*

```bash
export SGP_LOCATION="${GOOGLE_CLOUD_LOCATION}"
# Scope the regional aiplatform endpoint override to this shell session only so you do NOT
# break subsequent `gcloud ai` commands targeting `global` or another region!
# (If you ever use `gcloud config set api_endpoint_overrides/aiplatform`, always run
# `gcloud config unset api_endpoint_overrides/aiplatform` immediately afterward.)
export CLOUDSDK_API_ENDPOINT_OVERRIDES_AIPLATFORM="https://${SGP_LOCATION}-aiplatform.googleapis.com/"

# NOTE: Agent Registry canonical Resource Names use PROJECT_NUMBER (though gcloud accepts PROJECT_ID
# and normalizes it; using GOOGLE_CLOUD_PROJECT_NUMBER matches Layer 2 Resource Names explicitly).
export AGENT_RESOURCE_NAME="projects/${GOOGLE_CLOUD_PROJECT_NUMBER}/locations/${SGP_LOCATION}/agents/${AGENT_REGISTRY_AGENT_ID}"

# Policy 1 (Agent-scope — governs ADK load_skill in tainted sessions; verbatim pattern from govern-agent-skills):
gcloud beta ai semantic-governance-policies create block-tainted-outbound-skills \
  --location="${SGP_LOCATION}" \
  --project="${GOOGLE_CLOUD_PROJECT}" \
  --display-name="Block Outbound Skill Loads in Tainted Sessions" \
  --agent="${AGENT_RESOURCE_NAME}" \
  --natural-language-constraint="Do not load any skill that can send messages or write to external systems if the current chat history contains content fetched from inbound email, web pages, or uploaded documents." \
  --agent-response-denial-message="Blocked by enterprise skill governance policy: outbound skills cannot be loaded in sessions containing untrusted external content."

# Policy 2 (Tool-scope — supply-chain package allowlist for dependency installs):
gcloud beta ai semantic-governance-policies create approved-npm-packages-only \
  --location="${SGP_LOCATION}" \
  --project="${GOOGLE_CLOUD_PROJECT}" \
  --display-name="Approved Dependency Allowlist" \
  --agent="${AGENT_RESOURCE_NAME}" \
  --mcp-tools="mcp-server=${MCP_SERVER_RESOURCE_NAME},tools=npm_install" \
  --natural-language-constraint="Only allow the npm_install tool to run for packages on the approved list: react, express, lodash, or axios." \
  --agent-response-denial-message="Blocked by supply-chain policy: requested package is not on the approved allowlist."

# Policy 3 (Coding-agent skill script execution guardrail following NLC best practices):
gcloud beta ai semantic-governance-policies create guard-tainted-skill-scripts \
  --location="${SGP_LOCATION}" \
  --project="${GOOGLE_CLOUD_PROJECT}" \
  --display-name="Guard Skill Script Execution in Tainted Sessions" \
  --agent="${AGENT_RESOURCE_NAME}" \
  --natural-language-constraint="Disallow executing run_skill_script or installing third-party Python or Node packages whenever the current conversation contains untrusted external pull-request comments, web pages, or issue descriptions unless the user explicitly confirms the exact script path." \
  --agent-response-denial-message="Blocked by enterprise script execution policy: explicit developer confirmation is required in tainted sessions."

# Clean up the scoped override once policy authoring completes
unset CLOUDSDK_API_ENDPOINT_OVERRIDES_AIPLATFORM
```

#### Dry-Run Mode First & Cross-Control Governance Gotchas

Because Semantic Governance is LLM-powered and probabilistic, **always validate in dry-run mode first** via `PATCH` on the `AuthzExtension` `metadata`:

```bash
# GOTCHA: updateMask=metadata REPLACES the entire metadata map — include every key you want to keep!
curl -X PATCH \
  -H "Authorization: Bearer $(gcloud auth print-access-token)" \
  -H "Content-Type: application/json" \
  -d '{"metadata": {"sgpEnforcementMode": "DRY_RUN"}}' \
  "https://networkservices.googleapis.com/v1beta1/projects/${GOOGLE_CLOUD_PROJECT}/locations/${SGP_LOCATION}/authzExtensions/${SGP_AUTHZ_EXT_NAME}?updateMask=metadata"
```

Inspect dry-run verdicts and rationales in Cloud Logging:

```bash
gcloud logging read \
  'logName="projects/'"${GOOGLE_CLOUD_PROJECT}"'/logs/semantic-governance-policy" AND jsonPayload.verdict="DENY"' \
  --project="${GOOGLE_CLOUD_PROJECT}" \
  --limit=10
```

> [!CAUTION]
> **Critical Cross-Control Gotchas (IAM UAPs & Model Armor):**
> 1. **IAM UAP `iamEnforcementMode` API Validator Trap ([Configure IAM UAPs](https://docs.cloud.google.com/gemini-enterprise-agent-platform/govern/policies/configure-iam-policies-uap)):** To audit IAM UAPs, set `metadata.iamEnforcementMode: "DRY_RUN"` on the IAP `AuthzExtension`. To switch to active enforcement via `gcloud`, Terraform, or REST, you **MUST REMOVE the `iamEnforcementMode` key** from `metadata` — the IAP API validator **rejects** any explicit value other than `"DRY_RUN"` (including `"ENFORCED"`)!
> 2. **Never Blanket-Deny Unregistered Hosts in UAPs:** Blocking `destination.is_registered == false` breaks essential runtime telemetry endpoints such as `telemetry.mtls.googleapis.com`.
> 3. **Model Armor Token Limits & Service Agents ([Configure Model Armor](https://docs.cloud.google.com/gemini-enterprise-agent-platform/govern/configure-model-armor)):** Ingress (`CLIENT_TO_AGENT`) uses `gcp-sa-aiplatform-re` (`roles/modelarmor.calloutUser` + `roles/modelarmor.user`), while Egress (`AGENT_TO_ANYWHERE`) uses `gcp-sa-dep` (`roles/modelarmor.calloutUser` + `roles/modelarmor.user` + `roles/serviceusage.serviceUsageConsumer`). Unary/buffered sanitization is capped at **65,536 tokens** (PI/jailbreak/RAI/CSAM), **130,000 tokens** (SDP), and **4 MB** — payloads above those limits return `EXECUTION_SKIPPED` and **fail open** for that filter!

*(Optional Model Armor IAM reference snippet — review only; template creation is covered in [Configure Model Armor](https://docs.cloud.google.com/gemini-enterprise-agent-platform/govern/configure-model-armor):)*
```bash
# Required when attaching a Model Armor template to a CLIENT_TO_AGENT ingress gateway:
# gcloud projects add-iam-policy-binding "${GOOGLE_CLOUD_PROJECT}" \
#   --member="serviceAccount:service-${GOOGLE_CLOUD_PROJECT_NUMBER}@gcp-sa-aiplatform-re.iam.gserviceaccount.com" \
#   --role="roles/modelarmor.calloutUser"
# gcloud projects add-iam-policy-binding "${GOOGLE_CLOUD_PROJECT}" \
#   --member="serviceAccount:service-${GOOGLE_CLOUD_PROJECT_NUMBER}@gcp-sa-aiplatform-re.iam.gserviceaccount.com" \
#   --role="roles/modelarmor.user"
```

### Step D3: SPIFFE Agent Identity & 3-Identity Delegation Overview

When deployed with `identity_type = "AGENT_IDENTITY"`, your Coding Agent receives a cryptographically attested **SPIFFE X.509 identity** (auto-rotated **24-hour TTL**, supporting mTLS and DPoP) with **Context-Aware Access (RFC 8705 mTLS token binding)** enabled by default:

- **SPIFFE Workload ID:** `spiffe://agents.global.org-ORG_ID.system.id.goog/resources/aiplatform/projects/PROJECT_NUMBER/locations/REGION/reasoningEngines/AGENT_ID`
- **IAM Principal (for Allow/Deny/UAP policies — never use `spiffe://`!):** `principal://agents.global.org-ORG_ID.system.id.goog/resources/aiplatform/projects/PROJECT_NUMBER/locations/REGION/reasoningEngines/AGENT_ID` *(orgless projects use `agents.global.proj-PROJECT_NUMBER.system.id.goog`)*.
- **Least-Privilege Default Roles:** Agent Runtime auto-grants **`roles/aiplatform.agentContextEditor`** and **`roles/aiplatform.agentDefaultAccess`**. **Do NOT grant** broad `roles/aiplatform.user` or `roles/aiplatform.expressUser` roles to agent identities, and note that Legacy Bucket roles (`storage.legacyBucket*`) are unsupported.
- **Immutability Warning:** Deleting and recreating an Agent Runtime instance generates a **new resource ID and new SPIFFE principal** — prior IAM bindings do not transfer automatically.

#### Three-Identity Delegation Matrix

| Identity Layer | Credential Mechanism | Enforcement Boundary | Audit Log Attribution |
|---|---|---|---|
| **1. User Identity** | Human OAuth 2.0 / OIDC (Google or workforce IdP) | `CLIENT_TO_AGENT` ingress gateway checks caller authorization | Human user as caller |
| **2. Agent Identity** | SPIFFE X.509 cert (24h TTL, mTLS + DPoP), OIDC ID token, 2LO / API key from Auth Manager | `AGENT_TO_ANYWHERE` egress: IAM Allow/Deny/UAP, PAB, Context-Aware Access | Agent's SPIFFE principal |
| **3. Delegated Identity** | Scoped 3LO user token brokered by Agent Identity Auth Manager | `AGENT_TO_ANYWHERE` egress: **least-privilege intersection** of agent egress policy AND user permissions/consented scopes | **Dual attribution** (both agent SPIFFE ID and human user) |

---

## Lab 5 Verification Checkpoint

Run both the Skill Registry package validator and the automated Lab 5 verifier:

```bash
python3 scripts/package_registry_skill.py starter/skills_to_register/secure-code-review --dry-run
./scripts/verify_lab.sh 5
```

Expected pass criteria:
1. `starter/skills_to_register/secure-code-review/` passes every single Skill Registry ZIP and `SKILL.md` validation rule (`0 errors`).
2. Zero `# TODO(lab-5)` markers remain in `starter/coding_agent/tools/registry_loader.py` and `starter/coding_agent/agent.py`, and Python AST + import checks pass (with `google-adk[a2a,agent-identity]` installed).
3. `build_skill_registry_toolset()` cleanly falls back to local skills when remote registry access is disabled/offline, and `build_agent_registry_integrations()` wires `GcpAuthProvider` + `GoogleApiAuth` (`X-Goog-User-Project`).
4. *(Live GCP check)* `secure-code-review` is listed in Skill Registry alongside built-in `gcp-skill-registry` (on the second call) and/or registered as `private-secure-code-review` in Agent Registry with scan state `SUCCEEDED`.

Need a clean reference? Compare your code against [`solution/coding_agent/tools/registry_loader.py`](../solution/coding_agent/tools/registry_loader.py) and [`solution/coding_agent/agent.py`](../solution/coding_agent/agent.py).

---

## Canonical Reference Links

- **Vertex AI / Agent Platform Skill Registry Overview & Validation Rules:** https://docs.cloud.google.com/gemini-enterprise-agent-platform/build/skill-registry
  - Create & Manage Skills (Python, Node.js, REST): https://docs.cloud.google.com/gemini-enterprise-agent-platform/build/skill-registry/create-manage
- **Agent Registry (Agent Platform Hub):** https://docs.cloud.google.com/gemini-enterprise-agent-platform/govern/agent-registry
  - Agent Registry Overview & Setup: https://docs.cloud.google.com/agent-registry/overview
  - Skills Architecture: https://docs.cloud.google.com/agent-registry/skills-architecture
  - Register Standalone Skills: https://docs.cloud.google.com/agent-registry/register-skills
  - Manage Skills & Default Revisions: https://docs.cloud.google.com/agent-registry/manage-skills
  - Security Scanning & Custom Org Policy: https://docs.cloud.google.com/agent-registry/scan-skills
  - Agent Registry Quotas: https://docs.cloud.google.com/agent-registry/quotas
  - Authenticate ADK Toolsets & Auth Manager: https://docs.cloud.google.com/agent-registry/authenticate-toolsets
  - Resolve Endpoints & Orchestrators (`GoogleApiAuth` / OIDC / `.clone()`): https://docs.cloud.google.com/agent-registry/resolve-endpoints-and-build-orchestrators
- **Agent Gateway, Model Armor & IAM UAPs:**
  - Set up Agent Gateway: https://docs.cloud.google.com/gemini-enterprise-agent-platform/govern/gateways/set-up-agent-gateway
  - Configure Model Armor on Agent Gateway: https://docs.cloud.google.com/gemini-enterprise-agent-platform/govern/configure-model-armor
  - Configure IAM Unified Access Policies (UAPs): https://docs.cloud.google.com/gemini-enterprise-agent-platform/govern/policies/configure-iam-policies-uap
- **Semantic Governance Policies for Agent Skills:** https://docs.cloud.google.com/gemini-enterprise-agent-platform/govern/policies/govern-agent-skills
  - Configure Semantic Governance Policies: https://docs.cloud.google.com/gemini-enterprise-agent-platform/govern/policies/configure-semantic-governance
  - NLC Authoring Best Practices: https://docs.cloud.google.com/gemini-enterprise-agent-platform/govern/policies/best-practices
  - Dry-Run Reporting & IAM UAP Enforcement: https://docs.cloud.google.com/gemini-enterprise-agent-platform/govern/policies/dry-run-report
- **SPIFFE Agent Identity & Delegation:**
  - Agent Identity Overview: https://docs.cloud.google.com/gemini-enterprise-agent-platform/govern/agent-identity-overview
  - 3-Identity Delegation Architecture: https://docs.cloud.google.com/gemini-enterprise-agent-platform/govern/identity-delegation-architecture
- **ADK Integrations:**
  - ADK `SkillToolset`: https://adk.dev/skills/
  - ADK `GCPSkillRegistry`: https://adk.dev/integrations/skills-registry/
  - ADK `AgentRegistry`: https://adk.dev/integrations/agent-registry/
