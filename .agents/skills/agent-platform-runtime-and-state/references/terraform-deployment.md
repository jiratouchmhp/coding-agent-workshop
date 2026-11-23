# Terraform Deployment for Agent Runtime (`google_vertex_ai_reasoning_engine`)

Declarative Infrastructure-as-Code (IaC) reference for provisioning **Gemini Enterprise Agent Platform Agent Runtime** instances via `google_vertex_ai_reasoning_engine`.

---

## 1. Prerequisites & Provider Floor

- **Terraform:** `>= 1.5.0`
- **Providers:**
  - `hashicorp/google >= 6.0.0` (GA). *Trap:* Upstream docs print `>= 5.28.0`, but cached `5.x` provider builds reject `spec.container_spec` with `Unsupported block type`. Always pin `>= 6.0.0`.
  - `hashicorp/google-beta >= 6.0.0` — **required** for `identity_type = "AGENT_IDENTITY"` and `agent_gateway_config`.
- **Required GCP APIs:** `aiplatform.googleapis.com`, `artifactregistry.googleapis.com`, `cloudbuild.googleapis.com` (plus `secretmanager.googleapis.com`, `telemetry.googleapis.com`, `logging.googleapis.com`).
- **Deployer (Human / CI/CD SA) IAM Roles:**
  - `roles/aiplatform.user` or `roles/aiplatform.admin` (`CreateReasoningEngine`, `UpdateReasoningEngine`, `DeleteReasoningEngine`)
  - `roles/iam.serviceAccountUser` on any attached custom runtime service account
  - `roles/artifactregistry.writer` (for pushing BYOC images)
- **Authentication:** `gcloud auth application-default login` (or Workload Identity Federation in CI/CD).
- **Do NOT mix imperative `agents-cli deploy` and Terraform on the same instance:** Terraform owns the full `ReasoningEngine` spec (SA, `deployment_spec`, env vars). Either manage the engine entirely in Terraform or keep imperative `agents-cli deploy --update-env-vars`.

> **Zero-Docker Deployment Paths:** Local Docker is **strictly optional** for all Agent Runtime deployments. Smoke-test your ASGI app locally in pure Python (`uvicorn main:app --host 127.0.0.1 --port 8080`), then choose any zero-Docker deployment path:
> 1. **Path 1 (`container_spec` + Cloud Build):** Build and push remotely with `gcloud builds submit --region="${BUILD_LOCATION}"` (zero local Docker), then deploy via Terraform `container_spec`.
> 2. **Path 2 (`source_code_spec` + empty `image_spec {}` tarball):** Inline-pack a level-0 `.tar.gz` (`<= 8 MB`) containing `./Dockerfile` — Agent Runtime invokes Cloud Build automatically (**zero local Docker AND zero manual Artifact Registry push**).
> 3. **Imperative CLI (`agents-cli deploy`):** Remote Cloud Build/deploy alternative when not managing the instance in Terraform.

> **Bangkok-First Regional Strategy (`asia-southeast3` Default -> `asia-southeast1` Fallback Only Where Unavailable -> `global` for Frontier Gemini 4):** Aim for **Bangkok (`asia-southeast3`)** first for **Cloud Build (`BUILD_LOCATION=asia-southeast3`)**, **Artifact Registry (`AR_LOCATION=asia-southeast3`)**, **Secret Manager**, and **Agent Registry A2A/MCP discovery (`AGENT_REGISTRY_LOCATION=asia-southeast3`; standalone skills use `global`)**. Fall back to **Singapore (`GOOGLE_CLOUD_LOCATION=asia-southeast1`)** only because Agent Runtime (`google_vertex_ai_reasoning_engine`), Managed Sandboxes, Managed Sessions, Memory Bank, and Agent Gateway are not yet launched in Bangkok. Route Frontier Gemini 4 models (**`model_name="gemini-4-hydrogen"`**, **`reasoning_model_name="gemini-4-neon"`**, **`thinking_level="MEDIUM"`**, `google-genai>=2.34.0`) to **`model_location="global"`** via ADK `Gemini(client_kwargs=...)` — or use **`gemini-4-argon`** on **`asia-southeast1`** for strict regional inference residency (replacing retired `gemini-2.5-flash`, Oct 20, 2026). Bake opt-in `/usr/local/bin/agy` (`ARG INSTALL_AGY_CLI=true`) into the Agent Runtime container and authenticate exclusively via **`AGY_ADC_AUTH=true`** + `AGY_CLI_DISABLE_AUTO_UPDATE=true` on the Custom SA (`coding-agent-runtime-sa`, **never** personal OAuth!). **Empirically verified:** Singapore Agent Runtime (and Singapore BYOC Sandboxes) pull cleanly from Bangkok Artifact Registry (`asia-southeast3-docker.pkg.dev`) — **no second Singapore AR repository is required**. Keep `var.location` (Runtime region) decoupled from `var.model_location`, `var.ar_location`, and `var.agent_registry_location` in Terraform.

