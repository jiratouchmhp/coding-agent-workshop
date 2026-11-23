# Maintenance & Upstream Source Verification (`adk-coding-agent-build`)

- **Last Verified Date:** `2026-11-23`
- **Skill Scope:** Build Pillar — Google ADK Python (`v2.0+` / `v2.4.0` Preview), `EnvironmentToolset` / `LocalEnvironment` / `BaseEnvironment`, `ExecuteBashTool` / `BashToolPolicy`, ADK 2.0 Agent Architectures, Collaborative Teams, Service Registration, Graph & Dynamic Workflows, and `google/agents-cli` (`~= 1.15.0`).
- **Validation Command:** `python3 scripts/validate_skills.py .agents/skills` (must exit `0` with `PASS`, `<= 450` lines in `SKILL.md`, `< 1024` char folded `description: >-`, zero orphan references, zero 2-hop reference links, and zero hardcoded workstation paths).

---

## 1. Canonical Seed URLs

Every refresh pass MUST start from these two canonical seed entrypoints:

| Seed Topic | Canonical URL | Machine-Readable Refresh Endpoint |
|---|---|---|
| **Google ADK Documentation** | `https://adk.dev/get-started/` | `https://adk.dev/get-started/index.md` & full docs index `https://adk.dev/llms.txt` |
| **`google/agents-cli` Repository** | `https://github.com/google/agents-cli` | `https://raw.githubusercontent.com/google/agents-cli/main/README.md` |

---

## 2. Complete Tier-1 & Tier-2 Upstream Source Registry

### 2.1 Google ADK Core, Models & Setup (`adk-core-and-setup.md`)

