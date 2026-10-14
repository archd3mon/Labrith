"""
Designer stub agent.

Reads the brief from state, produces a DesignSpec with stub tokens and
component inventory, writes a valid proof-of-work record, and returns
a state update dict.

Design Doc §3: "Chooses layout, design tokens and component inventory per page."
"""

from __future__ import annotations

from pathlib import Path
from typing import Optional

from graph.state import DesignSpec, GraphState
from lib.proofs import create_proof
from lib.trace import TraceWriter


def run_designer(
    state: GraphState,
    trace_writer: Optional[TraceWriter] = None,
    *,
    artifact_dir: Path = Path("artifacts"),
) -> dict:
    """LangGraph node for the Designer (stub).

    Returns a partial-state dict with design_spec and an appended proof.
    """
    task_id = _find_task_id(state, "designer")

    # -- Stub design output --------------------------------------------------
    design_spec = DesignSpec(
        tokens={
            "color_primary": "#1E40AF",
            "color_background": "#F9FAFB",
            "spacing_unit": "4px",
            "font_family": "Inter, sans-serif",
        },
        component_inventory={
            "Dashboard": ["NavBar", "SidePanel", "TicketList", "FilterBar"],
            "TicketDetail": ["ThreadView", "ReplyForm"],
        },
        layout_notes="Two-column layout: sidebar navigation + main content area.",
    )

    # -- Stub evidence file --------------------------------------------------
    evidence_path = artifact_dir / task_id / "design_spec.json"
    artifact_dir_path = evidence_path.parent
    artifact_dir_path.mkdir(parents=True, exist_ok=True)
    evidence_path.write_text(design_spec.model_dump_json(indent=2), encoding="utf-8")

    proof = create_proof(
        agent="designer",
        task_id=task_id,
        claim="Design spec with tokens and component inventory produced.",
        evidence=[{"type": "design_spec", "ref": str(evidence_path)}],
        reasoning=(
            "Generated stub design tokens and a two-page component inventory "
            "from the brief. Pending real LLM call in a future slice."
        ),
    )

    if trace_writer:
        trace_writer.write(
            "designer",
            "handoff",
            {"task_id": task_id, "claim": proof.claim},
        )

    return {
        "design_spec": design_spec,
        "proofs": state.proofs + [proof],
    }


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _find_task_id(state: GraphState, agent: str) -> str:
    """Return the task_id for this agent's pending task, or a default."""
    for task in (state.plan or []):
        if task.assigned_agent == agent and task.status in ("pending", "in_progress"):
            return task.task_id
    return "T-01"
