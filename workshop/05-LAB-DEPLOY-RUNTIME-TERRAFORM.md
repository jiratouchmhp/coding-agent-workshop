# Lab 5: Deploy Your Coding Agent to Agent Runtime with Terraform

In Labs 1 through 4 you built the full coding agent locally: ADK 2.0 core, managed sandbox execution, sessions and memory, and skill registries. Now you'll wire the Agent Runtime HTTP server, build the container remotely with Cloud Build (no local Docker needed), and deploy it to Vertex AI Agent Runtime in `asia-southeast1` with Terraform.

**Duration:** 45 min (Full-Day) | 30 min (Fast-Track) | **Previous:** [Lab 4: Skill Registry & Agent Registry](./04-LAB-SKILLS-AND-AGENT-REGISTRY.md) | **Next:** [Lab 6: Observability, Evaluation & Quality Alerts](./06-LAB-OPTIMIZE-EVAL-AND-ALERTS.md)

## Files You Will Edit

| Step | File | Where to edit | What you're adding |
|---|---|---|---|
| Step 1 | [starter/main.py](../starter/main.py) | `get_runtime_app()`, `query_endpoint()`, `stream_query_endpoint()` (`# TODO(lab-5)`) | Lazy `AdkApp` loader and unary/streaming HTTP endpoints |
| Step 3 | `starter/terraform/terraform.tfvars` (copied from [terraform.tfvars.example](../starter/terraform/terraform.tfvars.example)) | Project, image URI, and sandbox variables | Your GCP project ID/number, pushed image URI, and optional Lab 2 sandbox template |
| Step 4 | [starter/terraform/main.tf](../starter/terraform/main.tf) | 5 `# TODO(lab-5)` blocks (`runtime_sa_roles`, AR service-agent IAM, `container_spec`, `deployment_spec`, `depends_on`) | Memory Bank role, Artifact Registry pull IAM, container spec, runtime env/secrets, and IAM ordering |

**Already built for you (no edits needed):** [starter/Dockerfile](../starter/Dockerfile), [starter/requirements.txt](../starter/requirements.txt), [starter/terraform/versions.tf](../starter/terraform/versions.tf), [starter/terraform/variables.tf](../starter/terraform/variables.tf), [starter/terraform/outputs.tf](../starter/terraform/outputs.tf), and `_parse_query_request()`, `_resolve_public_method()`, `_invoke_method()`, and `_ndjson_stream()` in [starter/main.py](../starter/main.py).

**Need a hand or fell behind?** Ask Antigravity to use [`.agents/skills/agent-platform-runtime-and-state`](../.agents/skills/agent-platform-runtime-and-state/SKILL.md), or run `make fast-forward LAB=5` to sync Lab 5 from `solution/` without touching Lab 6.

---

## Step 1: Wire the Agent Runtime HTTP Server (`starter/main.py`)

**File:** [starter/main.py](../starter/main.py) (`get_runtime_app()`, `query_endpoint()`, `stream_query_endpoint()`, `# TODO(lab-5)`)

Agent Runtime calls your container on `0.0.0.0:8080`: health probes hit `GET /` (already wired), unary `:query` calls hit `POST /api/reasoning_engine`, and streaming `:streamQuery` calls hit `POST /api/stream_reasoning_engine`. You'll complete three functions so FastAPI lazily loads your `AdkApp` and routes method calls to it.

- **`get_runtime_app()`:** Import `app as adk_app` and `root_agent` from `coding_agent.agent`, and `AdkApp` from `agentplatform.frameworks` (falling back to `vertexai.agent_engines`).
- **Empty env-var quirk:** Right *after* importing `coding_agent.agent` (which may load `.env`) and *before* creating `AdkApp`, pop `GOOGLE_CLOUD_AGENT_ENGINE_ID` if empty or whitespace. Otherwise `AdkApp.set_up()` checks `"GOOGLE_CLOUD_AGENT_ENGINE_ID" in os.environ` and crashes locally with `ValueError: agent_engine_id is required for VertexAiMemoryBankService`.
- **SDK compatibility:** Inspect `AdkApp.__init__` and pass `AdkApp(app=adk_app)` when `"app"` is supported (preserving `ResumabilityConfig` and plugins); otherwise pass `AdkApp(agent=root_agent)` (plus `plugins` if accepted), call `set_up()`, and return it.
- **`query_endpoint()` and `stream_query_endpoint()`:** Keep `request: Request` and call the pre-filled `await _parse_query_request(request)` helper (changing the type to `QueryRequest` causes FastAPI `0.163+` to fail proxied `:query` calls with HTTP 422). Resolve the method with `_resolve_public_method(...)`, invoke it with `await _invoke_method(...)`, and return JSON (`{"output": output}`) or `_ndjson_stream(output)`.

