# 00 — Workshop Overview: Building a Production Enterprise Coding Agent on Gemini Enterprise Agent Platform

> **Estimated Reading & Setup Time:** 20 minutes (Full-Day) / 10 minutes (Half-Day Fast-Track) — complete the GCP prerequisites and pre-flight checks before starting [Lab 1](01-LAB-SETUP-AND-BUILD-ADK.md).

---

## Executive Narrative: Why an Enterprise Coding Agent?

Autonomous coding agents are among the highest-value—and highest-risk—AI workloads an enterprise can deploy. Unlike read-only Q&A chatbots, a real coding agent must:

1. **Read, edit, and write multi-file repositories** deterministically.
2. **Execute arbitrary, LLM-generated shell commands and test suites** (`pytest`, `ruff`, `bandit`, build tools) without compromising the host network, cloud credentials, or neighboring tenants.
3. **Retain multi-turn task state and long-term engineering conventions** across sessions while defending against memory poisoning and prompt injection.
4. **Consume approved organizational skills and internal tools dynamically** from centralized registries under enforceable natural-language and identity policies.
5. **Prove and continuously improve engineering quality** through automated traces, offline/simulated/online evaluations, quality alerting, and closed-loop prompt optimization.

Solving all five requirements with ad-hoc containers and scripts creates brittle security boundaries and months of platform toil. **Google Cloud's Gemini Enterprise Agent Platform** provides the integrated control plane and managed runtime primitives—paired with **Google ADK (Agent Development Kit)** and **`google/agents-cli`**—to take a coding agent from laptop prototype to production governance across four pillars: **Build -> Scale -> Govern -> Optimize**.

---

## End-to-End Reference Architecture

```mermaid
flowchart LR
    subgraph BUILD["1. BUILD PILLAR (Lab 1)"]
        DEV["Developer IDE + Antigravity<br/>.agents/skills/* + agents-cli"]
        ADK["ADK 2.0 Coding Agent (Python)<br/>Simple -> Collaborative -> Graph -> Dynamic<br/>+ EnvironmentToolset & services.yaml/py"]
        LOCAL["LocalEnvironment<br/>Lab 1 Laptop Workspace"]
        DEV --> ADK
        ADK --> LOCAL
    end

    subgraph STATE_SBX["2. ISOLATE & STATE (Labs 2-3)"]
        SA_INST["Standalone Agent Platform Instance<br/>client.runtimes.create() (Labs 2-3)"]
        SBX["Managed BYOC / Shell / Code Sandbox<br/>gVisor Container - Zero Ambient Creds (Lab 2)"]
        SESS["Managed Sessions (Lab 3)<br/>VertexAiSessionService"]
        MEM["Memory Bank (Lab 3)<br/>VertexAiMemoryBankService"]
        FB["Feedback & Telemetry (Lab 3)<br/>OTel, Parent Sandbox Logs, Thumbs"]
        VPC["Customer VPC (Optional PSC-I)<br/>Cloud NGFW / SWP / DNS Peering"]

        SA_INST --> SBX
        SA_INST --> SESS
        SA_INST --> MEM
        SBX -. "PSC-I Egress (Optional)" .-> VPC
    end

    subgraph REG["3. EXTEND WITH REGISTRIES (Lab 4)"]
        SKREG["Skill Registry (v1beta1)<br/>16-Check Validated ZIP Packages"]
        AGREG["Agent Registry Discovery<br/>GCPSkillRegistry + AgentRegistry ADK Clients"]
        SKREG --> ADK
        AGREG --> ADK
    end

    subgraph DEPLOY["4. DEPLOY ONCE TO RUNTIME (Lab 5)"]
        AR_IMG["Artifact Registry<br/>Complete Agent Image + BYOC Sandbox Image"]
        TF["Terraform IaC / agents-cli deploy<br/>google_vertex_ai_reasoning_engine + Custom SA"]
        RT["Agent Runtime (ReasoningEngine)<br/>Trusted Orchestration Plane (Labs 1-4 Complete)"]

        ADK -->|"Build & Push ONCE"| AR_IMG
        TF --> RT
        AR_IMG -- "gcp-sa-aiplatform-re" --> RT
        AR_IMG -- "gcp-sa-vertex-sandbox" --> SBX
        RT -- "execute_bash / /exec / CodeExec" --> SBX
        RT <-->|"Decoupled REASONING_ENGINE_NAME"| SESS
        RT <-->|"roles/aiplatform.memoryUser"| MEM
        RT --> FB
    end

    subgraph OPTIMIZE["5. OPTIMIZE PILLAR (Lab 6)"]
        OTEL["GenAI OTel Traces, Cloud Logging<br/>& Cloud Monitoring (PromQL)"]
        EVAL["Managed Evaluation Service<br/>Offline | Simulated | Online Monitors"]
        ALERTS["Cloud Monitoring Quality Alerts<br/>& Failure Clustering"]
        OPT["Dual-Track Optimize Flywheel<br/>Prompt Canary + Zero-Redeploy Skill Update"]

        RT --> OTEL
        FB --> EVAL
        OTEL --> EVAL
        EVAL --> ALERTS
        EVAL --> OPT
        OPT -. "Track A: Prompt + Canary Revision" .-> RT
        OPT -. "Track B: client.skills.update / v2 Rev (Zero Redeploy)" .-> SKREG
    end

    subgraph HARDEN["6. OPTIONAL HARDENING (Lab 7 - Skippable)"]
        SCAN["Agent Registry (v1) ENABLED_BLOCKING<br/>LLM Scanning + Custom Org Policy"]
        SGP["Semantic Governance (NLC) & Model Armor<br/>Egress Agent Gateway"]
        SPIFFE["SPIFFE AGENT_IDENTITY Upgrade<br/>3-Identity Delegation + IAM Conditions + CMEK/VPC-SC"]
        SECOPS["WORM Audit Bucket + SIEM Pub/Sub<br/>+ 3-Layer Agent Anomaly Detection -> SCC"]

        SCAN -.-> AGREG
        SGP -. "Intercepts load_skill / scripts" .-> RT
        SPIFFE -. "Immutable Runtime Upgrade" .-> RT
        RT -.-> SECOPS
    end
```

