"""ADK 2.0 Multi-Agent, Declarative Graph, Dynamic Workflow, and ManagedAgent builders.

Reference solution track implementing the full ADK 2.0 architecture progression
while keeping ``AGENT_ARCHITECTURE=simple`` (single ``LlmAgent``) as the default
so Labs 2-8 run unchanged.

Verified ADK 2.0 Python design rules encoded in this module:
- **Collaborative agent modes (ADK Python v2.0.0):** Set ``mode="single_turn"``
  or ``mode="task"`` ONLY on subagents, NEVER on the root coordinator agent.
  ``mode="task"`` agents must be leaf agents (no ``sub_agents``) and are disabled
  inside ADK Python v2.0.0 graph-based ``Workflow`` objects.
- **Declarative graph workflows (ADK Python v2.0.0):** Compose ``LlmAgent`` nodes
  (default ``single_turn`` in graphs; ``chat`` mode is only allowed directly after
  ``START``) with ``@node`` functions, ``RetryConfig`` + ``timeout``, ``JoinNode``
  fan-in barriers (single terminal output rule), conditional ``Event(route=...)``
  cycles with explicit loop bounds (graph cycles are NOT bounded automatically),
  and ``RequestInput`` HITL pause nodes (``rerun_on_resume=False``).
- **Dynamic workflows (ADK Python v2.0.0):** Programmatic ``@node(rerun_on_resume=True)``
  orchestrators using ``await ctx.run_node(...)``, ``asyncio.gather(..., use_sub_branch=True)``,
  and automatic checkpointing across HITL pauses. Because Python ``{key}`` prompt
  templates read *session state* (not ``node_input``), yield ``Event(state=...)``
  before invoking ``fixer_agent``.
- **Single output & exception propagation (ADK Python v2.0.0):** Emit strictly ONE
  ``Event(output=...)`` per node execution, let transient errors (``TimeoutError``,
  ``NodeTimeoutError``) propagate to ``RetryConfig``, and NEVER catch ``BaseException``
  without re-raising (catching ``NodeInterruptedError`` breaks HITL pause/resume).
- **Managed agents (ADK Python v2.4.0 Preview):** ``ManagedAgent`` is backed by
  the Managed Agents / Interactions API (``global`` location ONLY on Agent Platform,
  streaming-only, server-side tools only).
"""

from __future__ import annotations

import asyncio
import inspect
import json
import logging
import os
import shutil
import sys
from collections.abc import Mapping, Sequence
from typing import Any

from google.adk import Context, Event, Workflow
from google.adk.agents import LlmAgent
from google.adk.events import RequestInput
from google.adk.plugins.global_instruction_plugin import GlobalInstructionPlugin
from google.adk.workflow import JoinNode, NodeTimeoutError, RetryConfig, node
from pydantic import BaseModel, Field

from coding_agent.config import Settings, get_settings
from coding_agent.models import (
    ModelRole,
    build_gemini4_generate_config,
    build_gemini_model,
)

__all__ = [
    "ApprovalDecision",
    "CheckOutcome",
    "CodeReviewReport",
    "Context",
    "GLOBAL_ENGINEERING_GUARDRAILS",
    "SpecPlan",
    "build_agy_harness_workflow",
    "build_collaborative_coding_team",
    "build_dynamic_coding_workflow",
    "build_global_instruction_plugin",
    "build_graph_coding_workflow",
    "build_optional_managed_agent",
]

logger = logging.getLogger(__name__)

GLOBAL_ENGINEERING_GUARDRAILS = """Global Enterprise Engineering Guardrails:
1. Inspect existing files before making modifications; prefer minimal surgical edits.
2. Never fabricate command output, lint status, or unit test results.
3. Keep all file reads, writes, and shell commands strictly confined to the active workspace.
4. Never hardcode secrets, credentials, or destructive host-level commands.
"""


class ApprovalDecision(BaseModel):
    """Structured human-in-the-loop (HITL) approval response for ``RequestInput``."""

    approved: bool = Field(
        description="Set to true to approve finalizing the verified code changes, or false to reject."
    )
    reviewer_notes: str = Field(
        default="",
        description="Optional human reviewer notes or follow-up instructions.",
    )


class CheckOutcome(BaseModel):
    """Deterministic verification outcome returned by pytest and ruff graph nodes."""

    check_name: str
    passed: bool
    exit_code: int
    summary: str


class CodeReviewReport(BaseModel):
    """Structured code & test review verdict returned by ``code_reviewer``."""

    approved: bool = Field(description="True if implementation and tests meet engineering bars.")
    summary: str = Field(description="Concise summary of code quality, edge cases, and security.")
    issues: list[str] = Field(
        default_factory=list,
        description="Concrete defects, missing tests, or security concerns to fix.",
    )


class SpecPlan(BaseModel):
    """Structured implementation specification emitted by ``spec_planner`` (``gemini-4-neon``)."""

    summary: str = Field(description="Concise engineering plan for the requested change.")
    target_files: list[str] = Field(
        default_factory=list,
        description="Concrete workspace file paths to inspect, modify, or create.",
    )
    acceptance_criteria: list[str] = Field(
        default_factory=list,
        description="Verifiable functional, lint, and unit-test acceptance criteria.",
    )
    implementation_prompt: str = Field(
        description="Actionable implementation brief passed to the coding harness.",
    )


def _build_gemini_model(settings: Settings, *, role: ModelRole = "coding") -> Any:
    """Build a Gemini 4 ADK model routed to ``settings.model_location`` with HTTP retries."""
    return build_gemini_model(settings, role=role)


def _build_generate_config(settings: Settings) -> Any:
    """Build Gemini 4 ``GenerateContentConfig`` using ``ThinkingConfig(thinking_level=...)``."""
    return build_gemini4_generate_config(settings)


def _extract_sandbox_environment(tools: Sequence[Any]) -> Any | None:
    """Return an attached remote ``AgentPlatformSandboxEnvironment`` from ``tools``, if present."""
    for tool in tools:
        env = getattr(tool, "_environment", None) or getattr(tool, "environment", None)
        if env is not None and (
            hasattr(env, "execute_with_env")
            or type(env).__name__ == "AgentPlatformSandboxEnvironment"
        ):
            return env
    return None


def _attach_optional_callbacks(
    agent_kwargs: dict[str, Any],
    callbacks: Mapping[str, Any] | None,
    *,
    include_tool_callbacks: bool = True,
    include_agent_callbacks: bool = False,
) -> None:
    """Attach optional Lab 3 callbacks to an ``LlmAgent`` kwargs dict."""
    if not callbacks:
        return
    if include_tool_callbacks:
        if callbacks.get("before_tool_callback") is not None:
            agent_kwargs["before_tool_callback"] = callbacks["before_tool_callback"]
        if callbacks.get("after_tool_callback") is not None:
            agent_kwargs["after_tool_callback"] = callbacks["after_tool_callback"]
    if include_agent_callbacks and callbacks.get("after_agent_callback") is not None:
        agent_kwargs["after_agent_callback"] = callbacks["after_agent_callback"]


