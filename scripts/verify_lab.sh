#!/usr/bin/env bash
# =============================================================================
# Enterprise Coding Agent Workshop — Automated Lab Checkpoint Verifier (Labs 1-7)
# =============================================================================
# Usage:
#   ./scripts/verify_lab.sh <1|2|3|4|5|6|7|all> [--track starter|solution]
#   TRACK=solution ./scripts/verify_lab.sh all
#   TRACK=solution ./scripts/verify_lab.sh 7
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
Usage: ./scripts/verify_lab.sh <1|2|3|4|5|6|7|all> [--track starter|solution]

Verify workshop checkpoints locally for Labs 1-7:
  1    Lab 1: Setup, agents-cli-manifest.yaml, .agents/skills/ & ADK LlmAgent + LocalEnvironment
  2    Lab 2: Non-root BYOC Sandbox Dockerfile, Lifecycle & BaseEnvironment execution
  3    Lab 3: Agent Runtime BYOC Dockerfile/main.py/requirements.txt & Terraform IaC + IAM
  4    Lab 4: Managed Sessions, Memory Bank, Prompt-Injection Sanitizer & Telemetry/Feedback
  5    Lab 5: Skill Registry 16-check packaging, GCPSkillRegistry & AgentRegistry loader
  6    Lab 6: Split JSON Eval Datasets, Offline/Simulated Eval, Online Monitor, Alerts & Optimize
  7    Lab 7 (Optional): Self-Hosted GKE Agent Sandbox overlay (RBAC, VAP hardening, WarmPool)
  all  Run checkpoints for core Labs 1-6

Options:
  --track <starter|solution>   Directory to verify (default: starter; or set TRACK=solution)
  -h, --help                   Show this help message
