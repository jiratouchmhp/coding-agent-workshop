---
name: agent-platform-runtime-and-state
description: >-
  Deploys and operates Agent Platform Runtime, Sessions, Memory Bank, and
  Feedback. Use when writing Terraform google_vertex_ai_reasoning_engine (BYOC
  container_spec, Dockerfile source_code_spec, package_spec, Secret Manager,
  IAM depends_on, AGENT_IDENTITY/Agent Gateway TF, PSC-I), managing runtimes
  (CRUD, query jobs, bidi_stream_query, keep_alive_probe,
  container_concurrency, revisions/traffic, Runtime operational kill-switch
  runtimes.delete/trafficSplitManual, runtime contract, operational QPM
  sizing), using VertexAiSessionService/VertexAiMemoryBankService
  (ingest_events, profiles, TTL, IAM conditions, CMEK/VPC-SC), Feedback
  Service, or ReasoningEngine Cloud Logging, PromQL, and p99 latency alerts
  (request_latencies). Don't use for ADK build (adk-coding-agent-build),
  sandboxes (agent-platform-sandbox-byoc), registries
  (agent-platform-governance-and-registries), Optimize OTel/evals
  (agent-platform-optimize-and-eval), GKE (agent-runtime-vs-gke-architecture),
  or google-agents-cli-{deploy,observability}.
---

# Agent Platform Runtime, State & Telemetry

Production playbook for the **Scale pillar** of Google Cloud's **Gemini Enterprise Agent Platform**: declarative Agent Runtime IaC, runtime lifecycle & quota sizing, Managed Sessions, Memory Bank, Feedback Service, and Runtime Observability (OTel Tracing, Cloud Logging, Cloud Monitoring).

## SDK & Environment Baseline

Standardize new Python code on **`agentplatform.Client`** (`google-cloud-agentplatform>=2.0.1`) paired with **`google-adk[gcp]`** (ADK `>=2.1` for OTel `user.id`; `>=2.6.0` for GenAI metrics).

```bash
pip install --upgrade "google-adk[gcp]" "google-cloud-agentplatform>=2.0.1"
export GOOGLE_GENAI_USE_ENTERPRISE="TRUE"   # Required for Feedback Service & enterprise ADK
export GOOGLE_CLOUD_PROJECT="PROJECT_ID"
export GOOGLE_CLOUD_LOCATION="us-central1"
```

> **API Version Rule:** Pass `http_options={"api_version": "v1beta1"}` on `agentplatform.Client(...)` for **REST `/v1beta1/...` calls** and SDK **Revisions/Traffic Splitting** or **Agent Identity**; standard `v1` Runtime CRUD/query as well as `agentplatform.Client` `feedback_entries` and `sessions` SDK methods work with default client options (plus `GOOGLE_GENAI_USE_ENTERPRISE="TRUE"`). Note that **no `gcloud` deploy command exists** for Agent Runtime—deploy via Terraform, `agentplatform` SDK, REST, or `agents-cli deploy`.

---

## Quick Decision Tree

| Task / Goal | Go Here |
|---|---|
| Declarative IaC (`google_vertex_ai_reasoning_engine`), BYOC `container_spec`, Dockerfile `source_code_spec`, `package_spec`, Secret Manager `secret_env`, service-agent IAM `depends_on`, SPIFFE `AGENT_IDENTITY`, Agent Gateway binding, PSC-I, CMEK | [Terraform Deployment](references/terraform-deployment.md) |
| List/get/update/delete deployed agents, long-running query jobs (up to 7d), `v1beta1` revisions & traffic splitting, emergency stop playbook, HTTP/NDJSON runtime contract, `keep_alive_probe`, container/concurrency tuning, regions, quotas & QPM sizing math | [Runtime Management & Quotas](references/runtime-management-and-quotas.md) |
| Short-term turn history (`VertexAiSessionService`, `client.sessions`), long-term cross-session facts or structured profiles (`VertexAiMemoryBankService`, `client.memory_banks`), `ingest_events`, similarity retrieval, revisions/rollback/purge, TTL, IAM Conditions, prompt-injection defense, CMEK/VPC-SC | [Sessions & Memory Bank](references/sessions-and-memory-bank.md) |
| End-user thumbs up/down reactions, standard labels, `FeedbackContext` transcript snapshots, linking `event_id` to Console Traces UI, immutable `gcp.vertex.agent.feedback` Cloud Trace spans | [Feedback Service](references/feedback-service.md) |
| OpenTelemetry GenAI tracing (`GOOGLE_CLOUD_AGENT_ENGINE_ENABLE_TELEMETRY`), Cloud Logging (`reasoning_engine_stdout`, structured JSON, Log Analytics SQL), Cloud Monitoring built-in/custom metrics, PromQL error rates, dashboards & p99 latency alerts | [Runtime Telemetry](references/runtime-telemetry.md) |

