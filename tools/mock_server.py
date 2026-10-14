"""
tools/mock_server.py — Mock API server for OpenAPI 3 specifications.

Serves responses for endpoints defined in an OpenAPI 3 spec (using examples
from the spec or generated based on schemas), with support for deliberate
response mismatches for testing agent conflict resolution and resilience.

Design Doc §3: "OpenAPI reader, mock server, HTTP client"
Design Doc §5 Scenario 3: "API response differs from the OpenAPI spec"
Design Doc §6 Gate 5: "Integration gate"
"""

from __future__ import annotations

import json
import logging
import re
import socket
import threading
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any, Callable, Optional, Union
from urllib.parse import parse_qs, urlparse

from tools.openapi import DEMO_BACKEND_SPEC, list_endpoints, list_schemas, load_openapi_spec

logger = logging.getLogger(__name__)


def find_free_port() -> int:
    """Find and return an available local TCP port."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("", 0))
        s.listen(1)
        return int(s.getsockname()[1])


class SpecDataGenerator:
    """Generates synthetic response data matching OpenAPI 3 schemas."""

    def __init__(self, spec: dict[str, Any]) -> None:
        self.spec = spec
        self.schemas = list_schemas(spec)

    def resolve_schema(self, schema_or_ref: dict[str, Any]) -> dict[str, Any]:
        """Resolve $ref pointer if present, otherwise return schema as is."""
        if "$ref" in schema_or_ref:
            ref = schema_or_ref["$ref"]
            prefix = "#/components/schemas/"
            prefix_def = "#/definitions/"
            if ref.startswith(prefix):
                name = ref[len(prefix) :]
                return self.schemas.get(name, {})
            elif ref.startswith(prefix_def):
                name = ref[len(prefix_def) :]
                return self.schemas.get(name, {})
        return schema_or_ref

    def generate_data(self, schema_or_ref: dict[str, Any], depth: int = 0) -> Any:
        """Recursively generate sample data matching the given schema."""
        if depth > 8:
            return None

        schema = self.resolve_schema(schema_or_ref)
        if not schema:
            return {}

        # If explicit example is present, use it
        if "example" in schema:
            return schema["example"]

        schema_type = schema.get("type")

        # Enum handling
        if "enum" in schema and schema["enum"]:
            return schema["enum"][0]

        if schema_type == "string":
            fmt = schema.get("format")
            if fmt == "date-time":
                return datetime.now(timezone.utc).isoformat()
            if fmt == "date":
                return "2026-10-14"
            if fmt == "email":
                return "agent@frontforge.test"
            if fmt == "uri" or fmt == "url":
                return "https://example.com/asset.png"
            return "Sample Text"

        elif schema_type in ("integer", "number"):
            minimum = schema.get("minimum", 1)
            maximum = schema.get("maximum", 100)
            return minimum if minimum is not None else 1

        elif schema_type == "boolean":
            return True

        elif schema_type == "array":
            items_schema = schema.get("items", {})
            return [self.generate_data(items_schema, depth + 1)]

        elif schema_type == "object" or "properties" in schema:
            props = schema.get("properties", {})
            required = schema.get("required", [])
            obj: dict[str, Any] = {}

            # Generate properties
            for prop_name, prop_schema in props.items():
                resolved_prop = self.resolve_schema(prop_schema)
                # Apply contextual heuristics for strings
                if resolved_prop.get("type") == "string" and "enum" not in resolved_prop:
                    lower = prop_name.lower()
                    if "id" in lower:
                        obj[prop_name] = f"id-{depth+1}01"
                        continue
                    if "title" in lower or "name" in lower:
                        obj[prop_name] = f"Sample {prop_name.capitalize()}"
                        continue
                    if "status" in lower:
                        obj[prop_name] = "open"
                        continue
                    if "priority" in lower:
                        obj[prop_name] = "medium"
                        continue
                    if "author" in lower or "user" in lower:
                        obj[prop_name] = "Test User"
                        continue
                    if "body" in lower or "message" in lower:
                        obj[prop_name] = "This is a simulated message body."
                        continue

                obj[prop_name] = self.generate_data(prop_schema, depth + 1)

            # Ensure all required properties exist
            for req in required:
                if req not in obj:
                    obj[req] = f"val_{req}"

            return obj

        return {}


class MockServerHandler(BaseHTTPRequestHandler):
    """HTTP request handler for MockServer."""

    mock_app: "MockServer"  # Class-level reference to MockServer

    def log_message(self, format: str, *args: Any) -> None:
        """Suppress default HTTP server stderr logging."""
        pass

    def do_GET(self) -> None:
        self._handle_request("GET")

    def do_POST(self) -> None:
        self._handle_request("POST")

    def do_PUT(self) -> None:
        self._handle_request("PUT")

    def do_PATCH(self) -> None:
        self._handle_request("PATCH")

    def do_DELETE(self) -> None:
        self._handle_request("DELETE")

    def do_OPTIONS(self) -> None:
        self.send_response(204)
        self._send_cors_headers()
        self.end_headers()

    def _send_cors_headers(self) -> None:
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, PUT, PATCH, DELETE, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type, Authorization")

    def _handle_request(self, method: str) -> None:
        parsed_url = urlparse(self.path)
        path = parsed_url.path
        query = parse_qs(parsed_url.query)

        # Read request body if present
        content_len = int(self.headers.get("Content-Length", 0))
        body = None
        if content_len > 0:
            raw_body = self.rfile.read(content_len)
            try:
                body = json.loads(raw_body.decode("utf-8"))
            except Exception:
                body = raw_body.decode("utf-8", errors="replace")

        # Record incoming request in server log
        req_record = {
            "method": method,
            "path": path,
            "query": query,
            "body": body,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }

        # Dispatch via parent MockServer
        status, headers, resp_body = self.mock_app.route_request(method, path, body, query)

        req_record["status"] = status
        req_record["response_body"] = resp_body
        self.mock_app.request_history.append(req_record)

        # Send response
        self.send_response(status)
        self._send_cors_headers()
        for k, v in headers.items():
            self.send_header(k, v)
        self.end_headers()

        if resp_body is not None:
            if isinstance(resp_body, (dict, list)):
                payload = json.dumps(resp_body).encode("utf-8")
            elif isinstance(resp_body, str):
                payload = resp_body.encode("utf-8")
            else:
                payload = str(resp_body).encode("utf-8")
            self.wfile.write(payload)


class MockServer:
    """Configurable HTTP mock server for an OpenAPI 3 specification.

    Features:
    - Automatically parses paths and endpoints from OpenAPI spec.
    - Generates realistic JSON responses using schema definitions.
    - Maintains in-memory store for interactive CRUD workflows (e.g. support tickets).
    - Supports deliberate response mismatches (missing fields, type errors, drift)
      to exercise agent detection and conflict resolution.
    - In-process HTTP server lifecycle with start() and stop() or context manager.
    """

    def __init__(
        self,
        spec_or_url: Optional[Union[str, dict[str, Any], Path]] = None,
        *,
        spec: Optional[Union[str, dict[str, Any], Path]] = None,
        host: str = "127.0.0.1",
        port: Optional[int] = None,
        mismatches: Optional[dict[str, Any]] = None,
    ) -> None:
        actual_spec = spec if spec is not None else (spec_or_url if spec_or_url is not None else DEMO_BACKEND_SPEC)
        self.spec = load_openapi_spec(actual_spec)
        self.host = host
        self.port = port or find_free_port()
        self.data_gen = SpecDataGenerator(self.spec)
        self.request_history: list[dict[str, Any]] = []

        # Deliberate mismatches: keyed by (METHOD, PATH_PATTERN) or PATH
        # E.g. {("/api/tickets", "GET"): {"type": "missing_field", "field": "status"}}
        self.mismatches: dict[tuple[str, str], dict[str, Any]] = {}
        if mismatches:
            for k, v in mismatches.items():
                if isinstance(k, tuple):
                    self.mismatches[(k[0].upper(), k[1])] = v
                else:
                    self.mismatches[("*", k)] = v

        # In-memory store for tickets and threads
        self._init_in_memory_store()

        # Server threading internals
        self._httpd: Optional[ThreadingHTTPServer] = None
        self._thread: Optional[threading.Thread] = None
        self.base_url = f"http://{self.host}:{self.port}"

    def _init_in_memory_store(self) -> None:
        """Seed initial in-memory dataset for common endpoints."""
        self.tickets: list[dict[str, Any]] = [
            {
                "id": "TCK-101",
                "title": "Cannot export analytics report to CSV",
                "priority": "high",
                "status": "open",
                "created_at": "2026-10-14T08:30:00Z",
                "assigned_to": "Alex Agent",
            },
            {
                "id": "TCK-102",
                "title": "Password reset email delayed by 15 minutes",
                "priority": "medium",
                "status": "pending",
                "created_at": "2026-10-14T09:15:00Z",
                "assigned_to": "Sam Agent",
            },
            {
                "id": "TCK-103",
                "title": "UI contrast issue on billing page toggle",
                "priority": "low",
                "status": "resolved",
                "created_at": "2026-10-14T09:45:00Z",
                "assigned_to": "Dana Agent",
            },
        ]
        self.ticket_details: dict[str, dict[str, Any]] = {
            "TCK-101": {
                "id": "TCK-101",
                "title": "Cannot export analytics report to CSV",
                "priority": "high",
                "status": "open",
                "messages": [
                    {
                        "id": "MSG-01",
                        "author": "customer@example.com",
                        "body": "When clicking the CSV button, an empty file downloads.",
                        "timestamp": "2026-10-14T08:30:00Z",
                    },
                    {
                        "id": "MSG-02",
                        "author": "Alex Agent",
                        "body": "Investigating query serialization in backend service.",
                        "timestamp": "2026-10-14T08:45:00Z",
                    },
                ],
            },
            "TCK-102": {
                "id": "TCK-102",
                "title": "Password reset email delayed by 15 minutes",
                "priority": "medium",
                "status": "pending",
                "messages": [
                    {
                        "id": "MSG-03",
                        "author": "user@example.com",
                        "body": "Tokens expire before email is delivered.",
                        "timestamp": "2026-10-14T09:15:00Z",
                    }
                ],
            },
        }

    # -----------------------------------------------------------------------
    # Deliberate mismatch configuration
    # -----------------------------------------------------------------------

    def set_mismatch(
        self,
        method: str,
        path: str,
        mismatch_type: str = "missing_field",
        override_data: Optional[Any] = None,
        field_name: Optional[str] = None,
    ) -> None:
        """Configure a deliberate response mismatch for a specific endpoint."""
        self.mismatches[(method.upper(), path)] = {
            "type": mismatch_type,
            "override_data": override_data,
            "field": field_name,
        }

    def clear_mismatches(self) -> None:
        """Clear all configured mismatches."""
        self.mismatches.clear()

    # -----------------------------------------------------------------------
    # Route matching & response dispatch
    # -----------------------------------------------------------------------

    def _find_matching_spec_path(self, method: str, req_path: str) -> tuple[Optional[str], dict[str, str]]:
        """Match incoming URL path against OpenAPI path patterns (e.g. /api/tickets/{id})."""
        paths = self.spec.get("paths", {})

        # Direct match first
        if req_path in paths:
            if method.lower() in paths[req_path]:
                return req_path, {}

        # Regex match parameterized paths
        for spec_path, path_item in paths.items():
            if method.lower() not in path_item:
                continue

            # Convert OpenAPI {param} into regex (?P<param>[^/]+)
            regex_pattern = "^" + re.sub(r"\{([a-zA-Z0-9_]+)\}", r"(?P<\1>[^/]+)", spec_path) + "$"
            match = re.match(regex_pattern, req_path)
            if match:
                return spec_path, match.groupdict()

        return None, {}

    def _check_mismatch(self, method: str, req_path: str, spec_path: Optional[str]) -> Optional[dict[str, Any]]:
        """Check if a deliberate mismatch is configured for this request."""
        # Check exact (method, req_path)
        if (method, req_path) in self.mismatches:
            return self.mismatches[(method, req_path)]
        if ("*", req_path) in self.mismatches:
            return self.mismatches[("*", req_path)]

        # Check spec_path if available
        if spec_path:
            if (method, spec_path) in self.mismatches:
                return self.mismatches[(method, spec_path)]
            if ("*", spec_path) in self.mismatches:
                return self.mismatches[("*", spec_path)]

        return None

    def route_request(
        self,
        method: str,
        path: str,
        body: Optional[Any] = None,
        query: Optional[dict[str, list[str]]] = None,
    ) -> tuple[int, dict[str, str], Any]:
        """Core routing logic producing (status_code, headers, response_body)."""
        method = method.upper()
        spec_path, path_params = self._find_matching_spec_path(method, path)

        headers = {"Content-Type": "application/json"}

        # Check for deliberate mismatch trigger
        mismatch_config = self._check_mismatch(method, path, spec_path)
        if mismatch_config:
            m_type = mismatch_config.get("type")
            if m_type == "custom_override":
                return 200, headers, mismatch_config.get("override_data")

            elif m_type == "missing_field":
                field_to_remove = mismatch_config.get("field", "status")
                data = self._generate_normal_response(method, path, spec_path, path_params, body, query)
                if isinstance(data, list):
                    # Remove field from all items in list
                    mutated = [
                        {k: v for k, v in item.items() if k != field_to_remove}
                        if isinstance(item, dict)
                        else item
                        for item in data
                    ]
                    return 200, headers, mutated
                elif isinstance(data, dict):
                    mutated = {k: v for k, v in data.items() if k != field_to_remove}
                    return 200, headers, mutated

            elif m_type == "type_mismatch":
                # E.g. id is returned as integer instead of string
                field_name = mismatch_config.get("field", "id")
                data = self._generate_normal_response(method, path, spec_path, path_params, body, query)
                if isinstance(data, list):
                    mutated = []
                    for item in data:
                        if isinstance(item, dict) and field_name in item:
                            m_item = dict(item)
                            m_item[field_name] = 99999  # Int instead of string
                            mutated.append(m_item)
                        else:
                            mutated.append(item)
                    return 200, headers, mutated
                elif isinstance(data, dict):
                    mutated = dict(data)
                    mutated[field_name] = 99999
                    return 200, headers, mutated

            elif m_type == "schema_drift":
                # Rename field to simulate breaking upstream drift
                old_f = mismatch_config.get("field", "status")
                new_f = mismatch_config.get("new_field", "ticket_state")
                data = self._generate_normal_response(method, path, spec_path, path_params, body, query)
                if isinstance(data, list):
                    mutated = []
                    for item in data:
                        if isinstance(item, dict):
                            d = dict(item)
                            if old_f in d:
                                d[new_f] = d.pop(old_f)
                            mutated.append(d)
                        else:
                            mutated.append(item)
                    return 200, headers, mutated

            elif m_type == "status_error":
                return 500, headers, {"error": "Internal Server Error", "code": "SRV_500"}

        # Normal response handling
        if not spec_path:
            return 404, headers, {"error": f"Path {path} not found in OpenAPI spec"}

        resp_data = self._generate_normal_response(method, path, spec_path, path_params, body, query)
        status = 201 if method == "POST" and spec_path == "/api/tickets" else 200
        return status, headers, resp_data

    def _generate_normal_response(
        self,
        method: str,
        path: str,
        spec_path: Optional[str],
        path_params: dict[str, str],
        body: Optional[Any],
        query: Optional[dict[str, list[str]]],
    ) -> Any:
        """Generate or retrieve standard response data for matched route."""
        # 1. Stateful support for tickets domain
        if spec_path == "/api/tickets":
            if method == "GET":
                results = list(self.tickets)
                if query:
                    priority = query.get("priority", [None])[0]
                    status = query.get("status", [None])[0]
                    if priority:
                        results = [t for t in results if t.get("priority") == priority]
                    if status:
                        results = [t for t in results if t.get("status") == status]
                return results

            elif method == "POST":
                new_id = f"TCK-{100 + len(self.tickets) + 1}"
                new_ticket = {
                    "id": new_id,
                    "title": (body or {}).get("title", "New Support Ticket"),
                    "priority": (body or {}).get("priority", "medium"),
                    "status": "open",
                    "created_at": datetime.now(timezone.utc).isoformat(),
                    "assigned_to": "Triage Agent",
                }
                self.tickets.append(new_ticket)
                self.ticket_details[new_id] = {
                    "id": new_id,
                    "title": new_ticket["title"],
                    "priority": new_ticket["priority"],
                    "status": new_ticket["status"],
                    "messages": [
                        {
                            "id": f"MSG-{len(self.ticket_details)+1}01",
                            "author": "customer@example.com",
                            "body": (body or {}).get("initial_message", "Ticket created."),
                            "timestamp": datetime.now(timezone.utc).isoformat(),
                        }
                    ],
                }
                return new_ticket

        if spec_path == "/api/tickets/{id}":
            ticket_id = path_params.get("id")
            if ticket_id in self.ticket_details:
                return self.ticket_details[ticket_id]
            # Return synthetic detail for any other ID
            return {
                "id": ticket_id or "TCK-999",
                "title": f"Ticket {ticket_id}",
                "priority": "medium",
                "status": "open",
                "messages": [
                    {
                        "id": "MSG-999",
                        "author": "system@example.com",
                        "body": "Synthetic ticket details.",
                        "timestamp": datetime.now(timezone.utc).isoformat(),
                    }
                ],
            }

        if spec_path == "/api/tickets/{id}/reply":
            ticket_id = path_params.get("id")
            detail = self.ticket_details.get(
                ticket_id or "",
                {
                    "id": ticket_id or "TCK-101",
                    "title": "Support Ticket",
                    "priority": "medium",
                    "status": "open",
                    "messages": [],
                },
            )
            new_msg = {
                "id": f"MSG-{len(detail.get('messages', [])) + 1}0",
                "author": "Support Representative",
                "body": (body or {}).get("body", "Thank you for reaching out."),
                "timestamp": datetime.now(timezone.utc).isoformat(),
            }
            detail.setdefault("messages", []).append(new_msg)
            return detail

        # 2. General OpenAPI response generation from spec schema
        if spec_path:
            operation = self.spec["paths"][spec_path].get(method.lower(), {})
            responses = operation.get("responses", {})
            # Look for 200 or 201 response schema
            success_resp = responses.get("200") or responses.get("201") or responses.get("default")
            if success_resp and "content" in success_resp:
                json_content = success_resp["content"].get("application/json", {})
                schema = json_content.get("schema")
                if schema:
                    return self.data_gen.generate_data(schema)

        return {"message": "Success"}

    # -----------------------------------------------------------------------
    # Server lifecycle management
    # -----------------------------------------------------------------------

    def start(self) -> str:
        """Start the HTTP server on a background thread and return base_url."""
        if self._httpd is not None:
            return self.base_url

        handler_factory = type("BoundMockServerHandler", (MockServerHandler,), {"mock_app": self})
        self._httpd = ThreadingHTTPServer((self.host, self.port), handler_factory)
        # Port might have been resolved dynamically if port=0
        self.port = self._httpd.server_port
        self.base_url = f"http://{self.host}:{self.port}"

        self._thread = threading.Thread(target=self._httpd.serve_forever, daemon=True)
        self._thread.start()
        logger.info("MockServer running at %s", self.base_url)
        return self.base_url

    def stop(self) -> None:
        """Stop the HTTP server cleanly."""
        if self._httpd:
            self._httpd.shutdown()
            self._httpd.server_close()
            self._httpd = None
        if self._thread:
            self._thread.join(timeout=2.0)
            self._thread = None
        logger.info("MockServer stopped")

    def __enter__(self) -> "MockServer":
        self.start()
        return self

    def __exit__(self, exc_type: Any, exc_val: Any, exc_tb: Any) -> None:
        self.stop()
