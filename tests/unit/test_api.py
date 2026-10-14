"""
tests/unit/test_api.py — Unit tests for the FrontForge FastAPI API.

Covers:
- POST /runs with invalid input returns clear 400/4xx and starts NO agents:
  - Missing brief
  - Missing api_spec_url
  - Missing target
  - Invalid target enum
  - Invalid max_iterations (< 1)
  - Malformed JSON
  - Invalid spec scheme
  - Unreachable remote spec URL
- POST /runs with valid input:
  - Returns 201 with run_id and status 'running'
- GET /runs/{run_id}:
  - Returns 200 with run status, report, and preview link
  - Returns 404 for unknown run_id
- GET /runs/{run_id}/events:
  - Returns 200 text/event-stream streaming trace entries
  - Concludes with event: end
  - Returns 404 for unknown run_id
- GET /health and GET /runs
"""

from __future__ import annotations

import json
import time
from pathlib import Path
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

from api.main import RUNS, app
from lib.llm import set_fake_llm_handler
from tests.fakes import make_scripted_llm


@pytest.fixture
def client():
    """Create a FastAPI test client."""
    return TestClient(app)


@pytest.fixture(autouse=True)
def _setup_fake_llm():
    """Ensure tests run with scripted fake LLM handler."""
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
    yield
    set_fake_llm_handler(None)


def _valid_payload() -> dict:
    return {
        "brief": "A dashboard for support agents to manage tickets.",
        "api_spec_url": "https://demo-backend.example.com/openapi.json",
        "target": "dashboard",
        "style_hints": ["minimal", "dark"],
        "required_flows": ["list tickets", "filter by priority"],
        "max_iterations": 2,
    }


# ===========================================================================
# 1. Invalid input validation tests (Must return clear 4xx, start NO agents)
# ===========================================================================
class TestAPIInputValidation:
    def test_missing_brief_returns_400(self, client: TestClient):
        initial_count = len(RUNS)
        payload = _valid_payload()
        del payload["brief"]

        response = client.post("/runs", json=payload)
        assert response.status_code == 400
        assert "brief" in response.json()["detail"].lower()
        # Ensure no agent/run was started
        assert len(RUNS) == initial_count

    def test_missing_api_spec_url_returns_400(self, client: TestClient):
        initial_count = len(RUNS)
        payload = _valid_payload()
        del payload["api_spec_url"]

        response = client.post("/runs", json=payload)
        assert response.status_code == 400
        assert "api_spec_url" in response.json()["detail"].lower()
        assert len(RUNS) == initial_count

    def test_missing_target_returns_400(self, client: TestClient):
        initial_count = len(RUNS)
        payload = _valid_payload()
        del payload["target"]

        response = client.post("/runs", json=payload)
        assert response.status_code == 400
        assert "target" in response.json()["detail"].lower()
        assert len(RUNS) == initial_count

    def test_invalid_target_enum_returns_400(self, client: TestClient):
        initial_count = len(RUNS)
        payload = _valid_payload()
        payload["target"] = "native_ios_app"

        response = client.post("/runs", json=payload)
        assert response.status_code == 400
        assert "target" in response.json()["detail"].lower()
        assert len(RUNS) == initial_count

    def test_invalid_max_iterations_returns_400(self, client: TestClient):
        initial_count = len(RUNS)
        payload = _valid_payload()
        payload["max_iterations"] = 0

        response = client.post("/runs", json=payload)
        assert response.status_code == 400
        assert "max_iterations" in response.json()["detail"].lower()
        assert len(RUNS) == initial_count

    def test_invalid_spec_url_scheme_returns_400(self, client: TestClient):
        initial_count = len(RUNS)
        payload = _valid_payload()
        payload["api_spec_url"] = "ftp://invalid-scheme.com/openapi.json"

        response = client.post("/runs", json=payload)
        assert response.status_code == 400
        assert "scheme" in response.json()["detail"].lower()
        assert len(RUNS) == initial_count

    def test_unreachable_spec_url_returns_400(self, client: TestClient):
        initial_count = len(RUNS)
        payload = _valid_payload()
        payload["api_spec_url"] = "http://localhost:59999/non_existent_spec.json"

        response = client.post("/runs", json=payload)
        assert response.status_code == 400
        assert "failed to reach openapi spec url" in response.json()["detail"].lower()
        assert len(RUNS) == initial_count

    def test_malformed_json_returns_400(self, client: TestClient):
        initial_count = len(RUNS)
        response = client.post(
            "/runs",
            content="{ invalid-json-syntax }",
            headers={"Content-Type": "application/json"},
        )
        assert response.status_code == 400
        assert len(RUNS) == initial_count


# ===========================================================================
# 2. Valid run lifecycle tests
# ===========================================================================
class TestAPIRunLifecycle:
    def test_health_check(self, client: TestClient):
        response = client.get("/health")
        assert response.status_code == 200
        assert response.json()["status"] == "ok"

    def test_sample_input_endpoint(self, client: TestClient):
        response = client.get("/api/sample-input")
        assert response.status_code == 200
        data = response.json()
        assert "brief" in data
        assert "api_spec_url" in data
        assert data["target"] in ("dashboard", "form_app", "mixed")

    def test_nonexistent_run_returns_404(self, client: TestClient):
        response = client.get("/runs/run-nonexistent-12345")
        assert response.status_code == 404
        assert "not found" in response.json()["detail"].lower()

    def test_nonexistent_run_events_returns_404(self, client: TestClient):
        response = client.get("/runs/run-nonexistent-12345/events")
        assert response.status_code == 404

    def test_successful_run_flow(self, client: TestClient):
        payload = _valid_payload()
        response = client.post("/runs", json=payload)
        assert response.status_code == 201

        data = response.json()
        assert "run_id" in data
        run_id = data["run_id"]
        assert data["status"] == "running"

        # Poll GET /runs/{run_id} until terminal status (6 agents take ~25-30s)
        max_wait = 45  # seconds
        start_time = time.time()
        record_data = None


        while time.time() - start_time < max_wait:
            get_resp = client.get(f"/runs/{run_id}")
            assert get_resp.status_code == 200
            record_data = get_resp.json()
            if record_data["status"] in ("accepted", "partial", "failed"):
                break
            time.sleep(0.5)

        assert record_data is not None
        assert record_data["status"] in ("accepted", "partial"), (
            f"Run completed with status: {record_data['status']}, error: {record_data.get('error')}"
        )
        assert record_data["report"] is not None
        assert "gates" in record_data["report"]

        # Check GET /runs list includes this run
        list_resp = client.get("/runs")
        assert list_resp.status_code == 200
        runs_list = list_resp.json()
        assert any(r["run_id"] == run_id for r in runs_list)

    def test_sse_streaming_events(self, client: TestClient):
        payload = _valid_payload()
        post_resp = client.post("/runs", json=payload)
        assert post_resp.status_code == 201
        run_id = post_resp.json()["run_id"]

        # Read SSE stream
        with client.stream("GET", f"/runs/{run_id}/events") as sse_stream:
            assert sse_stream.status_code == 200
            assert "text/event-stream" in sse_stream.headers["content-type"]

            collected_lines = []
            for line in sse_stream.iter_lines():
                if line:
                    collected_lines.append(line)
                if "event: end" in line:
                    break

            # Must have received events
            assert len(collected_lines) > 0
            # Check for trace events or connected greeting
            assert any("connected" in l or "event: trace" in l for l in collected_lines)
