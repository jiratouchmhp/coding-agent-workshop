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
  default     = "asia-southeast1"
  description = "Google Cloud region for Agent Runtime (aim for Bangkok asia-southeast3 first; falls back to nearest supported Singapore asia-southeast1 because Agent Runtime is not yet available in Bangkok)"
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
  description = "Full Artifact Registry URI for the trusted Agent Runtime BYOC container image (e.g., asia-southeast3-docker.pkg.dev/PROJECT_ID/coding-agent-repo/coding-agent:v1 — Bangkok AR is verified working for Singapore Agent Runtime pulls; no second Singapore AR repository is needed)"
}

variable "sandbox_image_uri" {
  type        = string
  default     = ""
  description = "Optional Artifact Registry URI for the Lab 2 untrusted BYOC sandbox image (e.g., asia-southeast3-docker.pkg.dev/PROJECT_ID/coding-agent-repo/coding-sandbox:v1 — Bangkok AR is verified working for Singapore BYOC Sandbox pulls by gcp-sa-vertex-sandbox; no second Singapore AR repository is needed)"
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
  default     = "gemini-4-hydrogen"
  description = "Default Frontier Gemini 4 coding & fast tool-calling model ID (use gemini-4-argon with model_location = \"asia-southeast1\" for strict regional residency)"
}

variable "reasoning_model_name" {
  type        = string
  default     = "gemini-4-neon"
  description = "Frontier Gemini 4 deep reasoning, architecture & review model ID (injected as REASONING_MODEL_NAME)"
}

variable "model_location" {
  type        = string
  default     = "global"
  description = "Vertex AI / Gemini Enterprise inference location injected as MODEL_LOCATION (gemini-4-hydrogen and gemini-4-neon require global; Agent Runtime stays in var.location = asia-southeast1)"
}

variable "thinking_level" {
  type        = string
  default     = "MEDIUM"
  description = "Gemini 4 ThinkingConfig thinking_level injected as THINKING_LEVEL (strictly LOW, MEDIUM, HIGH, or XHIGH; MINIMAL returns HTTP 400)"

  validation {
    condition     = contains(["LOW", "MEDIUM", "HIGH", "XHIGH"], upper(var.thinking_level))
    error_message = "thinking_level must be one of: LOW, MEDIUM, HIGH, XHIGH (Gemini 4 rejects MINIMAL with HTTP 400)."
  }
}

variable "agy_execution_mode" {
  type        = string
  default     = "auto"
  description = "Antigravity (agy) headless harness execution mode injected as AGY_EXECUTION_MODE (auto, local, or sandbox)"

  validation {
    condition     = contains(["auto", "local", "sandbox"], var.agy_execution_mode)
    error_message = "agy_execution_mode must be one of: auto, local, sandbox."
  }
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
  description = "Lab 4 Vertex AI Skill Registry Preview region injected as SKILL_REGISTRY_LOCATION (strictly 3 supported regions: us-central1, europe-west4, us-east5)"
}

variable "agent_registry_location" {
  type        = string
  default     = "asia-southeast3"
  description = "Lab 4 Agent Registry A2A/MCP discovery region injected as AGENT_REGISTRY_LOCATION (Bangkok asia-southeast3 first)"
}

variable "agent_registry_skills_location" {
  type        = string
  default     = "global"
  description = "Lab 4 Agent Registry standalone skills location injected as AGENT_REGISTRY_SKILLS_LOCATION (falls back to global because standalone skill endpoints currently time out in asia-southeast3)"
}
