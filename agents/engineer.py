"""
Engineer stub agent.

Reads the design_spec from state, produces stub code artifacts and a build
log, writes a valid proof-of-work record, and returns a state update dict.

Supports a ``force_failure`` flag so tests can simulate a build error and
verify the planner reroutes correctly.

Design Doc §3: "Writes React, TypeScript and Tailwind code for each task."
"""

from __future__ import annotations

from pathlib import Path
from typing import Optional

from graph.state import GraphState
from lib.proofs import create_proof
from lib.trace import TraceWriter


def run_engineer(
    state: GraphState,
    trace_writer: Optional[TraceWriter] = None,
    *,
    artifact_dir: Path = Path("artifacts"),
    force_failure: bool = False,
) -> dict:
    """LangGraph node for the Engineer (stub).

    Args:
        force_failure: If True, the stub simulates a build failure.
                       The returned state has a failed task status and no
                       proof (triggering planner to reroute or escalate).
    """
    task_id = _find_task_id(state, "engineer")

    if force_failure:
        if trace_writer:
            trace_writer.write(
                "engineer",
                "build_failed",
                {"task_id": task_id, "error": "Simulated type error in ComponentA.tsx"},
            )
        # Update the task status to failed in state's plan
        updated_plan = _mark_task_failed(state, task_id)
        return {
            "plan": updated_plan,
            "code_artifacts": {
                task_id: {
                    "status": "failed",
                    "error": "Simulated type error in ComponentA.tsx",
                }
            },
        }

    # -- Stub build output ---------------------------------------------------
    build_log_path = artifact_dir / task_id / "build.log"
    build_log_path.parent.mkdir(parents=True, exist_ok=True)
    build_log_path.write_text(
        "vite build --mode production\n"
        "✓ 42 modules transformed.\n"
        "dist/index.html                    0.46 kB\n"
        "dist/assets/index-aB3c4def.js    142.33 kB\n"
        "✓ built in 1.87s\n",
        encoding="utf-8",
    )

    component_path = artifact_dir / task_id / "TicketList.tsx"
    component_path.write_text(
        "// Stub component — real implementation in Slice 2\n"
        "export const TicketList = () => <div>Tickets</div>;\n",
        encoding="utf-8",
    )

    proof = create_proof(
        agent="engineer",
        task_id=task_id,
        claim="React components built successfully; build log is clean.",
        evidence=[
            {"type": "build_log", "ref": str(build_log_path)},
            {"type": "source_file", "ref": str(component_path)},
        ],
        reasoning=(
            "Stub build succeeded. Real engineer will run npm build and attach "
            "the actual exit code in a future slice."
        ),
    )

    if trace_writer:
        trace_writer.write(
            "engineer",
            "handoff",
            {"task_id": task_id, "claim": proof.claim},
        )

    return {
        "code_artifacts": {task_id: {"status": "success", "component": str(component_path)}},
        "proofs": state.proofs + [proof],
    }


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _find_task_id(state: GraphState, agent: str) -> str:
    for task in (state.plan or []):
        if task.assigned_agent == agent and task.status in ("pending", "in_progress", "failed"):
            return task.task_id
    return "T-02"


def _mark_task_failed(state: GraphState, task_id: str):
    if not state.plan:
        return state.plan
    updated = []
    for task in state.plan:
        if task.task_id == task_id:
            updated.append(task.model_copy(update={"status": "failed"}))
        else:
            updated.append(task)
    return updated
