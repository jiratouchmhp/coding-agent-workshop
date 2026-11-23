#!/usr/bin/env bash
# =============================================================================
# Enterprise Coding Agent Workshop — Automated Lab Checkpoint Verifier (Labs 1-8)
# =============================================================================
# Usage:
#   ./scripts/verify_lab.sh <1|2|3|4|5|6|7|8|all> [--track starter|solution]
#   TRACK=solution ./scripts/verify_lab.sh all
#   TRACK=solution ./scripts/verify_lab.sh 7
#   TRACK=solution ./scripts/verify_lab.sh 8
# =============================================================================

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
cd "${REPO_ROOT}"

# Redirect Python bytecode writes to a temporary directory so py_compile never
# pollutes starter/, solution/, or scripts/ with __pycache__/*.pyc files.
PYCACHE_TMP="$(mktemp -d)"
trap 'rm -rf "${PYCACHE_TMP}"' EXIT
export PYTHONPYCACHEPREFIX="${PYCACHE_TMP}"

TRACK="${TRACK:-starter}"
TARGET=""

usage() {
  cat <<'EOF'
Usage: ./scripts/verify_lab.sh <1|2|3|4|5|6|7|8|all> [--track starter|solution]

Verify workshop checkpoints locally for Labs 1-8:
  1    Lab 1: Setup, agents-cli-manifest.yaml, .agents/skills/ & ADK LlmAgent + LocalEnvironment
  2    Lab 2: Non-root BYOC Sandbox Dockerfile, Lifecycle & BaseEnvironment execution
  3    Lab 3: Managed Sessions, Memory Bank, Prompt-Injection Sanitizer & Telemetry/Feedback
  4    Lab 4: Skill Registry 16-check packaging, GCPSkillRegistry & AgentRegistry loader
  5    Lab 5: Agent Runtime BYOC Dockerfile/main.py/requirements.txt & Terraform IaC + IAM
  6    Lab 6: Split JSON Eval Datasets, Offline/Simulated Eval, Online Monitor, Alerts & Optimize
  7    Lab 7 (Optional): Enterprise Security & Governance Hardening checks
  8    Lab 8: Self-Hosted GKE Agent Sandbox overlay (RBAC, VAP hardening, WarmPool)
  all  Run checkpoints for core Labs 1-6

Options:
  --track <starter|solution>   Directory to verify (default: starter; or set TRACK=solution)
  -h, --help                   Show this help message
EOF
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    1|2|3|4|5|6|7|8|all)
      TARGET="$1"
      shift
      ;;
    --track)
      if [[ $# -lt 2 ]]; then
        echo "ERROR: --track requires 'starter' or 'solution'." >&2
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

if [[ -z "${TARGET}" ]]; then
  usage >&2
  exit 2
fi

if [[ "${TRACK}" != "starter" && "${TRACK}" != "solution" ]]; then
  echo "ERROR: TRACK must be 'starter' or 'solution' (got '${TRACK}')." >&2
  exit 2
fi

# Color helpers (disabled automatically when stdout is not a TTY)
if [[ -t 1 ]]; then
  C_GREEN='\033[0;32m'
  C_RED='\033[0;31m'
  C_YELLOW='\033[0;33m'
  C_BLUE='\033[0;34m'
  C_RESET='\033[0m'
else
  C_GREEN=''
  C_RED=''
  C_YELLOW=''
  C_BLUE=''
  C_RESET=''
fi

PASS_COUNT=0
FAIL_COUNT=0
WARN_COUNT=0

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

section() {
  printf "\n${C_BLUE}=== %s ===${C_RESET}\n" "$1"
}

check_file_exists() {
  local path="$1"
  if [[ -f "${path}" ]]; then
    pass "Found file: ${path}"
  else
    fail "Missing required file: ${path}"
  fi
}

check_py_compile() {
  local path="$1"
  if [[ ! -f "${path}" ]]; then
    fail "Cannot compile missing file: ${path}"
    return 0
  fi
  if python3 -m py_compile "${path}" 2>/dev/null; then
    pass "Python syntax valid: ${path}"
  else
    fail "Python syntax error in: ${path}"
  fi
}

check_bash_syntax() {
  local path="$1"
  if [[ ! -f "${path}" ]]; then
    fail "Cannot syntax-check missing bash script: ${path}"
    return 0
  fi
  if bash -n "${path}" 2>/dev/null; then
    pass "Bash syntax valid (bash -n): ${path}"
  else
    fail "Bash syntax error in: ${path}"
  fi
}

has_todo_markers() {
  local path="$1"
  local lab_tag="$2"
  [[ -f "${path}" ]] && grep -q "TODO(${lab_tag})" "${path}"
}

check_no_todo_markers() {
  local path="$1"
  local lab_tag="$2"
  if [[ ! -f "${path}" ]]; then
    return 0
  fi
  local count
  count="$(grep -c "TODO(${lab_tag})" "${path}" || true)"
  if [[ "${count}" -eq 0 ]]; then
    pass "Zero remaining TODO(${lab_tag}) markers in ${path}"
  else
    fail "${path} still has ${count} unfinished TODO(${lab_tag}) marker(s) (complete them or compare against solution/)."
  fi
}

check_pattern() {
  local path="$1"
  local pattern="$2"
  local label="$3"
  if [[ ! -f "${path}" ]]; then
    return 0
  fi
  if grep -Eq -- "${pattern}" "${path}"; then
    pass "${label} (${path})"
  else
    fail "Missing expected pattern [${label}] in ${path}"
  fi
}

check_dockerfile_non_root() {
  local df="$1"
  local label="$2"
  if [[ ! -f "${df}" ]]; then
    return 0
  fi
  local last_user
  last_user="$(grep -E '^USER[[:space:]]+' "${df}" | tail -n 1 || true)"
  if [[ -z "${last_user}" ]]; then
    fail "${label} is missing a non-root USER directive (${df})."
  elif [[ "${last_user}" =~ ^USER[[:space:]]+(root|0)([[:space:]:].*)?$ ]]; then
    fail "${label} ends with root user '${last_user}' (${df})."
  else
    pass "${label} final USER directive is non-root (${last_user})"
  fi
}

# -----------------------------------------------------------------------------
# Lab 1: Setup & Build ADK Coding Agent
# -----------------------------------------------------------------------------
verify_lab_1() {
  section "Lab 1 Verification (${TRACK}/ — Setup & ADK Build)"
  check_file_exists ".env.example"
  check_file_exists "Makefile"
  check_file_exists "scripts/preflight_check.sh"
  check_file_exists "scripts/fast_forward_lab.sh"
  check_file_exists "scripts/cleanup_workshop.sh"
  check_file_exists "scripts/live_gcp_e2e_validate.sh"
  check_bash_syntax "scripts/preflight_check.sh"
  check_bash_syntax "scripts/fast_forward_lab.sh"
  check_bash_syntax "scripts/cleanup_workshop.sh"
  check_bash_syntax "scripts/live_gcp_e2e_validate.sh"
  if [[ -x "scripts/fast_forward_lab.sh" ]]; then
    pass "scripts/fast_forward_lab.sh is executable (+x)"
  else
    fail "scripts/fast_forward_lab.sh is not executable (run: chmod +x scripts/fast_forward_lab.sh)"
  fi
  check_file_exists "${TRACK}/pyproject.toml"
  check_file_exists "${TRACK}/agents-cli-manifest.yaml"
  check_file_exists "${TRACK}/coding_agent/config.py"
  check_file_exists "${TRACK}/coding_agent/agent.py"
  check_file_exists "${TRACK}/coding_agent/architectures.py"
  check_file_exists "${TRACK}/services.yaml"
  check_file_exists "${TRACK}/services.py"

  check_pattern ".env.example" "^PRIMARY_REGION=asia-southeast3$" ".env.example sets PRIMARY_REGION=asia-southeast3 (Bangkok first)"
  check_pattern ".env.example" "^GOOGLE_CLOUD_LOCATION=asia-southeast1$" ".env.example sets GOOGLE_CLOUD_LOCATION=asia-southeast1 (Singapore fallback for Agent Platform)"
  check_pattern ".env.example" "^AGENT_REGISTRY_LOCATION=asia-southeast3$" ".env.example sets AGENT_REGISTRY_LOCATION=asia-southeast3 (Bangkok A2A/MCP discovery)"
  check_pattern ".env.example" "^AGENT_REGISTRY_SKILLS_LOCATION=global$" ".env.example sets AGENT_REGISTRY_SKILLS_LOCATION=global (Agent Registry standalone skills fallback)"
  check_pattern ".env.example" "^SKILL_REGISTRY_LOCATION=us-central1$" ".env.example sets SKILL_REGISTRY_LOCATION=us-central1"
  check_pattern ".env.example" "^EVAL_LOCATION=global$" ".env.example sets EVAL_LOCATION=global"
  check_pattern ".env.example" "^AGENT_ARCHITECTURE=simple$" "Default AGENT_ARCHITECTURE=simple preserves Labs 2-8 compatibility"
  check_pattern ".env.example" "^MAX_FIX_ROUNDS=3$" ".env.example sets MAX_FIX_ROUNDS=3"
  check_pattern ".env.example" "^ENABLE_HITL_APPROVAL=false$" ".env.example sets ENABLE_HITL_APPROVAL=false"

  check_pattern "Makefile" "^preflight:" "Makefile defines preflight target"
  check_pattern "Makefile" "^test-sandbox-local:" "Makefile defines zero-Docker test-sandbox-local target"
  check_pattern "Makefile" "^test-agent-local:" "Makefile defines zero-Docker test-agent-local target"
  check_pattern "Makefile" "^pack-agent-source:" "Makefile defines zero-Docker/zero-AR pack-agent-source target"
  check_pattern "Makefile" "^fast-forward:" "Makefile defines fast-forward target"
  check_pattern "Makefile" "^cleanup:" "Makefile defines cleanup target"

  # Regression check: Makefile `test-agent-local` must `unset GOOGLE_CLOUD_AGENT_ENGINE_ID`
  # instead of exporting `GOOGLE_CLOUD_AGENT_ENGINE_ID=""` (AdkApp.set_up() checks key presence
  # in os.environ and crashes with ValueError on an empty string).
  if [[ -f "Makefile" ]]; then
    if python3 - "Makefile" <<'PYEOF'
import re
import sys
from pathlib import Path

text = Path(sys.argv[1]).read_text(encoding="utf-8")
m = re.search(
    r"^test-agent-local:[^\n]*\n((?:\t[^\n]*\n|[ \t]*\n)*)",
    text,
    flags=re.MULTILINE,
)
if not m:
    sys.exit(1)

recipe = "\n".join(
    line for line in m.group(1).splitlines() if not line.lstrip().startswith("#")
)
joined = re.sub(r"\\\n[ \t]*", " ", recipe)
if not re.search(r"\bunset\b[^\n;]*\bGOOGLE_CLOUD_AGENT_ENGINE_ID\b", joined):
    sys.exit(1)
if re.search(r"\bGOOGLE_CLOUD_AGENT_ENGINE_ID\s*=", joined):
    sys.exit(1)
PYEOF
    then
      pass "Makefile test-agent-local unsets GOOGLE_CLOUD_AGENT_ENGINE_ID (does not export empty string)"
    else
      fail "Makefile test-agent-local must unset GOOGLE_CLOUD_AGENT_ENGINE_ID (and must NOT export GOOGLE_CLOUD_AGENT_ENGINE_ID=\"\")"
    fi
  fi

  # Regression check: scripts/live_gcp_e2e_validate.sh must not invoke bare
  # `gcloud beta services identity create` (hangs invisibly if gcloud beta component is absent).
  if [[ -f "scripts/live_gcp_e2e_validate.sh" ]]; then
    if python3 - "scripts/live_gcp_e2e_validate.sh" <<'PYEOF'
import re
import sys
from pathlib import Path

raw = Path(sys.argv[1]).read_text(encoding="utf-8")
code = "\n".join(
    line for line in raw.splitlines() if not line.lstrip().startswith("#")
)
joined = re.sub(r"\\\n[ \t]*", " ", code)
if re.search(r"\bgcloud\s+beta\s+services\s+identity\s+create\b", joined):
    sys.exit(1)
if not re.search(
    r"CLOUDSDK_CORE_DISABLE_PROMPTS=1\s+gcloud\s+alpha\s+services\s+identity\s+create\b[^\n]*</dev/null",
    joined,
):
    sys.exit(1)
PYEOF
    then
      pass "scripts/live_gcp_e2e_validate.sh uses non-interactive gcloud alpha services identity create (no bare gcloud beta)"
    else
      fail "scripts/live_gcp_e2e_validate.sh must use CLOUDSDK_CORE_DISABLE_PROMPTS=1 gcloud alpha services identity create ... </dev/null (never bare gcloud beta services identity create)"
    fi
  fi

  check_pattern "${TRACK}/agents-cli-manifest.yaml" "agent_directory:[[:space:]]*coding_agent" "agents-cli manifest sets agent_directory: coding_agent"
  check_pattern "${TRACK}/agents-cli-manifest.yaml" "framework:[[:space:]]*google-adk" "agents-cli manifest sets framework: google-adk"
  check_pattern "${TRACK}/agents-cli-manifest.yaml" "deployment_target:[[:space:]]*agent_runtime" "agents-cli manifest sets deployment_target: agent_runtime"

  check_py_compile "${TRACK}/coding_agent/config.py"
  check_py_compile "${TRACK}/coding_agent/agent.py"
  check_py_compile "${TRACK}/coding_agent/architectures.py"
  check_py_compile "${TRACK}/services.py"
  check_no_todo_markers "${TRACK}/coding_agent/agent.py" "lab-1"
  check_no_todo_markers "${TRACK}/coding_agent/architectures.py" "lab-1"

  check_pattern "${TRACK}/coding_agent/config.py" "AGENT_ARCHITECTURE" "config.py reads AGENT_ARCHITECTURE"
  check_pattern "${TRACK}/coding_agent/config.py" "agent_architecture" "config.py exposes typed agent_architecture"
  check_pattern "${TRACK}/coding_agent/config.py" "max_fix_rounds" "config.py exposes typed max_fix_rounds"
  check_pattern "${TRACK}/coding_agent/config.py" "enable_hitl_approval" "config.py exposes typed enable_hitl_approval"

  check_pattern "${TRACK}/coding_agent/agent.py" "LocalEnvironment\(" "Uses ADK LocalEnvironment"
  check_pattern "${TRACK}/coding_agent/agent.py" "Path" "Passes pathlib.Path to LocalEnvironment"
  check_pattern "${TRACK}/coding_agent/agent.py" "EnvironmentToolset\(" "Wraps environment in EnvironmentToolset"
  check_pattern "${TRACK}/coding_agent/agent.py" "max_output_chars" "Sets max_output_chars on EnvironmentToolset"
  check_pattern "${TRACK}/coding_agent/agent.py" "def build_root_agent\(" "Defines build_root_agent() architecture dispatcher"
  check_pattern "${TRACK}/coding_agent/agent.py" "agent_architecture" "Dispatches root_agent on cfg.agent_architecture"
  check_pattern "${TRACK}/coding_agent/agent.py" "ResumabilityConfig" "Configures ResumabilityConfig on App"
  check_pattern "${TRACK}/coding_agent/agent.py" 'App\(.*name="coding_agent"' "App.name matches coding_agent directory"

  check_pattern "${TRACK}/coding_agent/architectures.py" "^from google\.adk import Context, Event, Workflow\b" "Uses direct ADK 2.0 top-level import (Context, Event, Workflow)"
  check_pattern "${TRACK}/coding_agent/architectures.py" "^from google\.adk\.workflow import JoinNode, NodeTimeoutError, RetryConfig, node\b" "Uses direct ADK 2.0 workflow imports (JoinNode, NodeTimeoutError, RetryConfig, node)"
  check_pattern "${TRACK}/coding_agent/architectures.py" "def build_global_instruction_plugin\(" "Defines GlobalInstructionPlugin builder"
  check_pattern "${TRACK}/coding_agent/architectures.py" "def build_collaborative_coding_team\(" "Defines collaborative coordinator team builder"
  check_pattern "${TRACK}/coding_agent/architectures.py" "def build_graph_coding_workflow\(" "Defines declarative graph Workflow builder"
  check_pattern "${TRACK}/coding_agent/architectures.py" "def build_dynamic_coding_workflow\(" "Defines dynamic workflow builder"
  check_pattern "${TRACK}/coding_agent/architectures.py" "def build_optional_managed_agent\(" "Defines optional ManagedAgent builder"

  # Anti-regression check: forbid deprecated ADK 1.x workflow agents and legacy _require_adk_v2 wrapper
  for adk_file in "${TRACK}/coding_agent/architectures.py" "${TRACK}/coding_agent/agent.py"; do
    if [[ -f "${adk_file}" ]]; then
      if grep -Eq "\b(SequentialAgent|ParallelAgent|LoopAgent|_require_adk_v2)\b" "${adk_file}"; then
        fail "Deprecated ADK 1.x symbol (SequentialAgent/ParallelAgent/LoopAgent/_require_adk_v2) found in ${adk_file}"
      else
        pass "Zero deprecated SequentialAgent/ParallelAgent/LoopAgent/_require_adk_v2 references (${adk_file})"
      fi
    fi
  done

  if ! has_todo_markers "${TRACK}/coding_agent/architectures.py" "lab-1"; then
    check_pattern "${TRACK}/coding_agent/architectures.py" 'mode="single_turn"' "Collaborative team uses mode=\"single_turn\" on subagents"
    check_pattern "${TRACK}/coding_agent/architectures.py" 'mode="task"' "Collaborative team uses mode=\"task\" leaf clarifier"
    check_pattern "${TRACK}/coding_agent/architectures.py" "JoinNode\(" "Graph workflow merges parallel branches with JoinNode"
    check_pattern "${TRACK}/coding_agent/architectures.py" "RetryConfig\(" "Graph/dynamic check nodes configure RetryConfig"
    check_pattern "${TRACK}/coding_agent/architectures.py" "RequestInput\(" "Graph/dynamic HITL node yields RequestInput"
    check_pattern "${TRACK}/coding_agent/architectures.py" "rerun_on_resume=True" "Dynamic orchestrator sets rerun_on_resume=True"
    check_pattern "${TRACK}/coding_agent/architectures.py" "use_sub_branch=True" "Dynamic parallel checks isolate events with use_sub_branch=True"
  fi

  check_pattern "${TRACK}/services.yaml" "^services:" "services.yaml declares ADK service registration list"
  check_pattern "${TRACK}/services.py" "get_service_registry" "services.py demonstrates programmatic ServiceRegistry registration"

  # Validate Settings defaults/validation in config.py (stdlib-only smoke check)
  if [[ -f "${TRACK}/coding_agent/config.py" ]]; then
    if python3 - "${TRACK}/coding_agent/config.py" <<'PYEOF'
import importlib.util
import sys

spec = importlib.util.spec_from_file_location("_verify_cfg", sys.argv[1])
assert spec and spec.loader
mod = importlib.util.module_from_spec(spec)
sys.modules["_verify_cfg"] = mod
spec.loader.exec_module(mod)

s = mod.Settings()
assert s.agent_architecture == "simple", f"Expected default simple, got {s.agent_architecture!r}"
assert s.max_fix_rounds == 3, f"Expected default max_fix_rounds=3, got {s.max_fix_rounds!r}"
assert s.enable_hitl_approval is False, f"Expected default enable_hitl_approval=False, got {s.enable_hitl_approval!r}"
assert s.primary_region == "asia-southeast3", f"Expected Bangkok-first default primary_region='asia-southeast3', got {s.primary_region!r}"
assert s.google_cloud_location == "asia-southeast1", f"Expected Singapore fallback google_cloud_location='asia-southeast1', got {s.google_cloud_location!r}"
assert s.ar_location == "asia-southeast3", f"Expected Bangkok-first ar_location='asia-southeast3', got {s.ar_location!r}"
assert s.build_location == "asia-southeast3", f"Expected Bangkok-first build_location='asia-southeast3', got {s.build_location!r}"
assert s.skill_registry_location == "us-central1", f"Expected default skill_registry_location='us-central1', got {s.skill_registry_location!r}"
assert s.agent_registry_location == "asia-southeast3", f"Expected Bangkok-first default agent_registry_location='asia-southeast3', got {s.agent_registry_location!r}"
assert getattr(s, "agent_registry_skills_location", None) == "global", (
    f"Expected fallback default agent_registry_skills_location='global', got {getattr(s, 'agent_registry_skills_location', None)!r}"
)
assert s.eval_location == "global", f"Expected default eval_location='global', got {s.eval_location!r}"
assert s.gke_location == "asia-southeast3", f"Expected Bangkok-first default gke_location='asia-southeast3', got {s.gke_location!r}"
assert mod.Settings(primary_region="europe-west4", agent_registry_location="").agent_registry_location == "europe-west4"
assert mod.Settings(skill_registry_location="europe-west4", agent_registry_location="global").agent_registry_location == "global"
assert mod.Settings(agent_registry_skills_location="").agent_registry_skills_location == "global"

for arch in ("simple", "collaborative", "graph", "dynamic"):
    assert mod.Settings(agent_architecture=arch).agent_architecture == arch

try:
    mod.Settings(agent_architecture="invalid_arch")
    raise AssertionError("Expected ValueError for invalid agent_architecture")
except ValueError:
    pass

try:
    mod.Settings(max_fix_rounds=0)
    raise AssertionError("Expected ValueError for max_fix_rounds=0")
except ValueError:
    pass
PYEOF
    then
      pass "config.py Settings defaults and ADK 2.0 field validation verified (${TRACK}/coding_agent/config.py)"
    else
      fail "config.py Settings validation failed (${TRACK}/coding_agent/config.py)"
    fi
  fi

  # Validate services.yaml parses safely with a non-null services list
  if [[ -f "${TRACK}/services.yaml" ]]; then
    if python3 - "${TRACK}/services.yaml" 2>/dev/null <<'PYEOF'
import sys
from pathlib import Path

try:
    import yaml
except ImportError:
    sys.exit(2)

doc = yaml.safe_load(Path(sys.argv[1]).read_text(encoding="utf-8"))
assert isinstance(doc, dict) and isinstance(doc.get("services"), list), "services.yaml must define a list under 'services:'"
PYEOF
    then
      pass "services.yaml parses cleanly with a valid 'services' list (${TRACK}/services.yaml)"
    else
      rc=$?
      if [[ "${rc}" -eq 2 ]]; then
        warn "PyYAML not installed; skipping structured services.yaml validation."
      else
        fail "services.yaml YAML structure check failed (${TRACK}/services.yaml)"
      fi
    fi
  fi

  if [[ -d ".agents/skills" ]]; then
    if python3 scripts/validate_skills.py .agents/skills >/dev/null 2>&1; then
      pass "All bundled skills under .agents/skills/ pass validate_skills.py"
    else
      fail "scripts/validate_skills.py failed on .agents/skills/ (run 'make validate-skills' for details)"
    fi
  else
    warn ".agents/skills/ directory not present yet; skipping skill validation."
  fi

  if command -v agents-cli >/dev/null 2>&1; then
    pass "agents-cli found on PATH ($(command -v agents-cli)) — optional for Labs 1-6"
  else
    warn "agents-cli not found on PATH (optional for Labs 1-6; install anytime with: uvx google-agents-cli setup)"
  fi
}

# -----------------------------------------------------------------------------
# Lab 2: Custom Sandbox (BYOC), Lifecycle & Execution
# -----------------------------------------------------------------------------
verify_lab_2() {
  section "Lab 2 Verification (${TRACK}/ — BYOC Sandbox, Lifecycle & Execution)"
  local df="${TRACK}/sandbox_image/Dockerfile"
  local runner="${TRACK}/sandbox_image/runner.py"
  local lc="${TRACK}/coding_agent/tools/sandbox_lifecycle.py"
  local ex="${TRACK}/coding_agent/tools/sandbox_execution.py"
  local ag="${TRACK}/coding_agent/agent.py"

  check_file_exists "${df}"
  check_file_exists "${runner}"
  check_file_exists "${TRACK}/sandbox_image/requirements.txt"
  check_file_exists "${lc}"
  check_file_exists "${ex}"

  if [[ -f "${df}" ]]; then
    check_pattern "${df}" "^USER[[:space:]]+appuser" "BYOC Dockerfile enforces non-root USER appuser"
    check_pattern "${df}" "^WORKDIR[[:space:]]+/workspace" "BYOC Dockerfile sets WORKDIR /workspace"
    check_pattern "${df}" "^EXPOSE[[:space:]]+8080" "BYOC Dockerfile exposes port 8080"
    check_pattern "${df}" "RUN.*[[:space:]]chmod[[:space:]]+0?644[[:space:]]+/opt/sandbox_runner/runner\.py" "BYOC Dockerfile sets runner.py permissions with Cloud Build legacy-compatible RUN chmod 0644"
    if grep -Ev '^[[:space:]]*#' "${df}" | grep -Eq -- '--chmod='; then
      fail "BYOC Dockerfile uses BuildKit-only --chmod= flag (fails under default Cloud Build legacy builder); use RUN chmod 0644 instead (${df})"
    else
      pass "BYOC Dockerfile avoids BuildKit-only --chmod= flag (${df})"
    fi
    check_dockerfile_non_root "${df}" "BYOC Sandbox Dockerfile"
  fi

  check_py_compile "${runner}"
  check_pattern "${runner}" '"/bin/bash",[[:space:]]*"-c"' "Sandbox runner invokes non-login /bin/bash -c to preserve PATH"
  check_py_compile "${lc}"
  check_py_compile "${ex}"

  check_no_todo_markers "${lc}" "lab-2"
  check_no_todo_markers "${ex}" "lab-2"
  check_no_todo_markers "${ag}" "lab-2"

  check_pattern "${lc}" "v1beta1" "SandboxLifecycleManager uses api_version v1beta1"
  check_pattern "${lc}" "sandbox_environment_template" "Supports reusable SandboxEnvironmentTemplate"
  check_pattern "${ex}" "EnvironmentScope\.SESSION" "AgentPlatformSandboxEnvironment uses EnvironmentScope.SESSION"
  check_pattern "${ex}" "ctx:.*Context.*None = None" "BaseEnvironment hooks declare keyword-only ctx parameter"
  check_pattern "${ex}" "AgentEngineSandboxCodeExecutor" "Wires ADK AgentEngineSandboxCodeExecutor"
  check_pattern "${ex}" "execute_bash" "Supports Managed Shell Sandbox execute_bash()"
  check_pattern "${ex}" "_infer_parent_instance\(" "Resolves BYOC template parent ReasoningEngine via _infer_parent_instance()"

  # Regression check: agent.py must gate sandbox_template_name on sandbox_mode == "byoc"
  # so Lab 2's BYOC template in .env is never forwarded into SANDBOX_MODE=shell.
  if [[ -f "${ag}" ]]; then
    if python3 - "${ag}" <<'PYEOF'
import ast
import sys
from pathlib import Path

tree = ast.parse(Path(sys.argv[1]).read_text(encoding="utf-8"))


def is_byoc_mode_check(node: ast.AST) -> bool:
    for sub in ast.walk(node):
        if isinstance(sub, ast.Compare):
            src = ast.unparse(sub)
            if "sandbox_mode" in src and ('"byoc"' in src or "'byoc'" in src):
                return True
    return False


def has_template_name_attr(node: ast.AST) -> bool:
    for sub in ast.walk(node):
        if isinstance(sub, ast.Attribute) and sub.attr == "sandbox_template_name":
            return True
    return False


found_call = False
all_gated = True
for fn in ast.walk(tree):
    if not isinstance(fn, (ast.FunctionDef, ast.AsyncFunctionDef)):
        continue
    gated_vars: set[str] = set()
    for stmt in ast.walk(fn):
        if isinstance(stmt, ast.Assign):
            val = stmt.value
            if (
                isinstance(val, ast.IfExp)
                and is_byoc_mode_check(val.test)
                and has_template_name_attr(val.body)
                and not has_template_name_attr(val.orelse)
            ):
                for tgt in stmt.targets:
                    if isinstance(tgt, ast.Name):
                        gated_vars.add(tgt.id)
        elif isinstance(stmt, ast.If) and is_byoc_mode_check(stmt.test):
            for body_node in stmt.body:
                if isinstance(body_node, ast.Assign) and has_template_name_attr(body_node.value):
                    for tgt in body_node.targets:
                        if isinstance(tgt, ast.Name):
                            gated_vars.add(tgt.id)

    for call in ast.walk(fn):
        if not isinstance(call, ast.Call):
            continue
        func_name = (
            call.func.id
            if isinstance(call.func, ast.Name)
            else getattr(call.func, "attr", "")
        )
        if func_name != "AgentPlatformSandboxEnvironment":
            continue
        found_call = True
        kw_map = {kw.arg: kw.value for kw in call.keywords if kw.arg}
        tpl_val = kw_map.get("template_name")
        if tpl_val is None:
            all_gated = False
            continue
        if (
            isinstance(tpl_val, ast.IfExp)
            and is_byoc_mode_check(tpl_val.test)
            and has_template_name_attr(tpl_val.body)
            and not has_template_name_attr(tpl_val.orelse)
        ):
            continue
        if isinstance(tpl_val, ast.Name) and tpl_val.id in gated_vars:
            continue
        all_gated = False

if not (found_call and all_gated):
    sys.exit(1)
PYEOF
    then
      pass "agent.py gates sandbox_template_name forwarding strictly on sandbox_mode == \"byoc\" (${ag})"
    else
      fail "${ag} must gate AgentPlatformSandboxEnvironment(template_name=...) on sandbox_mode == \"byoc\" so BYOC templates are never forwarded in shell mode"
    fi
  fi

  # Regression check: sandbox_execution.py must never send both inline spec and template_name simultaneously
  if [[ -f "${ex}" ]]; then
    if python3 - "${ex}" <<'PYEOF'
import ast
import sys
from pathlib import Path

tree = ast.parse(Path(sys.argv[1]).read_text(encoding="utf-8"))


def is_self_template_ref(node: ast.AST) -> bool:
    return (
        isinstance(node, ast.Attribute)
        and isinstance(node.value, ast.Name)
        and node.value.id == "self"
        and node.attr == "_template_name"
    )


def is_none_const(node: ast.AST) -> bool:
    return isinstance(node, ast.Constant) and node.value is None


def expr_guards_spec_when_template_set(node: ast.AST) -> bool:
    if isinstance(node, ast.IfExp):
        test_src = ast.unparse(node.test)
        if is_self_template_ref(node.test) and is_none_const(node.body):
            return True
        if (
            "self._template_name" in test_src
            and (test_src.startswith("not ") or "is None" in test_src)
            and is_none_const(node.orelse)
        ):
            return True
    return False


init_fn = None
for cls in ast.walk(tree):
    if isinstance(cls, ast.ClassDef) and cls.name == "AgentPlatformSandboxEnvironment":
        for item in cls.body:
            if (
                isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef))
                and item.name == "initialize"
            ):
                init_fn = item
                break

if init_fn is None:
    sys.exit(1)

guarded_spec_vars: set[str] = set()
for node in ast.walk(init_fn):
    if isinstance(node, ast.Assign):
        if expr_guards_spec_when_template_set(node.value):
            for tgt in node.targets:
                if isinstance(tgt, ast.Name):
                    guarded_spec_vars.add(tgt.id)
    elif isinstance(node, ast.AnnAssign) and node.value is not None:
        if expr_guards_spec_when_template_set(node.value) and isinstance(node.target, ast.Name):
            guarded_spec_vars.add(node.target.id)
    elif isinstance(node, ast.If):
        test_src = ast.unparse(node.test)
        if "self._template_name" in test_src and (
            test_src.startswith("not ") or "is None" in test_src
        ):
            for sub in node.body:
                if isinstance(sub, ast.Assign):
                    for tgt in sub.targets:
                        if isinstance(tgt, ast.Name):
                            guarded_spec_vars.add(tgt.id)

found_create = False
all_safe = True
for call in ast.walk(init_fn):
    if not isinstance(call, ast.Call):
        continue
    if isinstance(call.func, ast.Attribute) and call.func.attr == "create_sandbox":
        found_create = True
        kw_map = {kw.arg: kw.value for kw in call.keywords if kw.arg}
        tpl_arg = kw_map.get("template_name")
        spec_arg = kw_map.get("spec")
        if spec_arg is None or is_none_const(spec_arg):
            continue
        if tpl_arg is None or is_none_const(tpl_arg):
            continue
        if expr_guards_spec_when_template_set(spec_arg):
            continue
        if isinstance(spec_arg, ast.Name) and spec_arg.id in guarded_spec_vars:
            continue
        all_safe = False

if not (found_create and all_safe):
    sys.exit(1)
PYEOF
    then
      pass "sandbox_execution.py guards inline spec so spec and template_name are never sent simultaneously (${ex})"
    else
      fail "${ex} must set spec=None whenever self._template_name is set so inline spec never collides with template_name"
    fi
  fi
}

