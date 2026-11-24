# Lab 2: Custom Sandbox (BYOC), Lifecycle Management, and Execution

In this lab, you'll swap Lab 1's local subprocess execution for gVisor-isolated Managed Sandboxes on Google Cloud (using either a custom BYOC container built in Cloud Build or the zero-build Shell Sandbox). You'll build a reusable lifecycle manager, wire a custom ADK `BaseEnvironment`, and confirm that untrusted commands inside the sandbox have zero access to cloud credentials or the metadata server.

**Duration:** 60 min (Full-Day) | 40 min (Half-Day Fast-Track) | **Previous:** [Lab 1: Setup & Build ADK Agent](./01-LAB-SETUP-AND-BUILD-ADK.md) | **Next:** [Lab 3: Managed Sessions, Memory Bank & Telemetry](./03-LAB-SESSIONS-MEMORY-FEEDBACK.md)

## Files You Will Edit

| Step | File | Where to edit | What you're adding |
|---|---|---|---|
| Step 1 | `.env` + GCP setup | `SANDBOX_IMAGE_URI`, `REASONING_ENGINE_NAME`, `SANDBOX_MODE` | Smoke-test pre-built runner, push BYOC image via Cloud Build (or use `shell`), grant AR IAM, create backing instance |
| Step 2 | [`starter/coding_agent/tools/sandbox_lifecycle.py`](../starter/coding_agent/tools/sandbox_lifecycle.py) | `create_template()`, `create_sandbox()`, `pause_sandbox()`, `snapshot_sandbox()` (`# TODO(lab-2)`) | Managed template, sandbox, pause, and snapshot lifecycle calls |
| Step 3 | [`starter/coding_agent/tools/sandbox_execution.py`](../starter/coding_agent/tools/sandbox_execution.py) | `execute_byoc_command()`, `AgentPlatformSandboxEnvironment.execute()` (`# TODO(lab-2)`) | BYOC `/exec` dual transport and ADK `BaseEnvironment.execute()` |
| Step 4 | [`starter/coding_agent/agent.py`](../starter/coding_agent/agent.py) | `_build_remote_execution_components()` (`# TODO(lab-2)`) | Wire `AgentPlatformSandboxEnvironment` (`shell`/`byoc`) and `build_code_execution_executor` |

**Already built for you (no edits needed):** [`starter/sandbox_image/Dockerfile`](../starter/sandbox_image/Dockerfile), [`starter/sandbox_image/runner.py`](../starter/sandbox_image/runner.py) (with baked `/usr/local/bin/agy` and allowlisted `/exec` `env`), CRUD helpers (`get`, `list`, `update`, `resume`, `delete`) in `sandbox_lifecycle.py`, and `execute_shell_command()`, `execute_code_snippet()`, `build_code_execution_executor()`, plus `initialize()`/`read_file()`/`write_file()` in `sandbox_execution.py`.

**Need help or running behind?** Point Antigravity at [`.agents/skills/agent-platform-sandbox-byoc`](../.agents/skills/agent-platform-sandbox-byoc/SKILL.md), or run `make fast-forward LAB=2` to sync only Lab 2 without touching Labs 3-8.

---

## Step 1: Test and Push the BYOC Image, Grant IAM, and Create the Backing Instance

You don't need Docker installed locally. First inspect the pre-built [`starter/sandbox_image/Dockerfile`](../starter/sandbox_image/Dockerfile) (non-root `USER appuser`, `WORKDIR /workspace`, `EXPOSE 8080`, opt-in `ARG INSTALL_AGY_CLI=true`) and [`starter/sandbox_image/runner.py`](../starter/sandbox_image/runner.py) (`GET /health` with `agy_cli_available`, `POST /exec` with workspace confinement and an explicit `env` allowlist), then smoke-test the runner locally in plain Python:

```bash
grep -E "^(FROM|ARG|USER|WORKDIR|EXPOSE|ENTRYPOINT)" starter/sandbox_image/Dockerfile
make test-sandbox-local
```

