"""12-to-15 round iterative run-workflow orchestrator for the Gemini Enterprise Agent Platform
Coding Agent Workshop, Starter/Solution Project, and Production Antigravity Skills.

Runs inside an agent `run_workflow` runner (Python 3.8+ with top-level await).
"""

import ast
import json
import os
import re
import shutil
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

from advanced import parallel as bounded_parallel
from advanced import retry

SCRATCH_DIR = Path(
    args.get(
        "scratch_dir",
        "./.workshop_scratch",
    )
)
OUTPUT_DIR = Path(
    args.get(
        "output_dir",
        ".",
    )
)
MIN_ROUNDS = int(args.get("min_rounds", 12))
MAX_ROUNDS = int(args.get("max_rounds", 15))
START_ROUND = int(args.get("start_round", 0))

CORPUS_DIR = SCRATCH_DIR / "corpus"
FACTS_DIR = SCRATCH_DIR / "facts"
LEDGER_PATH = SCRATCH_DIR / "round_ledger.json"
HARVESTER = SCRATCH_DIR / "harvest_corpus.py"

OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
FACTS_DIR.mkdir(parents=True, exist_ok=True)

USER_SEED_URLS = [
    "https://docs.cloud.google.com/gemini-enterprise-agent-platform/build/skill-registry",
    "https://docs.cloud.google.com/gemini-enterprise-agent-platform/scale/runtime/use-terraform",
    "https://docs.cloud.google.com/gemini-enterprise-agent-platform/scale/runtime/manage-deployed-agents",
    "https://docs.cloud.google.com/gemini-enterprise-agent-platform/scale/runtime/tracing",
    "https://docs.cloud.google.com/gemini-enterprise-agent-platform/scale/runtime/logging",
    "https://docs.cloud.google.com/gemini-enterprise-agent-platform/scale/runtime/monitoring",
    "https://adk.dev/get-started/",
    "https://docs.cloud.google.com/gemini-enterprise-agent-platform/scale/feedback-service",
    "https://docs.cloud.google.com/gemini-enterprise-agent-platform/scale/sessions",
    "https://docs.cloud.google.com/gemini-enterprise-agent-platform/scale/memory-bank",
    "https://docs.cloud.google.com/gemini-enterprise-agent-platform/scale/sandbox",
    "https://docs.cloud.google.com/gemini-enterprise-agent-platform/optimize/observability/overview",
    "https://docs.cloud.google.com/gemini-enterprise-agent-platform/optimize/evaluation/agent-evaluation",
    "https://docs.cloud.google.com/gemini-enterprise-agent-platform/optimize/evaluation/evaluate-online",
    "https://docs.cloud.google.com/gemini-enterprise-agent-platform/optimize/evaluation/evaluate-offline",
    "https://docs.cloud.google.com/gemini-enterprise-agent-platform/optimize/evaluation/evaluate-simulated",
    "https://docs.cloud.google.com/gemini-enterprise-agent-platform/optimize/evaluation/view-results",
    "https://docs.cloud.google.com/gemini-enterprise-agent-platform/optimize/evaluation/quality-alerts",
    "https://docs.cloud.google.com/gemini-enterprise-agent-platform/optimize/evaluation/optimize-agent",
    "https://github.com/google/agents-cli",
]

SAFETY_BOUNDARY = f"""
CRITICAL WORKSPACE BOUNDARY:
- ONLY create or modify files inside the designated output and scratch directories.
- ONLY write deliverables inside `{OUTPUT_DIR}` and scratch/facts inside `{SCRATCH_DIR}`.
- NEVER invent APIs, CLI flags, Terraform attributes, IAM roles, or quotas: verify every detail from `{CORPUS_DIR}` and `{FACTS_DIR}`.
- When finished writing/editing files on disk, ALWAYS call the `finish` tool with the exact JSON schema requested.
""".strip()

# ---------------------------------------------------------------------------
# Helpers (deterministic Python)
# ---------------------------------------------------------------------------

def run_harvester(extra_urls=None):
    cmd = [sys.executable, str(HARVESTER)]
    if extra_urls:
        clean = [u for u in extra_urls if isinstance(u, str) and u.startswith("http")]
        if not clean:
            return "no valid extra urls"
        cmd.extend(["--extra-urls", *clean])
    proc = subprocess.run(cmd, capture_output=True, text=True, timeout=180)
    out = (proc.stdout + "\n" + proc.stderr).strip()
    log(f"Harvester exit={proc.returncode}: {out.splitlines()[-1] if out else ''}")
    return out


def save_ledger(ledger):
    LEDGER_PATH.write_text(json.dumps(ledger, indent=2), encoding="utf-8")


def run_static_checks():
    """Run deterministic checks across deliverables; returns dict of errors & metrics."""
    errors = []
    warnings = []
    metrics = {}

    # 1. Python AST syntax check across starter/, solution/, scripts/
    py_files = []
    for sub in ["starter", "solution", "scripts"]:
        root = OUTPUT_DIR / sub
        if root.exists():
            py_files.extend(sorted(root.rglob("*.py")))
    metrics["python_files"] = len(py_files)
    if len(py_files) < 16:
        errors.append(f"Expected >=16 Python files across starter/solution/scripts, found {len(py_files)}")
    for pf in py_files:
        try:
            ast.parse(pf.read_text(encoding="utf-8"), filename=str(pf))
        except SyntaxError as e:
            errors.append(f"Python syntax error in {pf.relative_to(OUTPUT_DIR)}: line {e.lineno}: {e.msg}")

    # 2. Starter vs Solution parity & TODO checks
    starter_dir = OUTPUT_DIR / "starter"
    solution_dir = OUTPUT_DIR / "solution"
    required_rel_files = [
        "pyproject.toml",
        "coding_agent/__init__.py",
        "coding_agent/config.py",
        "coding_agent/agent.py",
        "coding_agent/tools/sandbox_lifecycle.py",
        "coding_agent/tools/sandbox_execution.py",
        "coding_agent/tools/registry_loader.py",
        "coding_agent/memory/session_manager.py",
        "coding_agent/memory/memory_bank_manager.py",
        "coding_agent/callbacks/telemetry_and_feedback.py",
        "sandbox_image/Dockerfile",
        "sandbox_image/runner.py",
        "skills_to_register/secure-code-review/SKILL.md",
        "terraform/main.tf",
        "terraform/variables.tf",
        "terraform/outputs.tf",
        "eval/datasets/coding_agent_eval.jsonl",
        "eval/run_offline_eval.py",
        "eval/run_simulated_eval.py",
        "eval/setup_online_monitor.py",
        "eval/setup_quality_alerts.py",
        "eval/optimize_prompt.py",
        "gke_reference/sandbox_template.yaml",
        "gke_reference/sandbox_warmpool.yaml",
        "gke_reference/rbac.yaml",
        "gke_reference/gke_agent_example.py",
    ]
    for rel in required_rel_files:
        if not (starter_dir / rel).exists():
            errors.append(f"Missing starter file: starter/{rel}")
        if not (solution_dir / rel).exists():
            errors.append(f"Missing solution file: solution/{rel}")

    # Check starter has TODO(lab- markers and solution has none
    starter_todos = 0
    for pf in starter_dir.rglob("*.py") if starter_dir.exists() else []:
        starter_todos += len(re.findall(r"TODO\(lab-", pf.read_text(encoding="utf-8")))
    metrics["starter_todo_markers"] = starter_todos
    if starter_todos < 8:
        errors.append(f"Starter project has too few TODO(lab-N) markers ({starter_todos}); expected >=8 across agent/sandbox/session/memory/eval")

    for pf in solution_dir.rglob("*.py") if solution_dir.exists() else []:
        sol_todos = re.findall(r"TODO\(lab-", pf.read_text(encoding="utf-8"))
        if sol_todos:
            errors.append(f"Solution file still contains TODO(lab- marker: solution/{pf.relative_to(solution_dir)}")

    # 3. Workshop docs presence & broken local markdown link check
    required_workshop = [
        "README.md",
        ".env.example",
        "Makefile",
        "workshop/00-WORKSHOP-OVERVIEW.md",
        "workshop/01-LAB-SETUP-AND-BUILD-ADK.md",
        "workshop/02-LAB-CUSTOM-SANDBOX-BYOC.md",
        "workshop/03-LAB-DEPLOY-RUNTIME-TERRAFORM.md",
        "workshop/04-LAB-SESSIONS-MEMORY-FEEDBACK.md",
        "workshop/05-LAB-GOVERN-SKILL-AGENT-REGISTRY.md",
        "workshop/06-LAB-OPTIMIZE-EVAL-AND-ALERTS.md",
        "workshop/07-ARCHITECTURE-AGENT-RUNTIME-VS-GKE.md",
        "workshop/FACILITATOR-GUIDE.md",
    ]
    for rel in required_workshop:
        if not (OUTPUT_DIR / rel).exists():
            errors.append(f"Missing workshop/root file: {rel}")

    # 4. Run scripts/validate_skills.py if present
    val_script = OUTPUT_DIR / "scripts/validate_skills.py"
    if val_script.exists():
        p = subprocess.run(
            [sys.executable, str(val_script), str(OUTPUT_DIR / ".agents/skills")],
            capture_output=True,
            text=True,
            timeout=60,
        )
        metrics["validate_skills_exit"] = p.returncode
        if p.returncode != 0:
            errors.append(f"validate_skills.py failed:\n{(p.stdout + p.stderr).strip()[:1500]}")
    else:
        errors.append("Missing scripts/validate_skills.py")

    # 5. Run scripts/package_registry_skill.py --dry-run if present
    pkg_script = OUTPUT_DIR / "scripts/package_registry_skill.py"
    if pkg_script.exists():
        p = subprocess.run(
            [
                sys.executable,
                str(pkg_script),
                str(OUTPUT_DIR / "solution/skills_to_register/secure-code-review"),
                "--dry-run",
            ],
            capture_output=True,
            text=True,
            timeout=60,
        )
        metrics["package_skill_exit"] = p.returncode
        if p.returncode != 0:
            errors.append(f"package_registry_skill.py --dry-run failed:\n{(p.stdout + p.stderr).strip()[:1000]}")
    else:
        errors.append("Missing scripts/package_registry_skill.py")

    # 6. Check all 6 expected Antigravity skills & 20/20 seed URL coverage inside .agents/skills/
    expected_skills = [
        "adk-coding-agent-build",
        "agent-platform-sandbox-byoc",
        "agent-platform-runtime-and-state",
        "agent-platform-governance-and-registries",
        "agent-platform-optimize-and-eval",
        "agent-runtime-vs-gke-architecture",
    ]
    all_skill_text = ""
    for sk in expected_skills:
        sk_md = OUTPUT_DIR / ".agents/skills" / sk / "SKILL.md"
        if not sk_md.exists():
            errors.append(f"Missing Antigravity skill: .agents/skills/{sk}/SKILL.md")
            continue
        lines = sk_md.read_text(encoding="utf-8").splitlines()
        if len(lines) > 500:
            errors.append(f"Skill {sk}/SKILL.md exceeds 500-line soft limit ({len(lines)} lines)")
        refs_dir = sk_md.parent / "references"
        if not refs_dir.exists() or len(list(refs_dir.glob("*.md"))) < 3:
            errors.append(f"Skill {sk} should have >=3 modular reference files under references/")
        for md in sk_md.parent.rglob("*.md"):
            all_skill_text += "\n" + md.read_text(encoding="utf-8")

    missing_seed_in_skills = []
    for u in USER_SEED_URLS:
        base = u.rstrip("/")
        if base not in all_skill_text:
            missing_seed_in_skills.append(u)
    metrics["seed_urls_covered_in_skills"] = f"{len(USER_SEED_URLS) - len(missing_seed_in_skills)}/{len(USER_SEED_URLS)}"
    if missing_seed_in_skills:
        errors.append(f"Seed URLs not covered/cited in .agents/skills/: {missing_seed_in_skills}")

    # 7. Check all 20 seed URLs also referenced across workshop/
    all_ws_text = ""
    for md in (OUTPUT_DIR / "workshop").rglob("*.md") if (OUTPUT_DIR / "workshop").exists() else []:
        all_ws_text += "\n" + md.read_text(encoding="utf-8")
    missing_seed_in_ws = [u for u in USER_SEED_URLS if u.rstrip("/") not in all_ws_text]
    metrics["seed_urls_covered_in_workshop"] = f"{len(USER_SEED_URLS) - len(missing_seed_in_ws)}/{len(USER_SEED_URLS)}"
    if missing_seed_in_ws:
        warnings.append(f"Seed URLs not explicitly cited in workshop/: {missing_seed_in_ws}")

    # 8. Dockerfile non-root check
    for track in ["starter", "solution"]:
        df = OUTPUT_DIR / track / "sandbox_image/Dockerfile"
        if df.exists():
            txt = df.read_text(encoding="utf-8")
            if not re.search(r"^\s*USER\s+(?!root\b)\S+", txt, flags=re.M):
                errors.append(f"{track}/sandbox_image/Dockerfile must set a non-root USER")

    # 9. Check JSONL eval dataset validity
    for track in ["starter", "solution"]:
        jl = OUTPUT_DIR / track / "eval/datasets/coding_agent_eval.jsonl"
        if jl.exists():
            line_count = 0
            for idx, line in enumerate(jl.read_text(encoding="utf-8").splitlines(), 1):
                if not line.strip():
                    continue
                line_count += 1
                try:
                    json.loads(line)
                except json.JSONDecodeError as e:
                    errors.append(f"Invalid JSON on line {idx} of {track}/eval/datasets/coding_agent_eval.jsonl: {e}")
            if line_count < 5:
                errors.append(f"{track}/eval/datasets/coding_agent_eval.jsonl has only {line_count} cases (expected >=5)")

    return {"passed": len(errors) == 0, "errors": errors, "warnings": warnings, "metrics": metrics}