# -----------------------------------------------------------------------------
# Lab 3: Managed Sessions, Memory Bank, Feedback & Telemetry
# -----------------------------------------------------------------------------
verify_lab_3() {
  section "Lab 3 Verification (${TRACK}/ — Sessions, Memory Bank, Feedback & Telemetry)"
  local sess="${TRACK}/coding_agent/memory/session_manager.py"
  local mem="${TRACK}/coding_agent/memory/memory_bank_manager.py"
  local cb="${TRACK}/coding_agent/callbacks/telemetry_and_feedback.py"
  local ag="${TRACK}/coding_agent/agent.py"

  check_file_exists "${sess}"
  check_file_exists "${mem}"
  check_file_exists "${cb}"

  check_py_compile "${sess}"
  check_py_compile "${mem}"
  check_py_compile "${cb}"

  check_no_todo_markers "${sess}" "lab-3"
  check_no_todo_markers "${mem}" "lab-3"
  check_no_todo_markers "${cb}" "lab-3"
  check_no_todo_markers "${ag}" "lab-3"

  check_pattern "${sess}" "VertexAiSessionService" "Wires ADK VertexAiSessionService"
  check_pattern "${mem}" "VertexAiMemoryBankService" "Wires ADK VertexAiMemoryBankService"
  check_pattern "${mem}" "sanitize_for_memory_ingestion" "Includes prompt-injection sanitizer before Memory Bank ingestion"
  check_pattern "${mem}" "granular_ttl_config" "Memory Bank TTL config uses SDK 2.10+ granular_ttl_config field"
  check_pattern "${cb}" "aiplatform\.googleapis\.com/ReasoningEngine" "Logs parent runtime sandbox output to ReasoningEngine resource"
  check_pattern "${cb}" "feedback_entries" "Implements Feedback Service client"

  # Regression check: memory_bank_manager.py must emit `granular_ttl_config` (not legacy `granular_ttl` dict key)
  if [[ -f "${mem}" ]]; then
    if python3 - "${mem}" <<'PYEOF'
import ast
import sys
from pathlib import Path

tree = ast.parse(Path(sys.argv[1]).read_text(encoding="utf-8"))
has_granular_ttl_config = False
for node in ast.walk(tree):
    if isinstance(node, ast.Dict):
        for key in node.keys:
            if isinstance(key, ast.Constant) and isinstance(key.value, str):
                if key.value == "granular_ttl":
                    sys.exit(1)
                if key.value == "granular_ttl_config":
                    has_granular_ttl_config = True

if not has_granular_ttl_config:
    sys.exit(1)
PYEOF
    then
      pass "memory_bank_manager.py uses granular_ttl_config dict key (zero legacy granular_ttl keys) (${mem})"
    else
      fail "${mem} must use 'granular_ttl_config' (not legacy 'granular_ttl') inside ttl_config dicts for agentplatform 2.10+"
    fi
  fi

  # Regression check: feedback_entries.list() must use parent= (not name=)
  if [[ -f "${cb}" ]]; then
    if python3 - "${cb}" <<'PYEOF'
import ast
import sys
from pathlib import Path

tree = ast.parse(Path(sys.argv[1]).read_text(encoding="utf-8"))
found_list = False
for node in ast.walk(tree):
    if (
        isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and node.func.attr == "list"
        and isinstance(node.func.value, ast.Attribute)
        and node.func.value.attr == "feedback_entries"
    ):
        found_list = True
        kw_names = {kw.arg for kw in node.keywords if kw.arg}
        if "name" in kw_names or "parent" not in kw_names:
            sys.exit(1)

if not found_list:
    sys.exit(1)
PYEOF
    then
      pass "telemetry_and_feedback.py calls feedback_entries.list(parent=...) (not name=) (${cb})"
    else
      fail "${cb} must call client.feedback_entries.list(parent=...) rather than name= for agentplatform 2.10+"
    fi
  fi

  # Regression check: sessions.get() must NOT pass unsupported user_id= (and sessions.create() must not pass top-level session_id=)
  if [[ -f "${sess}" ]]; then
    if python3 - "${sess}" <<'PYEOF'
import ast
import sys
from pathlib import Path

tree = ast.parse(Path(sys.argv[1]).read_text(encoding="utf-8"))
found_get = False
for node in ast.walk(tree):
    if (
        isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and isinstance(node.func.value, ast.Attribute)
        and node.func.value.attr == "sessions"
    ):
        kw_names = {kw.arg for kw in node.keywords if kw.arg}
        if node.func.attr == "get":
            found_get = True
            if "user_id" in kw_names:
                sys.exit(1)
        elif node.func.attr == "create":
            if "session_id" in kw_names:
                sys.exit(1)

if not found_get:
    sys.exit(1)
PYEOF
    then
      pass "session_manager.py calls sessions.get(name=...) without unsupported user_id= (${sess})"
    else
      fail "${sess} must NOT pass user_id= to client.sessions.get() or top-level session_id= to client.sessions.create()"
    fi
  fi
}

