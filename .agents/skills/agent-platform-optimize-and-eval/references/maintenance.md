# Maintenance & Upstream Verification Manifest

**Last Verified:** `2026-11-19`
**Skill:** `agent-platform-optimize-and-eval`
**Scope:** Gemini Enterprise Agent Platform — Optimize Pillar (Observability Overview & Traces, Multimodal GCS Capture & BigQuery Analytics, Security Ops & Anomaly Detection, Offline & Simulated Evaluation, Metric Registry, Online Monitors, Failure Clustering, Quality Alerts, ADK/CLI Optimization, Example Store, and Feedback-to-Eval-to-Canary Flywheel).

---

## 1. Canonical Upstream Sources (All 8 Seed Pages + Verified Sub-Links)

### Seed Pages (8 — Required Coverage)

| # | Canonical Upstream URL | Markdown Refresh Endpoint | Mapped Reference File |
|---|---|---|---|
| 1 | https://docs.cloud.google.com/gemini-enterprise-agent-platform/optimize/observability/overview | https://docs.cloud.google.com/gemini-enterprise-agent-platform/optimize/observability/overview.md.txt | `references/observability-overview.md` |
| 2 | https://docs.cloud.google.com/gemini-enterprise-agent-platform/optimize/evaluation/agent-evaluation | https://docs.cloud.google.com/gemini-enterprise-agent-platform/optimize/evaluation/agent-evaluation.md.txt | `references/offline-and-simulated-eval.md` |
| 3 | https://docs.cloud.google.com/gemini-enterprise-agent-platform/optimize/evaluation/evaluate-online | https://docs.cloud.google.com/gemini-enterprise-agent-platform/optimize/evaluation/evaluate-online.md.txt | `references/online-eval-and-alerts.md` |
| 4 | https://docs.cloud.google.com/gemini-enterprise-agent-platform/optimize/evaluation/evaluate-offline | https://docs.cloud.google.com/gemini-enterprise-agent-platform/optimize/evaluation/evaluate-offline.md.txt | `references/offline-and-simulated-eval.md` |
| 5 | https://docs.cloud.google.com/gemini-enterprise-agent-platform/optimize/evaluation/evaluate-simulated | https://docs.cloud.google.com/gemini-enterprise-agent-platform/optimize/evaluation/evaluate-simulated.md.txt | `references/offline-and-simulated-eval.md` |
| 6 | https://docs.cloud.google.com/gemini-enterprise-agent-platform/optimize/evaluation/view-results | https://docs.cloud.google.com/gemini-enterprise-agent-platform/optimize/evaluation/view-results.md.txt | `references/online-eval-and-alerts.md` |
| 7 | https://docs.cloud.google.com/gemini-enterprise-agent-platform/optimize/evaluation/quality-alerts | https://docs.cloud.google.com/gemini-enterprise-agent-platform/optimize/evaluation/quality-alerts.md.txt | `references/online-eval-and-alerts.md` |
| 8 | https://docs.cloud.google.com/gemini-enterprise-agent-platform/optimize/evaluation/optimize-agent | https://docs.cloud.google.com/gemini-enterprise-agent-platform/optimize/evaluation/optimize-agent.md.txt | `references/agent-optimization-flywheel.md` |

### Verified Tier-1 & Cached Deep-Dive Sub-Links (22)

