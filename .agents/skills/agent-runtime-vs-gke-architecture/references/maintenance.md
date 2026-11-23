# Maintenance & Upstream Documentation Provenance

- **Skill Name:** `agent-runtime-vs-gke-architecture`
- **Last Verified Date:** `2026-11-23`
- **Mandatory Primary Seed URLs (3):**
  1. `https://docs.cloud.google.com/gemini-enterprise-agent-platform/scale/sandbox`
  2. `https://docs.cloud.google.com/gemini-enterprise-agent-platform/scale/runtime/manage-deployed-agents`
  3. `https://github.com/google/agents-cli`

---

## 1. Canonical Upstream Sources & Refresh Endpoints

Fetch the `.md.txt` (Google Cloud Docs), `.md` (`adk.dev`), or raw GitHub endpoints below when auditing this skill for CRD updates, quota changes, GKE version floors, or `agents-cli` releases.

### Primary Seed URLs & Core Platform Pages (3)

| Canonical URL | Refresh Endpoint | Owned Skill File |
|---|---|---|
| `https://docs.cloud.google.com/gemini-enterprise-agent-platform/scale/sandbox` | `https://docs.cloud.google.com/gemini-enterprise-agent-platform/scale/sandbox.md.txt` | `SKILL.md`, `references/comparison-matrix-and-limitations.md`, `references/hybrid-and-migration-patterns.md` |
| `https://docs.cloud.google.com/gemini-enterprise-agent-platform/scale/runtime/manage-deployed-agents` | `https://docs.cloud.google.com/gemini-enterprise-agent-platform/scale/runtime/manage-deployed-agents.md.txt` | `references/comparison-matrix-and-limitations.md`, `references/hybrid-and-migration-patterns.md` |
| `https://github.com/google/agents-cli` | `https://raw.githubusercontent.com/google/agents-cli/main/README.md` | `SKILL.md`, `references/hybrid-and-migration-patterns.md` |

### Tier-1 GKE Agent Sandbox, Networking, Pod Snapshots, Storage, Substrate & ADK-GKE Pages (20)

