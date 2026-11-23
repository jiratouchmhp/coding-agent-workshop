# Online Evaluation Monitors, Failure Clustering & Quality Alerts

Production reference for continuous production quality tracking on Gemini Enterprise Agent Platform: **Online Monitors** (prerequisites, 10-minute loop, sampling/cost caps, P4SA security & propagation troubleshooting), **Viewing Results & Automatic Loss Analysis** (Console, `vertexai.evals`, complete 26-pattern Loss Taxonomies, 7-step triage), and **Quality Alerts** (Console templates, `gcloud`, and Python `google.cloud.monitoring_v3`).

---

## 1. Online Monitors Architecture & Cloud Monitoring Metric Descriptors

Online Monitors continuously detect **quality drift** (performance degradation from evolving user traffic, backend data shifts, or prompt interactions even when the model is unchanged) by executing an asynchronous **~10-minute scheduled loop**:

1. **Query:** Samples live traces and inference events from **Cloud Trace** and **Cloud Logging** matching your filter criteria.
2. **Evaluate:** Scores sampled interactions with configured predefined or custom Metric Registry metrics via the Gen AI Evaluation Service.
3. **Report:** Writes per-trace scores and rationales back to **Cloud Logging** and exports aggregated numeric time series to **Cloud Monitoring**.

### Telemetry Prerequisites (Identical to Offline Evaluation)

Online Monitors will produce empty dashboards unless your deployed Agent Runtime exports OpenTelemetry GenAI semantic conventions **v1.37.0+**:

- **Invoke agent span:** `gen_ai.agent.name`, `gen_ai.agent.description`, `gen_ai.conversation.id`.
- **Inference events (`gen_ai.client.inference.operation.details`):** `gen_ai.input.messages`, `gen_ai.output.messages`, `gen_ai.system_instructions`, `gen_ai.tool.definitions`.
- **ADK Python env vars:**
  ```bash
  GOOGLE_CLOUD_AGENT_ENGINE_ENABLE_TELEMETRY='true'
  OTEL_SEMCONV_STABILITY_OPT_IN='gen_ai_latest_experimental'
  OTEL_INSTRUMENTATION_GENAI_CAPTURE_MESSAGE_CONTENT='EVENT_ONLY'
  # Plus optional GCS upload vars for multimodal payloads:
  # OTEL_INSTRUMENTATION_GENAI_UPLOAD_FORMAT='jsonl'
  # OTEL_INSTRUMENTATION_GENAI_COMPLETION_HOOK='upload'
  # OTEL_INSTRUMENTATION_GENAI_UPLOAD_BASE_PATH='gs://STORAGE_BUCKET_NAME/PATH'
  ```

### Exported Cloud Monitoring Metric Descriptors (Verified `metrics_gcp_a_b`)

| Metric Type | Kind / Value Type / Unit | Monitored Resource | Labels |
|---|---|---|---|
| `aiplatform.googleapis.com/online_evaluator/scores` | `DELTA`, `DISTRIBUTION`, `1` | `aiplatform.googleapis.com/OnlineEvaluator` | `agent_resource_name`, `evaluation_metric_name`, `runtime_revision_id` |
| `aiplatform.googleapis.com/online_evaluator/evaluations_count` | `DELTA`, `INT64`, `1` | `aiplatform.googleapis.com/OnlineEvaluator` | `agent_resource_name`, `evaluation_metric_name`, `evaluation_status`, `runtime_revision_id` |

> **Per-Revision Drift Tracking:** Both metric descriptors carry `runtime_revision_id`, letting you isolate quality regressions on a newly deployed canary revision before promoting 100% traffic.

---

## 2. Creating, Managing & Troubleshooting Online Monitors

> **Programmatic SDK Transparency:** Verified against `vertexai._genai.evals.Evals` (`v1.153.1`), **no Python SDK creation method exists for `OnlineEvaluator`** (do not guess `client.evals.create_online_monitor()`). Provision and manage Online Monitors through the Google Cloud Console until an official REST/SDK method is published.

### Console Creation Workflow

