"""
tests/unit/test_mock_server.py — Unit tests for tools/mock_server.py.
"""

from __future__ import annotations

import httpx
import pytest

from tools.mock_server import MockServer
from tools.openapi import DEMO_BACKEND_SPEC


def test_mock_server_lifecycle():
    with MockServer(DEMO_BACKEND_SPEC) as server:
        assert server.base_url.startswith("http://127.0.0.1:")
        resp = httpx.get(f"{server.base_url}/api/tickets", timeout=5.0)
        assert resp.status_code == 200
        data = resp.json()
        assert isinstance(data, list)
        assert len(data) >= 3
        assert "title" in data[0]
        assert "status" in data[0]
        assert "priority" in data[0]


def test_mock_server_post_and_get_detail():
    with MockServer(DEMO_BACKEND_SPEC) as server:
        # 1. Post new ticket
        new_payload = {
            "title": "Database connection timeout during peak hours",
            "priority": "urgent",
            "initial_message": "Pool exhaustion observed at 14:00 UTC",
        }
        post_resp = httpx.post(f"{server.base_url}/api/tickets", json=new_payload, timeout=5.0)
        assert post_resp.status_code == 201
        created = post_resp.json()
        assert created["title"] == new_payload["title"]
        assert created["priority"] == "urgent"
        ticket_id = created["id"]

        # 2. Get detail
        detail_resp = httpx.get(f"{server.base_url}/api/tickets/{ticket_id}", timeout=5.0)
        assert detail_resp.status_code == 200
        detail = detail_resp.json()
        assert detail["id"] == ticket_id
        assert len(detail["messages"]) >= 1

        # 3. Post reply
        reply_resp = httpx.post(
            f"{server.base_url}/api/tickets/{ticket_id}/reply",
            json={"body": "We increased the connection pool size to 50."},
            timeout=5.0,
        )
        assert reply_resp.status_code == 200
        updated_detail = reply_resp.json()
        assert len(updated_detail["messages"]) == 2


def test_mock_server_deliberate_missing_field():
    with MockServer(DEMO_BACKEND_SPEC) as server:
        server.set_mismatch("GET", "/api/tickets", mismatch_type="missing_field", field_name="status")
        resp = httpx.get(f"{server.base_url}/api/tickets", timeout=5.0)
        assert resp.status_code == 200
        items = resp.json()
        assert len(items) > 0
        # Verified that status was removed deliberately
        for item in items:
            assert "status" not in item
            assert "title" in item


def test_mock_server_deliberate_type_mismatch():
    with MockServer(DEMO_BACKEND_SPEC) as server:
        server.set_mismatch("GET", "/api/tickets", mismatch_type="type_mismatch", field_name="id")
        resp = httpx.get(f"{server.base_url}/api/tickets", timeout=5.0)
        assert resp.status_code == 200
        items = resp.json()
        assert len(items) > 0
        for item in items:
            assert isinstance(item["id"], int)  # Deliberately int instead of string


def test_mock_server_deliberate_schema_drift():
    with MockServer(DEMO_BACKEND_SPEC) as server:
        server.set_mismatch("GET", "/api/tickets", mismatch_type="schema_drift", field_name="status")
        resp = httpx.get(f"{server.base_url}/api/tickets", timeout=5.0)
        assert resp.status_code == 200
        items = resp.json()
        for item in items:
            assert "status" not in item
            assert "ticket_state" in item


def test_mock_server_custom_override():
    with MockServer(DEMO_BACKEND_SPEC) as server:
        server.set_mismatch("GET", "/api/tickets", mismatch_type="custom_override", override_data=[{"broken": True}])
        resp = httpx.get(f"{server.base_url}/api/tickets", timeout=5.0)
        assert resp.status_code == 200
        assert resp.json() == [{"broken": True}]
