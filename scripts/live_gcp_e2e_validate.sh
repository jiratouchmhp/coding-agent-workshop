#!/usr/bin/env bash
# =============================================================================
# Enterprise Coding Agent Workshop — Live GCP End-to-End Validation Harness
# =============================================================================
# Usage:
#   ./scripts/live_gcp_e2e_validate.sh --project <SANDBOX_PROJECT_ID> [OPTIONS]
#
# Executes a full, real Google Cloud smoke validation following the workshop's
# Bangkok-first fallback strategy (asia-southeast3 first; falling back to
# asia-southeast1 / global / us-central1 only where GCP requires it) with
# guaranteed cleanup on EXIT (even on mid-run failure):
#   0. Frontier Gemini 4 config (`gemini-4-hydrogen` / `gemini-4-neon` on `global`,
#      `THINKING_LEVEL=MEDIUM`) + `make test-agy-harness` (`--dry-run` NDJSON & exit codes)
#   1. Cloud Build remote builds + Artifact Registry (Bangkok asia-southeast3 — ZERO local Docker)
#   2. BYOC Sandbox `GET /health` (local + live BYOC from Bangkok AR) + Shell Sandbox lifecycle (Singapore asia-southeast1 fallback)
#   3. Managed Sessions + Memory Bank + Feedback Service (Singapore asia-southeast1 fallback)
#   4. Disposable Vertex AI Skill Registry create+update (us-central1) +
#      Agent Registry standalone skill create + rev-1 + default-revision promote/activate via `gcloud alpha` (global fallback)
#   5. Isolated Terraform apply (Singapore asia-southeast1 fallback, Bangkok AR image, Gemini 4 + BYOC + Memory Bank + Skill Registry) + live :query & :streamQuery?alt=sse (Gemini 4 Hydrogen + BYOC `agy` check)
#   6. Offline Evaluation (global) + Cloud Monitoring Quality Alert Policy
#   7. Full Teardown + Verification that 0 dry-run resources remain (including SA & Secret)
#
# Safety Guardrails:
#   - --project is REQUIRED.
#   - Aborts if project ID contains "prod" unless --allow-non-sandbox is passed.
#   - Uses a unique timestamped suffix `dryrun-YYYYMMDD-HHMMSS` for images,
#     Terraform display name, alert policy, and Skill Registry SKILL_ID
#     (`secure-code-review-dryrun-...`) so permanent `secure-code-review` is
#     NEVER locked or modified.
# =============================================================================

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
cd "${REPO_ROOT}"

PROJECT_ID=""
ALLOW_NON_SANDBOX=0
PRIMARY_REG="asia-southeast3"
BUILD_LOC=""
AR_LOC=""
AGENT_REG_LOC=""
AGENT_REG_SKILLS_LOC="${AGENT_REGISTRY_SKILLS_LOCATION:-global}"
AGENT_PLATFORM_LOC="asia-southeast1"
SKILL_REG_LOC="us-central1"
EVAL_LOC="global"
AR_REPO="coding-agent-repo"
TRACK="solution"

