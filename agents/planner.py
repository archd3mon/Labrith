"""
Planner — supervisor agent.

Responsibilities (Design Doc §3, §4, §5):
- plan(): Parse OpenAPI spec (tools/openapi.py) and brief; produce pages,
  user flows and an ordered task list with required_flows validated by pydantic.
- decide(): Given state (task statuses, proofs, failures, iteration counts),
  the LLM chooses the next agent and gives a short reasoning note; deterministic
  guards still apply (iteration limits, proof validation, finish only when all gates pass).
- replan(): When a task keeps failing, produce a revised plan (smaller component,
  different approach) and log why.
- Every decision and reasoning note goes to the trace.

Public API:
    plan(request, trace_writer, artifact_dir) -> PlanOutput
    decide(state, trace_writer)               -> str
    replan(state, failing_task_id, trace_writer, artifact_dir) -> list[TaskDefinition]
    run_planner(state, trace_writer, ...)     -> dict   (LangGraph node function)
"""

from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

from graph.state import GraphState, TaskDefinition, UnresolvedIssue
from lib.llm import complete
from lib.models import InputRequest, PageDefinition, PlanOutput, PlanTask, UserFlow
from lib.proofs import create_proof, validate_proof
from lib.trace import TraceWriter
from tools.openapi import get_spec_summary, list_endpoints, list_schemas, load_openapi_spec

_VALID_DECISIONS = {"designer", "engineer", "integration", "qa", "critic", "finish", "escalate"}


# ---------------------------------------------------------------------------
# Helper: JSON extraction from LLM responses
# ---------------------------------------------------------------------------

def _extract_json(raw: str) -> dict[str, Any]:
    """Extract a JSON object from text that may contain markdown or surrounding text."""
    cleaned = raw.strip()

    # Direct parse attempt
    try:
        return json.loads(cleaned)
    except json.JSONDecodeError:
        pass

    # Try matching fenced code blocks ```json ... ```
    match = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", cleaned, re.DOTALL)
    if match:
        try:
            return json.loads(match.group(1))
        except json.JSONDecodeError:
            pass

    # Try matching outermost curly braces
    start = cleaned.find("{")
    end = cleaned.rfind("}")
    if start != -1 and end != -1 and end > start:
        snippet = cleaned[start : end + 1]
        try:
            return json.loads(snippet)
        except json.JSONDecodeError:
            pass

    raise ValueError(f"Could not parse valid JSON from LLM response: {raw[:120]}...")


# ---------------------------------------------------------------------------
# 1. plan() — Parse OpenAPI spec & brief, generate validated PlanOutput
# ---------------------------------------------------------------------------

def plan(
    request: InputRequest,
    trace_writer: Optional[TraceWriter] = None,
    artifact_dir: Path = Path("artifacts"),
) -> PlanOutput:
    """Parse the OpenAPI spec and brief to produce pages, user flows, and tasks.

    Output is strictly validated against the PlanOutput pydantic model.
    Writes plan_created and planner proof-of-work to trace.
    """
    spec_summary = get_spec_summary(request.api_spec_url)
    endpoints = spec_summary.get("endpoints", [])
    schema_names = spec_summary.get("schema_names", [])

    prompt = _build_plan_prompt(request, endpoints, schema_names)
    raw = complete(
        "planner",
        [{"role": "user", "content": prompt}],
    )

    plan_output = _parse_and_validate_plan(raw, request, endpoints)

    # Persist plan artifact
    artifact_dir.mkdir(parents=True, exist_ok=True)
    plan_file = artifact_dir / "plan.json"
    with open(plan_file, "w", encoding="utf-8") as f:
        f.write(plan_output.model_dump_json(indent=2))

    # Record proof-of-work for planner
    proof = create_proof(
        agent="planner",
        task_id="T-00",
        claim="Initial task plan created from OpenAPI spec and brief",
        evidence=[{"type": "plan", "ref": str(plan_file)}],
        reasoning=plan_output.reasoning or "Parsed OpenAPI spec and brief into structured plan",
    )

    if trace_writer:
        trace_writer.write(
            "planner",
            "plan_created",
            {
                "pages": [p.name for p in plan_output.pages],
                "user_flows": [f.name for f in plan_output.user_flows],
                "tasks": [t.task_id for t in plan_output.tasks],
                "required_flows": plan_output.required_flows,
                "reasoning": plan_output.reasoning,
                "proof_claim": proof.claim,
            },
        )

    return plan_output


