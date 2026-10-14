"""
tests/unit/test_gates.py — Unit tests for the five verification gates and quality report.

Design Doc §6 ("Verification gates a build must pass before the Planner accepts it"):
  1. Build gate: npm run build and the type checker exit cleanly.
  2. Test gate: generated app's own unit tests pass, and every required user flow passes.
  3. Accessibility gate: no critical or serious axe-core violations.
  4. Quality gate: Lighthouse performance and accessibility above threshold.
  5. Integration gate: every API call in client matches spec, or mismatches documented.

Design Doc §9 & schemas/output.schema.json:
  Validates output quality_report.json against output.schema.json.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
import jsonschema

from graph.gates import (
    all_gates_passed,
    evaluate_accessibility_gate,
    evaluate_build_gate,
    evaluate_gates,
    evaluate_integration_gate,
    evaluate_quality_gate,
    evaluate_tests_gate,
    generate_quality_report,
    save_quality_report,
    validate_quality_report,
    SCHEMA_PATH,
)
from graph.state import (
    AuditReport,
    DesignSpec,
    GraphState,
    IntegrationReport,
    QAResults,
    TaskDefinition,
    UnresolvedIssue,
)
from lib.models import AgentName, EvidenceItem, InputRequest, ProofOfWork, TargetType


@pytest.fixture
def base_request() -> InputRequest:
    return InputRequest(
        brief="A support dashboard for tickets.",
        api_spec_url="https://demo-backend.example.com/openapi.json",
        target=TargetType.DASHBOARD,
        required_flows=["list tickets", "filter by priority"],
    )


@pytest.fixture
def empty_state(base_request: InputRequest) -> GraphState:
    return GraphState(request=base_request)


# ---------------------------------------------------------------------------
# Test Gate 1: Build Gate
# ---------------------------------------------------------------------------

class TestBuildGate:
    def test_build_gate_passed_via_code_artifacts(self, empty_state: GraphState):
        state = empty_state.model_copy(update={
            "code_artifacts": {
                "T-02": {
                    "status": "success",
                    "build_log": "artifacts/T-02/build.log",
                }
            }
        })
        res = evaluate_build_gate(state)
        assert res["passed"] is True
        assert res.get("evidence") == "artifacts/T-02/build.log"

    def test_build_gate_failed_when_error(self, empty_state: GraphState):
        state = empty_state.model_copy(update={
            "code_artifacts": {
                "T-02": {
                    "status": "failed",
                    "error": "TypeScript compile error",
                }
            }
        })
        res = evaluate_build_gate(state)
        assert res["passed"] is False

    def test_build_gate_passed_via_proof(self, empty_state: GraphState):
        from lib.proofs import create_proof
        proof = create_proof(
            agent="engineer",
            task_id="T-02",
            claim="React component built cleanly and passed.",
            evidence=[{"type": "build_log", "ref": "runs/app/build.log"}],
            reasoning="npm run build exit 0",
        )
        state = empty_state.model_copy(update={"proofs": [proof]})
        res = evaluate_build_gate(state)
        assert res["passed"] is True
        assert res.get("evidence") == "runs/app/build.log"


# ---------------------------------------------------------------------------
# Test Gate 2: Tests Gate
# ---------------------------------------------------------------------------

class TestTestsGate:
    def test_tests_gate_all_flows_passed(self, empty_state: GraphState):
        qa_results = QAResults(
            flows=[
                {"flow": "list tickets", "passed": True},
                {"flow": "filter by priority", "passed": True},
            ]
        )
        state = empty_state.model_copy(update={"qa_results": qa_results})
        res = evaluate_tests_gate(state)
        assert res["passed"] is True
        assert res["flows_passed"] == 2
        assert res["flows_total"] == 2

    def test_tests_gate_failed_flow(self, empty_state: GraphState):
        qa_results = QAResults(
            flows=[
                {"flow": "list tickets", "passed": True},
                {"flow": "filter by priority", "passed": False},
            ]
        )
        state = empty_state.model_copy(update={"qa_results": qa_results})
        res = evaluate_tests_gate(state)
        assert res["passed"] is False
        assert res["flows_passed"] == 1
        assert res["flows_total"] == 2


# ---------------------------------------------------------------------------
# Test Gate 3: Accessibility Gate
# ---------------------------------------------------------------------------

class TestAccessibilityGate:
    def test_accessibility_gate_clean_audit(self, empty_state: GraphState):
        audit = AuditReport(
            axe_violations=[],
            lighthouse_scores={"accessibility": 96.0, "performance": 88.0},
            accepted=True,
        )
        state = empty_state.model_copy(update={"audit_report": audit})
        res = evaluate_accessibility_gate(state)
        assert res["passed"] is True
        assert res["critical"] == 0
        assert res["serious"] == 0

    def test_accessibility_gate_failing_violations(self, empty_state: GraphState):
        audit = AuditReport(
            axe_violations=[
                {"id": "color-contrast", "impact": "serious", "help": "Contrast"},
                {"id": "button-name", "impact": "critical", "help": "Name"},
            ],
            accepted=False,
        )
        state = empty_state.model_copy(update={"audit_report": audit})
        res = evaluate_accessibility_gate(state)
        assert res["passed"] is False
        assert res["critical"] == 1
        assert res["serious"] == 1


# ---------------------------------------------------------------------------
# Test Gate 4: Quality Gate
# ---------------------------------------------------------------------------

class TestQualityGate:
    def test_quality_gate_scores(self, empty_state: GraphState):
        audit = AuditReport(
            axe_violations=[],
            lighthouse_scores={"accessibility": 95.5, "performance": 85.0},
            accepted=True,
        )
        state = empty_state.model_copy(update={"audit_report": audit})
        res = evaluate_quality_gate(state)
        assert res["lighthouse_accessibility"] == 95.5
        assert res["lighthouse_performance"] == 85.0


# ---------------------------------------------------------------------------
# Test Gate 5: Integration Gate
# ---------------------------------------------------------------------------

class TestIntegrationGate:
    def test_integration_gate_clean(self, empty_state: GraphState):
        report = IntegrationReport(
            api_client_path="artifacts/client.ts",
            mismatches=[],
            passed=True,
        )
        state = empty_state.model_copy(update={"integration_report": report})
        res = evaluate_integration_gate(state)
        assert res["passed"] is True
        assert res["documented_mismatches"] == 0

    def test_integration_gate_documented_mismatches(self, empty_state: GraphState):
        report = IntegrationReport(
            api_client_path="artifacts/client.ts",
            mismatches=[{"path": "/api/tickets", "type": "missing_field"}],
            passed=True,
        )
        state = empty_state.model_copy(update={"integration_report": report})
        res = evaluate_integration_gate(state)
        assert res["passed"] is True
        assert res["documented_mismatches"] == 1


# ---------------------------------------------------------------------------
# Master Evaluator & Quality Report
# ---------------------------------------------------------------------------

class TestMasterGatesAndReport:
    def test_evaluate_gates_structure(self, empty_state: GraphState):
        gates = evaluate_gates(empty_state)
        assert "build" in gates
        assert "tests" in gates
        assert "accessibility" in gates
        assert "quality" in gates
        assert "integration" in gates

    def test_all_gates_passed_checker(self):
        passing_gates = {
            "build": {"passed": True},
            "tests": {"passed": True, "flows_passed": 2, "flows_total": 2},
            "accessibility": {"passed": True, "critical": 0, "serious": 0},
            "quality": {"lighthouse_accessibility": 95.0, "lighthouse_performance": 85.0},
            "integration": {"passed": True, "documented_mismatches": 0},
        }
        assert all_gates_passed(passing_gates) is True

        failing_gates = dict(passing_gates)
        failing_gates["build"] = {"passed": False}
        assert all_gates_passed(failing_gates) is False

    def test_generate_quality_report_strictly_matches_schema(
        self, base_request: InputRequest, tmp_path: Path
    ):
        # Build accepted state
        qa_results = QAResults(
            flows=[
                {"flow": "list tickets", "passed": True},
                {"flow": "filter by priority", "passed": True},
            ]
        )
        audit = AuditReport(
            axe_violations=[],
            lighthouse_scores={"accessibility": 95.0, "performance": 88.0},
            accepted=True,
        )
        integration = IntegrationReport(mismatches=[], passed=True)
        code_artifacts = {
            "T-02": {"status": "success", "build_log": "runs/build.log"},
            "preview_url": "https://labrith-demo.test",
        }
        from lib.proofs import create_proof
        proofs = [
            create_proof(agent="planner", task_id="T-00", claim="Plan", evidence=[{"type": "plan", "ref": "plan.json"}], reasoning="Plan ok"),
            create_proof(agent="designer", task_id="T-01", claim="Design", evidence=[{"type": "spec", "ref": "spec.json"}], reasoning="Design ok"),
            create_proof(agent="engineer", task_id="T-02", claim="React component built cleanly and passed.", evidence=[{"type": "build_log", "ref": "runs/build.log"}], reasoning="Build ok"),
            create_proof(agent="integration", task_id="T-03", claim="API integrated", evidence=[{"type": "client", "ref": "client.ts"}], reasoning="Integration ok"),
            create_proof(agent="qa", task_id="T-04", claim="QA flows passed", evidence=[{"type": "test_result", "ref": "qa.json"}], reasoning="QA ok"),
            create_proof(agent="critic", task_id="T-05", claim="Audit accepted", evidence=[{"type": "audit", "ref": "audit.json"}], reasoning="Critic ok"),
        ]

        state = GraphState(
            request=base_request,
            status="accepted",
            qa_results=qa_results,
            audit_report=audit,
            integration_report=integration,
            code_artifacts=code_artifacts,
            proofs=proofs,
            iteration_counters={"run_total": 6},
        )

        report = generate_quality_report(state, run_id="run-0001")

        # Validate against schemas/output.schema.json
        assert SCHEMA_PATH.exists()
        validate_quality_report(report)

        # Check fields
        assert report["run_id"] == "run-0001"
        assert report["status"] == "accepted"
        assert report["iterations"]["total"] == 6
        assert report["gates"]["build"]["passed"] is True
        assert report["gates"]["tests"]["passed"] is True
        assert report["gates"]["accessibility"]["passed"] is True
        assert report["gates"]["integration"]["passed"] is True
        assert report["preview_url"] == "https://labrith-demo.test"

        # Save and verify file
        out_file = tmp_path / "quality_report.json"
        save_quality_report(report, out_file)
        assert out_file.exists()
        loaded = json.loads(out_file.read_text(encoding="utf-8"))
        assert loaded["run_id"] == "run-0001"

    def test_generate_quality_report_partial_and_unresolved(self, base_request: InputRequest):
        state = GraphState(
            request=base_request,
            status="partial",
            iteration_counters={"run_total": 5},
            unresolved=[
                UnresolvedIssue(
                    issue="Playwright test failed on flow 'login'",
                    evidence="artifacts/qa/error.log",
                    agent="qa",
                )
            ],
        )

        report = generate_quality_report(state, run_id="run-partial-001")
        validate_quality_report(report)

        assert report["status"] == "partial"
        assert len(report["unresolved"]) == 1
        assert report["unresolved"][0]["issue"] == "Playwright test failed on flow 'login'"
        assert report["unresolved"][0]["evidence"] == "artifacts/qa/error.log"
        assert "agent" not in report["unresolved"][0]  # additionalProperties: false
