# Runtime Telemetry: Tracing, Cloud Logging & Cloud Monitoring

Production observability reference for deployed **Agent Runtime** (`aiplatform.googleapis.com/ReasoningEngine`) instances covering OpenTelemetry tracing, Cloud Logging, Log Analytics SQL, built-in and custom Cloud Monitoring metrics, PromQL queries, dashboards, and latency alerts.

---

## 1. OpenTelemetry Tracing (Cloud Trace)

### Required APIs & Runtime IAM

- **APIs:** Enable `telemetry.googleapis.com` (Telemetry OTLP API) and `logging.googleapis.com` (Cloud Logging API).
- **Runtime Service Account IAM:** `roles/cloudtrace.agent`, `roles/telemetry.tracesWriter`, `roles/logging.logWriter`, `roles/monitoring.metricWriter`.
- **Console Viewer IAM:** `roles/cloudtrace.user`, `roles/logging.viewer`, `roles/monitoring.viewer`.

### ADK (`AdkApp`) Deployment Environment Variables

Configure OpenTelemetry tracing, logging, and GenAI semantic-convention capture via the three standard runtime environment variables:

```python
env_vars = {
    # Enables traces, logs, and (on ADK >= 2.6.0) OTel GenAI semantic-convention metrics; excludes prompt/response text
    "GOOGLE_CLOUD_AGENT_ENGINE_ENABLE_TELEMETRY": "true",
    # Opts into latest OpenTelemetry GenAI semantic conventions
    "OTEL_SEMCONV_STABILITY_OPT_IN": "gen_ai_latest_experimental",
    # Enables logging of input prompts, output responses, and `user.id`
    # CRITICAL: ADK Python requires enum values (`NO_CONTENT`, `EVENT_ONLY`, `SPAN_ONLY`, `SPAN_AND_EVENT`).
    # Passing `"true"` silently falls back to `NO_CONTENT`!
    "OTEL_INSTRUMENTATION_GENAI_CAPTURE_MESSAGE_CONTENT": "EVENT_ONLY",
}
```

- **May 22, 2026 `user.id` Cutoff:** Logging `user.id` with prompt/response capture requires **ADK `>= 2.1`** effective **May 22, 2026**. Agents opted in prior to May 22, 2026 must be **redeployed and opted in again** for `user.id` to appear. Ensure appropriate end-user notices/consents before enabling message content capture.
- **Console Telemetry Toggle Prerequisite:** Configuring Observability toggles via **Deployments -> Telemetry configuration -> Configure** requires deploying with `google-cloud-agentplatform >= 2.0.1` (also bundled in `google-cloud-aiplatform >= 1.154.0`).
- **Viewing Traces:** **Google Cloud Console -> Agent Platform -> Deployments -> `<agent>` -> Traces** (**Session view** or **Span view** for span DAG, inputs/outputs, and metadata). Note that large span attributes may truncate under Cloud Trace quotas.

---

## 2. Cloud Logging

### Monitored Resource & Child-Resource Limitation

- **Monitored Resource Type:** `aiplatform.googleapis.com/ReasoningEngine`
  - Resource labels: `location`, `resource_container` (project ID), `reasoning_engine_id` (populated via auto-injected `GOOGLE_CLOUD_AGENT_ENGINE_ID`).
- **CRITICAL LIMITATION:** Cloud Logging is **NOT supported for child resources** of Agent Runtime—including **Sessions**, **Memory Bank**, **Managed Sandboxes / Code Execution**, and **Example Store**. Always emit structured JSON logs (with truncated, secret-redacted stdout/stderr previews) from your **parent Agent Runtime** tool callbacks!

### Three Logging Methods (Verified Python Patterns)

| Method | Log Name / ID | Payload Type | When to Use |
|---|---|---|---|
| **1. `stdout` / `stderr`** | `aiplatform.googleapis.com%2Freasoning_engine_stdout` / `*_stderr` *(build logs: `reasoning_engine_build`)* | `textPayload` only | Zero-setup debugging |
| **2. Python `logging` + `setup_logging()`** | Custom `LOG_ID` (`projects/PROJECT_ID/logs/LOG_ID`) | `jsonPayload` | Minimal setup with `logging.info(json.dumps(...), extra=...)` |
| **3. `google.cloud.logging.Client` `log_struct()`** | Custom `LOG_ID` | `jsonPayload` | Full control over severity, custom labels, and `trace` correlation |