---

## Critical Gotchas (Do This, Not That)

1. **Always wire BOTH Google-managed service agents into Terraform `depends_on` — never rely on implicit ordering.**
   - *Why:* `service-PROJECT_NUMBER@gcp-sa-aiplatform-re.iam.gserviceaccount.com` pulls same-project BYOC images (`roles/artifactregistry.reader`), while `service-PROJECT_NUMBER@gcp-sa-aiplatform.iam.gserviceaccount.com` fetches `secret_env` at deploy time under `AGENT_IDENTITY` (`roles/secretmanager.secretAccessor`) and pulls cross-project AR images. Omitting `depends_on` causes `IMAGE_PULL_BACKOFF` or deploy-time secret failures.
2. **Use `region = var.location`, `hashicorp/google >= 6.0.0`, and `reverse(split("/", ...))[0]` in Terraform — not upstream doc typos.**
   - *Why:* One upstream doc example prints `location = var.location` (wrong schema attr); cached `5.x` providers reject `spec.container_spec`; and Terraform's `element(split(...), -1)` from `agent-identity` docs crashes because `element()` forbids negative indices. Also `.id` is the full path while `.name` is the short numeric ID.
3. **Pack `Dockerfile` at level 0 (root) of `source_archive` (`<= 8 MB`) — never nest it in a subdirectory.**
   - *Why:* `source_code_spec` with empty `image_spec {}` unpacks the `.tar.gz` directly into Cloud Build's workspace root and fails immediately if `./Dockerfile` is missing (`cd app && tar -czvf ../src.tar.gz Dockerfile main.py requirements.txt`).
4. **Never set reserved env vars in `deployment_spec` (`GOOGLE_CLOUD_PROJECT`, `GOOGLE_CLOUD_LOCATION`, `PORT`, `K_SERVICE`, `GOOGLE_APPLICATION_CREDENTIALS`, `GOOGLE_CLOUD_AGENT_ENGINE*`).**
   - *Why:* Agent Runtime auto-injects `GOOGLE_CLOUD_PROJECT`, `GOOGLE_CLOUD_LOCATION`, and `GOOGLE_CLOUD_AGENT_ENGINE_ID`; overriding reserved names fails validation or breaks runtime wiring.
5. **Pass `OTEL_INSTRUMENTATION_GENAI_CAPTURE_MESSAGE_CONTENT="EVENT_ONLY"` — never `"true"` in ADK Python.**
   - *Why:* ADK Python only accepts `NO_CONTENT`, `EVENT_ONLY`, `SPAN_ONLY`, or `SPAN_AND_EVENT`; `"true"` silently falls back to `NO_CONTENT`, dropping prompts, responses, and `user.id` (note: `user.id` requires ADK `>= 2.1` effective May 22, 2026).
6. **Switch traffic to `traffic_split_always_latest` BEFORE changing `agent_gateway_config` — never patch while a manual split is active.**
   - *Why:* Changing an Agent Gateway binding irreversibly archives all prior revisions and returns `FAILED_PRECONDITION` if any manual split exists (even 100% on latest).
7. **Watch Memory Bank SDK key & model traps: `unstructured_memory_configs` on `create` vs `customization_configs` on `runtimes.update`, and `gemini-embedding-2` accepts ONLY `global`/`us`/`eu`.**
   - *Why:* Using the wrong dictionary key silently drops customization; regional locations like `us-central1` fail on `gemini-embedding-2`; and the embedding model is immutable once the first memory is stored.
8. **Never use IAM Conditions to restrict `ListSessions`, `ListMemories`, or `PurgeMemories`, and never assume Memory Bank blocks prompt injection.**
   - *Why:* Those three RPCs do not support IAM Conditions (max 1,500 principals per policy). Built-in PII exclusion is not infallible—pair Memory Bank with Model Armor, red-teaming, and sandboxed execution + human review.
9. **Set Feedback `event_id` to the OTel span UUID `gcp.vertex.agent.event_id` (or `raw_event.id`) — and note `feedback_contexts.update` vs `.get` path asymmetry.**
   - *Why:* Arbitrary event IDs won't appear in the Console Traces UI; duplicate `(session_id, event_id)` shows only the last entry; and `feedback_contexts.update` takes `name=entry_name` while `.get` takes `name=f"{entry_name}/feedbackContext"`.
