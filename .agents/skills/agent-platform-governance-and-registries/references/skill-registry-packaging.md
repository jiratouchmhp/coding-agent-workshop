# Skill Registry Packaging, Validation & CRUD (`aiplatform.googleapis.com/v1beta1`)

Production reference for authoring, pre-validating, packaging, uploading, and managing skills in **Vertex AI / Gemini Enterprise Agent Platform Skill Registry** (`Preview`), and distinguishing it cleanly from **Agent Registry Standalone Skills**.

---

## 1. Architecture Split: Two Distinct Skill Registry APIs

Google Cloud exposes **two separate skill registry surfaces** (both in Preview). Confirm which backend your runtime/SDK targets before authoring packaging or CI scripts:

| Dimension | Vertex AI / Agent Platform **Skill Registry** | **Agent Registry** Standalone Skills |
|---|---|---|
| **REST Endpoint** | `https://LOCATION-aiplatform.googleapis.com/v1beta1/projects/PROJECT_ID/locations/LOCATION/skills` | `https://agentregistry.googleapis.com/v1/projects/PROJECT_ID/locations/LOCATION/skills` |
| **CLI / SDK Surface** | Python `import agentplatform` (`google-cloud-aiplatform`, directory-only `local_path`), Node.js `@google-cloud/agentplatform`, REST `v1beta1` | **`gcloud alpha agent-registry skills ...`**, `revisions ...`, `findings ...`, REST `v1` *(alpha-only CLI; 2-step create without `--payload` -> `revisions create rev-1`)* |
| **Supported Locations** | `us-central1` (Iowa), `europe-west4` (Netherlands), `us-east5` (Columbus, Ohio) (`SKILL_REGISTRY_LOCATION`) | **`global`** (`AGENT_REGISTRY_SKILLS_LOCATION=global`; standalone skills currently time out in `asia-southeast3`, whereas A2A/MCP discovery stays in Bangkok `asia-southeast3`) |
| **Compressed ZIP Max** | **10 MB** | **1 MB** |
| **Uncompressed Max** | **500 MB** total | **10 MB** total & **1 MB** per individual file (when scanning is enabled) |
| **Skill ID Rules** | `SKILL_ID` 1–63 chars (`[a-z0-9-]`), starts with letter, ends with letter/number, **cannot start with `gcp-`**. Immutable; delete locks reuse for at least 24h (see §3). | Registry auto-assigns default `private` publisher and prepends **`private-`** (`private-SKILL_ID`). Must use `private-SKILL_ID` on all subsequent operations. |
| **Built-in / Managed Skills** | Built-in `gcp-skill-registry` (async first-call ingestion quirk) | Google-managed `FIRST_PARTY` skills (`cloud.google.com`, `discoveryengine.googleapis.com`, mirrored from `github.com/google/skills`) |
| **Security & IAM** | Project-level IAM (`roles/aiplatform.viewer` for read-only). Async 16-check ZIP/`SKILL.md` validation only. | Resource-level IAM auto-granted; automated LLM security scanning (`ENABLED_BLOCKING` default) + custom Org Policy enforcement. |
| **ADK `GCPSkillRegistry`** | `adk.dev/integrations/skills-registry` describes `GCPSkillRegistry` using Vertex AI SDK. | Latest `adk-python` `main` `gcp_skill_registry.py` targets `https://agentregistry.googleapis.com/v1alpha` (overridable via `AGENT_REGISTRY_ENDPOINT`). |

---

## 2. Core Entities, Regions & Compliance (`aiplatform.googleapis.com/v1beta1`)

- **Skill:** Mutable top-level entity holding metadata (`displayName`, `description`, `createTime`, `updateTime`, `labels`, `state` e.g. `"ACTIVE"`), default revision pointer, and content.
- **Skill Revision:** Immutable versioned snapshot of a skill (`name`, `description`, immutable parent skill reference).
- **Available Regions (3):**
  - `us-central1` (Iowa)
  - `europe-west4` (Netherlands)
  - `us-east5` (Columbus, Ohio)
- **IAM Permissions:** Inherits project-level permissions. `roles/aiplatform.viewer` is sufficient for read-only access (`list`, `get`, `revisions.list`, `revisions.get`, `retrieve`).
- **Compliance Matrix:**

