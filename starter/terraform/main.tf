# Declarative Terraform IaC for Gemini Enterprise Agent Platform (Agent Runtime).
# Starter track: complete every `# TODO(lab-5)` marker below before running
# `terraform fmt -check`, `terraform validate`, and `terraform plan`.
#
# Verified against:
#   https://docs.cloud.google.com/gemini-enterprise-agent-platform/scale/runtime/use-terraform
#   https://docs.cloud.google.com/gemini-enterprise-agent-platform/scale/runtime/agent-identity
#   https://docs.cloud.google.com/gemini-enterprise-agent-platform/scale/sandbox/custom-containers

provider "google" {
  project = var.project_id
  region  = var.location
}

provider "google-beta" {
  project = var.project_id
  region  = var.location
}

locals {
  # Auto-select isolated remote sandbox execution inside Agent Runtime so
  # deployed containers never silently fall back to `SANDBOX_MODE=local`.
  resolved_sandbox_mode = var.sandbox_mode != "" ? var.sandbox_mode : (var.sandbox_template_name != "" ? "byoc" : "shell")

  # Verified ADK method surface routed by Agent Runtime:
  # - api_mode "" / "async"        -> POST /api/reasoning_engine
  # - api_mode "stream" / "async_stream" -> POST /api/stream_reasoning_engine (NDJSON -> SSE)
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

# -----------------------------------------------------------------------------
# 1. Dedicated Least-Privilege Runtime Service Account
# -----------------------------------------------------------------------------

resource "google_service_account" "agent_runtime_sa" {
  account_id   = "coding-agent-runtime-sa"
  display_name = "Coding Agent Runtime Identity"
  project      = var.project_id
}

resource "google_project_iam_member" "runtime_sa_roles" {
  for_each = toset([
    "roles/aiplatform.user",
    # TODO(lab-5): Add "roles/aiplatform.memoryUser" so the deployed Agent Runtime SA
    # can read/write Lab 3 Memory Bank memories when ENABLE_MEMORY_BANK=true.
    "roles/logging.logWriter",
    "roles/cloudtrace.agent",
    "roles/telemetry.tracesWriter",
    "roles/monitoring.metricWriter",
  ])

  project = var.project_id
  role    = each.value
  member  = "serviceAccount:${google_service_account.agent_runtime_sa.email}"
}

# Grant Agent Registry read access when Lab 4 Skill Registry integration is enabled
# so the Custom SA can read from `agentregistry.googleapis.com`.
resource "google_project_iam_member" "runtime_sa_agentregistry_viewer" {
  count = var.enable_skill_registry ? 1 : 0

  project = var.project_id
  role    = "roles/agentregistry.viewer"
  member  = "serviceAccount:${google_service_account.agent_runtime_sa.email}"
}

# Allow the runtime SA to mint short-lived sandbox data-plane JWTs via
# `sandboxes.generate_access_token(service_account_email=...)` when SANDBOX_MODE=byoc.
resource "google_service_account_iam_member" "runtime_sa_self_token_creator" {
  service_account_id = google_service_account.agent_runtime_sa.name
  role               = "roles/iam.serviceAccountTokenCreator"
  member             = "serviceAccount:${google_service_account.agent_runtime_sa.email}"
}

# -----------------------------------------------------------------------------
# 2. Secret Manager Secret, Initial Version & Accessor IAM
# -----------------------------------------------------------------------------

resource "google_secret_manager_secret" "coding_agent_api_key" {
  secret_id = "coding-agent-api-key"
  project   = var.project_id

  replication {
    auto {}
  }
}

resource "google_secret_manager_secret_version" "coding_agent_api_key_v1" {
  secret      = google_secret_manager_secret.coding_agent_api_key.id
  secret_data = var.api_key_value
}

resource "google_secret_manager_secret_iam_member" "runtime_sa_secret_accessor" {
  secret_id = google_secret_manager_secret.coding_agent_api_key.id
  role      = "roles/secretmanager.secretAccessor"
  member    = "serviceAccount:${google_service_account.agent_runtime_sa.email}"
}

# Agent Platform Service Agent (gcp-sa-aiplatform): required to fetch secret_env
# at deploy time when using `identity_type = "AGENT_IDENTITY"` (Optional Lab 7) or when
# pulling BYOC images from a cross-project Artifact Registry repository.
resource "google_secret_manager_secret_iam_member" "platform_service_agent_secret_accessor" {
  secret_id = google_secret_manager_secret.coding_agent_api_key.id
  role      = "roles/secretmanager.secretAccessor"
  member    = "serviceAccount:service-${var.project_number}@gcp-sa-aiplatform.iam.gserviceaccount.com"
}

# -----------------------------------------------------------------------------
# 3. Google-Managed Service Agent Artifact Registry IAM Bindings
# -----------------------------------------------------------------------------
# CRITICAL: Agent Runtime and Agent Sandbox use TWO DISTINCT Google-managed
# service agents. Missing either grant causes `IMAGE_PULL_BACKOFF`:
#   1. Agent Runtime Service Agent:
#      service-${var.project_number}@gcp-sa-aiplatform-re.iam.gserviceaccount.com
#   2. Agent Sandbox Service Agent (Lab 2 BYOC sandboxes):
#      service-${var.project_number}@gcp-sa-vertex-sandbox.iam.gserviceaccount.com
#
# TODO(lab-5): Uncomment BOTH `google_project_iam_member` resources below so
# Terraform grants `roles/artifactregistry.reader` to both service agents before
# provisioning `google_vertex_ai_reasoning_engine.coding_agent`.
# (In stricter production environments, you can narrow these to a single repo
# with `google_artifact_registry_repository_iam_member` using `var.repository_name`.)

# resource "google_project_iam_member" "re_service_agent_ar_reader" {
#   project = var.project_id
#   role    = "roles/artifactregistry.reader"
#   member  = "serviceAccount:service-${var.project_number}@gcp-sa-aiplatform-re.iam.gserviceaccount.com"
# }
#
# resource "google_project_iam_member" "sandbox_service_agent_ar_reader" {
#   project = var.project_id
#   role    = "roles/artifactregistry.reader"
#   member  = "serviceAccount:service-${var.project_number}@gcp-sa-vertex-sandbox.iam.gserviceaccount.com"
# }

# -----------------------------------------------------------------------------
# 4. Agent Runtime Resource (google_vertex_ai_reasoning_engine)
# -----------------------------------------------------------------------------

resource "google_vertex_ai_reasoning_engine" "coding_agent" {
  # Verified Terraform schema note: use `region = var.location` (NOT `location`).
  # One upstream doc example prints `location = var.location` by mistake.
  display_name = var.display_name
  description  = "Enterprise ADK Coding Agent deployed declaratively with Terraform BYOC container_spec"
  project      = var.project_id
  region       = var.location

  spec {
    agent_framework = "google-adk"

    # Pass ONLY the service account email (NOT a full `projects/...` URI).
    # Optional Lab 7 Upgrade Path: to bind Agent Gateway or Semantic Governance Policies,
    # switch this resource to `provider = google-beta`, remove `service_account`,
    # and set `identity_type = "AGENT_IDENTITY"` (immutable at creation time!).
    service_account = google_service_account.agent_runtime_sa.email

    # -------------------------------------------------------------------------
    # Option 1 (Primary): BYOC Prebuilt Container Image (`container_spec`)
    # -------------------------------------------------------------------------
    # TODO(lab-5): Uncomment `container_spec` below to deploy the prebuilt
    # Agent Runtime BYOC container image pushed in Step B0 (`make push-agent`).
    #
    # container_spec {
    #   image_uri = var.agent_image_uri
    # }

    # -------------------------------------------------------------------------
    # Option 2 (Zero-Docker & Zero-AR Alternative): Dockerfile Build (`source_code_spec`)
    # -------------------------------------------------------------------------
    # Use `source_code_spec` + empty `image_spec {}` instead of `container_spec`
    # when you want Agent Runtime to build your container from a local tarball
    # (max 8 MB archive; zero local Docker AND no Artifact Registry push or GCS bucket required).
    #
    # CRITICAL ROOT-OF-TAR ARCHIVE WARNING:
    # `Dockerfile`, `main.py`, and `requirements.txt` MUST reside directly at
    # level 0 (the root) of the `.tar.gz` archive (`./Dockerfile`), NEVER nested
    # inside a parent folder like `starter/Dockerfile`! Cloud Build unpacks the
    # tarball into the build workspace root and fails immediately if `./Dockerfile`
    # is missing. Run `make pack-agent-source` (or `cd` into the app root first):
    #
    #   cd starter && tar -czvf terraform/coding_agent_source.tar.gz \
    #     Dockerfile main.py requirements.txt coding_agent/ skills_to_register/
    #   tar -tzvf terraform/coding_agent_source.tar.gz | head -n 5
    #
    # source_code_spec {
    #   inline_source {
    #     source_archive = filebase64("${path.module}/coding_agent_source.tar.gz")
    #   }
    #
    #   # Empty `image_spec {}` instructs Agent Runtime to build using `./Dockerfile`.
    #   image_spec {}
    # }

    deployment_spec {
      # NEVER set reserved/auto-injected env vars here:
      # GOOGLE_CLOUD_PROJECT, GOOGLE_CLOUD_QUOTA_PROJECT, GOOGLE_CLOUD_LOCATION,
      # PORT, K_SERVICE, K_REVISION, K_CONFIGURATION, GOOGLE_APPLICATION_CREDENTIALS.
      env {
        name  = "GOOGLE_CLOUD_AGENT_ENGINE_ENABLE_TELEMETRY"
        value = "true"
      }

      env {
        name  = "OTEL_SEMCONV_STABILITY_OPT_IN"
        value = "gen_ai_latest_experimental"
      }

      env {
        # ADK Python requires enum values (`EVENT_ONLY`, `NO_CONTENT`, `SPAN_ONLY`,
        # `SPAN_AND_EVENT`); passing `"true"` silently falls back to `NO_CONTENT`!
        name  = "OTEL_INSTRUMENTATION_GENAI_CAPTURE_MESSAGE_CONTENT"
        value = "EVENT_ONLY"
      }

      env {
        name  = "GOOGLE_GENAI_USE_ENTERPRISE"
        value = "TRUE"
      }

      env {
        name  = "MODEL_NAME"
        value = var.model_name
      }

      # Optional ADK 2.0 architecture overrides (Lab 1 Part B / Lab 5 portability).
      # Defaults to `AGENT_ARCHITECTURE=simple` (Labs 2-8 compatible) when omitted;
      # uncomment to switch the deployed Agent Runtime to `collaborative`, `graph`,
      # or `dynamic` with zero changes to Dockerfile, main.py, or the HTTP contract:
      #
      # env {
      #   name  = "AGENT_ARCHITECTURE"
      #   value = "simple" # simple | collaborative | graph | dynamic
      # }
      #
      # env {
      #   name  = "MAX_FIX_ROUNDS"
      #   value = "3"
      # }
      #
      # env {
      #   name  = "ENABLE_HITL_APPROVAL"
      #   value = "false"
      # }

      # TODO(lab-5): Uncomment ALL blocks below to wire isolated Managed Sandbox
      # execution (`SANDBOX_MODE`, `SANDBOX_TEMPLATE_NAME`, and
      # `SANDBOX_SERVICE_ACCOUNT_EMAIL`), optional Lab 3/Lab 4 runtime flags
      # (`ENABLE_MEMORY_BANK`, `ENABLE_SKILL_REGISTRY`, `SKILL_REGISTRY_LOCATION`,
      # `AGENT_REGISTRY_LOCATION`), plus Secret Manager `CODING_AGENT_API_KEY`.
      # Setting `SANDBOX_MODE` explicitly prevents deployed containers from silently
      # falling back to `local` inside the trusted Agent Runtime container.
      #
      # env {
      #   name  = "SANDBOX_MODE"
      #   value = local.resolved_sandbox_mode
      # }
      #
      # env {
      #   name  = "SANDBOX_TEMPLATE_NAME"
      #   value = var.sandbox_template_name
      # }
      #
      # env {
      #   name  = "SANDBOX_SERVICE_ACCOUNT_EMAIL"
      #   value = google_service_account.agent_runtime_sa.email
      # }
      #
      # env {
      #   name  = "ENABLE_MEMORY_BANK"
      #   value = tostring(var.enable_memory_bank)
      # }
      #
      # env {
      #   name  = "ENABLE_SKILL_REGISTRY"
      #   value = tostring(var.enable_skill_registry)
      # }
      #
      # env {
      #   name  = "SKILL_REGISTRY_LOCATION"
      #   value = var.skill_registry_location
      # }
      #
      # env {
      #   name  = "AGENT_REGISTRY_LOCATION"
      #   value = var.agent_registry_location
      # }
      #
      # secret_env {
      #   name = "CODING_AGENT_API_KEY"
      #   secret_ref {
      #     secret  = google_secret_manager_secret.coding_agent_api_key.secret_id
      #     version = "latest"
      #   }
      # }

      # Optional Lab 7 Upgrade Path — Agent Gateway binding (requires `provider = google-beta`
      # and `identity_type = "AGENT_IDENTITY"` in `spec`):
      # agent_gateway_config {
      #   agent_to_anywhere_config {
      #     agent_gateway = "projects/${var.project_id}/locations/${var.location}/agentGateways/EGRESS_GW_NAME"
      #   }
      #   client_to_agent_config {
      #     agent_gateway = "projects/${var.project_id}/locations/${var.location}/agentGateways/INGRESS_GW_NAME"
      #   }
      # }
    }

    class_methods = jsonencode(local.adk_class_methods)
  }

  # TODO(lab-5): Expand `depends_on` below with ALL remaining IAM bindings
  # (`re_service_agent_ar_reader`, `sandbox_service_agent_ar_reader`,
  # `runtime_sa_roles`, `runtime_sa_self_token_creator`,
  # `runtime_sa_secret_accessor`, `platform_service_agent_secret_accessor`)
  # alongside `runtime_sa_agentregistry_viewer` and `coding_agent_api_key_v1`.
  # Without explicit `depends_on`, container startup can race ahead of IAM
  # propagation and fail with `IMAGE_PULL_BACKOFF` or Secret Manager errors.
  depends_on = [
    google_project_iam_member.runtime_sa_agentregistry_viewer,
    google_secret_manager_secret_version.coding_agent_api_key_v1,
  ]
}
