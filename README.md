# Enterprise Coding Agent Workshop on Gemini Enterprise Agent Platform

Build, isolate, deploy, govern, and continuously optimize a production-grade **Enterprise Coding Agent** on **Google Cloud's Gemini Enterprise Agent Platform** using **Google ADK (Python)**, **`google/agents-cli`**, **Managed BYOC Sandboxes**, **Terraform**, **Managed Sessions & Memory Bank**, **Skill & Agent Registries**, and **Managed Evaluation & Quality Alerts**.

> **Who this workshop is for:** Principal/Staff Software Engineers, Cloud Architects, Platform Engineers, and AI/ML Engineers designing autonomous coding or developer-productivity agents that execute untrusted code safely at enterprise scale.

---

## What You Will Build

Over the course of this hands-on workshop, you evolve a single ADK Coding Agent (`coding_agent`) from a local prototype into an enterprise-governed, self-improving cloud service across all four pillars of the **Gemini Enterprise Agent Platform**:

| Pillar | Hands-On Labs | Key Platform Capabilities |
|---|---|---|
| **1. Build** | [Lab 1: Setup & Build ADK Agent](workshop/01-LAB-SETUP-AND-BUILD-ADK.md) | `google/agents-cli`, Google ADK 2.0 architectures (Simple `LlmAgent` → Collaborative Team → Graph `Workflow` → Dynamic `@node`), `EnvironmentToolset(LocalEnvironment)`, `ManagedAgent` trade-offs, Service Registration (`services.yaml`/`services.py`), Antigravity `.agents/skills/` |
| **2. Scale** | [Lab 2: Custom Sandbox (BYOC), Lifecycle & Execution](workshop/02-LAB-CUSTOM-SANDBOX-BYOC.md) | Standalone Agent Platform instance (`client.runtimes.create()`), Non-root Debian BYOC container, `SandboxEnvironmentTemplate`, Sandbox CRUD/Pause/Resume/Snapshot, Shell `execute_bash()`, Code Execution (`AgentEngineSandboxCodeExecutor`), custom `BaseEnvironment`, PSC-I/NGFW egress |
| **2. Scale** | [Lab 3: Managed Sessions, Memory Bank, Telemetry & Feedback](workshop/03-LAB-SESSIONS-MEMORY-FEEDBACK.md) | Reuses Lab 2 standalone instance: `VertexAiSessionService` & Sessions API, `VertexAiMemoryBankService` (topics, TTL, similarity retrieval), Feedback Service, GenAI OTel Tracing, parent sandbox `stdout`/`stderr` Cloud Logging & PromQL Monitoring |
| **3. Extend** | [Lab 4: Skill Registry & Agent Registry Discovery](workshop/04-LAB-SKILLS-AND-AGENT-REGISTRY.md) | Skill Registry 16-check ZIP/`SKILL.md` packaging, Vertex AI Skill Registry upload, `GCPSkillRegistry` + `SkillToolset`, `AgentRegistry` (`google-adk[a2a,agent-identity,mcp]`) wired into `coding_agent` before deployment |
| **2. Scale** | [Lab 5: Deploy Complete Agent ONCE (CLI & Terraform)](workshop/05-LAB-DEPLOY-RUNTIME-TERRAFORM.md) | Build & deploy the 100% feature-complete Labs 1–4 agent **once** via `agents-cli deploy` & declarative `google_vertex_ai_reasoning_engine` (`container_spec` & `source_code_spec`), Custom SA + `roles/aiplatform.memoryUser`, dual service-agent IAM `depends_on`, unified vs. decoupled `REASONING_ENGINE_NAME`, revisions, traffic splitting, emergency stop |
| **4. Optimize** | [Lab 6: Observability, Evaluation, Alerts & Optimize](workshop/06-LAB-OPTIMIZE-EVAL-AND-ALERTS.md) | Offline Eval (traces vs. sessions), 2-Step Simulated User Eval, Failure Clustering (`vertexai.evals`), Online Evaluation Monitors, Cloud Monitoring Quality Alerts (`monitoring_v3`), Prompt Optimization (`agents-cli eval optimize`) |
| **3. Govern (Optional)** | [Lab 7 (Optional / Skippable): Enterprise Security & Governance Hardening](workshop/07-LAB-OPTIONAL-SECURITY-AND-GOVERNANCE.md) | Agent Registry `ENABLED_BLOCKING` LLM scanning & lifecycle, Semantic Governance Policies (NLC) & Model Armor, SPIFFE `AGENT_IDENTITY` + Agent Gateway Terraform upgrade path, Multi-Tenant Session/Memory IAM Conditions, Memory Poisoning audit, CMEK/VPC-SC, WORM Audit Buckets + SIEM Pub/Sub + 3-Layer Agent Anomaly Detection → SCC *(skipping Lab 7 leaves Labs 1–6 100% green!)* |
| **Architecture** | [Lab 8: Agent Runtime vs. Self-Hosted GKE](workshop/08-ARCHITECTURE-AGENT-RUNTIME-VS-GKE.md) | 14-Dimension Limitations & Trade-Off Matrix comparing Agent Runtime + Managed Sandbox vs. Self-Hosted GKE + `kubernetes-sigs/agent-sandbox` + GKE Agent Substrate |

