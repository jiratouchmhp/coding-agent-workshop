# Runtime Management, Revisions, Contract, Sizing & Quotas

Operational reference for managing deployed **Agent Runtime** (`reasoningEngines`) instances, revisions, traffic splitting, emergency stops, the container runtime contract, concurrency tuning, regional support, and production quota sizing.

---

## 1. SDK & CLI Matrix

- **Canonical SDK:** `agentplatform.Client(project=..., location=...)` (`google-cloud-agentplatform>=2.0.1`, also bundled in `google-cloud-aiplatform>=1.154.0`). Pass `http_options={"api_version": "v1beta1"}` for **Revisions**, **Traffic Splitting**, and **Agent Identity**.
- **Legacy SDK (`vertexai`):** `vertexai.Client(...)` / `client.agent_engines.*` (`google-cloud-aiplatform[agent_engines,adk]>=1.144` for BYOC `container_spec`; `>=1.126.1` for console Observability toggles).
- **CLI Boundaries:** **No `gcloud` deploy CLI exists** for Agent Runtime (only `gcloud ai reasoning-engines describe` and `gcloud beta ai reasoning-engines add-iam-policy-binding`). Use Terraform, `agentplatform` SDK, REST, `adk deploy agent_engine`, `adkgo deploy agentengine`, or `agents-cli deploy`.

### Six SDK/REST Deployment Modes

| Mode | Languages | Archive / Bucket Requirement | Key `client.runtimes.create(config=...)` Fields |
|---|---|---|---|
| **1. Developer Connect** | Python | Private Git via Developer Connect | `developer_connect_source: {git_repository_link, revision, dir}`, `entrypoint_module`, `entrypoint_object`, `requirements_file` |
| **2. Public Git** | Python | Public Git repo | `git_source: {url, revision, dir}`, `entrypoint_module`, `entrypoint_object`, `class_methods` |
| **3. Local Source** | Python | `<= 8 MB` inline archive, no GCS | `source_packages`, `entrypoint_module`, `entrypoint_object`, `requirements_file`, `class_methods` |
| **4. Dockerfile (BYOD)** | Any | `<= 8 MB` archive with root `./Dockerfile`, no GCS | `source_packages: [..., "Dockerfile"]`, `image_spec: {}`, `class_methods` |
| **5. Prebuilt Image (BYOC)** | Any | Artifact Registry image | `container_spec: {"image_uri": "..."}`, `class_methods` |
| **6. Python Object (Pickle)** | Python | GCS `staging_bucket` | `agent=local_agent`, `requirements`, `extra_packages`, `build_options: {"installation_scripts": [...]}`, `gcs_dir_name` |

> **PSC-I via SDK:** Pass `"psc_interface_config": {"network_attachment": "...", "dns_peering_configs": [{"domain": "...", "target_project": "...", "target_network": "..."}]}` in `config`.

---

## 2. Deployed Agent CRUD, Invocation & Long-Running Query Jobs

### CRUD Operations (SDK & `v1` REST)

REST base: `https://LOCATION-aiplatform.googleapis.com/v1/projects/PROJECT_ID/locations/LOCATION/reasoningEngines`

```python
import agentplatform

client = agentplatform.Client(project="PROJECT_ID", location="LOCATION")
engine_name = "projects/PROJECT_ID/locations/LOCATION/reasoningEngines/RESOURCE_ID"

# List (optional display_name filter)
for rt in client.runtimes.list(config={"filter": 'display_name="my-agent"'}):
    print(rt.api_resource.name)

# Get
remote_agent = client.runtimes.get(name=engine_name)
print(remote_agent.operation_schemas())

# Update (unversioned metadata updates across all revisions; versioned spec fields create a new revision)
client.runtimes.update(
    name=engine_name,
    config={"display_name": "my-agent-v2", "description": "Updated description"},
)

# Delete (use force=True if child sessions/memories exist; invalidates SPIFFE identity!)
# After deletion, manually remove defunct SPIFFE principals from any IAM Unified Access Policies (UAPs).
client.runtimes.delete(name=engine_name, force=True)
```

