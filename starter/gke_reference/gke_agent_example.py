"""Self-Hosted GKE Agent Sandbox ADK Integration Example (Starter Track).

Demonstrates swapping Gemini Enterprise Agent Platform's managed
``AgentEngineSandboxCodeExecutor`` (Lab 2) for ADK's ``GkeCodeExecutor`` in
Sandbox Mode (``executor_type="sandbox"``), backed by Kubernetes SIG Apps
``agent-sandbox`` (``v1.0.6``, ``v1beta1`` CRDs) on GKE with gVisor isolation.

Verified against:
- https://adk.dev/integrations/gke-code-executor/ (ADK Python >= v1.14.0)
- https://docs.cloud.google.com/kubernetes-engine/docs/how-to/agent-sandbox

Optional dependencies (not installed by default in ``starter/pyproject.toml``):
- ADK GKE executor: ``pip install "google-adk[extensions]"``
- Standalone warm-pool Python SDK: ``pip install k8s-agent-sandbox==1.0.6``
"""

from __future__ import annotations

import argparse
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
    """Configuration matching ``starter/gke_reference/*.yaml`` manifests."""

    namespace: str = "agent-sandbox-system"
    sandbox_template: str = "coding-sandbox-template"
    warmpool: str = "coding-sandbox-warmpool"
    sandbox_gateway_name: str | None = None
    model_name: str = "gemini-2.5-flash"
    kubeconfig_path: str | None = None
    kubeconfig_context: str | None = None

    @classmethod
    def from_env(cls) -> GkeSandboxSettings:
        """Load settings from environment variables with workshop defaults."""
        gateway = os.environ.get("GKE_SANDBOX_GATEWAY_NAME", "").strip() or None
        kubeconfig = os.environ.get("KUBECONFIG", "").strip() or None
        kube_ctx = os.environ.get("KUBECONFIG_CONTEXT", "").strip() or None
        return cls(
            namespace=os.environ.get("GKE_SANDBOX_NAMESPACE", "agent-sandbox-system").strip(),
            sandbox_template=os.environ.get(
                "GKE_SANDBOX_TEMPLATE", "coding-sandbox-template"
            ).strip(),
            warmpool=os.environ.get("GKE_SANDBOX_WARMPOOL", "coding-sandbox-warmpool").strip(),
            sandbox_gateway_name=gateway,
            model_name=os.environ.get("MODEL_NAME", "gemini-2.5-flash").strip(),
            kubeconfig_path=kubeconfig,
            kubeconfig_context=kube_ctx,
        )


def build_gke_code_executor(settings: GkeSandboxSettings) -> Any:
    """Instantiate ADK ``GkeCodeExecutor`` in Sandbox Mode.

    Prerequisites:
    - ``pip install "google-adk[extensions]"`` (ADK Python >= v1.14.0).
    - ``rbac.yaml``, ``sandbox_template.yaml``, and ``sandbox_warmpool.yaml``
      applied in ``settings.namespace``.
    """
    # TODO(lab-7): Import ``GkeCodeExecutor`` from ``google.adk.code_executors``
    # and instantiate it with:
    #   - ``namespace=settings.namespace``
    #   - ``executor_type="sandbox"``
    #   - ``sandbox_template=settings.sandbox_template``
    #   - Optional ``sandbox_gateway_name=settings.sandbox_gateway_name`` (when set)
    #   - Optional ``kubeconfig_path`` / ``kubeconfig_context`` (when set)
    # Compare with ``solution/gke_reference/gke_agent_example.py`` for the complete wiring.
    raise NotImplementedError(
        "Complete TODO(lab-7) in starter/gke_reference/gke_agent_example.py: "
        "build_gke_code_executor()."
    )


def build_gke_coding_agent(settings: GkeSandboxSettings) -> Any:
    """Construct an ADK ``LlmAgent`` wired with ``GkeCodeExecutor``."""
    # TODO(lab-7): Import ``LlmAgent`` from ``google.adk.agents``, build the
    # executor via ``build_gke_code_executor(settings)``, and return:
    #   LlmAgent(
    #       name="gke_sandbox_coding_agent",
    #       model=settings.model_name,
    #       instruction=GKE_SYSTEM_INSTRUCTION,
    #       code_executor=executor,
    #   )
    raise NotImplementedError(
        "Complete TODO(lab-7) in starter/gke_reference/gke_agent_example.py: "
        "build_gke_coding_agent()."
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

    # TODO(lab-7): Instantiate ``SandboxClient`` with
    # ``connection_config=SandboxLocalTunnelConnectionConfig()`` and ``cleanup=True``,
    # call ``client.create_sandbox(warmpool=settings.warmpool, namespace=settings.namespace)``,
    # execute ``sandbox.commands.run(command)``, and return ``result.stdout``.
    _ = (SandboxClient, SandboxLocalTunnelConnectionConfig, settings, command)
    raise NotImplementedError(
        "Complete TODO(lab-7) in starter/gke_reference/gke_agent_example.py: "
        "run_warmpool_sdk_smoke_test()."
    )


def main(argv: list[str] | None = None) -> int:
    """CLI entry point for inspecting or exercising the GKE reference overlay."""
    parser = argparse.ArgumentParser(
        description="GKE Agent Sandbox ADK integration example (Lab 7 comparison track)."
    )
    parser.add_argument(
        "--mode",
        choices=("inspect", "adk-agent", "direct-exec", "warmpool-sdk"),
        default="inspect",
        help="Execution mode (default: inspect config without connecting to a GKE cluster).",
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