<details>
<summary>Stuck? Peek at the code</summary>

```python
@functools.lru_cache(maxsize=1)
def get_runtime_app() -> Any:
    from coding_agent.agent import app as adk_app
    from coding_agent.agent import root_agent

    try:
        from agentplatform.frameworks import AdkApp
    except ImportError:
        from vertexai.agent_engines import AdkApp

    if not os.environ.get("GOOGLE_CLOUD_AGENT_ENGINE_ID", "").strip():
        os.environ.pop("GOOGLE_CLOUD_AGENT_ENGINE_ID", None)

    init_params = inspect.signature(AdkApp.__init__).parameters
    if "app" in init_params:
        runtime_app = AdkApp(app=adk_app)
    else:
        kwargs: dict[str, Any] = {"agent": root_agent}
        app_plugins = getattr(adk_app, "plugins", None)
        if app_plugins and "plugins" in init_params:
            kwargs["plugins"] = list(app_plugins)
        runtime_app = AdkApp(**kwargs)

    setup_fn = getattr(runtime_app, "set_up", None)
    if callable(setup_fn):
        setup_fn()
    return runtime_app


@app.post("/api/reasoning_engine")
async def query_endpoint(request: Request) -> responses.JSONResponse:
    query_req = await _parse_query_request(request)
    method = _resolve_public_method(get_runtime_app(), query_req.class_method)
    if method is None:
        return responses.JSONResponse(
            status_code=400,
            content={"error": f"Method {query_req.class_method!r} not found on agent"},
        )
    output = await _invoke_method(method, query_req.input or {})
    return responses.JSONResponse(content=encoders.jsonable_encoder({"output": output}))


@app.post("/api/stream_reasoning_engine")
async def stream_query_endpoint(request: Request) -> responses.StreamingResponse:
    query_req = await _parse_query_request(request)
    method = _resolve_public_method(get_runtime_app(), query_req.class_method)
    if method is None:
        return responses.StreamingResponse(
            content=iter([json.dumps({"error": f"Method {query_req.class_method!r} not found"}) + "\n"]),
            status_code=400,
            media_type="application/json",
        )
    output = await _invoke_method(method, query_req.input or {})
    return responses.StreamingResponse(content=_ndjson_stream(output), media_type="application/json")
```

Full reference file: [`solution/main.py`](../solution/main.py).

</details>

**Check it works:**

```bash
make test-agent-local
```

This runs Uvicorn locally in pure Python (no Docker) and prints `[PASS]` for `GET /` (`200 {"status":"ok"}`) plus three `POST /api/reasoning_engine` (`list_sessions`) calls across `application/json`, missing `Content-Type`, and `text/plain` headers.

---

## Step 2: Build and Push the Agent Image via Cloud Build

Now build `starter/` (`Dockerfile`, `main.py`, `requirements.txt`, `coding_agent/`, and `skills_to_register/`) remotely with Cloud Build in `asia-southeast3`. This trusted image (`coding-agent:v1`) is separate from Lab 2's untrusted sandbox image (`coding-sandbox:v1`), and Agent Runtime in `asia-southeast1` pulls directly from your `asia-southeast3` Artifact Registry repo with no second repo needed.

If you customize the repo name or image tag, update `AGENT_IMAGE_URI` (and `AR_REPOSITORY`, not `AR_REPO`) in `.env` **before** running `make push-agent` so a blank `AGENT_IMAGE_URI=` template line in `.env` never overrides a shell-only `export` (and avoid appending duplicate `AGENT_IMAGE_URI=` lines to `.env`).

