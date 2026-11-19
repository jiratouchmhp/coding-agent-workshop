# Maintenance & Upstream Verification Manifest

**Last Verified:** `2026-11-19`
**Skill:** `agent-platform-governance-and-registries`
**Scope:** Gemini Enterprise Agent Platform — Build & Govern Pillars (Skill Registry Packaging & CRUD, Agent Registry Registration/Standalone Skills/Scanning/Search/Bindings/Quotas, ADK Registry Consumption, SPIFFE Agent Identity, Semantic Governance Policies, Agent Gateway, IAM UAPs, Model Armor, Dry-Run Reporting, Topology & Security Findings).

---

## 1. Canonical Upstream Sources (Seed + All 51 Verified Sub-Links & Source Files)

### Seed Page (Required Coverage)

| # | Canonical Upstream URL | Markdown Refresh Endpoint | Mapped Reference File |
|---|---|---|---|
| 1 | https://docs.cloud.google.com/gemini-enterprise-agent-platform/build/skill-registry | https://docs.cloud.google.com/gemini-enterprise-agent-platform/build/skill-registry.md.txt | `references/skill-registry-packaging.md` |

### Verified Tier-1 Cloud Docs, ADK Docs & Live `adk-python` Source Files (51)

| Domain | Canonical Upstream URL | Markdown / Raw Refresh Endpoint |
|---|---|---|
| **Skill Registry (`v1beta1`)** | https://docs.cloud.google.com/gemini-enterprise-agent-platform/build/skill-registry/create-manage | `...build/skill-registry/create-manage.md.txt` |
| **ADK Consumption Docs** | https://adk.dev/integrations/skills-registry/ | https://adk.dev/integrations/skills-registry/index.md |
| **ADK Consumption Docs** | https://adk.dev/skills/ | https://adk.dev/skills/index.md |
| **ADK Consumption Docs** | https://adk.dev/integrations/agent-registry/ | https://adk.dev/integrations/agent-registry/index.md |
| **ADK Python Source** | https://github.com/google/adk-python/blob/main/src/google/adk/integrations/skill_registry/gcp_skill_registry.py | https://raw.githubusercontent.com/google/adk-python/main/src/google/adk/integrations/skill_registry/gcp_skill_registry.py |
| **ADK Python Source** | https://github.com/google/adk-python/blob/main/src/google/adk/integrations/agent_registry/agent_registry.py | https://raw.githubusercontent.com/google/adk-python/main/src/google/adk/integrations/agent_registry/agent_registry.py |
| **ADK Python Source** | https://github.com/google/adk-python/blob/main/src/google/adk/tools/skill_toolset.py | https://raw.githubusercontent.com/google/adk-python/main/src/google/adk/tools/skill_toolset.py |
| **Agent Registry Core** | https://docs.cloud.google.com/agent-registry/overview | `...agent-registry/overview.md.txt` |
| **Agent Registry Core** | https://docs.cloud.google.com/agent-registry/setup | `...agent-registry/setup.md.txt` |
| **Agent Registry Core** | https://docs.cloud.google.com/agent-registry/data-model | `...agent-registry/data-model.md.txt` |
| **Agent Registry Core** | https://docs.cloud.google.com/agent-registry/identity-and-identifiers | `...agent-registry/identity-and-identifiers.md.txt` |
| **Agent Registry Core** | https://docs.cloud.google.com/agent-registry/boundaries-and-topology | `...agent-registry/boundaries-and-topology.md.txt` |
| **Agent Registry Core** | https://docs.cloud.google.com/agent-registry/roles-permissions | `...agent-registry/roles-permissions.md.txt` |
| **Agent Registry Core** | https://docs.cloud.google.com/agent-registry/quotas | `...agent-registry/quotas.md.txt` |
| **Agent Registry Core** | https://docs.cloud.google.com/gemini-enterprise-agent-platform/govern/agent-registry | `...govern/agent-registry.md.txt` |
| **Agent Registry Skills** | https://docs.cloud.google.com/agent-registry/skills-architecture | `...agent-registry/skills-architecture.md.txt` |
| **Agent Registry Skills** | https://docs.cloud.google.com/agent-registry/register-skills | `...agent-registry/register-skills.md.txt` |
| **Agent Registry Skills** | https://docs.cloud.google.com/agent-registry/manage-skills | `...agent-registry/manage-skills.md.txt` |
| **Agent Registry Skills** | https://docs.cloud.google.com/agent-registry/manage-skill-revisions | `...agent-registry/manage-skill-revisions.md.txt` |
| **Agent Registry Skills** | https://docs.cloud.google.com/agent-registry/scan-skills | `...agent-registry/scan-skills.md.txt` |
| **Agent Registry Services** | https://docs.cloud.google.com/agent-registry/manual-registration | `...agent-registry/manual-registration.md.txt` |
| **Agent Registry Services** | https://docs.cloud.google.com/agent-registry/register-custom-adk-agents | `...agent-registry/register-custom-adk-agents.md.txt` |
| **Agent Registry Services** | https://docs.cloud.google.com/agent-registry/search-agents-and-tools | `...agent-registry/search-agents-and-tools.md.txt` |
| **Agent Registry Services** | https://docs.cloud.google.com/agent-registry/manage-bindings | `...agent-registry/manage-bindings.md.txt` |
| **Agent Registry Services** | https://docs.cloud.google.com/agent-registry/authenticate-toolsets | `...agent-registry/authenticate-toolsets.md.txt` |
| **Agent Registry Services** | https://docs.cloud.google.com/agent-registry/resolve-endpoints-and-build-orchestrators | `...agent-registry/resolve-endpoints-and-build-orchestrators.md.txt` |
| **Semantic Governance** | https://docs.cloud.google.com/gemini-enterprise-agent-platform/govern/policies/semantic-governance-overview | `...govern/policies/semantic-governance-overview.md.txt` |
| **Semantic Governance** | https://docs.cloud.google.com/gemini-enterprise-agent-platform/govern/policies/configure-semantic-governance | `...govern/policies/configure-semantic-governance.md.txt` |
| **Semantic Governance** | https://docs.cloud.google.com/gemini-enterprise-agent-platform/govern/policies/govern-agent-skills | `...govern/policies/govern-agent-skills.md.txt` |
| **Semantic Governance** | https://docs.cloud.google.com/gemini-enterprise-agent-platform/govern/policies/best-practices | `...govern/policies/best-practices.md.txt` |
| **SPIFFE Agent Identity** | https://docs.cloud.google.com/gemini-enterprise-agent-platform/govern/agent-identity-overview | `...govern/agent-identity-overview.md.txt` |
| **SPIFFE Agent Identity** | https://docs.cloud.google.com/gemini-enterprise-agent-platform/govern/identity-delegation-architecture | `...govern/identity-delegation-architecture.md.txt` |
| **Agent Gateway** | https://docs.cloud.google.com/gemini-enterprise-agent-platform/govern/gateways/agent-gateway-overview | `...govern/gateways/agent-gateway-overview.md.txt` |
| **Agent Gateway** | https://docs.cloud.google.com/gemini-enterprise-agent-platform/govern/gateways/set-up-agent-gateway | `...govern/gateways/set-up-agent-gateway.md.txt` |
| **Agent Gateway** | https://docs.cloud.google.com/gemini-enterprise-agent-platform/govern/gateways/manage-agent-gateways | `...govern/gateways/manage-agent-gateways.md.txt` |
| **Agent Gateway** | https://docs.cloud.google.com/gemini-enterprise-agent-platform/govern/gateways/agent-gateway-ge-deploy | `...govern/gateways/agent-gateway-ge-deploy.md.txt` |
| **Agent Gateway** | https://docs.cloud.google.com/gemini-enterprise-agent-platform/govern/gateways/delegate-authorization | `...govern/gateways/delegate-authorization.md.txt` |
| **Agent Gateway** | https://docs.cloud.google.com/gemini-enterprise-agent-platform/govern/gateways/set-up-vpc-connectivity | `...govern/gateways/set-up-vpc-connectivity.md.txt` |
| **Agent Gateway** | https://docs.cloud.google.com/gemini-enterprise-agent-platform/govern/gateways/monitor-agent-gateway | `...govern/gateways/monitor-agent-gateway.md.txt` |
| **Agent Gateway** | https://docs.cloud.google.com/gemini-enterprise-agent-platform/agents/governance/agent-gateway-cross-cloud/overview | `...agents/governance/agent-gateway-cross-cloud/overview.md.txt` |
| **Model Armor** | https://docs.cloud.google.com/gemini-enterprise-agent-platform/govern/configure-model-armor | `...govern/configure-model-armor.md.txt` |
| **IAM UAPs & Dry-Run** | https://docs.cloud.google.com/gemini-enterprise-agent-platform/govern/policies/configure-iam-policies | `...govern/policies/configure-iam-policies.md.txt` |
| **IAM UAPs & Dry-Run** | https://docs.cloud.google.com/gemini-enterprise-agent-platform/govern/policies/iam-overview-uap | `...govern/policies/iam-overview-uap.md.txt` |
| **IAM UAPs & Dry-Run** | https://docs.cloud.google.com/gemini-enterprise-agent-platform/govern/policies/configure-iam-policies-uap | `...govern/policies/configure-iam-policies-uap.md.txt` |
| **IAM UAPs & Dry-Run** | https://docs.cloud.google.com/gemini-enterprise-agent-platform/govern/policies/manage-iam-policies-uap | `...govern/policies/manage-iam-policies-uap.md.txt` |
| **IAM UAPs & Dry-Run** | https://docs.cloud.google.com/gemini-enterprise-agent-platform/govern/policies/cel-attributes-uap | `...govern/policies/cel-attributes-uap.md.txt` |
| **IAM UAPs & Dry-Run** | https://docs.cloud.google.com/gemini-enterprise-agent-platform/govern/policies/dry-run-report | `...govern/policies/dry-run-report.md.txt` |
| **Topology & Security** | https://docs.cloud.google.com/gemini-enterprise-agent-platform/govern/topology | `...govern/topology.md.txt` |
| **Topology & Security** | https://docs.cloud.google.com/gemini-enterprise-agent-platform/govern/topology/view-agent-registry-topology | `...govern/topology/view-agent-registry-topology.md.txt` |
| **Topology & Security** | https://docs.cloud.google.com/gemini-enterprise-agent-platform/govern/topology/view-project-topology | `...govern/topology/view-project-topology.md.txt` |
| **Topology & Security** | https://docs.cloud.google.com/gemini-enterprise-agent-platform/govern/view-security-findings | `...govern/view-security-findings.md.txt` |

