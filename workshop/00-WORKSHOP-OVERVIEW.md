# 00: Workshop Overview & Setup

**Time needed:** 20 minutes (Full-Day) or 10 minutes (Half-Day). Complete the GCP setup checklist below before starting [Lab 1](01-LAB-SETUP-AND-BUILD-ADK.md).

---

## What You Are Building (and the Core Security Boundary)

A real coding agent has to read and edit repositories, run untrusted shell commands (`pytest`, `ruff`, `bandit`), remember project conventions across turns, pull approved internal skills, and ship to production with real monitoring.

One rule drives the entire design of this workshop: **keep your cloud credentials away from untrusted code execution.**

- **Agent Runtime (`ReasoningEngine`) holds credentials.** It runs as your dedicated custom service account (`coding-agent-runtime-sa`), calls Gemini 4 models, reads and writes Managed Sessions and Memory Bank, loads approved skills, and records traces and logs.
- **Managed Sandboxes (`SandboxEnvironment`) hold zero credentials.** Every LLM-generated shell command or test run executes inside an isolated gVisor container as an unprivileged `appuser` with no IAM roles, no Application Default Credentials (ADC), and no access to the metadata server (`169.254.169.254`).

We build the agent in order: **Labs 1–4** assemble and test every feature against managed cloud primitives (using a lightweight standalone backing instance created in Lab 2), so **Lab 5** packages and deploys the full agent **once**. **Lab 6** adds evaluation, alerts, and prompt/skill tuning. **Lab 1 Part B** (extra ADK 2.0 architectures) and **Lab 7** (optional security hardening) skip cleanly without breaking any later lab.

---

## Starter Pack File Map

You do all your hands-on coding inside [`starter/`](../starter/). Repetitive boilerplate (configs, schemas, Dockerfiles, datasets, and helper runners) is already written for you so each lab focuses on a handful of `# TODO(lab-N)` markers. Every file has a finished twin in [`solution/`](../solution/).

### Files You Will Edit by Lab

| Lab | Editable Files in `starter/` | What You Implement |
|---|---|---|
| **Lab 1 (Part A)** | [`coding_agent/models.py`](../starter/coding_agent/models.py), [`coding_agent/agent.py`](../starter/coding_agent/agent.py) | Gemini 4 model factory (`MODEL_LOCATION=global`), local `EnvironmentToolset(LocalEnvironment)`, root `LlmAgent` |
| **Lab 1 (Part B, Optional)** | [`coding_agent/architectures.py`](../starter/coding_agent/architectures.py), [`coding_agent/tools/agy_headless_harness.py`](../starter/coding_agent/tools/agy_headless_harness.py) | Collaborative Team, Graph `Workflow`, Dynamic `@node` workflow, and `agy` headless CLI harness |
| **Lab 2** | [`coding_agent/tools/sandbox_lifecycle.py`](../starter/coding_agent/tools/sandbox_lifecycle.py), [`coding_agent/tools/sandbox_execution.py`](../starter/coding_agent/tools/sandbox_execution.py), [`coding_agent/agent.py`](../starter/coding_agent/agent.py) | Template/Sandbox/Snapshot lifecycle, Shell & BYOC `/exec` runners, custom `BaseEnvironment` adapter, and sandbox tool wiring |
| **Lab 3** | [`coding_agent/memory/session_manager.py`](../starter/coding_agent/memory/session_manager.py), [`coding_agent/memory/memory_bank_manager.py`](../starter/coding_agent/memory/memory_bank_manager.py), [`coding_agent/callbacks/telemetry_and_feedback.py`](../starter/coding_agent/callbacks/telemetry_and_feedback.py), [`coding_agent/agent.py`](../starter/coding_agent/agent.py) | Managed Sessions, Memory Bank generation and retrieval, OTel callbacks, parent sandbox logging, and Feedback API |
| **Lab 4** | [`coding_agent/tools/registry_loader.py`](../starter/coding_agent/tools/registry_loader.py), [`coding_agent/agent.py`](../starter/coding_agent/agent.py) | `GCPSkillRegistry` + `SkillToolset`, `AgentRegistry` A2A/MCP discovery, and wiring into the agent |
| **Lab 5** | [`main.py`](../starter/main.py), [`terraform/main.tf`](../starter/terraform/main.tf) | FastAPI Agent Runtime HTTP adapter (`GET /`, `/api/reasoning_engine`, `/api/stream_reasoning_engine`) and Terraform runtime + IAM |
| **Lab 6** | [`eval/run_offline_eval.py`](../starter/eval/run_offline_eval.py), [`eval/run_simulated_eval.py`](../starter/eval/run_simulated_eval.py), [`eval/setup_online_monitor.py`](../starter/eval/setup_online_monitor.py), [`eval/setup_quality_alerts.py`](../starter/eval/setup_quality_alerts.py), [`eval/optimize_prompt.py`](../starter/eval/optimize_prompt.py) | Split single/multi-turn offline eval, 2-step user simulator, online monitor check, Cloud Monitoring quality alerts, and prompt/skill tuning |

