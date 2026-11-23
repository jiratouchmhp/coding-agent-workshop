# =============================================================================
# Enterprise Coding Agent Workshop — Root Makefile
# =============================================================================
# Run `make help` to view all targets.
# Override TRACK=solution (default: starter) to run against the reference code:
#   make TRACK=solution eval-offline
#   make verify-lab LAB=1
#
# Regional defaults (Bangkok first; fall back to Singapore / global / us-central1 only where required):
#   PRIMARY_REGION / BUILD_LOCATION / AR_LOCATION / AGENT_REGISTRY_LOCATION = asia-southeast3 (Bangkok)
#   GOOGLE_CLOUD_LOCATION (Agent Runtime, Sandboxes, Sessions, Memory Bank)  = asia-southeast1 (Singapore fallback)
#   MODEL_LOCATION (Frontier Gemini 4: gemini-4-hydrogen / gemini-4-neon)    = global (or gemini-4-argon in asia-southeast1)
#   AGENT_REGISTRY_SKILLS_LOCATION (gcloud alpha agent-registry skills)      = global
#   SKILL_REGISTRY_LOCATION (Vertex AI Skill Registry preview)               = us-central1
#   EVAL_LOCATION (Gen AI Evaluation Service + loss clustering)              = global
#
# Zero-Docker First-Class Path:
#   make test-agy-harness                               (Lab 1/2 — agy --dry-run, zero Docker / zero agy binary)
#   make test-sandbox-local && make push-sandbox        (Lab 2 — Cloud Build)
#   make test-agent-local   && make pack-agent-source   (Lab 5 — source_code_spec)
#   make test-agent-local   && make push-agent          (Lab 5 — Cloud Build)
# =============================================================================

SHELL := /usr/bin/env bash
.DEFAULT_GOAL := help

TRACK ?= starter
LAB ?= all
SANDBOX_DEMO_MODE ?= shell
SKILL_DIR ?= $(TRACK)/skills_to_register/secure-code-review
SKILL_ZIP_OUT ?= dist/secure-code-review.zip
PYTHON ?= python3
PREFLIGHT_ARGS ?=
FAST_FORWARD_ARGS ?=
CLEANUP_ARGS ?=

# Helper shell snippet to load `.env` without breaking on comments or quotes
LOAD_ENV = set -a; [ -f .env ] && source .env; set +a

define _TEST_SANDBOX_LOCAL_PY
import json
import urllib.error
import urllib.request

# 1. GET /health -> HTTP 200 (must include boolean `agy_cli_available`)
with urllib.request.urlopen("http://127.0.0.1:18081/health", timeout=5) as resp:
    assert resp.status == 200, f"Expected 200 from /health, got {resp.status}"
    health = json.loads(resp.read().decode("utf-8"))
    assert health.get("status") == "ok", f"Unexpected /health payload: {health}"
    assert "agy_cli_available" in health and isinstance(health["agy_cli_available"], bool), (
        f"Expected boolean 'agy_cli_available' key in /health payload, got {health}"
    )
    print(f"[PASS] GET /health -> 200 ({health})")

# 2. POST /exec {"command": "echo ok"} -> HTTP 200 & returncode == 0
req_ok = urllib.request.Request(
    "http://127.0.0.1:18081/exec",
    data=json.dumps({"command": "echo ok"}).encode("utf-8"),
    headers={"Content-Type": "application/json"},
    method="POST",
)
with urllib.request.urlopen(req_ok, timeout=5) as resp:
    assert resp.status == 200, f"Expected 200 from /exec, got {resp.status}"
    body = json.loads(resp.read().decode("utf-8"))
    assert body.get("returncode") == 0, f"Expected returncode==0, got {body}"
    assert "ok" in body.get("stdout", ""), f"Expected 'ok' in stdout, got {body}"
    print(
        f"[PASS] POST /exec ('echo ok') -> 200 "
        f"(returncode={body['returncode']}, stdout={body['stdout'].strip()!r})"
    )

# 3. POST /exec {"command": "pwd", "cwd": "/etc"} -> HTTP 400 (workspace confinement)
req_escape = urllib.request.Request(
    "http://127.0.0.1:18081/exec",
    data=json.dumps({"command": "pwd", "cwd": "/etc"}).encode("utf-8"),
    headers={"Content-Type": "application/json"},
    method="POST",
)
try:
    with urllib.request.urlopen(req_escape, timeout=5) as resp:
        raise AssertionError(f"Expected HTTP 400 for cwd='/etc', got {resp.status}")
except urllib.error.HTTPError as exc:
    assert exc.code == 400, f"Expected HTTP 400 for cwd='/etc', got {exc.code}"
    err_body = exc.read().decode("utf-8", errors="replace")
    print(f"[PASS] POST /exec (cwd='/etc') -> 400 rejected ({err_body})")