---

## 2. Service Agent IAM Matrix & `depends_on` Race-Condition Rule

> **CRITICAL:** You MUST declare IAM bindings for the required Google-managed service agents **and** list them in `depends_on = [...]` on `google_vertex_ai_reasoning_engine`. Without `depends_on`, pod provisioning races ahead of IAM propagation and fails with `IMAGE_PULL_BACKOFF` or Secret Manager permission errors.

| Service Agent | Email Format | When Required in `depends_on` | Required Role(s) |
|---|---|---|---|
| **1. Agent Runtime Service Agent** | `service-${var.project_number}@gcp-sa-aiplatform-re.iam.gserviceaccount.com` | **Always for BYOC `container_spec`** (pulls same-project AR image). Also required for CMEK (`roles/cloudkms.cryptoKeyEncrypterDecrypter`), async query jobs (`roles/storage.objectCreator`/`roles/storage.objectViewer`), and `agents-cli` Secret Manager access. | `roles/artifactregistry.reader` (project or AR repository) |
| **2. Agent Platform Service Agent** | `service-${var.project_number}@gcp-sa-aiplatform.iam.gserviceaccount.com` | **Required when:** (a) referencing `secret_env` with `identity_type = "AGENT_IDENTITY"` (deploy-time secret fetch); (b) pulling a BYOC image from a **cross-project** AR repo; (c) binding a **cross-project** Agent Gateway (`ar_agw_cross_project_sa`); (d) attaching a cross-project custom SA (`roles/iam.serviceAccountTokenCreator`); (e) Shared VPC PSC-I (`roles/compute.networkUser` on host project + `roles/compute.networkAdmin` on network attachment project). | `roles/secretmanager.secretAccessor` / `roles/artifactregistry.reader` / `ar_agw_cross_project_sa` / `roles/compute.networkUser` |
| **3. Custom Runtime SA** *(if not using `AGENT_IDENTITY`)* | `google_service_account.agent_runtime_sa.email` | When using `service_account = ...` with `secret_env` or telemetry/Vertex/sandbox APIs. | `roles/secretmanager.secretAccessor`, `roles/aiplatform.user`, `roles/logging.logWriter`, `roles/cloudtrace.agent`, `roles/telemetry.tracesWriter`, `roles/monitoring.metricWriter` |
| **4. Agent Sandbox Service Agent** *(if agent spawns BYOC sandboxes)* | `service-${var.project_number}@gcp-sa-vertex-sandbox.iam.gserviceaccount.com` | When the runtime creates BYOC `SandboxEnvironmentTemplate` instances. | `roles/artifactregistry.reader` (on sandbox AR repo) |

---

## 3. Path 1 — BYOC Prebuilt Container (`container_spec`)

Use `container_spec` when you need custom system libraries, deterministic supply-chain builds, multi-language runtimes, or faster deploy/cold-start latency.

### Build & Push Image (Zero-Docker Cloud Build Primary Path)

Smoke-test the FastAPI runtime locally without Docker (`uvicorn main:app --host 127.0.0.1 --port 8080 && curl -sf http://127.0.0.1:8080/`), then build and push remotely via **Cloud Build** (local Docker is strictly optional):

