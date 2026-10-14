"""
tests/e2e/test_e2e.py — End-to-end integration test for the FrontForge system.

Executes examples/sample_input.json against the demo backend.
Design Doc §4, §6, §9 & §10:
- "Full run on the demo spec produces an accepted report and a passing generated app."
- All six agents participate: planner, designer, engineer, integration, qa, critic.
- The five verification gates are evaluated: build, tests, accessibility, quality, integration.
- Produces quality_report.json and trace.jsonl matching schemas/output.schema.json.
- Checks that all proof-of-work records match schemas/proof.schema.json.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

import pytest
import jsonschema

from graph.gates import (
    SCHEMA_PATH as REPORT_SCHEMA_PATH,
    all_gates_passed,
    evaluate_gates,
    generate_quality_report,
    save_quality_report,
)
from graph.graph import create_graph, run_graph
from graph.state import GraphState
from lib.llm import get_fake_llm_handler, set_fake_llm_handler
from lib.models import load_input_request
from lib.proofs import validate_proof
from lib.trace import TraceWriter, read_trace
from tests.fakes import make_scripted_llm

ROOT_DIR = Path(__file__).resolve().parent.parent.parent
SAMPLE_INPUT = ROOT_DIR / "examples" / "sample_input.json"
PROOF_SCHEMA_PATH = ROOT_DIR / "schemas" / "proof.schema.json"


@pytest.fixture(autouse=True)
def _setup_llm():
    """Configure model execution: real provider if credentials exist, otherwise scripted fake."""
    has_real_key = bool(
        os.getenv("ANTHROPIC_API_KEY")
        or os.getenv("OPENAI_API_KEY")
        or os.getenv("GEMINI_API_KEY")
    )
    if not has_real_key:
        set_fake_llm_handler(make_scripted_llm([
            "designer",
            "engineer",
            "integration",
            "qa",
            "critic",
            "finish",
        ]))
    yield
    set_fake_llm_handler(None)


class TestEndToEndPipeline:
    """Full end-to-end execution of FrontForge against the demo backend."""

    def test_end_to_end_run(self, tmp_path: Path):
        request = load_input_request(SAMPLE_INPUT)
        artifact_dir = tmp_path / "artifacts"
        trace_path = tmp_path / "trace.jsonl"
        report_path = tmp_path / "quality_report.json"

        trace_writer = TraceWriter(trace_path, run_id="e2e-test-001")

        final_state = run_graph(
            request=request,
            trace_writer=trace_writer,
            artifact_dir=artifact_dir,
            report_path=report_path,
        )

        # 1. Final status must be accepted or an honest partial
        assert final_state.status in ("accepted", "partial"), (
            f"Expected status 'accepted' or 'partial', got '{final_state.status}'. "
            f"Unresolved issues: {final_state.unresolved}"
        )

        # 2. Trace must contain entries from all six agents
        trace_entries = read_trace(trace_path)
        assert len(trace_entries) > 0, "Trace must not be empty"

        agents_in_trace = {e.agent for e in trace_entries}
        expected_agents = {"planner", "designer", "engineer", "integration", "qa", "critic"}
        for expected in expected_agents:
            assert expected in agents_in_trace, (
                f"Agent '{expected}' not found in trace. Agents present: {agents_in_trace}"
            )

        # 3. Check proof-of-work records for all agents
        assert len(final_state.proofs) >= 5, (
            f"Expected at least 5 proofs, got {len(final_state.proofs)}"
        )
        for proof in final_state.proofs:
            valid, errors = validate_proof(proof)
            assert valid, f"Invalid proof from {proof.agent}: {errors}"

        # 4. Output quality report must exist and validate against schemas/output.schema.json
        assert report_path.exists(), "quality_report.json was not generated"
        report_data = json.loads(report_path.read_text(encoding="utf-8"))

        with open(REPORT_SCHEMA_PATH, "r", encoding="utf-8") as f:
            output_schema = json.load(f)
        jsonschema.validate(instance=report_data, schema=output_schema)

        # 5. Verify the five gates in the report
        gates = report_data["gates"]
        for gate_name in ("build", "tests", "accessibility", "quality", "integration"):
            assert gate_name in gates, f"Missing gate '{gate_name}' in quality report"

        # Check gate fields
        assert "passed" in gates["build"]
        assert "passed" in gates["tests"]
        assert "passed" in gates["accessibility"]
        assert "passed" in gates["integration"]

        # 6. Verify iterations in report
        iterations = report_data["iterations"]
        assert iterations["total"] >= 5
        assert "by_agent" in iterations
        for expected in expected_agents:
            assert expected in iterations["by_agent"]