| Canonical Upstream URL | Refresh Endpoint (`.md` / Raw) | Feeds Local File |
|---|---|---|
| `https://adk.dev/get-started/` | `https://adk.dev/get-started/index.md` | `references/adk-core-and-setup.md` |
| `https://adk.dev/get-started/about/` | `https://adk.dev/get-started/about/index.md` | `references/adk-core-and-setup.md` |
| `https://adk.dev/get-started/python/` | `https://adk.dev/get-started/python/index.md` | `references/adk-core-and-setup.md` |
| `https://adk.dev/get-started/typescript/` | `https://adk.dev/get-started/typescript/index.md` | `references/adk-core-and-setup.md` |
| `https://adk.dev/get-started/go/` | `https://adk.dev/get-started/go/index.md` | `references/adk-core-and-setup.md` |
| `https://adk.dev/get-started/java/` | `https://adk.dev/get-started/java/index.md` | `references/adk-core-and-setup.md` |
| `https://adk.dev/get-started/kotlin/` | `https://adk.dev/get-started/kotlin/index.md` | `references/adk-core-and-setup.md` |
| `https://adk.dev/get-started/google-cloud/` | `https://adk.dev/get-started/google-cloud/index.md` | `references/adk-core-and-setup.md` |
| `https://adk.dev/2.0/` | `https://adk.dev/2.0/index.md` | `references/adk-core-and-setup.md`, `references/agent-architectures-and-workflows.md`, `references/graph-and-dynamic-workflows.md`, `SKILL.md` |
| `https://adk.dev/agents/models/google-gemini/` | `https://adk.dev/agents/models/google-gemini/index.md` | `references/adk-core-and-setup.md`, `SKILL.md` |
| `https://docs.cloud.google.com/gemini-enterprise-agent-platform/build/agent-garden` | `https://docs.cloud.google.com/gemini-enterprise-agent-platform/build/agent-garden.md.txt` | `references/agents-cli-lifecycle.md` |
| `https://docs.cloud.google.com/gemini-enterprise-agent-platform/build/runtime/setup` | `https://docs.cloud.google.com/gemini-enterprise-agent-platform/build/runtime/setup.md.txt` | `references/adk-core-and-setup.md` |
| `https://docs.cloud.google.com/gemini-enterprise-agent-platform/build/runtime/create-an-agent` | `https://docs.cloud.google.com/gemini-enterprise-agent-platform/build/runtime/create-an-agent.md.txt` | `references/adk-core-and-setup.md` |
| `https://docs.cloud.google.com/gemini-enterprise-agent-platform/build/runtime/create-an-adk-agent` | `https://docs.cloud.google.com/gemini-enterprise-agent-platform/build/runtime/create-an-adk-agent.md.txt` | `references/adk-core-and-setup.md` |
| `https://docs.cloud.google.com/gemini-enterprise-agent-platform/build/runtime/create-a-custom-agent` | `https://docs.cloud.google.com/gemini-enterprise-agent-platform/build/runtime/create-a-custom-agent.md.txt` | `references/adk-core-and-setup.md` |
| `https://docs.cloud.google.com/gemini-enterprise-agent-platform/build/runtime/create-a-langchain-agent` | `https://docs.cloud.google.com/gemini-enterprise-agent-platform/build/runtime/create-a-langchain-agent.md.txt` | `references/adk-core-and-setup.md` |
| `https://docs.cloud.google.com/gemini-enterprise-agent-platform/build/runtime/create-a-langgraph-agent` | `https://docs.cloud.google.com/gemini-enterprise-agent-platform/build/runtime/create-a-langgraph-agent.md.txt` | `references/adk-core-and-setup.md` |
| `https://docs.cloud.google.com/gemini-enterprise-agent-platform/build/runtime/create-a-llamaindex-agent` | `https://docs.cloud.google.com/gemini-enterprise-agent-platform/build/runtime/create-a-llamaindex-agent.md.txt` | `references/adk-core-and-setup.md` |
| `https://docs.cloud.google.com/gemini-enterprise-agent-platform/resources/agent-quotas` | `https://docs.cloud.google.com/gemini-enterprise-agent-platform/resources/agent-quotas.md.txt` | `references/adk-core-and-setup.md` |
| `https://docs.cloud.google.com/gemini-enterprise-agent-platform/resources/data-residency` | `https://docs.cloud.google.com/gemini-enterprise-agent-platform/resources/data-residency.md.txt` | `references/adk-core-and-setup.md` |
| `https://docs.cloud.google.com/gemini-enterprise-agent-platform/agent-anomalies-overview` | `https://docs.cloud.google.com/gemini-enterprise-agent-platform/agent-anomalies-overview.md.txt` | `references/adk-core-and-setup.md` |
| `https://docs.cloud.google.com/gemini-enterprise-agent-platform/scale` | `https://docs.cloud.google.com/gemini-enterprise-agent-platform/scale.md.txt` | `references/adk-core-and-setup.md` |
| `https://docs.cloud.google.com/gemini-enterprise-agent-platform/machine-learning/shared-responsibility` | `https://docs.cloud.google.com/gemini-enterprise-agent-platform/machine-learning/shared-responsibility.md.txt` | `references/adk-core-and-setup.md` |
| `https://docs.cloud.google.com/gemini-enterprise-agent-platform/machine-learning/general/audit-logging` | `https://docs.cloud.google.com/gemini-enterprise-agent-platform/machine-learning/general/audit-logging.md.txt` | `references/adk-core-and-setup.md` |
| `https://docs.cloud.google.com/gemini-enterprise-agent-platform/machine-learning/general/cmek` | `https://docs.cloud.google.com/gemini-enterprise-agent-platform/machine-learning/general/cmek.md.txt` | `references/adk-core-and-setup.md` |
| `https://docs.cloud.google.com/gemini-enterprise-agent-platform/machine-learning/general/vpc-service-controls` | `https://docs.cloud.google.com/gemini-enterprise-agent-platform/machine-learning/general/vpc-service-controls.md.txt` | `references/adk-core-and-setup.md` |

### 2.2 ADK Agent Architectures, Collaboration & Multi-Agent Patterns (`agent-architectures-and-workflows.md`)

