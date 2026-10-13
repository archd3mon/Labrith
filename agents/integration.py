"""
Integration stub agent.

Reads the code_artifacts from state, produces a stub IntegrationReport
(generated API client, request/response log), writes a valid proof-of-work
record, and returns a state update dict.

Design Doc §3: "Binds components to the real API with types, loading and error states."
"""

from __future__ import annotations

from pathlib import Path
from typing import Optional

from graph.state import GraphState, IntegrationReport
from lib.proofs import create_proof
from lib.trace import TraceWriter


def run_integration(
    state: GraphState,
    trace_writer: Optional[TraceWriter] = None,
    *,
    artifact_dir: Path = Path("artifacts"),
) -> dict:
    """LangGraph node for the Integration agent (stub)."""
    task_id = _find_task_id(state, "integration")

    # -- Stub API client and request log ------------------------------------
    client_path = artifact_dir / task_id / "api_client.ts"
    request_log_path = artifact_dir / task_id / "requests.log"
    client_path.parent.mkdir(parents=True, exist_ok=True)

    client_path.write_text(
        "// Stub API client — real implementation in Slice 4\n"
        "export const fetchTickets = () => fetch('/api/tickets').then(r => r.json());\n",
        encoding="utf-8",
    )
    request_log_path.write_text(
        "GET /api/tickets 200 OK\n"
        "GET /api/tickets/42 200 OK\n"
        "POST /api/tickets/42/reply 201 Created\n",
        encoding="utf-8",
    )

    integration_report = IntegrationReport(
        api_client_path=str(client_path),
        request_response_log=[
            {"method": "GET", "path": "/api/tickets", "status": 200},
            {"method": "GET", "path": "/api/tickets/42", "status": 200},
            {"method": "POST", "path": "/api/tickets/42/reply", "status": 201},
        ],
        mismatches=[],
    )

    proof = create_proof(
        agent="integration",
        task_id=task_id,
        claim="API client generated; all endpoints matched spec; no mismatches.",
        evidence=[
            {"type": "api_client", "ref": str(client_path)},
            {"type": "request_log", "ref": str(request_log_path)},
        ],
        reasoning=(
            "Stub integration: client scaffolded and three endpoints exercised "
            "against the mock server with no spec mismatches."
        ),
    )

    if trace_writer:
        trace_writer.write(
            "integration",
            "handoff",
            {"task_id": task_id, "claim": proof.claim},
        )

    return {
        "integration_report": integration_report,
        "proofs": state.proofs + [proof],
    }


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _find_task_id(state: GraphState, agent: str) -> str:
    for task in (state.plan or []):
        if task.assigned_agent == agent and task.status in ("pending", "in_progress"):
            return task.task_id
    return "T-03"
