# Non-root Trusted Agent Runtime BYOC Container Image (Starter Track — Lab 5).
#
# Distinct from Lab 2's untrusted sandbox image (`starter/sandbox_image/Dockerfile`):
# - Trusted Agent Runtime container runs the FastAPI + ADK HTTP adapter (`main:app`)
#   pulled by `service-<PROJECT_NUMBER>@gcp-sa-aiplatform-re.iam.gserviceaccount.com`.
# - Untrusted LLM-generated commands execute inside Lab 2's separate gVisor Managed
#   Sandbox (`coding-sandbox:v1`), pulled by `gcp-sa-vertex-sandbox`.
#
# Verified Agent Runtime container contract (scale/runtime/runtime-contract):
#   1. Linux container listening on 0.0.0.0:8080 (`EXPOSE 8080`).
#   2. Non-root execution (`USER appuser`, strictly no `sudo`).
#   3. Answers `GET /` (200 OK), `POST /api/reasoning_engine`, and
#      `POST /api/stream_reasoning_engine` (NDJSON).
#
# Works identically with both:
#   - Option 1 (`container_spec`): `make push-agent` / `gcloud builds submit starter --tag=...`
#   - Option 2 (`source_code_spec` + `image_spec {}`):
#       cd starter && tar -czvf terraform/coding_agent_source.tar.gz \
#         Dockerfile main.py requirements.txt coding_agent/ skills_to_register/

FROM python:3.11-slim-bookworm

LABEL org.opencontainers.image.title="gemini-coding-agent-runtime-starter" \
      org.opencontainers.image.description="Non-root Python 3.11 Agent Runtime BYOC container serving the ADK Coding Agent HTTP contract on 0.0.0.0:8080."

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    AGY_CLI_DISABLE_AUTO_UPDATE=true \
    PORT=8080

# Install CA certificates and curl for HTTPS/TLS, optional Agent Gateway root CA trust,
# and opt-in Antigravity (`agy`) headless CLI installation (strictly NO sudo).
RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        ca-certificates \
        curl \
    && rm -rf /var/lib/apt/lists/*

# Opt-in native Go Antigravity (`agy`) headless CLI binary baked into /usr/local/bin.
# Inside Agent Runtime, `agy` uses the dedicated Custom SA ADC (`AGY_ADC_AUTH=true`)
# with `GOOGLE_CLOUD_LOCATION=global` and auto-updates disabled.
ARG INSTALL_AGY_CLI=true
RUN if [ "$INSTALL_AGY_CLI" = "true" ]; then \
      curl -fsSL https://antigravity.google/cli/install.sh -o /tmp/agy_install.sh \
      && bash /tmp/agy_install.sh --dir /usr/local/bin \
      && rm -f /tmp/agy_install.sh \
      && chmod 0755 /usr/local/bin/agy; \
    fi

# Optional Lab 7 Agent Gateway BYOC CA Trust pattern (scale/runtime/agent-gateway-runtime-deploy):
# Pass `agents-cli deploy --build-args AGENT_GATEWAY_ROOT_CERTIFICATES="$(gcloud network-services agent-gateways describe ...)"` (plural)
# or `docker build --build-arg AGENT_GATEWAY_ROOT_CERTIFICATES="$(gcloud network-services agent-gateways describe ...)"` (singular)
# and uncomment below to trust Agent Gateway interception certificates in Python/gRPC/OpenSSL:
# ARG AGENT_GATEWAY_ROOT_CERTIFICATES=""
# RUN if [ -n "$AGENT_GATEWAY_ROOT_CERTIFICATES" ]; then \
#       printf "%s\n" "$AGENT_GATEWAY_ROOT_CERTIFICATES" > /usr/local/share/ca-certificates/agw-root.crt && \
#       update-ca-certificates; \
#     fi
# ENV SSL_CERT_FILE=/etc/ssl/certs/ca-certificates.crt \
#     REQUESTS_CA_BUNDLE=/etc/ssl/certs/ca-certificates.crt \
#     GRPC_DEFAULT_SSL_ROOTS_FILE_PATH=/etc/ssl/certs/ca-certificates.crt \
#     AGENT_GATEWAY_ROOT_CERT_302034098528=/etc/ssl/certs/ca-certificates.crt

WORKDIR /app

COPY requirements.txt ./
RUN pip install --no-cache-dir --upgrade pip \
    && pip install --no-cache-dir -r requirements.txt

# Create unprivileged non-root `appuser` (UID 1000).
RUN groupadd --gid 1000 appuser \
    && useradd --uid 1000 --gid 1000 --create-home --shell /bin/bash appuser

COPY --chown=appuser:appuser main.py ./
COPY --chown=appuser:appuser coding_agent/ ./coding_agent/
COPY --chown=appuser:appuser skills_to_register/ ./skills_to_register/

USER appuser

EXPOSE 8080

CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8080"]
