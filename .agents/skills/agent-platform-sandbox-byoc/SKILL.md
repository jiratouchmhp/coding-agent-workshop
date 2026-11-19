---
name: agent-platform-sandbox-byoc
description: >-
  Builds, manages, executes, and secures Agent Platform Scale Sandboxes (BYOC,
  Shell, Code Execution, Computer Use). Use when building non-root BYOC images
  and gcp-sa-vertex-sandbox AR IAM, managing Sandbox/Template/Snapshot
  lifecycles (create/get/list/pause/resume/snapshot/restore/delete), running
  Shell execute_bash, BYOC /exec (generate_access_token/send_command), Code
  Execution execute_code, ADK AgentEngineSandboxCodeExecutor, Managed Sandbox
  BaseEnvironment adapter, or Computer Use CDP, or configuring gVisor
  isolation, PSC-I network_attachment, Cloud NGFW FQDN allowlists, Secure Web
  Proxy, DNS peering, PSC-E ingress, VPC-SC, CMEK, TTLs, or audit logs. Don't
  use for GKE Sandbox (agent-runtime-vs-gke-architecture),
  Runtime/Sessions/Memory (agent-platform-runtime-and-state,
  google-agents-cli-deploy), ADK builds (adk-coding-agent-build,
  google-agents-cli-adk-code), registries
  (agent-platform-governance-and-registries), evals
  (agent-platform-optimize-and-eval), or Managed Agents API sandboxes.
---

# Gemini Enterprise Agent Platform Scale Sandboxes & BYOC

Author, provision, execute, and secure **Managed Sandboxes** (`SandboxEnvironment`, `SandboxEnvironmentTemplate`, `SandboxEnvironmentSnapshot`) under a parent `ReasoningEngine` instance on Google Cloud's Gemini Enterprise Agent Platform.

> **Architecture Boundary:** Agent Runtime (`ReasoningEngine`) runs your trusted orchestration code with Agent Identity / SA credentials. A **Scale Sandbox** is an auxiliary, **gVisor-isolated container** in a Google-managed tenant project spawned to execute untrusted code, shell commands, browsers, or BYOC custom containers. Your agent does **not** need to be deployed on Agent Runtime to use Scale Sandboxes, but you must create a parent `ReasoningEngine` instance first (takes seconds without deploying code).

---

## Quick Decision Tree

### 1. Is Scale Sandbox the Right Surface?

| Need | Use This Surface | Skill / Target |
|---|---|---|
| Managed gVisor container for untrusted code, shell, browser, or BYOC image (agent runs anywhere) | **Scale Sandboxes** (`SandboxEnvironment`) | **This skill** |
| Self-managed Kubernetes CRDs (`Sandbox`, `SandboxWarmPool`, `PodSnapshot`, `sandbox-router` port `8888`) | **GKE Agent Sandbox** | `agent-runtime-vs-gke-architecture` |
| Deploy trusted agent service via `agents-cli deploy` or Terraform `google_vertex_ai_reasoning_engine` | **Agent Runtime** | `agent-platform-runtime-and-state` / `google-agents-cli-deploy` |
| Local dev subprocess execution (`LocalEnvironment`, `ExecuteBashTool`) | **ADK Local Tools** | `adk-coding-agent-build` / `google-agents-cli-adk-code` |
| Pre-GA REST-first harness with built-in domain `allowlist` and `/.agent/skills/` mounting | **Managed Agents API Sandbox** *(Pre-GA, non-prod)* | Distinct API — do not mix with `client.sandboxes.*` |

### 2. Which Scale Sandbox Type?

