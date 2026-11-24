#!/usr/bin/env bash
# =============================================================================
# Enterprise Coding Agent Workshop — Pre-Flight Environment & GCP Validator
# =============================================================================
# Usage:
#   ./scripts/preflight_check.sh [--offline|--skip-gcp] [--env-file PATH]
#
# Validates local developer toolchain (including advisory Antigravity `agy` CLI),
# Zero-Docker readiness, Gemini 4 model/location/thinking_level compatibility,
# regional config (Bangkok asia-southeast3 first — falling back to Singapore
# asia-southeast1 only for Agent Platform services not yet in Bangkok, global
# for frontier Gemini 4 models, Agent Registry standalone skills & Eval, and
# us-central1 for Vertex AI Skill Registry), and (when online) gcloud auth,
# gcloud alpha availability, Application Default Credentials (ADC), production
# project guardrails, and required enabled GCP APIs.
# =============================================================================

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
cd "${REPO_ROOT}"

OFFLINE=0
ENV_FILE="${REPO_ROOT}/.env"

usage() {
  cat <<'EOF'
Usage: ./scripts/preflight_check.sh [OPTIONS]

Run pre-flight checks for the Enterprise Coding Agent Workshop.

Options:
  --offline, --skip-gcp  Skip live gcloud network, auth, ADC, and API checks (for local CI/dry-runs)
  --env-file <path>      Path to .env file to validate (default: ./.env)
  -h, --help             Show this help message
EOF
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --offline|--skip-gcp)
      OFFLINE=1
      shift
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

PASS_COUNT=0
FAIL_COUNT=0
WARN_COUNT=0
INFO_COUNT=0

pass() {
  PASS_COUNT=$((PASS_COUNT + 1))
  printf "${C_GREEN}[PASS]${C_RESET} %s\n" "$1"
}

fail() {
  FAIL_COUNT=$((FAIL_COUNT + 1))
  printf "${C_RED}[FAIL]${C_RESET} %s\n" "$1"
}

warn() {
  WARN_COUNT=$((WARN_COUNT + 1))
  printf "${C_YELLOW}[WARN]${C_RESET} %s\n" "$1"
}

info() {
  INFO_COUNT=$((INFO_COUNT + 1))
  printf "${C_CYAN}[INFO]${C_RESET} %s\n" "$1"
}

section() {
  printf "\n${C_BLUE}=== %s ===${C_RESET}\n" "$1"
}

# -----------------------------------------------------------------------------
# 1. Local Toolchain Checks (Python, uv, Terraform, Docker)
# -----------------------------------------------------------------------------
section "1. Local Toolchain Checks"

if command -v python3 >/dev/null 2>&1; then
  PY_VER="$(python3 -c 'import sys; print(f"{sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}")')"
  if python3 -c 'import sys; sys.exit(0 if sys.version_info >= (3, 11) else 1)'; then
    pass "Python >= 3.11 detected (Python ${PY_VER})"
  else
    fail "Python ${PY_VER} detected, but Python >= 3.11 is required."
  fi
else
  fail "python3 not found on PATH. Install Python 3.11+ before proceeding."
fi

if command -v uv >/dev/null 2>&1; then
  UV_VER="$(uv --version 2>/dev/null | head -n 1 || echo "uv")"
  pass "uv detected (${UV_VER})"
else
  warn "uv not found on PATH."
  info "Recommended zero-sudo standalone install (avoids Debian/Ubuntu missing python3-venv pitfall):"
  info "  curl -LsSf https://astral.sh/uv/install.sh -o /tmp/uv_install.sh && sh /tmp/uv_install.sh"
  info "Alternative without uv: run 'make install-pip' (requires system python3-venv on Debian/Ubuntu)."
fi

if command -v terraform >/dev/null 2>&1; then
  TF_RAW="$(terraform version 2>/dev/null | head -n 1 || true)"
  TF_VER="$(printf '%s\n' "${TF_RAW}" | sed -nE 's/^Terraform v([0-9]+\.[0-9]+(\.[0-9]+)?).*/\1/p')"
  if [[ -n "${TF_VER}" ]] && python3 - "${TF_VER}" <<'PYEOF'
