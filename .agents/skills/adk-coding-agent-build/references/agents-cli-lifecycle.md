# `google/agents-cli` Coding-Agent Lifecycle, Scaffolding, Extensions & Recipes Reference

Verified reference for `google/agents-cli` (`~= 1.15.0`) covering installation, scaffolding (`create`, `enhance`, `upgrade`), local iteration (`run`, `playground`, `lint`), evaluation/infra/deploy/publish handoff boundaries, custom extensions (`agents-cli-extension/v1alpha1`), curated `google/adk-recipes`, and co-trigger anti-shadowing boundaries against the 7 built-in `google-agents-cli-*` skills.

---

## 1. Prerequisites, Installation, Auth & Telemetry

- **Required Tooling:** Python **3.11+**, `uv`, Node.js (for `npx skills add`), `gcloud`, `terraform` (`>= 1.5.0` for infra/GKE).
- **Install & Refresh Commands:**
  ```bash
  # Recommended: installs agents-cli + ADK packages + all 7 built-in skills into detected IDEs
  uvx google-agents-cli setup

  # Alternative installs
  pipx install google-agents-cli && agents-cli setup
  pip install google-agents-cli && agents-cli setup

  # Skills only (no CLI install)
  npx skills add google/agents-cli

  # Reinstall/refresh skills or inspect CLI install path, version, manifest & active extensions
  agents-cli setup --skip-auth
  agents-cli update
  agents-cli info

  # Authenticate / inspect auth status
  agents-cli login
  agents-cli login --interactive
  agents-cli login --status
  ```
- **Telemetry Opt-Out (Enterprise Policy):** By default, `agents-cli` writes one structured usage log entry per command to your own GCP project (`logName=projects/<project>/logs/agents-cli`) and sends CLI/OS/command metadata in `User-Agent`/`X-Goog-Api-Client` headers. Opt out with either:
  ```bash
  export AGENTS_CLI_TELEMETRY=0   # Accepts 0, false, no, off (case-insensitive)
  export DO_NOT_TRACK=1
  ```
  Verify telemetry state with `agents-cli info`.

---

## 2. Project Scaffolding: `create`, `enhance`, `upgrade`

### Hard Constraints (Verified in `scaffold/SKILL.md` & `flags.md`)
1. **Project Name Rule:** Must be **<= 26 characters**, lowercase letters `a-z`, digits `0-9`, and hyphens `-` only.
2. **NEVER `mkdir <name>` Before `create`:** `agents-cli create` creates the directory itself; pre-creating it causes failure or unintended enhance mode.
3. **Strict Programmatic Mode by Default:** Missing required flags raise `UsageError` unless `-y` / `--yes` / `--auto-approve` or `-i` / `--interactive` is passed.
4. **Custom Agent Directories:** Pass `-dir` / `--agent-directory <pkg>` whenever agent code does not live in `app/` (e.g., `coding_agent` or `src/my_agent`).
5. **Removed Legacy Flags (DO NOT USE):** `--datastore`, `agentic_rag`, `agents-cli infra datastore`, and `agents-cli data-ingestion` have been removed — use `google/adk-recipes` instead.
6. **Never Hand-Write A2A Plumbing:** Both `adk_python` and `adk_go` templates ship working A2A routes automatically (`app/fast_api_app.py` / `main.go`).

### `agents-cli scaffold create` (Alias: `agents-cli create`) Flag Matrix