# ---------------------------------------------------------------------------
# JSON Schemas
# ---------------------------------------------------------------------------

EXTRACT_SCHEMA = {
    "type": "object",
    "properties": {
        "domain": {"type": "string"},
        "fact_file": {"type": "string"},
        "pages_read": {"type": "integer"},
        "key_apis_and_limits": {"type": "array", "items": {"type": "string"}},
        "missing_sublinks": {"type": "array", "items": {"type": "string"}},
    },
    "required": ["domain", "fact_file", "pages_read", "key_apis_and_limits", "missing_sublinks"],
}

ROUND_WORK_SCHEMA = {
    "type": "object",
    "properties": {
        "round": {"type": "integer"},
        "summary": {"type": "string"},
        "files_written": {"type": "array", "items": {"type": "string"}},
        "missing_sublinks": {"type": "array", "items": {"type": "string"}},
    },
    "required": ["round", "summary", "files_written", "missing_sublinks"],
}

CRITIQUE_SCHEMA = {
    "type": "object",
    "properties": {
        "round": {"type": "integer"},
        "scores": {
            "type": "object",
            "properties": {
                "doc_coverage": {"type": "integer"},
                "api_code_accuracy": {"type": "integer"},
                "workshop_pedagogy": {"type": "integer"},
                "skill_production_quality": {"type": "integer"},
            },
            "required": ["doc_coverage", "api_code_accuracy", "workshop_pedagogy", "skill_production_quality"],
        },
        "overall_score": {"type": "integer"},
        "blocking_issues": {"type": "array", "items": {"type": "string"}},
        "improvements": {"type": "array", "items": {"type": "string"}},
        "missing_sublinks": {"type": "array", "items": {"type": "string"}},
    },
    "required": ["round", "scores", "overall_score", "blocking_issues", "improvements", "missing_sublinks"],
}

if START_ROUND > 0 and LEDGER_PATH.exists():
    ledger = json.loads(LEDGER_PATH.read_text(encoding="utf-8"))
    log(f"Resuming workflow from Round {START_ROUND} with {len(ledger.get('rounds', []))} prior round(s) loaded.")
else:
    ledger = {
        "started_at": datetime.now(timezone.utc).isoformat(),
        "output_dir": str(OUTPUT_DIR),
        "rounds": [],
    }

# ===========================================================================
# PHASE 0: Deterministic Corpus Harvesting
# ===========================================================================
if START_ROUND <= 0:
    phase("Phase 0: Deterministic Corpus Harvest (20 Seed URLs + Tier-1 Sub-Links)")
    harvest_out = run_harvester()
    log(harvest_out)

# ===========================================================================
# PHASE 1: Parallel Domain Fact Extraction (6 Analysts)
# ===========================================================================
phase("Phase 1: Parallel Domain Extraction (6 Corpus Analysts)")

DOMAINS = [
    {
        "id": "01_build",
        "title": "Build Pillar: ADK Python, EnvironmentToolset, BashTool, google/agents-cli",
        "focus": (
            "Extract exact ADK Python v1.x/2.0 installation, LlmAgent/Agent definitions, EnvironmentToolset & BaseEnvironment "
            "subclassing hooks (ReadFile/EditFile/WriteFile/Execute), BashTool, google/agents-cli commands (setup, create, "
            "scaffold enhance, run, eval, deploy, publish, infra, extensions), AND exact names/scopes/triggers of all 7 built-in "
            "google/agents-cli skills so our custom workshop skills complement them cleanly without co-trigger shadowing."
        ),
    },
    {
        "id": "02_sandbox",
        "title": "Scale Pillar (Sandbox): Managed Sandboxes, BYOC Custom Containers, Lifecycle & Execution",
        "focus": (
            "Extract EVERY exact detail from all sandbox pages: BYOC custom container requirements (Linux, non-root, runner/entrypoint, "
            "Artifact Registry IAM for service-PROJECT_NUMBER@gcp-sa-vertex-sandbox.iam.gserviceaccount.com), SandboxEnvironmentTemplate "
            "create/get/list/update/delete, SandboxEnvironment create/get/list/pause/resume/snapshot/delete, Snapshot list/delete, "
            "Shell sandbox execute_bash() vs Code Execution send_command()/execute_code() vs AgentEngineSandboxCodeExecutor, "
            "BYOC /exec runner patterns, TTL (7d BYOC vs 14d code-exec), cold start (2m / 20s shell), egress_control_config, "
            "PSC network_attachment + Cloud NGFW + Secure Web Proxy + DNS peering, VPC-SC, CMEK, no ambient creds, Audit Logs & stdout gaps."
        ),
    },
    {
        "id": "03_runtime_state",
        "title": "Scale Pillar (Runtime, Terraform, Sessions, Memory Bank, Feedback, Telemetry, Quotas)",
        "focus": (
            "Extract EVERY exact API/Terraform/CLI detail: google_vertex_ai_reasoning_engine (BYOC container_spec, Dockerfile source_code_spec "
            "root-of-tar rule, package_spec, Secret Manager, dedicated runtime SA, gcp-sa-aiplatform-re IAM depends_on), "
            "manage-deployed-agents (list/get/update/delete/emergency-stop), revisions & traffic splitting, Agent Identity (SPIFFE), "
            "runtime contract, Managed Sessions (ADK VertexAiSessionService + direct API CRUD/events + IAM conditions), "
            "Memory Bank (setup, adk-quickstart VertexAiMemoryBankService, api-quickstart, generate_memories, fetch/retrieve scope & similarity, "
            "TTL, customization config, prompt-injection governance), Feedback Service (SDK/API & UI), Tracing (OTel), Logging (stdout/Python/client), "
            "Monitoring (built-in metrics, PromQL, custom metrics, alerts), AND ALL exact quotas from resources/agent-quotas."
        ),
    },
    {
        "id": "04_govern",
        "title": "Govern Pillar: Skill Registry, Agent Registry, ADK Consumption & Semantic Governance",
        "focus": (
            "Extract EVERY exact detail: Skill Registry entities (Skill, Skill revision), ALL 14+ ZIP payload validation rules "
            "(10MB zip, 500MB unzipped, 10,000 items, 8 levels, no symlinks, compression ratio <=100, YAML name <=64, desc <=1024, body <=500k), "
            "built-in gcp-skill-registry first-call ingestion quirk, create/update/search/delete SDK/REST calls, Agent Registry overview & "
            "register-skills, ADK GCPSkillRegistry + SkillToolset (search_skills, load_skill, load_skill_resource, run_skill_script) + "
            "sandbox network requirement, ADK AgentRegistry (google-adk[a2a,agent-identity] extra, list_agents, list_mcp_servers, "
            "get_remote_a2a_agent with httpx.Auth, get_mcp_toolset with header_provider), Semantic Governance Policies (NLC intercepting "
            "load_skill / run_skill_script / supply-chain allowlists), SPIFFE Agent Identity & topology."
        ),
    },
    {
        "id": "05_optimize",
        "title": "Optimize Pillar: Observability, Offline/Online/Simulated Eval, View Results, Quality Alerts, Optimize Agent",
        "focus": (
            "Extract EVERY exact detail: Observability overview (GenAI OTel conventions, audit logs, tamper-evident retention, SIEM export, "
            "emergency stop & propagation latency), Agent Evaluation workflow (traces vs sessions, built-in & rubric/adaptive metrics, "
            "evaluate-offline from registry & single trace/session, evaluate-online monitors & telemetry requirements & sampling, "
            "evaluate-simulated 2-step workflow & user simulator settings & SDK example, view-results dashboard & vertexai.evals SDK & "
            "failure clustering, quality-alerts Console + gcloud + google.cloud.monitoring_v3 SDK, optimize-agent & adk.dev/optimize/ & "
            "agents-cli eval optimize)."
        ),
    },
    {
        "id": "06_gke_comparison",
        "title": "Architecture Comparison: Self-Hosted GKE + GKE Agent Sandbox + Agent Substrate vs Agent Runtime",
        "focus": (
            "Extract EVERY exact technical detail & limitation from GKE Agent Sandbox, Pod Snapshots, Storage, Agent Substrate, "
            "ADK deploy/gke, and ADK GkeCodeExecutor: Sandbox/SandboxTemplate/SandboxClaim/SandboxWarmPool CRDs, gVisor vs microVMs "
            "vs self-managed Kata Containers (no Google SLA), <1s warm pools, Pod Snapshots requirements (GKE >= 1.35.3-gke.1234000, "
            "non-E2 e.g. N2, gVisor only, no TPUs), GPUs/TPUs support, NetworkPolicy auto-generation per SandboxTemplate vs direct Sandbox, "
            "Agent Substrate on GKE higher actor density, GkeCodeExecutor(executor_type='sandbox' vs 'job'), RBAC requirements, "
            "and direct contrast against Agent Runtime + Managed Sandbox limitations & quotas."
        ),
    },
]


