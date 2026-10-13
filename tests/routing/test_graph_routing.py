"""
tests/routing/test_graph_routing.py

Covers the four required routing scenarios (Slice 1, Definition of Done):

1. Normal completion  — all stubs succeed; run finishes with status "accepted".
2. Failure reroute    — engineer returns a failed build; planner detects it and
                        reroutes back to engineer for a fix.
3. Proof rejection    — a worker submits an invalid/missing proof; planner
                        rejects it, logs the rejection, and sends it back.
4. Iteration limit    — repeated failures exhaust the budget; planner escalates,
                        state.unresolved is non-empty, status is "partial".

All tests use the scripted fake LLM (lib.llm.set_fake_llm_handler) — no real
network calls.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from graph.graph import create_graph, run_graph
from graph.routing import (
    DEFAULT_MAX_RUN_ITERATIONS,
    LimitExceeded,
    check_limits,
    route_decision,
)
from graph.state import GraphState, TaskDefinition, UnresolvedIssue
from lib.llm import set_fake_llm_handler
from lib.models import InputRequest, TargetType
from lib.proofs import create_proof
from lib.trace import TraceWriter


# ---------------------------------------------------------------------------
# Shared fixtures
# ---------------------------------------------------------------------------

@pytest.fixture(autouse=True)
def _clear_llm():
    """Always reset the fake LLM handler after each test."""
    yield
    set_fake_llm_handler(None)


@pytest.fixture
def sample_request() -> InputRequest:
    return InputRequest(
        brief="A support dashboard for viewing and replying to tickets.",
        api_spec_url="https://example.com/openapi.json",
        target=TargetType.DASHBOARD,
        required_flows=["list tickets", "filter by priority"],
        max_iterations=3,
    )


@pytest.fixture
def tmp_artifact_dir(tmp_path: Path) -> Path:
    return tmp_path / "artifacts"


@pytest.fixture
def tmp_trace(tmp_path: Path) -> TraceWriter:
    return TraceWriter(tmp_path / "trace.jsonl", run_id="test-run")


# ---------------------------------------------------------------------------
# Scripted fake-LLM helpers
# ---------------------------------------------------------------------------

def make_scripted_llm(responses: list[str]):
    """Return a fake LLM handler that pops responses in sequence."""
    queue = list(responses)

    def handler(agent_name: str, messages: list[dict], **kwargs) -> str:
        if agent_name == "engineer":
            return json.dumps({
                "files": [
                    {
                        "path": "src/components/TicketList.tsx",
                        "content": "export function TicketList() { return <div>Tickets</div>; }\nexport default TicketList;\n",
                    },
                    {
                        "path": "src/components/TicketList.test.tsx",
                        "content": "import { describe, it, expect } from 'vitest';\ndescribe('TicketList', () => { it('works', () => { expect(true).toBe(true); }); });\n",
                    }
                ]
            })
        if agent_name == "planner" and messages and "Analyze the product brief" in str(messages[-1].get("content", "")):
            return json.dumps({
                "pages": [{"name": "Dashboard", "route": "/", "description": "Main", "components": ["TicketList"]}],
                "user_flows": [{"flow_id": "F-01", "name": "list tickets", "description": "view tickets", "steps": ["view"]}],
                "tasks": [
                    {"task_id": "T-01", "description": "Design UI", "assigned_agent": "designer", "status": "pending", "depends_on": []},
                    {"task_id": "T-02", "description": "Build UI", "assigned_agent": "engineer", "status": "pending", "depends_on": ["T-01"]},
                    {"task_id": "T-03", "description": "Integrate API", "assigned_agent": "integration", "status": "pending", "depends_on": ["T-02"]},
                    {"task_id": "T-04", "description": "QA tests", "assigned_agent": "qa", "status": "pending", "depends_on": ["T-03"]},
                    {"task_id": "T-05", "description": "Accessibility audit", "assigned_agent": "critic", "status": "pending", "depends_on": ["T-04"]},
                ],
                "required_flows": ["list tickets", "filter by priority"],
                "reasoning": "Standard graph routing test plan",
            })
        if queue:
            return queue.pop(0)
        return "finish"

    return handler



# ---------------------------------------------------------------------------
# Test 1: Normal completion
# ---------------------------------------------------------------------------

class TestNormalCompletion:
    """Full pipeline with all stubs succeeding → status "accepted"."""

    def test_run_accepted(self, sample_request, tmp_artifact_dir, tmp_trace):
        # Scripted LLM: designer → engineer → integration → qa → critic → finish
        set_fake_llm_handler(
            make_scripted_llm(
                ["designer", "engineer", "integration", "qa", "critic", "finish"]
            )
        )

        final_state = run_graph(
            sample_request,
            trace_writer=tmp_trace,
            artifact_dir=tmp_artifact_dir,
        )

        assert final_state.status == "accepted", (
            f"Expected 'accepted', got '{final_state.status}'. "
            f"Unresolved: {final_state.unresolved}"
        )
        assert final_state.plan is not None
        assert len(final_state.proofs) >= 5  # one proof per worker

    def test_trace_contains_routing_decisions(self, sample_request, tmp_artifact_dir, tmp_trace):
        set_fake_llm_handler(
            make_scripted_llm(
                ["designer", "engineer", "integration", "qa", "critic", "finish"]
            )
        )
        run_graph(sample_request, trace_writer=tmp_trace, artifact_dir=tmp_artifact_dir)

        from lib.trace import read_trace, filter_trace
        entries = read_trace(tmp_trace.path)
        routing_entries = filter_trace(entries, event_type="routing_decision")
        assert len(routing_entries) >= 5, (
            f"Expected ≥5 routing_decision entries, found {len(routing_entries)}"
        )

    def test_trace_contains_proof_accepted(self, sample_request, tmp_artifact_dir, tmp_trace):
        set_fake_llm_handler(
            make_scripted_llm(
                ["designer", "engineer", "integration", "qa", "critic", "finish"]
            )
        )
        run_graph(sample_request, trace_writer=tmp_trace, artifact_dir=tmp_artifact_dir)

        from lib.trace import read_trace, filter_trace
        entries = read_trace(tmp_trace.path)
        accepted = filter_trace(entries, event_type="proof_accepted")
        assert len(accepted) >= 5

    def test_final_state_has_design_spec(self, sample_request, tmp_artifact_dir):
        set_fake_llm_handler(
            make_scripted_llm(
                ["designer", "engineer", "integration", "qa", "critic", "finish"]
            )
        )
        final = run_graph(sample_request, artifact_dir=tmp_artifact_dir)
        assert final.design_spec is not None
        assert "color_primary" in final.design_spec.tokens

    def test_final_state_has_audit_report(self, sample_request, tmp_artifact_dir):
        set_fake_llm_handler(
            make_scripted_llm(
                ["designer", "engineer", "integration", "qa", "critic", "finish"]
            )
        )
        final = run_graph(sample_request, artifact_dir=tmp_artifact_dir)
        assert final.audit_report is not None
        assert final.audit_report.accepted is True


# ---------------------------------------------------------------------------
# Test 2: Failure reroute
# ---------------------------------------------------------------------------

class TestFailureReroute:
    """Engineer build failure → planner reroutes back to engineer."""

    def test_engineer_failure_triggers_reroute(self, sample_request, tmp_artifact_dir, tmp_trace):
        """
        Script:
          1. designer (designer handoff succeeds)
          2. engineer (first attempt succeeds too in planner decision)
             BUT we inject force_failure=True on engineer node so it
             returns a failed task.
          3. planner sees engineer task failed → routes back to engineer
          4. engineer (second call without force_failure) → succeeds
          5. integration → qa → critic → finish
        """
        set_fake_llm_handler(
            make_scripted_llm(
                [
                    "designer",    # round 1: go to designer
                    "engineer",    # round 2: go to engineer (will fail)
                    "engineer",    # round 3: planner detects failure, re-routes to engineer
                    "integration", # round 4
                    "qa",          # round 5
                    "critic",      # round 6
                    "finish",      # round 7
                ]
            )
        )

        # First engineer call fails, second succeeds
        call_count = {"engineer": 0}
        original_engineer = __import__("agents.engineer", fromlist=["run_engineer"]).run_engineer

        def patched_engineer(state, trace_writer=None, artifact_dir=Path("artifacts"), **kwargs):
            call_count["engineer"] += 1
            fail = call_count["engineer"] == 1
            return original_engineer(
                state,
                trace_writer=trace_writer,
                artifact_dir=artifact_dir,
                force_failure=fail,
            )

        import agents.engineer as eng_mod
        original_fn = eng_mod.run_engineer
        eng_mod.run_engineer = patched_engineer

        try:
            final = run_graph(
                sample_request,
                trace_writer=tmp_trace,
                artifact_dir=tmp_artifact_dir,
            )
        finally:
            eng_mod.run_engineer = original_fn

        # After successful retry the run should complete
        assert final.status == "accepted"
        assert call_count["engineer"] >= 2, "Expected engineer to be called at least twice"

    def test_qa_failure_triggers_reroute(self, sample_request, tmp_artifact_dir, tmp_trace):
        """QA flow failure causes planner to route back to engineer, then QA retries."""
        qa_call_count = {"n": 0}
        original_qa = __import__("agents.qa", fromlist=["run_qa"]).run_qa

        def patched_qa(state, trace_writer=None, artifact_dir=Path("artifacts"), **kwargs):
            qa_call_count["n"] += 1
            fail = qa_call_count["n"] == 1
            return original_qa(
                state, trace_writer=trace_writer, artifact_dir=artifact_dir, force_failure=fail
            )

        import agents.qa as qa_mod
        original_fn = qa_mod.run_qa
        qa_mod.run_qa = patched_qa

        set_fake_llm_handler(
            make_scripted_llm(
                [
                    "designer",
                    "engineer",
                    "integration",
                    "qa",       # first call — fails
                    "engineer", # planner sees QA failure, routes to engineer for fix
                    "qa",       # QA retries — succeeds
                    "critic",
                    "finish",
                ]
            )
        )

        try:
            final = run_graph(
                sample_request,
                trace_writer=tmp_trace,
                artifact_dir=tmp_artifact_dir,
            )
        finally:
            qa_mod.run_qa = original_fn

        assert final.status == "accepted"
        assert qa_call_count["n"] >= 2


# ---------------------------------------------------------------------------
# Test 3: Proof rejection
# ---------------------------------------------------------------------------

class TestProofRejection:
    """Planner rejects a handoff with a missing/invalid proof and re-routes."""

    def _bad_designer(self, state: GraphState, trace_writer=None, artifact_dir=None, **kwargs) -> dict:
        """Returns a state update with an invalid proof (no evidence)."""
        from lib.models import ProofOfWork, EvidenceItem, AgentName
        from datetime import datetime, timezone

        # Build a proof dict that will fail validate_proof (empty evidence list)
        bad_proof_dict = {
            "agent": "designer",
            "task_id": "T-01",
            "claim": "Design done",
            "evidence": [],          # <-- invalid: must have at least one item
            "reasoning": "stub",
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }
        # We need to sneak it in as a ProofOfWork object bypassing model validation
        # by directly patching evidence after construction
        proof = ProofOfWork(
            agent=AgentName.DESIGNER,
            task_id="T-01",
            claim="Design done",
            evidence=[EvidenceItem(type="stub", ref="nonexistent/path/design.json")],
            reasoning="stub",
            timestamp=datetime.now(timezone.utc).isoformat(),
        )
        return {
            "proofs": state.proofs + [proof],
        }

    def test_missing_evidence_file_triggers_rejection(
        self, sample_request, tmp_artifact_dir, tmp_trace
    ):
        """A proof whose evidence ref doesn't exist on disk is rejected by the planner."""
        import agents.designer as des_mod
        original_fn = des_mod.run_designer
        des_mod.run_designer = self._bad_designer

        set_fake_llm_handler(
            make_scripted_llm(
                [
                    "designer",    # planner routes to designer (bad proof)
                    "designer",    # planner rejects proof, re-routes to designer
                    "designer",    # second attempt also bad → budget exhausted
                    "escalate",
                ]
            )
        )

        try:
            final = run_graph(
                sample_request,
                trace_writer=tmp_trace,
                artifact_dir=tmp_artifact_dir,
            )
        finally:
            des_mod.run_designer = original_fn

        # The run should have ended (accepted or partial)
        assert final.status in ("partial", "accepted")

        # Check that proof_rejected appeared in the trace
        from lib.trace import read_trace, filter_trace
        entries = read_trace(tmp_trace.path)
        rejections = filter_trace(entries, event_type="proof_rejected")
        assert len(rejections) >= 1, "Expected at least one proof_rejected trace entry"

    def test_proof_rejection_reroutes_to_same_agent(
        self, sample_request, tmp_artifact_dir, tmp_trace
    ):
        """After rejection the _last_rejected_agent triggers re-route to the same agent."""
        # We'll use the planner's decide() directly to test the reroute logic
        from graph.state import GraphState, TaskDefinition
        from lib.models import ProofOfWork, EvidenceItem, AgentName
        from agents.planner import decide
        from datetime import datetime, timezone

        state = GraphState(
            request=sample_request,
            plan=[
                TaskDefinition(
                    task_id="T-01",
                    description="Design",
                    assigned_agent="designer",
                    status="pending",
                )
            ],
            iteration_counters={"_last_rejected_agent": "designer"},
        )

        set_fake_llm_handler(make_scripted_llm(["finish"]))
        decision = decide(state, trace_writer=tmp_trace)
        assert decision == "designer", (
            f"Expected planner to reroute to 'designer', got '{decision}'"
        )


