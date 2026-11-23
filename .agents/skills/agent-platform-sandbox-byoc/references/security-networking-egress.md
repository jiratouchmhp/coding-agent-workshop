# Sandbox Security Boundaries, Networking, VPC-SC, CMEK & Observability

Production security architecture for Gemini Enterprise Agent Platform Scale Sandboxes: execution identity isolation, Private Service Connect egress/ingress (`PSC-I` / `PSC-E`), FQDN/URL filtering with Cloud NGFW and Secure Web Proxy, Cloud DNS peering, VPC Service Controls, single-region CMEK, and Cloud Audit Logging / telemetry coverage.

---

## 1. Execution Identity & Credential Isolation Boundaries

Code inside a Scale Sandbox runs inside a **gVisor-isolated container** in a Google-managed tenant project and **never** inherits the identity or credentials of the parent agent.

| Identity Layer | Principal | Scope & Permissions |
|---|---|---|
| **Parent Agent Runtime Identity** | Agent Identity (`principal://agents.global.org-ORG_ID.system.id.goog/...`) or default/custom SA on `ReasoningEngine` | Calls Google Cloud APIs and creates/invokes sandboxes from trusted orchestration code. **Never mounted inside the sandbox.** |
| **Agent Sandbox Service Agent** | `service-PROJECT_NUMBER@gcp-sa-vertex-sandbox.iam.gserviceaccount.com` | Control-plane infrastructure identity (pulls BYOC images from Artifact Registry). **Never accessible inside the sandbox.** |
| **In-Sandbox Execution Identity** | Unprivileged container user (e.g., `appuser`) backed by tenant identity `sandbox-untrusted` | Runs untrusted code/commands with **zero GCP IAM roles** on your project or parent `ReasoningEngine`. |

### Hard Credential Boundaries

- **No ADC & No Metadata Server:** Sandboxed processes have no Application Default Credentials and **cannot** reach `169.254.169.254:80` to mint OAuth 2.0 tokens, read service account keys, or inspect project metadata.
- **No `sudo` / No Root:** Unprivileged Linux user inside gVisor kernel containment.
- **Outbound Auth Best Practice:** Execute authenticated Google Cloud API operations in the trusted parent agent on Agent Runtime and pass only the required input data into the sandbox. If code inside the sandbox must call an external API directly, inject **short-lived, narrowly scoped tokens** per execution — never long-lived SA keys.
- **Zero-Ambient-Credential Boundary for `agy` Headless CLI:** Never proxy or relay a developer's personal `agy` OAuth credentials inside a shared runtime or sandbox. Prefer running `/usr/local/bin/agy` in the trusted Agent Runtime (`AGY_ADC_AUTH=true` on Custom SA `coding-agent-runtime-sa`) while keeping the gVisor BYOC Sandbox air-gapped (`internet_access: False`) for `pytest`/`ruff`/`bandit`. If running `agy` inside a BYOC sandbox (`AGY_EXECUTION_MODE=sandbox`), attach PSC-I + Cloud NGFW/SWP allowlisting Gemini/Vertex endpoints and pass only scoped ephemeral credentials/API keys per `/exec` call via `runner.py`'s strict `ALLOWED_EXEC_ENV_KEYS` allowlist (never written to disk or logged).

---

## 2. Network Egress Matrix & Private Service Connect Interface (PSC-I)

> **Critical Rule:** Scale Sandboxes and `SandboxEnvironmentTemplate` resources have **NO built-in domain allowlist field** (unlike Pre-GA Managed Agents API).