| Canonical Upstream URL | Refresh Endpoint (`.md`) | Feeds Local File |
|---|---|---|
| `https://adk.dev/agents/` | `https://adk.dev/agents/index.md` | `references/agent-architectures-and-workflows.md`, `SKILL.md` |
| `https://adk.dev/agents/managed-agents/` | `https://adk.dev/agents/managed-agents/index.md` | `references/agent-architectures-and-workflows.md`, `SKILL.md` |
| `https://adk.dev/agents/service-registration/` | `https://adk.dev/agents/service-registration/index.md` | `references/agent-architectures-and-workflows.md`, `SKILL.md` |
| `https://adk.dev/workflows/` | `https://adk.dev/workflows/index.md` | `references/agent-architectures-and-workflows.md`, `SKILL.md` |
| `https://adk.dev/workflows/collaboration/` | `https://adk.dev/workflows/collaboration/index.md` | `references/agent-architectures-and-workflows.md`, `SKILL.md` |
| `https://adk.dev/workflows/patterns/` | `https://adk.dev/workflows/patterns/index.md` | `references/agent-architectures-and-workflows.md`, `SKILL.md` |

### 2.3 ADK 2.0 Graph & Dynamic Workflows (`graph-and-dynamic-workflows.md`)

| Canonical Upstream URL | Refresh Endpoint (`.md`) | Feeds Local File |
|---|---|---|
| `https://adk.dev/graphs/` | `https://adk.dev/graphs/index.md` | `references/graph-and-dynamic-workflows.md`, `references/adk-core-and-setup.md`, `SKILL.md` |
| `https://adk.dev/graphs/routes/` | `https://adk.dev/graphs/routes/index.md` | `references/graph-and-dynamic-workflows.md`, `references/adk-core-and-setup.md`, `SKILL.md` |
| `https://adk.dev/graphs/data-handling/` | `https://adk.dev/graphs/data-handling/index.md` | `references/graph-and-dynamic-workflows.md`, `SKILL.md` |
| `https://adk.dev/graphs/human-input/` | `https://adk.dev/graphs/human-input/index.md` | `references/graph-and-dynamic-workflows.md`, `references/adk-core-and-setup.md`, `SKILL.md` |
| `https://adk.dev/graphs/retry/` | `https://adk.dev/graphs/retry/index.md` | `references/graph-and-dynamic-workflows.md`, `SKILL.md` |
| `https://adk.dev/graphs/dynamic/` | `https://adk.dev/graphs/dynamic/index.md` | `references/graph-and-dynamic-workflows.md`, `references/adk-core-and-setup.md`, `SKILL.md` |

### 2.4 ADK Coding-Agent Toolsets & Source Contracts (`coding-agent-toolsets.md`)

