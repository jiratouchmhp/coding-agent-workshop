# GKE Agent Sandbox, Pod Snapshots, Storage & Agent Substrate Reference

Production deployment, CRD specifications, security policies, Python SDKs, `GkeCodeExecutor`, GKE Pod Snapshots (`podsnapshot.gke.io/v1`), storage limits, and GKE Agent Substrate (`ate.dev/v1alpha1`) reference for self-hosted GKE agent execution planes.

---

## 1. GKE Agent Sandbox (`kubernetes-sigs/agent-sandbox` `v1.0.6`)

> **Breaking API Note:** `v1.0.0` **removed `v1alpha1`**. All Agent Sandbox CRDs use **`v1beta1`**: `agents.x-k8s.io/v1beta1` (`Sandbox`) and `extensions.agents.x-k8s.io/v1beta1` (`SandboxTemplate`, `SandboxClaim`, `SandboxWarmPool`).

### 1.1 Cluster Provisioning & Controller Install

```bash
export CLUSTER_NAME="agent-sandbox-cluster"
export AGENT_SANDBOX_VERSION="v1.0.6"

# Option A — GKE Autopilot (gVisor enabled automatically; regional GKE_LOCATION e.g. Bangkok asia-southeast3 for Thailand PDPA/BoT residency)
export GKE_LOCATION="${GKE_LOCATION:-asia-southeast3}"
gcloud container clusters create-auto "${CLUSTER_NAME}" --location="${GKE_LOCATION}"

# Option B — GKE Standard (zonal or regional; requires dedicated gVisor cos_containerd pool)
export ZONE="${ZONE:-asia-southeast3-a}"
export MACHINE_TYPE="n2-standard-2"  # Avoid e2-* if you plan to enable Pod Snapshots or microVMs
gcloud container clusters create "${CLUSTER_NAME}" --location="${ZONE}" --machine-type="${MACHINE_TYPE}" --num-nodes=1
gcloud container node-pools create agent-sandbox-pool \
  --cluster="${CLUSTER_NAME}" --location="${ZONE}" \
  --machine-type="${MACHINE_TYPE}" --num-nodes=1 \
  --image-type=cos_containerd --sandbox=type=gvisor

gcloud container clusters get-credentials "${CLUSTER_NAME}" --location="${GKE_LOCATION}" # Use "${ZONE}" for zonal Standard

# Install controller + all 4 v1beta1 CRDs into namespace agent-sandbox-system
kubectl apply -f "https://github.com/kubernetes-sigs/agent-sandbox/releases/download/${AGENT_SANDBOX_VERSION}/sandbox-with-extensions.yaml"
kubectl rollout status deployment/agent-sandbox-controller -n agent-sandbox-system --timeout=120s
```

- **Helm Alternative:** Supported via the `v1.0.6` Helm chart (`helm/README.md`). Note that Helm changes the controller Pod label to `app.kubernetes.io/name: agent-sandbox` (relevant for `PodMonitoring`).
- **Destructive Uninstall Caution:** Running `kubectl delete -f sandbox-with-extensions.yaml` deletes the CRDs, which **cascading-deletes every `Sandbox`, `SandboxTemplate`, `SandboxClaim`, and `SandboxWarmPool` across all namespaces**. Always check active resources first (`kubectl get sandboxes,sandboxclaims,sandboxwarmpools,sandboxtemplates --all-namespaces`).

### 1.2 Recommended `secure-sandbox-policy` ValidatingAdmissionPolicy (VAP)

By default, Agent Sandbox imposes no Pod hardening. Apply the official VAP (enforces in all non-system namespaces):

```bash
kubectl apply -f "https://raw.githubusercontent.com/kubernetes-sigs/agent-sandbox/${AGENT_SANDBOX_VERSION}/examples/policy/vap/secure-sandbox-policy.yaml"
kubectl apply -f "https://raw.githubusercontent.com/kubernetes-sigs/agent-sandbox/${AGENT_SANDBOX_VERSION}/examples/policy/vap/secure-sandbox-binding.yaml"
```

- **7 Required Settings (applied to all containers, including init & ephemeral containers):**
  1. `runtimeClassName: gvisor` *(rejects `microvm` and Kata unless VAP is edited)*
  2. `automountServiceAccountToken: false`
  3. `securityContext.runAsNonRoot: true` *(add `runAsUser: 1000` for images defaulting to root, e.g., `busybox`)*
  4. `containers[*].securityContext.capabilities.drop: ["ALL"]` (`allowPrivilegeEscalation: false` recommended)
  5. `containers[*].resources.limits` (CPU & memory limits **mandatory**)
  6. `nodeSelector: { "sandbox.gke.io/runtime": "gvisor" }`
  7. `tolerations: [{ key: "sandbox.gke.io/runtime", value: "gvisor", effect: "NoSchedule" }]`
