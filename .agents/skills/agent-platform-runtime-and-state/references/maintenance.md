# Maintenance & Upstream Verification Manifest

**Last Verified:** `2026-11-23`
**Skill:** `agent-platform-runtime-and-state`
**Scope:** Gemini Enterprise Agent Platform — Scale Pillar (Terraform Agent Runtime IaC, Deployed Runtime Operations & Quotas, Managed Sessions, Memory Bank, Feedback Service, and Runtime Telemetry).

---

## 1. Canonical Upstream Sources (All 8 Seed Pages + Verified Sub-Links)

### Seed Pages (8 — Required Coverage)

| # | Canonical Upstream URL | Markdown Refresh Endpoint | Mapped Reference File |
|---|---|---|---|
| 1 | https://docs.cloud.google.com/gemini-enterprise-agent-platform/scale/runtime/use-terraform | https://docs.cloud.google.com/gemini-enterprise-agent-platform/scale/runtime/use-terraform.md.txt | `references/terraform-deployment.md` |
| 2 | https://docs.cloud.google.com/gemini-enterprise-agent-platform/scale/runtime/manage-deployed-agents | https://docs.cloud.google.com/gemini-enterprise-agent-platform/scale/runtime/manage-deployed-agents.md.txt | `references/runtime-management-and-quotas.md` |
| 3 | https://docs.cloud.google.com/gemini-enterprise-agent-platform/scale/runtime/tracing | https://docs.cloud.google.com/gemini-enterprise-agent-platform/scale/runtime/tracing.md.txt | `references/runtime-telemetry.md` |
| 4 | https://docs.cloud.google.com/gemini-enterprise-agent-platform/scale/runtime/logging | https://docs.cloud.google.com/gemini-enterprise-agent-platform/scale/runtime/logging.md.txt | `references/runtime-telemetry.md` |
| 5 | https://docs.cloud.google.com/gemini-enterprise-agent-platform/scale/runtime/monitoring | https://docs.cloud.google.com/gemini-enterprise-agent-platform/scale/runtime/monitoring.md.txt | `references/runtime-telemetry.md` |
| 6 | https://docs.cloud.google.com/gemini-enterprise-agent-platform/scale/feedback-service | https://docs.cloud.google.com/gemini-enterprise-agent-platform/scale/feedback-service.md.txt | `references/feedback-service.md` |
| 7 | https://docs.cloud.google.com/gemini-enterprise-agent-platform/scale/sessions | https://docs.cloud.google.com/gemini-enterprise-agent-platform/scale/sessions.md.txt | `references/sessions-and-memory-bank.md` |
| 8 | https://docs.cloud.google.com/gemini-enterprise-agent-platform/scale/memory-bank | https://docs.cloud.google.com/gemini-enterprise-agent-platform/scale/memory-bank.md.txt | `references/sessions-and-memory-bank.md` |

### Verified Tier-1 & Cached Tier-2 Sub-Links (38)