| Task | Sandbox Type | Execution Entrypoint | Network Default | Snapshots | Max TTL |
|---|---|---|---|---|---|
| Fast stateless/stateful Python or JS data analysis (<=100 MB I/O, preinstalled libs, <1s) | **Code Execution** | `execute_code()` or ADK `AgentEngineSandboxCodeExecutor` | **None** (zero egress) | **No** | **14 days** (`execute_code` resets TTL) |
| Untrusted Linux shell commands as `appuser` under `/workspace` (~20s boot) | **Shell Sandbox** | `execute_bash()` -> container `/exec` | Off (`internet_access: False`) | **Yes** | **7 days** (configurable `ttl`) |
| Custom languages, compilers, SAST/lint tools, or custom data-plane HTTP/WS endpoints | **Custom Container (BYOC)** | Declared TCP `ports` + runner (`/exec`, WS, PTY) | Off (`internet_access: False`) | **Yes** | **7 days** (configurable `ttl`) |
| Browser automation (clicks, screenshots, Playwright CDP, live VNC/noVNC) | **Computer Use** | `send_command` (`/cdp`, `/tabs`) or `generate_browser_ws_headers` | Off (`internet_access: False`) | **Yes** | Configurable `ttl` (default 2h) |

---

## SDK Setup & Service Agent Prerequisites

- **Install:** `pip install "google-cloud-agentplatform>=2.0.1"` (canonical Agent Platform SDK). Add `google-adk[gcp]>=2.0.0` for `AgentEngineSandboxCodeExecutor` and `EnvironmentToolset`/`BaseEnvironment` (ADK Python 2.0+).
- **API Version:** Always pass `http_options={"api_version": "v1beta1"}` when creating BYOC `SandboxEnvironmentTemplate` resources, configuring PSC-I/PSC-E networking, or enabling CMEK on parent instances.
- **Payloads:** Pass plain Python `dict`s for `spec` and `config` — never import private `agentplatform._genai` modules.
- **Caller IAM:** `roles/aiplatform.user` (grants `aiplatform.sandboxEnvironments.execute` and full lifecycle). Add `roles/iam.serviceAccountTokenCreator` on the signing SA when calling `generate_access_token()` or `generate_browser_ws_headers()`.

### Three Distinct Service Agents — Never Confuse Them

| Service Agent | Email | Required Role & Purpose |
|---|---|---|
| **Agent Sandbox** | `service-PROJECT_NUMBER@gcp-sa-vertex-sandbox.iam.gserviceaccount.com` | `roles/artifactregistry.reader` on the Artifact Registry repo hosting **BYOC sandbox** images. |
| **Agent Runtime** | `service-PROJECT_NUMBER@gcp-sa-aiplatform-re.iam.gserviceaccount.com` | `roles/cloudkms.cryptoKeyEncrypterDecrypter` on Cloud KMS key for parent CMEK (and pulling Agent Runtime images). |
| **Agent Platform** | `service-PROJECT_NUMBER@gcp-sa-aiplatform.iam.gserviceaccount.com` | `roles/compute.networkUser` on `NETWORK_PROJECT_ID` when PSC-I `network_attachment` lives in a Shared VPC host project. |

---

## Critical Gotchas ("Do This, Not That")

1. **Grant AR pull IAM to `gcp-sa-vertex-sandbox`, NOT `gcp-sa-aiplatform-re`.**
   *Why:* Sandbox image pulls use the dedicated Agent Sandbox service agent (`service-PROJECT_NUMBER@gcp-sa-vertex-sandbox.iam.gserviceaccount.com`). Granting only the Runtime service agent causes BYOC provisioning failures.
2. **Use `execute_bash()` on Shell sandboxes — NEVER `send_command()` or `execute_code()`.**
   *Why:* Shell sandboxes expose `/exec` and reject Code Execution's Python payloads. Also, every `execute_bash()` call spawns a **fresh stateless shell** as `appuser` (no `sudo`) in `/workspace`: chain `cd /workspace/app && pytest -q` in one call or persist state to files under `/workspace`.
3. **Reuse `SandboxEnvironmentTemplate` resources — NEVER omit `sandbox_environment_template` in loops.**
   *Why:* Omitting it creates a brand-new orphan template on every `sandboxes.create()`, and deleting a sandbox does **not** delete its backing template. Templates have no documented SDK in-place update: **delete and recreate** (deletion fails while a warm pool or sandbox creation is active).