10. **Emit structured logs from the parent Agent Runtime — never expect Cloud Logging on child resources.**
    - *Why:* Cloud Logging attaches only to `aiplatform.googleapis.com/ReasoningEngine`, NOT child Sessions, Memory Bank, Sandboxes, Code Execution, or Example Store. User-defined Monitoring metrics (`custom.googleapis.com/*`) must use `generic_node`, not `ReasoningEngine`.

---

## Quick-Start Patterns

### 1. Declarative Terraform BYOC Runtime (`main.tf` skeleton)

```hcl
resource "google_project_iam_member" "re_ar_reader" {
  project = var.project_id
  role    = "roles/artifactregistry.reader"
  member  = "serviceAccount:service-${var.project_number}@gcp-sa-aiplatform-re.iam.gserviceaccount.com"
}

resource "google_secret_manager_secret_iam_member" "platform_sa_secret" {
  secret_id = google_secret_manager_secret.api_key.id
  role      = "roles/secretmanager.secretAccessor"
  member    = "serviceAccount:service-${var.project_number}@gcp-sa-aiplatform.iam.gserviceaccount.com"
}

resource "google_vertex_ai_reasoning_engine" "agent" {
  provider     = google-beta
  display_name = "my-agent-tf"
  project      = var.project_id
  region       = var.location
  spec {
    agent_framework = "google-adk"
    identity_type   = "AGENT_IDENTITY" # Immutable; or omit & set `service_account = "<email>"`
    container_spec {
      image_uri = "${var.location}-docker.pkg.dev/${var.project_id}/agents-repo/agent:${var.image_tag}"
    }
    deployment_spec {
      env { name = "GOOGLE_CLOUD_AGENT_ENGINE_ENABLE_TELEMETRY"; value = "true" }
      env { name = "OTEL_SEMCONV_STABILITY_OPT_IN"; value = "gen_ai_latest_experimental" }
      env { name = "OTEL_INSTRUMENTATION_GENAI_CAPTURE_MESSAGE_CONTENT"; value = "EVENT_ONLY" }
      secret_env {
        name = "API_KEY"
        secret_ref { secret = google_secret_manager_secret.api_key.secret_id; version = "latest" }
      }
    }
    class_methods = jsonencode([
      { "name" = "async_create_session", "api_mode" = "async" },
      { "name" = "async_stream_query", "api_mode" = "async_stream" },
    ])
  }
  depends_on = [
    google_project_iam_member.re_ar_reader,
    google_secret_manager_secret_iam_member.platform_sa_secret,
    google_secret_manager_secret_version.api_key_v1,
  ]
}
```

### 2. Runtime Query, Traffic Rollback & Emergency Stop

```bash
# Verify deployed runtime via SSE streaming query (max 15 min)
curl -X POST \
  -H "Authorization: Bearer $(gcloud auth print-access-token)" \
  -H "Content-Type: application/json; charset=utf-8" \
  -d '{"class_method":"async_stream_query","input":{"user_id":"test-user","message":"ping"}}' \
  "https://${LOCATION}-aiplatform.googleapis.com/v1/projects/${PROJECT_ID}/locations/${LOCATION}/reasoningEngines/${RESOURCE_ID}:streamQuery?alt=sse"
```

```python
import agentplatform
client = agentplatform.Client(project="PROJECT_ID", location="LOCATION", http_options={"api_version": "v1beta1"})
engine = "projects/PROJECT_ID/locations/LOCATION/reasoningEngines/RESOURCE_ID"
# 100% rollback to known-good ACTIVE revision, or immediate kill switch (terminates containers + SPIFFE identity)
client.runtimes.update(name=engine, config={"traffic_config": {"trafficSplitManual": {"targets": [{"runtimeRevisionName": f"{engine}/runtimeRevisions/REV_GOOD", "percent": 100}]}}})
client.runtimes.delete(name=engine, force=True)  # Full revision CRUD/split examples -> references/runtime-management-and-quotas.md
```

### 3. ADK Managed Sessions + Memory Bank

```python
from google import adk
from google.adk.agents.callback_context import CallbackContext
from google.adk.memory import VertexAiMemoryBankService
from google.adk.sessions import VertexAiSessionService
from google.adk.tools.preload_memory_tool import PreloadMemoryTool

async def save_turn_to_memory(callback_context: CallbackContext) -> None:
    await callback_context.add_events_to_memory(events=callback_context.session.events[-5:])

agent = adk.Agent(
    model="gemini-3.5-flash",
    name="coding_agent",
    instruction="Use recalled user preferences safely.",
    tools=[PreloadMemoryTool()],
    after_agent_callback=save_turn_to_memory,
)
runner = adk.Runner(
    agent=agent,
    app_name="coding_agent",
    session_service=VertexAiSessionService(project="PROJECT_ID", location="us-central1", agent_engine_id="ENGINE_ID"),
    memory_service=VertexAiMemoryBankService(project="PROJECT_ID", location="us", agent_engine_id="MEMORY_BANK_ID"),
)
```