import sys
parts = [int(p) for p in sys.argv[1].split(".")]
while len(parts) < 3:
    parts.append(0)
sys.exit(0 if tuple(parts[:3]) >= (1, 5, 0) else 1)
PYEOF
  then
    pass "Terraform >= 1.5 detected (v${TF_VER})"
  elif [[ -n "${TF_VER}" ]]; then
    warn "Terraform v${TF_VER} detected; Terraform >= 1.5 is required for Lab 5 (optional until Lab 5)."
  else
    warn "Terraform found on PATH (${TF_RAW:-unknown version}); verify version >= 1.5 before Lab 5."
  fi
else
  warn "terraform not found on PATH (optional until Lab 5; install Terraform >= 1.5 for Lab 5 IaC or use agents-cli deploy)."
fi

if command -v docker >/dev/null 2>&1; then
  DOCKER_VER="$(docker --version 2>/dev/null | head -n 1 || echo "docker")"
  pass "Local Docker detected (${DOCKER_VER}) — optional; Zero-Docker path is also 100% supported."
else
  info "Local Docker not detected — Zero-Docker path (Cloud Build + source_code_spec + make test-sandbox-local / test-agent-local) is 100% supported!"
fi

if command -v tar >/dev/null 2>&1; then
  pass "tar detected (required for 'make pack-agent-source' Zero-Docker / Zero-AR tarball deploys)"
else
  warn "tar not found on PATH (needed for 'make pack-agent-source')."
fi

if command -v agents-cli >/dev/null 2>&1; then
  pass "agents-cli detected ($(command -v agents-cli)) — optional for Labs 1-8"
else
  info "agents-cli not found on PATH (optional for Labs 1-8; install anytime with: uvx google-agents-cli setup)"
fi

if command -v agy >/dev/null 2>&1; then
  AGY_VER="$(agy --version 2>/dev/null | head -n 1 || echo "agy")"
  pass "Antigravity CLI (agy) detected (${AGY_VER}) — ready for local headless harness mode"
else
  info "Antigravity CLI (agy) not found on PATH (optional locally — 'make test-agy-harness' --dry-run and Bangkok Cloud Build BYOC images work without installing agy locally and without Docker)."
  info "  To install agy locally for headless mode: curl -fsSL https://antigravity.google/cli/install.sh -o /tmp/agy_install.sh && bash /tmp/agy_install.sh"
fi

# -----------------------------------------------------------------------------
# 2. Environment File (.env) & Regional Sanity Checks
# -----------------------------------------------------------------------------
section "2. Environment (.env) & Regional Sanity Checks"

ENV_LOADED_FROM=""
if [[ -f "${ENV_FILE}" ]]; then
  pass "Found environment file: ${ENV_FILE}"
  ENV_LOADED_FROM="${ENV_FILE}"
  set -a
  # shellcheck disable=SC1090
  source "${ENV_FILE}"
  set +a