# -----------------------------------------------------------------------------
# Lab 4: Skill Registry & Agent Registry Discovery
# -----------------------------------------------------------------------------
verify_lab_4() {
  section "Lab 4 Verification (${TRACK}/ — Skill Registry & Agent Registry Discovery)"
  local reg="${TRACK}/coding_agent/tools/registry_loader.py"
  local ag="${TRACK}/coding_agent/agent.py"
  local skill_dir="${TRACK}/skills_to_register/secure-code-review"

  check_file_exists "${reg}"
  check_file_exists "${skill_dir}/SKILL.md"
  check_file_exists "scripts/package_registry_skill.py"

  check_py_compile "${reg}"
  check_no_todo_markers "${reg}" "lab-4"
  check_no_todo_markers "${ag}" "lab-4"

  check_pattern "${reg}" "GCPSkillRegistry" "Integrates ADK GCPSkillRegistry"
  check_pattern "${reg}" "SkillToolset" "Integrates ADK SkillToolset"
  check_pattern "${reg}" "AgentRegistry" "Integrates ADK AgentRegistry"
  check_pattern "${reg}" "GcpAuthProvider" "Registers Agent Identity GcpAuthProvider"
  check_pattern "${reg}" "X-Goog-User-Project" "Implements GoogleApiAuth with X-Goog-User-Project header"
  check_pattern "${reg}" "is_dir\(\)" "Enforces directory-only local_path (is_dir()) for Vertex AI Skill Registry"
  check_pattern ".env.example" "^AGENT_REGISTRY_SKILLS_LOCATION=global$" ".env.example configures AGENT_REGISTRY_SKILLS_LOCATION=global for standalone skills"
  check_pattern "${TRACK}/coding_agent/config.py" "AGENT_REGISTRY_SKILLS_LOCATION" "config.py reads AGENT_REGISTRY_SKILLS_LOCATION for standalone skills"
  if ! has_todo_markers "${ag}" "lab-4"; then
    if grep -Eq "agent_registry_skills_location|AGENT_REGISTRY_SKILLS_LOCATION" "${ag}" "${reg}"; then
      pass "Lab 4 skill registry wiring uses AGENT_REGISTRY_SKILLS_LOCATION / agent_registry_skills_location"
    else
      fail "Lab 4 skill registry wiring in ${ag} / ${reg} must use agent_registry_skills_location (default global)"
    fi
  fi

  if [[ -d "${skill_dir}" ]]; then
    if python3 scripts/package_registry_skill.py "${skill_dir}" --dry-run >/dev/null 2>&1; then
      pass "${skill_dir} passed all 16 atomic Skill Registry validation checks (--dry-run)"
    else
      fail "${skill_dir} failed scripts/package_registry_skill.py --dry-run"
    fi
  fi

  # Regression check: reject invalid `--scanning-policy=enabled-non-<extra-hyphen>blocking` typo across repo
  if python3 - <<'PYEOF'
import sys
from pathlib import Path

bad_flag = "--scanning-policy=enabled-non-" + "blocking"
roots = [Path("workshop"), Path(".agents/skills"), Path("starter"), Path("solution"), Path("scripts")]
hits = []
for root in roots:
    if not root.exists():
        continue
    for path in root.rglob("*"):
        if not path.is_file() or ".venv" in path.parts or "__pycache__" in path.parts:
            continue
        try:
            text = path.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            continue
        if bad_flag in text:
            hits.append(str(path))
if hits:
    print("Found invalid flag spelling in:", ", ".join(hits), file=sys.stderr)
    sys.exit(1)
PYEOF
  then
    pass "Zero invalid Agent Registry --scanning-policy flag typos across workshop, skills, code, and scripts"
  else
    fail "Found invalid '--scanning-policy=enabled-non-'+'blocking' typo; valid gcloud flag is '--scanning-policy=enabled-nonblocking'"
  fi

  # Regression check: governance Antigravity skills must pass AGENT_REGISTRY_SKILLS_LOCATION / global to GCPSkillRegistry
  if python3 - <<'PYEOF'
import re
import sys
from pathlib import Path

gov_dir = Path(".agents/skills/agent-platform-governance-and-registries")
bad = []
if gov_dir.exists():
    for path in gov_dir.rglob("*.md"):
        text = path.read_text(encoding="utf-8")
        for m in re.finditer(r"GCPSkillRegistry\([^)]*\)", text, re.DOTALL):
            snippet = m.group(0)
            if "AGENT_REGISTRY_LOCATION" in snippet or "asia-southeast3" in snippet or "location=registry_location" in snippet:
                bad.append(f"{path}: {snippet}")
if bad:
    print("Stale regional GCPSkillRegistry snippet(s):", "\n".join(bad), file=sys.stderr)
    sys.exit(1)
PYEOF
  then
    pass "Governance Antigravity skills decouple GCPSkillRegistry location to AGENT_REGISTRY_SKILLS_LOCATION (global)"
  else
    fail "Governance Antigravity skills must pass AGENT_REGISTRY_SKILLS_LOCATION ('global') to GCPSkillRegistry(...), not AGENT_REGISTRY_LOCATION / asia-southeast3"
  fi
}

