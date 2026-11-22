# Facilitator Guide & Instructor Runbook — Enterprise Coding Agent Workshop

> **Audience:** Google Cloud Customer Engineers (CEs), Workshop Facilitators, Solutions Architects, and Lab Proctors  
> **Workshop Scope:** Full-Day (7h 00m total: 6h 10m labs + 50m breaks across Labs 1–8 with Optional/Skippable Lab 7; or 6h 25m skipping Lab 7) | Half-Day Fast-Track (3h 30m: Labs 1 Part A, 2, 4 & 5 hands-on, Lab 1 Part B walkthrough, Labs 3 & 6 instructor live demos, Optional Lab 7 skipped cleanly, Lab 8 briefing)  
> **Repository Companion:** [`README.md`](../README.md) · [`workshop/00-WORKSHOP-OVERVIEW.md`](./00-WORKSHOP-OVERVIEW.md) · [`scripts/verify_lab.sh`](../scripts/verify_lab.sh)

---

## 1. Project Topology & Region Selection (Decide at T-7d)

### 1.1 Recommended GCP Project Isolation Strategy

| Delivery Model | Recommended Cohort Size | Pros | Cons / Risks |
|---|---|---|---|
| **1 Dedicated GCP Project per Attendee** *(Strongly Recommended)* | Any (`5` to `100+`) | Eliminates shared `90 QPM`, `10 write/min`, `100 resources`, and `300 session appends/min` stampedes; isolates `OnlineEvaluator` P4SA permissions and Agent Registry namespaces. | Requires temporary sandbox project provisioning (e.g., Qwiklabs/Cloud Skills Boost, Argolis, or customer sandbox vending). |
| **Shared GCP Project (Small Cohort)** | **<= 8–10 attendees max** | Fast setup when only one customer sandbox project is available. | **Mandatory quota increases at T-7d** (especially `10 write/min` and `300 session appends/min`!); attendees must use unique `ATTENDEE_ID` prefixes for Terraform display names, AR images, templates, and Skill IDs; any admin creating an `OnlineEvaluator` can observe all agents in the project. |

### 1.2 Verified Regional Architecture: Bangkok (`asia-southeast3`) Primary + Singapore (`asia-southeast1`) Secondary

Do **not** pick an arbitrary single region—several Gemini Enterprise Agent Platform services have distinct regional availability matrices:
- **Bangkok (`asia-southeast3` — Primary Region):** Hosts **Artifact Registry** (`AR_LOCATION=asia-southeast3`), **Cloud Build** (`BUILD_LOCATION=asia-southeast3`, zero local Docker!), **Secret Manager**, **Agent Registry** (`AGENT_REGISTRY_LOCATION=asia-southeast3`), and **Lab 8 Self-Hosted GKE + GKE Agent Sandbox** (`GKE_LOCATION=asia-southeast3` — Thailand PDPA / BoT compute residency). *(Optional: set `AR_LOCATION=asia-southeast1` if you want strict same-region image pulls into Singapore Agent Runtime/Sandboxes.)*
- **Singapore (`asia-southeast1` — Secondary / Nearest Supported Agent Platform Region):** Hosts **Agent Runtime** (`ReasoningEngine`), **Managed Sandboxes** (Shell, BYOC, Code Exec), **Managed Sessions**, **Memory Bank**, **Agent Gateway**, and **Gemini 2.5 Flash** (`GOOGLE_CLOUD_LOCATION=asia-southeast1`) — all officially live in `asia-southeast1` with zero restrictions, and **not yet launched in `asia-southeast3`**.
- **Vertex AI Skill Registry (`aiplatform.googleapis.com/v1beta1`, Lab 4):** Preview is strictly **3 regions** — `us-central1`, `europe-west4`, and `us-east5`. Keep **`SKILL_REGISTRY_LOCATION=us-central1`** explicitly in `.env`.
- **Gen AI Evaluation Service (Lab 6):** Supports **14 US/EU regions** (`us-central1`, `us-east1`, `us-east4`, `us-east5`, `us-south1`, `us-west1`, `us-west4`, `europe-central2`, `europe-north1`, `europe-southwest1`, `europe-west1`, `europe-west4`, `europe-west8`, `europe-west9`) + **`global`**. Keep **`EVAL_LOCATION=global`** explicitly in `.env` — it is 100% APAC-ready AND supports `generate_loss_clusters` / `agents-cli eval analyze` in the same client!
- **Semantic Governance Policy Engine (Optional Lab 7 NLC):** 8 US/EU regions (`us-central1`, `us-east1`, `us-east4`, `us-west1`, `europe-southwest1`, `europe-west1`, `europe-west4`, `europe-west8`).
- **Memory Bank & Agent Gateway Exclusions:** Memory Bank excludes `asia-southeast2`, `australia-southeast2`, `northamerica-northeast2`; Agent Gateway excludes `asia-east2`, `asia-northeast3`, `asia-southeast2` (both are **fully live in `asia-southeast1`**).

> [!IMPORTANT]
> **Authoritative Workshop Defaults:** Standardize APAC cohorts on **Bangkok (`asia-southeast3`) Primary + Singapore (`asia-southeast1`) Agent Platform + `SKILL_REGISTRY_LOCATION=us-central1` + `EVAL_LOCATION=global`**. *(For Americas or EMEA cohorts preferring a single-region setup, `us-central1` or `europe-west4` supports Labs 1–8 natively while still setting `EVAL_LOCATION=global` for `generate_loss_clusters`.)*

---

## 1.3 Bangkok / Singapore Regional Pre-Flight & No-Docker Attendee Playbook

Many enterprise attendees join on locked-down corporate laptops or fresh Debian/Linux cloud workstations **without Docker Desktop, without root privileges, and without `python3-venv`**. Every lab in this workshop is verified **100% Zero-Docker**:

1. **Org Policy Regional Allowlist (Check at T-7d):** Ensure `constraints/gcp.resourceLocations` permits **`asia-southeast3`**, **`asia-southeast1`**, **`us-central1`** (Lab 4 Vertex AI Skill Registry Preview), and **`global`** (Lab 6 Gen AI Evaluation Service & loss clustering).
2. **Standalone `uv` Bootstrapping (No `python3-venv`, No `docker`):** Have attendees install standalone `uv` via `curl -LsSf https://astral.sh/uv/install.sh | sh` and run **`make preflight`** (`scripts/preflight_check.sh`) right after `cp .env.example .env`. It validates `gcloud`, ADC, enabled APIs, `uv`, and Bangkok/Singapore region variables — explicitly flagging local Docker as optional.
3. **Zero-Docker Lab 2 Playbook (BYOC Sandbox):**
   - Step 1: `make test-sandbox-local` — pure-Python stdlib localhost smoke test of `runner.py` (`/health` + `/exec`), zero Docker!
   - Step 2: `make push-sandbox` — remote Cloud Build in Bangkok (`gcloud builds submit --region=asia-southeast3`) pushing to `asia-southeast3-docker.pkg.dev/...` (or set `AR_LOCATION=asia-southeast1` if strict same-region AR pulls into Singapore sandboxes are preferred).
   - Fast-Track Escape Hatch: Set `SANDBOX_MODE=shell` in `.env` for instant Google-managed gVisor Shell Sandboxes in Singapore (`asia-southeast1`) with zero image build!
