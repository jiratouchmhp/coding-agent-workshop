# Agent Registry: Registration, Standalone Skills, Scanning, Bindings & Quotas

Production reference for **Google Cloud Agent Registry** (`agentregistry.googleapis.com/v1`), covering governance project topologies, the 4 architectural identifier layers, manual A2A/REST/MCP/Endpoint registration, standalone skills & revisions, automated LLM security scanning + Org Policy enforcement, search, Auth Manager bindings, and exact quotas/limits.

---

## 1. Governance Topologies, Setup & IAM Roles

### Governance Project Topologies
1. **Single-project governance:** Enable `agentregistry.googleapis.com` in the project. Supported Google Cloud workloads auto-register; custom/remote components register manually.
2. **Cross-project Management Boundary (`Preview`):** Configure a Resource Manager `Boundary` + `CapabilityConfig` (`agent-management`) on a folder/org. Resource Manager auto-enables `agentregistry.googleapis.com` on the **management project** and aggregates auto-discovered agents & MCP servers from up to **10,000** member projects.
   - **Critical Scoping Rule:** Manually registered `Service` resources, `Binding` resources, custom standalone `Skill` / `SkillRevision` / `Publisher` / `Finding` resources, and `AiApplication` resources are **scoped strictly to the project where created** — they are **NOT** rolled up from member projects into the management project! Create them directly in the management project for boundary-wide visibility.
3. **Cross-project without Management Boundary:** Host Agent Registry + Agent Gateway in a dedicated governance project and manually register remote workloads as `Service` resources.

### CLI & API Setup
```bash
gcloud components update
gcloud components install alpha    # Needed for preview commands
gcloud services enable agentregistry.googleapis.com --project=PROJECT_ID
# Also enable iap.googleapis.com if integrating with Agent Gateway
# For management boundaries, enable cloudresourcemanager.googleapis.com on the config project
```

> **Workforce Identity Federation Note:** Agent Registry and Agent Gateway have limited WIF console/CLI support — use a standard Google Account (Cloud Identity / Google Workspace) if console loading or auth errors occur.

### Predefined IAM Roles & Service Agent
| Role / Principal | Exact Scope |
|---|---|
| `roles/agentregistry.viewer` | List, view, download, and search agents, MCP servers, tools, standalone skills, revisions, publishers, endpoints, and bindings |
| `roles/agentregistry.user` | View all registry resources + create, update, delete **standalone skills, revisions, and scan settings** (cannot edit agents/MCP/endpoints) |
| `roles/agentregistry.editor` | View and edit agents, MCP servers, endpoints, standalone skills, and revisions |
| `roles/agentregistry.admin` | Full control: all editor actions + **bindings**, **resource-level skill IAM policies**, and **security `Finding` list/describe** |
| `service-PROJECT_NUMBER@gcp-sa-agentregistry.iam.gserviceaccount.com` | **GCS Import Service Agent** — requires `storage.objects.get` on buckets holding skill ZIPs. Trigger creation via `gcloud alpha services identity create --service=agentregistry.googleapis.com --project=PROJECT_ID` if no skill has been created yet. |

---

## 2. Four Architectural Identifier Layers (Do Not Confuse!)

| Layer | Primary Purpose | Governance Role | Exact Syntax |
|---|---|---|---|
| **1. Registry Identifiers (URNs)** | Immutable discovery, search, filtering, and `Binding` `--source-identifier` / `--target-identifier` | **NEVER pass URNs to IAM, IAP, Agent Gateway routes, or Semantic Governance!** | `urn:agent:projects-NUM:projects:NUM:locations:LOC:aiplatform:reasoningEngines:ID`<br>`urn:agent:googleapis.com:projects:NUM:locations:LOC:SERVICE:ID`<br>`urn:mcp:googleapis.com:projects:NUM:locations:global:SERVER_ID`<br>`urn:endpoint:projects-NUM:projects:NUM:locations:LOC:agentregistry:services:ID`<br>`urn:skill:projects-NUM:locations:LOC:private-SKILL_ID` *(private)*<br>`urn:skill:PUBLISHER_ID:NAMESPACE:SKILL_ID` *(Google-managed)* |
| **2. Resource Names** | Globally unique GCP resource paths | **Required** by IAM policies, IAP egress policies, Agent Gateway routes, and Semantic Governance `--agent` / `--mcp-tools` | `projects/PROJECT_NUMBER/locations/LOCATION/{agents\|mcpServers\|endpoints}/agentregistry-ID`<br>`projects/PROJECT_NUMBER/locations/LOCATION/skills/private-SKILL_ID[/revisions/REV_ID]`<br>Writable service: `projects/PROJECT_NUMBER/locations/LOCATION/services/SERVICE_ID` |
| **3. Agent Principals** | Caller authN, authZ, audit logs | **Required** by IAM Allow/Deny/UAP (**NEVER pass `spiffe://` — returns `INVALID_ARGUMENT`!**) | `principal://agents.global.org-ORG_ID.system.id.goog/resources/aiplatform/projects/NUM/locations/REGION/reasoningEngines/ID`<br>`principalSet://agents.global.org-ORG_ID.system.id.goog/attribute.platformContainer/aiplatform/projects/NUM`<br>`principalSet://agents.global.org-ORG_ID.system.id.goog/*` |
| **4. Runtime References** | Underlying compute/infrastructure URI | Topology graph matching & egress traffic matching | Output-only attribute `agentregistry.googleapis.com/system/RuntimeReference` (`uri`) |

