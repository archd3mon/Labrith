"""
Tests for tools/playwright_runner.py.

Covers:
1. Server lifecycle with AppServer (clean startup, responsiveness, teardown).
2. Passing browser flow execution (steps, text assertions, screenshots, results JSON).
3. Failing browser flow execution (missing element, step failure, failure screenshot).
4. Browser console log & error capture (console.error, unhandled page errors).
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from tools.playwright_runner import AppServer, PlaywrightRunner, find_free_port


@pytest.fixture
def tiny_fixture_app(tmp_path: Path) -> Path:
    """Create a tiny HTML app for runner tests."""
    app_dir = tmp_path / "tiny_app"
    app_dir.mkdir(parents=True, exist_ok=True)

    html_content = """<!DOCTYPE html>
<html>
<head>
  <title>Test Runner App</title>
</head>
<body>
  <h1 id="title">Welcome to Test App</h1>
  <button id="counter-btn" onclick="increment()">Clicks: 0</button>
  <button id="error-btn" onclick="triggerError()">Trigger Error</button>
  <div id="output">Initial</div>

  <script>
    let count = 0;
    function increment() {
      count++;
      document.getElementById('counter-btn').innerText = 'Clicks: ' + count;
      document.getElementById('output').innerText = 'Updated: ' + count;
      console.log('Counter incremented to ' + count);
    }

    function triggerError() {
      console.error('Deliberate console error triggered');
      throw new Error('Uncaught runtime exception in test app');
    }
  </script>
</body>
</html>
"""
    (app_dir / "index.html").write_text(html_content, encoding="utf-8")
    return app_dir


class TestAppServer:
    def test_find_free_port(self):
        port = find_free_port()
        assert isinstance(port, int)
        assert 1024 <= port <= 65535

    def test_app_server_lifecycle(self, tiny_fixture_app: Path):
        server = AppServer(app_dir=tiny_fixture_app)
        base_url = server.start()
        try:
            assert base_url.startswith("http://localhost:")
            assert server.proc is not None
            assert server.proc.poll() is None
        finally:
            server.stop()
        assert server.proc is None or server.proc.poll() is not None


class TestPlaywrightRunner:
    def test_run_passing_flow(self, tiny_fixture_app: Path, tmp_path: Path):
        artifact_dir = tmp_path / "artifacts"
        runner = PlaywrightRunner(artifact_dir=artifact_dir, headless=True)

        with AppServer(app_dir=tiny_fixture_app) as base_url:
            steps = [
                {"action": "goto", "value": "/"},
                {"action": "assert_visible", "selector": "#title"},
                {"action": "assert_text", "selector": "#title", "text": "Welcome to Test App"},
                {"action": "click", "selector": "#counter-btn"},
                {"action": "assert_text", "selector": "#counter-btn", "text": "Clicks: 1"},
                {"action": "assert_text", "selector": "#output", "text": "Updated: 1"},
            ]

            result = runner.run_flow(
                base_url=base_url,
                flow_name="click counter",
                steps=steps,
                task_id="T-TEST-PASS",
            )

        assert result.passed is True
        assert result.error is None
        assert len(result.steps) == 6
        assert all(s.status == "passed" for s in result.steps)

        # Artifacts verification
        assert result.result_path is not None
        assert Path(result.result_path).exists()
        assert result.log_path is not None
        assert Path(result.log_path).exists()
        assert len(result.screenshots) >= 1
        assert all(Path(s).exists() for s in result.screenshots)

        # Content verification in result JSON
        data = json.loads(Path(result.result_path).read_text(encoding="utf-8"))
        assert data["passed"] is True
        assert data["flow_name"] == "click counter"

        # Console log recorded
        log_content = Path(result.log_path).read_text(encoding="utf-8")
        assert "Counter incremented to 1" in log_content

    def test_run_failing_flow_missing_selector(self, tiny_fixture_app: Path, tmp_path: Path):
        artifact_dir = tmp_path / "artifacts"
        runner = PlaywrightRunner(artifact_dir=artifact_dir, headless=True)

        with AppServer(app_dir=tiny_fixture_app) as base_url:
            steps = [
                {"action": "goto", "value": "/"},
                {"action": "click", "selector": "#non-existent-button", "timeout_ms": 1500},
            ]

            result = runner.run_flow(
                base_url=base_url,
                flow_name="missing element flow",
                steps=steps,
                task_id="T-TEST-FAIL",
            )

        assert result.passed is False
        assert result.error is not None
        assert "Timeout" in result.error or "waiting for" in result.error
        assert len(result.steps) == 2
        assert result.steps[0].status == "passed"
        assert result.steps[1].status == "failed"

        # Failure screenshot captured and on disk
        assert len(result.screenshots) >= 1
        assert all(Path(s).exists() for s in result.screenshots)

    def test_console_error_and_page_error_capture(self, tiny_fixture_app: Path, tmp_path: Path):
        artifact_dir = tmp_path / "artifacts"
        runner = PlaywrightRunner(artifact_dir=artifact_dir, headless=True)

        with AppServer(app_dir=tiny_fixture_app) as base_url:
            steps = [
                {"action": "goto", "value": "/"},
                {"action": "click", "selector": "#error-btn"},
                {"action": "wait", "value": "300"},
            ]

            result = runner.run_flow(
                base_url=base_url,
                flow_name="trigger error flow",
                steps=steps,
                task_id="T-TEST-ERROR",
            )

        # Console logs and page errors recorded
        assert any("Deliberate console error" in log for log in result.console_logs)
        assert any("Uncaught runtime exception" in err for err in result.page_errors)

        log_content = Path(result.log_path).read_text(encoding="utf-8")
        assert "Deliberate console error" in log_content
