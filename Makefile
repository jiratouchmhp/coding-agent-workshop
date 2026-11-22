# =============================================================================
# Enterprise Coding Agent Workshop — Root Makefile
# =============================================================================
# Run `make help` to view all targets.
# Override TRACK=solution (default: starter) to run against the reference code:
#   make TRACK=solution eval-offline
#   make verify-lab LAB=1
#
# Regional defaults (Bangkok Primary + Singapore Agent Platform):
#   PRIMARY_REGION / BUILD_LOCATION / AR_LOCATION / AGENT_REGISTRY_LOCATION = asia-southeast3
#   GOOGLE_CLOUD_LOCATION (Agent Runtime, Sandboxes, Sessions, Memory Bank)  = asia-southeast1
#   SKILL_REGISTRY_LOCATION                                                  = us-central1
#   EVAL_LOCATION                                                            = global
#
# Zero-Docker First-Class Path:
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
CLEANUP_ARGS ?=

# Helper shell snippet to load `.env` without breaking on comments or quotes
LOAD_ENV = set -a; [ -f .env ] && source .env; set +a

define _TEST_SANDBOX_LOCAL_PY
import json
import urllib.error
import urllib.request

# 1. GET /health -> HTTP 200
with urllib.request.urlopen("http://127.0.0.1:18081/health", timeout=5) as resp:
    assert resp.status == 200, f"Expected 200 from /health, got {resp.status}"
    health = json.loads(resp.read().decode("utf-8"))
    assert health.get("status") == "ok", f"Unexpected /health payload: {health}"
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
endef
export _TEST_SANDBOX_LOCAL_PY

define _TEST_AGENT_LOCAL_PY
import json
import urllib.request

with urllib.request.urlopen("http://127.0.0.1:18082/", timeout=5) as resp:
    assert resp.status == 200, f"Expected HTTP 200 from GET /, got {resp.status}"
    raw = resp.read().decode("utf-8")
    payload = json.loads(raw)
    assert payload == {"status": "ok"}, f"Expected {{'status': 'ok'}}, got {payload!r}"
    print(
        f"[PASS] GET http://127.0.0.1:18082/ -> 200 "
        f"({json.dumps(payload, separators=(',', ':'))})"
    )
endef
export _TEST_AGENT_LOCAL_PY

.PHONY: help preflight install install-pip lint test-sandbox-local build-sandbox \
        push-sandbox sandbox-lifecycle-demo package-skill test-agent-local \
        pack-agent-source push-agent tf-plan tf-apply eval-offline eval-simulated \
        validate-skills verify-lab cleanup

help: ## Print available workshop targets and usage examples
	@echo "Enterprise Coding Agent Workshop — Makefile Targets"
	@echo ""
	@echo "Usage: make <target> [TRACK=starter|solution] [LAB=1..8|all]"
	@echo "Current TRACK=$(TRACK)"
	@echo ""
	@awk 'BEGIN {FS = ":.*## "} /^[a-zA-Z0-9_-]+:.*## / {printf "  \033[36m%-24s\033[0m %s\n", $$1, $$2}' $(MAKEFILE_LIST)
	@echo ""
	@echo "Examples:"
	@echo "  make preflight"
	@echo "  make install                   # or 'make install-pip' without uv"
	@echo "  make test-sandbox-local        # Lab 2 zero-Docker smoke test"
	@echo "  make test-agent-local          # Lab 5 zero-Docker smoke test"
	@echo "  make pack-agent-source         # Lab 5 zero-Docker / zero-AR tarball"
	@echo "  make validate-skills"
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
		ruff check starter solution scripts; \
	elif [ -x starter/.venv/bin/ruff ]; then \
		starter/.venv/bin/ruff check starter solution scripts; \
	elif command -v uv >/dev/null 2>&1; then \
		uv --directory starter run ruff check ../starter ../solution ../scripts; \
	else \
		echo "WARNING: ruff not found on PATH; run 'make install' or 'make install-pip' to install dev tools."; \
	fi

test-sandbox-local: ## Lab 2 (Zero-Docker): Smoke-test BYOC runner.py (/health, /exec, cwd escape)
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

test-agent-local: ## Lab 5 (Zero-Docker): Smoke-test FastAPI Agent Runtime server (GET / -> 200)
	@set -euo pipefail; \
	AGENT_LOG=$$(mktemp); \
	( \
		cd "$(TRACK)"; \
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
	$(PYTHON) - <<< "$$_TEST_AGENT_LOCAL_PY"

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

verify-lab: ## Verify Labs 1-8 checkpoints locally (usage: make verify-lab LAB=1..8|all)
	@echo "==> Running verify_lab.sh for LAB=$(LAB) (TRACK=$(TRACK))..."
	./scripts/verify_lab.sh "$(LAB)" --track "$(TRACK)"

cleanup: ## Teardown workshop GCP resources and local artifacts (supports CLEANUP_ARGS=--dry-run)
	@./scripts/cleanup_workshop.sh $(CLEANUP_ARGS)