| Canonical Upstream URL | Refresh Endpoint (`.md` / Raw Python Source) | Feeds Local File |
|---|---|---|
| `https://adk.dev/integrations/environment-toolset/` | `https://adk.dev/integrations/environment-toolset/index.md` | `references/coding-agent-toolsets.md`, `SKILL.md` |
| `https://adk.dev/integrations/bashtool/` | `https://adk.dev/integrations/bashtool/index.md` | `references/coding-agent-toolsets.md`, `SKILL.md` |
| `https://adk.dev/skills/` | `https://adk.dev/skills/index.md` | `references/coding-agent-toolsets.md` |
| `https://github.com/google/adk-python/blob/main/src/google/adk/environment/__init__.py` | `https://raw.githubusercontent.com/google/adk-python/main/src/google/adk/environment/__init__.py` | `references/coding-agent-toolsets.md` |
| `https://github.com/google/adk-python/blob/main/src/google/adk/environment/_base_environment.py` | `https://raw.githubusercontent.com/google/adk-python/main/src/google/adk/environment/_base_environment.py` | `references/coding-agent-toolsets.md`, `SKILL.md` |
| `https://github.com/google/adk-python/blob/main/src/google/adk/environment/_environment_scope.py` | `https://raw.githubusercontent.com/google/adk-python/main/src/google/adk/environment/_environment_scope.py` | `references/coding-agent-toolsets.md` |
| `https://github.com/google/adk-python/blob/main/src/google/adk/environment/_local_environment.py` | `https://raw.githubusercontent.com/google/adk-python/main/src/google/adk/environment/_local_environment.py` | `references/coding-agent-toolsets.md`, `SKILL.md` |
| `https://github.com/google/adk-python/blob/main/src/google/adk/tools/environment/__init__.py` | `https://raw.githubusercontent.com/google/adk-python/main/src/google/adk/tools/environment/__init__.py` | `references/coding-agent-toolsets.md` |
| `https://github.com/google/adk-python/blob/main/src/google/adk/tools/environment/_environment_toolset.py` | `https://raw.githubusercontent.com/google/adk-python/main/src/google/adk/tools/environment/_environment_toolset.py` | `references/coding-agent-toolsets.md`, `SKILL.md` |
| `https://github.com/google/adk-python/blob/main/src/google/adk/tools/bash_tool.py` | `https://raw.githubusercontent.com/google/adk-python/main/src/google/adk/tools/bash_tool.py` | `references/coding-agent-toolsets.md`, `SKILL.md` |
| `https://github.com/google/adk-python/blob/main/src/google/adk/tools/skill_toolset.py` | `https://raw.githubusercontent.com/google/adk-python/main/src/google/adk/tools/skill_toolset.py` | `references/coding-agent-toolsets.md` |
| `https://github.com/google/adk-python/blob/main/contributing/samples/environment_and_skills/local_environment/agent.py` | `https://raw.githubusercontent.com/google/adk-python/main/contributing/samples/environment_and_skills/local_environment/agent.py` | `references/coding-agent-toolsets.md` |
| `https://docs.cloud.google.com/gemini-enterprise-agent-platform/build/managed-agents` | `https://docs.cloud.google.com/gemini-enterprise-agent-platform/build/managed-agents.md.txt` | `references/coding-agent-toolsets.md` |
| `https://docs.cloud.google.com/gemini-enterprise-agent-platform/build/managed-agents/create-manage` | `https://docs.cloud.google.com/gemini-enterprise-agent-platform/build/managed-agents/create-manage.md.txt` | `references/coding-agent-toolsets.md` |
| `https://docs.cloud.google.com/gemini-enterprise-agent-platform/build/managed-agents/interact-with-agents` | `https://docs.cloud.google.com/gemini-enterprise-agent-platform/build/managed-agents/interact-with-agents.md.txt` | `references/coding-agent-toolsets.md` |

### 2.5 `google/agents-cli` Docs, Built-In Skills & Extensions (`agents-cli-lifecycle.md`)

