# Enterprise Coding Agent Workshop on Gemini Enterprise Agent Platform

Build, isolate, deploy, govern, and continuously optimize a production-grade **Enterprise Coding Agent** on **Google Cloud's Gemini Enterprise Agent Platform** using **Google ADK (Python)**, **`google/agents-cli`**, **Managed BYOC Sandboxes**, **Terraform**, **Managed Sessions & Memory Bank**, **Skill & Agent Registries**, and **Managed Evaluation & Quality Alerts**.

> **Who this workshop is for:** Principal/Staff Software Engineers, Cloud Architects, Platform Engineers, and AI/ML Engineers designing autonomous coding or developer-productivity agents that execute untrusted code safely at enterprise scale.

---

## What You Will Build

Over the course of this hands-on workshop, you evolve a single ADK Coding Agent (`coding_agent`) from a local prototype into an enterprise-governed, self-improving cloud service across all four pillars of the **Gemini Enterprise Agent Platform**:

| Pillar | Hands-On Labs | Key Platform Capabilities |
|---|---|---|
| **1. Build** | [Lab 1: Setup & Build ADK Agent](workshop/01-LAB-SETUP-AND-BUILD-ADK.md) | `google/agents-cli`, Google ADK 2.0 architectures (Simple `LlmAgent` → Collaborative Team → Graph `Workflow` → Dynamic `@node`), `EnvironmentToolset(LocalEnvironment)`, `ManagedAgent` trade-offs, Service Registration (`services.yaml`/`services.py`), Antigravity `.agents/skills/` |
| **2. Scale** | [Lab 2: Custom Sandbox (BYOC), Lifecycle & Execution](workshop/02-LAB-CUSTOM-SANDBOX-BYOC.md) | Non-root Debian BYOC container, `SandboxEnvironmentTemplate`, Sandbox CRUD/Pause/Resume/Snapshot, Shell `execute_bash()`, Code Execution (`AgentEngineSandboxCodeExecutor`), custom `BaseEnvironment`, PSC-I/NGFW egress |
| **2. Scale** | [Lab 3: Deploy to Agent Runtime with Terraform](workshop/03-LAB-DEPLOY-RUNTIME-TERRAFORM.md) | `agents-cli deploy` & declarative `google_vertex_ai_reasoning_engine` (`container_spec` & `source_code_spec`), dual service-agent IAM `depends_on`, revisions, traffic splitting, emergency stop |
| **2. Scale** | [Lab 4: Sessions, Memory Bank, Feedback & Telemetry](workshop/04-LAB-SESSIONS-MEMORY-FEEDBACK.md) | `VertexAiSessionService` & Sessions API, `VertexAiMemoryBankService` (topics, TTL, similarity retrieval, prompt-injection defense), Feedback Service, GenAI OTel Tracing, Cloud Logging & PromQL Monitoring |
| **3. Govern** | [Lab 5: Skill Registry, Agent Registry & Governance](workshop/05-LAB-GOVERN-SKILL-AGENT-REGISTRY.md) | Skill Registry 16-check ZIP/`SKILL.md` packaging, `GCPSkillRegistry` + `SkillToolset`, `AgentRegistry` (`google-adk[a2a,agent-identity]`), Semantic Governance Policies (NLC), SPIFFE Agent Identity |
| **4. Optimize** | [Lab 6: Observability, Evaluation, Alerts & Optimize](workshop/06-LAB-OPTIMIZE-EVAL-AND-ALERTS.md) | Offline Eval (traces vs. sessions), 2-Step Simulated User Eval, Failure Clustering (`vertexai.evals`), Online Evaluation Monitors, Cloud Monitoring Quality Alerts (`monitoring_v3`), Prompt Optimization (`agents-cli eval optimize`) |
| **Architecture** | [Lab 7: Agent Runtime vs. Self-Hosted GKE](workshop/07-ARCHITECTURE-AGENT-RUNTIME-VS-GKE.md) | 14-Dimension Limitations & Trade-Off Matrix comparing Agent Runtime + Managed Sandbox vs. Self-Hosted GKE + `kubernetes-sigs/agent-sandbox` + GKE Agent Substrate |