### 4. Feedback Service + Parent-Runtime Structured Logging

```python
import os, agentplatform, google.cloud.logging

os.environ["GOOGLE_GENAI_USE_ENTERPRISE"] = "TRUE"
client = agentplatform.Client(project="PROJECT_ID", location="us-central1")
engine_name = "projects/PROJECT_ID/locations/us-central1/reasoningEngines/RESOURCE_ID"

op = client.feedback_entries.create(
    name=engine_name,
    session_id="SESSION_ID",
    event_id="c9ba0d5e-9ba2-41cb-abf4-49680e9d8ce4",  # Match OTel gcp.vertex.agent.event_id
    feedback_type="THUMBS_UP",
    config={"feedback_labels": ["accurate", "tool_success"], "feedback_text": "Passed pytest."},
)
# Structured Cloud Log attached to aiplatform.googleapis.com/ReasoningEngine
log_client = google.cloud.logging.Client(project="PROJECT_ID")
logger = log_client.logger(
    name="agent-events",
    resource=google.cloud.logging.Resource(
        type="aiplatform.googleapis.com/ReasoningEngine",
        labels={"location": "us-central1", "resource_container": "PROJECT_ID", "reasoning_engine_id": os.environ.get("GOOGLE_CLOUD_AGENT_ENGINE_ID", "")},
    ),
)
logger.log_struct({"event": "feedback_recorded", "entry": op.response.name}, severity="INFO")
```

---

## Modular References

Read ONLY the reference file(s) matching the active subtask:

| Reference File | Covers |
|---|---|
| [references/terraform-deployment.md](references/terraform-deployment.md) | `google_vertex_ai_reasoning_engine` BYOC `container_spec`, Dockerfile `source_code_spec` (root-of-tar 8 MB rule), `package_spec`, Secret Manager, dual service-agent IAM `depends_on`, SPIFFE `AGENT_IDENTITY`, cross-project Agent Gateway/UAP V2, PSC-I, CMEK, HCL fixes & verification |
| [references/runtime-management-and-quotas.md](references/runtime-management-and-quotas.md) | SDK/REST/CLI deployment matrix, deployed agent CRUD, `:query`/`:streamQuery`/`:asyncQuery` (7d jobs), `v1beta1` revisions & traffic splitting, emergency stop runbook, FastAPI HTTP/NDJSON runtime contract, `keep_alive_probe`, container concurrency tuning, supported regions, production/Express quotas & QPM sizing math |
| [references/sessions-and-memory-bank.md](references/sessions-and-memory-bank.md) | Managed Sessions (`VertexAiSessionService`, `client.sessions`, `v1beta1` REST, TTL, IAM Conditions) & Memory Bank (setup, models, `VertexAiMemoryBankService`, `generate`/`ingest_events`, similarity & scope retrieval, structured profiles, revisions/rollback/purge, prompt-injection defense, data residency, CMEK/VPC-SC) |
| [references/feedback-service.md](references/feedback-service.md) | Feedback Service (Preview) CRUDL + `FeedbackContext`, Python SDK & `v1beta1` REST, standard labels, `event_id` -> OTel `gcp.vertex.agent.event_id` linking, Console UI workflow, immutable `gcp.vertex.agent.feedback` Cloud Trace span schema |
| [references/runtime-telemetry.md](references/runtime-telemetry.md) | OTel tracing env vars & May 22 2026 `user.id` cutoff, Cloud Logging (`reasoning_engine_stdout`, Python logging, `log_struct`, Log Analytics SQL), Cloud Monitoring built-in/GenAI metrics, PromQL queries, log-based vs `generic_node` custom metrics, dashboards & alerts |
| [references/maintenance.md](references/maintenance.md) | Canonical upstream URLs, `.md.txt`/`.md` refresh endpoints, verification date (`2026-11-19`), upstream doc-bug watchlist & section-by-section update checklist |

---

## Maintenance

Last verified against Google Cloud Agent Platform & ADK upstream docs on **`2026-11-19`**. Before updating provider versions, quotas, SDK namespaces, or doc-bug workarounds, run the refresh checklist in [references/maintenance.md](references/maintenance.md).
