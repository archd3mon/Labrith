"""
tests/generate_integration_evidence.py

Generates sample logs, mismatch reports, and proofs for docs/evidence/integration/:
1. Matching responses producing a clean report (0 mismatches).
2. Deliberately mismatched response producing a documented mismatch report
   and a request to the planner to involve the engineer.
3. Appends all trace events to docs/evidence/integration/trace.jsonl.
"""

from __future__ import annotations

import json
import shutil
import sys
from pathlib import Path

# Ensure repo root is on sys.path
root_dir = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(root_dir))

from agents.integration import run_integration
from graph.state import GraphState, TaskDefinition
from lib.llm import set_fake_llm_handler
from lib.models import EvidenceItem, load_input_request
from lib.trace import TraceWriter


def main() -> None:
    evidence_dir = root_dir / "docs" / "evidence" / "integration"
    evidence_dir.mkdir(parents=True, exist_ok=True)

    print("Generating Integration Agent Evidence...")

    trace_path = evidence_dir / "trace.jsonl"
    if trace_path.exists():
        trace_path.unlink()

    trace_writer = TraceWriter(trace_path, run_id="integration-evidence-001")

    # Load sample input request
    input_file = root_dir / "examples" / "sample_input.json"
    request = load_input_request(input_file)

    base_state = GraphState(
        request=request,
        plan=[
            TaskDefinition(
                task_id="T-01",
                description="Design tokens and inventory",
                assigned_agent="designer",
                status="done",
            ),
            TaskDefinition(
                task_id="T-02",
                description="Implement components",
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

    # -----------------------------------------------------------------------
    # Run 1: Clean Matching Run
    # -----------------------------------------------------------------------
    print("1. Running clean matching integration...")
    clean_artifact_dir = evidence_dir / "scratch_clean"
    clean_artifact_dir.mkdir(parents=True, exist_ok=True)

    clean_res = run_integration(
        base_state,
        trace_writer=trace_writer,
        artifact_dir=clean_artifact_dir,
    )

    clean_report = clean_res["integration_report"]
    clean_proof = clean_res["proofs"][-1]

    # Copy / save clean evidence artifacts
    task_clean_dir = clean_artifact_dir / "T-03"
    shutil.copyfile(task_clean_dir / "api_client.ts", evidence_dir / "api_client.ts")
    shutil.copyfile(task_clean_dir / "requests.log", evidence_dir / "requests_matching.log")
    shutil.copyfile(task_clean_dir / "mismatch_report.json", evidence_dir / "mismatch_report_clean.json")

    clean_proof_model = clean_proof.model_copy(update={
        "evidence": [
            EvidenceItem(type="api_client", ref="docs/evidence/integration/api_client.ts"),
            EvidenceItem(type="request_log", ref="docs/evidence/integration/requests_matching.log"),
            EvidenceItem(type="mismatch_report", ref="docs/evidence/integration/mismatch_report_clean.json"),
        ]
    })
    (evidence_dir / "proof_clean.json").write_text(clean_proof_model.model_dump_json(indent=2), encoding="utf-8")

    print(f"   Clean run completed: {len(clean_report.request_response_log)} calls, {len(clean_report.mismatches)} mismatches.")

    # -----------------------------------------------------------------------
    # Run 2: Mismatched Run (Breaking Contract -> Involve Engineer)
    # -----------------------------------------------------------------------
    print("2. Running mismatched integration with missing 'status' field...")
    mismatch_artifact_dir = evidence_dir / "scratch_mismatched"
    mismatch_artifact_dir.mkdir(parents=True, exist_ok=True)

    def fake_llm(agent_name: str, messages: list[dict], **kwargs) -> str:
        if agent_name == "integration":
            return json.dumps({
                "decision": "involve_engineer",
                "claim": "Spec mismatch detected: missing required property 'status'; requesting planner to involve engineer.",
                "reasoning": (
                    "The backend API omits the required 'status' property in tickets list. "
                    "Component Engineer must update TicketCard presentation and fallback error boundary."
                ),
            })
        return "{}"

    set_fake_llm_handler(fake_llm)

    deliberate = {
        ("GET", "/api/tickets"): {
            "mismatch_type": "missing_field",
            "field_name": "status",
        }
    }

    mismatched_res = run_integration(
        base_state,
        trace_writer=trace_writer,
        artifact_dir=mismatch_artifact_dir,
        deliberate_mismatch=deliberate,
    )

    mismatched_report = mismatched_res["integration_report"]
    mismatched_proof = mismatched_res["proofs"][-1]

    # Copy / save mismatched evidence artifacts
    task_mismatched_dir = mismatch_artifact_dir / "T-03"
    shutil.copyfile(task_mismatched_dir / "requests.log", evidence_dir / "requests_mismatched.log")
    shutil.copyfile(task_mismatched_dir / "mismatch_report.json", evidence_dir / "mismatch_report_mismatched.json")

    mismatched_proof_model = mismatched_proof.model_copy(update={
        "evidence": [
            EvidenceItem(type="api_client", ref="docs/evidence/integration/api_client.ts"),
            EvidenceItem(type="request_log", ref="docs/evidence/integration/requests_mismatched.log"),
            EvidenceItem(type="mismatch_report", ref="docs/evidence/integration/mismatch_report_mismatched.json"),
        ]
    })
    (evidence_dir / "proof_mismatched.json").write_text(mismatched_proof_model.model_dump_json(indent=2), encoding="utf-8")

    print(f"   Mismatched run completed: {len(mismatched_report.mismatches)} mismatch(es) detected.")
    print(f"   Planner action requested: {mismatched_report.planner_action}")

    # Clean up scratch folders
    shutil.rmtree(clean_artifact_dir, ignore_errors=True)
    shutil.rmtree(mismatch_artifact_dir, ignore_errors=True)

    print(f"\nAll evidence successfully written to {evidence_dir}:")
    for f in sorted(evidence_dir.iterdir()):
        print(f" - {f.name} ({f.stat().st_size} bytes)")


if __name__ == "__main__":
    main()