| Domain | Canonical Upstream URL | Refresh Endpoint |
|---|---|---|
| **Runtime Setup & Access** | https://docs.cloud.google.com/gemini-enterprise-agent-platform/build/runtime/setup | `...build/runtime/setup.md.txt` |
| **Runtime Setup & Access** | https://docs.cloud.google.com/gemini-enterprise-agent-platform/scale/runtime/manage-agent-access | `...scale/runtime/manage-agent-access.md.txt` |
| **Runtime Setup & Access** | https://docs.cloud.google.com/gemini-enterprise-agent-platform/machine-learning/general/cmek | `...machine-learning/general/cmek.md.txt` |
| **Runtime Setup & Access** | https://docs.cloud.google.com/gemini-enterprise-agent-platform/scale/runtime/private-service-connect-interface | `...scale/runtime/private-service-connect-interface.md.txt` |
| **Runtime Deploy & Contract** | https://docs.cloud.google.com/gemini-enterprise-agent-platform/scale/runtime/deploy-an-agent | `...scale/runtime/deploy-an-agent.md.txt` |
| **Runtime Deploy & Contract** | https://docs.cloud.google.com/gemini-enterprise-agent-platform/scale/runtime/runtime-contract | `...scale/runtime/runtime-contract.md.txt` |
| **Runtime Deploy & Contract** | https://docs.cloud.google.com/gemini-enterprise-agent-platform/scale/runtime/agent-identity | `...scale/runtime/agent-identity.md.txt` |
| **Runtime Deploy & Contract** | https://docs.cloud.google.com/gemini-enterprise-agent-platform/scale/runtime/agent-gateway-runtime-deploy | `...scale/runtime/agent-gateway-runtime-deploy.md.txt` |
| **Runtime Ops & Scaling** | https://docs.cloud.google.com/gemini-enterprise-agent-platform/scale/runtime/manage-revisions-and-traffic | `...scale/runtime/manage-revisions-and-traffic.md.txt` |
| **Runtime Ops & Scaling** | https://docs.cloud.google.com/gemini-enterprise-agent-platform/scale/runtime/optimize-and-scale | `...scale/runtime/optimize-and-scale.md.txt` |
| **Runtime Ops & Scaling** | https://docs.cloud.google.com/gemini-enterprise-agent-platform/scale/runtime/bidirectional-streaming | `...scale/runtime/bidirectional-streaming.md.txt` |
| **Runtime Ops & Scaling** | https://docs.cloud.google.com/gemini-enterprise-agent-platform/scale/runtime/use-an-agent | `...scale/runtime/use-an-agent.md.txt` |
| **Runtime Ops & Scaling** | https://docs.cloud.google.com/gemini-enterprise-agent-platform/scale/runtime/use-an-adk-agent | `...scale/runtime/use-an-adk-agent.md.txt` |
| **Runtime Ops & Scaling** | https://docs.cloud.google.com/gemini-enterprise-agent-platform/scale/runtime/use-a-custom-agent | `...scale/runtime/use-a-custom-agent.md.txt` |
| **Quotas & Locations** | https://docs.cloud.google.com/gemini-enterprise-agent-platform/resources/agent-quotas | `...resources/agent-quotas.md.txt` |
| **Quotas & Locations** | https://docs.cloud.google.com/gemini-enterprise-agent-platform/resources/agent-locations | `...resources/agent-locations.md.txt` |
| **Managed Sessions** | https://docs.cloud.google.com/gemini-enterprise-agent-platform/scale/sessions/manage-with-adk | `...scale/sessions/manage-with-adk.md.txt` |
| **Managed Sessions** | https://docs.cloud.google.com/gemini-enterprise-agent-platform/scale/sessions/manage-with-api | `...scale/sessions/manage-with-api.md.txt` |
| **Managed Sessions** | https://docs.cloud.google.com/gemini-enterprise-agent-platform/scale/sessions/iam-conditions | `...scale/sessions/iam-conditions.md.txt` |
| **Memory Bank** | https://docs.cloud.google.com/gemini-enterprise-agent-platform/scale/memory-bank/setup | `...scale/memory-bank/setup.md.txt` |
| **Memory Bank** | https://docs.cloud.google.com/gemini-enterprise-agent-platform/scale/memory-bank/adk-quickstart | `...scale/memory-bank/adk-quickstart.md.txt` |
| **Memory Bank** | https://docs.cloud.google.com/gemini-enterprise-agent-platform/scale/memory-bank/api-quickstart | `...scale/memory-bank/api-quickstart.md.txt` |
| **Memory Bank** | https://docs.cloud.google.com/gemini-enterprise-agent-platform/scale/memory-bank/use-with-adk | `...scale/memory-bank/use-with-adk.md.txt` |
| **Memory Bank** | https://docs.cloud.google.com/gemini-enterprise-agent-platform/scale/memory-bank/generate-memories | `...scale/memory-bank/generate-memories.md.txt` |
| **Memory Bank** | https://docs.cloud.google.com/gemini-enterprise-agent-platform/scale/memory-bank/ingest-events | `...scale/memory-bank/ingest-events.md.txt` |
| **Memory Bank** | https://docs.cloud.google.com/gemini-enterprise-agent-platform/scale/memory-bank/fetch-memories | `...scale/memory-bank/fetch-memories.md.txt` |
| **Memory Bank** | https://docs.cloud.google.com/gemini-enterprise-agent-platform/scale/memory-bank/profiles | `...scale/memory-bank/profiles.md.txt` |
| **Memory Bank** | https://docs.cloud.google.com/gemini-enterprise-agent-platform/scale/memory-bank/revisions | `...scale/memory-bank/revisions.md.txt` |
| **Memory Bank** | https://docs.cloud.google.com/gemini-enterprise-agent-platform/scale/memory-bank/iam-conditions | `...scale/memory-bank/iam-conditions.md.txt` |
| **Feedback Service** | https://docs.cloud.google.com/gemini-enterprise-agent-platform/scale/feedback-service/manage-with-sdk-or-api | `...scale/feedback-service/manage-with-sdk-or-api.md.txt` |
| **Feedback Service** | https://docs.cloud.google.com/gemini-enterprise-agent-platform/scale/feedback-service/view-with-ui | `...scale/feedback-service/view-with-ui.md.txt` |
| **ADK Docs** | https://adk.dev/deploy/agent-runtime/ | https://adk.dev/deploy/agent-runtime/index.md |
| **ADK Docs** | https://adk.dev/deploy/agent-runtime/deploy/ | https://adk.dev/deploy/agent-runtime/deploy/index.md |
| **ADK Docs** | https://adk.dev/deploy/agent-runtime/agents-cli/ | https://adk.dev/deploy/agent-runtime/agents-cli/index.md |
| **ADK Docs** | https://adk.dev/sessions/ | https://adk.dev/sessions/index.md |
| **ADK Docs** | https://adk.dev/sessions/session/ | https://adk.dev/sessions/session/index.md |
| **ADK Docs** | https://adk.dev/sessions/memory/ | https://adk.dev/sessions/memory/index.md |
| **`agents-cli` Boundary** | https://github.com/google/agents-cli | https://raw.githubusercontent.com/google/agents-cli/main/skills/google-agents-cli-deploy/SKILL.md |