else
  warn "Environment file not found: ${ENV_FILE} (copy template with: cp .env.example .env)"
  if [[ -f "${REPO_ROOT}/.env.example" ]]; then
    info "Checking default regional settings from .env.example until .env is created."
    ENV_LOADED_FROM="${REPO_ROOT}/.env.example"
    # Read .env.example defaults without overwriting variables already exported in shell
    while IFS='=' read -r raw_key raw_val; do
      # Trim leading whitespace before checking for optional `export ` prefix
      key="${raw_key#"${raw_key%%[![:space:]]*}"}"
      [[ -z "${key}" || "${key}" == \#* ]] && continue
      if [[ "${key}" == export[[:space:]]* ]]; then
        key="${key#export}"
        key="${key#"${key%%[![:space:]]*}"}"
      fi
      # Trim trailing whitespace from key
      key="${key%"${key##*[![:space:]]}"}"
      [[ -z "${key}" ]] && continue
      raw_val="${raw_val%%#*}"
      val="$(printf '%s' "${raw_val}" | sed -e 's/^[[:space:]]*//' -e 's/[[:space:]]*$//')"
      val="${val%\"}"
      val="${val#\"}"
      val="${val%\'}"
      val="${val#\'}"
      if [[ -z "${!key+x}" ]]; then
        export "${key}=${val}"
      fi
    done < <(grep -E '^[[:space:]]*(export[[:space:]]+)?[A-Za-z_][A-Za-z0-9_]*=' "${REPO_ROOT}/.env.example" || true)
  fi
fi

PRIMARY_REG="${PRIMARY_REGION:-asia-southeast3}"
AR_LOC="${AR_LOCATION:-${PRIMARY_REG}}"
BUILD_LOC="${BUILD_LOCATION:-${PRIMARY_REG}}"
GKE_LOC="${GKE_LOCATION:-${PRIMARY_REG}}"
AGENT_PLATFORM_LOC="${GOOGLE_CLOUD_LOCATION:-}"
AGENT_REG_LOC="${AGENT_REGISTRY_LOCATION:-${PRIMARY_REG}}"
AGENT_REG_SKILLS_LOC="${AGENT_REGISTRY_SKILLS_LOCATION:-global}"
SKILL_REG_LOC="${SKILL_REGISTRY_LOCATION:-us-central1}"
EVAL_LOC="${EVAL_LOCATION:-global}"
MODEL_VAL="${MODEL_NAME:-gemini-4-hydrogen}"
REASONING_MODEL_VAL="${REASONING_MODEL_NAME:-gemini-4-neon}"
AGY_MODEL_VAL="${AGY_MODEL:-gemini-4-hydrogen}"
MODEL_LOC="${MODEL_LOCATION:-global}"
THINK_LVL="${THINKING_LEVEL:-MEDIUM}"
PROJECT_ID="${GOOGLE_CLOUD_PROJECT:-}"

# Bangkok-first default region check
if [[ "${PRIMARY_REG}" == "asia-southeast3" ]]; then
  pass "PRIMARY_REGION=${PRIMARY_REG} (Bangkok first — Cloud Build, Artifact Registry, Secret Manager, Agent Registry A2A/MCP, and Lab 8 GKE)"
else
  info "PRIMARY_REGION=${PRIMARY_REG} (workshop default is Bangkok 'asia-southeast3')"
fi
info "Bangkok-first regional targets: AR_LOCATION=${AR_LOC} (verified for Singapore Runtime & BYOC Sandbox pulls), BUILD_LOCATION=${BUILD_LOC}, AGENT_REGISTRY_LOCATION=${AGENT_REG_LOC} (A2A/MCP), GKE_LOCATION=${GKE_LOC}"
if [[ "${AGENT_REG_SKILLS_LOC}" == "global" ]]; then
  pass "AGENT_REGISTRY_SKILLS_LOCATION=${AGENT_REG_SKILLS_LOC} (required fallback for 'gcloud alpha agent-registry skills' & ADK GCPSkillRegistry; AGENT_REGISTRY_LOCATION=${AGENT_REG_LOC} stays in Bangkok for A2A/MCP)"
else
  warn "AGENT_REGISTRY_SKILLS_LOCATION=${AGENT_REG_SKILLS_LOC} (recommended: 'global' — standalone Agent Registry skills are not yet supported in asia-southeast3)"
fi

# Agent Platform location check (Singapore asia-southeast1 fallback for services not yet available in Bangkok)
if [[ -z "${AGENT_PLATFORM_LOC}" ]]; then
  fail "GOOGLE_CLOUD_LOCATION is unset. Set GOOGLE_CLOUD_LOCATION=asia-southeast1 (Singapore — nearest fallback for Agent Platform services not yet available in Bangkok)."
elif [[ "${AGENT_PLATFORM_LOC}" == "asia-southeast3" ]]; then
  fail "GOOGLE_CLOUD_LOCATION=asia-southeast3 is NOT yet supported for Agent Runtime / Managed Sandboxes. Keep PRIMARY_REGION=asia-southeast3 (Bangkok) and fall back to GOOGLE_CLOUD_LOCATION=asia-southeast1 (Singapore)."
elif [[ "${AGENT_PLATFORM_LOC}" == "asia-southeast2" || "${AGENT_PLATFORM_LOC}" == "australia-southeast2" || "${AGENT_PLATFORM_LOC}" == "northamerica-northeast2" ]]; then
  fail "GOOGLE_CLOUD_LOCATION=${AGENT_PLATFORM_LOC} does NOT support Memory Bank (Lab 3). Fall back to asia-southeast1 (Singapore), us-central1, or europe-west4."
elif [[ "${AGENT_PLATFORM_LOC}" == "global" ]]; then
  fail "GOOGLE_CLOUD_LOCATION=global does NOT support Agent Runtime deployment or CMEK. Set GOOGLE_CLOUD_LOCATION=asia-southeast1 (and keep MODEL_LOCATION=global and EVAL_LOCATION=global)."
elif [[ "${AGENT_PLATFORM_LOC}" == "asia-southeast1" ]]; then
  pass "GOOGLE_CLOUD_LOCATION=${AGENT_PLATFORM_LOC} (Singapore fallback for Agent Platform services not yet in Bangkok: Agent Runtime, Managed Sandboxes, Sessions, Memory Bank, Agent Gateway)"
else
  pass "GOOGLE_CLOUD_LOCATION=${AGENT_PLATFORM_LOC} (Agent Platform regional endpoint)"
fi

# Frontier Gemini 4 model, endpoint location, and thinking_level checks
validate_model_location_pair() {
  local var_name="$1"
  local model_id="$2"
  local model_loc="$3"

  case "${model_id}" in
    gemini-2.5-flash|gemini-2.5-flash-*|gemini-2.5-pro|gemini-2.5-pro-*|gemini-2.0-*|gemini-1.5-*)
      fail "${var_name}=${model_id} uses a retired/legacy Gemini model. Upgrade to MODEL_NAME=gemini-4-hydrogen / REASONING_MODEL_NAME=gemini-4-neon / AGY_MODEL=gemini-4-hydrogen with MODEL_LOCATION=global (or gemini-4-argon with MODEL_LOCATION=asia-southeast1)."
      ;;
    gemini-4-hydrogen|gemini-4-neon)
      if [[ "${model_loc}" == "global" ]]; then
        pass "${var_name}=${model_id} paired with MODEL_LOCATION=global (verified HTTP 200 frontier Gemini 4 endpoint)"
      elif [[ "${model_loc}" == "asia-southeast1" ]]; then
        fail "${var_name}=${model_id} returns HTTP 404 on MODEL_LOCATION=asia-southeast1. Set MODEL_LOCATION=global, or switch to gemini-4-argon for strict asia-southeast1 regional residency."
      elif [[ "${model_loc}" == "asia-southeast3" ]]; then
        fail "${var_name}=${model_id} returns HTTP 501 on MODEL_LOCATION=asia-southeast3. Set MODEL_LOCATION=global, or switch to gemini-4-argon in asia-southeast1."
      else
        warn "${var_name}=${model_id} paired with MODEL_LOCATION=${model_loc} — frontier models gemini-4-hydrogen and gemini-4-neon require MODEL_LOCATION=global."
      fi
      ;;
    gemini-4-argon)
      if [[ "${model_loc}" == "asia-southeast1" ]]; then
        pass "${var_name}=${model_id} paired with MODEL_LOCATION=asia-southeast1 (verified HTTP 200 — strict Singapore regional residency)"
      elif [[ "${model_loc}" == "global" ]]; then
        pass "${var_name}=${model_id} paired with MODEL_LOCATION=global (verified HTTP 200)"
      elif [[ "${model_loc}" == "asia-southeast3" ]]; then
        fail "${var_name}=${model_id} is unsupported on MODEL_LOCATION=asia-southeast3. Set MODEL_LOCATION=asia-southeast1 (regional residency) or MODEL_LOCATION=global."
      else
        warn "${var_name}=${model_id} paired with MODEL_LOCATION=${model_loc} (verified endpoints: asia-southeast1, global)"
      fi
      ;;
    "")
      fail "${var_name} is unset. Set MODEL_NAME=gemini-4-hydrogen, REASONING_MODEL_NAME=gemini-4-neon, and AGY_MODEL=gemini-4-hydrogen (with MODEL_LOCATION=global)."
      ;;
    *)
      info "${var_name}=${model_id} paired with MODEL_LOCATION=${model_loc} (workshop defaults: gemini-4-hydrogen / gemini-4-neon on global)"
      ;;
  esac
}

