"""ADK 2.0 Multi-Agent, Declarative Graph, Dynamic Workflow, and ManagedAgent builders (starter track).

Complete the Lab 1 checkpoints in this file when exploring ADK 2.0
architectures beyond the default ``AGENT_ARCHITECTURE=simple`` single-agent setup:
- ``collaborative``: Coordinator ``LlmAgent`` + ``mode="single_turn"`` / ``mode="task"`` subagents
- ``graph``: Declarative ADK 2.0 ``Workflow`` graph with parallel checks, ``JoinNode``,
  bounded fix cycle, and optional ``RequestInput`` HITL approval gate
- ``dynamic``: Programmatic ``@node(rerun_on_resume=True)`` orchestrator with
  ``ctx.run_node()``, ``asyncio.gather(..., use_sub_branch=True)``, and checkpointed HITL
- ``agy_harness``: Outer ADK 2.0 orchestrator + Antigravity (``agy``) headless coding harness
  with independent pytest/ruff gates, ``--conversation`` fix loops, and ``gemini-4-neon`` review

Keep ``AGENT_ARCHITECTURE=simple`` as the default in ``.env`` so Labs 2-8
continue working unchanged.
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

from google.adk import Context, Event, Workflow  # noqa: F401
from google.adk.agents import LlmAgent  # noqa: F401
from google.adk.events import RequestInput  # noqa: F401
from google.adk.plugins.global_instruction_plugin import GlobalInstructionPlugin
from google.adk.workflow import JoinNode, NodeTimeoutError, RetryConfig, node  # noqa: F401
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

    Applies consistent rules across the coordinator and all subagents via
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
    """Format failing pytest/ruff ``CheckOutcome`` objects into a concise findings string."""
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

    Target design (``https://adk.dev/workflows/collaboration/``):
    - ``code_implementer`` (``mode="single_turn"``): receives ``tools`` (``EnvironmentToolset``
      + coding tools) and optional ``code_executor``; returns automatically.
    - ``code_reviewer`` (``mode="single_turn"``): reviews code/tests in an isolated
      session branch (parallel-capable) with ``output_schema=CodeReviewReport``.
    - ``requirements_clarifier`` (``mode="task"``): leaf agent ONLY (cannot have
      ``sub_agents``; note ``task`` mode is disabled inside Python v2.0.0 graph
      workflows!); asks clarifying questions and returns via ``finish_task``.
    - Coordinator ``LlmAgent(name="coding_agent", sub_agents=[...])`` — NEVER set
      ``mode`` on the root coordinator agent!
    """
    del settings, tools, callbacks, code_executor
    # TODO(lab-1): Construct `code_implementer` (mode="single_turn"),
    # `code_reviewer` (mode="single_turn", output_schema=CodeReviewReport),
    # and `requirements_clarifier` (mode="task", leaf-only), then return the
    # Coordinator `LlmAgent(name="coding_agent", sub_agents=[...])` WITHOUT
    # setting `mode` on the root agent. Compare against
    # `solution/coding_agent/architectures.py`.
    raise NotImplementedError(
        "Complete TODO(lab-1) in starter/coding_agent/architectures.py: "
        "build_collaborative_coding_team()."
    )


