"""Root ADK Coding Agent definition (starter track).

Evolution across workshop labs:
- Lab 1: Implement ``build_local_environment_toolset()`` and wire
  ``EnvironmentToolset(LocalEnvironment(working_dir=Path(...)))`` into ``LlmAgent``
  (plus optional ADK 2.0 ``collaborative``, ``graph``, and ``dynamic`` architectures
  in ``coding_agent/architectures.py`` selected via ``AGENT_ARCHITECTURE``).
- Lab 2: Switch cleanly to remote ``AgentPlatformSandboxEnvironment`` (``shell`` / ``byoc``)
  or ``AgentEngineSandboxCodeExecutor`` (``code_execution``) based on ``SANDBOX_MODE``.
- Lab 4: Attach parent-runtime telemetry callbacks (OTel + Cloud Logging for sandbox output)
  and optional Memory Bank tools/callbacks.
- Lab 5: Attach ``SkillToolset(registry=GCPSkillRegistry(...))`` for dynamic skill discovery.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

from google.adk.agents import LlmAgent
from google.adk.apps import App, ResumabilityConfig
from google.adk.environment import BaseEnvironment
from google.adk.models import Gemini
from google.adk.tools.environment import EnvironmentToolset
from google.genai import types

from coding_agent.config import Settings, get_settings

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

    Verified ADK gotchas:
    1. ``LocalEnvironment(working_dir=...)`` MUST receive a ``pathlib.Path`` (not ``str``),
       otherwise ``_resolve_path()`` raises ``AttributeError: 'str' object has no attribute 'resolve'``.
    2. ``max_output_chars`` belongs on ``EnvironmentToolset``, NOT on ``LocalEnvironment``.
    """
    # TODO(lab-1): Ensure ``workspace_dir`` exists (mkdir parents=True, exist_ok=True),
    # construct ``LocalEnvironment(working_dir=workspace_dir)``, and return
    # ``EnvironmentToolset(environment=local_env, max_output_chars=max_output_chars)``.
    raise NotImplementedError(
        "Complete TODO(lab-1) in starter/coding_agent/agent.py: "
        "build_local_environment_toolset()."
    )


def _build_remote_execution_components(
    settings: Settings,
) -> tuple[BaseEnvironment | None, list[Any], Any | None]:
    """Build remote sandbox environment/toolset or code executor for Lab 2.

    Returns:
        A tuple of ``(active_environment, extra_tools, code_executor)``.
    """
    if settings.sandbox_mode in {"shell", "byoc"}:
        # TODO(lab-2): Import ``AgentPlatformSandboxEnvironment`` from
        # ``coding_agent.tools.sandbox_execution``, instantiate it with
        # ``project_id``, ``location``, ``instance_name=settings.reasoning_engine_name``,
        # ``template_name=(settings.sandbox_template_name or None) if settings.sandbox_mode == "byoc" else None``
        # (only forward Lab 2's BYOC template when ``sandbox_mode == "byoc"`` so ``shell`` mode never
        # receives a ``custom_container_environment`` template),
        # ``mode=settings.sandbox_mode``, ``ttl=settings.sandbox_ttl``,
        # ``service_account_email=settings.sandbox_service_account_email or None``,
        # and ``runner_base_url=settings.sandbox_runner_base_url or None``.
        # Wrap it in ``EnvironmentToolset(environment=remote_env, max_output_chars=settings.max_output_chars)``
        # and return ``(remote_env, [toolset], None)``.
        raise NotImplementedError(
            "Complete TODO(lab-2) in starter/coding_agent/agent.py for "
            f"SANDBOX_MODE={settings.sandbox_mode!r}."
        )

    if settings.sandbox_mode == "code_execution":
        # TODO(lab-2): Import ``build_code_execution_executor`` from
        # ``coding_agent.tools.sandbox_execution``, build ``AgentEngineSandboxCodeExecutor``
        # using ``settings.sandbox_resource_name`` or ``settings.reasoning_engine_name``,
        # and return ``(None, [], code_executor)``.
        raise NotImplementedError(
            "Complete TODO(lab-2) in starter/coding_agent/agent.py for "
            "SANDBOX_MODE='code_execution'."
        )

    return None, [], None


def _build_optional_skill_toolset(
    settings: Settings,
    environment: BaseEnvironment | None,
) -> Any | None:
    """Optionally attach ``SkillToolset(registry=GCPSkillRegistry(...))`` in Lab 5.

    NOTE: ``SkillToolset`` accepts ``environment=`` OR ``code_executor=``, NEVER both.
    """
    if not settings.enable_skill_registry:
        return None

    # TODO(lab-5): Import ``build_skill_registry_toolset`` from
    # ``coding_agent.tools.registry_loader`` and pass:
    #   project_id=settings.google_cloud_project,
    #   location=settings.agent_registry_location,
    #   local_skill_dirs=[Path(__file__).resolve().parents[1] / "skills_to_register" / "secure-code-review"],
    #   environment=environment,
    #   enable_remote_registry=True,
    logger.info("ENABLE_SKILL_REGISTRY=true; complete TODO(lab-5) to attach SkillToolset.")
    return None


def _build_optional_callbacks(settings: Settings) -> dict[str, Any]:
    """Optionally wire Lab 4 telemetry and Memory Bank callbacks."""
    callbacks: dict[str, Any] = {
        "before_tool_callback": None,
        "after_tool_callback": None,
        "after_agent_callback": None,
        "extra_tools": [],
    }
    if not settings.enable_telemetry_callbacks and not settings.enable_memory_bank:
        return callbacks

    # TODO(lab-4): Import ``before_tool_callback`` and ``after_tool_callback`` from
    # ``coding_agent.callbacks.telemetry_and_feedback`` to log Managed Sandbox stdout/stderr
    # under the parent ReasoningEngine resource and attach OTel tool span attributes.
    # If ``settings.enable_memory_bank`` is enabled, attach ``PreloadMemoryTool()`` and
    # ``persist_turn_to_memory_callback`` as ``after_agent_callback``.
    return callbacks


def _assemble_runtime_components(
    cfg: Settings,
) -> tuple[list[Any], dict[str, Any], Any | None]:
    """Assemble workspace tools, optional Lab 5 skills, Lab 4 callbacks, and code executor."""
    tools: list[Any] = []
    active_environment: BaseEnvironment | None = None
    code_executor: Any | None = None

    if cfg.sandbox_mode == "local":
        workspace_path = cfg.local_workspace_path
        # TODO(lab-1): Call ``build_local_environment_toolset(workspace_path, cfg.max_output_chars)``
        # and append the resulting ``EnvironmentToolset`` to ``tools``.
        try:
            local_toolset = build_local_environment_toolset(
                workspace_dir=workspace_path,
                max_output_chars=cfg.max_output_chars,
            )
            active_environment = getattr(local_toolset, "_environment", None)
            tools.append(local_toolset)
        except NotImplementedError as exc:
            logger.warning("%s Running starter skeleton without EnvironmentToolset.", exc)
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

    # Use an explicit versioned Gemini model ID (do NOT use `gemini-flash-latest` on regional endpoints).
    # Keep `output_schema` unset on this tool-heavy LlmAgent as a cross-model reliability best
    # practice: ADK Python supports `output_schema` + `tools` together on Gemini on Google Cloud,
    # whereas other models fall back to an injected `set_model_response` tool that can be unreliable.
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