validate_model_location_pair "MODEL_NAME" "${MODEL_VAL}" "${MODEL_LOC}"
validate_model_location_pair "REASONING_MODEL_NAME" "${REASONING_MODEL_VAL}" "${MODEL_LOC}"
validate_model_location_pair "AGY_MODEL" "${AGY_MODEL_VAL}" "${MODEL_LOC}"

if [[ "${MODEL_VAL}" == gemini-4-* || "${REASONING_MODEL_VAL}" == gemini-4-* || "${AGY_MODEL_VAL}" == gemini-4-* ]]; then
  THINK_LVL_UPPER="$(printf '%s' "${THINK_LVL}" | tr '[:lower:]' '[:upper:]')"
  case "${THINK_LVL_UPPER}" in
    LOW|MEDIUM|HIGH|XHIGH)
      pass "THINKING_LEVEL=${THINK_LVL_UPPER} (valid Gemini 4 thinking level: LOW | MEDIUM | HIGH | XHIGH)"
      ;;
    MINIMAL)
      fail "THINKING_LEVEL=MINIMAL returns HTTP 400 on Gemini 4 models. Set THINKING_LEVEL to LOW, MEDIUM, HIGH, or XHIGH (default: MEDIUM)."
      ;;
    *)
      fail "THINKING_LEVEL=${THINK_LVL} is invalid on Gemini 4 models (returns HTTP 400). Valid values are strictly: LOW, MEDIUM, HIGH, XHIGH."
      ;;
  esac
  if [[ -n "${THINKING_BUDGET:-}" ]]; then
    warn "THINKING_BUDGET is set, but passing thinking_budget returns HTTP 400 on Gemini 4 models. Unset THINKING_BUDGET and use THINKING_LEVEL instead."
  fi
