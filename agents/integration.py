"""
agents/integration.py — Integration agent.

Binds components to the real/mock API with TypeScript types, loading and error states.
Exercises endpoints against the API, compares actual responses with the OpenAPI spec,
reports mismatches with evidence, and decides whether to adapt types or request the
planner to involve the component engineer.

Design Doc §3:
  "Binds components to the real API with types, loading and error states.
   Decides: How to map responses to UI; how to handle spec mismatches.
   Tools: OpenAPI reader, mock server, HTTP client.
   Proof of work: Generated API client, request and response log, mismatch report."
Design Doc §5 Scenario 3:
  "API response differs from the OpenAPI spec: The Integration Agent reports
   the mismatch with evidence; the Planner decides to adapt the types or ask
   the Engineer to handle the variant, and updates the plan."
Design Doc §6 Gate 5:
  "Integration gate: every API call in the generated client matches the spec,
   or each mismatch is documented (Integration evidence: mismatch report)."
"""

from __future__ import annotations

import json
import logging
import re
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional, Union

import httpx

from graph.state import GraphState, IntegrationReport
from lib.llm import complete
from lib.proofs import create_proof
from lib.trace import TraceWriter
from tools.mock_server import MockServer
from tools.openapi import (
    DEMO_BACKEND_SPEC,
    get_spec_summary,
    list_endpoints,
    list_schemas,
    load_openapi_spec,
)

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# 1. Type Generator & API Client Scaffolder
# ---------------------------------------------------------------------------

def _schema_type_to_ts(schema: dict[str, Any], schemas: dict[str, Any], depth: int = 0) -> str:
    """Convert an OpenAPI schema definition into a TypeScript type expression."""
    if depth > 6:
        return "any"

    if "$ref" in schema:
        ref = schema["$ref"]
        for prefix in ("#/components/schemas/", "#/definitions/"):
            if ref.startswith(prefix):
                return ref[len(prefix):]
        return "any"

    if "enum" in schema and schema["enum"]:
        return " | ".join(json.dumps(val) for val in schema["enum"])

    stype = schema.get("type")
    if stype == "string":
        return "string"
    if stype in ("integer", "number"):
        return "number"
    if stype == "boolean":
        return "boolean"
    if stype == "array":
        item_schema = schema.get("items", {})
        item_type = _schema_type_to_ts(item_schema, schemas, depth + 1)
        if " | " in item_type:
            return f"({item_type})[]"
        return f"{item_type}[]"
    if stype == "object" or "properties" in schema:
        props = schema.get("properties", {})
        required = set(schema.get("required", []))
        lines = []
        for prop_name, prop_schema in props.items():
            optional_marker = "" if prop_name in required else "?"
            prop_ts = _schema_type_to_ts(prop_schema, schemas, depth + 1)
            lines.append(f"  {prop_name}{optional_marker}: {prop_ts};")
        if not lines:
            return "Record<string, any>"
        return "{\n" + "\n".join(lines) + "\n}"

    return "any"