```python
import json, logging, os
import google.cloud.logging

class ObservableAgent:
    def set_up(self):
        self.logging_client = google.cloud.logging.Client(project="PROJECT_ID")
        resource = google.cloud.logging.Resource(
            type="aiplatform.googleapis.com/ReasoningEngine",
            labels={
                "location": "LOCATION",
                "resource_container": "PROJECT_ID",
                "reasoning_engine_id": os.environ.get("GOOGLE_CLOUD_AGENT_ENGINE_ID", ""),
            },
        )
        # Option A: Python stdlib logging handler
        self.logging_client.setup_logging(name="agent-py-logs", resource=resource)

        # Option B: Direct structured logger (recommended for tool/sandbox audit logs)
        self.struct_logger = self.logging_client.logger(name="agent-struct-logs", resource=resource)

    def log_tool_execution(self, tool_name: str, exit_code: int, preview: str, trace_id: str | None = None):
        extras = {"labels": {"tool": tool_name}}
        if trace_id:
            extras["trace"] = trace_id
        self.struct_logger.log_struct(
            {"event": "tool_exec", "tool": tool_name, "exit_code": exit_code, "stdout_preview": preview[:1000]},
            severity="INFO" if exit_code == 0 else "ERROR",
            **extras,
        )
```

### Querying Logs (Logs Explorer, Python & Log Analytics SQL)

- **Logs Explorer Filters** (requires `roles/logging.viewer`; Resource Type: **Gemini Enterprise Agent Platform Reasoning Engine**):
  ```text
  resource.type="aiplatform.googleapis.com/ReasoningEngine"
  resource.labels.reasoning_engine_id="RESOURCE_ID"
  severity>=INFO
  ```
- **Filter by Runtime Operation HTTP Endpoint:**
  - Sync / async queries: `POST /api/reasoning_engine`
  - Streaming / async streaming: `POST /api/stream_reasoning_engine`
  - Bidirectional streaming: `POST /api/bidi_reasoning_engine`
- **Programmatic Python Query:**
  ```python
  from google.cloud import logging as cloud_logging

  client = cloud_logging.Client(project="PROJECT_ID")
  for entry in client.logger("agent-struct-logs").list_entries(
      filter_='resource.labels.reasoning_engine_id="RESOURCE_ID"'
  ):
      print(entry.timestamp.isoformat(), entry.payload)
  ```
- **Log Analytics SQL** (for aggregations unsupported in Logs Explorer):
  ```sql
  -- Fixed-schema Log View
  SELECT timestamp, severity, json_payload
  FROM `PROJECT_ID.LOCATION.BUCKET_ID.LOG_VIEW_ID`
  WHERE resource.labels.reasoning_engine_id = 'RESOURCE_ID';

  -- Custom Analytics View
  SELECT * FROM `analytics_view.PROJECT_ID.LOCATION.ANALYTICS_VIEW_ID`;
  ```

---

## 3. Cloud Monitoring: Built-In Metrics, PromQL & REST API

### Built-In Metrics (`aiplatform.googleapis.com/ReasoningEngine`)

Collected automatically with zero config (requires `roles/monitoring.viewer` to inspect):

- `aiplatform.googleapis.com/reasoning_engine/request_count` (`DELTA`, `INT64`; metric labels: `response_code`, `response_code_class`)
- `aiplatform.googleapis.com/reasoning_engine/request_latencies`
- `aiplatform.googleapis.com/reasoning_engine/cpu/allocation_time`
- `aiplatform.googleapis.com/reasoning_engine/memory/allocation_time`
- **ADK `>= 2.6.0` GenAI Metrics:** Setting `GOOGLE_CLOUD_AGENT_ENGINE_ENABLE_TELEMETRY="true"` automatically exports OpenTelemetry GenAI semantic convention metrics to Cloud Monitoring as user-defined metrics.

### Verified PromQL Queries

*(In Metrics Explorer, `${__interval}` scales dynamically with the selected time range; pin `[10m]` windows when computing deterministic rates or ratios.)*

```promql
# 1. Absolute request count over 10m window for a specific response code
sum_over_time(
  increase(
    aiplatform_googleapis_com:reasoning_engine_request_count{
      monitored_resource='aiplatform.googleapis.com/ReasoningEngine',
      reasoning_engine_id='RESOURCE_ID',
      response_code='200'
    }[10m]
  )[10m:10m]
)
```

```promql
# 2. HTTP 500 error-rate ratio (failed requests / total requests)
sum_over_time(
  sum(
    rate(
      aiplatform_googleapis_com:reasoning_engine_request_count{
        monitored_resource='aiplatform.googleapis.com/ReasoningEngine',
        reasoning_engine_id='RESOURCE_ID',
        response_code='500'
      }[10m]
    )
  )[10m:10m]
)
/
sum_over_time(
  sum(
    rate(
      aiplatform_googleapis_com:reasoning_engine_request_count{
        monitored_resource='aiplatform.googleapis.com/ReasoningEngine',
        reasoning_engine_id='RESOURCE_ID'
      }[10m]
    )
  )[10m:10m]
)
```

### Cloud Monitoring v3 REST API (`gcurl`)

