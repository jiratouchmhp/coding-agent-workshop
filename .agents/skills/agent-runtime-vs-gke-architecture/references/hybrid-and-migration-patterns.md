# Hybrid Architectures, Self-Hosted ADK on GKE & `agents-cli` Migration Patterns

Production blueprints for combining **Gemini Enterprise Agent Platform** with **Self-Hosted GKE**, deploying ADK agents directly on GKE (`adk deploy gke` vs. manual Python/Go), and graduating agents across `agent_runtime`, `cloud_run`, and `gke` with `agents-cli` (`v1.15.0`).

---

## 1. Four Verified Hybrid Architecture Patterns

### Pattern A: Self-Hosted Orchestrator (GKE / Cloud Run / Local) -> Managed Scale Sandbox
- **When to use:** You need custom HTTP/UI/WebSocket routing, Eventarc/IAP, instant `kubectl rollout undo`, or relief from Agent Runtime's `90 QPM` / `10 Bidi/min` / `950 revisions/agent` limits — **without** operating GKE gVisor node pools, VAPs, or `sandbox-router`.
- **How it works:** Scale Sandboxes do **not** require deploying your agent code to Agent Runtime. Provision an empty parent `ReasoningEngine` instance (`client.runtimes.create()`), grant your GKE KSA `roles/aiplatform.user` via WIF, and call `client.sandboxes.*` or ADK `AgentEngineSandboxCodeExecutor` directly from GKE Pods.

```python
# Runs inside a GKE Pod (KSA bound to roles/aiplatform.user via WIF)
# pip install "google-adk[gcp]>=2.0.0" "google-cloud-agentplatform>=2.0.1"
import agentplatform
from google.adk.agents.llm_agent import Agent
from google.adk.code_executors.agent_engine_sandbox_code_executor import (
    AgentEngineSandboxCodeExecutor,
)

# One-time setup: create a minimal parent ReasoningEngine in Singapore (no runtime container deployed)
client = agentplatform.Client(
    project="PROJECT_ID",
    location="asia-southeast1",
    http_options={"api_version": "v1beta1"},
)
parent_engine_name = client.runtimes.create().api_resource.name

# Option 1: Managed Code Execution sandbox (<1s, 14d rolling TTL, zero network)
root_agent = Agent(
    model="gemini-2.5-flash",
    name="gke_orchestrator_managed_sandbox",
    instruction="Use the code executor to analyze data. Never run pip install.",
    code_executor=AgentEngineSandboxCodeExecutor(
        agent_engine_resource_name=parent_engine_name,
    ),
)

# Option 2: Managed Shell / BYOC sandbox via client.sandboxes.create(...) + execute_bash(...)
```

### Pattern B: Agent Runtime Orchestrator -> GKE Agent Sandbox or Agent Substrate
- **When to use:** You want Agent Runtime's **SPIFFE Agent Identity**, **Managed Agent Gateway** (`AGENT_TO_ANYWHERE`), **3LO OAuth user consent**, and **native ADK `publish gemini`** (`:streamQuery`), **plus** an execution plane requiring **GPUs/TPUs** (`gVisor` Agent Sandbox), **full-kernel microVMs**, **workspaces > 7d/14d**, **`< 1s` cross-version restore** (Agent Substrate), or **> 1,000 sandboxes/region**.
- **How it works:**
  1. Expose GKE `sandbox-router` (or Agent Substrate Envoy ingress) on an internal **GKE Gateway API** load balancer inside your VPC.
  2. Attach a **PSC-I** (`--network-attachment`, minimum `/28` subnet) + **Cloud DNS peering** (`dns_peering_configs`) to your Agent Runtime at creation time.
  3. Inside Agent Runtime tool code, connect via `k8s-agent-sandbox` `SandboxGatewayConnectionConfig` (or Substrate API over private DNS).
- **Critical Constraints:**
  - **PSC-I is immutable** on an existing Agent Runtime — you must recreate the `ReasoningEngine` to change it.
  - Enabling **PSC-I or VPC-SC caps Agent Runtime `max_instances` at `100`** (down from `1,000`).
  - For Shared VPC host projects, grant `service-PROJECT_NUMBER@gcp-sa-aiplatform.iam.gserviceaccount.com` `roles/compute.networkUser` on the host project (and `roles/compute.networkAdmin` or custom `networkAttachments.{get,update}` + `regionOperations.get` role on the attachment project).