1. Navigate to `Agent Platform > Agents > Evaluation` (`https://console.cloud.google.com/agent-platform/agent-evaluation`) -> **Online monitors** tab -> click **New monitor**.
2. **Specify Filter Traces:**
   - Select the target **Agent engine**.
   - Choose **All traces** or **Filter criteria**.
   - Use **Initial Inspection** (e.g., **Last 1 day**) to preview matching production traces; narrow by trace properties such as `Duration > 2` or `Token usage`.
3. **Configure Metrics:** Add predefined metrics (**Safety**, **Task Success**, **Tool Use Quality**, **Hallucination**) or registered custom metrics from the Metric Registry.
4. **Set Sampling & Cost Cap:**
   - **Sampling percentage:** Fraction of matching live traces to evaluate.
   - **Max samples per run:** Hard per-10-minute-cycle ceiling to bound judge LLM spend.
5. Click **Create**.

### Lifecycle Controls (`Online monitors` list -> `More options`)

- **Enable / Disable** or **Pause / Resume** without deleting monitor configuration.
- **Duplicate** an existing monitor to pre-fill filters and metrics for a staging/canary agent.
- **View traces** (from the **Sampled traces** column) to jump directly to filtered traces on the agent's **Traces** tab.

### Security Disclosure & P4SA Troubleshooting

- **Privilege Escalation Caution:** Online evaluation runs under the **project-level service account (P4SA)**. Any principal allowed to create an `OnlineEvaluator` can attach it to **any agent in the same project**. Restrict `OnlineEvaluator` creation strictly to authorized administrators.
- **First-Monitor Transient `"Failed"` Warning (Wait 30 Minutes):** The very first Online Monitor created in a project frequently enters a temporary **Failed** (`"permission denied"`) state while P4SA IAM permissions propagate. **Take no action immediately** — it retries automatically on its 10-minute schedule and transitions to **Active**. Only investigate P4SA IAM roles if it stays **Failed** past **30 minutes**.
- **Active Monitor Showing Zero Results — Diagnostic Checklist:**
  1. Confirm live traces in Cloud Trace contain `gen_ai.*` span attributes and `gen_ai.client.inference.operation.details` events.
  2. Re-check **Initial Inspection** to verify filter criteria actually match live traffic.
  3. Query Online Monitor internal diagnostic logs in **Logs Explorer**:
     ```text
     resource.labels.online_evaluator="projects/YOUR_PROJECT_ID/locations/YOUR_REGION/onlineEvaluators/YOUR_MONITOR_ID"
     # Or filter by a specific trace or agent:
     labels.trace="YOUR_TRACE_ID"
     labels.reasoning_engine_id="YOUR_AGENT_ID"
     ```

---

## 3. Viewing Results & Automatic Loss Analysis (Failure Clustering)

Agent Platform supports a **three-level diagnostic model**:

1. **Aggregate Trends (Console):** `Deployments` (`https://console.cloud.google.com/agent-platform/runtimes`) -> select agent -> `Dashboard -> Evaluation` subsection. Tracks metric trends across versions and timeframes (shows a zero-state CTA if no Online Monitors exist).
2. **Evaluations Report & Failure Clusters (Console):** `Evaluation -> Evaluations` tab -> click a completed run name -> inspect aggregate scores, expandable per-case rubric verdicts/rationales, and **Failure Clusters** (**Automatic Loss Analysis**).
3. **Trace Drill-Down (Console):** Click any failing row in an evaluation report (or open `Deployments -> Agent -> Traces` -> select row -> **Evaluation** tab) to jump directly to the failing turn, model input, tool calls, and judge rationale.

### Python SDK Visualization & Failure Clustering (`vertexai.evals`)

