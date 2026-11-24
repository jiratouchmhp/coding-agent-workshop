# Lab 4: Extend with Skill Registry & Agent Registry

In this lab, you'll validate and publish the `secure-code-review` skill to Google Cloud, wire ADK's `SkillToolset` so your coding agent loads skills on demand inside Lab 2's sandbox, and configure `AgentRegistry` to discover MCP servers and remote A2A agents. Once this lab passes, your local `coding_agent/` package has every capability wired and ready for a single deployment in Lab 5.

**Duration:** 40 min (Full-Day) | 30 min (Half-Day Fast-Track)  
**Previous:** [Lab 3: Managed Sessions, Memory Bank, Telemetry & Feedback](./03-LAB-SESSIONS-MEMORY-FEEDBACK.md) | **Next:** [Lab 5: Deploy & Manage the Complete Coding Agent on Agent Runtime (CLI & Terraform)](./05-LAB-DEPLOY-RUNTIME-TERRAFORM.md)

## Files You Will Edit

| Step | File | Where to edit | What you're adding |
|---|---|---|---|
| Step 1 | [starter/skills_to_register/secure-code-review/SKILL.md](../starter/skills_to_register/secure-code-review/SKILL.md) | Inspect only (`make package-skill`) | Validate all 16 Skill Registry rules and build `dist/secure-code-review.zip` |
| Step 2 | [starter/coding_agent/tools/registry_loader.py](../starter/coding_agent/tools/registry_loader.py) | `SkillRegistryPublisher.create_skill()`, `build_skill_registry_toolset()`, `build_agent_registry_integrations()` | Publish a skill directory, wire `GCPSkillRegistry` + `SkillToolset` with local fallback, and configure `AgentRegistry` MCP/A2A discovery |
| Step 3 | Live GCP publish (CLI) | `registry_loader publish-skill` & optional `gcloud alpha agent-registry skills` | Publish `secure-code-review` to Vertex AI Skill Registry (`us-central1`) and optionally activate an Agent Registry standalone skill (`global`) |
| Step 4 | [starter/coding_agent/agent.py](../starter/coding_agent/agent.py) | `_build_optional_skill_toolset()` | Attach `build_skill_registry_toolset()` to the coding agent reusing Lab 2's active sandbox environment |
| Step 5 | Checkpoint | `registry_loader offline-check` & `make verify-lab LAB=4` | Verify local fallback, 16-rule packaging, and zero remaining `# TODO(lab-4)` markers |

**Already built for you (no edits needed):** The ready-made skill package in [`starter/skills_to_register/secure-code-review/`](../starter/skills_to_register/secure-code-review/SKILL.md) (including [`references/owasp-checklist.md`](../starter/skills_to_register/secure-code-review/references/owasp-checklist.md)), plus `GoogleApiAuth`, `OidcIdTokenAuth`, `make_google_auth_header_provider`, `discover_agent_registry_catalog`, and `SkillRegistryPublisher`'s `list_skills`, `update_skill`, `search_skills`, and revision helpers in `registry_loader.py`.

**Stuck or catching up?** Ask your IDE agent with [`.agents/skills/agent-platform-governance-and-registries/SKILL.md`](../.agents/skills/agent-platform-governance-and-registries/SKILL.md), or run `make fast-forward LAB=4` to sync only Lab 4 without spoiling Labs 5-8.

---

## Step 1: Validate & Package the Ready-Made Skill

**Files:** [starter/skills_to_register/secure-code-review/SKILL.md](../starter/skills_to_register/secure-code-review/SKILL.md) and [references/owasp-checklist.md](../starter/skills_to_register/secure-code-review/references/owasp-checklist.md)

Skill Registry checks uploaded ZIP payloads asynchronously inside a long-running operation, so catching frontmatter or archive mistakes locally saves minutes of waiting on failed uploads. Open `SKILL.md` to see how its YAML frontmatter (`name`, `description`, `license`) and progressive-disclosure reference (`references/owasp-checklist.md`) are structured, then run the validator and packager.

**Check it works:**

```bash
python3 scripts/package_registry_skill.py starter/skills_to_register/secure-code-review --dry-run
make package-skill
```

Expected output: `Result: 16/16 atomic checks passed.` and `Wrote validated archive: dist/secure-code-review.zip`. (Add `--agent-registry` to also verify the stricter 1 MB ZIP and root `SKILL.md` limits required by Agent Registry standalone skills.)