---

## 3. Registering Agents, MCP Servers & Endpoints (`Service` vs Discovery Resources)

- **Automatic Registration:** Discovers Agent Runtime, Gemini Enterprise, Google Workspace, GKE/Cloud Run workloads with functional-type labels/flags, and Google remote MCP servers directly as read-only `Agent` or `McpServer` resources (no `Service` resource).
- **Manual Registration:** Creates a writable **`Service`** resource (`projects/.../services/SERVICE_ID`), which automatically generates a read-only discovery resource (`Agent`, `McpServer`, or `Endpoint`) exposed in `registryResource` (Terraform `.registry_resource`).
- **Mutually Exclusive Spec Flags (`gcloud agent-registry services create`):**

| Flag Pair (Mutually Exclusive) | Target Collection | Allowed `--*-spec-type` Values | Spec File Max |
|---|---|---|---|
| `--agent-spec-type` + `--agent-spec-content` | `agents` (`Agent`) | `a2a-agent-card`, `no-spec` | **10 KB** |
| `--mcp-server-spec-type` + `--mcp-server-spec-content` | `mcp-servers` (`McpServer`) | `tool-spec`, `no-spec` | **10 KB** |
| `--endpoint-spec-type` + `--endpoint-spec-content` | `endpoints` (`Endpoint`) | `no-spec` | — |

> **Collection Trap:** Passing `--agent-spec-type=no-spec` for a non-agent REST API registers it as an `Agent` instead of an `Endpoint`, causing type-specific governance rules to miss it. Use `endpoints` only for non-agent REST/SaaS APIs.

### Manual Registration Commands (`gcloud` & Terraform)
- `AGENT_NAME` / `service_id`: **4–63 chars**, lowercase letters, numbers, and hyphens.
- Custom self-hosted ADK agents must expose `/.well-known/agent-card.json` (A2A spec), save it locally, and register with `--agent-spec-type=a2a-agent-card`.

```bash
# 1. Register A2A-compliant agent (or custom ADK agent)
gcloud agent-registry services create my-support-agent \
  --project=PROJECT_ID --location=REGION \
  --display-name="Support Agent" \
  --agent-spec-type=a2a-agent-card \
  --agent-spec-content=agent-card.json

# 2. Register standard non-A2A REST agent (protocolBinding: http-json | grpc | jsonrpc)
gcloud agent-registry services create my-rest-agent \
  --project=PROJECT_ID --location=REGION \
  --display-name="Remote REST Agent" \
  --agent-spec-type=no-spec \
  --interfaces=url=https://api.example.com/v1/agents/1234,protocolBinding=http-json

# 3. Verify read-only Agent resource & inspect registryResource
gcloud agent-registry services describe my-support-agent --project=PROJECT_ID --location=REGION
gcloud agent-registry agents list --project=PROJECT_ID --location=REGION \
  --filter='protocols.type="A2A_AGENT"'
```