fi

# Skill Registry location check (strictly 3 preview regions)
case "${SKILL_REG_LOC}" in
  us-central1|europe-west4|us-east5)
    pass "SKILL_REGISTRY_LOCATION=${SKILL_REG_LOC} (valid Vertex AI Skill Registry region)"
    ;;
  *)
    fail "SKILL_REGISTRY_LOCATION=${SKILL_REG_LOC} is unsupported. Vertex AI Skill Registry (v1beta1) ONLY supports: us-central1, europe-west4, or us-east5."
    ;;
esac

# Evaluation location check (global or 14 supported US/EU regions)
case "${EVAL_LOC}" in
  global)
    pass "EVAL_LOCATION=global (APAC-ready and supports generate_loss_clusters in the same client)"
    ;;
  us-central1|us-east1|us-east4|us-east5|us-south1|us-west1|us-west4|\
  europe-central2|europe-north1|europe-southwest1|europe-west1|europe-west4|europe-west8|europe-west9)
    pass "EVAL_LOCATION=${EVAL_LOC} (supported Gen AI Evaluation Service region; note generate_loss_clusters uses global)"
    ;;
  *)
    fail "EVAL_LOCATION=${EVAL_LOC} is unsupported. Gen AI Evaluation Service ONLY supports 'global' or the 14 US/EU regions (us-central1, us-east1, us-east4, us-east5, us-south1, us-west1, us-west4, europe-central2, europe-north1, europe-southwest1, europe-west1, europe-west4, europe-west8, europe-west9)."
    ;;
