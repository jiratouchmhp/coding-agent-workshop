---
name: agent-platform-optimize-and-eval
description: >-
  Observes, evaluates, alerts on, and optimizes Agent Platform agents. Use when
  configuring Optimize-pillar GenAI OTel v1.37+ multimodal GCS/BigQuery
  capture, WORM/SIEM audit & policy propagation latency, or Anomaly Detection;
  running offline trace/session evals, rubric metrics (safety_v3 polarity,
  multi_turn_*), Metric Registry, or simulated user evals (vertexai.evals,
  agents-cli eval synthesize/analyze/submit); setting up Online Monitors,
  failure clustering (generate_loss_clusters, 26 Loss Patterns), or
  OnlineEvaluator Quality Alerts (online_evaluator/scores, gcloud,
  monitoring_v3); or optimizing prompts/skills (adk optimize, GEPA,
  SimplePromptOptimizer, Example Store, Feedback-to-Eval-to-Canary flywheel).
  Don't use for ADK build (adk-coding-agent-build), sandboxes
  (agent-platform-sandbox-byoc), runtime/state/PromQL
  (agent-platform-runtime-and-state), registries/UAP
  (agent-platform-governance-and-registries), GKE
  (agent-runtime-vs-gke-architecture), or generic
  google-agents-cli-{eval,observability}.
---

# Agent Platform Observability, Evaluation & Optimization

Production playbook for the **Optimize pillar** of Google Cloud's **Gemini Enterprise Agent Platform**: OpenTelemetry GenAI observability, tamper-evident audit/SIEM security ops, offline & simulated evaluation, continuous online monitors, automatic loss clustering, Cloud Monitoring quality alerts, and automated prompt/skill optimization.

## SDK & Environment Baseline

> **Preferred SDK & Fallback Split:** On `google-cloud-agentplatform[adk,evaluation]>=2.0.1` / `google-cloud-aiplatform>=1.154.0`, prefer **`agentplatform.Client(project=..., location="global")`** (and `agentplatform.types`) for evaluation, Feedback Service harvest, Canary `trafficSplitManual` rollouts, and Emergency Stop (`runtimes.delete`) — falling back to `from vertexai import Client, types` only on older builds to avoid `vertexai.Client` `FutureWarning` deprecations.

```bash
pip install --upgrade "google-cloud-agentplatform[adk,evaluation]>=2.0.1" "google-cloud-aiplatform[adk,evaluation]>=1.154.0" "google-adk>=2.0.0" "google-genai>=2.34.0" "google-cloud-monitoring"
# Optional: multimodal GCS OTel capture requires exact pinned fsspec
pip install "opentelemetry-instrumentation-google-genai>=0.4b0" "fsspec[gcs]==2025.10.0"

export GOOGLE_CLOUD_PROJECT="PROJECT_ID"
export PRIMARY_REGION="asia-southeast3"         # Bangkok default (AR, Cloud Build, Secrets, Agent Registry A2A/MCP)
export GOOGLE_CLOUD_LOCATION="asia-southeast1"  # Singapore fallback (Agent Runtime, Feedback & Canary rollouts — not yet in Bangkok)
export MODEL_LOCATION="global"                  # Frontier Gemini 4 Hydrogen/Neon inference (or asia-southeast1 with gemini-4-argon)
export EVAL_LOCATION="global"                   # APAC-ready Gen AI Eval region (14 US/EU + global) & required for generate_loss_clusters
export SKILL_REGISTRY_LOCATION="us-central1"    # Vertex AI Skill Registry Preview (3 regions only)
```

---

## Quick Decision Tree

| Task / Goal | Go Here |
|---|---|
| OTel GenAI semconv v1.37.0+ env vars, multimodal GCS JSONL capture + BigQuery/BigLake SQL, ADK span hierarchy, Console dashboards, dual-attribution (`is_agentic=true`), WORM locked log buckets, SIEM Pub/Sub sink, emergency stop propagation, Agent Anomaly Detection (OWASP ASI02/03/08/10) | [Observability & Security Ops](references/observability-overview.md) |
| Offline eval of historical traces vs. sessions, 15 supported regions, managed rubric metrics + LLM call cost + `safety_v3` polarity, Metric Registry (`LLMMetric`/`CodeExecutionMetric`), `vertexai.evals` SDK, 2-step Simulated User eval (`generate_conversation_scenarios`, `run_inference`, `eval dataset synthesize`), `agents-cli eval` schema & CI gating | [Offline & Simulated Evaluation](references/offline-and-simulated-eval.md) |
| Continuous Online Monitors (10-min loop, sampling/cost cap, P4SA security & 30-min wait, Logs Explorer queries), Viewing Results & Automatic Loss Analysis (`generate_loss_clusters`, `eval analyze`, all 26 Loss Patterns), 7-step triage, and Quality Alerts (Console, `gcloud`, `monitoring_v3`) | [Online Eval, Clustering & Alerts](references/online-eval-and-alerts.md) |
| Automated prompt/skill optimization (`adk optimize`, `GEPARootAgentPromptOptimizer`, `GEPARootAgentOptimizer`, `SimplePromptOptimizer`, custom `Sampler`/`AgentOptimizer`), `agents-cli eval optimize`, zero-redeploy Example Store (max 50/region), and Feedback-to-Eval-to-Canary flywheel | [Agent Optimization Flywheel](references/agent-optimization-flywheel.md) |
| Upstream source URLs (`.md.txt` / `.md` refresh endpoints), verification date (`2026-11-23`), and section-by-section update checklist | [Maintenance Manifest](references/maintenance.md) |

