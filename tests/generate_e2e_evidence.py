"""
tests/generate_e2e_evidence.py — Generates unedited raw trace and quality report for docs/evidence/end-to-end/.

Task:
  Run examples/sample_input.json against the demo backend.
  Produce docs/evidence/end-to-end/trace.jsonl and docs/evidence/end-to-end/quality_report.json.
  Verify handoffs among all six agents and evaluate the five gates.
"""

from __future__ import annotations

import json
import os
import shutil
import sys
from pathlib import Path

# Ensure repo root is on sys.path
root_dir = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(root_dir))

from graph.gates import (
    all_gates_passed,
    evaluate_gates,
    generate_quality_report,
    save_quality_report,
    validate_quality_report,
)
from graph.graph import run_graph
from lib.llm import set_fake_llm_handler
from lib.models import load_input_request
from lib.trace import TraceWriter, read_trace
from tests.fakes import make_scripted_llm


def main() -> None:
    evidence_dir = root_dir / "docs" / "evidence" / "end-to-end"
    evidence_dir.mkdir(parents=True, exist_ok=True)

    print("=================================================================")
    print("  FrontForge End-to-End Run — Full Agent Graph & Gates Execution")
    print("=================================================================")

    trace_path = evidence_dir / "trace.jsonl"
    report_path = evidence_dir / "quality_report.json"
    artifact_dir = evidence_dir / "artifacts"
    artifact_dir.mkdir(parents=True, exist_ok=True)

    if trace_path.exists():
        trace_path.unlink()
    if report_path.exists():
        report_path.unlink()

    run_id = "frontforge-e2e-run-001"
    trace_writer = TraceWriter(trace_path, run_id=run_id)

    # Load sample input request
    input_file = root_dir / "examples" / "sample_input.json"
    request = load_input_request(input_file)
    print(f"Loaded request: {request.brief}")
    print(f"Target: {request.target}, Required Flows: {request.required_flows}")

    # Set scripted LLM if no API key is in environment
    has_real_key = bool(
        os.getenv("ANTHROPIC_API_KEY")
        or os.getenv("OPENAI_API_KEY")
        or os.getenv("GEMINI_API_KEY")
    )
    if not has_real_key:
        print("Using scripted agent handler (no provider API key set in .env)")
        set_fake_llm_handler(make_scripted_llm([
            "designer",
            "engineer",
            "integration",
            "qa",
            "critic",
            "finish",
        ]))
    else:
        print("Using configured real LLM provider")

    # Execute supervisor graph
    print("\nRunning LangGraph supervisor loop...")
    final_state = run_graph(
        request=request,
        trace_writer=trace_writer,
        artifact_dir=artifact_dir,
        report_path=report_path,
    )

    print(f"\nGraph execution finished!")
    print(f"Final State Status: {final_state.status}")
    print(f"Accepted Proofs Count: {len(final_state.proofs)}")

    # Read and inspect trace
    trace_entries = read_trace(trace_path)
    agents_in_trace = {e.agent for e in trace_entries}
    print(f"Trace events logged: {len(trace_entries)}")
    print(f"Agents participating in trace: {sorted(agents_in_trace)}")

    # Read quality report
    report_data = json.loads(report_path.read_text(encoding="utf-8"))
    validate_quality_report(report_data)

    print("\n----------------- Verification Gate Results -----------------")
    for gate_name, gate_info in report_data.get("gates", {}).items():
        print(f"  * Gate '{gate_name}': {gate_info}")

    print("\n----------------- Quality Report Summary --------------------")
    print(f"  Run ID: {report_data.get('run_id')}")
    print(f"  Status: {report_data.get('status')}")
    print(f"  Iterations: {report_data.get('iterations')}")
    print(f"  Unresolved issues: {len(report_data.get('unresolved', []))}")
    if report_data.get("revisions"):
        print(f"  Revisions: {report_data.get('revisions')}")

    print("\nArtifacts saved in docs/evidence/end-to-end/:")
    for f in sorted(evidence_dir.iterdir()):
        if f.is_file():
            print(f"  - {f.name} ({f.stat().st_size} bytes)")

    print("\n[SUCCESS] End-to-end evidence generation complete.")


if __name__ == "__main__":
    main()