- **8 Prohibited Settings:** `hostNetwork: true`, `hostPID: true`, `hostIPC: true`, `privileged: true`, `procMount: Unmasked`, `HostPath` volumes, `capabilities.add`, `hostPort`, custom `sysctls`, projected volumes for SA tokens/certificates.
- **Service Mesh Rejection Gotcha:** Istio/Envoy sidecar init containers (`istio-init`, `proxy-init`) requesting `NET_ADMIN`/`NET_RAW` fail with `ValidatingAdmissionPolicy 'secure-sandbox-policy' ... denied request: Security Violation: Capabilities.add must be empty`. Edit via `kubectl edit validatingadmissionpolicy secure-sandbox-policy` to exempt trusted init containers.

### 1.3 Sandbox Router & Managed Prometheus `PodMonitoring`

```bash
# Deploy Sandbox Router (required for Python SDK; dev defaults — configure TLS/HA/NetworkPolicy for prod)
kubectl apply \
  -f "https://raw.githubusercontent.com/kubernetes-sigs/agent-sandbox/${AGENT_SANDBOX_VERSION}/sandbox-router/deploy/serviceaccount.yaml" \
  -f "https://raw.githubusercontent.com/kubernetes-sigs/agent-sandbox/${AGENT_SANDBOX_VERSION}/sandbox-router/deploy/rbac.yaml"
curl -sSL "https://raw.githubusercontent.com/kubernetes-sigs/agent-sandbox/${AGENT_SANDBOX_VERSION}/sandbox-router/deploy/deployment.yaml" \
  | sed "s|sandbox-router-go:latest|sandbox-router-go:${AGENT_SANDBOX_VERSION}|" \
  | kubectl apply -f -
kubectl apply -f "https://raw.githubusercontent.com/kubernetes-sigs/agent-sandbox/${AGENT_SANDBOX_VERSION}/sandbox-router/deploy/service.yaml"
kubectl rollout status deployment/sandbox-router -n agent-sandbox-system --timeout=120s
```

```yaml
# agent-sandbox-monitoring.yaml (Managed Service for Prometheus — port 8080, /metrics)
apiVersion: monitoring.googleapis.com/v1
kind: PodMonitoring
metadata:
  name: agent-sandbox-controller
  namespace: agent-sandbox-system
spec:
  selector:
    matchLabels:
      app: agent-sandbox-controller  # Helm installs: use app.kubernetes.io/name: agent-sandbox
  endpoints:
  - port: metrics
    path: /metrics
    interval: 30s
```

- **Reserved Label Rename Gotcha:** Managed Prometheus reserves `namespace` for the scraped controller Pod (`agent-sandbox-system`) and renames the Sandbox's namespace label to **`exported_namespace`**.
- **Exported Metrics & PromQL:**
  - `agent_sandbox_build_info` (version/commit)
  - `agent_sandboxes` (labels: `ready_condition`, `exported_namespace`, expiration, launch type, owner, creator, template):
    ```promql
    sum by (exported_namespace, ready_condition) (agent_sandboxes)
    ```
  - `agent_sandbox_claim_controller_startup_latency_ms` (histogram — must query `_bucket`, `_sum`, or `_count`):
    ```promql
    histogram_quantile(0.95, sum by (le) (rate(agent_sandbox_claim_controller_startup_latency_ms_bucket[5m])))
    ```

### 1.4 Verified `v1beta1` CRD Manifests (`SandboxTemplate`, `SandboxWarmPool`, `SandboxClaim`, Direct `Sandbox`)

> **Namespace & VAP Isolation Best Practice:** Deploy untrusted workload CRDs (`SandboxTemplate`, `SandboxWarmPool`, `SandboxClaim`) in a **dedicated non-system workload namespace** (e.g., `agent-workloads`) rather than the controller's `agent-sandbox-system` namespace so `secure-sandbox-policy` VAP (which excludes system namespaces by default) enforces Pod hardening automatically and isolates untrusted sandboxes from controller/router components. (If deploying a lab overlay inside `agent-sandbox-system`, explicitly verify your VAP `ValidatingAdmissionPolicyBinding` matchExpressions include that namespace!)