- **REST equivalents:**
  - `GET .../reasoningEngines` | `GET .../reasoningEngines/RESOURCE_ID`
  - `PATCH .../reasoningEngines/RESOURCE_ID?update_mask="display_name,description"`
  - `DELETE .../reasoningEngines/RESOURCE_ID`

### Invocation Endpoints & Timeouts

| Pattern | Endpoint / SDK Method | Limits & Notes |
|---|---|---|
| **Unary Query** | `POST .../v1/.../reasoningEngines/ID:query` / `remote_agent.query(...)` | Sync/async request-response (`api_mode: ""` or `"async"`) |
| **SSE Streaming** | `POST .../v1/.../reasoningEngines/ID:streamQuery?alt=sse` / `remote_agent.async_stream_query(...)` | **Max 15 minutes** per stream |
| **Underlying HTTP Proxy** | `https://LOCATION-aiplatform.googleapis.com/reasoningEngines/v1/projects/PROJECT_NUMBER/locations/LOCATION/reasoningEngines/ID/api/API_PATH` | Passthrough for ADK API server (`/api/run`, `/api/run_sse`, `/api/apps/{app}/trigger/*`) or custom FastAPI routes |
| **Live Bidi Streaming** | `client.aio.live.runtimes.connect(runtime=..., config={"class_method": "bidi_stream_query", ...})` | **Max 10 minutes**; requires `agent_server_mode: AgentServerMode.EXPERIMENTAL` and `api_mode: "bidi_stream"` |
| **Async Query Jobs** | `client.runtimes.{run_query_job, check_query_job, cancel_query_job}` / REST `v1beta1` `:asyncQuery`, `:cancelAsyncQuery` | **Up to 7 days**; requires `reasoningEngine` created **April 22, 2026+** |

### Long-Running Async Query Jobs (Up to 7 Days)

**Prerequisites:** Grant `service-PROJECT_NUMBER@gcp-sa-aiplatform-re.iam.gserviceaccount.com` `roles/storage.objectCreator` on the output GCS bucket (and `roles/storage.objectViewer` on the input bucket if separate; note: upstream `use-an-adk-agent` docs contain a typo naming a non-existent `objectReader` role). Custom containers must set `API_ENDPOINT_PREFIX` (e.g., `"/api/myendpoint"`).

```python
job = client.runtimes.run_query_job(
    name=engine_name,
    config={
        "query": '{"input": {"user_id": "u1", "message": "Audit repository"}}',
        "output_gcs_uri": "gs://MY_BUCKET/jobs/audit-out.json",
    },
)

status = client.runtimes.check_query_job(name=job.name, config={"retrieve_result": True})

client.runtimes.cancel_query_job(
    name=engine_name,
    config={"operation_name": "projects/PROJECT_ID/locations/LOCATION/operations/OPERATION_ID"},
)
```

> **Cancellation Gotcha:** Cancelled jobs complete with error code `1` (`CANCELLED`, `"Cancelled by user."`), which `check_query_job` reports under `FAILED`. Inspect the error code to distinguish intentional cancellation from an execution failure.

---

## 3. Revisions & Traffic Splitting (`v1beta1`)

Every agent creation or update to a **versioned field** produces an immutable revision (`ACTIVE` -> `ARCHIVED`, irreversible).

- **Versioned fields (create a new revision):**
  - `PackageSpec`: `pickleObjectGcsUri`, `dependencyFilesGcsUri`, `requirementsGcsUri`, `pythonVersion`
  - `DeploymentSpec`: `env[]`, `secretEnv[]`, `firstPartyImageOverride`, `agentServerMode`, `pscInterfaceConfig`, `minInstances`, `maxInstances`, `resourceLimits`, `containerConcurrency`
  - `SourceCodeSpec`: `source`, `languageSpec`
  - Top-level `spec`: `classMethods[]`, `agentFramework`, `identityType`, `agentCard[]`
