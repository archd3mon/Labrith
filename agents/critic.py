"""
Critic stub agent.

Audits the generated app for accessibility (axe-core violations) and quality
(Lighthouse scores), produces an AuditReport, writes a valid proof-of-work
record, and returns a state update dict.

Design Doc §3: "Audits WCAG compliance and visual/UX quality; sends concrete
revision requests."
"""

from __future__ import annotations

from pathlib import Path
from typing import Optional

from graph.state import AuditReport, GraphState
from lib.proofs import create_proof
from lib.trace import TraceWriter


def run_critic(
    state: GraphState,
    trace_writer: Optional[TraceWriter] = None,
    *,
    artifact_dir: Path = Path("artifacts"),
) -> dict:
    """LangGraph node for the Critic (stub)."""
    task_id = _find_task_id(state, "critic")

    # -- Stub audit report files ---------------------------------------------
    report_path = artifact_dir / task_id / "audit_report.json"
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(
        '{"axe_violations": [], "lighthouse": {"accessibility": 97, "performance": 89}}',
        encoding="utf-8",
    )

    audit_report = AuditReport(
        axe_violations=[],
        lighthouse_scores={"accessibility": 97.0, "performance": 89.0},
        revision_requests=[],
        accepted=True,
    )

    proof = create_proof(
        agent="critic",
        task_id=task_id,
        claim="No critical axe violations; Lighthouse accessibility 97, performance 89. Build accepted.",
        evidence=[{"type": "audit_report", "ref": str(report_path)}],
        reasoning=(
            "Stub audit: no violations found, all Lighthouse scores above thresholds. "
            "Real axe-core and Lighthouse execution in Slice 5."
        ),
    )

    if trace_writer:
        trace_writer.write(
            "critic",
            "handoff",
            {"task_id": task_id, "accepted": True, "claim": proof.claim},
        )

    return {
        "audit_report": audit_report,
        "proofs": state.proofs + [proof],
    }


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _find_task_id(state: GraphState, agent: str) -> str:
    for task in (state.plan or []):
        if task.assigned_agent == agent and task.status in ("pending", "in_progress"):
            return task.task_id
    return "T-05"