```bash
alias gcurl='curl -H "Authorization: Bearer $(gcloud auth print-access-token)" -H "Content-Type: application/json"'

# 1. Inspect ReasoningEngine monitored resource descriptor & labels
gcurl "https://monitoring.googleapis.com/v3/projects/${PROJECT_ID}/monitoredResourceDescriptors/aiplatform.googleapis.com/ReasoningEngine"

# 2. List all built-in reasoning_engine metric descriptors
gcurl "https://monitoring.googleapis.com/v3/projects/${PROJECT_ID}/metricDescriptors?filter=metric.type%3Dstarts_with(%22aiplatform.googleapis.com/reasoning_engine%22)"

# 3. Query raw request_count time series (RFC 3339 timestamps)
gcurl "https://monitoring.googleapis.com/v3/projects/${PROJECT_ID}/timeSeries?filter=metric.type%3D%22aiplatform.googleapis.com/reasoning_engine/request_count%22%20AND%20resource.labels.reasoning_engine_id%3D%22${RESOURCE_ID}%22&interval.startTime=2026-11-19T00:00:00Z&interval.endTime=2026-11-19T01:00:00Z"
```

---

## 4. Custom Metrics, Dashboards & Alerting

### Log-Based Metrics vs. User-Defined Metrics

| Aspect | Log-Based Counter Metric | User-Defined Custom Metric |
|---|---|---|
| **Monitored Resource** | Stays bound to **`aiplatform.googleapis.com/ReasoningEngine`** (retains `reasoning_engine_id` label) | MUST use **`generic_node`** (NOT `ReasoningEngine`) |
| **Metric Type Example** | `Logging/user/tool_calling_count` | `custom.googleapis.com/token_count` (`CUMULATIVE`, `INT64`) |
| **How to Create** | Cloud Logging -> **Log-based Metrics -> Create metric** (Counter, filter `resource.type="aiplatform.googleapis.com/ReasoningEngine"`, regex label extractors) | `POST .../v3/projects/PROJECT_ID/metricDescriptors` (once), then periodically `POST .../v3/projects/PROJECT_ID/timeSeries` |

```json
// Example user-defined MetricDescriptor (POST /v3/projects/PROJECT_ID/metricDescriptors)
{
  "name": "token_count",
  "description": "Tokens consumed by models.",
  "displayName": "Token Count",
  "type": "custom.googleapis.com/token_count",
  "metricKind": "CUMULATIVE",
  "valueType": "INT64",
  "unit": "1",
  "labels": [
    { "key": "model", "valueType": "STRING", "description": "Model." },
    { "key": "agent", "valueType": "STRING", "description": "Agent." }
  ],
  "monitoredResourceTypes": ["generic_node"]
}
```

> **Cumulative Time-Series Rule:** Each unique label combination is an independent time series reported in `projects.timeSeries.create`; `CUMULATIVE` values must be monotonically non-decreasing until container restart resets `startTime`.

### Dashboards & Latency Alerts

- **Built-in Agent Dashboard:** **Agent Platform -> Deployments -> `<agent>` -> Dashboard** provides 5 tabs: **Overview** (latency, request count, error rate), **Models** (model calls, error rate, token usage), **Tools** (tool calls, error rate, latency), **Usage** (input/output tokens, container CPU & memory allocation), and **Logs**.
- **Cloud Monitoring Overview Dashboard:** **Monitoring -> Dashboards -> Filter `Name:Agent Runtime Overview`**. Click **Copy Dashboard** to add custom log-based (`ReasoningEngine`) or user-defined (`Generic Node`) widgets.
- **Recommended p99 Latency Alert Policy (`latency-99p-alert`):**
  1. **Monitoring -> Alerting -> Create Policy -> Builder**.
  2. Metric: `Agent Platform Reasoning Engine -> reasoning_engine -> Request Latency` (optional filters: `reasoning_engine_id`, `response_code`).
  3. Rolling window: `5min`, Rolling window function: `99th percentile`.
  4. Condition: **Threshold**, **Any time series violates**, **Above threshold**, value **`5000ms`**.
  5. Attach notification channels and save.

---

## 5. Verification & Troubleshooting

- **Verify Telemetry:** Send 3+ `:streamQuery` calls -> check **Deployments -> `<agent>` -> Traces** for span DAG + prompt/response events, check **Logs Explorer** for `resource.labels.reasoning_engine_id="RESOURCE_ID"`, and run the `gcurl` `timeSeries` query above.
- **Common errors:**
  - Prompts/responses missing in Trace UI despite `GOOGLE_CLOUD_AGENT_ENGINE_ENABLE_TELEMETRY="true"` -> verify `OTEL_INSTRUMENTATION_GENAI_CAPTURE_MESSAGE_CONTENT` is `"EVENT_ONLY"` (NOT `"true"`).
  - `user.id` missing after May 22, 2026 -> upgrade to `google-adk>=2.1`, redeploy, and re-enable message content logging.
  - Sandbox or Memory Bank logs missing in Logs Explorer -> Cloud Logging does not support child resources; emit structured logs from the parent runtime callback.
  - `INVALID_ARGUMENT` creating custom metric with `ReasoningEngine` resource -> switch `monitoredResourceTypes` to `["generic_node"]` and populate `node_id` with `RESOURCE_ID`.