# 4. POST /exec with allowlisted ephemeral env key (GOOGLE_CLOUD_LOCATION) -> HTTP 200
req_env_ok = urllib.request.Request(
    "http://127.0.0.1:18081/exec",
    data=json.dumps(
        {
            "command": "printenv GOOGLE_CLOUD_LOCATION",
            "env": {"GOOGLE_CLOUD_LOCATION": "global"},
        }
    ).encode("utf-8"),
    headers={"Content-Type": "application/json"},
    method="POST",
)
with urllib.request.urlopen(req_env_ok, timeout=5) as resp:
    assert resp.status == 200, f"Expected 200 for allowlisted env key, got {resp.status}"
    body = json.loads(resp.read().decode("utf-8"))
    assert body.get("returncode") == 0, f"Expected returncode==0 for allowlisted env, got {body}"
    assert body.get("stdout", "").strip() == "global", (
        f"Expected GOOGLE_CLOUD_LOCATION='global' in child env stdout, got {body}"
    )
    print(
        f"[PASS] POST /exec (allowlisted env GOOGLE_CLOUD_LOCATION=global) -> 200 "
        f"(stdout={body['stdout'].strip()!r})"
    )

# 5. POST /exec with disallowed env key -> HTTP 400 (strict ephemeral env allowlist)
req_env_bad = urllib.request.Request(
    "http://127.0.0.1:18081/exec",
    data=json.dumps(
        {
            "command": "echo should-not-run",
            "env": {"LD_PRELOAD": "/tmp/disallowed.so"},
        }
    ).encode("utf-8"),
    headers={"Content-Type": "application/json"},
    method="POST",
)
try:
    with urllib.request.urlopen(req_env_bad, timeout=5) as resp:
        raise AssertionError(f"Expected HTTP 400 for disallowed env key, got {resp.status}")
except urllib.error.HTTPError as exc:
    assert exc.code == 400, f"Expected HTTP 400 for disallowed env key, got {exc.code}"
    err_body = exc.read().decode("utf-8", errors="replace")
    print(f"[PASS] POST /exec (disallowed env LD_PRELOAD) -> 400 rejected ({err_body})")
endef
export _TEST_SANDBOX_LOCAL_PY

define _TEST_AGY_HARNESS_PY
import json
import os
import subprocess
import sys
import tempfile

from coding_agent.config import Settings, get_settings
from coding_agent.tools.agy_headless_harness import (
    AgyExitCode,
    parse_agy_stream_json,
)

# 0. Verify 4-tier AgyExitCode enum values
assert int(AgyExitCode.SUCCESS) == 0, f"Expected SUCCESS==0, got {AgyExitCode.SUCCESS!r}"
assert int(AgyExitCode.FAILURE) == 1, f"Expected FAILURE==1, got {AgyExitCode.FAILURE!r}"
assert int(AgyExitCode.UNSUPPORTED_COMMAND) == 2, (
    f"Expected UNSUPPORTED_COMMAND==2, got {AgyExitCode.UNSUPPORTED_COMMAND!r}"
)
assert int(AgyExitCode.AGENT_ERROR) == 3, (
    f"Expected AGENT_ERROR==3, got {AgyExitCode.AGENT_ERROR!r}"
)
print(
    "[PASS] Verified 4-tier AgyExitCode contract "
    "(0=SUCCESS, 1=FAILURE, 2=UNSUPPORTED_COMMAND, 3=AGENT_ERROR)"
)

# 1. Verify --dry-run NDJSON stream-json parsing (conversation_id, tool_calls, token_usage, response_text)
proc = subprocess.run(
    [
        sys.executable,
        "-m",
        "coding_agent.tools.agy_headless_harness",
        "--prompt",
        "Dry-run smoke check: verify stream-json NDJSON parsing and 4-tier exit codes",
        "--dry-run",
    ],
    capture_output=True,
    text=True,
    check=False,
)
if proc.stdout:
    print(proc.stdout, end="" if proc.stdout.endswith("\n") else "\n")
if proc.stderr:
    print(proc.stderr, end="" if proc.stderr.endswith("\n") else "\n", file=sys.stderr)
assert proc.returncode == 0, f"agy_headless_harness --dry-run exited with {proc.returncode}"
result = json.loads(proc.stdout)
assert result.get("exit_code") == int(AgyExitCode.SUCCESS), (
    f"Expected exit_code=0 in --dry-run output, got {result!r}"
)
assert result.get("status") == "success", (
    f"Expected status='success' in --dry-run output, got {result!r}"
)
assert isinstance(result.get("conversation_id"), str) and result["conversation_id"].strip(), (
    f"Expected parsed conversation_id from stream-json NDJSON dry-run, got {result!r}"
)
assert isinstance(result.get("tool_calls"), list) and len(result["tool_calls"]) >= 1, (
    f"Expected non-empty tool_calls list in --dry-run output, got {result!r}"
)
assert isinstance(result.get("token_usage"), dict) and result["token_usage"].get("total_tokens", 0) > 0, (
    f"Expected populated token_usage dict in --dry-run output, got {result!r}"
)
assert isinstance(result.get("response_text"), str) and result["response_text"].strip(), (
    f"Expected non-empty response_text in --dry-run output, got {result!r}"
)
cmd_dry = result.get("command") or []
assert "--output-format" in cmd_dry and "stream-json" in cmd_dry, (
    f"Expected '--output-format', 'stream-json' in command argv, got {cmd_dry!r}"
)
print(
    "[PASS] (1/4) --dry-run stream-json NDJSON parsing verified "
    f"(conversation_id={result['conversation_id']!r}, tool_calls={len(result['tool_calls'])}, "
    f"total_tokens={result['token_usage'].get('total_tokens')}, "
    f"response_chars={len(result['response_text'])})"
)