### Architectural Separation of Concerns

One design principle anchors the entire workshop: **never run untrusted LLM-generated commands inside your trusted Agent Runtime.**

- **Agent Runtime (`ReasoningEngine`)** is the **trusted orchestration plane**. It holds the agent's identity (SPIFFE `AGENT_IDENTITY` or dedicated custom service account), invokes Gemini models, reads/writes Managed Sessions and Memory Bank, calls authenticated Google Cloud APIs, and records structured logs and OpenTelemetry traces.
- **Managed Sandboxes (`SandboxEnvironment`)** are the **untrusted execution plane**. Each sandbox runs in a Google-managed tenant project inside a **gVisor-isolated container** under an unprivileged user (`appuser` / tenant identity `sandbox-untrusted`) with **zero IAM roles**, **no Application Default Credentials (ADC)**, and **no access to the metadata server (`169.254.169.254:80`)**.

### ADK Agent Architecture Progression (`Build Pillar` — Lab 1)

Real enterprise coding workloads rarely stay a single monolithic prompt forever. Before scaling execution to remote BYOC Sandboxes in Lab 2, **[Lab 1](01-LAB-SETUP-AND-BUILD-ADK.md)** establishes the full **Google ADK 2.0** architectural progression — controlled via a single `AGENT_ARCHITECTURE` environment variable (`simple` default so Labs 2–8 remain 100% backward compatible):