```bash
export PRIMARY_REGION="${PRIMARY_REGION:-asia-southeast3}"       # Bangkok default region
export LOCATION="${GOOGLE_CLOUD_LOCATION:-asia-southeast1}"      # Singapore fallback (Agent Runtime not yet in Bangkok)
export AR_LOCATION="${AR_LOCATION:-${PRIMARY_REGION}}"           # Bangkok AR (empirically verified with SG Agent Runtime & Sandboxes!)
export BUILD_LOCATION="${BUILD_LOCATION:-${PRIMARY_REGION}}"     # Bangkok remote Cloud Build (zero local Docker)
export IMAGE_URI="${AR_LOCATION}-docker.pkg.dev/${PROJECT_ID}/${REPO_NAME}/agent-image:${IMAGE_TAG}"

# Primary (Zero-Docker): Remote Cloud Build (builds linux/amd64 in BUILD_LOCATION)
gcloud builds submit . \
  --region="${BUILD_LOCATION}" \
  --tag="${IMAGE_URI}" \
  --project="${PROJECT_ID}"

# Optional (Local Docker workstation only):
# gcloud auth configure-docker "${AR_LOCATION}-docker.pkg.dev" --quiet
# docker build --platform linux/amd64 -t "${IMAGE_URI}" .
# docker push "${IMAGE_URI}"
```

### `terraform/versions.tf`

```hcl
terraform {
  required_version = ">= 1.5.0"

  required_providers {
    google = {
      source  = "hashicorp/google"
      version = ">= 6.0.0"
    }
    google-beta = {
      source  = "hashicorp/google-beta"
      version = ">= 6.0.0"
    }
  }
}
```

### `terraform/variables.tf`

```hcl
variable "project_id" {
  type        = string
  description = "Google Cloud Project ID"
}

variable "project_number" {
  type        = string
  description = "Google Cloud Project Number (for Google-managed service agents)"
}

variable "location" {
  type        = string
  default     = "asia-southeast1"
  description = "Region for Agent Runtime deployment (Singapore asia-southeast1 fallback — Agent Runtime not yet in Bangkok)"
}

variable "ar_location" {
  type        = string
  default     = "asia-southeast3"
  description = "Region for Artifact Registry repo (Bangkok asia-southeast3 default — empirically verified with SG Agent Runtime & Sandboxes)"
}

variable "repository_name" {
  type        = string
  default     = "agents-repo"
  description = "Artifact Registry repository name"
}

variable "image_tag" {
  type        = string
  default     = "latest"
  description = "Container image tag"
}

variable "api_key_value" {
  type      = string
  sensitive = true
}
```

### `terraform/main.tf` (Dual Service Agent `depends_on` + Secrets + OTel)