def make_extract_agent(d):
    index_file = CORPUS_DIR / f"INDEX_{d['id']}.md"
    fact_file = FACTS_DIR / f"{d['id']}.md"
    prompt = f"""
You are a Senior Google Cloud Principal Documentation Analyst extracting ground-truth engineering facts for domain `{d['id']}` ({d['title']}).

1. Read `{index_file}` to get the complete list of locally cached official documentation pages for your domain.
2. Read ALL key local markdown files listed in `{index_file}` (use `read_file`; read long files in chunks if needed so you don't miss code blocks, tables, quotas, or gotchas).
3. Focus specifically on:
   {d['focus']}
4. Write a comprehensive, densely packed, code-accurate **Verified Fact Sheet** to `{fact_file}` containing:
   - Exact source URLs read (citing canonical `https://...` URLs)
   - Exact SDK package names, imports, client initializations, and method signatures (explicitly flagging where docs use `agentplatform` vs `vertexai` vs `google.adk` vs `google.cloud.*`!)
   - Exact CLI commands, Terraform resource schemas, YAML CRD specs, IAM roles, and service agent emails
   - Exact numeric quotas, limits, TTLs, latencies, validation constraints, and gotchas
   - Any important referenced sub-links NOT yet present in `{index_file}` that should be fetched in Tier-2.

{SAFETY_BOUNDARY}
"""
    return retry(
        lambda: agent(
            prompt,
            schema=EXTRACT_SCHEMA,
            role=f"Extract {d['id']}",
            model="flash",
        ),
        attempts=2,
    )


if START_ROUND <= 0:
    extraction_results = await bounded_parallel(DOMAINS, make_extract_agent, max_concurrency=6)
    tier2_candidates = []
    for r in extraction_results:
        log(f"Extracted {r['domain']}: {r['pages_read']} pages -> {r['fact_file']} (missing sublinks: {len(r['missing_sublinks'])})")
        tier2_candidates.extend(r["missing_sublinks"])

    if tier2_candidates:
        phase("Phase 1b: Dynamic Tier-2 Sub-Link Harvest")
        run_harvester(sorted(set(tier2_candidates))[:30])


# ===========================================================================
# PHASE 2: 12-to-15 Round Iterative Research, Build, Critique & Refinement Loop
# ===========================================================================

# --- ROUND 1: Deep Research Audit — Build, ADK & Governance ---
if START_ROUND <= 1:
    phase("Round 1/15: Deep Research Audit — Build, ADK Coding Agent, agents-cli & Skill/Agent Registry")
    r1 = await retry(
        lambda: agent(
            f"""
You are the Lead Principal Architect performing **Research Iteration 1**.
Read `{FACTS_DIR}/01_build.md`, `{FACTS_DIR}/04_govern.md`, and spot-verify against raw pages in `{CORPUS_DIR}/pages/` (especially `skill-registry`, `create-manage`, `agent-registry`, `register-skills`, `govern-agent-skills`, `adk.dev_integrations_skills-registry`, `adk.dev_integrations_agent-registry`, `adk.dev_integrations_environment-toolset`, and `google/agents-cli` SKILL.md files).

Tasks:
1. Verify and enrich `{FACTS_DIR}/01_build.md` and `{FACTS_DIR}/04_govern.md` with any newly harvested Tier-2 pages or missed details:
   - Exact `BaseEnvironment` abstract methods / `LocalEnvironment` / `EnvironmentToolset` interface in ADK so our Coding Agent starter code subclasses it accurately.
   - Exact `GCPSkillRegistry` + `SkillToolset` and `AgentRegistry` (including `google-adk[a2a,agent-identity]`, `httpx.Auth`, `header_provider`) usage.
   - Exact Skill Registry REST/Python create/update/search/delete payloads & all 14 ZIP validation rules.
   - Exact Semantic Governance Policy NLC examples for governing `load_skill` / `run_skill_script`.
   - Exact `agents-cli` skill overlap map (explicitly listing all 7 built-in `google-agents-cli-*` skills and what our 6 workshop skills must exclude via `Don't use for:` to prevent Co-Trigger Shadowing).
2. Report any remaining missing sub-links in `missing_sublinks`.

{SAFETY_BOUNDARY}
""",
            schema=ROUND_WORK_SCHEMA,
            role="Round 1: Build & Govern Research Audit",
        ),
        attempts=2,
    )
    ledger["rounds"].append(r1)
    save_ledger(ledger)
    if r1["missing_sublinks"]:
        run_harvester(r1["missing_sublinks"][:15])

# --- ROUND 2: Deep Research Audit — Sandbox Lifecycle/Execution, Runtime Terraform, Sessions, Memory Bank, Feedback ---
if START_ROUND <= 2:
    phase("Round 2/15: Deep Research Audit — Sandbox BYOC/Lifecycle/Exec, Terraform, Sessions & Memory Bank")
    r2 = await retry(
        lambda: agent(
            f"""
You are the Lead Platform & Sandbox Architect performing **Research Iteration 2**.
Read `{FACTS_DIR}/02_sandbox.md`, `{FACTS_DIR}/03_runtime_state.md`, and directly verify the raw corpus pages in `{CORPUS_DIR}/pages/` for:
- `scale_sandbox_manage-sandboxes`, `scale_sandbox_manage-templates`, `scale_sandbox_manage-snapshots`, `scale_sandbox_custom-containers`, `scale_sandbox_shell-sandbox-quickstart`, `scale_sandbox_code-execution-overview`, `scale_sandbox_configure-vpc-sc`
- `scale_runtime_use-terraform`, `scale_runtime_manage-deployed-agents`, `scale_runtime_deploy-an-agent`, `scale_runtime_runtime-contract`
- `scale_sessions_manage-with-adk`, `scale_sessions_manage-with-api`, `scale_memory-bank_adk-quickstart`, `scale_memory-bank_api-quickstart`, `scale_memory-bank_generate-memories`, `scale_memory-bank_fetch-memories`, `scale_memory-bank_setup`
- `scale_feedback-service_manage-with-sdk-or-api`, `scale_runtime_tracing`, `scale_runtime_logging`, `scale_runtime_monitoring`

Tasks:
1. Ensure `{FACTS_DIR}/02_sandbox.md` documents the EXACT SDK/REST calls for EVERY sandbox lifecycle operation (create, get, list, pause, resume, snapshot, delete sandbox; create, get, list, update, delete template; list, delete snapshot) AND EVERY sandbox execution path (Shell `execute_bash`, Code Execution `execute_code`/`send_command` + `AgentEngineSandboxCodeExecutor`, BYOC custom container `/exec` + runner contract & port exposure).
2. Reconcile SDK naming cleanly (`agentplatform.Client` vs `vertexai.Client` / `google-cloud-aiplatform[agent_engines]`) with explicit migration/compatibility guidance so our starter code and Antigravity skills are 100% honest and accurate.
3. Ensure `{FACTS_DIR}/03_runtime_state.md` has exact, verified Python code snippets for ADK + direct API **Managed Sessions**, **Memory Bank** (including `generate_memories`, scope-based & similarity retrieval, TTL, customization, prompt-injection defense), **Feedback Service**, and **Terraform** (`google_vertex_ai_reasoning_engine` BYOC + Dockerfile + `depends_on` IAM for both service agents).
4. Write updated verified facts back to `{FACTS_DIR}/02_sandbox.md` and `{FACTS_DIR}/03_runtime_state.md`.

{SAFETY_BOUNDARY}
""",
            schema=ROUND_WORK_SCHEMA,
            role="Round 2: Sandbox & Runtime Research Audit",
        ),
        attempts=2,
    )
    ledger["rounds"].append(r2)
    save_ledger(ledger)
    if r2["missing_sublinks"]:
        run_harvester(r2["missing_sublinks"][:15])

# --- ROUND 3: Deep Research Audit — GKE Agent Sandbox Comparison, Quotas & Optimize Flywheel ---
if START_ROUND <= 3:
    phase("Round 3/15: Deep Research Audit — GKE Comparison, Quotas & Optimize Evaluation Flywheel")
    r3 = await retry(
        lambda: agent(
            f"""
You are the Principal Distributed Systems & Eval Architect performing **Research Iteration 3**.
Read `{FACTS_DIR}/05_optimize.md`, `{FACTS_DIR}/06_gke_comparison.md`, and cross-verify against raw pages in `{CORPUS_DIR}/pages/` for:
- `resources_agent-quotas`, `kubernetes-engine_*`, `adk.dev_integrations_gke-code-executor`, `adk.dev_deploy_gke`
- `optimize_observability_overview`, `optimize_observability_traces`, `optimize_evaluation_*`, `adk.dev_optimize`

Tasks:
1. Build an authoritative **14-Dimension Agent Runtime + Managed Sandbox vs. Self-Hosted GKE + GKE Agent Sandbox vs. GKE Agent Substrate vs. `agents-cli` Comparison Matrix** inside `{FACTS_DIR}/06_gke_comparison.md`, citing exact numbers (7d/14d TTL, 2m vs <1s warm pool, GKE >=1.35.3 & non-E2 & gVisor Pod Snapshots, GPUs/TPUs/Kata/microVMs, PSC + NGFW/SWP vs NetworkPolicy + Dataplane V2 label cardinality, no ambient creds vs WIF, stdout/audit log blind spots, exact Agent Platform quotas: 90 QPM, 10 Bidi/min, 100 resources, 1000 sandbox execute/min & entities, 300 session appends/min, 950 revisions/agent, Express Mode limits, ops/TCO, hybrid patterns).
2. Enrich `{FACTS_DIR}/05_optimize.md` with exact verified SDK/CLI/Console workflows for Offline Eval (trace vs session, metrics/rubrics), Simulated User Eval (2-step workflow + SDK), Online Monitors (telemetry prereqs + sampling), View Results & Failure Clustering (`vertexai.evals`), Quality Alerts (`gcloud` + `monitoring_v3`), and Optimize Agent (`adk.dev/optimize/` + `agents-cli eval optimize`).

{SAFETY_BOUNDARY}
""",
            schema=ROUND_WORK_SCHEMA,
            role="Round 3: GKE & Optimize Research Audit",
        ),
        attempts=2,
    )
    ledger["rounds"].append(r3)
    save_ledger(ledger)
    if r3["missing_sublinks"]:
        run_harvester(r3["missing_sublinks"][:15])

# --- ROUND 4: Workshop Content Plan v1 (Parallel 3-Track Authoring) ---
phase("Round 4/15: Workshop Curriculum v1 (Parallel 3-Track Authoring)")

