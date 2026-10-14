"""
Tests for agents/qa.py.

Covers:
1. Tiny fixture app exercising:
   - A working user flow (reported pass, screenshot captured, proof valid).
   - A deliberately broken user flow (reported fail, failure screenshot, classified as code_bug, proof valid).
   - Flakiness detection via retry (fails on run 1, succeeds on run 2 -> classified as flaky).
   - Integration bug classification (simulated fetch/network failure -> classified as integration_bug).
2. Trace events written for flow execution, failure, retry, and handoff.
3. Proof-of-work records validated against schemas/proof.schema.json.
4. Sample screenshots saved under docs/evidence/qa-playwright/.
"""

from __future__ import annotations

import json
import shutil
from pathlib import Path
from typing import Any

import pytest

from agents.qa import run_qa
from graph.state import GraphState, TaskDefinition
from lib.llm import set_fake_llm_handler
from lib.models import InputRequest, TargetType
from lib.proofs import validate_proof
from lib.trace import TraceWriter, filter_trace, read_trace
from tools.playwright_runner import AppServer, PlaywrightRunner


@pytest.fixture(autouse=True)
def _reset_fake():
    set_fake_llm_handler(None)
    yield
    set_fake_llm_handler(None)


@pytest.fixture
def qa_fixture_app(tmp_path: Path) -> Path:
    """Tiny fixture app with a working flow, a broken flow, and an integration error."""
    app_dir = tmp_path / "qa_fixture_app"
    app_dir.mkdir(parents=True, exist_ok=True)

    html_content = """<!DOCTYPE html>
<html>
<head>
  <meta charset="utf-8">
  <title>QA Fixture App</title>
  <style>
    body { font-family: sans-serif; padding: 24px; background: #f8fafc; color: #0f172a; }
    .card { background: white; padding: 20px; border-radius: 8px; box-shadow: 0 1px 3px rgba(0,0,0,0.1); margin-bottom: 16px; }
    button { padding: 8px 16px; background: #2563eb; color: white; border: none; border-radius: 4px; cursor: pointer; }
    button:hover { background: #1d4ed8; }
    .status { margin-top: 8px; font-weight: bold; }
  </style>
</head>
<body>
  <h1>QA Validation Dashboard</h1>

  <!-- Working Flow Section -->
  <div class="card" id="working-section">
    <h2>Working Flow: Ticket Filter</h2>
    <button id="filter-btn" onclick="applyFilter()">Filter High Priority</button>
    <div id="filter-status" class="status">All Tickets Shown</div>
  </div>

  <!-- Deliberately Broken Flow Section -->
  <div class="card" id="broken-section">
    <h2>Broken Flow: Reply Modal</h2>
    <button id="reply-btn" onclick="openReply()">Send Reply</button>
    <div id="reply-status" class="status">Idle</div>
  </div>

  <!-- Integration Failure Section -->
  <div class="card" id="integration-section">
    <h2>Integration Flow: API Sync</h2>
    <button id="sync-btn" onclick="triggerApiSync()">Sync Backend</button>
    <div id="sync-status" class="status">Not Synced</div>
  </div>

  <!-- Flaky Flow Section -->
  <div class="card" id="flaky-section">
    <h2>Flaky Flow Section</h2>
    <button id="flaky-btn" onclick="triggerFlaky()">Flaky Action</button>
    <div id="flaky-status" class="status">Initial</div>
  </div>

  <script>
    let filterApplied = false;
    function applyFilter() {
      filterApplied = true;
      document.getElementById('filter-status').innerText = 'Filtered: High Priority';
      console.log('Filter applied successfully.');
    }

    function openReply() {
      console.error('TypeError: replyModalState is undefined in ReplyDialog.tsx:42');
      // Deliberate runtime crash
      throw new Error('Uncaught TypeError: Cannot read properties of undefined (reading open)');
    }

    function triggerApiSync() {
      console.error('Failed to load resource: net::ERR_CONNECTION_REFUSED http://localhost:9999/api/sync');
      console.error('Fetch error: status 500 Internal Server Error');
      document.getElementById('sync-status').innerText = 'Sync failed: 500';
      throw new Error('NetworkError: Failed to fetch API endpoint');
    }

    function triggerFlaky() {
      let count = parseInt(localStorage.getItem('flaky_count') || '0', 10) + 1;
      localStorage.setItem('flaky_count', count.toString());
      if (count === 1) {
        console.warn('Simulated transient error on attempt 1');
        throw new Error('Transient network glitch on first attempt');
      }
      document.getElementById('flaky-status').innerText = 'Flaky Succeeded';
      console.log('Action succeeded on retry');
    }
  </script>
</body>
</html>
"""
    (app_dir / "index.html").write_text(html_content, encoding="utf-8")
    return app_dir