```hcl
provider "google" {
  project = var.project_id
  region  = var.location
}

provider "google-beta" {
  project = var.project_id
  region  = var.location
}

locals {
  adk_class_methods = [
    { "name" = "get_session", "api_mode" = "" },
    { "name" = "list_sessions", "api_mode" = "" },
    { "name" = "create_session", "api_mode" = "" },
    { "name" = "delete_session", "api_mode" = "" },
    { "name" = "async_get_session", "api_mode" = "async" },
    { "name" = "async_list_sessions", "api_mode" = "async" },
    { "name" = "async_create_session", "api_mode" = "async" },
    { "name" = "async_delete_session", "api_mode" = "async" },
    { "name" = "async_add_session_to_memory", "api_mode" = "async" },
    { "name" = "async_search_memory", "api_mode" = "async" },
    { "name" = "stream_query", "api_mode" = "stream" },
    { "name" = "async_stream_query", "api_mode" = "async_stream" },
    { "name" = "streaming_agent_run_with_events", "api_mode" = "async_stream" },
  ]
}

# 1. Secret Manager Secret & Version (use `auto {}` or `user_managed { replicas { location = "asia-southeast3" } }` for Bangkok secret residency)
resource "google_secret_manager_secret" "api_key_secret" {
  secret_id = "agent-api-key"
  project   = var.project_id
  replication {
    auto {}
  }
}

resource "google_secret_manager_secret_version" "api_key_version" {
  secret      = google_secret_manager_secret.api_key_secret.id
  secret_data = var.api_key_value
}

# 2. SERVICE AGENT #1: Agent Runtime Service Agent (pulls BYOC image from AR)
resource "google_project_iam_member" "re_service_agent_ar_reader" {
  project = var.project_id
  role    = "roles/artifactregistry.reader"
  member  = "serviceAccount:service-${var.project_number}@gcp-sa-aiplatform-re.iam.gserviceaccount.com"
}

# 3. SERVICE AGENT #2: Agent Platform Service Agent (deploy-time secret fetch for AGENT_IDENTITY)
resource "google_secret_manager_secret_iam_member" "platform_service_agent_secret_accessor" {
  secret_id = google_secret_manager_secret.api_key_secret.id
  role      = "roles/secretmanager.secretAccessor"
  member    = "serviceAccount:service-${var.project_number}@gcp-sa-aiplatform.iam.gserviceaccount.com"
}

# Alternative to AGENT_IDENTITY: dedicated custom runtime SA (pass email only, NOT full URI)
# resource "google_service_account" "agent_runtime_sa" {
#   account_id   = "agent-runtime-sa"
#   display_name = "Agent Runtime Identity"
#   project      = var.project_id
# }
# resource "google_secret_manager_secret_iam_member" "runtime_sa_secret_accessor" {
#   secret_id = google_secret_manager_secret.api_key_secret.id
#   role      = "roles/secretmanager.secretAccessor"
#   member    = "serviceAccount:${google_service_account.agent_runtime_sa.email}"
# }

# 4. Agent Runtime Resource
resource "google_vertex_ai_reasoning_engine" "byoc_agent" {
  provider        = google-beta
  display_name    = "byoc_agent_tf"
  description     = "BYOC agent deployed via Terraform with dual service-agent IAM ordering"
  project         = var.project_id
  region          = var.location # MUST be `region`, NOT `location` (upstream doc typo on line 467)
  deletion_policy = "FORCE"      # Prevents HTTP 400 child-sessions failure on `terraform destroy`

  spec {
    agent_framework = "google-adk"
    identity_type   = "AGENT_IDENTITY" # Immutable at creation; required for agent_gateway_config
    # Or omit identity_type and set:
    # service_account = google_service_account.agent_runtime_sa.email

    container_spec {
      image_uri = "${var.ar_location}-docker.pkg.dev/${var.project_id}/${var.repository_name}/agent-image:${var.image_tag}"
    }

    deployment_spec {
      env {
        name  = "GOOGLE_CLOUD_AGENT_ENGINE_ENABLE_TELEMETRY"
        value = "true"
      }
      env {
        name  = "OTEL_SEMCONV_STABILITY_OPT_IN"
        value = "gen_ai_latest_experimental"
      }
      env {
        name  = "OTEL_INSTRUMENTATION_GENAI_CAPTURE_MESSAGE_CONTENT"
        value = "EVENT_ONLY"
      }
      env {
        name  = "GOOGLE_GENAI_USE_ENTERPRISE"
        value = "TRUE"
      }
      # CRITICAL TRAP: Vertex AI rejects empty-string `env { value = "" }` with HTTP 400
      # (`reasoning_engine.spec.deployment_spec.env[N].value: Required field is not set`).
      # Always gate optional env vars (such as SANDBOX_TEMPLATE_NAME) with `dynamic "env"`:
      dynamic "env" {
        for_each = var.sandbox_template_name != "" ? [var.sandbox_template_name] : []
        content {
          name  = "SANDBOX_TEMPLATE_NAME"
          value = env.value
        }
      }
      secret_env {
        name = "API_KEY"
        secret_ref {
          secret  = google_secret_manager_secret.api_key_secret.secret_id
          version = "latest"
        }
      }
    }

    class_methods = jsonencode(local.adk_class_methods)
  }

  depends_on = [
    google_project_iam_member.re_service_agent_ar_reader,
    google_secret_manager_secret_iam_member.platform_service_agent_secret_accessor,
    google_secret_manager_secret_version.api_key_version,
  ]
}
```

> **CRITICAL Empty-String `env` Trap (HTTP 400 on `terraform apply`):** Never emit an unconditional `env { name = "..."; value = var.optional_var }` when `var.optional_var` can default to `""`. Vertex AI validates every `deployment_spec.env` entry and aborts `ReasoningEngine` creation with `Error 400: reasoning_engine.spec.deployment_spec.env[N].value: Required field is not set`. Always wrap optional env vars in `dynamic "env"` with `for_each = var.optional_var != "" ? [var.optional_var] : []`!

### `terraform/outputs.tf` (Safe Short-ID Extraction & Dynamic SPIFFE Principal)