| Compliance Feature | Status |
|---|---|
| Access Transparency | **Supported** |
| Data Residency (DRZ) in US and EU | **Supported** |
| Customer-Managed Encryption Keys (CMEK) | **Not Supported** |
| HIPAA Certification | **Not Supported** |
| VPC Service Controls (VPC-SC) | **Not Supported** |

---

## 3. `SKILL_ID` Rules, Reuse Lockout & Built-in `gcp-skill-registry` Quirk

### `SKILL_ID` Naming & Lifecycle Rules
- **Format:** **1 to 63 characters**, lowercase letters (`a-z`), digits (`0-9`), and hyphens (`-`) only.
- **Boundaries:** Must **start with a letter** and **end with a letter or number**.
- **Reserved Prefix:** Must **NOT start with `gcp-`** (reserved for Google-managed built-in skills, which **cannot be deleted**).
- **Runtime Folder Name:** `SKILL_ID` becomes the directory name when mounted/attached to an agent — choose a descriptive kebab-case ID.
- **Reuse Lockout Discrepancy in Official Docs:**
  - Under *Create a skill*: *"The `SKILL_ID` is immutable and remains permanently reserved once created, even if you delete the skill later."*
  - Under *Delete a skill*: *"Caution: When you delete a skill, its `SKILL_ID` is reserved and cannot be reused for 24 hours."*
  - **Production Rule:** Treat deleted `SKILL_ID`s as **unreusable** during active deployments/CI pipelines. Update existing skills via `UpdateSkill` (which creates a new immutable revision) instead of delete-and-recreate; use a new versioned `SKILL_ID` only if you must recreate from scratch.

### Built-in `gcp-skill-registry` First-Call Quirk
- Skill Registry ships with a Google-managed `gcp-skill-registry` skill that lets agents create, search, and manage skills.
- **Quirk:** The ingestion pipeline for `gcp-skill-registry` is triggered **asynchronously on your very first API call** to Skill Registry in a project/location.
- **Consequence:** Your **first** `ListSkills` / `RetrieveSkills` response will **NOT** include `gcp-skill-registry`. It appears starting on subsequent API calls once background ingestion finishes. Do **not** fail bootstrap assertions on the first call; poll or issue a second call before asserting its presence.

---

## 4. All 16 Atomic ZIP Payload & `SKILL.md` Validation Rules

> **Rule Count Note:** The official `build/skill-registry` documentation lists **12 top-level bullets** where bullet 11 expands into **5 `SKILL.md` sub-rules**, totaling **16 atomic checks** (earlier rough summaries collapsed sub-items to 14). Validation runs **asynchronously** during `CreateSkill` and `UpdateSkill` LROs — validate locally **before** uploading to avoid slow LRO failures.

| # | Scope | Exact Validation Rule | Failure Trigger |
|---|---|---|---|
| **01** | ZIP | Valid ZIP archive | File isn't a proper `.zip` file or is missing required ZIP header/directory metadata |
| **02** | ZIP | Non-empty archive | ZIP archive contains zero entries |
| **03** | ZIP | Item count limit | ZIP archive contains **> 10,000 items** |
| **04** | ZIP | Safe relative paths | Any file or folder path contains `..` or starts with `/` or `\` |
| **05** | ZIP | Zero symlinks | ZIP archive contains any symbolic link |
| **06** | ZIP | Unique paths | Duplicate file or folder names exist inside the ZIP archive |
| **07** | ZIP | Uncompressed total size | Total unzipped size of all files **> 500 MB** *(Agent Registry scanned cap: **10 MB** total, **1 MB** per file)* |
| **08** | ZIP | Zip-bomb protection | Compression ratio (`uncompressed / compressed`) **> 100** |
| **09** | ZIP | Directory depth limit | Folder nesting depth **> 8 levels** |
| **10** | ZIP | Required entry file | ZIP archive does not contain a `SKILL.md` file *(place directly at archive root — never wrapped in an extra outer folder!)* |
| **11** | ZIP | Compressed archive size | Zipped `.zip` file itself **> 10 MB** *(Agent Registry cap: **1 MB**)* |
| **12** | `SKILL.md` | Structure | Missing required YAML frontmatter (`---` ... `---`) or missing Markdown instruction body |
| **13** | `SKILL.md` | Frontmatter `name` | Missing, **> 64 chars**, starts or ends with `-`, or contains characters outside `[a-z0-9-]` *(ADK local loader also rejects `--` consecutive hyphens and requires folder name == `name`)* |
| **14** | `SKILL.md` | Frontmatter `description` | Missing or **> 1,024 chars** |
| **15** | `SKILL.md` | Frontmatter `license` | Present and **> 1,024 chars** |
| **16** | `SKILL.md` | Instructions body | Markdown instructions body **> 500,000 chars** |

### Pre-Upload Local Packaging & Validation

Always package from **inside** the skill directory so `SKILL.md` sits at the ZIP root, strip OS/cache artifacts (`.DS_Store`, `__pycache__`, `.git`), and validate before upload:

```bash
# 1. Recommended: Use the deterministic workshop packager/validator (checks all 16 rules)
python3 scripts/package_registry_skill.py path/to/my-skill --dry-run