4. **Configure PSC-I (`network_attachment`) + Cloud NGFW or Secure Web Proxy for domain allowlisting — NEVER look for a template `allowlist` field.**
   *Why:* Scale Sandboxes have **no built-in domain allowlist** (unlike Pre-GA Managed Agents API). Setting `internet_access: True` without `network_attachment` allows unrestricted `0.0.0.0/0` public egress (blocking only RFC 1918 and `169.254.0.0/16`).
5. **Run authenticated Google Cloud API calls in the parent agent — NEVER expect ADC or `169.254.169.254` inside a sandbox.**
   *Why:* In-sandbox code runs under tenant identity `sandbox-untrusted` with **zero IAM roles**, no parent Agent Identity, and no Compute Engine metadata server. Pass only required input data into the sandbox, or inject short-lived narrowly scoped per-call tokens.
6. **Always capture template and snapshot names from `operation.response.name` or `.list()` — NEVER copy buggy upstream doc snippets verbatim.**
   *Why:* Verified upstream doc bugs exist in four places: (a) `manage-templates.md` hardcodes singular `.../SandboxEnvironmentTemplate/...` instead of `sandboxEnvironmentTemplates` and imports private `agentplatform._genai`; (b) `manage-snapshots.md` has a missing quote and passes a `sandboxEnvironments` path as `snapshot_name`; (c) `code-execution-quickstart.md` calls `.b64decode()` on a `str` instead of reading `Chunk.data` bytes; (d) `shell-sandbox-quickstart.md` mixes `client.agent_engines.sandboxes` and `client.sandboxes`.
7. **In custom ADK `BaseEnvironment` (`EnvironmentScope.SESSION`), NEVER short-circuit `initialize()` on `if self._is_initialized: return`.**
   *Why:* ADK's `EnvironmentToolset` reuses one environment instance across sessions and calls `initialize(ctx=ctx)` before every tool call. Always check `ctx.state` per session and declare `*, ctx: Context | None = None` on `initialize`, `execute`, `read_file`, and `write_file`.
8. **Log sandbox command outputs from your parent agent — NEVER assume `reasoning_engine_stdout` captures sandbox logs.**
   *Why:* Automatic Cloud Logging applies only to the parent `ReasoningEngine`, Cloud Audit Logs does not log in-container child processes or WebSocket/CDP/PTY frames, and VPC-SC omits audit request/response payloads. Enable `ADMIN_READ` + `DATA_WRITE` audit logs and emit structured logs in the parent agent.
9. **Always set `config.ttl` and respect lifecycle preconditions.**
   *Why:* Sandboxes bill while existing; `config.ttl` guarantees crash-safe auto-cleanup (max 7d BYOC, 14d Code Exec). `resume()` fails with `FAILED_PRECONDITION` unless state is `STATE_PAUSED`; snapshots are unsupported on Code Execution and fail to restore across CPU arch, runtime version, `image_uri`, or `owner` mismatches; CMEK requires a **single-region** KMS key set **immutably** at parent `ReasoningEngine` creation.

---

## Quick-Start Command & Code Patterns

### 1. Grant BYOC Artifact Registry Pull IAM (Run Once per Repo)

```bash
gcloud artifacts repositories add-iam-policy-binding REPO_NAME \
    --location=REGION \
    --member="serviceAccount:service-PROJECT_NUMBER@gcp-sa-vertex-sandbox.iam.gserviceaccount.com" \
    --role="roles/artifactregistry.reader"
```

### 2. Provision Parent Instance, BYOC Template & Sandbox (`v1beta1`)

```python
import agentplatform

client = agentplatform.Client(
    project="PROJECT_ID",
    location="us-central1",
    http_options={"api_version": "v1beta1"},
)
instance_name = client.runtimes.create().api_resource.name

tpl_op = client.sandboxes.templates.create(
    name=instance_name,
    display_name="byoc-coding-template",
    config={
        "custom_container_environment": {
            "custom_container_spec": {
                "image_uri": "us-central1-docker.pkg.dev/PROJECT_ID/REPO/coding-sandbox:v1"
            },
            "resources": {
                "requests": {"cpu": "1", "memory": "1Gi"},
                "limits": {"cpu": "2", "memory": "2Gi"},
            },
            "ports": [{"port": 8080, "protocol": "TCP"}],
        },
        "egress_control_config": {"internet_access": False},
    },
)
template_name = tpl_op.response.name

sb_op = client.sandboxes.create(
    name=instance_name,
    config={
        "sandbox_environment_template": template_name,
        "display_name": "coding-session-1",
        "ttl": "3600s",
        "wait_for_completion": True,
    },
)
sandbox_name = sb_op.response.name
```