---

## Quickstart (5 Minutes)

### Prerequisites

- **Python 3.11+** (required by `google/agents-cli` and ADK 2.0)
- **[`uv`](https://docs.astral.sh/uv/)** (fast Python package & virtualenv manager)
- **Google Cloud CLI (`gcloud`)** authenticated against a **Standard billing-enabled GCP project** (see [Express Mode vs. Standard GCP caveats](workshop/00-WORKSHOP-OVERVIEW.md#express-mode-vs-standard-gcp-project-important))
- **Docker** or **Cloud Build** (Lab 2), **Terraform >= 1.5.0** (Lab 3), **Node.js** (optional, for `npx skills add`)

### 1. Install `google/agents-cli` & Project Dependencies

```bash
# Install google/agents-cli and its 7 global IDE workflow skills
uvx google-agents-cli setup

# Verify CLI installation and active environment
agents-cli info

# Authenticate Application Default Credentials (ADC) for your GCP project
gcloud auth login
gcloud auth application-default login
```

### 2. Configure Workshop Environment & Sync `starter/`

```bash
# Copy environment template and fill in GOOGLE_CLOUD_PROJECT, GOOGLE_CLOUD_PROJECT_NUMBER, and GOOGLE_CLOUD_LOCATION (e.g., us-central1)
cp .env.example .env

# Install Python dependencies for starter/ and solution/ via uv
make install

# Run pre-flight skill and repo validation
make validate-skills
```

### 3. Open in Antigravity (Automatic `.agents/skills/` Discovery)

Open this repository folder in **Antigravity** (or any IDE supporting the open Agent Skills `.agents/skills/` standard). Antigravity automatically discovers all **6 modular workshop skills** bundled under [`.agents/skills/`](.agents/skills/) alongside the 7 global `google-agents-cli-*` skills installed by `uvx google-agents-cli setup`:

| Bundled Workshop Skill | Workshop Coverage |
|---|---|
| [`adk-coding-agent-build`](.agents/skills/adk-coding-agent-build/SKILL.md) | Lab 1 — ADK 2.0 Agent Architectures (Simple, Collaborative, Graph & Dynamic Workflows, `ManagedAgent`, `services.yaml`/`services.py`), `EnvironmentToolset`, `BaseEnvironment`, `LocalEnvironment`, `ExecuteBashTool`, `agents-cli` |
| [`agent-platform-sandbox-byoc`](.agents/skills/agent-platform-sandbox-byoc/SKILL.md) | Lab 2 — BYOC Dockerfile contract, Sandbox/Template/Snapshot lifecycle, Shell & Code Execution, PSC-I/NGFW/VPC-SC/CMEK |
| [`agent-platform-runtime-and-state`](.agents/skills/agent-platform-runtime-and-state/SKILL.md) | Labs 3–4 — Terraform `google_vertex_ai_reasoning_engine`, quotas, Managed Sessions, Memory Bank, Feedback, Telemetry |
| [`agent-platform-governance-and-registries`](.agents/skills/agent-platform-governance-and-registries/SKILL.md) | Lab 5 — Skill Registry (16 atomic ZIP/`SKILL.md` checks), Agent Registry, `GCPSkillRegistry`/`AgentRegistry` ADK clients, Semantic Governance |
| [`agent-platform-optimize-and-eval`](.agents/skills/agent-platform-optimize-and-eval/SKILL.md) | Lab 6 — GenAI OTel Observability, Offline/Simulated/Online Eval, Failure Clustering, Quality Alerts, Optimize Flywheel |
| [`agent-runtime-vs-gke-architecture`](.agents/skills/agent-runtime-vs-gke-architecture/SKILL.md) | Lab 7 — 14-Dimension Agent Runtime vs. Self-Hosted GKE Agent Sandbox & Agent Substrate decision guide |

> **Zero Co-Trigger Shadowing:** Every workshop skill declares explicit `Don't use for:` boundaries so it complements—rather than collides with—the 7 built-in `google-agents-cli-*` skills.

---

## Delivery Tracks: Full-Day vs. Half-Day Fast-Track

Choose the track that matches your session schedule (detailed time-boxed schedule in [00-WORKSHOP-OVERVIEW.md](workshop/00-WORKSHOP-OVERVIEW.md#workshop-schedules-full-day-vs-half-day-fast-track)):

| Track | Duration | Format & Scope |
|---|---|---|
| **Full-Day Deep-Dive** | **7 hours** *(6h 10m labs + 50m breaks)* | Complete hands-on implementation across **all 7 labs** (`starter/` -> Lab 1 Parts A & B across all 4 ADK architectures, BYOC sandbox & runtime image builds, Terraform apply, Sessions + Memory Bank + Feedback, Skill/Agent Registry + Semantic Governance, Offline/Simulated/Online Eval + Quality Alerts, and GKE Architecture Review). |
| **Half-Day Fast-Track** | **3.5 hours** *(210 min)* | High-velocity executive + engineering track: **Lab 1 (Part A hands-on + 5m Part B walkthrough), Labs 2, 3, and 5** hands-on (using pre-pushed sandbox/runtime images or `solution/` checkpoints where needed, including both Skill Registry & Agent Registry in Lab 5), instructor-led live demos of **Labs 4 (10m) & 6 (15m)**, and a **25-minute** architecture Q&A on **Lab 7 (Agent Runtime vs. GKE)**. |

> **Stuck on a Lab?** Every file in [`starter/`](starter/) contains clearly marked `# TODO(lab-N):` stubs, and [`solution/`](solution/) provides the complete, syntax-verified reference implementation for every lab so you can diff or fast-forward at any checkpoint.

---

## Repository Map

```text
gemini-coding-agent-workshop/
├── README.md                                   # You are here
├── .env.example                                # Environment variables template (GCP, Sandbox, Registries, Model)
├── Makefile                                    # Single-command runner for install, build, deploy, eval & verify
├── workshop/                                   # Step-by-step customer lab guides & facilitator runbook
│   ├── 00-WORKSHOP-OVERVIEW.md                 # Executive narrative, architecture diagram, prereqs & quotas
│   ├── 01-LAB-SETUP-AND-BUILD-ADK.md           # Build: agents-cli + ADK 2.0 Architectures (Simple/Collab/Graph/Dynamic) + EnvironmentToolset
│   ├── 02-LAB-CUSTOM-SANDBOX-BYOC.md           # Scale: BYOC Dockerfile, Sandbox Lifecycle, Execution & Egress
│   ├── 03-LAB-DEPLOY-RUNTIME-TERRAFORM.md      # Scale: Agent Runtime deploy (agents-cli + Terraform IaC)
│   ├── 04-LAB-SESSIONS-MEMORY-FEEDBACK.md      # Scale: Managed Sessions, Memory Bank, Feedback & Telemetry
│   ├── 05-LAB-GOVERN-SKILL-AGENT-REGISTRY.md   # Govern: Skill Registry, Agent Registry & Semantic Governance
│   ├── 06-LAB-OPTIMIZE-EVAL-AND-ALERTS.md      # Optimize: Offline/Simulated/Online Eval, Alerts & Prompt Tuning
│   ├── 07-ARCHITECTURE-AGENT-RUNTIME-VS-GKE.md # Architecture: Agent Runtime vs. Self-Hosted GKE & Substrate
│   └── FACILITATOR-GUIDE.md                    # Instructor checklist, quota math & Top-20 troubleshooting
├── starter/                                    # Hands-on participant workspace with # TODO(lab-N) markers
│   ├── pyproject.toml                          # Python >=3.11 uv dependencies (ADK >=2.0, Agent Platform, Eval, OTel)
│   ├── agents-cli-manifest.yaml                # Lab 1: agents-cli config (agent_directory: coding_agent, target: agent_runtime)
│   ├── services.yaml                           # Lab 1 Part B: Declarative ADK 2.0+ custom service registration
│   ├── services.py                             # Lab 1 Part B: Programmatic ADK 2.0+ service registration (precedence over YAML)
│   ├── Dockerfile                              # Lab 3: Trusted Agent Runtime BYOC image (0.0.0.0:8080, non-root)
│   ├── main.py                                 # Lab 3: FastAPI/ADK HTTP server (GET /, /api/reasoning_engine, /api/stream_reasoning_engine)
│   ├── requirements.txt                        # Lab 3: Agent Runtime container deps (for container_spec & source_code_spec)
│   ├── coding_agent/
│   │   ├── __init__.py
│   │   ├── config.py                           # Typed environment settings loader (incl. AGENT_ARCHITECTURE, MAX_FIX_ROUNDS, ENABLE_HITL_APPROVAL)
│   │   ├── agent.py                            # Root ADK LlmAgent + architecture dispatcher (Lab 1 -> Lab 2 sandbox -> Lab 4/5 wired)
│   │   ├── architectures.py                    # Lab 1 Part B: Collaborative Team, Declarative Graph, Dynamic Workflow & ManagedAgent builders
│   │   ├── train_eval_set.evalset.json         # Lab 6: Minimal ADK eval set consumed by `adk optimize`
│   │   ├── tools/
│   │   │   ├── sandbox_lifecycle.py            # Lab 2: Template, Sandbox & Snapshot CRUD + Pause/Resume CLI
│   │   │   ├── sandbox_execution.py            # Lab 2: Shell, BYOC /exec, Code Exec & BaseEnvironment adapter
│   │   │   └── registry_loader.py              # Lab 5: GCPSkillRegistry, SkillToolset & AgentRegistry loader
│   │   ├── memory/
│   │   │   ├── session_manager.py              # Lab 4: VertexAiSessionService & direct Sessions API manager
│   │   │   └── memory_bank_manager.py          # Lab 4: VertexAiMemoryBankService, generate/retrieve & hygiene
│   │   └── callbacks/
│   │       └── telemetry_and_feedback.py       # Lab 4: OTel spans, parent sandbox stdout logging & Feedback API
│   ├── sandbox_image/                          # Lab 2: Non-root Debian BYOC coding sandbox (untrusted /exec plane)
│   │   ├── Dockerfile                          # USER appuser, Python 3.11+, Node.js, pytest, ruff, bandit
│   │   ├── runner.py                           # Lightweight /health & /exec HTTP runner on port 8080
│   │   └── requirements.txt
│   ├── skills_to_register/                     # Lab 5: Enterprise skill package passing all 16 atomic checks
│   │   └── secure-code-review/
│   │       ├── SKILL.md
│   │       └── references/owasp-checklist.md
│   ├── terraform/                              # Lab 3: google_vertex_ai_reasoning_engine + dual SA IAM
│   │   ├── versions.tf
│   │   ├── variables.tf
│   │   ├── main.tf
│   │   ├── outputs.tf
│   │   └── terraform.tfvars.example
│   ├── eval/                                   # Lab 6: Split JSON datasets, eval/sampler configs, eval scripts & alerts
│   │   ├── datasets/
│   │   │   ├── coding_agent_eval.jsonl         # Combined 8-case JSONL (auto-split by --jsonl-dataset)
│   │   │   ├── coding_agent_single_turn.json   # Single-turn canonical {"eval_cases": [...]} dataset
│   │   │   └── coding_agent_multi_turn.json    # Multi-turn agent_data dataset (split to prevent HTTP 400)
│   │   ├── eval_config.yaml                    # Declarative agents-cli eval --config metrics configuration
│   │   ├── sampler_config.json                 # ADK `adk optimize` LocalEvalSampler config (train_eval_set)
│   │   ├── run_offline_eval.py
│   │   ├── run_simulated_eval.py
│   │   ├── setup_online_monitor.py
│   │   ├── setup_quality_alerts.py
│   │   └── optimize_prompt.py
│   └── gke_reference/                          # Lab 7: Self-hosted GKE Agent Sandbox CRD reference overlay
│       ├── sandbox_template.yaml
│       ├── sandbox_warmpool.yaml
│       ├── rbac.yaml
│       └── gke_agent_example.py
├── solution/                                   # Complete reference mirror of starter/ (0 TODO markers, incl. architectures.py, services.yaml/py, Dockerfile, main.py)
├── .agents/skills/                             # 6 modular production Antigravity skills (auto-discovered)
│   └── adk-coding-agent-build/references/      # Modular ADK build refs (incl. agent-architectures-and-workflows.md & graph-and-dynamic-workflows.md)
├── scripts/                                    # Verification & packaging tooling
│   ├── verify_lab.sh                           # Attendee checkpoint verifier (./scripts/verify_lab.sh <1..7|all>)
│   ├── validate_skills.py                      # Validates .agents/skills/ frontmatter, line limits & links
│   └── package_registry_skill.py               # Packages & checks all 16 atomic Skill Registry ZIP/SKILL.md rules
└── automation/                                 # Reproducible corpus harvest & provenance manifest
    ├── harvest_corpus.py
    ├── run_workshop_builder.py
    ├── corpus_manifest.json
    └── workflow_round_ledger.json
```

---

## `Makefile` Quick Reference

Run `make help` at any time from the repository root to list available targets. Override `TRACK=solution` (default: `starter`) to run any command against the reference solution:

| Target | Purpose | Lab |
|---|---|---|
| `make help` | Print all available targets and usage notes | All |
| `make install` | Sync Python 3.11+ dependencies via `uv` (`starter/` and `solution/`) | Lab 1 |
| `make lint` | Run `ruff check` across `starter/`, `solution/`, and `scripts/` | All |
| `make build-sandbox` | Build the non-root BYOC coding sandbox Docker image locally | Lab 2 |
| `make push-sandbox` | Build/push the BYOC sandbox image (`SANDBOX_IMAGE_URI`) to `coding-agent-repo` | Lab 2 |
| `make sandbox-lifecycle-demo` | Run the Sandbox Template -> Create -> Exec -> Pause -> Resume -> Snapshot -> Delete demo | Lab 2 |
| `make push-agent` | Build/push the trusted Agent Runtime BYOC image (`AGENT_IMAGE_URI`) to `coding-agent-repo` | Lab 3 |
| `make tf-plan` | Initialize and run `terraform plan` in `$(TRACK)/terraform` | Lab 3 |
| `make tf-apply` | Apply Terraform configuration for Agent Runtime + IAM bindings | Lab 3 |
| `make package-skill` | Validate all 16 atomic Skill Registry ZIP/`SKILL.md` checks and build the `.zip` archive | Lab 5 |
| `make eval-offline` | Run offline evaluation over split JSON datasets (`eval/datasets/coding_agent_{single,multi}_turn.json`) | Lab 6 |
| `make eval-simulated` | Run 2-step simulated user evaluation personas | Lab 6 |
| `make validate-skills` | Run `scripts/validate_skills.py` on `.agents/skills/` | Lab 1 / All |
| `make verify-lab LAB=1` | Run `./scripts/verify_lab.sh <1..7\|all>` checkpoint verification | Labs 1–7 |

---

## Next Step

Start with **[00-WORKSHOP-OVERVIEW.md](workshop/00-WORKSHOP-OVERVIEW.md)** to review the end-to-end architecture, enable required GCP APIs, configure the required service agents, and run your pre-flight quota check.

---

## Official Documentation References

- **Google ADK Documentation:** https://adk.dev/get-started/
- **Google ADK 2.0 Workflows & Graphs:** https://adk.dev/2.0/ · https://adk.dev/workflows/ · https://adk.dev/graphs/
- **`google/agents-cli` Repository:** https://github.com/google/agents-cli
- **Gemini Enterprise Agent Platform — Scale & Sandboxes:** https://docs.cloud.google.com/gemini-enterprise-agent-platform/scale/sandbox
- **Gemini Enterprise Agent Platform — Runtime Setup:** https://docs.cloud.google.com/gemini-enterprise-agent-platform/build/runtime/setup
- **Gemini Enterprise Agent Platform — Quotas & Locations:** https://docs.cloud.google.com/gemini-enterprise-agent-platform/resources/agent-quotas