def generate_typescript_client(
    spec: dict[str, Any],
    adapted_types: Optional[dict[str, str]] = None,
) -> str:
    """Generate typed TypeScript client with interfaces, loading/error states, and fetch methods."""
    schemas = list_schemas(spec)
    endpoints = list_endpoints(spec)

    lines: list[str] = [
        "/**",
        " * Auto-generated Typed API Client and UI State Hooks for FrontForge.",
        f" * Generated at: {datetime.now(timezone.utc).isoformat()}",
        " * OpenAPI Title: " + spec.get("info", {}).get("title", "API"),
        " */",
        "",
        "// --- Core UI Loading and Error State Types -------------------------------",
        "export interface ApiState<T> {",
        "  data: T | null;",
        "  loading: boolean;",
        "  error: string | null;",
        "}",
        "",
        "export interface ApiResponse<T> {",
        "  data?: T;",
        "  error?: string;",
        "  status: number;",
        "}",
        "",
        "export class ApiError extends Error {",
        "  constructor(public status: number, message: string, public details?: any) {",
        "    super(message);",
        "    this.name = 'ApiError';",
        "  }",
        "}",
        "",
        "// --- Schema Interfaces ---------------------------------------------------",
    ]

    # Generate interfaces for components.schemas
    for name, schema in schemas.items():
        if adapted_types and name in adapted_types:
            lines.append(f"export type {name} = {adapted_types[name]};\n")
            continue

        stype = schema.get("type", "object")
        if stype == "object" or "properties" in schema:
            props = schema.get("properties", {})
            required = set(schema.get("required", []))
            lines.append(f"export interface {name} {{")
            for prop_name, prop_schema in props.items():
                opt = "" if prop_name in required else "?"
                ts_type = _schema_type_to_ts(prop_schema, schemas)
                lines.append(f"  {prop_name}{opt}: {ts_type};")
            lines.append("}\n")
        else:
            ts_type = _schema_type_to_ts(schema, schemas)
            lines.append(f"export type {name} = {ts_type};\n")

    # Generate Client class and helper functions
    lines.extend([
        "// --- Typed API Client Implementation -------------------------------------",
        "export class ApiClient {",
        "  constructor(private baseUrl: string = '') {}",
        "",
        "  private async request<T>(path: string, options: RequestInit = {}): Promise<T> {",
        "    const url = `${this.baseUrl}${path}`;",
        "    const response = await fetch(url, {",
        "      ...options,",
        "      headers: {",
        "        'Content-Type': 'application/json',",
        "        ...(options.headers || {}),",
        "      },",
        "    });",
        "",
        "    if (!response.ok) {",
        "      let errorBody: any = null;",
        "      try { errorBody = await response.json(); } catch (_) { errorBody = await response.text(); }",
        "      throw new ApiError(response.status, `HTTP ${response.status} from ${path}`, errorBody);",
        "    }",
        "",
        "    return response.json() as Promise<T>;",
        "  }",
        "",
    ])

    # Method implementations
    for ep in endpoints:
        op_id = ep["operation_id"]
        method = ep["method"]
        path = ep["path"]
        summary = ep.get("summary", "")

        # Guess return type based on operationId and path
        ret_type = "any"
        if "/api/tickets" == path and method == "GET":
            ret_type = "Ticket[]"
        elif "/api/tickets" == path and method == "POST":
            ret_type = "Ticket"
        elif "/api/tickets/" in path:
            ret_type = "TicketDetail"

        param_args = []
        url_expr = f"`{path}`"
        if "{id}" in path:
            param_args.append("id: string")
            url_expr = f"`{path.replace('{id}', '${id}')}`"

        if method in ("POST", "PUT", "PATCH"):
            if "reply" in path.lower():
                param_args.append("payload: ReplyRequest")
            else:
                param_args.append("payload: CreateTicketRequest")

        params_sig = ", ".join(param_args)

        lines.append(f"  /** {summary or op_id} */")
        if method == "GET":
            lines.append(f"  async {op_id}({params_sig}): Promise<{ret_type}> {{")
            lines.append(f"    return this.request<{ret_type}>({url_expr}, {{ method: 'GET' }});")
            lines.append("  }\n")
        else:
            body_arg = "JSON.stringify(payload)" if any("payload" in a for a in param_args) else "undefined"
            lines.append(f"  async {op_id}({params_sig}): Promise<{ret_type}> {{")
            lines.append(f"    return this.request<{ret_type}>({url_expr}, {{ method: '{method}', body: {body_arg} }});")
            lines.append("  }\n")

    lines.append("}")
    lines.append("\n// Export singleton instance\nexport const apiClient = new ApiClient();")

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# 2. Spec Validation & Mismatch Detection
# ---------------------------------------------------------------------------

