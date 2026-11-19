"""ADK 2.0 Multi-Agent, Declarative Graph, Dynamic Workflow, and ManagedAgent builders.

Reference solution track implementing the full ADK 2.0 architecture progression
while keeping ``AGENT_ARCHITECTURE=simple`` (single ``LlmAgent``) 100% backward
compatible with Labs 2-7 and ADK ``1.29.x``.

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
from dataclasses import dataclass
from typing import Any

from pydantic import BaseModel, Field

from coding_agent.config import Settings, get_settings

try:
    from google.adk import Context
except ImportError:  # ADK 1.x fallback so `AGENT_ARCHITECTURE=simple` stays importable
    Context = Any  # type: ignore[misc, assignment]

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


@dataclass(frozen=True)
class _AdkV2Runtime:
    """Lazy bundle of ADK 2.0+ workflow, event, and node primitives."""

    Context: Any
    Event: Any
    JoinNode: Any
    NodeTimeoutError: Any
    RequestInput: Any
    RetryConfig: Any
    Workflow: Any
    node: Any


def _require_adk_v2() -> _AdkV2Runtime:
    """Verify ADK Python >= 2.0.0 workflow primitives are installed and return them.

    This lazy guard allows ``AGENT_ARCHITECTURE=simple`` to run cleanly even on
    ADK ``1.29.x``, while raising an actionable upgrade hint whenever
    ``collaborative``, ``graph``, or ``dynamic`` is selected on ADK ``< 2.0.0``.
    """
    try:
        import google.adk

        adk_version = getattr(google.adk, "__version__", "unknown")
    except ImportError as exc:
        raise RuntimeError(
            "google-adk is not installed. Install ADK 2.0+ with:\n"
            '  pip install "google-adk[a2a,agent-identity,mcp]>=2.0.0"'
        ) from exc

    try:
        from google.adk import Context as AdkContext
        from google.adk import Event, Workflow
        from google.adk.events import RequestInput
        from google.adk.workflow import JoinNode, NodeTimeoutError, RetryConfig, node
    except ImportError as exc:
        raise RuntimeError(
            "ADK Python >= 2.0.0 is required for AGENT_ARCHITECTURE in "
            "{collaborative, graph, dynamic} "
            f"(detected google-adk=={adk_version}). Upgrade with:\n"
            '  pip install "google-adk[a2a,agent-identity,mcp]>=2.0.0"\n'
            "Or set AGENT_ARCHITECTURE=simple in .env to stay on ADK 1.29.x."
        ) from exc

    return _AdkV2Runtime(
        Context=AdkContext,
        Event=Event,
        JoinNode=JoinNode,
        NodeTimeoutError=NodeTimeoutError,
        RequestInput=RequestInput,
        RetryConfig=RetryConfig,
        Workflow=Workflow,
        node=node,
    )


def _build_gemini_model(settings: Settings) -> Any:
    """Build a regional-safe versioned Gemini model with HTTP retries."""
    from google.adk.models import Gemini
    from google.genai import types

    return Gemini(
        model=settings.model_name,
        retry_options=types.HttpRetryOptions(initial_delay=1, attempts=2),
    )


def _attach_optional_callbacks(
    agent_kwargs: dict[str, Any],
    callbacks: Mapping[str, Any] | None,
    *,
    include_tool_callbacks: bool = True,
    include_agent_callbacks: bool = False,
) -> None:
    """Attach optional Lab 4 callbacks to an ``LlmAgent`` kwargs dict."""
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
    """Invoke Lab 4's optional ``after_agent_callback`` once at workflow completion.

    ADK 2.0 ``Workflow`` subclasses ``BaseNode`` (not ``BaseAgent``) and does not expose
    an ``after_agent_callback`` field, whereas ADK 2.0 unifies ``CallbackContext`` with
    ``Context`` (exposing ``add_events_to_memory()`` and ``session``). Invoking the
    callback once at the workflow's terminal step preserves Lab 4 Memory Bank turn
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
) -> Any | None:
    """Build ADK's ``GlobalInstructionPlugin`` for App-wide engineering guardrails.

    Applies consistent instructions across the coordinator and all subagents via
    ``App(plugins=[...])`` (replaces the deprecated ``LlmAgent.global_instruction``).
    Gracefully returns ``None`` if the installed ADK build does not expose
    ``GlobalInstructionPlugin``.
    """
    plugin_cls: Any | None = None
    try:
        from google.adk.plugins.global_instruction_plugin import GlobalInstructionPlugin

        plugin_cls = GlobalInstructionPlugin
    except ImportError:
        try:
            from google.adk.plugins import GlobalInstructionPlugin

            plugin_cls = GlobalInstructionPlugin
        except ImportError as exc:
            logger.debug("GlobalInstructionPlugin unavailable (%s); skipping plugin.", exc)
            return None

    return plugin_cls(global_instruction=global_instruction, name=name)


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
) -> CheckOutcome:
    """Run a deterministic verification CLI inside the local workspace.

    IMPORTANT (ADK 2.0 Retry & HITL semantics):
    - Never swallow ``Exception`` or ``BaseException``. The ``except BaseException``
      block around ``proc.communicate()`` only kills and reaps the child subprocess
      if ADK's ``@node(..., timeout=...)`` cancels the coroutine mid-execution, then
      immediately re-raises so ``asyncio.CancelledError``, ``TimeoutError``,
      ``NodeTimeoutError``, and ``NodeInterruptedError`` propagate unmodified to
      ADK's retry/HITL runtime.
    """
    if settings.sandbox_mode != "local":
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
    _require_adk_v2()
    from google.adk.agents import LlmAgent
    from google.genai import types

    implementer_kwargs: dict[str, Any] = {
        "name": "code_implementer",
        "mode": "single_turn",  # ADK 2.0: subagent only; no user interaction, automatic return
        "model": _build_gemini_model(settings),
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
        "generate_content_config": types.GenerateContentConfig(temperature=0.2),
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
        model=_build_gemini_model(settings),
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
        generate_content_config=types.GenerateContentConfig(temperature=0.1),
    )

    # ADK 2.0 constraint: `mode="task"` agents MUST be leaf agents (cannot declare `sub_agents`)
    # and are disabled inside ADK Python v2.0.0 graph-based `Workflow` definitions.
    requirements_clarifier = LlmAgent(
        name="requirements_clarifier",
        mode="task",  # Can ask clarifying questions; returns to coordinator via `finish_task`
        model=_build_gemini_model(settings),
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
        generate_content_config=types.GenerateContentConfig(temperature=0.2),
    )

    # CRITICAL (ADK 2.0): NEVER configure `mode` on the root coordinator agent.
    coordinator_kwargs: dict[str, Any] = {
        "name": "coding_agent",
        "model": _build_gemini_model(settings),
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
        "generate_content_config": types.GenerateContentConfig(temperature=0.2),
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
    adk_v2 = _require_adk_v2()
    from google.adk.agents import LlmAgent
    from google.genai import types

    coder_kwargs: dict[str, Any] = {
        "name": "coder_agent",
        "model": _build_gemini_model(settings),
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
        "generate_content_config": types.GenerateContentConfig(temperature=0.2),
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

    check_retry_config = adk_v2.RetryConfig(
        max_attempts=3,
        initial_delay=1.0,
        exceptions=[TimeoutError, adk_v2.NodeTimeoutError],
    )

    @adk_v2.node(
        name="run_pytest_node",
        retry_config=check_retry_config,
        timeout=30.0,
    )
    async def run_pytest_node(ctx: Context, node_input: Any = None) -> CheckOutcome:
        """Deterministic pytest verification node with automatic transient retries."""
        del ctx, node_input
        return await _run_workspace_check(
            settings,
            check_name="pytest",
            command=_pytest_command(),
            allow_exit_codes=frozenset({0, 5}),
            empty_exit_code_message="No pytest tests collected in workspace.",
        )

    @adk_v2.node(
        name="run_ruff_node",
        retry_config=check_retry_config,
        timeout=30.0,
    )
    async def run_ruff_node(ctx: Context, node_input: Any = None) -> CheckOutcome:
        """Deterministic ruff lint verification node with automatic transient retries."""
        del ctx, node_input
        return await _run_workspace_check(
            settings,
            check_name="ruff",
            command=_ruff_command(),
            allow_exit_codes=frozenset({0}),
            empty_exit_code_message="ruff check passed with zero violations.",
        )

    verify_join = adk_v2.JoinNode(name="verify_join")

    @adk_v2.node(name="verdict_router")
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
            return adk_v2.Event(
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
        return adk_v2.Event(
            route=route_key,
            output=summary_payload,
            state={
                "fix_attempts": fix_attempts,
                "latest_findings": findings,
                "checks_passed": all_passed,
            },
        )

    @adk_v2.node(name="request_human_approval", rerun_on_resume=False)
    async def request_human_approval(ctx: Context, node_input: Any):
        """Pause the graph workflow for structured human approval before finalizing."""
        del ctx
        yield adk_v2.RequestInput(
            message=(
                "Verification completed. Review the summary payload and respond with an "
                "ApprovalDecision (`approved`: bool, `reviewer_notes`: str) to continue."
            ),
            payload=node_input,
            response_schema=ApprovalDecision,
        )

    @adk_v2.node(name="finalize_report")
    async def finalize_report(
        ctx: Context,
        node_input: Any,
        fix_attempts: int = 0,
        latest_findings: str = "",
    ) -> Any:
        """Single terminal node emitting strictly ONE Event and resetting turn state."""
        approval_note = _format_approval_note(node_input) if settings.enable_hitl_approval else ""

        report = _build_final_report(
            code_summary="",
            findings=latest_findings,
            fix_attempts=fix_attempts,
            approval_note=approval_note,
        )
        await _invoke_optional_after_agent_callback(callbacks, ctx)
        # Reset per-turn workflow state on terminal completion so multi-turn sessions
        # start Turn 2+ fresh at `fix_attempts=0` while preserving state across HITL pauses.
        return adk_v2.Event(
            message=report,
            output=report,
            state={
                "fix_attempts": 0,
                "latest_findings": "",
            },
        )

    return adk_v2.Workflow(
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
    adk_v2 = _require_adk_v2()
    from google.adk.agents import LlmAgent
    from google.genai import types

    coder_kwargs: dict[str, Any] = {
        "name": "coder_agent",
        "model": _build_gemini_model(settings),
        "description": "Generates and edits workspace code for the user request.",
        "instruction": (
            "You are the Coding Generator agent. Inspect existing workspace files, "
            "implement the requested changes surgically with your tools, and summarize "
            "the modified files."
        ),
        "tools": list(tools),
        "generate_content_config": types.GenerateContentConfig(temperature=0.2),
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
        "model": _build_gemini_model(settings),
        "description": "Refactors workspace code based on pytest and ruff findings.",
        "instruction": (
            "Refactor the current workspace implementation to fix all verification findings.\n\n"
            "Previous implementation summary:\n{code}\n\n"
            "Pytest & ruff findings:\n{findings}\n\n"
            "Apply minimal surgical edits with your tools and summarize the fixes."
        ),
        "tools": list(tools),
        "generate_content_config": types.GenerateContentConfig(temperature=0.2),
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

    check_retry_config = adk_v2.RetryConfig(
        max_attempts=3,
        initial_delay=1.0,
        exceptions=[TimeoutError, adk_v2.NodeTimeoutError],
    )

    @adk_v2.node(
        name="run_pytest_node",
        retry_config=check_retry_config,
        timeout=30.0,
    )
    async def run_pytest_node(ctx: Context, node_input: Any = None) -> CheckOutcome:
        """Run pytest inside the active workspace."""
        del ctx, node_input
        return await _run_workspace_check(
            settings,
            check_name="pytest",
            command=_pytest_command(),
            allow_exit_codes=frozenset({0, 5}),
            empty_exit_code_message="No pytest tests collected in workspace.",
        )

    @adk_v2.node(
        name="run_ruff_node",
        retry_config=check_retry_config,
        timeout=30.0,
    )
    async def run_ruff_node(ctx: Context, node_input: Any = None) -> CheckOutcome:
        """Run ruff check inside the active workspace."""
        del ctx, node_input
        return await _run_workspace_check(
            settings,
            check_name="ruff",
            command=_ruff_command(),
            allow_exit_codes=frozenset({0}),
            empty_exit_code_message="ruff check passed with zero violations.",
        )

    @adk_v2.node(name="request_human_approval", rerun_on_resume=False)
    async def request_human_approval(ctx: Context, node_input: Any):
        """Leaf HITL node pausing for structured ApprovalDecision."""
        del ctx
        yield adk_v2.RequestInput(
            message=(
                "Dynamic coding workflow completed automated checks. Submit an "
                "ApprovalDecision (`approved`: bool, `reviewer_notes`: str) to finalize."
            ),
            payload=node_input,
            response_schema=ApprovalDecision,
        )

    @adk_v2.node(name="dynamic_coding_workflow", rerun_on_resume=True)
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
            yield adk_v2.Event(
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
        yield adk_v2.Event(
            message=final_report,
            output=final_report,
            state={
                "code": "",
                "findings": "",
                "fix_attempts": 0,
            },
        )

    return adk_v2.Workflow(
        name="coding_agent",
        description=(
            "ADK 2.0 dynamic programmatic workflow using @node(rerun_on_resume=True), "
            "ctx.run_node(), asyncio.gather(..., use_sub_branch=True), bounded fix "
            "iterations, and automatic HITL checkpointing."
        ),
        edges=[("START", dynamic_coding_workflow)],
    )


def build_optional_managed_agent(
    agent_id: str | None = None,
    settings: Settings | None = None,
) -> Any:
    """Build an optional ADK Python v2.4.0 Preview ``ManagedAgent`` reference subagent.

    Connects to a Google-hosted first-party managed agent (for example,
    ``antigravity-preview-05-2026``) via the Managed Agents / Interactions API.
    With ``mode="single_turn"``, it can be added directly to a parent coordinator
    ``LlmAgent.sub_agents`` as an inline tool (recommended over ``AgentTool``).

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
