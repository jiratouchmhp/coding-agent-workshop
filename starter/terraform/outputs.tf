# Canonical outputs for the deployed Agent Runtime (google_vertex_ai_reasoning_engine).
#
# CRITICAL PROVIDER SCHEMA TRAP (verified against scale/runtime/agent-identity):
# - In `hashicorp/google`, `google_vertex_ai_reasoning_engine.<name>.id` returns
#   the full resource path `projects/{PROJECT}/locations/{LOCATION}/reasoningEngines/{NUMERIC_ID}`,
#   whereas `.name` returns only the short numeric ID.
# - Always derive `reasoning_engine_short_id` explicitly so downstream REST URLs,
#   `REASONING_ENGINE_NAME`, and `REASONING_ENGINE_ID` work reliably across Labs 5-7.

locals {
  # NOTE: Terraform's `element(list, index)` strictly rejects negative indices
  # (known bug in upstream `scale/runtime/agent-identity` docs). Use `reverse(...)[0]`
  # to extract the trailing numeric ReasoningEngine ID reliably.
  reasoning_engine_short_id = reverse(split("/", google_vertex_ai_reasoning_engine.coding_agent.id))[0]

  # Optional Lab 7 Upgrade Path reference: dynamic SPIFFE Agent Identity principal when using
  # `provider = google-beta` and `identity_type = "AGENT_IDENTITY"` (survives recreate):
  # agent_identity_principal = "principal://agents.global.org-${var.organization_id}.system.id.goog/resources/aiplatform/projects/${var.project_number}/locations/${var.location}/reasoningEngines/${local.reasoning_engine_short_id}"
}

output "reasoning_engine_id" {
  value       = local.reasoning_engine_short_id
  description = "Short numeric ID of the deployed Agent Runtime instance"
}

output "reasoning_engine_resource_name" {
  value       = "projects/${var.project_id}/locations/${var.location}/reasoningEngines/${local.reasoning_engine_short_id}"
  description = "Canonical full resource name (projects/.../locations/.../reasoningEngines/ID)"
}

output "agent_runtime_service_account" {
  value       = google_service_account.agent_runtime_sa.email
  description = "Dedicated custom runtime service account email"
}

output "api_key_secret_id" {
  value       = google_secret_manager_secret.coding_agent_api_key.secret_id
  description = "Secret Manager secret ID bound to CODING_AGENT_API_KEY"
}