WORKSHOP_BATCHES = [
    {
        "name": "Batch A (Overview + Labs 1-2)",
        "files": [
            "README.md",
            "workshop/00-WORKSHOP-OVERVIEW.md",
            "workshop/01-LAB-SETUP-AND-BUILD-ADK.md",
            "workshop/02-LAB-CUSTOM-SANDBOX-BYOC.md",
        ],
        "facts": ["01_build.md", "02_sandbox.md", "03_runtime_state.md"],
        "instructions": f"""
Write these 4 customer-ready Markdown files under `{OUTPUT_DIR}`:
1. `README.md`: Repository landing page, quickstart (`uv`, `agents-cli`, Antigravity `.agents/skills/` auto-discovery), repository map (`workshop/`, `starter/`, `solution/`, `.agents/skills/`, `scripts/`, `automation/`), Full-Day (6-7h) & Half-Day (3.5h) tracks, and `Makefile` quick reference.
2. `workshop/00-WORKSHOP-OVERVIEW.md`: Executive narrative ("Building a Production Enterprise Coding Agent on Gemini Enterprise Agent Platform"), end-to-end Mermaid architecture diagram (Build -> Scale -> Govern -> Optimize), Full-Day vs Half-Day Fast-Track schedule table, GCP prerequisites (APIs, IAM roles, BOTH service agents `gcp-sa-aiplatform-re` & `gcp-sa-vertex-sandbox`, Express Mode vs Standard GCP caveats, pre-flight quota check), and how to use the bundled Antigravity `.agents/skills/` during the workshop.
3. `workshop/01-LAB-SETUP-AND-BUILD-ADK.md`: **Build Pillar** — Install `agents-cli`, inspect `.agents/skills/` in Antigravity, explore `starter/coding_agent/`, implement `TODO(lab-1)` in `coding_agent/agent.py` (ADK `LlmAgent` + `EnvironmentToolset(LocalEnvironment)`), run locally (`agents-cli run` / `adk web`), verify with `scripts/verify_lab.sh 1`. Cite `https://adk.dev/get-started/` and `https://github.com/google/agents-cli`.
4. `workshop/02-LAB-CUSTOM-SANDBOX-BYOC.md`: **Scale Pillar (Sandboxes, Lifecycle & Execution)** — Deep hands-on lab covering:
   - Building & pushing `starter/sandbox_image/Dockerfile` (non-root `appuser`, Debian/Ubuntu, Python + Node + `pytest`/`ruff`/`bandit` + `runner.py` `/exec` entrypoint) to Artifact Registry & granting `roles/artifactregistry.reader` to `service-PROJECT_NUMBER@gcp-sa-vertex-sandbox.iam.gserviceaccount.com`
   - Implementing `TODO(lab-2)` in `starter/coding_agent/tools/sandbox_lifecycle.py` (create/get/list/pause/resume/snapshot/delete Sandbox + Template lifecycle!)
   - Implementing `TODO(lab-2)` in `starter/coding_agent/tools/sandbox_execution.py` (BYOC/Shell `execute_bash()` vs Code Execution `AgentEngineSandboxCodeExecutor` + custom ADK `BaseEnvironment` -> `AgentPlatformSandboxEnvironment`)
   - Inspecting security/credential isolation (no metadata server, no ambient creds), egress controls (default-deny vs PSC `network_attachment` + NGFW/SWP), TTL (7d BYOC / 14d code-exec), cold start (2m) & Audit Log / stdout caveats.
   - Cite `https://docs.cloud.google.com/gemini-enterprise-agent-platform/scale/sandbox` and its sub-links!
""",
    },
    {
        "name": "Batch B (Labs 3-5)",
        "files": [
            "workshop/03-LAB-DEPLOY-RUNTIME-TERRAFORM.md",
            "workshop/04-LAB-SESSIONS-MEMORY-FEEDBACK.md",
            "workshop/05-LAB-GOVERN-SKILL-AGENT-REGISTRY.md",
        ],
        "facts": ["01_build.md", "03_runtime_state.md", "04_govern.md"],
        "instructions": f"""
Write these 3 customer-ready Markdown files under `{OUTPUT_DIR}`:
1. `workshop/03-LAB-DEPLOY-RUNTIME-TERRAFORM.md`: **Scale Pillar (Agent Runtime & Terraform)** — Deploy via `agents-cli deploy` AND declaratively via `starter/terraform/` (`google_vertex_ai_reasoning_engine` BYOC `container_spec` + Dockerfile `source_code_spec` root-of-tar warning, dedicated runtime SA, Secret Manager, `gcp-sa-aiplatform-re` IAM with `depends_on`), manage deployed agents (`manage-deployed-agents`: list/get/update/delete/emergency-stop), revisions & traffic splitting, and runtime contract. Cite `scale/runtime/use-terraform` and `scale/runtime/manage-deployed-agents`.
2. `workshop/04-LAB-SESSIONS-MEMORY-FEEDBACK.md`: **Scale Pillar (Sessions, Memory Bank, Feedback & Telemetry)** — Implement `TODO(lab-4)` in `starter/coding_agent/memory/session_manager.py` (Managed Sessions ADK `VertexAiSessionService` + direct API), `starter/coding_agent/memory/memory_bank_manager.py` (Memory Bank setup, `generate_memories`, scope & similarity retrieval, TTL, prompt-injection defense), and `starter/coding_agent/callbacks/telemetry_and_feedback.py` (OTel Tracing, structured Cloud Logging, Cloud Monitoring PromQL/custom metrics, Feedback Service linked to sessions/traces). Cite `scale/sessions`, `scale/memory-bank`, `scale/feedback-service`, `scale/runtime/tracing`, `scale/runtime/logging`, `scale/runtime/monitoring`.
3. `workshop/05-LAB-GOVERN-SKILL-AGENT-REGISTRY.md`: **Govern Pillar (Skill Registry, Agent Registry & Semantic Governance)** — Validate & package `starter/skills_to_register/secure-code-review/` using `scripts/package_registry_skill.py` (verifying all 14 ZIP validation rules), upload to Skill Registry (noting built-in `gcp-skill-registry` first-call ingestion quirk), register & govern in Agent Registry, implement `TODO(lab-5)` in `starter/coding_agent/tools/registry_loader.py` (`GCPSkillRegistry` + `SkillToolset` + `AgentRegistry` with `google-adk[a2a,agent-identity]` & auth providers + sandbox egress note), and author Semantic Governance Policies (Natural Language Constraints blocking unsafe `load_skill` / dependency installs in tainted sessions) + SPIFFE Agent Identity overview. Cite `build/skill-registry` and sub-links (`agent-registry`, `govern-agent-skills`).
""",
    },
    {
        "name": "Batch C (Labs 6-7 + Facilitator Guide)",
        "files": [
            "workshop/06-LAB-OPTIMIZE-EVAL-AND-ALERTS.md",
            "workshop/07-ARCHITECTURE-AGENT-RUNTIME-VS-GKE.md",
            "workshop/FACILITATOR-GUIDE.md",
        ],
        "facts": ["02_sandbox.md", "03_runtime_state.md", "05_optimize.md", "06_gke_comparison.md"],
        "instructions": f"""
Write these 3 customer-ready Markdown files under `{OUTPUT_DIR}`:
1. `workshop/06-LAB-OPTIMIZE-EVAL-AND-ALERTS.md`: **Optimize Pillar (Observability, Offline/Simulated/Online Eval, Alerts & Optimization)** — Walk through GenAI OTel Observability dashboard, audit retention & SIEM export; implement & run `starter/eval/run_offline_eval.py` (traces vs sessions, rubric/trajectory/tool metrics), `starter/eval/run_simulated_eval.py` (2-step user simulation personas), inspect failure clusters (`view-results` Console & `vertexai.evals`), configure Online Evaluation Monitors (`starter/eval/setup_online_monitor.py`) & Quality Alerts (`starter/eval/setup_quality_alerts.py` via `monitoring_v3` & `gcloud`), and close the optimization flywheel (`starter/eval/optimize_prompt.py` + `agents-cli eval optimize` + canary rollout). Explicitly cite ALL 8 optimize URLs (`optimize/observability/overview`, `agent-evaluation`, `evaluate-online`, `evaluate-offline`, `evaluate-simulated`, `view-results`, `quality-alerts`, `optimize-agent`).
2. `workshop/07-ARCHITECTURE-AGENT-RUNTIME-VS-GKE.md`: **Architecture & Limitations Deep-Dive** — Comprehensive executive & engineering guide comparing:
   - Option A: **Gemini Enterprise Agent Platform (Agent Runtime + Managed BYOC Sandbox)**
   - Option B: **Self-Hosted ADK Agent on GKE + GKE Agent Sandbox (`kubernetes-sigs/agent-sandbox`)**
   - Option C: **GKE Agent Substrate (high-density actor workloads)**
   - Option D: **Hybrid patterns via `agents-cli` (`agent_runtime`, `gke`, `cloud_run` targets)**
   Include the full **14-Dimension Verified Comparison & Limitations Matrix** (exact numbers for TTL, cold start/warm pools, GPUs/TPUs/Kata/microVM, Pod Snapshots requirements, Networking/PSC/NGFW/NetworkPolicy/Dataplane V2 cardinality, Identity/SPIFFE/WIF, Logging/Audit gaps, exact Agent Platform quotas & QPM sizing math, Operational TCO), a Mermaid decision flowchart, and a walkthrough of `starter/gke_reference/`.
3. `workshop/FACILITATOR-GUIDE.md`: Instructor runbook with T-7d / T-1d / T-0 checklist, multi-attendee quota sizing formula (`U * X * 1.5` QPM, `Peak QPM * Y * 1.5` session events/min, sandbox entities), Express Mode pitfalls, time-box recovery checkpoints (when to switch from `starter/` to `solution/`), and Top-15 Troubleshooting Table (covering `IMAGE_PULL_BACKOFF` for both service agents, `send_command()` on shell sandbox, tar root path, Skill Registry first-call quirk, missing `[a2a,agent-identity]` extra, sandbox missing VPC egress to Vertex AI, etc.).
""",
    },
]


def make_workshop_batch(b):
    fact_list = ", ".join(f"`{FACTS_DIR}/{f}`" for f in b["facts"])
    prompt = f"""
You are a Principal Cloud Solutions Architect & Technical Curriculum Designer executing **Round 4 ({b['name']})**.
First read the verified fact sheets: {fact_list}.
Then author ALL files specified below with rich, production-grade customer workshop content (exact commands, verified code references matching our planned `starter/`/`solution/` layout, clear lab verification checkpoints, Mermaid diagrams where helpful, and explicit canonical reference links):

{b['instructions']}

{SAFETY_BOUNDARY}
"""
    return retry(
        lambda: agent(prompt, schema=ROUND_WORK_SCHEMA, role=f"Round 4: {b['name']}"),
        attempts=2,
    )


if START_ROUND <= 4:
    r4_results = await bounded_parallel(WORKSHOP_BATCHES, make_workshop_batch, max_concurrency=3)
    ledger["rounds"].append({"round": 4, "batches": r4_results})
    save_ledger(ledger)