Lab 7 has zero `starter/` TODOs (CLI commands, policy checks, and Terraform review), and Module 8 is a read-only Architecture Information Guide (no coding lab, no live cluster).

### Pre-Built Files (No Edits Needed)

```text
starter/
├── pyproject.toml, requirements.txt         # Python 3.11+ deps (ADK 2.0+, google-genai>=2.34.0)
├── agents-cli-manifest.yaml                 # Tells agents-cli to load coding_agent/
├── Dockerfile, .dockerignore, .gcloudignore # Non-root Agent Runtime image (+ baked /usr/local/bin/agy)
├── services.yaml, services.py               # ADK 2.0 custom service registration examples
├── coding_agent/
│   ├── config.py                            # Typed env settings loader
│   └── train_eval_set.evalset.json          # ADK eval set for Lab 6 prompt optimization
├── sandbox_image/                           # Lab 2 non-root BYOC sandbox image (Debian + Python + Node + agy)
│   ├── Dockerfile, runner.py, requirements.txt
├── skills_to_register/secure-code-review/   # Lab 4 sample skill passing all 16 Skill Registry checks
│   ├── SKILL.md, references/owasp-checklist.md
├── terraform/                               # Supporting TF files alongside editable main.tf
│   ├── versions.tf, variables.tf, outputs.tf, terraform.tfvars.example
├── eval/                                    # Lab 6 configs and split JSON/JSONL datasets
│   ├── eval_config.yaml, sampler_config.json
│   └── datasets/coding_agent_{eval.jsonl,single_turn.json,multi_turn.json}
└── gke_reference/                           # Module 8 read-only GKE Agent Sandbox reference manifests (no edits needed)
    ├── rbac.yaml, sandbox_template.yaml, sandbox_warmpool.yaml, gke_agent_example.py
```

