# Custom Containers (BYOC) for Agent Platform Scale Sandboxes

Use Bring Your Own Container (**BYOC**) when predefined Code Execution, Shell, or Computer Use sandboxes lack the runtimes, compilers, linters, SAST tools, system packages, or custom HTTP/WebSocket data-plane interfaces your agent requires.

---

## 1. Container Image Requirements & Non-Root Hardening

Official BYOC container constraints (`scale/sandbox/custom-containers`):

1. **OS:** Linux-based container image (for example, Debian or Ubuntu; avoid bloated bases and privileged init systems).
2. **Security (Strict Non-Root / Unprivileged):** Must **not** require `root` privileges, `sudo`, `CAP_SYS_ADMIN`, or restricted kernel/system resources. Every sandbox runs inside a **gVisor-isolated container** in a Google-managed tenant project under an unprivileged user (backed by tenant identity `sandbox-untrusted` with zero GCP IAM roles, no ADC, and no access to `169.254.169.254:80`).
3. **Compatible Runner / Entrypoint:** Must include a runner or entrypoint on declared TCP port(s) that Gemini Enterprise Agent Platform or your data-plane client invokes to execute commands.
4. **Registry Location:** Hosted in **Google Cloud Artifact Registry** (`REGION-docker.pkg.dev/PROJECT_ID/REPO/IMAGE:TAG`) in a region accessible to the sandbox service agent.

### Runner & `/exec` Wire Contract — Explicit Upstream Honesty