esac

# Guard against ADK Python OTel capture boolean trap & Express Mode keys
CAPTURE_MODE="${OTEL_INSTRUMENTATION_GENAI_CAPTURE_MESSAGE_CONTENT:-}"
if [[ -n "${CAPTURE_MODE}" ]]; then
  case "${CAPTURE_MODE}" in
    NO_CONTENT|EVENT_ONLY|SPAN_ONLY|SPAN_AND_EVENT)
      pass "OTEL_INSTRUMENTATION_GENAI_CAPTURE_MESSAGE_CONTENT=${CAPTURE_MODE} (valid ADK Python enum)"
      ;;
    *)
      fail "OTEL_INSTRUMENTATION_GENAI_CAPTURE_MESSAGE_CONTENT=${CAPTURE_MODE} is invalid in ADK Python (must be NO_CONTENT, EVENT_ONLY, SPAN_ONLY, or SPAN_AND_EVENT — never true/false)."
      ;;
  esac
fi

if [[ -n "${GOOGLE_GENAI_API_KEY:-}" || -n "${GEMINI_API_KEY:-}" ]]; then
  warn "GOOGLE_GENAI_API_KEY or GEMINI_API_KEY is set. Unset Express Mode / AI Studio keys before Labs 2-8 so standard GCP billing + IAM are used."
fi

# Loud warning if project name looks like production (checked in both offline & online modes)
check_prod_project_warning() {
  local proj="$1"
  if [[ -z "${proj}" ]]; then
    return 0
  fi
  local lower_proj
  lower_proj="$(printf '%s' "${proj}" | tr '[:upper:]' '[:lower:]')"
  if [[ "${lower_proj}" == *prod* ]]; then
    printf "\n${C_BOLD}${C_RED}!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!${C_RESET}\n"
    warn "DANGER: Target project '${proj}' appears to be a PRODUCTION project (contains 'prod')!"
    warn "Do NOT run workshop labs or teardown scripts against a production GCP project."
    warn "Switch GOOGLE_CLOUD_PROJECT to a dedicated sandbox/dev project immediately."
    printf "${C_BOLD}${C_RED}!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!${C_RESET}\n\n"
  fi
}

if [[ -f "${ENV_FILE}" && "${PROJECT_ID}" == "your-gcp-project-id" ]]; then
  warn "GOOGLE_CLOUD_PROJECT in ${ENV_FILE} is still the template placeholder 'your-gcp-project-id'. Replace it with your sandbox GCP project ID before running Labs 2-8."
fi

check_prod_project_warning "${PROJECT_ID}"

# -----------------------------------------------------------------------------
# 3. Live Google Cloud Checks (Skipped when --offline)
# -----------------------------------------------------------------------------
section "3. Google Cloud Authentication, ADC & Required APIs"

if [[ "${OFFLINE}" -eq 1 ]]; then
  info "--offline specified: skipping live gcloud auth, ADC, and enabled API network checks."