```python
# Provision Agent Runtime with PSC-I + private DNS peering to reach GKE Gateway API
remote_agent = client.runtimes.create(
    agent=local_agent,
    config={
        "psc_interface_config": {
            "network_attachment": "projects/PROJECT_ID/regions/asia-southeast1/networkAttachments/gke-bridge-na",
            "dns_peering_configs": [
                {
                    "domain": "sandbox.internal.",
                    "target_project": "NETWORK_PROJECT_ID",
                    "target_network": "YOUR_VPC",
                }
            ],
        },
    },
)
```

### Pattern C: Dual-Tier GKE Cluster (Agent Sandbox + Agent Substrate)
- **When to use:** A single GKE Standard (`>= 1.37`) cluster serves both high-density intermittent CPU coding agents (**Agent Substrate**) and GPU/TPU or custom-`PodSpec` sidecar agents (**Agent Sandbox**).
- **Mandatory Node-Pool Separation Rule:**
  - **Pool 1 (Agent Sandbox):** `--sandbox=type=gvisor` (or `--enable-nested-virtualization` + `microvm`), optional supported GPU/TPU accelerators (`gVisor` only). Carries the `sandbox.gke.io/runtime` taint.
  - **Pool 2 (Agent Substrate):** Non-E2 uniform x86 CPU machine family (`c4`/`n2`/`c3`), **GKE Sandbox DISABLED** (no `sandbox.gke.io/runtime` taint!), optional `--enable-nested-virtualization` or bare metal for microVM Workers, and Linux `inotify`/ARP sysctl tuning for `>~800` sandboxes/node.

### Pattern D: Self-Hosted GKE Agents + Managed Agent Platform State & Anomaly Detection
- Keep **Managed Sessions**, **Memory Bank**, and **Agent Anomaly Detection** even when self-hosting your agent on GKE:
  - **Sessions (`agents-cli` or ADK):** Scaffold with `--session-type agent_platform_sessions` or pass `--session_service_uri=agentengine://AGENT_ENGINE_ID` (`VertexAiSessionService`).
  - **Memory Bank:** Pass `--memory_service_uri=agentengine://$MEMORY_BANK_ID` to `adk deploy gke` or instantiate `VertexAiMemoryBankService(project=..., location=..., agent_engine_id=...)`.
  - **Agent Anomaly Detection (`GKE_WORKLOAD`, Preview):** Supported for GKE agents built with **ADK Python `>= 2.1.0`** exporting OTel traces to Cloud Trace and logs to a Cloud Logging bucket (with Log Analytics enabled) in the same US/EU/global location as the `AgentAnomalyDetectionScope` (requires allowlisted opt-in).

---

## 2. Self-Hosted ADK on GKE (`adk deploy gke` vs. Manual Python & Go)

### 2.1 Automated Python Deployment (`adk deploy gke`)

```bash
# Prerequisite: bind default/default KSA to roles/aiplatform.user via WIF (otherwise model calls fail 403!)
gcloud projects add-iam-policy-binding "projects/${GOOGLE_CLOUD_PROJECT}" \
  --role=roles/aiplatform.user \
  --member="principal://iam.googleapis.com/projects/${GOOGLE_CLOUD_PROJECT_NUMBER}/locations/global/workloadIdentityPools/${GOOGLE_CLOUD_PROJECT}.svc.id.goog/subject/ns/default/sa/default" \
  --condition=None

# Deploy (Python ONLY — Go must deploy manually via gcloud builds submit + kubectl; Bangkok GKE default)
adk deploy gke \
  --project="${GOOGLE_CLOUD_PROJECT}" \
  --cluster_name="${CLUSTER_NAME}" \
  --region="${GKE_LOCATION:-asia-southeast3}" \
  --service_type=ClusterIP \
  --with_ui \
  --log_level=info \
  ./my_coding_agent
```

- **Key Gotchas:**
  1. **Default `ClusterIP`:** Service is cluster-internal unless you pass `--service_type=LoadBalancer` (test via `kubectl port-forward svc/adk-default-service-name 8080:80`).
  2. **UI Omitted by Default:** Pass `--with_ui` to include the ADK web UI.
  3. **Python SQLite Readonly Container Bug:** If `main.py` uses `sqlite+aiosqlite:///./sessions.db` and you ran the agent locally before building, copying `sessions.db` into a non-root container throws `OperationalError: attempt to write a readonly database`. Exclude `sessions.db*` in `.dockerignore` (or use `VertexAiSessionService` / Cloud SQL in prod).
  4. **Go vs. Python ADK REST API Delta:**

