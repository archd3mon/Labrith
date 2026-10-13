"""
Routing guards for the LangGraph supervisor.

Enforces iteration limits (per-task and per-run) and provides the conditional
edge function used by graph.py to route from the planner node.

Design Doc §4: "Iteration limits are enforced in graph/routing.py. When
exhausted, the planner escalates and records the issue as unresolved."
AGENTS.md: "Iteration limits are enforced in graph/routing.py."

Public API:
    check_limits(state, trace_writer) -> None   raises LimitExceeded
    route_decision(state)             -> str    conditional edge function
"""

from __future__ import annotations

from typing import Optional

from graph.state import GraphState, UnresolvedIssue
from lib.trace import TraceWriter

# ---------------------------------------------------------------------------
# Defaults (overridden by state.request.max_iterations for per-task limit)
# ---------------------------------------------------------------------------
DEFAULT_MAX_TASK_ITERATIONS: int = 3
DEFAULT_MAX_RUN_ITERATIONS: int = 15


class LimitExceeded(Exception):
    """Raised when an iteration limit is hit."""


# ---------------------------------------------------------------------------
# Limit guard
# ---------------------------------------------------------------------------

def check_limits(
    state: GraphState,
    *,
    max_task_iterations: Optional[int] = None,
    max_run_iterations: Optional[int] = None,
    trace_writer: Optional[TraceWriter] = None,
) -> None:
    """Check iteration limits and raise LimitExceeded if any are hit.

    Per-task limit comes from state.request.max_iterations (configurable per
    run) and defaults to DEFAULT_MAX_TASK_ITERATIONS.

    Per-run limit defaults to DEFAULT_MAX_RUN_ITERATIONS and can be
    overridden via the max_run_iterations parameter.

    When a limit is exceeded this function:
    1. Appends an UnresolvedIssue to state (mutating the list in place so
       the caller can persist it).
    2. Writes an escalation event to the trace.
    3. Raises LimitExceeded (the planner catches this and returns "escalate").
    """
    per_task_limit = (
        max_task_iterations
        if max_task_iterations is not None
        else (state.request.max_iterations if state.request else DEFAULT_MAX_TASK_ITERATIONS)
    )
    run_limit = (
        max_run_iterations
        if max_run_iterations is not None
        else DEFAULT_MAX_RUN_ITERATIONS
    )

    # ---- Run-total limit --------------------------------------------------
    run_total = state.iteration_counters.get("run_total", 0)
    if run_total >= run_limit:
        issue_text = (
            f"Run iteration limit reached ({run_total} >= {run_limit}). "
            "Stopping to avoid infinite loop."
        )
        _record_unresolved(state, issue_text, "planner", trace_writer)
        raise LimitExceeded(issue_text)

    # ---- Per-task limits --------------------------------------------------
    for task in (state.plan or []):
        task_count = state.iteration_counters.get(task.task_id, 0)
        if task_count >= per_task_limit and task.status not in ("done", "escalated"):
            issue_text = (
                f"Task {task.task_id} ({task.assigned_agent}) exceeded iteration limit "
                f"({task_count} >= {per_task_limit})."
            )
            _record_unresolved(state, issue_text, task.assigned_agent or "planner", trace_writer)
            raise LimitExceeded(issue_text)


# ---------------------------------------------------------------------------
# Conditional edge function (read-only — called by LangGraph after planner)
# ---------------------------------------------------------------------------

def route_decision(state: GraphState) -> str:
    """Conditional edge function: read _next_agent from state and return it.

    The planner node stores its decision in
    state.iteration_counters["_next_agent"] so LangGraph's conditional edge
    can route without calling any LLM itself.

    Falls back to "escalate" if the key is missing or invalid.
    """
    _VALID = {"designer", "engineer", "integration", "qa", "critic", "finish", "escalate"}
    decision = state.iteration_counters.get("_next_agent", "escalate")
    if decision not in _VALID:
        return "escalate"
    return decision


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _record_unresolved(
    state: GraphState,
    issue: str,
    agent: str,
    trace_writer: Optional[TraceWriter],
) -> None:
    """Append an UnresolvedIssue to state and write to trace."""
    unresolved_issue = UnresolvedIssue(
        issue=issue,
        evidence="iteration_counters",
        agent=agent,
    )
    # Mutate in place so the planner's return dict can snapshot it
    state.unresolved.append(unresolved_issue)

    if trace_writer:
        trace_writer.write(
            "planner",
            "limit_exceeded",
            {"issue": issue, "agent": agent},
        )
