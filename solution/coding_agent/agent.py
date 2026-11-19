"""Root ADK Coding Agent definition (complete reference solution).

Supports all four execution modes via ``SANDBOX_MODE``:
- ``local`` (Lab 1): Confined ``LocalEnvironment(working_dir=Path(...))`` inside ``EnvironmentToolset``.
- ``shell`` (Lab 2): Per-session Managed Shell Sandbox via ``AgentPlatformSandboxEnvironment``.
- ``byoc`` (Lab 2): Per-session BYOC Custom Container Sandbox via ``AgentPlatformSandboxEnvironment``.
- ``code_execution`` (Lab 2): ADK ``AgentEngineSandboxCodeExecutor``.

And four ADK 2.0 architectures via ``AGENT_ARCHITECTURE`` (default: ``simple``):
- ``simple`` (default; 100% compatible with Labs 2-7): Single ``LlmAgent``.
- ``collaborative``: ADK 2.0 Coordinator + ``single_turn``/``task`` subagents + ``GlobalInstructionPlugin``.
- ``graph``: ADK 2.0 declarative ``Workflow`` graph with parallel checks, ``JoinNode``, and HITL.
- ``dynamic``: ADK 2.0 programmatic ``@node(rerun_on_resume=True)`` workflow orchestrator.

Also wires:
- Lab 4: OTel + parent-runtime Cloud Logging callbacks and optional Memory Bank hooks.
- Lab 5: ``SkillToolset(registry=GCPSkillRegistry(...))`` with offline sandbox fallback.
"""

from __future__ import annotations

import logging
import time
from pathlib import Path
from typing import Any

from google.adk.agents import LlmAgent
from google.adk.apps import App, ResumabilityConfig
from google.adk.environment import BaseEnvironment, LocalEnvironment
from google.adk.models import Gemini
from google.adk.tools.environment import EnvironmentToolset
from google.genai import types
from opentelemetry import trace

from coding_agent.config import Settings, get_settings
from coding_agent.tools.sandbox_execution import (
    AgentPlatformSandboxEnvironment,
    build_code_execution_executor,
)

logger = logging.getLogger(__name__)

SYSTEM_INSTRUCTION = """You are an Enterprise Coding Agent built on Google ADK.
Follow these engineering rules strictly:
1. Inspect existing files with ReadFile before modifying code.
2. Prefer surgical EditFile updates over full-file rewrites when editing existing files.
3. Verify every code change by running unit tests (e.g., `pytest -q`) and linters (`ruff check`) with Execute.
4. Never fabricate test output or claim tests passed without running them.
5. Keep all file operations strictly inside your configured workspace directory.
"""


def build_local_environment_toolset(
    workspace_dir: Path,
    max_output_chars: int = 12_000,
) -> EnvironmentToolset:
    """Create a confined ADK ``LocalEnvironment`` wrapped in ``EnvironmentToolset``.

    CRITICAL: ``LocalEnvironment(working_dir=...)`` MUST receive a ``pathlib.Path``
    (passing ``str`` raises ``AttributeError`` on ``.resolve()``), and ``max_output_chars``
    belongs on ``EnvironmentToolset``, not ``LocalEnvironment``.
    """
    resolved_dir = Path(workspace_dir).resolve()
    resolved_dir.mkdir(parents=True, exist_ok=True)
    local_env = LocalEnvironment(working_dir=resolved_dir)
    return EnvironmentToolset(
        environment=local_env,
        max_output_chars=max_output_chars,
    )