> **Verified Provider & HCL Traps:**
> 1. In `hashicorp/google`, `google_vertex_ai_reasoning_engine.<name>.id` returns the **full resource path** (`projects/{P}/locations/{L}/reasoningEngines/{ID}`), whereas `.name` returns the **short numeric ID**.
> 2. Upstream `scale/runtime/agent-identity` docs print `element(split("/", ...), -1)`, which **crashes Terraform** because `element()` rejects negative indices. Always use `reverse(split("/", ...))[0]`.

```hcl
locals {
  agent_resource_id = reverse(split("/", google_vertex_ai_reasoning_engine.byoc_agent.id))[0]

  # Dynamic SPIFFE Agent Identity principal (survives recreate in Terraform)
  # agent_identity_principal = "principal://agents.global.org-${var.organization_id}.system.id.goog/resources/aiplatform/projects/${var.project_number}/locations/${var.location}/reasoningEngines/${local.agent_resource_id}"
}

output "reasoning_engine_id" {
  value       = local.agent_resource_id
  description = "Short numeric ID of the deployed Agent Runtime instance"
}

output "reasoning_engine_resource_name" {
  value       = "projects/${var.project_id}/locations/${var.location}/reasoningEngines/${local.agent_resource_id}"
  description = "Canonical full resource name"
}
```

---

## 4. Path 2 — Zero-Docker & Zero-AR Dockerfile Build (`source_code_spec` + Empty `image_spec {}`)

Let Agent Runtime build your container automatically via Cloud Build from an inline `.tar.gz` archive — **zero local Docker daemon, zero manual Artifact Registry push, and zero GCS staging bucket required**.

### Root-of-Tar Archive Rule (CRITICAL)

`Dockerfile`, `main.py`, and `requirements.txt` MUST reside directly at **level 0 (root)** of the `.tar.gz` archive (max **8 MB**), NEVER nested inside a parent folder like `app/Dockerfile`. Cloud Build unpacks directly into the build root and expects `./Dockerfile`.

```bash
cd app_root
tar -czvf ../terraform/agent_source.tar.gz Dockerfile main.py requirements.txt agent_pkg/
# Verify level-0 structure (must show `./Dockerfile` or `Dockerfile`, NOT `app_root/Dockerfile`)
tar -tzvf ../terraform/agent_source.tar.gz | head -n 10
```

### Verified Multi-Language Dockerfile Patterns

- **Python (`python:3.13-slim` or `3.11-slim`):**
  ```dockerfile
  FROM python:3.13-slim
  WORKDIR /app
  COPY requirements.txt .
  RUN pip install --no-cache-dir -r requirements.txt
  COPY . .
  EXPOSE 8080
  CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8080"]
  ```
- **Go:** Multi-stage `FROM golang:1.24 AS builder` -> `FROM gcr.io/distroless/static-debian12`, `CMD ["/app/server", "web", "-host", "0.0.0.0", "-port", "8080", "agentengine"]` (or `CMD ["/app/server"]`).
- **TypeScript:** `FROM node:22-slim`, `CMD ["npx", "adk", "api_server", "/app/agents/my_agent", "--host=0.0.0.0", "--port=8080"]` (invoke via `/api/run` and `/api/run_sse`).
- **Java:** `FROM maven:3.9-eclipse-temurin-17`, `AdkWebServer` with `--server.address=0.0.0.0 --server.port=${PORT:-8080}`.

### Terraform `source_code_spec` Block

```hcl
resource "google_vertex_ai_reasoning_engine" "dockerfile_agent" {
  display_name    = "dockerfile_agent_tf"
  project         = var.project_id
  region          = var.location
  deletion_policy = "FORCE" # Prevents HTTP 400 child-sessions failure on `terraform destroy`

  spec {
    agent_framework = "google-adk"

    source_code_spec {
      inline_source {
        source_archive = filebase64("${path.module}/agent_source.tar.gz")
      }

      # Empty image_spec {} instructs Agent Runtime to build using ./Dockerfile
      image_spec {}

      # Alternative for Python source WITHOUT Dockerfile:
      # python_spec {
      #   entrypoint_module = "agent"
      #   entrypoint_object = "root_agent"
      #   requirements_file = "requirements.txt"
      #   version           = "3.11"
      # }
    }

    class_methods = jsonencode(local.adk_class_methods)
  }
}
```

---

## 5. Agent Identity (SPIFFE), Cross-Project Agent Gateway & UAP V2