---

## Quickstart (5 Minutes)

### Prerequisites

- **Python 3.11+** (required by `google/agents-cli` and ADK 2.0)
- **[`uv`](https://docs.astral.sh/uv/)** (fast Python package & virtualenv manager)
- **Google Cloud CLI (`gcloud`)** authenticated against a **Standard billing-enabled GCP project** (see [Express Mode vs. Standard GCP caveats](workshop/00-WORKSHOP-OVERVIEW.md#express-mode-vs-standard-gcp-project-important))
- **Docker** or **Cloud Build** (Labs 2 & 5), **Terraform >= 1.5.0** (Lab 5), **Node.js** (optional, for `npx skills add`)

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
| [`agent-platform-runtime-and-state`](.agents/skills/agent-platform-runtime-and-state/SKILL.md) | Labs 3 & 5 — Managed Sessions, Memory Bank, Feedback, Telemetry, Terraform `google_vertex_ai_reasoning_engine`, quotas & deploy-once patterns |
| [`agent-platform-governance-and-registries`](.agents/skills/agent-platform-governance-and-registries/SKILL.md) | Lab 4 & Optional Lab 7 — Skill Registry (16 atomic ZIP/`SKILL.md` checks), Agent Registry, `GCPSkillRegistry`/`AgentRegistry` ADK clients, `ENABLED_BLOCKING` scanning, Semantic Governance (NLC) & SPIFFE |
| [`agent-platform-optimize-and-eval`](.agents/skills/agent-platform-optimize-and-eval/SKILL.md) | Lab 6 — GenAI OTel Observability, Offline/Simulated/Online Eval, Failure Clustering, Quality Alerts, Optimize Flywheel |
| [`agent-runtime-vs-gke-architecture`](.agents/skills/agent-runtime-vs-gke-architecture/SKILL.md) | Lab 8 — 14-Dimension Agent Runtime vs. Self-Hosted GKE Agent Sandbox & Agent Substrate decision guide |

> **Zero Co-Trigger Shadowing:** Every workshop skill declares explicit `Don't use for:` boundaries so it complements—rather than collides with—the 7 built-in `google-agents-cli-*` skills.

---

## Delivery Tracks: Full-Day vs. Half-Day Fast-Track

Choose the track that matches your session schedule (detailed time-boxed schedule in [00-WORKSHOP-OVERVIEW.md](workshop/00-WORKSHOP-OVERVIEW.md#workshop-schedules-full-day-vs-half-day-fast-track)):

| Track | Duration | Format & Scope |
|---|---|---|
| **Full-Day Deep-Dive** | **7 hours** *(6h 10m labs + 50m breaks; or 6h 25m skipping Optional Lab 7)* | Complete hands-on implementation across **Labs 1–8** (`starter/` → Lab 1 Parts A & B across all 4 ADK architectures, Lab 2 BYOC sandbox + standalone instance, Lab 3 Sessions + Memory Bank + Telemetry/Feedback, Lab 4 Skill/Agent Registry discovery, Lab 5 **Deploy ONCE** via `agents-cli` & Terraform, Lab 6 Offline/Simulated/Online Eval + Quality Alerts, **Optional / Skippable Lab 7** Security & Governance Hardening, and Lab 8 GKE Architecture Review). |
| **Half-Day Fast-Track** | **3.5 hours** *(210 min)* | High-velocity executive + engineering track (**Labs 1–6 + Lab 8**, cleanly skipping **Optional Lab 7** with zero broken checkpoints): **Lab 1 (Part A hands-on + 5m Part B walkthrough), Labs 2, 4, and 5** hands-on (using pre-pushed sandbox/runtime images or `solution/` checkpoints where needed), instructor-led live demos of **Labs 3 (15m) & 6 (15m)**, and a **25-minute** architecture Q&A on **Lab 8 (Agent Runtime vs. GKE)**. |

> **Stuck on a Lab?** Every file in [`starter/`](starter/) contains clearly marked `# TODO(lab-N):` stubs, and [`solution/`](solution/) provides the complete, syntax-verified reference implementation for every lab so you can diff or fast-forward at any checkpoint.

---

## Repository Map

```text
gemini-coding-agent-workshop/
├── README.md                                   # You are here
├── .env.example                                # Environment variables template (GCP, Sandbox, Registries, Model)
├── Makefile                                    # Single-command runner for install, build, deploy, eval & verify
├── workshop/                                       # Step-by-step customer lab guides & facilitator runbook
│   ├── 00-WORKSHOP-OVERVIEW.md                     # Executive narrative, architecture diagram, prereqs & quotas
│   ├── 01-LAB-SETUP-AND-BUILD-ADK.md               # Lab 1 (Build): agents-cli + ADK 2.0 Architectures + EnvironmentToolset
│   ├── 02-LAB-CUSTOM-SANDBOX-BYOC.md               # Lab 2 (Scale): Standalone instance, BYOC Dockerfile, Sandbox Lifecycle & Egress
│   ├── 03-LAB-SESSIONS-MEMORY-FEEDBACK.md          # Lab 3 (Scale): Managed Sessions, Memory Bank, Feedback & Telemetry
│   ├── 04-LAB-SKILLS-AND-AGENT-REGISTRY.md         # Lab 4 (Extend): Skill Registry 16-check packaging & Agent Registry Discovery
│   ├── 05-LAB-DEPLOY-RUNTIME-TERRAFORM.md          # Lab 5 (Scale): Deploy Complete Coding Agent ONCE (agents-cli + Terraform IaC)
│   ├── 06-LAB-OPTIMIZE-EVAL-AND-ALERTS.md          # Lab 6 (Optimize): Offline/Simulated/Online Eval, Alerts & Prompt Tuning
│   ├── 07-LAB-OPTIONAL-SECURITY-AND-GOVERNANCE.md  # Lab 7 (Optional / Skippable): Scanning, NLC, Model Armor, SPIFFE, CMEK/VPC-SC, WORM/SIEM/SCC
│   ├── 08-ARCHITECTURE-AGENT-RUNTIME-VS-GKE.md     # Lab 8 (Architecture): Agent Runtime vs. Self-Hosted GKE & Agent Substrate
│   └── FACILITATOR-GUIDE.md                        # Instructor checklist, skip-Lab-7 guide, quota math & Top-20 troubleshooting
├── starter/                                        # Hands-on participant workspace with # TODO(lab-N) markers
│   ├── pyproject.toml                              # Python >=3.11 uv dependencies (ADK >=2.0, Agent Platform, Eval, OTel)
│   ├── agents-cli-manifest.yaml                    # Lab 1: agents-cli config (agent_directory: coding_agent, target: agent_runtime)
│   ├── services.yaml                               # Lab 1 Part B: Declarative ADK 2.0+ custom service registration
│   ├── services.py                                 # Lab 1 Part B: Programmatic ADK 2.0+ service registration (precedence over YAML)
│   ├── Dockerfile                                  # Lab 5: Trusted Agent Runtime BYOC image (0.0.0.0:8080, non-root)
│   ├── main.py                                     # Lab 5: FastAPI/ADK HTTP server (GET /, /api/reasoning_engine, /api/stream_reasoning_engine)
│   ├── requirements.txt                            # Lab 5: Agent Runtime container deps (for container_spec & source_code_spec)
│   ├── coding_agent/
│   │   ├── __init__.py
│   │   ├── config.py                               # Typed environment settings loader (incl. AGENT_ARCHITECTURE, MAX_FIX_ROUNDS, ENABLE_HITL_APPROVAL)
│   │   ├── agent.py                                # Root ADK LlmAgent + architecture dispatcher (Lab 1 -> Lab 2 sandbox -> Lab 3/4 wired -> Lab 5 deployed)
│   │   ├── architectures.py                        # Lab 1 Part B: Collaborative Team, Declarative Graph, Dynamic Workflow & ManagedAgent builders
│   │   ├── train_eval_set.evalset.json             # Lab 6: Minimal ADK eval set consumed by `adk optimize`
│   │   ├── tools/
│   │   │   ├── sandbox_lifecycle.py                # Lab 2: Template, Sandbox & Snapshot CRUD + Pause/Resume CLI
│   │   │   ├── sandbox_execution.py                # Lab 2: Shell, BYOC /exec, Code Exec & BaseEnvironment adapter
│   │   │   └── registry_loader.py                  # Lab 4: GCPSkillRegistry, SkillToolset & AgentRegistry loader
│   │   ├── memory/
│   │   │   ├── session_manager.py                  # Lab 3: VertexAiSessionService & direct Sessions API manager
│   │   │   └── memory_bank_manager.py              # Lab 3 (+ Lab 7 audit): VertexAiMemoryBankService, generate/retrieve & hygiene
│   │   └── callbacks/
│   │       └── telemetry_and_feedback.py           # Lab 3: OTel spans, parent sandbox stdout logging & Feedback API
│   ├── sandbox_image/                              # Lab 2: Non-root Debian BYOC coding sandbox (untrusted /exec plane)
│   │   ├── Dockerfile                              # USER appuser, Python 3.11+, Node.js, pytest, ruff, bandit
│   │   ├── runner.py                               # Lightweight /health & /exec HTTP runner on port 8080
│   │   └── requirements.txt
│   ├── skills_to_register/                         # Lab 4: Enterprise skill package passing all 16 atomic checks
│   │   └── secure-code-review/
│   │       ├── SKILL.md
│   │       └── references/owasp-checklist.md
│   ├── terraform/                                  # Lab 5 (+ Lab 7 SPIFFE upgrade path): google_vertex_ai_reasoning_engine + dual SA IAM
│   │   ├── versions.tf
│   │   ├── variables.tf
│   │   ├── main.tf
│   │   ├── outputs.tf
│   │   └── terraform.tfvars.example
│   ├── eval/                                       # Lab 6: Split JSON datasets, eval/sampler configs, eval scripts & alerts
│   │   ├── datasets/
│   │   │   ├── coding_agent_eval.jsonl             # Combined 8-case JSONL (auto-split by --jsonl-dataset)
│   │   │   ├── coding_agent_single_turn.json       # Single-turn canonical {"eval_cases": [...]} dataset
│   │   │   └── coding_agent_multi_turn.json        # Multi-turn agent_data dataset (split to prevent HTTP 400)
│   │   ├── eval_config.yaml                        # Declarative agents-cli eval --config metrics configuration
│   │   ├── sampler_config.json                     # ADK `adk optimize` LocalEvalSampler config (train_eval_set)
│   │   ├── run_offline_eval.py
│   │   ├── run_simulated_eval.py
│   │   ├── setup_online_monitor.py
│   │   ├── setup_quality_alerts.py
│   │   └── optimize_prompt.py
│   └── gke_reference/                              # Lab 8: Self-hosted GKE Agent Sandbox CRD reference overlay
│       ├── sandbox_template.yaml
│       ├── sandbox_warmpool.yaml
│       ├── rbac.yaml
│       └── gke_agent_example.py
├── solution/                                       # Complete reference mirror of starter/ (0 TODO markers, incl. architectures.py, services.yaml/py, Dockerfile, main.py)
├── .agents/skills/                                 # 6 modular production Antigravity skills (auto-discovered)
│   └── adk-coding-agent-build/references/          # Modular ADK build refs (incl. agent-architectures-and-workflows.md & graph-and-dynamic-workflows.md)
├── scripts/                                        # Verification & packaging tooling
│   ├── verify_lab.sh                               # Attendee checkpoint verifier (./scripts/verify_lab.sh <1..8|all>)
│   ├── validate_skills.py                          # Validates .agents/skills/ frontmatter, line limits & links
│   └── package_registry_skill.py                   # Packages & checks all 16 atomic Skill Registry ZIP/SKILL.md rules
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
| `make push-agent` | Build/push the complete Labs 1–4 Agent Runtime BYOC image (`AGENT_IMAGE_URI`) to `coding-agent-repo` | Lab 5 |
| `make tf-plan` | Initialize and run `terraform plan` in `$(TRACK)/terraform` | Lab 5 |
| `make tf-apply` | Apply Terraform configuration for Agent Runtime + IAM bindings | Lab 5 |
| `make package-skill` | Validate all 16 atomic Skill Registry ZIP/`SKILL.md` checks and build the `.zip` archive | Lab 4 |
| `make eval-offline` | Run offline evaluation over split JSON datasets (`eval/datasets/coding_agent_{single,multi}_turn.json`) | Lab 6 |
| `make eval-simulated` | Run 2-step simulated user evaluation personas | Lab 6 |
| `make validate-skills` | Run `scripts/validate_skills.py` on `.agents/skills/` | Lab 1 / All |
| `make verify-lab LAB=1` | Run `./scripts/verify_lab.sh <1..8\|all>` checkpoint verification (`all` checks core Labs 1–6; `7` Optional Hardening; `8` GKE Overlay) | Labs 1–8 |

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