```bash
set -a && source .env && set +a
export AR_LOCATION="${AR_LOCATION:-asia-southeast3}"
export AR_REPOSITORY="${AR_REPOSITORY:-coding-agent-repo}"
gcloud config set project "${GOOGLE_CLOUD_PROJECT}"
gcloud artifacts repositories create "${AR_REPOSITORY}" \
  --repository-format=docker --location="${AR_LOCATION}" \
  --project="${GOOGLE_CLOUD_PROJECT}" || true

# Update AGENT_IMAGE_URI in .env BEFORE `make push-agent` (replace existing line, no duplicates):
# AGENT_IMAGE_URI=asia-southeast3-docker.pkg.dev/<YOUR_PROJECT_ID>/coding-agent-repo/coding-agent:v1
make push-agent
```

**Check it works:** Cloud Build finishes with `STATUS: SUCCESS` and prints the image digest for `coding-agent:v1`.

---

## Step 3: Create `starter/terraform/terraform.tfvars`

**File:** `starter/terraform/terraform.tfvars` (copied from [starter/terraform/terraform.tfvars.example](../starter/terraform/terraform.tfvars.example))

Copy the example file and fill in your `project_id`, `project_number`, the `AGENT_IMAGE_URI` you just pushed, and optionally your Lab 2 `sandbox_template_name` (leave it `""` to auto-select `SANDBOX_MODE=shell`). Keep `location = "asia-southeast1"` because Agent Runtime is not yet in `asia-southeast3`, and keep `enable_memory_bank = false` and `enable_skill_registry = false` for a clean initial deploy. Never commit `terraform.tfvars`.

```bash
cp starter/terraform/terraform.tfvars.example starter/terraform/terraform.tfvars
```

Key lines to update:

```hcl
project_id            = "YOUR_PROJECT_ID"
project_number        = "YOUR_PROJECT_NUMBER"
location              = "asia-southeast1"
agent_image_uri       = "asia-southeast3-docker.pkg.dev/YOUR_PROJECT_ID/coding-agent-repo/coding-agent:v1"
sandbox_template_name = "" # Paste Lab 2 template name for BYOC, or leave "" for shell mode
api_key_value         = "replace-with-workshop-placeholder-value"
```

**Check it works:** `grep -E 'your-gcp-project-id|123456789012' starter/terraform/terraform.tfvars || echo "tfvars ready"` prints `tfvars ready`.

---

## Step 4: Finish the 5 `# TODO(lab-5)` Blocks in `starter/terraform/main.tf`

**File:** [starter/terraform/main.tf](../starter/terraform/main.tf) (5 `# TODO(lab-5)` blocks)

Most of `main.tf` is already wired: the custom runtime SA (`coding-agent-runtime-sa`), Secret Manager secret, `deletion_policy = "FORCE"`, `class_methods`, OTel telemetry env vars, and `AGY_PROJECT_ID = var.project_id` (required because Agent Runtime injects your numeric project number into `GOOGLE_CLOUD_PROJECT`, which `agy` rejects). Complete the 5 `# TODO(lab-5)` blocks in order:

1. **`runtime_sa_roles`:** Add `"roles/aiplatform.memoryUser"` so the runtime SA can access Lab 3 Memory Bank when enabled.
2. **Service-agent Artifact Registry IAM:** Uncomment `re_service_agent_ar_reader` (`gcp-sa-aiplatform-re`) and `sandbox_service_agent_ar_reader` (`gcp-sa-vertex-sandbox`) so Google's service agents can pull your runtime and sandbox images.
3. **`container_spec`:** Uncomment `container_spec { image_uri = var.agent_image_uri }` inside `google_vertex_ai_reasoning_engine.coding_agent` (`class_methods = jsonencode(local.adk_class_methods)` is already uncommented right below `deployment_spec`).
4. **`deployment_spec`:** Uncomment the sandbox env vars (`SANDBOX_MODE`, `dynamic "env"` for `SANDBOX_TEMPLATE_NAME`, `SANDBOX_SERVICE_ACCOUNT_EMAIL`), Lab 3/4 flags (`ENABLE_MEMORY_BANK`, `ENABLE_SKILL_REGISTRY`, and the three `dynamic "env"` registry location blocks), and `secret_env` (`CODING_AGENT_API_KEY`).
5. **`depends_on`:** Expand `depends_on` with all 6 remaining IAM bindings (`re_service_agent_ar_reader`, `sandbox_service_agent_ar_reader`, `runtime_sa_roles`, `runtime_sa_self_token_creator`, `runtime_sa_secret_accessor`, `platform_service_agent_secret_accessor`) alongside `runtime_sa_agentregistry_viewer` and `coding_agent_api_key_v1`. Without this, container pulls can race IAM propagation and fail with `IMAGE_PULL_BACKOFF`.

> [!WARNING]
> **Two Terraform schema gotchas:** `google_vertex_ai_reasoning_engine` uses **`region = var.location`** (not `location`), and Vertex AI rejects empty-string env values with HTTP 400. Always keep optional vars like `SANDBOX_TEMPLATE_NAME` wrapped in `dynamic "env"` blocks.

<details>
<summary>Stuck? Peek at the 5 completed HCL blocks</summary>

```hcl
# 1. Add "roles/aiplatform.memoryUser" inside google_project_iam_member.runtime_sa_roles
  for_each = toset([
    "roles/aiplatform.user", "roles/aiplatform.memoryUser", "roles/logging.logWriter",
    "roles/cloudtrace.agent", "roles/telemetry.tracesWriter", "roles/monitoring.metricWriter",
  ])

# 2. Uncomment both Artifact Registry service-agent bindings
resource "google_project_iam_member" "re_service_agent_ar_reader" {
  project = var.project_id
  role    = "roles/artifactregistry.reader"
  member  = "serviceAccount:service-${var.project_number}@gcp-sa-aiplatform-re.iam.gserviceaccount.com"
}
resource "google_project_iam_member" "sandbox_service_agent_ar_reader" {
  project = var.project_id
  role    = "roles/artifactregistry.reader"
  member  = "serviceAccount:service-${var.project_number}@gcp-sa-vertex-sandbox.iam.gserviceaccount.com"
}

# 3. Uncomment container_spec inside spec {}
    container_spec {
      image_uri = var.agent_image_uri
    }

# 4. Uncomment sandbox/registry env vars + secret_env inside deployment_spec {}
      env {
        name  = "SANDBOX_MODE"
        value = local.resolved_sandbox_mode
      }
      dynamic "env" {
        for_each = var.sandbox_template_name != "" ? [1] : []
        content {
          name  = "SANDBOX_TEMPLATE_NAME"
          value = var.sandbox_template_name
        }
      }
      env {
        name  = "SANDBOX_SERVICE_ACCOUNT_EMAIL"
        value = google_service_account.agent_runtime_sa.email
      }
      env {
        name  = "ENABLE_MEMORY_BANK"
        value = tostring(var.enable_memory_bank)
      }
      env {
        name  = "ENABLE_SKILL_REGISTRY"
        value = tostring(var.enable_skill_registry)
      }
      dynamic "env" {
        for_each = var.skill_registry_location != "" ? [1] : []
        content {
          name  = "SKILL_REGISTRY_LOCATION"
          value = var.skill_registry_location
        }
      }
      dynamic "env" {
        for_each = var.agent_registry_location != "" ? [1] : []
        content {
          name  = "AGENT_REGISTRY_LOCATION"
          value = var.agent_registry_location
        }
      }
      dynamic "env" {
        for_each = var.agent_registry_skills_location != "" ? [1] : []
        content {
          name  = "AGENT_REGISTRY_SKILLS_LOCATION"
          value = var.agent_registry_skills_location
        }
      }
      secret_env {
        name = "CODING_AGENT_API_KEY"
        secret_ref {
          secret  = google_secret_manager_secret.coding_agent_api_key.secret_id
          version = "latest"
        }
      }

# 5. Expand depends_on on google_vertex_ai_reasoning_engine.coding_agent
  depends_on = [
    google_project_iam_member.re_service_agent_ar_reader,
    google_project_iam_member.sandbox_service_agent_ar_reader,
    google_project_iam_member.runtime_sa_roles,
    google_project_iam_member.runtime_sa_agentregistry_viewer,
    google_service_account_iam_member.runtime_sa_self_token_creator,
    google_secret_manager_secret_iam_member.runtime_sa_secret_accessor,
    google_secret_manager_secret_iam_member.platform_service_agent_secret_accessor,
    google_secret_manager_secret_version.coding_agent_api_key_v1,
  ]
```

