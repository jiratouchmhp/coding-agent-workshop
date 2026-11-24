---
name: agent-runtime-vs-gke-architecture
description: >-
  Compares Agent Platform (Agent Runtime + Managed Sandbox) vs self-hosted ADK
  on GKE (Agent Sandbox, Agent Substrate) and agents-cli targets. Use when
  comparing all 14 architecture/quota/limitation dimensions (TTLs, warm pools,
  GPU/TPU, gVisor/microVM/Kata, Pod Snapshots >=1.35.3 non-E2, PSC-I+NGFW/SWP
  vs NetworkPolicy/FQDNNetworkPolicy/Dataplane V2 identity cap, SPIFFE vs WIF,
  audit gaps, Agent Platform vs GKE quota trade-offs, TCO), configuring
  kubernetes-sigs/agent-sandbox v1.0.6 CRDs, k8s-agent-sandbox SDK,
  GkeCodeExecutor, secure-sandbox-policy VAP, PodMonitoring,
  Hyperdisk/Filestore, or Agent Substrate, deploying via adk deploy gke, or
  planning hybrid/migration across agent_runtime, cloud_run, and gke. Don't use
  for Managed Sandbox (agent-platform-sandbox-byoc), Runtime TF/operational QPM
  sizing/state (agent-platform-runtime-and-state), ADK
  (adk-coding-agent-build), registries
  (agent-platform-governance-and-registries), evals
  (agent-platform-optimize-and-eval), or routine google-agents-cli-deploy.
---

# Agent Runtime vs. Self-Hosted GKE Architecture Guide

Decision playbook and technical reference for choosing between **Gemini Enterprise Agent Platform** (Serverless Agent Runtime + Managed BYOC Sandbox), **Self-Hosted ADK on GKE + GKE Agent Sandbox** (`kubernetes-sigs/agent-sandbox` `v1.0.6`), **Self-Hosted GKE + GKE Agent Substrate** (`agent-substrate/substrate`), and **`agents-cli`** (`google-agents-cli` `v1.15.0`) multi-target graduation workflows.

> **Workshop Module 8 Mode (Read-Only Architecture Information Guide):** Module 8 (`workshop/08-ARCHITECTURE-AGENT-RUNTIME-VS-GKE.md`) is a **read-only Architecture Information Guide** — there are **no hands-on coding exercises and no live GKE cluster required**. Both `starter/gke_reference/` and `solution/gke_reference/` ship complete, hardened, ready-to-inspect reference files (`rbac.yaml`, `sandbox_template.yaml`, `sandbox_warmpool.yaml`, and `gke_agent_example.py` — inspect offline via `python starter/gke_reference/gke_agent_example.py --mode inspect`).

> **Four Distinct Layers — Never Conflate Them:**
> 1. **Agent Runtime + Managed Sandbox**: Serverless `ReasoningEngine` + Google-managed tenant gVisor `SandboxEnvironment` (lowest ops, SPIFFE Identity, Managed Agent Gateway, 3LO OAuth, CPU-only, 7d/14d sandbox TTLs).
> 2. **GKE Agent Sandbox (Pod-based, `v1.0.6`)**: 1 dedicated K8s Pod per sandbox (`v1beta1` CRDs), Standard & Autopilot, GPU/TPU (`gVisor`), microVMs (Standard), custom `PodSpec`/sidecars, Pod Snapshots (`whole-pod` `>= 1.35.3-gke.1234000`, gVisor, non-E2, + NVIDIA `cuda-checkpoint` GPU support; `rootfs-only` `>= 1.35.3-gke.1031000`, supports E2/cross-family restore).
> 3. **GKE Agent Substrate (Actor-based, GKE Default)**: Actors multiplexed onto shared `WorkerPool` Pods outside `kube-apiserver`/`etcd`; GKE Standard `>= 1.37` x86 CPU-only (min `c3-standard-4`); `< 1s` 3-layer GCS resume & per-actor SPIFFE/Envoy egress credential injection.
> 4. **`agents-cli` (`v1.15.0`)**: Multi-target scaffold/eval/Terraform/deploy/publish DX layer (`-d agent_runtime | cloud_run | gke`) — deploys agent containers only; does **not** install GKE Agent Sandbox/Substrate CRDs or Managed Sandboxes.

---

## Quick Decision Tree