If you fall behind on any lab, run `make fast-forward LAB=N` from the repo root. It copies only Lab `N`'s completed functions from `solution/` into `starter/` without touching later labs' TODO markers (see [Hard Cutover Checkpoints](FACILITATOR-GUIDE.md#hard-cutover-checkpoints)).

---

## Schedules: Full-Day vs. Half-Day

| Module | Topic | Full-Day (7h 00m) | Half-Day (3h 30m) |
|---|---|---:|---:|
| **Lab 0** | Overview, starter map, GCP APIs, service agents, pre-flight | 20 min | 10 min |
| **[Lab 1](01-LAB-SETUP-AND-BUILD-ADK.md)** | **Part A (Core):** Gemini 4 + `LlmAgent` + `LocalEnvironment`. **Part B (Optional):** Collaborative, Graph, Dynamic, `agy_harness` | 60 min (30m A + 30m B) | 35 min (Part A + 5m overview) |
| **[Lab 2](02-LAB-CUSTOM-SANDBOX-BYOC.md)** | Backing instance, BYOC sandbox image, Bangkok Cloud Build, Singapore sandbox lifecycle & execution | 60 min | 40 min |
| Break | Morning coffee break | 10 min | 10 min |
| **[Lab 3](03-LAB-SESSIONS-MEMORY-FEEDBACK.md)** | Managed Sessions, Memory Bank, Feedback API, OTel traces & parent sandbox logs | 40 min | 15 min (live demo) |
| **[Lab 4](04-LAB-SKILLS-AND-AGENT-REGISTRY.md)** | Skill Registry 16-check packaging, `GCPSkillRegistry` + `SkillToolset`, Bangkok `AgentRegistry` | 40 min | 30 min |
| Break | Lunch break (Full-Day only) | 40 min | - |
| **[Lab 5](05-LAB-DEPLOY-RUNTIME-TERRAFORM.md)** | Build and deploy complete agent once via Bangkok Cloud Build + Singapore Terraform / `agents-cli` | 45 min | 30 min |
| **[Lab 6](06-LAB-OPTIMIZE-EVAL-AND-ALERTS.md)** | Offline & simulated eval (`global`), loss clustering, online monitors, alerts, prompt/skill tuning | 40 min | 15 min (live demo) |
| **[Lab 7](07-LAB-OPTIONAL-SECURITY-AND-GOVERNANCE.md)** | **Optional:** Blocking skill scans, NLC Semantic Governance, Model Armor, SPIFFE, CMEK/VPC-SC, WORM/SIEM/SCC | 35 min (optional) | Skipped |
| **[Architecture Guide (08)](08-ARCHITECTURE-AGENT-RUNTIME-VS-GKE.md)** | **Read-Only Briefing (no coding lab, no live cluster):** Agent Runtime vs. self-hosted GKE (`asia-southeast3`) decision guide & reference manifests | 30 min | 25 min (Q&A) |

> [!TIP]
> **Two ways to work through the TODOs:** Edit the `# TODO(lab-N)` markers manually, or open the repo in **Antigravity** so all 6 `.agents/skills/` auto-load and pair-program through each lab. Mix both freely, and use `make verify-lab LAB=N` at the end of every lab.

---

## Pre-Workshop Setup Checklist

No local Docker daemon is required for any lab. Local smoke tests (`make test-sandbox-local`, `make test-agent-local`, `make test-agy-harness`) run in pure Python, container builds run remotely on Cloud Build in Bangkok (`--region=asia-southeast3`), and Lab 5 also supports zero-Docker, zero-AR deploys with `make pack-agent-source`.

### Step 1: Authenticate GCP & Install `gcloud alpha`

```bash
gcloud auth login
gcloud auth application-default login
gcloud components install alpha --quiet
```

If `uv` is not installed yet (works without `python3-venv` or Docker), install it with your package manager (recommended) or follow the [official `uv` installation guide](https://docs.astral.sh/uv/getting-started/installation/):

```bash
brew install uv   # macOS/Linux Homebrew; or: pipx install uv
```

Optional local extras: run `uvx google-agents-cli setup` for `agents-cli` shortcuts, and install `agy` locally if you plan to run Lab 1 Part B live without `--dry-run`. Cloud Build bakes `/usr/local/bin/agy` into Lab 2 and Lab 5 containers automatically.

### Step 2: Configure `.env` and Shell Variables

```bash
[ -f .env ] || cp .env.example .env
# Edit .env and set GOOGLE_CLOUD_PROJECT and GOOGLE_CLOUD_PROJECT_NUMBER
# (keep the Bangkok-first regional defaults already populated in .env.example)

set -a && source .env && set +a
gcloud config set project "$GOOGLE_CLOUD_PROJECT"
gcloud auth application-default set-quota-project "$GOOGLE_CLOUD_PROJECT"
```

Verify `.env` exports the Bangkok-first defaults (`PRIMARY_REGION=asia-southeast3`, `AR_LOCATION=asia-southeast3`, `BUILD_LOCATION=asia-southeast3`, `AGENT_REGISTRY_LOCATION=asia-southeast3`, `GKE_LOCATION=asia-southeast3`, `GOOGLE_CLOUD_LOCATION=asia-southeast1`, `MODEL_NAME=gemini-4-hydrogen`, `REASONING_MODEL_NAME=gemini-4-neon`, `MODEL_LOCATION=global`, `THINKING_LEVEL=MEDIUM`, `SKILL_REGISTRY_LOCATION=us-central1`, `EVAL_LOCATION=global`, `AGENT_REGISTRY_SKILLS_LOCATION=global`).

### Step 3: Enable Required APIs & Provision Service Identities

```bash
gcloud services enable \
  aiplatform.googleapis.com \
  artifactregistry.googleapis.com \
  cloudbuild.googleapis.com \
  secretmanager.googleapis.com \
  logging.googleapis.com \
  monitoring.googleapis.com \
  telemetry.googleapis.com \
  cloudtrace.googleapis.com \
  agentregistry.googleapis.com \
  storage-component.googleapis.com \
  pubsub.googleapis.com \
  --project="$GOOGLE_CLOUD_PROJECT"

# Provision Google-managed Vertex AI / Reasoning Engine service agents upfront
gcloud alpha services identity create \
  --service=aiplatform.googleapis.com \
  --project="$GOOGLE_CLOUD_PROJECT"
```

Verify your user account holds `roles/aiplatform.admin` (or `roles/aiplatform.user`), `roles/serviceusage.serviceUsageAdmin`, `roles/artifactregistry.writer`, `roles/cloudbuild.builds.editor`, `roles/iam.serviceAccountUser` (+ `serviceAccountAdmin` for Lab 5 TF), `roles/secretmanager.admin`, `roles/logging.viewer`, and `roles/monitoring.alertPolicyEditor`.

> [!CAUTION]
> **Two different service agents pull container images.** Mixing them up is the #1 cause of `IMAGE_PULL_BACKOFF` in Labs 2 and 5:
> - **Agent Runtime** pulls via `service-PROJECT_NUMBER@gcp-sa-aiplatform-re.iam.gserviceaccount.com` (Lab 5).
> - **BYOC Sandbox** pulls via `service-PROJECT_NUMBER@gcp-sa-vertex-sandbox.iam.gserviceaccount.com` (Lab 2).
> - **Agent Platform** (`service-PROJECT_NUMBER@gcp-sa-aiplatform.iam.gserviceaccount.com`) handles `secret_env` under `AGENT_IDENTITY` and cross-project AR/PSC-I.

### Step 4: Run Pre-Flight & Sync Dependencies

```bash
make preflight        # Checks gcloud, ADC, APIs, uv, and regional vars (zero Docker needed)
make install          # Fast default: syncs starter/ deps with uv (use `make install-all` for both, or `make install-pip`)
make validate-skills  # Validates .agents/skills/
```

When you are done with the workshop, run `make cleanup` (`scripts/cleanup_workshop.sh`) to tear down sandboxes, templates, alert policies, and runtimes cleanly.

---

## Regional Availability

We default to **Bangkok (`asia-southeast3`)** wherever Google Cloud supports the service, and fall back to **Singapore (`asia-southeast1`)**, **`global`**, or **`us-central1`** only where required:

| Scope | Region & Env Vars | Workshop Services | Practical Notes |
|---|---|---|---|
| **1. Default (Bangkok)** | `asia-southeast3`<br/>`PRIMARY_REGION`, `AR_LOCATION`, `BUILD_LOCATION`, `AGENT_REGISTRY_LOCATION`, `GKE_LOCATION` | Artifact Registry, Cloud Build, Secret Manager, Agent Registry A2A/MCP discovery, GKE (Architecture Guide 08) | Keeps builds, images, secrets, and GKE in Bangkok. One Bangkok Artifact Registry repo pulls directly into both Singapore Agent Runtime and Singapore BYOC Sandboxes. |
| **2. Fallback (Singapore)** | `asia-southeast1`<br/>`GOOGLE_CLOUD_LOCATION` | Agent Runtime, Managed Sandboxes, Managed Sessions, Memory Bank, Agent Gateway, optional `gemini-4-argon` | Nearest region where Agent Platform services are live. Both Memory Bank and Agent Gateway are supported here (unlike `asia-southeast2`). |
| **3. Preview (`us-central1`)** | `us-central1`<br/>`SKILL_REGISTRY_LOCATION` | Vertex AI Skill Registry (`v1beta1`, Lab 4) | Preview is limited to `us-central1`, `europe-west4`, and `us-east5`. |
| **4. Global (`global`)** | `global`<br/>`MODEL_LOCATION`, `EVAL_LOCATION`, `AGENT_REGISTRY_SKILLS_LOCATION` | Gemini 4 (`gemini-4-hydrogen`, `gemini-4-neon`), Gen AI Evaluation Service, `gcloud alpha agent-registry skills` | `gemini-4-hydrogen` and `gemini-4-neon` require `MODEL_LOCATION=global` (decoupled via ADK `Gemini(client_kwargs=...)`). `global` Eval also supports `generate_loss_clusters` in the same client. |

**Gemini 4 quick rules:** Use `gemini-4-hydrogen` (fast coding) and `gemini-4-neon` (planning/review) on `MODEL_LOCATION=global`, or switch to `gemini-4-argon` on `asia-southeast1` if you need strict Singapore model residency. Set `THINKING_LEVEL` strictly to `LOW`, `MEDIUM`, `HIGH`, or `XHIGH` (`MINIMAL` and legacy `thinking_budget` return HTTP 400; `temperature`/`top_p`/`top_k` are ignored), and keep `google-genai>=2.34.0` for 1M-token long decodes.

Running in the US or EMEA instead of APAC? Set all regional env vars to `us-central1` or `europe-west4` while keeping `MODEL_LOCATION=global`, `EVAL_LOCATION=global`, and `AGENT_REGISTRY_SKILLS_LOCATION=global`. Note that Optional Lab 7's Semantic Governance Policy Engine (NLC) is currently in 8 US/EU regions.

---

## Optional Reference Details

<details>
<summary>Express Mode vs. Standard GCP Project (Why Labs 2–7 need billing)</summary>

Do **not** use Express Mode (`GOOGLE_GENAI_API_KEY`) or AI Studio (`GEMINI_API_KEY`) after Lab 1. Unset both keys before starting Lab 2.

| Capability / Quota | Express Mode (Free Tier) | Standard Billing GCP Project |
|---|---|---|
| Max Agent Platform resources | 10 | 100 per region |
| Query / StreamQuery per min | 10/min | 90/min (adjustable) |
| Concurrent `BidiStreamQuery` / min | 1/min | 10/min |
| Session writes / event appends per min | 10/min / 30/min | 100/min / 300/min |
| Memory Bank writes / reads per min | 10/min / 10/min | 100/min / 300/min |
| BYOC Sandboxes, Terraform IAM, PSC-I, Cloud Monitoring Alerts | Not supported | Fully supported |

</details>

<details>
<summary>Antigravity <code>.agents/skills/</code> Overview (6 bundled workshop skills)</summary>

Open this repository root in Antigravity to auto-load all 6 skills below. Each defines explicit `Don't use for:` boundaries so it complements the 7 global `google-agents-cli-*` skills from `uvx google-agents-cli setup`.

| Skill | Covers |
|---|---|
| [`adk-coding-agent-build`](../.agents/skills/adk-coding-agent-build/SKILL.md) | Lab 1: Gemini 4 `client_kwargs`, 5 ADK 2.0 architectures, `EnvironmentToolset`, `BaseEnvironment`, `agy` harness, `services.yaml`/`services.py` |
| [`agent-platform-sandbox-byoc`](../.agents/skills/agent-platform-sandbox-byoc/SKILL.md) | Lab 2: BYOC Dockerfile contract, Sandbox/Template/Snapshot lifecycle, Shell & Code Execution, PSC-I/NGFW egress |
| [`agent-platform-runtime-and-state`](../.agents/skills/agent-platform-runtime-and-state/SKILL.md) | Labs 3 & 5: Managed Sessions, Memory Bank, Feedback, OTel telemetry, Terraform `google_vertex_ai_reasoning_engine` |
| [`agent-platform-governance-and-registries`](../.agents/skills/agent-platform-governance-and-registries/SKILL.md) | Lab 4 & Lab 7: 16-check Skill Registry packaging, `GCPSkillRegistry`/`AgentRegistry`, blocking scans, NLC, SPIFFE |
| [`agent-platform-optimize-and-eval`](../.agents/skills/agent-platform-optimize-and-eval/SKILL.md) | Lab 6: Offline/Simulated/Online Eval, loss clustering, `monitoring_v3` alerts, prompt & skill optimization |
| [`agent-runtime-vs-gke-architecture`](../.agents/skills/agent-runtime-vs-gke-architecture/SKILL.md) | Architecture Guide 08: Agent Runtime vs. self-hosted GKE Agent Sandbox & Agent Substrate decision guide |

</details>

<details>
<summary>SDK Namespace Note (<code>agentplatform</code> vs. <code>vertexai</code>) &amp; Quotas</summary>

- **SDK namespace:** Agent Platform is moving from `vertexai.Client` (`google-cloud-aiplatform>=1.154.0`) to `agentplatform.Client` (`google-cloud-agentplatform>=2.0.1`). Both `starter/` and `solution/` default to `agentplatform.Client` with a clean fallback to `vertexai.Client`. Keep `GOOGLE_GENAI_USE_ENTERPRISE=TRUE` in `.env`.
- **Shared-project quotas:** Default limits are `10/min` Reasoning Engine writes, `90/min` queries, `300/min` session event appends, and `1,000` sandboxes/region (with hard non-adjustable caps of `6,000` revisions/project/region and `950` revisions/agent). If multiple attendees share one GCP project, see the sizing formula and cohort table in [FACILITATOR-GUIDE.md](FACILITATOR-GUIDE.md).

</details>

---

## Next Step

Continue to **[Lab 1: Setup & Build the ADK Coding Agent](01-LAB-SETUP-AND-BUILD-ADK.md)**.

**Official docs:** [Google ADK](https://adk.dev/get-started/) · [ADK 2.0 Workflows](https://adk.dev/workflows/) · [`google/agents-cli`](https://github.com/google/agents-cli) · [Agent Platform Runtime Setup](https://docs.cloud.google.com/gemini-enterprise-agent-platform/build/runtime/setup) · [Sandboxes](https://docs.cloud.google.com/gemini-enterprise-agent-platform/scale/sandbox) · [Locations](https://docs.cloud.google.com/gemini-enterprise-agent-platform/resources/agent-locations) · [Quotas](https://docs.cloud.google.com/gemini-enterprise-agent-platform/resources/agent-quotas)