### 3. Execute Shell Commands, Pause/Resume, Snapshot & Clean Up

```python
# Shell sandbox execution (uses caller ADC/IAM; no JWT needed)
res = client.sandboxes.execute_bash(
    name=sandbox_name,
    command="cd /workspace && pytest -q",
    cwd="/workspace",
    timeout=120,
)
assert res["returncode"] == 0, res["stderr"]

# Lifecycle: Pause -> Resume -> Snapshot -> Branch -> Delete
client.sandboxes.pause(name=sandbox_name, config={"wait_for_completion": True})
client.sandboxes.resume(name=sandbox_name, config={"wait_for_completion": True})
snap_op = client.sandboxes.snapshots.create(
    source_sandbox_environment_name=sandbox_name,
    config={"display_name": "checkpoint-1", "ttl": "3600s"},
)
client.sandboxes.delete(name=sandbox_name)
```

### 4. Attach Managed Code Execution to an ADK Agent (`google-adk>=2.0.0`)

```python
from google.adk.agents.llm_agent import Agent
from google.adk.code_executors.agent_engine_sandbox_code_executor import AgentEngineSandboxCodeExecutor

# Use explicit versioned regional model ID (never `gemini-flash-latest` on us-central1)
root_agent = Agent(
    model="gemini-2.5-flash", name="code_exec_agent",
    code_executor=AgentEngineSandboxCodeExecutor(agent_engine_resource_name="projects/PROJECT_ID/locations/us-central1/reasoningEngines/INSTANCE_ID"),
)  # Pre-created sandbox_resource_name, custom BaseEnvironment & CDP -> references/sandbox-execution-and-adk.md
```

---

## Modular References

Load only the reference file matching the current subtask:

| Reference | When to Read |
|---|---|
| [references/custom-containers-byoc.md](references/custom-containers-byoc.md) | Building non-root Linux BYOC Dockerfiles, `/health` & `/exec` runner contract, Artifact Registry & `gcp-sa-vertex-sandbox` IAM (CLI + Terraform), `custom_container_environment` templates, and container verification. |
| [references/sandbox-lifecycle-management.md](references/sandbox-lifecycle-management.md) | Full Template/Sandbox/Snapshot CRUD (`create`, `get`, `list`, `pause`, `resume`, `snapshot`, `restore`, `delete`), `agentplatform` vs `vertexai` SDK shim, REST state enum & schema, quotas/latencies, and doc-bug workarounds. |
| [references/sandbox-execution-and-adk.md](references/sandbox-execution-and-adk.md) | Shell `execute_bash`, BYOC `/exec` + `generate_access_token`/`send_command`, Code Execution `execute_code` safe `Chunk` parsing & library inventory, ADK `AgentEngineSandboxCodeExecutor`, Computer Use CDP/Playwright, and custom ADK `BaseEnvironment`. |
| [references/security-networking-egress.md](references/security-networking-egress.md) | gVisor & `sandbox-untrusted` boundaries, PSC-I `network_attachment`, Cloud NAT, Cloud NGFW FQDN allowlists, Secure Web Proxy, Cloud DNS peering, Shared VPC IAM, PSC-E private ingress, VPC-SC, single-region CMEK, and Audit Logging / observability gaps. |
| [references/maintenance.md](references/maintenance.md) | Upstream documentation provenance, `.md.txt`/`.md` refresh URLs, known upstream doc bugs watchlist, and section-by-section maintenance checklist. |

---

## Maintenance

Last verified against official Gemini Enterprise Agent Platform and Google ADK documentation on **2026-11-19**. See [references/maintenance.md](references/maintenance.md) for canonical refresh endpoints, upstream doc-bug tracking, and update procedures.