# 2. Verify --conversation conv-round-2 continuity across fix rounds
proc_conv = subprocess.run(
    [
        sys.executable,
        "-m",
        "coding_agent.tools.agy_headless_harness",
        "--prompt",
        "Fix round 2: apply failing pytest/ruff fixes while continuing prior conversation",
        "--conversation",
        "conv-round-2",
        "--dry-run",
    ],
    capture_output=True,
    text=True,
    check=False,
)
if proc_conv.returncode != 0:
    if proc_conv.stdout:
        print(proc_conv.stdout, end="" if proc_conv.stdout.endswith("\n") else "\n")
    if proc_conv.stderr:
        print(proc_conv.stderr, end="" if proc_conv.stderr.endswith("\n") else "\n", file=sys.stderr)
assert proc_conv.returncode == 0, (
    f"agy_headless_harness --conversation conv-round-2 --dry-run exited with {proc_conv.returncode}"
)
result_conv = json.loads(proc_conv.stdout)
cmd_conv = result_conv.get("command") or []
assert "--conversation" in cmd_conv, (
    f"Expected '--conversation' in command argv, got {cmd_conv!r}"
)
conv_flag_idx = cmd_conv.index("--conversation")
assert conv_flag_idx + 1 < len(cmd_conv) and cmd_conv[conv_flag_idx + 1] == "conv-round-2", (
    f"Expected '--conversation', 'conv-round-2' in command argv, got {cmd_conv!r}"
)
assert result_conv.get("conversation_id") == "conv-round-2", (
    f"Expected echoed conversation_id=='conv-round-2', got {result_conv.get('conversation_id')!r}"
)
print(
    "[PASS] (2/4) --conversation conv-round-2 continuity verified "
    f"(command flag present, echoed conversation_id={result_conv['conversation_id']!r})"
)

# 3. Behavioral assertions via parse_agy_stream_json() for all 4 exit codes (0/1/2/3)
sample_ndjson = "\n".join(
    [
        json.dumps(
            {
                "type": "session_start",
                "conversation_id": "conv-parse-check",
                "model": "gemini-4-hydrogen",
            }
        ),
        json.dumps(
            {
                "type": "tool_use",
                "id": "tc_1",
                "name": "EditFile",
                "input": {"path": "app.py"},
            }
        ),
        json.dumps(
            {
                "type": "result",
                "conversation_id": "conv-parse-check",
                "model": "gemini-4-hydrogen",
                "result": "Applied surgical edit and verified tests.",
                "usage": {"input_tokens": 200, "output_tokens": 50, "total_tokens": 250},
            }
        ),
    ]
)

res_0 = parse_agy_stream_json(
    sample_ndjson,
    "",
    int(AgyExitCode.SUCCESS),
    model="gemini-4-hydrogen",
)
assert res_0.exit_code == 0 and res_0.ok is True, f"Exit 0 check failed: {res_0!r}"
assert res_0.status == "success", f"Expected status='success' on exit 0, got {res_0.status!r}"
assert res_0.should_retry_or_fallback is False, f"Exit 0 must NOT retry: {res_0!r}"
assert res_0.agy_error is None, f"Exit 0 should have agy_error=None, got {res_0.agy_error!r}"
assert res_0.conversation_id == "conv-parse-check", f"Exit 0 conversation_id mismatch: {res_0!r}"
assert len(res_0.tool_calls) == 1 and res_0.tool_calls[0]["name"] == "EditFile", (
    f"Exit 0 tool_calls mismatch: {res_0!r}"
)
assert res_0.token_usage.get("total_tokens") == 250, f"Exit 0 token_usage mismatch: {res_0!r}"
assert "Applied surgical edit" in res_0.response_text, f"Exit 0 response_text mismatch: {res_0!r}"

res_1 = parse_agy_stream_json(
    "",
    "auth failure: Application Default Credentials missing",
    int(AgyExitCode.FAILURE),
    model="gemini-4-hydrogen",
)
assert res_1.exit_code == 1 and res_1.ok is False, f"Exit 1 check failed: {res_1!r}"
assert res_1.status == "failure", f"Expected status='failure' on exit 1, got {res_1.status!r}"
assert res_1.should_retry_or_fallback is False, f"Exit 1 must NOT retry: {res_1!r}"
assert "AGY_ADC_AUTH" in res_1.actionable_hint, (
    f"Expected actionable AGY_ADC_AUTH hint on exit 1, got {res_1.actionable_hint!r}"
)

res_2 = parse_agy_stream_json(
    "",
    "unknown flag: --unsupported-flag",
    int(AgyExitCode.UNSUPPORTED_COMMAND),
    model="gemini-4-hydrogen",
)
assert res_2.exit_code == 2 and res_2.ok is False, f"Exit 2 check failed: {res_2!r}"
assert res_2.status == "unsupported_command", (
    f"Expected status='unsupported_command' on exit 2, got {res_2.status!r}"
)
assert res_2.should_retry_or_fallback is False, f"Exit 2 must NEVER retry: {res_2!r}"

res_3 = parse_agy_stream_json(
    "",
    "WARN: transient upstream throttle\nAGY_ERROR: RESOURCE_EXHAUSTED on gemini-4-neon\n",
    int(AgyExitCode.AGENT_ERROR),
    model="gemini-4-neon",
)
assert res_3.exit_code == 3 and res_3.ok is False, f"Exit 3 check failed: {res_3!r}"
assert res_3.status == "agent_error", f"Expected status='agent_error' on exit 3, got {res_3.status!r}"
assert res_3.should_retry_or_fallback is True, (
    f"Exit 3 MUST set should_retry_or_fallback=True: {res_3!r}"
)
assert res_3.agy_error == "RESOURCE_EXHAUSTED on gemini-4-neon", (
    f"Expected extracted AGY_ERROR detail on exit 3, got {res_3.agy_error!r}"
)

