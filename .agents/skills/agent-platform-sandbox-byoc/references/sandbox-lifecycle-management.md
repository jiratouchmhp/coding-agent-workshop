# Sandbox, Template & Snapshot Lifecycle Management

Complete reference for provisioning, inspecting, pausing, resuming, checkpointing, branching, and deleting **Scale Sandbox** resources (`SandboxEnvironmentTemplate`, `SandboxEnvironment`, `SandboxEnvironmentSnapshot`) under a parent `ReasoningEngine` instance.

---

## 1. SDK Namespace Reconciliation & Defensive Shim

Official Scale Sandbox documentation is transitioning from `vertexai.Client` (`google-cloud-aiplatform[agent_engines]`) to `agentplatform.Client` (`google-cloud-agentplatform>=2.0.1`, also re-exported by `google-cloud-aiplatform>=1.154.0`).

| Capability | Canonical SDK (`agentplatform`) | Legacy / Parallel SDK (`vertexai`) |
|---|---|---|
| **Install** | `pip install "google-cloud-agentplatform>=2.0.1"` | `pip install "google-cloud-aiplatform[agent_engines]"` (`>=1.144` for BYOC) |
| **Client Init** | `agentplatform.Client(project=..., location=..., http_options={"api_version": "v1beta1"})` | `vertexai.Client(project=..., location=..., http_options={"api_version": "v1beta1"})` |
| **Parent Instance** | `client.runtimes.create()` -> `.api_resource.name` | `client.agent_engines.create()` -> `.api_resource.name` |
| **Sandbox CRUD** | `client.sandboxes.{create, get, list, pause, resume, delete}` | `client.agent_engines.sandboxes.{create, delete}` |
| **Template CRUD** | `client.sandboxes.templates.{create, get, list, delete}` | `client.agent_engines.sandboxes.templates.create` |
| **Snapshot CRUD** | `client.sandboxes.snapshots.{create, get, list, delete}` | Not documented on `vertexai.Client` |
| **Shell Exec** | `client.sandboxes.execute_bash(...)` | Mixed in docs (`shell-sandbox-quickstart` calls `client.sandboxes.execute_bash`) |
| **Code Exec** | `client.sandboxes.execute_code(...)` | Legacy/alt `send_command()` mentioned alongside `execute_code()` |
| **Computer Use CDP** | Not shown on `client.sandboxes` in current docs | `client.agent_engines.sandboxes.generate_browser_ws_headers(...)` |

### Verified Upstream Documentation Bugs to Avoid

1. **`manage-templates.md`:** Imports private `from agentplatform._genai import types`, mixes `client.agent_engines.sandboxes.templates.create` with `client.sandboxes.*`, and hardcodes singular `.../SandboxEnvironmentTemplate/TEMPLATE_ID` (the verified collection name in Cloud Audit Logs is `sandboxEnvironmentTemplates`). **Fix:** Pass plain Python `dict` payloads and always capture `template_op.response.name` or read `tpl.name` from `templates.list()`.
2. **`manage-snapshots.md`:** Omits a closing quote on `agent_instance_name` and assigns a `.../sandboxEnvironments/SANDBOX_ID` path to `snapshot_name` instead of `.../sandboxEnvironmentSnapshots/...`. **Fix:** Always capture `snapshot_op.response.name` or iterate `client.sandboxes.snapshots.list(name=instance_name)`.
3. **`shell-sandbox-quickstart.md`:** Initializes `vertexai.Client` + `client.agent_engines.sandboxes.create()`, then calls `client.sandboxes.execute_bash()`. **Fix:** Use `agentplatform.Client` consistently or resolve namespaces with the compatibility shim below.
4. **`code-execution-quickstart.md`:** Output-decoding snippet calls `output_file_content.b64decode(...)` on a `str` instead of reading `Chunk.data` bytes. **Fix:** Iterate `response.outputs` chunks by `mime_type` and `attributes["file_name"]`.

### Defensive Compatibility Shim (Works with Either Installed Package)

```python
def build_platform_client(project: str, location: str, api_version: str | None = "v1beta1"):
    http_options = {"api_version": api_version} if api_version else None
    try:
        import agentplatform
        return agentplatform.Client(project=project, location=location, http_options=http_options)
    except ImportError:
        import vertexai
        return vertexai.Client(project=project, location=location, http_options=http_options)

def get_runtimes_ns(client):
    return getattr(client, "runtimes", None) or client.agent_engines

def get_sandboxes_ns(client):
    return getattr(client, "sandboxes", None) or client.agent_engines.sandboxes
```

---

## 2. Resource Paths, REST Schema & State Machine

Verified from `reference/rest/v1/projects.locations.reasoningEngines.sandboxEnvironments` and `machine-learning/general/audit-logging`:

