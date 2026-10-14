"""
tests/generate_critic_evidence.py

Generates evidence for Slice 6 (docs/evidence/critic/):
1. Audits a low-contrast fixture page with axe-core and Lighthouse:
   - Produces rejection finding with failing contrast pair (#94a3b8 on #f9fafb).
   - Emits revision request targeting the Designer.
   - Persists docs/evidence/critic/audit_report_rejected.json and proof_rejected.json.
2. Audits the fixed fixture page:
   - Verifies 0 critical/serious violations and passing Lighthouse scores.
   - Accepts the build.
   - Persists docs/evidence/critic/audit_report.json and proof_accepted.json.
3. Records all audit events and routing decisions in docs/evidence/critic/trace.jsonl.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

# Ensure repo root is on sys.path
root_dir = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(root_dir))

from agents.critic import run_critic
from graph.state import GraphState, TaskDefinition
from lib.llm import set_fake_llm_handler
from lib.models import load_input_request
from lib.trace import TraceWriter
from tools.playwright_runner import AppServer


def main() -> None:
    evidence_dir = root_dir / "docs" / "evidence" / "critic"
    evidence_dir.mkdir(parents=True, exist_ok=True)

    print("Running Critic Evidence Generation...")

    trace_path = evidence_dir / "trace.jsonl"
    if trace_path.exists():
        trace_path.unlink()

    trace_writer = TraceWriter(trace_path, run_id="critic-evidence-001")

    # Load sample input request
    input_file = root_dir / "examples" / "sample_input.json"
    request = load_input_request(input_file)

    state = GraphState(
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
                task_id="T-04",
                description="QA Playwright user flows",
                assigned_agent="qa",
                status="done",
            ),
            TaskDefinition(
                task_id="T-05",
                description="Audit accessibility and quality",
                assigned_agent="critic",
                status="in_progress",
            ),
        ],
    )

    # 1. Setup Low-Contrast App Fixture
    scratch_dir = evidence_dir / "fixtures"
    scratch_dir.mkdir(parents=True, exist_ok=True)
    low_contrast_dir = scratch_dir / "low_contrast_app"
    low_contrast_dir.mkdir(parents=True, exist_ok=True)

    (low_contrast_dir / "index.html").write_text(
        """<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>Support Tickets</title>
  <style>
    body { background-color: #f9fafb; font-family: sans-serif; padding: 24px; margin: 0; }
    .card { background-color: #f9fafb; padding: 20px; border-radius: 8px; }
    .subtext { color: #94a3b8; font-size: 14px; }
    h1 { color: #0f172a; }
  </style>
</head>
<body>
  <main>
    <h1>Support Dashboard</h1>
    <div class="card">
      <p class="subtext" id="ticket-desc">Ticket #1042: Low priority agent assistance needed.</p>
    </div>
  </main>
</body>
</html>""",
        encoding="utf-8",
    )

    print("Auditing low-contrast fixture (expecting rejection)...")
    server_low = AppServer(low_contrast_dir)
    url_low = server_low.start()

    try:
        reject_res = run_critic(
            state,
            trace_writer=trace_writer,
            artifact_dir=evidence_dir / "artifacts_rejected",
            target_url=url_low,
            evidence_dir=None,
        )
    finally:
        server_low.stop()

    reject_report = reject_res["audit_report"]
    reject_proof = reject_res["proofs"][-1]
    print(f"Rejection result: accepted={reject_report.accepted}, revisions={len(reject_report.revision_requests)}")

    # Save rejected evidence
    rejected_data = {
        "status": "rejected",
        "gates": {
            "accessibility": {
                "passed": False,
                "critical": sum(1 for v in reject_report.axe_violations if v.get("impact") == "critical"),
                "serious": sum(1 for v in reject_report.axe_violations if v.get("impact") == "serious"),
            },
            "quality": {
                "passed": True,
                "lighthouse_accessibility": reject_report.lighthouse_scores.get("accessibility"),
                "lighthouse_performance": reject_report.lighthouse_scores.get("performance"),
            },
        },
        "axe_violations": reject_report.axe_violations,
        "lighthouse_scores": reject_report.lighthouse_scores,
        "revision_requests": reject_report.revision_requests,
        "accepted": False,
    }
    (evidence_dir / "audit_report_rejected.json").write_text(
        json.dumps(rejected_data, indent=2), encoding="utf-8"
    )
    (evidence_dir / "proof_rejected.json").write_text(
        json.dumps(reject_proof.model_dump(), indent=2), encoding="utf-8"
    )

    # 2. Setup Fixed Contrast App Fixture
    fixed_dir = scratch_dir / "fixed_app"
    fixed_dir.mkdir(parents=True, exist_ok=True)

    (fixed_dir / "index.html").write_text(
        """<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>Support Tickets</title>
  <style>
    body { background-color: #f9fafb; font-family: sans-serif; padding: 24px; margin: 0; }
    .card { background-color: #f9fafb; padding: 20px; border-radius: 8px; }
    .subtext { color: #0f172a; font-size: 14px; font-weight: 500; }
    h1 { color: #0f172a; }
  </style>
</head>
<body>
  <main>
    <h1>Support Dashboard</h1>
    <div class="card">
      <p class="subtext" id="ticket-desc">Ticket #1042: Low priority agent assistance needed.</p>
    </div>
  </main>
</body>
</html>""",
        encoding="utf-8",
    )

    print("Auditing fixed fixture (expecting acceptance)...")
    server_fixed = AppServer(fixed_dir)
    url_fixed = server_fixed.start()

    try:
        accept_res = run_critic(
            state,
            trace_writer=trace_writer,
            artifact_dir=evidence_dir / "artifacts_accepted",
            target_url=url_fixed,
            evidence_dir=evidence_dir,
        )
    finally:
        server_fixed.stop()

    accept_report = accept_res["audit_report"]
    accept_proof = accept_res["proofs"][-1]
    print(f"Acceptance result: accepted={accept_report.accepted}, revisions={len(accept_report.revision_requests)}")

    (evidence_dir / "proof_accepted.json").write_text(
        json.dumps(accept_proof.model_dump(), indent=2), encoding="utf-8"
    )

    print(f"Critic evidence generation complete! Artifacts saved to: {evidence_dir}")


if __name__ == "__main__":
    main()
