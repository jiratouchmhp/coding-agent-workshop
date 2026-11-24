# Lab 3: Managed Sessions, Memory Bank, Telemetry & Feedback

In this lab, you'll add persistent conversation history with Managed Sessions, cross-chat recall with Memory Bank, and parent-runtime sandbox logs plus trace-linked user feedback. Everything here reuses the standalone `REASONING_ENGINE_NAME` you created in Lab 2 (`asia-southeast1`), so you don't need to build or deploy agent code yet.

**Duration:** 40 min (Full-Day) | 15 min (Half-Day Fast-Track: instructor live demo or run `make fast-forward LAB=3`)  
**Previous:** [Lab 2: Custom Sandbox (BYOC), Lifecycle & Execution](./02-LAB-CUSTOM-SANDBOX-BYOC.md) | **Next:** [Lab 4: Extend with Skill Registry & Agent Registry](./04-LAB-SKILLS-AND-AGENT-REGISTRY.md)

## Files You Will Edit

| Step | File | Where to edit | What you're adding |
|---|---|---|---|
| Step 1 | [starter/coding_agent/memory/session_manager.py](../starter/coding_agent/memory/session_manager.py) | `build_adk_session_service()`, `SessionLifecycleManager.create_session()` | Wire ADK `VertexAiSessionService` (with local fallback) and direct session creation with TTL and LRO handling |
| Step 2 | [starter/coding_agent/memory/memory_bank_manager.py](../starter/coding_agent/memory/memory_bank_manager.py) | `build_adk_memory_service()`, `MemoryBankManager.generate_memories_from_session()`, `MemoryBankManager.retrieve_similar_memories()` | Wire ADK `VertexAiMemoryBankService`, session-to-memory generation, and semantic similarity search |
| Step 3 | [starter/coding_agent/callbacks/telemetry_and_feedback.py](../starter/coding_agent/callbacks/telemetry_and_feedback.py) | `after_tool_callback()`, `FeedbackClient.submit_feedback()` | Log redacted sandbox stdout/stderr from the parent runtime, attach OTel attributes, and submit trace-linked feedback |
| Step 4 | [starter/coding_agent/agent.py](../starter/coding_agent/agent.py) | `_build_optional_callbacks()` | Attach telemetry callbacks, `PreloadMemoryTool()`, and `persist_turn_to_memory_callback` to the coding agent |
| Step 5 | Checkpoint | `make verify-lab LAB=3` | Verify zero `# TODO(lab-3)` markers remain and all syntax/SDK checks pass |

**Already built for you (no edits needed):** Session CRUD and event helpers (`get_session`, `list_sessions`, `append_event`, `list_events`, `delete_session`) in `session_manager.py`; Memory Bank config, topic, revision, TTL, purge, and sanitizer helpers (`sanitize_for_memory_ingestion`, `persist_turn_to_memory_callback`) in `memory_bank_manager.py`; and `build_reasoning_engine_logger`, `before_tool_callback`, and `FeedbackContext` helpers in `telemetry_and_feedback.py`.

**Stuck or catching up?** Ask your IDE agent with [`.agents/skills/agent-platform-runtime-and-state/SKILL.md`](../.agents/skills/agent-platform-runtime-and-state/SKILL.md), or run `make fast-forward LAB=3` to sync only Lab 3 without spoiling Labs 4-6.

---

## Step 1: Wire Managed Sessions

**File:** [starter/coding_agent/memory/session_manager.py](../starter/coding_agent/memory/session_manager.py) -> `build_adk_session_service()` and `SessionLifecycleManager.create_session()` (`# TODO(lab-3)`)

You'll edit two functions here so your coding agent persists multi-turn history and state updates in Managed Sessions while falling back to `InMemorySessionService` for offline tests. `build_adk_session_service()` plugs into the ADK runner, and `SessionLifecycleManager.create_session()` wraps `agentplatform.Client.sessions` directly for backend scripts and demos.