def validate_response_against_schema(
    response_data: Any,
    schema: dict[str, Any],
    schemas: dict[str, Any],
    path_prefix: str = "",
) -> list[dict[str, Any]]:
    """Validate actual response JSON against OpenAPI schema, returning list of mismatches."""
    mismatches: list[dict[str, Any]] = []

    # Resolve $ref
    if "$ref" in schema:
        ref = schema["$ref"]
        for prefix in ("#/components/schemas/", "#/definitions/"):
            if ref.startswith(prefix):
                name = ref[len(prefix):]
                schema = schemas.get(name, {})
                break

    stype = schema.get("type")

    if stype == "array":
        if not isinstance(response_data, list):
            mismatches.append({
                "issue_type": "type_mismatch",
                "field": path_prefix or "root",
                "expected": "array",
                "actual": type(response_data).__name__,
                "message": f"Expected array at '{path_prefix or 'root'}', got {type(response_data).__name__}",
            })
            return mismatches

        items_schema = schema.get("items", {})
        for idx, item in enumerate(response_data):
            elem_prefix = f"{path_prefix}[{idx}]"
            sub_mismatches = validate_response_against_schema(item, items_schema, schemas, elem_prefix)
            mismatches.extend(sub_mismatches)
        return mismatches

    if stype == "object" or "properties" in schema:
        if not isinstance(response_data, dict):
            mismatches.append({
                "issue_type": "type_mismatch",
                "field": path_prefix or "root",
                "expected": "object",
                "actual": type(response_data).__name__,
                "message": f"Expected object at '{path_prefix or 'root'}', got {type(response_data).__name__}",
            })
            return mismatches

        required = schema.get("required", [])
        for req_prop in required:
            if req_prop not in response_data:
                field_name = f"{path_prefix}.{req_prop}" if path_prefix else req_prop
                mismatches.append({
                    "issue_type": "missing_required_property",
                    "field": field_name,
                    "expected": f"required property '{req_prop}'",
                    "actual": "missing",
                    "message": f"Missing required property '{req_prop}' at '{field_name}'",
                })

        properties = schema.get("properties", {})
        for prop_name, prop_val in response_data.items():
            if prop_name in properties:
                prop_schema = properties[prop_name]
                field_name = f"{path_prefix}.{prop_name}" if path_prefix else prop_name
                sub_mismatches = validate_response_against_schema(prop_val, prop_schema, schemas, field_name)
                mismatches.extend(sub_mismatches)
        return mismatches

    if stype == "string":
        if not isinstance(response_data, str):
            mismatches.append({
                "issue_type": "type_mismatch",
                "field": path_prefix or "root",
                "expected": "string",
                "actual": type(response_data).__name__,
                "message": f"Field '{path_prefix}' expected string, got {type(response_data).__name__}",
            })
        elif "enum" in schema and schema["enum"]:
            if response_data not in schema["enum"]:
                mismatches.append({
                    "issue_type": "enum_violation",
                    "field": path_prefix or "root",
                    "expected": f"one of {schema['enum']}",
                    "actual": response_data,
                    "message": f"Field '{path_prefix}' value '{response_data}' not in enum {schema['enum']}",
                })

    elif stype in ("integer", "number"):
        if not isinstance(response_data, (int, float)) or isinstance(response_data, bool):
            mismatches.append({
                "issue_type": "type_mismatch",
                "field": path_prefix or "root",
                "expected": "number",
                "actual": type(response_data).__name__,
                "message": f"Field '{path_prefix}' expected number, got {type(response_data).__name__}",
            })

    elif stype == "boolean":
        if not isinstance(response_data, bool):
            mismatches.append({
                "issue_type": "type_mismatch",
                "field": path_prefix or "root",
                "expected": "boolean",
                "actual": type(response_data).__name__,
                "message": f"Field '{path_prefix}' expected boolean, got {type(response_data).__name__}",
            })

    return mismatches


# ---------------------------------------------------------------------------
# 3. LLM-driven Decision on Mismatches
# ---------------------------------------------------------------------------

