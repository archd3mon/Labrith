"""
tests/fakes.py — Scripted fake LLM handlers for testing without real network calls.

AGENTS.md: "Unit tests mock the LLM with a scripted fake (tests/fakes.py). Only the e2e test uses a real model."
"""

from __future__ import annotations

import json
from typing import Any, Callable, Optional


def make_scripted_llm(responses: Optional[list[str]] = None) -> Callable[..., str]:
    """Return a fake LLM handler that pops responses in sequence or generates valid agent responses.

    Args:
        responses: Optional list of specific responses to yield in sequence.
    """
    queue = list(responses or [])

    def handler(agent_name: str, messages: list[dict[str, Any]], **kwargs: Any) -> str:
        # 1. Designer fake response
        if agent_name == "designer":
            return json.dumps({
                "tokens": {
                    "colors": {
                        "primary": "#1E40AF",
                        "background": "#F9FAFB",
                        "surface": "#FFFFFF",
                        "text": "#111827",
                        "text_muted": "#6B7280",
                        "border": "#E5E7EB",
                    },
                    "spacing": {"unit": "4px", "xs": "4px", "sm": "8px", "md": "16px", "lg": "24px"},
                    "type_scale": {"font_family": "Inter, sans-serif", "h1": "2rem", "body": "1rem"},
                },
                "component_inventory": {
                    "Dashboard": ["TicketList", "TicketFilter", "TicketDetailModal"],
                },
                "layout_notes": "Clean dashboard layout with sidebar and high contrast text.",
            })

        # 2. Engineer fake response
        if agent_name == "engineer":
            return json.dumps({
                "files": [
                    {
                        "path": "src/components/TicketList.tsx",
                        "content": (
                            "export function TicketList() {\n"
                            "  return (\n"
                            "    <div className='p-4 bg-white rounded shadow'>\n"
                            "      <h1 className='text-xl font-bold'>Support Tickets</h1>\n"
                            "      <div id='ticket-1'>TCK-101 - Urgent Issue</div>\n"
                            "    </div>\n"
                            "  );\n"
                            "}\n"
                            "export default TicketList;\n"
                        ),
                    },
                    {
                        "path": "src/components/TicketList.test.tsx",
                        "content": (
                            "import { describe, it, expect } from 'vitest';\n"
                            "describe('TicketList', () => {\n"
                            "  it('renders tickets list', () => {\n"
                            "    expect(true).toBe(true);\n"
                            "  });\n"
                            "});\n"
                        ),
                    },
                ]
            })

        # 3. Planner fake response
        if agent_name == "planner":
            last_msg = str(messages[-1].get("content", "")) if messages else ""
            if "Analyze the product brief" in last_msg or "schema_contract" in last_msg:
                return json.dumps({
                    "pages": [{"name": "Dashboard", "route": "/", "description": "Main Dashboard", "components": ["TicketList"]}],
                    "user_flows": [
                        {"flow_id": "F-01", "name": "list tickets", "description": "view tickets", "steps": ["view"]},
                        {"flow_id": "F-02", "name": "filter by priority", "description": "filter tickets", "steps": ["filter"]},
                    ],
                    "tasks": [
                        {"task_id": "T-01", "description": "Design UI", "assigned_agent": "designer", "status": "pending", "depends_on": []},
                        {"task_id": "T-02", "description": "Build UI", "assigned_agent": "engineer", "status": "pending", "depends_on": ["T-01"]},
                        {"task_id": "T-03", "description": "Integrate API", "assigned_agent": "integration", "status": "pending", "depends_on": ["T-02"]},
                        {"task_id": "T-04", "description": "QA tests", "assigned_agent": "qa", "status": "pending", "depends_on": ["T-03"]},
                        {"task_id": "T-05", "description": "Accessibility audit", "assigned_agent": "critic", "status": "pending", "depends_on": ["T-04"]},
                    ],
                    "required_flows": ["list tickets", "filter by priority"],
                    "reasoning": "Plan generated from OpenAPI spec and brief.",
                })
            # If popped from queue, return that next agent
            if queue:
                next_agent = queue.pop(0)
                return json.dumps({"next_agent": next_agent, "reasoning": f"Routing to {next_agent}"})
            return json.dumps({"next_agent": "finish", "reasoning": "All tasks completed and gates pass."})

        # 4. QA fake response
        if agent_name == "qa":
            return json.dumps({
                "flow_name": "list tickets",
                "steps": [
                    {"action": "goto", "value": "/"},
                    {"action": "wait", "value": "50"},
                ],
            })

        # 5. Integration fake response
        if agent_name == "integration":
            return json.dumps({
                "decision": "adapt_types",
                "claim": "All API endpoints verified against spec.",
                "reasoning": "Endpoints match OpenAPI schema.",
            })

        # 6. Critic fake response
        if agent_name == "critic":
            return "Visual review: high contrast, accessible hierarchy, modern layout."

        if queue:
            return queue.pop(0)
        return "finish"

    return handler
