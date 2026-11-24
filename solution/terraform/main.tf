# Declarative Terraform IaC for Gemini Enterprise Agent Platform (Agent Runtime).
# Solution track: complete, ready-to-apply production IaC configuration.
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
  # - api_mode "" / "async"              -> POST /api/reasoning_engine
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
    "roles/aiplatform.memoryUser",
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

# SERVICE AGENT #2: Agent Platform Service Agent (gcp-sa-aiplatform)
# Required to fetch `secret_env` at deploy time when using `identity_type = "AGENT_IDENTITY"`
# (Optional Lab 7) or when pulling BYOC images from a cross-project Artifact Registry repo.
resource "google_secret_manager_secret_iam_member" "platform_service_agent_secret_accessor" {
  secret_id = google_secret_manager_secret.coding_agent_api_key.id
  role      = "roles/secretmanager.secretAccessor"
  member    = "serviceAccount:service-${var.project_number}@gcp-sa-aiplatform.iam.gserviceaccount.com"
}

# -----------------------------------------------------------------------------
# 3. Google-Managed Service Agent Artifact Registry IAM Bindings
# -----------------------------------------------------------------------------
# CRITICAL: Agent Runtime and Agent Sandbox use TWO DISTINCT Google-managed
# service agents. In stricter production environments, you can narrow either
# grant to a single repository via `google_artifact_registry_repository_iam_member`
# referencing `var.repository_name`.

# SERVICE AGENT #1: Agent Runtime Service Agent (pulls BYOC runtime image from AR)
resource "google_project_iam_member" "re_service_agent_ar_reader" {
  project = var.project_id
  role    = "roles/artifactregistry.reader"
  member  = "serviceAccount:service-${var.project_number}@gcp-sa-aiplatform-re.iam.gserviceaccount.com"
}