# -----------------------------------------------------------------------------
# Lab 5: Deploy & Manage Complete Coding Agent on Agent Runtime + Terraform IaC
# -----------------------------------------------------------------------------
verify_lab_5() {
  section "Lab 5 Verification (${TRACK}/ — Agent Runtime & Terraform IaC)"
  local tf_dir="${TRACK}/terraform"
  local main_tf="${tf_dir}/main.tf"
  local vars_tf="${tf_dir}/variables.tf"
  local outputs_tf="${tf_dir}/outputs.tf"
  local versions_tf="${tf_dir}/versions.tf"
  local tfvars_example="${tf_dir}/terraform.tfvars.example"
  local runtime_df="${TRACK}/Dockerfile"
  local runtime_main="${TRACK}/main.py"
  local runtime_reqs="${TRACK}/requirements.txt"
  local manifest="${TRACK}/agents-cli-manifest.yaml"
  local gcloudignore="${TRACK}/.gcloudignore"
  local dockerignore="${TRACK}/.dockerignore"

  check_file_exists "${runtime_df}"
  check_file_exists "${runtime_main}"
  check_file_exists "${runtime_reqs}"
  check_file_exists "${manifest}"
  check_file_exists "${gcloudignore}"
  check_file_exists "${dockerignore}"
  check_file_exists "${versions_tf}"
  check_file_exists "${vars_tf}"
  check_file_exists "${main_tf}"
  check_file_exists "${outputs_tf}"
  check_file_exists "${tfvars_example}"

  # Regression check: .gcloudignore and .dockerignore must exclude .venv/, caches,
  # secrets (.env, *.tfvars*, *.tfstate*), terraform/, artifacts/, and *.tar.gz
  # while preserving all Agent Runtime build & manifest assets.
  if [[ -f "${gcloudignore}" && -f "${dockerignore}" ]]; then
    if python3 - "${gcloudignore}" "${dockerignore}" <<'PYEOF'
import fnmatch
import os
import re
import sys
from pathlib import Path

gcloud_path = Path(sys.argv[1])
docker_path = Path(sys.argv[2])


def load_patterns(path: Path) -> list[str]:
    return [
        line.strip()
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip() and not line.lstrip().startswith("#")
    ]


def gcloud_matches_pattern(pat: str, relpath: str, is_dir: bool) -> bool:
    must_be_dir = pat.endswith("/")
    if must_be_dir:
        if not is_dir:
            return False
        pat = pat[:-1]
    if pat.startswith("/"):
        pat = pat[1:]
        return fnmatch.fnmatchcase(relpath, pat)
    if "/" not in pat:
        return fnmatch.fnmatchcase(os.path.basename(relpath), pat)
    # Handle **/ prefix or nested slash patterns
    if pat.startswith("**/"):
        sub = pat[3:]
        parts = relpath.split("/")
        return any(fnmatch.fnmatchcase("/".join(parts[i:]), sub) for i in range(len(parts)))
    return fnmatch.fnmatchcase(relpath, pat)


def gcloud_excluded(patterns: list[str], relpath: str, is_dir: bool = False) -> bool:
    parts = relpath.split("/")
    prefixes = ["/".join(parts[:i]) for i in range(1, len(parts) + 1)]
    for idx, prefix in enumerate(prefixes):
        prefix_is_dir = (idx < len(prefixes) - 1) or is_dir
        ignored = False
        for raw in patterns:
            neg = raw.startswith("!")
            pat = raw[1:] if neg else raw
            if gcloud_matches_pattern(pat, prefix, prefix_is_dir):
                ignored = not neg
        if ignored:
            return True
    return False


def compile_docker(raw: str):
    neg = raw.startswith("!")
    p = os.path.normpath(raw[1:] if neg else raw)
    reg = "^"
    i = 0
    while i < len(p):
        ch = p[i]
        if ch == "*":
            if i + 1 < len(p) and p[i + 1] == "*":
                i += 2
                if i < len(p) and p[i] == "/":
                    i += 1
                reg += ".*" if i == len(p) else "(.*/)?"
                continue
            reg += "[^/]*"
        elif ch == "?":
            reg += "[^/]"
        elif ch in ".+()|{}$":
            reg += "\\" + ch
        else:
            reg += ch
        i += 1
    reg += "$"
    return re.compile(reg), neg


def docker_excluded(compiled, relpath: str) -> bool:
    relpath = os.path.normpath(relpath)
    parts = relpath.split("/")
    prefixes = ["/".join(parts[:i]) for i in range(1, len(parts) + 1)]
    matched = False
    for rx, neg in compiled:
        if neg != matched:
            continue
        if any(rx.match(pref) for pref in prefixes):
            matched = not neg
    return matched


g_pats = load_patterns(gcloud_path)
d_pats = [compile_docker(p) for p in load_patterns(docker_path)]

must_exclude = [
    (".venv/lib/python3.11/site-packages/pkg.py", False),
    ("venv/bin/python", False),
    ("coding_agent/__pycache__/agent.cpython-311.pyc", False),
    ("coding_agent/agent.pyc", False),
    ("coding_agent/agent.pyo", False),
    ("coding_agent/agent.pyd", False),
    (".pytest_cache/README.md", False),
    (".ruff_cache/CACHEDIR.TAG", False),
    (".env", False),
    (".env.local", False),
    ("terraform/.terraform/providers/registry", False),
    ("terraform/terraform.tfvars", False),
    ("terraform/terraform.tfstate", False),
    ("terraform/coding_agent_source.tar.gz", False),
    ("artifacts/eval_report.json", False),
    ("bundle.tar.gz", False),
    ("local.tfstate.backup", False),
    ("local.tfvars.json", False),
]
must_preserve = [
    "Dockerfile",
    "main.py",
    "requirements.txt",
    "pyproject.toml",
    "agents-cli-manifest.yaml",
    "services.py",
    "services.yaml",
    "coding_agent/agent.py",
    "skills_to_register/secure-code-review/SKILL.md",
]

for path_str, is_dir in must_exclude:
    assert gcloud_excluded(g_pats, path_str, is_dir=is_dir), f".gcloudignore failed to exclude {path_str}"
    assert docker_excluded(d_pats, path_str), f".dockerignore failed to exclude {path_str}"

for path_str in must_preserve:
    assert not gcloud_excluded(g_pats, path_str, is_dir=False), f".gcloudignore excluded {path_str}"
    assert not docker_excluded(d_pats, path_str), f".dockerignore excluded {path_str}"
PYEOF
    then
      pass ".gcloudignore and .dockerignore exclude .venv/, caches, secrets, terraform/, artifacts/, and archives while preserving runtime assets (${TRACK}/)"
    else
      fail "${TRACK}/.gcloudignore or ${TRACK}/.dockerignore failed exclusion/preservation checks"
    fi
  fi

  if [[ -f "${runtime_df}" ]]; then
    check_dockerfile_non_root "${runtime_df}" "Agent Runtime BYOC Dockerfile"
    check_pattern "${runtime_df}" "^EXPOSE[[:space:]]+8080" "Agent Runtime Dockerfile exposes port 8080"
    check_pattern "${runtime_df}" "uvicorn" "Agent Runtime Dockerfile launches uvicorn"
    check_pattern "${runtime_df}" '^COPY[[:space:]]+.*skills_to_register/[[:space:]]+\./skills_to_register/' "Agent Runtime Dockerfile packages skills_to_register/ for Lab 4 local fallback"
    check_pattern "${runtime_df}" 'Dockerfile[[:space:]]+main\.py[[:space:]]+requirements\.txt[[:space:]]+coding_agent/[[:space:]]+skills_to_register/' "Agent Runtime Dockerfile source_code_spec tar example includes skills_to_register/"
  fi

  check_py_compile "${runtime_main}"
  check_no_todo_markers "${runtime_main}" "lab-5"
  check_pattern "${runtime_main}" "/api/reasoning_engine" "Agent Runtime server defines POST /api/reasoning_engine"
  check_pattern "${runtime_main}" "/api/stream_reasoning_engine" "Agent Runtime server defines POST /api/stream_reasoning_engine"

  # Regression check: FastAPI 0.163+ strict content-type parsing rejects raw JSON `:query` proxy
  # payloads when endpoints declare `request: QueryRequest`; endpoints must accept `Request` and
  # parse raw JSON body explicitly.
  if [[ -f "${runtime_main}" ]]; then
    if python3 - "${runtime_main}" <<'PYEOF'
import ast
import sys
from pathlib import Path

source = Path(sys.argv[1]).read_text(encoding="utf-8")
tree = ast.parse(source)
has_todo = "TODO(lab-5)" in source

endpoints: dict[str, ast.FunctionDef | ast.AsyncFunctionDef] = {}
for node in tree.body:
    if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name in {
        "query_endpoint",
        "stream_query_endpoint",
    }:
        endpoints[node.name] = node

if len(endpoints) != 2:
    sys.exit(1)

for fn in endpoints.values():
    params = fn.args.args + fn.args.kwonlyargs
    has_request_param = False
    for arg in params:
        ann = ast.unparse(arg.annotation) if arg.annotation is not None else ""
        if "QueryRequest" in ann:
            sys.exit(1)
        if ann == "Request" or ann.endswith(".Request"):
            has_request_param = True
    if not has_request_param:
        sys.exit(1)

if not has_todo:
    has_raw_parse = any(
        isinstance(n, ast.Call)
        and isinstance(n.func, ast.Attribute)
        and n.func.attr in {"body", "json"}
        for n in ast.walk(tree)
    )
    if not has_raw_parse:
        sys.exit(1)
PYEOF
    then
      pass "main.py accepts FastAPI Request and parses raw JSON bodies (FastAPI 0.163+ :query proxy safe) (${runtime_main})"
    else
      fail "${runtime_main} must declare query_endpoint/stream_query_endpoint with FastAPI Request (not QueryRequest) and parse raw JSON body explicitly"
    fi
  fi

  check_no_todo_markers "${main_tf}" "lab-5"

  check_pattern "${versions_tf}" 'version[[:space:]]*=[[:space:]]*">= 6\.0\.0"' "Terraform provider floor >= 6.0.0 for container_spec support"
  check_pattern "${vars_tf}" 'variable "enable_memory_bank"' "Declares optional enable_memory_bank variable with safe default"
  check_pattern "${vars_tf}" 'variable "enable_skill_registry"' "Declares optional enable_skill_registry variable with safe default"
  check_pattern "${vars_tf}" 'variable "skill_registry_location"' "Declares optional skill_registry_location variable with safe default"
  check_pattern "${tfvars_example}" '^enable_memory_bank[[:space:]]*=[[:space:]]*false' "terraform.tfvars.example declares enable_memory_bank = false"
  check_pattern "${tfvars_example}" '^enable_skill_registry[[:space:]]*=[[:space:]]*false' "terraform.tfvars.example declares enable_skill_registry = false"
  check_pattern "${tfvars_example}" '^skill_registry_location[[:space:]]*=[[:space:]]*"us-central1"' "terraform.tfvars.example declares skill_registry_location"
  check_pattern "${main_tf}" 'resource "google_vertex_ai_reasoning_engine"' "Declares google_vertex_ai_reasoning_engine"
  check_pattern "${main_tf}" "region[[:space:]]*=[[:space:]]*var\.location" "Uses verified Terraform attribute 'region = var.location'"
  if [[ -f "${main_tf}" ]]; then
    if python3 - "${main_tf}" <<'PYEOF'
import re
import sys
from pathlib import Path

raw = Path(sys.argv[1]).read_text(encoding="utf-8")
in_re_block = False
depth = 0
found_force = False

for raw_line in raw.splitlines():
    stripped = raw_line.lstrip()
    if stripped.startswith(("#", "//")):
        continue
    no_strings = re.sub(r'"(?:\\.|[^"\\])*"', '""', raw_line)
    no_comments = re.sub(r"(?:#|//).*$", "", no_strings)

    if not in_re_block:
        if re.match(r'\s*resource\s+"google_vertex_ai_reasoning_engine"\s+"[^"]+"\s*\{', raw_line):
            in_re_block = True
            depth = no_comments.count("{") - no_comments.count("}")
            if depth <= 0:
                in_re_block = False
        continue

    if depth == 1 and re.match(r'\s*deletion_policy\s*=\s*"FORCE"\s*(?:(?:#|//).*)?$', raw_line):
        found_force = True

    depth += no_comments.count("{") - no_comments.count("}")
    if depth <= 0:
        in_re_block = False

sys.exit(0 if found_force else 1)
PYEOF
    then
      pass "main.tf declares deletion_policy = \"FORCE\" on google_vertex_ai_reasoning_engine (${main_tf})"
    else
      fail "${main_tf} must declare deletion_policy = \"FORCE\" on google_vertex_ai_reasoning_engine so terraform destroy cleans up live sessions"
    fi
  fi
  check_pattern "${main_tf}" 'Dockerfile[[:space:]]+main\.py[[:space:]]+requirements\.txt[[:space:]]+coding_agent/[[:space:]]+skills_to_register/' "Terraform source_code_spec tar example includes skills_to_register/"
  check_pattern "${main_tf}" "SANDBOX_MODE" "Injects SANDBOX_MODE env var in Agent Runtime deployment_spec"
  check_pattern "${main_tf}" 'dynamic[[:space:]]+"env"' "Uses dynamic \"env\" block to omit empty SANDBOX_TEMPLATE_NAME"
  if [[ -f "${main_tf}" ]] && ! has_todo_markers "${main_tf}" "lab-5"; then
    if python3 - "${main_tf}" <<'PYEOF'
import re
import sys
from pathlib import Path

raw = Path(sys.argv[1]).read_text(encoding="utf-8")
code = "\n".join(
    line for line in raw.splitlines() if not line.lstrip().startswith(("#", "//"))
)

# Reject unconditional static env { name = "SANDBOX_TEMPLATE_NAME" ... }
if re.search(
    r'(?<!dynamic\s)\benv\s*\{[^{}]*name\s*=\s*"SANDBOX_TEMPLATE_NAME"',
    code,
    flags=re.DOTALL,
):
    sys.exit(1)

# Require dynamic "env" block containing SANDBOX_TEMPLATE_NAME gated on var.sandbox_template_name
if not re.search(
    r'dynamic\s+"env"\s*\{[^}]*sandbox_template_name[^}]*content\s*\{[^}]*"SANDBOX_TEMPLATE_NAME"',
    code,
    flags=re.DOTALL,
):
    sys.exit(1)
PYEOF
    then
      pass "main.tf gates SANDBOX_TEMPLATE_NAME inside dynamic \"env\" block (prevents HTTP 400 on empty value) (${main_tf})"
    else
      fail "${main_tf} must emit SANDBOX_TEMPLATE_NAME via a dynamic \"env\" block gated on var.sandbox_template_name (not an unconditional static env block)"
    fi
  fi
  check_pattern "${main_tf}" "roles/aiplatform\.memoryUser" "Grants roles/aiplatform.memoryUser for Lab 3 Memory Bank access"
  check_pattern "${main_tf}" 'resource "google_project_iam_member" "runtime_sa_agentregistry_viewer"' "Declares conditional runtime_sa_agentregistry_viewer IAM binding for Lab 4 Skill Registry"
  check_pattern "${main_tf}" 'roles/agentregistry\.viewer' "Grants conditional roles/agentregistry.viewer when enable_skill_registry is true"
  check_pattern "${main_tf}" 'google_project_iam_member\.runtime_sa_agentregistry_viewer' "Wires runtime_sa_agentregistry_viewer into reasoning engine depends_on"
  check_pattern "${main_tf}" "ENABLE_MEMORY_BANK" "Injects ENABLE_MEMORY_BANK env var in Agent Runtime deployment_spec"
  check_pattern "${main_tf}" "ENABLE_SKILL_REGISTRY" "Injects ENABLE_SKILL_REGISTRY env var in Agent Runtime deployment_spec"
  check_pattern "${main_tf}" "SKILL_REGISTRY_LOCATION" "Injects SKILL_REGISTRY_LOCATION env var in Agent Runtime deployment_spec"
  check_pattern "${main_tf}" "AGENT_REGISTRY_LOCATION" "Injects AGENT_REGISTRY_LOCATION env var in Agent Runtime deployment_spec"
  check_pattern "${main_tf}" "roles/telemetry\.tracesWriter" "Grants roles/telemetry.tracesWriter for OTel telemetry.googleapis.com export"
  check_pattern "${main_tf}" "roles/iam\.serviceAccountTokenCreator" "Grants self serviceAccountTokenCreator for BYOC generate_access_token()"
  check_pattern "${main_tf}" "gcp-sa-aiplatform\.iam\.gserviceaccount\.com" "Grants Secret Manager access to Agent Platform SA (gcp-sa-aiplatform)"
  check_pattern "${main_tf}" "gcp-sa-aiplatform-re\.iam\.gserviceaccount\.com" "Grants Artifact Registry access to Agent Runtime SA (gcp-sa-aiplatform-re)"
  check_pattern "${main_tf}" "gcp-sa-vertex-sandbox\.iam\.gserviceaccount\.com" "Grants Artifact Registry access to Agent Sandbox SA (gcp-sa-vertex-sandbox)"
  check_pattern "${main_tf}" "depends_on[[:space:]]*=" "Orders IAM bindings with depends_on to prevent IMAGE_PULL_BACKOFF"
  check_pattern "${outputs_tf}" 'output "reasoning_engine_resource_name"' "Exports canonical reasoning_engine_resource_name"
  check_pattern "${outputs_tf}" 'output "reasoning_engine_id"' "Exports short numeric reasoning_engine_id"
  check_pattern "${outputs_tf}" "reverse\(split\(" "Extracts trailing numeric ID safely with reverse(split(...))[0]"

  # Reject Terraform's invalid negative-index `element(..., -1)` bug in outputs.tf
  if [[ -f "${outputs_tf}" ]]; then
    if python3 - "${outputs_tf}" <<'PYEOF'
import re
import sys
from pathlib import Path

text = Path(sys.argv[1]).read_text(encoding="utf-8")
# Strip HCL line comments before scanning expressions
code_only = "\n".join(
    line for line in text.splitlines() if not line.lstrip().startswith(("#", "//"))
)
if re.search(r"\belement\s*\([^)]*,\s*-\d+", code_only, flags=re.DOTALL):
    sys.exit(1)
PYEOF
    then
      pass "outputs.tf avoids invalid negative-index element(..., -1) HCL expression"
    else
      fail "outputs.tf uses invalid negative index with Terraform element(..., -1); use reverse(split(...))[0]"
    fi
  fi

  if command -v terraform >/dev/null 2>&1; then
    if [[ -d "${tf_dir}" ]]; then
      if terraform -chdir="${tf_dir}" fmt -check >/dev/null 2>&1; then
        pass "terraform fmt -check passed in ${tf_dir}"
      else
        fail "terraform fmt -check failed in ${tf_dir} (run: terraform -chdir=${tf_dir} fmt)"
      fi
    fi
  else
    warn "terraform binary not found on PATH; skipping terraform fmt -check."
  fi
}

