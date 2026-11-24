# Antigravity (`agy`) Headless CLI Harness & Outer ADK Factory Reference

Authoritative guide for integrating the **Antigravity (`agy`) Headless CLI** into **Google ADK Python 2.0+** coding agents (`AGENT_ARCHITECTURE=agy_harness`), running seamlessly across developer laptops, CI/CD, **Agent Runtime** (using Custom SA ADC `AGY_ADC_AUTH=true`), and **BYOC Managed Sandboxes** (**zero local Docker required**).

---

## 1. "10% Model / 90% Harness" & Outer ADK Factory Pattern

Frontier models (**Gemini 4 Hydrogen** `gemini-4-hydrogen` and **Gemini 4 Neon** `gemini-4-neon` on `MODEL_LOCATION=global`) perform best inside a battle-tested coding harness, while enterprise deployments require a deterministic **ADK 2.0 outer control plane** for planning, independent test/lint verification, bounded retries, OTel tracing, and HITL sign-off:

1. **Spec / Planner Node (`gemini-4-neon`, `global`):** Produces concrete file targets and acceptance criteria before edits begin.
2. **Inner Coding Harness `@node` (`AgyHeadlessHarness`):** Delegates implementation to `agy -p ... --output-format stream-json`, parses NDJSON tool/token events into OpenTelemetry spans, and captures `conversation_id`.
3. **Independent Deterministic Verification Gates:** Runs `pytest` and `ruff` concurrently via `asyncio.gather(..., use_sub_branch=True)` — **never trusting the coding harness to grade itself**.
4. **Bounded Fix Loop (`MAX_FIX_ROUNDS`):** Feeds exact failure output back into `agy` using `--conversation <conversation_id>`, applying bounded retry + model fallback (`gemini-4-neon` -> `gemini-4-hydrogen`) strictly on exit code `3` (`AGENT_ERROR`).
5. **Independent Reviewer & Optional HITL Gate:** Runs a `gemini-4-neon` `code_reviewer` (`output_schema=CodeReviewReport`) plus optional `RequestInput` approval pause.

---

## 2. Installing `agy` (Static Go Binary — Zero Local Docker)

`agy` distributes as a static native Go binary supporting custom `--dir` paths:

```bash
# Developer laptop / Cloud Workstations (safe download-then-execute):
curl -fsSL https://antigravity.google/cli/install.sh -o /tmp/agy_install.sh \
  && bash /tmp/agy_install.sh \
  && rm -f /tmp/agy_install.sh

# Container / CI deterministic install (used in Agent Runtime & BYOC Sandbox Dockerfiles):
curl -fsSL https://antigravity.google/cli/install.sh -o /tmp/agy_install.sh \
  && bash /tmp/agy_install.sh --dir /usr/local/bin \
  && rm -f /tmp/agy_install.sh \
  && chmod 0755 /usr/local/bin/agy
```

> **Install Script Log Note:** When `agy_install.sh --dir /usr/local/bin` runs as `root` during a container build, it places the working static binary at `/usr/local/bin/agy` (`0755`, executable by non-root `appuser`). Its internal `agy install` step may also log a secondary message referencing `/root/.local/bin/agy` (inaccessible to `appuser`) — this is harmless because `/usr/local/bin/agy` is on `PATH` and verified by `which agy && agy --version`.

In both Agent Runtime (`Dockerfile`) and BYOC Sandbox (`sandbox_image/Dockerfile`), gate installation behind `ARG INSTALL_AGY_CLI=true` and build remotely via Cloud Build (`gcloud builds submit --region=asia-southeast3`) so attendees need **zero local Docker**.

---

## 3. Exact Verified Headless CLI Flags & Environment

```bash
AGY_ADC_AUTH=true \
AGY_CLI_DISABLE_AUTO_UPDATE=true \
GOOGLE_CLOUD_PROJECT="${AGY_PROJECT_ID:-${GOOGLE_CLOUD_PROJECT}}" \
GOOGLE_CLOUD_QUOTA_PROJECT="${AGY_PROJECT_ID:-${GOOGLE_CLOUD_PROJECT}}" \
GOOGLE_CLOUD_LOCATION="global" \
agy -p "<prompt>" \
  --output-format stream-json \
  --model gemini-4-hydrogen \
  --effort medium \
  --print-timeout 5m \
  --sandbox
```