```text
What constraint dominates your agent architecture?
├── Zero cluster ops, CPU-only, <=7d/14d sandbox TTL, SPIFFE Identity, Managed Agent Gateway, 3LO OAuth, native ADK Gemini publish
│   └── START HERE: Agent Runtime + Managed Sandbox (pre-request quota if >90 QPM or >300 session appends/min)
├── Need custom HTTP/UI/WebSockets, kubectl rollback, or >90 QPM / >10 Bidi/min — WITHOUT managing gVisor pools
│   └── Hybrid Pattern A: Self-hosted ADK on GKE or Cloud Run -> Managed Scale Sandbox (minimal parent ReasoningEngine)
├── Need Agent Runtime governance/3LO/Gemini publish — PLUS GPUs/TPUs, microVMs, >14d workspaces, or >1,000 sandboxes/region
│   └── Hybrid Pattern B: Agent Runtime -> GKE Agent Sandbox/Substrate over PSC-I + GKE Gateway API
├── High-density intermittent CPU agents (thousands to millions of idle-heavy coding/productivity sessions, <1s resume, best TCO)
│   └── Pure GKE Agent Substrate (Standard >=1.37, x86 non-E2, NO GKE Sandbox on worker pools, Filestore agent volumes)
└── Dedicated K8s Pod per agent (GPUs/TPUs on gVisor, custom sidecars/initContainers, Arm nodes, GKE Autopilot, persistent dev/Jupyter)
    └── Pure GKE Agent Sandbox (v1.0.6 v1beta1 CRDs, SandboxWarmPool, Pod Snapshots >=1.35.3 non-E2 gVisor)
```

### Hard Trigger -> Architectural Target

| Hard Requirement / Trigger | Recommended Target | Why (Verified Platform Boundary) |
|---|---|---|
| **GPUs or TPUs inside sandbox** | **GKE Agent Sandbox (`gVisor`)** | Agent Runtime is CPU-only; Agent Substrate cannot passthrough `nvidia.com/gpu`; microVMs forbid accelerators; Pod Snapshots forbid TPUs. |
| **Full Linux syscalls (Docker-in-VM, raw kernel)** | **GKE Agent Sandbox (`microvm`)** or **Agent Substrate (`microvm`)** | Managed Sandbox & Autopilot are gVisor-only. MicroVMs require GKE Standard + `--enable-nested-virtualization` (or x86 bare metal on Substrate). |
| **Workspaces living > 7d (BYOC) / > 14d (Code Exec)** | **GKE Agent Sandbox (PVC/Pod Snapshot)** or **Agent Substrate (GCS/Filestore)** | Managed Sandboxes enforce hard 7d (BYOC/Shell) and 14d (Code Exec) TTL caps. |
| **> 1,000 concurrent sandboxes/region or > 100 VPC-SC instances** | **GKE Agent Substrate** (CPU) or **GKE Agent Sandbox** (GPU/Pod) | Managed Code Exec defaults to 1,000 entities/region; VPC-SC/PSC-I caps Agent Runtime `max_instances` at `100`. |
| **Zero-ops 3LO OAuth user consent + native Gemini app publish** | **Agent Runtime** (optionally Pattern B for heavy execution) | Cloud Run/GKE lack managed 3LO OAuth and only support A2A `publish gemini` (not native ADK `:streamQuery`). |
| **No-downtime instant rollback via CLI** | **GKE (`kubectl rollout undo`)**, **Cloud Run (`update-traffic`)**, or **Agent Runtime `v1beta1` `trafficSplitManual`** | `agents-cli` has no revision rollback command on `agent_runtime`; Agent Runtime Gateway changes irreversibly archive prior revisions. |
| **Strict in-country compute residency (e.g., Thailand PDPA / BoT)** | **Self-Hosted GKE + GKE Agent Sandbox (`asia-southeast3` Bangkok)** | GKE, AR, Cloud Build, Secret Manager & Agent Registry are live in Bangkok (`asia-southeast3`) today; Agent Runtime/Managed Sandboxes run in Singapore (`asia-southeast1`). |

### Hard Limits At-a-Glance Cheatsheet