# --- ROUND 5: Workshop Curriculum v2 (Adversarial Critique + Refinement) ---
if START_ROUND <= 5:
    phase("Round 5/15: Workshop Curriculum v2 (Adversarial Pedagogical, Quota & Link Audit + Fixes)")
    r5_critique = await retry(
        lambda: agent(
            f"""
You are an Adversarial Workshop & Enterprise Architecture Critic executing **Round 5 Critique**.
Read `{OUTPUT_DIR}/README.md` and ALL 9 files in `{OUTPUT_DIR}/workshop/`. Cross-check against `{FACTS_DIR}/*.md` and the 20 user seed URLs:
{json.dumps(USER_SEED_URLS, indent=2)}

Audit ruthlessly for:
1. Missing coverage or uncited seed URLs / critical sub-links (especially Sandbox lifecycle & execution, BYOC custom container contract, Sessions & Memory Bank, Feedback Service, Skill/Agent Registry, Semantic Governance, Offline/Online/Simulated Eval, Quality Alerts, Optimize Agent, GKE Agent Sandbox & Agent Substrate limitations).
2. Unverified or hallucinated APIs, flags, Terraform blocks, or quota numbers.
3. Workshop timing / UX traps (cold starts, Express Mode traps, missing checkpoints, unclear `starter/` vs `solution/` instructions).
4. Broken internal relative links between `README.md`, `workshop/*.md`, and planned `starter/` / `.agents/skills/` paths.

Return a strict critique with scores (0-100) and concrete file-by-file fixes needed. Do NOT edit files yet.

{SAFETY_BOUNDARY}
""",
            schema=CRITIQUE_SCHEMA,
            role="Round 5: Workshop Critic",
        ),
        attempts=2,
    )
    log(f"Round 5 Workshop Critique score={r5_critique['overall_score']}, blocking={len(r5_critique['blocking_issues'])}")

    r5_fix = await retry(
        lambda: agent(
            f"""
You are the Lead Curriculum Editor executing **Round 5 Refinement**.
Apply EVERY blocking issue and high-impact improvement identified by the Round 5 Critic across `{OUTPUT_DIR}/README.md` and `{OUTPUT_DIR}/workshop/*.md`:

CRITIQUE REPORT:
{json.dumps(r5_critique, indent=2)}

Verify every correction against `{FACTS_DIR}/*.md`, edit only the affected sections cleanly, and ensure all 20 seed URLs are accurately cited and woven into the curriculum.

{SAFETY_BOUNDARY}
""",
            schema=ROUND_WORK_SCHEMA,
            role="Round 5: Workshop Refinement",
        ),
        attempts=2,
    )
    ledger["rounds"].append({"round": 5, "critique": r5_critique, "fix": r5_fix})
    save_ledger(ledger)

# --- ROUND 6: Starter & Solution Project v1 (Core Agent, Sandbox Lifecycle, Sandbox Execution & BYOC Image) ---
phase("Round 6/15: Starter & Solution v1 — Core Coding Agent, Sandbox Lifecycle, Sandbox Execution & BYOC Image")
r6 = await retry(
    lambda: agent(
        f"""
You are a Staff Python & Cloud Infrastructure Engineer executing **Round 6**.
Read `{FACTS_DIR}/01_build.md`, `{FACTS_DIR}/02_sandbox.md`, `{OUTPUT_DIR}/workshop/01-LAB-SETUP-AND-BUILD-ADK.md`, and `{OUTPUT_DIR}/workshop/02-LAB-CUSTOM-SANDBOX-BYOC.md`.

Author BOTH **`{OUTPUT_DIR}/starter/`** (clean, runnable skeletons with well-documented `# TODO(lab-N): ...` markers and type hints so attendees implement the core logic cleanly) AND **`{OUTPUT_DIR}/solution/`** (100% complete, production-clean, working reference implementations with ZERO `TODO(lab-` markers!) for:

1. `pyproject.toml` (Python `>=3.11`, `uv`-compatible, dependencies including `google-adk[a2a,agent-identity]`, `google-cloud-aiplatform[agent_engines,evaluation]`, `google-cloud-logging`, `google-cloud-monitoring`, `httpx`, `pydantic`, `opentelemetry-api`, plus optional `agentplatform` note and dev tools `ruff`, `pytest`).
2. `coding_agent/__init__.py` and `coding_agent/config.py` (typed Settings loaded from env vars matching `.env.example`: `GOOGLE_CLOUD_PROJECT`, `GOOGLE_CLOUD_PROJECT_NUMBER`, `GOOGLE_CLOUD_LOCATION`, `REASONING_ENGINE_NAME`, `SANDBOX_TEMPLATE_NAME`, `SANDBOX_IMAGE_URI`, `SANDBOX_MODE`, `SKILL_REGISTRY_LOCATION`, `AGENT_REGISTRY_LOCATION`, `MODEL_NAME`).
3. `coding_agent/agent.py` (Root ADK Coding Agent using `LlmAgent`/`Agent`, switching cleanly between local `EnvironmentToolset(LocalEnvironment)` in Lab 1 and remote `AgentPlatformSandboxEnvironment` / `AgentEngineSandboxCodeExecutor` in Lab 2, wiring `SkillToolset(registry=GCPSkillRegistry(...))` in Lab 5, and callbacks in Lab 4).
4. `coding_agent/tools/sandbox_lifecycle.py` (**CRITICAL USER REQUIREMENT — Lifecycle Sandbox Management**):
   - Clean `SandboxLifecycleManager` class + runnable CLI (`python -m coding_agent.tools.sandbox_lifecycle ...`) covering EVERY verified lifecycle operation:
     - `create_template(...)`, `get_template(...)`, `list_templates(...)`, `update_template(...)`, `delete_template(...)` (supporting BYOC `custom_container_environment` with `image_uri`, CPU/RAM requests/limits, TCP ports, `egress_control_config`, and Shell `shell_environment`)
     - `create_sandbox(...)`, `get_sandbox(...)`, `list_sandboxes(...)`, `pause_sandbox(...)`, `resume_sandbox(...)`, `snapshot_sandbox(...)`, `delete_sandbox(...)`
     - `list_snapshots(...)`, `delete_snapshot(...)`
   - In `starter/`, scaffold the class, dataclasses, helper auth/client builder, and CLI with clear `# TODO(lab-2)` blocks for template creation, sandbox provisioning, pause/resume/snapshot, and cleanup; in `solution/`, provide the complete implementation verified against `{FACTS_DIR}/02_sandbox.md`!
5. `coding_agent/tools/sandbox_execution.py` (**CRITICAL USER REQUIREMENT — Sandbox Execution Starter & Solution**):
   - Clean execution helpers + ADK `BaseEnvironment` subclass (`AgentPlatformSandboxEnvironment`) covering ALL 3 execution paths:
     - Path A: **Shell Sandbox execution** (`execute_bash()` via `/exec`, explaining why `send_command()`/`execute_code()` do NOT work on shell sandboxes, non-root `appuser`, stateless per-call `cwd` & command chaining under `/workspace`).
     - Path B: **BYOC Custom Container execution** (calling the custom container's `/exec` runner endpoint with short-lived access token via `generate_access_token` / IAM bearer auth, returning structured `stdout`, `stderr`, `returncode`, `duration_ms`).
     - Path C: **Code Execution Sandbox via ADK** (`build_code_execution_executor()` returning `AgentEngineSandboxCodeExecutor(sandbox_resource_name=... | agent_engine_resource_name=...)`).
     - Path D: **`AgentPlatformSandboxEnvironment(BaseEnvironment)`** implementing file read/write/edit + command execute against a live managed sandbox so ADK's `EnvironmentToolset` works seamlessly remotely!
   - Include clear `# TODO(lab-2)` markers in `starter/` and complete implementation in `solution/`.
6. `sandbox_image/Dockerfile`, `sandbox_image/runner.py`, `sandbox_image/requirements.txt`:
   - Linux (Debian Bookworm slim) multi-tool coding sandbox containing Python 3.11+, Node.js LTS, git, `pytest`, `ruff`, `bandit`, `jq`, running strictly as **non-root `USER appuser`** with `/workspace` owned by `appuser`, exposing port `8080`, and running `runner.py` (lightweight HTTP `/health` & `/exec` server with timeout enforcement, workspace confinement, and structured JSON `{{stdout, stderr, returncode, duration_ms}}` output — zero `sudo`, zero hardcoded credentials).

Verify every single `.py` file you write compiles cleanly with `python3 -m py_compile` (via `run_command`).

{SAFETY_BOUNDARY}
""",
        schema=ROUND_WORK_SCHEMA,
        role="Round 6: Core Agent & Sandbox Code",
    ),
    attempts=2,
)
ledger["rounds"].append(r6)
save_ledger(ledger)

# --- ROUND 7: Starter & Solution Project v2 (Parallel 3-Track: State/Governance, Terraform/GKE, Eval/Scripts) ---
phase("Round 7/15: Starter & Solution v2 — Sessions, Memory Bank, Registries, Terraform, Eval & Scripts")