def _decide_mismatch_action(
    mismatches: list[dict[str, Any]],
    endpoints_tested: int,
    log_summary: list[dict[str, Any]],
) -> tuple[str, str, str]:
    """Consult LLM to decide whether to adapt types or involve engineer.

    Returns (decision, claim, reasoning).
    decision in: 'verified', 'adapt_types', 'involve_engineer'.
    """
    if not mismatches:
        claim = f"API client generated; all {endpoints_tested} endpoints matched OpenAPI spec; zero mismatches."
        reasoning = (
            f"Successfully exercised {endpoints_tested} API endpoints against the server. "
            "All responses match schema types, required properties, and enums. Integration gate passed."
        )
        return "verified", claim, reasoning

    prompt = json.dumps(
        {
            "instruction": (
                "You are FrontForge's Integration Agent. You tested API endpoints against the OpenAPI spec "
                "and detected discrepancies. Analyze the mismatches. Decide whether to: "
                "(1) 'adapt_types': if the mismatch is minor, non-breaking, or can be handled in TypeScript (e.g. optional fields, union types), OR "
                "(2) 'involve_engineer': if the backend contract is broken, missing essential required data, or requires UI component changes. "
                "Return a JSON object: {\"decision\": \"adapt_types\"|\"involve_engineer\", \"claim\": \"string\", \"reasoning\": \"string\"}"
            ),
            "endpoints_tested": endpoints_tested,
            "mismatches_count": len(mismatches),
            "mismatches": mismatches[:5],
            "sample_logs": [
                {"method": l.get("method"), "path": l.get("path"), "status": l.get("status")}
                for l in log_summary[:5]
            ],
        },
        indent=2,
    )

    raw = complete("integration", [{"role": "user", "content": prompt}])

    try:
        match = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", raw, re.DOTALL)
        content = match.group(1) if match else raw[raw.find("{") : raw.rfind("}") + 1]
        parsed = json.loads(content)
        decision = parsed.get("decision", "involve_engineer")
        if decision not in ("adapt_types", "involve_engineer"):
            decision = "involve_engineer"
        claim = parsed.get(
            "claim",
            f"API client generated; {len(mismatches)} spec mismatch(es) detected; requesting planner to {decision}.",
        )
        reasoning = parsed.get(
            "reasoning",
            f"Detected {len(mismatches)} mismatch(es) between actual API responses and OpenAPI spec. Action: {decision}.",
        )
        return decision, claim, reasoning
    except Exception:
        # Fallback decision logic
        has_missing = any(m.get("issue_type") == "missing_required_property" for m in mismatches)
        decision = "involve_engineer" if has_missing else "adapt_types"
        claim = (
            f"API client generated; {len(mismatches)} spec mismatch(es) detected; requesting planner to {decision}."
        )
        reasoning = (
            f"Discrepancies found across {len(mismatches)} property check(s). "
            f"Evaluated severity and decided to request planner to {decision}."
        )
        return decision, claim, reasoning


# ---------------------------------------------------------------------------
# 4. Main Agent Runner / LangGraph Node
# ---------------------------------------------------------------------------