| Resource | Verified Resource Path Format | REST Collection |
|---|---|---|
| **Parent Instance** | `projects/{PROJECT}/locations/{LOCATION}/reasoningEngines/{INSTANCE_ID}` | `reasoningEngines` |
| **Sandbox** | `projects/{PROJECT}/locations/{LOCATION}/reasoningEngines/{INSTANCE_ID}/sandboxEnvironments/{SANDBOX_ID}` | `sandboxEnvironments` |
| **Template** | `projects/{PROJECT}/locations/{LOCATION}/reasoningEngines/{INSTANCE_ID}/sandboxEnvironmentTemplates/{TEMPLATE_ID}` | `sandboxEnvironmentTemplates` |
| **Snapshot** | `projects/{PROJECT}/locations/{LOCATION}/reasoningEngines/{INSTANCE_ID}/sandboxEnvironmentSnapshots/{SNAPSHOT_ID}` | `sandboxEnvironmentSnapshots` |

### `SandboxEnvironment` Key Fields & Expiration Union (REST v1)

- `name`, `displayName`, `createTime`, `updateTime` (RFC 3339 timestamps)
- `state`: One of 10 enum values:
  `STATE_UNSPECIFIED`, `STATE_PROVISIONING`, `STATE_RUNNING`, `STATE_DEPROVISIONING`, `STATE_TERMINATED`, `STATE_DELETED`, `STATE_PAUSED`, `STATE_PAUSING`, `STATE_RESUMING`, `STATE_STOPPING`.
- `spec`: Mutually exclusive union of `codeExecutionEnvironment` (`codeLanguage`: `LANGUAGE_PYTHON` | `LANGUAGE_JAVASCRIPT`, `machineConfig`: `MACHINE_CONFIG_UNSPECIFIED` [2 vCPU / 1.5 GiB] | `MACHINE_CONFIG_VCPU4_RAM4GIB` [4 vCPU / 4 GiB]) or `shellEnvironment` (`{}`).
- `sandboxEnvironmentTemplate`: Backing template resource name.
- `sandboxEnvironmentSnapshot` / `latestSandboxEnvironmentSnapshot`: Source snapshot (on restore) / latest snapshot taken (output-only).
- `owner`: Optional owner string; **a sandbox can only be restored from a snapshot belonging to the same `owner`** (defaults to default owner if unset).
- `connectionInfo` (output-only): `loadBalancerIp`, `loadBalancerHostname`, `sandboxInternalIp`, `routingToken`, `serviceAttachment` (populated only when PSC-E private ingress is enabled on the template).
- `expiration` (mutually exclusive union): `ttl` (input-only protobuf duration string ending in `s`, e.g., `"3600s"`) vs `expireTime` (output-only RFC 3339 timestamp always returned). Note: `computer-use-quickstart` notes a default 2-hour lifetime when omitted, while REST v1 docs warn that omitting expiration can prevent automatic deletion — **always set an explicit `ttl` on every `create()` call** for deterministic billing control.

---

## 3. Parent Instance & Template Lifecycle (5 Operations)

| Operation | SDK Method | Audit RPC (`aiplatform.googleapis.com`) | Rules & Constraints |
|---|---|---|---|
| **Create** | `client.sandboxes.templates.create(name=..., display_name=..., config=...)` | `CreateSandboxEnvironmentTemplate` (`ADMIN_WRITE`) | Triggers pre-warmed pool creation. **Reuse templates**: omitting `sandbox_environment_template` on `sandboxes.create()` leaks a new default template every time, and deleting a sandbox does **not** delete its template. |
| **Get** | `client.sandboxes.templates.get(name=template_name)` | `GetSandboxEnvironmentTemplate` (`ADMIN_READ`) | Also readable from a sandbox via `sandbox.sandbox_environment_template`. |
| **List** | `client.sandboxes.templates.list(name=instance_name)` | `ListSandboxEnvironmentTemplates` (`ADMIN_READ`) | Iterate `.sandbox_environment_templates`. |
| **Update** | **Delete + recreate** *(no SDK update method documented)* | `UpdateSandboxEnvironmentTemplate` exists in audit table, not exposed in SDK docs | Delete existing template and create a new one with updated image/resources/egress. |
| **Delete** | `client.sandboxes.templates.delete(name=template_name)` | `DeleteSandboxEnvironmentTemplate` (`ADMIN_WRITE`) | **Fails** if a warm pool is actively being created or sandboxes are currently being created from it. |