- **Unversioned fields** (e.g., `displayName`, `description`): update across all revisions without minting a new revision.

### Hard Limits & Automatic Garbage Collection

- **Non-adjustable system limits:** **6,000 revisions/project/region** and **950 revisions/agent** (internal limit, not shown on Console Quotas page).
- **Automatic GC (always enabled; runs only during update operations, never in background):**
  - Configured via `revision_garbage_collection_strategy.keep_n_latest.max_revisions` (range `[1, 950]`; default **100** for new agents, **950** for existing agents).
  - Deletes oldest eligible revisions that are `ACTIVE` and receive **0% traffic**. If not enough eligible revisions exist, updates fail with `FAILED_PRECONDITION`.
  - Archived revisions do **not** consume revision quota and remain deletable.

### SDK & REST Operations (`v1beta1`)

```python
import agentplatform

client = agentplatform.Client(project="PROJECT_ID", location="LOCATION", http_options={"api_version": "v1beta1"})
engine_name = "projects/PROJECT_ID/locations/LOCATION/reasoningEngines/RESOURCE_ID"

# List & inspect revisions
revisions = list(client.runtimes.revisions.list(name=engine_name))
rev = client.runtimes.revisions.get(name=f"{engine_name}/runtimeRevisions/REVISION_ID")

# Direct revision query (bypasses traffic rules; requires reasoningEngineRuntimeRevisions.query)
resp = rev.query(input={"message": "canary test"}, config={"class_method": "query"})

# Configure manual traffic split (integers summing to 100; ACTIVE revisions only)
client.runtimes.update(
    name=engine_name,
    config={
        "traffic_config": {
            "trafficSplitManual": {
                "targets": [
                    {"runtimeRevisionName": f"{engine_name}/runtimeRevisions/REV_1", "percent": 90},
                    {"runtimeRevisionName": f"{engine_name}/runtimeRevisions/REV_2", "percent": 10},
                ]
            }
        }
    },
)

# Switch back to always-latest (required before changing agent_gateway_config!)
client.runtimes.update(name=engine_name, config={"traffic_config": {"trafficSplitAlwaysLatest": {}}})

# Manual revision delete (must receive 0% traffic)
client.runtimes.revisions.delete(name=f"{engine_name}/runtimeRevisions/OLD_REV_ID")
```

- **REST traffic patch:** `PATCH https://LOCATION-aiplatform.googleapis.com/v1beta1/projects/PROJECT_ID/locations/LOCATION/reasoningEngines/RESOURCE_ID?update_mask=traffic_config`
- **Agent Gateway + Revisions Rule:** Attaching, changing, or detaching `spec.deployment_spec.agent_gateway_config` **irreversibly archives** every prior revision. The API rejects the change with `FAILED_PRECONDITION` if any manual traffic split is active (even 100% on latest). Always switch to `traffic_split_always_latest` (or clear `traffic_config`) first.

---

## 4. Emergency Stop & Access Revocation Playbook

| Mechanism | Effect on Active Traffic & Identity | Propagation Window |
|---|---|---|
| **1. Delete deployed agent** (`runtimes.delete(force=True)`) | Terminates all containers, cuts active `:streamQuery` streams, permanently invalidates SPIFFE identity | **Immediate** upon operation completion (seconds–few min) |
| **2. Traffic rollback / archive** (`trafficSplitManual` 100% -> known-good) | Shifts root endpoint traffic to safe revision; direct revision calls persist until that revision is deleted/archived | **Seconds to a few minutes** |
| **3. Agent Gateway UAP `DENY`** (active enforcement: remove `iamEnforcementMode` from `metadata` via CLI/Terraform/REST — IAP rejects explicit values other than `"DRY_RUN"`; Console UI shows **Enforce policies**) | Blocks outbound tool/MCP/A2A calls on new checks while keeping containers alive for forensics; does NOT kill open streams | **2–7+ min** globally (`principalSet`/group updates: minutes to hours) |
| **4. IAM deny / role revoke / PAB** | Blocks direct GCP API calls on new requests; does NOT terminate container | **2–7+ min** |

