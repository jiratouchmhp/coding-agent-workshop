# Facilitator Guide & Instructor Runbook

**For:** Customer Engineers, Solutions Architects, and lab proctors running this workshop.  
**Tracks:** Full-Day (7h 00m total across Labs 0–7 + Architecture Guide 08, or 6h 25m without Optional Lab 7) · Half-Day (3h 30m: Lab 1A + Labs 2, 4, 5 hands-on; Labs 3 & 6 live demos; Lab 1B & Lab 7 skipped; Architecture Guide 08 Q&A).  
**Companion files:** [`README.md`](../README.md) · [`00-WORKSHOP-OVERVIEW.md`](./00-WORKSHOP-OVERVIEW.md) · [`scripts/verify_lab.sh`](../scripts/verify_lab.sh) · [`scripts/fast_forward_lab.sh`](../scripts/fast_forward_lab.sh)

---

## 1. Project Setup, Bangkok-First Regions & Zero-Docker Playbook

### Dedicated vs. Shared GCP Projects

Give every attendee **1 dedicated billing-enabled GCP project** whenever you can. A shared project works only for small cohorts and requires quota increases ahead of time:

| Topology | Cohort Size | Trade-Offs |
|---|---|---|
| **1 Project per Attendee (Recommended)** | Any (5–100+) | Zero quota collisions (`10/min` runtime writes, `90` QPM, `300/min` session appends); isolated Agent Registry namespaces and Online Monitor P4SAs. |
| **Shared Project** | 8–10 max | Fast when only one sandbox project exists, but requires T-7d quota increases and unique `ATTENDEE_ID` prefixes on Terraform display names, AR images, templates, and Skill IDs. |

### Bangkok-First Defaults