Full reference file: [`solution/terraform/main.tf`](../solution/terraform/main.tf).

</details>

**Check it works:**

```bash
make tf-plan
```

Expected output: `init`, `fmt -check`, `validate`, and `plan` all pass cleanly. If `fmt -check` reports spacing differences, run `terraform -chdir=starter/terraform fmt` and re-run `make tf-plan`.

---

## Step 5: Deploy with Terraform and Save Your Runtime ID

Apply the Terraform plan and export the outputs (first container boot takes 5 to 10 minutes):

```bash
make tf-apply
export REASONING_ENGINE_NAME="$(terraform -chdir=starter/terraform output -raw reasoning_engine_resource_name)"
export REASONING_ENGINE_ID="$(terraform -chdir=starter/terraform output -raw reasoning_engine_id)"
echo "Deployed: ${REASONING_ENGINE_NAME} (ID=${REASONING_ENGINE_ID})"
```

> [!IMPORTANT]
> **Update `.env` for Lab 6:** Update **both** `REASONING_ENGINE_NAME` and `REASONING_ENGINE_ID` together in `.env` so Cloud Trace and Lab 6 Online Monitors point at this deployed runtime. (Never clear or change only `REASONING_ENGINE_NAME` while leaving Lab 2's old `REASONING_ENGINE_ID` behind, because `config.py` reconstructs `reasoning_engine_name` from `REASONING_ENGINE_ID`.) Note that `outputs.tf` extracts the short ID from `.id` with `reverse(split("/", ...))[0]`, because in `hashicorp/google` `.id` is the full resource path while `.name` is only the numeric ID (and Terraform's `element(..., -1)` rejects negative indices).

**Check it works:** `echo "${REASONING_ENGINE_NAME}"` prints `projects/<YOUR_PROJECT>/locations/asia-southeast1/reasoningEngines/<NUMERIC_ID>`.

---

## Step 6: Smoke-Test Your Live Deployed Agent

Test unary `:query` (`create_session` and `list_sessions`) and streaming `:streamQuery?alt=sse` (`async_stream_query`) against the live endpoint:

```bash
# 1. Unary :query -> create a session and list sessions
SESSION_JSON=$(curl -sS -X POST \
  -H "Authorization: Bearer $(gcloud auth print-access-token)" -H "Content-Type: application/json; charset=utf-8" \
  -d '{"class_method": "create_session", "input": {"user_id": "terraform_test_user"}}' \
  "https://${GOOGLE_CLOUD_LOCATION}-aiplatform.googleapis.com/v1/${REASONING_ENGINE_NAME}:query")
echo "${SESSION_JSON}"
export SESSION_ID="$(echo "${SESSION_JSON}" | python3 -c 'import json,sys; print(json.load(sys.stdin)["output"]["id"])')"

curl -sS -X POST \
  -H "Authorization: Bearer $(gcloud auth print-access-token)" -H "Content-Type: application/json; charset=utf-8" \
  -d '{"class_method": "list_sessions", "input": {"user_id": "terraform_test_user"}}' \
  "https://${GOOGLE_CLOUD_LOCATION}-aiplatform.googleapis.com/v1/${REASONING_ENGINE_NAME}:query"

# 2. Streaming :streamQuery?alt=sse -> real coding turn
curl -sS -X POST \
  -H "Authorization: Bearer $(gcloud auth print-access-token)" -H "Content-Type: application/json; charset=utf-8" \
  -d '{"class_method": "async_stream_query", "input": {"user_id": "terraform_test_user", "session_id": "'"${SESSION_ID}"'", "message": "Create calc.py with add(a, b) and test_calc.py, run pytest -q and ruff check, and summarize the output."}}' \
  "https://${GOOGLE_CLOUD_LOCATION}-aiplatform.googleapis.com/v1/${REASONING_ENGINE_NAME}:streamQuery?alt=sse"
```