4. **Zero-Docker Lab 5 Playbook (3 Deployment Paths):**
   - **Path 1 (Primary):** `make test-agent-local` (pure-Python local FastAPI smoke test!) → `make push-agent` (Cloud Build `--region=asia-southeast3`) → `make tf-apply` (`container_spec` → Singapore `asia-southeast1`).
   - **Path 2 (Zero-Docker AND Zero-AR):** `make pack-agent-source` (level-0 `coding_agent_source.tar.gz`, `<= 8 MB`) → Terraform `source_code_spec` + empty `image_spec {}`.
   - **Path 3 (Rapid Dev):** `agents-cli deploy --region asia-southeast1`.
5. **Mandatory Instructor Live GCP End-to-End Dry-Run Rehearsal (Run at T-1d):**
   Before putting attendees in the room, validate your entire Bangkok/Singapore sandbox project end-to-end against live GCP APIs with one command:
   ```bash
   ./scripts/live_gcp_e2e_validate.sh --project <SANDBOX_PROJECT_ID>
   ```
   Confirm every Bangkok (`asia-southeast3`), Singapore (`asia-southeast1`), Skill Registry (`us-central1`), and Evaluation (`global`) check reports `PASS` before T-0!

---

## 2. T-7d / T-1d / T-0 Instructor Pre-Flight Checklist

### T-7 Days — Quotas, Org Policies & Environment Design
- [ ] Confirm **Standard GCP Billing** projects (NEVER Express Mode free tier—see §4).
- [ ] Confirm the regional split in `.env.example` / cohort slide deck: **`PRIMARY_REGION=asia-southeast3`** (Bangkok AR, Cloud Build, Secret Manager, Agent Registry, Lab 8 GKE), **`GOOGLE_CLOUD_LOCATION=asia-southeast1`** (Singapore Agent Runtime, Sandboxes, Sessions, Memory Bank, Gateway, Gemini 2.5 Flash), **`SKILL_REGISTRY_LOCATION=us-central1`**, and **`EVAL_LOCATION=global`** *(or `us-central1` / `europe-west4` for US/EMEA cohorts)*.
- [ ] Run the **Multi-Attendee Quota Sizing Formula** (§3) and submit Cloud Quotas increase requests for shared projects in **`asia-southeast1`** (allow 2–5 business days for approval).
- [ ] Audit Organization Policies in target project(s):
  - Disable `constraints/iam.managed.disableAccessPolicyBindings` if running **Optional Lab 7** IAM UAPs (enabled by default in new orgs).
  - Verify `constraints/gcp.resourceLocations` allows **`asia-southeast3`**, **`asia-southeast1`**, **`us-central1`**, and **`global`**.
  - Confirm Artifact Registry Docker push (`asia-southeast3` / `asia-southeast1`) and Cloud Build (`--region=asia-southeast3`) are permitted so attendees need **zero local Docker**.
- [ ] Decide **Optional Lab 7** mode upfront: **Include Live** (Full-Day cohorts with Org/Governance focus — noting Agent Registry scanning runs in Bangkok `asia-southeast3`, Agent Gateway/SPIFFE in Singapore `asia-southeast1`, and NLC Semantic Governance Preview requires one of the 8 US/EU regions) vs. **Skip Cleanly** (Half-Day Fast-Track, tight schedules, or sandbox projects without Org-level Agent Gateway — zero impact on Labs 1–6 or Lab 8!).
- [ ] Decide **Lab 8** GKE mode: **Walkthrough + Manifest Review** (default, zero cluster cost; highlight Bangkok `asia-southeast3` Thailand PDPA / BoT compute residency as the primary real-world GKE trigger!) vs. **Live Instructor Demo Cluster** in `GKE_LOCATION=asia-southeast3` (if demonstrating GKE Pod Snapshots live, provision GKE **`>= 1.35.3-gke.1234000`** Rapid channel with `--enable-pod-snapshots`, `--sandbox=type=gvisor`, and **non-E2** nodes such as `n2-standard-4`).

### T-1 Day — API Enablement, Service Agents, Pre-Warming & Live E2E Dry Run
- [ ] Enable all required APIs across workshop project(s):
  ```bash
  gcloud services enable \
    aiplatform.googleapis.com \
    artifactregistry.googleapis.com \
    cloudbuild.googleapis.com \
    secretmanager.googleapis.com \
    telemetry.googleapis.com \
    cloudtrace.googleapis.com \
    logging.googleapis.com \
    monitoring.googleapis.com \
    pubsub.googleapis.com \
    storage-component.googleapis.com \
    agentregistry.googleapis.com \
    networkservices.googleapis.com \
    networksecurity.googleapis.com \
    compute.googleapis.com \
    dns.googleapis.com \
    iam.googleapis.com \
    iap.googleapis.com \
    modelarmor.googleapis.com \
    --project="${GOOGLE_CLOUD_PROJECT}"
  ```
