# Managed Sessions & Memory Bank

Production reference for stateful agent persistence on Gemini Enterprise Agent Platform: **Managed Sessions** (turn-by-turn conversation history and temporary state) and **Memory Bank** (cross-session LLM-extracted facts, streaming ingestion, structured profiles, revisions, and security governance).

---

## 1. Sessions vs. Memory Bank Selection

| Capability | Managed Sessions | Memory Bank |
|---|---|---|
| **Scope & Lifetime** | Single conversation thread (`user_id` + `session_id`); default TTL **365 days** | Cross-session identity scope (up to **5** key-value pairs); default **no TTL** (revisions default **365 days**) |
| **Data Model** | Chronological `SessionEvent` stream + mutable `state` dict | Self-contained natural-language `Memory.fact` items AND/OR static-schema `STRUCTURED_PROFILE` records |
| **ADK Service** | `VertexAiSessionService(project, location, agent_engine_id)` | `VertexAiMemoryBankService(project, location, agent_engine_id)` (auto-scopes to `{"user_id", "app_name"}`) |
| **Direct SDK Namespace** | `client.sessions.{create,get,list,delete}` + `client.sessions.events.{list,append}` | `client.memory_banks.{create,delete,ingest_events}` + `client.memory_banks.memories.*` |
| **Parent Resource** | Standalone `reasoningEngines` instance (no code deploy needed) or deployed runtime | Same (can pair a multi-regional `us` Memory Bank with a single-region `us-central1` deployed `AdkApp`) |

---

## 2. Managed Sessions (ADK & Direct API)

### Core Constraints & Locations

- **Locations:** All supported single regions, multi-regional (`us`, `eu`), and `global`.
- **ID Limits:**
  - `user_id`: max **128 characters**.
  - Custom `session_id`: if starting with a letter, up to **63 chars** `[a-z0-9-]` ending with alphanumeric; if starting with a digit, up to **9 chars** `[0-9]` with no leading zeros.
- **TTL:** Defaults to **365 days** unless `ttl` (e.g., `"864000s"`) or `expire_time` (ISO 8601 / `datetime`) is specified.
- **ADK Web CLI Gotcha:** `adk web --session_service_uri=agentengine://AGENT_ENGINE_ID` **ignores `.env`** when `--session_service_uri` is passed—export `GOOGLE_CLOUD_PROJECT` and `GOOGLE_CLOUD_LOCATION` in your shell first.

### ADK Managed Sessions (`VertexAiSessionService`)

```python
import asyncio, os, time
import agentplatform
from google import adk
from google.adk import Runner
from google.adk.events import Event, EventActions
from google.adk.sessions import VertexAiSessionService
from google.genai import types

os.environ["GOOGLE_GENAI_USE_ENTERPRISE"] = "TRUE"

# 1. Standalone parent instance for Sessions (no code deployment required)
client = agentplatform.Client(project="PROJECT_ID", location="us-central1")
parent = client.runtimes.create(config={"display_name": "Workshop Session Store"})
agent_engine_id = parent.api_resource.name.split("/")[-1]

# 2. Wire ADK Runner to VertexAiSessionService
root_agent = adk.Agent(model="gemini-3.5-flash", name="coding_agent", instruction="Help with code.")
session_service = VertexAiSessionService(project="PROJECT_ID", location="us-central1", agent_engine_id=agent_engine_id)
runner = Runner(agent=root_agent, app_name="coding_agent", session_service=session_service)

async def main():
    app_name, user_id = "coding_agent", "user-123"
    session = await session_service.create_session(
        app_name=app_name,
        user_id=user_id,
        session_id="workshop-session-1",      # Optional; auto-generated if omitted
        state={"repo": "demo-app"},
        ttl=f"{10 * 24 * 60 * 60}s",
    )

    msg = types.Content(role="user", parts=[types.Part(text="Summarize repo layout.")])
    async for event in runner.run_async(user_id=user_id, session_id=session.id, new_message=msg):
        if event.is_final_response():
            print(event.content.parts[0].text)

    # Mutate session state outside runner via EventActions(state_delta=...)
    await session_service.append_event(
        session,
        Event(invocation_id="inv-state-1", author="system", actions=EventActions(state_delta={"repo": "demo-v2"}), timestamp=time.time()),
    )

    # Append custom framework fields (persisted into raw_event on backend)
    await session_service.append_event(
        session,
        Event(invocation_id="inv-custom-1", author="user", timestamp=time.time(), custom_field="v1"),
    )

    sessions = await session_service.list_sessions(app_name=app_name, user_id=user_id)
    fetched = await session_service.get_session(app_name=app_name, user_id=user_id, session_id=session.id)
    await session_service.delete_session(app_name=app_name, user_id=user_id, session_id=session.id)

asyncio.run(main())
```