### Additional Deep-Dive Reference URLs to Check on Future Refreshes

- REST API schemas: `https://docs.cloud.google.com/gemini-enterprise-agent-platform/reference/rest/v1/projects.locations.reasoningEngines.md.txt`, `https://docs.cloud.google.com/gemini-enterprise-agent-platform/reference/rest/v1beta1/ReasoningEngineSpec.md.txt`, `https://docs.cloud.google.com/gemini-enterprise-agent-platform/reference/rest/v1beta1/projects.locations.reasoningEngines.sessions.md.txt`
- Troubleshooting & Metrics: `https://docs.cloud.google.com/gemini-enterprise-agent-platform/troubleshooting/memory-bank.md.txt`, `https://docs.cloud.google.com/gemini-enterprise-agent-platform/troubleshooting/troubleshoot-agent-gateway.md.txt`, `https://docs.cloud.google.com/monitoring/api/metrics_gcp_a_b.md.txt`, `https://docs.cloud.google.com/stackdriver/docs/instrumentation/collect-view-multimodal-prompts-responses.md.txt`
- `agents-cli` deploy sub-references: `https://raw.githubusercontent.com/google/agents-cli/main/skills/google-agents-cli-deploy/references/agent-runtime.md`, `.../terraform-patterns.md`, `.../cmek.md`

---

## 2. Section-by-Section Update Checklist

When refreshing this skill after upstream releases, re-verify each module in order:

- [ ] **`SKILL.md` (Frontmatter, Quick Decision Tree & Gotchas)**
  - Confirm `google-cloud-agentplatform` minimum version (`>= 2.0.1`), `google-adk` minimum versions (`>= 2.1` for `user.id`, `>= 2.6.0` for GenAI metrics), and `GOOGLE_GENAI_USE_ENTERPRISE="TRUE"`.
  - Confirm `SKILL.md` stays strictly `< 450` lines (target `150–380`) and frontmatter `description` stays `< 1024` chars with explicit `Use when` and `Don't use for` clauses covering all sibling skills and `google-agents-cli-*` built-ins.
