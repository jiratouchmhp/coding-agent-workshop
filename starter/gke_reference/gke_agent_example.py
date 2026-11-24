"""Module 8 Architecture Guide — Read-Only GKE Agent Sandbox ADK Reference Example.

Ready-to-inspect complete reference implementation for the Module 8 Architecture
Guide (``workshop/08-ARCHITECTURE-AGENT-RUNTIME-VS-GKE.md``). No coding exercises
and no live GKE cluster are required during this workshop — run
``python gke_reference/gke_agent_example.py --mode inspect`` to inspect the
resolved configuration offline.

Demonstrates swapping Gemini Enterprise Agent Platform's managed
``AgentEngineSandboxCodeExecutor`` (Lab 2) for ADK's ``GkeCodeExecutor`` in
Sandbox Mode (``executor_type="sandbox"``), backed by Kubernetes SIG Apps
``agent-sandbox`` (``v1.0.6``, ``v1beta1`` CRDs) on GKE with gVisor isolation.

Verified against:
- https://adk.dev/integrations/gke-code-executor/ (ADK Python 2.0+)
- https://docs.cloud.google.com/kubernetes-engine/docs/how-to/agent-sandbox

Optional dependencies (not installed by default in ``starter/pyproject.toml``):
- ADK GKE executor: ``pip install "google-adk[extensions]"``
- Standalone warm-pool Python SDK: ``pip install k8s-agent-sandbox==1.0.6``

IMPORTANT SDK COMPATIBILITY NOTE:
``google-adk==2.15.0``'s ``GkeCodeExecutor._execute_in_sandbox()`` uses the pre-1.0
``k8s-agent-sandbox`` context-manager API, which conflicts with ``k8s-agent-sandbox==1.0.6``
if both are installed in the same virtual environment. Keep ADK ``GkeCodeExecutor`` and
the standalone ``k8s-agent-sandbox==1.0.6`` warm-pool SDK in separate virtual environments
until ADK migrates to ``k8s-agent-sandbox`` v1.x.

Production namespace note:
The workshop reference defaults to ``agent-sandbox-system`` for single-namespace
convenience, but ``secure-sandbox-policy`` ValidatingAdmissionPolicy excludes
controller namespaces by default. For production clusters, deploy templates/warm
pools/RBAC into a dedicated non-system workload namespace (e.g.,
``GKE_SANDBOX_NAMESPACE=coding-sandboxes``).
"""

from __future__ import annotations

import argparse
import inspect
import json
import os
from dataclasses import asdict, dataclass
from typing import Any

GKE_SYSTEM_INSTRUCTION = (
    "You are an Enterprise Coding Agent executing untrusted code inside a "
    "GKE Agent Sandbox (gVisor) container. Always verify fixes by running "
    "minimal Python assertions or unit tests and report exact stdout/stderr."
)


@dataclass(frozen=True)
class GkeSandboxSettings:
    """Configuration matching ``starter/gke_reference/*.yaml`` reference manifests."""

    namespace: str = "agent-sandbox-system"
    sandbox_template: str = "coding-sandbox-template"
    warmpool: str = "coding-sandbox-warmpool"
    sandbox_gateway_name: str | None = None
    model_name: str = "gemini-4-hydrogen"
    model_location: str = "global"
    google_cloud_project: str | None = None
    kubeconfig_path: str | None = None
    kubeconfig_context: str | None = None

    @classmethod
    def from_env(cls) -> GkeSandboxSettings:
        """Load settings from environment variables with workshop defaults."""
        gateway = os.environ.get("GKE_SANDBOX_GATEWAY_NAME", "").strip() or None
        project = os.environ.get("GOOGLE_CLOUD_PROJECT", "").strip() or None
        kubeconfig = os.environ.get("KUBECONFIG", "").strip() or None
        kube_ctx = os.environ.get("KUBECONFIG_CONTEXT", "").strip() or None
        return cls(
            namespace=os.environ.get("GKE_SANDBOX_NAMESPACE", "agent-sandbox-system").strip(),
            sandbox_template=os.environ.get(
                "GKE_SANDBOX_TEMPLATE", "coding-sandbox-template"
            ).strip(),
            warmpool=os.environ.get("GKE_SANDBOX_WARMPOOL", "coding-sandbox-warmpool").strip(),
            sandbox_gateway_name=gateway,
            model_name=os.environ.get("MODEL_NAME", "gemini-4-hydrogen").strip()
            or "gemini-4-hydrogen",
            model_location=os.environ.get("MODEL_LOCATION", "global").strip() or "global",
            google_cloud_project=project,
            kubeconfig_path=kubeconfig,
            kubeconfig_context=kube_ctx,
        )