# -----------------------------------------------------------------------------
# Lab 6: Optimize, Eval, Online Monitors, Quality Alerts & Prompt Tuning
# -----------------------------------------------------------------------------
verify_lab_6() {
  section "Lab 6 Verification (${TRACK}/ — Optimize, Eval, Alerts & Prompt Tuning)"
  local eval_dir="${TRACK}/eval"
  local scripts_list=(
    "${eval_dir}/run_offline_eval.py"
    "${eval_dir}/run_simulated_eval.py"
    "${eval_dir}/setup_online_monitor.py"
    "${eval_dir}/setup_quality_alerts.py"
    "${eval_dir}/optimize_prompt.py"
  )

  check_file_exists "${eval_dir}/datasets/coding_agent_eval.jsonl"
  check_file_exists "${eval_dir}/datasets/coding_agent_single_turn.json"
  check_file_exists "${eval_dir}/datasets/coding_agent_multi_turn.json"
  check_file_exists "${eval_dir}/eval_config.yaml"
  check_file_exists "${eval_dir}/sampler_config.json"
  check_file_exists "${TRACK}/coding_agent/train_eval_set.evalset.json"

  # Validate dataset integrity & strict single-turn / multi-turn separation
  if python3 - "${eval_dir}" "${TRACK}/coding_agent/train_eval_set.evalset.json" <<'PYEOF'
import json
import sys
from pathlib import Path

eval_dir = Path(sys.argv[1])
evalset_path = Path(sys.argv[2])

jsonl_lines = [
    json.loads(line)
    for line in (eval_dir / "datasets/coding_agent_eval.jsonl").read_text(encoding="utf-8").splitlines()
    if line.strip()
]
assert len(jsonl_lines) == 8, f"Expected 8 JSONL eval cases, found {len(jsonl_lines)}"

single = json.loads((eval_dir / "datasets/coding_agent_single_turn.json").read_text(encoding="utf-8"))
assert isinstance(single.get("eval_cases"), list) and len(single["eval_cases"]) == 5
for case in single["eval_cases"]:
    assert "prompt" in case and "agent_data" not in case

multi = json.loads((eval_dir / "datasets/coding_agent_multi_turn.json").read_text(encoding="utf-8"))
assert isinstance(multi.get("eval_cases"), list) and len(multi["eval_cases"]) == 3
for case in multi["eval_cases"]:
    assert "agent_data" in case and "prompt" not in case

sampler = json.loads((eval_dir / "sampler_config.json").read_text(encoding="utf-8"))
assert sampler.get("app_name") == "coding_agent"
assert sampler.get("train_eval_set") == "train_eval_set"

evalset = json.loads(evalset_path.read_text(encoding="utf-8"))
assert evalset.get("eval_set_id") == "train_eval_set"
assert isinstance(evalset.get("eval_cases"), list) and len(evalset["eval_cases"]) >= 1
PYEOF
  then
    pass "Evaluation datasets (8 JSONL + 5 single-turn + 3 multi-turn + sampler/evalset) validated"
  else
    fail "Evaluation dataset schema validation failed in ${eval_dir}"
  fi

  local any_todo=0
  for script in "${scripts_list[@]}"; do
    check_file_exists "${script}"
    check_py_compile "${script}"
    check_no_todo_markers "${script}" "lab-6"
    if has_todo_markers "${script}" "lab-6"; then
      any_todo=1
    fi
  done

  check_pattern "${eval_dir}/run_offline_eval.py" 'location="global"' "Failure clustering enforces global region"
  check_pattern "${eval_dir}/run_offline_eval.py" "generate_loss_clusters" "Calls vertexai.evals generate_loss_clusters"
  check_pattern "${eval_dir}/run_offline_eval.py" 'SAFETY\(version="v1"\)' "Pins SAFETY(version=\"v1\") to prevent safety_v3 polarity inversion"
  check_pattern "${eval_dir}/run_simulated_eval.py" "generate_conversation_scenarios" "Implements Step 1 scenario generation"
  check_pattern "${eval_dir}/run_simulated_eval.py" "user_simulator_config" "Implements Step 2 multi-turn user simulation"
  check_pattern "${eval_dir}/setup_online_monitor.py" "EVENT_ONLY" "Validates ADK Python OTel capture enum (EVENT_ONLY)"
  check_pattern "${eval_dir}/setup_online_monitor.py" "verify_deployed_runtime" "Includes --verify-runtime helper verify_deployed_runtime()"
  check_pattern "${eval_dir}/setup_online_monitor.py" "google_cloud_location" "setup_online_monitor.py reads google_cloud_location for runtime region"
  check_pattern "${eval_dir}/setup_online_monitor.py" "eval_location" "setup_online_monitor.py tracks eval_location separately from runtime region"

  # Regression check: setup_online_monitor.py must decouple runtime region
  # (`settings.google_cloud_location`, e.g. asia-southeast1) from `eval_location`
  # (e.g. global) so --verify-runtime and target_agent_engine never query `global`.
  if [[ -f "${eval_dir}/setup_online_monitor.py" ]]; then
    if python3 - "${eval_dir}/setup_online_monitor.py" <<'PYEOF'
import ast
import sys
from pathlib import Path

tree = ast.parse(Path(sys.argv[1]).read_text(encoding="utf-8"))

main_fn = None
for node in tree.body:
    if isinstance(node, ast.FunctionDef) and node.name == "main":
        main_fn = node
        break

if main_fn is None:
    sys.exit(1)

runtime_loc_vars: set[str] = set()
eval_loc_vars: set[str] = set()
for stmt in ast.walk(main_fn):
    if isinstance(stmt, ast.Assign):
        val_src = ast.unparse(stmt.value)
        for tgt in stmt.targets:
            if not isinstance(tgt, ast.Name):
                continue
            if "google_cloud_location" in val_src:
                runtime_loc_vars.add(tgt.id)
            if "eval_location" in val_src or "EVAL_LOCATION" in val_src:
                eval_loc_vars.add(tgt.id)

if not runtime_loc_vars or not eval_loc_vars or (runtime_loc_vars & eval_loc_vars):
    sys.exit(1)

verified_runtime_call = False
verified_spec_call = False
for call in ast.walk(main_fn):
    if not isinstance(call, ast.Call):
        continue
    fn_name = call.func.id if isinstance(call.func, ast.Name) else getattr(call.func, "attr", "")
    if fn_name == "verify_deployed_runtime":
        # Location is positional arg #1 or keyword 'location'
        loc_arg = call.args[1] if len(call.args) >= 2 else next(
            (kw.value for kw in call.keywords if kw.arg == "location"), None
        )
        if isinstance(loc_arg, ast.Name) and loc_arg.id in runtime_loc_vars:
            verified_runtime_call = True
    elif fn_name == "build_online_monitor_spec":
        kw_map = {kw.arg: kw.value for kw in call.keywords if kw.arg}
        rt_arg = kw_map.get("runtime_location")
        ev_arg = kw_map.get("location")
        if (
            isinstance(rt_arg, ast.Name)
            and rt_arg.id in runtime_loc_vars
            and isinstance(ev_arg, ast.Name)
            and ev_arg.id in eval_loc_vars
        ):
            verified_spec_call = True

if not (verified_runtime_call and verified_spec_call):
    sys.exit(1)
PYEOF
    then
      pass "setup_online_monitor.py cleanly decouples google_cloud_location (runtime region) from eval_location (${eval_dir}/setup_online_monitor.py)"
    else
      fail "${eval_dir}/setup_online_monitor.py must decouple settings.google_cloud_location (runtime region) from eval_location when calling build_online_monitor_spec() and verify_deployed_runtime()"
    fi
  fi
  check_pattern "${eval_dir}/setup_quality_alerts.py" "monitoring_v3" "Uses google.cloud.monitoring_v3"
  check_pattern "${eval_dir}/setup_quality_alerts.py" "aiplatform\.googleapis\.com/online_evaluator/scores" "Targets verified online_evaluator/scores metric"
  check_pattern "${eval_dir}/setup_quality_alerts.py" "aiplatform\.googleapis\.com/OnlineEvaluator" "Alert filter restricts resource.type=\"aiplatform.googleapis.com/OnlineEvaluator\""
  check_pattern "${eval_dir}/setup_quality_alerts.py" "ALIGN_PERCENTILE_50" "Alert policy uses DISTRIBUTION-compatible ALIGN_PERCENTILE_50 aligner"

  # Regression check: Cloud Monitoring rejects ALIGN_MEAN on DELTA/DISTRIBUTION online_evaluator/scores
  if [[ -f "${eval_dir}/setup_quality_alerts.py" ]]; then
    if python3 - "${eval_dir}/setup_quality_alerts.py" <<'PYEOF'
import ast
import re
import sys
from pathlib import Path

tree = ast.parse(Path(sys.argv[1]).read_text(encoding="utf-8"))

docstring_nodes: set[int] = set()
for parent in ast.walk(tree):
    if isinstance(parent, (ast.Module, ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)):
        if (
            parent.body
            and isinstance(parent.body[0], ast.Expr)
            and isinstance(parent.body[0].value, ast.Constant)
            and isinstance(parent.body[0].value.value, str)
        ):
            docstring_nodes.add(id(parent.body[0].value))

for node in ast.walk(tree):
    if isinstance(node, ast.Attribute) and node.attr == "ALIGN_MEAN":
        sys.exit(1)
    if (
        isinstance(node, ast.Constant)
        and isinstance(node.value, str)
        and id(node) not in docstring_nodes
    ):
        for line in node.value.splitlines():
            stripped = line.strip()
            if not stripped or stripped.startswith("#"):
                continue
            if stripped == "ALIGN_MEAN" or re.search(
                r"(?:perSeriesAligner|per_series_aligner)\s*[:=]\s*['\"]?ALIGN_MEAN\b",
                stripped,
            ):
                sys.exit(1)
PYEOF
    then
      pass "setup_quality_alerts.py avoids incompatible ALIGN_MEAN aligner in alert code/YAML (${eval_dir}/setup_quality_alerts.py)"
    else
      fail "${eval_dir}/setup_quality_alerts.py must use ALIGN_PERCENTILE_50 (not ALIGN_MEAN) for DELTA/DISTRIBUTION online_evaluator/scores metrics"
    fi
  fi

  check_pattern "${eval_dir}/optimize_prompt.py" "SimplePromptOptimizer" "Integrates ADK SimplePromptOptimizer"
  check_pattern "${eval_dir}/optimize_prompt.py" "agents-cli eval optimize" "Documents agents-cli eval optimize command"
  check_pattern "${eval_dir}/optimize_prompt.py" "load_skill_from_dir" "Attaches local SkillToolset skills via load_skill_from_dir for GEPARootAgentOptimizer"
  check_pattern "${eval_dir}/optimize_prompt.py" "client\.skills\.update" "Supports zero-redeploy Skill Registry hot-update via client.skills.update"
  check_pattern "${eval_dir}/optimize_prompt.py" "gcloud alpha agent-registry skills" "Uses gcloud alpha agent-registry skills for standalone skill revisions"
  check_pattern "${eval_dir}/optimize_prompt.py" "(AGENT_REGISTRY_SKILLS_LOCATION|agent_registry_skills_location|--location=global|location=global)" "Targets global / AGENT_REGISTRY_SKILLS_LOCATION for standalone Agent Registry skills"
  check_pattern "${eval_dir}/optimize_prompt.py" "revisions create rev-2" "Documents Agent Registry immutable rev-2 skill revision creation"
  check_pattern "${eval_dir}/optimize_prompt.py" "--default-revision=" "Documents Agent Registry --default-revision promotion and rollback"

  # Regression check: optimize_prompt.py feedback_entries.list() uses parent= (not name=)
  # and client.skills.update() passes skill directory (not zip_path) as local_path.
  if [[ -f "${eval_dir}/optimize_prompt.py" ]]; then
    if python3 - "${eval_dir}/optimize_prompt.py" <<'PYEOF'
import ast
import sys
from pathlib import Path

source = Path(sys.argv[1]).read_text(encoding="utf-8")
tree = ast.parse(source)
has_todo = "TODO(lab-6)" in source

for node in ast.walk(tree):
    if (
        isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and node.func.attr == "list"
        and isinstance(node.func.value, ast.Attribute)
        and node.func.value.attr == "feedback_entries"
    ):
        kw_names = {kw.arg for kw in node.keywords if kw.arg}
        if "name" in kw_names or "parent" not in kw_names:
            sys.exit(1)
    if (
        not has_todo
        and isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and node.func.attr == "update"
        and isinstance(node.func.value, ast.Attribute)
        and node.func.value.attr == "skills"
    ):
        for kw in node.keywords:
            if kw.arg == "config" and isinstance(kw.value, ast.Dict):
                for k, v in zip(kw.value.keys, kw.value.values):
                    if isinstance(k, ast.Constant) and k.value == "local_path":
                        if "zip_path" in ast.unparse(v):
                            sys.exit(1)
PYEOF
    then
      pass "optimize_prompt.py uses feedback_entries.list(parent=...) and directory local_path for client.skills.update() (${eval_dir}/optimize_prompt.py)"
    else
      fail "${eval_dir}/optimize_prompt.py must use feedback_entries.list(parent=...) and pass the skill directory (not zip_path) as local_path to client.skills.update()"
    fi
  fi

  # Regression check: pre-recorded multi-turn traces (coding_agent_multi_turn.json) MUST use
  # `agents-cli eval grade --traces`, NEVER `agents-cli eval run --dataset`.
  if [[ -f "workshop/06-LAB-OPTIMIZE-EVAL-AND-ALERTS.md" && -f "${eval_dir}/run_offline_eval.py" ]]; then
    if python3 - "workshop/06-LAB-OPTIMIZE-EVAL-AND-ALERTS.md" "${eval_dir}/run_offline_eval.py" <<'PYEOF'
import ast
import re
import sys
from pathlib import Path

doc_path = Path(sys.argv[1])
py_path = Path(sys.argv[2])

doc_text = doc_path.read_text(encoding="utf-8")
doc_norm = re.sub(r"\\\s*\n\s*", " ", doc_text)
doc_norm = re.sub(r"[ \t]+", " ", doc_norm)
bad_doc = re.search(
    r"agents-cli\s+eval\s+run\b[^\n]*--dataset\s+eval/datasets/coding_agent_multi_turn\.json",
    doc_norm,
)
good_doc = re.search(
    r"agents-cli\s+eval\s+grade\b[^\n]*--traces\s+eval/datasets/coding_agent_multi_turn\.json",
    doc_norm,
)
if bad_doc or not good_doc:
    sys.exit(1)

tree = ast.parse(py_path.read_text(encoding="utf-8"))
strings = [
    node.value
    for node in ast.walk(tree)
    if isinstance(node, ast.Constant) and isinstance(node.value, str)
]
bad_py = any(
    re.search(
        r"agents-cli\s+eval\s+run\b.*--dataset\s+eval/datasets/coding_agent_multi_turn\.json",
        s,
        flags=re.DOTALL,
    )
    for s in strings
)
good_py = any(
    re.search(
        r"agents-cli\s+eval\s+grade\b.*--traces\s+eval/datasets/coding_agent_multi_turn\.json",
        s,
        flags=re.DOTALL,
    )
    for s in strings
)
if bad_py or not good_py:
    sys.exit(1)
PYEOF
    then
      pass "Lab 6 doc and run_offline_eval.py grade coding_agent_multi_turn.json with 'agents-cli eval grade --traces' (not 'eval run --dataset')"
    else
      fail "Lab 6 doc and ${eval_dir}/run_offline_eval.py must use 'agents-cli eval grade --traces eval/datasets/coding_agent_multi_turn.json' rather than 'eval run --dataset'"
    fi
  fi

  # Regression check: client.evals.run_inference(src=...) ONLY accepts
  # `str | pd.DataFrame | types.EvaluationDataset` — NEVER a raw Python dict
  # such as `src={"eval_cases": ...}`.
  if [[ -f "${eval_dir}/run_offline_eval.py" ]]; then
    if python3 - "${eval_dir}/run_offline_eval.py" <<'PYEOF'
import ast
import sys
from pathlib import Path

source = Path(sys.argv[1]).read_text(encoding="utf-8")
tree = ast.parse(source)
has_todo = "TODO(lab-6)" in source


def is_raw_dict_expr(node: ast.AST) -> bool:
    if isinstance(node, ast.Dict):
        return True
    if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id == "dict":
        return True
    return False


found_run_inference = False
found_eval_dataset = False

for node in ast.walk(tree):
    if isinstance(node, ast.Attribute) and node.attr == "EvaluationDataset":
        found_eval_dataset = True
    elif isinstance(node, ast.Name) and node.id == "EvaluationDataset":
        found_eval_dataset = True
    elif isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) and node.func.attr == "run_inference":
        found_run_inference = True
        kw_map = {kw.arg: kw.value for kw in node.keywords if kw.arg}
        src_arg = kw_map.get("src")
        if src_arg is not None and is_raw_dict_expr(src_arg):
            sys.exit(1)