# SERVICE AGENT #3: Agent Sandbox Service Agent (pulls BYOC sandbox image from Lab 2)
resource "google_project_iam_member" "sandbox_service_agent_ar_reader" {
  project = var.project_id
  role    = "roles/artifactregistry.reader"
  member  = "serviceAccount:service-${var.project_number}@gcp-sa-vertex-sandbox.iam.gserviceaccount.com"
}

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

  # Allow `terraform destroy` and `make cleanup` to tear down the engine cleanly
  # after live attendee sessions or Memory Bank memories are created.
  deletion_policy = "FORCE"

  spec {
    agent_framework = "google-adk"

    # Pass ONLY the service account email (NOT a full `projects/...` URI).
    # Optional Lab 7 Upgrade Path: to bind Agent Gateway or Semantic Governance Policies,
    # switch this resource to `provider = google-beta`, remove `service_account`,
    # and set `identity_type = "AGENT_IDENTITY"` (immutable at creation time!).
    service_account = google_service_account.agent_runtime_sa.email

    # -------------------------------------------------------------------------
    # Option 1 (Active): BYOC Prebuilt Container Image (`container_spec`)
    # -------------------------------------------------------------------------
    container_spec {
      image_uri = var.agent_image_uri
    }

    # -------------------------------------------------------------------------
    # Option 2 (Zero-Docker & Zero-AR Alternative): Dockerfile Build (`source_code_spec`)
    # -------------------------------------------------------------------------
    # Replace `container_spec` with `source_code_spec` + empty `image_spec {}`
    # when you want Agent Runtime to build your container directly from a local
    # `.tar.gz` archive (max 8 MB; zero local Docker AND no Artifact Registry push or GCS bucket needed).
    #
    # CRITICAL ROOT-OF-TAR ARCHIVE WARNING:
    # `Dockerfile`, `main.py`, and `requirements.txt` MUST reside directly at
    # level 0 (the root) of the `.tar.gz` archive (`./Dockerfile`), NEVER nested
    # inside a parent folder like `solution/Dockerfile`! Cloud Build unpacks the
    # tarball directly into the build workspace root and fails immediately if
    # `./Dockerfile` is missing. Run `make TRACK=solution pack-agent-source` (or `cd` into the app root first):
    #
    #   cd solution && tar -czvf terraform/coding_agent_source.tar.gz \
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

      env {
        name  = "REASONING_MODEL_NAME"
        value = var.reasoning_model_name
      }

      env {
        name  = "MODEL_LOCATION"
        value = var.model_location
      }

      env {
        name  = "THINKING_LEVEL"
        value = upper(var.thinking_level)
      }

      env {
        name  = "AGY_EXECUTION_MODE"
        value = var.agy_execution_mode
      }

      env {
        name  = "AGY_ADC_AUTH"
        value = "true"
      }

      env {
        name  = "AGY_CLI_DISABLE_AUTO_UPDATE"
        value = "true"
      }

      # Non-reserved string project ID for Antigravity (`agy`) headless CLI:
      # Agent Runtime auto-injects the numeric project number into GOOGLE_CLOUD_PROJECT /
      # GOOGLE_CLOUD_QUOTA_PROJECT (and its GCE metadata server returns the tenant project),
      # whereas `agy` rejects numeric project IDs with exit code 3 (`invalid project ID`).
      env {
        name  = "AGY_PROJECT_ID"
        value = var.project_id
      }

      # Optional ADK 2.0 architecture overrides (Lab 1 Part B / Lab 5 portability).
      # Defaults to `AGENT_ARCHITECTURE=simple` (Labs 2-8 compatible) when omitted;
      # uncomment to switch the deployed Agent Runtime to `collaborative`, `graph`,
      # `dynamic`, or `agy_harness` with zero changes to Dockerfile, main.py, or the HTTP contract:
      #
      # env {
      #   name  = "AGENT_ARCHITECTURE"
      #   value = "simple" # simple | collaborative | graph | dynamic | agy_harness
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

      env {
        name  = "SANDBOX_MODE"
        value = local.resolved_sandbox_mode
      }

      # Vertex AI rejects empty env var values with HTTP 400 (`Required field is not set`).
      dynamic "env" {
        for_each = var.sandbox_template_name != "" ? [1] : []
        content {
          name  = "SANDBOX_TEMPLATE_NAME"
          value = var.sandbox_template_name
        }
      }

      env {
        name  = "SANDBOX_SERVICE_ACCOUNT_EMAIL"
        value = google_service_account.agent_runtime_sa.email
      }

      env {
        name  = "ENABLE_MEMORY_BANK"
        value = tostring(var.enable_memory_bank)
      }

      env {
        name  = "ENABLE_SKILL_REGISTRY"
        value = tostring(var.enable_skill_registry)
      }

      dynamic "env" {
        for_each = var.skill_registry_location != "" ? [1] : []
        content {
          name  = "SKILL_REGISTRY_LOCATION"
          value = var.skill_registry_location
        }
      }

      dynamic "env" {
        for_each = var.agent_registry_location != "" ? [1] : []
        content {
          name  = "AGENT_REGISTRY_LOCATION"
          value = var.agent_registry_location
        }
      }

      dynamic "env" {
        for_each = var.agent_registry_skills_location != "" ? [1] : []
        content {
          name  = "AGENT_REGISTRY_SKILLS_LOCATION"
          value = var.agent_registry_skills_location
        }
      }

      secret_env {
        name = "CODING_AGENT_API_KEY"
        secret_ref {
          secret  = google_secret_manager_secret.coding_agent_api_key.secret_id
          version = "latest"
        }
      }

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

  # CRITICAL: Prevents `IMAGE_PULL_BACKOFF` and Secret Manager deploy-time races
  # by enforcing IAM propagation ordering before container provisioning begins.
  depends_on = [
    google_project_iam_member.re_service_agent_ar_reader,
    google_project_iam_member.sandbox_service_agent_ar_reader,
    google_project_iam_member.runtime_sa_roles,
    google_project_iam_member.runtime_sa_agentregistry_viewer,
    google_service_account_iam_member.runtime_sa_self_token_creator,
    google_secret_manager_secret_iam_member.runtime_sa_secret_accessor,
    google_secret_manager_secret_iam_member.platform_service_agent_secret_accessor,
    google_secret_manager_secret_version.coding_agent_api_key_v1,
  ]
}