1. **Simple Agent (`AGENT_ARCHITECTURE=simple` — Part A):** A single `LlmAgent` wired with `EnvironmentToolset(LocalEnvironment)`. Fast to iterate, ideal until prompt complexity, context limits, code modularity, or deterministic test/lint gates justify splitting responsibilities. *(We also contrast `LlmAgent` with ADK Python v2.4.0 Preview [`ManagedAgent`](https://adk.dev/agents/managed-agents/) and introduce ADK 2.0+ [`services.yaml` / `services.py`](https://adk.dev/agents/service-registration/) custom backend registration.)*
2. **Collaborative Agent Team (`AGENT_ARCHITECTURE=collaborative` — Part B):** Coordinator `LlmAgent` delegating across isolated session branches to mode-scoped subagents (`mode="single_turn"` for `code_implementer`/`code_reviewer` and leaf-only `mode="task"` for `requirements_clarifier`), governed by `GlobalInstructionPlugin`.
3. **Declarative Graph Workflow (`AGENT_ARCHITECTURE=graph` — Part B):** Deterministic ADK 2.0 `Workflow(edges=...)` combining LLM reasoning with parallel `@node` `pytest`/`ruff` checks (`RetryConfig` + per-attempt timeout), `JoinNode` fan-in, bounded `Event(route=...)` fix loops, and `RequestInput` HITL pauses.
4. **Dynamic Checkpointed Workflow (`AGENT_ARCHITECTURE=dynamic` — Part B):** Programmatic `@node(rerun_on_resume=True)` async Python orchestration (`for` loops, `asyncio.gather(..., use_sub_branch=True)`, and automatic checkpoint replay across HITL pauses).

Because all four architectures share the **exact same `EnvironmentToolset`**, moving from `LocalEnvironment` (Lab 1) to `AgentPlatformSandboxEnvironment` (Lab 2), wiring Sessions/Memory (Lab 3) and Registries (Lab 4), and deploying **once** to Agent Runtime (Lab 5) requires **zero changes** to your workflow graph or container contract!

---

## Workshop Schedules: Full-Day vs. Half-Day Fast-Track

This workshop follows a **Build → Isolate → Persist → Extend → Deploy ONCE → Optimize → (Optional Harden)** flow: Labs 1–4 iteratively build and test the complete Coding Agent against managed cloud primitives (using a lightweight standalone Agent Platform instance created in Lab 2) so **[Lab 5](05-LAB-DEPLOY-RUNTIME-TERRAFORM.md)** builds and deploys the **100% feature-complete** container **once**. **[Lab 7](07-LAB-OPTIONAL-SECURITY-AND-GOVERNANCE.md)** is a self-contained **Optional / Skippable** enterprise security & governance module—skipping it leaves Labs 1–6 100% green (`make verify-lab LAB=all`).

| Module | Topic & Hands-On Deliverable | Full-Day (7h 00m) | Half-Day Fast-Track (3h 30m) |
|---|---|---:|---:|
| **Lab 0** | Overview, GCP APIs, Service Agents, Pre-Flight Quota Check (`00-WORKSHOP-OVERVIEW.md`) | 20 min | 10 min |
| **[Lab 1](01-LAB-SETUP-AND-BUILD-ADK.md)** | **Build:** Part A — `agents-cli`, Antigravity skills, ADK Architecture Spectrum, Simple `LlmAgent` + `EnvironmentToolset`; Part B — Collaborative, Graph & Dynamic Workflows + Service Registration | 60 min *(30m Part A + 30m Part B)* | 35 min *(30m Part A hands-on + 5m Part B walkthrough)* |
| **[Lab 2](02-LAB-CUSTOM-SANDBOX-BYOC.md)** | **Scale (Sandboxes):** Standalone Agent Platform instance (`client.runtimes.create()`), Non-root BYOC Dockerfile, Template/Sandbox/Snapshot Lifecycle, Shell vs. BYOC vs. Code Exec, `AgentPlatformSandboxEnvironment`, Egress & Security | 60 min | 40 min *(use pre-pushed image or `solution/` checkpoint if tight)* |
| *Break* | *Morning Coffee / Stretch Break* | *10 min* | *10 min* |
| **[Lab 3](03-LAB-SESSIONS-MEMORY-FEEDBACK.md)** | **Scale (State & Telemetry):** Reuses Lab 2 standalone instance for Managed Sessions, Memory Bank (topics/TTL/retrieval), Feedback Service, OTel Tracing, Logging & PromQL Monitoring | 40 min | 15 min *(instructor live demo + code walkthrough)* |
| **[Lab 4](04-LAB-SKILLS-AND-AGENT-REGISTRY.md)** | **Extend (Registries):** Skill Registry 16-check ZIP/`SKILL.md` packaging, publish to Vertex AI Skill Registry, wire `GCPSkillRegistry` + `SkillToolset` & `AgentRegistry` discovery before deployment | 40 min | 30 min *(Parts A, B & C hands-on)* |
| *Break* | *Lunch Break (Full-Day only)* | *40 min* | *—* |
| **[Lab 5](05-LAB-DEPLOY-RUNTIME-TERRAFORM.md)** | **Scale (Deploy ONCE via Runtime & Terraform):** Build & push complete Labs 1–4 Coding Agent image **once**, `agents-cli deploy --dry-run` + Terraform `google_vertex_ai_reasoning_engine` (Custom SA + `roles/aiplatform.memoryUser` + dual service-agent `depends_on` + unified vs. decoupled `REASONING_ENGINE_NAME`), Revisions & Emergency Stop | 45 min | 30 min |
| **[Lab 6](06-LAB-OPTIMIZE-EVAL-AND-ALERTS.md)** | **Optimize:** GenAI Observability, Split Offline/Simulated/Online Eval, Failure Clustering, Quality Alerts (`monitoring_v3`), Prompt Optimization Flywheel | 40 min | 15 min *(instructor live demo + walkthrough)* |
| **[Lab 7](07-LAB-OPTIONAL-SECURITY-AND-GOVERNANCE.md)** *(Optional / Skippable)* | **Govern & SecOps Hardening (Optional):** Agent Registry `ENABLED_BLOCKING` scanning & lifecycle, Semantic Governance (NLC) & Model Armor, SPIFFE `AGENT_IDENTITY` + Agent Gateway Terraform upgrade path, Multi-Tenant IAM Conditions, Memory Poisoning audit, CMEK/VPC-SC, WORM Audit + SIEM + Agent Anomaly Detection → SCC | 35 min *(optional — skip to finish at 6h 25m)* | *— (Skipped — self-paced)* |
| **[Lab 8](08-ARCHITECTURE-AGENT-RUNTIME-VS-GKE.md)** | **Architecture Decision:** Agent Runtime + Managed Sandbox vs. Self-Hosted GKE + `kubernetes-sigs/agent-sandbox` + Agent Substrate (14-Dimension Matrix) | 30 min | 25 min *(executive + engineering Q&A)* |
| **Total** | | **420 min (7h 00m)** *(370m labs + 50m breaks; 385m / 6h 25m skipping Optional Lab 7)* | **210 min (3h 30m)** *(200m labs/demos + 10m break; skips Optional Lab 7 cleanly)* |

> **Fast-Forward Rule:** Every lab in `starter/` has a 1-to-1 mirror in `solution/`. If a build or Terraform apply runs behind schedule, copy the target module from `solution/` into `starter/` and continue without losing momentum. See [FACILITATOR-GUIDE.md](FACILITATOR-GUIDE.md) for exact checkpoint cutoffs.

---

## GCP Prerequisites & Environment Setup

> [!TIP]
> **No Local Docker Required!** Every lab in this workshop is designed for **100% zero-Docker attendee execution** (`docker` CLI is strictly optional):
> - **Standalone `uv` without `python3-venv` or Docker:** Install `uv` with `curl -LsSf https://astral.sh/uv/install.sh | sh` — works out of the box even on fresh Debian/Linux workstations or cloud dev environments without `python3-venv` or `docker`.
> - **Lab 2 (Sandboxes):** Verify your BYOC runner locally via pure Python (`make test-sandbox-local`), build and push remotely via Cloud Build in Bangkok (`make push-sandbox` → `gcloud builds submit --region=asia-southeast3`), or use the zero-build `SANDBOX_MODE=shell` fast-track.
> - **Lab 5 (Agent Runtime):** Smoke-test `main.py` locally via pure Python (`make test-agent-local`), then deploy via (1) `make push-agent` (Cloud Build `--region=asia-southeast3`) + Terraform `container_spec`, (2) `make pack-agent-source` + Terraform `source_code_spec` + empty `image_spec {}` (zero Docker AND zero Artifact Registry push!), or (3) `agents-cli deploy`.

### Express Mode vs. Standard GCP Project (Important!)

Gemini Enterprise Agent Platform offers an **Express Mode** free tier (`GOOGLE_GENAI_API_KEY` + `GOOGLE_GENAI_USE_ENTERPRISE=TRUE`), as well as AI Studio (`GEMINI_API_KEY`). **Do NOT use Express Mode for Labs 2–8.**

| Capability / Quota | Express Mode (Free Tier) | Standard Billing-Enabled GCP Project |
|---|---|---|
| Agent Platform resources (max) | **10** | **100** per region (and non-regional) |
| Write requests / min | **10/min** | **10/min** (Reasoning Engine) / **500/min** (Sandboxes) |
| Query / StreamQuery requests / min | **10/min** | **90/min** (adjustable) |
| Concurrent `BidiStreamQuery` / min | **1/min** | **10/min** |
| Session writes / event appends per min | **10/min** / **30/min** | **100/min** / **300/min** |
| Memory Bank writes / reads per min | **10/min** / **10/min** | **100/min** / **300/min** |
| Artifact Registry BYOC Sandboxes, Terraform IAM, PSC-I/NGFW, Cloud Monitoring Alerts | **Not supported** | **Fully supported** |

- **Lab 1 only:** You may use AI Studio (`GEMINI_API_KEY`) or Express Mode strictly for local ADK prototyping if your GCP project is still provisioning.
- **Labs 2–8:** Require a **Standard GCP project with billing enabled** and Application Default Credentials (`gcloud auth application-default login`).

### Regional Availability Matrix (Bangkok Primary + Singapore Secondary)

This workshop standardizes on **Bangkok (`asia-southeast3`) as the Primary Region** paired with **Singapore (`asia-southeast1`) as the Secondary Agent Platform Region**, plus two explicit service-mandated overrides (`us-central1` and `global`). Every placement below is source-verified against Google Cloud's live regional availability tables:

| Region / Env Var | Role in This Workshop | Services Hosted Here | Verified Availability Notes |
|---|---|---|---|
| **Bangkok (`asia-southeast3`)**<br/>`PRIMARY_REGION=asia-southeast3`<br/>`AR_LOCATION=asia-southeast3`<br/>`BUILD_LOCATION=asia-southeast3`<br/>`AGENT_REGISTRY_LOCATION=asia-southeast3`<br/>`GKE_LOCATION=asia-southeast3` | **Primary Region** *(Build, Artifacts, Secrets, Agent Registry & Self-Hosted GKE)* | • **Artifact Registry** (`asia-southeast3-docker.pkg.dev`)<br/>• **Cloud Build** (`--region=asia-southeast3`, zero local Docker!)<br/>• **Secret Manager** (`asia-southeast3` / automatic)<br/>• **Agent Registry** (discovery, standalone skills & `ENABLED_BLOCKING` scanning)<br/>• **Lab 8 Self-Hosted GKE + GKE Agent Sandbox** | Keeps container builds, image storage, secrets, registry catalog, and optional self-hosted GKE clusters in Bangkok (ideal for Thailand PDPA / Bank of Thailand compute residency). *(Optional: set `AR_LOCATION=asia-southeast1` if you prefer strict same-region image pulls into Singapore Agent Runtime/Sandboxes.)* |
| **Singapore (`asia-southeast1`)**<br/>`GOOGLE_CLOUD_LOCATION=asia-southeast1` | **Secondary / Nearest Supported Agent Platform Region** | • **Agent Runtime** (`ReasoningEngine`)<br/>• **Managed Sandboxes** (Shell, BYOC, Code Exec)<br/>• **Managed Sessions** (`VertexAiSessionService`)<br/>• **Memory Bank** (`VertexAiMemoryBankService`)<br/>• **Agent Gateway** & **Gemini 2.5 Flash** | All Agent Platform Runtime, Sandbox, State, Gateway, and Gemini 2.5 Flash capabilities are **officially live in `asia-southeast1` with zero restrictions** — and are **not yet launched in `asia-southeast3`** (Bangkok). |
| **Iowa (`us-central1`)**<br/>`SKILL_REGISTRY_LOCATION=us-central1` | **Service-Mandated Override (Lab 4)** | • **Vertex AI Skill Registry** (`aiplatform.googleapis.com/v1beta1`) | Preview is strictly limited to **3 regions**: `us-central1`, `europe-west4`, and `us-east5`. Keeping `SKILL_REGISTRY_LOCATION=us-central1` explicitly in `.env` ensures Lab 4 succeeds cleanly from APAC. |
| **Global (`global`)**<br/>`EVAL_LOCATION=global` | **Service-Mandated Override (Lab 6)** | • **Gen AI Evaluation Service** (offline, simulated, `generate_loss_clusters` / `agents-cli eval analyze`) | Managed Evaluation supports **14 US/EU regions + `global`** (not yet `asia-southeast1`/`asia-southeast3`). Using `EVAL_LOCATION=global` is 100% APAC-ready AND runs `generate_loss_clusters` in the same client without `Unsupported region` errors! |

Additional verified regional boundaries to keep in mind:
- **Memory Bank is NOT available** in `asia-southeast2`, `australia-southeast2`, or `northamerica-northeast2` (fully supported in **`asia-southeast1`**).
- **Agent Gateway is NOT available** in `asia-east2`, `asia-northeast3`, or `asia-southeast2` (fully supported in **`asia-southeast1`**).
- **Semantic Governance Policy Engine (Optional Lab 7 NLC)** is currently available in 8 US/EU regions (`us-central1`, `us-east1`, `us-east4`, `us-west1`, `europe-southwest1`, `europe-west1`, `europe-west4`, `europe-west8`).
- **`global`** supports Memory Bank, Sessions, and Gen AI Evaluation (`generate_loss_clusters` / `agents-cli eval analyze` are **`global`-only**), but does **not** support `client.runtimes.create()` deployment or CMEK.
- *(Running a cohort in Americas or EMEA instead of APAC? You can optionally set all regional env vars to a single golden region — `us-central1` or `europe-west4` — while keeping `EVAL_LOCATION=global` for `generate_loss_clusters`.)*
- See [Supported locations](https://docs.cloud.google.com/gemini-enterprise-agent-platform/resources/agent-locations) for the full 23-region matrix.

### 1. Set Core Environment Variables

```bash
export GOOGLE_CLOUD_PROJECT="YOUR_PROJECT_ID"
export GOOGLE_CLOUD_PROJECT_NUMBER="$(gcloud projects describe "$GOOGLE_CLOUD_PROJECT" --format='value(projectNumber)')"

# Bangkok (asia-southeast3) Primary: Artifact Registry, Cloud Build, Secret Manager, Agent Registry, Lab 8 GKE
export PRIMARY_REGION="asia-southeast3"
export AR_LOCATION="asia-southeast3"             # Optional: set asia-southeast1 for same-region AR pulls
export BUILD_LOCATION="asia-southeast3"
export AGENT_REGISTRY_LOCATION="asia-southeast3"
export GKE_LOCATION="asia-southeast3"

# Singapore (asia-southeast1) Secondary: Agent Runtime, Sandboxes, Sessions, Memory Bank, Gateway, Gemini 2.5 Flash
export GOOGLE_CLOUD_LOCATION="asia-southeast1"

# Service-mandated overrides: Skill Registry (3-region Preview) & Gen AI Evaluation (APAC-ready + loss clustering)
export SKILL_REGISTRY_LOCATION="us-central1"
export EVAL_LOCATION="global"

gcloud config set project "$GOOGLE_CLOUD_PROJECT"
echo "Project: $GOOGLE_CLOUD_PROJECT (#${GOOGLE_CLOUD_PROJECT_NUMBER}) | Primary: $PRIMARY_REGION | Agent Platform: $GOOGLE_CLOUD_LOCATION | Skill Registry: $SKILL_REGISTRY_LOCATION | Eval: $EVAL_LOCATION"
```

### 2. Enable Required Google Cloud APIs

Requires `serviceusage.services.enable` (included in `roles/serviceusage.serviceUsageAdmin`):

```bash
gcloud services enable \
  aiplatform.googleapis.com \
  artifactregistry.googleapis.com \
  cloudbuild.googleapis.com \
  secretmanager.googleapis.com \
  logging.googleapis.com \
  monitoring.googleapis.com \
  telemetry.googleapis.com \
  cloudtrace.googleapis.com \
  agentregistry.googleapis.com \
  storage-component.googleapis.com \
  pubsub.googleapis.com \
  --project="$GOOGLE_CLOUD_PROJECT"
```

*(Optional APIs for advanced networking/encryption exercises: `compute.googleapis.com` for PSC-I/Cloud NGFW, `cloudkms.googleapis.com` for CMEK, `run.googleapis.com` if testing Cloud Run via `agents-cli`.)*

### 3. Verify Your User / Deployer IAM Roles

Ensure your user principal has the following roles on `$GOOGLE_CLOUD_PROJECT` (see [Runtime Setup](https://docs.cloud.google.com/gemini-enterprise-agent-platform/build/runtime/setup)):

| Role | Why It Is Needed |
|---|---|
| `roles/aiplatform.user` *(or `roles/aiplatform.admin`)* | Create/manage Agent Runtime instances, Managed Sandboxes, Templates, Snapshots, Sessions, Memory Bank, Feedback, Evaluation, and Skill Registry (`roles/aiplatform.admin` recommended for Terraform IAM/control-plane work). |
| `roles/serviceusage.serviceUsageAdmin` | Enable GCP APIs and provision service identities. |
| `roles/artifactregistry.writer` *(or `admin`)* | Create Artifact Registry repositories and push BYOC sandbox/agent container images. |
| `roles/cloudbuild.builds.editor` | Build container images remotely with Cloud Build (if not pushing locally with Docker). |
| `roles/iam.serviceAccountUser` *(and `roles/iam.serviceAccountAdmin` for Lab 5 TF)* | Create and attach the dedicated custom runtime service account in Terraform. |
| `roles/secretmanager.admin` | Create and bind workshop Secret Manager secrets in Lab 5. |
| `roles/logging.viewer` & `roles/monitoring.viewer` *(+ `monitoring.alertPolicyEditor` for Lab 6)* | Inspect Agent Runtime logs, PromQL metrics, and create Quality Alert policies. |

### 4. Understand and Pre-Provision Google-Managed Service Agents (CRITICAL!)

> [!CAUTION]
> **The #1 cause of `IMAGE_PULL_BACKOFF` failures in workshops is confusing Google Cloud's Agent Runtime Service Agent with the Agent Sandbox Service Agent.** They are **two completely separate identities**!

| Service Agent | Exact Email Format | What It Does in This Workshop | Required Grant |
|---|---|---|---|
| **Agent Runtime Service Agent** | `service-PROJECT_NUMBER@gcp-sa-aiplatform-re.iam.gserviceaccount.com` | Pulls **Agent Runtime** BYOC container images from same-project Artifact Registry; accesses Runtime CMEK keys; fetches secrets in `agents-cli deploy`. | `roles/artifactregistry.reader` (Lab 5), `roles/secretmanager.secretAccessor` (if using default SA) |
| **Agent Sandbox Service Agent** | `service-PROJECT_NUMBER@gcp-sa-vertex-sandbox.iam.gserviceaccount.com` | Pulls **BYOC Sandbox** custom container images from Artifact Registry into the isolated gVisor tenant project. Never accessible to code inside the sandbox. | `roles/artifactregistry.reader` on the sandbox Artifact Registry repo (Lab 2) |
| **Agent Platform Service Agent** | `service-PROJECT_NUMBER@gcp-sa-aiplatform.iam.gserviceaccount.com` | Fetches `secret_env` at deploy time when using `AGENT_IDENTITY`; handles cross-project Artifact Registry / GCS / Agent Gateway / Shared VPC PSC-I (`roles/compute.networkUser`). | `roles/secretmanager.secretAccessor` (Lab 5 / Optional Lab 7 with `AGENT_IDENTITY`) |

Manually trigger service identity creation upfront so IAM bindings never race ahead of identity provisioning:

```bash
# Triggers provisioning of Vertex AI & Reasoning Engine Service Agents
# (CLI output may display only the Vertex AI Service Agent, but gcp-sa-aiplatform-re is also created)
gcloud beta services identity create \
  --service=aiplatform.googleapis.com \
  --project="$GOOGLE_CLOUD_PROJECT"
```

*(Note: `service-PROJECT_NUMBER@gcp-sa-vertex-sandbox.iam.gserviceaccount.com` is granted `roles/artifactregistry.reader` on your Artifact Registry repo in Lab 2—if IAM rejects the principal on a brand-new project before the first sandbox API call, creating one temporary empty Agent Platform instance initializes the sandbox service identity.)*

### 5. Pre-Flight Quota Check & Multi-Attendee Sizing Math

Before running a live workshop (especially if multiple attendees share one GCP project!), inspect your project's active quotas against the defaults documented in [Agent Platform Quotas](https://docs.cloud.google.com/gemini-enterprise-agent-platform/resources/agent-quotas):

| Quota / System Limit | Default (Standard GCP) | Adjustable? | Metric Identifier |
|---|---:|:---:|---|
| Reasoning Engine create/update/delete per min | **10/min** | Yes | `aiplatform.googleapis.com/reasoning_engine_service_write_requests` |
| Max Reasoning Engine entities per region | **100** | Yes | `aiplatform.googleapis.com/reasoning_engine_service_entities` |
| `Query` / `StreamQuery` requests per min | **90/min** | Yes | `aiplatform.googleapis.com/reasoning_engine_service_query_requests` |
| Concurrent `BidiStreamQuery` connections / min | **10/min** | Yes | `aiplatform.googleapis.com/reasoning_engine_service_concurrent_query_requests` |
| Session create/update/delete per min | **100/min** | Yes | `aiplatform.googleapis.com/session_write_requests` |
| Session event appends per min | **300/min** | Yes | `aiplatform.googleapis.com/session_event_append_requests` |
| Memory Bank writes / reads per min | **100/min** / **300/min** | Yes | `memory_bank_{write,read}_requests` |
| Code Execution sandbox execute / write per min | **1,000/min** / **500/min** | Yes | `sandbox_environment_{execute,write}_requests` |
| Code Execution sandbox entities per region | **1,000** | Yes | `sandbox_environment_entities` |
| Max revisions per project per region | **6,000** | **No (Hard)** | `agent_engine_revisions_per_project_per_region` |
| Max revisions per agent | **950** | **No (Hard)** | `agent_engine_revisions_per_agent` |

**Quick Quota Sizing Formula (Shared Workshop Project):**
- Suppose **U** attendees each send **X** queries/min (typical lab burst: `X = 4` QPM) and each turn appends **Y** session events (typical coding agent with 2 tool calls: `Y = 6` events):
  - `Required Query QPM = U * X * 1.5` (50% headroom buffer against `429 RESOURCE_EXHAUSTED`)
  - `Required Session Event Appends/min = (U * X) * Y * 1.5`
- For **15+ concurrent attendees** in a single project, request increases on `reasoning_engine_service_query_requests` (from 90 to >= 150 QPM) and `reasoning_engine_service_write_requests` (from 10 to >= 30/min) at least 48 hours ahead—or assign **1 dedicated GCP project per attendee**.

Quick pre-flight command to verify authentication, enabled services, regional overrides, and local toolchain (zero Docker required!):

```bash
# Recommended automated pre-flight check (runs scripts/preflight_check.sh)
make preflight

# Or inspect individual components manually:
gcloud auth list --filter=status:ACTIVE --format="value(account)"
gcloud services list --enabled --project="$GOOGLE_CLOUD_PROJECT" \
  --filter="config.name:(aiplatform|artifactregistry|cloudbuild|secretmanager|logging|monitoring|telemetry|cloudtrace|agentregistry|storage-component|pubsub)" \
  --format="table(config.name)"
python3 --version && uv --version && terraform version | head -n 1
```

*(When you finish the workshop, run **`make cleanup`** — backed by `scripts/cleanup_workshop.sh` — to safely delete sandboxes, templates, alert policies, and runtimes.)*

---

## Using the Bundled Antigravity `.agents/skills/` During the Workshop

This repository ships with **6 modular, production-tested Antigravity skills** under `.agents/skills/`. Rather than copy-pasting boilerplate or searching scattered docs mid-lab, ask Antigravity directly—it automatically loads the matching skill's `SKILL.md` cheatsheet and on-demand `references/*.md` files:

| Skill Auto-Triggered | When You Need Help With... | Example Prompt to Antigravity |
|---|---|---|
| `adk-coding-agent-build` | Lab 1 — ADK `EnvironmentToolset`, `BaseEnvironment`, ADK 2.0 agent architectures (`collaborative`/`graph`/`dynamic`), `ManagedAgent`, or `services.yaml`/`services.py` | *"Compare ADK 2.0 `JoinNode` vs. dynamic `ctx.run_node(use_sub_branch=True)` and verify `BaseEnvironment` keyword-only `ctx`."* |
| `agent-platform-sandbox-byoc` | Lab 2 — BYOC sandbox Dockerfile rules, `SandboxEnvironmentTemplate` CRUD, `execute_bash()` vs. `execute_code()`, or PSC-I egress | *"Help me configure a BYOC sandbox template with default-deny egress and check which service agent pulls the image."* |
| `agent-platform-runtime-and-state` | Labs 3 & 5 — Managed Sessions, Memory Bank, Feedback, Telemetry, Terraform `google_vertex_ai_reasoning_engine`, `depends_on` IAM ordering, or PromQL | *"Check my Terraform `depends_on` block for `IMAGE_PULL_BACKOFF` and show me Memory Bank similarity retrieval."* |
| `agent-platform-governance-and-registries` | Lab 4 & Optional Lab 7 — Skill Registry 16 atomic ZIP/`SKILL.md` checks, `GCPSkillRegistry`, `AgentRegistry` auth, `ENABLED_BLOCKING` scanning, Semantic Governance NLC, or SPIFFE | *"Why did my Skill Registry ZIP fail validation, and how do I wire `AgentRegistry` with `httpx.Auth`?"* |
| `agent-platform-optimize-and-eval` | Lab 6 — Offline/Simulated/Online Evaluation, failure clustering, `monitoring_v3` Quality Alerts, or prompt tuning | *"Write a `monitoring_v3` quality alert policy for evaluation score drops and explain the 2-step user simulator."* |
| `agent-runtime-vs-gke-architecture` | Lab 8 — Deciding between Agent Runtime + Managed Sandbox vs. GKE + `kubernetes-sigs/agent-sandbox` + Agent Substrate | *"Compare Agent Runtime Managed Sandbox vs. GKE Agent Sandbox when we need GPUs and sub-second warm pools."* |

> **Co-Existence with `google/agents-cli` Built-In Skills:** Running `uvx google-agents-cli setup` installs 7 general lifecycle skills (`google-agents-cli-workflow`, `google-agents-cli-adk-code`, `google-agents-cli-scaffold`, `google-agents-cli-eval`, `google-agents-cli-deploy`, `google-agents-cli-publish`, `google-agents-cli-observability`). Use those for generic scaffolding (`agents-cli create`) and imperative deploys (`agents-cli deploy`); our 6 workspace skills handle the deeper enterprise platform surfaces (BYOC sandboxes, Terraform IaC, Skill/Agent Registries, Semantic Governance, Managed Evaluation/Alerts, and GKE comparisons).

---

## SDK Namespace Note (`agentplatform` vs. `vertexai`)

Gemini Enterprise Agent Platform documentation is transitioning from the legacy Vertex AI Python SDK namespace (`vertexai.Client` in `google-cloud-aiplatform[agent_engines]`) to the dedicated Agent Platform namespace (`agentplatform.Client` in `google-cloud-agentplatform>=2.0.1`, also re-exported by `google-cloud-aiplatform>=1.154.0`).

- **Environment variable:** Set `GOOGLE_GENAI_USE_ENTERPRISE=TRUE` as the standard enterprise environment configuration for Agent Platform and ADK 2.0+.
- **Starter & Solution compatibility:** Our workshop modules default to `agentplatform.Client` with a clean compatibility fallback to `vertexai.Client` so your code runs reliably across SDK versions.

---

## Proceed to Lab 1

Ready to write your first ADK Coding Agent? Continue to **[Lab 1: Setup & Build ADK Coding Agent](01-LAB-SETUP-AND-BUILD-ADK.md)**.

---

## Canonical References

- [Gemini Enterprise Agent Platform — Runtime Setup](https://docs.cloud.google.com/gemini-enterprise-agent-platform/build/runtime/setup)
- [Gemini Enterprise Agent Platform — Supported Locations](https://docs.cloud.google.com/gemini-enterprise-agent-platform/resources/agent-locations)
- [Gemini Enterprise Agent Platform — Quotas and System Limits](https://docs.cloud.google.com/gemini-enterprise-agent-platform/resources/agent-quotas)
- [Google ADK — Get Started](https://adk.dev/get-started/)
- [`google/agents-cli` — Official CLI & Workflow Skills](https://github.com/google/agents-cli)
- [Gemini Enterprise Agent Platform — Scale Sandboxes](https://docs.cloud.google.com/gemini-enterprise-agent-platform/scale/sandbox)