| Flag | Short | Default | Description & Verified Caveats |
|---|---|---|---|
| `--agent` | `-a` | `adk_python` (with `-y`) | Built-in: `adk_python` (alias `adk`), `adk_go`. Custom: `local@/path` or `<org>/<repo>[/<path>][@<ref>]` (e.g., `google/agents-cli-extensions/core/langchain/template`). |
| `--deployment-target` | `-d` | `agent_runtime` (with `-y`) | `agent_runtime`, `cloud_run`, `gke`, or `none` (code-only, still generates `Dockerfile`). |
| `--region` | — | `us-east1` | GCP region (e.g., `us-central1`). |
| `--prototype` | `-p` | off | Skip CI/CD and Terraform (recommended first pass; upgrade later with `scaffold enhance`). |
| `--adk` | — | off | Quickstart shortcut: `adk_python` + `agent_runtime` + `--prototype`, skips prompts. **Python only** (for Go use `--agent adk_go --prototype --yes`). |
| `--session-type` | — | — | `in_memory`, `cloud_sql`, `agent_platform_sessions` — for `cloud_run` / `gke` ONLY (`agent_runtime` manages sessions itself and overrides/clears `session_type`). |
| `--cicd-runner` | — | — | `github_actions`, `google_cloud_build`, `skip`. |
| `--agent-directory` | `-dir` | `app/` | Agent package folder inside the project (supports nested paths, e.g., `src/my_agent`). |
| `--agent-guidance-filename` | — | `GEMINI.md` | IDE guidance file: `GEMINI.md` (Antigravity), `CLAUDE.md`, or `AGENTS.md`. |
| `--output-dir` | `-o` | `.` | Parent output directory. |
| `--bq-analytics` | — | off | Enable `BigQueryAgentAnalyticsPlugin` (`agent_runtime`, `cloud_run`, `gke`). |
| `--memory-bank` | — | off | **Claude Agent SDK template ONLY** — for ADK agents, wire Memory Bank via ADK / `cross-session-memory` recipe. |
| `--agent-gateway` / `--no-agent-gateway` | — | off | Configures `Dockerfile` for `AGENT_GATEWAY_ROOT_CERTIFICATES` build arg and sets `agent_gateway: true` in `agents-cli-manifest.yaml`. |
| `--agent-runtime-identity-default` / `--cloud-run-identity-default` | — | Agent Identity | Pass `service_account` to opt out of default per-agent Agent Identity principal. |
| `--skip-checks` | `-s` | off | Skip GCP / Agent Platform prerequisite checks. |
| `--auto-approve` / `--yes` | `-y` | off | Non-interactive mode using defaults for omitted flags. |
| `--interactive` | `-i` | off | Interactive prompts/menus. |

### `agents-cli scaffold enhance` & `scaffold upgrade`

| Command / Key Flags | Purpose & Behavior |
|---|---|
| `agents-cli scaffold enhance . --from-adk-project --agent-directory coding_agent` | Adopts an existing ADK repository by writing **only** `agents-cli-manifest.yaml` (renders no template; **rejects** `--deployment-target` and template flags). Accepts `--name`, `--agent-directory`, `--region`, `--dry-run`, `--force`, `--yes`/`--interactive`. |
| `agents-cli scaffold enhance . -d agent_runtime` | Promotes a `--prototype` project to a deployment target (`agent_runtime`, `cloud_run`, `gke`, `none`). Also supports `--cicd-runner`, `--session-type`, `--bq-analytics`, `--agent-gateway`, `--dry-run`, `--force`, `--prefer-new`. |
| `agents-cli scaffold upgrade [path]` | Smart-merge upgrade to a newer `agents-cli` template version (`--dry-run`, `--auto-approve`, `--force`). Preserves agent code, config, `README.md`, guidance file, and eval datasets; `--force` is needed if the originating CLI version is absent from PyPI. |
| **Scaffold as Reference** | Run `agents-cli scaffold create ref-proj -o /tmp -a adk_python -d agent_runtime` to inspect Terraform/Dockerfile/CI templates without altering your live repo. |

---

## 3. Local Development, Testing & Eval Commands

### Develop & Smoke Test
```bash
agents-cli install                         # Runs uv sync + materializes pinned extensions
agents-cli lint                            # Runs Ruff code quality checks
agents-cli playground                      # Hot-reload ADK Web UI at http://localhost:8080
agents-cli run "Inspect workspace files"   # One-shot smoke test (-v / --verbose prints full JSON events)
agents-cli run "Next step" --start-server --session-id s1  # Persistent local server + multi-turn session reuse
agents-cli run "Check health" --url https://SERVICE_URL --mode adk   # Remote target (--mode a2a|adk)
```

> **Unit Tests vs. Eval Rule:** Use `uv run pytest` strictly for deterministic code contracts (imports, `BaseEnvironment` confinement, `BashToolPolicy`, schema validation). **Never** assert on non-deterministic LLM prose in unit tests — use `agents-cli eval`.