PROJECT_BATCHES = [
    {
        "name": "Track A: Sessions, Memory Bank, Feedback, Telemetry & Registries",
        "facts": ["03_runtime_state.md", "04_govern.md"],
        "instructions": f"""
Author BOTH `{OUTPUT_DIR}/starter/` (with clear `# TODO(lab-4)` / `# TODO(lab-5)` markers) AND `{OUTPUT_DIR}/solution/` (complete implementations with ZERO `TODO(lab-` markers) for:
1. `coding_agent/memory/__init__.py`
2. `coding_agent/memory/session_manager.py` (**CRITICAL USER REQUIREMENT — Sessions Starter & Solution**):
   - ADK integration builder (`build_adk_session_service()` using `VertexAiSessionService` with fallback to `InMemorySessionService` for local offline mode)
   - Direct Agent Platform Session lifecycle wrapper (`SessionLifecycleManager`: create/get/list/delete session, append_event, list_events, with exact verified SDK calls from `{FACTS_DIR}/03_runtime_state.md`).
   - Runnable CLI demo (`python -m coding_agent.memory.session_manager ...`).
3. `coding_agent/memory/memory_bank_manager.py` (**CRITICAL USER REQUIREMENT — Memory Bank Starter & Solution**):
   - ADK integration builder (`build_adk_memory_service()` using `VertexAiMemoryBankService`)
   - Direct Memory Bank manager (`MemoryBankManager`: configure memory topics & TTL, `generate_memories` from session/events, `retrieve_memories` via BOTH scope-based and similarity search, delete/revision inspection, AND a prompt-injection sanitization helper referencing Memory Bank governance guidance).
   - Runnable CLI demo (`python -m coding_agent.memory.memory_bank_manager ...`).
4. `coding_agent/callbacks/__init__.py` and `coding_agent/callbacks/telemetry_and_feedback.py`:
   - ADK `before_tool_callback` / `after_tool_callback` emitting OpenTelemetry span attributes + structured JSON Cloud Logging (explicitly logging sandbox `stdout`/`stderr` from parent runtime since managed sandboxes don't auto-export stdout to Cloud Logging!)
   - `FeedbackClient` wrapper submitting thumbs/score/comment feedback to Agent Platform Feedback Service linked to `session_id` / `trace_id`.
5. `coding_agent/tools/__init__.py` and `coding_agent/tools/registry_loader.py`:
   - `build_skill_registry_toolset()` configuring `GCPSkillRegistry` + `SkillToolset` (plus graceful fallback to local skills if running in an air-gapped sandbox without Vertex AI egress!).
   - `build_agent_registry_integrations()` configuring `AgentRegistry` (`list_agents`, `list_mcp_servers`, `get_remote_a2a_agent` with `GoogleAuth(httpx.Auth)`, `get_mcp_toolset` with `header_provider`).
   - `SkillRegistryPublisher` helper to create/update/search/list skills in Skill Registry (noting the first-call `gcp-skill-registry` ingestion quirk).
6. `skills_to_register/secure-code-review/SKILL.md` and `skills_to_register/secure-code-review/references/owasp-checklist.md`:
   - A production-valid enterprise skill package (identical in `starter/` and `solution/`) conforming to ALL 14 Google Cloud Skill Registry ZIP validation rules so attendees publish & consume it in Lab 5!
""",
    },
    {
        "name": "Track B: Terraform IaC & GKE Reference Overlay",
        "facts": ["02_sandbox.md", "03_runtime_state.md", "06_gke_comparison.md"],
        "instructions": f"""
Author BOTH `{OUTPUT_DIR}/starter/` (with clear `# TODO(lab-3)` / `# TODO(lab-7)` comments where appropriate while staying syntactically valid!) AND `{OUTPUT_DIR}/solution/` (complete production IaC) for:
1. `terraform/versions.tf`, `terraform/variables.tf`, `terraform/main.tf`, `terraform/outputs.tf`, `terraform/terraform.tfvars.example`:
   - Google provider `>= 5.28.0` (verified against `scale/runtime/use-terraform.md.txt`).
   - Dedicated runtime service account (`google_service_account.agent_runtime_sa`) + least-privilege IAM roles (`roles/aiplatform.user`, `roles/logging.logWriter`, `roles/cloudtrace.agent`, `roles/monitoring.metricWriter`).
   - Secret Manager secret + version placeholder + `roles/secretmanager.secretAccessor` binding.
   - Explicit `roles/artifactregistry.reader` bindings for BOTH:
     - `serviceAccount:service-${{var.project_number}}@gcp-sa-aiplatform-re.iam.gserviceaccount.com` (Agent Runtime Service Agent)
     - `serviceAccount:service-${{var.project_number}}@gcp-sa-vertex-sandbox.iam.gserviceaccount.com` (Agent Sandbox Service Agent)
   - `google_vertex_ai_reasoning_engine` resource with `agent_framework = "google-adk"`, `container_spec` (BYOC prebuilt image) AND a clearly documented optional `source_code_spec` + `image_spec {{}}` block (with the root-of-tar archive warning!), `class_methods`, `service_account`, and `depends_on = [google_project_iam_member.re_service_agent_ar_reader, ...]`.
   - Note: In `starter/terraform/main.tf`, keep valid HCL with `# TODO(lab-3)` markers on key spec blocks (e.g., `depends_on` / `container_spec` / secret env vars) so `terraform fmt` works; in `solution/terraform/main.tf`, provide the complete ready-to-apply config!
2. `gke_reference/sandbox_template.yaml`, `gke_reference/sandbox_warmpool.yaml`, `gke_reference/rbac.yaml`, `gke_reference/gke_agent_example.py`:
   - Verified `kubernetes-sigs/agent-sandbox` CRDs (`SandboxTemplate` with gVisor `runtimeClassName: gvisor`, non-root `securityContext`, egress `NetworkPolicy` comments, `SandboxWarmPool` for `<1s` startup, and `Role`/`RoleBinding` for `SandboxClaim` & `Sandbox` resources).
   - `gke_agent_example.py` showing ADK `GkeCodeExecutor(executor_type="sandbox", sandbox_template=..., namespace=...)` verified against `adk.dev/integrations/gke-code-executor`.
""",
    },
    {
        "name": "Track C: Optimize/Eval Scripts, Root Configs & Automated Validators",
        "facts": ["04_govern.md", "05_optimize.md"],
        "instructions": f"""
Author root configs, helper scripts, and BOTH `{OUTPUT_DIR}/starter/eval/` (with `# TODO(lab-6)` markers) AND `{OUTPUT_DIR}/solution/eval/` (complete working implementations):
1. Root `{OUTPUT_DIR}/.env.example` and `{OUTPUT_DIR}/Makefile` (targets: `help`, `install`, `lint`, `build-sandbox`, `push-sandbox`, `sandbox-lifecycle-demo`, `tf-plan`, `tf-apply`, `package-skill`, `eval-offline`, `eval-simulated`, `validate-skills`, `verify-lab`).
2. `eval/datasets/coding_agent_eval.jsonl`: 8 realistic Coding Agent evaluation cases (unit-test generation, bug fixing, security audit using Skill Registry, sandbox command execution, multi-turn debugging, prompt-injection/tainted-session refusal, session memory recall, out-of-scope refusal).
3. `eval/run_offline_eval.py`: Runs offline evaluation over traces/sessions/dataset with trajectory, tool-use, and custom coding-quality rubrics + failure clustering via `vertexai.evals` / Agent Platform SDK.
4. `eval/run_simulated_eval.py`: Implements the 2-step User Simulation workflow (scenario generation from agent info + multi-turn simulated conversation execution).
5. `eval/setup_online_monitor.py`: Configures Agent Platform Online Evaluation Monitors (sampling rate, OTel telemetry prerequisites, metrics).
6. `eval/setup_quality_alerts.py`: Creates Cloud Monitoring alerting policies on evaluation quality metrics using `google.cloud.monitoring_v3` AND prints equivalent `gcloud` commands.
7. `eval/optimize_prompt.py`: Closed-loop prompt/instruction optimization referencing failure clusters, Feedback Service data, `adk.dev/optimize/`, and `agents-cli eval optimize`.
8. `{OUTPUT_DIR}/scripts/validate_skills.py`: Standalone Python CLI validator checking every skill under `.agents/skills/`:
   - Valid YAML frontmatter (`name` kebab-case `<=64` chars matching dir name, `description` using `>-` and `<1024` chars, includes `Use when` and `Don't use for`)
   - `SKILL.md` `<500` lines (fail at `>500` soft warning or `>800` hard fail — enforce `<=500` strictly for our production skills!)
   - All relative links (`references/*.md`) resolve to existing files, zero orphan `references/*.md` files, and zero 2-hop reference links (references must not link to other references as deep chains).
9. `{OUTPUT_DIR}/scripts/package_registry_skill.py`: Builds a Skill Registry `.zip` from any skill folder and validates ALL 14 official Google Cloud Skill Registry payload validation rules (`--dry-run` supported!).
10. `{OUTPUT_DIR}/scripts/verify_lab.sh`: Executable Bash script (`chmod +x`) allowing attendees to verify Labs 1–6 locally (`./scripts/verify_lab.sh <1..6|all>`).
""",
    },
]


def make_project_batch(b):
    fact_list = ", ".join(f"`{FACTS_DIR}/{f}`" for f in b["facts"])
    prompt = f"""
You are a Staff Cloud & Agent Platform Engineer executing **Round 7 ({b['name']})**.
Read the verified fact sheets: {fact_list}, plus `{OUTPUT_DIR}/workshop/` files relevant to your track so every filename, env var, and `TODO(lab-N)` aligns 100%.

{b['instructions']}

Validate all Python files you create with `python3 -m py_compile` before finishing.

{SAFETY_BOUNDARY}
"""
    return retry(
        lambda: agent(prompt, schema=ROUND_WORK_SCHEMA, role=f"Round 7: {b['name'][:38]}"),
        attempts=2,
    )


r7_results = await bounded_parallel(PROJECT_BATCHES, make_project_batch, max_concurrency=3)
ledger["rounds"].append({"round": 7, "batches": r7_results})
save_ledger(ledger)

# --- ROUND 8: Starter & Solution Project v3 (Adversarial Code, API & Parity Audit + Fixes) ---
phase("Round 8/15: Starter & Solution v3 (Adversarial API, Terraform, Dockerfile & Parity Audit)")
r8_critique = await retry(
    lambda: agent(
        f"""
You are a Principal Code & API Verification Reviewer executing **Round 8 Critique**.
Inspect `{OUTPUT_DIR}/starter/`, `{OUTPUT_DIR}/solution/`, `{OUTPUT_DIR}/scripts/`, `{OUTPUT_DIR}/Makefile`, and `{OUTPUT_DIR}/.env.example`.
Cross-check EVERY file against `{FACTS_DIR}/*.md` and run quick read-only syntax checks via `run_command` (e.g. `python3 -m py_compile` on all `.py` files, `bash -n {OUTPUT_DIR}/scripts/verify_lab.sh`, JSONL validation).

Audit ruthlessly for:
1. Any hallucinated imports, wrong SDK signatures, or mismatch between `starter/` and `solution/` (including missing `sandbox_lifecycle.py` ops, missing `sandbox_execution.py` paths, or thin `session_manager.py` / `memory_bank_manager.py`).
2. Terraform errors (missing `depends_on` on `re_service_agent_ar_reader`, missing `gcp-sa-vertex-sandbox` binding, invalid HCL syntax, wrong provider version).
3. Dockerfile security violations (must be non-root `USER`, Linux, expose runner port, no `sudo`, clean `/exec` contract).
4. `starter/` must have clean `# TODO(lab-N)` markers matching `workshop/01..06`, while `solution/` must have ZERO `TODO(lab-` markers.
5. `scripts/validate_skills.py` and `scripts/package_registry_skill.py` correctness against all 14 Skill Registry rules.

Do NOT edit files yet; return exact file-by-file fixes in JSON.

{SAFETY_BOUNDARY}
""",
        schema=CRITIQUE_SCHEMA,
        role="Round 8: Code & API Critic",
    ),
    attempts=2,
)
log(f"Round 8 Code Critique score={r8_critique['overall_score']}, blocking={len(r8_critique['blocking_issues'])}")

r8_fix = await retry(
    lambda: agent(
        f"""
You are a Staff Engineer executing **Round 8 Code Refinement**.
Fix EVERY blocking issue and high-value improvement reported by the Round 8 Code Critic across `{OUTPUT_DIR}/starter/`, `{OUTPUT_DIR}/solution/`, `{OUTPUT_DIR}/scripts/`, `Makefile`, and `.env.example`:

CRITIQUE REPORT:
{json.dumps(r8_critique, indent=2)}

Verify every modified `.py` file with `python3 -m py_compile` and verify `scripts/package_registry_skill.py --dry-run` passes on `solution/skills_to_register/secure-code-review`.

{SAFETY_BOUNDARY}
""",
        schema=ROUND_WORK_SCHEMA,
        role="Round 8: Code Refinement",
    ),
    attempts=2,
)
ledger["rounds"].append({"round": 8, "critique": r8_critique, "fix": r8_fix})
save_ledger(ledger)

# --- ROUND 9: Production Antigravity Skills v1 (Parallel Modular Authoring of All 6 Skills) ---
phase("Round 9/15: Production Antigravity Skills v1 (6 Modular Skills under .agents/skills/)")