# Enforce stricter Agent Registry limits (1 MB ZIP, 10 MB uncompressed, 1 MB/file, root SKILL.md)
python3 scripts/package_registry_skill.py path/to/my-skill --agent-registry --output /tmp/my-skill.zip

# Validate an existing archive
python3 scripts/package_registry_skill.py --validate-zip /tmp/my-skill.zip

# 2. Pure shell ZIP + Base64 preparation (for raw REST CreateSkill / UpdateSkill)
cd path/to/my-skill && zip -r /tmp/skill.zip SKILL.md scripts/ references/ assets/
BASE64_ZIPPED_BODY=$(base64 -w 0 -i /tmp/skill.zip)
```

> **Packaging Pitfall:** Running `zip -r skill.zip my-skill/` puts `my-skill/SKILL.md` one level deep instead of `SKILL.md` at archive root, breaking Agent Registry root-`SKILL.md` checks and increasing nesting depth by 1. Always `cd` into the skill folder (or use `package_registry_skill.py`).

---

## 5. Exact SDK & REST CRUD Reference (`v1beta1`)

> **Import, Payload & LRO Return-Type Rules (`google-cloud-agentplatform==2.10.0`):** Skill Registry Python SDK uses **`import agentplatform`** (also re-exported by `google-cloud-aiplatform >= 1.154.0`, NOT `import vertexai`). Pay close attention to THREE critical SDK rules:
> 1. **`local_path` (directory) vs. `zipped_filesystem` (bytes/base64):** In `CreateSkillConfig` / `UpdateSkillConfig`, **`local_path` MUST be a directory path — NEVER a `.zip` file!** `get_zipped_filesystem_payload(local_path)` zips the directory internally and raises `ValueError: Path is not a directory` if passed a `.zip`. If you already built raw ZIP bytes in memory, pass `config={"zipped_filesystem": zip_bytes}` instead (and use `.zip` files on disk for raw REST `zippedFilesystem` and `gcloud alpha agent-registry skills revisions create --payload=...`).
> 2. **Return Type (`Skill` vs. `SkillOperation`):** `client.skills.create()` / `.update()` default to `wait_for_completion=True` and return a **`Skill`** directly; passing `config={"wait_for_completion": False, ...}` returns an async **`SkillOperation`** LRO.
> 3. **`skill_id` Placement:** **`google-cloud-aiplatform >= 1.154.0` / `google-cloud-agentplatform >= 2.0.1`** accept `skill_id` as a top-level keyword arg (older `< 1.154.0` requires `"skill_id"` inside `config={...}`).

### Python (`google-cloud-aiplatform`)

```python
import os
import agentplatform

# Vertex AI Skill Registry Preview is strictly 3 regions: us-central1, europe-west4, us-east5
SKILL_REGISTRY_LOCATION = os.environ.get("SKILL_REGISTRY_LOCATION", "us-central1")
client = agentplatform.Client(project="PROJECT_ID", location=SKILL_REGISTRY_LOCATION)

# --- CREATE ---
# google-cloud-aiplatform >= 1.154.0 (skill_id is a top-level keyword arg):
skill = client.skills.create(
    skill_id="secure-code-review",
    display_name="Secure Code Review",
    description="Audits Python/Go patches for security anti-patterns and OWASP issues.",
    config={
        # MUST be a local skill DIRECTORY (SDK zips it internally; passing a .zip raises ValueError!)
        "local_path": "./skills/secure-code-review",
    },
)
print(skill.name)