usage() {
  cat <<'EOF'
Usage: ./scripts/live_gcp_e2e_validate.sh --project <SANDBOX_PROJECT_ID> [OPTIONS]

Run a full live GCP end-to-end smoke validation with guaranteed teardown on EXIT.

Required:
  --project <PROJECT_ID>                 Target sandbox GCP project ID (aborts if name contains 'prod')

Options:
  --allow-non-sandbox                    Override safety abort when project ID contains 'prod' (USE WITH EXTREME CAUTION)
  --primary-region <REGION>              Bangkok-first region for Cloud Build, AR, Agent Registry A2A/MCP (default: asia-southeast3)
  --agent-location <REGION>              Agent Platform fallback region (default: asia-southeast1)
  --agent-registry-skills-location <REG> Agent Registry standalone skills location (default: global)
  --skill-registry-location <REG>        Vertex AI Skill Registry region (default: us-central1)
  --eval-location <REGION>               Gen AI Evaluation Service location (default: global)
  --ar-repo <REPO_NAME>                  Artifact Registry Docker repository (default: coding-agent-repo)
  --track <solution|starter>             Workshop track to validate (default: solution)
  -h, --help                             Show this help message
EOF
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --project)
      if [[ $# -lt 2 ]]; then
        echo "ERROR: --project requires a GCP project ID." >&2
        exit 2
      fi
      PROJECT_ID="$2"
      shift 2
      ;;
    --allow-non-sandbox)
      ALLOW_NON_SANDBOX=1
      shift
      ;;
    --primary-region)
      if [[ $# -lt 2 ]]; then
        echo "ERROR: $1 requires a value." >&2
        exit 2
      fi
      PRIMARY_REG="$2"
      shift 2
      ;;
    --agent-location)
      if [[ $# -lt 2 ]]; then
        echo "ERROR: $1 requires a value." >&2
        exit 2
      fi
      AGENT_PLATFORM_LOC="$2"
      shift 2
      ;;
    --agent-registry-skills-location)
      if [[ $# -lt 2 ]]; then
        echo "ERROR: $1 requires a value." >&2
        exit 2
      fi
      AGENT_REG_SKILLS_LOC="$2"
      shift 2
      ;;
    --skill-registry-location)
      if [[ $# -lt 2 ]]; then
        echo "ERROR: $1 requires a value." >&2
        exit 2
      fi
      SKILL_REG_LOC="$2"
      shift 2
      ;;
    --eval-location)
      if [[ $# -lt 2 ]]; then
        echo "ERROR: $1 requires a value." >&2
        exit 2
      fi
      EVAL_LOC="$2"
      shift 2
      ;;
    --ar-repo)
      if [[ $# -lt 2 ]]; then
        echo "ERROR: $1 requires a value." >&2
        exit 2
      fi
      AR_REPO="$2"
      shift 2
      ;;
    --track)
      if [[ $# -lt 2 ]]; then
        echo "ERROR: $1 requires a value." >&2
        exit 2
      fi
      TRACK="$2"
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

if [[ -z "${PROJECT_ID}" ]]; then
  echo "ERROR: --project <SANDBOX_PROJECT_ID> is required." >&2
  usage >&2
  exit 2
fi

if [[ "${TRACK}" != "solution" && "${TRACK}" != "starter" ]]; then
  echo "ERROR: --track must be 'solution' or 'starter' (got '${TRACK}')." >&2
  exit 2
fi

# Safety Gate: Explicitly abort if project ID contains 'prod' unless overridden
LOWER_PROJECT="$(printf '%s' "${PROJECT_ID}" | tr '[:upper:]' '[:lower:]')"
if [[ "${LOWER_PROJECT}" == *prod* && "${ALLOW_NON_SANDBOX}" -ne 1 ]]; then
  echo "ERROR: Refusing to run live E2E validation against project '${PROJECT_ID}' (contains 'prod')." >&2
  echo "Use a dedicated sandbox project, or pass --allow-non-sandbox if you explicitly accept the risk." >&2
  exit 1
fi

BUILD_LOC="${BUILD_LOC:-${PRIMARY_REG}}"
AR_LOC="${AR_LOC:-${PRIMARY_REG}}"
# Bangkok-first for Agent Registry A2A/MCP discovery; standalone skills require `global` fallback.
AGENT_REG_LOC="${AGENT_REG_LOC:-${PRIMARY_REG}}"
AGENT_REG_SKILLS_LOC="${AGENT_REG_SKILLS_LOC:-${AGENT_REGISTRY_SKILLS_LOCATION:-global}}"

# Unique timestamped suffix so every live resource is isolated and disposable
RUN_TIMESTAMP="$(date +%Y%m%d-%H%M%S)"
RUN_SUFFIX="dryrun-${RUN_TIMESTAMP}"
SHORT_TS="$(date +%m%d%H%M%S)"
SKILL_ID="secure-code-review-${RUN_SUFFIX}"
AGENT_REG_SKILL_NAME="private-${SKILL_ID}"
TF_DISPLAY_NAME="coding-agent-${RUN_SUFFIX}"
TF_SA_ID="ca-dr-${SHORT_TS}"
TF_SA_EMAIL="${TF_SA_ID}@${PROJECT_ID}.iam.gserviceaccount.com"
TF_SECRET_ID="coding-agent-key-${RUN_SUFFIX}"
ALERT_DISPLAY_NAME="Coding Agent Quality Drift (${RUN_SUFFIX})"

SANDBOX_IMG_URI="${AR_LOC}-docker.pkg.dev/${PROJECT_ID}/${AR_REPO}/coding-sandbox:${RUN_SUFFIX}"
AGENT_IMG_URI="${AR_LOC}-docker.pkg.dev/${PROJECT_ID}/${AR_REPO}/coding-agent:${RUN_SUFFIX}"

TMP_WORK_DIR="$(mktemp -d -t coding-agent-e2e-XXXXXX)"
TF_WORK_DIR="${TMP_WORK_DIR}/terraform"

# Track live resources created for guaranteed teardown
TF_APPLIED=0
TF_DESTROY_FAILED=0
STANDALONE_ENGINE_NAME=""
BYOC_TEMPLATE_NAME=""
TF_ENGINE_NAME=""
ALERT_POLICY_NAME=""
SKILL_REG_CREATED=0
AGENT_REG_CREATED=0
AR_REPO_CREATED=0
SANDBOX_IMG_PUSHED=0
AGENT_IMG_PUSHED=0
CLEANUP_RAN=0
PROJECT_NUMBER=""

log()  { printf "\n[E2E %s] %s\n" "$(date +%H:%M:%S)" "$1"; }
pass() { printf "[PASS] %s\n" "$1"; }
warn() { printf "[WARN] %s\n" "$1" >&2; }

# Pick Python runtime inside the target track
run_track_python() {
  local track_dir="${REPO_ROOT}/${TRACK}"
  if [[ -x "${track_dir}/.venv/bin/python" ]]; then
    (cd "${track_dir}" && env PYTHONDONTWRITEBYTECODE=1 "${track_dir}/.venv/bin/python" "$@")
  elif command -v uv >/dev/null 2>&1; then
    (cd "${track_dir}" && env PYTHONDONTWRITEBYTECODE=1 uv run python "$@")
  else
    (cd "${track_dir}" && env PYTHONDONTWRITEBYTECODE=1 python3 "$@")
  fi
}

# -----------------------------------------------------------------------------
# Guaranteed Teardown Handler (registered via trap cleanup EXIT)
# -----------------------------------------------------------------------------
run_teardown() {
  if [[ "${CLEANUP_RAN}" -eq 1 ]]; then
    return 0
  fi
  CLEANUP_RAN=1
  set +e

  log "Running guaranteed teardown for ${RUN_SUFFIX}..."

  # 1. Destroy Terraform-managed Agent Runtime, SA, Secret, and IAM bindings
  if [[ "${TF_APPLIED}" -eq 1 && -d "${TF_WORK_DIR}" ]]; then
    log "Teardown [1/6]: terraform destroy in ${TF_WORK_DIR}"
    if ! terraform -chdir="${TF_WORK_DIR}" destroy -auto-approve \
      -var-file="${TF_WORK_DIR}/e2e.tfvars"; then
      TF_DESTROY_FAILED=1
      warn "terraform destroy reported errors (will be surfaced in Stage 7 leak verification)"
    fi
  fi

  # 2. Delete standalone Agent Platform instance (sandboxes -> snapshots -> templates + engine)
  if [[ -n "${STANDALONE_ENGINE_NAME}" ]]; then
    log "Teardown [2/6]: Draining sandboxes/snapshots/templates & deleting ${STANDALONE_ENGINE_NAME}"
    for _ in $(seq 1 3); do
      local clean_out
      clean_out="$(run_track_python -m coding_agent.tools.sandbox_lifecycle \
        --project "${PROJECT_ID}" \
        --location "${AGENT_PLATFORM_LOC}" \
        --instance "${STANDALONE_ENGINE_NAME}" \
        cleanup-all --include-templates 2>/dev/null || true)"
      if python3 - "${clean_out}" <<'PYEOF'
import json, sys
try:
    d = json.loads(sys.argv[1])
    sys.exit(0 if sum(int(v) for v in d.values()) == 0 else 1)
except Exception:
    sys.exit(1)
PYEOF
      then
        break
      fi
      sleep 5
    done

    local token del_code check_code del_resp
    token="$(gcloud auth print-access-token 2>/dev/null || true)"
    if [[ -n "${token}" ]]; then
      del_resp="${TMP_WORK_DIR}/delete_standalone_engine.json"
      del_code="$(curl -sS -o "${del_resp}" -w "%{http_code}" -X DELETE \
        -H "Authorization: Bearer ${token}" \
        "https://${AGENT_PLATFORM_LOC}-aiplatform.googleapis.com/v1beta1/${STANDALONE_ENGINE_NAME}?force=true" || echo "000")"
      if [[ "${del_code}" == "200" || "${del_code}" == "202" || "${del_code}" == "204" ]]; then
        for _ in $(seq 1 12); do
          check_code="$(curl -sS -o /dev/null -w "%{http_code}" \
            -H "Authorization: Bearer ${token}" \
            "https://${AGENT_PLATFORM_LOC}-aiplatform.googleapis.com/v1beta1/${STANDALONE_ENGINE_NAME}" || echo "000")"
          if [[ "${check_code}" == "404" ]]; then
            break
          fi
          sleep 5
        done
      elif [[ "${del_code}" != "404" ]]; then
        warn "Unexpected HTTP ${del_code} deleting ${STANDALONE_ENGINE_NAME}: $(cat "${del_resp}" 2>/dev/null || true)"
      fi
    fi
  fi

  # 3. Delete Cloud Monitoring Quality Alert Policy
  if [[ -n "${ALERT_POLICY_NAME}" ]]; then
    log "Teardown [3/6]: Deleting Cloud Monitoring alert policy ${ALERT_POLICY_NAME}"
    gcloud monitoring policies delete "${ALERT_POLICY_NAME}" \
      --project="${PROJECT_ID}" --quiet >/dev/null 2>&1 || true
  fi

  # 4. Clear default revision, delete Agent Registry standalone skill revisions, then delete skill
  if [[ "${AGENT_REG_CREATED}" -eq 1 ]]; then
    log "Teardown [4/6]: Clearing default revision & deleting Agent Registry skill ${AGENT_REG_SKILL_NAME} (${AGENT_REG_SKILLS_LOC})"
    local clear_out rev_list rev_full rev_short rev_del_out skill_del_out
    if ! clear_out="$(CLOUDSDK_CORE_DISABLE_PROMPTS=1 gcloud alpha agent-registry skills update "${AGENT_REG_SKILL_NAME}" \
      --clear-default-revision \
      --target-state=disabled \
      --project="${PROJECT_ID}" \
      --location="${AGENT_REG_SKILLS_LOC}" </dev/null 2>&1)"; then
      warn "Could not clear default revision for ${AGENT_REG_SKILL_NAME} (continuing): ${clear_out}"
    fi
    rev_list="$(CLOUDSDK_CORE_DISABLE_PROMPTS=1 gcloud alpha agent-registry skills revisions list \
      --skill="${AGENT_REG_SKILL_NAME}" \
      --project="${PROJECT_ID}" \
      --location="${AGENT_REG_SKILLS_LOC}" \
      --format="value(name)" </dev/null 2>/dev/null || true)"
    if [[ -n "${rev_list}" ]]; then
      while IFS= read -r rev_full; do
        [[ -z "${rev_full}" ]] && continue
        rev_short="${rev_full##*/}"
        if ! rev_del_out="$(CLOUDSDK_CORE_DISABLE_PROMPTS=1 gcloud alpha agent-registry skills revisions delete "${rev_short}" \
          --skill="${AGENT_REG_SKILL_NAME}" \
          --project="${PROJECT_ID}" \
          --location="${AGENT_REG_SKILLS_LOC}" \
          --quiet </dev/null 2>&1)"; then
          warn "Failed to delete Agent Registry revision ${rev_short} for ${AGENT_REG_SKILL_NAME}: ${rev_del_out}"
        fi
      done <<< "${rev_list}"
    fi
    if ! skill_del_out="$(CLOUDSDK_CORE_DISABLE_PROMPTS=1 gcloud alpha agent-registry skills delete "${AGENT_REG_SKILL_NAME}" \
      --project="${PROJECT_ID}" \
      --location="${AGENT_REG_SKILLS_LOC}" \
      --quiet </dev/null 2>&1)"; then
      warn "Failed to delete Agent Registry skill ${AGENT_REG_SKILL_NAME}: ${skill_del_out}"
    fi
  fi

  # 5. Delete disposable Vertex AI Skill Registry skill in SKILL_REG_LOC
  #    (Uses timestamped dryrun ID so permanent 'secure-code-review' is NEVER touched!)
  if [[ "${SKILL_REG_CREATED}" -eq 1 ]]; then
    log "Teardown [5/6]: Deleting disposable Skill Registry skill ${SKILL_ID} (${SKILL_REG_LOC})"
    local token
    token="$(gcloud auth print-access-token 2>/dev/null || true)"
    if [[ -n "${token}" ]]; then
      curl -sS -o /dev/null -X DELETE \
        -H "Authorization: Bearer ${token}" \
        "https://${SKILL_REG_LOC}-aiplatform.googleapis.com/v1beta1/projects/${PROJECT_ID}/locations/${SKILL_REG_LOC}/skills/${SKILL_ID}" || true
    fi
  fi

  # 6. Delete dry-run Artifact Registry images (and disposable repo if created in Stage 0)
  if [[ "${SANDBOX_IMG_PUSHED}" -eq 1 ]]; then
    log "Teardown [6a/6]: Deleting Artifact Registry image ${SANDBOX_IMG_URI}"
    gcloud artifacts docker images delete "${SANDBOX_IMG_URI}" \
      --delete-tags --quiet --project="${PROJECT_ID}" >/dev/null 2>&1 || true
  fi
  if [[ "${AGENT_IMG_PUSHED}" -eq 1 ]]; then
    log "Teardown [6b/6]: Deleting Artifact Registry image ${AGENT_IMG_URI}"
    gcloud artifacts docker images delete "${AGENT_IMG_URI}" \
      --delete-tags --quiet --project="${PROJECT_ID}" >/dev/null 2>&1 || true
  fi
  if [[ "${AR_REPO_CREATED}" -eq 1 ]]; then
    log "Teardown [6c/6]: Deleting newly created disposable Artifact Registry repository ${AR_REPO} (${AR_LOC})"
    gcloud artifacts repositories delete "${AR_REPO}" \
      --location="${AR_LOC}" \
      --project="${PROJECT_ID}" \
      --quiet </dev/null >/dev/null 2>&1 || true
  fi

  # Remove ephemeral workspace
  rm -rf "${TMP_WORK_DIR}" 2>/dev/null || true
}

cleanup() {
  local exit_code=$?
  run_teardown
  if [[ "${exit_code}" -ne 0 ]]; then
    warn "Live E2E validation exited with status ${exit_code} (teardown completed)."
  fi
  exit "${exit_code}"
}

trap cleanup EXIT

# -----------------------------------------------------------------------------
# Stage 0: Preflight & Project Metadata
# -----------------------------------------------------------------------------
log "Stage 0: Validating prerequisites for project=${PROJECT_ID} (suffix=${RUN_SUFFIX})"
for bin in gcloud terraform curl python3; do
  if ! command -v "${bin}" >/dev/null 2>&1; then
    echo "ERROR: Required CLI '${bin}' not found on PATH." >&2
    exit 1
  fi
done

PROJECT_NUMBER="$(gcloud projects describe "${PROJECT_ID}" --format='value(projectNumber)')"
if [[ -z "${PROJECT_NUMBER}" ]]; then
  echo "ERROR: Unable to resolve projectNumber for project '${PROJECT_ID}'." >&2
  exit 1
fi

export GOOGLE_GENAI_USE_ENTERPRISE=TRUE
export GOOGLE_CLOUD_PROJECT="${PROJECT_ID}"
export GOOGLE_CLOUD_PROJECT_NUMBER="${PROJECT_NUMBER}"
export PRIMARY_REGION="${PRIMARY_REG}"
export BUILD_LOCATION="${BUILD_LOC}"
export AR_LOCATION="${AR_LOC}"
export AGENT_REGISTRY_LOCATION="${AGENT_REG_LOC}"
export AGENT_REGISTRY_SKILLS_LOCATION="${AGENT_REG_SKILLS_LOC}"
export GOOGLE_CLOUD_LOCATION="${AGENT_PLATFORM_LOC}"
export SKILL_REGISTRY_LOCATION="${SKILL_REG_LOC}"
export EVAL_LOCATION="${EVAL_LOC}"
export MODEL_NAME="gemini-4-hydrogen"
export REASONING_MODEL_NAME="gemini-4-neon"
export MODEL_LOCATION="global"
export THINKING_LEVEL="MEDIUM"
export AGY_EXECUTION_MODE="auto"
export AGY_ADC_AUTH="true"
export AGY_CLI_DISABLE_AUTO_UPDATE="true"
export GOOGLE_CLOUD_AGENT_ENGINE_ENABLE_TELEMETRY=true
export OTEL_SEMCONV_STABILITY_OPT_IN=gen_ai_latest_experimental
export OTEL_INSTRUMENTATION_GENAI_CAPTURE_MESSAGE_CONTENT=EVENT_ONLY

# Validate Antigravity (agy) headless CLI harness locally before provisioning cloud resources
make -C "${REPO_ROOT}" TRACK="${TRACK}" test-agy-harness
pass "Verified Antigravity (agy) headless CLI harness (--dry-run NDJSON + 4-tier exit codes)"

# Ensure Artifact Registry repository exists in AR_LOC (asia-southeast3)
if ! gcloud artifacts repositories describe "${AR_REPO}" \
  --location="${AR_LOC}" --project="${PROJECT_ID}" >/dev/null 2>&1; then
  log "Creating Artifact Registry repository '${AR_REPO}' in ${AR_LOC}..."
  gcloud artifacts repositories create "${AR_REPO}" \
    --repository-format=docker \
    --location="${AR_LOC}" \
    --project="${PROJECT_ID}" \
    --description="Enterprise Coding Agent Workshop BYOC images"
  AR_REPO_CREATED=1
fi

# Ensure Vertex AI / Reasoning Engine service identities exist
CLOUDSDK_CORE_DISABLE_PROMPTS=1 gcloud alpha services identity create \
  --service=aiplatform.googleapis.com \
  --project="${PROJECT_ID}" </dev/null >/dev/null 2>&1 || true

pass "Stage 0 ready (project=${PROJECT_ID} #${PROJECT_NUMBER}, model=${MODEL_NAME}/${REASONING_MODEL_NAME}@${MODEL_LOCATION}, thinking=${THINKING_LEVEL}, bangkok-first=${PRIMARY_REG}, agent-fallback=${AGENT_PLATFORM_LOC}, agent-reg-skills=${AGENT_REG_SKILLS_LOC}, skill=${SKILL_REG_LOC}, eval=${EVAL_LOC})"

# -----------------------------------------------------------------------------
# Stage 1: Cloud Build Remote Image Builds (asia-southeast3 — ZERO Docker)
# -----------------------------------------------------------------------------
log "Stage 1: Cloud Build (${BUILD_LOC}) -> BYOC Sandbox + Agent Runtime images in ${AR_LOC}"

gcloud builds submit "${REPO_ROOT}/${TRACK}/sandbox_image" \
  --region="${BUILD_LOC}" \
  --tag="${SANDBOX_IMG_URI}" \
  --project="${PROJECT_ID}"
SANDBOX_IMG_PUSHED=1
pass "Pushed BYOC sandbox image: ${SANDBOX_IMG_URI}"

gcloud builds submit "${REPO_ROOT}/${TRACK}" \
  --region="${BUILD_LOC}" \
  --tag="${AGENT_IMG_URI}" \
  --project="${PROJECT_ID}"
AGENT_IMG_PUSHED=1
pass "Pushed Agent Runtime image: ${AGENT_IMG_URI}"

# -----------------------------------------------------------------------------
# Stage 2: Managed Sandboxes — Shell Sandbox + BYOC Sandbox (asia-southeast1)
# -----------------------------------------------------------------------------
log "Stage 2: Provisioning standalone parent instance + Shell & BYOC Sandboxes (${AGENT_PLATFORM_LOC})"

# Verify BYOC runner HTTP contract locally (GET /health + agy_cli_available, /exec allowlisted/disallowed env, cwd escape)
make -C "${REPO_ROOT}" TRACK="${TRACK}" test-sandbox-local
pass "Verified BYOC sandbox runner GET /health (agy_cli_available) and /exec security boundaries locally"

INST_JSON="$(run_track_python -m coding_agent.tools.sandbox_lifecycle \
  --project "${PROJECT_ID}" \
  --location "${AGENT_PLATFORM_LOC}" \
  create-instance \
  --display-name "workshop-e2e-parent-${RUN_SUFFIX}")"
STANDALONE_ENGINE_NAME="$(python3 -c 'import json,sys; print(json.load(sys.stdin)["instance_name"])' <<< "${INST_JSON}")"
export REASONING_ENGINE_NAME="${STANDALONE_ENGINE_NAME}"
pass "Created standalone Agent Platform instance: ${STANDALONE_ENGINE_NAME}"

# Ensure Agent Sandbox service agent can pull BYOC image from Artifact Registry
gcloud artifacts repositories add-iam-policy-binding "${AR_REPO}" \
  --location="${AR_LOC}" \
  --project="${PROJECT_ID}" \
  --member="serviceAccount:service-${PROJECT_NUMBER}@gcp-sa-vertex-sandbox.iam.gserviceaccount.com" \
  --role="roles/artifactregistry.reader" \
  --quiet >/dev/null 2>&1 || true

# Shell Sandbox lifecycle validation
run_track_python -m coding_agent.tools.sandbox_lifecycle \
  --project "${PROJECT_ID}" \
  --location "${AGENT_PLATFORM_LOC}" \
  --instance "${STANDALONE_ENGINE_NAME}" \
  demo --mode shell --ttl 900s >/dev/null
pass "Shell Sandbox full lifecycle demo succeeded in ${AGENT_PLATFORM_LOC}"

# BYOC Sandbox template + live GET /health probe + lifecycle validation
TPL_JSON="$(run_track_python -m coding_agent.tools.sandbox_lifecycle \
  --project "${PROJECT_ID}" \
  --location "${AGENT_PLATFORM_LOC}" \
  --instance "${STANDALONE_ENGINE_NAME}" \
  create-template \
  --kind byoc \
  --display-name "byoc-tpl-${RUN_SUFFIX}" \
  --image-uri "${SANDBOX_IMG_URI}")"
BYOC_TEMPLATE_NAME="$(python3 -c 'import json,sys; print(json.load(sys.stdin)["name"])' <<< "${TPL_JSON}")"
export SANDBOX_TEMPLATE_NAME="${BYOC_TEMPLATE_NAME}"
pass "Created BYOC SandboxEnvironmentTemplate: ${BYOC_TEMPLATE_NAME}"

# Probe GET /health on a disposable live BYOC sandbox (with guaranteed finally delete)
BYOC_HEALTH_OUT="$(run_track_python - "${PROJECT_ID}" "${AGENT_PLATFORM_LOC}" "${STANDALONE_ENGINE_NAME}" "${BYOC_TEMPLATE_NAME}" "${RUN_SUFFIX}" <<'PYEOF'
import json
import os
import sys

from coding_agent.tools.sandbox_execution import (
    fetch_iam_bearer_token,
    generate_sandbox_access_token,
)
from coding_agent.tools.sandbox_lifecycle import (
    SandboxLifecycleManager,
    get_sandboxes_namespace,
)

project_id, location, instance_name, template_name, suffix = sys.argv[1:6]
mgr = SandboxLifecycleManager(
    project_id=project_id,
    location=location,
    instance_name=instance_name,
)
sb = mgr.create_sandbox(
    display_name=f"byoc-health-{suffix}",
    template_name=template_name,
    ttl="900s",
    wait_for_completion=True,
)
try:
    sandboxes_ns = get_sandboxes_namespace(mgr.client)
    sandbox_env = sandboxes_ns.get(name=sb.name)
    sa_email = os.environ.get("SANDBOX_SERVICE_ACCOUNT_EMAIL", "").strip()
    token = (
        generate_sandbox_access_token(mgr.client, sa_email)
        if sa_email
        else fetch_iam_bearer_token()
    )
    try:
        resp = sandboxes_ns.send_command(
            http_method="GET",
            path="health",
            access_token=token,
            request_dict=None,
            sandbox_environment=sandbox_env,
        )
    except Exception as exc:
        msg = str(exc).upper()
        if not sa_email and any(tok in msg for tok in ("401", "403", "UNAUTHENTICATED", "PERMISSION_DENIED")):
            print(json.dumps({"skipped_reason": str(exc)}))
            sys.exit(0)
        raise

    # agentplatform's Sandboxes.send_command() returns HttpResponse(body=..., headers=...)
    # without calling raise_for_status(), so HTTP 401/403 without a signed SA token
    # often yields an empty or non-JSON body instead of raising an exception.
    status_code = getattr(resp, "status_code", None)
    raw_headers = getattr(resp, "headers", None) or {}
    headers_lower = (
        {str(k).lower(): str(v) for k, v in raw_headers.items()}
        if isinstance(raw_headers, dict)
        else {}
    )
    raw_body = getattr(resp, "body", resp)
    if isinstance(raw_body, bytes):
        raw_body = raw_body.decode("utf-8", errors="replace")

    if isinstance(raw_body, str):
        stripped = raw_body.strip()
        if not stripped:
            if not sa_email and (
                status_code in (401, 403, None)
                or "www-authenticate" in headers_lower
            ):
                print(
                    json.dumps(
                        {
                            "skipped_reason": (
                                "BYOC data-plane returned empty response body without "
                                f"SANDBOX_SERVICE_ACCOUNT_EMAIL (status_code={status_code!r}, "
                                f"www-authenticate={headers_lower.get('www-authenticate', '')!r}); "
                                "live BYOC data-plane auth is exercised in Stage 5 via the deployed Runtime SA."
                            )
                        }
                    )
                )
                sys.exit(0)
            raise AssertionError(
                f"Live BYOC GET /health returned empty body (status_code={status_code!r}, headers={headers_lower!r})"
            )
        try:
            health = json.loads(stripped)
        except json.JSONDecodeError as exc:
            if not sa_email and (
                status_code in (401, 403, None)
                or "www-authenticate" in headers_lower
                or any(
                    tok in stripped.upper()
                    for tok in ("401", "403", "UNAUTHENTICATED", "UNAUTHORIZED", "PERMISSION_DENIED")
                )
            ):
                print(
                    json.dumps(
                        {
                            "skipped_reason": (
                                "BYOC data-plane returned non-JSON auth response without "
                                f"SANDBOX_SERVICE_ACCOUNT_EMAIL: {stripped[:200]!r}"
                            )
                        }
                    )
                )
                sys.exit(0)
            raise AssertionError(
                f"Live BYOC GET /health returned non-JSON body ({exc}): {stripped[:300]!r}"
            ) from exc
    else:
        health = raw_body

    assert isinstance(health, dict) and health.get("status") == "ok", (
        f"Unexpected live BYOC GET /health payload: {health!r}"
    )
    assert isinstance(health.get("agy_cli_available"), bool), (
        f"Live BYOC GET /health missing boolean 'agy_cli_available': {health!r}"
    )

    # Also probe POST /exec when data-plane authentication succeeded
    exec_resp = sandboxes_ns.send_command(
        http_method="POST",
        path="exec",
        access_token=token,
        request_dict={"command": "echo byoc-exec-ok"},
        sandbox_environment=sandbox_env,
    )
    exec_body = getattr(exec_resp, "body", exec_resp)
    if isinstance(exec_body, bytes):
        exec_body = exec_body.decode("utf-8", errors="replace")
    exec_json = json.loads(exec_body) if isinstance(exec_body, str) and exec_body.strip() else exec_body
    assert isinstance(exec_json, dict) and exec_json.get("returncode") == 0 and "byoc-exec-ok" in str(exec_json.get("stdout", "")), (
        f"Unexpected live BYOC POST /exec payload: {exec_json!r}"
    )
    print(json.dumps({"health": health, "exec_stdout": str(exec_json.get("stdout", "")).strip()}))
finally:
    mgr.delete_sandbox(sb.name, wait_for_completion=True)
PYEOF
)"
if grep -q '"skipped_reason"' <<< "${BYOC_HEALTH_OUT}"; then
  warn "Live BYOC data-plane GET /health skipped without SANDBOX_SERVICE_ACCOUNT_EMAIL (${BYOC_HEALTH_OUT}); local GET /health + agy_cli_available verified, and Stage 5 exercises live BYOC via the deployed Runtime SA."
else
  pass "Live BYOC Sandbox GET /health + POST /exec verified in ${AGENT_PLATFORM_LOC} (${BYOC_HEALTH_OUT})"
fi

run_track_python -m coding_agent.tools.sandbox_lifecycle \
  --project "${PROJECT_ID}" \
  --location "${AGENT_PLATFORM_LOC}" \
  --instance "${STANDALONE_ENGINE_NAME}" \
  demo --mode byoc --image-uri "${SANDBOX_IMG_URI}" --ttl 900s >/dev/null
pass "BYOC Sandbox full lifecycle demo succeeded in ${AGENT_PLATFORM_LOC}"

# -----------------------------------------------------------------------------
# Stage 3: Managed Sessions + Memory Bank + Feedback Service (asia-southeast1)
# -----------------------------------------------------------------------------
log "Stage 3: Validating Managed Sessions, Memory Bank, and Feedback Service (${AGENT_PLATFORM_LOC})"

run_track_python -m coding_agent.memory.session_manager \
  --project "${PROJECT_ID}" \
  --location "${AGENT_PLATFORM_LOC}" \
  --runtime-name "${STANDALONE_ENGINE_NAME}" \
  --user-id "e2e-${RUN_SUFFIX}" \
  --demo >/dev/null
pass "Managed Sessions CRUD + event demo succeeded in ${AGENT_PLATFORM_LOC}"

run_track_python -m coding_agent.memory.memory_bank_manager \
  --project "${PROJECT_ID}" \
  --location "${AGENT_PLATFORM_LOC}" \
  --memory-bank-name "${STANDALONE_ENGINE_NAME}" \
  --user-id "e2e-${RUN_SUFFIX}" \
  --demo >/dev/null
pass "Memory Bank topic config, generation, retrieval, and purge demo succeeded in ${AGENT_PLATFORM_LOC}"

# Feedback Service live roundtrip (create -> list -> delete)
run_track_python - "${PROJECT_ID}" "${AGENT_PLATFORM_LOC}" "${STANDALONE_ENGINE_NAME}" "${RUN_SUFFIX}" <<'PYEOF'
import sys
import uuid
from coding_agent.callbacks.telemetry_and_feedback import FeedbackClient
from coding_agent.memory.session_manager import SessionLifecycleManager

project_id, location, runtime_name, suffix = sys.argv[1:5]
sm = SessionLifecycleManager(project_id=project_id, location=location, runtime_name=runtime_name)
sess_name = sm.create_session(user_id=f"fb-{suffix}", session_id=f"fb-{suffix}"[:60], ttl_days=1)
sess_id = sess_name.rstrip("/").split("/")[-1]
event_uuid = str(uuid.uuid4())
try:
    sm.append_raw_event(
        session_name=sess_name,
        author="coding_agent",
        invocation_id=f"inv-{suffix}",
        raw_payload={"id": event_uuid, "content": "E2E smoke check passed."},
    )
    fb = FeedbackClient(project_id=project_id, location=location, runtime_name=runtime_name)
    entry_name = fb.submit_feedback(
        session_id=sess_id,
        event_id=event_uuid,
        feedback_type="THUMBS_UP",
        feedback_text=f"E2E smoke validation ({suffix})",
        feedback_labels=["accurate", "tool_success"],
        user_id=f"fb-{suffix}",
    )
    listed = fb.list_session_feedback(session_id=sess_id)
    assert listed, "Expected created feedback entry in list_session_feedback()"
    fb.delete_feedback(entry_name)
finally:
    sm.delete_session(sess_name)
PYEOF
pass "Feedback Service live submit -> list -> delete succeeded in ${AGENT_PLATFORM_LOC}"

# -----------------------------------------------------------------------------
# Stage 4: Disposable Skill Registry (us-central1) + Agent Registry Skills (global fallback)
# -----------------------------------------------------------------------------
log "Stage 4: Validating Vertex AI Skill Registry (${SKILL_REG_LOC}) + Agent Registry Standalone Skills (${AGENT_REG_SKILLS_LOC})"

SKILL_DIR="${REPO_ROOT}/${TRACK}/skills_to_register/secure-code-review"
SKILL_ZIP="${TMP_WORK_DIR}/secure-code-review-${RUN_SUFFIX}.zip"
python3 "${REPO_ROOT}/scripts/package_registry_skill.py" \
  "${SKILL_DIR}" \
  --agent-registry \
  --output "${SKILL_ZIP}" >/dev/null
pass "Packaged validated 16-rule Agent Registry + Skill Registry skill ZIP: ${SKILL_ZIP}"

# Vertex AI Skill Registry `local_path` requires a directory (auto-zipped by SDK)
run_track_python -m coding_agent.tools.registry_loader \
  --project "${PROJECT_ID}" \
  --location "${SKILL_REG_LOC}" \
  publish-skill \
  --skill-id "${SKILL_ID}" \
  --display-name "Secure Code Review (${RUN_SUFFIX})" \
  --description "Disposable E2E dry-run skill (${RUN_SUFFIX})." \
  --path "${SKILL_DIR}" >/dev/null
SKILL_REG_CREATED=1
pass "Created disposable Vertex AI Skill Registry skill: ${SKILL_ID} (${SKILL_REG_LOC})"

run_track_python -m coding_agent.tools.registry_loader \
  --project "${PROJECT_ID}" \
  --location "${SKILL_REG_LOC}" \
  update-skill \
  --skill-id "${SKILL_ID}" \
  --description "Updated disposable E2E dry-run skill (${RUN_SUFFIX})." >/dev/null
pass "Updated disposable Vertex AI Skill Registry skill: ${SKILL_ID} (${SKILL_REG_LOC})"

# Three-step Agent Registry standalone skill lifecycle (gcloud alpha in global fallback):
# 1. Create bare skill container without --payload (works around gcloud alpha --payload drop bug)
#    using --scanning-policy=enabled-nonblocking so immediate --default-revision promotion succeeds
#    (production hardening in Lab 7 uses enabled-blocking and awaits async scan completion).
# 2. Upload initial revision `rev-1` (3+ chars required) with --payload=<zip>.
# 3. Promote `rev-1` as --default-revision and activate (--target-state=active) so ADK
#    GCPSkillRegistry.get_skill() can download content cleanly in Stage 5 (DRAFT returns 400).
CLOUDSDK_CORE_DISABLE_PROMPTS=1 gcloud alpha agent-registry skills create "${SKILL_ID}" \
  --project="${PROJECT_ID}" \
  --location="${AGENT_REG_SKILLS_LOC}" \
  --display-name="Secure Code Review (${RUN_SUFFIX})" \
  --description="Disposable E2E dry-run standalone skill (${RUN_SUFFIX})." \
  --target-state=disabled \
  --scanning-policy=enabled-nonblocking </dev/null >/dev/null
AGENT_REG_CREATED=1
CLOUDSDK_CORE_DISABLE_PROMPTS=1 gcloud alpha agent-registry skills revisions create rev-1 \
  --skill="${AGENT_REG_SKILL_NAME}" \
  --project="${PROJECT_ID}" \
  --location="${AGENT_REG_SKILLS_LOC}" \
  --payload="${SKILL_ZIP}" </dev/null >/dev/null
CLOUDSDK_CORE_DISABLE_PROMPTS=1 gcloud alpha agent-registry skills update "${AGENT_REG_SKILL_NAME}" \
  --project="${PROJECT_ID}" \
  --location="${AGENT_REG_SKILLS_LOC}" \
  --default-revision="projects/${PROJECT_ID}/locations/${AGENT_REG_SKILLS_LOC}/skills/${AGENT_REG_SKILL_NAME}/revisions/rev-1" \
  --target-state=active </dev/null >/dev/null
CLOUDSDK_CORE_DISABLE_PROMPTS=1 gcloud alpha agent-registry skills describe "${AGENT_REG_SKILL_NAME}" \
  --project="${PROJECT_ID}" \
  --location="${AGENT_REG_SKILLS_LOC}" </dev/null >/dev/null
pass "Created rev-1, promoted default revision, activated, and described Agent Registry skill: ${AGENT_REG_SKILL_NAME} (${AGENT_REG_SKILLS_LOC})"

# -----------------------------------------------------------------------------
# Stage 5: Terraform Apply (asia-southeast1) + Live :query & :streamQuery Checks
# -----------------------------------------------------------------------------
log "Stage 5: Deploying isolated Agent Runtime via Terraform (${AGENT_PLATFORM_LOC}) + Live :query & :streamQuery checks"

# Verify HTTP contract locally (GET / + POST /api/reasoning_engine with and without application/json)
make -C "${REPO_ROOT}" TRACK="${TRACK}" test-agent-local
pass "Verified Agent Runtime HTTP contract (GET / and POST /api/reasoning_engine) locally"

cp -R "${REPO_ROOT}/${TRACK}/terraform" "${TF_WORK_DIR}"
rm -rf "${TF_WORK_DIR}/.terraform" "${TF_WORK_DIR}/terraform.tfstate" "${TF_WORK_DIR}/terraform.tfstate.backup"

# Isolate ephemeral SA account_id (<=30 chars) & secret_id so E2E never collides with attendee state
python3 - "${TF_WORK_DIR}/main.tf" "${TF_SA_ID}" "${TF_SECRET_ID}" <<'PYEOF'
import sys
from pathlib import Path

tf_path = Path(sys.argv[1])
sa_id, secret_id = sys.argv[2], sys.argv[3]
text = tf_path.read_text(encoding="utf-8")
text = text.replace('"coding-agent-runtime-sa"', f'"{sa_id}"')
text = text.replace('"coding-agent-api-key"', f'"{secret_id}"')
tf_path.write_text(text, encoding="utf-8")
PYEOF

cat > "${TF_WORK_DIR}/e2e.tfvars" <<EOF
project_id              = "${PROJECT_ID}"
project_number          = "${PROJECT_NUMBER}"
location                = "${AGENT_PLATFORM_LOC}"
repository_name         = "${AR_REPO}"
display_name            = "${TF_DISPLAY_NAME}"
agent_image_uri         = "${AGENT_IMG_URI}"
sandbox_image_uri       = "${SANDBOX_IMG_URI}"
sandbox_template_name   = "${BYOC_TEMPLATE_NAME}"
sandbox_mode            = "byoc"
model_name              = "gemini-4-hydrogen"
reasoning_model_name    = "gemini-4-neon"
model_location          = "global"
thinking_level          = "MEDIUM"
api_key_value           = "e2e-dryrun-placeholder-${RUN_SUFFIX}"
enable_memory_bank      = true
enable_skill_registry   = true
skill_registry_location = "${SKILL_REG_LOC}"
EOF

if grep -q 'variable "agent_registry_location"' "${TF_WORK_DIR}/variables.tf"; then
  printf 'agent_registry_location = "%s"\n' "${AGENT_REG_LOC}" >> "${TF_WORK_DIR}/e2e.tfvars"
fi
if grep -q 'variable "agent_registry_skills_location"' "${TF_WORK_DIR}/variables.tf"; then
  printf 'agent_registry_skills_location = "%s"\n' "${AGENT_REG_SKILLS_LOC}" >> "${TF_WORK_DIR}/e2e.tfvars"
fi
if grep -q 'variable "agy_execution_mode"' "${TF_WORK_DIR}/variables.tf"; then
  printf 'agy_execution_mode = "auto"\n' >> "${TF_WORK_DIR}/e2e.tfvars"
fi

terraform -chdir="${TF_WORK_DIR}" init -input=false >/dev/null
terraform -chdir="${TF_WORK_DIR}" validate >/dev/null
TF_APPLIED=1
terraform -chdir="${TF_WORK_DIR}" apply -auto-approve -input=false -var-file="${TF_WORK_DIR}/e2e.tfvars"

TF_ENGINE_NAME="$(terraform -chdir="${TF_WORK_DIR}" output -raw reasoning_engine_resource_name)"
TF_ENGINE_ID="$(terraform -chdir="${TF_WORK_DIR}" output -raw reasoning_engine_id)"
pass "Terraform deployed Agent Runtime (BYOC + Memory Bank + Skill Registry + Gemini 4): ${TF_ENGINE_NAME} (id=${TF_ENGINE_ID})"

# Verify deployed ReasoningEngine metadata & live :query / :streamQuery endpoints
run_track_python eval/setup_online_monitor.py \
  --project "${PROJECT_ID}" \
  --agent-resource-name "${TF_ENGINE_NAME}" \
  --verify-runtime \
  --strict-env >/dev/null
pass "Verified deployed Agent Runtime resource via setup_online_monitor.py --verify-runtime"

ACCESS_TOKEN="$(gcloud auth print-access-token)"
QUERY_RESP_FILE="${TMP_WORK_DIR}/live_query_resp.json"
QUERY_HTTP_CODE="$(curl -sS -o "${QUERY_RESP_FILE}" -w "%{http_code}" \
  -X POST \
  -H "Authorization: Bearer ${ACCESS_TOKEN}" \
  -H "Content-Type: application/json" \
  -d '{"class_method": "list_sessions", "input": {"user_id": "e2e-smoke"}}' \
  "https://${AGENT_PLATFORM_LOC}-aiplatform.googleapis.com/v1beta1/${TF_ENGINE_NAME}:query")"
if [[ "${QUERY_HTTP_CODE}" != "200" ]]; then
  echo "ERROR: Live Agent Runtime :query returned HTTP ${QUERY_HTTP_CODE}: $(cat "${QUERY_RESP_FILE}")" >&2
  exit 1
fi
pass "Live Agent Runtime :query (list_sessions) returned HTTP 200"

CREATE_SESS_RESP_FILE="${TMP_WORK_DIR}/live_create_session_resp.json"
CREATE_SESS_HTTP_CODE="$(curl -sS -o "${CREATE_SESS_RESP_FILE}" -w "%{http_code}" \
  -X POST \
  -H "Authorization: Bearer ${ACCESS_TOKEN}" \
  -H "Content-Type: application/json" \
  -d "{\"class_method\": \"create_session\", \"input\": {\"user_id\": \"e2e-smoke-${RUN_SUFFIX}\"}}" \
  "https://${AGENT_PLATFORM_LOC}-aiplatform.googleapis.com/v1beta1/${TF_ENGINE_NAME}:query")"
if [[ "${CREATE_SESS_HTTP_CODE}" != "200" ]]; then
  echo "ERROR: Live Agent Runtime :query (create_session) returned HTTP ${CREATE_SESS_HTTP_CODE}: $(cat "${CREATE_SESS_RESP_FILE}")" >&2
  exit 1
fi
STREAM_SESSION_ID="$(python3 - "${CREATE_SESS_RESP_FILE}" <<'PYEOF'
import json, sys
from pathlib import Path

data = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))
out = data.get("output") if isinstance(data, dict) else None
sid = ""
if isinstance(out, dict):
    sid = str(out.get("id") or out.get("session_id") or "")
    if not sid and out.get("name"):
        sid = str(out["name"]).rstrip("/").split("/")[-1]
elif isinstance(out, str):
    sid = out.rstrip("/").split("/")[-1]
if not sid:
    raise SystemExit(f"Could not extract session_id from create_session response: {data!r}")
print(sid)
PYEOF
)"
pass "Live Agent Runtime :query (create_session) returned HTTP 200 (session_id=${STREAM_SESSION_ID}; exercises Stage 7 deletion_policy=\"FORCE\")"

# Live :streamQuery?alt=sse turn testing Gemini 4 Hydrogen + BYOC sandbox `agy` check
STREAM_RESP_FILE="${TMP_WORK_DIR}/live_stream_query_resp.sse"
STREAM_REQ_BODY="$(python3 - "e2e-smoke-${RUN_SUFFIX}" "${STREAM_SESSION_ID}" <<'PYEOF'
import json, sys

print(
    json.dumps(
        {
            "class_method": "async_stream_query",
            "input": {
                "user_id": sys.argv[1],
                "session_id": sys.argv[2],
                "message": (
                    "Use your sandbox Execute tool to run `whoami && which agy && agy --version` "
                    "inside the BYOC sandbox, then reply concisely with the command output and E2E_STREAM_OK."
                ),
            },
        }
    )
)
PYEOF
)"
STREAM_HTTP_CODE="$(curl -sS --max-time 180 -o "${STREAM_RESP_FILE}" -w "%{http_code}" \
  -X POST \
  -H "Authorization: Bearer ${ACCESS_TOKEN}" \
  -H "Content-Type: application/json" \
  -d "${STREAM_REQ_BODY}" \
  "https://${AGENT_PLATFORM_LOC}-aiplatform.googleapis.com/v1beta1/${TF_ENGINE_NAME}:streamQuery?alt=sse")"
if [[ "${STREAM_HTTP_CODE}" != "200" ]]; then
  echo "ERROR: Live Agent Runtime :streamQuery?alt=sse returned HTTP ${STREAM_HTTP_CODE}: $(cat "${STREAM_RESP_FILE}")" >&2
  exit 1
fi
STREAM_SUMMARY="$(python3 - "${STREAM_RESP_FILE}" <<'PYEOF'
import json, sys
from pathlib import Path

raw = Path(sys.argv[1]).read_text(encoding="utf-8", errors="replace")
events = []
for line in raw.splitlines():
    stripped = line.strip()
    if not stripped or stripped.startswith(":") or stripped.startswith("event:"):
        continue
    if stripped.startswith("data:"):
        stripped = stripped[5:].strip()
    if not stripped or stripped == "[DONE]":
        continue
    try:
        events.append(json.loads(stripped))
    except json.JSONDecodeError:
        continue

if not events:
    raise SystemExit(f"No JSON event frames received from :streamQuery?alt=sse. Raw tail: {raw[-500:]!r}")

for ev in events:
    if isinstance(ev, dict) and ev.get("error"):
        raise SystemExit(f"Streamed error frame from Agent Runtime: {ev['error']!r}")

text_chunks = []
tool_calls = 0
tool_outputs = []


def _walk(obj):
    global tool_calls
    if isinstance(obj, dict):
        for key in ("function_call", "functionCall"):
            if key in obj and obj[key]:
                tool_calls += 1
        for key in ("function_response", "functionResponse"):
            if key in obj and obj[key]:
                tool_outputs.append(json.dumps(obj[key], default=str))
        if isinstance(obj.get("text"), str) and obj["text"].strip():
            text_chunks.append(obj["text"])
        for val in obj.values():
            _walk(val)
    elif isinstance(obj, list):
        for item in obj:
            _walk(item)


_walk(events)

combined_text = "\n".join(text_chunks).strip()
combined_all = (combined_text + "\n" + "\n".join(tool_outputs)).lower()
if not combined_text:
    raise SystemExit(f"Empty model response text across {len(events)} SSE frames.")
if tool_calls < 1 and not tool_outputs:
    raise SystemExit(
        f"Expected at least 1 BYOC sandbox tool call during :streamQuery turn (frames={len(events)}, text={combined_text[:200]!r})."
    )
if "appuser" not in combined_all or "agy" not in combined_all:
    raise SystemExit(
        f"BYOC sandbox agy/non-root verification missing expected markers ('appuser' and 'agy') in streamed turn. "
        f"tool_calls={tool_calls}, text={combined_text[:300]!r}"
    )

preview = " ".join(combined_text.split())[:140]
print(f"frames={len(events)}, tool_calls={tool_calls}, preview={preview!r}")
PYEOF
)"
pass "Live Agent Runtime :streamQuery?alt=sse (Gemini 4 Hydrogen + BYOC sandbox agy check) succeeded (${STREAM_SUMMARY})"

# -----------------------------------------------------------------------------
# Stage 6: Offline Evaluation (global) + Cloud Monitoring Quality Alert Policy
# -----------------------------------------------------------------------------
log "Stage 6: Running Offline Evaluation (${EVAL_LOC}) + Cloud Monitoring Quality Alert Policy"

run_track_python eval/run_offline_eval.py \
  --project "${PROJECT_ID}" \
  --location "${EVAL_LOC}" \
  --single-turn-dataset eval/datasets/coding_agent_single_turn.json \
  --multi-turn-dataset eval/datasets/coding_agent_multi_turn.json \
  --output-json "${TMP_WORK_DIR}/offline_eval_report.json" >/dev/null
pass "Offline Evaluation succeeded in ${EVAL_LOC}"

ALERT_OUT="$(run_track_python eval/setup_quality_alerts.py \
  --project "${PROJECT_ID}" \
  --display-name "${ALERT_DISPLAY_NAME}" \
  --agent-resource-name "${TF_ENGINE_NAME}")"
ALERT_POLICY_NAME="$(printf '%s\n' "${ALERT_OUT}" | sed -nE 's|^Created Cloud Monitoring alerting policy:[[:space:]]*(projects/.+)$|\1|p' | tail -n 1)"
if [[ -z "${ALERT_POLICY_NAME}" ]]; then
  echo "ERROR: Failed to parse created alert policy name from setup_quality_alerts.py output." >&2
  exit 1
fi
pass "Created Cloud Monitoring Quality Alert policy: ${ALERT_POLICY_NAME}"

# -----------------------------------------------------------------------------
# Stage 7: Full Teardown + Verification that 0 Dry-Run Resources Remain
# -----------------------------------------------------------------------------
log "Stage 7: Executing full teardown and verifying 0 dry-run resources remain"
run_teardown

LEAKS=0
VERIFY_TOKEN="$(gcloud auth print-access-token)"

if [[ "${TF_DESTROY_FAILED}" -ne 0 ]]; then
  warn "TEARDOWN FAILURE: terraform destroy returned a non-zero exit code in Stage 7"
  LEAKS=$((LEAKS + 1))
fi

# 7a. Verify 0 dry-run ReasoningEngines remain in AGENT_PLATFORM_LOC (allow LRO propagation)
REMAINING_ENGINES=1
for _ in $(seq 1 12); do
  ENGINES_JSON="$(curl -sS -H "Authorization: Bearer ${VERIFY_TOKEN}" \
    "https://${AGENT_PLATFORM_LOC}-aiplatform.googleapis.com/v1beta1/projects/${PROJECT_ID}/locations/${AGENT_PLATFORM_LOC}/reasoningEngines")"
  REMAINING_ENGINES="$(ENGINES_JSON="${ENGINES_JSON}" python3 - "${RUN_SUFFIX}" <<'PYEOF'
import json, os, sys
suffix = sys.argv[1]
data = json.loads(os.environ.get("ENGINES_JSON") or "{}")
matches = [e.get("name") for e in data.get("reasoningEngines", []) if suffix in str(e.get("displayName", ""))]
print(len(matches))
PYEOF
)"
  if [[ "${REMAINING_ENGINES}" -eq 0 ]]; then
    break
  fi
  sleep 5
done
if [[ "${REMAINING_ENGINES}" -ne 0 ]]; then
  warn "LEAK DETECTED: ${REMAINING_ENGINES} dry-run ReasoningEngine(s) still present in ${AGENT_PLATFORM_LOC}"
  LEAKS=$((LEAKS + 1))
else
  pass "Verified 0 dry-run ReasoningEngines remain in ${AGENT_PLATFORM_LOC}"
fi

# 7b. Verify 0 dry-run Cloud Monitoring Alert Policies remain
REMAINING_ALERTS="$(gcloud monitoring policies list \
  --project="${PROJECT_ID}" \
  --filter="displayName:\"${RUN_SUFFIX}\"" \
  --format="value(name)" 2>/dev/null | grep -c . || true)"
