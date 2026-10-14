"""
Tests for agents/critic.py, tools/axe_runner.py, and tools/lighthouse_runner.py.

Covers:
1. Fixture page with known contrast violation:
   - Critic rejects build (accessibility gate fails).
   - Revision request emitted targeting the Designer with the failing colour pair (#94a3b8 on #f9fafb).
2. Fixed fixture page:
   - Contrast resolved to compliant ratio (#0f172a on #f9fafb).
   - Critic accepts build (accessibility and quality gates pass).
   - Audit report saved to docs/evidence/critic/audit_report.json.
3. Conflict case (Design Doc §5 Scenario 5):
   - QA passed, but Critic rejects because accessibility gate failed.
   - Trace records conflict_detected event.
4. Engineer targeting:
   - Markup/button accessibility failure targets engineer.
5. Vision review integration:
   - Screenshot reviewed via multimodal complete() call.
6. Proof-of-work validation:
   - Proof records validated against schemas/proof.schema.json.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from agents.critic import run_critic
from graph.state import GraphState, QAResults, TaskDefinition
from lib.llm import set_fake_llm_handler
from lib.models import InputRequest, TargetType
from lib.proofs import validate_proof
from lib.trace import TraceWriter, read_trace
from tools.axe_runner import AxeRunner, parse_axe_results
from tools.lighthouse_runner import LighthouseRunner, compute_scores_from_metrics
from tools.playwright_runner import AppServer


@pytest.fixture(autouse=True)
def _clear_llm():
    """Reset fake LLM handler before and after each test."""
    set_fake_llm_handler(None)
    yield
    set_fake_llm_handler(None)


@pytest.fixture
def sample_request() -> InputRequest:
    return InputRequest(
        brief="A ticket support dashboard.",
        api_spec_url="https://demo-backend.example.com/openapi.json",
        target=TargetType.DASHBOARD,
        required_flows=["list tickets"],
        max_iterations=3,
    )


@pytest.fixture
def sample_state(sample_request: InputRequest) -> GraphState:
    return GraphState(
        request=sample_request,
        plan=[
            TaskDefinition(
                task_id="T-01",
                description="Design UI",
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
                description="Run Playwright flows",
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


@pytest.fixture
def low_contrast_fixture(tmp_path: Path) -> Path:
    """Fixture HTML directory with a deliberate WCAG AA contrast failure."""
    app_dir = tmp_path / "low_contrast_app"
    app_dir.mkdir(parents=True, exist_ok=True)

    index_html = """<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>Support Dashboard</title>
  <style>
    body {
      background-color: #f9fafb;
      font-family: sans-serif;
      margin: 0;
      padding: 24px;
    }
    .card {
      background-color: #f9fafb;
      padding: 20px;
      border-radius: 8px;
    }
    .failing-text {
      color: #94a3b8; /* Insufficient contrast ratio ~2.45:1 against #f9fafb */
      font-size: 14px;
      font-weight: 400;
    }
    h1 {
      color: #0f172a;
    }
  </style>
</head>
<body>
  <main>
    <h1>Support Tickets</h1>
    <div class="card">
      <p class="failing-text" id="status-message">Ticket #1042 status: pending review by support specialist.</p>
    </div>
  </main>
</body>
</html>
"""
    (app_dir / "index.html").write_text(index_html, encoding="utf-8")
    return app_dir


@pytest.fixture
def fixed_contrast_fixture(tmp_path: Path) -> Path:
    """Fixture HTML directory where contrast violation is fixed to WCAG AA compliance."""
    app_dir = tmp_path / "fixed_contrast_app"
    app_dir.mkdir(parents=True, exist_ok=True)

    index_html = """<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>Support Dashboard</title>
  <style>
    body {
      background-color: #f9fafb;
      font-family: sans-serif;
      margin: 0;
      padding: 24px;
    }
    .card {
      background-color: #f9fafb;
      padding: 20px;
      border-radius: 8px;
    }
    .compliant-text {
      color: #0f172a; /* High contrast > 13:1 against #f9fafb */
      font-size: 14px;
      font-weight: 500;
    }
    h1 {
      color: #0f172a;
    }
  </style>
</head>
<body>
  <main>
    <h1>Support Tickets</h1>
    <div class="card">
      <p class="compliant-text" id="status-message">Ticket #1042 status: pending review by support specialist.</p>
    </div>
  </main>