---

## Step 2: Implement Skill Registry & Agent Registry Loaders

**File:** [starter/coding_agent/tools/registry_loader.py](../starter/coding_agent/tools/registry_loader.py) -> `SkillRegistryPublisher.create_skill()`, `build_skill_registry_toolset()`, and `build_agent_registry_integrations()` (`# TODO(lab-4)`)

You'll edit three functions here: publishing a skill directory to Vertex AI Skill Registry, building ADK's `SkillToolset` backed by `GCPSkillRegistry` with a safe local fallback, and configuring `AgentRegistry` in `asia-southeast3` to discover MCP servers and remote A2A agents.

> [!CAUTION]
> **Two instant-crash traps in this file:**
> 1. **Pass the skill directory to `local_path`, never a `.zip` file.** `client.skills.create(config={"local_path": ...})` zips the folder internally and raises `ValueError: Path is not a directory` if given `dist/secure-code-review.zip`. Use the `.zip` only for REST uploads or `gcloud alpha agent-registry skills`.
> 2. **`AgentRegistry` requires ADK extras.** `google.adk.integrations.agent_registry` imports `a2a-sdk` and Agent Identity at module scope, so bare `google-adk` fails immediately with `ImportError`. Make sure `google-adk[a2a,agent-identity,mcp]>=2.0.0` is installed (already in `starter/pyproject.toml`).