```terraform
resource "google_agent_registry_service" "a2a_agent" {
  project      = var.governance_project_id
  location     = var.region
  service_id   = "my-support-agent"
  display_name = "Support Agent"

  agent_spec {
    type = "A2A_AGENT_CARD"
    content = jsonencode({
      name               = "my-support-agent"
      description        = "Custom support agent registered via Terraform."
      version            = "1.0.0"
      capabilities       = {}
      defaultInputModes  = ["text/plain"]
      defaultOutputModes = ["text/plain"]
      supportedInterfaces = [{
        url             = "https://api.example.com/v1/agents/support"
        protocolBinding = "JSONRPC"   # HTTP_JSON | GRPC | JSONRPC
        protocolVersion = "1.0"
      }]
      skills = [{
        id          = "customer_lookup"
        name        = "customer_lookup"
        description = "Looks up customer info by email address."
        tags        = ["support", "customer"]
      }]
    })
  }
}

output "agent_resource_name" {
  value = google_agent_registry_service.a2a_agent.registry_resource
}

data "google_agent_registry_agent" "lookup" {
  location = var.region
  filter   = "displayName=\"Support Agent\""
}
```

---

## 4. Standalone Skills, Revisions & Lifecycle (`agentregistry.googleapis.com/v1`)

Standalone skills do **NOT** use `Service` resources — they are top-level `Skill` containers with immutable `SkillRevision` snapshots (`agentskills.io` spec), distinct from inline A2A `skills` arrays inside `agent-card.json`.

### Key Constraints & Automatic Behaviors
- **Payload Limits:** `SKILL.md` directly at ZIP root (valid YAML frontmatter); **<= 1 MB** compressed ZIP; **<= 10 MB** total uncompressed & **<= 1 MB** per file (when scanning is enabled — exceeding returns `INVALID_ARGUMENT` or scan state `UNSUPPORTED_FORMAT`); **<= 8** directory nesting levels.
- **Auto `private-` Prefix:** All user-registered skills are placed under the default `private` publisher (custom publishers cannot be created). Creating `SKILL_ID` produces published ID **`private-SKILL_ID`** (`projects/PROJECT_NUMBER/locations/LOCATION/skills/private-SKILL_ID`). Use **`private-SKILL_ID`** in every subsequent update, revision, IAM, or delete call!
- **Auto Resource-Level IAM:** Creation automatically grants `roles/agentregistry.admin` to the creator and (for org-backed projects) `roles/agentregistry.viewer` to the project's agent workload `principalSet`.
- **5 Lifecycle States (`targetState`):** `DRAFT` -> `ACTIVE` <-> `DISABLED` -> `DEPRECATED` -> `DECOMMISSIONED`.
  - **`DECOMMISSIONED` is terminal:** Can only transition from `DEPRECATED` and **cannot be reverted**.
  - Without `initialRevision`, creation only accepts `DRAFT` or `DISABLED`.
  - Deleting the `defaultRevision` clears the pointer and transitions an `ACTIVE` skill to `DISABLED` (update `defaultRevision` first to avoid downtime!).
  - **Download Preconditions:** Parent skill must be `ACTIVE` or `DEPRECATED`, revision must be `ACTIVE`, and (if `ENABLED_BLOCKING`) zero findings.

### Standalone Skill & Revision Commands (`gcloud alpha` in `--location=global` & REST)

> **Empirically Verified Regional Split & `gcloud 588.0.0 alpha` CLI Quirks:**
> 1. **Alpha-Only CLI:** Only **`gcloud alpha agent-registry skills`** exists (`gcloud agent-registry skills` returns `Invalid choice`). Run `gcloud components install alpha`.
> 2. **Bangkok A2A/MCP vs. `global` Standalone Skills:** Keep A2A/MCP discovery (`gcloud agent-registry agents list`, ADK `AgentRegistry`) in **Bangkok (`asia-southeast3`)** first, and run standalone skills in **`--location=global`** (`AGENT_REGISTRY_SKILLS_LOCATION=global`, because `--location=asia-southeast3` currently times out for `skills list`/`skills create`).
> 3. **2-Step Create (Omit `--payload` on `skills create`):** In `gcloud 588.0.0 alpha`, `skills create --payload=...` drops `--payload` from the JSON request (`400 source is required`), and 2-char revision IDs (`v1`, `v2`) fail format validation. Create the bare skill shell first, then upload `rev-1` / `rev-2` (or `v1-0-0`) via `revisions create --payload=...`.
> 4. **Wait for Async Scan Under `ENABLED_BLOCKING` & Always Set `--target-state=active`:** Immediately calling `skills update --default-revision=...` right after `revisions create` returns **`FAILED_PRECONDITION: cannot set default revision to a revision with pending scan results when scanning policy is ENABLED_BLOCKING`**. Poll `revisions describe <rev>` until `scanResult.scanState: SUCCEEDED` with 0 findings before promoting — or pass `--scanning-policy=enabled-nonblocking` on `skills create` for rapid workshop/CI demos. In addition, `skills create` defaults to `STATE_DRAFT`; while `search_skills` finds `DRAFT` skills, `GCPSkillRegistry.get_skill()` (`?alt=media`) fails with HTTP 400 `FAILED_PRECONDITION: skill container must be in ACTIVE or DEPRECATED state to download content` unless `--target-state=active` is set!
> 5. **Clear Default Revision -> Delete Revisions -> Delete Skill:** Before deleting revisions, clear the active default revision (`gcloud alpha agent-registry skills update private-SKILL_ID --clear-default-revision --target-state=disabled --location=global`) — deleting an active default revision can fail with `FAILED_PRECONDITION`, cascading into `cannot_delete_skill_with_revisions` when calling `skills delete` (no `--force` flag in CLI).