</body>
</html>
"""
    (app_dir / "index.html").write_text(index_html, encoding="utf-8")
    return app_dir


# ===========================================================================
# 1. Contrast Violation Fixture & Fix Tests
# ===========================================================================

def test_critic_rejects_known_contrast_violation_and_targets_designer(
    sample_state: GraphState,
    low_contrast_fixture: Path,
    tmp_path: Path,
):
    """When auditing a page with low contrast, Critic rejects and targets the Designer."""
    trace_path = tmp_path / "trace.jsonl"
    tw = TraceWriter(trace_path, run_id="critic-contrast-reject-run")

    server = AppServer(low_contrast_fixture)
    server_url = server.start()

    try:
        result = run_critic(
            sample_state,
            trace_writer=tw,
            artifact_dir=tmp_path / "artifacts",
            target_url=server_url,
            evidence_dir=tmp_path / "evidence",
        )
    finally:
        server.stop()

    audit_report = result["audit_report"]
    assert audit_report.accepted is False, "Critic should reject low-contrast build"

    # Verify accessibility gate failed
    violations = audit_report.axe_violations
    assert len(violations) > 0
    contrast_violation = next((v for v in violations if v["id"] == "color-contrast"), None)
    assert contrast_violation is not None
    assert contrast_violation["impact"] in ("serious", "critical")

    # Verify revision requests
    assert len(audit_report.revision_requests) >= 1
    rev = next((r for r in audit_report.revision_requests if r["target_agent"] == "designer"), None)
    assert rev is not None, "Revision request must target the Designer"
    assert rev["to"] == "designer"
    assert "contrast" in rev["reason"].lower() or "contrast" in rev["finding"].lower()

    # Verify failing colour pair is included
    failing_pair = rev.get("failing_pair")
    assert failing_pair is not None, "Failing colour pair must be included"
    assert failing_pair["foreground"].lower() == "#94a3b8"
    assert failing_pair["background"].lower() == "#f9fafb"

    # Verify Proof-of-Work
    proof = result["proofs"][-1]
    assert proof.agent == "critic"
    assert "rejected" in proof.claim.lower()
    validate_proof(proof)

    # Verify trace handoff
    events = read_trace(trace_path)
    handoff = next((e for e in events if e.event_type == "handoff"), None)
    assert handoff is not None
    assert handoff.payload["accepted"] is False


def test_critic_accepts_when_contrast_fixed(
    sample_state: GraphState,
    fixed_contrast_fixture: Path,
    tmp_path: Path,
):
    """After fixing the contrast violation, Critic accepts the build and saves report."""
    trace_path = tmp_path / "trace.jsonl"
    tw = TraceWriter(trace_path, run_id="critic-fixed-accept-run")
    evidence_dir = Path("docs/evidence/critic")
    evidence_dir.mkdir(parents=True, exist_ok=True)

    server = AppServer(fixed_contrast_fixture)
    server_url = server.start()

    try:
        result = run_critic(
            sample_state,
            trace_writer=tw,
            artifact_dir=tmp_path / "artifacts",
            target_url=server_url,
            evidence_dir=evidence_dir,
        )
    finally:
        server.stop()

    audit_report = result["audit_report"]
    assert audit_report.accepted is True, "Critic must accept when contrast is compliant"
    assert len(audit_report.revision_requests) == 0

    # Verify no critical or serious violations
    for v in audit_report.axe_violations:
        assert v.get("impact") not in ("critical", "serious")

    # Verify lighthouse scores meet quality thresholds
    scores = audit_report.lighthouse_scores
    assert scores["accessibility"] >= 90.0
    assert scores["performance"] >= 80.0

    # Verify audit report file was saved under docs/evidence/critic/
    evidence_file = evidence_dir / "audit_report.json"
    assert evidence_file.exists(), f"Expected audit report at {evidence_file}"
    saved_data = json.loads(evidence_file.read_text(encoding="utf-8"))
    assert saved_data["accepted"] is True
    assert saved_data["gates"]["accessibility"]["passed"] is True
    assert saved_data["gates"]["quality"]["passed"] is True

    # Verify Proof-of-Work
    proof = result["proofs"][-1]
    assert proof.agent == "critic"
    assert "accepted" in proof.claim.lower()
    validate_proof(proof)


# ===========================================================================
# 2. Conflict Case (Design Doc §5 Scenario 5)
# ===========================================================================

def test_critic_rejects_build_even_when_qa_passed(
    sample_state: GraphState,
    low_contrast_fixture: Path,
    tmp_path: Path,
):
    """Critic can reject a build even when QA reported all flows passing."""
    # QA reports 100% passing flows
    sample_state.qa_results = QAResults(
        flows=[
            {"flow_name": "list tickets", "passed": True},
            {"flow_name": "filter by priority", "passed": True},
        ],
        screenshots=["artifacts/T-04/ticket_list.png"],
        console_logs=["artifacts/T-04/console.log"],
    )

    trace_path = tmp_path / "trace.jsonl"
    tw = TraceWriter(trace_path, run_id="critic-qa-conflict-run")

    server = AppServer(low_contrast_fixture)
    server_url = server.start()

    try:
        result = run_critic(
            sample_state,
            trace_writer=tw,
            artifact_dir=tmp_path / "artifacts",
            target_url=server_url,
            evidence_dir=tmp_path / "evidence",
        )
    finally:
        server.stop()

    audit_report = result["audit_report"]
    # Critic holds acceptance and rejects
    assert audit_report.accepted is False

    # Check trace for conflict resolution event
    events = read_trace(trace_path)
    conflict_event = next((e for e in events if e.event_type == "conflict_detected"), None)
    assert conflict_event is not None
    assert conflict_event.payload["qa_passed"] is True
    assert conflict_event.payload["priority"] == "accessibility"
    assert conflict_event.payload["action"] == "hold_acceptance"


# ===========================================================================
# 3. Engineer Targeting on Structural Violations
# ===========================================================================

def test_critic_targets_engineer_on_markup_violations(
    sample_state: GraphState,
    tmp_path: Path,
):
    """When axe finds structural/markup violations (e.g. missing button label), targets engineer."""
    app_dir = tmp_path / "broken_markup_app"
    app_dir.mkdir(parents=True, exist_ok=True)
    (app_dir / "index.html").write_text(
        """<!DOCTYPE html>