```yaml
apiVersion: extensions.agents.x-k8s.io/v1beta1
kind: SandboxTemplate
metadata:
  name: python-sandbox-template
  namespace: agent-workloads
spec:
  podTemplate:
    metadata:
      labels:
        sandbox: python-sandbox-example
    spec:
      runtimeClassName: gvisor
      automountServiceAccountToken: false
      securityContext:
        runAsNonRoot: true
        runAsUser: 1000
      nodeSelector:
        sandbox.gke.io/runtime: gvisor
      tolerations:
      - key: "sandbox.gke.io/runtime"
        value: "gvisor"
        effect: "NoSchedule"
      containers:
      - name: python-runtime
        image: registry.k8s.io/agent-sandbox/python-runtime-sandbox:v0.1.0
        ports:
        - containerPort: 8888
        env:
        # Workaround for up to 2-min IPv6 TCP SYN timeout on dual-stack clusters without IPv6 NAT/IGW
        - name: NODE_OPTIONS
          value: "--dns-result-order=ipv4first --no-network-family-autoselection"
        readinessProbe:
          httpGet: { path: "/", port: 8888 }
          initialDelaySeconds: 0
          periodSeconds: 1
        resources:
          requests: { cpu: "250m", memory: "512Mi" }
          limits: { cpu: "500m", memory: "1Gi" }
        securityContext:
          capabilities: { drop: ["ALL"] }
          allowPrivilegeEscalation: false
      restartPolicy: "OnFailure"
---
apiVersion: extensions.agents.x-k8s.io/v1beta1
kind: SandboxWarmPool
metadata:
  name: python-sandbox-warmpool
  namespace: agent-workloads
spec:
  replicas: 2
  sandboxTemplateRef:
    name: python-sandbox-template
---
apiVersion: extensions.agents.x-k8s.io/v1beta1
kind: SandboxClaim
metadata:
  name: python-sandbox-claim
  namespace: agent-workloads
spec:
  warmPoolRef:
    name: python-sandbox-warmpool
```

- **Warm Pool Wait & Claim Ownership:** Always wait for `kubectl wait sandboxwarmpool python-sandbox-warmpool --for=jsonpath='{.status.readyReplicas}'=2 --timeout=600s` before creating claims (early claims fall back to cold Pod creation). Inspect `Sandbox` `metadata.ownerReferences[*].kind`: `SandboxWarmPool` = idle, `SandboxClaim` = claimed.
- **Direct `Sandbox` (`agents.x-k8s.io/v1beta1`):** Define `spec.podTemplate` directly when you do not need warm pools. Direct `Sandbox` resources do **not** receive an auto-generated `NetworkPolicy` — author your own.

---

## 2. Python SDK (`k8s-agent-sandbox==1.0.6`) & ADK `GkeCodeExecutor`

> **CRITICAL Breaking API Skew (`google-adk==2.15.0` vs. `k8s-agent-sandbox==1.0.6`):**
> `google-adk==2.15.0` `GkeCodeExecutor._execute_in_sandbox()` invokes the **pre-1.0 context-manager API** (`with SandboxClient(template_name=..., gateway_name=..., namespace=...) as sandbox: sandbox.write(...); sandbox.run(...)`), whereas **`k8s-agent-sandbox==1.0.6`** changed `SandboxClient` to `SandboxClient(connection_config=..., cleanup=True).create_sandbox(...)` with `sandbox.commands.run(...)`!
> - **Do NOT install `k8s-agent-sandbox==1.0.6` in the same Python environment as `google-adk==2.15.0` `GkeCodeExecutor(executor_type="sandbox")`** — doing so breaks `_execute_in_sandbox()` with `TypeError`/`AttributeError`.
> - Either use standalone `k8s-agent-sandbox==1.0.6` directly in an ADK `FunctionTool`/`BaseEnvironment` wrapper (recommended for `v1.0.6` controllers), OR pin the pre-1.0 `k8s-agent-sandbox` version compatible with `google-adk==2.15.0` in a separate environment until a future ADK release migrates `GkeCodeExecutor` to `k8s-agent-sandbox` v1.x.

### 2.1 Standalone `k8s-agent-sandbox==1.0.6` Connection Modes

```python
# pip install k8s-agent-sandbox==1.0.6  (pin to match v1.0.6 controller; keep isolated from ADK 2.15.0 GkeCodeExecutor!)
from k8s_agent_sandbox import SandboxClient
from k8s_agent_sandbox.models import SandboxLocalTunnelConnectionConfig
# Production modes:
# - In-cluster orchestrator: SandboxDirectConnectionConfig (targets svc/sandbox-router-svc URL & port)
# - External orchestrator (e.g., Agent Runtime over PSC-I): SandboxGatewayConnectionConfig (GKE Gateway API)

client = SandboxClient(
    connection_config=SandboxLocalTunnelConnectionConfig(),  # Dev-only kubectl port-forward!
    cleanup=True,  # Deletes SandboxClaim/Sandbox on exit
)
sandbox = client.create_sandbox(warmpool="python-sandbox-warmpool", namespace="agent-workloads")
result = sandbox.commands.run("python3 -c 'print(2 + 2)'")
print(result.stdout)
```