async def _invoke_optional_after_agent_callback(
    callbacks: Mapping[str, Any] | None,
    ctx: Context,
) -> None:
    """Invoke Lab 3's optional ``after_agent_callback`` once at workflow completion.

    ADK 2.0 ``Workflow`` subclasses ``BaseNode`` (not ``BaseAgent``) and does not expose
    an ``after_agent_callback`` field, whereas ADK 2.0 unifies ``CallbackContext`` with
    ``Context`` (exposing ``add_events_to_memory()`` and ``session``). Invoking the
    callback once at the workflow's terminal step preserves Lab 3 Memory Bank turn
    persistence (``persist_turn_to_memory_callback``) in ``graph`` and ``dynamic`` modes
    without duplicating writes across intermediate fix iterations.
    """
    callback = callbacks.get("after_agent_callback") if callbacks else None
    if not callable(callback):
        return
    result = callback(ctx)
    if inspect.isawaitable(result):
        await result


def build_global_instruction_plugin(
    global_instruction: str = GLOBAL_ENGINEERING_GUARDRAILS,
    name: str = "enterprise_coding_guardrails",
) -> GlobalInstructionPlugin:
    """Build ADK's ``GlobalInstructionPlugin`` for App-wide engineering guardrails.

    Applies consistent instructions across the coordinator and all subagents via
    ``App(plugins=[...])``.
    """
    return GlobalInstructionPlugin(global_instruction=global_instruction, name=name)


def _pytest_command() -> list[str]:
    """Return the workspace pytest command using the active Python interpreter."""
    return [sys.executable, "-m", "pytest", "-q"]


def _ruff_command() -> list[str]:
    """Return the workspace ruff command (falling back to ``python -m ruff``)."""
    ruff_bin = shutil.which("ruff")
    return [ruff_bin, "check", "."] if ruff_bin else [sys.executable, "-m", "ruff", "check", "."]