EOF
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    1|2|3|4|5|6|7|all)
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
  if grep -Eq "${pattern}" "${path}"; then
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
  check_file_exists "${TRACK}/pyproject.toml"
  check_file_exists "${TRACK}/agents-cli-manifest.yaml"
  check_file_exists "${TRACK}/coding_agent/config.py"
  check_file_exists "${TRACK}/coding_agent/agent.py"
  check_file_exists "${TRACK}/coding_agent/architectures.py"
  check_file_exists "${TRACK}/services.yaml"
  check_file_exists "${TRACK}/services.py"

  check_pattern ".env.example" "^AGENT_ARCHITECTURE=simple$" "Default AGENT_ARCHITECTURE=simple preserves Labs 2-7 compatibility"
  check_pattern ".env.example" "^MAX_FIX_ROUNDS=3$" ".env.example sets MAX_FIX_ROUNDS=3"
  check_pattern ".env.example" "^ENABLE_HITL_APPROVAL=false$" ".env.example sets ENABLE_HITL_APPROVAL=false"

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
    pass "agents-cli found on PATH ($(command -v agents-cli))"
  else
    warn "agents-cli not found on PATH (install with: uvx google-agents-cli setup)"
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
# Lab 3: Deploy Agent Runtime with Terraform
# -----------------------------------------------------------------------------
verify_lab_3() {
  section "Lab 3 Verification (${TRACK}/ — Agent Runtime & Terraform IaC)"
  local tf_dir="${TRACK}/terraform"
  local main_tf="${tf_dir}/main.tf"
  local outputs_tf="${tf_dir}/outputs.tf"
  local versions_tf="${tf_dir}/versions.tf"
  local runtime_df="${TRACK}/Dockerfile"
  local runtime_main="${TRACK}/main.py"
  local runtime_reqs="${TRACK}/requirements.txt"
  local manifest="${TRACK}/agents-cli-manifest.yaml"

  check_file_exists "${runtime_df}"
  check_file_exists "${runtime_main}"
  check_file_exists "${runtime_reqs}"
  check_file_exists "${manifest}"
  check_file_exists "${versions_tf}"
  check_file_exists "${tf_dir}/variables.tf"
  check_file_exists "${main_tf}"
  check_file_exists "${outputs_tf}"
  check_file_exists "${tf_dir}/terraform.tfvars.example"

  if [[ -f "${runtime_df}" ]]; then
    check_dockerfile_non_root "${runtime_df}" "Agent Runtime BYOC Dockerfile"
    check_pattern "${runtime_df}" "^EXPOSE[[:space:]]+8080" "Agent Runtime Dockerfile exposes port 8080"
    check_pattern "${runtime_df}" "uvicorn" "Agent Runtime Dockerfile launches uvicorn"
  fi

  check_py_compile "${runtime_main}"
  check_no_todo_markers "${runtime_main}" "lab-3"
  check_pattern "${runtime_main}" "/api/reasoning_engine" "Agent Runtime server defines POST /api/reasoning_engine"
  check_pattern "${runtime_main}" "/api/stream_reasoning_engine" "Agent Runtime server defines POST /api/stream_reasoning_engine"

  check_no_todo_markers "${main_tf}" "lab-3"

  check_pattern "${versions_tf}" 'version[[:space:]]*=[[:space:]]*">= 6\.0\.0"' "Terraform provider floor >= 6.0.0 for container_spec support"
  check_pattern "${main_tf}" 'resource "google_vertex_ai_reasoning_engine"' "Declares google_vertex_ai_reasoning_engine"
  check_pattern "${main_tf}" "region[[:space:]]*=[[:space:]]*var\.location" "Uses verified Terraform attribute 'region = var.location'"
  check_pattern "${main_tf}" "SANDBOX_MODE" "Injects SANDBOX_MODE env var in Agent Runtime deployment_spec"
  check_pattern "${main_tf}" "roles/telemetry\.tracesWriter" "Grants roles/telemetry.tracesWriter for OTel telemetry.googleapis.com export"
  check_pattern "${main_tf}" "roles/iam\.serviceAccountTokenCreator" "Grants self serviceAccountTokenCreator for BYOC generate_access_token()"
  check_pattern "${main_tf}" "gcp-sa-aiplatform-re\.iam\.gserviceaccount\.com" "Grants Artifact Registry access to Agent Runtime SA (gcp-sa-aiplatform-re)"
  check_pattern "${main_tf}" "gcp-sa-vertex-sandbox\.iam\.gserviceaccount\.com" "Grants Artifact Registry access to Agent Sandbox SA (gcp-sa-vertex-sandbox)"
  check_pattern "${main_tf}" "depends_on[[:space:]]*=" "Orders IAM bindings with depends_on to prevent IMAGE_PULL_BACKOFF"
  check_pattern "${outputs_tf}" 'output "reasoning_engine_resource_name"' "Exports canonical reasoning_engine_resource_name"
  check_pattern "${outputs_tf}" 'output "reasoning_engine_id"' "Exports short numeric reasoning_engine_id"

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
# Lab 4: Managed Sessions, Memory Bank, Feedback & Telemetry
# -----------------------------------------------------------------------------
verify_lab_4() {
  section "Lab 4 Verification (${TRACK}/ — Sessions, Memory Bank, Feedback & Telemetry)"
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

  check_no_todo_markers "${sess}" "lab-4"
  check_no_todo_markers "${mem}" "lab-4"
  check_no_todo_markers "${cb}" "lab-4"
  check_no_todo_markers "${ag}" "lab-4"

  check_pattern "${sess}" "VertexAiSessionService" "Wires ADK VertexAiSessionService"
  check_pattern "${mem}" "VertexAiMemoryBankService" "Wires ADK VertexAiMemoryBankService"
  check_pattern "${mem}" "sanitize_for_memory_ingestion" "Includes prompt-injection sanitizer before Memory Bank ingestion"
  check_pattern "${cb}" "aiplatform\.googleapis\.com/ReasoningEngine" "Logs parent runtime sandbox output to ReasoningEngine resource"
  check_pattern "${cb}" "feedback_entries" "Implements Feedback Service client"
}

# -----------------------------------------------------------------------------
# Lab 5: Skill Registry, Agent Registry & Governance
# -----------------------------------------------------------------------------
verify_lab_5() {
  section "Lab 5 Verification (${TRACK}/ — Skill Registry, Agent Registry & Governance)"
  local reg="${TRACK}/coding_agent/tools/registry_loader.py"
  local ag="${TRACK}/coding_agent/agent.py"
  local skill_dir="${TRACK}/skills_to_register/secure-code-review"

  check_file_exists "${reg}"
  check_file_exists "${skill_dir}/SKILL.md"
  check_file_exists "scripts/package_registry_skill.py"

  check_py_compile "${reg}"
  check_no_todo_markers "${reg}" "lab-5"
  check_no_todo_markers "${ag}" "lab-5"

  check_pattern "${reg}" "GCPSkillRegistry" "Integrates ADK GCPSkillRegistry"
  check_pattern "${reg}" "SkillToolset" "Integrates ADK SkillToolset"
  check_pattern "${reg}" "AgentRegistry" "Integrates ADK AgentRegistry"
  check_pattern "${reg}" "GcpAuthProvider" "Registers Agent Identity GcpAuthProvider"
  check_pattern "${reg}" "X-Goog-User-Project" "Implements GoogleApiAuth with X-Goog-User-Project header"

  if [[ -d "${skill_dir}" ]]; then
    if python3 scripts/package_registry_skill.py "${skill_dir}" --dry-run >/dev/null 2>&1; then
      pass "${skill_dir} passed all 16 atomic Skill Registry validation checks (--dry-run)"
    else
      fail "${skill_dir} failed scripts/package_registry_skill.py --dry-run"
    fi
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
  check_pattern "${eval_dir}/setup_quality_alerts.py" "monitoring_v3" "Uses google.cloud.monitoring_v3"
  check_pattern "${eval_dir}/setup_quality_alerts.py" "aiplatform\.googleapis\.com/online_evaluator/scores" "Targets verified online_evaluator/scores metric"
  check_pattern "${eval_dir}/optimize_prompt.py" "SimplePromptOptimizer" "Integrates ADK SimplePromptOptimizer"
  check_pattern "${eval_dir}/optimize_prompt.py" "agents-cli eval optimize" "Documents agents-cli eval optimize command"

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
    if GOOGLE_CLOUD_AGENT_ENGINE_ENABLE_TELEMETRY=true \
       OTEL_SEMCONV_STABILITY_OPT_IN=gen_ai_latest_experimental \
       OTEL_INSTRUMENTATION_GENAI_CAPTURE_MESSAGE_CONTENT=EVENT_ONLY \
       python3 "${eval_dir}/setup_online_monitor.py" --strict-env >/dev/null 2>&1; then
      pass "setup_online_monitor.py --strict-env succeeded with valid OTel env"
    else
      fail "setup_online_monitor.py --strict-env failed"
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
  else
    warn "Skipping Lab 6 --dry-run smoke executions until TODO(lab-6) markers are resolved."
  fi
}

# -----------------------------------------------------------------------------
# Lab 7 (Optional): Self-Hosted GKE Agent Sandbox Reference Overlay
# -----------------------------------------------------------------------------
verify_lab_7() {
  section "Lab 7 Verification (${TRACK}/ — Optional Self-Hosted GKE Agent Sandbox Overlay)"
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

  check_no_todo_markers "${rbac}" "lab-7"
  check_no_todo_markers "${tpl}" "lab-7"
  check_no_todo_markers "${pool}" "lab-7"
  check_no_todo_markers "${py}" "lab-7"

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