| Domain | Canonical Upstream URL | Markdown Refresh Endpoint |
|---|---|---|
| **Observability & Traces** | https://docs.cloud.google.com/gemini-enterprise-agent-platform/optimize/observability/traces | https://docs.cloud.google.com/gemini-enterprise-agent-platform/optimize/observability/traces.md.txt |
| **Multimodal GCS & BQ** | https://docs.cloud.google.com/stackdriver/docs/instrumentation/collect-view-multimodal-prompts-responses | https://docs.cloud.google.com/stackdriver/docs/instrumentation/collect-view-multimodal-prompts-responses.md.txt |
| **Cloud Monitoring Metrics** | https://docs.cloud.google.com/monitoring/api/metrics_gcp_a_b | https://docs.cloud.google.com/monitoring/api/metrics_gcp_a_b.md.txt |
| **Runtime Tracing** | https://docs.cloud.google.com/gemini-enterprise-agent-platform/scale/runtime/tracing | https://docs.cloud.google.com/gemini-enterprise-agent-platform/scale/runtime/tracing.md.txt |
| **Runtime Logging** | https://docs.cloud.google.com/gemini-enterprise-agent-platform/scale/runtime/logging | https://docs.cloud.google.com/gemini-enterprise-agent-platform/scale/runtime/logging.md.txt |
| **Emergency Stop & Runtimes** | https://docs.cloud.google.com/gemini-enterprise-agent-platform/scale/runtime/manage-deployed-agents | https://docs.cloud.google.com/gemini-enterprise-agent-platform/scale/runtime/manage-deployed-agents.md.txt |
| **Canary Revisions & Traffic** | https://docs.cloud.google.com/gemini-enterprise-agent-platform/scale/runtime/manage-revisions-and-traffic | https://docs.cloud.google.com/gemini-enterprise-agent-platform/scale/runtime/manage-revisions-and-traffic.md.txt |
| **Feedback Service SDK** | https://docs.cloud.google.com/gemini-enterprise-agent-platform/scale/feedback-service/manage-with-sdk-or-api | https://docs.cloud.google.com/gemini-enterprise-agent-platform/scale/feedback-service/manage-with-sdk-or-api.md.txt |
| **Agent Anomaly Detection** | https://docs.cloud.google.com/gemini-enterprise-agent-platform/agent-anomalies-overview | https://docs.cloud.google.com/gemini-enterprise-agent-platform/agent-anomalies-overview.md.txt |
| **Security Findings (SCC)** | https://docs.cloud.google.com/gemini-enterprise-agent-platform/govern/view-security-findings | https://docs.cloud.google.com/gemini-enterprise-agent-platform/govern/view-security-findings.md.txt |
| **Evaluate Agents Guide** | https://docs.cloud.google.com/gemini-enterprise-agent-platform/optimize/evaluation/evaluate-agents | https://docs.cloud.google.com/gemini-enterprise-agent-platform/optimize/evaluation/evaluate-agents.md.txt |
| **Manage Metrics Registry** | https://docs.cloud.google.com/gemini-enterprise-agent-platform/optimize/evaluation/manage-metrics | https://docs.cloud.google.com/gemini-enterprise-agent-platform/optimize/evaluation/manage-metrics.md.txt |
| **Gen AI Eval Overview** | https://docs.cloud.google.com/gemini-enterprise-agent-platform/models/evaluation-overview | https://docs.cloud.google.com/gemini-enterprise-agent-platform/models/evaluation-overview.md.txt |
| **Gen AI Eval SDK Quickstart** | https://docs.cloud.google.com/gemini-enterprise-agent-platform/models/evaluation-genai-sdk | https://docs.cloud.google.com/gemini-enterprise-agent-platform/models/evaluation-genai-sdk.md.txt |
| **Managed Rubric Details** | https://docs.cloud.google.com/gemini-enterprise-agent-platform/models/rubric-metric-details | https://docs.cloud.google.com/gemini-enterprise-agent-platform/models/rubric-metric-details.md.txt |
| **Python `Evals` Class Ref** | https://docs.cloud.google.com/python/docs/reference/vertexai/latest/vertexai._genai.evals.Evals | https://docs.cloud.google.com/python/docs/reference/vertexai/latest/vertexai._genai.evals.Evals.md.txt |
| **Example Store Overview** | https://docs.cloud.google.com/gemini-enterprise-agent-platform/optimize/example-store/overview | https://docs.cloud.google.com/gemini-enterprise-agent-platform/optimize/example-store/overview.md.txt |
| **ADK Optimize Docs** | https://adk.dev/optimize/ | https://adk.dev/optimize/index.md |
| **`agents-cli` Eval Guide** | https://github.com/google/agents-cli/blob/main/docs/src/guide/evaluation.md | https://raw.githubusercontent.com/google/agents-cli/main/docs/src/guide/evaluation.md |
| **`agents-cli` Eval Skill** | https://github.com/google/agents-cli/blob/main/skills/google-agents-cli-eval/SKILL.md | https://raw.githubusercontent.com/google/agents-cli/main/skills/google-agents-cli-eval/SKILL.md |
| **`agents-cli` Dataset Schema** | https://github.com/google/agents-cli/blob/main/skills/google-agents-cli-eval/references/dataset_schema.md | https://raw.githubusercontent.com/google/agents-cli/main/skills/google-agents-cli-eval/references/dataset_schema.md |
| **`agents-cli` Obs Skill** | https://github.com/google/agents-cli/blob/main/skills/google-agents-cli-observability/SKILL.md | https://raw.githubusercontent.com/google/agents-cli/main/skills/google-agents-cli-observability/SKILL.md |

### Additional Tier-2 Reference Endpoints to Monitor on Future Refreshes