### Incident Response Sequence

1. **Halt execution immediately:** Run `client.runtimes.delete(name=..., force=True)` (full kill switch) OR reroute 100% traffic to a known-good revision (and delete/archive the faulty revision if callers target revision paths directly).
2. **Revoke downstream access:** Add a UAP `DENY` rule on Agent Gateway under active enforcement (remove `iamEnforcementMode` from `metadata` via CLI/Terraform/REST — IAP rejects explicit values other than `"DRY_RUN"`; Console UI shows **Enforce policies**) and revoke IAM roles or apply an IAM Deny / Principal Access Boundary (PAB) policy. Never rely solely on policy updates for active anomalous tool loops because of the 2–7+ min propagation window.
3. **Verify containment:** Query Cloud Logging for `is_agentic=true` and `networkservices.googleapis.com/gateway_requests` denials. After full deletion, prune defunct SPIFFE principals from UAP rules.

```yaml
# Example IAM Deny rule preventing any org agent identity from creating/updating/deleting runtimes
deniedPrincipals:
  - principalSet://agents.global.org-ORGANIZATION_ID.system.id.goog/*
deniedPermissions:
  - aiplatform.googleapis.com/reasoningEngines.create
  - aiplatform.googleapis.com/reasoningEngines.delete
  - aiplatform.googleapis.com/reasoningEngines.update
```

---

## 5. Runtime Contract, Keep-Alive Probe & Container Tuning

### HTTP / NDJSON Runtime Contract

Custom containers MUST bind **`0.0.0.0:8080`** (default `PORT=8080`) and answer `GET /` with `HTTP 200 OK`:

- `api_mode: ""` or `"async"` -> `POST /api/reasoning_engine` (`{"class_method": "...", "input": {...}}`) -> `200 OK` JSON `{"output": ...}`
- `api_mode: "stream"` or `"async_stream"` -> `POST /api/stream_reasoning_engine` -> `200 OK` NDJSON (`{"output": ...}\n`) converted to SSE
- `api_mode: "bidi_stream"` -> `POST /api/bidi_reasoning_engine` (max 10 min)

```python
import inspect, json, os, uvicorn
from fastapi import FastAPI, encoders, responses
from pydantic import BaseModel

app = FastAPI()

class QueryRequest(BaseModel):
    input: dict | None = None
    class_method: str

class AgentServer:
    has_active_background_tasks: bool = False

    def query(self, message: str) -> str:
        return f"Echo: {message}"

    async def stream_query(self, message: str):
        for token in message.split():
            yield {"output": token + " "}

agent = AgentServer()

async def _invoke(fn, payload):
    return await fn(**payload) if inspect.iscoroutinefunction(fn) else fn(**payload)

async def _ndjson(stream):
    async for chunk in stream:
        yield json.dumps(encoders.jsonable_encoder(chunk)) + "\n"

@app.get("/")
def health():
    return {"status": "ok"}

@app.get("/is_busy")
def keep_alive():
    if agent.has_active_background_tasks:
        return responses.JSONResponse(status_code=200, content={"status": "busy"})
    return responses.JSONResponse(status_code=412, content={"status": "idle"})

@app.post("/api/reasoning_engine")
async def unary(req: QueryRequest):
    fn = getattr(agent, req.class_method, None)
    if fn is None:
        return responses.JSONResponse(status_code=400, content={"error": f"Unknown method {req.class_method}"})
    return responses.JSONResponse(content=encoders.jsonable_encoder({"output": await _invoke(fn, req.input or {})}))

@app.post("/api/stream_reasoning_engine")
async def stream(req: QueryRequest):
    fn = getattr(agent, req.class_method, None)
    if fn is None:
        return responses.StreamingResponse(iter([json.dumps({"error": f"Unknown method {req.class_method}"})]), status_code=400, media_type="application/json")
    return responses.StreamingResponse(_ndjson(await _invoke(fn, req.input or {})), media_type="application/json")

if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=int(os.environ.get("PORT", 8080)))
```