| Surface | Key Verified Hard Limits & Floors |
|---|---|
| **Agent Platform Runtime** | `90 QPM` query, `10/min` concurrent Bidi, `300/min` session appends, `100` regional entities (adjustable); **`6,000` rev/project/region & `950` rev/agent** (non-adjustable); VPC-SC/PSC-I caps `max_instances=100`; `:streamQuery` `15m`, `:bidi` `10m`, `:asyncQuery` `7d`, `keep_alive_probe` `900..3600s`; **CPU-only**. |
| **Managed Scale Sandboxes** | TTL max **`7d`** (BYOC/Shell) / **`14d`** (Code Exec, resets on call); Code Exec `1,000` req/min, `1,000` entities/region, `100 MB` payload, zero network, no snapshots; PSC-I subnet `>= /28`; PSC-E max `1` same-project consumer; gVisor only. |
| **GKE Agent Sandbox (`v1.0.6`)** | `v1beta1` CRDs (`v1alpha1` removed in `v1.0.0`); Standard & Autopilot; `microvm` Standard only (`250 mCPU + 130 MiB/Pod`); Pod Snapshots: `whole-pod` **`>= 1.35.3-gke.1234000`** (**gVisor only**, **no E2**, **no TPUs**, **no GCS FUSE CSI**, NVIDIA `cuda-checkpoint` GPU support, no MIG; `~3–5s` restore) vs `rootfs-only` **`>= 1.35.3-gke.1031000`** (supports E2/cross-family restore); `FQDNNetworkPolicy` **`50`** IPs/policy & **`100`** IPs/hostname; Dataplane V2: cluster-create-only, `anetd` **2–3 vCPUs/node** under TCP churn, **0.25%** RAM eBPF map, **260k** Service map, **400k** Pods, **1,000-node** `CiliumNetworkPolicy` cap, & **`65,535`** `CiliumIdentity` cap *(uncached `troubleshooting/dataplane-v2-issues`)*; Hyperdisk **`128`** disks/node; Filestore **`80`** shares / `20k` conns/inst. |
| **GKE Agent Substrate** | **Standard ONLY `>= 1.37`** (no Autopilot, no Extended channel); x86 CPU only (min **`c3-standard-4`**), **no E2/mixed-CPU**, **no GPUs/TPUs**; `< 1s` GCS restore & `< 100 ms` Filestore agent volume re-attach; `>~800` sandboxes/node needs 5 sysctls (`net.ipv4.neigh.default.gc_thresh1/2/3`, `fs.inotify.max_user_instances/watches`); **no GKE Sandbox on worker pools**; Cloud Shell install blocked (`5 GB`). |

---

## Critical Gotchas ("Do This, Not That")

1. **Calculate `U * X * Y * 1.5` and request Agent Platform quota increases BEFORE launch — never assume defaults handle production load.**
   *Why:* Default `Query`/`StreamQuery` is **90 QPM** and `session_event_append_requests` is **300/min**. A 250-user multi-tool agent (`2 req/min`, `12 events/req`) needs **750 QPM** (8.3x default) and **9,000 appends/min** (30x default). Revision caps (**6,000/project/region**, **950/agent**) are **non-adjustable** system limits.
2. **Plan for GKE Dataplane V2 operational specs AND exclude `agents.x-k8s.io/sandbox-name-hash` in `cilium-config` before high-churn GKE Agent Sandbox scale.**
   *Why:* Dataplane V2 is cluster-create-only; `anetd` can use **2–3 vCPUs/node** under rapid TCP churn (use HTTP keep-alives/pooling), reserves **0.25%** RAM for eBPF maps, caps Service maps at **260,000** entries (400k Pods), and caps `CiliumNetworkPolicy` CRDs at **1,000 nodes** (use `CiliumClusterwideNetworkPolicy` up to 5,000). Separately, Cilium enforces a **65,535** cluster-wide `CiliumIdentity` cap *(provenance: uncached `troubleshooting/dataplane-v2-issues`)* — filter per-Pod `agents.x-k8s.io/sandbox-name-hash` (GKE `1.34.6-gke.1307000+` / `1.35.2-gke.1962000+` fixes override application).
3. **Never enable GKE Sandbox (`--sandbox=type=gvisor`) on GKE Agent Substrate worker node pools.**
   *Why:* Substrate manages its own gVisor/microVM runtimes inside `WorkerPool` Pods; the GKE Sandbox `sandbox.gke.io/runtime` taint prevents `WorkerPool` Pods from scheduling. Keep GKE Sandbox enabled *only* on separate Agent Sandbox pools.
4. **Match GKE Pod Snapshot scope (`whole-pod` vs `rootfs-only`) and GPU rules — and always wait for `PodSnapshot` `condition=Ready` before suspending.**
   *Why:* `whole-pod` snapshots require GKE **`>= 1.35.3-gke.1234000`**, **`gVisor` only**, **non-E2** (`n2`/`c3` or Autopilot `ComputeClass` `non-e2-class`), **no TPUs**, and **no GCS FUSE CSI sidecar** (NVIDIA `cuda-checkpoint` supports A100/H100/RTX PRO 6000 single-GPU and L4 `g2-standard-*` multi-GPU, no MIG). Use **`rootfs-only`** scope (`>= 1.35.3-gke.1031000`) when restoring across machine families including E2. Setting `spec.operatingMode: Suspended` deletes the Pod; suspending before `condition=Ready` cold-starts from scratch on resume.