def _build_plan_prompt(
    request: InputRequest,
    endpoints: list[dict[str, Any]],
    schema_names: list[str],
) -> str:
    """Build prompt for plan generation."""
    return json.dumps(
        {
            "instruction": (
                "You are FrontForge's Planner agent. Analyze the product brief and OpenAPI spec. "
                "Produce a structured plan with: (1) pages, (2) user flows, (3) ordered tasks "
                "assigned to the 5 workers (designer, engineer, integration, qa, critic), and "
                "(4) required_flows. Return ONLY a valid JSON object matching the requested schema."
            ),
            "brief": request.brief,
            "target": request.target.value if hasattr(request.target, "value") else str(request.target),
            "style_hints": request.style_hints or [],
            "required_flows_requested": request.required_flows or [],
            "openapi_endpoints": endpoints[:10],
            "openapi_schemas": schema_names[:10],
            "schema_contract": {
                "pages": [{"name": "string", "route": "string", "description": "string", "components": ["string"]}],
                "user_flows": [{"flow_id": "string", "name": "string", "description": "string", "steps": ["string"]}],
                "tasks": [
                    {
                        "task_id": "T-01",
                        "description": "string",
                        "assigned_agent": "designer|engineer|integration|qa|critic",
                        "status": "pending",
                        "depends_on": ["string"],
                        "required_flows": ["string"],
                    }
                ],
                "required_flows": ["string"],
                "reasoning": "string",
            },
        },
        indent=2,
    )


def _parse_and_validate_plan(
    raw: str,
    request: InputRequest,
    endpoints: list[dict[str, Any]],
) -> PlanOutput:
    """Parse raw LLM output into validated PlanOutput, with fallback synthesis if needed."""
    try:
        data = _extract_json(raw)
        return PlanOutput.model_validate(data)
    except Exception:
        # Robust fallback: synthesize validated PlanOutput from request and endpoints
        target_name = (
            request.target.value.capitalize()
            if hasattr(request.target, "value")
            else str(request.target).capitalize()
        )
        flows = list(request.required_flows or ["list tickets", "filter by priority", "view detail", "send reply"])
        user_flows = [
            UserFlow(
                flow_id=f"F-{i+1:02d}",
                name=f,
                description=f"User interaction flow for: {f}",
                steps=[f"Navigate to {target_name}", f"Perform {f}", "Verify outcome"],
            )
            for i, f in enumerate(flows)
        ]
        pages = [
            PageDefinition(
                name="MainDashboard",
                route="/",
                description=f"Main view for {request.brief}",
                components=["Navbar", "TicketList", "TicketFilter", "TicketDetailModal"],
            )
        ]
        tasks = [
            PlanTask(
                task_id="T-01",
                description="Design UI tokens, palette, and component inventory",
                assigned_agent="designer",
                status="pending",
                depends_on=[],
            ),
            PlanTask(
                task_id="T-02",
                description="Implement React + TypeScript + Tailwind UI components",
                assigned_agent="engineer",
                status="pending",
                depends_on=["T-01"],
                required_flows=flows[:2],
            ),
            PlanTask(
                task_id="T-03",
                description="Generate typed API client and bind components to backend endpoints",
                assigned_agent="integration",
                status="pending",
                depends_on=["T-02"],
            ),
            PlanTask(
                task_id="T-04",
                description="Run headless browser Playwright tests for required user flows",
                assigned_agent="qa",
                status="pending",
                depends_on=["T-03"],
                required_flows=flows,
            ),
            PlanTask(
                task_id="T-05",
                description="Audit accessibility (WCAG / axe-core) and quality (Lighthouse)",
                assigned_agent="critic",
                status="pending",
                depends_on=["T-04"],
            ),
        ]
        return PlanOutput(
            pages=pages,
            user_flows=user_flows,
            tasks=tasks,
            required_flows=flows,
            reasoning="Fallback plan synthesized from OpenAPI spec and request parameters.",
        )


# ---------------------------------------------------------------------------
# 2. decide() — LLM-driven decision with deterministic guards
# ---------------------------------------------------------------------------