### Additional Deep-Dive URLs to Watch on Future Refreshes
- Auth Manager overview & OAuth flows: `https://docs.cloud.google.com/iam/docs/auth-manager-overview.md.txt`, `https://docs.cloud.google.com/iam/docs/auth-with-2lo-v2.md.txt`, `https://docs.cloud.google.com/iam/docs/auth-with-3lo-v2.md.txt`, `https://docs.cloud.google.com/iam/docs/auth-with-api-key-v2.md.txt`
- ADK Python sample agent: `https://raw.githubusercontent.com/google/adk-python/main/contributing/samples/integrations/agent_registry_agent/agent.py`
- Google-managed skills catalog: `https://github.com/google/skills/tree/main`
- Agent Skills open specification: `https://agentskills.io/specification`

---

## 2. Section-by-Section Update Checklist

When refreshing this skill after upstream SDK, CLI, or platform releases, re-verify each section in order:

- [ ] **`SKILL.md` (Frontmatter, Decision Tree & Gotchas)**
  - Confirm frontmatter `name` matches directory (`agent-platform-governance-and-registries`), `description` uses `>-`, stays strictly `< 1024` chars, lists every reference subtopic under `Use when`, and disambiguates all sibling skills + `google-agents-cli-*` under `Don't use for`.
  - Confirm `SKILL.md` stays within `150–380` lines (strictly `< 450` lines).