### Evaluation Command Summary (Handoff to `google-agents-cli-eval` / `agent-platform-optimize-and-eval`)
- `agents-cli eval run` — Chains `generate` + `grade`, writes `artifacts/grade_results/results_<ts>.{json,html}`, prints `RESULT: PASS|FAIL (...)`, exits `1` on missed threshold or errored case. Key flags: `--dataset`, `--metrics`, `--output`, `--config`, `--fail-under METRIC=SCORE`, `--region` (default `global`), `--mode adk_live`.
- `agents-cli eval generate` — Runs inference locally (via `fast_api_app.py` or `adk api_server`) or remotely (`--url`, `--app-name`). **Trap:** honors `.env` `GOOGLE_CLOUD_LOCATION` and takes **no** `--region` flag.
- `agents-cli eval grade` — Grades traces (`--traces`, `--config`, `--region`, `--qps` default `15`). **Multi-turn trap:** only `multi_turn_task_success`, `multi_turn_trajectory_quality`, and `multi_turn_tool_use_quality` accept multi-turn traces; other built-ins return HTTP `400`.
- `agents-cli eval dataset synthesize [--count N]` — Synthesizes user-simulated multi-turn traces (ADK Python).
- `agents-cli eval compare <base.json> <cand.json>` — Diffs two grade result runs to catch regressions.
- `agents-cli eval analyze --eval-result <file.json>` — LLM failure clustering (`global` region only).
- `agents-cli eval optimize --dataset <path> --target-metric <metric>` — ADK Python GEPA prompt tuning (expensive; run manually once after exhausting direct prompt edits).
- `agents-cli eval metric list` / `eval submit` / `eval results` — Metric catalog and cloud evaluation jobs.

---

## 4. Infra, Deploy & Publish Lifecycle Boundaries

Use this overview to coordinate build-time decisions with deployment and publishing; delegate deep Terraform/runtime/registry operations to `google-agents-cli-deploy`, `google-agents-cli-publish`, `agent-platform-runtime-and-state`, and `agent-platform-governance-and-registries`:

| Command | Critical Build-Time Rules & Verified Defaults |
|---|---|
| **`agents-cli infra single-project --apply`** | **Ordering Rule:** MUST run **before** first `agents-cli deploy` if you want Terraform-managed observability (prompt-response logging / BQ Agent Analytics). Never apply Terraform *after* an imperative Agent Runtime `deploy`. Note: `agents-cli deploy` does not auto-bind Terraform's `app_sa`; pass `--service-account SA_EMAIL` (ignored when Agent Identity is active). |
| **`agents-cli infra cicd`** | Provisions Workload Identity Federation (WIF), `cicd_runner_sa`, and staging + prod infrastructure. Cloud Build SA (`service-PROJECT_NUMBER@gcp-sa-cloudbuild.iam.gserviceaccount.com`) needs `roles/secretmanager.admin` in the CI/CD project for GitHub token access. |
| **`agents-cli deploy`** | **Defaults (Agent Runtime & Cloud Run):** `--cpu 1 --memory 4Gi --concurrency 8 --min-instances 0 --max-instances 10` (generated `service.tf` sets `min_instances = 1`; GKE rejects sizing flags). **Timeout Recovery:** Agent Runtime deploys take **5–10 min**; use `--no-wait` then poll `--status` every 60s. **Secrets Semantics:** `--secrets` **appends** on Cloud Run but **replaces all secrets** on Agent Runtime. **Non-interactive Automation:** Pass `--no-confirm-project` when omitting `--project`. **Other Flags:** `--env-vars`, `--agent-identity` / `--no-agent-identity`, `--network-attachment`, `--dns-peering-*`, `--agent-gateway-egress`/`--agent-gateway-ingress` (Agent Runtime + Agent Identity only), `--key` (CMEK, create-only), `--timeout` (Cloud Run up to `3600`s, default `300`s), `--iap`, `--image` (cannot combine with `--build-args`), `--dry-run`/`-n`, `--list`. |
| **`agents-cli publish gemini`** | Hidden alias `publish gemini-enterprise`. Auto-detects `AGENT_RUNTIME_ID` from `deployment_metadata.json`. **ADK mode** (default on Agent Runtime) invokes `:streamQuery` (`streaming_agent_run_with_events`) and supports `--authorization-id` OAuth; **A2A mode** is the only mode on Cloud Run/GKE & non-ADK (Python card `/a2a/{app_name}/.well-known/agent-card.json`, Go card `/.well-known/agent-card.json`; requires `roles/run.servicesInvoker` for `service-PROJECT_NUMBER@gcp-sa-discoveryengine.iam.gserviceaccount.com`). Live/voice agents are unsupported. Upgrade `google-cloud-aiplatform > 1.128.0` to avoid `"Session not found"`. |

---

## 5. Extensions System (`agents-cli-extension/v1alpha1`)

Extensions override individual built-in commands or register new subcommands via a single YAML manifest.

### Ad-Hoc Project Extension (`agents-cli-extension.yaml` at Repo Root)

Place `agents-cli-extension.yaml` next to `agents-cli-manifest.yaml` (auto-loaded at project scope without `extension add`; unknown keys fail loudly):

