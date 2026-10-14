"""
tests/generate_designer_evidence.py

Generates evidence for Slice 4 (docs/evidence/designer/):
1. Loads examples/sample_input.json.
2. Invokes the Designer to generate the initial design_spec.json with design tokens,
   component inventory, and layout notes.
3. Simulates a Critic accessibility finding (WCAG AA low-contrast failure between text and background).
4. Invokes the Designer to revise the design spec, resolving the contrast failure
   and recording the rationale.
5. Persists:
   - docs/evidence/designer/design_spec.json
   - docs/evidence/designer/revised_design_spec.json
   - docs/evidence/designer/trace.jsonl
   - docs/evidence/designer/proof.json
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

# Ensure repo root is on sys.path
root_dir = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(root_dir))

from agents.designer import run_designer
from graph.state import AuditReport, GraphState, TaskDefinition
from lib.llm import set_fake_llm_handler
from lib.models import load_input_request
from lib.trace import TraceWriter


def main() -> None:
    evidence_dir = root_dir / "docs" / "evidence" / "designer"
    evidence_dir.mkdir(parents=True, exist_ok=True)

    print("Running Designer Evidence Generation...")

    trace_path = evidence_dir / "trace.jsonl"
    if trace_path.exists():
        trace_path.unlink()

    trace_writer = TraceWriter(trace_path, run_id="designer-evidence-001")

    # Load examples/sample_input.json
    input_file = root_dir / "examples" / "sample_input.json"
    request = load_input_request(input_file)
    print(f"Loaded input request: '{request.brief[:60]}...'")

    # Define realistic fake LLM handler for Designer
    def realistic_designer_llm(agent_name: str, messages: list[dict], **kwargs) -> str:
        prompt = messages[-1].get("content", "")
        if isinstance(prompt, list):
            # Multimodal content
            prompt = next((b.get("text", "") for b in prompt if b.get("type") == "text"), "")

        if "CRITIC FINDINGS" in prompt:
            # Revision response
            return json.dumps({
                "tokens": {
                    "colors": {
                        "primary": "#1E40AF",
                        "background": "#F9FAFB",
                        "surface": "#FFFFFF",
                        "text": "#0F172A",
                        "text_muted": "#475569",
                        "border": "#CBD5E1",
                        "error": "#EF4444",
                        "success": "#10B981",
                    },
                    "spacing": {
                        "unit": "4px",
                        "xs": "4px",
                        "sm": "8px",
                        "md": "16px",
                        "lg": "24px",
                        "xl": "32px",
                    },
                    "type_scale": {
                        "font_family": "Inter, sans-serif",
                        "h1": "2rem",
                        "h2": "1.5rem",
                        "h3": "1.25rem",
                        "body": "1rem",
                        "small": "0.875rem",
                    },
                },
                "revisions": [
                    {
                        "finding": "Color contrast between text (#94A3B8) and background (#F9FAFB) is 2.8:1, failing WCAG AA (minimum 4.5:1).",
                        "change": "Updated primary body text from #94A3B8 to #0F172A (slate-900) and muted text to #475569.",
                        "changed_tokens": {
                            "colors.text": "#0F172A",
                            "colors.text_muted": "#475569",
                        },
                        "rationale": "Contrast ratio increased from 2.8:1 to 15.3:1 against #F9FAFB, fully satisfying WCAG AA and AAA requirements.",
                    }
                ],
                "layout_notes": "Two-column responsive layout with high-contrast accessible design tokens.",
            })

        # Initial spec generation response
        return json.dumps({
            "tokens": {
                "colors": {
                    "primary": "#1E40AF",
                    "background": "#F9FAFB",
                    "surface": "#FFFFFF",
                    "text": "#94A3B8",  # Deliberately muted to demonstrate critique flow
                    "text_muted": "#CBD5E1",
                    "border": "#E5E7EB",
                    "error": "#EF4444",
                    "success": "#10B981",
                },
                "spacing": {
                    "unit": "4px",
                    "xs": "4px",
                    "sm": "8px",
                    "md": "16px",
                    "lg": "24px",
                    "xl": "32px",
                },
                "type_scale": {
                    "font_family": "Inter, sans-serif",
                    "h1": "2rem",
                    "h2": "1.5rem",
                    "h3": "1.25rem",
                    "body": "1rem",
                    "small": "0.875rem",
                },
            },
            "component_inventory": {
                "TicketsDashboard": ["TicketNavBar", "TicketFilterBar", "TicketDataTable", "PriorityBadge"],
                "TicketDetail": ["TicketThreadView", "StatusSelector", "TicketReplyForm"],
            },
            "layout_notes": "Two-column responsive layout: collapsible sidebar with persistent ticket queue and fluid detail canvas.",
        })

    set_fake_llm_handler(realistic_designer_llm)

    # 1. Initial State
    state = GraphState(
        request=request,
        plan=[
            TaskDefinition(
                task_id="T-01",
                description="Design tokens, layout and component inventory",
                assigned_agent="designer",
                status="in_progress",
            ),
            TaskDefinition(
                task_id="T-02",
                description="Build frontend components",
                assigned_agent="engineer",
                status="pending",
            ),
        ],
    )

    print("\n--- 1. Generating Initial Design Spec ---")
    initial_res = run_designer(state, trace_writer=trace_writer, artifact_dir=evidence_dir)
    state.design_spec = initial_res["design_spec"]
    state.proofs = initial_res["proofs"]

    initial_spec_file = evidence_dir / "design_spec.json"
    initial_spec_file.write_text(
        state.design_spec.model_dump_json(indent=2),
        encoding="utf-8",
    )
    print(f"Saved initial spec to: {initial_spec_file}")
    print(f"Tokens generated: primary={state.design_spec.tokens['colors']['primary']}, text={state.design_spec.tokens['colors']['text']}")
    print(f"Component inventory pages: {list(state.design_spec.component_inventory.keys())}")

    # 2. Simulate Critic Finding (Contrast violation)
    print("\n--- 2. Simulating Critic Contrast Violation Finding ---")
    contrast_finding = {
        "target_agent": "designer",
        "finding": "Color contrast between text (#94A3B8) and background (#F9FAFB) is 2.8:1, failing WCAG AA (minimum 4.5:1).",
        "failing_pair": {"foreground": "#94A3B8", "background": "#F9FAFB"},
        "reason": "Body text contrast below WCAG AA",
    }
    state.audit_report = AuditReport(
        revision_requests=[contrast_finding],
        accepted=False,
    )

    # 3. Revise Design Spec
    print("\n--- 3. Running Designer Revision ---")
    revision_res = run_designer(state, trace_writer=trace_writer, artifact_dir=evidence_dir)
    state.design_spec = revision_res["design_spec"]
    state.proofs = revision_res["proofs"]

    revised_spec_file = evidence_dir / "revised_design_spec.json"
    revised_spec_file.write_text(
        state.design_spec.model_dump_json(indent=2),
        encoding="utf-8",
    )
    print(f"Saved revised spec to: {revised_spec_file}")
    print(f"Revised text color: {state.design_spec.tokens['colors']['text']}")
    print(f"Revisions recorded: {len(state.design_spec.revisions)}")
    for r in state.design_spec.revisions:
        print(f"  • Finding: {r.finding}")
        print(f"  • Change: {r.change}")
        print(f"  • Rationale: {r.rationale}")

    # 4. Save Final Proof
    proof_file = evidence_dir / "proof.json"
    proof_file.write_text(
        state.proofs[-1].model_dump_json(indent=2),
        encoding="utf-8",
    )
    print(f"\nSaved proof record to: {proof_file}")
    print(f"Trace logged to: {trace_path}")
    print("\nDesigner evidence generation complete!")


if __name__ == "__main__":
    main()