- [ ] **`references/skill-registry-packaging.md`**
  - Re-fetch `build/skill-registry.md.txt` and `build/skill-registry/create-manage.md.txt`.
  - Verify whether new regions, CMEK, HIPAA, or VPC-SC support have been added to Vertex AI Skill Registry.
  - Re-check all 16 atomic ZIP / `SKILL.md` validation rules, `google-cloud-aiplatform >= 1.154.0` `skill_id` top-level signature, `SKILL_ID` deletion reuse lockout wording, and `gcp-skill-registry` first-call ingestion quirk.
  - Keep `scripts/package_registry_skill.py` in sync with any new validation limits.
- [ ] **`references/agent-registry-and-discovery.md`**
  - Re-fetch `agent-registry/*.md.txt` (`skills-architecture`, `register-skills`, `manage-skills`, `manage-skill-revisions`, `scan-skills`, `manual-registration`, `search-agents-and-tools`, `manage-bindings`, `quotas`).
  - Confirm whether standalone skills still auto-prepend `private-`, whether custom `Publisher` creation or managed Org Policy constraints have launched, and whether allocation/rate quotas or ZIP limits (`1 MB` / `10 MB`) have changed.
  - Confirm whether `gcloud agent-registry` subcommands have promoted from `alpha` to GA.
- [ ] **`references/adk-consuming-registries.md`**
  - Re-fetch `adk.dev/integrations/skills-registry/index.md`, `adk.dev/integrations/agent-registry/index.md`, and live `adk-python` `main` (`gcp_skill_registry.py`, `agent_registry.py`, `skill_toolset.py`).
  - Re-check whether `GCPSkillRegistry` has stabilized from `agentregistry.googleapis.com/v1alpha` to `v1` and whether `POST skills:search` GET-fallback was removed.
  - Confirm minimum `google-adk` floor (`>= 2.0.0` for `google-adk[a2a,agent-identity,mcp]`), `RemoteA2aAgent.clone()`, `header_provider` scope, and Go `agentregistry` options.
- [ ] **`references/semantic-governance-and-identity.md`**
  - Re-fetch `govern/policies/*.md.txt`, `govern/agent-identity-overview.md.txt`, `govern/gateways/*.md.txt`, and `govern/configure-model-armor.md.txt`.
  - Check whether Semantic Governance has added streaming model response support, expanded beyond 8 regions, or promoted `gcloud beta ai semantic-governance-*` to GA.
  - Re-verify the `iamEnforcementMode` API validator quirk (whether `"ENFORCED"` is still rejected), UAP GA scope, Model Armor token limits (`65,536` / `130,000` / `4 MB`), VPC-SC September 8, 2026 gateway cutoff, and App Topology October 15, 2026 billing transition.
- [ ] **Automated Validation**
  - Run `python3 scripts/validate_skills.py .agents/skills` from the repository root and confirm `[PASS] agent-platform-governance-and-registries` with zero errors, zero warnings, zero orphan references, and zero 2-hop links.