```yaml
# yaml-language-server: $schema=https://raw.githubusercontent.com/google/agents-cli/main/schemas/agents-cli-extension-v1alpha1.schema.json
schema: agents-cli-extension/v1alpha1
name: coding-agent-guardrails
description: Run skill validation and ruff lint before built-in deploy.
requires:
  agents_cli: ">=1.15,<2"   # Match lower bound to `agents-cli --version`
  on_incompatible: warn     # warn | error (blocks commands if CLI drifts out of range)

commands:
  override:
    deploy:
      run: ["uv", "run", "python", "scripts/guarded_deploy.py"]
      description: Pre-flight checks followed by built-in deploy.
    eval.generate:          # Dotted group.sub allowed; NEVER override whole group (e.g., `eval`)
      run: ["uv", "run", "python", "scripts/custom_eval_gen.py"]
      description: Custom trace generator.
  add:
    validate-skills:
      run: ["python3", "scripts/validate_skills.py", ".agents/skills"]
      description: Validate local .agents/skills/ frontmatter and links.
```

### Mandatory Extension Rules & Adoption Commands
- **No Shell Execution:** `run:` is an exec vector — always start with a program (`["uv", "run", "python", ...]`), never a bare script path. Relative paths resolve against `$AGENTS_CLI_EXTENSION_DIR`.
- **Safe Built-In Re-Invocation:** Overrides execute with `AGENTS_CLI_DISABLE_OVERRIDES=1`, so calling `agents-cli deploy "$@"` inside a wrapper script invokes the built-in command without infinite recursion.
- **Cannot Override a Group:** Override `eval.generate` (specific subcommand), never `eval`.
- **Scopes & Conflicts:** Project scope (`agents-cli-extensions.yaml` + vendored `extensions/`) beats user scope (`--global`, `~/.config/agents-cli/`). Within the same scope, first-wins (inspect with `agents-cli info`). Skill directories owned by an extension carry a `.agents-cli-extension` marker and are replaced whole on `install`/`update`.
- **Trust & Pinning:** First-party repos (`google/agents-cli`, `google/agents-cli-extensions`, `google/adk-recipes`, `pypi@google-agents-cli-extensions`) are auto-trusted; third-party/local refs prompt unless `--yes` is passed.
  ```bash
  agents-cli extension add <org>/<repo>#<name> --ref v1.2.0       # Project scope (git tag pin)
  agents-cli extension add pypi@acme-extensions==1.2.0 --global   # User scope (wheel sha256 pin)
  agents-cli extension add local@../my-ext                        # Local dev
  agents-cli extension list
  agents-cli extension update [<name>] [--to <ref|version|:latest>]
  agents-cli extension remove <name> [--global]
  ```

---

## 6. Official Curated Recipes (`google/adk-recipes`, `core/python/`)

Always **clone and read `AGENTS.md`** before building complex agent harness features from scratch (never scaffold directly from a recipe):

```bash
[ -d /tmp/adk-recipes ] || git clone --filter=blob:none --depth 1 --sparse \
  https://github.com/google/adk-recipes /tmp/adk-recipes
cd /tmp/adk-recipes && git sparse-checkout add core/python/long-horizon-harness
cat core/python/long-horizon-harness/AGENTS.md
```

| Recipe (`core/python/`) | Production Capabilities Covered (Complete Set of 11 Curated Recipes) |
|---|---|
| **`long-horizon-harness`** | **Primary coding-agent harness reference:** per-user sandbox, runtime-discovered `SKILL.md` loading, layered tool guardrails + exfil detection, durable mid-turn HITL, per-user secrets, sub-agent isolated contexts, compaction, A2A quirks, self-improvement Memory Bank loop |
| **`safety-plugins`** | Runner-wide `BasePlugin` safety guardrails (Model Armor / LLM-as-judge) across all sub-agents |
| **`cross-session-memory`** | Memory Bank write (`after_agent_callback`) + recall (`PreloadMemoryTool`) |
| **`ambient-expense-agent`** | Event-driven Pub/Sub `Workflow` + workflow pause HITL |
| **`ambient-quality-agent`** | AQuA production trace monitoring, failure clustering & root-cause analysis (ships as `agents-cli` extension) |
| **`oauth-user-consent-flow`** | OAuth 2.0 user consent working in both local ADK Web and Gemini app |
| **`deep-search`** | Plan-approval HITL + iterative search/critique/refine with citations |
| **`rag-agent-search`** / **`rag-vector-search`** | Managed Discovery Engine GCS connector vs. Vector Search 2.0 + KFP ingestion |
| **`genmedia-for-commerce`** | Multi-agent retail media + MCP toolsets + Veo pipelines |
| **`adk-voice-agent`** | Gemini Live (`run_live`) delegating background coding tasks + non-blocking tools + OAuth MCP gateway |