---

## Critical Gotchas (Do This, Not That)

1. **Check `safety_v3` vs. `safety_v1` score polarity before gating CI or setting Quality Alerts — never assume `1.0` means safe on `safety_v3`.**
   - *Why:* Verified in `rubric-metric-details`: **`safety_v3`** (modern Gemini 3.5 Flash default, 31× calls) returns **`1` = UNSAFE** (policy violated) and **`0` = SAFE**, the **exact opposite** of legacy `safety_v1` (`1` = safe, `0` = unsafe). Standardize on `types.RubricMetric.SAFETY(version="v3")` with inverted checks (`COMPARISON_GT`, e.g., `> 0.05` in alerts), or explicitly pin `version=` so polarity never shifts silently.
2. **Pass `dataset=` to `client.evals.evaluate(...)`, typed `EvaluationDataset` to `run_inference(src=...)`, expand `BaseToolset`s before `AgentInfo.load_from_agent(...)`, and strip ADK 2.15 `content=None` events before grading simulated traces.**
   - *Why:* `client.evals.evaluate()` requires `dataset=` (`traces=` raises `TypeError`); `run_inference(src=...)` rejects raw Python `dict`s (use `types.EvaluationDataset.model_validate(...)`, DataFrame, or file path); in `google-cloud-agentplatform==2.10.0`, `types.evals.AgentInfo.load_from_agent(agent=...)` crashes with `TypeError: Expected a callable object, got EnvironmentToolset` on ADK `BaseToolset` instances unless you expand `await toolset.get_tools()` onto a clone first; and ADK 2.15.0 emits a trailing `end_of_agent` event with `content=None` that `agentplatform` copies into `turns[*].events`, causing Vertex Evaluation Service to fail every simulated case with HTTP 400 (`Required field is not set`) unless empty-content events are stripped before `evaluate()`.
3. **Run `generate_loss_clusters` and `agents-cli eval analyze` against `location="global"` — regional clients fail.**
   - *Why:* Automatic Loss Analysis (`GenerateLossClusters` LRO) is **`global`-only**. For multi-metric or multi-candidate runs, pass `metric=` and `candidate=` explicitly (`eval_result.metadata.candidate_names`).
4. **Use ONLY the 3 `multi_turn_*` metrics on multi-turn traces — never mix single-turn and multi-turn cases in one dataset.**
   - *Why:* Every built-in metric except `multi_turn_task_success`, `multi_turn_tool_use_quality`, and `multi_turn_trajectory_quality` rejects multi-turn traces with HTTP 400. Split single-turn and multi-turn suites into separate dataset + config pairs.
5. **Set `OTEL_INSTRUMENTATION_GENAI_CAPTURE_MESSAGE_CONTENT` to `"EVENT_ONLY"` in ADK Python and `"true"` in ADK Go — never swap them.**
   - *Why:* ADK Python accepts only `NO_CONTENT | EVENT_ONLY | SPAN_ONLY | SPAN_AND_EVENT` (`"true"` silently falls back to `NO_CONTENT`, breaking evals). ADK Go reads it as a boolean (`"1"`/`"true"`) and elides content on Python enum strings. Separately, GCS uploads (`COMPLETION_HOOK=upload`) do **not** honor this var.
6. **Provision Online Monitors in Console and wait 30 minutes on the first monitor's `"Failed"` warning — never invent SDK create methods or panic-edit P4SA IAM.**
   - *Why:* `vertexai._genai.evals.Evals` (`v1.153.1`) exposes **no** programmatic `OnlineEvaluator` create method. On a project's first monitor, P4SA IAM propagation often triggers a transient `"permission denied"` failure that self-heals on the 10-minute retry loop. Restrict `OnlineEvaluator` creation to admins (P4SA can attach to any agent in the project).