for scope_nodes in [tree.body] + [
    n.body for n in ast.walk(tree) if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))
]:
    dict_vars: set[str] = set()
    for stmt in scope_nodes:
        for sub in ast.walk(stmt):
            if isinstance(sub, ast.Assign) and is_raw_dict_expr(sub.value):
                for tgt in sub.targets:
                    if isinstance(tgt, ast.Name):
                        dict_vars.add(tgt.id)
            elif (
                isinstance(sub, ast.AnnAssign)
                and sub.value is not None
                and is_raw_dict_expr(sub.value)
                and isinstance(sub.target, ast.Name)
            ):
                dict_vars.add(sub.target.id)
    for stmt in scope_nodes:
        for call in ast.walk(stmt):
            if not isinstance(call, ast.Call):
                continue
            if isinstance(call.func, ast.Attribute) and call.func.attr == "run_inference":
                kw_map = {kw.arg: kw.value for kw in call.keywords if kw.arg}
                src_arg = kw_map.get("src")
                if isinstance(src_arg, ast.Name) and src_arg.id in dict_vars:
                    sys.exit(1)

if not has_todo and (not found_run_inference or not found_eval_dataset):
    sys.exit(1)
PYEOF
    then
      pass "run_offline_eval.py wraps prompt-only cases in types.EvaluationDataset for client.evals.run_inference(src=...) (never a raw dict)"
    else
      fail "${eval_dir}/run_offline_eval.py must pass a typed types.EvaluationDataset (never a raw dict like src={\"eval_cases\": ...}) to client.evals.run_inference(...)"
    fi
  fi

  # Dry-run smoke checks (always run when TODOs are completed)
  if [[ "${any_todo}" -eq 0 ]]; then
    if python3 "${eval_dir}/run_offline_eval.py" --dry-run >/dev/null 2>&1; then
      pass "run_offline_eval.py --dry-run succeeded"
    else
      fail "run_offline_eval.py --dry-run failed"
    fi
    if python3 "${eval_dir}/run_simulated_eval.py" --dry-run >/dev/null 2>&1; then
      pass "run_simulated_eval.py --dry-run succeeded"
    else
      fail "run_simulated_eval.py --dry-run failed"
    fi
    local monitor_out=""
    if monitor_out="$(
       GOOGLE_CLOUD_LOCATION=asia-southeast1 \
       EVAL_LOCATION=global \
       GOOGLE_CLOUD_AGENT_ENGINE_ENABLE_TELEMETRY=true \
       OTEL_SEMCONV_STABILITY_OPT_IN=gen_ai_latest_experimental \
       OTEL_INSTRUMENTATION_GENAI_CAPTURE_MESSAGE_CONTENT=EVENT_ONLY \
       python3 "${eval_dir}/setup_online_monitor.py" --strict-env 2>/dev/null
    )" && MONITOR_OUT="${monitor_out}" python3 - <<'PYEOF'
