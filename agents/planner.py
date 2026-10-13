"""
Planner — supervisor agent.

Responsibilities (Design Doc §3 & §4):
- Initialise the task plan on the first call.
- After every worker handoff: validate the proof-of-work and decide the next
  agent based on current state.
- Enforce per-task and per-run iteration limits (graph/routing.py).
- Escalate when limits are exhausted; add unresolved issues.
- Write every routing decision and proof-validation event to the trace.

This slice uses a scripted fake LLM via lib.llm.  The real LLM call is a
drop-in replacement: swap set_fake_llm_handler() with a real model config.

Public API:
    run_planner(state, trace_writer) -> dict   (LangGraph node function)
"""

from __future__ import annotations

import json
from typing import Optional

from graph.state import GraphState, TaskDefinition, UnresolvedIssue
from lib.llm import complete
from lib.proofs import validate_proof
from lib.trace import TraceWriter

# ---------------------------------------------------------------------------
# Decide helper — separated so it can be unit-tested independently
# ---------------------------------------------------------------------------

_VALID_DECISIONS = {"designer", "engineer", "integration", "qa", "critic", "finish", "escalate"}


def decide(state: GraphState, trace_writer: Optional[TraceWriter] = None) -> str:
    """Evaluate state and return the next routing decision.

    Decision logic (in priority order):
    1. If run is already terminal, return "finish" / "escalate" immediately.
    2. If a pending-proof rejection is queued on state, re-route to same agent.
    3. Enforce iteration limits via graph.routing guards.
    4. Ask the LLM (or fake) for the next step; guard deterministically.

    Returns one of: "designer" | "engineer" | "integration" | "qa" |
                    "critic" | "finish" | "escalate"
    """
    from graph.routing import check_limits, LimitExceeded  # local to avoid circular

    # ---- 1. Already terminal -----------------------------------------------
    if state.status in ("accepted", "partial", "failed"):
        return "finish" if state.status == "accepted" else "escalate"

    # ---- 2. Proof-rejection re-route (last_rejected_agent on state) --------
    last_rejected = (state.iteration_counters or {}).get("_last_rejected_agent")
    if last_rejected:
        if trace_writer:
            trace_writer.write(
                "planner",
                "routing_decision",
                {
                    "next_agent": last_rejected,
                    "reason": "re-routing after proof rejection",
                },
            )
        return last_rejected

    # ---- 3. Iteration-limit guard ------------------------------------------
    try:
        check_limits(state, trace_writer=trace_writer)
    except LimitExceeded as exc:
        if trace_writer:
            trace_writer.write(
                "planner",
                "escalate",
                {"reason": str(exc)},
            )
        return "escalate"

    # ---- 4. LLM-driven decision --------------------------------------------
    prompt = _build_decision_prompt(state)
    raw = complete(
        "planner",
        [{"role": "user", "content": prompt}],
    )

    decision = _parse_decision(raw)

    if trace_writer:
        trace_writer.write(
            "planner",
            "routing_decision",
            {"next_agent": decision, "llm_raw": raw},
        )

    return decision


# ---------------------------------------------------------------------------
# LangGraph node function
# ---------------------------------------------------------------------------