SKILL_SPECS = [
    {
        "name": "adk-coding-agent-build",
        "facts": ["01_build.md"],
        "seed_urls": [
            "https://adk.dev/get-started/",
            "https://github.com/google/agents-cli",
        ],
        "refs": [
            "references/adk-core-and-setup.md",
            "references/agents-cli-lifecycle.md",
            "references/coding-agent-toolsets.md",
            "references/maintenance.md",
        ],
        "scope": (
            "Build pillar: Building Coding Agents with Google ADK Python (LlmAgent, EnvironmentToolset, LocalEnvironment, "
            "custom BaseEnvironment, BashTool, callbacks, state, artifacts) and orchestrating development with google/agents-cli "
            "(setup, create, scaffold enhance, run, lint, eval, deploy, publish, infra, extensions). Explicitly state `Don't use for:` "
            "managed sandboxes (use `agent-platform-sandbox-byoc`), Terraform/sessions/memory (use `agent-platform-runtime-and-state`), "
            "registries/governance (use `agent-platform-governance-and-registries`), or duplicating generic `google-agents-cli-*` built-ins."
        ),
    },
    {
        "name": "agent-platform-sandbox-byoc",
        "facts": ["02_sandbox.md"],
        "seed_urls": [
            "https://docs.cloud.google.com/gemini-enterprise-agent-platform/scale/sandbox",
        ],
        "refs": [
            "references/custom-containers-byoc.md",
            "references/sandbox-lifecycle-management.md",
            "references/sandbox-execution-and-adk.md",
            "references/security-networking-egress.md",
            "references/maintenance.md",
        ],
        "scope": (
            "Scale pillar (Sandboxes): Building and deploying custom container images (BYOC) for Gemini Enterprise Agent Platform "
            "Sandboxes, full Sandbox/Template/Snapshot lifecycle management (create/get/list/pause/resume/snapshot/delete), "
            "executing commands/code across Shell (`execute_bash`), BYOC (`/exec` runner), and Code Execution (`AgentEngineSandboxCodeExecutor` "
            "& custom ADK `BaseEnvironment`), plus security boundaries (gVisor, `gcp-sa-vertex-sandbox`, no ambient creds/metadata server, "
            "PSC `network_attachment` + Cloud NGFW/SWP/DNS peering, VPC-SC, CMEK, TTL 7d/14d, cold-start 2m, audit/stdout gaps). "
            "Explicitly state `Don't use for:` GKE Agent Sandbox (use `agent-runtime-vs-gke-architecture`) or Agent Runtime deployment."
        ),
    },
    {
        "name": "agent-platform-runtime-and-state",
        "facts": ["03_runtime_state.md"],
        "seed_urls": [
            "https://docs.cloud.google.com/gemini-enterprise-agent-platform/scale/runtime/use-terraform",
            "https://docs.cloud.google.com/gemini-enterprise-agent-platform/scale/runtime/manage-deployed-agents",
            "https://docs.cloud.google.com/gemini-enterprise-agent-platform/scale/runtime/tracing",
            "https://docs.cloud.google.com/gemini-enterprise-agent-platform/scale/runtime/logging",
            "https://docs.cloud.google.com/gemini-enterprise-agent-platform/scale/runtime/monitoring",
            "https://docs.cloud.google.com/gemini-enterprise-agent-platform/scale/feedback-service",
            "https://docs.cloud.google.com/gemini-enterprise-agent-platform/scale/sessions",
            "https://docs.cloud.google.com/gemini-enterprise-agent-platform/scale/memory-bank",
        ],
        "refs": [
            "references/terraform-deployment.md",
            "references/runtime-management-and-quotas.md",
            "references/sessions-and-memory-bank.md",
            "references/feedback-service.md",
            "references/runtime-telemetry.md",
            "references/maintenance.md",
        ],
        "scope": (
            "Scale pillar (Agent Runtime, State & Telemetry): Declarative Terraform deployment (`google_vertex_ai_reasoning_engine` BYOC, "
            "Dockerfile root-of-tar, package_spec, Secret Manager, `gcp-sa-aiplatform-re` IAM `depends_on`), managing deployed agents "
            "(list/get/update/delete/emergency-stop, revisions/traffic, runtime contract, exact quotas & QPM sizing math), "
            "Managed Sessions (ADK `VertexAiSessionService` + API + IAM conditions), Memory Bank (setup, ADK `VertexAiMemoryBankService`, "
            "generate/retrieve scope & similarity, TTL, prompt-injection governance, CMEK/VPC-SC), Feedback Service (SDK/API & UI), "
            "and Runtime Tracing (OTel), Logging (`reasoning_engine_stdout`, structured JSON), and Monitoring (built-in/custom metrics, PromQL, alerts)."
        ),
    },
    {
        "name": "agent-platform-governance-and-registries",
        "facts": ["04_govern.md"],
        "seed_urls": [
            "https://docs.cloud.google.com/gemini-enterprise-agent-platform/build/skill-registry",
        ],
        "refs": [
            "references/skill-registry-packaging.md",
            "references/agent-registry-and-discovery.md",
            "references/adk-consuming-registries.md",
            "references/semantic-governance-and-identity.md",
            "references/maintenance.md",
        ],
        "scope": (
            "Build & Govern pillars (Registries, Consumption & Policies): Authoring, validating (all 14 ZIP rules), and managing skills "
            "in Skill Registry (including built-in `gcp-skill-registry` first-call quirk), registering/governing standalone skills, MCP servers, "
            "and A2A agents in Agent Registry, consuming them dynamically from ADK (`GCPSkillRegistry`, `SkillToolset`, `AgentRegistry` with "
            "`google-adk[a2a,agent-identity]`, `httpx.Auth`, `header_provider`, sandbox egress caveat), Agent Identity (SPIFFE), "
            "and authoring Semantic Governance Policies (Natural Language Constraints intercepting `load_skill` / `run_skill_script` / supply chain)."
        ),
    },
    {
        "name": "agent-platform-optimize-and-eval",
        "facts": ["05_optimize.md"],
        "seed_urls": [
            "https://docs.cloud.google.com/gemini-enterprise-agent-platform/optimize/observability/overview",
            "https://docs.cloud.google.com/gemini-enterprise-agent-platform/optimize/evaluation/agent-evaluation",
            "https://docs.cloud.google.com/gemini-enterprise-agent-platform/optimize/evaluation/evaluate-online",
            "https://docs.cloud.google.com/gemini-enterprise-agent-platform/optimize/evaluation/evaluate-offline",
            "https://docs.cloud.google.com/gemini-enterprise-agent-platform/optimize/evaluation/evaluate-simulated",
            "https://docs.cloud.google.com/gemini-enterprise-agent-platform/optimize/evaluation/view-results",
            "https://docs.cloud.google.com/gemini-enterprise-agent-platform/optimize/evaluation/quality-alerts",
            "https://docs.cloud.google.com/gemini-enterprise-agent-platform/optimize/evaluation/optimize-agent",
        ],
        "refs": [
            "references/observability-overview.md",
            "references/offline-and-simulated-eval.md",
            "references/online-eval-and-alerts.md",
            "references/agent-optimization-flywheel.md",
            "references/maintenance.md",
        ],
        "scope": (
            "Optimize pillar: Agent Platform Observability overview (GenAI OTel conventions, audit logs, tamper-evident retention, SIEM export, "
            "emergency stop/propagation latency), Offline Evaluation (traces vs sessions, registry & single-trace eval, built-in/rubric/adaptive metrics), "
            "Simulated User Evaluation (2-step workflow, personas, SDK), Online Evaluation Monitors (telemetry prereqs, sampling, troubleshooting), "
            "Viewing Results & Failure Clustering (Console + `vertexai.evals` SDK), Quality Alerts (Console, `gcloud`, `google.cloud.monitoring_v3`), "
            "and Optimize Agent (`adk.dev/optimize/`, `agents-cli eval optimize`, Feedback-to-Eval-to-Canary flywheel)."
        ),
    },
    {
        "name": "agent-runtime-vs-gke-architecture",
        "facts": ["06_gke_comparison.md", "02_sandbox.md", "03_runtime_state.md"],
        "seed_urls": [
            "https://docs.cloud.google.com/gemini-enterprise-agent-platform/scale/sandbox",
            "https://docs.cloud.google.com/gemini-enterprise-agent-platform/scale/runtime/manage-deployed-agents",
            "https://github.com/google/agents-cli",
        ],
        "refs": [
            "references/comparison-matrix-and-limitations.md",
            "references/gke-agent-sandbox-reference.md",
            "references/hybrid-and-migration-patterns.md",
            "references/maintenance.md",
        ],
        "scope": (
            "Architecture & Limitations Decision Guide: Comparing Gemini Enterprise Agent Platform (Agent Runtime + Managed BYOC Sandbox) "
            "against Self-Hosted ADK on GKE + GKE Agent Sandbox (`kubernetes-sigs/agent-sandbox`) + GKE Agent Substrate and `agents-cli` "
            "multi-target workflows. Covers all 14+ verified limitation dimensions (TTL, cold start/warm pools, GPU/TPU/gVisor/microVM/Kata, "
            "GKE Pod Snapshots >=1.35.3 & non-E2, PSC+NGFW/SWP vs NetworkPolicy & Dataplane V2 cardinality, SPIFFE vs WIF, stdout/audit gaps, "
            "exact Agent Platform quotas, ops overhead), `GkeCodeExecutor(executor_type='sandbox'|'job')`, and hybrid/migration patterns."
        ),
    },
]


def make_skill_author(sk):
    fact_list = ", ".join(f"`{FACTS_DIR}/{f}`" for f in sk["facts"])
    skill_dir = OUTPUT_DIR / ".agents/skills" / sk["name"]
    prompt = f"""
You are a Staff Agent Skill Author building a **PRODUCTION-LEVEL, MODULAR Antigravity skill** at `{skill_dir}`.

Read the verified fact sheet(s): {fact_list}, and check raw pages in `{CORPUS_DIR}/pages/` whenever you need exact commands, code snippets, or tables.

Strict Production Skill Rules (MUST ALL PASS `validate_skills.py`):
1. **`{skill_dir}/SKILL.md`**:
   - YAML frontmatter with exact `name: {sk['name']}` and `description: >-` (strictly `< 1024` characters! Third-person capability statement + `Use when...` listing EVERY subtopic covered in `references/` so there is ZERO Frontmatter Blindness + `Don't use for...` disambiguating sibling skills and `google-agents-cli-*` built-in skills!).
   - Keep `SKILL.md` lean, high-signal, imperative, opinionated cheatsheet: **150–380 lines (STRICTLY `< 450` lines)**!
   - Include: Quick Decision Tree / When to Use, Critical Gotchas ("Do this, not that" with *why*), Quick-Start Command/Code Patterns, a clear **Modular References Table** linking directly to EVERY file in `references/*.md` (1-level deep only!), and a `## Maintenance` footer linking `references/maintenance.md`.
   - Do NOT dump bulky reference tables/schemas into `SKILL.md` — offload them to the separate modular `references/*.md` files so each section is easy to maintain independently!
2. **Modular Reference Files (write EVERY file listed below)**:
   {json.dumps(sk['refs'], indent=2)}
   - Each reference file covers ONE clean domain section in production depth (verified imports, exact CLI flags, Terraform/YAML/Python snippets, error modes & fixes, exact limits/quotas, and concrete verification steps).
   - Reference files MUST NOT chain-link to other reference files (keep links strictly 1-level deep from `SKILL.md`).
   - `references/maintenance.md` MUST list EVERY canonical upstream URL (including ALL of these seed URLs: {json.dumps(sk['seed_urls'])} PLUS all relevant Tier-1 sub-links from the fact sheet!), their `.md.txt` / `.md` refresh endpoints, verification date (`2026-11-19`), and section-by-section update checklist.
3. **Domain Scope**:
   {sk['scope']}

{SAFETY_BOUNDARY}
"""
    return retry(
        lambda: agent(prompt, schema=ROUND_WORK_SCHEMA, role=f"Round 9 Skill: {sk['name']}"),
        attempts=2,
    )


r9_results = await bounded_parallel(SKILL_SPECS, make_skill_author, max_concurrency=3)
ledger["rounds"].append({"round": 9, "skills": r9_results})
save_ledger(ledger)