7. **Pair UAP/IAM revocation with `runtimes.delete(force=True)` or `trafficSplitManual` rollback during active incidents — never rely on policy deny alone.**
   - *Why:* UAP and IAM denies are eventually consistent (**2–7+ min** globally; `principalSet` takes **minutes to hours**) and do **not** kill already-open streaming sessions. Also query recent audit logs with `--freshness=1d` (`--freshness=6h` can miss freshly indexed entries).
8. **Match ADK `App(name=...)` to the containing directory name and initialize template state keys in `before_agent_callback`.**
   - *Why:* Mismatched `App(name=...)` causes `"Session not found"` during `eval generate` and `adk optimize`; uninitialized `{state_key}` placeholders crash turn 0 with `KeyError`.
9. **Override ADK optimizer `model_configuration` + `GOOGLE_CLOUD_LOCATION=global`, load local `SkillToolset.skills` for `GEPARootAgentOptimizer`, and keep a holdout slice BEFORE running GEPA — never auto-loop GEPA.**
   - *Why:* In `google-adk==2.15.0`, `SimplePromptOptimizerConfig` and `GEPARootAgentPromptOptimizerConfig` default to retired `gemini-2.5-flash` AND `ThinkingConfig(thinking_budget=10240)` (**HTTP 400 on Gemini 4**), and their default `Gemini(model=...)` omits `location="global"` (**HTTP 404** when `GOOGLE_CLOUD_LOCATION=asia-southeast1`). Always set `optimizer_model="gemini-4-hydrogen"`, pass `ThinkingConfig(thinking_level="MEDIUM", include_thoughts=True)` (no `thinking_budget`), and export `GOOGLE_CLOUD_LOCATION=global` (or use `gemini-4-argon` regionally). GEPA optimizes **only root instructions** (plus local in-memory `SkillToolset.skills` in `GEPARootAgentOptimizer`, NOT lazy remote `GCPSkillRegistry` handles). Preserve YAML frontmatter on optimized `SKILL.md` files, validate on holdout, then hot-update skills via `client.skills.update` or Agent Registry `revisions create` + `skills update --default-revision=... --target-state=active`.
10. **Pin `fsspec[gcs]==2025.10.0` for GCS multimodal capture and grant write IAM to the agent Service Account — not your user account.**
    - *Why:* Other `fsspec` versions break OTel JSONL uploads; missing SA roles (`roles/storage.objectUser`, `roles/logging.logWriter`, `roles/monitoring.metricWriter`, `roles/telemetry.tracesWriter`) silently drop prompt/response payloads.

---

## Quick-Start Patterns

### 1. Mandatory OTel Env Vars + WORM Audit Bucket & SIEM Sink

```bash
# Required on Agent Runtime for Offline Eval & Online Monitors (ADK Python)
export GOOGLE_CLOUD_AGENT_ENGINE_ENABLE_TELEMETRY="true"
export OTEL_SEMCONV_STABILITY_OPT_IN="gen_ai_latest_experimental"
export OTEL_INSTRUMENTATION_GENAI_CAPTURE_MESSAGE_CONTENT="EVENT_ONLY"

# Tamper-evident WORM audit log bucket (1..3650 days; --locked is IRREVERSIBLE)
gcloud logging buckets create agent-audit-worm-bucket \
  --location=global --retention-days=365 --project=PROJECT_ID
gcloud logging buckets update agent-audit-worm-bucket \
  --location=global --locked --project=PROJECT_ID

# Stream Cloud Audit, Agent Gateway, Runtime & is_agentic=true logs to SIEM Pub/Sub topic
gcloud logging sinks create agent-audit-siem-sink \
  pubsub.googleapis.com/projects/DEST_PROJECT_ID/topics/SIEM_TOPIC \
  --log-filter='logName:("cloudaudit.googleapis.com" OR "networkservices.googleapis.com%2Fgateway_requests" OR "aiplatform.googleapis.com%2Freasoning_engine") OR jsonPayload.is_agentic=true OR labels.is_agentic="true"' \
  --project=PROJECT_ID
```

### 2. Simulated User Eval + Multi-Turn Grading + Global Failure Clustering (Python SDK)