5. **Do not assume `secure-sandbox-policy` VAP works out-of-the-box with microVMs, WIF, or Istio/Envoy sidecars.**
   *Why:* The recommended VAP enforces `runtimeClassName: gvisor`, `automountServiceAccountToken: false`, and empty `capabilities.add` (rejecting microVMs and `istio-init` `NET_ADMIN`/`NET_RAW`). Auto-generated `SandboxTemplate` `NetworkPolicy` also blocks `169.254.169.254` (breaking WIF until customized) and is **not** created for direct `Sandbox` CRDs.
6. **Never rely on Agent Platform `reasoning_engine_stdout` or Cloud Audit Logs for inside-sandbox observability.**
   *Why:* Automatic Cloud Logging collects parent `ReasoningEngine` logs only — not Managed Sandboxes, Sessions, or Memory Bank. Cloud Audit Logs never capture guest child processes, syscalls, file writes, or WS/CDP/PTY frames, and VPC-SC omits `DATA_WRITE` payloads.
7. **Always pass `http_options={"api_version": "v1beta1"}` for Agent Platform BYOC templates, PSC-I/PSC-E, CMEK, Agent Identity, and traffic splits — and never confuse the 3 service agents.**
   *Why:* `gcp-sa-vertex-sandbox` pulls BYOC sandbox images; `gcp-sa-aiplatform-re` pulls BYOC runtime images & uses CMEK; `gcp-sa-aiplatform` handles Shared VPC PSC-I & `AGENT_IDENTITY` deploy-time secrets.
8. **Never run `agents-cli infra single-project --apply` AFTER imperative `agents-cli deploy` on `agent_runtime`, and never pass `--cpu`/`--memory`/`--agent-identity` on `gke`.**
   *Why:* Terraform cannot adopt an existing imperatively deployed Agent Runtime; all sizing and `--agent-identity` flags are rejected on `gke` (owned by `deployment/terraform/` + HPA).
9. **Bind `default/default` KSA to `roles/aiplatform.user` and add `sessions.db` to `.dockerignore` when using `adk deploy gke`.**
   *Why:* `adk deploy gke` (Python-only; default `ClusterIP`) uses the `default` KSA (`403 PERMISSION_DENIED` without WIF binding), and copying a local SQLite `sessions.db` into a non-root container throws `OperationalError: attempt to write a readonly database`.
10. **Never install GKE Agent Substrate from Cloud Shell, set `--soft-delete-duration=0d` on Pod Snapshot GCS buckets, and isolate `google-adk==2.15.0` `GkeCodeExecutor` from `k8s-agent-sandbox==1.0.6`.**
    *Why:* Cloud Shell's 5 GB disk cap blocks Substrate installation; Pod Snapshot temp files trigger soft-delete storage bills unless disabled; and `google-adk==2.15.0` `GkeCodeExecutor._execute_in_sandbox()` calls the pre-1.0 `SandboxClient(...)` context-manager API, which breaks if `k8s-agent-sandbox==1.0.6` (`SandboxClient(connection_config=...).create_sandbox(...)`) is installed in the same Python environment (see `references/gke-agent-sandbox-reference.md`).

---

## Quick-Start Command & Code Patterns

### 1. Agent Platform Production Quota Sizing Check
```python
# Worked formula from docs.cloud.google.com/gemini-enterprise-agent-platform/resources/agent-quotas
peak_users, reqs_per_user_min, events_per_req, spike_buffer = 250, 2, 12, 1.5
peak_qpm = peak_users * reqs_per_user_min                  # 500 QPM
rec_query_qpm = int(peak_qpm * spike_buffer)               # 750  (default: 90  -> request increase!)
rec_append_qpm = int(peak_qpm * events_per_req * spike_buffer)  # 9000 (default: 300 -> request increase!)
rec_session_writes = rec_query_qpm                         # 750  (default: 100 -> request increase!)
# Async ADK Runtime scaling: 9 processes/container -> raise container_concurrency from 9 to 36 (watch RAM)
```