- `scale/sandbox/custom-containers` states that a BYOC image must include *"a compatible runner or entry point that Gemini Enterprise Agent Platform can use to execute commands"* and expose TCP `ports` on `custom_container_environment`.
- `scale/sandbox/shell-sandbox-quickstart` documents that the managed Shell Sandbox runner listens on HTTP `/exec` and returns `{"stdout": str, "stderr": str, "returncode": int, "duration_ms": int}`.
- `scale/sandbox` cites the open-source reference architectures **AX** (https://agentexecutor.io/) and **Substrate** (https://github.com/agent-substrate/substrate) and lists data-plane RPCs `ExecuteSandboxEnvironment`, `BidiExecuteSandboxEnvironment`, and `AuthorizeSandboxEnvironmentAccess`.
- **Verified Documentation Gap:** Upstream `scale/sandbox/custom-containers` does **not** publish a verbatim Dockerfile or mandatory JSON wire schema for implementing a custom `/exec` runner from scratch. Do **not** invent undocumented platform-reserved headers or confuse GKE Agent Sandbox's `sandbox-router` port `8888` with Agent Platform BYOC `custom_container_environment.ports`.
- **Production Pattern:** Expose `GET /health` and `POST /exec` on a declared TCP port (such as `8080`), returning the exact Shell-aligned JSON schema `{"stdout", "stderr", "returncode", "duration_ms"}`, confining `cwd` inside `/workspace`, enforcing hard process-group timeouts (`SIGTERM` -> `SIGKILL`), and keeping the runner script read-only (`root:root 0644`) so untrusted `appuser` commands cannot modify it.

### Production Non-Root BYOC Dockerfile Pattern (Debian Bookworm Slim)

```dockerfile
# Multi-stage non-root BYOC coding sandbox (Python 3.11 + Node.js 22 LTS + CLI tooling)
FROM node:22-bookworm-slim AS node_lts
FROM python:3.11-slim-bookworm

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    SANDBOX_WORKSPACE=/workspace \
    SANDBOX_HOST=0.0.0.0 \
    SANDBOX_PORT=8080

# Copy Node.js cleanly from official image (avoids curl|bash installer patterns)
COPY --from=node_lts /usr/local/bin/node /usr/local/bin/node
COPY --from=node_lts /usr/local/lib/node_modules /usr/local/lib/node_modules
RUN ln -sf /usr/local/lib/node_modules/npm/bin/npm-cli.js /usr/local/bin/npm \
    && ln -sf /usr/local/lib/node_modules/npm/bin/npx-cli.js /usr/local/bin/npx

# Install minimal CLI utilities (strictly NO sudo)
RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        bash ca-certificates curl git jq \
    && rm -rf /var/lib/apt/lists/*

# Bake Python test/lint/security tools at build time so sandbox can stay air-gapped
COPY requirements.txt /tmp/requirements.txt
RUN pip install --upgrade pip \
    && pip install -r /tmp/requirements.txt \
    && rm -f /tmp/requirements.txt

# Opt-in static Go Antigravity (`agy`) headless CLI (zero local Docker via Bangkok Cloud Build)
ARG INSTALL_AGY_CLI=true
RUN if [ "${INSTALL_AGY_CLI}" = "true" ]; then \
      curl -fsSL https://antigravity.google/cli/install.sh -o /tmp/agy_install.sh \
      && bash /tmp/agy_install.sh --dir /usr/local/bin \
      && rm -f /tmp/agy_install.sh \
      && chmod 0755 /usr/local/bin/agy; \
    fi

# Unprivileged UID 1000 user; confine writable workspace to /workspace
RUN groupadd --gid 1000 appuser \
    && useradd --uid 1000 --gid 1000 --create-home --shell /bin/bash appuser \
    && mkdir -p /workspace /opt/sandbox_runner \
    && chown -R appuser:appuser /workspace /home/appuser

# Mount runner read-only (root:root 0644) so untrusted commands cannot tamper with it.
# CRITICAL: Do NOT use `COPY --chmod=0644` — Cloud Build (`gcloud builds submit --tag=...`)
# runs the legacy Docker builder without BuildKit and fails with `the --chmod option requires BuildKit`.
COPY --chown=root:root runner.py /opt/sandbox_runner/runner.py
RUN chmod 0644 /opt/sandbox_runner/runner.py

USER appuser
WORKDIR /workspace
EXPOSE 8080

HEALTHCHECK --interval=30s --timeout=5s --start-period=5s --retries=3 \
    CMD python3 -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8080/health', timeout=2)" || exit 1

ENTRYPOINT ["python3", "/opt/sandbox_runner/runner.py"]
```

### Runner Hardening Checklist

- Bind `0.0.0.0:8080` (matching the declared `ports` entry on the template).
- Report `"agy_cli_available": shutil.which("agy") is not None` in `GET /health` so `AGY_EXECUTION_MODE=auto` can probe sandbox capabilities cleanly.
- Resolve requested `cwd` with `Path.resolve().is_relative_to(WORKSPACE_ROOT)` to block directory traversal outside `/workspace`.
- Pass a strict allowlist of non-credential base environment variables (`PATH`, `HOME`, `USER`, `LANG`, `TMPDIR`, `PYTHONUNBUFFERED`) to child shells. When `POST /exec` optionally accepts `"env": dict[str, str]` for ephemeral `agy` invocations, restrict keys strictly to `ALLOWED_EXEC_ENV_KEYS` (`AGY_ADC_AUTH`, `AGY_CLI_DISABLE_AUTO_UPDATE`, `GOOGLE_CLOUD_PROJECT`, `GOOGLE_CLOUD_LOCATION`, `GOOGLE_CLOUD_QUOTA_PROJECT`, `GEMINI_API_KEY`), reject non-dict `env` or unknown keys with **HTTP 400**, inject ONLY into that single child process `env`, and **NEVER** write values to disk or log them.
- Spawn child processes with `start_new_session=True` so timeouts kill the entire process group (`os.killpg(proc.pid, SIGTERM)` -> `SIGKILL`), preventing zombie background processes.
- Cap request payload size (e.g., 2 MB) and stdout/stderr truncation size (e.g., 1 MB) to avoid OOM under container memory limits.
- Prefer `["/bin/bash", "-c", command]` (non-login) so `/etc/profile` does not overwrite your configured `PATH`.

---

## 2. Artifact Registry, Vulnerability Scanning & Service Agent IAM

> **Bangkok-First Regional Strategy (`asia-southeast3` Default -> `asia-southeast1` Fallback Only Where Unavailable):** Aim for **Bangkok (`asia-southeast3`)** first for Cloud Build (`BUILD_LOCATION=asia-southeast3`) and Artifact Registry (`AR_LOCATION=asia-southeast3`). Fall back to **Singapore (`GOOGLE_CLOUD_LOCATION=asia-southeast1`)** only because Managed Scale Sandboxes and Agent Runtime are not yet launched in Bangkok. **Empirically verified:** Singapore BYOC Sandboxes pull cleanly from Bangkok Artifact Registry (`asia-southeast3-docker.pkg.dev`) — **no second Singapore AR repository is required**.

### Step 1: Create Artifact Registry Repo (Optional CMEK on AR Repo)

> **CMEK Boundary:** Parent `ReasoningEngine` CMEK encrypts sandbox runtime boot disks and snapshot buckets, **not** source images stored in Artifact Registry. To encrypt BYOC images at rest with your own key, configure CMEK directly on the Artifact Registry repository (`--kms-key=...`).

```bash
export PROJECT_ID="YOUR_PROJECT_ID"
export PROJECT_NUMBER="$(gcloud projects describe "${PROJECT_ID}" --format='value(projectNumber)')"
export PRIMARY_REGION="${PRIMARY_REGION:-asia-southeast3}"               # Bangkok default region
export GOOGLE_CLOUD_LOCATION="${GOOGLE_CLOUD_LOCATION:-asia-southeast1}" # Singapore fallback (Managed Sandboxes not yet in Bangkok)
export AR_LOCATION="${AR_LOCATION:-${PRIMARY_REGION}}"                   # Bangkok AR (empirically verified with SG BYOC Sandboxes!)
export BUILD_LOCATION="${BUILD_LOCATION:-${PRIMARY_REGION}}"             # Bangkok remote Cloud Build (zero local Docker)
export REPO_NAME="coding-agent-repo"

# Enable required APIs
gcloud services enable \
    aiplatform.googleapis.com \
    artifactregistry.googleapis.com \
    cloudbuild.googleapis.com \
    containerscanning.googleapis.com \
    --project="${PROJECT_ID}"

# Create Docker repository (add --kms-key=... if CMEK for source images is required)
gcloud artifacts repositories create "${REPO_NAME}" \
    --repository-format=docker \
    --location="${AR_LOCATION}" \
    --description="BYOC sandbox and agent container images" \
    --project="${PROJECT_ID}"
```

### Step 2: Grant `roles/artifactregistry.reader` to the Agent Sandbox Service Agent

**Critical:** Grant pull access to **`gcp-sa-vertex-sandbox`** (NOT `gcp-sa-aiplatform-re` or `gcp-sa-aiplatform`) on the repository in `${AR_LOCATION}`.

```bash
gcloud artifacts repositories add-iam-policy-binding "${REPO_NAME}" \
    --location="${AR_LOCATION}" \
    --project="${PROJECT_ID}" \
    --member="serviceAccount:service-${PROJECT_NUMBER}@gcp-sa-vertex-sandbox.iam.gserviceaccount.com" \
    --role="roles/artifactregistry.reader"
```

#### Terraform Equivalent for Artifact Registry IAM

> **IaC Scope Note:** No Terraform resource (`google_vertex_ai_sandbox_*`) is documented for Managed Sandboxes, Templates, or Snapshots. Manage infrastructure prerequisites (Artifact Registry repo, `gcp-sa-vertex-sandbox` IAM, VPC/PSC-I, KMS, and parent `google_vertex_ai_reasoning_engine`) in Terraform, and create templates/sandboxes via the Python SDK.

```hcl
data "google_project" "current" {
  project_id = var.project_id
}

resource "google_artifact_registry_repository_iam_member" "sandbox_pull_reader" {
  project    = var.project_id
  location   = var.ar_location # Default "asia-southeast3" (Bangkok AR — empirically verified with SG BYOC Sandboxes!)
  repository = var.artifact_registry_repo
  role       = "roles/artifactregistry.reader"
  member     = "serviceAccount:service-${data.google_project.current.number}@gcp-sa-vertex-sandbox.iam.gserviceaccount.com"
}
```

### Step 3: Build, Push & Scan the BYOC Image (Zero-Docker Default Path)

Use **Cloud Build (`gcloud builds submit --region=...`)** as the **default zero-Docker path** — no local Docker daemon is required, and Cloud Build compiles `linux/amd64` images directly in Bangkok (`asia-southeast3`) matching sandbox CPU architecture for snapshot compatibility. Note that `gcloud builds submit --tag=...` runs Cloud Build's legacy Docker builder without BuildKit, so always use `COPY --chown=root:root` + `RUN chmod 0644` instead of `COPY --chmod=0644`. Local `docker build` / `docker push` is strictly optional. For rapid prototyping without building any image, use Managed Shell Sandbox (`SANDBOX_MODE=shell`) as a zero-build fast-track.

```bash
export IMAGE_URI="${AR_LOCATION}-docker.pkg.dev/${PROJECT_ID}/${REPO_NAME}/coding-sandbox:v1"

# Default (Zero-Docker): Remote Cloud Build in Bangkok (BUILD_LOCATION=asia-southeast3 -> AR_LOCATION=asia-southeast3)
gcloud builds submit ./sandbox_image \
    --region="${BUILD_LOCATION}" \
    --tag="${IMAGE_URI}" \
    --project="${PROJECT_ID}"

# Optional (Local Docker workstation only): Local linux/amd64 build & push
gcloud auth configure-docker "${AR_LOCATION}-docker.pkg.dev" --quiet
docker build --platform linux/amd64 -t "${IMAGE_URI}" ./sandbox_image
docker push "${IMAGE_URI}"

# Inspect Artifact Registry vulnerability scan results before deploying to a template
gcloud artifacts docker images list-vulnerabilities "${IMAGE_URI}" --project="${PROJECT_ID}"
```

---

## 3. Creating a BYOC `SandboxEnvironmentTemplate` & Sandbox (`v1beta1`)

Creating a `SandboxEnvironmentTemplate` triggers **pre-warmed pools** associated with the template for faster, more reliable startup times. Always pass `http_options={"api_version": "v1beta1"}`.

```python
import os
import agentplatform

PROJECT_ID = os.environ.get("GOOGLE_CLOUD_PROJECT", "YOUR_PROJECT_ID")
# Managed Sandbox region: Singapore fallback (asia-southeast1 — not yet launched in Bangkok asia-southeast3)
SANDBOX_LOCATION = os.environ.get("GOOGLE_CLOUD_LOCATION", "asia-southeast1")
# Artifact Registry region: Bangkok default (asia-southeast3 — empirically verified pulling into SG BYOC Sandboxes!)
AR_LOCATION = os.environ.get("AR_LOCATION", "asia-southeast3")
IMAGE_URI = f"{AR_LOCATION}-docker.pkg.dev/{PROJECT_ID}/coding-agent-repo/coding-sandbox:v1"

client = agentplatform.Client(
    project=PROJECT_ID,
    location=SANDBOX_LOCATION,
    http_options={"api_version": "v1beta1"},
)

# 1. Create (or reuse) a parent Agent Platform instance (no agent deployment required)
remote_agent = client.runtimes.create()
instance_name = remote_agent.api_resource.name

# 2. Create the reusable BYOC SandboxEnvironmentTemplate
template_op = client.sandboxes.templates.create(
    name=instance_name,
    display_name="byoc-coding-sandbox-template",
    config={
        "custom_container_environment": {
            "custom_container_spec": {
                "image_uri": IMAGE_URI,
            },
            "resources": {
                "requests": {"cpu": "1", "memory": "1Gi"},
                "limits": {"cpu": "2", "memory": "2Gi"},
            },
            "ports": [
                {"port": 8080, "protocol": "TCP"},
            ],
        },
        "egress_control_config": {
            # Keep False when tools are baked into the image; set True (or attach PSC-I) if egress is needed
            "internet_access": False,
        },
    },
)
template_name = template_op.response.name
print(f"Created BYOC template: {template_name}")

# 3. Provision a SandboxEnvironment from the template (always set ttl; max 7 days for BYOC)
sandbox_op = client.sandboxes.create(
    name=instance_name,
    config={
        "sandbox_environment_template": template_name,
        "display_name": "byoc-coding-sandbox-01",
        "ttl": "3600s",
        "wait_for_completion": True,
    },
)
sandbox = sandbox_op.response
print(f"Provisioned BYOC sandbox: {sandbox.name} (state={sandbox.state})")
```

### Updating a BYOC Image Version

Templates do **not** have a documented SDK in-place update method:
1. Build and push an immutable tag (e.g., `:v2` or digest `@sha256:...` — avoid mutable `:latest` tags so snapshots stay compatible with `image_uri`).
2. Delete the old `SandboxEnvironmentTemplate` once no warm pool or sandbox creation is actively using it.
3. Create a new `SandboxEnvironmentTemplate` pointing to the new `image_uri`.

---

## 4. Common BYOC Errors & Fixes

| Symptom / Error | Root Cause | Fix |
|---|---|---|
| `the --chmod option requires BuildKit` during `gcloud builds submit --tag=...` | Cloud Build's `--tag` shorthand invokes the legacy Docker builder without BuildKit enabled | Replace `COPY --chown=root:root --chmod=0644 ...` with `COPY --chown=root:root ...` followed by `RUN chmod 0644 ...`. |
| Image pull `PERMISSION_DENIED` / `403` during template or sandbox creation | `roles/artifactregistry.reader` granted to `gcp-sa-aiplatform-re` instead of `gcp-sa-vertex-sandbox`, wrong project number, or IAM bound in wrong `AR_LOCATION` | Bind `roles/artifactregistry.reader` on the AR repo in `${AR_LOCATION}` (e.g., Bangkok `asia-southeast3`, verified working with Singapore BYOC Sandboxes) to `service-PROJECT_NUMBER@gcp-sa-vertex-sandbox.iam.gserviceaccount.com`. |
| Sandbox reaches `STATE_TERMINATED` immediately on startup | Container entrypoint requires `root`, `sudo`, privileged syscalls blocked by gVisor, or crashes on missing env vars | Smoke-test `runner.py` locally with pure Python first (zero Docker), and optionally run `docker run --rm --cap-drop=ALL --security-opt=no-new-privileges`; verify `USER appuser` and read-only runner permissions. |
| API rejects `custom_container_environment` or `egress_control_config` fields | Client initialized without `v1beta1` | Pass `http_options={"api_version": "v1beta1"}` to `agentplatform.Client(...)`. |
| First cold-start sandbox takes >30 seconds | Initial cold provisioning of unprovisioned capacity takes up to **2 minutes** | Reuse one `SandboxEnvironmentTemplate` so pre-warmed pools serve subsequent sandboxes in seconds. |
| Snapshot restore fails after pushing a new image to `:latest` | Snapshot restore requires identical CPU architecture (`amd64` vs `arm64`), runtime version, and `image_uri` | Pin immutable tags (`:v1`, `:sha-...`) per template version. |
| Template deletion fails | Warm pool creation or sandbox creation is actively referencing the template | Wait for active creations to settle, then retry `client.sandboxes.templates.delete(name=template_name)`. |

---

## 5. Verification Steps

### Option A (Primary — Zero-Docker): Pure-Python Local `runner.py` Smoke Test

Verify the stdlib HTTP runner locally without requiring a Docker daemon:

```bash
# 1. Start runner.py locally bound to localhost against a temporary workspace
mkdir -p /tmp/byoc-smoke-ws
SANDBOX_WORKSPACE=/tmp/byoc-smoke-ws \
SANDBOX_HOST=127.0.0.1 \
SANDBOX_PORT=8080 \
python3 ./sandbox_image/runner.py &
RUNNER_PID=$!
trap 'kill "${RUNNER_PID}" 2>/dev/null || true' EXIT
sleep 1

# 2. Verify /health reports non-root UID != 0 and confined workspace
curl -sS http://127.0.0.1:8080/health | jq .

# 3. Verify /exec returns the Shell-aligned JSON schema {"stdout","stderr","returncode","duration_ms"}
curl -sS -X POST http://127.0.0.1:8080/exec \
    -H "Content-Type: application/json" \
    -d '{"command": "id && pwd", "cwd": "/tmp/byoc-smoke-ws", "timeout": 15}' | jq .

# 4. Expect HTTP 400 when attempting cwd escape outside SANDBOX_WORKSPACE
curl -sS -o /dev/null -w "%{http_code}\n" -X POST http://127.0.0.1:8080/exec \
    -H "Content-Type: application/json" \
    -d '{"command": "ls", "cwd": "/etc"}'

kill "${RUNNER_PID}"
```

### Option B (Optional — Local Docker): Container Capability & Non-Root Check

Run when a local Docker daemon is available to validate dropped Linux capabilities and `USER appuser` image hardening:

```bash
# 1. Run container locally with dropped capabilities and verify non-root UID
docker run -d --name byoc-smoke --rm -p 8080:8080 \
    --cap-drop=ALL --security-opt=no-new-privileges \
    "${IMAGE_URI}"

# 2. Verify /health reports non-root UID != 0
curl -sS http://127.0.0.1:8080/health | jq .

# 3. Verify /exec returns expected schema and blocks sudo / path traversal
curl -sS -X POST http://127.0.0.1:8080/exec \
    -H "Content-Type: application/json" \
    -d '{"command": "id && whoami && pwd", "cwd": "/workspace", "timeout": 15}' | jq .

# Expect HTTP 400 when attempting cwd escape
curl -sS -o /dev/null -w "%{http_code}\n" -X POST http://127.0.0.1:8080/exec \
    -H "Content-Type: application/json" \
    -d '{"command": "ls", "cwd": "/etc"}'

docker stop byoc-smoke
```

### Cloud IAM & Provisioning Check

```bash
# Confirm gcp-sa-vertex-sandbox holds roles/artifactregistry.reader in AR_LOCATION
gcloud artifacts repositories get-iam-policy "${REPO_NAME}" \
    --location="${AR_LOCATION}" \
    --project="${PROJECT_ID}" \
    --format="yaml(bindings)" | grep -B2 -A4 "gcp-sa-vertex-sandbox"
```