# --- ROUND 10: Production Antigravity Skills v2 (Trigger Simulation, 20-URL Coverage & Signal Audit + Fixes) ---
phase("Round 10/15: Production Antigravity Skills v2 (Trigger Simulation, 20-URL Audit & Refinement)")
r10_critique = await retry(
    lambda: agent(
        f"""
You are a Principal Antigravity Skill Quality & Trigger Calibration Auditor executing **Round 10 Critique**.

1. Run `python3 {OUTPUT_DIR}/scripts/validate_skills.py {OUTPUT_DIR}/.agents/skills` via `run_command` and capture every error/warning.
2. Read ALL 6 `SKILL.md` files under `{OUTPUT_DIR}/.agents/skills/*/SKILL.md` and inspect their `references/*.md` files.
3. Verify **100% coverage** of ALL 20 user seed URLs + critical sub-links (Sandbox lifecycle, Sandbox execution, BYOC Dockerfile, Sessions, Memory Bank, Feedback, Skill Registry, Agent Registry, Semantic Governance, Terraform, Manage Deployed Agents, Tracing/Logging/Monitoring, Observability, Offline/Online/Simulated Eval, View Results, Quality Alerts, Optimize Agent, ADK, `agents-cli`, GKE Agent Sandbox).
4. **Simulate 24 realistic customer workshop prompts** (4 per skill, plus edge cases overlapping `google-agents-cli-*` built-ins) strictly against the 6 YAML frontmatter `description` fields:
   - Catch any **Frontmatter Blindness** (a topic exists in `references/` but isn't triggered by `description`).
   - Catch any **Co-Trigger Shadowing** (ambiguous overlap between sibling skills or `google-agents-cli-*`).
   - Catch any `SKILL.md` over 450 lines, duplicate content between `SKILL.md` and `references/`, or unverified APIs/flags.

Do NOT edit files yet; return exact actionable fixes in JSON.

{SAFETY_BOUNDARY}
""",
        schema=CRITIQUE_SCHEMA,
        role="Round 10: Skill Trigger & Quality Critic",
    ),
    attempts=2,
)
log(f"Round 10 Skill Critique score={r10_critique['overall_score']}, blocking={len(r10_critique['blocking_issues'])}")

r10_fix = await retry(
    lambda: agent(
        f"""
You are the Lead Antigravity Skill Architect executing **Round 10 Refinement**.
Fix EVERY blocking issue, validator error, trigger gap, and coverage gap reported by the Round 10 Skill Critic across `{OUTPUT_DIR}/.agents/skills/`:

CRITIQUE REPORT:
{json.dumps(r10_critique, indent=2)}

After editing, run `python3 {OUTPUT_DIR}/scripts/validate_skills.py {OUTPUT_DIR}/.agents/skills` to confirm exit code 0!

{SAFETY_BOUNDARY}
""",
        schema=ROUND_WORK_SCHEMA,
        role="Round 10: Skill Refinement",
    ),
    attempts=2,
)
ledger["rounds"].append({"round": 10, "critique": r10_critique, "fix": r10_fix})
save_ledger(ledger)

# --- ROUND 11: Holistic Cross-Deliverable Alignment & End-to-End Customer Dry-Run ---
phase("Round 11/15: End-to-End Customer Dry-Run & Cross-Deliverable Alignment")
r11 = await retry(
    lambda: agent(
        f"""
You are a Customer Solutions Architect performing a full **Round 11 End-to-End Dry-Run & Alignment Audit** across `{OUTPUT_DIR}`.

Walk sequentially through the ENTIRE customer journey from Lab 0 -> Lab 7:
1. Check every file path, Python module path (`coding_agent.tools.sandbox_lifecycle`, `coding_agent.tools.sandbox_execution`, `coding_agent.memory.session_manager`, `coding_agent.memory.memory_bank_manager`, `coding_agent.tools.registry_loader`, `coding_agent.callbacks.telemetry_and_feedback`, `eval/*.py`), class/function name, `TODO(lab-N)` marker, `Makefile` target, `.env.example` variable, Terraform variable/output, and `.agents/skills/<name>` name referenced in `README.md` and `workshop/00..07` + `FACILITATOR-GUIDE.md`.
2. Verify that EVERY reference matches the ACTUAL files on disk in `starter/`, `solution/`, `scripts/`, and `.agents/skills/` (zero stale paths, zero mismatched env var names, zero missing `Makefile` targets!).
3. Directly edit any files that have mismatches so all 4 deliverables (Workshop Docs, Starter Project, Solution Project, Antigravity Skills) interlock cleanly as one unified customer kit!
4. Run `bash -n {OUTPUT_DIR}/scripts/verify_lab.sh` and `python3 {OUTPUT_DIR}/scripts/validate_skills.py {OUTPUT_DIR}/.agents/skills` to verify nothing broke.

{SAFETY_BOUNDARY}
""",
        schema=ROUND_WORK_SCHEMA,
        role="Round 11: End-to-End Alignment Dry-Run",
    ),
    attempts=2,
)
ledger["rounds"].append(r11)
save_ledger(ledger)

# --- ROUNDS 12..15: Deterministic Static Gate + Iterative Convergence Loop ---
final_static = None
final_critique = None

for round_num in range(MIN_ROUNDS, MAX_ROUNDS + 1):
    phase(f"Round {round_num}/{MAX_ROUNDS}: Automated Verification Gate & Convergence Audit")
    static_res = run_static_checks()
    final_static = static_res
    log(
        f"Round {round_num} static checks: passed={static_res['passed']} "
        f"errors={len(static_res['errors'])} warnings={len(static_res['warnings'])} "
        f"metrics={json.dumps(static_res['metrics'])}"
    )

    critique = await retry(
        lambda rn=round_num, sr=static_res: agent(
            f"""
You are the Principal Release Auditor executing **Convergence Round {rn}/{MAX_ROUNDS}** for `{OUTPUT_DIR}`.

Automated static verification report:
{json.dumps(sr, indent=2)}

Inspect the actual repository files (`README.md`, `workshop/`, `starter/`, `solution/`, `.agents/skills/`, `scripts/`) and score strictly (0-100) on 4 production dimensions:
1. `doc_coverage`: Are ALL 20 user seed URLs + critical sub-links (Sandbox BYOC/lifecycle/exec, Sessions, Memory Bank, Feedback, Terraform, Manage Deployed Agents, Tracing/Logging/Monitoring, Skill Registry, Agent Registry, Semantic Governance, Observability, Offline/Online/Simulated Eval, View Results, Quality Alerts, Optimize Agent, ADK, agents-cli, GKE Agent Sandbox/Substrate) thoroughly and accurately reflected?
2. `api_code_accuracy`: Are starter & solution code (especially `sandbox_lifecycle.py`, `sandbox_execution.py`, `session_manager.py`, `memory_bank_manager.py`, `registry_loader.py`, `Dockerfile`, `terraform/`, `eval/`, `gke_reference/`) syntactically valid, API-accurate, and cleanly structured with `TODO(lab-N)` parity?
3. `workshop_pedagogy`: Are `workshop/00..07` + `FACILITATOR-GUIDE.md` crystal clear, well-paced (Full-Day + Half-Day), practical, and honest about limitations/quotas/gotchas?
4. `skill_production_quality`: Do all 6 `.agents/skills/` pass `validate_skills.py`, stay modular & easy to maintain (`references/<section>.md` + `maintenance.md`), avoid Co-Trigger Shadowing & Frontmatter Blindness, and deliver high signal-to-noise?

Any static error MUST appear in `blocking_issues` and cap the affected score at `<= 88`.
Only award `>= 95` across all 4 scores when the kit is genuinely ready to hand directly to an enterprise GCP customer!

{SAFETY_BOUNDARY}
""",
            schema=CRITIQUE_SCHEMA,
            role=f"Round {rn}: Release Auditor",
        ),
        attempts=2,
    )
    final_critique = critique
    scores = critique["scores"]
    min_score = min(scores.values())
    log(
        f"Round {round_num} Auditor scores: {scores} (overall={critique['overall_score']}, "
        f"blocking={len(critique['blocking_issues'])})"
    )

    converged = (
        static_res["passed"]
        and min_score >= 95
        and critique["overall_score"] >= 95
        and len(critique["blocking_issues"]) == 0
    )

    if converged or round_num == MAX_ROUNDS:
        ledger["rounds"].append(
            {
                "round": round_num,
                "static_checks": static_res,
                "critique": critique,
                "converged": converged,
            }
        )
        save_ledger(ledger)
        if converged:
            log(f"CONVERGED at Round {round_num} with overall_score={critique['overall_score']}!")
            break
        # If Round 15 still had blocking items, do one final surgical fix pass right before exit
        if critique["blocking_issues"] or not static_res["passed"]:
            phase(f"Round {round_num}b: Final Surgical Remediation")
            fix_final = await retry(
                lambda c=critique, sr=static_res: agent(
                    f"""
Apply surgical fixes for all remaining static errors and blocking issues in `{OUTPUT_DIR}`:
STATIC ERRORS: {json.dumps(sr['errors'], indent=2)}
BLOCKING ISSUES: {json.dumps(c['blocking_issues'], indent=2)}
{SAFETY_BOUNDARY}
""",
                    schema=ROUND_WORK_SCHEMA,
                    role="Round 15: Final Remediation",
                ),
                attempts=2,
            )
            final_static = run_static_checks()
            ledger["rounds"].append({"round": "15b", "fix": fix_final, "static_checks": final_static})
            save_ledger(ledger)
        break

    # Apply targeted convergence refinement and loop to next round!
    fix = await retry(
        lambda rn=round_num, c=critique, sr=static_res: agent(
            f"""
You are the Principal Refinement Engineer executing **Round {rn} Targeted Fix Pass** in `{OUTPUT_DIR}`.
Resolve EVERY static check error, blocking issue, and top improvement below so the next convergence round scores >=95/100 across all 4 rubric dimensions:

STATIC ERRORS & WARNINGS:
{json.dumps({"errors": sr["errors"], "warnings": sr["warnings"]}, indent=2)}

AUDITOR CRITIQUE:
{json.dumps(c, indent=2)}

Verify fixes directly with `python3 {OUTPUT_DIR}/scripts/validate_skills.py {OUTPUT_DIR}/.agents/skills` and `python3 -m py_compile` on touched Python files.

{SAFETY_BOUNDARY}
""",
            schema=ROUND_WORK_SCHEMA,
            role=f"Round {rn}: Refinement Pass",
        ),
        attempts=2,
    )
    ledger["rounds"].append(
        {"round": round_num, "static_checks": static_res, "critique": critique, "fix": fix, "converged": False}
    )
    save_ledger(ledger)

# ===========================================================================
# PHASE 3: Export Reusable Automation Artifacts & Summary
# ===========================================================================
phase("Phase 3: Export Reusable Automation & Provenance Manifest")
auto_dir = OUTPUT_DIR / "automation"
auto_dir.mkdir(parents=True, exist_ok=True)
shutil.copy2(HARVESTER, auto_dir / "harvest_corpus.py")
shutil.copy2(SCRATCH_DIR / "run_workshop_builder.py", auto_dir / "run_workshop_builder.py")
shutil.copy2(CORPUS_DIR / "corpus_manifest.json", auto_dir / "corpus_manifest.json")
shutil.copy2(LEDGER_PATH, auto_dir / "workflow_round_ledger.json")

ledger["finished_at"] = datetime.now(timezone.utc).isoformat()
ledger["final_static_checks"] = final_static
ledger["final_critique"] = final_critique
save_ledger(ledger)
shutil.copy2(LEDGER_PATH, auto_dir / "workflow_round_ledger.json")

print(
    json.dumps(
        {
            "output_dir": str(OUTPUT_DIR),
            "rounds_completed": len(ledger["rounds"]),
            "final_static_checks": final_static,
            "final_scores": final_critique["scores"] if final_critique else None,
            "final_overall_score": final_critique["overall_score"] if final_critique else None,
        },
        indent=2,
    )
)