```python
from vertexai import Client, types

# CRITICAL: generate_loss_clusters is ONLY available in the `global` region!
client = Client(project="YOUR_PROJECT_ID", location="global")

result = client.evals.evaluate(
    dataset=eval_dataset,
    metrics=[
        types.RubricMetric.MULTI_TURN_TASK_SUCCESS,
        types.RubricMetric.MULTI_TURN_TOOL_USE_QUALITY,
    ],
)

# 1. Interactive Colab/Jupyter summary (mean/std/pass rate + per-case rubric verdicts)
result.show()

# 2. Automatic Loss Analysis — calls GenerateLossClusters LRO & polls to completion
# Auto-infers metric/candidate ONLY when unambiguous; pass explicitly for multi-metric runs!
loss_clusters = client.evals.generate_loss_clusters(
    eval_result=result,
    metric=types.RubricMetric.MULTI_TURN_TASK_SUCCESS,
    # candidate=result.metadata.candidate_names[0],  # Required if evaluating multiple candidates
)
loss_clusters.show()
```

### `agents-cli` Failure Clustering (`eval analyze`)

```bash
# Experimental — global region ONLY; most effective with 10+ failing cases
agents-cli eval analyze \
    --eval-result artifacts/grade_results/results_20261119_040000.json \
    --metric multi_turn_task_success   # Allowed: multi_turn_task_success or multi_turn_tool_use_quality
```

---

## 4. Complete Verified Loss Pattern Taxonomies (26 Patterns)

Automatic Loss Analysis classifies rubric failures into concrete, actionable root-cause patterns aligned to two multi-turn metrics.

### Taxonomy 1 — Agent Task Success (`multi_turn_task_success_v1`, 13 Patterns / 5 Categories)

| Category | Loss Pattern | Root Cause Description |
|---|---|---|
| **Hallucination** | `Hallucination of Action` | Claims to have completed an action without executing the required tool call. |
| **Hallucination** | `Hallucination of Missing Information` | Invents a value, fact, or date absent from the user query or tool output. |
| **Hallucination** | `Hallucination of Tool or Capability` | Claims to have a tool or capability it does not possess. |
| **Instruction Following** | `Constraint Violation` | Performs the task but violates explicit user constraints (format rules, negative constraints). |
| **Instruction Following** | `Futile Action (Under-Punting)` | Takes an irrelevant action instead of stating the task is impossible with available tools. |
| **Instruction Following** | `Incomplete Execution` | Partially completes a task, stops prematurely, or asks unnecessary permission for requested steps. |
| **Instruction Following** | `Over-Punting` | Declines a task claiming it lacks a tool/capability it actually possesses. |
| **Tool Calling** | `Incorrect Tool Selection` | Selects the wrong tool from its available options. |
| **Tool Calling** | `Semantically Incorrect Tool Parameters` | Syntactically valid call with logically/semantically wrong argument values. |
| **Tool Calling** | `Syntactically Incorrect Tool Call` | Syntax errors, missing mandatory parameters, or invalid argument values. |
| **Tool Output Handling** | `Incorrect Tool Output Processing` | Receives valid tool output but mis-extracts or misinterprets it. |
| **Tool Quality** | `Insufficient Tool Output` | Tool succeeds but returns insufficient or missing data to proceed. |
| **Tool Quality** | `Tool Failure` | Tool fails due to auth error, timeout, or internal infrastructure failure. |

### Taxonomy 2 — Tool Use Quality (`multi_turn_tool_use_quality_v1`, 13 Patterns / 3 Categories)

| Category | Loss Pattern | Root Cause Description |
|---|---|---|
| **Hallucination** | `Hallucination of Parameter Value` | Invents a parameter value neither provided by the user nor derivable from context. |
| **Hallucination** | `Hallucination of Tool` | Attempts to invoke a function not in its defined toolset. |
| **Tool Calling** | `Failure to Set Parameter` | Omits a parameter required by user constraints, unintentionally falling back to a default. |
| **Tool Calling** | `Incorrect Parameter Data Type` | Passes wrong data type (e.g., string when integer is required). |
| **Tool Calling** | `Incorrect Parameter Mapping` | Assigns a value to the wrong parameter (e.g., swapped start and end dates). |
| **Tool Calling** | `Incorrect Parameter Value` | Logically/factually wrong value or missing required transformation. |
| **Tool Calling** | `Incorrect Tool Selection` | Selects the wrong function from the toolset. |
| **Tool Calling** | `Invalid Tool Call Syntax` | Generates unparseable/unexecutable function call syntax. |
| **Tool Calling** | `Non-Existent Parameter` | Passes an argument not defined in the tool's signature. |
| **Tool Calling** | `Omission of Required Tool Call` | Skips a needed tool call (answers directly or omits a prerequisite step). |
| **Tool Calling** | `Under-Punting` | Forces a tool call instead of clarifying or declining an out-of-scope request. |
| **Tool Response** | `Irrelevant Tool Response` | Tool succeeds but returns data irrelevant to the query. |
| **Tool Response** | `Tool Error` | Tool returns an explicit error/failure status (API outage, invalid permissions). |