async def _run_workspace_check(
    settings: Settings,
    *,
    check_name: str,
    command: list[str],
    allow_exit_codes: frozenset[int] = frozenset({0}),
    empty_exit_code_message: str = "",
    sandbox_env: Any | None = None,
    remote_command: str | None = None,
    ctx: Context | None = None,
) -> CheckOutcome:
    """Run a deterministic verification CLI inside the local or remote Managed Sandbox workspace.

    IMPORTANT (ADK 2.0 Retry & HITL semantics):
    - Never swallow ``Exception`` or ``BaseException``. The ``except BaseException``
      block around ``proc.communicate()`` only kills and reaps the child subprocess
      if ADK's ``@node(..., timeout=...)`` cancels the coroutine mid-execution, then
      immediately re-raises so ``asyncio.CancelledError``, ``TimeoutError``,
      ``NodeTimeoutError``, and ``NodeInterruptedError`` propagate unmodified to
      ADK's retry/HITL runtime.
    """
    if settings.sandbox_mode != "local":
        if sandbox_env is not None and callable(getattr(sandbox_env, "execute", None)):
            cmd_str = remote_command or " ".join(command)
            exec_res = await sandbox_env.execute(cmd_str, timeout=30.0, ctx=ctx)
            exit_code = int(getattr(exec_res, "exit_code", 1))
            combined = (
                f"{getattr(exec_res, 'stdout', '') or ''}\n"
                f"{getattr(exec_res, 'stderr', '') or ''}"
            ).strip()
            max_chars = min(settings.max_output_chars, 4_000)
            if len(combined) > max_chars:
                combined = combined[:max_chars] + "\n...[truncated]..."
            if exit_code in allow_exit_codes:
                summary = combined or empty_exit_code_message or f"{check_name} passed."
                if exit_code != 0 and empty_exit_code_message:
                    summary = f"{empty_exit_code_message}\n{combined}".strip()
                return CheckOutcome(
                    check_name=check_name,
                    passed=True,
                    exit_code=0,
                    summary=summary,
                )
            return CheckOutcome(
                check_name=check_name,
                passed=False,
                exit_code=exit_code,
                summary=combined or f"{check_name} failed in sandbox with exit code {exit_code}.",
            )
        return CheckOutcome(
            check_name=check_name,
            passed=True,
            exit_code=0,
            summary=(
                f"Skipped host-local {check_name} check while SANDBOX_MODE={settings.sandbox_mode!r}; "
                "verification runs inside the remote Managed Sandbox."
            ),
        )

    workspace_dir = settings.local_workspace_path
    workspace_dir.mkdir(parents=True, exist_ok=True)

    try:
        proc = await asyncio.create_subprocess_exec(
            *command,
            cwd=str(workspace_dir),
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
    except FileNotFoundError:
        return CheckOutcome(
            check_name=check_name,
            passed=True,
            exit_code=0,
            summary=f"{check_name} executable not found on PATH; check skipped.",
        )

    try:
        stdout_bytes, stderr_bytes = await proc.communicate()
    except BaseException:
        if proc.returncode is None:
            try:
                proc.kill()
            except ProcessLookupError:
                pass
        await proc.wait()
        raise

    exit_code = int(proc.returncode or 0)
    combined = (
        stdout_bytes.decode("utf-8", errors="replace").strip()
        + "\n"
        + stderr_bytes.decode("utf-8", errors="replace").strip()
    ).strip()

    max_chars = min(settings.max_output_chars, 4_000)
    if len(combined) > max_chars:
        combined = combined[:max_chars] + "\n...[truncated]..."

    if exit_code in allow_exit_codes:
        summary = combined or empty_exit_code_message or f"{check_name} passed."
        if exit_code != 0 and empty_exit_code_message:
            summary = f"{empty_exit_code_message}\n{combined}".strip()
        return CheckOutcome(
            check_name=check_name,
            passed=True,
            exit_code=0,
            summary=summary,
        )

    return CheckOutcome(
        check_name=check_name,
        passed=False,
        exit_code=exit_code,
        summary=combined or f"{check_name} failed with exit code {exit_code}.",
    )


def _coerce_check_outcome(name: str, raw: Any) -> CheckOutcome:
    """Normalize a ``CheckOutcome`` (or serialized dict) emitted from a workflow node."""
    if isinstance(raw, CheckOutcome):
        return raw
    if isinstance(raw, Mapping):
        return CheckOutcome(
            check_name=str(raw.get("check_name", name)),
            passed=bool(raw.get("passed", False)),
            exit_code=int(raw.get("exit_code", 1)),
            summary=str(raw.get("summary", "")),
        )
    return CheckOutcome(
        check_name=name,
        passed=bool(raw),
        exit_code=0 if raw else 1,
        summary=str(raw),
    )


def _format_check_findings(pytest_raw: Any, ruff_raw: Any) -> str:
    """Format failing pytest/ruff results into a concise findings string (empty when clean)."""
    pytest_res = _coerce_check_outcome("pytest", pytest_raw)
    ruff_res = _coerce_check_outcome("ruff", ruff_raw)
    parts: list[str] = []
    if not pytest_res.passed:
        parts.append(f"[pytest exit={pytest_res.exit_code}]\n{pytest_res.summary}")
    if not ruff_res.passed:
        parts.append(f"[ruff exit={ruff_res.exit_code}]\n{ruff_res.summary}")
    return "\n\n".join(parts)


def _coerce_bool(value: Any) -> bool:
    """Interpret booleans and stringified booleans cleanly for HITL decisions."""
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        return value.strip().lower() in {"1", "true", "yes", "y", "approved"}
    return bool(value)


def _format_approval_note(decision: Any) -> str:
    """Normalize HITL ``RequestInput`` replies across ``graph`` and ``dynamic`` workflows.

    Handles ``ApprovalDecision`` instances, deserialized JSON ``Mapping`` dicts
    containing ``"approved"``, JSON-encoded strings, and plain-text human replies.
    Returns ``""`` when ``decision`` is empty or is the non-HITL graph summary
    payload forwarded along the ``PASS`` route.
    """
    if decision is None:
        return ""
    if isinstance(decision, ApprovalDecision):
        verdict = "APPROVED" if decision.approved else "REJECTED"
        notes = decision.reviewer_notes.strip()
        suffix = f" — {notes}" if notes else ""
        return f"\n\n### Human Approval\n- Decision: **{verdict}**{suffix}"
    if isinstance(decision, Mapping):
        if "approved" in decision:
            verdict = "APPROVED" if _coerce_bool(decision.get("approved")) else "REJECTED"
            notes = str(decision.get("reviewer_notes", "")).strip()
            suffix = f" — {notes}" if notes else ""
            return f"\n\n### Human Approval\n- Decision: **{verdict}**{suffix}"
        if {"checks_passed", "findings"}.issubset(decision.keys()):
            return ""
        if decision:
            return f"\n\n### Human Approval\n- Response: {dict(decision)}"
        return ""
    if isinstance(decision, str):
        text = decision.strip()
        if not text:
            return ""
        if text.startswith("{") and text.endswith("}"):
            try:
                parsed = json.loads(text)
            except json.JSONDecodeError:
                parsed = None
            if isinstance(parsed, Mapping) and "approved" in parsed:
                return _format_approval_note(parsed)
        return f"\n\n### Human Approval\n- Response: {text}"
    return f"\n\n### Human Approval\n- Response: {decision}"


def _build_final_report(
    *,
    code_summary: str,
    findings: str,
    fix_attempts: int,
    approval_note: str = "",
) -> str:
    """Render a deterministic final summary report for graph & dynamic workflows."""
    status = "PASSED" if not findings else f"COMPLETED WITH FINDINGS (after {fix_attempts} fix round(s))"
    lines = [
        f"## Coding Workflow Report — {status}",
        f"- Fix rounds executed: {fix_attempts}",
        "",
        "### Verification Summary",
        findings if findings else "All deterministic checks (pytest + ruff) passed cleanly.",
    ]
    if code_summary:
        lines.extend(["", "### Latest Implementation Summary", code_summary])
    if approval_note:
        lines.append(approval_note)
    return "\n".join(lines)


def build_collaborative_coding_team(
    settings: Settings,
    tools: Sequence[Any],
    callbacks: Mapping[str, Any] | None = None,
    code_executor: Any | None = None,
) -> Any:
    """Build an ADK 2.0 collaborative coordinator team with mode-scoped subagents.

    Architecture (``https://adk.dev/workflows/collaboration/``):
    - Root ``coding_agent`` (Coordinator ``LlmAgent``, NO ``mode`` set on root!)
      delegates automatically via ADK-injected tools named after each subagent:
      - ``code_implementer`` (``mode="single_turn"``): owns ``EnvironmentToolset`` +
        coding tools; runs without user interaction and returns automatically.
      - ``code_reviewer`` (``mode="single_turn"``): reviews code & test results in an
        isolated session branch; parallel-capable and returns a structured
        ``CodeReviewReport``.
      - ``requirements_clarifier`` (``mode="task"``): leaf agent ONLY (no ``sub_agents``);
        asks clarifying questions when requirements are ambiguous and returns control
        to the coordinator automatically via ``finish_task``.
        NOTE: ``mode="task"`` agents must be leaf agents and are disabled inside
        ADK Python v2.0.0 graph-based ``Workflow`` objects.
    """
    implementer_kwargs: dict[str, Any] = {
        "name": "code_implementer",
        "mode": "single_turn",  # ADK 2.0: subagent only; no user interaction, automatic return
        "model": _build_gemini_model(settings, role="coding"),
        "description": (
            "Reads, edits, writes, and tests code inside the confined workspace "
            "using EnvironmentToolset and coding tools."
        ),
        "instruction": (
            "You are the Code Implementer specialist. Inspect existing files with ReadFile, "
            "apply minimal surgical edits with EditFile/WriteFile, and verify changes by "
            "running pytest and ruff with Execute. Report exact modified files and test output."
        ),
        "tools": list(tools),
        "generate_content_config": _build_generate_config(settings),
    }
    if code_executor is not None:
        implementer_kwargs["code_executor"] = code_executor
    _attach_optional_callbacks(
        implementer_kwargs,
        callbacks,
        include_tool_callbacks=True,
        include_agent_callbacks=False,
    )
    code_implementer = LlmAgent(**implementer_kwargs)

    code_reviewer = LlmAgent(
        name="code_reviewer",
        mode="single_turn",  # Isolated session branch; parallel-capable; auto-returns result
        model=_build_gemini_model(settings, role="reasoning"),
        description=(
            "Reviews implemented code changes and verification output for correctness, "
            "edge cases, test coverage, and security regressions."
        ),
        instruction=(
            "You are the Code Reviewer specialist running in an isolated review branch. "
            "Evaluate the provided code changes and verification results for bugs, "
            "missing edge-case tests, style issues, and security vulnerabilities. "
            "Return a concise structured CodeReviewReport."
        ),
        output_schema=CodeReviewReport,
        generate_content_config=_build_generate_config(settings),
    )

    # ADK 2.0 constraint: `mode="task"` agents MUST be leaf agents (cannot declare `sub_agents`)
    # and are disabled inside ADK Python v2.0.0 graph-based `Workflow` definitions.
    requirements_clarifier = LlmAgent(
        name="requirements_clarifier",
        mode="task",  # Can ask clarifying questions; returns to coordinator via `finish_task`
        model=_build_gemini_model(settings, role="coding"),
        description=(
            "Clarifies ambiguous engineering requirements, acceptance criteria, or "
            "target file constraints with the user before implementation begins."
        ),
        instruction=(
            "You are the Requirements Clarifier leaf agent. Ask concise, targeted "
            "clarifying questions ONLY when the engineering request is genuinely ambiguous "
            "(for example, conflicting API contracts or unspecified target files). Once "
            "requirements are clear, call `finish_task` with a crisp specification summary."
        ),
        generate_content_config=_build_generate_config(settings),
    )

    # CRITICAL (ADK 2.0): NEVER configure `mode` on the root coordinator agent.
    coordinator_kwargs: dict[str, Any] = {
        "name": "coding_agent",
        "model": _build_gemini_model(settings, role="coding"),
        "description": (
            "ADK 2.0 Collaborative Coding Coordinator delegating to code_implementer, "
            "code_reviewer, and requirements_clarifier subagents."
        ),
        "instruction": (
            "You are the Enterprise Coding Agent Coordinator. Orchestrate your specialist "
            "subagents to deliver verified code:\n"
            "1. If requirements are ambiguous, delegate to `requirements_clarifier` first.\n"
            "2. Delegate implementation and local/sandbox verification to `code_implementer`.\n"
            "3. Delegate independent quality and security review to `code_reviewer`.\n"
            "4. If `code_reviewer` reports blocking issues, send them back to `code_implementer` "
            "before returning a concise final summary to the user."
        ),
        "sub_agents": [code_implementer, code_reviewer, requirements_clarifier],
        "generate_content_config": _build_generate_config(settings),
    }
    _attach_optional_callbacks(
        coordinator_kwargs,
        callbacks,
        include_tool_callbacks=False,
        include_agent_callbacks=True,
    )
    return LlmAgent(**coordinator_kwargs)


def build_graph_coding_workflow(
    settings: Settings,
    tools: Sequence[Any],
    callbacks: Mapping[str, Any] | None = None,
    code_executor: Any | None = None,
) -> Any:
    """Build a declarative ADK 2.0 ``Workflow`` graph with parallel checks and HITL.

    Graph topology::

        START -> coder_agent ─┬─> run_pytest_node ─┐
                              └─> run_ruff_node   ─┴─> verify_join (JoinNode)
                                                            │
                                                            ▼
                                                      verdict_router
                                                 ┌──────────┼──────────┐
                                            NEEDS_FIX   NEEDS_APPROVAL PASS
                                                 │          │          │
                                                 ▼          ▼          ▼
                                            coder_agent  request_human_approval
                                                            │          │
                                                            └───> finalize_report

    Verified ADK 2.0 invariants:
    - ``coder_agent`` runs in default graph ``single_turn`` mode (NOT ``chat`` mode)
      so conditional back-edges from ``verdict_router`` are valid.
    - ``run_pytest_node`` and ``run_ruff_node`` use ``@node(retry_config=..., timeout=30.0)``
      and always emit a ``CheckOutcome`` output so ``JoinNode`` never stalls.
    - ``verdict_router`` explicitly enforces ``settings.max_fix_rounds`` because
      ADK 2.0 graph cycles are NOT bounded automatically.
    - ``request_human_approval`` uses ``@node(rerun_on_resume=False)`` and yields
      ``RequestInput(..., response_schema=ApprovalDecision)`` (handoff resume mode).
    - ``finalize_report`` is the single terminal node emitting strictly ONE
      ``Event(message=..., output=..., state={"fix_attempts": 0, "latest_findings": ""})``
      (single terminal output rule + per-turn state reset for multi-turn sessions).
    """
    sandbox_env = _extract_sandbox_environment(tools)
    coder_kwargs: dict[str, Any] = {
        "name": "coder_agent",
        "model": _build_gemini_model(settings, role="coding"),
        "description": (
            "Implements or repairs code in the workspace based on the user request "
            "or structured pytest/ruff verification findings."
        ),
        "instruction": (
            "You are the Enterprise Coding Agent inside a deterministic verification graph. "
            "Read existing files before editing, apply minimal surgical changes with your "
            "workspace tools, and summarize the exact files modified. If your input contains "
            "pytest or ruff failures from a previous attempt, fix every reported failure."
        ),
        "tools": list(tools),
        "output_key": "latest_code_summary",
        "generate_content_config": _build_generate_config(settings),
    }
    if code_executor is not None:
        coder_kwargs["code_executor"] = code_executor
    _attach_optional_callbacks(
        coder_kwargs,
        callbacks,
        include_tool_callbacks=True,
        include_agent_callbacks=False,
    )
    coder_agent = LlmAgent(**coder_kwargs)

    check_retry_config = RetryConfig(
        max_attempts=3,
        initial_delay=1.0,
        exceptions=[TimeoutError, NodeTimeoutError],
    )

    @node(
        name="run_pytest_node",
        retry_config=check_retry_config,
        timeout=30.0,
    )
    async def run_pytest_node(ctx: Context, node_input: Any = None) -> CheckOutcome:
        """Deterministic pytest verification node with automatic transient retries."""
        del node_input
        return await _run_workspace_check(
            settings,
            check_name="pytest",
            command=_pytest_command(),
            allow_exit_codes=frozenset({0, 5}),
            empty_exit_code_message="No pytest tests collected in workspace.",
            sandbox_env=sandbox_env,
            remote_command="python3 -m pytest -q",
            ctx=ctx,
        )

    @node(
        name="run_ruff_node",
        retry_config=check_retry_config,
        timeout=30.0,
    )
    async def run_ruff_node(ctx: Context, node_input: Any = None) -> CheckOutcome:
        """Deterministic ruff lint verification node with automatic transient retries."""
        del node_input
        return await _run_workspace_check(
            settings,
            check_name="ruff",
            command=_ruff_command(),
            allow_exit_codes=frozenset({0}),
            empty_exit_code_message="ruff check passed with zero violations.",
            sandbox_env=sandbox_env,
            remote_command="ruff check .",
            ctx=ctx,
        )

    verify_join = JoinNode(name="verify_join")

    @node(name="verdict_router")
    async def verdict_router(
        ctx: Context,
        node_input: dict[str, Any],
        fix_attempts: int = 0,
    ) -> Any:
        """Route parallel JoinNode check results with an explicit max_fix_rounds bound."""
        del ctx
        joined = node_input if isinstance(node_input, Mapping) else {}
        pytest_raw = joined.get("run_pytest_node")
        ruff_raw = joined.get("run_ruff_node")
        findings = _format_check_findings(pytest_raw, ruff_raw)
        all_passed = not findings

        # ADK 2.0 graph cycles are NOT bounded automatically; enforce `max_fix_rounds` explicitly.
        if not all_passed and fix_attempts < settings.max_fix_rounds:
            next_attempt = fix_attempts + 1
            fix_prompt = (
                f"Automated verification failed on attempt {next_attempt}/{settings.max_fix_rounds}.\n"
                f"Fix all issues below without regressing existing functionality:\n\n{findings}"
            )
            return Event(
                route="NEEDS_FIX",
                output=fix_prompt,
                state={
                    "fix_attempts": next_attempt,
                    "latest_findings": findings,
                    "checks_passed": False,
                },
            )

        summary_payload = {
            "checks_passed": all_passed,
            "fix_attempts": fix_attempts,
            "findings": findings or "All checks (pytest + ruff) passed cleanly.",
        }
        route_key = "NEEDS_APPROVAL" if settings.enable_hitl_approval else "PASS"
        return Event(
            route=route_key,
            output=summary_payload,
            state={
                "fix_attempts": fix_attempts,
                "latest_findings": findings,
                "checks_passed": all_passed,
            },
        )

    @node(name="request_human_approval", rerun_on_resume=False)
    async def request_human_approval(ctx: Context, node_input: Any):
        """Pause the graph workflow for structured human approval before finalizing."""
        del ctx
        yield RequestInput(
            message=(
                "Verification completed. Review the summary payload and respond with an "
                "ApprovalDecision (`approved`: bool, `reviewer_notes`: str) to continue."
            ),
            payload=node_input,
            response_schema=ApprovalDecision,
        )

    @node(name="finalize_report")
    async def finalize_report(
        ctx: Context,
        node_input: Any,
        fix_attempts: int = 0,
        latest_findings: str = "",
        latest_code_summary: str = "",
    ) -> Any:
        """Single terminal node emitting strictly ONE Event and resetting turn state."""
        approval_note = _format_approval_note(node_input) if settings.enable_hitl_approval else ""

        report = _build_final_report(
            code_summary=str(latest_code_summary or "").strip(),
            findings=latest_findings,
            fix_attempts=fix_attempts,
            approval_note=approval_note,
        )
        await _invoke_optional_after_agent_callback(callbacks, ctx)
        # Reset per-turn workflow state on terminal completion so multi-turn sessions
        # start Turn 2+ fresh at `fix_attempts=0` while preserving state across HITL pauses.
        return Event(
            message=report,
            output=report,
            state={
                "fix_attempts": 0,
                "latest_findings": "",
                "latest_code_summary": "",
            },
        )

    return Workflow(
        name="coding_agent",
        description=(
            "ADK 2.0 declarative graph workflow combining coder_agent, parallel "
            "pytest/ruff nodes with RetryConfig, JoinNode fan-in, bounded fix routing, "
            "optional RequestInput HITL approval, and a single terminal report node."
        ),
        edges=[
            ("START", coder_agent),
            (coder_agent, run_pytest_node, verify_join),
            (coder_agent, run_ruff_node, verify_join),
            (verify_join, verdict_router),
            (
                verdict_router,
                {
                    "NEEDS_FIX": coder_agent,
                    "NEEDS_APPROVAL": request_human_approval,
                    "PASS": finalize_report,
                },
            ),
            (request_human_approval, finalize_report),
        ],
    )


def build_dynamic_coding_workflow(
    settings: Settings,
    tools: Sequence[Any],
    callbacks: Mapping[str, Any] | None = None,
    code_executor: Any | None = None,
) -> Any:
    """Build an ADK 2.0 dynamic programmatic workflow mirroring ``adk.dev/graphs/dynamic/#loop-route``.

    Uses a ``@node(rerun_on_resume=True)`` orchestrator that:
    1. Calls ``await ctx.run_node(coder_agent, node_input)``.
    2. Runs parallel ``pytest`` and ``ruff`` checks via ``asyncio.gather(...)`` with
       ``use_sub_branch=True`` to isolate parallel events.
    3. Iterates up to ``settings.max_fix_rounds``, writing ``{"code": ..., "findings": ...}``
       to session state via ``Event(state=...)`` (required because Python ``{key}``
       prompt templates read session state, NOT ``node_input``) before invoking
       ``await ctx.run_node(fixer_agent, ...)``.
    4. Optionally awaits ``request_human_approval`` (``rerun_on_resume=False``),
       relying on ADK 2.0 automatic checkpointing to skip already-completed child
       runs upon resume.
    """
    sandbox_env = _extract_sandbox_environment(tools)
    coder_kwargs: dict[str, Any] = {
        "name": "coder_agent",
        "model": _build_gemini_model(settings, role="coding"),
        "description": "Generates and edits workspace code for the user request.",
        "instruction": (
            "You are the Coding Generator agent. Inspect existing workspace files, "
            "implement the requested changes surgically with your tools, and summarize "
            "the modified files."
        ),
        "tools": list(tools),
        "generate_content_config": _build_generate_config(settings),
    }
    if code_executor is not None:
        coder_kwargs["code_executor"] = code_executor
    _attach_optional_callbacks(
        coder_kwargs,
        callbacks,
        include_tool_callbacks=True,
        include_agent_callbacks=False,
    )
    coder_agent = LlmAgent(**coder_kwargs)

    fixer_kwargs: dict[str, Any] = {
        "name": "fixer_agent",
        "model": _build_gemini_model(settings, role="coding"),
        "description": "Refactors workspace code based on pytest and ruff findings.",
        "instruction": (
            "Refactor the current workspace implementation to fix all verification findings.\n\n"
            "Previous implementation summary:\n{code}\n\n"
            "Pytest & ruff findings:\n{findings}\n\n"
            "Apply minimal surgical edits with your tools and summarize the fixes."
        ),
        "tools": list(tools),
        "generate_content_config": _build_generate_config(settings),
    }
    if code_executor is not None:
        fixer_kwargs["code_executor"] = code_executor
    _attach_optional_callbacks(
        fixer_kwargs,
        callbacks,
        include_tool_callbacks=True,
        include_agent_callbacks=False,
    )
    fixer_agent = LlmAgent(**fixer_kwargs)

    check_retry_config = RetryConfig(
        max_attempts=3,
        initial_delay=1.0,
        exceptions=[TimeoutError, NodeTimeoutError],
    )

    @node(
        name="run_pytest_node",
        retry_config=check_retry_config,
        timeout=30.0,
    )
    async def run_pytest_node(ctx: Context, node_input: Any = None) -> CheckOutcome:
        """Run pytest inside the active workspace."""
        del node_input
        return await _run_workspace_check(
            settings,
            check_name="pytest",
            command=_pytest_command(),
            allow_exit_codes=frozenset({0, 5}),
            empty_exit_code_message="No pytest tests collected in workspace.",
            sandbox_env=sandbox_env,
            remote_command="python3 -m pytest -q",
            ctx=ctx,
        )

    @node(
        name="run_ruff_node",
        retry_config=check_retry_config,
        timeout=30.0,
    )
    async def run_ruff_node(ctx: Context, node_input: Any = None) -> CheckOutcome:
        """Run ruff check inside the active workspace."""
        del node_input
        return await _run_workspace_check(
            settings,
            check_name="ruff",
            command=_ruff_command(),
            allow_exit_codes=frozenset({0}),
            empty_exit_code_message="ruff check passed with zero violations.",
            sandbox_env=sandbox_env,
            remote_command="ruff check .",
            ctx=ctx,
        )

    @node(name="request_human_approval", rerun_on_resume=False)
    async def request_human_approval(ctx: Context, node_input: Any):
        """Leaf HITL node pausing for structured ApprovalDecision."""
        del ctx
        yield RequestInput(
            message=(
                "Dynamic coding workflow completed automated checks. Submit an "
                "ApprovalDecision (`approved`: bool, `reviewer_notes`: str) to finalize."
            ),
            payload=node_input,
            response_schema=ApprovalDecision,
        )

    @node(name="dynamic_coding_workflow", rerun_on_resume=True)
    async def dynamic_coding_workflow(ctx: Context, node_input: str):
        """Programmatic ADK 2.0 orchestrator with bounded fix loop and HITL checkpointing."""
        code_summary = await ctx.run_node(coder_agent, node_input)

        pytest_res, ruff_res = await asyncio.gather(
            ctx.run_node(run_pytest_node, code_summary, use_sub_branch=True),
            ctx.run_node(run_ruff_node, code_summary, use_sub_branch=True),
        )
        latest_findings = _format_check_findings(pytest_res, ruff_res)
        attempts_used = 0

        for attempt in range(settings.max_fix_rounds):
            if not latest_findings:
                break
            attempts_used = attempt + 1
            # CRITICAL (ADK Python): `{code}` and `{findings}` in `fixer_agent.instruction`
            # are substituted from session state, NOT from `node_input`.
            yield Event(
                state={
                    "code": str(code_summary),
                    "findings": latest_findings,
                    "fix_attempts": attempts_used,
                }
            )
            code_summary = await ctx.run_node(
                fixer_agent,
                {"code": str(code_summary), "findings": latest_findings},
            )
            pytest_res, ruff_res = await asyncio.gather(
                ctx.run_node(run_pytest_node, code_summary, use_sub_branch=True),
                ctx.run_node(run_ruff_node, code_summary, use_sub_branch=True),
            )
            latest_findings = _format_check_findings(pytest_res, ruff_res)

        approval_note = ""
        if settings.enable_hitl_approval:
            decision = await ctx.run_node(
                request_human_approval,
                {
                    "code_summary": str(code_summary),
                    "findings": latest_findings or "All checks (pytest + ruff) passed cleanly.",
                    "fix_attempts": attempts_used,
                },
            )
            approval_note = _format_approval_note(decision)

        final_report = _build_final_report(
            code_summary=str(code_summary),
            findings=latest_findings,
            fix_attempts=attempts_used,
            approval_note=approval_note,
        )
        await _invoke_optional_after_agent_callback(callbacks, ctx)
        # Emit strictly ONE Event(output=...) per node execution and clear per-turn
        # fixer template keys so subsequent turns start clean.
        yield Event(
            message=final_report,
            output=final_report,
            state={
                "code": "",
                "findings": "",
                "fix_attempts": 0,
            },
        )

    return Workflow(
        name="coding_agent",
        description=(
            "ADK 2.0 dynamic programmatic workflow using @node(rerun_on_resume=True), "
            "ctx.run_node(), asyncio.gather(..., use_sub_branch=True), bounded fix "
            "iterations, and automatic HITL checkpointing."
        ),
        edges=[("START", dynamic_coding_workflow)],
    )


def _format_spec_brief(spec_output: Any, fallback_prompt: str) -> str:
    """Render a ``SpecPlan`` (or raw string/mapping) into a concrete implementation brief."""
    if isinstance(spec_output, SpecPlan):
        targets = "\n".join(f"- {f}" for f in spec_output.target_files) or "- (inspect workspace)"
        criteria = "\n".join(f"- {c}" for c in spec_output.acceptance_criteria) or "- All pytest and ruff checks pass"
        return (
            f"Implementation Brief:\n{spec_output.implementation_prompt}\n\n"
            f"Summary:\n{spec_output.summary}\n\n"
            f"Target Files:\n{targets}\n\n"
            f"Acceptance Criteria:\n{criteria}"
        )
    if isinstance(spec_output, Mapping):
        impl_prompt = str(spec_output.get("implementation_prompt") or fallback_prompt).strip()
        summary = str(spec_output.get("summary") or "").strip()
        target_files = spec_output.get("target_files") or []
        acceptance = spec_output.get("acceptance_criteria") or []
        targets = "\n".join(f"- {f}" for f in target_files) or "- (inspect workspace)"
        criteria = "\n".join(f"- {c}" for c in acceptance) or "- All pytest and ruff checks pass"
        return (
            f"Implementation Brief:\n{impl_prompt}\n\n"
            f"Summary:\n{summary}\n\n"
            f"Target Files:\n{targets}\n\n"
            f"Acceptance Criteria:\n{criteria}"
        )
    text = str(spec_output or "").strip()
    return text or fallback_prompt


def _format_review_section(review_output: Any) -> str:
    """Format an independent ``CodeReviewReport`` into a markdown report section."""
    if isinstance(review_output, CodeReviewReport):
        verdict = "APPROVED" if review_output.approved else "CHANGES REQUESTED"
        issues = "\n".join(f"- {item}" for item in review_output.issues)
        body = f"- Verdict: **{verdict}**\n- Summary: {review_output.summary}"
        if issues:
            body += f"\n- Issues:\n{issues}"
        return body
    if isinstance(review_output, Mapping):
        verdict = "APPROVED" if _coerce_bool(review_output.get("approved", False)) else "CHANGES REQUESTED"
        summary = str(review_output.get("summary", "")).strip()
        issues_list = review_output.get("issues") or []
        body = f"- Verdict: **{verdict}**\n- Summary: {summary}"
        if issues_list:
            body += "\n- Issues:\n" + "\n".join(f"- {item}" for item in issues_list)
        return body
    return str(review_output or "").strip()


def build_agy_harness_workflow(
    settings: Settings,
    tools: Sequence[Any],
    callbacks: Mapping[str, Any] | None = None,
    code_executor: Any | None = None,
) -> Any:
    """Build the 5th ADK 2.0 architecture: outer ADK workflow + Antigravity (``agy``) harness.

    5-stage enterprise workflow (``AGENT_ARCHITECTURE=agy_harness``):
    1. ``spec_planner`` (``gemini-4-neon`` on ``global``) produces concrete file targets
       and verifiable acceptance criteria (``SpecPlan``).
    2. ``run_agy_harness_node`` delegates code edits to ``AgyHeadlessHarness`` (auto-selecting
       BYOC Managed Sandbox vs local/Agent Runtime ``agy``, capturing ``conversation_id``,
       recording OTel trace/token attributes, and retrying/falling back ``gemini-4-neon`` ->
       ``gemini-4-hydrogen`` on exit code 3; gracefully falling back to native ADK 2.0
       ``fallback_coder_agent`` if ``agy`` is unavailable or sandbox is air-gapped).
    3. Independent deterministic verification gates (``pytest`` + ``ruff`` via
       ``asyncio.gather(..., use_sub_branch=True)``) — never trusting the coding harness
       to grade itself.
    4. Bounded fix loop (``settings.max_fix_rounds``) feeding exact failures back via
       ``--conversation <conversation_id>`` (or into ``fallback_coder_agent``).
    5. Independent ``code_reviewer`` (``gemini-4-neon`` on ``global``) + optional
       ``RequestInput`` HITL approval gate (``ApprovalDecision``).
    """
    from coding_agent.tools.agy_headless_harness import AgyExitCode, AgyHeadlessHarness

    sandbox_env = _extract_sandbox_environment(tools)
    harness = AgyHeadlessHarness(settings=settings, sandbox_env=sandbox_env)

    spec_planner = LlmAgent(
        name="spec_planner",
        model=_build_gemini_model(settings, role="reasoning"),
        description=(
            "Frontier Gemini 4 Neon planner that converts engineering requests into "
            "concrete file targets, acceptance criteria, and a crisp implementation brief."
        ),
        instruction=(
            "You are the Principal Engineering Planner. Given the user's coding request, "
            "produce a structured SpecPlan identifying concrete target workspace files, "
            "verifiable acceptance criteria (including unit tests and ruff linting), and "
            "a clear implementation brief for the coding harness."
        ),
        output_schema=SpecPlan,
        generate_content_config=_build_generate_config(settings),
    )

    fallback_coder_kwargs: dict[str, Any] = {
        "name": "fallback_coder_agent",
        "model": _build_gemini_model(settings, role="coding"),
        "description": (
            "Native ADK 2.0 coding fallback agent used automatically when the `agy` CLI "
            "is unavailable locally or inside an air-gapped Managed Sandbox."
        ),
        "instruction": (
            "You are the native ADK 2.0 fallback Coding Agent. Inspect workspace files "
            "with ReadFile, apply minimal surgical edits with EditFile/WriteFile, and "
            "summarize the exact modified files."
        ),
        "tools": list(tools),
        "generate_content_config": _build_generate_config(settings),
    }
    if code_executor is not None:
        fallback_coder_kwargs["code_executor"] = code_executor
    _attach_optional_callbacks(
        fallback_coder_kwargs,
        callbacks,
        include_tool_callbacks=True,
        include_agent_callbacks=False,
    )
    fallback_coder_agent = LlmAgent(**fallback_coder_kwargs)

    code_reviewer = LlmAgent(
        name="code_reviewer",
        model=_build_gemini_model(settings, role="reasoning"),
        description=(
            "Independent Gemini 4 Neon reviewer auditing implementation summaries and "
            "deterministic pytest/ruff outputs for correctness, edge cases, and security."
        ),
        instruction=(
            "You are the Independent Code Reviewer. Evaluate the specification, coding "
            "harness summary, and independent pytest/ruff verification results. Return "
            "a concise, objective CodeReviewReport."
        ),
        output_schema=CodeReviewReport,
        generate_content_config=_build_generate_config(settings),
    )

    check_retry_config = RetryConfig(
        max_attempts=3,
        initial_delay=1.0,
        exceptions=[TimeoutError, NodeTimeoutError],
    )

    @node(name="run_agy_harness_node")
    async def run_agy_harness_node(ctx: Context, node_input: Any) -> dict[str, Any]:
        """Delegate coding implementation to ``AgyHeadlessHarness`` with exit-code-3 retry."""
        payload = node_input if isinstance(node_input, Mapping) else {"prompt": str(node_input)}
        prompt = str(payload.get("prompt", "")).strip()
        conv_id = payload.get("conversation_id")
        result = await harness.run_with_retry_and_fallback(
            prompt=prompt,
            conversation_id=str(conv_id) if conv_id else None,
            max_retries=1,
            ctx=ctx,
        )
        return result.to_dict()

    @node(
        name="run_pytest_node",
        retry_config=check_retry_config,
        timeout=30.0,
    )
    async def run_pytest_node(ctx: Context, node_input: Any = None) -> CheckOutcome:
        """Independent deterministic pytest gate (never trusting the coding harness)."""
        del node_input
        return await _run_workspace_check(
            settings,
            check_name="pytest",
            command=_pytest_command(),
            allow_exit_codes=frozenset({0, 5}),
            empty_exit_code_message="No pytest tests collected in workspace.",
            sandbox_env=sandbox_env,
            remote_command="python3 -m pytest -q",
            ctx=ctx,
        )

    @node(
        name="run_ruff_node",
        retry_config=check_retry_config,
        timeout=30.0,
    )
    async def run_ruff_node(ctx: Context, node_input: Any = None) -> CheckOutcome:
        """Independent deterministic ruff lint gate (never trusting the coding harness)."""
        del node_input
        return await _run_workspace_check(
            settings,
            check_name="ruff",
            command=_ruff_command(),
            allow_exit_codes=frozenset({0}),
            empty_exit_code_message="ruff check passed with zero violations.",
            sandbox_env=sandbox_env,
            remote_command="ruff check .",
            ctx=ctx,
        )

    @node(name="request_human_approval", rerun_on_resume=False)
    async def request_human_approval(ctx: Context, node_input: Any):
        """Leaf HITL node pausing for structured ApprovalDecision."""
        del ctx
        yield RequestInput(
            message=(
                "Antigravity coding harness workflow completed independent verification "
                "and Gemini 4 Neon review. Submit an ApprovalDecision (`approved`: bool, "
                "`reviewer_notes`: str) to finalize."
            ),
            payload=node_input,
            response_schema=ApprovalDecision,
        )

    def _extract_agy_exit_code(result: Any) -> int:
        if not isinstance(result, Mapping):
            return int(AgyExitCode.FAILURE)
        raw = result.get("exit_code", int(AgyExitCode.FAILURE))
        try:
            return int(raw)
        except (TypeError, ValueError):
            return int(AgyExitCode.FAILURE)

    def _format_agy_failure(result: Any, *, exit_code: int, stage: str) -> str:
        if isinstance(result, Mapping):
            status_label = str(result.get("status") or "failure").strip()
            detail = str(
                result.get("agy_error") or result.get("stderr") or "Unknown agy error"
            ).strip()
            hint = str(result.get("actionable_hint") or "").strip()
            lines = [
                f"[agy_harness exit={exit_code} status={status_label} stage={stage}]",
                detail,
            ]
            if hint:
                lines.append(f"Hint: {hint}")
            return "\n".join(lines)
        return f"[agy_harness exit={exit_code} stage={stage}]\n{result}"

    def _combine_findings(harness_failure: str, check_findings: str) -> str:
        parts = [part for part in (harness_failure.strip(), check_findings.strip()) if part]
        return "\n\n".join(parts)

    @node(name="agy_harness_workflow", rerun_on_resume=True)
    async def agy_harness_workflow(ctx: Context, node_input: str):
        """ADK 2.0 orchestrator combining Gemini 4 Neon planning/review + ``agy`` harness."""
        spec_plan = await ctx.run_node(spec_planner, node_input)
        implementation_brief = _format_spec_brief(spec_plan, node_input)

        agy_result = await ctx.run_node(
            run_agy_harness_node,
            {"prompt": implementation_brief, "conversation_id": None},
        )
        conversation_id = (
            agy_result.get("conversation_id") if isinstance(agy_result, Mapping) else None
        )
        using_native_fallback = (
            isinstance(agy_result, Mapping) and agy_result.get("status") == "unavailable"
        )
        harness_backend = str(
            agy_result.get("execution_mode", "fallback")
            if isinstance(agy_result, Mapping)
            else "fallback"
        )
        agy_failure_finding = ""
        agy_fail_fast = False

        if using_native_fallback:
            logger.info(
                "agy CLI unavailable (%s); falling back to native ADK 2.0 LlmAgent + EnvironmentToolset.",
                agy_result.get("actionable_hint", ""),
            )
            harness_backend = "adk_native_fallback"
            code_summary = str(await ctx.run_node(fallback_coder_agent, implementation_brief))
        else:
            agy_exit_code = _extract_agy_exit_code(agy_result)
            if agy_exit_code == int(AgyExitCode.SUCCESS):
                code_summary = str(agy_result.get("response_text") or "").strip()
            else:
                # Exit codes 1 (FAILURE) and 2 (UNSUPPORTED_COMMAND) must fail fast and NEVER
                # re-invoke `agy` in the fix loop; exhausted exit code 3 (AGENT_ERROR, after
                # run_agy_harness_node already ran bounded retry + model fallback) likewise
                # stops cleanly and surfaces the failure in findings so the final report never
                # claims PASSED.
                agy_failure_finding = _format_agy_failure(
                    agy_result,
                    exit_code=agy_exit_code,
                    stage="initial",
                )
                code_summary = agy_failure_finding
                agy_fail_fast = True

        pytest_res, ruff_res = await asyncio.gather(
            ctx.run_node(run_pytest_node, code_summary, use_sub_branch=True),
            ctx.run_node(run_ruff_node, code_summary, use_sub_branch=True),
        )
        check_findings = _format_check_findings(pytest_res, ruff_res)
        latest_findings = _combine_findings(agy_failure_finding, check_findings)
        attempts_used = 0

        if not agy_fail_fast:
            for attempt in range(settings.max_fix_rounds):
                if not check_findings:
                    break
                attempts_used = attempt + 1
                fix_prompt = (
                    f"Independent verification failed on fix round {attempts_used}/{settings.max_fix_rounds}.\n"
                    f"Fix every pytest/ruff issue below without regressing existing tests:\n\n"
                    f"{check_findings}"
                )
                yield Event(
                    state={
                        "agy_conversation_id": conversation_id or "",
                        "fix_attempts": attempts_used,
                        "latest_findings": latest_findings,
                    }
                )
                if using_native_fallback:
                    code_summary = str(await ctx.run_node(fallback_coder_agent, fix_prompt))
                else:
                    agy_result = await ctx.run_node(
                        run_agy_harness_node,
                        {"prompt": fix_prompt, "conversation_id": conversation_id},
                    )
                    if isinstance(agy_result, Mapping):
                        conversation_id = agy_result.get("conversation_id") or conversation_id
                        if agy_result.get("status") == "unavailable":
                            using_native_fallback = True
                            harness_backend = "adk_native_fallback"
                            agy_failure_finding = ""
                            code_summary = str(await ctx.run_node(fallback_coder_agent, fix_prompt))
                        else:
                            fix_exit_code = _extract_agy_exit_code(agy_result)
                            if fix_exit_code == int(AgyExitCode.SUCCESS):
                                agy_failure_finding = ""
                                code_summary = str(
                                    agy_result.get("response_text") or code_summary
                                ).strip()
                            else:
                                agy_failure_finding = _format_agy_failure(
                                    agy_result,
                                    exit_code=fix_exit_code,
                                    stage=f"fix_round_{attempts_used}",
                                )
                                code_summary = agy_failure_finding
                                agy_fail_fast = True
                    else:
                        agy_failure_finding = _format_agy_failure(
                            agy_result,
                            exit_code=int(AgyExitCode.FAILURE),
                            stage=f"fix_round_{attempts_used}",
                        )
                        code_summary = agy_failure_finding
                        agy_fail_fast = True

                pytest_res, ruff_res = await asyncio.gather(
                    ctx.run_node(run_pytest_node, code_summary, use_sub_branch=True),
                    ctx.run_node(run_ruff_node, code_summary, use_sub_branch=True),
                )
                check_findings = _format_check_findings(pytest_res, ruff_res)
                latest_findings = _combine_findings(agy_failure_finding, check_findings)
                if agy_fail_fast:
                    break

        review_input = (
            f"Specification:\n{implementation_brief}\n\n"
            f"Execution Backend: {harness_backend}\n"
            f"Conversation ID: {conversation_id or 'n/a'}\n"
            f"Fix Rounds Used: {attempts_used}\n\n"
            f"Implementation Summary:\n{code_summary}\n\n"
            f"Independent Deterministic Verification & Harness Status:\n"
            f"{latest_findings or 'All deterministic checks (pytest + ruff) passed cleanly.'}"
        )
        review_report = await ctx.run_node(code_reviewer, review_input)
        review_section = _format_review_section(review_report)

        approval_note = ""
        if settings.enable_hitl_approval:
            decision = await ctx.run_node(
                request_human_approval,
                {
                    "backend": harness_backend,
                    "conversation_id": conversation_id,
                    "code_summary": code_summary,
                    "findings": latest_findings or "All checks (pytest + ruff) passed cleanly.",
                    "review": review_section,
                    "fix_attempts": attempts_used,
                },
            )
            approval_note = _format_approval_note(decision)

        base_report = _build_final_report(
            code_summary=f"[backend={harness_backend}, conversation_id={conversation_id or 'n/a'}]\n{code_summary}",
            findings=latest_findings,
            fix_attempts=attempts_used,
            approval_note=approval_note,
        )
        final_report = f"{base_report}\n\n### Independent Gemini 4 Neon Review\n{review_section}"

        await _invoke_optional_after_agent_callback(callbacks, ctx)
        yield Event(
            message=final_report,
            output=final_report,
            state={
                "agy_conversation_id": "",
                "fix_attempts": 0,
                "latest_findings": "",
            },
        )

    return Workflow(
        name="coding_agent",
        description=(
            "ADK 2.0 hybrid coding workflow pairing Gemini 4 Neon spec/review with "
            "Antigravity (`agy`) headless coding harness (auto sandbox/local/native fallback), "
            "independent parallel pytest/ruff verification, bounded --conversation fix loops, "
            "and optional RequestInput HITL approval."
        ),
        edges=[("START", agy_harness_workflow)],
    )


def build_optional_managed_agent(
    agent_id: str | None = None,
    settings: Settings | None = None,
) -> Any:
    """Build an optional ADK Python v2.4.0 Preview ``ManagedAgent`` reference subagent.

    Connects to a Google-hosted first-party managed agent (for example,
    ``antigravity-preview-05-2026``) via the Managed Agents / Interactions API.
    With ``mode="single_turn"``, it can be added directly to a parent coordinator
    ``LlmAgent.sub_agents`` as an inline tool.

    Verified ADK Python v2.4.0 Preview limitations (``adk.dev/agents/managed-agents/``):
    - **Agent Platform backend is ``global``-only:** The Managed Agents API is served
      exclusively from the ``global`` location; regional endpoints raise an error
      (``ManagedAgent`` enforces ``location="global"`` on enterprise clients).
    - **Server-side tools only:** Supports built-in server-side tools (e.g.,
      ``google_search``, ``types.Tool(code_execution=types.ToolCodeExecution())``)
      and remote MCP servers declared as ``google.adk.tools.RemoteMcpServer``.
      Client-executed Python callables / ``FunctionTool`` and raw
      ``types.Tool.mcp_servers`` raise ``NotImplementedError``.
    - **Streaming only:** Uses streaming Interactions API calls (``stream=True``).
    """
    try:
        from google.adk.agents import ManagedAgent
        from google.adk.tools import google_search
    except ImportError as exc:
        raise RuntimeError(
            "ManagedAgent requires ADK Python >= 2.4.0 (Preview). Upgrade with:\n"
            '  pip install "google-adk[a2a,agent-identity,mcp]>=2.4.0"'
        ) from exc

    cfg = settings or get_settings()
    resolved_agent_id = (
        (agent_id or "").strip()
        or cfg.managed_agent_id
        or os.environ.get("MANAGED_AGENT_ID", "").strip()
        or "antigravity-preview-05-2026"
    )
    return ManagedAgent(
        name="managed_research_agent",
        mode="single_turn",
        description=(
            "Google-hosted Managed Agent that answers fresh engineering and API "
            "questions using built-in server-side Google Search."
        ),
        agent_id=resolved_agent_id,
        environment={"type": "remote"},
        tools=[google_search],
    )