```python
import agentplatform

client = agentplatform.Client(
    project="PROJECT_ID",
    location="us-central1",
    http_options={"api_version": "v1beta1"},
)

# Parent instance (takes seconds; no agent deployment needed)
instance_name = client.runtimes.create().api_resource.name

# Create reusable default Shell or Computer Use template (plain dict avoids private imports)
shell_tpl_op = client.sandboxes.templates.create(
    name=instance_name,
    display_name="reusable-shell-template",
    config={
        "default_container_environment": {
            "default_container_category": "DEFAULT_CONTAINER_CATEGORY_SHELL_SANDBOX",
            # Or "DEFAULT_CONTAINER_CATEGORY_COMPUTER_USE"
        },
        "egress_control_config": {"internet_access": False},
    },
)
template_name = shell_tpl_op.response.name

# List & Get templates
for tpl in client.sandboxes.templates.list(name=instance_name).sandbox_environment_templates:
    print(tpl.name)
details = client.sandboxes.templates.get(name=template_name)

# Update = Delete + Recreate
client.sandboxes.templates.delete(name=template_name)
```

---

## 4. `SandboxEnvironment` Lifecycle (All 7 Operations)

To change a sandbox's spec/template configuration, you must **delete and recreate** it — in-place reconfiguration is not supported.

| Operation | SDK Method | Audit RPC & Category | Operational Behavior |
|---|---|---|---|
| **Create** | `client.sandboxes.create(name=..., spec=..., config=...)` | `CreateSandboxEnvironment` (`ADMIN_WRITE`) | Must pass at least one of `spec`, `config.sandbox_environment_template`, or `config.sandbox_environment_snapshot`. Pass `"wait_for_completion": True` to block until `STATE_RUNNING`. |
| **Get** | `client.sandboxes.get(name=sandbox_name)` | `GetSandboxEnvironment` (`ADMIN_READ`) | Inspect live `state`, `expire_time`, `sandbox_environment_template`, `connection_info.service_attachment`. |
| **List** | `client.sandboxes.list(name=instance_name)` | `ListSandboxEnvironments` (`ADMIN_READ`) | Returns iterable of `SandboxEnvironment` resources. |
| **Pause** | `client.sandboxes.pause(name=sandbox_name, config={"wait_for_completion": True})` | `PauseSandboxEnvironment` (`ADMIN_WRITE`) | Releases compute (significantly lower cost); retains sandbox ID, PSC endpoint, connection metadata, and filesystem state. Transitions to `STATE_PAUSED`; data-plane requests error until resumed. |
| **Resume** | `client.sandboxes.resume(name=sandbox_name, config={"wait_for_completion": True})` | `ResumeSandboxEnvironment` (`ADMIN_WRITE`) | Restores compute in seconds with identical ID, PSC attachment, and disk state (`STATE_RUNNING`). **Only valid in `STATE_PAUSED`** — calling on a running sandbox returns `FAILED_PRECONDITION`. |
| **Snapshot** | `client.sandboxes.snapshots.create(source_sandbox_environment_name=..., config=...)` | `SnapshotSandboxEnvironment` (`ADMIN_WRITE`) | Checkpoints libraries, disk, and memory state to managed GCS bucket (inherits parent CMEK). **Not supported on Code Execution sandboxes.** |
| **Delete** | `client.sandboxes.delete(name=sandbox_name)` | `DeleteSandboxEnvironment` (`ADMIN_WRITE`) | Stops billing immediately; does **not** delete backing template. |

### Verified Python Snippets for All Creation Modes & Lifecycle Calls

```python
# 1a. Create Code Execution Sandbox
code_op = client.sandboxes.create(
    name=instance_name,
    spec={
        "code_execution_environment": {
            "code_language": "LANGUAGE_PYTHON",  # or "LANGUAGE_JAVASCRIPT"
            "machine_config": "MACHINE_CONFIG_VCPU4_RAM4GIB",  # default: 2 vCPU / 1.5 GB RAM
        }
    },
    config={"display_name": "code-sandbox", "ttl": "3600s"},
)
code_sandbox_name = code_op.response.name

# 1b. Create Shell Sandbox (reusing template; typically reaches STATE_RUNNING in ~20s)
shell_op = client.sandboxes.create(
    name=instance_name,
    spec={"shell_environment": {}},
    config={
        "display_name": "shell-sandbox",
        "sandbox_environment_template": template_name,
        "ttl": "3600s",
        "wait_for_completion": True,
    },
)
sandbox_name = shell_op.response.name

# 2. List & Get
for sb in client.sandboxes.list(name=instance_name):
    print(sb.name, sb.state)
sb_details = client.sandboxes.get(name=sandbox_name)

# 3. Pause & Resume (check state first to avoid FAILED_PRECONDITION)
pause_op = client.sandboxes.pause(name=sandbox_name, config={"wait_for_completion": True})
assert str(pause_op.response.state).endswith("STATE_PAUSED")

resume_op = client.sandboxes.resume(name=sandbox_name, config={"wait_for_completion": True})
assert str(resume_op.response.state).endswith("STATE_RUNNING")

# 4. Delete
client.sandboxes.delete(name=sandbox_name)
```