### 2.2 ADK `GkeCodeExecutor` (`google-adk[extensions]>=2.0.0`, ADK Python 2.0+)

| Parameter | Type | Default | Notes |
|---|---|---|---|
| `namespace` | `str` | `"default"` | Dedicated workload namespace where `SandboxClaim` and `Sandbox` resources are created (match `SandboxTemplate` namespace, e.g., `"agent-workloads"`). |
| `executor_type` | `str` | *(set `"sandbox"`)* | Always set **`"sandbox"`** to execute via GKE Agent Sandbox CRDs (`Sandbox`, `SandboxTemplate`, `SandboxClaim`, `SandboxWarmPool`). |
| `sandbox_template` | `str \| None` | `"python-sandbox-template"` | `SandboxTemplate` name in `namespace`. |
| `sandbox_gateway_name` | `str \| None` | `None` | Optional GKE Gateway API name for out-of-cluster routing. |
| `kubeconfig_path` / `kubeconfig_context` | `str` | `None` | Optional explicit kubeconfig; falls back to in-cluster config or default local kubeconfig. |

- **Required Kubernetes RBAC (`executor_type="sandbox"`):** `create`, `get`, `watch`, `delete` on `SandboxClaim` (`extensions.agents.x-k8s.io`) and `Sandbox` (`agents.x-k8s.io`) in `namespace`.

```python
from google.adk.agents import LlmAgent
from google.adk.code_executors import GkeCodeExecutor

# GKE Agent Sandbox Mode (match dedicated non-system workload namespace & SandboxTemplate name;
# on ADK 2.15.0, requires pre-1.0 k8s-agent-sandbox client until GkeCodeExecutor migrates to v1.x)
sandbox_executor = GkeCodeExecutor(
    namespace="agent-workloads",
    executor_type="sandbox",
    sandbox_template="python-sandbox-template",
    sandbox_gateway_name="your-gateway-name",  # Optional
)

import inspect
from google import genai
from google.adk.models import Gemini

auth_key = "enterprise" if "enterprise" in inspect.signature(genai.Client.__init__).parameters else "vertexai"
agent = LlmAgent(
    name="gke_sandbox_coding_agent",
    model=Gemini(model="gemini-4-hydrogen", client_kwargs={auth_key: True, "project": "PROJECT_ID", "location": "global"}),
    instruction="Write and execute Python code safely in the GKE sandbox.",
    code_executor=sandbox_executor,
)
```

---

## 3. GKE Pod Snapshots for Agent Sandbox (`podsnapshot.gke.io/v1`)

### 3.1 Hard Requirements, Scopes (`whole-pod` vs. `rootfs-only`) & GPU Checkpointing (`cuda-checkpoint`)
- **GKE Version:** **`>= 1.35.3-gke.1234000`** (`--release-channel=rapid --enable-pod-snapshots`, Standard & Autopilot) for **`whole-pod`** snapshots; **`>= 1.35.3-gke.1031000`** for **`rootfs-only`** (file system) snapshots.
- **Runtime & Sidecars:** **`gVisor` ONLY** (`runtimeClassName: gvisor`). **Does NOT work with microVMs**, **TPUs**, or **Cloud Storage FUSE CSI sidecars**.
- **Scopes & Machine Families:**
  - **Default `whole-pod` scope:** Captures process memory + rootfs; target node must match machine series, CPU vendor, and `CPUID` flags (**NO E2 machine types** — on Standard use `n2`/`c3`, and on Autopilot bind a custom `ComputeClass` `non-e2-class` below).
  - **`rootfs-only` (file system) scope (`>= 1.35.3-gke.1031000`):** Skips process memory and distilled Pod spec hash matching, enabling restore **across different machine families (including E2)** while keeping compatible container images and node versions.
- **GPU Checkpointing (NVIDIA `cuda-checkpoint`):** Writes GPU state into Pod process memory during snapshot and reverses it on restore (size Pod memory limits accordingly and measure readiness via TTFT/readiness probes since GPU state streams asynchronously). Supported GPU machine types: **`a2-highgpu-1g`** (A100-40GB), **`a2-ultragpu-1g`** (A100-80GB), **`a3-highgpu-1g`** (H100-80GB), **`g4-standard-48`** (RTX PRO 6000) single-GPU, and single- or multi-GPU L4 **`g2-standard-*`** (`4, 8, 12, 16, 32, 48, 96`; multi-GPU Pods supported **only** on L4 `g2-standard-*`). **Multi-Instance GPU (MIG) is NOT supported.**
- **Restore Latency:** **~3 to 5 seconds** (with background memory streaming from GCS).

