"""
api/main.py — FastAPI service for FrontForge multi-agent system.

Endpoints (Design Doc §7, §8, §9 & Slice 9):
- POST /runs: Validates input, starts a run in background, returns 201 with run_id.
- GET /runs/{run_id}: Returns run status, quality report, and preview URL.
- GET /runs/{run_id}/events: Server-Sent Events (SSE) streaming trace events in real time.
- GET /runs: Lists recent runs.
- GET /health: Health check.
- Static file serving for web/dist when built.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import threading
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, AsyncGenerator, Optional
from urllib.parse import urlparse

import httpx
from fastapi import BackgroundTasks, FastAPI, HTTPException, Request, Response, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles

from graph.graph import run_graph
from lib.models import InputRequest, load_input_request
from lib.trace import TraceWriter, read_trace
from tools.openapi import DEMO_BACKEND_SPEC, load_openapi_spec

logger = logging.getLogger("frontforge.api")

ROOT_DIR = Path(__file__).resolve().parent.parent
RUNS_DIR = ROOT_DIR / "runs"
RUNS_DIR.mkdir(parents=True, exist_ok=True)
WEB_DIST_DIR = ROOT_DIR / "web" / "dist"
EXAMPLES_DIR = ROOT_DIR / "examples"

app = FastAPI(
    title="FrontForge API",
    description="Multi-agent frontend engineering system API",
    version="1.0.0",
)

# Enable CORS for frontend UI
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ---------------------------------------------------------------------------
# In-memory Run Registry & State
# ---------------------------------------------------------------------------
class RunRecord:
    def __init__(
        self,
        run_id: str,
        request: InputRequest,
        run_dir: Path,
    ) -> None:
        self.run_id = run_id
        self.request = request
        self.run_dir = run_dir
        self.artifact_dir = run_dir / "artifacts"
        self.trace_path = run_dir / "trace.jsonl"
        self.report_path = run_dir / "quality_report.json"
        self.status: str = "running"  # running, accepted, partial, failed
        self.created_at: str = datetime.now(timezone.utc).isoformat()
        self.completed_at: Optional[str] = None
        self.report: Optional[dict[str, Any]] = None
        self.preview_url: Optional[str] = None
        self.error: Optional[str] = None
        self.is_terminal: bool = False

    def to_dict(self) -> dict[str, Any]:
        return {
            "run_id": self.run_id,
            "status": self.status,
            "created_at": self.created_at,
            "completed_at": self.completed_at,
            "report": self.report,
            "preview_url": self.preview_url,
            "error": self.error,
        }


# Global runs registry
RUNS: dict[str, RunRecord] = {}
RUNS_LOCK = threading.Lock()


def get_run_record(run_id: str) -> Optional[RunRecord]:
    """Retrieve run record from memory or reconstruct from disk if exists."""
    with RUNS_LOCK:
        if run_id in RUNS:
            return RUNS[run_id]

    # Reconstruct from disk if present
    run_dir = RUNS_DIR / run_id
    if run_dir.exists() and (run_dir / "trace.jsonl").exists():
        # Read quality_report if present
        report_path = run_dir / "quality_report.json"
        report_data = None
        run_status = "unknown"
        preview_url = None
        if report_path.exists():
            try:
                report_data = json.loads(report_path.read_text(encoding="utf-8"))
                run_status = report_data.get("status", "accepted")
                preview_url = report_data.get("preview_url")
            except Exception:
                run_status = "completed"

        dummy_request = InputRequest(
            brief="Historical run loaded from disk",
            api_spec_url="https://demo-backend.example.com/openapi.json",
            target="dashboard",
        )
        record = RunRecord(run_id=run_id, request=dummy_request, run_dir=run_dir)
        record.status = run_status
        record.report = report_data
        record.preview_url = preview_url
        record.is_terminal = True
        with RUNS_LOCK:
            RUNS[run_id] = record
        return record

    return None


# ---------------------------------------------------------------------------
# Background Worker
# ---------------------------------------------------------------------------
def _execute_run_worker(
    record: RunRecord,
    agent_overrides: Optional[dict[str, Any]] = None,
) -> None:
    """Executes the multi-agent graph in a background thread."""
    try:
        # Fall back to scripted multi-agent simulation if no provider keys are set
        has_real_key = bool(
            os.getenv("ANTHROPIC_API_KEY")
            or os.getenv("OPENAI_API_KEY")
            or os.getenv("GEMINI_API_KEY")
        )
        if not has_real_key:
            from lib.llm import set_fake_llm_handler
            from tests.fakes import make_scripted_llm
            set_fake_llm_handler(
                make_scripted_llm([
                    "designer",
                    "engineer",
                    "integration",
                    "qa",
                    "critic",
                    "finish",
                ])
            )

        record.artifact_dir.mkdir(parents=True, exist_ok=True)

        trace_writer = TraceWriter(record.trace_path, run_id=record.run_id)

        final_state = run_graph(
            request=record.request,
            trace_writer=trace_writer,
            artifact_dir=record.artifact_dir,
            agent_overrides=agent_overrides,
            report_path=record.report_path,
        )

        report_data = None
        if record.report_path.exists():
            try:
                report_data = json.loads(record.report_path.read_text(encoding="utf-8"))
            except Exception as e:
                logger.warning("Failed to parse quality_report.json: %s", e)

        if report_data is None:
            from graph.gates import generate_quality_report
            report_data = generate_quality_report(final_state, run_id=record.run_id)

        with RUNS_LOCK:
            record.report = report_data
            record.preview_url = report_data.get("preview_url") if isinstance(report_data, dict) else None
            record.status = final_state.status
    except Exception as exc:
        logger.exception("Run %s failed with error: %s", record.run_id, exc)
        with RUNS_LOCK:
            record.status = "failed"
            record.error = str(exc)
    finally:
        with RUNS_LOCK:
            record.is_terminal = True
            record.completed_at = datetime.now(timezone.utc).isoformat()


# ---------------------------------------------------------------------------
# Spec Validation Helper
# ---------------------------------------------------------------------------
def validate_spec_reachability(api_spec_url: Any) -> None:
    """Validate OpenAPI spec reachability or structure before starting agents."""
    if isinstance(api_spec_url, dict):
        if not api_spec_url:
            raise ValueError("Inline OpenAPI spec dictionary cannot be empty.")
        return

    if isinstance(api_spec_url, str):
        parsed = urlparse(api_spec_url)
        if parsed.scheme not in ("http", "https"):
            # Check if it's a valid local file path or JSON string
            if Path(api_spec_url).exists():
                return
            try:
                data = json.loads(api_spec_url)
                if isinstance(data, dict):
                    return
            except json.JSONDecodeError:
                pass
            raise ValueError(
                f"Invalid OpenAPI spec URL scheme '{parsed.scheme}'. Must be 'http' or 'https'."
            )

        # Allow demo example.com domain (offline mock)
        if "example.com" in parsed.netloc:
            return

        # Attempt to reach remote URL
        try:
            with httpx.Client(timeout=3.0, follow_redirects=True) as client:
                resp = client.get(api_spec_url)
                if resp.status_code >= 400:
                    raise ValueError(
                        f"OpenAPI spec URL returned HTTP status {resp.status_code}: {api_spec_url}"
                    )
                # Ensure response is valid JSON
                try:
                    resp.json()
                except Exception:
                    raise ValueError(f"OpenAPI spec at {api_spec_url} is not valid JSON.")
        except httpx.RequestError as exc:
            raise ValueError(
                f"Failed to reach OpenAPI spec URL ({api_spec_url}): {exc}"
            ) from exc


# ---------------------------------------------------------------------------
# API Routes
# ---------------------------------------------------------------------------
@app.get("/health")
def health_check() -> dict[str, str]:
    """Health check endpoint."""
    return {"status": "ok", "service": "FrontForge API"}


@app.get("/runs")
def list_runs() -> list[dict[str, Any]]:
    """List all runs."""
    with RUNS_LOCK:
        return [record.to_dict() for record in RUNS.values()]


@app.get("/api/sample-input")
def get_sample_input() -> dict[str, Any]:
    """Return the demo sample_input.json for quick frontend testing."""
    sample_file = EXAMPLES_DIR / "sample_input.json"
    if sample_file.exists():
        return json.loads(sample_file.read_text(encoding="utf-8"))
    return {
        "brief": "A support dashboard where agents view open tickets, filter by priority, open a ticket to read its history, and reply.",
        "api_spec_url": "https://demo-backend.example.com/openapi.json",
        "target": "dashboard",
        "style_hints": ["minimal", "data-dense"],
        "required_flows": ["list tickets", "filter by priority", "open ticket detail", "send reply"],
        "max_iterations": 3,
    }


@app.post("/runs", status_code=status.HTTP_201_CREATED)
async def create_run(
    request: Request,
    background_tasks: BackgroundTasks,
) -> dict[str, Any]:
    """Validate input, initiate a new agentic run, and return run_id.

    Returns HTTP 400 with itemised errors on invalid input or unreachable spec,
    starting NO agents.
    """
    try:
        body = await request.json()
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Malformed JSON in request body: {exc}",
        )

    # 1. Schema & Pydantic validation
    try:
        validated_request = load_input_request(body)
    except (ValueError, TypeError) as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(exc),
        )

    # 2. OpenAPI spec reachability & validity check
    try:
        validate_spec_reachability(validated_request.api_spec_url)
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"OpenAPI spec validation failed: {exc}",
        )

    # 3. Create run directory and record
    run_id = f"run-{uuid.uuid4().hex[:8]}"
    run_dir = RUNS_DIR / run_id
    run_dir.mkdir(parents=True, exist_ok=True)

    record = RunRecord(
        run_id=run_id,
        request=validated_request,
        run_dir=run_dir,
    )

    with RUNS_LOCK:
        RUNS[run_id] = record

    # Check for test-provided agent overrides in headers/body
    agent_overrides = body.get("_agent_overrides")

    # Start multi-agent execution in background thread
    worker_thread = threading.Thread(
        target=_execute_run_worker,
        args=(record, agent_overrides),
        daemon=True,
    )
    worker_thread.start()

    return {
        "run_id": run_id,
        "status": "running",
        "message": "Run initiated successfully",
        "created_at": record.created_at,
    }


@app.get("/runs/{run_id}")
def get_run(run_id: str) -> dict[str, Any]:
    """Retrieve run status, preview link, and quality report."""
    record = get_run_record(run_id)
    if not record:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Run '{run_id}' not found.",
        )
    return record.to_dict()


@app.get("/runs/{run_id}/events")
async def stream_run_events(run_id: str) -> StreamingResponse:
    """Stream trace events in real time using Server-Sent Events (SSE)."""
    record = get_run_record(run_id)
    if not record:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Run '{run_id}' not found.",
        )

    async def event_generator() -> AsyncGenerator[str, None]:
        trace_path = record.trace_path
        line_offset = 0

        # Initial keepalive
        yield ": connected\n\n"

        while True:
            # Read any new lines from the trace file
            if trace_path.exists():
                with open(trace_path, "r", encoding="utf-8") as f:
                    lines = f.readlines()
                    if len(lines) > line_offset:
                        for line in lines[line_offset:]:
                            stripped = line.strip()
                            if stripped:
                                yield f"event: trace\ndata: {stripped}\n\n"
                        line_offset = len(lines)

            # Check if run has finished and all trace entries streamed
            if record.is_terminal:
                # One last pass to ensure all lines read
                if trace_path.exists():
                    with open(trace_path, "r", encoding="utf-8") as f:
                        lines = f.readlines()
                        if len(lines) > line_offset:
                            for line in lines[line_offset:]:
                                stripped = line.strip()
                                if stripped:
                                    yield f"event: trace\ndata: {stripped}\n\n"
                            line_offset = len(lines)

                # Send completion event
                end_payload = {
                    "run_id": record.run_id,
                    "status": record.status,
                    "completed_at": record.completed_at,
                    "preview_url": record.preview_url,
                    "report": record.report,
                    "error": record.error,
                }
                yield f"event: end\ndata: {json.dumps(end_payload)}\n\n"
                break

            await asyncio.sleep(0.3)

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


# ---------------------------------------------------------------------------
# Mount Static Frontend (if built)
# ---------------------------------------------------------------------------
if WEB_DIST_DIR.exists():
    app.mount("/", StaticFiles(directory=str(WEB_DIST_DIR), html=True), name="static")