if [[ "${REMAINING_ALERTS}" -ne 0 ]]; then
  warn "LEAK DETECTED: ${REMAINING_ALERTS} dry-run alert policy/policies still present"
  LEAKS=$((LEAKS + 1))
else
  pass "Verified 0 dry-run Cloud Monitoring alert policies remain"
fi

# 7c. Verify 0 dry-run Agent Registry standalone skills remain in AGENT_REG_SKILLS_LOC
if CLOUDSDK_CORE_DISABLE_PROMPTS=1 gcloud alpha agent-registry skills describe "${AGENT_REG_SKILL_NAME}" \
  --project="${PROJECT_ID}" --location="${AGENT_REG_SKILLS_LOC}" </dev/null >/dev/null 2>&1; then
  warn "LEAK DETECTED: Agent Registry skill ${AGENT_REG_SKILL_NAME} still present in ${AGENT_REG_SKILLS_LOC}"
  LEAKS=$((LEAKS + 1))
else
  pass "Verified 0 dry-run Agent Registry skills remain in ${AGENT_REG_SKILLS_LOC}"
fi

# 7d. Verify disposable Vertex AI Skill Registry skill is deleted in SKILL_REG_LOC (allow brief LRO propagation)
SKILL_CHECK_CODE="000"
for _ in $(seq 1 6); do
  SKILL_CHECK_CODE="$(curl -sS -o /dev/null -w "%{http_code}" \
    -H "Authorization: Bearer ${VERIFY_TOKEN}" \
    "https://${SKILL_REG_LOC}-aiplatform.googleapis.com/v1beta1/projects/${PROJECT_ID}/locations/${SKILL_REG_LOC}/skills/${SKILL_ID}")"
  if [[ "${SKILL_CHECK_CODE}" == "404" ]]; then
    break
  fi
  sleep 5