| Canonical Upstream URL | Refresh Endpoint (`.md` / Raw) | Feeds Local File |
|---|---|---|
| `https://github.com/google/agents-cli` | `https://raw.githubusercontent.com/google/agents-cli/main/README.md` | `references/agents-cli-lifecycle.md`, `SKILL.md` |
| `https://adk.dev/get-started/agents-cli/` | `https://adk.dev/get-started/agents-cli/index.md` | `references/agents-cli-lifecycle.md` |
| `https://adk.dev/deploy/agent-runtime/agents-cli/` | `https://adk.dev/deploy/agent-runtime/agents-cli/index.md` | `references/agents-cli-lifecycle.md` |
| `https://github.com/google/agents-cli/blob/main/docs/src/guide/lifecycle.md` | `https://raw.githubusercontent.com/google/agents-cli/main/docs/src/guide/lifecycle.md` | `references/agents-cli-lifecycle.md` |
| `https://github.com/google/agents-cli/blob/main/docs/src/guide/deployment.md` | `https://raw.githubusercontent.com/google/agents-cli/main/docs/src/guide/deployment.md` | `references/agents-cli-lifecycle.md` |
| `https://github.com/google/agents-cli/blob/main/skills/google-agents-cli-workflow/SKILL.md` | `https://raw.githubusercontent.com/google/agents-cli/main/skills/google-agents-cli-workflow/SKILL.md` | `references/agents-cli-lifecycle.md` |
| `https://github.com/google/agents-cli/blob/main/skills/google-agents-cli-workflow/references/commands.md` | `https://raw.githubusercontent.com/google/agents-cli/main/skills/google-agents-cli-workflow/references/commands.md` | `references/agents-cli-lifecycle.md` |
| `https://github.com/google/agents-cli/blob/main/skills/google-agents-cli-workflow/references/extension.md` | `https://raw.githubusercontent.com/google/agents-cli/main/skills/google-agents-cli-workflow/references/extension.md` | `references/agents-cli-lifecycle.md` |
| `https://github.com/google/agents-cli/blob/main/skills/google-agents-cli-adk-code/SKILL.md` | `https://raw.githubusercontent.com/google/agents-cli/main/skills/google-agents-cli-adk-code/SKILL.md` | `references/adk-core-and-setup.md`, `references/agents-cli-lifecycle.md` |
| `https://github.com/google/agents-cli/blob/main/skills/google-agents-cli-adk-code/references/adk-python.md` | `https://raw.githubusercontent.com/google/agents-cli/main/skills/google-agents-cli-adk-code/references/adk-python.md` | `references/adk-core-and-setup.md` |
| `https://github.com/google/agents-cli/blob/main/skills/google-agents-cli-adk-code/references/adk-python-workflows.md` | `https://raw.githubusercontent.com/google/agents-cli/main/skills/google-agents-cli-adk-code/references/adk-python-workflows.md` | `references/adk-core-and-setup.md` |
| `https://github.com/google/agents-cli/blob/main/skills/google-agents-cli-adk-code/references/recipes.md` | `https://raw.githubusercontent.com/google/agents-cli/main/skills/google-agents-cli-adk-code/references/recipes.md` | `references/agents-cli-lifecycle.md` |
| `https://github.com/google/agents-cli/blob/main/skills/google-agents-cli-scaffold/SKILL.md` | `https://raw.githubusercontent.com/google/agents-cli/main/skills/google-agents-cli-scaffold/SKILL.md` | `references/agents-cli-lifecycle.md` |
| `https://github.com/google/agents-cli/blob/main/skills/google-agents-cli-scaffold/references/flags.md` | `https://raw.githubusercontent.com/google/agents-cli/main/skills/google-agents-cli-scaffold/references/flags.md` | `references/agents-cli-lifecycle.md` |
| `https://github.com/google/agents-cli/blob/main/skills/google-agents-cli-eval/SKILL.md` | `https://raw.githubusercontent.com/google/agents-cli/main/skills/google-agents-cli-eval/SKILL.md` | `references/agents-cli-lifecycle.md` |
| `https://github.com/google/agents-cli/blob/main/skills/google-agents-cli-deploy/SKILL.md` | `https://raw.githubusercontent.com/google/agents-cli/main/skills/google-agents-cli-deploy/SKILL.md` | `references/agents-cli-lifecycle.md` |
| `https://github.com/google/agents-cli/blob/main/skills/google-agents-cli-publish/SKILL.md` | `https://raw.githubusercontent.com/google/agents-cli/main/skills/google-agents-cli-publish/SKILL.md` | `references/agents-cli-lifecycle.md` |
| `https://github.com/google/agents-cli/blob/main/skills/google-agents-cli-observability/SKILL.md` | `https://raw.githubusercontent.com/google/agents-cli/main/skills/google-agents-cli-observability/SKILL.md` | `references/agents-cli-lifecycle.md` |
| `https://github.com/google/agents-cli/blob/main/schemas/agents-cli-extension-v1alpha1.schema.json` | `https://raw.githubusercontent.com/google/agents-cli/main/schemas/agents-cli-extension-v1alpha1.schema.json` | `references/agents-cli-lifecycle.md` |

---

## 3. Section-by-Section Refresh Checklist

Run this checklist quarterly or after any minor/major release of `google-adk`, `google-cloud-aiplatform`, or `google-agents-cli`:

1. **`references/adk-core-and-setup.md`:**
   - Check `https://adk.dev/2.0/index.md` and `https://adk.dev/agents/models/google-gemini/index.md` for new ADK 2.x releases, design contract updates, or regional model ID updates.
   - Verify whether `GOOGLE_GENAI_USE_ENTERPRISE=TRUE` defaults, `from agentplatform.frameworks import AdkApp`, or `google-cloud-agentplatform` (`>= 2.0.1`) / `google-cloud-aiplatform` (`>= 1.154.0`) SDK minimum versions changed.
   - Re-check `AdkApp` method signatures and `user_id` limits (`128` chars) in `create-an-adk-agent.md.txt`.
