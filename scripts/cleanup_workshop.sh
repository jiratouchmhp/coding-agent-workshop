#!/usr/bin/env bash
# =============================================================================
# Enterprise Coding Agent Workshop — Safe & Idempotent Resource Cleanup Script
# =============================================================================
# Usage:
#   ./scripts/cleanup_workshop.sh [--dry-run] [--yes] [--allow-non-sandbox]
#                                 [--include-skill-registry]
#                                 [--project PROJECT_ID] [--env-file PATH]
#
# Tears down workshop cloud resources and local temporary artifacts in order:
#   1. Terraform resources (starter/terraform & solution/terraform if state exists)
#   2. Standalone Agent Platform instance (REASONING_ENGINE_NAME / asia-southeast1
#      sandboxes, snapshots, templates, and parent ReasoningEngine)
#   3. Lab 6 Cloud Monitoring Quality Alert policies ("Coding Agent Quality Drift")
#   4. Lab 4/7 Agent Registry standalone skills in AGENT_REGISTRY_LOCATION (asia-southeast3)
#   5. Vertex AI Skill Registry skills in SKILL_REGISTRY_LOCATION (us-central1)
#      ONLY when --include-skill-registry is explicitly passed (permanent ID lockout!)
#   6. Artifact Registry images in AR_LOCATION (asia-southeast3)
#   7. Local temporary artifacts (dist/, */terraform/coding_agent_source.tar.gz,
#      /tmp/byoc_smoke, /tmp/coding_agent_workspace)
# =============================================================================

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
cd "${REPO_ROOT}"

DRY_RUN=0
ASSUME_YES=0
ALLOW_NON_SANDBOX=0
INCLUDE_SKILL_REGISTRY=0
CLI_PROJECT=""
ENV_FILE="${REPO_ROOT}/.env"