**Check it works:** `:query` returns HTTP 200 JSON with `output.id` and your session in `list_sessions`; `:streamQuery?alt=sse` streams events showing file writes, passing test execution, and a summary.

---

## Lab 5 Checkpoint

Run the automated check from the repo root:

```bash
make verify-lab LAB=5
```

This verifies zero remaining `# TODO(lab-5)` markers in [starter/main.py](../starter/main.py) and [starter/terraform/main.tf](../starter/terraform/main.tf), `terraform fmt -check`, and all IAM/env/`depends_on` wiring. Continue to **[Lab 6: Observability, Evaluation & Quality Alerts](./06-LAB-OPTIMIZE-EVAL-AND-ALERTS.md)**.

---

## Optional Reference & Deep Dive

<details>
<summary>Alternative Deployment Paths: Path 2 (Zero-AR source_code_spec) & Path 3 (agents-cli deploy)</summary>

There is no `gcloud` deploy command for Agent Runtime (`gcloud ai reasoning-engines` only supports `describe` and IAM bindings). Alongside the default Cloud Build + Terraform `container_spec` path above, you have two other zero-Docker options:

- **Path 2 (Zero-Docker AND Zero-Artifact-Registry via `source_code_spec`):** Run `make pack-agent-source` from the repo root to create a `<= 8 MB` `.tar.gz` with `./Dockerfile` at **level 0** (never nested inside a folder like `starter/`, or Cloud Build fails). Then replace `container_spec` in `starter/terraform/main.tf` with:
  ```hcl
  source_code_spec {
    inline_source { source_archive = filebase64("${path.module}/coding_agent_source.tar.gz") }
    image_spec {} # Empty block tells Agent Runtime to build ./Dockerfile
  }
  ```
- **Path 3 (Imperative Dev Prototyping via `agents-cli deploy`):**
  ```bash
  cd starter && agents-cli deploy --project "${GOOGLE_CLOUD_PROJECT}" --region "${GOOGLE_CLOUD_LOCATION}" \
    --service-name "coding-agent-cli" --cpu 2 --memory 4Gi --concurrency 5 --min-instances 0 --max-instances 10 \
    --env-vars "GOOGLE_CLOUD_AGENT_ENGINE_ENABLE_TELEMETRY=true,OTEL_SEMCONV_STABILITY_OPT_IN=gen_ai_latest_experimental,OTEL_INSTRUMENTATION_GENAI_CAPTURE_MESSAGE_CONTENT=EVENT_ONLY" \
    --dry-run
  ```
  Key gotchas: run `agents-cli infra single-project --apply` *before* your first `agents-cli deploy` (never apply Terraform on top of an imperative deploy); on Agent Runtime `--secrets` replaces the entire map so use `--update-secrets` for incremental edits; pass `--no-wait` and poll with `--status`; `--key` (CMEK) and `--agent-identity` (SPIFFE, [Lab 7](./07-LAB-OPTIONAL-SECURITY-AND-GOVERNANCE.md)) are immutable; PSC-I (`--network-attachment`) has no default internet egress. Never set reserved env vars (`GOOGLE_CLOUD_PROJECT`, `GOOGLE_CLOUD_QUOTA_PROJECT`, `GOOGLE_CLOUD_LOCATION`, `PORT`, `K_SERVICE`, `K_REVISION`, `K_CONFIGURATION`, `GOOGLE_APPLICATION_CREDENTIALS`). You can switch Lab 1 architectures (`simple`, `collaborative`, `graph`, `dynamic`, `agy_harness`) purely via `AGENT_ARCHITECTURE`, `AGY_EXECUTION_MODE`, `MAX_FIX_ROUNDS`, and `ENABLE_HITL_APPROVAL` env vars with zero `Dockerfile`/`main.py` changes.