| Canonical URL | Refresh Endpoint | Owned Skill File |
|---|---|---|
| `https://adk.dev/deploy/gke/` | `https://adk.dev/deploy/gke/index.md` | `references/hybrid-and-migration-patterns.md` |
| `https://adk.dev/integrations/gke-code-executor/` | `https://adk.dev/integrations/gke-code-executor/index.md` | `SKILL.md`, `references/gke-agent-sandbox-reference.md` |
| `https://docs.cloud.google.com/kubernetes-engine/ai-ml/about-agent-substrate` | `https://docs.cloud.google.com/kubernetes-engine/ai-ml/about-agent-substrate.md.txt` | `references/comparison-matrix-and-limitations.md`, `references/gke-agent-sandbox-reference.md` |
| `https://docs.cloud.google.com/kubernetes-engine/ai-ml/install-overview-substrate` | `https://docs.cloud.google.com/kubernetes-engine/ai-ml/install-overview-substrate.md.txt` | `references/comparison-matrix-and-limitations.md`, `references/gke-agent-sandbox-reference.md` |
| `https://docs.cloud.google.com/kubernetes-engine/docs/how-to/design-substrate-infrastructure` | `https://docs.cloud.google.com/kubernetes-engine/docs/how-to/design-substrate-infrastructure.md.txt` | `references/comparison-matrix-and-limitations.md`, `references/gke-agent-sandbox-reference.md` |
| `https://docs.cloud.google.com/kubernetes-engine/docs/concepts/machine-learning/agent-sandbox` | `https://docs.cloud.google.com/kubernetes-engine/docs/concepts/machine-learning/agent-sandbox.md.txt` | `references/comparison-matrix-and-limitations.md`, `references/gke-agent-sandbox-reference.md` |
| `https://docs.cloud.google.com/kubernetes-engine/docs/concepts/machine-learning/agent-sandbox-storage` | `https://docs.cloud.google.com/kubernetes-engine/docs/concepts/machine-learning/agent-sandbox-storage.md.txt` | `references/comparison-matrix-and-limitations.md`, `references/gke-agent-sandbox-reference.md` |
| `https://docs.cloud.google.com/kubernetes-engine/docs/how-to/agent-sandbox-storage` | `https://docs.cloud.google.com/kubernetes-engine/docs/how-to/agent-sandbox-storage.md.txt` | `references/gke-agent-sandbox-reference.md` |
| `https://docs.cloud.google.com/kubernetes-engine/docs/concepts/machine-learning/agent-workloads` | `https://docs.cloud.google.com/kubernetes-engine/docs/concepts/machine-learning/agent-workloads.md.txt` | `SKILL.md`, `references/comparison-matrix-and-limitations.md`, `references/gke-agent-sandbox-reference.md` |
| `https://docs.cloud.google.com/kubernetes-engine/docs/how-to/agent-sandbox` | `https://docs.cloud.google.com/kubernetes-engine/docs/how-to/agent-sandbox.md.txt` | `references/gke-agent-sandbox-reference.md` |
| `https://docs.cloud.google.com/kubernetes-engine/docs/how-to/agent-sandbox-pod-snapshots` | `https://docs.cloud.google.com/kubernetes-engine/docs/how-to/agent-sandbox-pod-snapshots.md.txt` | `references/comparison-matrix-and-limitations.md`, `references/gke-agent-sandbox-reference.md` |
| `https://docs.cloud.google.com/kubernetes-engine/docs/concepts/pod-snapshots` | `https://docs.cloud.google.com/kubernetes-engine/docs/concepts/pod-snapshots.md.txt` | `references/comparison-matrix-and-limitations.md`, `references/gke-agent-sandbox-reference.md` |
| `https://docs.cloud.google.com/kubernetes-engine/docs/how-to/how-install-agent-sandbox` | `https://docs.cloud.google.com/kubernetes-engine/docs/how-to/how-install-agent-sandbox.md.txt` | `references/gke-agent-sandbox-reference.md` |
| `https://docs.cloud.google.com/kubernetes-engine/docs/concepts/sandbox-pods` | `https://docs.cloud.google.com/kubernetes-engine/docs/concepts/sandbox-pods.md.txt` | `references/comparison-matrix-and-limitations.md`, `references/gke-agent-sandbox-reference.md` |
| `https://docs.cloud.google.com/kubernetes-engine/docs/how-to/sandbox-pods` | `https://docs.cloud.google.com/kubernetes-engine/docs/how-to/sandbox-pods.md.txt` | `references/gke-agent-sandbox-reference.md` |
| `https://docs.cloud.google.com/kubernetes-engine/docs/concepts/dataplane-v2` | `https://docs.cloud.google.com/kubernetes-engine/docs/concepts/dataplane-v2.md.txt` | `references/comparison-matrix-and-limitations.md` |
| `https://docs.cloud.google.com/kubernetes-engine/docs/how-to/network-policy` | `https://docs.cloud.google.com/kubernetes-engine/docs/how-to/network-policy.md.txt` | `references/comparison-matrix-and-limitations.md` |
| `https://docs.cloud.google.com/kubernetes-engine/docs/how-to/fqdn-network-policies` | `https://docs.cloud.google.com/kubernetes-engine/docs/how-to/fqdn-network-policies.md.txt` | `SKILL.md`, `references/comparison-matrix-and-limitations.md` |
| `https://docs.cloud.google.com/kubernetes-engine/security/about-agent-identity` | `https://docs.cloud.google.com/kubernetes-engine/security/about-agent-identity.md.txt` | `references/comparison-matrix-and-limitations.md` |
| `https://docs.cloud.google.com/filestore/docs/agent-substrate` | `https://docs.cloud.google.com/filestore/docs/agent-substrate.md.txt` | `references/gke-agent-sandbox-reference.md` |

### Tier-1 Cross-Verified Agent Platform, Quotas, Networking & `agents-cli` Pages (20)