def run_planner(
    state: GraphState,
    trace_writer: Optional[TraceWriter] = None,
) -> dict:
    """LangGraph node for the planner / supervisor.

    On first call (no plan), initialises a minimal stub plan.
    Validates the most-recent proof-of-work received from a worker.
    Then calls decide() and stores the result in iteration_counters so the
    routing edge in graph.py can read it.
    """
    updates: dict = {}

    # ---- Initialise plan if empty -----------------------------------------
    if not state.plan:
        stub_plan = _make_stub_plan(state)
        updates["plan"] = stub_plan
        # Apply plan to state for this call (routing uses it)
        state = state.model_copy(update={"plan": stub_plan})
        if trace_writer:
            trace_writer.write(
                "planner",
                "plan_created",
                {"tasks": [t.task_id for t in stub_plan]},
            )

    # ---- Validate latest proof from state.proofs --------------------------
    if state.proofs:
        latest_proof = state.proofs[-1]
        valid, errors = validate_proof(latest_proof)
        if not valid:
            # Mark rejection and add unresolved if it keeps failing
            if trace_writer:
                trace_writer.write(
                    "planner",
                    "proof_rejected",
                    {"agent": str(latest_proof.agent), "errors": errors},
                )
            # Record which agent we must re-route to
            counters = dict(state.iteration_counters)
            rejected_agent = str(latest_proof.agent.value if hasattr(latest_proof.agent, "value") else latest_proof.agent)
            counters["_last_rejected_agent"] = rejected_agent
            updates["iteration_counters"] = counters
            state = state.model_copy(update={"iteration_counters": counters})
        else:
            # Clear any lingering rejection flag
            if "_last_rejected_agent" in state.iteration_counters:
                counters = dict(state.iteration_counters)
                counters.pop("_last_rejected_agent", None)
                updates["iteration_counters"] = counters
                state = state.model_copy(update={"iteration_counters": counters})
            if trace_writer:
                trace_writer.write(
                    "planner",
                    "proof_accepted",
                    {"agent": str(latest_proof.agent), "task_id": latest_proof.task_id},
                )

    # ---- Increment run-total counter --------------------------------------
    counters = dict(state.iteration_counters)
    counters["run_total"] = counters.get("run_total", 0) + 1
    updates["iteration_counters"] = counters
    state = state.model_copy(update={"iteration_counters": counters})

    # ---- Get routing decision ---------------------------------------------
    next_agent = decide(state, trace_writer=trace_writer)

    # Store decision for conditional edge to read
    counters["_next_agent"] = next_agent
    updates["iteration_counters"] = counters

    # ---- Update status if accepting/escalating ----------------------------
    if next_agent == "finish" and state.status not in ("accepted", "partial", "failed"):
        updates["status"] = "accepted"
        if trace_writer:
            trace_writer.write("planner", "run_accepted", {})
    elif next_agent == "escalate":
        updates["status"] = "partial"

    return updates


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _make_stub_plan(state: GraphState) -> list[TaskDefinition]:
    """Create a minimal stub task plan from the input request."""
    return [
        TaskDefinition(
            task_id="T-01",
            description="Design the UI layout and component inventory",
            assigned_agent="designer",
            status="pending",
        ),
        TaskDefinition(
            task_id="T-02",
            description="Implement React components",
            assigned_agent="engineer",
            status="pending",
            depends_on=["T-01"],
        ),
        TaskDefinition(
            task_id="T-03",
            description="Integrate components with the API",
            assigned_agent="integration",
            status="pending",
            depends_on=["T-02"],
        ),
        TaskDefinition(
            task_id="T-04",
            description="Run QA browser flows",
            assigned_agent="qa",
            status="pending",
            depends_on=["T-03"],
        ),
        TaskDefinition(
            task_id="T-05",
            description="Accessibility and design critique",
            assigned_agent="critic",
            status="pending",
            depends_on=["T-04"],
        ),
    ]


def _build_decision_prompt(state: GraphState) -> str:
    """Build a prompt summarising state for the LLM to reason over."""
    done_agents = {p.agent for p in state.proofs}
    pending_tasks = [
        t for t in (state.plan or []) if t.status in ("pending", "failed")
    ]
    return json.dumps(
        {
            "instruction": (
                "You are the planner. Based on the state below, choose the next agent. "
                "Reply with exactly one of: designer, engineer, integration, qa, critic, "
                "finish, escalate. Nothing else."
            ),
            "status": state.status,
            "agents_with_accepted_proofs": [str(a) for a in done_agents],
            "pending_tasks": [
                {"task_id": t.task_id, "agent": t.assigned_agent, "status": t.status}
                for t in pending_tasks
            ],
            "unresolved_count": len(state.unresolved),
            "run_total_iterations": state.iteration_counters.get("run_total", 0),
        }
    )


def _parse_decision(raw: str) -> str:
    """Extract a valid decision keyword from the LLM response."""
    cleaned = raw.strip().lower().rstrip(".")
    # The fake/real LLM may return exactly the keyword or embed it
    for keyword in _VALID_DECISIONS:
        if keyword in cleaned:
            return keyword
    # Fallback: if response is gibberish, escalate
    return "escalate"