| Endpoint / Body | Python ADK (`get_fast_api_app`) | Go ADK (`full.NewLauncher()`, `google.golang.org/adk/v2/...`) |
|---|---|---|
| **Path Prefix** | Root (`/list-apps`, `/apps/...`, `/run_sse`) | `/api` prefix (`/api/list-apps`, `/api/apps/...`, `/api/run_sse`; override via `-path_prefix ""`) |
| **JSON Field Casing** | **`snake_case`** (`app_name`, `user_id`, `session_id`, `new_message`) | **`camelCase`** (`appName`, `userId`, `sessionId`, `newMessage`) |
| **GKE CLI Support** | `adk deploy gke` + manual `gcloud`/`kubectl` | Manual `gcloud builds submit` + `kubectl apply` only |

```bash
# Manual GKE deployment WIF binding (dedicated adk-agent-sa KSA — preferred over default/default)
kubectl create serviceaccount adk-agent-sa
gcloud projects add-iam-policy-binding "projects/${GOOGLE_CLOUD_PROJECT}" \
  --role=roles/aiplatform.user \
  --member="principal://iam.googleapis.com/projects/${GOOGLE_CLOUD_PROJECT_NUMBER}/locations/global/workloadIdentityPools/${GOOGLE_CLOUD_PROJECT}.svc.id.goog/subject/ns/default/sa/adk-agent-sa" \
  --condition=None

# Verify REST endpoint (Python: /run_sse + snake_case; Go: /api/run_sse + camelCase)
curl -X POST "${APP_URL}/run_sse" -H "Content-Type: application/json" \
  -d '{"app_name":"capital_agent","user_id":"u1","session_id":"s1","new_message":{"role":"user","parts":[{"text":"Hello"}]},"streaming":false}'
```

---

## 3. `agents-cli` (`v1.15.0`) Multi-Target Graduation & Asymmetries

### 3.1 Progressive Graduation Workflow (`agent_runtime` -> `cloud_run` / `gke`)

```bash
# 1. Start fast on Agent Runtime in Singapore (or cloud_run for Eventarc/IAP/WebSockets)
agents-cli create coding-agent --agent adk_python -d agent_runtime --region asia-southeast1 --bq-analytics
# Run Terraform infra BEFORE first deploy if you want GCS/BQ prompt-response logging
agents-cli infra single-project --apply --project "${DEV_PROJECT_ID}"
agents-cli eval run
agents-cli deploy --project "${DEV_PROJECT_ID}" --no-wait --no-confirm-project
agents-cli deploy --status

# 2. Graduate the SAME ADK codebase + eval suite to GKE when hitting quotas/GPU/K8s triggers
agents-cli scaffold enhance . --deployment-target gke
agents-cli deploy --project "${DEV_PROJECT_ID}" --dry-run   # Read-only API/cluster/IAM preflight!
agents-cli deploy --project "${DEV_PROJECT_ID}" --cluster-name "${CLUSTER_NAME}"
```

### 3.2 Complete `agents-cli` Target Asymmetry Matrix (Avoid Silent Failures)