def build_gke_code_executor(settings: GkeSandboxSettings) -> Any:
    """Instantiate ADK ``GkeCodeExecutor`` in Sandbox Mode.

    Prerequisites (only if later running against your own live GKE cluster):
    - ``pip install "google-adk[extensions]"`` (ADK Python 2.0+; do NOT co-install
      ``k8s-agent-sandbox==1.0.6`` in the same venv — ADK 2.15.0's
      ``GkeCodeExecutor._execute_in_sandbox()`` expects the pre-1.0 context-manager API).
    - ``rbac.yaml``, ``sandbox_template.yaml``, and ``sandbox_warmpool.yaml``
      applied in ``settings.namespace`` (use a dedicated non-system workload namespace
      such as ``coding-sandboxes`` in production for full VAP enforcement).
    """
    try:
        from google.adk.code_executors import GkeCodeExecutor
    except ImportError as exc:
        raise ImportError(
            "ADK GKE Code Executor requires `pip install \"google-adk[extensions]\"`."
        ) from exc

    kwargs: dict[str, Any] = {
        "namespace": settings.namespace,
        "executor_type": "sandbox",
        "sandbox_template": settings.sandbox_template,
    }
    if settings.sandbox_gateway_name:
        kwargs["sandbox_gateway_name"] = settings.sandbox_gateway_name
    if settings.kubeconfig_path:
        kwargs["kubeconfig_path"] = settings.kubeconfig_path
    if settings.kubeconfig_context:
        kwargs["kubeconfig_context"] = settings.kubeconfig_context

    return GkeCodeExecutor(**kwargs)


def build_gke_coding_agent(settings: GkeSandboxSettings) -> Any:
    """Construct an ADK ``LlmAgent`` wired with Frontier Gemini 4 and ``GkeCodeExecutor``."""
    try:
        from google import genai
        from google.adk.agents import LlmAgent
        from google.adk.models import Gemini
    except ImportError as exc:
        raise ImportError(
            "ADK LlmAgent requires `pip install \"google-adk[extensions]\"`."
        ) from exc

    # Route Frontier Gemini 4 models (e.g., gemini-4-hydrogen on global, or
    # gemini-4-argon on asia-southeast1 for strict regional residency) cleanly
    # across google-genai versions without overriding ADK's api_client property.
    try:
        params = inspect.signature(genai.Client.__init__).parameters
    except (TypeError, ValueError):
        params = {}
    auth_key = "enterprise" if "enterprise" in params else "vertexai"

    client_kwargs: dict[str, Any] = {
        auth_key: True,
        "location": settings.model_location,
    }
    project = (
        settings.google_cloud_project
        or os.environ.get("GOOGLE_CLOUD_PROJECT", "").strip()
        or None
    )
    if project:
        client_kwargs["project"] = project

    gemini_kwargs: dict[str, Any] = {"model": settings.model_name}
    model_fields = getattr(Gemini, "model_fields", None)
    if model_fields is None or "client_kwargs" in model_fields:
        gemini_kwargs["client_kwargs"] = client_kwargs
    gemini_model = Gemini(**gemini_kwargs)

    executor = build_gke_code_executor(settings)
    return LlmAgent(
        name="gke_sandbox_coding_agent",
        model=gemini_model,
        instruction=GKE_SYSTEM_INSTRUCTION,
        code_executor=executor,
    )


