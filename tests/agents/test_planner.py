"""
tests/agents/test_planner.py

Unit and behavioural tests for the LLM-driven Planner supervisor (agents/planner.py):
1. plan() parsing OpenAPI spec & brief, producing validated PlanOutput.
2. decide() dynamically choosing different agents for different blackboard states.
3. decide() guards overriding invalid finish proposals and enforcing limits.
4. replan() triggering upon task failure and decomposing tasks into smaller components.
5. LangGraph node run_planner() integrating plan, proof validation, replan, and decide.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from agents.planner import decide, plan, replan, run_planner
from graph.state import AuditReport, GraphState, QAResults, TaskDefinition
from lib.llm import set_fake_llm_handler
from lib.models import AgentName, EvidenceItem, InputRequest, PlanOutput, ProofOfWork, TargetType
from lib.proofs import create_proof
from lib.trace import TraceWriter, filter_trace, read_trace
from tools.openapi import get_spec_summary, list_endpoints, list_schemas, load_openapi_spec


@pytest.fixture(autouse=True)
def _clear_llm():
    """Always reset the fake LLM handler after each test."""
    yield
    set_fake_llm_handler(None)


@pytest.fixture
def sample_request() -> InputRequest:
    return InputRequest(
        brief="A support dashboard where agents view open tickets, filter by priority, open a ticket to read its history, and reply.",
        api_spec_url="https://demo-backend.example.com/openapi.json",
        target=TargetType.DASHBOARD,
        style_hints=["minimal", "data-dense"],
        required_flows=["list tickets", "filter by priority", "open ticket detail", "send reply"],
        max_iterations=3,
    )


@pytest.fixture
def tmp_artifact_dir(tmp_path: Path) -> Path:
    d = tmp_path / "artifacts"
    d.mkdir(parents=True, exist_ok=True)
    return d


@pytest.fixture
def tmp_trace(tmp_path: Path) -> TraceWriter:
    return TraceWriter(tmp_path / "trace.jsonl", run_id="test-planner-run")


# ---------------------------------------------------------------------------
# 1. OpenAPI Parser Tool Tests
# ---------------------------------------------------------------------------

class TestOpenAPIParser:
    def test_load_and_list_endpoints(self):
        spec = load_openapi_spec("https://demo-backend.example.com/openapi.json")
        endpoints = list_endpoints(spec)
        assert len(endpoints) >= 3
        paths = [e["path"] for e in endpoints]
        assert "/api/tickets" in paths
        assert "/api/tickets/{id}" in paths

    def test_list_schemas(self):
        spec = load_openapi_spec("https://demo-backend.example.com/openapi.json")
        schemas = list_schemas(spec)
        assert "Ticket" in schemas
        assert "TicketDetail" in schemas

    def test_get_spec_summary(self):
        summary = get_spec_summary("https://demo-backend.example.com/openapi.json")
        assert "endpoints" in summary
        assert "Ticket" in summary["schema_names"]


# ---------------------------------------------------------------------------
# 2. plan() Unit Tests
# ---------------------------------------------------------------------------

class TestPlanGeneration:
    def test_plan_parsing_and_validation(self, sample_request, tmp_artifact_dir, tmp_trace):
        """Mock LLM returns structured JSON plan; plan() parses and validates against PlanOutput."""
        def fake_llm(agent_name: str, messages: list[dict], **kwargs) -> str:
            assert agent_name == "planner"
            return json.dumps({
                "pages": [
                    {
                        "name": "TicketsDashboard",
                        "route": "/",
                        "description": "Main ticket view",
                        "components": ["TicketList", "PriorityFilter"],
                    },
                    {
                        "name": "TicketDetail",
                        "route": "/tickets/:id",
                        "description": "Detailed thread and reply",
                        "components": ["MessageThread", "ReplyBox"],
                    },
                ],
                "user_flows": [
                    {
                        "flow_id": "F-01",
                        "name": "list tickets",
                        "description": "View open tickets in list",
                        "steps": ["Open dashboard", "Verify ticket items are rendered"],
                    },
                    {
                        "flow_id": "F-02",
                        "name": "send reply",
                        "description": "Reply to ticket",
                        "steps": ["Click ticket", "Type reply", "Click send"],
                    },
                ],
                "tasks": [
                    {
                        "task_id": "T-01",
                        "description": "Design layout and color system",
                        "assigned_agent": "designer",
                        "status": "pending",
                        "depends_on": [],
                        "required_flows": [],
                    },
                    {
                        "task_id": "T-02",
                        "description": "Implement TicketList and TicketDetail components",
                        "assigned_agent": "engineer",
                        "status": "pending",
                        "depends_on": ["T-01"],
                        "required_flows": ["list tickets"],
                    },
                ],
                "required_flows": ["list tickets", "send reply"],
                "reasoning": "Standard two-phase design and engineering plan.",
            })

        set_fake_llm_handler(fake_llm)

        plan_result = plan(sample_request, trace_writer=tmp_trace, artifact_dir=tmp_artifact_dir)

        assert isinstance(plan_result, PlanOutput)
        assert len(plan_result.pages) == 2
        assert len(plan_result.user_flows) == 2
        assert len(plan_result.tasks) == 2
        assert plan_result.tasks[0].assigned_agent == "designer"
        assert plan_result.required_flows == ["list tickets", "send reply"]

        # Check artifact written to disk
        plan_file = tmp_artifact_dir / "plan.json"
        assert plan_file.exists()

        # Check trace recorded plan_created
        entries = read_trace(tmp_trace.path)
        plan_entries = filter_trace(entries, event_type="plan_created")
        assert len(plan_entries) == 1
        assert "TicketsDashboard" in plan_entries[0].payload["pages"]

    def test_plan_fallback_resilience(self, sample_request, tmp_artifact_dir, tmp_trace):
        """Malformed LLM response gracefully synthesizes valid PlanOutput."""
        def bad_llm(agent_name: str, messages: list[dict], **kwargs) -> str:
            return "Non-JSON gibberish response"

        set_fake_llm_handler(bad_llm)

        plan_result = plan(sample_request, trace_writer=tmp_trace, artifact_dir=tmp_artifact_dir)
        assert isinstance(plan_result, PlanOutput)
        assert len(plan_result.tasks) >= 3
        assert (tmp_artifact_dir / "plan.json").exists()


# ---------------------------------------------------------------------------
# 3. decide() State-Driven Decisions Tests
# ---------------------------------------------------------------------------

class TestDecideRouting:
    def test_decide_chooses_different_agents_for_different_states(
        self, sample_request, tmp_artifact_dir, tmp_trace
    ):
        """decide() chooses designer initially, engineer after design, QA after integration."""
        calls = []

        def scripted_llm(agent_name: str, messages: list[dict], **kwargs) -> str:
            prompt_content = messages[-1]["content"]
            parsed_prompt = json.loads(prompt_content)
            accepted = [p["agent"] for p in parsed_prompt.get("accepted_proofs", [])]

            if "designer" not in accepted:
                return json.dumps({
                    "next_agent": "designer",
                    "reasoning": "Plan is fresh; starting with design tokens and inventory.",
                })
            elif "engineer" not in accepted:
                return json.dumps({
                    "next_agent": "engineer",
                    "reasoning": "Design spec is complete; proceeding to React component engineering.",
                })
            else:
                return json.dumps({
                    "next_agent": "qa",
                    "reasoning": "Components built; moving to browser flow verification.",
                })

        set_fake_llm_handler(scripted_llm)

        # State 1: Fresh state, no proofs
        state1 = GraphState(
            request=sample_request,
            plan=[
                TaskDefinition(task_id="T-01", description="Design UI", assigned_agent="designer"),
                TaskDefinition(task_id="T-02", description="Build components", assigned_agent="engineer"),
            ],
        )
        dec1 = decide(state1, trace_writer=tmp_trace)
        assert dec1 == "designer"

        # State 2: Designer has proof
        proof_file = tmp_artifact_dir / "design.json"
        proof_file.write_text("{}", encoding="utf-8")
        des_proof = create_proof(
            agent="designer",
            task_id="T-01",
            claim="Design spec complete",
            evidence=[{"type": "spec", "ref": str(proof_file)}],
            reasoning="Tokens generated",
        )
        state2 = state1.model_copy(update={"proofs": [des_proof]})
        dec2 = decide(state2, trace_writer=tmp_trace)
        assert dec2 == "engineer"

        # State 3: Engineer has proof
        build_log = tmp_artifact_dir / "build.log"
        build_log.write_text("Build passed", encoding="utf-8")
        eng_proof = create_proof(
            agent="engineer",
            task_id="T-02",
            claim="Component built",
            evidence=[{"type": "log", "ref": str(build_log)}],
            reasoning="Compiled with TypeScript",
        )
        state3 = state2.model_copy(update={"proofs": [des_proof, eng_proof]})
        dec3 = decide(state3, trace_writer=tmp_trace)
        assert dec3 == "qa"

        # Check trace recorded routing decisions with reasoning notes
        entries = read_trace(tmp_trace.path)
        dec_entries = filter_trace(entries, event_type="routing_decision")
        assert len(dec_entries) == 3
        assert dec_entries[0].payload["next_agent"] == "designer"
        assert "design tokens" in dec_entries[0].payload["reasoning"]
        assert dec_entries[1].payload["next_agent"] == "engineer"

    def test_guard_overrides_premature_finish(self, sample_request, tmp_trace):
        """Guard prevents finish when pending tasks remain."""
        set_fake_llm_handler(lambda *args, **kwargs: json.dumps({
            "next_agent": "finish",
            "reasoning": "I want to finish now.",
        }))

        state = GraphState(
            request=sample_request,
            plan=[
                TaskDefinition(task_id="T-01", description="Build UI", assigned_agent="engineer", status="pending")
            ],
        )
        decision = decide(state, trace_writer=tmp_trace)
        # Guard must prevent finish and route to pending task's agent
        assert decision == "engineer"


# ---------------------------------------------------------------------------
# 4. replan() Tests
# ---------------------------------------------------------------------------

class TestReplan:
    def test_replan_triggered_on_repeated_failure(self, sample_request, tmp_trace, tmp_artifact_dir):
        """When a task fails, replan decomposes it into smaller components and logs why."""
        def replan_llm(agent_name: str, messages: list[dict], **kwargs) -> str:
            return json.dumps({
                "revised_tasks": [
                    {
                        "task_id": "T-02-presentation",
                        "description": "Implement TicketCard UI markup and styling",
                        "assigned_agent": "engineer",
                        "depends_on": ["T-01"],
                    },
                    {
                        "task_id": "T-02-logic",
                        "description": "Implement TicketCard state and event handler hooks",
                        "assigned_agent": "engineer",
                        "depends_on": ["T-02-presentation"],
                    },
                ],
                "reasoning": "Decomposing complex card component into separate presentation and state logic.",
            })

        set_fake_llm_handler(replan_llm)

        failing_task = TaskDefinition(
            task_id="T-02",
            description="Implement massive monolithic TicketCard",
            assigned_agent="engineer",
            status="failed",
        )
        state = GraphState(
            request=sample_request,
            plan=[
                TaskDefinition(task_id="T-01", description="Design UI", assigned_agent="designer", status="done"),
                failing_task,
                TaskDefinition(task_id="T-03", description="QA tests", assigned_agent="qa", status="pending"),
            ],
            code_artifacts={"T-02": {"last_error": "Component too large and complex"}},
        )

        revised = replan(state, failing_task_id="T-02", trace_writer=tmp_trace, artifact_dir=tmp_artifact_dir)

        assert len(revised) == 4
        task_ids = [t.task_id for t in revised]
        assert "T-02-presentation" in task_ids
        assert "T-02-logic" in task_ids
        assert "T-02" not in task_ids

        # Check trace recorded plan_revised with reasoning
        entries = read_trace(tmp_trace.path)
        revised_entries = filter_trace(entries, event_type="plan_revised")
        assert len(revised_entries) == 1
        assert "presentation and state logic" in revised_entries[0].payload["reasoning"]


# ---------------------------------------------------------------------------
# 5. run_planner LangGraph Node Integration Tests
# ---------------------------------------------------------------------------

class TestRunPlannerNode:
    def test_run_planner_initializes_plan_and_routes(self, sample_request, tmp_trace, tmp_artifact_dir):
        """First call initializes plan via plan() and routes to first agent."""
        set_fake_llm_handler(lambda *args, **kwargs: json.dumps({
            "next_agent": "designer",
            "reasoning": "Initial plan created, routing to designer.",
        }))

        state = GraphState(request=sample_request)
        result = run_planner(state, trace_writer=tmp_trace, artifact_dir=tmp_artifact_dir)

        assert "plan" in result
        assert len(result["plan"]) >= 2
        assert result["iteration_counters"]["_next_agent"] == "designer"
        assert (tmp_artifact_dir / "plan.json").exists()