### Direct SDK (`client.sessions`), Deployed `AdkApp` & `v1beta1` REST

```python
import datetime, agentplatform

client = agentplatform.Client(project="PROJECT_ID", location="us-central1")
runtime_name = "projects/PROJECT_ID/locations/us-central1/reasoningEngines/AGENT_ENGINE_ID"

# LRO return-shape guard: handle both session_op.response.name and session_op.name across SDK builds
session_op = client.sessions.create(
    name=runtime_name,
    user_id="user-123",
    session_id="custom-session-1",
    config={"ttl": f"{10 * 86400}s"},
)
session_name = session_op.response.name if hasattr(session_op, "response") else session_op.name

# List (default order: create_time desc; SDK lacks order_by -> use REST for custom sort)
for s in client.sessions.list(name=runtime_name, config={"filter": "user_id=user-123"}):
    print(s.name)

# Get, append standard Content OR raw_event, list events, delete
session = client.sessions.get(name=session_name, user_id="user-123")
client.sessions.events.append(
    name=session_name,
    author="user",
    invocation_id="1",
    timestamp=datetime.datetime.now(tz=datetime.timezone.utc),
    config={"content": {"role": "user", "parts": [{"text": "hello"}]}},
)
client.sessions.events.append(
    name=session_name,
    author="user",
    invocation_id="2",
    timestamp=datetime.datetime.now(tz=datetime.timezone.utc),
    config={"raw_event": {"content": "hello", "framework": "custom"}},
)
events = list(client.sessions.events.list(name=session_name))
client.sessions.delete(name=session_name)
```

- **Deployed `AdkApp` methods:** `await adk_app.async_create_session(user_id=...)`, `async_list_sessions`, `async_get_session`, `async_stream_query(user_id=..., session_id=..., message=...)`, `async_delete_session`. *Gotcha:* Omitting `session_id` auto-creates a new session; passing a non-existent `session_id` returns an empty response.
- **Verified `v1beta1` REST endpoints** (`https://LOCATION-aiplatform.googleapis.com/v1beta1/projects/PROJECT_ID/locations/LOCATION/reasoningEngines/AGENT_ENGINE_ID/sessions`):
  - `GET .../sessions?filter=user_id="USER_ID"&orderBy=update_time%20desc` (`create_time`, `update_time`, `display_name`)
  - `POST .../sessions` (`{"userId": "USER_ID"}`, returns LRO) | `GET .../sessions/SESSION_ID` | `DELETE .../sessions/SESSION_ID` | `GET .../sessions/SESSION_ID/events`
  - *Verified upstream doc bugs:* `manage-with-api.md` REST tab for appending events accidentally pasted `POST .../sessions` (use `client.sessions.events.append` in Python); `manage-with-adk.md` passes `resource_name=` to `client.runtimes.update(...)` instead of `name=`.

### Sessions IAM Conditions

- **Roles:** `roles/aiplatform.sessionViewer`, `roles/aiplatform.sessionEditor`, `roles/aiplatform.sessionUser`.
- **CEL attribute:** `api.getAttribute('aiplatform.googleapis.com/sessionUserId', '') == 'user-123'`.
- **Limits:** Max **1,500 unique principals** per policy. **`ListSessions` does NOT support IAM Conditions** (requires an unconditional role).

---

## 3. Memory Bank Setup, Customization & Models

### Regions, Default Models & Immutability