### 3.2 Cluster, GCS Bucket (`--soft-delete-duration=0d`), WIF & IAM Setup

```bash
export PROJECT_ID=$(gcloud config get project)
export PROJECT_NUMBER=$(gcloud projects describe "${PROJECT_ID}" --format="value(projectNumber)")
export CLUSTER_NAME="agent-sandbox-cluster"
export GKE_LOCATION="${GKE_LOCATION:-asia-southeast3}"  # Bangkok default (Thailand PDPA / BoT compute residency)
export ZONE="${ZONE:-asia-southeast3-a}"
export SNAPSHOTS_BUCKET_NAME="agent-sandbox-snapshots-${PROJECT_ID}"
export SNAPSHOT_NAMESPACE="pod-snapshots-ns"
export SNAPSHOT_KSA_NAME="pod-snapshot-sa"
export SNAPSHOT_FOLDER="my-snapshots"

# Standard cluster example (Autopilot: gcloud container clusters create-auto ... --release-channel=rapid --enable-pod-snapshots --location="${GKE_LOCATION}")
gcloud container clusters create "${CLUSTER_NAME}" \
  --release-channel=rapid --enable-pod-snapshots \
  --machine-type="n2-standard-2" \
  --workload-pool="${PROJECT_ID}.svc.id.goog" --workload-metadata=GKE_METADATA \
  --num-nodes=1 --location="${ZONE}"
gcloud container node-pools create agent-sandbox-node-pool \
  --cluster="${CLUSTER_NAME}" --location="${ZONE}" --project="${PROJECT_ID}" \
  --num-nodes=1 --machine-type="n2-standard-2" --sandbox type=gvisor

# Hierarchical namespace improves throughput; soft-delete=0d avoids billing for transient upload files!
gcloud storage buckets create "gs://${SNAPSHOTS_BUCKET_NAME}" \
  --uniform-bucket-level-access --enable-hierarchical-namespace \
  --soft-delete-duration=0d --location="${GKE_LOCATION}"
gcloud storage managed-folders create "gs://${SNAPSHOTS_BUCKET_NAME}/${SNAPSHOT_FOLDER}/"

# Custom role (NOTE: deleting this role triggers a 37-day cooldown before the role ID can be reused!)
gcloud iam roles create podSnapshotGcsReadWriter --project="${PROJECT_ID}" \
  --permissions="storage.objects.get,storage.objects.create,storage.objects.delete,storage.folders.create"

kubectl create namespace "${SNAPSHOT_NAMESPACE}"
kubectl create serviceaccount "${SNAPSHOT_KSA_NAME}" --namespace "${SNAPSHOT_NAMESPACE}"

# 1) Namespace WIF -> bucketViewer, 2) KSA WIF -> custom role + objectUser, 3) GKE snapshot controller SA -> objectUser
gcloud storage buckets add-iam-policy-binding "gs://${SNAPSHOTS_BUCKET_NAME}" \
  --member="principalSet://iam.googleapis.com/projects/${PROJECT_NUMBER}/locations/global/workloadIdentityPools/${PROJECT_ID}.svc.id.goog/namespace/${SNAPSHOT_NAMESPACE}" \
  --role="roles/storage.bucketViewer"
gcloud storage buckets add-iam-policy-binding "gs://${SNAPSHOTS_BUCKET_NAME}" \
  --member="principal://iam.googleapis.com/projects/${PROJECT_NUMBER}/locations/global/workloadIdentityPools/${PROJECT_ID}.svc.id.goog/subject/ns/${SNAPSHOT_NAMESPACE}/sa/${SNAPSHOT_KSA_NAME}" \
  --role="projects/${PROJECT_ID}/roles/podSnapshotGcsReadWriter"
gcloud storage buckets add-iam-policy-binding "gs://${SNAPSHOTS_BUCKET_NAME}" \
  --member="principal://iam.googleapis.com/projects/${PROJECT_NUMBER}/locations/global/workloadIdentityPools/${PROJECT_ID}.svc.id.goog/subject/ns/${SNAPSHOT_NAMESPACE}/sa/${SNAPSHOT_KSA_NAME}" \
  --role="roles/storage.objectUser"
gcloud storage buckets add-iam-policy-binding "gs://${SNAPSHOTS_BUCKET_NAME}" \
  --member="serviceAccount:service-${PROJECT_NUMBER}@container-engine-robot.iam.gserviceaccount.com" \
  --role="roles/storage.objectUser"
```