# google-cloud-aiplatform < 1.154.0 (skill_id passed inside config dict):
# skill = client.skills.create(
#     display_name="Secure Code Review",
#     description="...",
#     config={"skill_id": "secure-code-review", "local_path": "./skills/secure-code-review"},
# )

# --- UPDATE (creates a new immutable revision when local_path directory is supplied) ---
updated = client.skills.update(
    name="projects/PROJECT_ID/locations/us-central1/skills/secure-code-review",
    config={
        "display_name": "Secure Code Review v2",
        "description": "Updated OWASP + secret-scanning guidance.",
        "local_path": "./skills/secure-code-review",  # Optional DIRECTORY path (never .zip!)
    },
)

# --- LIST & GET ---
for s in client.skills.list():
    print(s.name, s.display_name)

fetched = client.skills.get(
    name="projects/PROJECT_ID/locations/us-central1/skills/secure-code-review"
)

# --- REVISIONS ---
revs = client.skills.revisions.list(
    name="projects/PROJECT_ID/locations/us-central1/skills/secure-code-review"
)
for rev in revs.skill_revisions:
    print(rev.name, rev.create_time)

rev = client.skills.revisions.get(
    name="projects/PROJECT_ID/locations/us-central1/skills/secure-code-review/revisions/REVISION_ID"
)

# --- SEMANTIC SEARCH (RETRIEVE) ---
search_resp = client.skills.retrieve(
    query="audit Python patches for security vulnerabilities",
    config={"top_k": 5},
)
for item in search_resp.retrieved_skills:
    print(item.skill_name, item.description)

# --- DELETE (LRO; locks SKILL_ID reuse!) ---
client.skills.delete(
    name="projects/PROJECT_ID/locations/us-central1/skills/secure-code-review"
)
```

### Node.js (`@google-cloud/agentplatform`)

```javascript
import { Client } from '@google-cloud/agentplatform';

const client = new Client({ project: 'PROJECT_ID', location: 'us-central1' });

const created = await client.skills.create({
  skillId: 'secure-code-review',
  displayName: 'Secure Code Review',
  description: 'Audits patches for security issues.',
  config: { localPath: './skills/secure-code-review' },
});

for await (const s of await client.skills.list()) {
  console.log(s.name, s.displayName);
}

const retrieved = await client.skills.retrieve({
  query: 'security code audit',
  config: { topK: 5 },
});
for (const item of retrieved.retrievedSkills || []) {
  console.log(item.skillName, item.description);
}

const revs = await client.skills.revisions.list({
  name: 'projects/PROJECT_ID/locations/us-central1/skills/secure-code-review',
});
```

### REST API (`v1beta1`) & LRO Polling

All `CreateSkill`, `UpdateSkill`, and `DeleteSkill` requests return a **long-running operation (LRO)** whose `name` follows `projects/PROJECT_NUMBER/locations/LOCATION/skills/SKILL_ID/operations/OPERATION_ID`. Extract `OPERATION_ID` and poll `GetOperation`:

```bash
export TOKEN="$(gcloud auth application-default print-access-token)"
export BASE="https://${LOCATION}-aiplatform.googleapis.com/v1beta1/projects/${PROJECT_ID}/locations/${LOCATION}"

# CreateSkill (LRO)
curl -X POST \
  -H "Authorization: Bearer ${TOKEN}" \
  -H "Content-Type: application/json" \
  -d "{
    \"displayName\": \"Secure Code Review\",
    \"description\": \"Audits patches for security issues.\",
    \"zippedFilesystem\": \"${BASE64_ZIPPED_BODY}\"
  }" \
  "${BASE}/skills?skillId=secure-code-review"

# UpdateSkill (LRO — only fields in updateMask are modified)
curl -X PATCH \
  -H "Authorization: Bearer ${TOKEN}" \
  -H "Content-Type: application/json; charset=utf-8" \
  -d "{
    \"displayName\": \"Secure Code Review v2\",
    \"description\": \"Updated guidance.\",
    \"zippedFilesystem\": \"${BASE64_ZIPPED_BODY}\"
  }" \
  "${BASE}/skills/secure-code-review?updateMask=displayName,description,zippedFilesystem"