---

## 5. 7-Step Failure Triage Loop & Failure-to-Fix Map

1. **Summary metrics:** Identify the lowest-scoring metric across the dataset.
2. **Per-case failures:** Filter failed cases and read judge rationales.
3. **Failure clusters:** Run Automatic Loss Analysis (`generate_loss_clusters` / `eval analyze`) to group systemic issues.
4. **Trace drill-down:** Inspect the exact failing turn, prompt, tool call, and tool response.
5. **Root-cause classification:** Separate **prompt issues** (instructions/constraints) vs. **tool issues** (schema/docstrings/API errors) vs. **data issues**.
6. **Targeted fix:** Edit system instructions, tool signatures/docstrings, `tool_config`, or add Example Store few-shot examples.
7. **Re-run & compare:** Re-run evaluation and diff with `agents-cli eval compare <before>.json <after>.json` while holding back a clean holdout slice to catch overfitting.

| Failing Signal | Targeted Remediation |
|---|---|
| `multi_turn_task_success` low | Fix orchestration logic, missing prerequisite tool calls, premature stopping, or tool selection. |
| `multi_turn_trajectory_quality` low | Tighten planning prompt order, remove redundant/looping tool calls. |
| `multi_turn_tool_use_quality` low | Rewrite tool descriptions & parameter docstrings; set `tool_config` (`mode="ANY"`) if thinking mode bypasses tools. |
| `final_response_quality` low | Address the lowest-passing adaptive rubric criterion (completeness, clarity, formatting). |
| `hallucination` low | Ground instructions strictly in tool output; verify tools return all claimed fields. |
| `safety` violated | Add explicit policy guardrails to system instructions and enable inline Model Armor filtering. |
| Flaky/noisy scores | Set `temperature=0` or multi-sample judge (`judge_model_sampling_count: 3`) — **never** lower thresholds or drop flaky cases. |

---

## 6. Quality Alerts (Console, `gcloud` CLI & Python `monitoring_v3`)

Quality alerts trigger Cloud Monitoring **incidents** when Online Monitor scores cross your threshold and notify via Slack, email, or Pub/Sub. Every incident carries `OnlineEvaluator` labels (`agent_resource_name`, `evaluation_metric_name`, `runtime_revision_id`) to trace back directly to drifting spans.

> **CRITICAL Threshold Polarity Check (`safety_v3` vs other metrics):** Most quality metrics (`task_success`, `tool_use_quality`, `hallucination`, `safety_v1`) score higher = better (`COMPARISON_LT`, e.g., `< 0.8`). However, **`safety_v3` uses `1` = policy violation (unsafe) and `0` = safe** — alert on `safety_v3` with **`COMPARISON_GT`** (e.g., `> 0.05`), NOT `COMPARISON_LT`!

### Console Alert Workflows

- **Path A — Per-Monitor Policy:** `Evaluation -> Online monitors` tab -> **More options** -> **Create alerting policy** -> pick from auto-generated per-metric templates -> select **Notification Channels** *(uncheck **Use notification channels** to silently record incidents in `Monitoring > Alerting` without paging)* -> **Create**.
- **Path B — Dashboard Recommended Alerts:** `Deployments -> Agent -> Dashboard -> Evaluation` -> **Recommended Alerts** (top right) -> select *Online Monitor - Low evaluation score* or *Individual Metric Alerts* -> choose channels -> **Create**.