# ---------------------------------------------------------------------------
# Test 4: Iteration limit → escalation and status "partial"
# ---------------------------------------------------------------------------

class TestIterationLimit:
    """Iteration budget exhausted → escalation, unresolved issues, status partial."""

    def test_run_limit_triggers_partial(self, sample_request, tmp_artifact_dir, tmp_trace):
        """Set a very low run limit to force escalation mid-run."""
        # We monkeypatch the routing guard to use a tiny limit
        import graph.routing as routing_mod
        original_default = routing_mod.DEFAULT_MAX_RUN_ITERATIONS
        routing_mod.DEFAULT_MAX_RUN_ITERATIONS = 2  # forces escalation very quickly

        set_fake_llm_handler(
            make_scripted_llm(
                ["designer", "engineer", "engineer", "escalate"]
            )
        )

        try:
            final = run_graph(
                sample_request,
                trace_writer=tmp_trace,
                artifact_dir=tmp_artifact_dir,
            )
        finally:
            routing_mod.DEFAULT_MAX_RUN_ITERATIONS = original_default

        assert final.status == "partial", (
            f"Expected 'partial', got '{final.status}'"
        )

    def test_unresolved_issues_populated(self, sample_request, tmp_artifact_dir, tmp_trace):
        """When escalation happens, state.unresolved must be non-empty."""
        import graph.routing as routing_mod
        original_default = routing_mod.DEFAULT_MAX_RUN_ITERATIONS
        routing_mod.DEFAULT_MAX_RUN_ITERATIONS = 2

        set_fake_llm_handler(make_scripted_llm(["designer", "escalate"]))

        try:
            final = run_graph(
                sample_request,
                trace_writer=tmp_trace,
                artifact_dir=tmp_artifact_dir,
            )
        finally:
            routing_mod.DEFAULT_MAX_RUN_ITERATIONS = original_default

        assert len(final.unresolved) > 0, (
            "Expected state.unresolved to be non-empty after escalation"
        )

    def test_trace_contains_limit_exceeded(self, sample_request, tmp_artifact_dir, tmp_trace):
        """A limit_exceeded trace event must be written when escalating."""
        import graph.routing as routing_mod
        original_default = routing_mod.DEFAULT_MAX_RUN_ITERATIONS
        routing_mod.DEFAULT_MAX_RUN_ITERATIONS = 2

        set_fake_llm_handler(make_scripted_llm(["designer", "escalate"]))

        try:
            run_graph(
                sample_request,
                trace_writer=tmp_trace,
                artifact_dir=tmp_artifact_dir,
            )
        finally:
            routing_mod.DEFAULT_MAX_RUN_ITERATIONS = original_default

        from lib.trace import read_trace, filter_trace
        entries = read_trace(tmp_trace.path)
        limit_events = filter_trace(entries, event_type="limit_exceeded")
        assert len(limit_events) >= 1, "Expected a limit_exceeded trace entry"

    def test_per_task_limit_raises(self, sample_request, tmp_artifact_dir):
        """check_limits raises LimitExceeded when per-task counter is at limit."""
        state = GraphState(
            request=sample_request,
            plan=[
                TaskDefinition(
                    task_id="T-01",
                    description="Design",
                    assigned_agent="designer",
                    status="pending",
                )
            ],
            iteration_counters={"T-01": 3},
        )
        with pytest.raises(LimitExceeded, match="T-01"):
            check_limits(state, max_task_iterations=3)

    def test_run_total_limit_raises(self, sample_request):
        """check_limits raises LimitExceeded when run_total is at the run limit."""
        state = GraphState(
            request=sample_request,
            iteration_counters={"run_total": 15},
        )
        with pytest.raises(LimitExceeded, match="Run iteration limit"):
            check_limits(state, max_run_iterations=15)

    def test_request_max_iterations_respected(self, tmp_artifact_dir, tmp_trace):
        """state.request.max_iterations is used as the per-task limit."""
        request = InputRequest(
            brief="test",
            api_spec_url="https://example.com/openapi.json",
            target=TargetType.DASHBOARD,
            max_iterations=1,  # very tight budget
        )
        state = GraphState(
            request=request,
            plan=[
                TaskDefinition(
                    task_id="T-01",
                    description="Design",
                    assigned_agent="designer",
                    status="pending",
                )
            ],
            iteration_counters={"T-01": 1},
        )
        with pytest.raises(LimitExceeded):
            check_limits(state)


# ---------------------------------------------------------------------------
# Test: route_decision conditional edge
# ---------------------------------------------------------------------------

class TestRouteDecision:
    def test_routes_to_stored_decision(self, sample_request):
        state = GraphState(
            request=sample_request,
            iteration_counters={"_next_agent": "engineer"},
        )
        assert route_decision(state) == "engineer"

    def test_missing_decision_escalates(self, sample_request):
        state = GraphState(
            request=sample_request,
            iteration_counters={},
        )
        assert route_decision(state) == "escalate"

    def test_invalid_decision_escalates(self, sample_request):
        state = GraphState(
            request=sample_request,
            iteration_counters={"_next_agent": "hacker"},
        )
        assert route_decision(state) == "escalate"

    @pytest.mark.parametrize(
        "agent",
        ["designer", "engineer", "integration", "qa", "critic", "finish", "escalate"],
    )
    def test_all_valid_decisions_pass_through(self, sample_request, agent):
        state = GraphState(
            request=sample_request,
            iteration_counters={"_next_agent": agent},
        )
        assert route_decision(state) == agent