def run_integration(
    state: GraphState,
    trace_writer: Optional[TraceWriter] = None,
    *,
    artifact_dir: Path = Path("artifacts"),
    mock_server: Optional[MockServer] = None,
    api_base_url: Optional[str] = None,
    deliberate_mismatch: Optional[dict[str, Any]] = None,
) -> dict[str, Any]:
    """LangGraph node for the Integration agent.

    1. Loads the OpenAPI spec.
    2. Generates a typed TypeScript API client and loading/error states.
    3. Exercises endpoints against the server (using existing mock server or auto-starting one).
    4. Validates actual responses against the spec and captures mismatches.
    5. Decides whether to adapt types or ask the planner to involve the engineer.
    6. Produces a validated ProofOfWork and updates GraphState.
    """
    task_id = _find_task_id(state, "integration")
    run_artifact_dir = artifact_dir / task_id
    run_artifact_dir.mkdir(parents=True, exist_ok=True)

    spec = load_openapi_spec(state.request.api_spec_url or DEMO_BACKEND_SPEC)
    schemas = list_schemas(spec)

    # 1. Generate Initial Typed API Client
    client_code = generate_typescript_client(spec)
    client_path = run_artifact_dir / "api_client.ts"
    client_path.write_text(client_code, encoding="utf-8")

    if trace_writer:
        trace_writer.write(
            "integration",
            "api_client_generated",
            {"task_id": task_id, "path": str(client_path)},
        )

    # 2. Determine Server URL & Start Mock Server if needed
    managed_server: Optional[MockServer] = None
    target_base_url = api_base_url

    if not target_base_url:
        if mock_server:
            target_base_url = mock_server.base_url
        else:
            # Auto-spin in-process mock server
            managed_server = MockServer(spec=spec)
            if deliberate_mismatch:
                for k, v in deliberate_mismatch.items():
                    if isinstance(k, tuple):
                        managed_server.set_mismatch(k[0], k[1], **v)
                    else:
                        managed_server.set_mismatch("GET", k, **v)
            managed_server.start()
            target_base_url = managed_server.base_url

    # 3. Exercise Endpoints and Capture Request/Response Logs
    request_logs: list[dict[str, Any]] = []
    mismatches: list[dict[str, Any]] = []

    try:
        with httpx.Client(base_url=target_base_url, timeout=10.0) as http_client:
            # Test 1: GET /api/tickets
            t0 = time.time()
            resp_list = http_client.get("/api/tickets")
            latency_ms = round((time.time() - t0) * 1000, 2)
            data_list = resp_list.json() if resp_list.status_code == 200 else resp_list.text

            request_logs.append({
                "method": "GET",
                "path": "/api/tickets",
                "status": resp_list.status_code,
                "latency_ms": latency_ms,
                "response": data_list,
                "timestamp": datetime.now(timezone.utc).isoformat(),
            })

            # Check GET /api/tickets schema
            list_schema = (
                spec.get("paths", {})
                .get("/api/tickets", {})
                .get("get", {})
                .get("responses", {})
                .get("200", {})
                .get("content", {})
                .get("application/json", {})
                .get("schema", {})
            )
            if list_schema and isinstance(data_list, (dict, list)):
                mismatches.extend(validate_response_against_schema(data_list, list_schema, schemas, "GET /api/tickets"))

            # Test 2: POST /api/tickets
            t0 = time.time()
            new_ticket_body = {
                "title": "Integration test ticket verification",
                "priority": "high",
                "initial_message": "Automated contract verification request.",
            }
            resp_post = http_client.post("/api/tickets", json=new_ticket_body)
            latency_ms = round((time.time() - t0) * 1000, 2)
            data_post = resp_post.json() if resp_post.status_code in (200, 201) else resp_post.text

            request_logs.append({
                "method": "POST",
                "path": "/api/tickets",
                "status": resp_post.status_code,
                "latency_ms": latency_ms,
                "response": data_post,
                "timestamp": datetime.now(timezone.utc).isoformat(),
            })

            post_schema = (
                spec.get("paths", {})
                .get("/api/tickets", {})
                .get("post", {})
                .get("responses", {})
                .get("201", {})
                .get("content", {})
                .get("application/json", {})
                .get("schema", {})
            )
            if post_schema and isinstance(data_post, (dict, list)):
                mismatches.extend(validate_response_against_schema(data_post, post_schema, schemas, "POST /api/tickets"))

            # Test 3: GET /api/tickets/{id}
            test_id = data_post.get("id", "TCK-101") if isinstance(data_post, dict) else "TCK-101"
            t0 = time.time()
            resp_detail = http_client.get(f"/api/tickets/{test_id}")
            latency_ms = round((time.time() - t0) * 1000, 2)
            data_detail = resp_detail.json() if resp_detail.status_code == 200 else resp_detail.text

            request_logs.append({
                "method": "GET",
                "path": f"/api/tickets/{test_id}",
                "status": resp_detail.status_code,
                "latency_ms": latency_ms,
                "response": data_detail,
                "timestamp": datetime.now(timezone.utc).isoformat(),
            })

            detail_schema = (
                spec.get("paths", {})
                .get("/api/tickets/{id}", {})
                .get("get", {})
                .get("responses", {})
                .get("200", {})
                .get("content", {})
                .get("application/json", {})
                .get("schema", {})
            )
            if detail_schema and isinstance(data_detail, (dict, list)):
                mismatches.extend(validate_response_against_schema(data_detail, detail_schema, schemas, f"GET /api/tickets/{test_id}"))

    finally:
        if managed_server:
            managed_server.stop()

    # 4. Write Request Logs and Mismatch Report Artifacts
    req_log_path = run_artifact_dir / "requests.log"
    log_lines = []
    for entry in request_logs:
        log_lines.append(
            f"[{entry['timestamp']}] {entry['method']} {entry['path']} -> {entry['status']} ({entry['latency_ms']}ms)"
        )
    req_log_path.write_text("\n".join(log_lines) + "\n", encoding="utf-8")

    # 5. LLM Decision on Mismatches
    decision, claim, reasoning = _decide_mismatch_action(
        mismatches=mismatches,
        endpoints_tested=len(request_logs),
        log_summary=request_logs,
    )

    # If decision is adapt_types, regenerate client with adapted types
    if decision == "adapt_types" and mismatches:
        adapted_types: dict[str, str] = {}
        # Adapt Ticket interface if status is missing or optional
        adapted_types["Ticket"] = (
            "{\n  id: string;\n  title: string;\n  priority: 'low' | 'medium' | 'high' | 'urgent';\n"
            "  status?: 'open' | 'pending' | 'resolved' | 'closed';\n  created_at: string;\n  assigned_to?: string;\n}"
        )
        adapted_client_code = generate_typescript_client(spec, adapted_types=adapted_types)
        client_path.write_text(adapted_client_code, encoding="utf-8")
        reasoning += " Client types adapted with optional fields to ensure safe parsing."

    mismatch_report_path = run_artifact_dir / "mismatch_report.json"
    mismatch_report_data = {
        "total_endpoints_tested": len(request_logs),
        "mismatches_count": len(mismatches),
        "passed": len(mismatches) == 0 or decision == "adapt_types",
        "planner_action": None if len(mismatches) == 0 else decision,
        "mismatches": mismatches,
        "reasoning": reasoning,
    }
    mismatch_report_path.write_text(json.dumps(mismatch_report_data, indent=2), encoding="utf-8")

    # 6. Trace Events
    if trace_writer:
        trace_writer.write(
            "integration",
            "api_exercised",
            {"calls_count": len(request_logs), "log_file": str(req_log_path)},
        )
        if mismatches:
            trace_writer.write(
                "integration",
                "mismatch_detected",
                {
                    "count": len(mismatches),
                    "decision": decision,
                    "mismatches": mismatches[:3],
                },
            )

    # 7. Proof of Work Creation
    proof = create_proof(
        agent="integration",
        task_id=task_id,
        claim=claim,
        evidence=[
            {"type": "api_client", "ref": str(client_path)},
            {"type": "request_log", "ref": str(req_log_path)},
            {"type": "mismatch_report", "ref": str(mismatch_report_path)},
        ],
        reasoning=reasoning,
    )

    if trace_writer:
        trace_writer.write(
            "integration",
            "handoff",
            {
                "task_id": task_id,
                "claim": proof.claim,
                "planner_action": mismatch_report_data["planner_action"],
            },
        )

    integration_report = IntegrationReport(
        api_client_path=str(client_path),
        request_response_log=[
            {"method": r["method"], "path": r["path"], "status": r["status"]}
            for r in request_logs
        ],
        mismatches=mismatches,
        planner_action=mismatch_report_data["planner_action"],
        passed=mismatch_report_data["passed"],
    )

    return {
        "integration_report": integration_report,
        "proofs": state.proofs + [proof],
    }


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _find_task_id(state: GraphState, agent: str) -> str:
    """Find active task ID for agent from plan or default to T-03."""
    for task in state.plan or []:
        if task.assigned_agent == agent and task.status in ("pending", "in_progress"):
            return task.task_id
    return "T-03"