retry_matrix = {r.exit_code: r.should_retry_or_fallback for r in (res_0, res_1, res_2, res_3)}
assert retry_matrix == {0: False, 1: False, 2: False, 3: True}, (
    f"should_retry_or_fallback must be True ONLY on exit code 3, got {retry_matrix!r}"
)
print(
    "[PASS] (3/4) parse_agy_stream_json() 4-tier exit-code behavioral contract verified "
    f"(retry_matrix={retry_matrix}, exit3_agy_error={res_3.agy_error!r})"
)

# 4. Validate AGENT_ARCHITECTURE=agy_harness (+ ADK workflow/root dispatch when google-adk is installed)
cfg_agy = Settings(agent_architecture="agy_harness")
assert cfg_agy.agent_architecture == "agy_harness", (
    f"Expected Settings(agent_architecture='agy_harness'), got {cfg_agy.agent_architecture!r}"
)
try:
    import google.adk  # noqa: F401
    has_google_adk = True
except ImportError:
    has_google_adk = False

if has_google_adk:
    with tempfile.TemporaryDirectory(prefix="agy_harness_smoke_") as tmp_ws:
        # Keep module-level root_agent init 100% offline/local even if .env uses SANDBOX_MODE=byoc.
        os.environ["SANDBOX_MODE"] = "local"
        os.environ["LOCAL_WORKSPACE_DIR"] = tmp_ws
        os.environ["ENABLE_MEMORY_BANK"] = "false"
        os.environ["ENABLE_SKILL_REGISTRY"] = "false"
        os.environ["AGENT_ARCHITECTURE"] = "simple"
        get_settings.cache_clear()

        from coding_agent.agent import build_root_agent
        from coding_agent.architectures import build_agy_harness_workflow

        cfg_agy_local = Settings(
            agent_architecture="agy_harness",
            sandbox_mode="local",
            local_workspace_dir=tmp_ws,
            enable_memory_bank=False,
            enable_skill_registry=False,
        )
        wf = build_agy_harness_workflow(settings=cfg_agy_local, tools=[])
        assert wf is not None and getattr(wf, "name", "") == "coding_agent", (
            f"Expected build_agy_harness_workflow() -> Workflow(name='coding_agent'), got {wf!r}"
        )
        root = build_root_agent(cfg_agy_local)
        assert root is not None and getattr(root, "name", "") == "coding_agent", (
            f"Expected build_root_agent(cfg_agy) -> Workflow(name='coding_agent'), got {root!r}"
        )
        assert isinstance(root, type(wf)), (
            f"Expected build_root_agent(cfg_agy) to dispatch to build_agy_harness_workflow(), "
            f"got {type(root)!r} vs {type(wf)!r}"
        )
    print(
        "[PASS] (4/4) AGENT_ARCHITECTURE=agy_harness verified "
        "(Settings + build_agy_harness_workflow + build_root_agent with google-adk)"
    )
else:
    print(
        "[PASS] (4/4) AGENT_ARCHITECTURE=agy_harness Settings validation verified "
        "(google-adk not installed in current interpreter; skipped ADK workflow instantiation)"
    )
endef
export _TEST_AGY_HARNESS_PY

define _TEST_AGENT_LOCAL_PY
import http.client
import json
import urllib.request

# 1. GET / -> HTTP 200 {"status":"ok"}
with urllib.request.urlopen("http://127.0.0.1:18082/", timeout=5) as resp:
    assert resp.status == 200, f"Expected HTTP 200 from GET /, got {resp.status}"
    raw = resp.read().decode("utf-8")
    payload = json.loads(raw)
    assert payload == {"status": "ok"}, f"Expected {{'status': 'ok'}}, got {payload!r}"
    print(
        f"[PASS] GET http://127.0.0.1:18082/ -> 200 "
        f"({json.dumps(payload, separators=(',', ':'))})"
    )

# 2. POST /api/reasoning_engine with BOTH `Content-Type: application/json` AND
#    raw JSON bodies without `application/json` (mirrors Agent Runtime :query proxy
#    and catches FastAPI 0.163+ strict content-type body-parsing regressions locally).
query_body = json.dumps(
    {"class_method": "list_sessions", "input": {"user_id": "local-smoke"}}
).encode("utf-8")

for label, headers in (
    ("Content-Type: application/json", {"Content-Type": "application/json"}),
    ("raw JSON without Content-Type header", {}),
    ("raw JSON with Content-Type: text/plain", {"Content-Type": "text/plain"}),
):
    conn = http.client.HTTPConnection("127.0.0.1", 18082, timeout=30)
    try:
        conn.request("POST", "/api/reasoning_engine", body=query_body, headers=headers)
        resp = conn.getresponse()
        resp_body = resp.read().decode("utf-8", errors="replace")
    finally:
        conn.close()
    assert resp.status == 200, (
        f"POST /api/reasoning_engine ({label}) returned HTTP {resp.status} "
        f"(expected 200; HTTP 422 indicates FastAPI strict content-type regression "
        f"on QueryRequest — parse raw JSON via `request: Request`): {resp_body}"
    )
    parsed = json.loads(resp_body)
    assert "output" in parsed, (
        f"POST /api/reasoning_engine ({label}) missing 'output' key: {parsed!r}"
    )
    print(
        f"[PASS] POST http://127.0.0.1:18082/api/reasoning_engine ({label}) -> 200 "
        f"(keys={sorted(parsed.keys())})"
    )