def run_direct_sandbox_execution(
    settings: GkeSandboxSettings,
    code: str = "print('Hello from GKE gVisor Sandbox Mode!')",
) -> dict[str, Any]:
    """Execute a code snippet directly via ``GkeCodeExecutor.execute_code()``.

    Follows the verified ``adk.dev/integrations/gke-code-executor`` contract
    constructing ``InvocationContext`` with ``InMemorySessionService`` and ``Session``.
    """
    try:
        from google.adk.agents.invocation_context import InvocationContext
        from google.adk.code_executors.code_execution_utils import CodeExecutionInput
        from google.adk.sessions import InMemorySessionService, Session
    except ImportError as exc:
        raise ImportError(
            "ADK GKE Code Executor requires `pip install \"google-adk[extensions]\"`."
        ) from exc

    executor = build_gke_code_executor(settings)
    ctx = InvocationContext(
        session_service=InMemorySessionService(),
        invocation_id="gke-sandbox-demo-invocation",
        session=Session(id="gke-sandbox-demo-session", app_name="demo", user_id="demo-user"),
    )
    result = executor.execute_code(ctx, CodeExecutionInput(code=code))
    return {
        "stdout": getattr(result, "stdout", ""),
        "stderr": getattr(result, "stderr", ""),
    }


def run_warmpool_sdk_smoke_test(
    settings: GkeSandboxSettings,
    command: str = "echo 'Hello from GKE Agent Sandbox WarmPool!'",
) -> str:
    """Claim a pre-warmed Pod directly using ``k8s-agent-sandbox==1.0.6``.

    Install ``k8s-agent-sandbox==1.0.6`` in a dedicated venv separate from
    ``google-adk==2.15.0`` (whose ``GkeCodeExecutor`` still uses the pre-1.0 API).
    Development mode uses ``SandboxLocalTunnelConnectionConfig()`` (which
    invokes ``kubectl port-forward`` to ``svc/sandbox-router-svc`` in
    ``agent-sandbox-system``). For production clusters, switch to:
    - ``SandboxDirectConnectionConfig`` (in-cluster -> Sandbox Router Service)
    - ``SandboxGatewayConnectionConfig`` (external -> GKE Gateway API LB)
    See: https://github.com/kubernetes-sigs/agent-sandbox/blob/v1.0.6/clients/python/agentic-sandbox-client/README.md
    """
    try:
        from k8s_agent_sandbox import SandboxClient
        from k8s_agent_sandbox.models import SandboxLocalTunnelConnectionConfig
    except ImportError as exc:
        raise ImportError(
            "Standalone GKE Sandbox client requires `pip install k8s-agent-sandbox==1.0.6`."
        ) from exc

    client = SandboxClient(
        connection_config=SandboxLocalTunnelConnectionConfig(),
        cleanup=True,
    )
    sandbox = client.create_sandbox(
        warmpool=settings.warmpool,
        namespace=settings.namespace,
    )
    result = sandbox.commands.run(command)
    return str(result.stdout)


def main(argv: list[str] | None = None) -> int:
    """CLI entry point for inspecting the Module 8 GKE reference overlay offline."""
    parser = argparse.ArgumentParser(
        description=(
            "GKE Agent Sandbox ADK integration example "
            "(Module 8 Architecture Guide — read-only reference)."
        )
    )
    parser.add_argument(
        "--mode",
        choices=("inspect", "adk-agent", "direct-exec", "warmpool-sdk"),
        default="inspect",
        help="Execution mode (default: inspect config offline without a live GKE cluster).",
    )
    parser.add_argument(
        "--code",
        default="print('Hello from GKE gVisor Sandbox Mode!')",
        help="Python snippet for --mode direct-exec.",
    )
    parser.add_argument(
        "--command",
        default="echo 'Hello from GKE Agent Sandbox WarmPool!'",
        help="Shell command for --mode warmpool-sdk.",
    )
    args = parser.parse_args(argv)
    settings = GkeSandboxSettings.from_env()

    if args.mode == "inspect":
        print(json.dumps(asdict(settings), indent=2))
        return 0
    if args.mode == "adk-agent":
        agent = build_gke_coding_agent(settings)
        print(f"Constructed ADK LlmAgent '{agent.name}' with GkeCodeExecutor (sandbox mode).")
        return 0
    if args.mode == "direct-exec":
        output = run_direct_sandbox_execution(settings, code=args.code)
        print(json.dumps(output, indent=2))
        return 0

    stdout = run_warmpool_sdk_smoke_test(settings, command=args.command)
    print(stdout)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