> **Console Prebuilt Samples (Agent Garden):** For curated one-click Agent Platform templates (RAG, multi-agent, and Terraform/Application Design Center blueprints deployable via `agents-cli`), see [Agent Garden](https://docs.cloud.google.com/gemini-enterprise-agent-platform/build/agent-garden).

---

## 7. Anti-Shadowing Map: Built-In `google-agents-cli-*` vs. Custom Workshop Skills

Users running `uvx google-agents-cli setup` already have **7 global built-in skills** installed. Keep responsibilities cleanly partitioned:

| Built-In Skill (`google/agents-cli` v1.15.0) | Owns | Companion Custom Skill & Unique Non-Overlapping Scope |
|---|---|---|
| `google-agents-cli-workflow` | Generic 8-phase lifecycle, `.agents-cli-spec.md`, code preservation rules | **`adk-coding-agent-build`** — Coding-agent ADK toolsets (`EnvironmentToolset`, `BaseEnvironment`, `LocalEnvironment`, `ExecuteBashTool`), ADK 2.0 coding loops, SDK namespace/version pitfalls, extension & recipe boundaries |
| `google-agents-cli-adk-code` | Generic ADK Python/Go API cheatsheet | **`adk-coding-agent-build`** — Source-verified `BaseEnvironment`/`EnvironmentToolset`/`BashToolPolicy` internals & ADK 2.0 Native Design Contract |
| `google-agents-cli-scaffold` | Generic `scaffold create/enhance/upgrade` flows | **`adk-coding-agent-build`** — Coding-agent manifest adoption (`--from-adk-project --agent-directory`) & extension manifests |
| `google-agents-cli-deploy` | Imperative `agents-cli deploy`, CI/CD, basic secrets/gateway flags | **`agent-platform-sandbox-byoc`** (BYOC sandboxes/snapshots/egress), **`agent-platform-runtime-and-state`** (declarative Terraform `google_vertex_ai_reasoning_engine`, quotas, Sessions, Memory Bank, Feedback), **`agent-runtime-vs-gke-architecture`** (GKE Agent Sandbox CRDs & 14-dimension matrix) |
| `google-agents-cli-publish` | `agents-cli publish gemini` & basic Agent Registry CLI | **`agent-platform-governance-and-registries`** — Skill Registry 16 ZIP/`SKILL.md` rules, `GCPSkillRegistry`/`AgentRegistry` ADK clients, Semantic Governance (NLC), SPIFFE Agent Identity, IAM UAPs, Model Armor |
| `google-agents-cli-eval` & `google-agents-cli-observability` | Local `agents-cli eval`, Cloud Trace, BQ Agent Analytics | **`agent-platform-optimize-and-eval`** — Managed Online Evaluation Monitors, Cloud Monitoring Quality Alerts, 2-Step Simulated User Eval, Failure Clustering, Optimize Flywheel |

---

## 8. Troubleshooting & Verification Checklist

| Symptom | Cause | Fix |
|---|---|---|
| `UsageError` on `agents-cli create` | Strict programmatic mode requires explicit flags | Pass `-a adk_python -d agent_runtime` (or `-y` / `--adk`). |
| `agents-cli create` enters enhance mode or fails | Pre-created folder with `mkdir <name>` or name `> 26` chars | Delete empty dir; choose `<= 26` char lowercase `[a-z0-9-]` name. |
| `agents-cli run` cannot locate `coding_agent` | Missing `agents-cli-manifest.yaml` or wrong `agent_directory` | Run `agents-cli scaffold enhance . --from-adk-project --agent-directory coding_agent` and verify via `agents-cli info`. |
| Prompt-response logging missing after `deploy` | Ran `agents-cli deploy` before `agents-cli infra single-project --apply` | Provision `infra single-project --apply` *before* first deploy. |
| `agents-cli deploy` hangs/times out in terminal | Agent Runtime build takes 5–10 minutes | Re-run with `--no-wait` and poll `agents-cli deploy --status` every 60s. |
| `agents-cli` skills appear stale or missing | Outdated IDE skill registration | Run `agents-cli setup --skip-auth` or `agents-cli update`, then verify with `agents-cli info`. |

### Verification Commands
```bash
agents-cli info                     # Confirm CLI version (~=1.15.0), manifest agent_directory, extensions, telemetry
agents-cli lint                     # Confirm clean Ruff lint across project
agents-cli run "List workspace" -v  # Confirm tool calls and JSON event stream locally
agents-cli deploy --dry-run         # Preview deployment pipeline and read-only GCP checks without mutating infra
```