### 3.3 Autopilot `ComputeClass` (`non-e2-class`), Snapshot CRDs & Safe Suspend/Resume Sequence

```yaml
# Autopilot ONLY: prevent scheduling onto unsupported E2 nodes; reference via nodeSelector: { cloud.google.com/compute-class: non-e2-class }
apiVersion: cloud.google.com/v1
kind: ComputeClass
metadata:
  name: non-e2-class
spec:
  priorities:
  - machineFamily: n2
  - machineFamily: c3
  activeMigration:
    optimizeRulePriority: false
  whenUnsatisfiable: DoNotScaleUp
---
# Cluster-scoped (no namespace!)
apiVersion: podsnapshot.gke.io/v1
kind: PodSnapshotStorageConfig
metadata:
  name: cpu-pssc-gcs
spec:
  snapshotStorageConfig:
    gcs:
      bucket: "SNAPSHOTS_BUCKET_NAME"
      path: "my-snapshots"
---
apiVersion: podsnapshot.gke.io/v1
kind: PodSnapshotPolicy
metadata:
  name: cpu-psp
  namespace: pod-snapshots-ns
spec:
  storageConfigName: cpu-pssc-gcs
  selector:
    matchLabels:
      app: agent-sandbox-workload
  triggerConfig:
    type: manual
    postCheckpoint: resume
  snapshotGroupingRules:
    groupByLabelValue:
      labels:
      - agents.x-k8s.io/sandbox-name-hash
```

```bash
# 1. Trigger manual snapshot against running Sandbox Pod (Pod name == Sandbox name)
kubectl apply -f - <<EOF
apiVersion: podsnapshot.gke.io/v1
kind: PodSnapshotManualTrigger
metadata:
  name: cpu-snapshot-trigger
  namespace: ${SNAPSHOT_NAMESPACE}
spec:
  targetPod: ${SANDBOX_NAME}
EOF

# 2. CRITICAL: Wait for PodSnapshot condition=Ready BEFORE suspending (or resume cold-starts!)
export SNAPSHOT_NAME=$(kubectl get podsnapshotmanualtriggers.podsnapshot.gke.io cpu-snapshot-trigger \
  -n "${SNAPSHOT_NAMESPACE}" -o jsonpath='{.status.snapshotCreated.name}')
kubectl wait podsnapshots.podsnapshot.gke.io "${SNAPSHOT_NAME}" \
  -n "${SNAPSHOT_NAMESPACE}" --for=condition=Ready --timeout=600s

# 3. Suspend (deletes Pod, retains Sandbox CRD + PVCs)
kubectl patch sandbox "${SANDBOX_NAME}" -n "${SNAPSHOT_NAMESPACE}" \
  --type=merge -p '{"spec":{"operatingMode":"Suspended"}}'
kubectl wait pod "${SANDBOX_NAME}" -n "${SNAPSHOT_NAMESPACE}" --for=delete --timeout=120s

# 4. Resume (auto-restores latest Ready PodSnapshot in ~3-5s)
kubectl patch sandbox "${SANDBOX_NAME}" -n "${SNAPSHOT_NAMESPACE}" \
  --type=merge -p '{"spec":{"operatingMode":"Running"}}'
kubectl wait sandbox "${SANDBOX_NAME}" -n "${SNAPSHOT_NAMESPACE}" --for=condition=Ready --timeout=300s
```

---

## 4. GKE Storage Matrix & GKE Agent Substrate (`ate.dev/v1alpha1`)

### 4.1 GKE Agent Storage Options & Exact Limits

| Feature | **Hyperdisk Balanced** (RWO) / **Hyperdisk ML** (ROX) | **Filestore Multishares Enterprise** (RWX) | **Agent Substrate GCS Checkpoints + Filestore Agent Volumes** |
|---|---|---|---|
| **Access Modes** | RWO (Balanced); ROX (ML, up to **2,500 instances**/vol) | RWX (`ReadWriteMany`) | Per-actor exclusive CSI volume (deleted with actor; Hyperdisk NOT used for per-actor CSI) |
| **Provision & Attach** | Several sec provision; several sec attach | **~6 min** instance create; **sub-sec** NFS mount | GCS restore **< 1s**; Filestore agent volume re-attach **< 100 ms** |
| **Size Limits** | **4 GiB–64 TiB**/disk (**128 TiB** C4); **247 TiB** (<32 vCPU) or **512 TiB** (>=32 vCPU)/node | **1–10 TiB**/instance; **10 GiB–1 TiB**/share (PVC) | GCS snapshot + `<bucket>-assets` buckets; `ActorTemplate` `externalVolumeTemplate.capacity` |
| **Scale & Perf** | Up to **128 disks/node**; **2,400 MiB/s**; **3k–160k IOPS** | No node attach limit; max **80 shares** & **20,000 conns**/inst (`2,000/TiB`, steps of `500`); **120 MiB/s** (max **1,200 MiB/s**); **12k R / 4k W IOPS per TiB** | **>~800 concurrent sandboxes/node** requires Linux `inotify` & ARP sysctl tuning |
| **Scaling & Snapshots** | Scales **up only**; CSI `VolumeSnapshot` **supported** | Scales **up or down**; per-share CSI `VolumeSnapshot` **NOT supported** *(Preview: Filestore Multishares for Agent Storage lowers cost)* | 3-layer automatic GCS snapshots; Filestore agent volumes (Allowlisted GA / Preview CSI) do **not** automate Filestore snapshots, cloning, or tiering |