| Feature / Operation | **`agent_runtime`** | **`cloud_run`** | **`gke`** |
|---|---|---|---|
| **Deploy Command Behavior** | Builds container from `Dockerfile` (5–10 min; use `--no-wait` + `--status`) or deploys `--image`. No `gcloud` deploy CLI exists. | Wraps `gcloud run deploy` (`--no-allow-unauthenticated` always on). | Runs Terraform + `gcloud builds submit` + `kubectl set image` (defaults cluster name to project name; override `--cluster-name`). |
| **Sizing Flags (`--cpu`, `--memory`, `--min/max-instances`, `--concurrency`)** | Supported (`1` vCPU, `4Gi`, `0..10`, `8` dev defaults; `service.tf` pins `min_instances=1`). | Supported (+ `--timeout` up to `3600s`, default `300s`). | **ALL REJECTED.** Size pods & HPA directly in `deployment/terraform/`. |
| **Networking & Gateway Flags** | `--network-attachment`, `--dns-peering-*`, `--agent-gateway-egress/ingress`, `--key` (CMEK, create-only). | `--iap`, `--ingress internal\|internal-and-cloud-load-balancing`. | Managed in `deployment/terraform/` only. |
| **Identity (`--agent-identity`)** | Default on (SPIFFE). Opt out at scaffold (`--agent-runtime-identity-default service_account`). | Default on (**irreversible** without deleting service!). Opt out via `--cloud-run-identity-default service_account`. | **REJECTED.** Uses Terraform `app_sa` + WIF. |
| **Secret Manager Grant** | Grant `roles/secretmanager.secretAccessor` to `gcp-sa-aiplatform-re` (and `gcp-sa-aiplatform` for TF `secret_env` with `AGENT_IDENTITY`). `--secrets` **replaces** existing secrets! | Grant to service's recorded SA (`app_sa`/compute SA) **even with Agent Identity**. `--secrets` is additive. | Grant `roles/secretmanager.secretAccessor` to `app_sa` in Terraform. `--secrets` flag unsupported. |
| **Env Vars Reset Behavior** | Additive (`--env-vars`); supports `--remove-env-vars` & `--clear-env-vars`. | Additive (`--env-vars`); supports `--remove-env-vars` & `--clear-env-vars`. | Deploy **without `--image` resets env vars to Terraform's**; put lasting vars in `.env` or Terraform. `--clear-env-vars` unsupported. |
| **Rollback Mechanism** | **No `agents-cli` rollback** — redeploy via Git/CLI, or use `v1beta1` `trafficSplitManual` via SDK/REST (note: Gateway change irreversibly archives prior revisions). | `gcloud run services update-traffic SVC --to-revisions=REV=100 --region=REG`. | `kubectl rollout undo deployment/NAME -n NS`. |
| **`publish gemini` Mode** | **ADK** (native `:streamQuery`, supports `--authorization-id` 3LO OAuth; LangChain/Claude refused on `agent_runtime`). | **A2A ONLY** (`/a2a/{app}/.well-known/agent-card.json` Python; `/.well-known/agent-card.json` Go; grant `roles/run.servicesInvoker` to `gcp-sa-discoveryengine`). | **A2A ONLY** (requires reachable HTTPS agent-card URL). |
| **Irreversible / Ordering Traps** | (1) Never run `infra single-project --apply` *after* imperative `deploy`; (2) Cannot switch existing engine between source build and `--image`; (3) First deploy with Agent Identity starts image once *before* env vars/secrets attach. | Cannot disable Agent Identity after creation without deleting service. | `--service-name` rejected (names owned by Terraform). |

- **Python vs. Go OTel Capture Trap (All Targets):** In ADK Python, `OTEL_INSTRUMENTATION_GENAI_CAPTURE_MESSAGE_CONTENT` **requires enum strings** (`EVENT_ONLY`, `NO_CONTENT`, `SPAN_ONLY`, `SPAN_AND_EVENT` — passing `"true"` silently falls back to `NO_CONTENT`). In ADK Go, it reads a **boolean** (`"1"` or `"true"` — passing `"EVENT_ONLY"` elides all prompt/response content!).

---

## 4. Migration Checklists & Verification Steps

### Migrating `agent_runtime` -> `gke` (Without Losing State or Governance)
1. **Preserve State:** Keep existing `VertexAiSessionService` / `VertexAiMemoryBankService` by configuring `--session-type agent_platform_sessions` and binding GKE `app_sa` via WIF to `roles/aiplatform.user`.
2. **Preserve Sandbox Isolation:** Either keep Managed Sandboxes via **Pattern A** (fastest migration, zero gVisor pool ops) or install GKE Agent Sandbox (`v1.0.6` + `secure-sandbox-policy` VAP + `SandboxWarmPool` + Dataplane V2 label exclusion) and switch ADK `code_executor` from `AgentEngineSandboxCodeExecutor` to `GkeCodeExecutor(executor_type="sandbox")`.
3. **Preserve Governance & Publishing:** Replace Managed Agent Gateway with self-managed GKE Gateway API + Secure Web Proxy / `EgressPolicy`; re-register with Gemini via `agents-cli publish gemini` in **A2A mode**; enroll GKE deployment in Agent Anomaly Detection (`GKE_WORKLOAD`, ADK Python `>= 2.1.0`).
4. **Verify End-to-End:**
   ```bash
   # Preflight GKE Terraform + Cloud Build + kubectl permissions (zero mutations)
   agents-cli deploy --project "${PROJECT_ID}" --dry-run

   # Verify deployed GKE service & WIF Gemini call
   kubectl rollout status deployment/"${DEPLOYMENT_NAME}" -n "${NAMESPACE}"
   agents-cli run --url "${SERVICE_URL}" --mode a2a "Verify sandbox and session connectivity"
   ```