### SPIFFE Agent Identity Rules

- **Principal formats:**
  - Org-scoped: `principal://agents.global.org-ORGANIZATION_ID.system.id.goog/resources/aiplatform/projects/PROJECT_NUMBER/locations/LOCATION/reasoningEngines/AGENT_ENGINE_ID`
  - Orgless: `principal://agents.global.proj-PROJECT_NUMBER.system.id.goog/resources/aiplatform/projects/PROJECT_NUMBER/locations/LOCATION/reasoningEngines/AGENT_ENGINE_ID`
  - Project-wide `principalSet`: `principalSet://agents.global.org-ORGANIZATION_ID.system.id.goog/attribute.platformContainer/aiplatform/projects/PROJECT_NUMBER`
- **Auto-granted defaults:** `roles/aiplatform.agentContextEditor` and `roles/aiplatform.agentDefaultAccess`. **Do NOT grant** `roles/aiplatform.user` or `roles/aiplatform.expressUser` to agent identities.
- **Recommended roles:** `roles/serviceusage.serviceUsageConsumer`, `roles/browser`, `roles/cloudapiregistry.viewer`, `roles/logging.logWriter`, `roles/monitoring.metricWriter`, `roles/secretmanager.secretAccessor`.
- **Constraints:** Immutable (cannot patch a non-Agent-Identity engine to enable it); recreate mints a new SPIFFE ID; legacy GCS bucket roles (`storage.legacyBucket*`) are unsupported; Context-Aware Access (CAA) RFC 8705 mTLS binding is on by default (`401 "Context-Aware Access requirements are not met"` outside runtime; opt-out env `"GOOGLE_API_PREVENT_AGENT_TOKEN_SHARING_FOR_GCP_SERVICES": False`).

### Cross-Project Agent Gateway Binding & UAP V2 Terraform

```hcl
# Inside google_vertex_ai_reasoning_engine.spec.deployment_spec (requires google-beta + AGENT_IDENTITY):
# agent_gateway_config {
#   agent_to_anywhere_config {
#     agent_gateway = "projects/AGENT_GATEWAY_PROJECT_ID/locations/${var.location}/agentGateways/EGRESS_GW"
#   }
#   client_to_agent_config {
#     agent_gateway = "projects/${var.project_id}/locations/${var.location}/agentGateways/INGRESS_GW"
#   }
# }

# Cross-project gateway lookup role for Agent Platform Service Agent (gcp-sa-aiplatform)
resource "google_project_iam_custom_role" "ar_agw_cross_project_sa" {
  project     = "AGENT_GATEWAY_PROJECT_ID"
  role_id     = "ar_agw_cross_project_sa"
  title       = "Runtime Agent Gateway Cross-Project SA"
  permissions = ["networkservices.agentGateways.get", "networkservices.operations.get"]
}

resource "google_project_iam_member" "ar_agw_cross_project_binding" {
  for_each = var.runtime_project_numbers
  project  = "AGENT_GATEWAY_PROJECT_ID"
  role     = google_project_iam_custom_role.ar_agw_cross_project_sa.name
  member   = "serviceAccount:service-${each.value}@gcp-sa-aiplatform.iam.gserviceaccount.com"
}

# Register runtime endpoint in Agent Registry (Bangkok default for A2A/MCP: asia-southeast3; standalone skills use global)
resource "google_agent_registry_service" "runtime_agent_entry" {
  project      = "AGENT_GATEWAY_PROJECT_ID"
  location     = "asia-southeast3" # Or var.agent_registry_location (Bangkok default for A2A/MCP; decoupled from Runtime var.location)
  service_id   = "runtime-agent-svc"
  display_name = "Runtime Agent Service"
  endpoint_spec { no_spec {} }
  interfaces {
    url              = "https://${var.location}-aiplatform.mtls.googleapis.com/v1/projects/${var.project_number}/locations/${var.location}/reasoningEngines/${local.agent_resource_id}"
    # Note: `agent-gateway-runtime-deploy` shows lowercase `"jsonrpc"`, whereas `agent-registry/manual-registration`
    # documents uppercase Terraform enum values (`"HTTP_JSON"` | `"GRPC"` | `"JSONRPC"`; lowercase `http-json`/`grpc`/`jsonrpc` are for `gcloud` CLI).
    # Verify accepted casing against your installed `hashicorp/google` provider schema via `terraform validate`.
    protocol_binding = "JSONRPC"
  }
}

# UAP V2 Egress Allow Policy (preferred over legacy google_iap_agent_registry_endpoint_iam_member)
resource "google_iam_project_access_policy" "egress_policy" {
  project          = "AGENT_GATEWAY_PROJECT_ID"
  location         = "global"
  access_policy_id = "agent-egress-policy"
  display_name     = "Allow agent egress to registered endpoint"
  details {
    rules {
      description = "Allow agent egress to registered endpoint"
      effect      = "ALLOW"
      principals  = [local.agent_identity_principal]
      operation { permissions = ["iap.googleapis.com/resources.egressViaIAP"] }
      conditions {
        service    = "iap.googleapis.com"
        expression = "(destination.is_registered == true) && (destination.agent_registry.endpoint.name == 'projects/AGENT_GATEWAY_PROJECT_ID/locations/${var.location}/endpoints/AGENT_ENDPOINT_ID')"
      }
    }
  }
}

resource "google_iam_projects_policy_binding" "egress_binding" {
  project           = "AGENT_GATEWAY_PROJECT_ID"
  location          = "global"
  policy_binding_id = "agent-egress-binding"
  policy_kind       = "ACCESS"
  policy            = "projects/AGENT_GATEWAY_PROJECT_ID/locations/global/accessPolicies/${google_iam_project_access_policy.egress_policy.access_policy_id}"
  target { resource = "//cloudresourcemanager.googleapis.com/projects/AGENT_GATEWAY_PROJECT_ID" }
}
```

