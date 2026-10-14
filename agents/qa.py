"""
QA stub agent.

Exercises stub browser flows, produces QAResults with per-flow pass/fail,
writes a valid proof-of-work record, and returns a state update dict.

Supports a ``force_failure`` flag for tests that verify the planner reroutes
when a QA flow fails.

Design Doc §3: "Runs the app in a headless browser and exercises user flows."
"""

from __future__ import annotations

from pathlib import Path
from typing import Optional

from graph.state import GraphState, QAResults
from lib.proofs import create_proof
from lib.trace import TraceWriter


def run_qa(
    state: GraphState,
    trace_writer: Optional[TraceWriter] = None,
    *,
    artifact_dir: Path = Path("artifacts"),
    force_failure: bool = False,
) -> dict:
    """LangGraph node for the QA agent (stub).

    Args:
        force_failure: If True, simulates a failing QA flow.
    """
    task_id = _find_task_id(state, "qa")

    # -- Stub screenshot and test-result files ------------------------------
    screenshots_dir = artifact_dir / task_id / "screenshots"
    screenshots_dir.mkdir(parents=True, exist_ok=True)
    screenshot_path = screenshots_dir / "login_flow.png"
    screenshot_path.write_bytes(b"PNG_STUB")

    results_path = artifact_dir / task_id / "playwright.json"

    if force_failure:
        flows = [
            {"flow": "list tickets", "passed": True},
            {"flow": "filter by priority", "passed": False, "error": "Timeout waiting for filter results"},
        ]
        results_path.write_text(
            '{"flows": [{"flow": "list tickets", "passed": true}, '
            '{"flow": "filter by priority", "passed": false}]}',
            encoding="utf-8",
        )
        qa_results = QAResults(
            flows=flows,
            screenshots=[str(screenshot_path)],
            console_logs=[],
        )

        proof = create_proof(
            agent="qa",
            task_id=task_id,
            claim="QA flows ran; 1 of 2 flows failed.",
            evidence=[
                {"type": "test_result", "ref": str(results_path)},
                {"type": "screenshot", "ref": str(screenshot_path)},
            ],
            reasoning=(
                "filter-by-priority flow timed out. Likely a missing state "
                "update in FilterBar component. Routing back to engineer."
            ),
        )

        if trace_writer:
            trace_writer.write(
                "qa",
                "flow_failed",
                {"task_id": task_id, "failing_flow": "filter by priority"},
            )

        updated_plan = _mark_task_failed(state, task_id)
        return {
            "plan": updated_plan,
            "qa_results": qa_results,
            "proofs": state.proofs + [proof],
        }

    # -- All flows pass ------------------------------------------------------
    flows = [
        {"flow": "list tickets", "passed": True},
        {"flow": "filter by priority", "passed": True},
        {"flow": "open ticket detail", "passed": True},
        {"flow": "send reply", "passed": True},
    ]
    results_path.write_text(
        '{"flows": [{"flow": "list tickets", "passed": true}, '
        '{"flow": "filter by priority", "passed": true}, '
        '{"flow": "open ticket detail", "passed": true}, '
        '{"flow": "send reply", "passed": true}]}',
        encoding="utf-8",
    )
    qa_results = QAResults(
        flows=flows,
        screenshots=[str(screenshot_path)],
        console_logs=[],
    )

    proof = create_proof(
        agent="qa",
        task_id=task_id,
        claim="All 4 required user flows passed.",
        evidence=[
            {"type": "test_result", "ref": str(results_path)},
            {"type": "screenshot", "ref": str(screenshot_path)},
        ],
        reasoning="All required flows exercised in headless Chromium; no failures.",
    )

    if trace_writer:
        trace_writer.write(
            "qa",
            "handoff",
            {"task_id": task_id, "claim": proof.claim},
        )

    return {
        "qa_results": qa_results,
        "proofs": state.proofs + [proof],
    }


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _find_task_id(state: GraphState, agent: str) -> str:
    for task in (state.plan or []):
        if task.assigned_agent == agent and task.status in ("pending", "in_progress"):
            return task.task_id
    return "T-04"


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