### 4.2 GKE Agent Substrate Requirements, 3-Layer Checkpoints & `kubectl ate`

- **Hard Requirements:**
  - **GKE Standard ONLY `>= 1.37`** (control plane & node pools); **Autopilot unsupported** (privileged `atelet` DaemonSet); **Extended release channel unsupported** by installer (enables beta APIs).
  - **x86 CPU only** (minimum **`c3-standard-4`** nodes; no Arm), **no E2 / mixed-CPU** (gVisor issue), uniform VM family per `ActorTemplate` (`workerSelector` -> `WorkerPool` `nodeSelector`). **NO GPUs or TPUs.**
  - **High-Density Kernel Sysctls (`>~800` concurrent sandboxes/node):** Configure all 5 Linux kernel sysctls on worker nodes: `net.ipv4.neigh.default.gc_thresh1=4096`, `net.ipv4.neigh.default.gc_thresh2=16384`, `net.ipv4.neigh.default.gc_thresh3=32768`, `fs.inotify.max_user_instances=65536`, and `fs.inotify.max_user_watches=1048576`.
  - **NEVER enable GKE Sandbox** on Substrate worker pools (`sandbox.gke.io/runtime` taint blocks `WorkerPool` Pods).
  - **Cloud Shell install blocked** (5 GB persistent disk cap) — install from workstation/VM via `github.com/ai-on-gke/substrate-gke`.
  - **Open network connections** (DB/MCP) drop on suspend — agent code must reconnect on resume.
- **WIF & IAM:**
  - `ate-snapshot-transfer` GSA & `ate-api-server` KSA: `roles/storage.objectAdmin` + `roles/storage.bucketViewer` on snapshot bucket.
  - `ate-api-server` KSA: `roles/iam.serviceAccountTokenCreator` on `ate-snapshot-transfer` (GKE nodes need zero bucket access).
  - `atelet` KSA (microVMs): `roles/storage.objectViewer` on `<snapshot-bucket>-assets`.
- **3-Layer GCS Checkpoint Graceful Downgrade (gVisor & microVMs):**
  1. **Memory + rootfs + volumes (`< 1s`)**: hardware, runtime, and image unchanged.
  2. **Rootfs + volumes**: node hardware or sandbox runtime changed (restarts processes, keeps rootfs & durable dirs).
  3. **Volumes only**: `ActorTemplate` container image updated while suspended (write durable data to mounted volumes/durable dirs).
- **Verified Filestore CSI + `WorkerPool` + `ActorTemplate` YAML & `kubectl ate` Lifecycle:**

```yaml
apiVersion: storage.k8s.io/v1
kind: StorageClass
metadata:
  name: substrate-volumepool-sc
provisioner: filestore.csi.storage.gke.io
parameters:
  volume-pool: "projects/PROJECT_ID/locations/LOCATION/volumePools/VOLUME_POOL_NAME"
allowVolumeExpansion: false
reclaimPolicy: Delete
volumeBindingMode: Immediate
---
apiVersion: ate.dev/v1alpha1
kind: CSIDriverConfig
metadata:
  name: filestore.csi.storage.gke.io
spec:
  driverName: filestore.csi.storage.gke.io
  controllerEndpoint: tcp://csi-filestore-controller.gcp-filestore-csi-driver.svc:10000
  nodeSocketOverride: unix:///var/lib/kubelet/plugins/filestore.csi.storage.gke.io/csi.sock
  tls:
    enabled: true
    usePodIdentity: true
    serverName: csi-filestore-controller.gcp-filestore-csi-driver.svc
---
apiVersion: ate.dev/v1alpha1
kind: WorkerPool
metadata:
  name: agent-pool
  namespace: ate-demo
  labels:
    workload: stateful-agent
spec:
  replicas: 5
  workerImage: ko://github.com/agent-substrate/substrate/cmd/ateom-gvisor
```