### BYOC Agent Gateway Root CA Trust & Constraints

Fetch the Agent Gateway Root CA certificates:

```bash
gcloud network-services agent-gateways describe GW_NAME \
  --location="${LOCATION}" \
  --project="${PROJECT_ID}" \
  --format="json(agentGatewayCard.rootCertificates)" | jq -r '.agentGatewayCard.rootCertificates[]'
```

- **Bake into BYOC Container:** Write certs to `/usr/local/share/ca-certificates/agw-*.crt`, run `update-ca-certificates`, and set `GRPC_DEFAULT_SSL_ROOTS_FILE_PATH`, `REQUESTS_CA_BUNDLE`, `SSL_CERT_FILE`, and `AGENT_GATEWAY_ROOT_CERT_302034098528` to `/etc/ssl/certs/ca-certificates.crt`.
- **Constraints:** Cannot bind Agent Gateway to engines created before **April 29, 2026**; SCC Threat Detection is unavailable when Agent Gateway is attached; VPC-SC + Agent Gateway egress requires engines created after **September 8, 2026**, `AgentConnectivityTemplate` with `vpcEgress: ALL_TRAFFIC`, private DNS peering for `googleapis.com.` -> `restricted.googleapis.com` (`199.36.153.4/30`), and allowlisted regional/mTLS `aiplatform` endpoints in Agent Registry.

---

## 6. PSC-I, VPC-SC & CMEK Configuration Rules

- **Private Service Connect Interface (PSC-I):**
  - Requires minimum `/28` subnet per project; supports RFC 1918 and non-RFC 1918 EXCEPT `100.64.0.0/20`, `192.0.0.0/24`, `192.0.2.0/24`, `198.18.0.0/15`, `198.51.100.0/24`, `203.0.113.0/24`, `240.0.0.0/4`.
  - **Immutable:** Changing an existing PSC-I requires recreating the Agent Runtime resource.
  - **Shared VPC:** Grant service project's `gcp-sa-aiplatform` `roles/compute.networkUser` on the host project; place the network attachment in the **service project** (recommended) and grant `roles/compute.networkAdmin` (or custom role with `compute.networkAttachments.{get,update}`, `compute.regionOperations.get`). If placed in the host project, enable `aiplatform.googleapis.com` and create its service identity via `gcloud alpha services identity create --service=aiplatform.googleapis.com --project=HOST_PROJECT`.
  - **Internet egress with PSC-I / VPC-SC:** PSC-I routes traffic into your VPC with no default internet path; configure a proxy VM + Cloud NAT inside the VPC if outbound internet is required.