Next, pick **BYOC (recommended)** or the **zero-build fast-track**:
- **Zero-build fast-track:** Skip the Artifact Registry / Cloud Build commands below and use `SANDBOX_MODE=shell` in Step 4. Managed Shell Sandboxes work immediately in `asia-southeast1` with zero image builds.
- **BYOC container path:** Create one Docker repository in Bangkok (`asia-southeast3`) and submit the build remotely via Cloud Build (Singapore `asia-southeast1` sandboxes pull directly from Bangkok Artifact Registry, so one repo covers everything):

```bash
source .env
export AR_LOCATION="${AR_LOCATION:-asia-southeast3}"
gcloud artifacts repositories create coding-agent-repo \
  --repository-format=docker --location="$AR_LOCATION" --project="$GOOGLE_CLOUD_PROJECT" || true
export SANDBOX_IMAGE_URI="${AR_LOCATION}-docker.pkg.dev/${GOOGLE_CLOUD_PROJECT}/coding-agent-repo/coding-sandbox:v1"
make push-sandbox
```

Grant the **Agent Sandbox Service Agent** pull access to `coding-agent-repo`:

> [!CAUTION]
> **Grant `roles/artifactregistry.reader` to `gcp-sa-vertex-sandbox`, NOT `gcp-sa-aiplatform-re`!** `gcp-sa-vertex-sandbox` pulls Lab 2 BYOC Sandbox images; `gcp-sa-aiplatform-re` pulls Lab 5 Agent Runtime images. Using the wrong service agent breaks template image pulls.

```bash
gcloud artifacts repositories add-iam-policy-binding coding-agent-repo \
  --location="${AR_LOCATION:-asia-southeast3}" --project="$GOOGLE_CLOUD_PROJECT" \
  --member="serviceAccount:service-${GOOGLE_CLOUD_PROJECT_NUMBER}@gcp-sa-vertex-sandbox.iam.gserviceaccount.com" \
  --role="roles/artifactregistry.reader"
```

Finally, create a standalone backing instance (`ReasoningEngine`) in `asia-southeast1` (~3 seconds, zero code deploy). It powers both Lab 2 Sandboxes and Lab 3 Managed Sessions / Memory Bank until you deploy your agent once in Lab 5:

```bash
(cd starter && uv run python -m coding_agent.tools.sandbox_lifecycle create-instance)
```

Save the printed `instance_name` to `REASONING_ENGINE_NAME` (and its trailing numeric ID to `REASONING_ENGINE_ID`) in `.env`, plus `SANDBOX_IMAGE_URI` if you pushed the BYOC image.

**Check it works:** `make test-sandbox-local` prints 5 `[PASS]` lines (including HTTP 400 rejections for `cwd='/etc'` and disallowed `env` keys), and `create-instance` prints JSON with `projects/.../locations/asia-southeast1/reasoningEngines/...`.

---

## Step 2: Implement Sandbox Lifecycle Hooks

**File:** [`starter/coding_agent/tools/sandbox_lifecycle.py`](../starter/coding_agent/tools/sandbox_lifecycle.py), methods `create_template()`, `create_sandbox()`, `pause_sandbox()`, and `snapshot_sandbox()` (`# TODO(lab-2)`)

All CRUD helpers (`get`, `list`, `update`, `resume`, `delete`) and the `v1beta1` client initializer (`build_platform_client()`) are pre-filled. Wire the four core write operations on `self.sandboxes`:

- **`create_template()`**: Call `self.sandboxes.templates.create(name=parent_name, display_name=display_name, config=config)` and return `_summarize_template(_extract_response(operation))`. Templates create a warm pool so later sandboxes spin up in seconds instead of up to 2 minutes.
- **`create_sandbox()`**: Pass `name=parent_name` and `config=config`, adding `spec=spec` only when `spec is not None`. Call `self.sandboxes.create(**kwargs)` and return `_summarize_sandbox(_extract_response(operation))`. Always set an explicit `ttl` (default is 2h).
- **`pause_sandbox()`**: Call `self.sandboxes.pause(name=sandbox_name, config={"wait_for_completion": wait_for_completion})` and return `_summarize_sandbox(_extract_response(operation))`.
- **`snapshot_sandbox()`**: Call `self.sandboxes.snapshots.create(source_sandbox_environment_name=sandbox_name, config={"display_name": display_name, "ttl": ttl, "wait_for_completion": wait_for_completion})`. Read `getattr(getattr(operation, "response", None), "name", "")` first so an `/operations/...` LRO path is never treated as a snapshot name; if empty, match `display_name` in `self.list_snapshots(instance_name=parent)`.

> [!WARNING]
> **Two `google-cloud-agentplatform==2.10.0` quirks:**
> 1. Never send `spec` and `sandbox_environment_template` together to `sandboxes.create()`.
> 2. Never pass `config={"wait_for_completion": True}` to `.delete()`: `Delete*Config` accepts only `http_options` and raises `pydantic.ValidationError`. Use the pre-filled `delete_sandbox()` / `delete_snapshot()` / `delete_template()` helpers, which poll each delete LRO cleanly.

<details>
<summary>Stuck? Peek at the code</summary>

```python
# Inside create_template() (after `config` is built):
        operation = self.sandboxes.templates.create(name=parent_name, display_name=display_name, config=config)
        summary = _summarize_template(_extract_response(operation))
        logger.info("Created sandbox template: %s", summary.name)
        return summary

# Inside create_sandbox() (after `config` is built):
        kwargs: dict[str, Any] = {"name": parent_name, "config": config}
        if spec is not None:
            kwargs["spec"] = spec
        operation = self.sandboxes.create(**kwargs)
        summary = _summarize_sandbox(_extract_response(operation))
        logger.info("Created sandbox: %s (state=%s)", summary.name, summary.state)
        return summary

# Inside pause_sandbox():
        operation = self.sandboxes.pause(name=sandbox_name, config={"wait_for_completion": wait_for_completion})
        summary = _summarize_sandbox(_extract_response(operation))
        logger.info("Paused sandbox: %s (state=%s)", summary.name or sandbox_name, summary.state)
        return summary

# Inside snapshot_sandbox():
        operation = self.sandboxes.snapshots.create(
            source_sandbox_environment_name=sandbox_name,
            config={"display_name": display_name, "ttl": ttl, "wait_for_completion": wait_for_completion},
        )
        resp = getattr(operation, "response", None)
        if getattr(resp, "name", None):
            return _summarize_snapshot(resp)
        parent = instance_name or self.instance_name or _infer_parent_instance(sandbox_name)
        if parent:
            matched = [s for s in self.list_snapshots(instance_name=parent) if s.display_name == display_name]
            if matched:
                return matched[0]
        raise RuntimeError(f"Snapshot {display_name!r} not returned by operation {getattr(operation, 'name', '')!r}.")
```

</details>

**Check it works:** Run the full Template -> Sandbox -> Pause -> Resume -> Snapshot -> Branch -> Delete demo (pass `SANDBOX_DEMO_MODE=byoc` once your image is pushed):
```bash
make sandbox-lifecycle-demo
```
Expected output: JSON showing timings for each step and sequential cleanup with zero leftover resources.

---

## Step 3: Implement BYOC Execution and `BaseEnvironment.execute()`

**File:** [`starter/coding_agent/tools/sandbox_execution.py`](../starter/coding_agent/tools/sandbox_execution.py), functions `execute_byoc_command()` and `AgentPlatformSandboxEnvironment.execute()` (`# TODO(lab-2)`)

`execute_shell_command()`, `execute_code_snippet()`, `build_code_execution_executor()`, and `AgentPlatformSandboxEnvironment`'s `initialize()`, `read_file()`, and `write_file()` methods are pre-filled. Wire the two remaining execution hooks:

- **`execute_byoc_command()`**: Import `httpx` (at top-level or inline) and build `payload = {"command": command, "cwd": cwd, "timeout": max(1, int(timeout))}` (plus `"env": dict(env)` if provided).
  - If `runner_base_url` is set (local test or VPC PSC-E), POST JSON `payload` to `f"{runner_base_url.rstrip('/')}/exec"` via `httpx.Client` with optional `Authorization: Bearer <token>`, call `resp.raise_for_status()`, and return `_normalize_command_response(resp.json(), elapsed_ms)`.
  - Otherwise require `client` and `sandbox_name`, fetch `sandbox_env = sandboxes_ns.get(name=sandbox_name)`, resolve `token` (`access_token`, else `generate_sandbox_access_token(client, service_account_email)`, else `fetch_iam_bearer_token()` when `use_iam_bearer=True`), call `sandboxes_ns.send_command(http_method="POST", path="exec", access_token=token, request_dict=payload, sandbox_environment=sandbox_env)`, and return `_normalize_command_response(raw_response, elapsed_ms)`. (`send_command()` doesn't raise on 401/403 and can return an empty body, which `_normalize_command_response()` validates.)
- **`AgentPlatformSandboxEnvironment.execute()`**: Call `await self.initialize(ctx=ctx)`, dispatch via `await asyncio.to_thread(...)` to `execute_byoc_command()` (when `self._mode == "byoc" or self._runner_base_url`, setting `use_iam_bearer=(not bool(self._runner_base_url) and not bool(self._service_account_email))`) or `execute_shell_command()` (when `shell`), and return `ExecutionResult(exit_code=out.returncode, stdout=out.stdout, stderr=out.stderr, timed_out=out.timed_out)`.

> [!IMPORTANT]
> **Three ADK `BaseEnvironment` rules:**
> 1. `BaseEnvironment` has exactly 3 abstract methods: `execute`, `read_file`, and `write_file`. Do not add a fake `edit_file` override (`EditFileTool` layers on `read_file` + `write_file`).
> 2. Keep keyword-only `*, ctx: Context | None = None` on all hooks so ADK passes `ctx.state` without deprecation warnings.
> 3. Under `EnvironmentScope.SESSION`, one instance serves many sessions. Never short-circuit `initialize()` on `if self._is_initialized: return`; always check `ctx.state[self.STATE_KEY]` (already done in pre-filled `initialize()`).

<details>
<summary>Stuck? Peek at the code</summary>

```python
# Inside execute_byoc_command():
    import httpx

    start = time.monotonic()
    payload: dict[str, Any] = {"command": command, "cwd": cwd, "timeout": max(1, int(timeout))}
    if env:
        payload["env"] = dict(env)

    if runner_base_url:
        headers = {"Content-Type": "application/json"}
        bearer = access_token or (fetch_iam_bearer_token() if use_iam_bearer else None)
        if bearer:
            headers["Authorization"] = f"Bearer {bearer}"
        with httpx.Client(timeout=max(float(timeout) + 10.0, 15.0)) as http_client:
            resp = http_client.post(f"{runner_base_url.rstrip('/')}/exec", json=payload, headers=headers)
            resp.raise_for_status()
            return _normalize_command_response(resp.json(), max(0, int((time.monotonic() - start) * 1000)))

    if client is None or not sandbox_name:
        raise ValueError("execute_byoc_command() requires `runner_base_url` OR both `client` and `sandbox_name`.")

    sandboxes_ns = get_sandboxes_namespace(client)
    sandbox_env = sandboxes_ns.get(name=sandbox_name)
    token = access_token or (
        generate_sandbox_access_token(client, service_account_email) if service_account_email
        else (fetch_iam_bearer_token() if use_iam_bearer else None)
    )
    if not token:
        raise ValueError("Managed BYOC requires `access_token`, `service_account_email`, or `use_iam_bearer=True`.")
    raw = sandboxes_ns.send_command(
        http_method="POST", path="exec", access_token=token, request_dict=payload, sandbox_environment=sandbox_env,
    )
    return _normalize_command_response(raw, max(0, int((time.monotonic() - start) * 1000)))
```

```python
# Inside AgentPlatformSandboxEnvironment.execute():
        await self.initialize(ctx=ctx)
        cwd_str = str(self._working_dir)
        sandbox_name = self._get_active_sandbox_name(ctx)
        if self._mode == "byoc" or self._runner_base_url:
            out = await asyncio.to_thread(
                execute_byoc_command, command=command, cwd=cwd_str, timeout=timeout if timeout is not None else 60,
                client=None if self._runner_base_url else self._get_client(), sandbox_name=sandbox_name,
                service_account_email=self._service_account_email, runner_base_url=self._runner_base_url,
                use_iam_bearer=(not bool(self._runner_base_url) and not bool(self._service_account_email)),
            )
        else:
            if not sandbox_name:
                raise RuntimeError("No active Managed Sandbox found after initialize().")
            out = await asyncio.to_thread(execute_shell_command, self._get_client(), sandbox_name, command, cwd=cwd_str, timeout=timeout)
        return ExecutionResult(exit_code=out.returncode, stdout=out.stdout, stderr=out.stderr, timed_out=out.timed_out)
```

</details>

**Check it works:** Verify the CLI loads cleanly and (against any active sandbox) run the isolation probe:
```bash
(cd starter && uv run python -m coding_agent.tools.sandbox_execution --help)
# Optional live probe:
# (cd starter && uv run python -m coding_agent.tools.sandbox_execution probe-isolation --mode shell --sandbox-name "$SANDBOX_RESOURCE_NAME")
```
Expected output: `probe-isolation` prints `PASS:METADATA_UNREACHABLE` and `PASS:NO_SUDO` as `appuser`.

---

## Step 4: Wire Remote Sandboxes Into `agent.py`

**File:** [`starter/coding_agent/agent.py`](../starter/coding_agent/agent.py), function `_build_remote_execution_components()` (`# TODO(lab-2)`)

Connect `AgentPlatformSandboxEnvironment` and `build_code_execution_executor()` into the root agent so `SANDBOX_MODE` switches local vs. remote execution across every ADK architecture.

What goes inside `_build_remote_execution_components(settings)`:
- When `settings.sandbox_mode in {"shell", "byoc"}`: import `AgentPlatformSandboxEnvironment`, instantiate it with `project_id=settings.require_gcp_project()`, `location=settings.google_cloud_location`, `instance_name=settings.reasoning_engine_name`, `template_name=(settings.sandbox_template_name or None) if settings.sandbox_mode == "byoc" else None` (never forward a BYOC template into `shell` mode), `sandbox_name=settings.sandbox_resource_name or None`, `mode=settings.sandbox_mode`, `working_dir=Path("/workspace")`, `ttl=settings.sandbox_ttl`, `service_account_email=settings.sandbox_service_account_email or None`, and `runner_base_url=settings.sandbox_runner_base_url or None`. Wrap in `EnvironmentToolset(environment=remote_env, max_output_chars=settings.max_output_chars)` and return `(remote_env, [toolset], None)`.
- When `settings.sandbox_mode == "code_execution"`: import `build_code_execution_executor`, call `build_code_execution_executor(sandbox_resource_name=settings.sandbox_resource_name or None, agent_engine_resource_name=settings.reasoning_engine_name or None)`, and return `(None, [], code_executor)`.

<details>
<summary>Stuck? Peek at the code</summary>

```python
def _build_remote_execution_components(settings: Settings) -> tuple[BaseEnvironment | None, list[Any], Any | None]:
    if settings.sandbox_mode in {"shell", "byoc"}:
        from coding_agent.tools.sandbox_execution import AgentPlatformSandboxEnvironment

        remote_env = AgentPlatformSandboxEnvironment(
            project_id=settings.require_gcp_project(), location=settings.google_cloud_location,
            instance_name=settings.reasoning_engine_name,
            template_name=(settings.sandbox_template_name or None) if settings.sandbox_mode == "byoc" else None,
            sandbox_name=settings.sandbox_resource_name or None, mode=settings.sandbox_mode,  # type: ignore[arg-type]
            working_dir=Path("/workspace"), ttl=settings.sandbox_ttl,
            service_account_email=settings.sandbox_service_account_email or None,
            runner_base_url=settings.sandbox_runner_base_url or None,
        )
        return remote_env, [EnvironmentToolset(environment=remote_env, max_output_chars=settings.max_output_chars)], None

    if settings.sandbox_mode == "code_execution":
        from coding_agent.tools.sandbox_execution import build_code_execution_executor

        code_executor = build_code_execution_executor(
            sandbox_resource_name=settings.sandbox_resource_name or None,
            agent_engine_resource_name=settings.reasoning_engine_name or None,
        )
        return None, [], code_executor
    return None, [], None
```

</details>

**Check it works:** Set `SANDBOX_MODE=shell` in `.env` (or create a BYOC template with `(cd starter && uv run python -m coding_agent.tools.sandbox_lifecycle create-template --kind byoc --display-name coding-byoc-tpl)` and set `SANDBOX_MODE=byoc` + `SANDBOX_TEMPLATE_NAME`), then test in `adk web`:
```bash
(cd starter && uv run adk web --port 8000)
```
Ask: *"Run `id && whoami` and check if `http://169.254.169.254/computeMetadata/v1/` is reachable."* Confirm commands run as `appuser` inside `/workspace` with the metadata server unreachable.

---

## Step 5: Lab 2 Checkpoint & Cleanup

Run the Lab 2 verifier from the repo root and delete temporary demo sandboxes so idle compute stops billing:

```bash
make verify-lab LAB=2
# Delete temporary demo sandboxes/snapshots (add --include-templates to remove templates too):
(cd starter && uv run python -m coding_agent.tools.sandbox_lifecycle cleanup-all)
```

Keep `REASONING_ENGINE_NAME` in `.env` for Lab 3, then continue to **[Lab 3: Managed Sessions, Memory Bank, Feedback Service & Runtime Telemetry](./03-LAB-SESSIONS-MEMORY-FEEDBACK.md)**.

---

## Optional Reference & Deep Dive

<details>
<summary>Google Cloud's 3 Sandbox Surfaces &amp; 4 Scale Sandbox Types</summary>

| Surface | Managed By | Key Characteristics | Covered In |
|---|---|---|---|
| 1. Agent Platform Scale Sandboxes (`scale/sandbox`) | `agentplatform.Client.sandboxes.*` under a parent `ReasoningEngine` | gVisor containers: Code Execution, Shell, Computer Use, BYOC. No built-in FQDN allowlist field (use PSC-I + Cloud NGFW/SWP). | This Lab (Lab 2) |
| 2. Managed Agents API Sandbox (Pre-GA) | `google.genai` Interactions API (`global` only) | Built-in `antigravity-preview-05-2026` harness with native network allowlist and `env_id` sharing. Pre-GA. | Reference contrast |
| 3. Self-Hosted GKE Agent Sandbox (`kubernetes-sigs/agent-sandbox`) | Kubernetes CRDs (`Sandbox`, `SandboxTemplate`, `SandboxWarmPool`, `PodSnapshot`) + `sandbox-router` (`8888`) | Self-managed GKE clusters with GPU/TPU, `<1s` warm pools, Kata/gVisor, Kubernetes `NetworkPolicy`. | [Lab 8](./08-ARCHITECTURE-AGENT-RUNTIME-VS-GKE.md) |

Never mix data-plane APIs across sandbox categories (Shell uses `execute_bash()`, Code Execution uses `execute_code()`, BYOC / Computer Use use `generate_access_token()` + `send_command()`):

| Sandbox Type | Spec / Template Key | Execution Path | Network Access | Snapshots | Max TTL |
|---|---|---|---|---|---|
| Code Execution | `code_execution_environment` (`LANGUAGE_PYTHON` / `LANGUAGE_JAVASCRIPT`) | `execute_code()` or `AgentEngineSandboxCodeExecutor` (100 MB payload cap, preinstalled scientific stack, no `pip install`) | None | Not supported | 14 days (`execute_code` resets TTL) |
| Shell Sandbox | `shell_environment: {}` or `DEFAULT_CONTAINER_CATEGORY_SHELL_SANDBOX` | `execute_bash()` (IAM/ADC auto-auth, stateless fresh shell per call under `/workspace`) | Off by default | Supported | 2h default, up to 7d |
| Computer Use | `DEFAULT_CONTAINER_CATEGORY_COMPUTER_USE` | `generate_access_token()` + `send_command()`, CDP WebSocket (`generate_browser_ws_headers`), VNC/noVNC | Off by default | Supported | 2h default |
| Custom Container (BYOC) | `custom_container_environment` on `SandboxEnvironmentTemplate` | Declared TCP `ports` (`8080`) + container runner (`/exec`, WebSocket, PTY, or PSC-E) | Off by default; direct or PSC-I | Supported (same CPU arch, runtime version, and `image_uri` required) | 2h default, up to 7d |

</details>

<details>
<summary>Cloud Build Legacy Builder Gotcha, BYOC Runner Contract &amp; <code>agy</code> Boundary</summary>

- **Cloud Build legacy builder (`COPY --chmod` fails):** `gcloud builds submit --region=asia-southeast3` uses Cloud Build's legacy Docker builder without BuildKit, rejecting `COPY --chmod=0644`. Always split permissions into `COPY --chown=root:root runner.py ...` and `RUN chmod 0644 ...`.
- **Runner contract & allowlisted `/exec` `env`:** BYOC images need Linux, non-root execution, and a runner on a declared TCP port (docs reference [AX](https://agentexecutor.io/) and [Substrate](https://github.com/agent-substrate/substrate)). `runner.py` exposes `GET /health` (`agy_cli_available`) and `POST /exec` returning `{stdout, stderr, returncode, duration_ms}`, accepting `"env"` strictly from `ALLOWED_EXEC_ENV_KEYS` (`AGY_ADC_AUTH`, `AGY_CLI_DISABLE_AUTO_UPDATE`, `GOOGLE_CLOUD_PROJECT`, `GOOGLE_CLOUD_LOCATION`, `GOOGLE_CLOUD_QUOTA_PROJECT`, `GEMINI_API_KEY`) scoped to that single child process (never written to disk or logged).
- **`agy` CLI inside BYOC sandboxes:** Inside an air-gapped BYOC sandbox (`internet_access=False`, no metadata server), `which agy` and `/health` pass while `agy -p` exits `1` (`authentication required`). That's why `AGY_EXECUTION_MODE=auto` prefers running `agy` in the trusted Agent Runtime (Lab 5) via Custom SA ADC while running untrusted `pytest`/`ruff`/`bandit` inside the air-gapped BYOC sandbox, unless you enable PSC-I egress and inject an ephemeral Secret Manager key per `/exec` call.
- **Image scanning:** Enable Artifact Registry Vulnerability Scanning on `coding-agent-repo`; Managed Sandboxes do not run an in-guest IDS or pre-deployment CVE scanner.

</details>

<details>
<summary>Network Egress (PSC-I, Cloud NGFW, SWP), Private Ingress (PSC-E), VPC-SC &amp; CMEK</summary>

Managed Sandboxes have no built-in domain allowlist field:
- **Air-gapped (`internet_access: False`):** Best default when tools are baked into your BYOC image.
- **Direct public egress (`internet_access: True`, no `network_attachment`):** Unrestricted `0.0.0.0/0` internet while blocking RFC 1918 and `169.254.0.0/16`; no FQDN filtering.
- **FQDN / URL allowlisting via PSC-I:** Add `customer_vpc_network` + `network_attachment` (min `/28` subnet) to `egress_control_config`, then enforce **Cloud NGFW** (`--dest-fqdns=...` + default-deny `0.0.0.0/0` at priority `65000` with logging), **Secure Web Proxy (SWP)** for L7 TLS/URL filtering, **Cloud DNS Peering** (public DNS forwarding is disabled in VPC-bridged sandboxes), and **Cloud NAT** if outbound internet is needed. For Shared VPC, grant `roles/compute.networkUser` on the host project to `service-PROJECT_NUMBER@gcp-sa-aiplatform.iam.gserviceaccount.com`.
- **Private ingress (PSC-E):** Set `ingress_control_config.private_service_connect_config.enable_private_service_connect: True` on the template and target `sandbox.connection_info.service_attachment` (limit: 1 consumer project, same project as the sandbox).
- **VPC-SC & CMEK (see [Lab 7](./07-LAB-OPTIONAL-SECURITY-AND-GOVERNANCE.md)):** Add `aiplatform.googleapis.com`, `storage.googleapis.com`, and `artifactregistry.googleapis.com` to Restricted Services before creating sandboxes and route `*.googleapis.com` / `pkg.dev` via `199.36.153.4/30`. Configure CMEK (`encryption_spec.kms_key_name`, single-region, immutable) when creating the parent `ReasoningEngine`, granting `roles/cloudkms.cryptoKeyEncrypterDecrypter` to `gcp-sa-aiplatform-re` (configure AR CMEK separately).

</details>

<details>
<summary>Identity Isolation, TTLs, Cold-Start Latencies &amp; Logging Caveats</summary>

| Dimension | Verified Behavior &amp; Operational Impact |
|---|---|
| Identity isolation | Parent Agent Runtime SA and `gcp-sa-vertex-sandbox` are never reachable inside the sandbox. Commands run as `appuser` / `sandbox-untrusted` (0 IAM roles, `169.254.169.254:80` blocked). Run all authenticated GCP API calls in the parent runtime. |
| TTLs | 2h default if omitted; up to 7d max for BYOC; up to 14d max for Code Execution (`execute_code` resets TTL). Always set an explicit `ttl`. |
| Provisioning latency | Cold start (unprovisioned template): up to 2 minutes. Warm template spin-up, pause/resume, or snapshot restore: seconds (~20s typical for Shell; `<1s` for Code Execution). |
| Cloud Audit Logs | `ADMIN_WRITE` is always on. `ADMIN_READ` (`Get`/`List`) and `DATA_WRITE` (`ExecuteSandboxEnvironment`, `BidiExecuteSandboxEnvironment`, `AuthorizeSandboxEnvironmentAccess`, `ExecuteCode`) are off by default; enable both. Inside VPC-SC, request/response payloads are omitted. Subprocesses, syscalls, and file writes inside the container are not captured. |
| `stdout` / `stderr` blind spot | Automatic `reasoning_engine_stdout` / `reasoning_engine_stderr` logs apply only to the parent `ReasoningEngine`, not child sandboxes. Log sandbox outputs explicitly in parent ADK callbacks ([Lab 3](./03-LAB-SESSIONS-MEMORY-FEEDBACK.md)). |

**Canonical docs:** [Managed Sandboxes](https://docs.cloud.google.com/gemini-enterprise-agent-platform/scale/sandbox) | [Custom Containers (BYOC)](https://docs.cloud.google.com/gemini-enterprise-agent-platform/scale/sandbox/custom-containers) | [Manage Templates](https://docs.cloud.google.com/gemini-enterprise-agent-platform/scale/sandbox/manage-templates) | [Manage Snapshots](https://docs.cloud.google.com/gemini-enterprise-agent-platform/scale/sandbox/manage-snapshots) | [Shell Quickstart](https://docs.cloud.google.com/gemini-enterprise-agent-platform/scale/sandbox/shell-sandbox-quickstart) | [VPC-SC & PSC-I](https://docs.cloud.google.com/gemini-enterprise-agent-platform/scale/sandbox/configure-vpc-sc) | [ADK EnvironmentToolset](https://adk.dev/integrations/environment-toolset/)

</details>