### Keep-Alive Probe (`keep_alive_probe`, Preview)

- Default idle scale-down is **15 min (`900s`)**.
- Polls `GET http_get.path` on `http_get.port` (default `8080`, range `[1, 65535]`; **cannot use reserved ports** `15000, 15001, 15006, 15007, 15020, 15021`) every **10s** (1s timeout).
- `2xx` = busy; non-`2xx` (e.g., `412`) or **3 consecutive timeouts** = idle.
- `max_seconds` range: **`[900, 3600]`** (disables CPU throttling — billed continuously while busy).
- **Managed `AdkApp` trap:** Accepts ONLY `"keep_alive_probe": {}` (`max_seconds=3600`); passing custom fields returns `400 FAILED_PRECONDITION`.

### Container Sizing, Scaling & Env Var Controls

| Setting | Default | Range / Production Guidance |
|---|---|---|
| `min_instances` | `1` (`0` in `agents-cli`) | `[0, 75]`. Mitigates cold starts (e.g., 300 concurrent reqs drop from ~4.7s to ~1.4s at `min_instances=10`). |
| `max_instances` | `100` (`10` in `agents-cli`) | `[1, 1000]` (**capped at `[1, 100]`** if VPC-SC or PSC-I is enabled). |
| `resource_limits` | `{"cpu": "4", "memory": "4Gi"}` | `cpu`: `1, 2, 4, 6, 8`; `memory`: `1Gi`..`32Gi`. |
| `container_concurrency` | `9` (`8` in `agents-cli`) | Recommended `2 * cpu + 1` for sync. For **async I/O-bound ADK agents**, each container runs 9 processes (`concurrency / 9` per process): start at a **multiple of 9 (e.g., `36`)** to drop tail queueing spikes (e.g., 60s -> ~7s under 300 concurrent reqs); avoid setting too high to prevent OOM. |
| **Forbidden env vars** | — | `GOOGLE_CLOUD_PROJECT`, `GOOGLE_CLOUD_QUOTA_PROJECT`, `GOOGLE_CLOUD_LOCATION`, `PORT`, `K_SERVICE`, `K_REVISION`, `K_CONFIGURATION`, `GOOGLE_APPLICATION_CREDENTIALS`; avoid `GOOGLE_CLOUD_AGENT_ENGINE*`. |
| **Auto-injected env vars** | — | `GOOGLE_CLOUD_PROJECT`, `GOOGLE_CLOUD_LOCATION`, `GOOGLE_CLOUD_AGENT_ENGINE_ID`. |

---

## 6. Supported Regions, Quotas & QPM Sizing Math

### Supported Locations (23 Single-Region + Multi-Regional `us`/`eu` + `global`)

- **Americas:** `us-east1`, `us-east4`, `us-west1`, `us-central1`, `northamerica-northeast1`, `northamerica-northeast2` *(no Memory Bank)*, `southamerica-east1`
- **Europe & Middle East:** `europe-west1`, `europe-west2`, `europe-west3`, `europe-west4`, `europe-west6`, `europe-west8`, `europe-southwest1`, `me-west1`
- **Asia-Pacific:** `asia-east1`, `asia-east2` *(no Agent Gateway)*, `asia-northeast1`, `asia-northeast3` *(no Agent Gateway)*, `asia-south1`, `asia-southeast1`, `asia-southeast2` *(no Memory Bank, no Agent Gateway)*, `australia-southeast2` *(no Memory Bank)*
- **Multi-regional (`us`, `eu`):** Memory Bank, Sessions, Runtime, Code Execution.
- **`global`:** Memory Bank, Sessions, Google agents (**NOT** `client.runtimes.create`; **NO CMEK**).