```bash
export AGENT_REGISTRY_SKILLS_LOCATION="${AGENT_REGISTRY_SKILLS_LOCATION:-global}"

# Step 1: Create bare skill shell WITHOUT --payload (Agent Registry auto-prefixes `private-`)
# Production default: `--scanning-policy=enabled-blocking` (or `--scanning-policy=enabled-nonblocking` for rapid workshop demos)
gcloud alpha agent-registry skills create workspace-docs-skill \
  --project=PROJECT_ID --location="${AGENT_REGISTRY_SKILLS_LOCATION}" \
  --display-name="Workspace Docs Skill" \
  --description="Audits and summarizes workspace docs." \
  --target-state=disabled \
  --scanning-policy=enabled-blocking

# Step 2: Upload initial revision `rev-1` from local ZIP (or --gcs-source-uri="gs://BUCKET/skill.zip")
# Avoid 2-char IDs like `v1`/`v2` (rejected by revision ID format validation).
gcloud alpha agent-registry skills revisions create rev-1 \
  --skill=private-workspace-docs-skill \
  --project=PROJECT_ID --location="${AGENT_REGISTRY_SKILLS_LOCATION}" \
  --payload="./workspace-docs-skill.zip"

# Subsequent ops MUST use private-workspace-docs-skill!
gcloud alpha agent-registry skills list --project=PROJECT_ID --location="${AGENT_REGISTRY_SKILLS_LOCATION}"
gcloud alpha agent-registry skills describe private-workspace-docs-skill \
  --project=PROJECT_ID --location="${AGENT_REGISTRY_SKILLS_LOCATION}"

# Upload new revision `rev-2`, verify scan completion, promote defaultRevision, and activate
gcloud alpha agent-registry skills revisions create rev-2 \
  --skill=private-workspace-docs-skill \
  --project=PROJECT_ID --location="${AGENT_REGISTRY_SKILLS_LOCATION}" \
  --payload="./workspace-docs-skill-v2.zip"

# REQUIRED under ENABLED_BLOCKING: wait until scanResult.scanState == SUCCEEDED with 0 findings
# (promoting immediately fails with FAILED_PRECONDITION: pending scan results)
gcloud alpha agent-registry skills revisions describe rev-2 \
  --skill=private-workspace-docs-skill \
  --project=PROJECT_ID --location="${AGENT_REGISTRY_SKILLS_LOCATION}"

# ALWAYS include --target-state=active so GCPSkillRegistry.get_skill() (?alt=media) succeeds (STATE_DRAFT returns 400 FAILED_PRECONDITION)
gcloud alpha agent-registry skills update private-workspace-docs-skill \
  --project=PROJECT_ID --location="${AGENT_REGISTRY_SKILLS_LOCATION}" \
  --default-revision="projects/PROJECT_ID/locations/${AGENT_REGISTRY_SKILLS_LOCATION}/skills/private-workspace-docs-skill/revisions/rev-2" \
  --target-state=active

# Download & extract revision locally (gcloud auto-extracts & deletes temp zip)
gcloud alpha agent-registry skills revisions download rev-2 \
  --skill=private-workspace-docs-skill \
  --project=PROJECT_ID --location="${AGENT_REGISTRY_SKILLS_LOCATION}" \
  --destination="./extracted" --allow-overwrite

# Share skill via resource-level IAM (requires roles/agentregistry.admin)
gcloud alpha agent-registry skills add-iam-policy-binding private-workspace-docs-skill \
  --project=PROJECT_ID --location="${AGENT_REGISTRY_SKILLS_LOCATION}" \
  --member="serviceAccount:agent-sa@PROJECT_ID.iam.gserviceaccount.com" \
  --role="roles/agentregistry.viewer"

# Teardown: 1) clear active default revision -> 2) delete every child revision -> 3) delete parent skill (no --force in CLI!)
gcloud alpha agent-registry skills update private-workspace-docs-skill \
  --clear-default-revision --target-state=disabled \
  --project=PROJECT_ID --location="${AGENT_REGISTRY_SKILLS_LOCATION}"
gcloud alpha agent-registry skills revisions delete rev-2 \
  --skill=private-workspace-docs-skill \
  --project=PROJECT_ID --location="${AGENT_REGISTRY_SKILLS_LOCATION}" --quiet
gcloud alpha agent-registry skills revisions delete rev-1 \
  --skill=private-workspace-docs-skill \
  --project=PROJECT_ID --location="${AGENT_REGISTRY_SKILLS_LOCATION}" --quiet
gcloud alpha agent-registry skills delete private-workspace-docs-skill \
  --project=PROJECT_ID --location="${AGENT_REGISTRY_SKILLS_LOCATION}" --quiet
```