<html lang="en">
<head><title>App</title><meta name="viewport" content="width=device-width"></head>
<body>
  <main>
    <h1>Title</h1>
    <!-- Button with no text or accessible name -->
    <button id="empty-button" onclick="alert(1)"></button>
  </main>
</body>
</html>""",
        encoding="utf-8",
    )

    server = AppServer(app_dir)
    server_url = server.start()

    try:
        result = run_critic(
            sample_state,
            artifact_dir=tmp_path / "artifacts",
            target_url=server_url,
            evidence_dir=tmp_path / "evidence",
        )
    finally:
        server.stop()

    audit_report = result["audit_report"]
    assert audit_report.accepted is False

    # Find button-name violation
    button_rev = next(
        (r for r in audit_report.revision_requests if r["target_agent"] == "engineer"),
        None,
    )
    assert button_rev is not None, "Must emit revision request to engineer for button-name violation"
    assert button_rev["to"] == "engineer"


# ===========================================================================
# 4. Vision Review and Runner Unit Tests
# ===========================================================================

def test_critic_vision_review(sample_state: GraphState, tmp_path: Path):
    """Vision review integrates with screenshot and records trace event."""
    screenshot_file = tmp_path / "app_preview.png"
    screenshot_file.write_bytes(b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR" + b"\x00" * 50)

    sample_state.qa_results = QAResults(
        flows=[{"flow_name": "home", "passed": True}],
        screenshots=[str(screenshot_file)],
    )

    vision_called = False

    def fake_llm(agent_name: str, messages: list[dict], **kwargs):
        nonlocal vision_called
        if agent_name == "critic":
            vision_called = True
            return "Visual review: Layout is well-structured; header alignment conforms to design spec."
        return "ok"

    set_fake_llm_handler(fake_llm)

    trace_path = tmp_path / "trace.jsonl"
    tw = TraceWriter(trace_path, run_id="critic-vision-run")

    result = run_critic(
        sample_state,
        trace_writer=tw,
        artifact_dir=tmp_path / "artifacts",
        vision_enabled=True,
    )

    assert vision_called is True
    events = read_trace(trace_path)
    vision_event = next((e for e in events if e.event_type == "vision_review"), None)
    assert vision_event is not None
    assert "Visual review" in vision_event.payload["review"]


def test_axe_runner_direct_evaluation(low_contrast_fixture: Path):
    """AxeRunner parses violations and extracts failing pairs correctly."""
    server = AppServer(low_contrast_fixture)
    url = server.start()

    try:
        runner = AxeRunner()
        result = runner.run(url)
    finally:
        server.stop()

    assert result.passed_gate is False
    assert result.serious_count >= 1

    contrast = next((v for v in result.violations if v.id == "color-contrast"), None)
    assert contrast is not None
    assert contrast.failing_pair is not None
    assert contrast.failing_pair["foreground"].lower() == "#94a3b8"
    assert contrast.failing_pair["background"].lower() == "#f9fafb"


def test_lighthouse_runner_scoring():
    """LighthouseRunner computes normalized scores and evaluates thresholds."""
    metrics = {
        "fcp_ms": 320,
        "load_time_ms": 450,
        "has_title": True,
        "has_lang": True,
        "has_viewport": True,
        "images_without_alt": 0,
        "buttons_without_text": 0,
    }

    scores, audits = compute_scores_from_metrics(metrics)
    assert scores.performance >= 90.0
    assert scores.accessibility == 100.0

    # With serious axe violations
    penalized_scores, _ = compute_scores_from_metrics(metrics, axe_serious_count=2)
    assert penalized_scores.accessibility <= 75.0