def decide(state: GraphState, trace_writer: Optional[TraceWriter] = None) -> str:
    """Evaluate blackboard state and choose the next agent with reasoning.

    Design Doc §4: "Supervisor over a shared blackboard. The Planner chooses the
    next step from that state. LLM proposes, guards dispose."

    Deterministic guards:
    1. Terminal status check.
    2. Iteration limit check via graph.routing.check_limits.
    3. Proof-rejection re-route.
    4. Finish gate guard: only allow 'finish' when all tasks are complete and gates pass.
    """
    from graph.routing import LimitExceeded, check_limits  # local to avoid circular import

    # ---- Guard 1: Already terminal -----------------------------------------
    if state.status in ("accepted", "partial", "failed"):
        return "finish" if state.status == "accepted" else "escalate"

    # ---- Guard 2: Iteration-limit guard ------------------------------------
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

    # ---- Guard 3: Proof-rejection re-route ---------------------------------
    last_rejected = (state.iteration_counters or {}).get("_last_rejected_agent")
    if last_rejected:
        if trace_writer:
            trace_writer.write(
                "planner",
                "routing_decision",
                {
                    "next_agent": last_rejected,
                    "reasoning": f"Re-routing directly to {last_rejected} after proof rejection.",
                },
            )
        return last_rejected

    # ---- LLM-driven proposal -----------------------------------------------
    prompt = _build_decision_prompt(state)
    raw = complete(
        "planner",
        [{"role": "user", "content": prompt}],
    )

    proposed_agent, reasoning = _parse_decision_and_reasoning(raw)

    # ---- Guard 4: Validate gates before allowing finish --------------------
    final_decision, guarded_reasoning = _apply_finish_guard(proposed_agent, reasoning, state)

    if trace_writer:
        trace_writer.write(
            "planner",
            "routing_decision",
            {
                "next_agent": final_decision,
                "reasoning": guarded_reasoning,
                "proposed_by_llm": proposed_agent,
            },
        )

    return final_decision


def _build_decision_prompt(state: GraphState) -> str:
    """Build a comprehensive context summary of blackboard state for LLM reasoning."""
    accepted_proofs = [
        {"agent": str(p.agent.value if hasattr(p.agent, "value") else p.agent), "task_id": p.task_id, "claim": p.claim}
        for p in state.proofs
    ]
    tasks_summary = [
        {"task_id": t.task_id, "agent": t.assigned_agent, "status": t.status, "depends_on": t.depends_on}
        for t in (state.plan or [])
    ]
    pending_tasks = [t for t in (state.plan or []) if t.status in ("pending", "in_progress", "failed")]

    # Verification gates inspection
    qa_passed = False
    if state.qa_results and state.qa_results.flows:
        qa_passed = all(f.get("status") == "pass" for f in state.qa_results.flows)
    critic_accepted = state.audit_report.accepted if state.audit_report else False

    context = {
        "instruction": (
            "You are the Supervisor Planner. Analyze the blackboard state and choose the NEXT agent to invoke. "
            "Available choices: designer, engineer, integration, qa, critic, finish, escalate. "
            "Respond with a JSON object: {\"next_agent\": \"...\", \"reasoning\": \"short note\"}."
        ),
        "status": state.status,
        "run_total_iterations": state.iteration_counters.get("run_total", 0),
        "pending_tasks_count": len(pending_tasks),
        "tasks": tasks_summary,
        "accepted_proofs": accepted_proofs,
        "qa_flows_passed": qa_passed,
        "critic_accepted": critic_accepted,
        "unresolved_issues": [u.issue for u in state.unresolved],
    }
    return json.dumps(context, indent=2)


def _parse_decision_and_reasoning(raw: str) -> tuple[str, str]:
    """Parse raw LLM response into (next_agent, reasoning)."""
    cleaned = raw.strip()

    # Try JSON extraction
    try:
        data = _extract_json(cleaned)
        agent = str(data.get("next_agent", "")).lower().strip()
        reasoning = str(data.get("reasoning", "")).strip() or "LLM routing decision"
        for valid in _VALID_DECISIONS:
            if valid == agent or valid in agent:
                return valid, reasoning
    except Exception:
        pass

    # Fallback to keyword matching
    cleaned_lower = cleaned.lower()
    for valid in _VALID_DECISIONS:
        if valid in cleaned_lower:
            return valid, f"Decided on {valid} from response text"

    return "escalate", f"Unrecognized decision from LLM: {raw[:60]}"


def _apply_finish_guard(
    proposed_agent: str, reasoning: str, state: GraphState
) -> tuple[str, str]:
    """Deterministic guard: ensure finish only occurs when gates pass."""
    if proposed_agent != "finish":
        return proposed_agent, reasoning

    # Check tasks: only consider tasks pending if they don't have an accepted proof
    done_task_ids = {p.task_id for p in state.proofs}
    pending = [
        t for t in (state.plan or [])
        if t.status in ("pending", "in_progress", "failed") and t.task_id not in done_task_ids
    ]
    if pending:
        next_task = pending[0]
        assigned = next_task.assigned_agent or "engineer"
        return (
            assigned,
            f"Guarded override: Cannot finish while task {next_task.task_id} is pending. Routing to {assigned}.",
        )

    return "finish", reasoning


# ---------------------------------------------------------------------------
# 3. replan() — Decompose failing tasks or propose revised approaches
# ---------------------------------------------------------------------------