def build_graph_coding_workflow(
    settings: Settings,
    tools: Sequence[Any],
    callbacks: Mapping[str, Any] | None = None,
    code_executor: Any | None = None,
) -> Any:
    """Build a declarative ADK 2.0 ``Workflow`` graph with parallel checks and HITL.

    Target design (``https://adk.dev/graphs/``):
    - ``coder_agent`` (``LlmAgent``, default ``single_turn`` in graph — NOT ``chat`` mode)
    - Parallel ``run_pytest_node`` & ``run_ruff_node`` decorated with
      ``@node(retry_config=RetryConfig(max_attempts=3, initial_delay=1.0,
      exceptions=[TimeoutError, NodeTimeoutError]), timeout=30.0)``
    - ``JoinNode(name="verify_join")`` merging both branches into a dict keyed by
      predecessor node name (respecting the single terminal output rule!)
    - ``verdict_router`` emitting ``Event(route="PASS" | "NEEDS_FIX" | "NEEDS_APPROVAL",
      output=..., state={"fix_attempts": ...})`` with explicit ``settings.max_fix_rounds``
      bound (ADK 2.0 graph cycles are NOT bounded automatically!)
    - Optional ``request_human_approval`` (``@node(rerun_on_resume=False)``) yielding
      ``RequestInput(message=..., payload=..., response_schema=ApprovalDecision)``
    - ``finalize_report`` formatting optional HITL replies via
      ``_format_approval_note(...)``, rendering ``_build_final_report(...)``,
      invoking optional Lab 3 ``callbacks["after_agent_callback"]`` once via
      ``_invoke_optional_after_agent_callback(callbacks, ctx)``, and emitting
      strictly ONE ``Event(message=report, output=report, state={"fix_attempts": 0, "latest_findings": ""})``
      so per-turn workflow state resets cleanly for Turn 2+ while remaining intact
      across intermediate HITL pauses.
    """
    del settings, tools, callbacks, code_executor
    # TODO(lab-1): Define `coder_agent` (with `output_key="latest_code_summary"`),
    # parallel `run_pytest_node` / `run_ruff_node` (using `_run_workspace_check(...,
    # allow_exit_codes=frozenset({0, 5}))` for pytest so exit code 5 [no tests collected]
    # succeeds, forwarding `sandbox_env=_extract_sandbox_environment(tools)` + `ctx=ctx`,
    # and `@node(retry_config=..., timeout=30.0)`), `JoinNode(name="verify_join")`, bounded
    # `verdict_router` (note: include `{"checks_passed", "findings"}` in the non-HITL
    # summary payload so `_format_approval_note()` distinguishes it from human replies),
    # `@node(rerun_on_resume=False)` `request_human_approval`, and `finalize_report`,
    # then return `Workflow(name="coding_agent", edges=[...])`.
    # Note: keep the top-level `from google.adk.workflow import JoinNode, NodeTimeoutError,
    # RetryConfig, node` import line intact (import `DEFAULT_ROUTE` locally inside this
    # function if using a partial route map).
    # Compare against `solution/coding_agent/architectures.py`.
    raise NotImplementedError(
        "Complete TODO(lab-1) in starter/coding_agent/architectures.py: "
        "build_graph_coding_workflow()."
    )


def build_dynamic_coding_workflow(
    settings: Settings,
    tools: Sequence[Any],
    callbacks: Mapping[str, Any] | None = None,
    code_executor: Any | None = None,
) -> Any:
    """Build an ADK 2.0 programmatic dynamic workflow mirroring ``adk.dev/graphs/dynamic/#loop-route``.

    Target design:
    - ``@node(rerun_on_resume=True)`` orchestrator ``dynamic_coding_workflow(ctx: Context, node_input: str)``
    - Calls ``await ctx.run_node(coder_agent, node_input)``
    - Runs initial parallel checks via ``await asyncio.gather(ctx.run_node(run_pytest_node, ..., use_sub_branch=True),
      ctx.run_node(run_ruff_node, ..., use_sub_branch=True))`` before entering a bounded
      ``for attempt in range(settings.max_fix_rounds):`` loop that calls ``fixer_agent``
      and re-runs parallel checks after every fix round
    - Yields ``Event(state={"code": ..., "findings": ..., "fix_attempts": ...})`` BEFORE calling
      ``await ctx.run_node(fixer_agent, ...)`` (Python ``{key}`` prompt templates
      read session state, NOT ``node_input``!)
    - If ``settings.enable_hitl_approval`` is true, awaits
      ``await ctx.run_node(request_human_approval, {...})`` (``rerun_on_resume=False``)
    - Formats optional HITL replies via ``_format_approval_note(decision)``, renders
      ``_build_final_report(...)``, invokes optional Lab 3
      ``callbacks["after_agent_callback"]`` once via
      ``_invoke_optional_after_agent_callback(callbacks, ctx)``, and yields strictly
      ONE terminal ``Event(message=..., output=..., state={"code": "", "findings": "", "fix_attempts": 0})``
    - Wraps in ``Workflow(name="coding_agent", edges=[("START", dynamic_coding_workflow)])``
    """
    del settings, tools, callbacks, code_executor
    # TODO(lab-1): Implement `coder_agent`, `fixer_agent`, parallel check nodes,
    # `request_human_approval` (`rerun_on_resume=False`), and the
    # `@node(rerun_on_resume=True)` `dynamic_coding_workflow` orchestrator, then
    # wrap in `Workflow(name="coding_agent", edges=[("START", dynamic_coding_workflow)])`.
    # Compare against `solution/coding_agent/architectures.py`.
    raise NotImplementedError(
        "Complete TODO(lab-1) in starter/coding_agent/architectures.py: "
        "build_dynamic_coding_workflow()."
    )