```python
from google.adk.agents import Agent
try:
    from agentplatform import Client, types
except ImportError:
    from vertexai import Client, types

# Use location="global" so generate_loss_clusters works in the same client
client = Client(project="YOUR_PROJECT_ID", location="global")

agent_info = types.evals.AgentInfo.load_from_agent(agent=my_adk_agent)
scenarios = client.evals.generate_conversation_scenarios(
    agent_info=agent_info,
    config={"count": 10, "generation_instruction": "Test multi-turn edge cases and tool errors."},
)
traces_ds = client.evals.run_inference(
    agent=my_adk_agent,
    src=scenarios,
    config={"user_simulator_config": {"max_turn": 5}},
)
result = client.evals.evaluate(
    dataset=traces_ds,
    metrics=[
        types.RubricMetric.MULTI_TURN_TASK_SUCCESS,
        types.RubricMetric.MULTI_TURN_TOOL_USE_QUALITY,
    ],
)
result.show()

clusters = client.evals.generate_loss_clusters(
    eval_result=result,
    metric=types.RubricMetric.MULTI_TURN_TASK_SUCCESS,
)
clusters.show()
```

### 3. CI Eval Gating & Quality Drift Alert (`agents-cli` + `gcloud`)

```bash
# Local / CI eval loop with regression comparison
agents-cli eval run --dataset tests/eval/datasets/custom.json \
  --metrics final_response_quality --fail-under final_response_quality=0.8
agents-cli eval compare artifacts/grade_results/results_before.json \
  artifacts/grade_results/results_after.json

# Deploy Cloud Monitoring quality drift alert against OnlineEvaluator scores
gcloud monitoring policies create --policy-from-file="policy.yaml"
```

### 4. Automated Prompt Optimization (`adk optimize`)

```bash
# Directory must contain __init__.py exposing `agent.root_agent`; keep validation_eval_set separate!
# CRITICAL (ADK 2.15.0 + Gemini 4): export GOOGLE_CLOUD_LOCATION=global AND pass --optimizer_config_file_path
# overriding default retired gemini-2.5-flash + thinking_budget=10240 (which triggers HTTP 400 on Gemini 4)!
GOOGLE_CLOUD_LOCATION="${MODEL_LOCATION:-global}" adk optimize path/to/my_agent \
  --sampler_config_file_path path/to/my_agent/sampler_config.json \
  --optimizer_config_file_path path/to/my_agent/optimizer_config.json \
  --print_detailed_results \
  --log_level INFO
```

---

## Modular References

| Reference File | Scope & Production Deep-Dive Contents |
|---|---|
| [references/observability-overview.md](references/observability-overview.md) | OTel GenAI semconv v1.37.0+ prereqs, multimodal GCS JSONL capture + BigQuery/BigLake SQL, ADK span tree, Console dashboards, `agents-cli` content tiers, dual-attribution audit logs, WORM locked retention, SIEM Pub/Sub sink, emergency stop propagation, Agent Anomaly Detection |
| [references/offline-and-simulated-eval.md](references/offline-and-simulated-eval.md) | Traces vs. sessions, 15 regions + data-residency fallback, complete managed rubric matrix (`safety_v3` polarity, LLM call counts, version pinning), Console & `vertexai.evals` SDK, Metric Registry CRUD, 2-step Simulated User eval, `agents-cli eval` schema/config/CI gating |
| [references/online-eval-and-alerts.md](references/online-eval-and-alerts.md) | Online Monitor 10-min loop, `online_evaluator/*` metric descriptors, Console setup/lifecycle, P4SA security & 30-min wait, Logs Explorer queries, 3-level result analysis, `generate_loss_clusters`/`eval analyze`, all 26 Loss Patterns, 7-step triage, Quality Alerts (Console, `gcloud`, `monitoring_v3`) |
| [references/agent-optimization-flywheel.md](references/agent-optimization-flywheel.md) | ADK optimizer comparison (`GEPARootAgentPromptOptimizer`, `GEPARootAgentOptimizer`, `SimplePromptOptimizer`), `adk optimize` CLI & programmatic API, custom `Sampler`/`AgentOptimizer`, `agents-cli eval optimize` guardrails, Example Store (max 50), Feedback-to-Eval-to-Canary flywheel |
| [references/maintenance.md](references/maintenance.md) | All 8 canonical seed URLs, 22 verified Tier-1/deep-dive refresh endpoints (`.md.txt`/`.md`), verification date (`2026-11-23`), and section-by-section update checklist |

---

## Maintenance

Last verified `2026-11-23` against Gemini Enterprise Agent Platform Optimize docs, `vertexai._genai.evals.Evals` (`1.153.1`), `adk.dev/optimize/`, and `google/agents-cli` (`v1.15.0`). Follow [references/maintenance.md](references/maintenance.md) to refresh upstream sources and re-run `python3 scripts/validate_skills.py .agents/skills`.