### When to Pause vs. Snapshot vs. Delete

- **Pause:** Idle single-session sandbox you plan to return to with the **same sandbox ID and PSC-E service attachment** (lower cost than running; resumes in seconds).
- **Snapshot:** Checkpointing before risky refactors or **branching** multiple parallel sandboxes from one warmed-up state (install deps once -> snapshot -> branch N sandboxes in seconds).
- **Delete:** Work complete — stops sandbox billing immediately (remember to garbage-collect unused templates and snapshots separately).

---

## 5. `SandboxEnvironmentSnapshot` Lifecycle (5 Operations)

> **Unsupported Type:** Snapshots are **not supported** for Code Execution sandboxes.

### Verified Restore Compatibility Constraints

Restoring a snapshot into a new sandbox **fails** if any of the following differ between source and target:
1. **Server CPU architecture** (for example, `amd64` vs. `arm64`).
2. **Sandbox runtime version** (for example, after an underlying GKE cluster upgrade).
3. **Container `image_uri`** (always pin immutable image tags/digests).
4. **Sandbox `owner` field** (per REST v1 spec, a sandbox can only restore from a snapshot belonging to the same `owner`).

```python
# 1. Create snapshot (persists installed packages, disk changes & memory state for ttl)
snap_op = client.sandboxes.snapshots.create(
    source_sandbox_environment_name=sandbox_name,
    config={"display_name": "pre-refactor-checkpoint", "ttl": "3600s"},
)
print("Snapshot operation:", snap_op.name)

# 2. List & capture canonical snapshot_name dynamically (never hardcode sandbox path)
snaps = client.sandboxes.snapshots.list(name=instance_name).sandbox_environment_snapshots
snapshot_name = snaps[0].name

# 3. Get snapshot metadata
snap_details = client.sandboxes.snapshots.get(name=snapshot_name)

# 4. Restore / Branch one or more new sandboxes from the snapshot (restores in seconds)
branch_op = client.sandboxes.create(
    name=instance_name,
    config={
        "display_name": "branched-sandbox-a",
        "sandbox_environment_snapshot": snapshot_name,
        "ttl": "3600s",
        "wait_for_completion": True,
    },
)
branched_sandbox = branch_op.response

# 5. Delete snapshot before TTL expiration
client.sandboxes.snapshots.delete(name=snapshot_name)
```

---

## 6. Verified Latencies, TTLs & Quotas

| Dimension | Verified Limit / Behavior |
|---|---|
| **Cold start (unprovisioned)** | Up to **2 minutes** |
| **Warm start / resume / snapshot restore** | **Seconds** (reusing templates enables pre-warmed pools) |
| **Shell sandbox boot** | Typically **~20 seconds** to `STATE_RUNNING` |
| **Code Execution create + execute** | **Under 1 second** (per-call timeout: **300 seconds**) |
| **TTL — BYOC / Custom Container** | Up to **7 days** (`config.ttl`) |
| **TTL — Code Execution** | Up to **14 days** (`config.ttl`; **every `execute_code()` resets TTL**) |
| **TTL — Default (Computer Use quickstart)** | **2 hours** if `ttl` omitted (always set explicitly) |
| **Quota: Code Exec execute req/min** | **1,000** / project / region (`aiplatform.googleapis.com/sandbox_environment_execute_requests`) |
| **Quota: Code Exec entities** | **1,000** / project / region (`aiplatform.googleapis.com/sandbox_environment_entities`) |
| **Quota: Code Exec write req/min** | **500** / project / region (`aiplatform.googleapis.com/sandbox_environment_write_requests`) |
| **Quota: Parent ReasoningEngine writes/entities** | **10/min** write (`reasoning_engine_service_write_requests`); **100** max entities (`reasoning_engine_service_entities`) — **10** entities in Express Mode |

---

## 7. Verification Steps

Run this end-to-end verification sequence after implementing lifecycle automation:
1. Create a single reusable template and assert `templates.list()` returns its canonical `.../sandboxEnvironmentTemplates/...` name.
2. Create a sandbox referencing `sandbox_environment_template` with `ttl="1800s"` and verify `get()` reports `STATE_RUNNING` and non-empty `expire_time`.
3. Call `pause(wait_for_completion=True)` -> verify `STATE_PAUSED` -> verify calling `resume()` succeeds (`STATE_RUNNING`) -> verify a second `resume()` raises `FAILED_PRECONDITION` (or is guarded by checking `state`).
4. Create a snapshot, branch a second sandbox from it, verify state carried over, then delete both sandboxes, the snapshot, and the template; re-run `list()` on all three collections to confirm zero leaked billable resources.