</details>

<details>
<summary>Service Agent IAM Matrix, agy Auth & Optional Memory Bank Query</summary>

| Principal | Email Format | Required Roles | Purpose |
|---|---|---|---|
| **Agent Runtime SA** | `service-${var.project_number}@gcp-sa-aiplatform-re.iam.gserviceaccount.com` | `roles/artifactregistry.reader` (+ `cloudkms.cryptoKeyEncrypterDecrypter` for CMEK, `storage.objectCreator` for async jobs) | Pulls BYOC runtime image from Artifact Registry |
| **Agent Platform SA** | `service-${var.project_number}@gcp-sa-aiplatform.iam.gserviceaccount.com` | `roles/secretmanager.secretAccessor` (+ `artifactregistry.reader` for cross-project AR) | Fetches `secret_env` under `AGENT_IDENTITY` or cross-project pulls |
| **Agent Sandbox SA** | `service-${var.project_number}@gcp-sa-vertex-sandbox.iam.gserviceaccount.com` | `roles/artifactregistry.reader` | Pulls Lab 2's BYOC sandbox image (`coding-sandbox:v1`) |
| **Custom Runtime SA** | `coding-agent-runtime-sa@${var.project_id}.iam.gserviceaccount.com` | `aiplatform.user`, `aiplatform.memoryUser`, `agentregistry.viewer` (conditional), `secretmanager.secretAccessor`, `logging.logWriter`, `cloudtrace.agent`, `telemetry.tracesWriter`, `monitoring.metricWriter`, self `iam.serviceAccountTokenCreator` | Default runtime identity for Labs 5 and 6; upgrade to SPIFFE `AGENT_IDENTITY` + Agent Gateway in [Lab 7 (Optional)](./07-LAB-OPTIONAL-SECURITY-AND-GOVERNANCE.md) |

Inside the container, `/usr/local/bin/agy` runs under `coding-agent-runtime-sa` ADC (`AGY_ADC_AUTH=true`) with `AGY_PROJECT_ID` and `GOOGLE_CLOUD_LOCATION=global` scoped per subprocess. Never copy personal developer OAuth tokens into a shared runtime. When `enable_memory_bank = true`, `AdkApp.async_search_memory` takes only `user_id` and `query` (passing `app_name` raises `TypeError`).

</details>

<details>
<summary>Agent Runtime HTTP/NDJSON Contract, Container Sizing & Quotas</summary>

| Requirement | Specification |
|---|---|
| **Port & Health Probe** | Listen on `0.0.0.0:8080` (`PORT` env var) and return `200 OK` on `GET /`. |
| **Unary / Async (`""`, `"async"`)** | `POST /api/reasoning_engine` with `{"class_method": "...", "input": {...}}`; return `200 OK` JSON `{"output": ...}`. |
| **Streaming (`"stream"`, `"async_stream"`)** | `POST /api/stream_reasoning_engine`; return `200 OK` NDJSON (converted to SSE). Max stream duration: **15 minutes**. |
| **Bidirectional (`"bidi_stream"`)** | `POST /api/bidi_reasoning_engine` (`AgentServerMode.EXPERIMENTAL`). Max timeout: **10 minutes**. |
| **Keep-Alive Probe (Preview)** | Idle scale-down defaults to 15 min (`900s`). `keep_alive_probe` polls `GET /is_busy` every `10s` (`2xx` = busy, `412` = idle; `max_seconds` in `[900, 3600]`). Avoid reserved ports `15000, 15001, 15006, 15007, 15020, 15021`. |
| **Resources & Scaling** | `cpu`: `1, 2, 4, 6, 8` (API default `4`); `memory`: `1Gi` to `32Gi` (default `4Gi`); `min_instances`: `[0, 75]`; `max_instances`: `[1, 1000]` (`[1, 100]` with VPC-SC/PSC-I); concurrency: `2 * cpu + 1` (or multiples of `9` for async I/O). |
| **Agent Gateway BYOC CA Trust** | Bake `AGENT_GATEWAY_ROOT_CERTIFICATES` into `/usr/local/share/ca-certificates/agw-*.crt`, run `update-ca-certificates`, and point `SSL_CERT_FILE`, `REQUESTS_CA_BUNDLE`, `GRPC_DEFAULT_SSL_ROOTS_FILE_PATH`, and `AGENT_GATEWAY_ROOT_CERT_302034098528` to `/etc/ssl/certs/ca-certificates.crt`. |
| **Default Quotas (per project/region)** | `Query`/`StreamQuery`: **90 req/min**; Create/Update/Delete: **10 req/min**; Max entities: **100**; Concurrent `BidiStreamQuery`: **10/min**. Express Mode Free Tier drops to 10 query/min and 10 entities (see [Architecture Guide: Agent Runtime vs. GKE](./08-ARCHITECTURE-AGENT-RUNTIME-VS-GKE.md)). |