- [ ] **`references/terraform-deployment.md`**
  - Re-fetch `use-terraform.md.txt`, `agent-identity.md.txt`, `agent-gateway-runtime-deploy.md.txt`, `private-service-connect-interface.md.txt`, and `manage-agent-access.md.txt`.
  - Verify whether `identity_type = "AGENT_IDENTITY"` and `agent_gateway_config` have graduated from `google-beta` to GA `hashicorp/google`, and confirm `>= 6.0.0` provider floor.
  - Check upstream doc-bug fixes: `location = var.location` typo on `advanced_weather_agent` (`use-terraform`), `element(split(...), -1)` crash (`agent-identity`).
  - Confirm service-agent emails (`gcp-sa-aiplatform-re`, `gcp-sa-aiplatform`, `gcp-sa-vertex-sandbox`) and VPC-SC/CMEK limitations.
- [ ] **`references/runtime-management-and-quotas.md`**
  - Re-fetch `manage-deployed-agents.md.txt`, `manage-revisions-and-traffic.md.txt`, `runtime-contract.md.txt`, `optimize-and-scale.md.txt`, `agent-quotas.md.txt`, and `agent-locations.md.txt`.
  - Check whether Revisions/Traffic Splitting and `keep_alive_probe` have moved from `v1beta1`/Preview to `v1`/GA.
  - Verify quota defaults (`90` QPM query, `300` session event appends, `100` session/memory writes, `300` memory reads, `6,000`/`950` revision hard limits), Express Mode limits, and regional exceptions (`asia-southeast2`, `australia-southeast2`, `northamerica-northeast2`, `asia-east2`, `asia-northeast3`).
  - Re-check date-bound milestones: April 22, 2026 (async query jobs), April 29, 2026 (Agent Gateway binding), September 8, 2026 (VPC-SC + Agent Gateway).
- [ ] **`references/sessions-and-memory-bank.md`**
  - Re-fetch `sessions*.md.txt` and `memory-bank*.md.txt` (including `profiles.md.txt`).
  - Verify default Memory Bank LLM (`gemini-3.5-flash` post-June 29, 2026) and `gemini-embedding-2` location restrictions (`global`, `us`, `eu`).
  - Check upstream doc discrepancies: `manage-with-api.md` REST `appendEvent` copy-paste bug, `manage-with-adk.md` `resource_name=` vs `name=`, `session.response.name` vs `session.name`, `unstructured_memory_configs` vs `customization_configs`, `granular_ttl` vs `granular_ttl_config`, `memory_revision_default_ttl` vs `revision_ttl`.
  - Verify IAM Conditions limits (1,500 principals; `ListSessions`, `ListMemories`, `PurgeMemories` unsupported).
- [ ] **`references/feedback-service.md`**
  - Re-fetch `feedback-service*.md.txt`.
  - Check whether Feedback Service has graduated from Preview/`v1beta1` to GA/`v1`.
  - Re-verify the SDK path asymmetry (`feedback_contexts.update(name=entry_name)` vs `feedback_contexts.get(name=f"{entry_name}/feedbackContext")`), standard label list, and `gcp.vertex.agent.feedback` trace span attributes.
- [ ] **`references/runtime-telemetry.md`**
  - Re-fetch `tracing.md.txt`, `logging.md.txt`, and `monitoring.md.txt`.
  - Verify `OTEL_INSTRUMENTATION_GENAI_CAPTURE_MESSAGE_CONTENT` enum requirement in ADK Python, May 22, 2026 `user.id` cutoff, child-resource Cloud Logging status, built-in `reasoning_engine/*` metrics, and `generic_node` requirement for user-defined metrics.
- [ ] **Automated Validation**
  - Run `python3 scripts/validate_skills.py .agents/skills` from the repository root and confirm `[PASS] agent-platform-runtime-and-state` with zero errors, zero warnings, zero orphan references, and zero 2-hop links.
