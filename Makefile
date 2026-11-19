# =============================================================================
# Enterprise Coding Agent Workshop — Root Makefile
# =============================================================================
# Run `make help` to view all targets.
# Override TRACK=solution (default: starter) to run against the reference code:
#   make TRACK=solution eval-offline
#   make verify-lab LAB=1
# =============================================================================

SHELL := /usr/bin/env bash
.DEFAULT_GOAL := help

TRACK ?= starter
LAB ?= all
SANDBOX_DEMO_MODE ?= shell
SKILL_DIR ?= $(TRACK)/skills_to_register/secure-code-review
SKILL_ZIP_OUT ?= dist/secure-code-review.zip
PYTHON ?= python3

# Helper shell snippet to load `.env` without breaking on comments or quotes
LOAD_ENV = set -a; [ -f .env ] && source .env; set +a

.PHONY: help install lint build-sandbox push-sandbox sandbox-lifecycle-demo \
        push-agent tf-plan tf-apply package-skill eval-offline eval-simulated \
        validate-skills verify-lab

help: ## Print available workshop targets and usage examples
	@echo "Enterprise Coding Agent Workshop — Makefile Targets"
	@echo ""
	@echo "Usage: make <target> [TRACK=starter|solution] [LAB=1..7|all]"
	@echo "Current TRACK=$(TRACK)"
	@echo ""
	@awk 'BEGIN {FS = ":.*## "} /^[a-zA-Z0-9_-]+:.*## / {printf "  \033[36m%-24s\033[0m %s\n", $$1, $$2}' $(MAKEFILE_LIST)
	@echo ""
	@echo "Examples:"
	@echo "  make install"
	@echo "  make validate-skills"
	@echo "  make verify-lab LAB=1"
	@echo "  make TRACK=solution eval-offline"

install: ## Sync Python 3.11+ dependencies via uv for starter/ and solution/
	@echo "==> Syncing starter/ dependencies with uv..."
	cd starter && uv sync --dev
	@echo "==> Syncing solution/ dependencies with uv..."
	cd solution && uv sync --dev

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
		echo "WARNING: ruff not found on PATH; run 'make install' to install dev tools."; \
	fi

build-sandbox: ## Lab 2: Build the non-root BYOC coding sandbox Docker image locally
	@echo "==> Building BYOC coding sandbox image from $(TRACK)/sandbox_image..."
	docker build -t coding-sandbox:v1 $(TRACK)/sandbox_image

push-sandbox: ## Lab 2: Build and push BYOC sandbox image (SANDBOX_IMAGE_URI) via Cloud Build
	@$(LOAD_ENV); \
	if [ -z "$${GOOGLE_CLOUD_PROJECT:-}" ]; then \
		echo "ERROR: GOOGLE_CLOUD_PROJECT is not set. Copy .env.example to .env first." >&2; \
		exit 1; \
	fi; \
	LOC="$${GOOGLE_CLOUD_LOCATION:-us-central1}"; \
	URI="$${SANDBOX_IMAGE_URI:-$${LOC}-docker.pkg.dev/$${GOOGLE_CLOUD_PROJECT}/coding-agent-repo/coding-sandbox:v1}"; \
	echo "==> Submitting $(TRACK)/sandbox_image to Cloud Build -> $${URI}"; \
	gcloud builds submit "$(TRACK)/sandbox_image" \
		--tag="$${URI}" \
		--project="$${GOOGLE_CLOUD_PROJECT}"

sandbox-lifecycle-demo: ## Lab 2: Run Template -> Sandbox -> Pause -> Resume -> Snapshot -> Delete demo
	@$(LOAD_ENV); \
	echo "==> Running sandbox lifecycle demo in $(TRACK)/ (mode=$(SANDBOX_DEMO_MODE))..."; \
	cd $(TRACK) && uv run python -m coding_agent.tools.sandbox_lifecycle demo --mode "$(SANDBOX_DEMO_MODE)" --ttl 1800s

push-agent: ## Lab 3: Build and push trusted Agent Runtime BYOC image (AGENT_IMAGE_URI) via Cloud Build
	@$(LOAD_ENV); \
	if [ -z "$${GOOGLE_CLOUD_PROJECT:-}" ]; then \
		echo "ERROR: GOOGLE_CLOUD_PROJECT is not set. Copy .env.example to .env first." >&2; \
		exit 1; \
	fi; \
	LOC="$${GOOGLE_CLOUD_LOCATION:-us-central1}"; \
	URI="$${AGENT_IMAGE_URI:-$${LOC}-docker.pkg.dev/$${GOOGLE_CLOUD_PROJECT}/coding-agent-repo/coding-agent:v1}"; \
	echo "==> Submitting $(TRACK)/ Agent Runtime image to Cloud Build -> $${URI}"; \
	gcloud builds submit "$(TRACK)" \
		--tag="$${URI}" \
		--project="$${GOOGLE_CLOUD_PROJECT}"

tf-plan: ## Lab 3: Initialize, format-check, validate, and plan Terraform in $(TRACK)/terraform
	@echo "==> Running Terraform init / fmt / validate / plan in $(TRACK)/terraform..."
	terraform -chdir=$(TRACK)/terraform init
	terraform -chdir=$(TRACK)/terraform fmt -check
	terraform -chdir=$(TRACK)/terraform validate
	terraform -chdir=$(TRACK)/terraform plan

tf-apply: ## Lab 3: Initialize and apply Terraform in $(TRACK)/terraform
	@echo "==> Applying Terraform configuration in $(TRACK)/terraform..."
	terraform -chdir=$(TRACK)/terraform init
	terraform -chdir=$(TRACK)/terraform apply

package-skill: ## Lab 5: Validate all 16 atomic Skill Registry rules and build skill .zip
	@echo "==> Validating and packaging $(SKILL_DIR) -> $(SKILL_ZIP_OUT)..."
	$(PYTHON) scripts/package_registry_skill.py "$(SKILL_DIR)" --output "$(SKILL_ZIP_OUT)"

eval-offline: ## Lab 6: Run offline evaluation over split single-turn and multi-turn datasets
	@$(LOAD_ENV); \
	echo "==> Running offline evaluation in $(TRACK)/..."; \
	cd $(TRACK) && uv run python eval/run_offline_eval.py \
		--single-turn-dataset eval/datasets/coding_agent_single_turn.json \
		--multi-turn-dataset eval/datasets/coding_agent_multi_turn.json

eval-simulated: ## Lab 6: Run 2-step simulated user evaluation personas
	@$(LOAD_ENV); \
	echo "==> Running simulated user evaluation in $(TRACK)/..."; \
	cd $(TRACK) && uv run python eval/run_simulated_eval.py --count 5 --max-turns 5

validate-skills: ## Validate all Antigravity workshop skills under .agents/skills/
	@echo "==> Validating .agents/skills/..."
	$(PYTHON) scripts/validate_skills.py .agents/skills

verify-lab: ## Verify Labs 1-7 checkpoints locally (usage: make verify-lab LAB=1..7|all)
	@echo "==> Running verify_lab.sh for LAB=$(LAB) (TRACK=$(TRACK))..."
	./scripts/verify_lab.sh "$(LAB)" --track "$(TRACK)"
