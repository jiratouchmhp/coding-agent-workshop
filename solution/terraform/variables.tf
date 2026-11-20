# Input variables for deploying the Enterprise Coding Agent to Agent Runtime.

variable "project_id" {
  type        = string
  description = "The Google Cloud Project ID"
}

variable "project_number" {
  type        = string
  description = "The Google Cloud Project Number (used to build Google-managed service agent emails)"
}

variable "location" {
  type        = string
  default     = "us-central1"
  description = "The Google Cloud region for Agent Runtime (golden workshop regions: us-central1 or europe-west4)"
}

variable "repository_name" {
  type        = string
  default     = "coding-agent-repo"
  description = "The Artifact Registry Docker repository hosting the BYOC agent and sandbox images"
}

variable "display_name" {
  type        = string
  default     = "coding_agent_byoc_tf"
  description = "Display name of the deployed Agent Runtime (ReasoningEngine) instance"
}

variable "agent_image_uri" {
  type        = string
  description = "Full Artifact Registry URI for the trusted Agent Runtime BYOC container image (e.g., us-central1-docker.pkg.dev/PROJECT_ID/coding-agent-repo/coding-agent:v1)"
}

variable "sandbox_image_uri" {
  type        = string
  default     = ""
  description = "Optional Artifact Registry URI for the Lab 2 untrusted BYOC sandbox image (pulled by gcp-sa-vertex-sandbox)"
}

variable "sandbox_template_name" {
  type        = string
  default     = ""
  description = "Optional full resource name of the Lab 2 SandboxEnvironmentTemplate injected into the runtime container"
}

variable "sandbox_mode" {
  type        = string
  default     = ""
  description = "Execution mode injected as SANDBOX_MODE (byoc, shell, code_execution, or local). When empty, defaults to 'byoc' if sandbox_template_name is non-empty, else 'shell' (never silently falls back to 'local' inside Agent Runtime)."

  validation {
    condition     = contains(["", "byoc", "shell", "code_execution", "local"], var.sandbox_mode)
    error_message = "sandbox_mode must be empty (auto) or one of: byoc, shell, code_execution, local."
  }
}

variable "model_name" {
  type        = string
  default     = "gemini-2.5-flash"
  description = "Explicit versioned Gemini model ID (avoid gemini-flash-latest on regional endpoints)"
}

variable "api_key_value" {
  type        = string
  sensitive   = true
  description = "Secret payload stored in Secret Manager and injected via deployment_spec.secret_env (use a non-sensitive workshop placeholder; never commit real secrets)"
}

variable "enable_memory_bank" {
  type        = bool
  default     = false
  description = "Enable Lab 3 Memory Bank tools and after_agent_callback inside the deployed Agent Runtime (ENABLE_MEMORY_BANK)"
}

variable "enable_skill_registry" {
  type        = bool
  default     = false
  description = "Enable Lab 4 Skill Registry SkillToolset integration inside the deployed Agent Runtime (ENABLE_SKILL_REGISTRY)"
}

variable "skill_registry_location" {
  type        = string
  default     = "us-central1"
  description = "Lab 4 Skill Registry / Agent Registry region injected as SKILL_REGISTRY_LOCATION and AGENT_REGISTRY_LOCATION (supported: us-central1, europe-west4, us-east5)"
}