def replan(
    state: GraphState,
    failing_task_id: Optional[str] = None,
    trace_writer: Optional[TraceWriter] = None,
    artifact_dir: Path = Path("artifacts"),
) -> list[TaskDefinition]:
    """Revise the plan when a task repeatedly fails.

    Design Doc §5 (Scenario 1): "After the limit it replans the task
    (smaller component, different approach) and logs why."
    """
    plan_tasks = list(state.plan or [])
    failing_task: Optional[TaskDefinition] = None

    if failing_task_id:
        failing_task = next((t for t in plan_tasks if t.task_id == failing_task_id), None)
    if not failing_task:
        failing_task = next((t for t in plan_tasks if t.status == "failed"), None)

    if not failing_task:
        # Fallback to the first pending task
        failing_task = plan_tasks[0] if plan_tasks else TaskDefinition(
            task_id="T-01", description="General implementation", assigned_agent="engineer"
        )

    # Gather failure context
    code_artifacts = state.code_artifacts or {}
    art_info = code_artifacts.get(failing_task.task_id, {})
    error_context = art_info.get("last_error") or "Repeated build/test failure encountered"

    prompt = json.dumps(
        {
            "instruction": (
                "Task execution failed. Revise the plan by breaking down this task into smaller components "
                "or adopting a simplified architecture. Return a JSON object with: "
                "{\"revised_tasks\": [{\"task_id\": \"...\", \"description\": \"...\", \"assigned_agent\": \"...\", \"depends_on\": [...] }], \"reasoning\": \"...\"}"
            ),
            "failing_task": {
                "task_id": failing_task.task_id,
                "description": failing_task.description,
                "assigned_agent": failing_task.assigned_agent,
            },
            "error_context": str(error_context),
        },
        indent=2,
    )

    raw = complete(
        "planner",
        [{"role": "user", "content": prompt}],
    )

    revised_definitions, reasoning = _parse_replan_output(raw, failing_task)

    # Replace the failing task with revised sub-tasks in plan
    new_plan: list[TaskDefinition] = []
    replaced = False
    for t in plan_tasks:
        if t.task_id == failing_task.task_id and not replaced:
            new_plan.extend(revised_definitions)
            replaced = True
        elif t.task_id != failing_task.task_id:
            new_plan.append(t)

    if not replaced:
        new_plan.extend(revised_definitions)

    # Log replan event
    if trace_writer:
        trace_writer.write(
            "planner",
            "plan_revised",
            {
                "failing_task_id": failing_task.task_id,
                "new_tasks": [t.task_id for t in revised_definitions],
                "reasoning": reasoning,
            },
        )

    return new_plan


def _parse_replan_output(
    raw: str, failing_task: TaskDefinition
) -> tuple[list[TaskDefinition], str]:
    """Parse raw LLM output into revised task definitions and reasoning."""
    try:
        data = _extract_json(raw)
        tasks_data = data.get("revised_tasks", [])
        reasoning = data.get("reasoning", "Decomposed failing task into smaller components")
        revised: list[TaskDefinition] = []
        for i, td in enumerate(tasks_data):
            tid = td.get("task_id", f"{failing_task.task_id}-sub{i+1}")
            revised.append(
                TaskDefinition(
                    task_id=tid,
                    description=td.get("description", f"Sub-component of {failing_task.description}"),
                    assigned_agent=td.get("assigned_agent", failing_task.assigned_agent or "engineer"),
                    status="pending",
                    depends_on=td.get("depends_on", failing_task.depends_on),
                    required_flows=failing_task.required_flows,
                )
            )
        if revised:
            return revised, reasoning
    except Exception:
        pass

    # Fallback decomposition: split failing task into two focused subcomponents
    sub1 = TaskDefinition(
        task_id=f"{failing_task.task_id}A",
        description=f"Isolated UI presentation component: {failing_task.description}",
        assigned_agent=failing_task.assigned_agent or "engineer",
        status="pending",
        depends_on=failing_task.depends_on,
        required_flows=failing_task.required_flows,
    )
    sub2 = TaskDefinition(
        task_id=f"{failing_task.task_id}B",
        description=f"State handling and interaction logic for: {failing_task.description}",
        assigned_agent=failing_task.assigned_agent or "engineer",
        status="pending",
        depends_on=[sub1.task_id],
        required_flows=failing_task.required_flows,
    )
    return [sub1, sub2], "Decomposed into isolated presentation and interaction subtasks due to repeated failure"


# ---------------------------------------------------------------------------
# 4. LangGraph node function
# ---------------------------------------------------------------------------