- **Unsupported regions:** `asia-southeast2`, `australia-southeast2`, `northamerica-northeast2`. Multi-regional (`us`, `eu`) and `global` are supported.
- **Generation LLM:** Defaults to **`gemini-3.5-flash`** effective **June 29, 2026** (earlier instances use `gemini-2.5-flash`). Routing: `us`/`us-*` -> `us`, `eu`/`eu-*` -> `eu`, others -> `global`.
- **Embedding Model:** Defaults to **`text-embedding-005`** (multilingual alternatives: `gemini-embedding-2`, `gemini-embedding-001`, `text-multilingual-embedding-002`).
  - **CRITICAL TRAP 1:** `gemini-embedding-2` ONLY accepts `global`, `us`, or `eu` in its model resource name—NOT regional locations like `us-central1`.
  - **CRITICAL TRAP 2:** The embedding model can **only be changed before the first memory is stored**.
- **Verified Upstream SDK Key Discrepancies:**
  1. `client.memory_banks.create(managed_semantic_memory_config={...})` uses **`"unstructured_memory_configs"`**, whereas `client.runtimes.update(name=..., config={"context_spec": {"memory_bank_config": {...}}})` uses **`"customization_configs"`**.
  2. Granular TTL dict uses `"granular_ttl": {...}`, whereas class-based SDK uses `TtlConfig(granular_ttl_config=GranularTtlConfig(...))`.
  3. Revision TTL appears as `"memory_revision_default_ttl"` in setup configs and `"revision_ttl"` in revision/request configs.

### Create & Update Customized Memory Bank

```python
import agentplatform

client = agentplatform.Client(project="PROJECT_ID", location="us")

memory_cfg = {
    "generation_config": {
        "model": "projects/PROJECT_ID/locations/global/publishers/google/models/gemini-3.5-flash"
    },
    "similarity_search_config": {
        "embedding_model": "projects/PROJECT_ID/locations/us/publishers/google/models/text-embedding-005"
    },
    "ttl_config": {
        "granular_ttl": {
            "create_ttl": f"{90 * 86400}s",
            "generate_created_ttl": f"{90 * 86400}s",
            "generate_updated_ttl": f"{90 * 86400}s",
        },
        "memory_revision_default_ttl": f"{365 * 86400}s",
    },
    "unstructured_memory_configs": [
        {
            "scope_keys": ["user_id"], # Exact key-set match; omit for default fallback
            "memory_topics": [
                {"managed_memory_topic": {"managed_topic_enum": "USER_PERSONAL_INFO"}},
                {"managed_memory_topic": {"managed_topic_enum": "USER_PREFERENCES"}},
                {"managed_memory_topic": {"managed_topic_enum": "KEY_CONVERSATION_DETAILS"}},
                {"managed_memory_topic": {"managed_topic_enum": "EXPLICIT_INSTRUCTIONS"}},
                {
                    "custom_memory_topic": {
                        "label": "coding_conventions",
                        "description": "User-stated repo coding standards, test commands, and architecture rules.",
                    }
                },
            ],
            "consolidation_config": {"revisions_per_candidate_count": 1}, # Increase (e.g. 10) for trend corroboration
            "enable_third_person_memories": False, # False = "I ..."; True = "The user ..."
            "generate_memories_examples": [
                {
                    "conversationSource": {"events": [{"content": {"role": "user", "parts": [{"text": "Always run pytest -q before committing."}]}}]},
                    "generatedMemories": [{"fact": "I prefer running pytest -q before committing."}],
                },
                {
                    "conversationSource": {"events": [{"content": {"role": "user", "parts": [{"text": "Thanks!"}]}}]},
                    "generatedMemories": [], # Negative example suppresses noisy extraction
                },
            ],
        }
    ],
    "disable_memory_revisions": False,
}

memory_bank = client.memory_banks.create(
    config={"display_name": "Workshop Memory Bank"},
    managed_semantic_memory_config=memory_cfg,
)

# Updating an existing instance uses `customization_configs` under `context_spec.memory_bank_config`:
client.runtimes.update(
    name=memory_bank.name,
    config={
        "context_spec": {
            "memory_bank_config": {
                "generation_config": memory_cfg["generation_config"],
                "customization_configs": memory_cfg["unstructured_memory_configs"],
                "similarity_search_config": memory_cfg["similarity_search_config"],
                "ttl_config": memory_cfg["ttl_config"],
                "disable_memory_revisions": False,
            }
        }
    },
)
```

---

## 4. ADK Integration (`VertexAiMemoryBankService`)