endef
export _TEST_AGENT_LOCAL_PY

.PHONY: help preflight install install-pip lint test-agy-harness test-sandbox-local build-sandbox \
        push-sandbox sandbox-lifecycle-demo package-skill test-agent-local \
        pack-agent-source push-agent tf-plan tf-apply eval-offline eval-simulated \
        validate-skills fast-forward verify-lab cleanup

help: ## Print available workshop targets and usage examples
	@echo "Enterprise Coding Agent Workshop — Makefile Targets (Gemini 4: gemini-4-hydrogen / gemini-4-neon)"
	@echo ""
	@echo "Usage: make <target> [TRACK=starter|solution] [LAB=1..8|all]"
	@echo "Current TRACK=$(TRACK)"
	@echo ""
	@awk 'BEGIN {FS = ":.*## "} /^[a-zA-Z0-9_-]+:.*## / {printf "  \033[36m%-24s\033[0m %s\n", $$1, $$2}' $(MAKEFILE_LIST)
	@echo ""
	@echo "Examples:"
	@echo "  make preflight"
	@echo "  make install                   # or 'make install-pip' without uv"
	@echo "  make test-agy-harness          # Lab 1/2 zero-Docker agy NDJSON + 4-tier exit-code dry-run"
	@echo "  make test-sandbox-local        # Lab 2 zero-Docker BYOC runner.py smoke test"
	@echo "  make test-agent-local          # Lab 5 zero-Docker smoke test"
	@echo "  make pack-agent-source         # Lab 5 zero-Docker / zero-AR tarball"
	@echo "  make validate-skills"
	@echo "  make fast-forward LAB=1        # Catch up on Lab 1 without spoiling Labs 2-6"
	@echo "  make fast-forward LAB=2 FAST_FORWARD_ARGS=--dry-run"
	@echo "  make verify-lab LAB=1"
	@echo "  make TRACK=solution eval-offline"
	@echo "  make cleanup CLEANUP_ARGS=--dry-run"

preflight: ## Lab 0: Run environment, toolchain, region, and GCP pre-flight checks
	@./scripts/preflight_check.sh $(PREFLIGHT_ARGS)

install: ## Sync Python 3.11+ dependencies via uv for starter/ and solution/
	@if ! command -v uv >/dev/null 2>&1; then \
		echo "ERROR: 'uv' not found on PATH." >&2; \
		echo "Install standalone uv (zero sudo): curl -LsSf https://astral.sh/uv/install.sh | sh" >&2; \
		echo "Or use pure venv + pip fallback:   make install-pip" >&2; \
		exit 1; \
	fi
	@echo "==> Syncing starter/ dependencies with uv..."
	cd starter && uv sync --dev
	@echo "==> Syncing solution/ dependencies with uv..."
	cd solution && uv sync --dev

install-pip: ## Pure python3 -m venv + pip dependency install fallback (zero uv required)
	@set -euo pipefail; \
	VENV_ERR=$$(mktemp); \
	trap 'rm -f "$${VENV_ERR}"' EXIT; \
	for dir in starter solution; do \
		echo "==> Creating virtual environment and installing dependencies in $${dir}/..."; \
		if ! $(PYTHON) -m venv "$${dir}/.venv" 2>"$${VENV_ERR}"; then \
			cat "$${VENV_ERR}" >&2; \
			echo "" >&2; \
			echo "ERROR: '$(PYTHON) -m venv $${dir}/.venv' failed (common on Debian/Ubuntu when python3-venv is not installed)." >&2; \
			echo "Recommended zero-sudo fix — install standalone uv instead:" >&2; \
			echo "  curl -LsSf https://astral.sh/uv/install.sh | sh" >&2; \
			echo "  export PATH=\"\$$HOME/.local/bin:\$$PATH\"" >&2; \
			echo "  make install" >&2; \
			echo "Or install Debian venv support: sudo apt-get install -y python3-venv" >&2; \
			exit 1; \
		fi; \
		"$${dir}/.venv/bin/python" -m pip install --upgrade pip; \
		"$${dir}/.venv/bin/python" -m pip install -e "./$${dir}[dev]"; \
	done; \
	echo "==> Installed starter/.venv and solution/.venv successfully via pip."

lint: ## Run ruff check and python3 -m py_compile across starter/, solution/, and scripts/
	@echo "==> Checking Python syntax with py_compile..."
	@PYCACHE_TMP=$$(mktemp -d); \
	trap 'rm -rf "$$PYCACHE_TMP"' EXIT; \
	find starter solution scripts -name '*.py' -not -path '*/.venv/*' -print0 | xargs -0 env PYTHONPYCACHEPREFIX="$$PYCACHE_TMP" $(PYTHON) -m py_compile
	@echo "==> Running ruff linter..."
	@if command -v ruff >/dev/null 2>&1; then \
		ruff check --config starter/pyproject.toml starter solution scripts; \
	elif [ -x starter/.venv/bin/ruff ]; then \
		starter/.venv/bin/ruff check --config starter/pyproject.toml starter solution scripts; \
	elif [ -x solution/.venv/bin/ruff ]; then \
		solution/.venv/bin/ruff check --config solution/pyproject.toml starter solution scripts; \
	elif command -v uv >/dev/null 2>&1; then \
		uv --directory starter run ruff check --config pyproject.toml ../starter ../solution ../scripts; \
	else \
		echo "WARNING: ruff not found on PATH; run 'make install' or 'make install-pip' to install dev tools."; \
	fi