**REST Essentials (`v1`):**
- Create with local ZIP: `POST https://agentregistry.googleapis.com/v1/projects/PROJECT_ID/locations/LOCATION/skills?skillId=SKILL_ID` with `{"displayName": "...", "description": "...", "type": "SIMPLE", "targetState": "TARGET_STATE_DISABLED", "initialRevision": {"archiveUploadSource": {"archiveContent": "<base64>"}}}` (or `"gcsSource": {"uri": "gs://..."}`).
- Download revision payload (**MUST pass `-L`** to follow 302 GCS signed URL redirect!):
  `curl -L -H "Authorization: Bearer $(gcloud auth print-access-token)" -o skill.zip "https://agentregistry.googleapis.com/v1/projects/PROJECT_ID/locations/LOCATION/skills/private-SKILL_ID/revisions/REV_ID?alt=media"`
- Delete skill with revisions: `DELETE .../skills/private-SKILL_ID?force=true`.

---

## 5. Automated Security Scanning, Findings Triage & Custom Org Policy

### Scanning Policies (`scanningConfig.policy`)
| Operation | `ENABLED_BLOCKING` *(Default)* | `ENABLED_NONBLOCKING` *(Audit)* | `DISABLED` |
|---|---|---|---|
| Create w/ `initialRevision` + `TARGET_STATE_ACTIVE` | Starts in `STATE_DRAFT`; auto-promotes to `STATE_ACTIVE` **only** if scan returns 0 findings while still `STATE_DRAFT` pointing to `initialRevision` | Transitions to `STATE_ACTIVE` immediately after LRO | Transitions to `STATE_ACTIVE` immediately after LRO |
| Download revision payload | Fails with `FAILED_PRECONDITION` if findings exist | Allowed with high-visibility warning | Allowed |
| Promote `defaultRevision` | Fails with `FAILED_PRECONDITION` if findings exist OR scan pending | Allowed with warning | Allowed |
| Switch policy to `ENABLED_BLOCKING` | Fails with `FAILED_PRECONDITION` if current `defaultRevision` has findings, pending, failed, or incomplete scan | Permitted (unless blocked by Org Policy) | Permitted (unless blocked by Org Policy) |

- **Non-Retroactive:** Changing `scanningConfig.policy` applies **only to future revisions** — upload a new revision to scan previously uploaded content.
- **LLM Probabilistic Disclaimer:** Scanning uses LLMs to detect data exfiltration, exposed secrets, and prompt injection; verify reported file paths and line numbers before remediating.
- **Scan States (`scanResult.scanState`):** `SUCCEEDED`, `RUNNING`, `DISABLED`, `UNSUPPORTED_FORMAT`, `FAILED`.