import json
import os

payload = json.loads(os.environ["MONITOR_OUT"])
check = payload.get("otel_prerequisite_check") or {}
spec = payload.get("online_monitor_spec") or {}
assert check.get("passed") is True, f"Expected OTel check passed=True, got {check}"
assert spec.get("eval_location") == "global", f"Expected eval_location='global', got {spec.get('eval_location')!r}"
assert spec.get("runtime_location") == "asia-southeast1", f"Expected runtime_location='asia-southeast1', got {spec.get('runtime_location')!r}"
assert "locations/asia-southeast1/reasoningEngines/" in str(spec.get("target_agent_engine", "")), (
    f"Expected Singapore runtime region in target_agent_engine, got {spec.get('target_agent_engine')!r}"
)
PYEOF
    then
      pass "setup_online_monitor.py --strict-env succeeded and decoupled runtime_location=asia-southeast1 from eval_location=global"
    else
      fail "setup_online_monitor.py --strict-env failed or mixed runtime_location with eval_location"
    fi
    if python3 "${eval_dir}/setup_quality_alerts.py" --dry-run >/dev/null 2>&1; then
      pass "setup_quality_alerts.py --dry-run succeeded"
    else
      fail "setup_quality_alerts.py --dry-run failed"
    fi
    if python3 "${eval_dir}/optimize_prompt.py" --dry-run >/dev/null 2>&1; then
      pass "optimize_prompt.py --dry-run succeeded"
    else
      fail "optimize_prompt.py --dry-run failed"
    fi
    if python3 "${eval_dir}/optimize_prompt.py" --optimizer gepa-skills --publish-skill --dry-run >/dev/null 2>&1; then
      pass "optimize_prompt.py --optimizer gepa-skills --publish-skill --dry-run succeeded (16-rule skill validation)"
    else
      fail "optimize_prompt.py --optimizer gepa-skills --publish-skill --dry-run failed"
    fi
  else
    warn "Skipping Lab 6 --dry-run smoke executions until TODO(lab-6) markers are resolved."
  fi
}