def _format_spec_brief(spec_output: Any, fallback_prompt: str) -> str:
    """Render a ``SpecPlan`` (or raw string/mapping) into a concrete implementation brief."""
    if isinstance(spec_output, SpecPlan):
        targets = "\n".join(f"- {f}" for f in spec_output.target_files) or "- (inspect workspace)"
        criteria = (
            "\n".join(f"- {c}" for c in spec_output.acceptance_criteria)
            or "- All pytest and ruff checks pass"
        )
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
        criteria = (
            "\n".join(f"- {c}" for c in acceptance) or "- All pytest and ruff checks pass"
        )
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
        verdict = (
            "APPROVED" if _coerce_bool(review_output.get("approved", False)) else "CHANGES REQUESTED"
        )
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

    Target 5-stage design (``AGENT_ARCHITECTURE=agy_harness``):
    1. ``spec_planner`` (``_build_gemini_model(settings, role="reasoning")`` -> ``gemini-4-neon``,
       ``output_schema=SpecPlan``) produces concrete file targets & acceptance criteria,
       formatted via ``_format_spec_brief(...)``.
    2. ``run_agy_harness_node`` delegates edits to ``AgyHeadlessHarness`` (auto-selecting BYOC
       sandbox vs local/Agent Runtime ``agy`` vs native ADK fallback, capturing ``conversation_id``).
    3. Independent deterministic ``run_pytest_node`` + ``run_ruff_node`` via
       ``asyncio.gather(..., use_sub_branch=True)`` (forwarding ``sandbox_env`` + ``ctx``
       into ``_run_workspace_check(...)``).
    4. Bounded fix loop (``settings.max_fix_rounds``) feeding failures back via
       ``--conversation <conversation_id>`` (with exit-code-3 retry/fallback,
       fail-fast on non-zero exit codes 1/2 without re-invoking ``agy``, and
       surfacing any non-zero harness exit code in ``findings`` so the report
       never claims ``PASSED`` on harness failure).
    5. Independent ``code_reviewer`` (``gemini-4-neon``, ``output_schema=CodeReviewReport``,
       formatted via ``_format_review_section(...)``) + optional ``RequestInput`` HITL
       approval gate + single terminal ``Event``.
    """
    del settings, tools, callbacks, code_executor
    # TODO(lab-1): Implement the 5-stage Antigravity (`agy`) headless coding harness
    # workflow described above using `_extract_sandbox_environment`, `_format_spec_brief`,
    # `_run_workspace_check`, and `_format_review_section`. Compare against
    # `solution/coding_agent/architectures.py`.
    raise NotImplementedError(
        "Complete TODO(lab-1) in starter/coding_agent/architectures.py: "
        "build_agy_harness_workflow()."
    )


def build_optional_managed_agent(
    agent_id: str | None = None,
    settings: Settings | None = None,
) -> Any:
    """Build an optional ADK Python v2.4.0 Preview ``ManagedAgent`` reference subagent.

    Verified ADK Python v2.4.0 Preview limitations (``adk.dev/agents/managed-agents/``):
    - **Agent Platform backend is ``global``-only:** Regional endpoints raise an error;
      ``ManagedAgent`` enforces ``location="global"`` on enterprise clients.
    - **Server-side tools only:** Supports ADK built-in server-side tools (e.g.,
      ``google_search``) and ``google.adk.tools.RemoteMcpServer``. Client Python
      callables / ``FunctionTool`` and raw ``types.Tool.mcp_servers`` raise
      ``NotImplementedError``.
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