| Egress Mode | Configuration | Allowed Destinations | Blocked Automatically |
|---|---|---|---|
| **Code Execution** | Built-in (`code_execution_environment`) | **None** (air-gapped) | All public & private networks |
| **Template Default** | `egress_control_config.internet_access: False` | **None** (air-gapped; recommended for BYOC with baked-in tools) | All public & private networks |
| **Direct Public Internet** | `internet_access: True` **without** `network_attachment` | Unrestricted public IPs (`0.0.0.0/0`) — **cannot filter domains** | Private RFC 1918 (`10.0.0.0/8`, `172.16.0.0/12`, `192.168.0.0/16`) & link-local/metadata (`169.254.0.0/16`) |
| **VPC-Bridged (PSC-I)** | `internet_access: True` + `customer_vpc_network` + `network_attachment` | Governed by **your VPC** (Cloud NGFW FQDN rules, Secure Web Proxy L7 URL rules, Cloud NAT for internet, private routes for VPC/on-prem) | Public DNS forwarding disabled (anti-DNS-tunneling); must resolve via Cloud DNS peering |

### Step 1: Create PSC-I Subnet (Min `/28`) & Network Attachment

Requires `roles/compute.networkAdmin` in the project owning the network attachment.

> **Prohibited Subnet / Non-Routable Ranges** (per Agent Platform PSC-I docs): Subnet must be at least `/28` and must not use `100.64.0.0/20` or `240.0.0.0/4`. Agent Platform cannot route to privately used public IPs or non-RFC-1918 ranges `100.64.0.0/20`, `192.0.0.0/24`, `192.0.2.0/24`, `198.18.0.0/15`, `198.51.100.0/24`, `203.0.113.0/24`, `240.0.0.0/4`. PSC-I attachments cannot be changed in place — recreate resources to switch attachments.

```bash
# 1. Dedicated PSC-I subnet (minimum /28; enable VPC Flow Logs for egress telemetry)
gcloud compute networks subnets create sandbox-psc-subnet \
    --network=YOUR_VPC \
    --range=10.0.0.0/28 \
    --region=REGION \
    --enable-flow-logs

# 2. Network Attachment accepting the sandbox PSC interface
gcloud compute networks network-attachments create sandbox-egress-na \
    --region=REGION \
    --connection-preference=ACCEPT_AUTOMATIC \
    --subnets=sandbox-psc-subnet
```

### Step 2: Reference PSC-I on `SandboxEnvironmentTemplate` (`v1beta1`)

```python
import agentplatform

client = agentplatform.Client(
    project="PROJECT_ID",
    location="REGION",
    http_options={"api_version": "v1beta1"},
)

tpl_op = client.sandboxes.templates.create(
    name=instance_name,
    display_name="egress-governed-byoc-template",
    config={
        "custom_container_environment": {
            "custom_container_spec": {"image_uri": "IMAGE_URI"},
            "ports": [{"port": 8080, "protocol": "TCP"}],
        },
        "egress_control_config": {
            "internet_access": True,
            "customer_vpc_network": "projects/PROJECT_ID/global/networks/YOUR_VPC",  # Checked by VPC-SC at create time
            "network_attachment": "projects/PROJECT_ID/regions/REGION/networkAttachments/sandbox-egress-na",
        },
    },
)
```

### Step 3: Govern Egress in Your VPC (Internet vs. Private-Only)

#### Option A — Internet Egress: Cloud NAT + Cloud NGFW FQDN Allowlist (or Secure Web Proxy)

The sandbox enters your VPC on an RFC 1918 IP, so **Cloud NAT** is required to reach the public internet:

```bash
# Reserve static egress IP (optional; enables destination IP allowlisting)
gcloud compute addresses create sandbox-egress-ip --region=REGION

# Cloud Router + NAT scoped strictly to the PSC subnet
gcloud compute routers create sandbox-egress-router --network=YOUR_VPC --region=REGION
gcloud compute routers nats create sandbox-egress-nat \
    --router=sandbox-egress-router \
    --region=REGION \
    --nat-external-ip-pool=sandbox-egress-ip \
    --nat-custom-subnet-ip-ranges=sandbox-psc-subnet

# Cloud NGFW Global Network Firewall Policy: FQDN allowlist + default-deny + logging
gcloud compute network-firewall-policies create sandbox-egress-policy --global

gcloud compute network-firewall-policies rules create 1000 \
    --firewall-policy=sandbox-egress-policy --global-firewall-policy \
    --direction=EGRESS --action=allow --layer4-configs=tcp:443 \
    --dest-fqdns=api.partner.example.com \
    --enable-logging

gcloud compute network-firewall-policies rules create 65000 \
    --firewall-policy=sandbox-egress-policy --global-firewall-policy \
    --direction=EGRESS --action=deny --layer4-configs=all \
    --dest-ip-ranges=0.0.0.0/0 \
    --enable-logging

gcloud compute network-firewall-policies associations create \
    --firewall-policy=sandbox-egress-policy --global-firewall-policy \
    --network=YOUR_VPC
```