test-agy-harness: ## Lab 1/2 (Zero-Docker): Verify agy harness (--dry-run NDJSON, --conversation, 4-tier exit codes, agy_harness)
	@set -euo pipefail; \
	$(LOAD_ENV); \
	echo "==> Running Antigravity (agy) headless CLI harness --dry-run in $(TRACK)/..."; \
	cd "$(TRACK)"; \
	if [ -x .venv/bin/python ]; then \
		env PYTHONDONTWRITEBYTECODE=1 .venv/bin/python - <<< "$$_TEST_AGY_HARNESS_PY"; \
	elif command -v uv >/dev/null 2>&1 && [ -d .venv ]; then \
		env PYTHONDONTWRITEBYTECODE=1 uv run python - <<< "$$_TEST_AGY_HARNESS_PY"; \
	else \
		env PYTHONDONTWRITEBYTECODE=1 $(PYTHON) - <<< "$$_TEST_AGY_HARNESS_PY"; \
	fi

test-sandbox-local: ## Lab 2 (Zero-Docker): Smoke-test BYOC runner.py (/health + agy_cli_available, /exec, env allowlist, cwd)
	@set -euo pipefail; \
	mkdir -p /tmp/byoc_smoke; \
	RUNNER_LOG=$$(mktemp); \
	SANDBOX_HOST=127.0.0.1 SANDBOX_WORKSPACE=/tmp/byoc_smoke SANDBOX_PORT=18081 \
		$(PYTHON) "$(TRACK)/sandbox_image/runner.py" >"$${RUNNER_LOG}" 2>&1 & \
	RUNNER_PID=$$!; \
	cleanup_runner() { \
		kill "$${RUNNER_PID}" 2>/dev/null || true; \
		wait "$${RUNNER_PID}" 2>/dev/null || true; \
		rm -f "$${RUNNER_LOG}"; \
	}; \
	trap cleanup_runner EXIT; \
	echo "==> Waiting for BYOC runner ($(TRACK)/sandbox_image/runner.py) on http://127.0.0.1:18081..."; \
	READY=0; \
	for _ in $$(seq 1 20); do \
		if ! kill -0 "$${RUNNER_PID}" 2>/dev/null; then \
			echo "ERROR: runner.py exited prematurely:" >&2; \
			cat "$${RUNNER_LOG}" >&2; \
			exit 1; \
		fi; \
		if $(PYTHON) -c 'import urllib.request; r = urllib.request.urlopen("http://127.0.0.1:18081/health", timeout=1); assert r.status == 200' 2>/dev/null; then \
			READY=1; \
			break; \
		fi; \
		sleep 0.5; \
	done; \
	if [ "$${READY}" -ne 1 ]; then \
		echo "ERROR: runner.py did not become ready within 10s:" >&2; \
		cat "$${RUNNER_LOG}" >&2; \
		exit 1; \
	fi; \
	$(PYTHON) - <<< "$$_TEST_SANDBOX_LOCAL_PY"

build-sandbox: ## Lab 2 (Optional — requires local Docker; use test-sandbox-local + push-sandbox for zero-Docker)
	@if ! command -v docker >/dev/null 2>&1; then \
		echo "ERROR: Local 'docker' CLI not found." >&2; \
		echo "Use the zero-Docker Lab 2 path instead:" >&2; \
		echo "  make test-sandbox-local" >&2; \
		echo "  make push-sandbox" >&2; \
		exit 1; \
	fi
	@echo "==> Building BYOC coding sandbox image locally from $(TRACK)/sandbox_image..."
	docker build -t coding-sandbox:v1 $(TRACK)/sandbox_image

push-sandbox: ## Lab 2 (Zero-Docker): Build and push BYOC sandbox image via Cloud Build
	@$(LOAD_ENV); \
	if [ -z "$${GOOGLE_CLOUD_PROJECT:-}" ]; then \
		echo "ERROR: GOOGLE_CLOUD_PROJECT is not set. Copy .env.example to .env first." >&2; \
		exit 1; \
	fi; \
	BUILD_LOC="$${BUILD_LOCATION:-$${PRIMARY_REGION:-asia-southeast3}}"; \
	AR_LOC="$${AR_LOCATION:-$${PRIMARY_REGION:-asia-southeast3}}"; \
	URI="$${SANDBOX_IMAGE_URI:-$${AR_LOC}-docker.pkg.dev/$${GOOGLE_CLOUD_PROJECT}/coding-agent-repo/coding-sandbox:v1}"; \
	echo "==> Submitting $(TRACK)/sandbox_image to Cloud Build (region=$${BUILD_LOC}) -> $${URI}"; \
	gcloud builds submit "$(TRACK)/sandbox_image" \
		--region="$${BUILD_LOC}" \
		--tag="$${URI}" \
		--project="$${GOOGLE_CLOUD_PROJECT}"