- Automatically scopes memories to **`{"user_id": USER_ID, "app_name": APP_NAME}`**.
- **Write callbacks:** Prefer incremental `callback_context.add_events_to_memory(events=...)` (backed by `IngestEvents`; pass `custom_metadata={"wait_for_completion": True}` in tests/demos) over full-session `add_session_to_memory()`.
- **Read tools:** `PreloadMemoryTool()` (auto-injects every turn), `LoadMemoryTool()` (model-decided), or a custom `FunctionTool` calling `await tool_context.search_memory(query)`.
- **ADK Web CLI:** `adk web --memory_service_uri=agentengine://$MEMORY_BANK_ID memory_agent` (default user is `user`; override with `?userId=USER_ID`). Also supported on `adk deploy cloud_run` and `adk deploy gke`.
- **Pairing multi-regional (`us`) Memory Bank with single-region (`us-central1`) `AdkApp`:**

```python
from agentplatform.frameworks import AdkApp
from google.adk.memory import VertexAiMemoryBankService

def memory_bank_service_builder() -> VertexAiMemoryBankService:
    return VertexAiMemoryBankService(project="PROJECT_ID", location="us", agent_engine_id="MEMORY_BANK_ID")

adk_app = AdkApp(agent=root_agent, memory_service_builder=memory_bank_service_builder)
```

> **Teardown Gotcha:** Deleting a runtime immediately after a conversation can fail with `FAILED_PRECONDITION` while background memory generation finishes—wait ~1 minute and retry.

---

## 5. Generation, Streaming Ingestion, Retrieval, Profiles & Revisions

### Scope & Multimodal Rules

- **Scope:** Max **5 key-value pairs**, **no `*` characters**, immutable. Consolidation and retrieval match **exact scope** (order-independent).
- **Multimodal:** Extracts textual insights from text, `inline_data`, and `file_data` (images/video/audio). **Function calls and function responses are ignored.**

### Generate, Create & Streaming `IngestEvents`

```python
import datetime, agentplatform

client = agentplatform.Client(project="PROJECT_ID", location="us")
mb_name = "projects/PROJECT_ID/locations/us/reasoningEngines/MEMORY_BANK_ID"

# 1. Generate from Managed Session (wait_for_completion=False recommended in prod; default True blocks!)
op = client.memory_banks.memories.generate(
    name=mb_name,
    vertex_session_source={
        "session": "projects/PROJECT_ID/locations/us/reasoningEngines/ENGINE_ID/sessions/SESSION_ID",
        "start_time": datetime.datetime.now(tz=datetime.timezone.utc) - datetime.timedelta(hours=1),
        "end_time": datetime.datetime.now(tz=datetime.timezone.utc),
    },
    scope={"user_id": "123"},
    config={
        "wait_for_completion": False,
        "metadata": {"source_app": {"string_value": "coding-agent"}, "verified": {"bool_value": True}},
        "metadata_merge_strategy": "MERGE", # MERGE (default in generate), OVERWRITE, REQUIRE_EXACT_MATCH
        "allowed_topics": [{"managed_memory_topic": "USER_PREFERENCES"}, {"custom_memory_topic_label": "coding_conventions"}],
    },
)

# 2. Generate from inline events (or direct_memories_source up to 5 pre-extracted facts; or semantic forget)
client.memory_banks.memories.generate(
    name=mb_name,
    direct_contents_source={"events": [{"content": {"role": "user", "parts": [{"text": "I prefer pytest with strict mypy."}]}}]},
    scope={"user_id": "123"},
    config={"wait_for_completion": True},
)

# 3. Streaming IngestEvents (buffers per (scope, stream_id), deduplicates event_id, auto-flushes at 24h)
# GOTCHA: default metadata_merge_strategy in IngestEvents is OVERWRITE (unlike MERGE in generate)!
# idle_duration and fixed_interval require multiples of 60s and are mutually exclusive.
client.memory_banks.ingest_events(
    name=mb_name,
    stream_id="coding-stream-1",
    direct_contents_source={"events": [{"content": {"role": "user", "parts": [{"text": "Use ruff check."}]}, "event_id": "ev-1"}]},
    generation_trigger_config={
        "generation_rule": {"event_count": 10, "idle_duration": "300s", "overlap_event_count": 2} # overlap < event_count
    },
    config={"revision_labels": {"source": "ide"}, "revision_ttl": f"{30 * 86400}s"}, # or "force_flush": True
    scope={"user_id": "123"},
)

# 4. Direct CreateMemory (CAUTION: bypasses extraction & consolidation -> can create duplicates!)
client.memory_banks.memories.create(name=mb_name, fact="I use Terraform >= 1.5.", scope={"user_id": "123"})
```