- In `build_adk_session_service()`: import `InMemorySessionService` and `VertexAiSessionService` from `google.adk.sessions`. When both `project_id` and `agent_engine_id` are set, call `os.environ.setdefault("GOOGLE_GENAI_USE_ENTERPRISE", "TRUE")` and return `VertexAiSessionService(project=project_id, location=location, agent_engine_id=agent_engine_id)`; otherwise return `InMemorySessionService()`.
- In `SessionLifecycleManager.create_session()`: build `config` with optional `"session_id"`, plus either `"expire_time"` or `"ttl": f"{ttl_days * 24 * 60 * 60}s"`. Call `self.client.sessions.create(name=runtime_name, user_id=user_id, ...)` and return `_extract_session_name(session_op)`. (Omit `session_id` to get a server-generated numeric ID whenever you plan to pass the session into Step 2's `generate_memories_from_session()`.)

> [!WARNING]
> **Two `google-cloud-agentplatform==2.10.0` quirks to watch out for:**
> 1. Pass `session_id` inside `config={"session_id": ...}`, never as a top-level keyword argument to `client.sessions.create()` (top-level `session_id=` raises `TypeError`).
> 2. `RuntimeSessionOperation` always exposes a `.response` attribute that can be `None`, so `hasattr(op, "response")` is always `True`. Always use the pre-filled `_extract_session_name()` helper to check `response is not None`.

<details>
<summary>Stuck? Peek at the code</summary>

```python
# Replace # TODO(lab-3) in build_adk_session_service() (indent 4 spaces):
    from google.adk.sessions import InMemorySessionService, VertexAiSessionService

    if project_id and agent_engine_id:
        os.environ.setdefault("GOOGLE_GENAI_USE_ENTERPRISE", "TRUE")
        return VertexAiSessionService(
            project=project_id,
            location=location,
            agent_engine_id=agent_engine_id,
        )
    return InMemorySessionService()
```

```python
# Replace # TODO(lab-3) in SessionLifecycleManager.create_session() (indent 8 spaces):
        config: dict[str, Any] = {}
        if session_id is not None:
            config["session_id"] = session_id
        if expire_time is not None:
            config["expire_time"] = expire_time
        elif ttl_days is not None:
            config["ttl"] = f"{ttl_days * 24 * 60 * 60}s"

        kwargs: dict[str, Any] = {"name": runtime_name, "user_id": user_id}
        if config:
            kwargs["config"] = config
        session_op = self.client.sessions.create(**kwargs)
        return _extract_session_name(session_op)
```

</details>

**Check it works:**

```bash
(cd starter && uv run python -m coding_agent.memory.session_manager --offline-check)
# Optional live round-trip against Lab 2's REASONING_ENGINE_NAME:
(cd starter && uv run python -m coding_agent.memory.session_manager --user-id workshop-dev --demo)
```

`--offline-check` prints JSON with `"adk_session_service_class": "InMemorySessionService"` and `"session_id_valid": true`. Live `--demo` creates a session, appends 2 events, lists them back, and deletes the test session (`"deleted": true`).

---

## Step 2: Add Memory Bank Generation & Similarity Retrieval

**File:** [starter/coding_agent/memory/memory_bank_manager.py](../starter/coding_agent/memory/memory_bank_manager.py) -> `build_adk_memory_service()`, `MemoryBankManager.generate_memories_from_session()`, and `MemoryBankManager.retrieve_similar_memories()` (`# TODO(lab-3)`)

Managed Sessions remember one chat; Memory Bank distills durable facts across future chats, such as `"Always run pytest -q and ruff check before opening a PR"`. You'll complete three functions here while reusing the pre-filled topic configuration, revision helpers, and `sanitize_for_memory_ingestion()` prompt-injection filter.

- In `build_adk_memory_service()`: import `InMemoryMemoryService` and `VertexAiMemoryBankService` from `google.adk.memory`. When both `project_id` and `agent_engine_id` are set, call `validate_memory_bank_location(location)`, set `GOOGLE_GENAI_USE_ENTERPRISE="TRUE"`, and return `VertexAiMemoryBankService(...)`; otherwise return `InMemoryMemoryService()`.
- In `generate_memories_from_session()`: resolve `resolved_scope` from `scope` or `{"user_id": user_id}` (omit `scope` from kwargs if both are `None` so the backend derives it from the session), validate it with `validate_memory_scope()`, build `vertex_session_source` (`session`, optional `start_time`/`end_time`) and `config` (`wait_for_completion`, default `metadata`, `metadata_merge_strategy`, default `allowed_topics`), and call `self.client.memory_banks.memories.generate(...)`.
- In `retrieve_similar_memories()`: call `self.client.memory_banks.memories.retrieve(name=target_name, scope=resolved_scope, similarity_search_params={"search_query": query, "top_k": top_k})`, iterate over `getattr(resp, "page", resp) or []` rather than eager `list(resp)`, and return dicts with `distance`, `name`, and `fact`.
- **Important session-ID rule:** `generate_memories_from_session(vertex_session_source=...)` returns HTTP `404 NOT_FOUND` on sessions created with custom string `session_id`s (like `session_manager --demo`'s `workshop-sess-...`). Always pass a **server-generated numeric session ID** (created by calling `create_session(user_id=...)` with `session_id=None`).
- SDK namespace note: all memory calls live under `client.memory_banks.memories.*` (there is no `client.memories`), and TTL configs require `"granular_ttl_config"` rather than `"granular_ttl"`.

<details>
<summary>Stuck? Peek at the code</summary>

```python
# Replace # TODO(lab-3) in build_adk_memory_service() (indent 4 spaces):
    from google.adk.memory import InMemoryMemoryService, VertexAiMemoryBankService

    if project_id and agent_engine_id:
        validate_memory_bank_location(location)
        os.environ.setdefault("GOOGLE_GENAI_USE_ENTERPRISE", "TRUE")
        return VertexAiMemoryBankService(
            project=project_id,
            location=location,
            agent_engine_id=agent_engine_id,
        )
    return InMemoryMemoryService()
```

```python
# Replace # TODO(lab-3) in MemoryBankManager.generate_memories_from_session() (indent 8 spaces):
        resolved_scope = scope if scope is not None else ({"user_id": user_id} if user_id else None)
        if resolved_scope is not None:
            validate_memory_scope(resolved_scope)

        vertex_session_source: dict[str, Any] = {"session": session_name}
        if start_time is not None:
            vertex_session_source["start_time"] = start_time
        if end_time is not None:
            vertex_session_source["end_time"] = end_time

        config: dict[str, Any] = {
            "wait_for_completion": wait_for_completion,
            "metadata": metadata or {"source_app": {"string_value": "coding-agent"}},
            "metadata_merge_strategy": metadata_merge_strategy,
            "allowed_topics": allowed_topics
            or [
                {"managed_memory_topic": "USER_PREFERENCES"},
                {"custom_memory_topic_label": "coding_conventions"},
            ],
        }
        kwargs: dict[str, Any] = {
            "name": target_name,
            "vertex_session_source": vertex_session_source,
            "config": config,
        }
        if resolved_scope is not None:
            kwargs["scope"] = resolved_scope
        return self.client.memory_banks.memories.generate(**kwargs)
```

```python
# Replace # TODO(lab-3) in MemoryBankManager.retrieve_similar_memories() (indent 8 spaces):
        resp = self.client.memory_banks.memories.retrieve(
            name=target_name,
            scope=resolved_scope,
            similarity_search_params={"search_query": query, "top_k": top_k},
        )
        items = getattr(resp, "page", resp) or []
        return [
            {
                "distance": getattr(item, "distance", None),
                "name": str(getattr(item.memory, "name", "")),
                "fact": str(getattr(item.memory, "fact", "")),
            }
            for item in items
        ]
```

</details>

**Check it works:**

```bash
(cd starter && uv run python -m coding_agent.memory.memory_bank_manager --offline-check)
# Optional live round-trip (configures topics, blocks a poisoned prompt, generates, retrieves, purges):
(cd starter && uv run python -m coding_agent.memory.memory_bank_manager --user-id workshop-dev --demo)
```

`--offline-check` outputs `"adk_memory_service_class": "InMemoryMemoryService"`, `"configured_topics_count": 5`, `"poison_text_blocked": true`, and `"secret_redacted": true`. Live `--demo` exercises pre-filled `generate_memories_from_text()` plus your `retrieve_similar_memories()` (reporting 2 accepted utterances, 1 blocked prompt-injection attempt, and matching similarity results). To test `generate_memories_from_session()` live too, create a session with `session_id=None` via `SessionLifecycleManager`, append a text event, and pass that server-generated numeric `session_name` into `MemoryBankManager.generate_memories_from_session()`.

---

## Step 3: Capture Sandbox Logs, OTel Spans & Feedback

**File:** [starter/coding_agent/callbacks/telemetry_and_feedback.py](../starter/coding_agent/callbacks/telemetry_and_feedback.py) -> `after_tool_callback()` and `FeedbackClient.submit_feedback()` (`# TODO(lab-3)`)

Cloud Logging attaches only to the parent `aiplatform.googleapis.com/ReasoningEngine` resource, not to child resources like Managed Sandboxes. You'll complete `after_tool_callback()` so the parent runtime logs secret-redacted `stdout`/`stderr` previews and tags the active OpenTelemetry span, then implement `FeedbackClient.submit_feedback()` to attach user ratings to sessions and traces.

> [!CAUTION]
> **Two real runtime traps here:**
> 1. **ADK 2.0 `tool_context.state` has no `.pop()` method.** Calling `state.pop(key, None)` crashes with `AttributeError: 'State' object has no attribute 'pop'`. Read with `state.get(start_key, None)` and clear with `state[start_key] = None`.
> 2. **ADK Python OTel content capture accepts enum strings only.** Set `OTEL_INSTRUMENTATION_GENAI_CAPTURE_MESSAGE_CONTENT="EVENT_ONLY"` (valid: `NO_CONTENT`, `EVENT_ONLY`, `SPAN_ONLY`, `SPAN_AND_EVENT`). Passing `"true"` silently falls back to `NO_CONTENT`.

- In `after_tool_callback()`: read `state.get(f"_tool_start_ts:{tool_name}", None)` (set by `before_tool_callback`), clear it with `state[start_key] = None`, compute `duration_ms` with `time.monotonic()`, unpack `stdout`/`stderr`/`exit_code`/`timed_out` from `_extract_tool_execution_fields(tool_response)`, tag `trace.get_current_span()` when recording, and call `_emit_structured_tool_log(...)` with `redact_and_truncate_preview(...)` (severity `INFO` if `exit_code in (None, 0)` and not timed out, else `WARNING`). Return `None` so ADK preserves `tool_response`.
- In `FeedbackClient.submit_feedback()`: verify `session_id` and `event_id` are non-empty, merge optional `score` and `trace_id` (falling back to `_current_trace_info(self.project_id)[0]`) into string-valued `custom_metadata`, call `self.client.feedback_entries.create(...)`, and return `_extract_entry_name(op)`.
- Pass the OTel span attribute `gcp.vertex.agent.event_id` (or `raw_event.id` from Managed Sessions) as `event_id` so ratings appear directly on spans in Console Traces.

<details>
<summary>Stuck? Peek at the code</summary>

```python
# Replace # TODO(lab-3) in after_tool_callback() (indent 4 spaces):
    del args
    tool_name = str(getattr(tool, "name", None) or getattr(tool, "__name__", "tool"))
    state = getattr(tool_context, "state", None)
    start_key = f"_tool_start_ts:{tool_name}"
    start_ts = state.get(start_key, None) if state is not None else None
    if state is not None and start_ts is not None:
        state[start_key] = None  # ADK 2.0 State has no .pop()!
    duration_ms = int((time.monotonic() - start_ts) * 1000) if start_ts is not None else -1

    fields = _extract_tool_execution_fields(tool_response)
    stdout_text, stderr_text = fields["stdout"], fields["stderr"]
    exit_code, timed_out = fields["exit_code"], fields["timed_out"]

    settings = get_settings()
    trace_hex, trace_resource = _current_trace_info(settings.google_cloud_project)
    span = trace.get_current_span()
    if span is not None and span.is_recording():
        span.set_attribute("coding_agent.tool.name", tool_name)
        if duration_ms >= 0:
            span.set_attribute("coding_agent.tool.duration_ms", duration_ms)
        if exit_code is not None:
            span.set_attribute("coding_agent.sandbox.exit_code", exit_code)

    invocation_ctx = getattr(tool_context, "_invocation_context", None)
    session_obj = getattr(invocation_ctx, "session", None)
    session_id = str(getattr(tool_context, "session_id", None) or getattr(session_obj, "id", ""))
    severity = "INFO" if exit_code in (None, 0) and not timed_out else "WARNING"
    payload: dict[str, Any] = {
        "event": "sandbox_tool_execution" if exit_code is not None else "tool_execution",
        "tool_name": tool_name,
        "duration_ms": duration_ms,
        "exit_code": exit_code,
        "timed_out": timed_out,
        "sandbox_mode": settings.sandbox_mode,
        "stdout_preview": redact_and_truncate_preview(stdout_text, max_chars=preview_max_chars),
        "stderr_preview": redact_and_truncate_preview(stderr_text, max_chars=preview_max_chars),
        "session_id": session_id,
        "invocation_id": str(getattr(tool_context, "invocation_id", "") or ""),
        "trace_id": trace_hex or "",
    }
    target_logger = (
        cloud_logger
        if cloud_logger is not None
        else _get_cached_cloud_logger(
            settings.google_cloud_project, settings.google_cloud_location, DEFAULT_TOOL_LOG_ID
        )
    )
    _emit_structured_tool_log(
        payload,
        severity=severity,
        cloud_logger=target_logger,
        labels={"tool_name": tool_name, "sandbox_mode": settings.sandbox_mode},
        trace_resource=trace_resource,
    )
    return None
```

```python
# Replace # TODO(lab-3) in FeedbackClient.submit_feedback() (indent 8 spaces):
        if not session_id or not event_id:
            raise ValueError("Both session_id and event_id are required to submit feedback.")

        merged_metadata: dict[str, str] = {str(k): str(v) for k, v in (custom_metadata or {}).items()}
        if score is not None:
            merged_metadata["score"] = f"{float(score):.3f}"
        resolved_trace_id = trace_id or _current_trace_info(self.project_id)[0]
        if resolved_trace_id:
            merged_metadata["trace_id"] = resolved_trace_id

        config: dict[str, Any] = {
            "feedback_text": feedback_text,
            "feedback_labels": list(feedback_labels or []),
            "source": source,
            "custom_metadata": merged_metadata,
        }
        if user_id:
            config["user_id"] = user_id

        op = self.client.feedback_entries.create(
            name=self._require_runtime_name(),
            session_id=session_id,
            event_id=event_id,
            feedback_type=feedback_type,
            config=config,
        )
        return _extract_entry_name(op)
```

</details>

**Check it works:**

```bash
set -a && source .env && set +a
(cd starter && uv run python -m coding_agent.callbacks.telemetry_and_feedback --offline-check)
```

Use `set -a && source .env && set +a` (not plain `source .env`) so OTel variables are exported into child `uv run` and `adk web` processes. Expected output: JSON with `"recorded_log_count": 1`, `"severity": "INFO"`, `"stdout_preview": "3 passed in 0.12s\nAPI_KEY=[REDACTED]"`, and `"otel_warnings": []`.

---

## Step 4: Wire Callbacks & Memory Tool into `agent.py`

**File:** [starter/coding_agent/agent.py](../starter/coding_agent/agent.py) -> `_build_optional_callbacks()` (`# TODO(lab-3)`)

Now plug your telemetry callbacks and Memory Bank hooks into the coding agent factory so they activate whenever `ENABLE_TELEMETRY_CALLBACKS=true` or `ENABLE_MEMORY_BANK=true` in `.env` (and carry straight into your Lab 5 runtime deployment).

- When `settings.enable_telemetry_callbacks` is `True`, import `before_tool_callback` and `after_tool_callback` from `coding_agent.callbacks.telemetry_and_feedback` and assign both on `callbacks`.
- When `settings.enable_memory_bank` is `True`, import `PreloadMemoryTool` from `google.adk.tools.preload_memory_tool` and `persist_turn_to_memory_callback` from `coding_agent.memory.memory_bank_manager`. Append `PreloadMemoryTool()` to `callbacks["extra_tools"]` and assign `callbacks["after_agent_callback"] = persist_turn_to_memory_callback`.

<details>
<summary>Stuck? Peek at the code</summary>

```python
# Replace # TODO(lab-3) in _build_optional_callbacks() (indent 4 spaces):
    if settings.enable_telemetry_callbacks:
        from coding_agent.callbacks.telemetry_and_feedback import (
            after_tool_callback,
            before_tool_callback,
        )

        callbacks["before_tool_callback"] = before_tool_callback
        callbacks["after_tool_callback"] = after_tool_callback

    if settings.enable_memory_bank:
        from google.adk.tools.preload_memory_tool import PreloadMemoryTool

        from coding_agent.memory.memory_bank_manager import persist_turn_to_memory_callback

        callbacks["extra_tools"].append(PreloadMemoryTool())
        callbacks["after_agent_callback"] = persist_turn_to_memory_callback

    return callbacks
```

</details>

**Check it works:**

```bash
(cd starter && uv run python - <<'EOF'
from coding_agent.agent import _build_optional_callbacks
from coding_agent.config import Settings

bundle = _build_optional_callbacks(
    Settings(enable_telemetry_callbacks=True, enable_memory_bank=True)
)
print("callbacks:", {k: bool(v) for k, v in bundle.items()})
EOF
)
```

Expected output: `callbacks: {'before_tool_callback': True, 'after_tool_callback': True, 'after_agent_callback': True, 'extra_tools': True}`.

---

## Step 5: Lab 3 Checkpoint

Run the Lab 3 verifier from the repo root:

```bash
make verify-lab LAB=3
```

Pass criteria:
1. Zero `# TODO(lab-3)` markers remain in `session_manager.py`, `memory_bank_manager.py`, `telemetry_and_feedback.py`, and `agent.py`.
2. All four modules compile cleanly and pass SDK checks (`VertexAiSessionService`, `VertexAiMemoryBankService`, `sanitize_for_memory_ingestion`, `granular_ttl_config`, `feedback_entries.list(parent=...)`, and no invalid `sessions.get(user_id=...)` or top-level `sessions.create(session_id=...)` calls).

Compare against [`solution/coding_agent/memory/`](../solution/coding_agent/memory/), [`solution/coding_agent/callbacks/telemetry_and_feedback.py`](../solution/coding_agent/callbacks/telemetry_and_feedback.py), and [`solution/coding_agent/agent.py`](../solution/coding_agent/agent.py) if anything fails.

Next up: **[Lab 4: Extend with Skill Registry & Agent Registry](./04-LAB-SKILLS-AND-AGENT-REGISTRY.md)**.

---

## Optional Reference & Deep Dive

<details>
<summary>Architecture & comparing Managed Sessions, Memory Bank, and Feedback Service</summary>

| Store | Primary Purpose | Default TTL | Key Quotas (per project/region) | Cloud Logging Support |
|---|---|---|---|---|
| **Managed Sessions** | Per-conversation turn history, `state_delta`, and `raw_event` interoperability | 365 days (override with `ttl` / `expire_time`) | 100 writes/min; 300 event appends/min | Parent runtime only (not child Session APIs) |
| **Memory Bank** | Extracted, consolidated long-term facts across sessions | None by default (revisions default 365 days) | 100 writes/min; 300 reads/retrieves/min | Parent runtime only (not child Memory Bank APIs) |
| **Feedback Service** | Structured ratings (`THUMBS_UP`/`THUMBS_DOWN`), labels, and durable `FeedbackContext` snapshots | Retained until deleted (exports immutable Trace span) | Uses Reasoning Engine control plane (`roles/aiplatform.user`) | Linked directly to Cloud Trace (`gcp.vertex.agent.event_id`) |

Enable required GCP APIs if you haven't already run `make preflight`:

```bash
gcloud services enable aiplatform.googleapis.com telemetry.googleapis.com \
  logging.googleapis.com monitoring.googleapis.com cloudtrace.googleapis.com \
  --project="${GOOGLE_CLOUD_PROJECT}"
```

</details>

<details>
<summary>Managed Sessions: ID limits, out-of-band state updates & adk web shell tip</summary>

- **ID limits:** `user_id` max 128 chars. Custom `session_id` starting with a letter: up to 63 chars `[a-z0-9-]` ending with a letter or digit; starting with a digit: up to 9 digits `[0-9]` with no leading zeros.
- **State updates outside the runner:** Append a system `Event(invocation_id="...", author="system", actions=EventActions(state_delta={"active_repo": "payments-service"}), timestamp=time.time())` via `await session_service.append_event(session, state_event)`.
- **`adk web` shell tip:** When inspecting Managed Sessions with `adk web --session_service_uri=agentengine://${REASONING_ENGINE_ID}`, `adk web` ignores `.env` whenever `--session_service_uri` is set. Export your env vars first with `set -a && source .env && set +a`.
- **Additional SDK 2.10 quirks:** `client.sessions.get(name=...)` accepts no `user_id=`; `client.runtimes.update(name=...)` uses `name=` (not `resource_name=`); `wait_for_completion` defaults to `True`; and the REST tab for `appendEvent` in `sessions/manage-with-api` copy-pastes the create payload, so prefer `client.sessions.events.append(...)`.
- **Custom stores (ADK 2.0 Service Registration):** Plug custom URI schemes (`mysession://`, `mymemory://`) into [`starter/services.yaml`](../starter/services.yaml) or [`starter/services.py`](../starter/services.py) (`services.py` overrides `services.yaml` on duplicate schemes; rigid custom SQL schemas need columns for ADK 2.0 `node_info` and `output` fields).

</details>

<details>
<summary>Memory Bank: custom topics JSON, models, streaming ingest & revision rollbacks</summary>

- **Models & regions:** Default generation model is `gemini-3.5-flash`. Default embedding model is `text-embedding-005` (`gemini-embedding-2` accepts only `global`, `us`, or `eu` in its resource path, never regional paths). You can only change the embedding model before storing your first memory. Memory Bank is unavailable in `asia-southeast2`, `australia-southeast2`, and `northamerica-northeast2`.
- **Config key split:** `client.memory_banks.create(managed_semantic_memory_config={...})` uses `"unstructured_memory_configs"`, whereas `client.runtimes.update(name=..., config={"context_spec": {"memory_bank_config": {...}}})` uses `"customization_configs"`. Both require `"granular_ttl_config"` inside `ttl_config`.
- **Scopes & ingestion:** Max 5 key-value pairs, no `*`, immutable, exact match (`VertexAiMemoryBankService` scopes to `{"user_id": USER_ID, "app_name": APP_NAME}`). Prefer `memories.generate()` or `client.memory_banks.ingest_events(...)` over `memories.create()` (which skips consolidation). `memories.generate()` ignores function calls/responses; `ingest_events()` buffers by `(scope, stream_id)`, deduplicates by `event_id`, auto-flushes after 24h, requires `idle_duration` multiples of 60s, and defaults metadata merge strategy to `OVERWRITE` (vs. `MERGE` in `generate`).
- **Multi-region & cleanup:** Pass a `memory_service_builder` callable to `AdkApp` to pair a `global`/`us`/`eu` Memory Bank with a regional runtime (`AdkApp.async_search_memory` accepts `(user_id, query)` only). Wait ~60s before deleting a runtime right after a turn if you hit `FAILED_PRECONDITION`.

Custom topic and few-shot payload built by `MemoryBankManager.build_managed_semantic_memory_config()`:

```json
{
  "generation_config": {"model": "projects/<PROJECT_ID>/locations/global/publishers/google/models/gemini-3.5-flash"},
  "similarity_search_config": {"embedding_model": "projects/<PROJECT_ID>/locations/asia-southeast1/publishers/google/models/text-embedding-005"},
  "ttl_config": {
    "granular_ttl_config": {"create_ttl": "7776000s", "generate_created_ttl": "7776000s", "generate_updated_ttl": "7776000s"},
    "memory_revision_default_ttl": "31536000s"
  },
  "unstructured_memory_configs": [{
    "scope_keys": ["user_id"],
    "memory_topics": [
      {"managed_memory_topic": {"managed_topic_enum": "USER_PREFERENCES"}},
      {"managed_memory_topic": {"managed_topic_enum": "KEY_CONVERSATION_DETAILS"}},
      {"managed_memory_topic": {"managed_topic_enum": "EXPLICIT_INSTRUCTIONS"}},
      {"custom_memory_topic": {"label": "coding_conventions", "description": "User-stated repo standards, test commands, and lint rules."}}
    ],
    "enable_third_person_memories": false,
    "generate_memories_examples": [
      {"conversationSource": {"events": [{"content": {"role": "user", "parts": [{"text": "Always run pytest -q and ruff check before committing."}]}}]},
       "generatedMemories": [{"fact": "I prefer running pytest -q and ruff check before committing changes."}]},
      {"conversationSource": {"events": [{"content": {"role": "user", "parts": [{"text": "Thanks, looks good!"}]}}]},
       "generatedMemories": []}
    ]
  }],
  "disable_memory_revisions": false
}
```

**Revisions, rollback, and purge (pre-filled):** Deleted memories retain revisions for up to 48 hours. Call `manager.list_revisions(memory_name)`, `manager.rollback_memory(memory_name, target_revision_id)`, and `manager.purge_user_memories(user_id, force=False)` (dry-run count; `force=True` deletes). For Model Armor, exact-casing `aiplatform.googleapis.com/memoryScope` IAM Conditions, CMEK, and VPC-SC, see [Lab 7 (Optional)](./07-LAB-OPTIONAL-SECURITY-AND-GOVERNANCE.md).

</details>

<details>
<summary>Cloud Logging, Cloud Monitoring PromQL & FeedbackContext deep dive</summary>

**OTel environment flags** (in `.env.example` and injected via Terraform in [Lab 5](./05-LAB-DEPLOY-RUNTIME-TERRAFORM.md)):
`GOOGLE_CLOUD_AGENT_ENGINE_ENABLE_TELEMETRY="true"`, `OTEL_SEMCONV_STABILITY_OPT_IN="gen_ai_latest_experimental"`, `OTEL_INSTRUMENTATION_GENAI_CAPTURE_MESSAGE_CONTENT="EVENT_ONLY"`. Capturing `user.id` requires ADK `>= 2.1`; OTel GenAI metrics require ADK `>= 2.6.0`.

Query parent-runtime sandbox logs after deploying in [Lab 5](./05-LAB-DEPLOY-RUNTIME-TERRAFORM.md):

```bash
gcloud logging read \
  'resource.type="aiplatform.googleapis.com/ReasoningEngine" AND resource.labels.reasoning_engine_id="'"${REASONING_ENGINE_ID}"'"' \
  --project="${GOOGLE_CLOUD_PROJECT}" --limit=20 \
  --format="table(timestamp,severity,jsonPayload.event,jsonPayload.tool_name,jsonPayload.exit_code)"
```

**Cloud Monitoring & PromQL:** Built-in `aiplatform.googleapis.com/ReasoningEngine` metrics are `request_count`, `request_latencies`, `cpu/allocation_time`, and `memory/allocation_time`. Log-based metrics stay on `ReasoningEngine`, while user-defined custom metrics must use `monitoredResourceTypes: ["generic_node"]`. Latency alert baseline: `request_latencies` p99 > `5000ms` over `5m` (extended with quality alerts in [Lab 6](./06-LAB-OPTIMIZE-EVAL-AND-ALERTS.md)).

```promql
sum_over_time(sum(rate(aiplatform_googleapis_com:reasoning_engine_request_count{monitored_resource='aiplatform.googleapis.com/ReasoningEngine', reasoning_engine_id='RESOURCE_ID', response_code='500'}[10m]))[10m:10m])
/
sum_over_time(sum(rate(aiplatform_googleapis_com:reasoning_engine_request_count{monitored_resource='aiplatform.googleapis.com/ReasoningEngine', reasoning_engine_id='RESOURCE_ID'}[10m]))[10m:10m])
```

**Feedback Service & `FeedbackContext`:**
- Types: `THUMBS_UP`, `THUMBS_DOWN`, `FEEDBACK_TYPE_UNSPECIFIED`. Positive labels: `accurate`, `complete`, `helpful`, `on_topic`, `fast`, `safe`, `factual`, `tool_success`. Negative labels: `inaccurate`, `incomplete`, `unhelpful`, `off_topic`, `too_slow`, `unsafe`, `hallucination`, `tool_error`.
- Creating feedback exports an immutable `gcp.vertex.agent.feedback` Trace span; later updates or deletes do not modify exported spans, and Console displays only the newest entry per `(session_id, event_id)`.
- SDK path quirks (pre-filled): `feedback_entries.list(parent=runtime_name, ...)` takes `parent=` (while `create`/`delete` take `name=`); `feedback_contexts.update(name=entry_name, ...)` takes `.../feedbackEntries/ID`, while `feedback_contexts.get(name=f"{entry_name}/feedbackContext")` needs the `/feedbackContext` suffix. Deleting an entry deletes its child `FeedbackContext`.
- Live CLI submission and cleanup: submit with `(cd starter && uv run python -m coding_agent.callbacks.telemetry_and_feedback --session-id "<SID>" --event-id "<EID>" --feedback-type THUMBS_UP --labels accurate,tool_success)` and delete a test entry afterward with `--delete-feedback --entry-name "<ENTRY_NAME>"`.

</details>

<details>
<summary>Official documentation links</summary>

- Managed Sessions: https://docs.cloud.google.com/gemini-enterprise-agent-platform/scale/sessions (ADK: `/manage-with-adk`, Direct API: `/manage-with-api`, IAM: `/iam-conditions`)
- Memory Bank: https://docs.cloud.google.com/gemini-enterprise-agent-platform/scale/memory-bank (Setup: `/setup`, ADK: `/use-with-adk`, Generate: `/generate-memories`, Fetch: `/fetch-memories`, Stream: `/ingest-events`, Revisions: `/revisions`)
- Feedback Service: https://docs.cloud.google.com/gemini-enterprise-agent-platform/scale/feedback-service (`/manage-with-sdk-or-api`, `/view-with-ui`)
- Runtime Telemetry: https://docs.cloud.google.com/gemini-enterprise-agent-platform/scale/runtime/tracing | `/logging` | `/monitoring`

</details>