sandbox-lifecycle-demo: ## Lab 2: Run Template -> Sandbox -> Pause -> Resume -> Snapshot -> Delete demo
	@$(LOAD_ENV); \
	echo "==> Running sandbox lifecycle demo in $(TRACK)/ (mode=$(SANDBOX_DEMO_MODE))..."; \
	cd $(TRACK) && \
	if command -v uv >/dev/null 2>&1; then \
		uv run python -m coding_agent.tools.sandbox_lifecycle demo --mode "$(SANDBOX_DEMO_MODE)" --ttl 1800s; \
	elif [ -x .venv/bin/python ]; then \
		.venv/bin/python -m coding_agent.tools.sandbox_lifecycle demo --mode "$(SANDBOX_DEMO_MODE)" --ttl 1800s; \
	else \
		$(PYTHON) -m coding_agent.tools.sandbox_lifecycle demo --mode "$(SANDBOX_DEMO_MODE)" --ttl 1800s; \
	fi

package-skill: ## Lab 4: Validate all 16 atomic Skill Registry rules and build skill .zip
	@echo "==> Validating and packaging $(SKILL_DIR) -> $(SKILL_ZIP_OUT)..."
	$(PYTHON) scripts/package_registry_skill.py "$(SKILL_DIR)" --output "$(SKILL_ZIP_OUT)"

test-agent-local: ## Lab 5 (Zero-Docker): Smoke-test FastAPI Agent Runtime (GET / + POST /api/reasoning_engine)
	@set -euo pipefail; \
	AGENT_LOG=$$(mktemp); \
	( \
		cd "$(TRACK)"; \
		unset GOOGLE_CLOUD_AGENT_ENGINE_ID REASONING_ENGINE_NAME REASONING_ENGINE_ID; \
		export PYTHONDONTWRITEBYTECODE=1 \
			SANDBOX_MODE=local \
			ENABLE_MEMORY_BANK=false \
			ENABLE_SKILL_REGISTRY=false; \
		if command -v uv >/dev/null 2>&1 && ( [ -d .venv ] || uv run python -c "import uvicorn, fastapi" >/dev/null 2>&1 ); then \
			exec uv run uvicorn main:app --host 127.0.0.1 --port 18082; \
		elif [ -x .venv/bin/uvicorn ]; then \
			exec .venv/bin/uvicorn main:app --host 127.0.0.1 --port 18082; \
		elif [ -x .venv/bin/python ]; then \
			exec .venv/bin/python -m uvicorn main:app --host 127.0.0.1 --port 18082; \
		elif $(PYTHON) -c "import uvicorn, fastapi" >/dev/null 2>&1; then \
			exec $(PYTHON) -m uvicorn main:app --host 127.0.0.1 --port 18082; \
		else \
			echo "ERROR: uvicorn/fastapi not found in $(TRACK)/. Run 'make install' or 'make install-pip' first." >&2; \
			exit 1; \
		fi \
	) >"$${AGENT_LOG}" 2>&1 & \
	AGENT_PID=$$!; \
	cleanup_agent() { \
		pkill -TERM -P "$${AGENT_PID}" 2>/dev/null || true; \
		kill "$${AGENT_PID}" 2>/dev/null || true; \
		wait "$${AGENT_PID}" 2>/dev/null || true; \
		rm -f "$${AGENT_LOG}"; \
	}; \
	trap cleanup_agent EXIT; \
	echo "==> Waiting for FastAPI Agent Runtime ($(TRACK)/main.py) on http://127.0.0.1:18082..."; \
	READY=0; \
	for _ in $$(seq 1 30); do \
		if ! kill -0 "$${AGENT_PID}" 2>/dev/null; then \
			echo "ERROR: uvicorn exited prematurely:" >&2; \
			cat "$${AGENT_LOG}" >&2; \
			exit 1; \
		fi; \
		if $(PYTHON) -c 'import urllib.request; r = urllib.request.urlopen("http://127.0.0.1:18082/", timeout=1); assert r.status == 200' 2>/dev/null; then \
			READY=1; \
			break; \
		fi; \
		sleep 0.5; \
	done; \
	if [ "$${READY}" -ne 1 ]; then \
		echo "ERROR: uvicorn did not become ready within 15s:" >&2; \
		cat "$${AGENT_LOG}" >&2; \
		exit 1; \
	fi; \
	if ! $(PYTHON) - <<< "$$_TEST_AGENT_LOCAL_PY"; then \
		echo "--- FastAPI uvicorn log ($(TRACK)/main.py) ---" >&2; \
		cat "$${AGENT_LOG}" >&2; \
		exit 1; \
	fi

pack-agent-source: ## Lab 5 (Zero-Docker & Zero-AR): Build source_code_spec tarball with level-0 Dockerfile
	@set -euo pipefail; \
	echo "==> Packaging $(TRACK)/ into $(TRACK)/terraform/coding_agent_source.tar.gz..."; \
	cd "$(TRACK)" && tar --exclude='__pycache__' --exclude='*.pyc' \
		-czf terraform/coding_agent_source.tar.gz \
		Dockerfile main.py requirements.txt coding_agent/ skills_to_register/; \
	echo "==> Verifying level-0 Dockerfile in $(TRACK)/terraform/coding_agent_source.tar.gz..."; \
	TAR_LIST=$$(tar -tzf terraform/coding_agent_source.tar.gz); \
	if ! grep -Eq '^(\./)?Dockerfile$$' <<< "$${TAR_LIST}"; then \
		echo "ERROR: Dockerfile is NOT at level 0 of terraform/coding_agent_source.tar.gz!" >&2; \
		exit 1; \
	fi; \
	SIZE_BYTES=$$(wc -c < terraform/coding_agent_source.tar.gz | tr -d '[:space:]'); \
	if [ "$${SIZE_BYTES}" -gt 8388608 ]; then \
		echo "ERROR: coding_agent_source.tar.gz ($${SIZE_BYTES} bytes) exceeds 8 MB inline_source limit!" >&2; \
		exit 1; \
	fi; \
	echo "[PASS] Level-0 Dockerfile verified ($${SIZE_BYTES} bytes <= 8 MB inline_source limit):"; \
	sed -n '1,10p' <<< "$${TAR_LIST}"