done
if [[ "${SKILL_CHECK_CODE}" == "404" ]]; then
  pass "Verified disposable Skill Registry skill ${SKILL_ID} removed (HTTP 404) in ${SKILL_REG_LOC}"
else
  warn "LEAK DETECTED: Skill Registry skill ${SKILL_ID} returned HTTP ${SKILL_CHECK_CODE} (expected 404)"
  LEAKS=$((LEAKS + 1))
fi

# 7e. Verify 0 dry-run Artifact Registry tags (and any disposable repo created in Stage 0) remain in AR_LOC
REMAINING_AR=0
for img in "${SANDBOX_IMG_URI}" "${AGENT_IMG_URI}"; do
  if gcloud artifacts docker images describe "${img}" --project="${PROJECT_ID}" >/dev/null 2>&1; then
    warn "LEAK DETECTED: Artifact Registry image still present: ${img}"
    REMAINING_AR=$((REMAINING_AR + 1))
  fi
done
if [[ "${REMAINING_AR}" -ne 0 ]]; then
  LEAKS=$((LEAKS + 1))
else
  pass "Verified 0 dry-run Artifact Registry images remain in ${AR_LOC}"
fi

if [[ "${AR_REPO_CREATED}" -eq 1 ]]; then
  AR_REPO_GONE=0
  for _ in $(seq 1 6); do
    if ! gcloud artifacts repositories describe "${AR_REPO}" \
      --location="${AR_LOC}" --project="${PROJECT_ID}" </dev/null >/dev/null 2>&1; then
      AR_REPO_GONE=1
      break
    fi
    sleep 5
  done
  if [[ "${AR_REPO_GONE}" -eq 1 ]]; then
    pass "Verified disposable Artifact Registry repository ${AR_REPO} removed from ${AR_LOC}"
  else
    warn "LEAK DETECTED: Disposable Artifact Registry repository ${AR_REPO} still present in ${AR_LOC}"
    LEAKS=$((LEAKS + 1))
  fi
