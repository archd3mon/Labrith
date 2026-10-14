"""
Generate a sample trace file demonstrating the trace writer in action.

Run this script to produce docs/evidence/foundations/sample_trace.jsonl.
"""

import sys
from pathlib import Path

# Ensure the project root is on the path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from lib.trace import TraceWriter, read_trace

evidence_dir = Path(__file__).resolve().parent.parent / "docs" / "evidence" / "foundations"
evidence_dir.mkdir(parents=True, exist_ok=True)
trace_path = evidence_dir / "sample_trace.jsonl"

# Remove old trace if it exists (this is a demo generator, not production code)
if trace_path.exists():
    trace_path.unlink()

tw = TraceWriter(trace_path, run_id="demo-run-001")

tw.write(agent="system", event_type="run_start", payload={
    "input_file": "examples/sample_input.json",
    "config": {"max_iterations": 3},
})

tw.write(agent="planner", event_type="routing", payload={
    "decision": "start",
    "next_agent": "designer",
    "reasoning": "Input validated; starting with design phase.",
})

tw.write(agent="designer", event_type="proof", payload={
    "task_id": "T-01",
    "claim": "Design spec produced",
    "evidence": [{"type": "spec", "ref": "artifacts/T-01/design_spec.json"}],
})

tw.write(agent="planner", event_type="routing", payload={
    "decision": "continue",
    "next_agent": "engineer",
    "reasoning": "Design spec ready; sending to engineer for implementation.",
})

tw.write(agent="engineer", event_type="proof", payload={
    "task_id": "T-02",
    "claim": "Component built and tests pass",
    "evidence": [
        {"type": "build_log", "ref": "artifacts/T-02/build.log"},
        {"type": "diff", "ref": "artifacts/T-02/component.diff"},
    ],
})

tw.write(agent="planner", event_type="routing", payload={
    "decision": "continue",
    "next_agent": "qa",
    "reasoning": "Build passed; routing to QA for flow testing.",
})

tw.write(agent="qa", event_type="proof", payload={
    "task_id": "T-03",
    "claim": "All required flows pass",
    "evidence": [
        {"type": "test_result", "ref": "artifacts/T-03/playwright.json"},
        {"type": "screenshot", "ref": "artifacts/T-03/login.png"},
    ],
})

tw.write(agent="planner", event_type="routing", payload={
    "decision": "finish",
    "reasoning": "All gates passed. Run complete.",
})

tw.write(agent="system", event_type="run_end", payload={
    "status": "accepted",
    "total_entries": tw.seq,
})

# Verify round-trip
entries = read_trace(trace_path)
print(f"Wrote {len(entries)} trace entries to {trace_path}")
for e in entries:
    print(f"  [{e.seq}] {e.agent:12s} {e.event_type:12s} {e.payload}")