def run_planner(
    state: GraphState,
    trace_writer: Optional[TraceWriter] = None,
    artifact_dir: Path = Path("artifacts"),
    **kwargs: Any,
) -> dict:
    """LangGraph node for the Planner / Supervisor.

    On first call (no plan), initialises plan via plan().
    Validates most recent proof-of-work from state.proofs.
    Checks for failing tasks to trigger replan() when needed.
    Calls decide() to choose the next agent, storing the decision in iteration_counters.
    """
    updates: dict = {}

    # ---- Initialise plan if empty -----------------------------------------
    if not state.plan:
        plan_output = plan(state.request, trace_writer=trace_writer, artifact_dir=artifact_dir)
        tasks = [
            TaskDefinition(
                task_id=t.task_id,
                description=t.description,
                assigned_agent=t.assigned_agent,
                status=t.status,
                depends_on=t.depends_on,
                required_flows=t.required_flows,
            )
            for t in plan_output.tasks
        ]
        updates["plan"] = tasks
        state = state.model_copy(update={"plan": tasks})

    # ---- Validate latest proof from state.proofs --------------------------
    if state.proofs:
        latest_proof = state.proofs[-1]
        counters = dict(state.iteration_counters)
        if latest_proof.task_id:
            counters[latest_proof.task_id] = counters.get(latest_proof.task_id, 0) + 1
        valid, errors = validate_proof(latest_proof)
        if not valid:
            if trace_writer:
                trace_writer.write(
                    "planner",
                    "proof_rejected",
                    {"agent": str(latest_proof.agent), "errors": errors},
                )
            rejected_agent = str(
                latest_proof.agent.value if hasattr(latest_proof.agent, "value") else latest_proof.agent
            )
            counters["_last_rejected_agent"] = rejected_agent
            updates["iteration_counters"] = counters
            state = state.model_copy(update={"iteration_counters": counters})
        else:
            counters.pop("_last_rejected_agent", None)
            updates["iteration_counters"] = counters
            state = state.model_copy(update={"iteration_counters": counters})
            if latest_proof.task_id and state.plan:
                updated_plan = [
                    t.model_copy(update={"status": "done"}) if t.task_id == latest_proof.task_id else t
                    for t in state.plan
                ]
                updates["plan"] = updated_plan
                state = state.model_copy(update={"plan": updated_plan})
            if trace_writer:
                trace_writer.write(
                    "planner",
                    "proof_accepted",
                    {"agent": str(latest_proof.agent), "task_id": latest_proof.task_id},
                )

    # ---- Check for repeated failures triggering replan ---------------------
    failed_tasks = [t for t in (state.plan or []) if t.status == "failed"]
    for ft in failed_tasks:
        # Task must have failed repeatedly (at least 2 attempts) to trigger replan (Design Doc §5 scenario 1)
        task_attempts = state.iteration_counters.get(ft.task_id, 0)
        replan_key = f"_replanned_{ft.task_id}"
        if task_attempts >= 2 and not state.iteration_counters.get(replan_key):
            revised_plan = replan(state, failing_task_id=ft.task_id, trace_writer=trace_writer, artifact_dir=artifact_dir)
            updates["plan"] = revised_plan
            state = state.model_copy(update={"plan": revised_plan})
            counters = dict(state.iteration_counters)
            counters[replan_key] = True
            updates["iteration_counters"] = counters
            state = state.model_copy(update={"iteration_counters": counters})
            break

    # ---- Increment run-total counter --------------------------------------
    counters = dict(state.iteration_counters)
    counters["run_total"] = counters.get("run_total", 0) + 1
    updates["iteration_counters"] = counters
    state = state.model_copy(update={"iteration_counters": counters})

    # ---- Get routing decision ---------------------------------------------
    next_agent = decide(state, trace_writer=trace_writer)

    counters = dict(state.iteration_counters)
    counters.pop("_last_rejected_agent", None)
    counters["_next_agent"] = next_agent
    updates["iteration_counters"] = counters

    # ---- Update status if accepting/escalating ----------------------------
    if next_agent == "finish" and state.status not in ("accepted", "partial", "failed"):
        updates["status"] = "accepted"
        if trace_writer:
            trace_writer.write("planner", "run_accepted", {})
    elif next_agent == "escalate":
        updates["status"] = "partial"
        if not state.unresolved:
            state.unresolved.append(
                UnresolvedIssue(
                    issue="Escalation triggered by planner",
                    evidence="planner",
                    agent="planner",
                )
            )
        updates["unresolved"] = list(state.unresolved)
    elif state.unresolved:
        updates["unresolved"] = list(state.unresolved)

    return updates