push-agent: ## Lab 5 (Zero-Docker): Build and push Agent Runtime image via Cloud Build
	@$(LOAD_ENV); \
	if [ -z "$${GOOGLE_CLOUD_PROJECT:-}" ]; then \
		echo "ERROR: GOOGLE_CLOUD_PROJECT is not set. Copy .env.example to .env first." >&2; \
		exit 1; \
	fi; \
	BUILD_LOC="$${BUILD_LOCATION:-$${PRIMARY_REGION:-asia-southeast3}}"; \
	AR_LOC="$${AR_LOCATION:-$${PRIMARY_REGION:-asia-southeast3}}"; \
	URI="$${AGENT_IMAGE_URI:-$${AR_LOC}-docker.pkg.dev/$${GOOGLE_CLOUD_PROJECT}/coding-agent-repo/coding-agent:v1}"; \
	echo "==> Submitting $(TRACK)/ Agent Runtime image to Cloud Build (region=$${BUILD_LOC}) -> $${URI}"; \
	gcloud builds submit "$(TRACK)" \
		--region="$${BUILD_LOC}" \
		--tag="$${URI}" \
		--project="$${GOOGLE_CLOUD_PROJECT}"

tf-plan: ## Lab 5: Initialize, format-check, validate, and plan Terraform in $(TRACK)/terraform
	@echo "==> Running Terraform init / fmt / validate / plan in $(TRACK)/terraform..."
	terraform -chdir=$(TRACK)/terraform init
	terraform -chdir=$(TRACK)/terraform fmt -check
	terraform -chdir=$(TRACK)/terraform validate
	terraform -chdir=$(TRACK)/terraform plan

tf-apply: ## Lab 5: Initialize and apply Terraform in $(TRACK)/terraform
	@echo "==> Applying Terraform configuration in $(TRACK)/terraform..."
	terraform -chdir=$(TRACK)/terraform init
	terraform -chdir=$(TRACK)/terraform apply

eval-offline: ## Lab 6: Run offline evaluation over split single-turn and multi-turn datasets
	@$(LOAD_ENV); \
	echo "==> Running offline evaluation in $(TRACK)/..."; \
	cd $(TRACK) && \
	if command -v uv >/dev/null 2>&1; then \
		uv run python eval/run_offline_eval.py \
			--single-turn-dataset eval/datasets/coding_agent_single_turn.json \
			--multi-turn-dataset eval/datasets/coding_agent_multi_turn.json; \
	elif [ -x .venv/bin/python ]; then \
		.venv/bin/python eval/run_offline_eval.py \
			--single-turn-dataset eval/datasets/coding_agent_single_turn.json \
			--multi-turn-dataset eval/datasets/coding_agent_multi_turn.json; \
	else \
		$(PYTHON) eval/run_offline_eval.py \
			--single-turn-dataset eval/datasets/coding_agent_single_turn.json \
			--multi-turn-dataset eval/datasets/coding_agent_multi_turn.json; \
	fi

eval-simulated: ## Lab 6: Run 2-step simulated user evaluation personas
	@$(LOAD_ENV); \
	echo "==> Running simulated user evaluation in $(TRACK)/..."; \
	cd $(TRACK) && \
	if command -v uv >/dev/null 2>&1; then \
		uv run python eval/run_simulated_eval.py --count 5 --max-turns 5; \
	elif [ -x .venv/bin/python ]; then \
		.venv/bin/python eval/run_simulated_eval.py --count 5 --max-turns 5; \
	else \
		$(PYTHON) eval/run_simulated_eval.py --count 5 --max-turns 5; \
	fi

validate-skills: ## Validate all Antigravity workshop skills under .agents/skills/
	@echo "==> Validating .agents/skills/..."
	$(PYTHON) scripts/validate_skills.py .agents/skills

fast-forward: ## Catch up on a lab by syncing solution/ into starter/ without spoiling later labs (usage: make fast-forward LAB=1..6|8|all; supports FAST_FORWARD_ARGS=--dry-run)
	@echo "==> Fast-forwarding starter/ for LAB=$(LAB)..."
	./scripts/fast_forward_lab.sh "$(LAB)" $(FAST_FORWARD_ARGS)

verify-lab: ## Verify Labs 1-8 checkpoints locally (usage: make verify-lab LAB=1..8|all)
	@echo "==> Running verify_lab.sh for LAB=$(LAB) (TRACK=$(TRACK))..."
	./scripts/verify_lab.sh "$(LAB)" --track "$(TRACK)"

cleanup: ## Teardown workshop GCP resources and local artifacts (supports CLEANUP_ARGS=--dry-run)
	@./scripts/cleanup_workshop.sh $(CLEANUP_ARGS)
