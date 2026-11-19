# Terraform and Google Cloud Provider constraints for Agent Runtime deployment.
#
# Verified against:
#   https://docs.cloud.google.com/gemini-enterprise-agent-platform/scale/runtime/use-terraform
#
# Notes:
# - Upstream `use-terraform.md` prints `>= 5.28.0`, but `google_vertex_ai_reasoning_engine`
#   with `spec.container_spec` requires `hashicorp/google >= 6.0.0` (cached 5.x providers
#   reject `container_spec` with `Unsupported block type`).
# - `hashicorp/google-beta >= 6.0.0` is included so Lab 5 can opt into
#   `identity_type = "AGENT_IDENTITY"` and `agent_gateway_config`.

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