### Inspecting Scans & Triaging `Finding` Resources (Requires `roles/agentregistry.admin`)
```bash
# Check revision scan state (`--location=global` for standalone skills)
gcloud alpha agent-registry skills revisions describe rev-1 \
  --skill=private-my-skill --project=PROJECT_ID --location=global

# List findings for a revision
gcloud alpha agent-registry findings list \
  --project=PROJECT_ID --location=global \
  --filter='resource="projects/PROJECT_ID/locations/global/skills/private-my-skill/revisions/rev-1"'

# Inspect severity (SEVERITY_{CRITICAL,HIGH,MEDIUM,LOW}), findingClass (VULNERABILITY|SECRET),
# files[{path, lineNumber (0 = whole file)}], and detail
gcloud alpha agent-registry findings describe FINDING_ID \
  --project=PROJECT_ID --location=global --format=json
```

### Custom Organization Policy Constraint (No Managed Constraint Exists)
```yaml
# skills-scan-constraint.yaml
name: organizations/ORGANIZATION_ID/customConstraints/custom.skillsScanningEnforcement
resourceTypes:
- agentregistry.googleapis.com/Skill
methodTypes:
- CREATE
- UPDATE
condition: resource.scanningConfig.policy == "DISABLED"
actionType: DENY
displayName: Prevent Disabling Skills Scanning
description: Prevents creating or updating skills with scanning disabled.
```
*(To require strict blocking mode everywhere, use `condition: resource.scanningConfig.policy == "ENABLED_BLOCKING"` with `actionType: ALLOW`.)*

```yaml
# skills-scan-policy.yaml (with optional Resource Manager tag exemption)
name: organizations/ORGANIZATION_ID/policies/custom.skillsScanningEnforcement
spec:
  rules:
  - enforce: true
    condition:
      expression: "!resource.matchTag('ORGANIZATION_ID/exempt-scanning-enforcement', 'true')"
      title: "Enforce Scanning"
  - enforce: false
    condition:
      expression: "resource.matchTag('ORGANIZATION_ID/exempt-scanning-enforcement', 'true')"
      title: "Exempt Testing Projects"
```
```bash
gcloud org-policies set-custom-constraint skills-scan-constraint.yaml
gcloud org-policies set-policy skills-scan-policy.yaml
gcloud org-policies describe custom.skillsScanningEnforcement --project=PROJECT_ID --effective
```
> **Org Policy Limitations:** Custom constraints evaluate `Skill.scanningConfig.policy` only — they **cannot** inspect `SkillRevision` payloads, file sizes, or findings, and are not retroactive (existing `DISABLED` skills fail on their next `UPDATE` unless updated to a compliant policy).

---

## 6. Search, Discovery & Bindings

### Search Commands (`agents`, `mcp-servers`, `skills`)
- **IAM Filtering:** Skill search automatically returns only skills where caller has `agentregistry.skills.get`.
- **Endpoints:** Do **NOT** support `:search` — use `gcloud agent-registry endpoints list --filter="..."`.

```bash
# Keyword + inline A2A skill search & source-prefix search
gcloud agent-registry agents search --project=PROJECT_ID --location=REGION \
  --search-string='skills.tags:incident OR displayName:Support_*'

gcloud agent-registry agents search --project=PROJECT_ID --location=REGION \
  --search-string='agentId:"urn:agent:googleapis.com:*"'   # or urn:agent:projects-NUM:*

gcloud agent-registry mcp-servers search --project=PROJECT_ID --location=REGION \
  --search-string="database"

# Standalone skill keyword search (`gcloud alpha`, `--location=global`; fields: displayName, description, name,
# skillId, publisher, frontmatter.*, plus filter-only: state, targetState, defaultRevisionFindingCount)
gcloud alpha agent-registry skills search --project=PROJECT_ID --location=global \
  --query="displayName:cloud-* AND description:database" --search-type=keyword

# Google-managed FIRST_PARTY skills (from github.com/google/skills)
gcloud alpha agent-registry skills search --project=PROJECT_ID --location=global \
  --query="publisher:cloud.google.com" --search-type=keyword

# Standalone skill semantic search (indexes full SKILL.md, scripts & assets of defaultRevision)
gcloud alpha agent-registry skills search --project=PROJECT_ID --location=global \
  --query="manage and configure relational databases" --search-type=semantic
```

### Resource & Auth Provider Bindings (Requires `roles/agentregistry.admin`)
Bindings connect a source agent URN to a target resource URN (and optionally an Agent Identity Auth Manager `authProvider` for 2LO/API-key/3LO credentials so code never hardcodes auth config):