> **CRITICAL — Agent Runtime Numeric `GOOGLE_CLOUD_PROJECT` Trap (Live-Verified on `agy 1.5.15`):**
> Agent Runtime auto-injects the **numeric project number** (e.g., `123456789012`) into `GOOGLE_CLOUD_PROJECT` and `GOOGLE_CLOUD_QUOTA_PROJECT`, and its GCE metadata endpoint (`/project/project-id`) returns Google's internal tenant project (`<tenant>-tp`, which fails with HTTP 403 `aiplatform.endpoints.predict`). Real **`agy 1.5.15` rejects numeric project IDs with exit code `3`** (`invalid project ID: "<project-number>"`).
>
> **Verified Fix:** Inject a non-reserved env var **`AGY_PROJECT_ID = var.project_id`** (the customer's string GCP project ID, e.g., `my-gcp-project`) in `deployment_spec.env` (Terraform / deploy flags). Inside `build_local_agy_env()`, prefer non-numeric `AGY_PROJECT_ID` when setting both `GOOGLE_CLOUD_PROJECT` and `GOOGLE_CLOUD_QUOTA_PROJECT` (alongside `GOOGLE_CLOUD_LOCATION="global"` and `AGY_ADC_AUTH="true"`) on the `agy` subprocess environment. With this override, both `agy -p ... --dangerously-skip-permissions` and `agy -p ... --sandbox` succeed (`exit 0`) directly under the Agent Runtime Custom SA ADC!

| Flag | Verified Behavior |
|---|---|
| `-p "<prompt>"` | Non-interactive headless print mode. |
| `--output-format stream-json` | Emits NDJSON events (`conversation_id`, tool invocations, text deltas, token usage, final response); `json` and `text` also supported. |
| `--model <id>` | `gemini-4-hydrogen` (fast coding), `gemini-4-neon` (deep reasoning), or `gemini-4-argon` (regional `asia-southeast1`). |
| `--effort <level>` | Maps directly from Gemini 4 `THINKING_LEVEL`: `low`, `medium`, `high`, `xhigh` (never `minimal`). |
| `--print-timeout <duration>` | Hard wall-clock timeout (e.g., `5m`, `90s`) preventing stalled headless runs. |
| `--conversation <id>` | Continues the exact prior harness conversation across outer ADK fix rounds. |
| `--sandbox` | Enables terminal sandboxing for local / CI / trusted Agent Runtime runs. |
| `--dangerously-skip-permissions` | Unattended auto-approve **strictly inside** an isolated gVisor Managed Sandbox, Agent Runtime container, or ephemeral CI container. |
| `--json-schema <schema_json>` | Optional structured JSON schema constraint for machine-readable output (accepts JSON string or serialized `dict`). |

---

## 4. NDJSON `stream-json` Event Schema & `AGY_ERROR` Format

`parse_agy_stream_json()` **must** support **both** real `agy 1.5.15` nested JSON envelopes and the workshop's flat dry-run NDJSON format (plus plain-text fallback if a non-JSON line is emitted). Ignoring nested envelopes causes `parse_agy_stream_json()` to return empty `response_text=""` and `token_usage={}` on live `agy 1.5.15` output!

### 4.1 Real `agy 1.5.15` Nested Envelopes (Live-Verified)

```json
{"event":"init","conversation_id":"conv-abc123","init":{"model":"gemini-4-hydrogen"}}
{"event":"step_update","step_update":{"step_type":"tool_use","id":"call-1","name":"ReadFile","input":{"path":"app.py"}}}
{"event":"step_update","step_update":{"step_type":"agent_response","text_delta":"AGY_LIVE_OK\n","usage":{"input_tokens":8100,"output_tokens":12,"thinking_tokens":618,"cache_read_tokens":4096,"total_tokens":8730}}}
{"event":"result","result":{"conversation_id":"conv-abc123","status":"SUCCESS","response":"AGY_LIVE_OK\n","error":null,"usage":{"input_tokens":8100,"output_tokens":12,"thinking_tokens":618,"cache_read_tokens":4096,"total_tokens":8730}}}
```

On error, `result.status` is `"ERROR"` and `result.error` holds the failure detail (e.g., `"authentication failed or timed out"`).

### 4.2 Flat / Workshop Dry-Run NDJSON Envelopes

```json
{"type":"session_start","conversation_id":"conv-dry-run-1"}
{"type":"tool_use","id":"t1","name":"EditFile","input":{"path":"calc.py"}}
{"type":"text_delta","delta":"Updated calc.py"}
{"type":"result","result":"Updated calc.py and verified tests.","usage":{"input_tokens":120,"output_tokens":45,"total_tokens":165}}
{"type":"error","error":"Rate limit exceeded"}
```

### 4.3 Mandatory Parser Rules (`parse_agy_stream_json`)
1. **Unwrap Nested Objects:** For each JSON line, inspect both top-level keys (`type`, `conversation_id`, `delta`, `result`, `usage`, `error`) AND nested dicts when `isinstance(parsed.get("result"), dict)`, `isinstance(parsed.get("step_update"), dict)`, or `isinstance(parsed.get("init"), dict)` (keyed by `"event"` or `"type"`).
2. **Response Extraction Precedence:** Prefer `result.response` (nested `agy 1.5.15`) or string `parsed["result"]` (flat), falling back to concatenated `step_update.text_delta` / `delta` chunks, and finally raw plain-text stdout lines if no JSON events were emitted.
3. **Token Usage Keys:** Extract `input_tokens`, `output_tokens`, `total_tokens`, **`thinking_tokens`**, and **`cache_read_tokens`** (plus `prompt_tokens`/`completion_tokens` aliases) from either top-level `usage`, `result.usage`, or `step_update.usage`.
4. **Stderr `AGY_ERROR:` Extraction:** Scan `stderr` lines for `AGY_ERROR: <detail>` (case-sensitive prefix). When `exit_code == 0`, harmless diagnostic `stderr` lines **without** an error status must leave `agy_error = None`.

---

## 5. Verified 4-Tier Exit-Code State Machine (`AgyExitCode`)

```python
from enum import IntEnum

class AgyExitCode(IntEnum):
    SUCCESS = 0              # Parse NDJSON stream, capture conversation_id & telemetry, run independent gates
    FAILURE = 1              # CLI/auth/transport fault -> FAIL FAST with actionable AGY_ADC_AUTH=true hint
    UNSUPPORTED_COMMAND = 2  # Usage/flag error -> NEVER retry!
    AGENT_ERROR = 3          # Quota/model/timeout (parses AGY_ERROR on stderr) -> bounded retry or neon -> hydrogen fallback
```

- **Never retry exit code `1` or `2`:** Exit `1` usually indicates missing `AGY_ADC_AUTH=true` / `GOOGLE_CLOUD_PROJECT` / `GOOGLE_CLOUD_LOCATION=global`, expired ADC, or running inside an air-gapped sandbox without credentials; exit `2` indicates a caller bug in flags.
- **Retry / fallback ONLY on exit code `3`:** Parse `AGY_ERROR` details from `stderr` (and check for `invalid project ID` if numeric `GOOGLE_CLOUD_PROJECT` leaked in), apply bounded backoff, and fall back from `gemini-4-neon` to `gemini-4-hydrogen` when quota/latency limits trigger.

---

## 6. Execution Modes (`AGY_EXECUTION_MODE`) & 3-Surface Comparison

| `AGY_EXECUTION_MODE` | Execution Target | Credential Path |
|---|---|---|
| **`local`** *(recommended on Agent Runtime with ADC)* | Current host / CI / trusted **Agent Runtime** container | `AGY_ADC_AUTH=true` + `AGY_CLI_DISABLE_AUTO_UPDATE=true` + non-numeric `AGY_PROJECT_ID` mapped to `GOOGLE_CLOUD_PROJECT` & `GOOGLE_CLOUD_QUOTA_PROJECT` + `GOOGLE_CLOUD_LOCATION=global` via Runtime Custom SA (`coding-agent-runtime-sa`). |
| **`sandbox`** | Remote gVisor **BYOC Managed Sandbox** via `AgentPlatformSandboxEnvironment.execute_with_env(...)` (with `execute(...)` fallback) (`--dangerously-skip-permissions`) | Requires PSC-I + Cloud NGFW/SWP egress AND passing only allowlisted ephemeral keys (`ALLOWED_EXEC_ENV_KEYS`, e.g., `GEMINI_API_KEY`) in `POST /exec`'s `env` dict (never written to disk or logged). Fails with exit `1` (`authentication required`) inside air-gapped sandboxes (`internet_access=false`) because gVisor sandboxes have no GCE metadata server / ADC. |
| **`auto`** *(default)* | Prefers **`local`** when `AGY_ADC_AUTH=true` and `shutil.which("agy")` is available without a BYOC `GEMINI_API_KEY`/egress override; routes to **`sandbox`** only when BYOC `GET /health` reports `agy_cli_available=True` AND BYOC credentials/egress are configured; otherwise falls back to native ADK 2.0 `LlmAgent` + `EnvironmentToolset` | Prevents accidentally routing `agy` into an air-gapped BYOC gVisor sandbox where `agy_cli_available=true` causes exit `1` auth failure; keeps BYOC dedicated to untrusted `pytest`/`ruff`/`bandit` execution. |

### Three Antigravity / ADK Coding Surfaces

| Surface | Best Used For | Key Constraint |
|---|---|---|
| **`agy` Headless CLI** | Battle-tested coding harness in laptop, CI, Agent Runtime (`AGY_ADC_AUTH=true` + `AGY_PROJECT_ID`), or egress-enabled BYOC Sandbox | Requires `/usr/local/bin/agy` binary (zero-Docker via Cloud Build), non-numeric `AGY_PROJECT_ID` on Agent Runtime, nested `1.5.15` stream-json parsing, and strict adherence to Enterprise Auth/ToS boundary. |
| **`google-antigravity` Python SDK** | Direct in-process Python control without CLI subprocess orchestration | Standard GCP ADC / Service Account IAM. |
| **ADK `ManagedAgent` / Native `LlmAgent` + `EnvironmentToolset`** | `ManagedAgent`: zero-ops `global` Preview prototyping · Native `LlmAgent`: regional production (`asia-southeast1`), BYOC sandboxes, `SkillToolset`, MCP, CMEK/VPC-SC | `ManagedAgent` forbids client Python tools (`NotImplementedError`); native `LlmAgent` is the zero-binary universal fallback. |

---

## 7. Enterprise Auth & ToS Boundary (Non-Negotiable)

1. **NEVER proxy or relay personal developer `agy` OAuth credentials** inside a shared or multi-tenant service.
2. **On Agent Runtime:** Authenticate `/usr/local/bin/agy` strictly via **`AGY_ADC_AUTH=true`** using the runtime's dedicated least-privilege Service Account (`coding-agent-runtime-sa`) plus non-numeric **`AGY_PROJECT_ID`** (`AGY_EXECUTION_MODE=local`), OR use native ADK 2.0 `LlmAgent` / `ManagedAgent` / `google-antigravity` SDK.
3. **In gVisor Managed Sandboxes (zero IAM roles, `169.254.169.254` blocked):** Prefer running `agy` in the trusted Agent Runtime (`AGY_EXECUTION_MODE=local`) while routing untrusted `pytest`/`ruff`/`bandit` commands into the air-gapped gVisor Sandbox (`internet_access=False`). Only run `agy` inside a BYOC Sandbox when PSC-I + Cloud NGFW/SWP egress is configured and a scoped ephemeral credential/API key from Secret Manager is injected strictly per-exec via `runner.py`'s allowlisted `env` map (never written to disk).