def _build_remote_execution_components(
    settings: Settings,
) -> tuple[BaseEnvironment | None, list[Any], Any | None]:
    """Build remote Managed Sandbox toolset or Code Execution executor."""
    if settings.sandbox_mode in {"shell", "byoc"}:
        remote_env = AgentPlatformSandboxEnvironment(
            project_id=settings.require_gcp_project(),
            location=settings.google_cloud_location,
            instance_name=settings.reasoning_engine_name,
            template_name=(settings.sandbox_template_name or None) if settings.sandbox_mode == "byoc" else None,
            sandbox_name=settings.sandbox_resource_name or None,
            mode=settings.sandbox_mode,  # type: ignore[arg-type]
            working_dir=Path("/workspace"),
            ttl=settings.sandbox_ttl,
            service_account_email=settings.sandbox_service_account_email or None,
            runner_base_url=settings.sandbox_runner_base_url or None,
        )
        toolset = EnvironmentToolset(
            environment=remote_env,
            max_output_chars=settings.max_output_chars,
        )
        return remote_env, [toolset], None

    if settings.sandbox_mode == "code_execution":
        code_executor = build_code_execution_executor(
            sandbox_resource_name=settings.sandbox_resource_name or None,
            agent_engine_resource_name=settings.reasoning_engine_name or None,
        )
        return None, [], code_executor

    return None, [], None


def _build_optional_skill_toolset(
    settings: Settings,
    environment: BaseEnvironment | None,
) -> Any | None:
    """Build ``SkillToolset(registry=GCPSkillRegistry(...))`` when enabled (Lab 5).

    NOTE: ``SkillToolset`` accepts ``environment=`` OR ``code_executor=``, NEVER both.
    """
    if not settings.enable_skill_registry:
        return None

    local_skill_dir = (
        Path(__file__).resolve().parents[1] / "skills_to_register" / "secure-code-review"
    )
    local_dirs = [local_skill_dir] if local_skill_dir.exists() else []

    try:
        from coding_agent.tools.registry_loader import build_skill_registry_toolset

        return build_skill_registry_toolset(
            project_id=settings.google_cloud_project or None,
            location=settings.agent_registry_location or None,
            local_skill_dirs=local_dirs,
            environment=environment,
            enable_remote_registry=bool(settings.google_cloud_project),
        )
    except ImportError:
        pass

    # Standalone fallback wiring using ADK's built-in GCPSkillRegistry + SkillToolset.
    try:
        from google.adk.skills import load_skill_from_dir
        from google.adk.tools.skill_toolset import (
            SkillDiscoveryMode,
            SkillLifecycleConfig,
            SkillLifecycleMode,
            SkillToolset,
        )
    except ImportError as exc:
        logger.warning("ADK SkillToolset unavailable (%s); skipping skill registry.", exc)
        return None

    local_skills = [load_skill_from_dir(d) for d in local_dirs]
    registry = None
    if settings.google_cloud_project and settings.agent_registry_location:
        try:
            from google.adk.integrations.skill_registry import GCPSkillRegistry

            registry = GCPSkillRegistry(
                project_id=settings.google_cloud_project,
                location=settings.agent_registry_location,
            )
        except Exception as exc:
            logger.warning(
                "GCPSkillRegistry unavailable (%s); falling back to local skills only.",
                exc,
            )

    if not local_skills and registry is None:
        return None

    return SkillToolset(
        skills=local_skills,
        registry=registry,
        environment=environment,
        discovery_mode=SkillDiscoveryMode.LAZY,
        lifecycle_config=SkillLifecycleConfig(
            default_mode=SkillLifecycleMode.BOUNDED,
            max_active_skills=5,
        ),
    )


def _fallback_before_tool_callback(
    tool: Any,
    args: dict[str, Any],
    tool_context: Any,
) -> None:
    """Lightweight OTel start-time marker used when Lab 4 callback module is absent."""
    del args
    state = getattr(tool_context, "state", None)
    if state is not None:
        state[f"_tool_start_ts:{getattr(tool, 'name', 'tool')}"] = time.monotonic()
    return None