### Production Quotas & System Limits (per project per region)

| Resource / Operation | Standard Quota | Express Mode (Free Tier) | Metric (`aiplatform.googleapis.com/...`) |
|---|---|---|---|
| Create/update/delete resources/min (reg. & non-reg.) | **10** | 10 | `[non_regional_]reasoning_engine_service_write_requests` |
| Max Agent Platform resources (reg. & non-reg.) | **100** | 10 | `[non_regional_]reasoning_engine_service_entities` |
| `Query` or `StreamQuery` / min | **90** | 10 | `reasoning_engine_service_query_requests` |
| Concurrent `BidiStreamQuery` / min | **10** | 1 | `reasoning_engine_service_concurrent_query_requests` |
| Create/update/delete sessions / min (reg. & non-reg.) | **100** | 10 | `[non_regional_]session_write_requests` |
| Append session events / min (reg. & non-reg.) | **300** | 30 | `[non_regional_]session_event_append_requests` |
| Create/update/delete memories / min (reg. & non-reg.) | **100** | 10 | `[non_regional_]memory_bank_write_requests` |
| Get/list/retrieve memories / min (reg. & non-reg.) | **300** | 10 | `[non_regional_]memory_bank_read_requests` |
| Sandbox execute / entities / write | **1,000 / 1,000 / 500** | — | `sandbox_environment_{execute_requests,entities,write_requests}` |
| A2A post (`sendMessage`, `cancelTask`) / get (`getTask`, `getCard`) | **60 / 600** | — | `a2a_agent_{post,get}_requests` |
| Max revisions per project/region *(hard limit)* | **6,000** | — | `agent_engine_revisions_per_project_per_region` |
| Max revisions per agent *(internal hard limit)* | **950** | — | `agent_engine_revisions_per_agent` |

### Production QPM Sizing Formula (Prevent `429 Resource Exhausted`)

Define `U` = peak concurrent users, `X` = avg requests/user/min, `Y` = avg session events generated per request (LLM calls + tool calls + tool results + final response).

- **Peak QPM** = `U * X` -> Request `reasoning_engine_service_query_requests` = `Peak QPM * 1.5` (**+50% buffer**)
- **Peak Session Events/min** = `Peak QPM * Y` -> Request `session_event_append_requests` = `Peak Session Events/min * 1.5`
- **Session Writes/min** (`session_write_requests`) <= Query Quota

**Worked Example (`U = 250`, `X = 2`, `Y = 12`):**
- Query quota: `250 * 2 = 500 QPM` -> with 50% buffer = **`750`** (default is `90`!)
- Session event append quota: `500 * 12 = 6,000/min` -> with 50% buffer = **`9,000`** (default is `300`!)
- Session write quota: `<= 750/min` (default is `100`!)

---

## 7. Verification & Troubleshooting

- **Verify active revision & health:** Run `client.runtimes.revisions.list(...)` (`v1beta1`) and confirm at least one revision is `ACTIVE`, then send a `:streamQuery?alt=sse` smoke test.
- **Common errors:**
  - `429 Resource Exhausted`: Check `reasoning_engine_service_query_requests` (default `90/min`) and `session_event_append_requests` (default `300/min`); request Cloud Quotas increase using the `+50%` formula above.
  - `FAILED_PRECONDITION` on revision update: Either manual traffic split blocks `agent_gateway_config` change (switch to `trafficSplitAlwaysLatest`), or all active revisions receive traffic so GC cannot reclaim a slot (shift unused revisions to 0% traffic).
  - `400 FAILED_PRECONDITION` on `keep_alive_probe` with `AdkApp`: Pass empty `"keep_alive_probe": {}` only.
  - High p99 latency under burst on async ADK agent: Raise `min_instances` for baseline traffic and set `container_concurrency` to a multiple of `9` (e.g., `36`).
