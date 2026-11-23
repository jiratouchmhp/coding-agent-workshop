# Non-root multi-tool BYOC Coding Sandbox image for Gemini Enterprise Agent Platform.
#
# Verified requirements (scale/sandbox/custom-containers):
#   1. Linux-based OS (Debian Bookworm slim).
#   2. Strictly non-root execution (USER appuser, no sudo, no ambient credentials).
#   3. Compatible /health & /exec HTTP runner listening on declared TCP port 8080.

FROM node:22-bookworm-slim AS node_lts

FROM python:3.11-slim-bookworm

LABEL org.opencontainers.image.title="gemini-coding-agent-sandbox" \
      org.opencontainers.image.description="Non-root Debian Bookworm BYOC coding sandbox with Python 3.11+, Node.js LTS, Antigravity (agy) headless CLI, git, jq, pytest, ruff, and bandit."

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    AGY_CLI_DISABLE_AUTO_UPDATE=true \
    SANDBOX_WORKSPACE=/workspace \
    SANDBOX_HOST=0.0.0.0 \
    SANDBOX_PORT=8080

# Copy Node.js LTS runtime & npm cleanly from official Bookworm image (avoids curl|bash).
COPY --from=node_lts /usr/local/bin/node /usr/local/bin/node
COPY --from=node_lts /usr/local/lib/node_modules /usr/local/lib/node_modules
RUN ln -sf /usr/local/lib/node_modules/npm/bin/npm-cli.js /usr/local/bin/npm \
    && ln -sf /usr/local/lib/node_modules/npm/bin/npx-cli.js /usr/local/bin/npx

# Install minimal CLI tooling (strictly NO sudo).
RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        bash \
        ca-certificates \
        curl \
        git \
        jq \
    && rm -rf /var/lib/apt/lists/*

# Opt-in native Go Antigravity (`agy`) headless CLI binary baked into /usr/local/bin
# (built remotely via Cloud Build `make push-sandbox` — zero local Docker required).
ARG INSTALL_AGY_CLI=true
RUN if [ "$INSTALL_AGY_CLI" = "true" ]; then \
      curl -fsSL https://antigravity.google/cli/install.sh -o /tmp/agy_install.sh \
      && bash /tmp/agy_install.sh --dir /usr/local/bin \
      && rm -f /tmp/agy_install.sh \
      && chmod 0755 /usr/local/bin/agy; \
    fi

# Install Python coding, testing, linting, and SAST tools.
COPY requirements.txt /tmp/requirements.txt
RUN pip install --upgrade pip \
    && pip install -r /tmp/requirements.txt \
    && rm -f /tmp/requirements.txt

# Create unprivileged non-root `appuser` (UID 1000) and confine writable space to `/workspace`.
RUN groupadd --gid 1000 appuser \
    && useradd --uid 1000 --gid 1000 --create-home --shell /bin/bash appuser \
    && mkdir -p /workspace /opt/sandbox_runner \
    && chown -R appuser:appuser /workspace /home/appuser

# Keep runner.py read-only (root:root 0644) so untrusted commands running as appuser cannot tamper with it.
# Use a separate RUN chmod instead of BuildKit-only COPY --chmod so Cloud Build's legacy builder succeeds.
COPY --chown=root:root runner.py /opt/sandbox_runner/runner.py
RUN chmod 0644 /opt/sandbox_runner/runner.py

USER appuser
WORKDIR /workspace

EXPOSE 8080

HEALTHCHECK --interval=30s --timeout=5s --start-period=5s --retries=3 \
    CMD python3 -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8080/health', timeout=2)" || exit 1

ENTRYPOINT ["python3", "/opt/sandbox_runner/runner.py"]