| Canonical URL | Refresh Endpoint | Owned Skill File |
|---|---|---|
| `https://docs.cloud.google.com/gemini-enterprise-agent-platform/resources/agent-quotas` | `https://docs.cloud.google.com/gemini-enterprise-agent-platform/resources/agent-quotas.md.txt` | `SKILL.md`, `references/comparison-matrix-and-limitations.md` |
| `https://docs.cloud.google.com/gemini-enterprise-agent-platform/scale/sandbox/code-execution-overview` | `https://docs.cloud.google.com/gemini-enterprise-agent-platform/scale/sandbox/code-execution-overview.md.txt` | `references/comparison-matrix-and-limitations.md` |
| `https://docs.cloud.google.com/gemini-enterprise-agent-platform/scale/sandbox/manage-sandboxes` | `https://docs.cloud.google.com/gemini-enterprise-agent-platform/scale/sandbox/manage-sandboxes.md.txt` | `references/comparison-matrix-and-limitations.md` |
| `https://docs.cloud.google.com/gemini-enterprise-agent-platform/scale/sandbox/manage-templates` | `https://docs.cloud.google.com/gemini-enterprise-agent-platform/scale/sandbox/manage-templates.md.txt` | `references/comparison-matrix-and-limitations.md` |
| `https://docs.cloud.google.com/gemini-enterprise-agent-platform/scale/sandbox/manage-snapshots` | `https://docs.cloud.google.com/gemini-enterprise-agent-platform/scale/sandbox/manage-snapshots.md.txt` | `references/comparison-matrix-and-limitations.md` |
| `https://docs.cloud.google.com/gemini-enterprise-agent-platform/scale/sandbox/custom-containers` | `https://docs.cloud.google.com/gemini-enterprise-agent-platform/scale/sandbox/custom-containers.md.txt` | `references/comparison-matrix-and-limitations.md` |
| `https://docs.cloud.google.com/gemini-enterprise-agent-platform/scale/sandbox/shell-sandbox-quickstart` | `https://docs.cloud.google.com/gemini-enterprise-agent-platform/scale/sandbox/shell-sandbox-quickstart.md.txt` | `references/comparison-matrix-and-limitations.md` |
| `https://docs.cloud.google.com/gemini-enterprise-agent-platform/scale/sandbox/configure-vpc-sc` | `https://docs.cloud.google.com/gemini-enterprise-agent-platform/scale/sandbox/configure-vpc-sc.md.txt` | `references/comparison-matrix-and-limitations.md` |
| `https://docs.cloud.google.com/gemini-enterprise-agent-platform/scale/sandbox/configure-cmek` | `https://docs.cloud.google.com/gemini-enterprise-agent-platform/scale/sandbox/configure-cmek.md.txt` | `references/comparison-matrix-and-limitations.md` |
| `https://adk.dev/integrations/code-exec-agent-runtime/` | `https://adk.dev/integrations/code-exec-agent-runtime/index.md` | `references/hybrid-and-migration-patterns.md` |
| `https://docs.cloud.google.com/gemini-enterprise-agent-platform/scale/runtime/deploy-an-agent` | `https://docs.cloud.google.com/gemini-enterprise-agent-platform/scale/runtime/deploy-an-agent.md.txt` | `references/comparison-matrix-and-limitations.md`, `references/hybrid-and-migration-patterns.md` |
| `https://docs.cloud.google.com/gemini-enterprise-agent-platform/scale/runtime/runtime-contract` | `https://docs.cloud.google.com/gemini-enterprise-agent-platform/scale/runtime/runtime-contract.md.txt` | `references/comparison-matrix-and-limitations.md` |
| `https://docs.cloud.google.com/gemini-enterprise-agent-platform/scale/runtime/optimize-and-scale` | `https://docs.cloud.google.com/gemini-enterprise-agent-platform/scale/runtime/optimize-and-scale.md.txt` | `references/comparison-matrix-and-limitations.md` |
| `https://docs.cloud.google.com/gemini-enterprise-agent-platform/scale/runtime/private-service-connect-interface` | `https://docs.cloud.google.com/gemini-enterprise-agent-platform/scale/runtime/private-service-connect-interface.md.txt` | `references/comparison-matrix-and-limitations.md`, `references/hybrid-and-migration-patterns.md` |
| `https://docs.cloud.google.com/gemini-enterprise-agent-platform/agent-anomalies-overview` | `https://docs.cloud.google.com/gemini-enterprise-agent-platform/agent-anomalies-overview.md.txt` | `references/comparison-matrix-and-limitations.md`, `references/hybrid-and-migration-patterns.md` |
| `https://github.com/google/agents-cli/blob/main/docs/src/guide/deployment.md` | `https://raw.githubusercontent.com/google/agents-cli/main/docs/src/guide/deployment.md` | `references/hybrid-and-migration-patterns.md` |
| `https://github.com/google/agents-cli/blob/main/docs/src/guide/lifecycle.md` | `https://raw.githubusercontent.com/google/agents-cli/main/docs/src/guide/lifecycle.md` | `references/hybrid-and-migration-patterns.md` |
| `https://github.com/google/agents-cli/blob/main/skills/google-agents-cli-deploy/SKILL.md` | `https://raw.githubusercontent.com/google/agents-cli/main/skills/google-agents-cli-deploy/SKILL.md` | `references/comparison-matrix-and-limitations.md`, `references/hybrid-and-migration-patterns.md` |
| `https://github.com/google/agents-cli/blob/main/skills/google-agents-cli-publish/SKILL.md` | `https://raw.githubusercontent.com/google/agents-cli/main/skills/google-agents-cli-publish/SKILL.md` | `references/hybrid-and-migration-patterns.md` |
| `https://github.com/kubernetes-sigs/agent-sandbox` | `https://github.com/kubernetes-sigs/agent-sandbox/releases` | `references/gke-agent-sandbox-reference.md` |