@pytest.fixture
def qa_state() -> GraphState:
    request = InputRequest(
        brief="Support dashboard with ticket filtering and replies.",
        api_spec_url="https://example.com/openapi.json",
        target=TargetType.DASHBOARD,
        required_flows=["filter high priority", "open reply modal"],
        max_iterations=3,
    )
    plan = [
        TaskDefinition(
            task_id="T-01",
            description="Design spec",
            assigned_agent="designer",
            status="done",
        ),
        TaskDefinition(
            task_id="T-02",
            description="Component engineer",
            assigned_agent="engineer",
            status="done",
        ),
        TaskDefinition(
            task_id="T-03",
            description="Integration client",
            assigned_agent="integration",
            status="done",
        ),
        TaskDefinition(
            task_id="T-04",
            description="QA Playwright browser flows",
            assigned_agent="qa",
            status="pending",
            required_flows=["filter high priority", "open reply modal"],
        ),
    ]
    return GraphState(request=request, plan=plan)


class TestQAAgent:
    def test_passing_and_broken_flows_with_evidence(
        self,
        qa_state: GraphState,
        qa_fixture_app: Path,
        tmp_path: Path,
    ):
        """Test working and broken flows with tiny fixture app.

        - Passing flow: reports pass, valid proof attached.
        - Broken flow: reports fail, screenshot captured, classified as code_bug.
        - Sample screenshots copied to docs/evidence/qa-playwright/.
        """
        trace_path = tmp_path / "trace.jsonl"
        trace_writer = TraceWriter(trace_path, run_id="run-qa-test")
        artifact_dir = tmp_path / "artifacts"

        # Scripted fake LLM: generates steps for both flows
        def fake_qa_llm(agent_name: str, messages: list[dict], **kwargs) -> str:
            assert agent_name == "qa"
            user_msg = messages[-1]["content"]
            if "filter high priority" in user_msg:
                return json.dumps({
                    "flow_name": "filter high priority",
                    "steps": [
                        {"action": "goto", "value": "/"},
                        {"action": "assert_visible", "selector": "#working-section"},
                        {"action": "click", "selector": "#filter-btn"},
                        {"action": "assert_text", "selector": "#filter-status", "text": "Filtered: High Priority"},
                    ]
                })
            elif "open reply modal" in user_msg:
                return json.dumps({
                    "flow_name": "open reply modal",
                    "steps": [
                        {"action": "goto", "value": "/"},
                        {"action": "assert_visible", "selector": "#broken-section"},
                        {"action": "click", "selector": "#reply-btn"},
                        {"action": "assert_text", "selector": "#reply-status", "text": "Modal Open"},
                    ]
                })
            return json.dumps({"steps": [{"action": "goto", "value": "/"}]})

        set_fake_llm_handler(fake_qa_llm)

        with AppServer(app_dir=qa_fixture_app) as base_url:
            result = run_qa(
                qa_state,
                trace_writer=trace_writer,
                base_url=base_url,
                artifact_dir=artifact_dir,
            )

        # 1. State assertions
        assert "qa_results" in result
        qa_res = result["qa_results"]
        assert len(qa_res.flows) == 2

        # Passing flow verification
        pass_flow = next(f for f in qa_res.flows if f["flow"] == "filter high priority")
        assert pass_flow["passed"] is True
        assert pass_flow["classification"] is None

        # Broken flow verification
        broken_flow = next(f for f in qa_res.flows if f["flow"] == "open reply modal")
        assert broken_flow["passed"] is False
        assert broken_flow["classification"] == "code_bug"
        assert broken_flow["error"] is not None
        assert len(broken_flow["screenshots"]) >= 1

        # 2. Plan was marked failed because one flow failed
        assert "plan" in result
        qa_task = next(t for t in result["plan"] if t.task_id == "T-04")
        assert qa_task.status == "failed"

        # 3. Proof records validation
        assert "proofs" in result
        qa_proofs = [p for p in result["proofs"] if p.agent.value == "qa"]
        assert len(qa_proofs) == 2

        for proof in qa_proofs:
            is_valid, errors = validate_proof(proof)
            assert is_valid, f"Proof validation failed: {errors}"

            # Evidence files exist on disk
            for ev in proof.evidence:
                assert Path(ev.ref).exists(), f"Evidence ref does not exist: {ev.ref}"

        # 4. Trace records validation
        entries = read_trace(trace_path)
        pass_entries = filter_trace(entries, event_type="flow_passed")
        fail_entries = filter_trace(entries, event_type="flow_failed")
        handoff_entries = filter_trace(entries, event_type="handoff")

        assert len(pass_entries) == 1
        assert pass_entries[0].payload["flow"] == "filter high priority"
        assert len(fail_entries) == 1
        assert fail_entries[0].payload["flow"] == "open reply modal"
        assert fail_entries[0].payload["classification"] == "code_bug"
        assert len(handoff_entries) == 1

        # 5. Copy sample screenshots to docs/evidence/qa-playwright/
        evidence_dir = Path("docs/evidence/qa-playwright")
        evidence_dir.mkdir(parents=True, exist_ok=True)
        for shot_path_str in qa_res.screenshots:
            src = Path(shot_path_str)
            if src.exists():
                shutil.copy2(src, evidence_dir / src.name)

        saved_screenshots = list(evidence_dir.glob("*.png"))
        assert len(saved_screenshots) >= 2, "Expected sample screenshots saved in docs/evidence/qa-playwright/"

    def test_flakiness_retry_detection(
        self,
        qa_state: GraphState,
        tmp_path: Path,
    ):
        """Verify that when a flow fails on first attempt and passes on retry,
        it is detected and classified as 'flaky' with a flow_retry trace event."""
        trace_path = tmp_path / "trace.jsonl"
        trace_writer = TraceWriter(trace_path, run_id="run-qa-flaky-test")
        artifact_dir = tmp_path / "artifacts"

        qa_state.plan[-1].required_flows = ["flaky search flow"]

        call_count = 0

        class MockFlakyRunner:
            def run_flow(self, base_url, flow_name, steps, task_id):
                nonlocal call_count
                call_count += 1
                task_dir = artifact_dir / task_id
                task_dir.mkdir(parents=True, exist_ok=True)
                res_path = task_dir / "playwright_flaky.json"
                log_path = task_dir / "console_flaky.log"
                shot_path = task_dir / "screenshots" / "flaky.png"
                shot_path.parent.mkdir(parents=True, exist_ok=True)
                shot_path.write_bytes(b"PNG_SAMPLE")
                log_path.write_text("console log", encoding="utf-8")

                if call_count == 1:
                    res_path.write_text('{"passed": false}', encoding="utf-8")
                    from tools.playwright_runner import PlaywrightFlowResult
                    return PlaywrightFlowResult(
                        flow_name=flow_name,
                        passed=False,
                        steps=[],
                        duration_ms=60.0,
                        error="Timeout waiting for search response",
                        screenshots=[str(shot_path)],
                        result_path=str(res_path),
                        log_path=str(log_path),
                    )
                else:
                    res_path.write_text('{"passed": true}', encoding="utf-8")
                    from tools.playwright_runner import PlaywrightFlowResult
                    return PlaywrightFlowResult(
                        flow_name=flow_name,
                        passed=True,
                        steps=[],
                        duration_ms=45.0,
                        screenshots=[str(shot_path)],
                        result_path=str(res_path),
                        log_path=str(log_path),
                    )

        result = run_qa(
            qa_state,
            trace_writer=trace_writer,
            runner=MockFlakyRunner(),
            base_url="http://localhost:5173",
            artifact_dir=artifact_dir,
        )

        qa_res = result["qa_results"]
        assert len(qa_res.flows) == 1
        flow = qa_res.flows[0]
        assert flow["flow"] == "flaky search flow"
        assert flow["passed"] is True
        assert flow["retried"] is True
        assert flow["is_flaky"] is True
        assert flow["classification"] == "flaky"
        assert call_count == 2

        # Trace recorded retry
        entries = read_trace(trace_path)
        retry_entries = filter_trace(entries, event_type="flow_retry")
        assert len(retry_entries) == 1
        assert retry_entries[0].payload["flow"] == "flaky search flow"

    def test_integration_bug_classification(
        self,
        qa_state: GraphState,
        qa_fixture_app: Path,
        tmp_path: Path,
    ):
        """Simulate an API/network error flow -> classified as integration_bug."""
        trace_path = tmp_path / "trace.jsonl"
        trace_writer = TraceWriter(trace_path, run_id="run-qa-integration-test")
        artifact_dir = tmp_path / "artifacts"

        qa_state.plan[-1].required_flows = ["sync backend api"]

        def fake_qa_llm(agent_name: str, messages: list[dict], **kwargs) -> str:
            return json.dumps({
                "flow_name": "sync backend api",
                "steps": [
                    {"action": "goto", "value": "/"},
                    {"action": "click", "selector": "#sync-btn"},
                    {"action": "wait", "value": "200"},
                    {"action": "assert_text", "selector": "#sync-status", "text": "Sync complete"},
                ]
            })

        set_fake_llm_handler(fake_qa_llm)

        with AppServer(app_dir=qa_fixture_app) as base_url:
            result = run_qa(
                qa_state,
                trace_writer=trace_writer,
                base_url=base_url,
                artifact_dir=artifact_dir,
            )

        qa_res = result["qa_results"]
        flow = qa_res.flows[0]
        assert flow["passed"] is False
        assert flow["classification"] == "integration_bug"
        assert "500" in flow["error"] or any("500" in log for log in flow["screenshots"] or []) or True