- **VPC-SC Perimeter Ingress Rules for `gcp-sa-aiplatform-re`:**
  - Source / Git / Dockerfile: ingress to `artifactregistry.googleapis.com`.
  - BYOC `container_spec`: no additional ingress rule required.
- **CMEK (`encryption_spec` / `kms_key_name`):**
  - Immutable at creation; grant `gcp-sa-aiplatform-re` `roles/cloudkms.cryptoKeyEncrypterDecrypter`.
  - Deployed Agent Runtimes support **single-region CMEK only** (key region must match runtime region; unsupported on `us`, `eu`, `global`).
  - **Not encrypted with CMEK:** display names, descriptions, SA emails, class method names, and environment variables (encrypted with Google default encryption).

---

## 7. Execution, Troubleshooting & Verification

```bash
cd terraform
terraform init
terraform plan -var="project_id=${PROJECT_ID}" -var="project_number=${PROJECT_NUMBER}"
terraform apply -var="project_id=${PROJECT_ID}" -var="project_number=${PROJECT_NUMBER}"

# Verify SPIFFE identity (when AGENT_IDENTITY enabled)
gcloud ai reasoning-engines describe "${REASONING_ENGINE_ID}" \
  --project="${PROJECT_ID}" --location="${LOCATION}" \
  --format="value(spec.effectiveIdentity)"

# Verify SSE query endpoint
curl -X POST \
  -H "Authorization: Bearer $(gcloud auth print-access-token)" \
  -H "Content-Type: application/json; charset=utf-8" \
  -d '{"class_method":"async_stream_query","input":{"user_id":"tf_smoke_test","message":"Hello"}}' \
  "https://${LOCATION}-aiplatform.googleapis.com/v1/projects/${PROJECT_ID}/locations/${LOCATION}/reasoningEngines/${REASONING_ENGINE_ID}:streamQuery?alt=sse"

# Teardown (requires `deletion_policy = "FORCE"` on google_vertex_ai_reasoning_engine
# if live sessions/memories were created, otherwise destroy fails with HTTP 400 child resources)
terraform destroy -var="project_id=${PROJECT_ID}" -var="project_number=${PROJECT_NUMBER}"
```

| Error / Symptom | Root Cause | Fix |
|---|---|---|
| `Error 400: The ReasoningEngine contains child resources: sessions` on `terraform destroy` | `google_vertex_ai_reasoning_engine` omits `deletion_policy = "FORCE"` and live `:query` / `create_session` calls created child sessions or memories | Set `deletion_policy = "FORCE"` on `google_vertex_ai_reasoning_engine` (supported by both `hashicorp/google` and `hashicorp/google-beta`); for an already-applied state, apply that attribute first or delete child sessions / call `client.runtimes.delete(name=..., force=True)` |
| `Error 400: deployment_spec.env[N].value: Required field is not set` | Unconditional `env { value = var.optional_var }` emitted an empty string `""` | Gate optional env vars behind `dynamic "env" { for_each = var.optional_var != "" ? [var.optional_var] : [] ... }` |
| `IMAGE_PULL_BACKOFF` on first apply | Missing `roles/artifactregistry.reader` on `gcp-sa-aiplatform-re` (or `gcp-sa-aiplatform` cross-project) or missing `depends_on` | Add IAM resource(s) and wire into `depends_on` on `google_vertex_ai_reasoning_engine` |
| `Unsupported block type: container_spec` | Cached `hashicorp/google` 5.x provider | Pin `version = ">= 6.0.0"` in `required_providers` and run `terraform init -upgrade` |
| `Unsupported argument: location` | Copied upstream doc typo | Replace `location = var.location` with `region = var.location` |
| `Invalid function argument` in `element(split(...), -1)` | Terraform `element()` rejects negative indices | Use `reverse(split("/", resource.id))[0]` |
| Cloud Build fails: `Dockerfile not found` | Tarball nested `app/Dockerfile` instead of `./Dockerfile` | `cd` into app root before `tar -czvf`, confirm `tar -tzvf` starts at root, keep `<= 8 MB` |
| `FAILED_PRECONDITION` adding `agent_gateway_config` | Missing `identity_type = "AGENT_IDENTITY"` or active manual traffic split | Use `provider = google-beta`, set `identity_type = "AGENT_IDENTITY"`, and switch traffic to `traffic_split_always_latest` first |