---

## 2. Uncached Tier-2 Upstream Targets (Re-Verify on Next Refresh)

> **Provenance Note:** The GKE Dataplane V2 `CiliumIdentity` `65,535` ceiling, `cilium-config-emergency-override`, and GKE `1.34.6-gke.1307000+` / `1.35.2-gke.1962000+` fix cited in `SKILL.md` and `references/comparison-matrix-and-limitations.md` originate from the uncached `troubleshooting/dataplane-v2-issues` doc below (not `concepts/dataplane-v2`). Prioritize caching and re-verifying these 6 URLs during the next refresh cycle:

1. `https://docs.cloud.google.com/kubernetes-engine/docs/troubleshooting/dataplane-v2-issues` (`.md.txt`) — Dataplane V2 `65,535` `CiliumIdentity` cap, `cilium-config-emergency-override`, and GKE `1.34.6-gke.1307000+` / `1.35.2-gke.1962000+` fix.
2. `https://github.com/kubernetes-sigs/agent-sandbox/blob/v1.0.6/docs/api.md` (raw GitHub) — Full `v1beta1` CRD schema reference.
3. `https://github.com/kubernetes-sigs/agent-sandbox/blob/v1.0.6/clients/python/agentic-sandbox-client/README.md` (raw GitHub) — `SandboxDirectConnectionConfig` & `SandboxGatewayConnectionConfig` constructor signatures.
4. `https://github.com/kubernetes-sigs/agent-sandbox/blob/v1.0.6/examples/policy/network-policy-management/README.md` (raw GitHub) — Custom `NetworkPolicy` templates for WIF & air-gapped sandboxes.
5. `https://github.com/google/adk-python/blob/main/contributing/samples/integrations/gke_agent_sandbox/deployment_rbac.yaml` (raw GitHub) — Ready-to-use K8s RBAC manifests for `GkeCodeExecutor`.
6. `https://github.com/ai-on-gke/substrate-gke/blob/main/tools/setup-gcp/README.md` (raw GitHub) — Full IAM bindings created by Substrate `setup-gcp`.

---

## 3. Section-by-Section Update Checklist

1. **`SKILL.md`:**
   - Keep strictly **150–380 lines (`< 450` lines)** and frontmatter `description` **`< 1024` chars** with `Use when` and `Don't use for` covering all 4 reference files and disambiguating sibling skills + `google-agents-cli-*`.
   - Confirm the hard-trigger table reflects current GPU/TPU, microVM, TTL, quota, and OAuth boundaries.
2. **`references/comparison-matrix-and-limitations.md`:**
   - Re-check `resources/agent-quotas.md.txt` for changes to `90 QPM`, `10 Bidi/min`, `1,000` sandbox entities, `6,000`/`950` revision limits, and Express Mode caps.
   - Re-verify `optimize-and-scale.md.txt` cold-start (`4.7s`/`0.4s`/`1.4s`) and concurrency (`9 -> 36`) benchmarks and `configure-vpc-sc.md.txt` (`max_instances` cap of `100`, PSC-E 1-project cap).
   - Check whether Managed Sandboxes gain native domain allowlisting or Terraform resources (`google_vertex_ai_sandbox_*`), or whether Managed OTel for GKE adds TLS/connector support.
3. **`references/gke-agent-sandbox-reference.md`:**
   - Check `kubernetes-sigs/agent-sandbox/releases` for releases newer than `v1.0.6` and pin `k8s-agent-sandbox==<version>` accordingly.
   - Check `agent-sandbox-pod-snapshots.md.txt` for changes to the `>= 1.35.3-gke.1234000` floor, E2/microVM/TPU exclusions, or GA status.
   - Check `about-agent-substrate.md.txt` and `filestore/docs/agent-substrate.md.txt` for GKE `>= 1.37` changes, Filestore agent volumes GA/snapshot support, or Autopilot/GPU support.
   - Check `adk.dev/integrations/gke-code-executor/index.md` for new `GkeCodeExecutor` parameters or default `executor_type` changes.
4. **`references/hybrid-and-migration-patterns.md`:**
   - Re-check `google/agents-cli` `deployment.md` and `google-agents-cli-deploy/SKILL.md` for changes to GKE flag support, `agent_runtime` revision rollback, `infra single-project` ordering, or Python/Go OTel capture env var alignment.
   - Re-check `adk.dev/deploy/gke/index.md` for Go CLI support or default `ClusterIP`/WIF changes.
5. **Run Validator After Every Edit (from repository root):**
   ```bash
   python3 scripts/validate_skills.py .agents/skills
   ```