# ListSkills / GetSkill / ListSkillRevisions / GetSkillRevision
curl -H "Authorization: Bearer ${TOKEN}" "${BASE}/skills"
curl -H "Authorization: Bearer ${TOKEN}" "${BASE}/skills/secure-code-review"
curl -H "Authorization: Bearer ${TOKEN}" "${BASE}/skills/secure-code-review/revisions"
curl -H "Authorization: Bearer ${TOKEN}" "${BASE}/skills/secure-code-review/revisions/${REVISION_ID}"

# RetrieveSkills (Semantic Search)
curl -H "Authorization: Bearer ${TOKEN}" "${BASE}/skills:retrieve?query=audit+python+security"

# DeleteSkill (LRO)
curl -X DELETE -H "Authorization: Bearer ${TOKEN}" "${BASE}/skills/secure-code-review"

# Poll LRO (GetOperation)
curl -H "Authorization: Bearer ${TOKEN}" "${BASE}/operations/${OPERATION_ID}"
```

---

## 6. Error Modes, Verification & Troubleshooting

| Symptom / Error | Root Cause | Fix |
|---|---|---|
| `gcp-skill-registry` missing on first `ListSkills` | First API call kicks off async built-in skill ingestion | Re-run `ListSkills` / `RetrieveSkills` after a few seconds; never assert presence on call #1 |
| LRO fails with validation error after `CreateSkill` | One of the 16 ZIP / `SKILL.md` rules failed asynchronously | Run `python3 scripts/package_registry_skill.py <dir> --dry-run` locally to pinpoint exact rule |
| `TypeError` on `client.skills.create(skill_id=...)` | Installed `google-cloud-aiplatform < 1.154.0` | Upgrade `google-cloud-aiplatform>=1.154.0` or pass `"skill_id"` inside `config={...}` |
| `ALREADY_EXISTS` after deleting & recreating same `SKILL_ID` | Deleted `SKILL_ID` is locked (24h–permanent reservation) | Use `client.skills.update(...)` for revisions or pick a new `SKILL_ID` |
| `INVALID_ARGUMENT` on `skillId=gcp-my-skill` | `gcp-` prefix is reserved for Google-managed skills | Rename without `gcp-` prefix (`[a-z][a-z0-9-]*[a-z0-9]`, <= 63 chars) |
| `ValueError: Path is not a directory` in `client.skills.create` / `.update` | Passed a `.zip` file to `config["local_path"]` | Always pass the validated skill **directory** path (`agentplatform==2.10.0` zips the directory internally); reserve `.zip` for REST `zippedFilesystem` and `gcloud alpha agent-registry skills revisions create --payload=...` |
| Unsupported region error | Skill Registry only exists in 3 regions | Use `us-central1`, `europe-west4`, or `us-east5` |

### Concrete Verification Steps
1. Run `python3 scripts/package_registry_skill.py <skill_dir> --dry-run` and confirm **16/16 checks PASS**.
2. Upload via `client.skills.create(..., config={"local_path": "<skill_dir>"})` (directory only — or REST `POST` with base64 ZIP + poll `GetOperation` until `"done": true` with no `"error"`).
3. Run `client.skills.list()` twice: verify your custom skill appears with `"state": "ACTIVE"` and verify `gcp-skill-registry` appears on the second call.
4. Run `client.skills.retrieve(query="<intent>", config={"top_k": 3})` and confirm your skill ranks in `retrieved_skills`.
5. **Closed-Loop Optimize Flywheel (Zero Agent Container Rebuild):** When offline/online evals or `GEPARootAgentOptimizer` improve `SKILL.md`, preserve its YAML frontmatter, re-run `package_registry_skill.py`, and publish live via `client.skills.update(..., config={"local_path": "<skill_dir>"})` (Vertex AI Skill Registry — directory only!) or `gcloud alpha agent-registry skills revisions create rev-2 --skill=private-<id> --location=global --payload=<zip>` + `gcloud alpha agent-registry skills update private-<id> --location=global --default-revision=.../revisions/rev-2 --target-state=active` (Agent Registry — remember `--target-state=active` so `GCPSkillRegistry.get_skill()` succeeds; under `ENABLED_BLOCKING`, wait for `scanState=SUCCEEDED` before promoting or use `enabled-nonblocking` for rapid workshop demos; on teardown, `--clear-default-revision --target-state=disabled` before `revisions delete` -> `skills delete`).