usage() {
  cat <<'EOF'
Usage: ./scripts/cleanup_workshop.sh [OPTIONS]

Safely and idempotently tear down workshop GCP resources and local artifacts.

Options:
  --dry-run                 Preview every teardown step without deleting anything
  --yes                     Skip interactive confirmation prompt (does NOT bypass prod safety gate)
  --allow-non-sandbox       Override safety abort when project ID contains 'prod' (USE WITH EXTREME CAUTION)
  --include-skill-registry  Also delete Vertex AI Skill Registry skills in SKILL_REGISTRY_LOCATION
                            (WARNING: deleted SKILL_IDs are permanently reserved!)
  --project <PROJECT_ID>    Override GOOGLE_CLOUD_PROJECT from .env
  --env-file <PATH>         Path to .env file (default: ./.env)
  -h, --help                Show this help message
EOF
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --dry-run)
      DRY_RUN=1
      shift
      ;;
    --yes|-y)
      ASSUME_YES=1
      shift
      ;;
    --allow-non-sandbox)
      ALLOW_NON_SANDBOX=1
      shift
      ;;
    --include-skill-registry)
      INCLUDE_SKILL_REGISTRY=1
      shift
      ;;
    --project)
      if [[ $# -lt 2 ]]; then
        echo "ERROR: --project requires a GCP project ID." >&2
        exit 2
      fi
      CLI_PROJECT="$2"
      shift 2
      ;;
    --env-file)
      if [[ $# -lt 2 ]]; then
        echo "ERROR: --env-file requires a file path." >&2
        exit 2
      fi
      ENV_FILE="$2"
      shift 2
      ;;
    -h|--help)
      usage
      exit 0
      ;;
    *)
      echo "ERROR: Unknown argument: $1" >&2
      usage >&2
      exit 2
      ;;
  esac
done

# Color helpers (disabled automatically when stdout is not a TTY)
if [[ -t 1 ]]; then
  C_GREEN='\033[0;32m'
  C_RED='\033[0;31m'
  C_YELLOW='\033[0;33m'
  C_BLUE='\033[0;34m'
  C_CYAN='\033[0;36m'
  C_BOLD='\033[1m'
  C_RESET='\033[0m'
else
  C_GREEN=''
  C_RED=''
  C_YELLOW=''
  C_BLUE=''
  C_CYAN=''
  C_BOLD=''
  C_RESET=''
fi

info()    { printf "${C_CYAN}[INFO]${C_RESET} %s\n" "$1"; }
ok()      { printf "${C_GREEN}[DONE]${C_RESET} %s\n" "$1"; }
skip()    { printf "${C_YELLOW}[SKIP]${C_RESET} %s\n" "$1"; }
warn()    { printf "${C_YELLOW}[WARN]${C_RESET} %s\n" "$1"; }
dry()     { printf "${C_CYAN}[DRY-RUN]${C_RESET} %s\n" "$1"; }
section() { printf "\n${C_BLUE}=== %s ===${C_RESET}\n" "$1"; }

# Load .env if present
if [[ -f "${ENV_FILE}" ]]; then
  info "Loading configuration from ${ENV_FILE}"
  set -a
  # shellcheck disable=SC1090
  source "${ENV_FILE}"
  set +a
else
  info "No ${ENV_FILE} found; using active shell environment and regional defaults."
fi

PROJECT_ID="${CLI_PROJECT:-${GOOGLE_CLOUD_PROJECT:-}}"
if [[ -z "${PROJECT_ID}" || "${PROJECT_ID}" == "your-gcp-project-id" ]]; then
  if command -v gcloud >/dev/null 2>&1; then
    PROJECT_ID="$(gcloud config get-value project 2>/dev/null | tr -d '[:space:]' || true)"
  fi
fi
if [[ "${PROJECT_ID}" == "(unset)" || "${PROJECT_ID}" == "your-gcp-project-id" ]]; then
  PROJECT_ID=""
fi

PRIMARY_REG="${PRIMARY_REGION:-asia-southeast3}"
AGENT_PLATFORM_LOC="${GOOGLE_CLOUD_LOCATION:-asia-southeast1}"
AR_LOC="${AR_LOCATION:-${PRIMARY_REG}}"
AR_REPO="${AR_REPOSITORY:-coding-agent-repo}"
AGENT_REG_LOC="${AGENT_REGISTRY_LOCATION:-${PRIMARY_REG}}"
SKILL_REG_LOC="${SKILL_REGISTRY_LOCATION:-us-central1}"

ENGINE_NAME="${REASONING_ENGINE_NAME:-}"
if [[ -z "${ENGINE_NAME}" && -n "${PROJECT_ID}" && -n "${REASONING_ENGINE_ID:-}" ]]; then
  ENGINE_NAME="projects/${PROJECT_ID}/locations/${AGENT_PLATFORM_LOC}/reasoningEngines/${REASONING_ENGINE_ID}"
fi

printf "\n=============================================================================\n"
printf "Enterprise Coding Agent Workshop — Teardown Plan\n"
printf "=============================================================================\n"
printf "  Mode:                    %s\n" "$([[ "${DRY_RUN}" -eq 1 ]] && echo "DRY-RUN (no mutations)" || echo "LIVE TEARDOWN")"
printf "  GCP Project:             %s\n" "${PROJECT_ID:-<none — local cleanup only>}"
printf "  Agent Platform Location: %s\n" "${AGENT_PLATFORM_LOC}"
printf "  Agent Registry Location: %s\n" "${AGENT_REG_LOC}"
printf "  Artifact Registry:       %s-docker.pkg.dev/%s/%s\n" "${AR_LOC}" "${PROJECT_ID:-<project>}" "${AR_REPO}"
printf "  Skill Registry Cleanup:  %s\n" "$([[ "${INCLUDE_SKILL_REGISTRY}" -eq 1 ]] && echo "ENABLED (${SKILL_REG_LOC} — PERMANENT SKILL_ID RESERVATION!)" || echo "SKIPPED (safe default)")"
printf "=============================================================================\n"

# Production project safety check
if [[ -n "${PROJECT_ID}" ]]; then
  LOWER_PROJ="$(printf '%s' "${PROJECT_ID}" | tr '[:upper:]' '[:lower:]')"
  if [[ "${LOWER_PROJ}" == *prod* ]]; then
    printf "\n${C_BOLD}${C_RED}WARNING: Target project '%s' looks like a PRODUCTION project (contains 'prod')!${C_RESET}\n" "${PROJECT_ID}" >&2
    if [[ "${DRY_RUN}" -eq 0 && "${ALLOW_NON_SANDBOX}" -ne 1 ]]; then
      echo "ERROR: Refusing live teardown against project '${PROJECT_ID}' (contains 'prod')." >&2
      echo "Note: --yes does NOT bypass this safety guardrail." >&2
      echo "Verify GOOGLE_CLOUD_PROJECT, run with --dry-run first, or pass --allow-non-sandbox if you explicitly accept the risk." >&2
      exit 1
    fi
  fi
fi

# Confirmation prompt when live and not --yes
if [[ "${DRY_RUN}" -eq 0 && "${ASSUME_YES}" -eq 0 ]]; then
  printf "\nProceed with teardown? [y/N]: "
  read -r REPLY
  if [[ ! "${REPLY}" =~ ^[Yy]([Ee][Ss])?$ ]]; then
    info "Cleanup cancelled by user."
    exit 0
  fi
fi

CAN_RUN_GCP=0
if [[ -n "${PROJECT_ID}" ]] && command -v gcloud >/dev/null 2>&1; then
  CAN_RUN_GCP=1
elif [[ -z "${PROJECT_ID}" ]]; then
  warn "GOOGLE_CLOUD_PROJECT is unset; skipping GCP teardown steps (Steps 2-6) and cleaning local artifacts only."
else
  warn "gcloud CLI not found on PATH; skipping GCP CLI teardown steps (Steps 2-6)."
fi

tf_state_has_resources() {
  local tf_dir="$1"
  if [[ -f "${tf_dir}/terraform.tfstate" ]]; then
    python3 - "${tf_dir}/terraform.tfstate" <<'PYEOF'
import json, sys
try:
    data = json.load(open(sys.argv[1], encoding="utf-8"))
    sys.exit(0 if data.get("resources") else 1)
except Exception:
    sys.exit(0)
PYEOF
    return $?
  fi
  # Also detect configured remote backend state
  [[ -f "${tf_dir}/.terraform/terraform.tfstate" ]]
}

# -----------------------------------------------------------------------------
# Step 1: Terraform Resources (starter/terraform & solution/terraform)
# -----------------------------------------------------------------------------
section "Step 1: Terraform Resources (starter/terraform & solution/terraform)"

for tf_dir in starter/terraform solution/terraform; do
  if [[ ! -d "${tf_dir}" ]]; then
    skip "Directory not found: ${tf_dir}"
    continue
  fi
  if ! tf_state_has_resources "${tf_dir}"; then
    skip "No active Terraform state in ${tf_dir}"
    continue
  fi

  TF_ARGS=()
  if [[ -f "${tf_dir}/terraform.tfvars" ]]; then
    TF_ARGS+=(-var-file=terraform.tfvars)
  fi

  if [[ "${DRY_RUN}" -eq 1 ]]; then
    dry "Would run: terraform -chdir=${tf_dir} destroy -auto-approve ${TF_ARGS[*]:-}"
  elif ! command -v terraform >/dev/null 2>&1; then
    warn "Active Terraform state found in ${tf_dir}, but 'terraform' binary is not installed."
  else
    info "Destroying Terraform resources in ${tf_dir}..."
    if terraform -chdir="${tf_dir}" destroy -auto-approve ${TF_ARGS[@]+"${TF_ARGS[@]}"}; then
      ok "Destroyed Terraform resources in ${tf_dir}"
    else
      warn "terraform destroy encountered an error in ${tf_dir}; continuing remaining cleanup steps."
    fi
  fi
done

# -----------------------------------------------------------------------------
# Step 2: Standalone Agent Platform Instance (Sandboxes, Snapshots, Templates)
# -----------------------------------------------------------------------------
section "Step 2: Standalone Agent Platform Instance (${AGENT_PLATFORM_LOC})"

if [[ -z "${ENGINE_NAME}" ]]; then
  skip "REASONING_ENGINE_NAME / REASONING_ENGINE_ID not set in environment."
  if [[ -n "${PROJECT_ID}" ]]; then
    info "To check for orphaned instances in ${AGENT_PLATFORM_LOC}, run:"
    info "  curl -sS -H \"Authorization: Bearer \$(gcloud auth print-access-token)\" \"https://${AGENT_PLATFORM_LOC}-aiplatform.googleapis.com/v1beta1/projects/${PROJECT_ID}/locations/${AGENT_PLATFORM_LOC}/reasoningEngines\""
  fi
elif [[ "${DRY_RUN}" -eq 1 ]]; then
  dry "Would delete all sandboxes, snapshots, and templates under: ${ENGINE_NAME}"
  dry "Would delete parent ReasoningEngine (force=true): ${ENGINE_NAME}"
elif [[ "${CAN_RUN_GCP}" -eq 0 ]]; then
  skip "Cannot delete ${ENGINE_NAME} without gcloud + GOOGLE_CLOUD_PROJECT."
else
  # Extract location directly from resource name if present
  ENGINE_LOC="$(printf '%s\n' "${ENGINE_NAME}" | sed -nE 's|^projects/[^/]+/locations/([^/]+)/reasoningEngines/.*|\1|p')"
  ENGINE_LOC="${ENGINE_LOC:-${AGENT_PLATFORM_LOC}}"

  # 2a. Clean up child sandboxes, snapshots, and templates via sandbox_lifecycle CLI if available
  PY_BIN=""
  if [[ -x "${REPO_ROOT}/solution/.venv/bin/python" ]]; then
    PY_BIN="${REPO_ROOT}/solution/.venv/bin/python"
  elif [[ -x "${REPO_ROOT}/starter/.venv/bin/python" ]]; then
    PY_BIN="${REPO_ROOT}/starter/.venv/bin/python"
  fi

  if [[ -n "${PY_BIN}" ]]; then
    info "Deleting sandboxes, snapshots, and templates under ${ENGINE_NAME}..."
    if (cd "${REPO_ROOT}/solution" && "${PY_BIN}" -m coding_agent.tools.sandbox_lifecycle \
      --project "${PROJECT_ID}" --location "${ENGINE_LOC}" --instance "${ENGINE_NAME}" \
      cleanup-all --include-templates); then
      ok "Cleaned up sandboxes, snapshots, and templates under ${ENGINE_NAME}"
    else
      warn "sandbox_lifecycle cleanup-all returned non-zero (instance may already be deleted); continuing with force delete."
    fi
  else
    info "Local venv not detected; relying on Agent Platform force=true teardown for child resources."
  fi

  # 2b. Force-delete parent ReasoningEngine via v1beta1 REST API
  TOKEN="$(gcloud auth print-access-token 2>/dev/null || true)"
  if [[ -z "${TOKEN}" ]]; then
    warn "Unable to obtain gcloud access token; skipping deletion of ${ENGINE_NAME}."
  else
    DELETE_URL="https://${ENGINE_LOC}-aiplatform.googleapis.com/v1beta1/${ENGINE_NAME}?force=true"
    HTTP_CODE="$(curl -sS -o /tmp/cleanup_engine_resp_$$.json -w "%{http_code}" \
      -X DELETE \
      -H "Authorization: Bearer ${TOKEN}" \
      "${DELETE_URL}" || echo "000")"
    if [[ "${HTTP_CODE}" == "200" || "${HTTP_CODE}" == "202" || "${HTTP_CODE}" == "204" ]]; then
      ok "Requested deletion (HTTP ${HTTP_CODE}) for ${ENGINE_NAME}"
    elif [[ "${HTTP_CODE}" == "404" ]]; then
      skip "ReasoningEngine already deleted (HTTP 404): ${ENGINE_NAME}"
    else
      warn "Unexpected HTTP ${HTTP_CODE} deleting ${ENGINE_NAME}: $(cat /tmp/cleanup_engine_resp_$$.json 2>/dev/null || true)"
    fi
    rm -f "/tmp/cleanup_engine_resp_$$.json"
  fi
fi

# -----------------------------------------------------------------------------
# Step 3: Lab 6 Cloud Monitoring Quality Alert Policies
# -----------------------------------------------------------------------------
section "Step 3: Lab 6 Cloud Monitoring Quality Alert Policies"

if [[ "${DRY_RUN}" -eq 1 ]]; then
  dry "Would list and delete Cloud Monitoring alert policies matching displayName:\"Coding Agent Quality Drift\" in project '${PROJECT_ID:-<project>}'"
elif [[ "${CAN_RUN_GCP}" -eq 0 ]]; then
  skip "Skipping Cloud Monitoring alert policy cleanup (GCP unavailable)."
else
  ALERT_POLICIES="$(gcloud monitoring policies list \
    --project="${PROJECT_ID}" \
    --filter='displayName:"Coding Agent Quality Drift"' \
    --format='value(name)' 2>/dev/null || true)"

  if [[ -z "${ALERT_POLICIES}" ]]; then
    skip "No 'Coding Agent Quality Drift' alert policies found in ${PROJECT_ID}."
  else
    while IFS= read -r policy_name; do
      [[ -z "${policy_name}" ]] && continue
      info "Deleting Cloud Monitoring alert policy: ${policy_name}"
      if gcloud monitoring policies delete "${policy_name}" --project="${PROJECT_ID}" --quiet; then
        ok "Deleted alert policy: ${policy_name}"
      else
        warn "Failed to delete alert policy: ${policy_name}"
      fi
    done <<< "${ALERT_POLICIES}"
  fi
fi

# -----------------------------------------------------------------------------
# Step 4: Lab 4/7 Agent Registry Standalone Skills (AGENT_REGISTRY_LOCATION)
# -----------------------------------------------------------------------------
section "Step 4: Agent Registry Standalone Skills (${AGENT_REG_LOC})"

if [[ "${DRY_RUN}" -eq 1 ]]; then
  dry "Would list and delete workshop Agent Registry standalone skills (private-secure-code-review*) in location '${AGENT_REG_LOC}'"
elif [[ "${CAN_RUN_GCP}" -eq 0 ]]; then
  skip "Skipping Agent Registry standalone skills cleanup (GCP unavailable)."
else
  AGENT_REG_SKILLS="$(gcloud agent-registry skills list \
    --project="${PROJECT_ID}" \
    --location="${AGENT_REG_LOC}" \
    --format='value(name)' 2>/dev/null || true)"

  FOUND_AR_SKILL=0
  if [[ -n "${AGENT_REG_SKILLS}" ]]; then
    while IFS= read -r skill_full_name; do
      [[ -z "${skill_full_name}" ]] && continue
      skill_short="${skill_full_name##*/}"
      if [[ "${skill_short}" == private-secure-code-review* ]]; then
        FOUND_AR_SKILL=1
        info "Deleting Agent Registry standalone skill: ${skill_short} (${AGENT_REG_LOC})"
        if gcloud agent-registry skills delete "${skill_short}" \
          --project="${PROJECT_ID}" \
          --location="${AGENT_REG_LOC}" \
          --quiet 2>/dev/null; then
          ok "Deleted Agent Registry skill: ${skill_short}"
        else
          warn "Could not delete Agent Registry skill '${skill_short}' (may require decommission/force or already deleted)."
        fi
      fi
    done <<< "${AGENT_REG_SKILLS}"
  fi

  if [[ "${FOUND_AR_SKILL}" -eq 0 ]]; then
    skip "No workshop Agent Registry standalone skills (private-secure-code-review*) found in ${AGENT_REG_LOC}."
  fi
fi

# -----------------------------------------------------------------------------
# Step 5: Vertex AI Skill Registry Skills (Opt-In ONLY: --include-skill-registry)
# -----------------------------------------------------------------------------
section "Step 5: Vertex AI Skill Registry Skills (${SKILL_REG_LOC})"

if [[ "${INCLUDE_SKILL_REGISTRY}" -eq 0 ]]; then
  skip "Vertex AI Skill Registry (${SKILL_REG_LOC}) teardown skipped by default."
  info "Deleted Vertex AI Skill Registry SKILL_IDs (e.g., 'secure-code-review') are permanently reserved."
  info "Pass --include-skill-registry ONLY if you intentionally want to permanently retire the SKILL_ID."
else
  printf "\n${C_BOLD}${C_RED}=============================================================================${C_RESET}\n"
  printf "${C_BOLD}${C_RED}WARNING: --include-skill-registry ENABLED!${C_RESET}\n"
  printf "${C_BOLD}${C_YELLOW}Deleted Vertex AI Skill Registry SKILL_IDs are PERMANENTLY RESERVED (and locked${C_RESET}\n"
  printf "${C_BOLD}${C_YELLOW}for >=24h) and CANNOT be recreated with the same ID ('secure-code-review')!${C_RESET}\n"
  printf "${C_BOLD}${C_RED}=============================================================================${C_RESET}\n\n"

  SKILL_RESOURCE="projects/${PROJECT_ID:-<project>}/locations/${SKILL_REG_LOC}/skills/secure-code-review"
  if [[ "${DRY_RUN}" -eq 1 ]]; then
    dry "Would DELETE Vertex AI Skill Registry skill: ${SKILL_RESOURCE}"
  elif [[ "${CAN_RUN_GCP}" -eq 0 ]]; then
    skip "Skipping Vertex AI Skill Registry deletion (GCP unavailable)."
  else
    TOKEN="$(gcloud auth print-access-token 2>/dev/null || true)"
    if [[ -z "${TOKEN}" ]]; then
      warn "Unable to obtain gcloud access token; skipping Skill Registry deletion."
    else
      SKILL_URL="https://${SKILL_REG_LOC}-aiplatform.googleapis.com/v1beta1/${SKILL_RESOURCE}"
      HTTP_CODE="$(curl -sS -o /tmp/cleanup_skill_resp_$$.json -w "%{http_code}" \
        -X DELETE \
        -H "Authorization: Bearer ${TOKEN}" \
        "${SKILL_URL}" || echo "000")"
      if [[ "${HTTP_CODE}" == "200" || "${HTTP_CODE}" == "202" || "${HTTP_CODE}" == "204" ]]; then
        ok "Deleted Vertex AI Skill Registry skill (HTTP ${HTTP_CODE}): ${SKILL_RESOURCE}"
      elif [[ "${HTTP_CODE}" == "404" ]]; then
        skip "Vertex AI Skill Registry skill not found (HTTP 404): ${SKILL_RESOURCE}"
      else
        warn "Unexpected HTTP ${HTTP_CODE} deleting ${SKILL_RESOURCE}: $(cat /tmp/cleanup_skill_resp_$$.json 2>/dev/null || true)"
      fi
      rm -f "/tmp/cleanup_skill_resp_$$.json"
    fi
  fi
fi

# -----------------------------------------------------------------------------
# Step 6: Artifact Registry Images (AR_LOCATION)
# -----------------------------------------------------------------------------
section "Step 6: Artifact Registry Images (${AR_LOC})"

AR_IMAGES=(
  "${AR_LOC}-docker.pkg.dev/${PROJECT_ID:-<project>}/${AR_REPO}/coding-sandbox"
  "${AR_LOC}-docker.pkg.dev/${PROJECT_ID:-<project>}/${AR_REPO}/coding-agent"
)

if [[ "${DRY_RUN}" -eq 1 ]]; then
  for img in "${AR_IMAGES[@]}"; do
    dry "Would delete Artifact Registry image package (all tags/digests): ${img}"
  done
elif [[ "${CAN_RUN_GCP}" -eq 0 ]]; then
  skip "Skipping Artifact Registry image cleanup (GCP unavailable)."
else
  for img in "${AR_IMAGES[@]}"; do
    IMG_LIST="$(gcloud artifacts docker images list "${img}" \
      --project="${PROJECT_ID}" \
      --format='value(package)' 2>/dev/null || true)"
    if [[ -n "${IMG_LIST}" ]]; then
      info "Deleting Artifact Registry image: ${img}"
      if gcloud artifacts docker images delete "${img}" \
        --delete-tags \
        --quiet \
        --project="${PROJECT_ID}"; then
        ok "Deleted Artifact Registry image: ${img}"
      else
        warn "Failed to delete Artifact Registry image: ${img}"
      fi
    else
      skip "Artifact Registry image not found: ${img}"
    fi
  done
fi

# -----------------------------------------------------------------------------
# Step 7: Local Temporary Artifacts
# -----------------------------------------------------------------------------
section "Step 7: Local Temporary Artifacts"

LOCAL_ARTIFACTS=(
  "${REPO_ROOT}/dist"
  "${REPO_ROOT}/starter/terraform/coding_agent_source.tar.gz"
  "${REPO_ROOT}/solution/terraform/coding_agent_source.tar.gz"
  "/tmp/byoc_smoke"
  "/tmp/coding_agent_workspace"
)

for target_path in "${LOCAL_ARTIFACTS[@]}"; do
  if [[ -e "${target_path}" ]]; then
    if [[ "${DRY_RUN}" -eq 1 ]]; then
      dry "Would remove local artifact: ${target_path}"
    else
      rm -rf "${target_path}"
      ok "Removed local artifact: ${target_path}"
    fi
  else
    skip "Local artifact not present: ${target_path}"
  fi
done

printf "\n=============================================================================\n"
if [[ "${DRY_RUN}" -eq 1 ]]; then
  printf "Dry-run teardown preview complete (no resources were modified).\n"
else
  printf "Workshop teardown complete.\n"
fi
printf "=============================================================================\n"
exit 0