- OTel & Instrumentation: `https://docs.cloud.google.com/stackdriver/docs/instrumentation/ai-agent-adk.md.txt`, `https://docs.cloud.google.com/stackdriver/docs/opentelemetry/ai-agent-developers.md.txt`, `https://docs.cloud.google.com/mcp/monitor-mcp-tool-use-with-cloud-trace.md.txt`, `https://docs.cloud.google.com/model-armor/configure-logging.md.txt`
- Anomaly Setup & Console Eval: `https://docs.cloud.google.com/gemini-enterprise-agent-platform/audit/agent-anomalies`, `https://docs.cloud.google.com/gemini-enterprise-agent-platform/models/evaluation-genai-console.md.txt`
- Example Store CRUD: `https://docs.cloud.google.com/gemini-enterprise-agent-platform/optimize/example-store/create-examplestore.md.txt`, `https://docs.cloud.google.com/gemini-enterprise-agent-platform/optimize/example-store/upload-examples.md.txt`, `https://docs.cloud.google.com/gemini-enterprise-agent-platform/optimize/example-store/quickstart.md.txt`
- `agents-cli` Sub-References: `https://raw.githubusercontent.com/google/agents-cli/main/skills/google-agents-cli-eval/references/metrics-guide.md`, `.../user-simulation.md`, `.../advanced-commands.md`, `.../live-eval.md`, `.../multimodal-eval.md`, and `.../google-agents-cli-observability/references/cloud-trace-and-logging.md`, `.../bigquery-agent-analytics.md`

---

## 2. Section-by-Section Update Checklist

Re-verify each module in order whenever upstream SDKs, metrics, or docs ship new versions:

- [ ] **`SKILL.md` (Frontmatter, Quick Decision Tree & Critical Gotchas)**
  - Confirm `SKILL.md` stays strictly `< 450` lines (target `150–380` lines) and frontmatter `description` stays `< 1024` chars with `>-`, `Use when`, and `Don't use for` disambiguating every sibling workshop skill and `google-agents-cli-*` built-in.
  - Check whether evaluation APIs have migrated from `google-cloud-aiplatform` (`vertexai.Client`) into `google-cloud-agentplatform` (`agentplatform.Client`).
- [ ] **`references/observability-overview.md`**
  - Re-fetch `observability/overview.md.txt`, `observability/traces.md.txt`, `collect-view-multimodal-prompts-responses.md.txt`, `scale/runtime/tracing.md.txt`, `scale/runtime/manage-deployed-agents.md.txt`, and `agent-anomalies-overview.md.txt`.
  - Verify OTel GenAI semconv floor (`v1.37.0+`), pinned `fsspec[gcs]==2025.10.0`, May 22, 2026 `user.id` ADK `>= 2.1` rule, ADK Python enum vs. Go boolean behavior for `OTEL_INSTRUMENTATION_GENAI_CAPTURE_MESSAGE_CONTENT`, WORM retention range (`1–3,650` days), UAP/IAM propagation windows (`2–7+` min), and Agent Anomaly Detection GA/allowlist status.
- [ ] **`references/offline-and-simulated-eval.md`**
  - Re-fetch `agent-evaluation.md.txt`, `evaluate-offline.md.txt`, `evaluate-simulated.md.txt`, `manage-metrics.md.txt`, `models/evaluation-overview.md.txt`, `models/rubric-metric-details.md.txt`, and `vertexai._genai.evals.Evals.md.txt`.
  - Verify the 15 supported eval regions, judge model versions (Gemini 3.5 Flash / 3.1 Pro), **`safety_v3` vs. `safety_v1` score polarity** (especially whether `manage-metrics.md` updated to match `rubric-metric-details.md`), `client.evals.evaluate(dataset=...)` vs. `evaluate-agents.md` `traces=` discrepancy, multi-turn 400 restriction, and `agents-cli` experimental flags (`eval dataset synthesize`, `eval submit`).
- [ ] **`references/online-eval-and-alerts.md`**
  - Re-fetch `evaluate-online.md.txt`, `view-results.md.txt`, `quality-alerts.md.txt`, and `monitoring/api/metrics_gcp_a_b.md.txt`.
  - Check whether `vertexai._genai.evals.Evals` or `agentplatform.Client` has added programmatic `OnlineEvaluator` CRUD methods, whether `generate_loss_clusters` / `eval analyze` expanded beyond the `global` region, and whether the 26 Loss Pattern taxonomies or `online_evaluator/*` metric descriptors changed.
- [ ] **`references/agent-optimization-flywheel.md`**
  - Re-fetch `optimize-agent.md.txt`, `adk.dev/optimize/index.md`, `example-store/overview.md.txt`, and `agents-cli/docs/src/guide/evaluation.md`.
  - Verify whether `GEPARootAgentPromptOptimizer` / `GEPARootAgentOptimizer` or `agents-cli eval optimize` graduated from experimental, confirm whether `client.optimizer.optimize` has full SDK reference documentation, and confirm Example Store launch stage and the 50-instance per-region/project cap.
- [ ] **Automated Validation**
  - Run `python3 scripts/validate_skills.py .agents/skills` from the repository root and confirm `[PASS] agent-platform-optimize-and-eval` with zero errors, zero warnings, zero orphan references, and zero 2-hop links.