### 2. ADK `GkeCodeExecutor` vs. Standalone `k8s-agent-sandbox==1.0.6` Wiring
```python
# WARNING (Breaking SDK API Skew): Do NOT co-install k8s-agent-sandbox==1.0.6 in the same venv as
# google-adk==2.15.0 GkeCodeExecutor(executor_type="sandbox") — ADK 2.15.0 calls the pre-1.0
# context-manager SandboxClient API until ADK migrates to k8s-agent-sandbox v1.x!

# Option A — ADK GkeCodeExecutor (pip install "google-adk[extensions]>=2.0.0" + pre-1.0 k8s-agent-sandbox on ADK 2.15.0)
from google.adk.code_executors import GkeCodeExecutor
executor = GkeCodeExecutor(namespace="agent-workloads", executor_type="sandbox", sandbox_template="python-sandbox-template")
# Pass code_executor=executor to LlmAgent (full RBAC & Gateway config -> references/gke-agent-sandbox-reference.md)

# Option B — Standalone k8s-agent-sandbox v1.0.6 SDK (pip install k8s-agent-sandbox==1.0.6; prod uses Direct/Gateway configs)
from k8s_agent_sandbox import SandboxClient
from k8s_agent_sandbox.models import SandboxLocalTunnelConnectionConfig
sb = SandboxClient(connection_config=SandboxLocalTunnelConnectionConfig(), cleanup=True).create_sandbox(warmpool="python-sandbox-warmpool", namespace="agent-workloads")
print(sb.commands.run("echo ok").stdout)
```

### 3. Hybrid Pattern A (GKE/Cloud Run Agent -> Managed Scale Sandbox) & `agents-cli` Target Switch
```python
# Run from GKE (e.g., Bangkok asia-southeast3) / Cloud Run / local with roles/aiplatform.user (no code deployed to Agent Runtime needed)
import agentplatform
client = agentplatform.Client(project="PROJECT_ID", location="asia-southeast1", http_options={"api_version": "v1beta1"})
parent_name = client.runtimes.create().api_resource.name  # Minimal parent ReasoningEngine for Managed Sandboxes in Singapore
```
```bash
# Graduate an existing agents-cli project from agent_runtime -> gke (preview first with --dry-run)
agents-cli scaffold enhance . --deployment-target gke
agents-cli deploy --project PROJECT_ID --dry-run
```

---

## Modular References

Read only the specific reference file needed for your task (all links are 1-hop from this file):

| Reference File | Scope & Deep-Dive Contents |
|---|---|
| [Comparison Matrix & Limitations](references/comparison-matrix-and-limitations.md) | Full 14-dimension comparison across Agent Runtime + Managed Sandbox, GKE Agent Sandbox, GKE Agent Substrate, and `agents-cli`; exact Agent Platform production & Express Mode quotas + sizing math; gVisor vs. Cloud Hypervisor microVM vs. Kata table; PSC-I + NGFW/SWP vs. NetworkPolicy/`FQDNNetworkPolicy`/Dataplane V2 65,535 cardinality; SPIFFE vs. WIF; stdout/audit blind spots. |
| [GKE Agent Sandbox & Substrate Reference](references/gke-agent-sandbox-reference.md) | `kubernetes-sigs/agent-sandbox` `v1.0.6` install, `v1beta1` CRD YAML (`SandboxTemplate`, `SandboxWarmPool`, `SandboxClaim`, `Sandbox`), `secure-sandbox-policy` VAP, Sandbox Router, Managed Prometheus `PodMonitoring` & PromQL, `k8s-agent-sandbox` SDK, `GkeCodeExecutor` (`executor_type="sandbox"`), GKE Pod Snapshots (`>= 1.35.3-gke.1234000`, `non-e2-class`, GCS/IAM, suspend/resume), Hyperdisk vs. Filestore storage limits, and Agent Substrate (`Standard >= 1.37`, `ate.dev/v1alpha1`, `kubectl ate`). |
| [Hybrid & Migration Patterns](references/hybrid-and-migration-patterns.md) | Patterns A–D (GKE -> Managed Sandbox, Agent Runtime -> GKE via PSC-I + Gateway API, Dual-Tier GKE Sandbox + Substrate, Managed Sessions/Memory Bank/Anomaly Detection `GKE_WORKLOAD` on GKE); `adk deploy gke` vs. manual Python/Go GKE deployment; `agents-cli` `v1.15.0` multi-target graduation, target asymmetry table, rollback & OTel traps, and migration checklists. |
| [Maintenance & Provenance](references/maintenance.md) | Canonical upstream URLs (all seed URLs + Tier-1 & Tier-2 sub-links), `.md.txt`/`.md` refresh endpoints, uncached networking doc provenance notes, upstream watchlist, and section-by-section refresh checklist. |

---

## Maintenance

- **Last Verified:** `2026-11-23`
- **Refresh & Provenance Playbook:** See [Maintenance & Upstream Provenance](references/maintenance.md) for all canonical URLs, `.md.txt` refresh endpoints, and validation commands.
