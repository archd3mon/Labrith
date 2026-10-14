"""
tests/agents/test_integration.py — Tests for agents/integration.py.

Covers:
1. Clean run against conforming API:
   - Generated typed API client with loading and error states.
   - All endpoints exercised and logged in requests.log.
   - Clean mismatch report with 0 mismatches.
   - Proof-of-work valid against schemas/proof.schema.json.
2. Mismatch run against non-conforming API:
   - Missing required field 'status' detected and documented with evidence.
   - LLM / Agent decides to ask planner to involve engineer.
   - Request to planner documented in integration report.
   - Proof-of-work cites mismatch report and logs.
3. Type adaptation run:
   - Minor non-breaking difference handled by adapting TypeScript types.
4. Trace events emitted:
   - api_client_generated, api_exercised, mismatch_detected, handoff.
5. Supervisor planner routing:
   - Planner routes to engineer upon integration requesting engineer involvement.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from agents.integration import (
    generate_typescript_client,
    run_integration,
    validate_response_against_schema,
)
from agents.planner import decide
from graph.state import GraphState, TaskDefinition
from lib.llm import set_fake_llm_handler
from lib.models import InputRequest, TargetType
from lib.proofs import validate_proof
from lib.trace import TraceWriter, filter_trace, read_trace
from tools.mock_server import MockServer
from tools.openapi import DEMO_BACKEND_SPEC, list_schemas


@pytest.fixture(autouse=True)
def _clear_llm():
    """Reset fake LLM handler before and after each test."""
    set_fake_llm_handler(None)
    yield
    set_fake_llm_handler(None)


@pytest.fixture
def sample_request() -> InputRequest:
    return InputRequest(
        brief="A customer support ticket triage dashboard.",
        api_spec_url="https://demo-backend.example.com/openapi.json",
        target=TargetType.DASHBOARD,
        required_flows=["list tickets", "filter by priority", "reply to ticket"],
        max_iterations=3,
    )


@pytest.fixture
def tmp_artifact_dir(tmp_path: Path) -> Path:
    d = tmp_path / "artifacts"
    d.mkdir(parents=True, exist_ok=True)
    return d


@pytest.fixture
def tmp_trace(tmp_path: Path) -> TraceWriter:
    return TraceWriter(tmp_path / "trace.jsonl", run_id="test-integration-run")


# ---------------------------------------------------------------------------
# 1. Clean Run Tests
# ---------------------------------------------------------------------------

def test_clean_integration_run(sample_request, tmp_artifact_dir, tmp_trace):
    """When API conforms to spec, integration agent produces a clean report and valid proof."""
    state = GraphState(
        request=sample_request,
        plan=[
            TaskDefinition(
                task_id="T-03",
                description="API integration & client generation",
                assigned_agent="integration",
                status="in_progress",
            )
        ],
    )

    update = run_integration(state, trace_writer=tmp_trace, artifact_dir=tmp_artifact_dir)

    assert "integration_report" in update
    report = update["integration_report"]
    assert report.api_client_path is not None
    assert Path(report.api_client_path).exists()
    assert report.passed is True
    assert len(report.mismatches) == 0
    assert report.planner_action is None
    assert len(report.request_response_log) >= 3

    # Check client content
    client_code = Path(report.api_client_path).read_text(encoding="utf-8")
    assert "export interface ApiState<T>" in client_code
    assert "export interface Ticket" in client_code
    assert "export class ApiClient" in client_code
    assert "listTickets" in client_code

    # Check proof of work
    assert len(update["proofs"]) == 1
    proof = update["proofs"][-1]
    valid, errors = validate_proof(proof)
    assert valid, f"Proof invalid: {errors}"
    assert proof.agent.value == "integration"
    assert "zero mismatches" in proof.claim or "matched" in proof.claim

    # Check trace events
    events = read_trace(tmp_trace.path)
    agent_events = [e for e in events if e.agent == "integration"]
    event_names = [e.event_type for e in agent_events]
    assert "api_client_generated" in event_names
    assert "api_exercised" in event_names
    assert "handoff" in event_names


# ---------------------------------------------------------------------------
# 2. Mismatched Run Tests (Contract Breaking -> Involve Engineer)
# ---------------------------------------------------------------------------

def test_mismatched_integration_run_involves_engineer(sample_request, tmp_artifact_dir, tmp_trace):
    """When API has breaking mismatch (missing required field), agent reports it and requests engineer."""
    state = GraphState(
        request=sample_request,
        plan=[
            TaskDefinition(
                task_id="T-03",
                description="API integration & client generation",
                assigned_agent="integration",
                status="in_progress",
            )
        ],
    )

    # Fake LLM deciding to involve engineer
    def fake_handler(agent_name: str, messages: list[dict], **kwargs) -> str:
        if agent_name == "integration":
            return json.dumps({
                "decision": "involve_engineer",
                "claim": "Spec mismatch detected: missing required property 'status'; requesting planner to involve engineer.",
                "reasoning": "The backend API omits the required 'status' property in tickets list. UI requires engineer to update status indicators and fallback handling.",
            })
        return "{}"

    set_fake_llm_handler(fake_handler)

    # Configure deliberate mismatch: missing 'status' field on GET /api/tickets
    deliberate = {
        ("GET", "/api/tickets"): {
            "mismatch_type": "missing_field",
            "field_name": "status",
        }
    }

    update = run_integration(
        state,
        trace_writer=tmp_trace,
        artifact_dir=tmp_artifact_dir,
        deliberate_mismatch=deliberate,
    )

    report = update["integration_report"]
    assert report.passed is False
    assert len(report.mismatches) > 0
    assert report.planner_action == "involve_engineer"

    # Verify documented mismatch details
    missing_status_mismatches = [m for m in report.mismatches if "status" in m["field"]]
    assert len(missing_status_mismatches) > 0
    assert missing_status_mismatches[0]["issue_type"] == "missing_required_property"

    # Verify proof-of-work
    proof = update["proofs"][-1]
    valid, errors = validate_proof(proof)
    assert valid, f"Proof invalid: {errors}"
    assert "mismatch" in proof.claim.lower()
    assert any(e.type == "mismatch_report" for e in proof.evidence)

    # Verify trace records mismatch_detected
    events = read_trace(tmp_trace.path)
    mismatch_events = [e for e in events if e.event_type == "mismatch_detected"]
    assert len(mismatch_events) == 1
    assert mismatch_events[0].payload.get("decision") == "involve_engineer"


# ---------------------------------------------------------------------------
# 3. Type Adaptation Run Tests (Minor Variation -> Adapt Types)
# ---------------------------------------------------------------------------

def test_type_adaptation_run(sample_request, tmp_artifact_dir, tmp_trace):
    """When discrepancy is minor, agent adapts TypeScript types in generated client."""
    state = GraphState(
        request=sample_request,
        plan=[
            TaskDefinition(
                task_id="T-03",
                description="API integration & client generation",
                assigned_agent="integration",
                status="in_progress",
            )
        ],
    )

    def fake_handler(agent_name: str, messages: list[dict], **kwargs) -> str:
        if agent_name == "integration":
            return json.dumps({
                "decision": "adapt_types",
                "claim": "Spec mismatch detected; adapted TypeScript client types with optional status.",
                "reasoning": "Backend intermittently omits status. Adapted Ticket interface to make status optional to prevent runtime parse failures.",
            })
        return "{}"

    set_fake_llm_handler(fake_handler)

    deliberate = {
        ("GET", "/api/tickets"): {
            "mismatch_type": "missing_field",
            "field_name": "status",
        }
    }

    update = run_integration(
        state,
        trace_writer=tmp_trace,
        artifact_dir=tmp_artifact_dir,
        deliberate_mismatch=deliberate,
    )

    report = update["integration_report"]
    assert report.planner_action == "adapt_types"
    assert report.passed is True  # Passed because types were adapted

    # Client code should have adapted definition
    client_code = Path(report.api_client_path).read_text(encoding="utf-8")
    assert "status?:" in client_code

    proof = update["proofs"][-1]
    valid, errors = validate_proof(proof)
    assert valid, f"Proof invalid: {errors}"


# ---------------------------------------------------------------------------
# 4. Supervisor Routing on Mismatch
# ---------------------------------------------------------------------------

def test_planner_routes_to_engineer_on_mismatch(sample_request, tmp_artifact_dir, tmp_trace):
    """Planner supervisor routes work to engineer when integration requests engineer involvement."""
    # First, run integration with deliberate mismatch
    def fake_handler(agent_name: str, messages: list[dict], **kwargs) -> str:
        if agent_name == "integration":
            return json.dumps({
                "decision": "involve_engineer",
                "claim": "Breaking mismatch detected; requesting planner to involve engineer.",
                "reasoning": "Missing field requires UI error state update.",
            })
        if agent_name == "planner":
            # Planner sees integration_action_requested == 'involve_engineer' and routes to engineer
            return json.dumps({
                "next_agent": "engineer",
                "reasoning": "Integration reported breaking API mismatch; routing to component engineer to update UI contract.",
            })
        return "{}"

    set_fake_llm_handler(fake_handler)

    state = GraphState(
        request=sample_request,
        plan=[
            TaskDefinition(
                task_id="T-01",
                description="Design UI",
                assigned_agent="designer",
                status="done",
            ),
            TaskDefinition(
                task_id="T-02",
                description="Build UI",
                assigned_agent="engineer",
                status="done",
            ),
            TaskDefinition(
                task_id="T-03",
                description="API integration & client generation",
                assigned_agent="integration",
                status="in_progress",
            ),
        ],
    )

    deliberate = {
        ("GET", "/api/tickets"): {
            "mismatch_type": "missing_field",
            "field_name": "status",
        }
    }

    update = run_integration(
        state,
        trace_writer=tmp_trace,
        artifact_dir=tmp_artifact_dir,
        deliberate_mismatch=deliberate,
    )

    new_state = state.model_copy(update={
        "integration_report": update["integration_report"],
        "proofs": state.proofs + update["proofs"],
    })

    # Planner decide() should be called with updated blackboard
    next_agent = decide(new_state, trace_writer=tmp_trace)
    assert next_agent == "engineer"


# ---------------------------------------------------------------------------
# 5. Schema Validation Unit Tests
# ---------------------------------------------------------------------------

def test_validate_response_schema_units():
    schemas = list_schemas(DEMO_BACKEND_SPEC)
    ticket_schema = schemas["Ticket"]

    # Conforming ticket
    good = {
        "id": "TCK-1",
        "title": "Title",
        "priority": "low",
        "status": "open",
        "created_at": "2026-10-14T10:00:00Z",
    }
    mismatches = validate_response_against_schema(good, ticket_schema, schemas)
    assert len(mismatches) == 0

    # Missing required field
    missing_status = {
        "id": "TCK-1",
        "title": "Title",
        "priority": "low",
        "created_at": "2026-10-14T10:00:00Z",
    }
    m = validate_response_against_schema(missing_status, ticket_schema, schemas)
    assert len(m) == 1
    assert m[0]["issue_type"] == "missing_required_property"
    assert m[0]["field"] == "status"

    # Type mismatch
    bad_type = dict(good, id=12345)
    m2 = validate_response_against_schema(bad_type, ticket_schema, schemas)
    assert len(m2) == 1
    assert m2[0]["issue_type"] == "type_mismatch"
    assert m2[0]["field"] == "id"

    # Enum violation
    bad_enum = dict(good, priority="super-critical")
    m3 = validate_response_against_schema(bad_enum, ticket_schema, schemas)
    assert len(m3) == 1
    assert m3[0]["issue_type"] == "enum_violation"