fi

# 7f. Verify ephemeral Terraform Runtime Service Account was destroyed
if [[ "${TF_APPLIED}" -eq 1 ]]; then
  if gcloud iam service-accounts describe "${TF_SA_EMAIL}" \
    --project="${PROJECT_ID}" </dev/null >/dev/null 2>&1; then
    warn "LEAK DETECTED: Ephemeral Terraform Service Account still present: ${TF_SA_EMAIL}"
    LEAKS=$((LEAKS + 1))
  else
    pass "Verified ephemeral Terraform Service Account removed: ${TF_SA_EMAIL}"
  fi
fi

# 7g. Verify ephemeral Terraform Secret Manager secret was destroyed
if [[ "${TF_APPLIED}" -eq 1 ]]; then
  if gcloud secrets describe "${TF_SECRET_ID}" \
    --project="${PROJECT_ID}" </dev/null >/dev/null 2>&1; then
    warn "LEAK DETECTED: Ephemeral Terraform Secret Manager secret still present: ${TF_SECRET_ID}"
    LEAKS=$((LEAKS + 1))
  else
    pass "Verified ephemeral Terraform Secret Manager secret removed: ${TF_SECRET_ID}"
  fi
fi

if [[ "${LEAKS}" -gt 0 ]]; then
  echo "ERROR: ${LEAKS} resource leak check(s) failed after teardown!" >&2
  exit 1
fi

printf "\n=============================================================================\n"
printf "LIVE GCP E2E VALIDATION PASSED (project=%s, suffix=%s, leaks=0)\n" "${PROJECT_ID}" "${RUN_SUFFIX}"
printf "=============================================================================\n"
exit 0