```bash
# Resource + 3LO Auth Manager binding (use PROJECT_ID in --auth-provider-binding!)
gcloud agent-registry bindings create my-mcp-binding \
  --project=PROJECT_ID --location=REGION \
  --display-name="Orchestrator to MCP Binding" \
  --source-identifier="urn:agent:projects-NUM:projects:NUM:locations:REGION:aiplatform:reasoningEngines:ID" \
  --target-identifier="urn:mcp:projects-NUM:projects:NUM:locations:REGION:agentregistry:services:SERVER_ID" \
  --auth-provider-binding="projects/PROJECT_ID/locations/REGION/authProviders/AUTH_PROVIDER_ID" \
  --auth-provider-binding-scopes="https://www.googleapis.com/auth/cloud-platform" \
  --auth-provider-binding-continue-uri="https://app.example.com/continue"
```

```terraform
resource "google_agent_registry_binding" "auth_binding" {
  project      = var.governance_project_id
  location     = var.region
  binding_id   = "my-mcp-binding"
  display_name = "Orchestrator to MCP Binding"

  source { identifier = var.source_agent_urn }
  target { identifier = var.target_mcp_urn }

  auth_provider_binding {
    auth_provider = "projects/${var.governance_project_id}/locations/${var.region}/authProviders/${var.auth_provider_id}"
    scopes        = ["https://www.googleapis.com/auth/cloud-platform"]
    continue_uri  = "https://app.example.com/continue"
  }
}
```

---

## 7. Quotas, System Limits & Verification

### Quotas & System Limits (`agent-registry/quotas`)
| Category | Metric / Limit | Default / Hard Limit |
|---|---|---|
| **Allocation Quotas** | Agents / MCP servers / Endpoints / Bindings / A2A skills per project | **100** each (global & per region) |
| **Allocation Quotas** | Standalone skills per project per location | **100** |
| **Allocation Quotas** | Skill revisions per project per location (shared across all skills in location) | **500** |
| **Rate Quotas** | Aggregate API requests (global + regional) | **12,000/min** (200 QPS) |
| **Rate Quotas** | Global OR per-region API requests | **1,200/min** (20 QPS) |
| **Rate Quotas** | Skill & revision CUD (`create`/`update`/`delete`) | **120/min** (2 QPS) per location |
| **Rate Quotas** | Skill & revision read (`get`/`list`/`search`) | **1,200/min** (20 QPS) per location |
| **System Limits** | Display name / Description max length | **63 chars** (services/bindings), **128 chars** (skills) / **2,048 chars** |
| **System Limits** | Agent or MCP spec content size | **10 KB** |
| **System Limits** | Compressed skill ZIP / Scanned uncompressed total / Per-file | **1 MB** / **10 MB** / **1 MB** |
| **System Limits** | A2A skills or tools per service / Pagination / Boundary member projects | **100** / **100** / **10,000** |

> **3-Layer Runtime Quota Rule:** Agent Registry rate quotas apply **only** to discovery/management calls. Once resolved, live A2A/MCP traffic consumes target runtime quotas and downstream per-service API/LLM token quotas (govern bursty loops with Secure Web Proxy / Agent Gateway token management policies).

### Concrete Verification Steps
1. Register a standalone skill in `--location=global` via the 2-step flow: bare `gcloud alpha agent-registry skills create ... --target-state=disabled --scanning-policy=enabled-blocking` (no `--payload`) followed by `gcloud alpha agent-registry skills revisions create rev-1 --skill=private-SKILL_ID --location=global --payload=<zip>`, and verify `private-SKILL_ID` appears in `gcloud alpha agent-registry skills list --location=global`.
2. Poll `gcloud alpha agent-registry skills revisions describe rev-1 --skill=private-SKILL_ID --location=global` until `scanResult.scanState: SUCCEEDED` and `findings` is empty.
3. Promote to `--target-state=ACTIVE` with `--default-revision=.../revisions/rev-1`, verify `gcloud alpha agent-registry skills search --location=global --search-type=semantic` returns it, test `gcloud alpha agent-registry skills revisions download rev-1 ...` cleanly extracts `SKILL.md`, and on teardown delete child revisions (`revisions delete`) **before** `skills delete`.
4. For manual A2A/MCP registrations (in Bangkok `asia-southeast3` default), confirm `services describe` populates `registryResource` and `agents list` / `mcp-servers list` reflects the read-only resource.
