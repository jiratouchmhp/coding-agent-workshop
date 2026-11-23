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
# Developer laptop / Cloud Workstations:
curl -fsSL https://antigravity.google/cli/install.sh | bash

# Container / CI deterministic install (used in Agent Runtime & BYOC Sandbox Dockerfiles):
curl -fsSL https://antigravity.google/cli/install.sh -o /tmp/agy_install.sh \
  && bash /tmp/agy_install.sh --dir /usr/local/bin \
  && rm -f /tmp/agy_install.sh \
  && chmod 0755 /usr/local/bin/agy
```

In both Agent Runtime (`Dockerfile`) and BYOC Sandbox (`sandbox_image/Dockerfile`), gate installation behind `ARG INSTALL_AGY_CLI=true` and build remotely via Cloud Build (`gcloud builds submit --region=asia-southeast3`) so attendees need **zero local Docker**.

---

## 3. Exact Verified Headless CLI Flags & Environment

```bash
AGY_ADC_AUTH=true \
AGY_CLI_DISABLE_AUTO_UPDATE=true \
GOOGLE_CLOUD_PROJECT="${GOOGLE_CLOUD_PROJECT}" \
GOOGLE_CLOUD_LOCATION="global" \
agy -p "<prompt>" \
  --output-format stream-json \
  --model gemini-4-hydrogen \
  --effort medium \
  --print-timeout 5m \
  --sandbox
```

| Flag | Verified Behavior |
|---|---|
| `-p "<prompt>"` | Non-interactive headless print mode. |
| `--output-format stream-json` | Emits NDJSON events (`conversation_id`, tool invocations, token usage, final response); `json` and `text` also supported. |
| `--model <id>` | `gemini-4-hydrogen` (fast coding), `gemini-4-neon` (deep reasoning), or `gemini-4-argon` (regional `asia-southeast1`). |
| `--effort <level>` | Maps directly from Gemini 4 `THINKING_LEVEL`: `low`, `medium`, `high`, `xhigh` (never `minimal`). |
| `--print-timeout <duration>` | Hard wall-clock timeout (e.g., `5m`) preventing stalled headless runs. |
| `--conversation <id>` | Continues the exact prior harness conversation across outer ADK fix rounds. |
| `--sandbox` | Enables terminal sandboxing for local / CI runs. |
| `--dangerously-skip-permissions` | Unattended auto-approve **strictly inside** an isolated gVisor Managed Sandbox or ephemeral CI container. |
| `--json-schema <schema_json>` | Optional structured JSON schema constraint for machine-readable output. |

---

## 4. Verified 4-Tier Exit-Code State Machine (`AgyExitCode`)

```python
from enum import IntEnum

class AgyExitCode(IntEnum):
    SUCCESS = 0              # Parse NDJSON stream, capture conversation_id & telemetry, run independent gates
    FAILURE = 1              # CLI/auth/transport fault -> FAIL FAST with actionable AGY_ADC_AUTH=true hint
    UNSUPPORTED_COMMAND = 2  # Usage/flag error -> NEVER retry!
    AGENT_ERROR = 3          # Quota/model/timeout (parses AGY_ERROR on stderr) -> bounded retry or neon -> hydrogen fallback
```

- **Never retry exit code `1` or `2`:** Exit `1` usually indicates missing `AGY_ADC_AUTH=true` / `GOOGLE_CLOUD_PROJECT` / `GOOGLE_CLOUD_LOCATION=global` or expired ADC; exit `2` indicates a caller bug in flags.
- **Retry / fallback ONLY on exit code `3`:** Parse `AGY_ERROR` details from `stderr`, apply bounded backoff, and fall back from `gemini-4-neon` to `gemini-4-hydrogen` when quota/latency limits trigger.

---

## 5. Execution Modes (`AGY_EXECUTION_MODE`) & 3-Surface Comparison

| `AGY_EXECUTION_MODE` | Execution Target | Credential Path |
|---|---|---|
| **`local`** | Current host / CI / trusted **Agent Runtime** container | `AGY_ADC_AUTH=true` + `AGY_CLI_DISABLE_AUTO_UPDATE=true` + `GOOGLE_CLOUD_PROJECT` + `GOOGLE_CLOUD_LOCATION=global` via Runtime Custom SA (`coding-agent-runtime-sa`). |
| **`sandbox`** | Remote gVisor **BYOC Managed Sandbox** via `AgentPlatformSandboxEnvironment.execute_with_env(...)` (with `execute(...)` fallback) (`--dangerously-skip-permissions`) | Requires PSC-I + Cloud NGFW/SWP egress AND passing only allowlisted ephemeral keys (`ALLOWED_EXEC_ENV_KEYS`) in `POST /exec`'s `env` dict (never written to disk or logged). |
| **`auto`** *(default)* | Probes sandbox `GET /health` (`agy_cli_available=True`) when `SANDBOX_MODE=byoc`, else local `shutil.which("agy")`, else native ADK 2.0 `LlmAgent` + `EnvironmentToolset` | Gracefully degrades when `agy` is not installed locally or when the BYOC sandbox is air-gapped (`internet_access=False`). |

### Three Antigravity / ADK Coding Surfaces

| Surface | Best Used For | Key Constraint |
|---|---|---|
| **`agy` Headless CLI** | Battle-tested coding harness in laptop, CI, Agent Runtime (`AGY_ADC_AUTH=true`), or BYOC Sandbox | Requires `/usr/local/bin/agy` binary (zero-Docker via Cloud Build) and strict adherence to Enterprise Auth/ToS boundary. |
| **`google-antigravity` Python SDK** | Direct in-process Python control without CLI subprocess orchestration | Standard GCP ADC / Service Account IAM. |
| **ADK `ManagedAgent` / Native `LlmAgent` + `EnvironmentToolset`** | `ManagedAgent`: zero-ops `global` Preview prototyping · Native `LlmAgent`: regional production (`asia-southeast1`), BYOC sandboxes, `SkillToolset`, MCP, CMEK/VPC-SC | `ManagedAgent` forbids client Python tools (`NotImplementedError`); native `LlmAgent` is the zero-binary universal fallback. |

---

## 6. Enterprise Auth & ToS Boundary (Non-Negotiable)

1. **NEVER proxy or relay personal developer `agy` OAuth credentials** inside a shared or multi-tenant service.
2. **On Agent Runtime:** Authenticate `/usr/local/bin/agy` strictly via **`AGY_ADC_AUTH=true`** using the runtime's dedicated least-privilege Service Account (`coding-agent-runtime-sa`), OR use native ADK 2.0 `LlmAgent` / `ManagedAgent` / `google-antigravity` SDK.
3. **In gVisor Managed Sandboxes (zero IAM roles, `169.254.169.254` blocked):** Prefer running `agy` in the trusted Agent Runtime while routing untrusted `pytest`/`ruff`/`bandit` commands into the air-gapped gVisor Sandbox (`internet_access=False`). Only run `agy` inside a BYOC Sandbox when PSC-I + Cloud NGFW/SWP egress is configured and a scoped ephemeral credential/API key from Secret Manager is injected strictly per-exec via `runner.py`'s allowlisted `env` map (never written to disk).