```yaml
# actor-template.yaml (non-K8s resource submitted via `kubectl ate create actor-template`)
metadata:
  atespace: ate-demo
  name: stateful-agent-template
workerSelector:
  matchLabels:
    workload: stateful-agent
containers:
- name: agent
  image: CONTAINER_IMAGE  # e.g., asia-southeast3-docker.pkg.dev/PROJECT_ID/REPO/agent-app@sha256:...
  volumeMounts:
  - name: shared-storage
    mountPath: /mnt/shared
  readyz:
    httpGet:
      path: /readyz
      port: 8080
sandboxConfig:
  sandboxClass: SANDBOX_CLASS_GVISOR
  configName: gvisor-default
snapshotsConfig:
  storageLocation: gs://SNAPSHOT_BUCKET/stateful-agent
volumes:
- name: shared-storage
  externalVolumeTemplate:
    capacity: 5Gi
    storageClassName: substrate-volumepool-sc
```

```bash
kubectl ate create atespace ate-demo && kubectl create namespace ate-demo
kubectl apply -f storageclass.yaml -f csi-driver-config.yaml -f worker-pool.yaml
kubectl ate create actor-template -f actor-template.yaml
kubectl ate create actor my-agent-1 --template=stateful-agent-template -a ate-demo
kubectl ate suspend actor my-agent-1 -a ate-demo
kubectl ate resume actor my-agent-1 -a ate-demo
```

---

## 5. Common Error Modes, Fixes & Verification Steps

| Symptom / Error | Root Cause | Fix |
|---|---|---|
| `Security Violation: Capabilities.add must be empty` or `runtimeClassName` rejected | `secure-sandbox-policy` VAP rejects Istio/Envoy `istio-init` (`NET_ADMIN`/`NET_RAW`) or `microvm`. | `kubectl edit validatingadmissionpolicy secure-sandbox-policy` to exempt trusted init containers or permit `microvm`. |
| Sandbox Pod resumes at state `0` instead of checkpointed memory | Patched `operatingMode: Suspended` before `PodSnapshot` reached `condition=Ready`, or ran on E2 / microVM. | Verify non-E2 + `gvisor` + GKE `>= 1.35.3-gke.1234000`, and always wait on `kubectl wait podsnapshots.podsnapshot.gke.io ... --for=condition=Ready`. |
| WIF / Google Cloud API calls time out inside GKE Agent Sandbox | Default `SandboxTemplate` `NetworkPolicy` blocks `169.254.169.254`, and VAP sets `automountServiceAccountToken: false`. | Customize `SandboxTemplate` `NetworkPolicy` to permit metadata server / WIF endpoint and grant KSA WIF bindings. |
| ~2-minute delay connecting to external APIs or Vertex AI from sandbox | Dual-stack IPv6 GKE cluster without IPv6 NAT/IGW causes Node.js AAAA SYN timeout. | Configure IPv6 egress or set `NODE_OPTIONS="--dns-result-order=ipv4first --no-network-family-autoselection"`. |
| `FAILED_PRECONDITION` creating `podSnapshotGcsReadWriter` | Deleted custom IAM role ID is in 37-day deletion cooldown. | Create with a new ID (e.g., `podSnapshotGcsReadWriter2`). |
| `WorkerPool` Pods stuck `Pending` on GKE Agent Substrate | GKE Sandbox (`--sandbox=type=gvisor`) enabled on Substrate worker node pool (`sandbox.gke.io/runtime` taint). | Recreate Substrate worker node pool **without** GKE Sandbox (keep GKE Sandbox on separate Agent Sandbox pools). |
| `TypeError` / `AttributeError` in `GkeCodeExecutor._execute_in_sandbox()` | `google-adk==2.15.0` calls pre-1.0 `SandboxClient` context-manager API, which is incompatible with `k8s-agent-sandbox==1.0.6`. | Keep `k8s-agent-sandbox==1.0.6` isolated from ADK 2.15.0 `GkeCodeExecutor` (wrap `k8s-agent-sandbox==1.0.6` directly in a `FunctionTool`/`BaseEnvironment`, or pin pre-1.0 client until ADK migrates to v1.x). |

```bash
# Verify Agent Sandbox CRDs, controller, router, and active claims
kubectl get crd sandboxes.agents.x-k8s.io sandboxtemplates.extensions.agents.x-k8s.io \
  sandboxclaims.extensions.agents.x-k8s.io sandboxwarmpools.extensions.agents.x-k8s.io
kubectl get deploy agent-sandbox-controller sandbox-router -n agent-sandbox-system
kubectl get sandboxwarmpool,sandboxclaim,sandbox,pod -A
```