### `gcloud` CLI Workflow (`policy.yaml`)

> **CRITICAL Cloud Monitoring HTTP 400 Traps on `online_evaluator/scores`:**
> 1. **Always include `resource.type="aiplatform.googleapis.com/OnlineEvaluator"` in `filter`:** Omitting it fails with HTTP 400 (`must specify a restriction on "resource.type" in the filter`).
> 2. **Never use `ALIGN_MEAN` on `online_evaluator/scores`:** Because the metric has kind `DELTA` and value type `DISTRIBUTION`, `ALIGN_MEAN` fails with HTTP 400 (`The aligner cannot be applied to metrics with kind DELTA and value type DISTRIBUTION`). Use **`ALIGN_PERCENTILE_50`** (or `ALIGN_DELTA` + `REDUCE_PERCENTILE_50`).

```yaml
# policy.yaml — alerts if median (p50) Task Success drops below 0.80 for 30 minutes
displayName: "Low Task Success Score"
conditions:
- displayName: "Task Success (p50) < 0.8"
  conditionThreshold:
    filter: >
      resource.type="aiplatform.googleapis.com/OnlineEvaluator"
      AND metric.type="aiplatform.googleapis.com/online_evaluator/scores"
      AND metric.labels.evaluation_metric_name="task_success"
    # Optional multi-agent scoping (verified in monitoring/api/metrics_gcp_a_b):
    # AND metric.labels.agent_resource_name="projects/YOUR_PROJECT_ID/locations/asia-southeast1/reasoningEngines/ENGINE_ID"
    comparison: COMPARISON_LT
    thresholdValue: 0.8
    duration: 1800s
    aggregations:
    - alignmentPeriod: 60s
      perSeriesAligner: ALIGN_PERCENTILE_50
combiner: OR
enabled: true
notificationChannels:
- "projects/YOUR_PROJECT_ID/notificationChannels/CHANNEL_ID"
```

```bash
gcloud monitoring policies create --policy-from-file="policy.yaml"
```

### Python Cloud Monitoring SDK (`google-cloud-monitoring`, `monitoring_v3`)

```python
# pip install google-cloud-monitoring
from google.cloud import monitoring_v3

client = monitoring_v3.AlertPolicyServiceClient()
project_name = "projects/YOUR_PROJECT_ID"

policy = {
    "display_name": "Agent Quality Drift",
    "conditions": [{
        "display_name": "Low Evaluation Score (p50)",
        "condition_threshold": {
            "filter": (
                'resource.type="aiplatform.googleapis.com/OnlineEvaluator"'
                ' AND metric.type="aiplatform.googleapis.com/online_evaluator/scores"'
                ' AND metric.labels.evaluation_metric_name="task_success"'
                # Optional narrowing filters verified from monitoring/api/metrics_gcp_a_b:
                # ' AND metric.labels.agent_resource_name="projects/YOUR_PROJECT_ID/locations/asia-southeast1/reasoningEngines/ENGINE_ID"'
                # ' AND metric.labels.runtime_revision_id="REVISION_ID"'
            ),
            "comparison": monitoring_v3.ComparisonType.COMPARISON_LT,
            "threshold_value": 0.7,
            "duration": {"seconds": 3600},
            "aggregations": [{
                "alignment_period": {"seconds": 60},
                # CRITICAL: DELTA/DISTRIBUTION rejects ALIGN_MEAN (HTTP 400); use ALIGN_PERCENTILE_50!
                "per_series_aligner": monitoring_v3.Aggregation.Aligner.ALIGN_PERCENTILE_50,
            }],
        },
    }],
    "combiner": monitoring_v3.AlertPolicy.ConditionCombinerType.OR,
    "enabled": True,
}

response = client.create_alert_policy(name=project_name, alert_policy=policy)
print(f"Created alerting policy {response.name}")
```

Manage policies and triage open incidents in Cloud Monitoring Alerting (`https://console.cloud.google.com/monitoring/alerting`).
