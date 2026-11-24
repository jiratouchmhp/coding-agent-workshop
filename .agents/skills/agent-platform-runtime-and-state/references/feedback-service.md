# Feedback Service (Preview)

Production reference for collecting, updating, querying, and visualizing end-user feedback linked to **Agent Runtime**, **Managed Sessions**, and **Cloud Trace**.

---

## 1. Prerequisites, IAM & Schema

- **Launch Stage:** Preview (subject to Pre-GA Offerings Terms).
- **Mandatory Environment Variable:** `export GOOGLE_GENAI_USE_ENTERPRISE="TRUE"` (required by `agentplatform` SDK for Feedback Service).
- **IAM Permissions:**
  - Callers & custom user-managed service accounts: **`roles/aiplatform.user`**.
  - Agent Runtime Service Agent (`service-PROJECT_NUMBER@gcp-sa-aiplatform-re.iam.gserviceaccount.com`): already permitted for outbound calls from Agent Runtime.
- **Feedback Types (`feedback_type`):**
  - `"THUMBS_UP"`
  - `"THUMBS_DOWN"`
  - `"FEEDBACK_TYPE_UNSPECIFIED"`
- **Standard Feedback Labels (`feedback_labels`):**
  - **Positive:** `accurate`, `complete`, `helpful`, `on_topic`, `fast`, `safe`, `factual`, `tool_success`
  - **Negative:** `inaccurate`, `incomplete`, `unhelpful`, `off_topic`, `too_slow`, `unsafe`, `hallucination`, `tool_error`
- **`FeedbackContext`:** Optional child resource storing conversation transcripts or user-selected messages so audit context survives even if the original Managed Session is later deleted.

---

## 2. Python SDK — All 7 Verified Operations

> **CRITICAL SDK PATH QUIRK:** Verified against upstream `manage-with-sdk-or-api`:
> - `client.feedback_entries.feedback_contexts.update(...)` expects `name=entry_name` (`.../feedbackEntries/FEEDBACK_ENTRY_ID`),
> - `client.feedback_entries.feedback_contexts.get(...)` expects `name=f"{entry_name}/feedbackContext"`.

```python
import os
import agentplatform

os.environ["GOOGLE_GENAI_USE_ENTERPRISE"] = "TRUE"
client = agentplatform.Client(project="PROJECT_ID", location="asia-southeast1")
engine_name = "projects/PROJECT_ID/locations/asia-southeast1/reasoningEngines/AGENT_ENGINE_ID"

# 1. Create feedback entry (returns LRO; wait_for_completion=True is the SDK default)
# IMPORTANT: `event_id` MUST match the OTel span UUID `gcp.vertex.agent.event_id`
# (or `raw_event.id` in Managed Sessions) to render in the Console Traces UI.
create_op = client.feedback_entries.create(
    name=engine_name,
    session_id="SESSION_ID",
    event_id="c9ba0d5e-9ba2-41cb-abf4-49680e9d8ce4",
    feedback_type="THUMBS_UP",
    config={
        "feedback_text": "The fix passed all unit tests cleanly.",
        "feedback_labels": ["accurate", "tool_success"],
        "user_id": "user-123",
        "source": "Chat UI",
        "custom_metadata": {"model_name": "gemini-4-hydrogen", "thinking_level": "MEDIUM", "revision": "rev-42"},
    },
)
# None-safe LRO extraction (Pydantic operation models always have a `.response` attribute, which may be None)
resp = getattr(create_op, "response", None)
entry_name = resp.name if (resp is not None and getattr(resp, "name", None)) else create_op.name  # .../feedbackEntries/FEEDBACK_ENTRY_ID

# 2. Get feedback entry
entry = client.feedback_entries.get(name=entry_name)
print(entry.feedback_type, entry.feedback_labels, entry.feedback_text)

# 3. List feedback entries
# Verified for google-cloud-agentplatform==2.10.0:
# `feedback_entries.list(*, parent: str, config=None)` requires `parent=` (NOT `name=`, which raises TypeError),
# whereas `feedback_entries.create` and `feedback_entries.delete` use `name=`.
# Filterable fields: session_id, user_id, feedback_type, feedback_labels, create_time, update_time
# Sortable fields: create_time, update_time
for item in client.feedback_entries.list(
    parent=engine_name,
    config={
        "filter": 'session_id="SESSION_ID" AND feedback_type="THUMBS_UP"',
        "order_by": "create_time desc",
    },
):
    print(item.name, item.feedback_type)

# 4. Update feedback entry (returns LRO)
update_op = client.feedback_entries.update(
    name=entry_name,
    feedback_type="THUMBS_DOWN",
    config={
        "feedback_text": "Missed an edge case in null handling.",
        "feedback_labels": ["incomplete"],
    },
)

# 5. Update FeedbackContext (preserves transcript if session is deleted; pass [] to clear)
ctx_op = client.feedback_entries.feedback_contexts.update(
    name=entry_name,  # NOTE: entry_name WITHOUT `/feedbackContext` suffix
    context_events=[
        {"author": "user", "content": {"role": "user", "parts": [{"text": "Fix the parser bug."}]}},
        {"author": "coding_agent", "content": {"role": "model", "parts": [{"text": "Updated parser.py."}]}},
    ],
)

# 6. Get FeedbackContext
ctx = client.feedback_entries.feedback_contexts.get(
    name=f"{entry_name}/feedbackContext"  # NOTE: WITH `/feedbackContext` suffix
)
for ev in ctx.context_events:
    text = ev.content.parts[0].text if ev.content and ev.content.parts else ""
    print(ev.author, text)

# 7. Delete feedback entry (automatically deletes its child FeedbackContext)
client.feedback_entries.delete(name=entry_name)
```