def _fallback_after_tool_callback(
    tool: Any,
    args: dict[str, Any],
    tool_context: Any,
    tool_response: Any,
) -> None:
    """Attach OTel attributes and log tool completion on the parent runtime."""
    del args
    tool_name = str(getattr(tool, "name", "tool"))
    state = getattr(tool_context, "state", None)
    start_ts = state.pop(f"_tool_start_ts:{tool_name}", None) if state is not None else None
    duration_ms = int((time.monotonic() - start_ts) * 1000) if start_ts is not None else -1

    span = trace.get_current_span()
    if span is not None and span.is_recording():
        span.set_attribute("coding_agent.tool.name", tool_name)
        if duration_ms >= 0:
            span.set_attribute("coding_agent.tool.duration_ms", duration_ms)
        if isinstance(tool_response, dict) and "exit_code" in tool_response:
            span.set_attribute("coding_agent.sandbox.exit_code", int(tool_response["exit_code"]))
    logger.info("Tool completed: name=%s duration_ms=%s", tool_name, duration_ms)
    return None


def _build_optional_callbacks(settings: Settings) -> dict[str, Any]:
    """Wire Lab 4 telemetry callbacks and optional Memory Bank tools/callbacks."""
    callbacks: dict[str, Any] = {
        "before_tool_callback": None,
        "after_tool_callback": None,
        "after_agent_callback": None,
        "extra_tools": [],
    }

    if settings.enable_telemetry_callbacks:
        try:
            from coding_agent.callbacks.telemetry_and_feedback import (
                after_tool_callback,
                before_tool_callback,
            )

            callbacks["before_tool_callback"] = before_tool_callback
            callbacks["after_tool_callback"] = after_tool_callback
        except ImportError:
            callbacks["before_tool_callback"] = _fallback_before_tool_callback
            callbacks["after_tool_callback"] = _fallback_after_tool_callback

    if settings.enable_memory_bank:
        try:
            from google.adk.tools.preload_memory_tool import PreloadMemoryTool

            from coding_agent.memory.memory_bank_manager import persist_turn_to_memory_callback

            callbacks["extra_tools"].append(PreloadMemoryTool())
            callbacks["after_agent_callback"] = persist_turn_to_memory_callback
        except ImportError as exc:
            logger.warning("Memory Bank tool/callback unavailable (%s); skipping memory wiring.", exc)

    return callbacks


def _assemble_runtime_components(
    cfg: Settings,
) -> tuple[list[Any], dict[str, Any], Any | None]:
    """Assemble workspace tools, optional Lab 5 skills, Lab 4 callbacks, and code executor."""
    tools: list[Any] = []
    active_environment: BaseEnvironment | None = None
    code_executor: Any | None = None

    if cfg.sandbox_mode == "local":
        local_toolset = build_local_environment_toolset(
            workspace_dir=cfg.local_workspace_path,
            max_output_chars=cfg.max_output_chars,
        )
        active_environment = getattr(local_toolset, "_environment", None)
        tools.append(local_toolset)
    else:
        active_environment, remote_tools, code_executor = _build_remote_execution_components(cfg)
        tools.extend(remote_tools)

    skill_toolset = _build_optional_skill_toolset(cfg, environment=active_environment)
    if skill_toolset is not None:
        tools.append(skill_toolset)

    callback_bundle = _build_optional_callbacks(cfg)
    tools.extend(callback_bundle["extra_tools"])
    return tools, callback_bundle, code_executor