Keep the cohort on one consistent regional config (full matrix in [00-WORKSHOP-OVERVIEW.md](./00-WORKSHOP-OVERVIEW.md#regional-availability)):

- **Bangkok (`asia-southeast3`) default:** Artifact Registry (`AR_LOCATION`), Cloud Build (`BUILD_LOCATION`), Secret Manager, Agent Registry A2A/MCP (`AGENT_REGISTRY_LOCATION`), and GKE reference manifests in Architecture Guide 08 (`GKE_LOCATION`). One Bangkok AR repo pulls directly into both Singapore Agent Runtime and Singapore BYOC Sandboxes.
- **Singapore (`asia-southeast1`) fallback:** Agent Runtime, Managed Sandboxes, Managed Sessions, Memory Bank, Agent Gateway (`GOOGLE_CLOUD_LOCATION`), and optional `gemini-4-argon` if a customer requires regional model inference.
- **`global`:** Gemini 4 (`gemini-4-hydrogen` / `gemini-4-neon`, `MODEL_LOCATION`), Gen AI Evaluation Service (`EVAL_LOCATION`, includes `generate_loss_clusters`), and `gcloud alpha agent-registry skills` (`AGENT_REGISTRY_SKILLS_LOCATION`).
- **`us-central1`:** Vertex AI Skill Registry preview (`SKILL_REGISTRY_LOCATION`).

For US or EMEA cohorts, you can collapse all regional vars to `us-central1` or `europe-west4` while keeping `MODEL_LOCATION=global`, `EVAL_LOCATION=global`, and `AGENT_REGISTRY_SKILLS_LOCATION=global`.

### Zero-Docker Attendee Playbook

Assume corporate laptops do not have Docker Desktop, root access, or `python3-venv`. Every lab runs without local Docker:

1. **Bootstrap `uv` + `gcloud alpha`:** Install `uv` (`brew install uv`, `pipx install uv`, or the [official `uv` installation guide](https://docs.astral.sh/uv/getting-started/installation/)), run `gcloud components install alpha --quiet`, run `[ -f .env ] || cp .env.example .env`, and run `make preflight`.
2. **Lab 2 (BYOC Sandbox):** Smoke-test locally in pure Python (`make test-sandbox-local`), save `SANDBOX_IMAGE_URI` in `.env`, then build and push remotely via Bangkok Cloud Build (`make push-sandbox`). If a build lags, flip `SANDBOX_MODE=shell` in `.env` for instant Google-managed shell sandboxes in Singapore with zero image build.
3. **Lab 5 (Deploy Agent):** Smoke-test locally (`make test-agent-local`), then pick any of three zero-Docker paths: (a) save `AGENT_IMAGE_URI` in `.env` + `make push-agent` + `make tf-apply` (`container_spec`), (b) `make pack-agent-source` (`<= 8 MB` tarball with level-0 `Dockerfile`) + Terraform `source_code_spec` + empty `image_spec {}` (zero Docker and zero AR push), or (c) `agents-cli deploy --region asia-southeast1`.

---

## 2. Instructor Pre-Flight Checklist (T-7d, T-1d, T-0)

### T-7 Days: Projects, Quotas & Scope Decisions

- [ ] Confirm **standard billing-enabled** GCP projects (never Express Mode free tier; see Section 3).
- [ ] For shared projects, run the quota formula in Section 3 and request increases in `asia-southeast1` (allow 2–5 business days).
- [ ] Check Org Policies: confirm `constraints/gcp.resourceLocations` allows `asia-southeast3`, `asia-southeast1`, `us-central1`, and `global`; disable `constraints/iam.managed.disableAccessPolicyBindings` only if running Optional Lab 7 IAM UAPs.
- [ ] Decide **Lab 7** (skip cleanly for Half-Day or orgless sandbox projects). **Module 8 (Architecture Guide)** is a read-only decision briefing with ready-to-inspect `starter/gke_reference/` manifests, so no coding lab and no live GKE cluster are needed.

### T-1 Day: APIs, Service Agents, Pre-Warming & Live Dry Run

- [ ] Enable all workshop APIs across target project(s) (include the bottom 7 APIs if running Optional Lab 7):

```bash
gcloud services enable \
  aiplatform.googleapis.com artifactregistry.googleapis.com cloudbuild.googleapis.com \
  secretmanager.googleapis.com telemetry.googleapis.com cloudtrace.googleapis.com \
  logging.googleapis.com monitoring.googleapis.com pubsub.googleapis.com \
  storage-component.googleapis.com agentregistry.googleapis.com \
  networkservices.googleapis.com networksecurity.googleapis.com compute.googleapis.com \
  dns.googleapis.com iam.googleapis.com iap.googleapis.com modelarmor.googleapis.com \
  --project="$GOOGLE_CLOUD_PROJECT"
```

- [ ] **Pre-create the Bangkok AR repo and grant all 3 Google-managed service agents** upfront (prevents `IMAGE_PULL_BACKOFF`):

```bash
export PROJECT_NUMBER="$(gcloud projects describe "$GOOGLE_CLOUD_PROJECT" --format='value(projectNumber)')"
export AR_LOCATION="${AR_LOCATION:-asia-southeast3}"

gcloud alpha services identity create --service=aiplatform.googleapis.com --project="$GOOGLE_CLOUD_PROJECT"
gcloud artifacts repositories create coding-agent-repo \
  --repository-format=docker --location="$AR_LOCATION" --project="$GOOGLE_CLOUD_PROJECT" || true

# 1. Agent Runtime Service Agent (Lab 5 runtime image)
gcloud projects add-iam-policy-binding "$GOOGLE_CLOUD_PROJECT" \
  --member="serviceAccount:service-${PROJECT_NUMBER}@gcp-sa-aiplatform-re.iam.gserviceaccount.com" \
  --role="roles/artifactregistry.reader"

# 2. Agent Sandbox Service Agent (Lab 2 BYOC sandbox image - distinct identity!)
gcloud artifacts repositories add-iam-policy-binding coding-agent-repo \
  --location="$AR_LOCATION" --project="$GOOGLE_CLOUD_PROJECT" \
  --member="serviceAccount:service-${PROJECT_NUMBER}@gcp-sa-vertex-sandbox.iam.gserviceaccount.com" \
  --role="roles/artifactregistry.reader"

# 3. Agent Platform Service Agent (secret_env under AGENT_IDENTITY + Shared VPC PSC-I)
gcloud projects add-iam-policy-binding "$GOOGLE_CLOUD_PROJECT" \
  --member="serviceAccount:service-${PROJECT_NUMBER}@gcp-sa-aiplatform.iam.gserviceaccount.com" \
  --role="roles/secretmanager.secretAccessor"
```

- [ ] **Pre-warm instructor demo assets:** Push `solution/sandbox_image` (`coding-sandbox:v1`) and `solution/` (`coding-agent:v1`) to Bangkok AR as known-good fallback URIs, create 1 warm `SandboxEnvironmentTemplate` in `asia-southeast1` (cuts live demo cold start from ~2 min to seconds), and create 1 Online Evaluation Monitor at least **30 minutes before Lab 6** so the first-time P4SA permission propagation finishes off-stage.
- [ ] Run static checks and the **live GCP E2E dry run** (~16–17 min total; confirm every step reports `PASS` and `leaks=0`):

```bash
python3 scripts/validate_skills.py .agents/skills
python3 scripts/package_registry_skill.py solution/skills_to_register/secure-code-review --dry-run
./scripts/verify_lab.sh all --track solution && ./scripts/verify_lab.sh 7 --track solution && ./scripts/verify_lab.sh 8 --track solution
./scripts/live_gcp_e2e_validate.sh --project <SANDBOX_PROJECT_ID>
```

### T-0 (60 Minutes Before Kickoff)

- [ ] Confirm `gcloud alpha` is installed (`gcloud components install alpha --quiet`) and pre-run `make install` on lab images so 30 laptops don't saturate conference Wi-Fi downloading wheels.
- [ ] Remind the room that local `agents-cli` and local `agy` are optional (`make test-agy-harness` runs via `--dry-run`, and Cloud Build bakes `/usr/local/bin/agy` into Lab 2 & Lab 5 containers).
- [ ] Have attendees run `gcloud auth login`, `gcloud auth application-default login`, `gcloud config set project "$GOOGLE_CLOUD_PROJECT"`, `gcloud auth application-default set-quota-project "$GOOGLE_CLOUD_PROJECT"`, `make preflight`, and `make install`.
- [ ] Brief proctors on the `gcloud 588.0.0` alpha skills quirk: `skills create --payload=...` drops `--payload` on the wire and rejects 2-char IDs like `v1`. Always use the 2-step flow (bare `skills create` -> `revisions create rev-1 --skill=private-<id> --payload=<zip>`) and promote with `--target-state=active` (plus `--scanning-policy=enabled-nonblocking` for live demos).
- [ ] Post the room cheat-sheet: region defaults, fallback `SANDBOX_IMAGE_URI`, `SANDBOX_MODE=shell`, and `make fast-forward LAB=N`. Note that Cloud Shell works for all zero-Docker labs (skip local Docker builds there; Module 8 is a read-only briefing so no GKE cluster is needed).

---

## 3. Shared-Project Quota Sizing & Express Mode Check

Use these formulas when `U` attendees share one GCP project in `asia-southeast1`, with `X = 2` QPM/attendee during interactive labs (`4` during Lab 6 eval bursts), `Y = 12` session events per turn, and a `1.5x` spike buffer:

- `Target Query QPM = U * X * 1.5`
- `Target Session Appends/min = U * X * Y * 1.5`
- `Target Runtime Writes/min >= max(20, U * 1.5)` (default is only `10/min`!)
- `Target Entities = U * 3 * 1.25`

| Cloud Quotas Metric | Default | 10 Users | 25 Users | 50 Users | 100 Users |
|---|---:|---:|---:|---:|---:|
| `reasoning_engine_service_query_requests` (/min) | 90 | 30 | 75 (ask 150) | **150** | **300** |
| `session_event_append_requests` (/min) | 300 | **360** | **900** | **1,800** | **3,600** |
| `session_write_requests` (/min) | 100 | 30 | 75 | **150** | **300** |
| `reasoning_engine_service_write_requests` (/min) | 10 | **15** | **40** | **75** | **150** |
| `reasoning_engine_service_entities` | 100 | 38 | 94 (ask 150) | **188** | **375** |
| `memory_bank_write_requests` / `read_requests` (/min) | 100 / 300 | 30 / 60 | 75 / 150 | **150** / 300 | **300 / 600** |
| `sandbox_environment_entities` / `execute_requests` | 1,000 / 1,000 | 30 / 60 | 75 / 150 | 150 / 300 | 300 / 600 |

> [!WARNING]
> **Hard non-adjustable revision ceilings:** `6,000` revisions per project/region and `950` revisions per agent cannot be increased. On reused training projects, set `revision_garbage_collection_strategy.keep_n_latest.max_revisions = 20` and clean up engines after each session.

**Express Mode check (T-0):** Express Mode (`GOOGLE_GENAI_API_KEY`) caps a project at 10 resources, 10 QPM, 30 session appends/min, and blocks BYOC Sandboxes, Terraform IAM, Registries, and Alerts. Run this on any attendee machine throwing early `429` or auth errors:

```bash
env | grep -E "GOOGLE_GENAI_API_KEY|GEMINI_API_KEY|GOOGLE_CLOUD_PROJECT"
unset GOOGLE_GENAI_API_KEY GEMINI_API_KEY
export GOOGLE_GENAI_USE_ENTERPRISE="TRUE"
```

---

## 4. Pacing, Async Waits & Cutover Checkpoints

### Pacing & What to Teach While Builds Run

| Module | Full-Day | Half-Day | Async Wait Choreography |
|---|---|---|---|
| **00. Overview** | 0:00–0:20 | 0:00–0:10 | Run `make preflight`, verify `.agents/skills/` loaded, explain Bangkok-first regions |
| **01. Build ADK** | 0:20–1:20 | 0:10–0:45 | Part A (30m core): Gemini 4 + `LlmAgent` + `LocalEnvironment`. Part B (30m optional): skip if tight; reset `AGENT_ARCHITECTURE=simple` before Lab 2 |
| **02. BYOC Sandbox** | 1:20–2:20 | 0:45–1:25 | Kick off `make push-sandbox` (~1–2m) and template warm pool (up to 2m), then teach gVisor isolation & egress while they build |
| Morning Break | 2:20–2:30 | 1:25–1:35 | Doubles as Lab 2 catch-up buffer |
| **03. Sessions & Memory** | 2:30–3:10 | 1:35–1:50 (demo) | Reuses Lab 2's backing instance (`REASONING_ENGINE_NAME`). Use `wait_for_completion=True` on Memory Bank demos |
| **04. Registries** | 3:10–3:50 | 1:50–2:20 | Run `package_registry_skill.py --dry-run`, upload directory (not `.zip`) to `us-central1`, wire `GCPSkillRegistry` & Bangkok `AgentRegistry` before Lab 5 |
| Lunch Break | 3:50–4:30 | - | Full-Day only |
| **05. Deploy Once** | 4:30–5:15 | 2:20–2:50 | Kick off `make push-agent` (~2–3m) + `make tf-apply` (~2–5m), then explain HTTP contract, `dynamic "env"`, revisions & emergency stop |
| **06. Eval & Alerts** | 5:15–5:55 | 2:50–3:05 (demo) | Show your pre-warmed Online Monitor; run split JSON offline eval (`global`), loss clusters, quality alert, and bounded `optimize_prompt.py --iterations 2 --batch-size 4` |
| **07. Security (Optional)** | 5:55–6:30 | Skipped | Skip whenever >15 min behind or on orgless sandbox projects; Labs 1–6 stay 100% green |
| **08. Architecture Guide (Read-Only)** | 6:30–7:00 | 3:05–3:30 (Q&A) | Read-only briefing (no coding lab, no live cluster): whiteboard Bangkok PDPA/BoT residency trigger, compare 4 options, and walk through `starter/gke_reference/` |

> [!TIP]
> **When to skip Lab 1 Part B or Lab 7:** Always skip both in the 3.5-hour Half-Day track, and skip either in Full-Day whenever the room slips >15 minutes behind or uses orgless sandbox projects without Organization Policies or Agent Gateways. Skipping Lab 7 keeps `make verify-lab LAB=all` 100% green, and skipping Lab 1 Part B leaves Labs 2–6 working cleanly (run `make fast-forward LAB=1` if you also want `make verify-lab LAB=1` and `LAB=all` 100% green).

<a id="52-hard-cutover-checkpoints-when-to-switch-from-starter-to-solution"></a>
### Hard Cutover Checkpoints

Call a **Yellow Light** (5 min left to debug) and enforce the **Red Light** catch-up command so the room moves together. `make fast-forward LAB=N` uses Python AST splicing on shared `coding_agent/agent.py` so it fills only Lab `N` without spoiling later labs' TODOs. If a laptop's `starter/` tree is badly broken, switch to `TRACK=solution` (or `cd solution && uv sync`).

| Lab | Yellow Light | Red Light Catch-Up | Verify Command |
|---|---|---|---|
| **Lab 1** | +22m (A) / +45m (B) | `make fast-forward LAB=1` | `make verify-lab LAB=1` |
| **Lab 2** | +45m | `make fast-forward LAB=2` | `make verify-lab LAB=2` |
| **Lab 3** | +28m | `make fast-forward LAB=3` | `make verify-lab LAB=3` |
| **Lab 4** | +28m | `make fast-forward LAB=4` | `make verify-lab LAB=4` |
| **Lab 5** | +32m | `make fast-forward LAB=5` | `make verify-lab LAB=5` |
| **Lab 6** | +28m | `make fast-forward LAB=6` | `make verify-lab LAB=6` |
| **Lab 7 (Optional)** | +25m | No starter TODOs; skip straight to Architecture Guide 08 | `make verify-lab LAB=7` |
| **Module 8 (Architecture Guide)** | +20m | Read-only briefing (no coding lab, no live cluster) | `make verify-lab LAB=8` (optional offline check) |
| **Full Reset** | Anytime | `cd solution && uv sync` (or `TRACK=solution`) | `make verify-lab LAB=all TRACK=solution` |

---

## 5. Top Troubleshooting Table

| Symptom / Error | Lab | Root Cause | Fix |
|---|---|---|---|
| `IMAGE_PULL_BACKOFF` deploying Agent Runtime | 5 | Missing `roles/artifactregistry.reader` on `gcp-sa-aiplatform-re`, or missing Terraform `depends_on` race | Grant `roles/artifactregistry.reader` to `service-NUM@gcp-sa-aiplatform-re.iam.gserviceaccount.com` (and `gcp-sa-aiplatform` for cross-project AR / `secret_env`), wire all IAM resources into `depends_on` |
| `IMAGE_PULL_BACKOFF` creating BYOC Sandbox template | 2 | Granted AR reader to `gcp-sa-aiplatform-re` instead of the Sandbox service agent | Grant `roles/artifactregistry.reader` on the AR repo to `service-NUM@gcp-sa-vertex-sandbox.iam.gserviceaccount.com` and use `http_options={"api_version": "v1beta1"}` |
| BYOC `send_command()` returns HTTP 401 (`Missing or invalid issuer (iss) claim`) from laptop | 2 | `send_command()` rejects raw ADC OAuth2 bearer tokens and requires a signed JWT via `generate_access_token()` | Without `SANDBOX_SERVICE_ACCOUNT_EMAIL`, delegate plain BYOC commands to `execute_bash()` (caller ADC, ~12ms); set `SANDBOX_SERVICE_ACCOUNT_EMAIL` + `roles/iam.serviceAccountTokenCreator` only when testing `/exec` `env` or `/health` (auto-wired in Lab 5 Terraform) |
| `make push-sandbox` / `make push-agent` ignores custom image URI or `AR_REPO` | 2, 5 | Blank `SANDBOX_IMAGE_URI=` / `AGENT_IMAGE_URI=` in `.env` overrides shell exports on `source .env`; `Makefile` reads `AR_REPOSITORY` | Update `SANDBOX_IMAGE_URI` / `AGENT_IMAGE_URI` (and `AR_REPOSITORY`) directly in `.env` before running `make push-*`; always update or clear `REASONING_ENGINE_NAME` and `REASONING_ENGINE_ID` together |
| `execute_code()` or `send_command()` fails on Shell Sandbox | 2 | Wrong API for `shell_environment` (also, each bash call spawns a fresh shell) | Use `client.sandboxes.execute_bash(name=..., command=..., cwd="/workspace", timeout=120)` and persist state under `/workspace` |
| `generate_memories_from_session()` returns HTTP 404 on a live session | 3 | `vertex_session_source` rejects custom string `session_id`s (like `workshop-sess-...`) | Create the source session with `session_id=None` so Vertex assigns a server-generated numeric ID; use `set -a && source .env && set +a` before running CLI checks |
| `source_code_spec` fails (`Dockerfile not found` or size error) | 5 | Tarred parent folder instead of directory contents, or `.tar.gz > 8 MB` | Use `make pack-agent-source` (verifies level-0 `Dockerfile` and `<= 8 MB`, excluding `.venv/` and `__pycache__/`) |
| `gcp-skill-registry` missing on 1st call, or `SKILL_ID` locked after delete | 4 | Built-in registry ingests async on 1st call; deleted `SKILL_ID` stays reserved 24h+ | Call `skills.list()` a second time; pick a versioned ID (`secure-code-review-v2`); always pre-check with `package_registry_skill.py --dry-run` |
| `gcloud alpha agent-registry skills` fails (`source is required`, `STATE_DRAFT` HTTP 400, or delete blocked) | 4, 6, 7 | `gcloud 588.0.0` drops `--payload` on `skills create`; skills default to `STATE_DRAFT`; `skills delete` has no `--force` | Use 2-step flow (bare `skills create` -> `revisions create rev-1 --skill=private-<id> --payload=<zip>`); pass `--target-state=active` on `skills update` (and `--scanning-policy=enabled-nonblocking` for demos); on teardown run `--clear-default-revision --target-state=disabled` -> delete revisions -> delete skill |
| `ImportError` importing `AgentRegistry` | 4 | Bare `google-adk` lacks `a2a-sdk` and Agent Identity extras | Install `"google-adk[a2a,agent-identity,mcp]>=2.0.0"` or run `make install` |
| Code inside Sandbox cannot reach Vertex AI, PyPI, or `169.254.169.254` | 2, 4 | Sandboxes default to `internet_access=False`, zero IAM, and block metadata server | Keep Vertex AI / Skill Registry calls in Agent Runtime; bake deps into `sandbox_image/Dockerfile`; attach PSC-I (`network_attachment`, min `/28`) + NGFW for VPC egress |
| `LocalEnvironment` `.resolve()` error, or `BaseEnvironment` loses `ctx.state` | 1, 2 | Passed `str` instead of `Path`, or omitted keyword-only `*, ctx: Context \| None = None` | Pass `LocalEnvironment(working_dir=Path(...))`, put `max_output_chars` on `EnvironmentToolset`, and keep `*, ctx: Context \| None = None` on all 5 `BaseEnvironment` overrides |
| ADK `"Session not found"` | 1, 3, 6 | `App.name` mismatch, `adk web --session_service_uri=...` ignores `.env`, or old SDK | Match `App.name` to package dir, export `GOOGLE_CLOUD_PROJECT` and `GOOGLE_CLOUD_LOCATION` in shell, and keep `google-cloud-agentplatform>=2.0.1` |
| Eval returns `400` or fails on `generate_loss_clusters` | 6 | Wrong region (`asia-southeast1` unsupported), mixed single+multi-turn cases, missing `metric=`, or ADK 2.15 trailing `end_of_agent` (`content=None`) events in simulated traces | Set `EVAL_LOCATION=global`, keep `coding_agent_single_turn.json` and `coding_agent_multi_turn.json` separate, pass explicit `metric=` to `generate_loss_clusters`, and strip `content=None` events before grading simulated traces (`num_cases_valid > 0`) |
| First Online Monitor shows `Failed` (`permission denied`) | 6 | Normal 10–30m P4SA IAM propagation delay on a project's first monitor | **Do not delete it.** Wait for the 10-min retry loop to flip it `Active`; only debug IAM if still `Failed` after 30 min |
| Traces lack prompt/response text | 3, 5, 6 | Set `OTEL_INSTRUMENTATION_GENAI_CAPTURE_MESSAGE_CONTENT=true` instead of enum `"EVENT_ONLY"` | Set `GOOGLE_CLOUD_AGENT_ENGINE_ENABLE_TELEMETRY=true`, `OTEL_SEMCONV_STABILITY_OPT_IN=gen_ai_latest_experimental`, and `OTEL_INSTRUMENTATION_GENAI_CAPTURE_MESSAGE_CONTENT=EVENT_ONLY` |
| `make test-agent-local` crashes (`agent_engine_id is required`) | 5 | `GOOGLE_CLOUD_AGENT_ENGINE_ID=""` is still present in `os.environ` | `unset GOOGLE_CLOUD_AGENT_ENGINE_ID` (never export `""`) and pop empty values in `main.py:get_runtime_app()` |
| `terraform destroy` fails (`contains child resources: sessions`) | 5 | Engine has live sessions/memories and lacks `FORCE` deletion policy | Set `deletion_policy = "FORCE"` on `google_vertex_ai_reasoning_engine` (or call `client.runtimes.delete(name=..., force=True)`) |
| Gemini 4 returns HTTP 404/501 or HTTP 400 on thinking config | 1, 5 | `gemini-4-hydrogen`/`neon` require `MODEL_LOCATION=global`; `MINIMAL` and `thinking_budget` are invalid | Route via `models.py` (`MODEL_LOCATION=global`, or `gemini-4-argon` on `asia-southeast1`), keep `THINKING_LEVEL` in `LOW\|MEDIUM\|HIGH\|XHIGH`, and require `google-genai>=2.34.0` |
| `agy` exits `1`/`2`/`3` (`invalid project ID: "<NUMBER>"`) or empty `stream-json` | 1B, 2, 5 | Agent Runtime injects numeric project number into `GOOGLE_CLOUD_PROJECT`; air-gapped sandbox has no ADC; `agy 1.5.15` nests `step_update`/`result` | Pass non-numeric `AGY_PROJECT_ID = var.project_id` + `AGY_ADC_AUTH=true` + `GOOGLE_CLOUD_LOCATION=global` in Agent Runtime; keep `AGY_EXECUTION_MODE=local`/`auto`; unwrap nested `agy 1.5.15` JSON envelopes |

<details>
<summary>More edge-case fixes (Lab 1B Workflows, Lab 7 Governance, Module 8 GKE &amp; SDK quirks)</summary>

- **Lab 1B Graph/Dynamic/Collaborative/ManagedAgent:** Converge parallel branches into one `JoinNode` (every predecessor must emit output) and bound graph loops with `MAX_FIX_ROUNDS`. Decorate dynamic orchestrators with `@node(rerun_on_resume=True)` and leaf HITL nodes with `rerun_on_resume=False`, never catch `BaseException`, and include a non-numeric char in custom `run_id` (`f"check-{name}"`). In Python ADK, `{key}` reads session state (not `node_input`) and nodes emit at most one `Event(output=...)`. Keep `mode` off root agents, keep `mode="task"` on leaf collaborative subagents only, and note `ManagedAgent` (v2.4.0 preview) is `global`-only for server-side tools.
- **ADK `State` (`google-adk==2.15.0`):** `ctx.state` has `.get()`, `.setdefault()`, `.update()`, `.to_dict()`, not `.pop()`, `.keys()`, or `__delitem__`. Clear keys with `state[key] = None`.
- **SDK `agentplatform==2.10.0` quirks:** Sandbox/snapshot/template `.delete(name=...)` rejects `config={"wait_for_completion": True}` (poll returned LROs sequentially `sandboxes -> snapshots -> templates`); `.list()` returns an iterator directly; `sessions.create()` `op.response` can be `None` even though `hasattr(op, "response")` is `True`; `AdkApp.async_search_memory` takes `(user_id, query)` only (no `app_name`).
- **Lab 6 Optimizer & Simulator (`adk==2.15.0`):** Override `SimplePromptOptimizerConfig` / `GEPARootAgentPromptOptimizerConfig` with `ThinkingConfig(thinking_level="MEDIUM", include_thoughts=True)` (removes legacy `thinking_budget=10240`) and pass `--optimizer_config_file_path` with `GOOGLE_CLOUD_LOCATION=global`. Expand `BaseToolset` via `get_tools()` before calling `AgentInfo.load_from_agent()`, and sanitize trailing `end_of_agent` (`content=None`) events before `client.evals.evaluate()`.
- **Lab 7 (Optional Governance):** If attendees already ran Lab 4 Step 3's optional standalone skill create, use a fresh skill ID (`secure-code-review-blocking`) to avoid `ALREADY_EXISTS`; `skills describe` prints `state: STATE_ACTIVE` (while `revisions describe` prints `state: ACTIVE`), and `findings list` logs a benign `filter keys were not present: resource` warning when 0 findings exist. Semantic Governance Policy Engine does not support streamed LLM responses (`:streamGenerateContent`); exclude gRPC (`!request.headers['content-type'].startsWith('application/grpc')`) in `AuthzPolicy` CEL; run `agents-cli infra single-project --apply` before first `agents-cli deploy`; remove `iamEnforcementMode` from IAP UAP metadata to switch out of `"DRY_RUN"`.
- **Module 8 (Architecture Guide GKE Notes):** Module 8 is read-only and uses no live cluster. If a team deploys the manifests later on their own cluster: bind `default/default` KSA via WIF for `adk deploy gke`; `whole-pod` Pod Snapshots require GKE `>= 1.35.3-gke.1234000`, gVisor, non-E2 nodes, no TPUs/GCS FUSE, and `PodSnapshot` `Ready` before `Suspended`; do not mix `google-adk==2.15.0` `GkeCodeExecutor` with `k8s-agent-sandbox==1.0.6` in the same venv; never run `kubectl delete -f sandbox-with-extensions.yaml` on a shared cluster.

</details>

---

## 6. Post-Workshop Cleanup (`make cleanup`)

Run cleanup right after the session so warm pools, `min_instances >= 1` runtimes, and Online Monitors stop billing.

```bash
# Preview first, then delete
make cleanup CLEANUP_ARGS=--dry-run
make cleanup
```

Quick manual verification pass after `make cleanup`:

1. **Online Monitors & Alerts:** Confirm Online Evaluation Monitors are disabled/deleted and temporary Cloud Monitoring alert policies are gone.
2. **Sandboxes, Snapshots & Templates (`asia-southeast1`):** Deleting a sandbox does not delete its template. If anything remains, run `cd solution && uv run python -m coding_agent.tools.sandbox_lifecycle cleanup-all --include-templates` (polls delete LROs in `sandboxes -> snapshots -> templates` order).
3. **Runtimes & Standalone Skills:** Wait ~1 minute after the last conversation if Memory Bank generation just fired, then confirm `deletion_policy = "FORCE"` before `terraform destroy` and delete any separate Lab 2/3 backing instance (`client.runtimes.delete(name=..., force=True)`). For `global` Agent Registry skills, run `skills update private-<id> --clear-default-revision --target-state=disabled` before deleting child revisions and the skill.
4. **Optional Lab 7 leftovers:** Delete `agent-siem-sink`, `agent-siem-events`, and `agent-audit-worm` (only if the retention lock is not set). Module 8 is a read-only briefing and creates zero live GKE resources by default (if you ran an off-script GKE demo in `asia-southeast3`, delete only `kubectl delete -f starter/gke_reference/ --ignore-not-found` or delete your dedicated cluster).