### Retrieval (Similarity Search & Scope Filters), Revisions, Rollback & Purge

```python
# 1. Scope-based similarity search (ascending Euclidean distance; top_k defaults to 3)
sim = client.memory_banks.memories.retrieve(
    name=mb_name,
    scope={"user_id": "123"},
    similarity_search_params={"search_query": "testing preferences", "top_k": 3},
)
for item in sim.page: # Always use .page (up to 100/page); avoid list() on large collections!
    print(item.distance, item.memory.fact)

# 2. Combined DNF metadata filter_groups (outer=OR, inner=AND) + EBNF filter
filtered = client.memory_banks.memories.retrieve(
    name=mb_name,
    scope={"user_id": "123"},
    config={
        "filter_groups": [{"filters": [{"key": "source_app", "value": {"string_value": "coding-agent"}}, {"key": "verified", "value": {"bool_value": True}}]}],
        "filter": 'fact=~".*pytest.*" AND update_time>="2026-01-01T00:00:00Z" AND topics.managed_memory_topic: USER_PREFERENCES',
    },
)

# 3. Revisions & Rollback (deleted memories retain revisions for up to 48 hours!)
revs = list(client.memory_banks.memories.revisions.list(name=mem_name, config={"filter": 'labels.source="ide"'}))
rev = client.memory_banks.memories.revisions.get(name=revs[0].name)
client.memory_banks.memories.rollback(name=mem_name, target_revision_id=prev_revision_id)

# 4. Delete single memory or Criteria Purge (force=False dry-runs and returns purge_count!)
client.memory_banks.memories.delete(name=mem_name, config={"wait_for_completion": True})
purge_op = client.memory_banks.memories.purge(
    name=mb_name, filter='scope.user_id="123"', force=True, config={"wait_for_completion": True}
)
print("Purged:", purge_op.response.purge_count)
```

> **Latency Rule:** `memories.list(...)` scans across scopes and is not recommended for low-latency serving—use scope-based `memories.retrieve(...)` with `.page`.

### Structured Memory Profiles (`retrieve_profiles`)

Define fixed Pydantic schemas for low-latency initialization without vector search (adding a schema does not backfill prior memories):

```python
from typing import Literal
from pydantic import BaseModel, Field

class UserProfile(BaseModel):
    technical_stack: str = Field(description="Comma-separated languages and tools.")
    expertise_level: str = Field(description="Skill level (e.g., Junior, Senior).")
    job_status: Literal["unemployed", "part_time", "full_time", "student"] = Field(description="Status.")

mb = client.memory_banks.create(
    managed_semantic_memory_config={
        "structured_memory_configs": [{"schema_configs": [{"id": "user-profile", "memory_schema": UserProfile.model_json_schema()}]}],
        # Optional: disable natural-language facts if only profiles are needed
        "unstructured_memory_configs": [{"disable_natural_language_memories": True}],
    }
)

# Low-latency consolidated profile read
profiles = client.memory_banks.memories.retrieve_profiles(name=mb.name, scope={"user_id": "123"})
print(profiles.profiles["user-profile"].profile)

# Audit individual STRUCTURED_PROFILE field memories & revisions
fragments = client.memory_banks.memories.retrieve(name=mb.name, scope={"user_id": "123"}, config={"memory_types": ["STRUCTURED_PROFILE"]})
```

---

## 6. Governance: Prompt-Injection Defense, IAM Conditions, CMEK & VPC-SC

### Prompt-Injection & Memory-Poisoning Governance

False or malicious instructions in conversation history can be persisted into Memory Bank and hijack future sessions. Upstream docs explicitly caution that built-in PII/sensitive-data exclusion is **not infallible**. Apply all three official mitigations plus pre-ingestion hygiene:

1. **Model Armor:** Inspect prompts sent to Memory Bank or emitted by your agent to block prompt injection and redact sensitive data before memory generation.
2. **Adversarial Testing (Red-Teaming):** Proactively simulate indirect prompt-injection and memory-poisoning payloads against both extraction and retrieval paths.
3. **Sandboxed Execution + Human Review:** Isolate external/critical tool calls in sandboxes with least-privilege IAM and human approval gates.
4. **Defense-in-Depth Pre-Ingestion Hygiene:** Strip `<untrusted_content>` / tool-output wrapper blocks, redact secrets (API keys, private keys, bearer tokens), and screen instruction-override patterns before calling `add_events_to_memory` / `generate`.

### Memory Bank IAM Conditions & Data Residency

- **Roles:** `roles/aiplatform.memoryViewer`, `roles/aiplatform.memoryEditor`, `roles/aiplatform.memoryUser` (minimal custom runtime SA permissions: `aiplatform.memories.generate`, `aiplatform.memories.retrieve`).
- **CEL Attribute:** `api.getAttribute('aiplatform.googleapis.com/memoryScope', {})` (exact key casing; prefer positive checks; shorten expressions to fit IAM policy size limits):
  - Exact: `api.getAttribute('aiplatform.googleapis.com/memoryScope', {}) == {'userId': 'userA'}`
  - Key match: `api.getAttribute('aiplatform.googleapis.com/memoryScope', {})['userId'] == 'userA'`
  - Prefix: `api.getAttribute('aiplatform.googleapis.com/memoryScope', {})['userId'].startsWith('user')`
  - Allowed set: `api.getAttribute('aiplatform.googleapis.com/memoryScope', {})['userId'] in ['userA', 'userB']`
- **Limits:** Max **1,500 unique principals**; **`ListMemories` and `PurgeMemories` do NOT support IAM Conditions**.
- **Cross-Border Prevention:** Deploy regional/multi-regional instances (`us`, `eu`), bind separate regional agent identities/SAs per jurisdiction, and enforce the `gcp.resourceLocations` Org Policy constraint. *(Note: ML processing falls back to `global` Gemini endpoints when a model lacks a regional endpoint, e.g., Gemini 3 or Asia single regions.)*

### CMEK & VPC-SC Rules (Sessions & Memory Bank)

| Control | Standalone Parent Instance (No Deployed Code) | Deployed Agent Runtime Parent |
|---|---|---|
| **CMEK (`encryption_spec`)** | Regional AND multi-regional (`us` with `us` key; `eu` with `europe` key). **Unsupported on `global`.** Key is **immutable**. | **Single-region only** (unsupported on `us`, `eu`, `global`). Key is **immutable**. |
| **VPC-SC Perimeter** | Add `aiplatform.googleapis.com` and project to perimeter **before creating** parent instance; route via `restricted.googleapis.com` (`199.36.153.4/30`) or PSC. | Same + if bound to enforcing Agent Gateway: `AgentConnectivityTemplate` (`vpcEgress: ALL_TRAFFIC`), private DNS peering for `googleapis.com.`, allowlist regional/mTLS `aiplatform` endpoints in Agent Registry, grant `roles/iap.egressor`. |

---

## 7. Verification & Troubleshooting

- **Verify Sessions:** Create a session, append an event, call `list_events`, confirm persistence, then delete.
- **Verify Memory Bank:** Call `memories.generate(..., config={"wait_for_completion": True})`, call `memories.retrieve(..., similarity_search_params={"search_query": "...", "top_k": 3})`, inspect `.page`, then dry-run `memories.purge(..., force=False)` before `force=True`.
- **Common errors:**
  - `adk web --session_service_uri` fails to find project/location -> export `GOOGLE_CLOUD_PROJECT` and `GOOGLE_CLOUD_LOCATION` in the shell (`.env` is ignored).
  - `gemini-embedding-2` creation fails -> change model location segment to `global`, `us`, or `eu` (never `us-central1`).
  - `FAILED_PRECONDITION` deleting runtime after chat -> wait ~1 min for async memory generation to settle and retry.
  - `PERMISSION_DENIED` on `ListSessions` / `ListMemories` / `PurgeMemories` -> IAM Conditions are unsupported on those RPCs; grant unconditional role or use scoped `retrieve`.