---

## 3. Verified `v1beta1` REST API Endpoints

Base path: `https://LOCATION-aiplatform.googleapis.com/v1beta1/projects/PROJECT_ID/locations/LOCATION/reasoningEngines/AGENT_ENGINE_ID`

| Operation | Method & Path | Notes |
|---|---|---|
| **Create** | `POST .../feedbackEntries` | Returns LRO |
| **Get** | `GET .../feedbackEntries/FEEDBACK_ENTRY_ID` | Single entry |
| **List** | `GET .../feedbackEntries` | Supports `?filter=...&orderBy=create_time%20desc` |
| **Update** | `PATCH .../feedbackEntries/FEEDBACK_ENTRY_ID?updateMask=feedbackType,feedbackLabels,feedbackText` | Returns LRO |
| **Delete** | `DELETE .../feedbackEntries/FEEDBACK_ENTRY_ID` | Also deletes `feedbackContext` |
| **Get Context** | `GET .../feedbackEntries/FEEDBACK_ENTRY_ID/feedbackContext` | Returns `contextEvents` |
| **Update Context** | `PATCH .../feedbackEntries/FEEDBACK_ENTRY_ID/feedbackContext?updateMask=contextEvents` | Pass `"contextEvents": []` to clear |

```bash
# Example curl: Create a feedback entry
curl -X POST \
  -H "Authorization: Bearer $(gcloud auth print-access-token)" \
  -H "Content-Type: application/json; charset=utf-8" \
  -d '{
    "sessionId": "SESSION_ID",
    "eventId": "c9ba0d5e-9ba2-41cb-abf4-49680e9d8ce4",
    "feedbackType": "THUMBS_UP",
    "feedbackText": "Accurate and fast.",
    "feedbackLabels": ["accurate", "fast"],
    "userId": "user-123",
    "source": "Web UI"
  }' \
  "https://${LOCATION}-aiplatform.googleapis.com/v1beta1/projects/${PROJECT_ID}/locations/${LOCATION}/reasoningEngines/${AGENT_ENGINE_ID}/feedbackEntries"
```

---

## 4. Console UI Integration & Cloud Trace Export

### Viewing Feedback in the Google Cloud Console

1. Ensure Agent Runtime has **OpenTelemetry tracing enabled** (`GOOGLE_CLOUD_AGENT_ENGINE_ENABLE_TELEMETRY="true"`).
2. Navigate to **Agent Platform -> Deployments -> `<agent>` -> Traces**.
3. Use **Sessions view** or **Traces view**, filter by the **Feedback** column, select a trace ID with a feedback icon badge, and open the **Feedback** tab in the trace details pane.

### Critical UI & Trace Constraints

- **Strict `event_id` Correlation:** The Console UI ONLY maps feedback entries whose `event_id` matches the OpenTelemetry UUID in span attribute **`gcp.vertex.agent.event_id`** (emitted on `generate_content` / `execute_tool` spans, or stored as `raw_event.id` in Managed Sessions). Arbitrary custom IDs still save in the Feedback API but will **not** attach to traces in the UI.
- **Duplicate Submissions:** If multiple feedback entries share the same `(session_id, event_id)` pair, the Console UI displays **only the last received** entry.
- **Immutable Cloud Trace Export:** Submitting feedback automatically exports a Cloud Trace span named **`gcp.vertex.agent.feedback`**. Because Cloud Trace spans are immutable, **updating or deleting a feedback entry does NOT modify or delete previously exported trace spans**.

### Exported `gcp.vertex.agent.feedback` Span Attributes

| Attribute | Scope | Description |
|---|---|---|
| `gcp.project_id` | Resource | Google Cloud Project ID |
| `cloud.resource.id` | Resource | Agent Runtime (`reasoningEngines`) instance ID |
| `gcp.vertex.agent.feedback.type` | Span | `THUMBS_UP`, `THUMBS_DOWN`, or `FEEDBACK_TYPE_UNSPECIFIED` |
| `gen_ai.conversation_id` | Span | Session ID associated with the interaction |
| `gcp.vertex.agent.event_id` | Span | Event ID UUID of the specific conversation turn |
| `gcp.vertex.agent.feedback.entry.name` | Span | Full resource path of the created feedback entry |
| `gcp.vertex.agent.feedback.labels` | Span | Optional list of attached feedback labels |

---

## 5. Verification & Troubleshooting

- **End-to-end check:** Run an agent turn with tracing enabled, capture the OTel `gcp.vertex.agent.event_id` (or session `raw_event.id`), call `feedback_entries.create`, verify `feedback_entries.list(parent=engine_name, config={"filter": 'session_id="..."'})`, attach `feedback_contexts.update`, read back via `feedback_contexts.get(name=f"{entry_name}/feedbackContext")`, and confirm the feedback badge appears under **Deployments -> `<agent>` -> Traces**.
- **Common errors:**
  - Feedback missing from Console Traces UI -> `event_id` does not match `gcp.vertex.agent.event_id` UUID or tracing was disabled when the turn ran.
  - `404` / invalid resource name on `feedback_contexts.get` or `.update` -> verify `.update` uses `entry_name` and `.get` uses `f"{entry_name}/feedbackContext"`.
  - Updated/deleted feedback still visible in Cloud Trace explorer -> expected behavior; `gcp.vertex.agent.feedback` trace spans are immutable (query `client.feedback_entries.list` for current ground truth).
  - SDK error or missing `feedback_entries` behavior -> verify `GOOGLE_GENAI_USE_ENTERPRISE="TRUE"` and `google-cloud-agentplatform>=2.0.1` + `roles/aiplatform.user`.