- **`SkillRegistryPublisher.create_skill()`:** Call `self.client.skills.create(skill_id=skill_id, display_name=display_name, description=description, config={"local_path": str(resolved)})`. Catch `TypeError` and retry with `skill_id` inside `config={"skill_id": skill_id, "local_path": str(resolved)}` for `google-cloud-aiplatform < 1.154.0`.
- **`build_skill_registry_toolset()`:** Load existing paths in `local_skill_dirs` with `load_skill_from_dir(Path(d))`. When `enable_remote_registry`, `project_id`, and `location` are truthy, construct `GCPSkillRegistry(project_id=project_id, location=location)` with keyword-only arguments (always pass `location=` explicitly so it doesn't fall back to regional `GOOGLE_CLOUD_LOCATION`), catching `Exception` to fall back to local skills. Return `SkillToolset(...)` with `SkillDiscoveryMode.LAZY`, `SkillLifecycleConfig(default_mode=SkillLifecycleMode.BOUNDED, max_active_skills=max_active_skills)`, and either `environment=` or `code_executor=` (never both).
- **`build_agent_registry_integrations()`:** Import `AgentRegistry` (wrapping `ImportError` with an install hint). If `register_auth_provider` is `True`, call `CredentialManager.register_auth_provider(GcpAuthProvider())`. Construct `AgentRegistry(project_id=project_id, location=location, header_provider=header_provider)` (default `asia-southeast3`), optionally populate `agents`/`mcp_servers` via `discover_agent_registry_catalog(registry)`, resolve `mcp_toolset` via `registry.get_mcp_toolset(...)`, and resolve `remote_agent` via `registry.get_remote_a2a_agent(...)` with an `httpx.AsyncClient` authenticated by `OidcIdTokenAuth(a2a_audience)` or `GoogleApiAuth(project_id)`. Remember: a `RemoteA2aAgent` can only have one parent orchestrator at a time, so call `remote_agent.clone()` when reusing it.

<details>
<summary>Stuck? Peek at the code</summary>

```python
# Replace # TODO(lab-4) in SkillRegistryPublisher.create_skill():
try:
    return self.client.skills.create(
        skill_id=skill_id,
        display_name=display_name,
        description=description,
        config={"local_path": str(resolved)},
    )
except TypeError:
    return self.client.skills.create(
        display_name=display_name,
        description=description,
        config={"skill_id": skill_id, "local_path": str(resolved)},
    )

# Replace # TODO(lab-4) in build_skill_registry_toolset():
from google.adk.skills import load_skill_from_dir
from google.adk.tools.skill_toolset import (
    SkillDiscoveryMode, SkillLifecycleConfig, SkillLifecycleMode, SkillToolset,
)

local_skills = [load_skill_from_dir(Path(d)) for d in (local_skill_dirs or []) if Path(d).exists()]
registry: Any | None = None
if enable_remote_registry and project_id and location:
    try:
        from google.adk.integrations.skill_registry import GCPSkillRegistry
        registry = GCPSkillRegistry(project_id=project_id, location=location)
    except Exception as exc:
        logger.warning("GCPSkillRegistry unavailable (%s); falling back to %d local skill(s).", exc, len(local_skills))

toolset_kwargs: dict[str, Any] = {
    "skills": local_skills,
    "registry": registry,
    "discovery_mode": discovery_mode if discovery_mode is not None else SkillDiscoveryMode.LAZY,
    "lifecycle_config": SkillLifecycleConfig(
        default_mode=SkillLifecycleMode.BOUNDED, max_active_skills=max_active_skills,
    ),
}
if environment is not None:
    toolset_kwargs["environment"] = environment
elif code_executor is not None:
    toolset_kwargs["code_executor"] = code_executor
return SkillToolset(**toolset_kwargs)

# Replace # TODO(lab-4) in build_agent_registry_integrations():
try:
    from google.adk.integrations.agent_registry import AgentRegistry
except ImportError as exc:
    raise ImportError(
        'Install ADK extras: pip install --upgrade "google-adk[a2a,agent-identity,mcp]>=2.0.0"'
    ) from exc

if register_auth_provider:
    from google.adk.auth.credential_manager import CredentialManager
    from google.adk.integrations.agent_identity import GcpAuthProvider
    CredentialManager.register_auth_provider(GcpAuthProvider())

registry = AgentRegistry(project_id=project_id, location=location, header_provider=header_provider)
result: dict[str, Any] = {
    "registry": registry, "mcp_toolset": None, "remote_agent": None, "agents": [], "mcp_servers": [],
}
if discover_catalog:
    catalog = discover_agent_registry_catalog(registry)
    result["agents"], result["mcp_servers"] = catalog["agents"], catalog["mcp_servers"]
if mcp_server_name:
    mcp_kwargs = {"continue_uri": continue_uri} if continue_uri is not None else {}
    result["mcp_toolset"] = registry.get_mcp_toolset(mcp_server_name, **mcp_kwargs)
if remote_a2a_agent_name:
    auth_handler: httpx.Auth = OidcIdTokenAuth(a2a_audience) if a2a_audience else GoogleApiAuth(project_id)
    httpx_client = httpx.AsyncClient(auth=auth_handler, timeout=httpx.Timeout(httpx_timeout_seconds))
    a2a_kwargs: dict[str, Any] = {"httpx_client": httpx_client}
    if continue_uri is not None:
        a2a_kwargs["continue_uri"] = continue_uri
    result["remote_agent"] = registry.get_remote_a2a_agent(remote_a2a_agent_name, **a2a_kwargs)
return result
```

</details>

**Check it works:**

```bash
(cd starter && uv run python -m coding_agent.tools.registry_loader offline-check)
```

Expected output: JSON with `"local_skill_exists": true`, `"toolset_class": "SkillToolset"`, and `"supported_skill_registry_locations": ["europe-west4", "us-central1", "us-east5"]`.

---

## Step 3: Publish to Vertex AI Skill Registry (and Optional Standalone Skill)

Vertex AI Skill Registry preview runs in `us-central1` (alongside `europe-west4` and `us-east5`), so keep `SKILL_REGISTRY_LOCATION=us-central1`. Run the CLI you just completed to publish your skill directory, observe the built-in skill warmup, and test semantic search.

> [!WARNING]
> **Two Skill Registry quirks to keep in mind:**
> 1. **Built-in `gcp-skill-registry` shows up on your second API call.** Your first call kicks off async ingestion of `gcp-skill-registry`, so pass `--warmup` (or call `list-skills` twice) to see it listed.
> 2. **Don't delete and immediately recreate the same `SKILL_ID`.** Deleted IDs are locked out for at least 24 hours (and Create docs warn permanently). Pick a fresh suffix like `secure-code-review-v2` if you need to re-test creation.

```bash
source .env
export SKILL_REGISTRY_LOCATION="${SKILL_REGISTRY_LOCATION:-us-central1}"

(cd starter && uv run python -m coding_agent.tools.registry_loader publish-skill \
  --skill-id secure-code-review \
  --display-name "Secure Code Review" \
  --description "Enterprise OWASP static security audit checklist." \
  --path skills_to_register/secure-code-review)

(cd starter && uv run python -m coding_agent.tools.registry_loader list-skills --warmup)

(cd starter && uv run python -m coding_agent.tools.registry_loader search-skills \
  --query "audit Python code for OWASP injection flaws" \
  --top-k 3)
```

Expected output: `publish-skill` prints `created_skill`, `list-skills --warmup` lists both `secure-code-review` and `gcp-skill-registry`, and `search-skills` returns `secure-code-review`.

### Optional: Activate an Agent Registry Standalone Skill (`global`)

ADK's live `GCPSkillRegistry` queries Agent Registry standalone skills in `global` (`AGENT_REGISTRY_SKILLS_LOCATION=global`), not Vertex AI Skill Registry in `us-central1`. Run these three `gcloud alpha` commands if you want your live agent to download `private-secure-code-review` remotely from Agent Registry (otherwise your local fallback copy handles it offline).

Watch three CLI quirks: create the bare skill shell first without `--payload` (passing `--payload` on `skills create` fails with `400 source is required`), use `--scanning-policy=enabled-nonblocking` so you don't block on async scanning during the workshop, and pass `--target-state=active` when promoting `rev-1` (leaving a skill in `DRAFT` makes `GCPSkillRegistry.get_skill()` return HTTP 400).

```bash
export AGENT_REGISTRY_SKILLS_LOCATION="${AGENT_REGISTRY_SKILLS_LOCATION:-global}"

# 1. Create the skill container without --payload (auto-prefixed with `private-`)
gcloud alpha agent-registry skills create secure-code-review \
  --project="${GOOGLE_CLOUD_PROJECT}" \
  --location="${AGENT_REGISTRY_SKILLS_LOCATION}" \
  --display-name="Secure Code Review" \
  --description="Enterprise OWASP static security audit checklist." \
  --scanning-policy=enabled-nonblocking

# 2. Upload the validated ZIP bundle as revision rev-1 (avoid 2-char IDs like v1)
gcloud alpha agent-registry skills revisions create rev-1 \
  --skill=private-secure-code-review \
  --project="${GOOGLE_CLOUD_PROJECT}" \
  --location="${AGENT_REGISTRY_SKILLS_LOCATION}" \
  --payload="dist/secure-code-review.zip"

# 3. Promote rev-1 and activate so GCPSkillRegistry.get_skill() can download it
gcloud alpha agent-registry skills update private-secure-code-review \
  --project="${GOOGLE_CLOUD_PROJECT}" \
  --location="${AGENT_REGISTRY_SKILLS_LOCATION}" \
  --default-revision="projects/${GOOGLE_CLOUD_PROJECT}/locations/${AGENT_REGISTRY_SKILLS_LOCATION}/skills/private-secure-code-review/revisions/rev-1" \
  --target-state=active
```

---

## Step 4: Wire `SkillToolset` into `agent.py`

**File:** [starter/coding_agent/agent.py](../starter/coding_agent/agent.py) -> `_build_optional_skill_toolset()` (`# TODO(lab-4)`)

Connect `build_skill_registry_toolset()` inside `agent.py` so enabling `ENABLE_SKILL_REGISTRY=true` attaches `SkillToolset` to your coding agent and executes skill scripts inside Lab 2's active sandbox environment.

- Resolve the bundled skill directory (`Path(__file__).resolve().parents[1] / "skills_to_register" / "secure-code-review"`).
- Pass `location=settings.agent_registry_skills_location or "global"` (never `settings.agent_registry_location`, which is `asia-southeast3` for A2A/MCP discovery and times out on standalone skill endpoints).
- Forward `environment=environment` and `enable_remote_registry=bool(settings.google_cloud_project)`.

<details>
<summary>Stuck? Peek at the code</summary>

```python
# Replace # TODO(lab-4) in _build_optional_skill_toolset():
from coding_agent.tools.registry_loader import build_skill_registry_toolset

local_skill_dir = Path(__file__).resolve().parents[1] / "skills_to_register" / "secure-code-review"
local_dirs = [local_skill_dir] if local_skill_dir.exists() else []
return build_skill_registry_toolset(
    project_id=settings.google_cloud_project or None,
    location=settings.agent_registry_skills_location or "global",
    local_skill_dirs=local_dirs,
    environment=environment,
    enable_remote_registry=bool(settings.google_cloud_project),
)
```

</details>

**Check it works:**

```bash
(cd starter && uv run python - <<'EOF'
from coding_agent.agent import _build_optional_skill_toolset
from coding_agent.config import Settings

ts = _build_optional_skill_toolset(
    Settings(enable_skill_registry=True, google_cloud_project=""),
    environment=None,
)
print("attached:", type(ts).__name__)
EOF
)
```

Expected output: `attached: SkillToolset`.

---

## Step 5: Lab 4 Checkpoint

Run the offline registry check and the Lab 4 verifier:

```bash
(cd starter && uv run python -m coding_agent.tools.registry_loader offline-check)
make verify-lab LAB=4
# Optional live A2A/MCP catalog check in asia-southeast3:
# (cd starter && uv run python -m coding_agent.tools.registry_loader discover-agent-registry)
```

Pass criteria:
1. `starter/skills_to_register/secure-code-review/` passes all 16 checks in `scripts/package_registry_skill.py --dry-run`.
2. Zero `# TODO(lab-4)` markers remain in `starter/coding_agent/tools/registry_loader.py` and `starter/coding_agent/agent.py`.
3. `registry_loader.py` integrates `GCPSkillRegistry`, `SkillToolset`, `AgentRegistry`, `GcpAuthProvider`, `X-Goog-User-Project`, and directory-only `is_dir()` validation, and `agent.py` passes `agent_registry_skills_location`.

Compare against [`solution/coding_agent/tools/registry_loader.py`](../solution/coding_agent/tools/registry_loader.py) and [`solution/coding_agent/agent.py`](../solution/coding_agent/agent.py) if anything fails.

Your local `coding_agent/` package now has ADK tools, sandboxes, sessions/memory/telemetry, and skills ready to deploy once. Continue to **[Lab 5: Deploy & Manage the Complete Coding Agent on Agent Runtime (CLI & Terraform)](./05-LAB-DEPLOY-RUNTIME-TERRAFORM.md)**.

---

## Optional Reference & Deep Dive

<details>
<summary>Three registry endpoints, regional split & standalone skill teardown</summary>

| Surface | API Endpoint | Workshop Location | Primary Client | Payload Limits & Notes |
|---|---|---|---|---|
| **Agent Registry A2A/MCP Catalog** | `agentregistry.googleapis.com` | `asia-southeast3` (`AGENT_REGISTRY_LOCATION`) | ADK `AgentRegistry`, `gcloud agent-registry agents list` | Calls `google.auth.default()` eagerly at init; `header_provider` applies to `McpToolset` only |
| **Vertex AI Skill Registry** | `aiplatform.googleapis.com/v1beta1` | `us-central1` (`SKILL_REGISTRY_LOCATION`; also `europe-west4`, `us-east5`) | `agentplatform.Client.skills.*` | <= 10 MB ZIP, <= 500 MB unzipped; SDK zips a directory path; includes built-in `gcp-skill-registry` |
| **Agent Registry Standalone Skills** | `agentregistry.googleapis.com/v1alpha` | `global` (`AGENT_REGISTRY_SKILLS_LOCATION`) | `gcloud alpha agent-registry skills`, live ADK `GCPSkillRegistry` | <= 1 MB ZIP, <= 10 MB unzipped, root `SKILL.md`; auto-prefixed `private-*`; lazy init in ADK 2.15+ (air-gapped calls return `REGISTRY_ERROR` while local skills keep working) |

**Clean teardown order for standalone skills:** Clear `--default-revision` first, delete child revisions next, then delete the skill container (`skills delete` has no `--force` flag):

```bash
gcloud alpha agent-registry skills update private-secure-code-review \
  --clear-default-revision --target-state=disabled \
  --project="${GOOGLE_CLOUD_PROJECT}" --location="${AGENT_REGISTRY_SKILLS_LOCATION}"
gcloud alpha agent-registry skills revisions delete rev-1 \
  --skill=private-secure-code-review \
  --project="${GOOGLE_CLOUD_PROJECT}" --location="${AGENT_REGISTRY_SKILLS_LOCATION}" --quiet
gcloud alpha agent-registry skills delete private-secure-code-review \
  --project="${GOOGLE_CLOUD_PROJECT}" --location="${AGENT_REGISTRY_SKILLS_LOCATION}" --quiet
```

For blocking LLM security scans (`ENABLED_BLOCKING`), `Finding` triage, Custom Org Policies, NLC semantic governance, and SPIFFE `AGENT_IDENTITY`, see [Lab 7 (Optional)](./07-LAB-OPTIONAL-SECURITY-AND-GOVERNANCE.md).

</details>

<details>
<summary>All 16 atomic Skill Registry ZIP & SKILL.md validation rules</summary>

`scripts/package_registry_skill.py` enforces all 16 rules (11 ZIP-level + 5 `SKILL.md`-level) before emitting an archive:

| # | Scope | Validation Rule |
|---|---|---|
| 1 | ZIP | Valid, non-corrupt ZIP archive with complete header metadata |
| 2 | ZIP | Archive is not empty |
| 3 | ZIP | Contains at most 10,000 items |
| 4 | ZIP | No file or folder name contains `..` or starts with `/` or `\` |
| 5 | ZIP | Contains zero symbolic links |
| 6 | ZIP | Contains zero duplicate file or folder names |
| 7 | ZIP | Total unzipped size <= 500 MB (keep <= 10 MB total and <= 1 MB per file for Agent Registry scanning) |
| 8 | ZIP | Compression ratio <= 100 (zip-bomb protection) |
| 9 | ZIP | Directory nesting depth <= 8 levels |
| 10 | ZIP | Contains a `SKILL.md` file (place directly at ZIP root for Agent Registry) |
| 11 | ZIP | Compressed ZIP archive size <= 10 MB (keep <= 1 MB for Agent Registry) |
| 12 | `SKILL.md` | Valid YAML frontmatter AND non-empty Markdown instruction body |
| 13 | `SKILL.md` | Frontmatter `name`: required, <= 64 chars, `[a-z0-9-]` only, cannot start or end with `-` (ADK local loader also rejects `--` and requires parent folder name == `name`) |
| 14 | `SKILL.md` | Frontmatter `description`: required and <= 1,024 chars |
| 15 | `SKILL.md` | Frontmatter `license` (if present): <= 1,024 chars |
| 16 | `SKILL.md` | Markdown instruction body <= 500,000 chars |

</details>

<details>
<summary>Vertex AI Skill Registry REST v1beta1 upload & AgentRegistry auth patterns</summary>

**REST `v1beta1` upload (uses `dist/secure-code-review.zip` from `make package-skill`):**

```bash
ZIP_B64="$(base64 < dist/secure-code-review.zip | tr -d '\n')"
curl -X POST \
  -H "Authorization: Bearer $(gcloud auth print-access-token)" \
  -H "Content-Type: application/json" \
  "https://${SKILL_REGISTRY_LOCATION}-aiplatform.googleapis.com/v1beta1/projects/${GOOGLE_CLOUD_PROJECT}/locations/${SKILL_REGISTRY_LOCATION}/skills?skillId=secure-code-review" \
  -d "{\"displayName\":\"Secure Code Review\",\"description\":\"Enterprise OWASP static security audit checklist.\",\"zippedFilesystem\":\"${ZIP_B64}\"}"
```

Poll the returned LRO with `GET .../operations/OPERATION_ID`. Read-only IAM role: `roles/aiplatform.viewer`.

**Three ADK `AgentRegistry` auth patterns (wired in `registry_loader.py`):**
1. **Auth Manager bindings (2LO, API Key, 3LO):** `CredentialManager.register_auth_provider(GcpAuthProvider())`. On Agent Runtime, `AgentRegistry` re-resolves bindings via `bindings:fetchAvailable` and strips deployer credentials on pickle. Pass `continue_uri` for 3LO user consent flows.
2. **Custom MCP headers:** Pass `header_provider` to `AgentRegistry(...)`. Applies to `McpToolset` only, never to `RemoteA2aAgent`.
3. **Authenticated `RemoteA2aAgent` client:** Pass `httpx.AsyncClient(auth=GoogleApiAuth(project_id))` for `*.googleapis.com` endpoints (adds OAuth Bearer + `X-Goog-User-Project`), or `OidcIdTokenAuth(audience)` for Cloud Run (`*.run.app`) and IAP endpoints.

</details>

<details>
<summary>Official documentation links</summary>

- Vertex AI Skill Registry: https://docs.cloud.google.com/gemini-enterprise-agent-platform/build/skill-registry (`/create-manage`)
- Agent Registry: https://docs.cloud.google.com/agent-registry/overview (`/skills-architecture`, `/authenticate-toolsets`, `/resolve-endpoints-and-build-orchestrators`)
- ADK integrations: https://adk.dev/skills/ | https://adk.dev/integrations/skills-registry/ | https://adk.dev/integrations/agent-registry/

</details>