- [ ] **Trigger Service Identity Creation & Pre-Grant ALL THREE Service Agents** (eliminates the #1 workshop blocker, `IMAGE_PULL_BACKOFF`):
  ```bash
  export PROJECT_NUMBER=$(gcloud projects describe "${GOOGLE_CLOUD_PROJECT}" --format="value(projectNumber)")
  export AR_LOCATION="${AR_LOCATION:-asia-southeast3}"        # Bangkok primary AR (or asia-southeast1 for same-region pulls)
  export BUILD_LOCATION="${BUILD_LOCATION:-asia-southeast3}"  # Bangkok remote Cloud Build (zero local Docker!)

  gcloud beta services identity create --service=aiplatform.googleapis.com --project="${GOOGLE_CLOUD_PROJECT}"

  # Create Artifact Registry repository in Bangkok (asia-southeast3) for BYOC runtime + sandbox images
  gcloud artifacts repositories create coding-agent-repo \
    --repository-format=docker \
    --location="${AR_LOCATION}" \
    --project="${GOOGLE_CLOUD_PROJECT}" || true

  # 1. Agent Runtime Service Agent (pulls BYOC Agent Runtime images)
  gcloud projects add-iam-policy-binding "${GOOGLE_CLOUD_PROJECT}" \
    --member="serviceAccount:service-${PROJECT_NUMBER}@gcp-sa-aiplatform-re.iam.gserviceaccount.com" \
    --role="roles/artifactregistry.reader"

  # 2. Agent Sandbox Service Agent (pulls BYOC Sandbox images — DISTINCT from gcp-sa-aiplatform-re!)
  gcloud artifacts repositories add-iam-policy-binding coding-agent-repo \
    --location="${AR_LOCATION}" \
    --project="${GOOGLE_CLOUD_PROJECT}" \
    --member="serviceAccount:service-${PROJECT_NUMBER}@gcp-sa-vertex-sandbox.iam.gserviceaccount.com" \
    --role="roles/artifactregistry.reader"

  # 3. Agent Platform Service Agent (Secret Manager deploy fetch under AGENT_IDENTITY + Shared VPC PSC-I)
  gcloud projects add-iam-policy-binding "${GOOGLE_CLOUD_PROJECT}" \
    --member="serviceAccount:service-${PROJECT_NUMBER}@gcp-sa-aiplatform.iam.gserviceaccount.com" \
    --role="roles/secretmanager.secretAccessor"
  ```
- [ ] **Pre-Build & Pre-Warm the Instructor Demo Assets (Zero Local Docker!):**
  - Build and push via Bangkok Cloud Build (`--region=asia-southeast3`): `solution/sandbox_image/` to `${AR_LOCATION}-docker.pkg.dev/${GOOGLE_CLOUD_PROJECT}/coding-agent-repo/coding-sandbox:v1` AND `solution/` (`Dockerfile`, `main.py`, `requirements.txt`, `coding_agent/`, `skills_to_register/`) to `${AR_LOCATION}-docker.pkg.dev/${GOOGLE_CLOUD_PROJECT}/coding-agent-repo/coding-agent:v1` so attendees who fall behind in Lab 2 or Lab 5 can reference known-good images immediately.
  - Create one warm `SandboxEnvironmentTemplate` in your instructor project in **Singapore (`asia-southeast1`)** so live sandbox spin-up takes **seconds** instead of waiting up to **2 minutes** on stage.
  - Create one **Online Evaluation Monitor** in your instructor project at least **30+ minutes before Lab 6** (avoids presenting the normal first-monitor transient `"Failed"` / `"permission denied"` P4SA propagation state during the live walkthrough).
- [ ] Run end-to-end automated static validation AND the live GCP E2E rehearsal script:
  ```bash
  # 1. Static repo, skill & lab verification (target --track solution because starter/ retains # TODO markers)
  python3 scripts/validate_skills.py .agents/skills
  python3 scripts/package_registry_skill.py solution/skills_to_register/secure-code-review --dry-run
  ./scripts/verify_lab.sh all --track solution && ./scripts/verify_lab.sh 7 --track solution && ./scripts/verify_lab.sh 8 --track solution

  # 2. Instructor Live GCP End-to-End Dry-Run Rehearsal (validates Bangkok/Singapore/us-central1/global end-to-end!)
  ./scripts/live_gcp_e2e_validate.sh --project <SANDBOX_PROJECT_ID>
  ```

### T-0 (60 Minutes Before Kickoff) — Room & Attendee Readiness
- [ ] Verify attendee workstation prerequisites (**zero local Docker needed!**): `python >= 3.11`, standalone `uv` (`curl -LsSf https://astral.sh/uv/install.sh | sh` — works without `python3-venv` or `docker`), `gcloud` (updated), `terraform >= 1.5`, `uvx google-agents-cli setup`, and Antigravity IDE open at the repo root (confirm all 6 skills in `.agents/skills/` are auto-discovered).
- [ ] Verify ADC, quota project, and automated pre-flight on every laptop:
  ```bash
  gcloud auth login
  gcloud auth application-default login
  gcloud config set project "${GOOGLE_CLOUD_PROJECT}"
  gcloud auth application-default set-quota-project "${GOOGLE_CLOUD_PROJECT}"
  make preflight
  ```
- [ ] Post the shared slide/cheat-sheet showing: `PRIMARY_REGION=asia-southeast3` (Bangkok AR/Build/Agent Registry), `GOOGLE_CLOUD_LOCATION=asia-southeast1` (Singapore Agent Platform), `SKILL_REGISTRY_LOCATION=us-central1`, `EVAL_LOCATION=global`, pre-built fallback `SANDBOX_IMAGE_URI`, `SANDBOX_MODE=shell` escape hatch, and the exact **starter → solution** cutover command (§5).
- [ ] Remind attendees that Cloud Shell works cleanly for all zero-Docker labs (`make push-sandbox`, `make push-agent`, `make pack-agent-source`), though they should **not** run local Docker builds or Lab 8 Agent Substrate installs inside Cloud Shell (5 GB persistent disk ceiling).

---

## 3. Multi-Attendee Quota Sizing Formula & Cohort Table

Use the official sizing formulas from [`resources/agent-quotas`](https://docs.cloud.google.com/gemini-enterprise-agent-platform/resources/agent-quotas) whenever multiple attendees share a single GCP project and region:

### 3.1 Verified Sizing Equations
Let:
- **`U`** = Concurrent attendees (users) in the same project & region
- **`X`** = Average agent queries per attendee per minute during peak lab exercises (typically **`2` QPM/attendee** during interactive testing, **`4` QPM/attendee** during Lab 6 offline/simulated eval bursts)
- **`Y`** = Average session events generated per coding-agent turn (typically **`12` events/request** across user prompt → LLM → `ReadFile`/`EditFile`/`Execute` tool calls → final response)

Calculate required quota with the mandatory **50% spike buffer (`* 1.5`)**:
1. **Query / StreamQuery QPM (`aiplatform.googleapis.com/reasoning_engine_service_query_requests`):**
   - `Target QPM = U * X * 1.5` (where `Peak QPM = U * X`)
2. **Session Event Appends/min (`aiplatform.googleapis.com/session_event_append_requests`):**
   - `Target Session Appends/min = Peak QPM * Y * 1.5 = (U * X) * Y * 1.5`
3. **Session Writes/min (`aiplatform.googleapis.com/session_write_requests`):**
   - `Target Session Writes/min <= Peak QPM * 1.5 = (U * X) * 1.5`
4. **Runtime Entities (`aiplatform.googleapis.com/reasoning_engine_service_entities`):**
   - `Target Entities = U * 3 * 1.25` (1 deployed runtime + 1 standalone sandbox/session/memory parent + 1 buffer per attendee)
5. **Runtime Writes/min (`aiplatform.googleapis.com/reasoning_engine_service_write_requests` — THE #1 SHARED-PROJECT STAMPEDE TRAP!):**
   - Default is **only `10` writes/minute**! If 25 attendees run `terraform apply` or `agents-cli deploy` in the same minute, 15 will hit `429 RESOURCE_EXHAUSTED`. Request **`>= max(20, U * 1.5)`** writes/min (or stagger deployments by table/row).
6. **Sandbox Entities & Execute/min (`sandbox_environment_entities`, `sandbox_environment_execute_requests`):**
   - Defaults are **`1,000` entities/region**, **`1,000` execute reqs/min**, and **`500` writes/min** (sufficient for up to ~50–100 workshop attendees unless running heavy parallel load tests; still budget `U * 3` active/paused sandboxes per attendee).
7. **Non-Adjustable Revision Limits (Reused Training Projects!):**
   - **`6,000` revisions/project/region** and **`950` revisions/agent** are **hard system limits** (cannot be increased!). If reusing a single demo project across multiple customer workshops, configure `revision_garbage_collection_strategy.keep_n_latest.max_revisions = 20` and delete workshop engines after each cohort.

### 3.2 Pre-Calculated Shared-Project Cohort Sizing Table (`X = 2`, `Y = 12`)

| Metric (Cloud Quotas Name) | Default | **10 Attendees** | **25 Attendees** | **50 Attendees** | **100 Attendees** |
|---|---:|---:|---:|---:|---:|
| `reasoning_engine_service_query_requests` (QPM) | **90** | 30 *(OK)* | 75 *(Tight — ask 150)* | **150** *(Increase!)* | **300** *(Increase!)* |
| `session_event_append_requests` (/min) | **300** | **360** *(Increase!)* | **900** *(Increase!)* | **1,800** *(Increase!)* | **3,600** *(Increase!)* |
| `session_write_requests` (/min) | **100** | 30 *(OK)* | 75 *(OK)* | **150** *(Increase!)* | **300** *(Increase!)* |
| `reasoning_engine_service_write_requests` (/min) | **10** | **15** *(Increase!)* | **40** *(Increase!)* | **75** *(Increase!)* | **150** *(Increase!)* |
| `reasoning_engine_service_entities` (count) | **100** | 38 *(OK)* | 94 *(Ask 150)* | **188** *(Increase!)* | **375** *(Increase!)* |
| `memory_bank_write_requests` / `read_requests` (/min) | **100 / 300** | 30 / 60 *(OK)* | 75 / 150 *(OK)* | **150** / 300 *(Inc W)* | **300 / 600** *(Inc)* |
| `sandbox_environment_entities` / `execute_requests` | **1,000 / 1,000** | 30 / 60 *(OK)* | 75 / 150 *(OK)* | 150 / 300 *(OK)* | 300 / 600 *(OK)* |
| `agentregistry` standalone skills / revisions | **100 / 500** | 20 / 60 *(OK)* | 50 / 150 *(OK)* | 100 / 300 *(Inc)* | **200 / 600** *(Inc)* |

> [!TIP]
> Even a **10-person** shared project breaches the default **`300/min`** session event append limit and the **`10/min`** runtime write limit! That is why **1 GCP Project per Attendee** is overwhelmingly the smoothest delivery model.

---

## 4. Express Mode (Free Tier) Pitfalls

Attendees who accidentally sign up for or authenticate against **Agent Platform Express Mode** (using `GOOGLE_GENAI_API_KEY` + `GOOGLE_GENAI_USE_ENTERPRISE=TRUE` without a standard billing-enabled GCP project) will hit catastrophic blocks starting in Lab 2:

| Resource / Operation | Standard Production Default | Express Mode Limit | Impact on Workshop |
|---|---:|---:|---|
| Max Agent Platform resources | 100 | **10** | Shared room hits ceiling immediately |
| `Query` / `StreamQuery` per min | 90 | **10** | Single offline eval run triggers `429` |
| Concurrent `BidiStreamQuery` / min | 10 | **1** | Only 1 live stream allowed project-wide |
| Session event appends / min | 300 | **30** | Just **3** multi-tool coding turns/min exhausts quota! |
| Memory Bank writes / reads per min | 100 / 300 | **10 / 10** | Lab 3 memory retrieval throttled |
| Infrastructure & Governance | Full GCP IAM, AR, Terraform, Secret Manager, VPC, Cloud Monitoring | **Restricted / Unavailable** | Labs 2 (BYOC AR), 4 (Registries), 5 (Terraform), 6 (Online Monitors/Alerts), and Optional Lab 7 (Agent Registry Scanning / NLC / WORM) cannot complete |

**Fast Detection & Fix (T-0 Check):**
```bash
# Ensure Express Mode API key is UNSET and standard ADC + project are active
env | grep -E "GOOGLE_GENAI_API_KEY|GEMINI_API_KEY|GOOGLE_CLOUD_PROJECT|GOOGLE_GENAI_USE"
unset GOOGLE_GENAI_API_KEY GEMINI_API_KEY
export GOOGLE_GENAI_USE_ENTERPRISE="TRUE"
export GOOGLE_CLOUD_PROJECT="your-billing-enabled-project-id"
export PRIMARY_REGION="asia-southeast3"
export GOOGLE_CLOUD_LOCATION="asia-southeast1"
export SKILL_REGISTRY_LOCATION="us-central1"
export EVAL_LOCATION="global"
```

---

## 5. Pacing Schedule & Time-Box Recovery Checkpoints (`starter/` → `solution/`)

### 5.1 Full-Day (7h 00m) vs. Half-Day (3h 30m) Schedule & Async Wait Choreography

| Module | Full-Day Window (420m) | Half-Day Fast-Track (210m) | Async Wait Choreography (Do NOT Stand Idle!) |
|---|---|---|---|
| **[00. Overview & Setup](./00-WORKSHOP-OVERVIEW.md)** | `0:00–0:20` (20m) | `0:00–0:10` (10m) | Verify `gcloud`, standalone `uv`, `make preflight`, Antigravity `.agents/skills/` auto-discovery & Bangkok (`asia-southeast3`) / Singapore (`asia-southeast1`) regional split |
| **[01. Build ADK Agent](./01-LAB-SETUP-AND-BUILD-ADK.md)** | `0:20–1:20` (60m: Part A 30m + Part B 30m) | `0:10–0:45` (35m: Part A 30m hands-on, Part B 5m walkthrough) | Part A: local `LlmAgent` + `EnvironmentToolset(LocalEnvironment)` (`AGENT_ARCHITECTURE=simple`); Part B: evolve across `collaborative`, `graph` (`JoinNode` + `RetryConfig`), and `dynamic` (`ctx.run_node` + `RequestInput`) + inspect `services.yaml`/`services.py`, then reset `AGENT_ARCHITECTURE=simple` before Lab 2 |
| **[02. Custom BYOC Sandbox](./02-LAB-CUSTOM-SANDBOX-BYOC.md)** | `1:20–2:20` (60m) | `0:45–1:25` (40m) | Create lightweight standalone Agent Platform instance (`client.runtimes.create()`), **kick off** `make push-sandbox` (`coding-agent-repo/coding-sandbox:v1`) + `SandboxEnvironmentTemplate` warm pool (**up to 2m cold start**) → teach security boundaries & egress while it builds! |
| *Morning Break* | `2:20–2:30` (10m) | `1:25–1:35` (10m) | *Coffee / Stretch Break* |
| **[03. Sessions, Memory & Feedback](./03-LAB-SESSIONS-MEMORY-FEEDBACK.md)** | `2:30–3:10` (40m) | `1:35–1:50` (15m live demo) | Reuses Lab 2's standalone instance (`REASONING_ENGINE_NAME`) so no runtime deploy is required yet! Full-Day hands-on; Half-Day 15m instructor live demo + walkthrough. Remember Memory Bank `wait_for_completion=True` for demos; wait ~1m before deleting engines after memory gen |
| **[04. Skill & Agent Registry Discovery](./04-LAB-SKILLS-AND-AGENT-REGISTRY.md)** | `3:10–3:50` (40m) | `1:50–2:20` (30m) | Run `package_registry_skill.py --dry-run` (16 checks), publish `secure-code-review` to Vertex AI Skill Registry, and wire `GCPSkillRegistry` + `AgentRegistry` into `coding_agent` **before** building the runtime image in Lab 5 |
| *Lunch Break* | `3:50–4:30` (40m) | *—* | *Lunch Break (Full-Day only)* |
| **[05. Deploy ONCE: Runtime & Terraform](./05-LAB-DEPLOY-RUNTIME-TERRAFORM.md)** | `4:30–5:15` (45m) | `2:20–2:50` (30m) | **Kick off** `make push-agent` (`coding-agent-repo/coding-agent:v1`) + `make tf-apply` (**5–10m**) deploying the **100% feature-complete Labs 1–4 Coding Agent** once (Custom SA + `roles/aiplatform.memoryUser` + unified vs. decoupled `REASONING_ENGINE_NAME`) → teach runtime contract, `.id` vs. `.name` outputs, revisions & emergency stop while provisioning completes! |
| **[06. Optimize, Eval & Alerts](./06-LAB-OPTIMIZE-EVAL-AND-ALERTS.md)** | `5:15–5:55` (40m) | `2:50–3:05` (15m live demo) | Full-Day hands-on; Half-Day 15m instructor live demo. Show instructor's pre-warmed Online Monitor, split single/multi-turn JSON evals, `global` `generate_loss_clusters`, and bounded `optimize_prompt.py --iterations 2 --batch-size 4` |
| **[07. Enterprise Security & Governance](./07-LAB-OPTIONAL-SECURITY-AND-GOVERNANCE.md)** *(Optional / Skippable)* | `5:55–6:30` (35m *(optional — skip to finish at 6h 25m)*) | *Skipped (self-paced)* | **Skip cleanly if short on time!** Covers Agent Registry `ENABLED_BLOCKING` scanning, NLC Semantic Governance & Model Armor, SPIFFE `AGENT_IDENTITY` + Agent Gateway Terraform upgrade, multi-tenant Session/Memory IAM Conditions, CMEK/VPC-SC, WORM + SIEM + 3-layer SCC Anomaly Detection |
| **[08. Agent Runtime vs. GKE](./08-ARCHITECTURE-AGENT-RUNTIME-VS-GKE.md)** | `6:30–7:00` (30m) | `3:05–3:30` (25m) | Whiteboard decision tree + quota math + walkthrough `starter/gke_reference/` |
| **Total** | **420m (7h 00m)** *(370m labs + 50m breaks; 385m / 6h 25m skipping Lab 7)* | **210m (3h 30m)** *(200m labs/demos + 10m break; skips Lab 7 cleanly)* | |

> [!TIP]
> **When to Skip Optional Lab 7 (`07-LAB-OPTIONAL-SECURITY-AND-GOVERNANCE.md`):**
> - **Always skip** in the **3.5-hour Half-Day Fast-Track** so Lab 8 keeps its full 25-minute architecture & Q&A window.
> - **Skip in Full-Day deliveries** if the room runs >15 minutes behind schedule after Lab 6, or if attendees are working in standalone/orgless sandbox projects without Organization Policies or Agent Gateways.
> - **Zero downstream impact:** Core Labs 1–6 deliver a 100% functional, deployed, and evaluated Coding Agent (`make verify-lab LAB=all` passes 100% without Lab 7), and Lab 8 has zero dependencies on Lab 7. Share [Lab 7](./07-LAB-OPTIONAL-SECURITY-AND-GOVERNANCE.md) as a post-workshop security & SecOps reference pack.

### 5.2 Hard Cutover Checkpoints (When to Switch from `starter/` to `solution/`)

Every lab is designed so attendees can cleanly jump forward from [`starter/`](../starter/) to [`solution/`](../solution/) without losing downstream progress. Announce the **Yellow Light** (5 min left to debug) and enforce the **Red Light** cutover command:

| Lab | Yellow Light (Debug Cap) | Red Light Cutover Command (Copy Verified Reference File into `starter/`) | Verification Command |
|---|---|---|---|
| **Lab 1** | +22m *(Part A)* / +45m *(Part B)* | `cp solution/coding_agent/agent.py solution/coding_agent/architectures.py starter/coding_agent/ && cp solution/services.yaml solution/services.py starter/` *(keep `AGENT_ARCHITECTURE=simple` and `ENABLE_TELEMETRY_CALLBACKS=false` until Lab 3, since `solution/coding_agent/agent.py` imports Lab 3 callbacks)* | `./scripts/verify_lab.sh 1` |
| **Lab 2** | +45 min | `cp solution/coding_agent/tools/sandbox_lifecycle.py solution/coding_agent/tools/sandbox_execution.py starter/coding_agent/tools/ && cp -r solution/sandbox_image/* starter/sandbox_image/` *(also complete `# TODO(lab-2)` in `starter/coding_agent/agent.py` or copy `solution/coding_agent/agent.py` with `ENABLE_TELEMETRY_CALLBACKS=false` until Lab 3)* | `./scripts/verify_lab.sh 2` |
| **Lab 3** | +28 min | `cp solution/coding_agent/memory/session_manager.py solution/coding_agent/memory/memory_bank_manager.py starter/coding_agent/memory/ && cp solution/coding_agent/callbacks/telemetry_and_feedback.py starter/coding_agent/callbacks/ && cp solution/coding_agent/agent.py starter/coding_agent/agent.py` | `./scripts/verify_lab.sh 3` |
| **Lab 4** | +28 min | `cp solution/coding_agent/tools/registry_loader.py starter/coding_agent/tools/ && cp solution/coding_agent/agent.py starter/coding_agent/agent.py` | `./scripts/verify_lab.sh 4` |
| **Lab 5** | +32 min | `cp solution/main.py starter/main.py && cp -r solution/terraform/* starter/terraform/` | `./scripts/verify_lab.sh 5` |
| **Lab 6** | +28 min | `cp -r solution/eval/* starter/eval/` | `./scripts/verify_lab.sh 6` |
| **Lab 7 (Optional / Skippable)** | +25 min | *No `starter/` file cutover required — Lab 7 is an optional CLI, Terraform-diff & security-audit module; skip straight to Lab 8 with zero broken code* | `./scripts/verify_lab.sh 7` *(optional)* |
| **Lab 8 (Optional GKE Overlay)** | +20 min | `cp -r solution/gke_reference/* starter/gke_reference/` | `./scripts/verify_lab.sh 8` |
| **Full Reset** | Anytime | Switch working directory straight into `solution/` (`cd solution && uv sync`) | `./scripts/verify_lab.sh all --track solution` |

---

## 6. Top-20 Workshop Troubleshooting Playbook

Every failure mode and fix below is verified directly against official Google Cloud documentation and ADK Python source code.

| # | Symptom / Error | Lab | Verified Root Cause | Exact Fix |
|---:|---|---|---|---|
| **1** | `IMAGE_PULL_BACKOFF` (or Secret Manager fetch error) deploying BYOC Agent Runtime | Lab 5 | Missing `roles/artifactregistry.reader` on **Agent Runtime Service Agent** (`service-PROJECT_NUMBER@gcp-sa-aiplatform-re.iam.gserviceaccount.com`), missing Terraform `depends_on` race condition, or missing `roles/secretmanager.secretAccessor` / cross-project AR reader on **Agent Platform Service Agent** (`gcp-sa-aiplatform`). | Grant `roles/artifactregistry.reader` to `gcp-sa-aiplatform-re` (and `gcp-sa-aiplatform` if cross-project AR or `secret_env` with `AGENT_IDENTITY`), wire ALL IAM resources into `depends_on = [...]` on `google_vertex_ai_reasoning_engine`, and re-apply. |
| **2** | `IMAGE_PULL_BACKOFF` / `PERMISSION_DENIED` creating BYOC `SandboxEnvironmentTemplate` | Lab 2 | Granted `roles/artifactregistry.reader` to `gcp-sa-aiplatform-re` instead of the **separate Agent Sandbox Service Agent**. | Grant `roles/artifactregistry.reader` on the Artifact Registry repository specifically to `service-PROJECT_NUMBER@gcp-sa-vertex-sandbox.iam.gserviceaccount.com`, and verify `http_options={"api_version": "v1beta1"}` on the SDK client. |
| **3** | `execute_code()` or `send_command()` fails on Shell Sandbox (`shell_environment`) | Lab 2 | `execute_code()` targets Code Execution sandboxes (Python/JS) and `send_command()` + `generate_access_token()` is the Computer Use HTTP data-plane API—neither matches Shell Sandbox's IAM-authenticated `/exec` contract. Also, each bash call spawns a fresh shell so `cd`/env vars don't persist. | Call `client.sandboxes.execute_bash(name=sandbox.name, command="cd /workspace/app && pytest -q", cwd="/workspace", timeout=120)` (hits `/exec` as unprivileged `appuser` with no `sudo`). Persist state in files under `/workspace`. |
| **4** | Dockerfile `source_code_spec` deploy fails with `Dockerfile not found` or archive size error | Lab 5 | Archiving a parent folder (`tar -czf src.tar.gz app_dir/`) places `Dockerfile` at `app_dir/Dockerfile` instead of the **tarball root** (`./Dockerfile`), OR inline `.tar.gz` exceeds the **8 MB** max archive limit. | `cd` into the directory first: `cd app_dir && tar -czvf ../src.tar.gz main.py requirements.txt Dockerfile`, verify `tar -tzf ../src.tar.gz` shows `./Dockerfile` at root, and keep `.tar.gz <= 8 MB` (exclude `.venv/`, `__pycache__/`). |
| **5** | `gcp-skill-registry` missing from first `skills.list()` call, or `SKILL_ID` creation fails after delete | Lab 4 | Built-in `gcp-skill-registry` begins **async ingestion on your first API call** and appears starting on the **second** call. Deleting a `SKILL_ID` reserves it for **24h / permanently** (docs warn against reuse). LRO failures can also stem from violating any of the **16 atomic ZIP/`SKILL.md` rules** (10 MB zip, 500 MB unzipped, 8 levels, no symlinks/`..`, valid frontmatter). | Call `skills.list()` a second time after a few seconds; use a new versioned suffix (`secure-code-review-v2`) instead of deleting & recreating; always pre-validate with `python3 scripts/package_registry_skill.py <dir> --dry-run`. |
| **6** | `ImportError` on `from google.adk.integrations.agent_registry import AgentRegistry` | Lab 4 | `agent_registry.py` imports both `a2a-sdk` and the Agent Identity auth provider at **module import time**; bare `pip install google-adk` omits these extras. | Install `pip install --upgrade "google-adk[a2a,agent-identity,mcp]>=2.0.0"` (minimum `google-adk[a2a,agent-identity]>=2.0.0`) or run `uv sync` against `starter/pyproject.toml`. |
| **7** | Code inside Managed Sandbox cannot call Vertex AI, Skill Registry, PyPI, or `169.254.169.254` | Lab 2 / Lab 4 | Managed Sandboxes default to `internet_access: False`, run as `sandbox-untrusted`/`appuser` with **zero IAM roles**, and block `169.254.169.254:80` and RFC 1918. `GCPSkillRegistry` fails inside air-gapped sandboxes. | Keep Vertex AI / Skill Registry calls in the **parent Agent Runtime** and pass data into the sandbox; bake Python/Node dependencies into the BYOC image (`sandbox_image/Dockerfile`); for controlled VPC/FQDN egress, attach **PSC-I** (`network_attachment`, min `/28`) + Cloud NGFW/SWP + Cloud DNS peering. |
| **8** | `AttributeError: 'str' object has no attribute 'resolve'` on `LocalEnvironment`, or `DeprecationWarning` losing `ctx.state` in `BaseEnvironment` | Lab 1 / Lab 2 | `LocalEnvironment._resolve_path()` calls `.resolve()` on `working_dir` without casting `str` → `Path`. `BaseEnvironment.__init_subclass__` wraps overrides that omit `*, ctx: Context \| None = None`, stripping `ctx`! | Always pass `LocalEnvironment(working_dir=Path("/tmp/workspace"))` (a `pathlib.Path`), put `max_output_chars` on `EnvironmentToolset(...)` (not `LocalEnvironment`), and include `*, ctx: Context \| None = None` on all 5 `BaseEnvironment` overrides (`initialize`, `execute`, `read_file`, `read_file_stream`, `write_file`). |
| **9** | ADK `"Session not found"` during `adk web`, `eval generate`, or Gemini publish | Lab 1 / Lab 3 / Lab 6 | (a) `App(root_agent=..., name="...")` does not match the containing folder name; (b) `adk web --session_service_uri=agentengine://...` **ignores `.env`**; (c) `google-cloud-aiplatform <= 1.128.0` bug. | Ensure `App.name` matches the agent package directory name; export `GOOGLE_CLOUD_PROJECT` and `GOOGLE_CLOUD_LOCATION` directly in your shell before `adk web --session_service_uri=...`; upgrade `google-cloud-aiplatform>=1.154.0` / `google-cloud-agentplatform>=2.0.1`. |
| **10** | `400 FAILED_PRECONDITION` / API error during Evaluation or `generate_loss_clusters` | Lab 6 | (a) Eval Service supports **14 US/EU regions + `global`** (NOT `asia-southeast1`/`asia-southeast3`), and **`generate_loss_clusters` / `eval analyze` are `global`-only** (`generate_loss_clusters` also requires explicit `metric=` for multi-metric results); (b) mixing multi-turn cases into a single-turn dataset fails with HTTP 400 (`Single-turn metric ... received agent_eval_data with N turns`); (c) `gemini-flash-latest` alias can fail on regional endpoints. | Set **`EVAL_LOCATION=global`** in `.env` (works seamlessly for APAC `asia-southeast1` runtimes AND supports `generate_loss_clusters` with explicit `metric=types.RubricMetric.MULTI_TURN_TASK_SUCCESS` in the same client!); keep `coding_agent_single_turn.json` and `coding_agent_multi_turn.json` strictly separated; pin explicit versioned Gemini model IDs (e.g., `gemini-2.5-flash`). |
| **11** | First Online Evaluation Monitor shows **`Failed`** (`"permission denied"`) right after creation | Lab 6 | Expected transient IAM propagation delay for the project-level service account (**P4SA**) on the project's very first `OnlineEvaluator`. | **Do not delete.** Wait 10–30 minutes for the scheduled 10-minute retry loop to turn it **Active**. Only inspect P4SA IAM if still `Failed` after **30 minutes**. |
| **12** | Traces appear, but prompt/response text is blank or Online Monitor sees zero gradeable events | Lab 3 / Lab 5 / Lab 6 | Passed `"true"` instead of enum `"EVENT_ONLY"` for ADK Python `OTEL_INSTRUMENTATION_GENAI_CAPTURE_MESSAGE_CONTENT` (silently falls back to `NO_CONTENT`!), or used ADK `< 2.1` after May 22, 2026 for `user.id`, or missed `GOOGLE_CLOUD_AGENT_ENGINE_ENABLE_TELEMETRY=true`. | For ADK Python, set `GOOGLE_CLOUD_AGENT_ENGINE_ENABLE_TELEMETRY="true"`, `OTEL_SEMCONV_STABILITY_OPT_IN="gen_ai_latest_experimental"`, and `OTEL_INSTRUMENTATION_GENAI_CAPTURE_MESSAGE_CONTENT="EVENT_ONLY"` (for ADK Go, use `"1"`/`"true"` instead!). |
| **13** | Semantic Governance fails to block tool calls OR breaks Agent Runtime startup | Lab 7 (Optional) | (a) Policy Engine **does NOT support streamed model responses** (`:streamGenerateContent` / `"stream": true`); (b) `AuthzPolicy` `when` CEL omitted `!request.headers['content-type'].startsWith('application/grpc')`, intercepting Cloud Resource Manager gRPC calls, or used `.endsWith()` instead of `.contains()`. | Disable streaming on governed LLM calls; include `!request.headers['content-type'].startsWith('application/grpc') && (request.path.contains(':generateContent') ...)` in `AuthzPolicy`; deploy engine with immutable `identity_type = "AGENT_IDENTITY"` + `agent_gateway_config`. |
| **14** | `agents-cli infra single-project --apply` conflicts with deployed runtime, or IAP UAP rejects `iamEnforcementMode: "ENFORCED"` | Lab 5 / Lab 7 (Optional) | (a) `agents-cli infra` must run **before** your first imperative `agents-cli deploy` on `agent_runtime`; (b) IAP first-party API validator **rejects** any explicit `iamEnforcementMode` value other than `"DRY_RUN"`. | Run `agents-cli infra single-project --apply` first (or use `--update-env-vars` on an existing imperative deployment); to activate IAP UAP enforcement via Terraform/gcloud/REST, **remove** the `iamEnforcementMode` key from `metadata`. |
| **15** | Lab 8 GKE errors: `403` on `adk deploy gke`, Pod Snapshot cold-starts or rejects E2/TPU, or Dataplane V2 `anetd` CPU spikes | Lab 8 | (a) `adk deploy gke` uses `default/default` KSA without WIF `roles/aiplatform.user`; (b) `whole-pod` Pod Snapshots require GKE `>= 1.35.3-gke.1234000`, `gVisor`, non-E2 nodes, no TPUs, no GCS FUSE CSI sidecar, and waiting for `PodSnapshot` `condition=Ready` before `operatingMode: Suspended`; (c) Dataplane V2 `anetd` can spike to 2–3 vCPUs/node under rapid TCP connection open/close churn. | Bind `default/default` KSA via WIF; use `n2`/`c3` nodes (Autopilot `ComputeClass` `non-e2-class`) for `whole-pod` snapshots (or `rootfs-only` on `>= 1.35.3-gke.1031000` for E2 portability) and wait for `PodSnapshot` `Ready` before suspend; use HTTP keep-alives and connection pooling for `anetd`; NEVER run `kubectl delete -f sandbox-with-extensions.yaml` on shared clusters! |
| **16** | Graph `Workflow` fails with `ValueError` (multiple terminal outputs), downstream `JoinNode` misses branch data, or graph loop spins forever | Lab 1 (Part B) | (a) Two parallel branches terminated with output instead of converging; (b) a predecessor feeding `JoinNode` returned no output; (c) graph cycles are **not bounded automatically** (and unconditional cycles are rejected at build time). | Converge parallel branches into a single `JoinNode` → single terminal node; guarantee every predecessor of `JoinNode` emits output (attach `RetryConfig` to flaky checks); add a conditional `Event(route=...)` exit counter (`MAX_FIX_ROUNDS`) or switch to `AGENT_ARCHITECTURE=dynamic`. |
| **17** | Dynamic workflow fails to resume after `RequestInput` HITL pause, re-runs completed nodes, or hits `run_id` collision | Lab 1 (Part B) | (a) Parent orchestrator calling `ctx.run_node()` omitted `@node(rerun_on_resume=True)` (or caught bare `BaseException`, trapping `NodeInterruptedError`); (b) custom numeric-only `run_id` collided with auto-generated sequential IDs (`"1"`, `"2"`, ...); (c) `App` omitted `ResumabilityConfig(is_resumable=True)`. | Decorate dynamic orchestrators with `@node(rerun_on_resume=True)` and leaf HITL nodes with `@node(rerun_on_resume=False)`; never catch `BaseException`; ensure any custom `run_id` contains at least one non-numeric character (e.g., `f"check-{name}"`); keep `ResumabilityConfig(is_resumable=True)` on `App`. |
| **18** | Python `LlmAgent.instruction` leaves `{Class.field}` verbatim, OR a Python node raises a runtime error when yielding multiple outputs | Lab 1 (Part B) | (a) In ADK Python, `{key}` templates substitute **session state**, NOT `node_input` (only ADK TypeScript supports `{Class.field}` / `<Class.field from node>`); (b) Python nodes allow **strictly ONE** `Event(output=...)` per execution. | Write values to state via `yield Event(state={"code": ..., "findings": ...})` before invoking `{code}`/`{findings}` agents (or attach `input_schema=MyModel` and reference fields in prose); use `Event(message=...)` for progress updates and emit only a single `Event(output=...)`. |
| **19** | Collaborative team misbehaves: `mode` on root agent, `task` subagent errors inside Python v2.0.0 graph / with children, or `Workflow` added to `LlmAgent.sub_agents` | Lab 1 (Part B) | (a) `mode` is strictly for subagents (never root); (b) `task` mode agents must be leaf agents and `task` mode is disabled in ADK Python v2.0.0 graph workflows; (c) a `Workflow` cannot yet be used as an `LlmAgent` `sub_agent`. | Remove `mode` from the root coordinator; keep `requirements_clarifier` (`mode="task"`) as a leaf subagent in collaborative teams only; nest `Workflow`s inside another `Workflow` (or switch to `dynamic`), not inside `LlmAgent.sub_agents`. |
| **20** | `ManagedAgent` raises regional error or `NotImplementedError` on Python tool, OR `RetryConfig` never retries / `ctx.attempt_count` resets after HITL pause | Lab 1 (Part B) | (a) `ManagedAgent` (v2.4.0 Preview) is **`global`-only** on Agent Platform and supports **server-side tools & `RemoteMcpServer` only** (streaming only); (b) broad `except Exception:` masked failures from `RetryConfig`, `NodeTimeoutError` wasn't listed in `exceptions`, or a HITL pause reset in-memory `ctx.attempt_count`. | Keep BYOC `EnvironmentToolset` on `LlmAgent`/Workflows (use `ManagedAgent(mode="single_turn")` only for `global` server-side tools); let transient exceptions propagate, include `NodeTimeoutError` in `RetryConfig.exceptions`, and make retried nodes idempotent since `ctx.attempt_count` is not persisted across pauses/restarts. |

---

## 7. Post-Workshop Teardown & Cost-Hygiene Checklist

Run this ordered cleanup sequence after the workshop so sandbox warm pools, `min_instances >= 1` runtimes, and Online Monitors do not continue accruing charges.

### Automated One-Command Teardown (`make cleanup`)

Have every attendee (and your instructor rehearsal project) run the bundled cleanup script from the repository root first:

```bash
# Preview teardown first with --dry-run, then run live cleanup:
make cleanup CLEANUP_ARGS=--dry-run
# Runs scripts/cleanup_workshop.sh — tears down sandboxes, templates, alert policies, and runtimes cleanly
make cleanup
```

### Manual Verification & Deep-Clean Checklist

Confirm each resource category is empty after `make cleanup` (or tear down manually if any step requires custom confirmation):

1. **Disable/Delete Online Evaluation Monitors** (`Agent Platform → Evaluation → Online monitors → More options → Disable / Delete`) and confirm temporary Cloud Monitoring alerting policies are removed.
2. **Delete Sandboxes, Snapshots, and Templates in Singapore (`asia-southeast1`)** (note: deleting a sandbox does **NOT** delete its backing template, and deleting a template fails while warm-pool or sandbox creation is still active):
   ```bash
   cd solution && uv run python -m coding_agent.tools.sandbox_lifecycle cleanup-all --include-templates
   ```
3. **Delete Agent Platform Runtimes & Standalone State Instance (with `force=True`):**
   - Wait **~1 minute** after the final conversation before deleting if Memory Bank background generation just fired (prevents `FAILED_PRECONDITION`).
   - Run `terraform destroy` inside `starter/terraform/` (or `solution/terraform/`) for the Lab 5 deployed runtime, AND delete your Lab 2/3 standalone parent instance via `client.runtimes.delete(name=..., force=True)` if created separately.
   - Remind attendees who completed Optional Lab 7 that deleting an `AGENT_IDENTITY` runtime permanently invalidates its SPIFFE identity—clean up any dangling `principal://...` entries in UAPs or IAM policies.
4. **Clean Up Optional Lab 7 Log Sinks & Buckets (if created):** Delete `agent-siem-sink`, `agent-siem-events` Pub/Sub topic, and `agent-audit-worm` log bucket (note: only unlocked log buckets can be deleted before their retention period expires!).
5. **Clean Up Optional Lab 8 GKE Resources in Bangkok (`asia-southeast3`) (Safe Namespace-Only Delete):**
   ```bash
   kubectl delete -f solution/gke_reference/ --ignore-not-found
   # Only delete a dedicated workshop cluster as a whole via `gcloud container clusters delete --region=asia-southeast3`
   ```