For **Layer 7 TLS inspection and per-URL allowlisting**, deploy **Secure Web Proxy** in your VPC, route `sandbox-psc-subnet` egress through it, and enable Secure Web Proxy access logging.

#### Option B — Private-Only Egress (VPC / On-Premises, No Internet)

Omit Cloud NAT. Configure VPC routes to your private targets, add an egress firewall rule from `sandbox-psc-subnet` (`10.0.0.0/28`), and configure **Cloud DNS peering** (`dns_peering_configs`) backed by a Cloud DNS private zone. Public DNS forwarding is disabled automatically when egress is bridged into your VPC to prevent DNS-tunnel exfiltration.

### Step 4: Shared VPC Cross-Project IAM (If Network Attachment Is in a Host Project)

Grant `roles/compute.networkUser` on the Shared VPC host project (`NETWORK_PROJECT_ID`) to the sandbox project's **Agent Platform service agent** (`gcp-sa-aiplatform`):

```bash
gcloud projects add-iam-policy-binding NETWORK_PROJECT_ID \
    --member="serviceAccount:service-PROJECT_NUMBER@gcp-sa-aiplatform.iam.gserviceaccount.com" \
    --role="roles/compute.networkUser"
```

*(Per PSC-I setup docs, if creating the network attachment in the service project [recommended] or host project, ensure the owning project's Agent Platform service agent also has `roles/compute.networkAdmin` or a custom role with `compute.networkAttachments.get`, `compute.networkAttachments.update`, and `compute.regionOperations.get`.)*

---

## 3. Private Ingress with Private Service Connect Endpoint (PSC-E)

Reach interactive sandbox data planes (WebSocket, CDP, `/exec`) privately inside your VPC instead of over the public internet.

- **Hard Constraint:** PSC-E supports **at most 1 consumer project**, which **must be the same project** that runs the sandbox.

```python
# Add to SandboxEnvironmentTemplate config:
config["ingress_control_config"] = {
    "private_service_connect_config": {
        "enable_private_service_connect": True,
    }
}

# After creating the sandbox, read its PSC-E service attachment:
service_attachment = sandbox.connection_info.service_attachment
```

```bash
# Reserve internal IP and create the PSC forwarding rule in the same project's VPC
gcloud compute addresses create sandbox-ingress-ip \
    --region=REGION --subnet=YOUR_SUBNET

gcloud compute forwarding-rules create sandbox-ingress-ep \
    --region=REGION \
    --network=YOUR_VPC \
    --address=sandbox-ingress-ip \
    --target-service-attachment="${SERVICE_ATTACHMENT_URI}"
```

---

## 4. VPC Service Controls (VPC-SC) Perimeter Checklist

PSC-I and PSC-E make sandboxes VPC-SC compliant (and can also be used without a perimeter). When running inside a VPC-SC perimeter:

1. **Order of Operations:** Add your project to the VPC-SC service perimeter **before** creating any sandboxes.
2. **Restricted Services:** Include all three services in the perimeter:
   - `aiplatform.googleapis.com` (Agent Platform + Sandbox control/data planes)
   - `storage.googleapis.com` (managed snapshot buckets)
   - `artifactregistry.googleapis.com` (BYOC custom container pulls)
3. **Private Google Access & Restricted VIP:** Route `*.googleapis.com` (plus `pkg.dev` / `gcr.io` for image pulls) to the restricted VIP **`199.36.153.4/30`**, enable Private Google Access on calling subnets, and create Cloud DNS private zones resolving to the restricted VIP.
4. **Access Levels:** Attach an Access Context Manager access level for trusted corporate/CI callers outside the perimeter.
5. **Audit Payload Caveat:** Inside a VPC-SC perimeter, **request and response payloads are omitted** from Cloud Audit Logs.

---

## 5. Customer-Managed Encryption Keys (CMEK)

### Encryption Scope & Hard Constraints

- **Configured ONLY at parent `ReasoningEngine` creation** (`encryption_spec.kms_key_name`); all child templates, sandboxes, and snapshots inherit the key.
- **Single-region KMS keys only** (same region as parent instance). Multi-region, dual-region, and global keys are **not supported**.
- **Immutable key:** You cannot change the key on an existing `ReasoningEngine` (create a new instance instead). Rotating to new versions of the same key is automatic.
- **What IS encrypted:** (1) GKE node boot disk / root filesystem (runtime files + paged memory state); (2) Snapshot Cloud Storage bucket.
- **What is NOT encrypted:** Resource metadata (names, labels, state, connection info), environment variables, service account emails, and Artifact Registry source images (configure CMEK directly on the AR repository).
- **Revocation impact:** Disabling/destroying the key version or revoking `roles/cloudkms.cryptoKeyEncrypterDecrypter` blocks sandbox provisioning/resuming and fails snapshot writes until restored.

### Exact `gcloud`, Python SDK & REST Setup

```bash
# 1. Provision AI Platform service identity (if not already present)
gcloud alpha services identity create \
    --service=aiplatform.googleapis.com \
    --project=PROJECT_ID

# 2. Create single-region Cloud KMS keyring & key matching ReasoningEngine region
gcloud kms keyrings create sandbox-keyring --location=REGION
gcloud kms keys create sandbox-key \
    --location=REGION --keyring=sandbox-keyring --purpose=encryption

# 3. Grant Encrypter/Decrypter to the AGENT RUNTIME service agent (gcp-sa-aiplatform-re)
gcloud kms keys add-iam-policy-binding sandbox-key \
    --location=REGION --keyring=sandbox-keyring \
    --member="serviceAccount:service-PROJECT_NUMBER@gcp-sa-aiplatform-re.iam.gserviceaccount.com" \
    --role="roles/cloudkms.cryptoKeyEncrypterDecrypter"
```

```python
# 4a. Python SDK: create CMEK-protected parent instance (v1beta1)
import agentplatform

client = agentplatform.Client(
    project="PROJECT_ID", location="REGION", http_options={"api_version": "v1beta1"}
)
parent = client.runtimes.create(
    config={
        "encryption_spec": {
            "kms_key_name": "projects/PROJECT_ID/locations/REGION/keyRings/sandbox-keyring/cryptoKeys/sandbox-key"
        }
    }
)
```

```bash
# 4b. REST API equivalent
curl -X POST \
  -H "Authorization: Bearer $(gcloud auth print-access-token)" \
  -H "Content-Type: application/json" \
  "https://REGION-aiplatform.googleapis.com/v1beta1/projects/PROJECT_ID/locations/REGION/reasoningEngines" \
  -d '{
    "display_name": "cmek-protected-engine",
    "encryption_spec": {
      "kms_key_name": "projects/PROJECT_ID/locations/REGION/keyRings/sandbox-keyring/cryptoKeys/sandbox-key"
    }
  }'
```

---

## 6. Cloud Audit Logs, `stdout`/`stderr` Gap & Threat Detection

Service name: `aiplatform.googleapis.com` | Monitored resource type: `audited_resource`.

| Activity Boundary | Operations / Methods | Log Category | Default & Gaps |
|---|---|---|---|
| **Lifecycle mutations** | `CreateSandboxEnvironment`, `DeleteSandboxEnvironment`, `SnapshotSandboxEnvironment`, `PauseSandboxEnvironment`, `ResumeSandboxEnvironment`, `CreateSandboxEnvironmentTemplate`, `UpdateSandboxEnvironmentTemplate`, `DeleteSandboxEnvironmentTemplate`, `DeleteSandboxEnvironmentSnapshot` | `ADMIN_WRITE` | **Always enabled.** Records caller, resource name, metadata. |
| **Metadata reads** | `GetSandboxEnvironment`, `ListSandboxEnvironments`, `GetSandboxEnvironmentTemplate`, `ListSandboxEnvironmentTemplates`, `GetSandboxEnvironmentSnapshot`, `ListSandboxEnvironmentSnapshots` | `ADMIN_READ` | **Disabled by default.** Enable on `aiplatform.googleapis.com`. |
| **Data-plane exec & auth** | `ExecuteSandboxEnvironment`, `BidiExecuteSandboxEnvironment`, `AuthorizeSandboxEnvironmentAccess`, `ExecuteCode` | `DATA_WRITE` | **Disabled by default.** Under **VPC-SC**, request/response payloads are omitted. |
| **In-container activity** | Child subprocesses, syscalls, file writes, individual WebSocket / CDP / PTY frames | **Not logged** | Only the initiating API RPC is audited — never in-guest syscalls or stream frames. |
| **Container `stdout` / `stderr`** | Command output streams | **API response only** | `reasoning_engine_stdout` / `reasoning_engine_stderr` apply **only** to the parent `ReasoningEngine`, **not** sandbox child resources. |

### Defense-in-Depth Monitoring Checklist

1. **Parent Agent Structured Logging:** Inspect every `execute_bash()` / `execute_code()` / `/exec` response (`returncode`, truncated `stdout`/`stderr`, `duration_ms`, `sandbox_name`) in the parent agent and write structured JSON logs to Cloud Logging.
2. **Enable Data Access Audit Logs:** Turn on `ADMIN_READ` and `DATA_WRITE` for `aiplatform.googleapis.com` to alert on unexpected `AuthorizeSandboxEnvironmentAccess` or `ExecuteSandboxEnvironment` calls.
3. **Parent Agent Anomaly Detection (Preview):** Enable OTel tracing (`ADK >= 2.1.0`) and Agent Anomaly Detection to catch tool misuse (OWASP ASI02), privilege abuse (ASI03), cascading failures (ASI08), and resource exhaustion.
4. **VPC Network Telemetry:** Combine PSC-I + VPC Flow Logs on `sandbox-psc-subnet` + Cloud NGFW `--enable-logging` + Secure Web Proxy access logs + Cloud DNS query logging.
5. **Pre-Deployment Scanning:** Run Artifact Registry vulnerability scanning on every BYOC image before creating a `SandboxEnvironmentTemplate`.

---

## 7. Verification Steps

### 1. In-Sandbox Identity & Metadata Isolation Probe

Execute inside a live Shell or BYOC sandbox and verify **both** checks print `PASS`:

```bash
id && whoami && pwd && \
(curl -sS --max-time 3 -H 'Metadata-Flavor: Google' \
  http://169.254.169.254/computeMetadata/v1/instance/service-accounts/default/token \
  && echo 'FAIL:METADATA_REACHABLE' || echo 'PASS:METADATA_UNREACHABLE') && \
(sudo -n true 2>&1 && echo 'FAIL:SUDO_AVAILABLE' || echo 'PASS:NO_SUDO')
```

### 2. CMEK & Egress Verification

- **CMEK:** Inspect parent `ReasoningEngine` metadata to confirm `encryption_spec.kms_key_name` is populated, then check Cloud KMS audit logs for `Encrypt`/`Decrypt` entries when starting a sandbox and writing a snapshot.
- **PSC-I / NGFW Egress:** From inside a PSC-I sandbox, `curl -I https://api.partner.example.com` succeeds (matching rule 1000) while `curl --max-time 5 https://example.com` is blocked (rule 65000) and appears as a denied egress entry in Cloud NGFW firewall logs.