</details>

<details>
<summary>Day-2 Operations: CRUD, Async Query Jobs, Canary Traffic Split & Emergency Stop</summary>

**Lifecycle CRUD (`agentplatform.Client`):** Use `client.runtimes.list(...)`, `client.runtimes.get(name=runtime_name)`, and `client.runtimes.update(name=runtime_name, config={...})` (always pass `name=`, not `resource_name=`).

**Long-Running Async Query Jobs (up to 7 days):** For tasks beyond the 15-minute `:streamQuery` limit, grant `gcp-sa-aiplatform-re` `roles/storage.objectCreator` on the output bucket (and `roles/storage.objectViewer` on any input bucket) and call `client.runtimes.run_query_job(...)` + `check_query_job(name=job.name, config={"retrieve_result": True})`. Cancelled jobs report status `FAILED` with error code `1` (`CANCELLED`).

**Revisions & Canary Traffic Splitting (`v1beta1`):** Every spec update creates an immutable revision (limits: 950/agent, 6,000/project/region; configure `revision_garbage_collection_strategy.keep_n_latest.max_revisions`). Percentages must sum to 100 across `ACTIVE` revisions; switch back to `trafficSplitAlwaysLatest: {}` before changing Agent Gateway bindings:

```bash
curl -X PATCH -H "Authorization: Bearer $(gcloud auth print-access-token)" -H "Content-Type: application/json; charset=utf-8" \
  -d '{"trafficConfig":{"trafficSplitManual":{"targets":[{"runtimeRevisionName":"'"${STABLE_REVISION_NAME}"'","percent":90},{"runtimeRevisionName":"'"${CANARY_REVISION_NAME}"'","percent":10}]}}}' \
  "https://${GOOGLE_CLOUD_LOCATION}-aiplatform.googleapis.com/v1beta1/${REASONING_ENGINE_NAME}?update_mask=traffic_config"
```

**Emergency Stop Containment SLAs:**

| Action | Propagation | Kills Active Streams? | Notes |
|---|---|---|---|
| `client.runtimes.delete(name=..., force=True)` | Seconds to minutes | Yes | `force=True` required if child sessions/memories exist |
| `trafficSplitManual` -> 100% stable | Seconds to minutes | New traffic shifts immediately | Best zero-downtime rollback for Lab 6 alerts |
| IAM Deny / Agent Gateway UAP / PAB | 2 to 7+ min (groups: hours) | No | Always pair policy revocations with traffic rollback or runtime delete |

**Official Docs:** [Deploy with Terraform](https://docs.cloud.google.com/gemini-enterprise-agent-platform/scale/runtime/use-terraform) | [Runtime Contract](https://docs.cloud.google.com/gemini-enterprise-agent-platform/scale/runtime/runtime-contract) | [Manage Deployed Agents](https://docs.cloud.google.com/gemini-enterprise-agent-platform/scale/runtime/manage-deployed-agents) | [Revisions & Traffic](https://docs.cloud.google.com/gemini-enterprise-agent-platform/scale/runtime/manage-revisions-and-traffic) | [Quotas](https://docs.cloud.google.com/gemini-enterprise-agent-platform/resources/agent-quotas)

</details>