2. **`references/agent-architectures-and-workflows.md`:**
   - Check `https://adk.dev/agents/managed-agents/index.md` for `ManagedAgent` GA graduation, regional support beyond `global`, non-streaming/polling support, or `RemoteMcpServer` API changes.
   - Check `https://adk.dev/agents/service-registration/index.md` for new service types beyond `session`/`artifact`/`memory`/`task_store` or discovery/precedence changes (`services.yaml` vs `services.py`).
   - Check `https://adk.dev/workflows/collaboration/index.md` and `https://adk.dev/workflows/patterns/index.md` to verify whether `mode="task"` has been re-enabled in Python graph workflows, whether `Workflow` can be nested as an `LlmAgent` `sub_agent`, or whether `SecurityPlugin`/`BasePolicyEngine` expanded beyond TypeScript.
3. **`references/graph-and-dynamic-workflows.md`:**
   - Check `https://adk.dev/graphs/index.md` and `https://adk.dev/graphs/routes/index.md` for graph `LlmAgent` mode rules, `JoinNode` requirements, single-terminal-output `ValueError` rules, and third-party integration compatibility updates.
   - Check `https://adk.dev/graphs/data-handling/index.md` for single-`Event(output=...)` enforcement and Python `{key}` state-only templating vs TS `{Class.field}` / `<Class.field from node>`.
   - Check `https://adk.dev/graphs/human-input/index.md` and `https://adk.dev/graphs/retry/index.md` for `RequestInput` schema handling, `RetryConfig` defaults, `NodeTimeoutError`, and whether `ctx.attempt_count` persistence or TS/Java/Kotlin retry GA status changed.
   - Check `https://adk.dev/graphs/dynamic/index.md` for `@node(rerun_on_resume=True)`, `ctx.run_node`, `use_sub_branch=True`, and custom `run_id` non-numeric rules.
4. **`references/coding-agent-toolsets.md`:**
   - Fetch raw `_local_environment.py` and confirm whether `LocalEnvironment(working_dir=...)` now coerces `str` to `Path` (currently calls `self._working_dir.resolve()` directly).
   - Fetch raw `_base_environment.py` and `_environment_toolset.py`: verify whether `BaseEnvironment` gained new abstract methods, whether `working_dir` accepts `ctx`, or whether the `ctx` compatibility shim was removed.
   - Fetch raw `bash_tool.py` and verify `BashToolPolicy` default `allowed_command_prefixes=("*",)` and `blocked_operators=()`, plus POSIX-only and HITL confirmation behavior.
   - Fetch raw `skill_toolset.py` and verify `environment=` vs `code_executor=` mutual exclusion and `save_output_artifacts` support.
   - Check `build/managed-agents.md.txt` and `build/managed-agents/sandbox-environment.md.txt` (watch target) for GA graduation, new `base_agent` versions, or Python SDK `agents.update()` support.
5. **`references/agents-cli-lifecycle.md`:**
   - Diff `skills/google-agents-cli-*/SKILL.md` frontmatter triggers against this skill's `SKILL.md` `Use when` / `Don't use for` clauses to guarantee zero co-trigger shadowing.
   - Diff `scaffold/references/flags.md`, `workflow/references/extension.md`, and `adk-code/references/recipes.md` for added/deprecated flags, schema version bumps beyond `agents-cli-extension/v1alpha1`, or newly promoted `core/python/` recipes.
6. **`SKILL.md` & Automated Validation:**
   - Confirm `SKILL.md` stays strictly `< 350` lines (production ceiling `<= 450`), `description: >-` remains strictly `< 1024` characters, and every new subtopic in `references/*.md` is surfaced in `description` and the Modular References Table.
   - Update `Last Verified Date` above and run:
     ```bash
     python3 scripts/validate_skills.py .agents/skills
     ```