# -----------------------------------------------------------------------------
# Lab 7 (Optional): Enterprise Security & Governance Hardening
# -----------------------------------------------------------------------------
verify_lab_7() {
  section "Lab 7 Verification (${TRACK}/ — Optional Enterprise Security & Governance Hardening)"
  local lab7_doc="workshop/07-LAB-OPTIONAL-SECURITY-AND-GOVERNANCE.md"
  local runtime_df="${TRACK}/Dockerfile"
  local sandbox_df="${TRACK}/sandbox_image/Dockerfile"
  local mem="${TRACK}/coding_agent/memory/memory_bank_manager.py"
  local reg="${TRACK}/coding_agent/tools/registry_loader.py"
  local main_tf="${TRACK}/terraform/main.tf"

  check_file_exists "${lab7_doc}"
  check_pattern "${lab7_doc}" "ENABLED_BLOCKING" "Optional Lab 7 doc covers Agent Registry ENABLED_BLOCKING scanning"
  check_pattern "${lab7_doc}" "AGENT_IDENTITY" "Optional Lab 7 doc covers SPIFFE AGENT_IDENTITY upgrade path"
  check_pattern "${lab7_doc}" "agent_gateway_config" "Optional Lab 7 doc covers Terraform agent_gateway_config binding"
  check_pattern "${lab7_doc}" "modelarmor\.calloutUser" "Optional Lab 7 doc covers Model Armor roles/modelarmor.calloutUser"
  check_pattern "${lab7_doc}" "agent-audit-worm" "Optional Lab 7 doc covers WORM audit bucket agent-audit-worm"

  check_file_exists "${runtime_df}"
  check_file_exists "${sandbox_df}"
  check_dockerfile_non_root "${runtime_df}" "Agent Runtime BYOC Dockerfile"
  check_dockerfile_non_root "${sandbox_df}" "BYOC Sandbox Dockerfile"

  check_file_exists "${mem}"
  check_pattern "${mem}" "sanitize_for_memory_ingestion" "Memory Bank includes sanitize_for_memory_ingestion prompt-injection defense"

  check_file_exists "${reg}"
  check_pattern "${reg}" "GcpAuthProvider" "Agent Registry loader registers GcpAuthProvider"
  check_pattern "${reg}" "X-Goog-User-Project" "Agent Registry loader sends X-Goog-User-Project header"

  check_file_exists "${main_tf}"
  check_pattern "${main_tf}" "AGENT_IDENTITY" "Terraform main.tf documents SPIFFE AGENT_IDENTITY upgrade path"
  check_pattern "${main_tf}" "agent_gateway_config" "Terraform main.tf documents agent_gateway_config hardening reference"
}

# -----------------------------------------------------------------------------
# Lab 8: Self-Hosted GKE Agent Sandbox Reference Overlay & Architecture Capstone
# -----------------------------------------------------------------------------
verify_lab_8() {
  section "Lab 8 Verification (${TRACK}/ — GKE Reference & Architecture Capstone)"
  local gke_dir="${TRACK}/gke_reference"
  local rbac="${gke_dir}/rbac.yaml"
  local tpl="${gke_dir}/sandbox_template.yaml"
  local pool="${gke_dir}/sandbox_warmpool.yaml"
  local py="${gke_dir}/gke_agent_example.py"

  check_file_exists "${rbac}"
  check_file_exists "${tpl}"
  check_file_exists "${pool}"
  check_file_exists "${py}"

  check_py_compile "${py}"

  check_no_todo_markers "${rbac}" "lab-8"
  check_no_todo_markers "${tpl}" "lab-8"
  check_no_todo_markers "${pool}" "lab-8"
  check_no_todo_markers "${py}" "lab-8"

  if python3 - "${rbac}" "${tpl}" "${pool}" 2>/dev/null <<'PYEOF'
import sys
from pathlib import Path

try:
    import yaml
except ImportError:
    sys.exit(2)

rbac_docs = [d for d in yaml.safe_load_all(Path(sys.argv[1]).read_text(encoding="utf-8")) if d]
tpl_doc = yaml.safe_load(Path(sys.argv[2]).read_text(encoding="utf-8"))
pool_doc = yaml.safe_load(Path(sys.argv[3]).read_text(encoding="utf-8"))

# 1. Verify dual API group RBAC (extensions.agents.x-k8s.io + agents.x-k8s.io)
roles = [d for d in rbac_docs if d.get("kind") == "Role"]
assert roles, "rbac.yaml missing Role document"
rules = roles[0].get("rules", [])
groups = {g for r in rules for g in (r.get("apiGroups") or [])}
assert "extensions.agents.x-k8s.io" in groups, "Role missing extensions.agents.x-k8s.io"
assert "agents.x-k8s.io" in groups, "Role missing core agents.x-k8s.io rule for sandboxes"

# 2. Verify secure-sandbox-policy VAP hardening on SandboxTemplate
assert tpl_doc.get("kind") == "SandboxTemplate"
pod_spec = tpl_doc["spec"]["podTemplate"]["spec"]
assert pod_spec.get("runtimeClassName") == "gvisor", "runtimeClassName must be gvisor"
assert pod_spec.get("automountServiceAccountToken") is False, "automountServiceAccountToken must be false"
pod_sc = pod_spec.get("securityContext") or {}
assert pod_sc.get("runAsNonRoot") is True, "pod securityContext.runAsNonRoot must be true"
containers = pod_spec.get("containers") or []
assert containers, "SandboxTemplate missing containers"
for container in containers:
    csc = container.get("securityContext") or {}
    assert csc.get("allowPrivilegeEscalation") is False, "allowPrivilegeEscalation must be false"
    drops = ((csc.get("capabilities") or {}).get("drop")) or []
    assert "ALL" in drops, "container capabilities.drop must include ALL"
    limits = ((container.get("resources") or {}).get("limits")) or {}
    assert "cpu" in limits and "memory" in limits, "container resources.limits must set cpu and memory"

# 3. Verify SandboxWarmPool references matching template
assert pool_doc.get("kind") == "SandboxWarmPool"
assert pool_doc["spec"]["sandboxTemplateRef"]["name"] == tpl_doc["metadata"]["name"]
PYEOF
  then
    pass "GKE YAML syntax, dual API-group RBAC, and secure-sandbox-policy VAP hardening validated"
  else
    rc=$?
    if [[ "${rc}" -eq 2 ]]; then
      warn "PyYAML not installed; skipping structured GKE YAML/VAP validation."
    else
      fail "GKE YAML syntax, dual API-group RBAC, or VAP hardening check failed in ${gke_dir}"
    fi
  fi

  if python3 "${py}" --mode inspect >/dev/null 2>&1; then
    pass "gke_agent_example.py --mode inspect succeeded"
  else
    fail "gke_agent_example.py --mode inspect failed"
  fi
}

case "${TARGET}" in
  1) verify_lab_1 ;;
  2) verify_lab_2 ;;
  3) verify_lab_3 ;;
  4) verify_lab_4 ;;
  5) verify_lab_5 ;;
  6) verify_lab_6 ;;
  7) verify_lab_7 ;;
  8) verify_lab_8 ;;
  all)
    verify_lab_1
    verify_lab_2
    verify_lab_3
    verify_lab_4
    verify_lab_5
    verify_lab_6
    ;;
esac

printf "\n=============================================================================\n"
printf "Verification Summary (target=%s, track=%s): PASS=%d | FAIL=%d | WARN=%d\n" \
  "${TARGET}" "${TRACK}" "${PASS_COUNT}" "${FAIL_COUNT}" "${WARN_COUNT}"
printf "=============================================================================\n"

if [[ "${FAIL_COUNT}" -gt 0 ]]; then
  if [[ "${TRACK}" == "starter" ]]; then
    printf "Tip: Complete the remaining # TODO(lab-N) markers or compare against solution/.\n"
    printf "     To verify the reference solution directly: TRACK=solution ./scripts/verify_lab.sh %s\n" "${TARGET}"
  fi
  exit 1
fi
exit 0