else
  if ! command -v gcloud >/dev/null 2>&1; then
    fail "gcloud CLI not found on PATH. Install Google Cloud CLI before running live GCP labs."
  else
    GCLOUD_VER="$(gcloud version 2>/dev/null | head -n 1 || echo "gcloud")"
    pass "gcloud CLI detected (${GCLOUD_VER})"

    if CLOUDSDK_CORE_DISABLE_PROMPTS=1 gcloud alpha agent-registry skills --help </dev/null >/dev/null 2>&1; then
      pass "gcloud alpha component available (supports 'gcloud alpha agent-registry skills' for Lab 4/6/7)"
    else
      warn "gcloud alpha component (or 'gcloud alpha agent-registry skills') is unavailable — needed for Lab 4/6/7 standalone Agent Registry skills."
      info "Install or update with: gcloud components install alpha && gcloud components update"
    fi

    ACTIVE_ACCT="$(gcloud auth list --filter='status:ACTIVE' --format='value(account)' 2>/dev/null | head -n 1 || true)"
    if [[ -n "${ACTIVE_ACCT}" ]]; then
      pass "gcloud active account: ${ACTIVE_ACCT}"
    else
      fail "No active gcloud account found. Run: gcloud auth login"
    fi

    if gcloud auth application-default print-access-token >/dev/null 2>&1; then
      pass "Application Default Credentials (ADC) are valid"
    else
      fail "Application Default Credentials (ADC) missing or expired. Run: gcloud auth application-default login"
    fi

    if [[ -z "${PROJECT_ID}" || "${PROJECT_ID}" == "your-gcp-project-id" ]]; then
      if [[ "${PROJECT_ID}" == "your-gcp-project-id" && ! -f "${ENV_FILE}" ]]; then
        warn "GOOGLE_CLOUD_PROJECT is still template placeholder 'your-gcp-project-id'; falling back to 'gcloud config get-value project'."
      elif [[ "${PROJECT_ID}" == "your-gcp-project-id" ]]; then
        info "Falling back to 'gcloud config get-value project' while GOOGLE_CLOUD_PROJECT is placeholder 'your-gcp-project-id'."
      fi
      PROJECT_ID="$(gcloud config get-value project 2>/dev/null | tr -d '[:space:]' || true)"
    fi

    if [[ -z "${PROJECT_ID}" || "${PROJECT_ID}" == "(unset)" || "${PROJECT_ID}" == "your-gcp-project-id" ]]; then
      fail "No valid GCP project configured. Set GOOGLE_CLOUD_PROJECT in .env or run: gcloud config set project <SANDBOX_PROJECT_ID>"
    else
      pass "Active target GCP project: ${PROJECT_ID}"
      if [[ "${PROJECT_ID}" != "${GOOGLE_CLOUD_PROJECT:-}" ]]; then
        check_prod_project_warning "${PROJECT_ID}"
      fi

      REQUIRED_APIS=(
        "aiplatform.googleapis.com"
        "artifactregistry.googleapis.com"
        "cloudbuild.googleapis.com"
        "secretmanager.googleapis.com"
        "logging.googleapis.com"
        "monitoring.googleapis.com"
        "telemetry.googleapis.com"
        "cloudtrace.googleapis.com"
        "agentregistry.googleapis.com"
        "storage-component.googleapis.com"
        "pubsub.googleapis.com"
      )

      ENABLED_APIS="$(gcloud services list --enabled --project="${PROJECT_ID}" --format='value(config.name)' 2>/dev/null || true)"
      if [[ -z "${ENABLED_APIS}" ]]; then
        fail "Unable to list enabled APIs for project '${PROJECT_ID}' (verify permissions or project ID)."
      else
        MISSING_APIS=()
        for api in "${REQUIRED_APIS[@]}"; do
          if grep -qx "${api}" <<< "${ENABLED_APIS}"; then
            pass "API enabled: ${api}"
          else
            fail "API NOT enabled: ${api}"
            MISSING_APIS+=("${api}")
          fi
        done

        if [[ "${#MISSING_APIS[@]}" -gt 0 ]]; then
          info "Enable all missing APIs in one command:"
          info "  gcloud services enable ${MISSING_APIS[*]} --project=${PROJECT_ID}"
        fi
      fi
    fi
  fi
fi

# -----------------------------------------------------------------------------
# Summary
# -----------------------------------------------------------------------------
printf "\n=============================================================================\n"
printf "Pre-Flight Summary (mode=%s, env=%s): PASS=%d | FAIL=%d | WARN=%d | INFO=%d\n" \
  "$([[ "${OFFLINE}" -eq 1 ]] && echo "offline" || echo "online")" \
  "${ENV_LOADED_FROM:-none}" \
  "${PASS_COUNT}" "${FAIL_COUNT}" "${WARN_COUNT}" "${INFO_COUNT}"
printf "=============================================================================\n"

if [[ "${FAIL_COUNT}" -gt 0 ]]; then
  exit 1
fi
exit 0