def build_coding_agent(settings: Settings | None = None) -> LlmAgent:
    """Build the single-agent ADK ``LlmAgent`` for ``AGENT_ARCHITECTURE=simple``."""
    cfg = settings or get_settings()
    tools, callback_bundle, code_executor = _assemble_runtime_components(cfg)

    # Always use an explicit versioned Gemini model ID (do NOT use `gemini-flash-latest`
    # on regional Vertex AI / Agent Platform endpoints). Keep `output_schema` unset on this
    # tool-heavy LlmAgent as a cross-model reliability best practice: ADK Python supports
    # `output_schema` + `tools` on Gemini on Google Cloud, whereas other models fall back to
    # an injected `set_model_response` tool that can be unreliable (isolate structured outputs
    # in dedicated specialist/formatter agents such as `code_reviewer`).
    agent_kwargs: dict[str, Any] = {
        "name": "coding_agent",
        "model": Gemini(
            model=cfg.model_name,
            retry_options=types.HttpRetryOptions(initial_delay=1, attempts=2),
        ),
        "description": (
            "Enterprise Coding Agent that reads, edits, writes, and verifies code "
            "inside a confined local or remote Managed Sandbox environment."
        ),
        "instruction": SYSTEM_INSTRUCTION,
        "tools": tools,
        "generate_content_config": types.GenerateContentConfig(temperature=0.2),
    }
    if code_executor is not None:
        agent_kwargs["code_executor"] = code_executor
    if callback_bundle["before_tool_callback"] is not None:
        agent_kwargs["before_tool_callback"] = callback_bundle["before_tool_callback"]
    if callback_bundle["after_tool_callback"] is not None:
        agent_kwargs["after_tool_callback"] = callback_bundle["after_tool_callback"]
    if callback_bundle["after_agent_callback"] is not None:
        agent_kwargs["after_agent_callback"] = callback_bundle["after_agent_callback"]

    return LlmAgent(**agent_kwargs)


def build_root_agent(settings: Settings | None = None) -> Any:
    """Dispatch root agent construction based on ``AGENT_ARCHITECTURE``.

    - ``simple`` (default): Single ``LlmAgent`` via ``build_coding_agent()`` (Labs 1-7).
    - ``collaborative``: ADK 2.0 Coordinator + ``single_turn``/``task`` subagents.
    - ``graph``: ADK 2.0 declarative ``Workflow`` graph with ``JoinNode`` + bounded fix loop.
    - ``dynamic``: ADK 2.0 programmatic ``@node(rerun_on_resume=True)`` orchestrator.
    """
    cfg = settings or get_settings()
    if cfg.agent_architecture == "simple":
        return build_coding_agent(cfg)

    tools, callback_bundle, code_executor = _assemble_runtime_components(cfg)

    from coding_agent.architectures import (
        build_collaborative_coding_team,
        build_dynamic_coding_workflow,
        build_graph_coding_workflow,
    )

    if cfg.agent_architecture == "collaborative":
        return build_collaborative_coding_team(
            settings=cfg,
            tools=tools,
            callbacks=callback_bundle,
            code_executor=code_executor,
        )
    if cfg.agent_architecture == "graph":
        return build_graph_coding_workflow(
            settings=cfg,
            tools=tools,
            callbacks=callback_bundle,
            code_executor=code_executor,
        )
    if cfg.agent_architecture == "dynamic":
        return build_dynamic_coding_workflow(
            settings=cfg,
            tools=tools,
            callbacks=callback_bundle,
            code_executor=code_executor,
        )
    raise ValueError(f"Unsupported AGENT_ARCHITECTURE={cfg.agent_architecture!r}.")


def _build_app_options(settings: Settings | None = None) -> dict[str, Any]:
    """Build ``App`` resumability and optional ``GlobalInstructionPlugin`` kwargs.

    Attaches ``GlobalInstructionPlugin`` across multi-agent and workflow modes
    (``collaborative``, ``graph``, ``dynamic``) per ADK 2.0 guidance
    (``adk.dev/graphs/``, ``adk.dev/workflows/collaboration/``), while keeping
    ``simple`` mode unchanged for Labs 2-7 backward compatibility.
    """
    cfg = settings or get_settings()
    options: dict[str, Any] = {
        "resumability_config": ResumabilityConfig(is_resumable=True),
    }
    if cfg.agent_architecture in {"collaborative", "graph", "dynamic"}:
        from coding_agent.architectures import build_global_instruction_plugin

        options["plugins"] = [build_global_instruction_plugin()]
    return options


root_agent = build_root_agent()

# CRITICAL: App.name MUST match the package folder name ("coding_agent")
# to avoid "Session not found" errors in ADK runtime and `agents-cli eval`.
app = App(root_agent=root_agent, name="coding_agent", **_build_app_options())
