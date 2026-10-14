"""
tests/agents/test_designer.py

Unit and behavioural tests for the Design Architect agent (agents/designer.py):
1. Initial spec generation from plan and style hints using a scripted fake LLM.
2. Pydantic validation of DesignSpec (colours, spacing, type scale, components, layout notes).
3. Critic revision handling: resolving contrast failure findings, updating tokens,
   and recording rationale entries.
4. Vision-capable call verification when screenshot_path is provided.
5. Proof-of-work validity and citation of the spec file.
6. Ensuring designer does not write application code.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from agents.designer import (
    generate_design_spec,
    revise_design_spec,
    run_designer,
    validate_design_spec,
)
from graph.state import AuditReport, DesignSpec, GraphState, RevisionRecord, TaskDefinition
from lib.llm import set_fake_llm_handler
from lib.models import InputRequest, TargetType
from lib.proofs import validate_proof
from lib.trace import TraceWriter, read_trace


@pytest.fixture(autouse=True)
def _clear_llm():
    """Ensure the fake LLM handler is cleared before and after each test."""
    set_fake_llm_handler(None)
    yield
    set_fake_llm_handler(None)


@pytest.fixture
def sample_request() -> InputRequest:
    return InputRequest(
        brief="A modern support dashboard for viewing and managing tickets.",
        api_spec_url="https://demo-backend.example.com/openapi.json",
        target=TargetType.DASHBOARD,
        style_hints=["minimal", "data-dense"],
        required_flows=["list tickets", "filter by priority"],
        max_iterations=3,
    )


@pytest.fixture
def sample_initial_state(sample_request: InputRequest) -> GraphState:
    return GraphState(
        request=sample_request,
        plan=[
            TaskDefinition(
                task_id="T-01",
                description="Design tokens, layout and component inventory",
                assigned_agent="designer",
                status="in_progress",
            ),
            TaskDefinition(
                task_id="T-02",
                description="Implement Dashboard components",
                assigned_agent="engineer",
                status="pending",
            ),
        ],
    )


@pytest.fixture
def tmp_artifact_dir(tmp_path: Path) -> Path:
    d = tmp_path / "artifacts"
    d.mkdir(parents=True, exist_ok=True)
    return d


@pytest.fixture
def tmp_trace(tmp_path: Path) -> TraceWriter:
    return TraceWriter(tmp_path / "trace.jsonl", run_id="test-designer-run")


# ===========================================================================
# 1. Initial Spec Generation Tests
# ===========================================================================

class TestInitialSpecGeneration:
    def test_generate_spec_with_scripted_llm(self, sample_initial_state: GraphState):
        fake_response = json.dumps({
            "tokens": {
                "colors": {
                    "primary": "#2563EB",
                    "background": "#F8FAFC",
                    "surface": "#FFFFFF",
                    "text": "#0F172A",
                    "text_muted": "#64748B",
                    "border": "#E2E8F0",
                    "error": "#DC2626",
                    "success": "#16A34A",
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
                    "h1": "2.25rem",
                    "h2": "1.75rem",
                    "h3": "1.25rem",
                    "body": "1rem",
                    "small": "0.875rem",
                },
            },
            "component_inventory": {
                "Dashboard": ["Header", "Sidebar", "TicketGrid", "FilterToolbar"],
                "TicketDetail": ["DetailPane", "ReplyBox"],
            },
            "layout_notes": "Two-column responsive layout with sticky sidebar and fluid content area.",
        })

        def fake_handler(agent_name: str, messages: list[dict], **kwargs):
            assert agent_name == "designer"
            prompt_content = messages[0]["content"]
            assert "A modern support dashboard" in prompt_content
            assert "minimal, data-dense" in prompt_content
            return fake_response

        set_fake_llm_handler(fake_handler)

        spec = generate_design_spec(sample_initial_state)

        assert isinstance(spec, DesignSpec)
        assert spec.tokens["colors"]["primary"] == "#2563EB"
        assert spec.tokens["colors"]["text"] == "#0F172A"
        assert spec.tokens["color_primary"] == "#2563EB"  # Flat alias
        assert spec.tokens["spacing"]["unit"] == "4px"
        assert spec.tokens["type_scale"]["font_family"] == "Inter, sans-serif"
        assert "Dashboard" in spec.component_inventory
        assert "Sidebar" in spec.component_inventory["Dashboard"]
        assert "Two-column" in spec.layout_notes

    def test_run_designer_node_attaches_proof_and_artifact(
        self,
        sample_initial_state: GraphState,
        tmp_artifact_dir: Path,
        tmp_trace: TraceWriter,
    ):
        fake_response = json.dumps({
            "tokens": {
                "colors": {
                    "primary": "#3B82F6",
                    "background": "#FFFFFF",
                    "text": "#111827",
                },
                "spacing": {"unit": "4px"},
                "type_scale": {"font_family": "Inter"},
            },
            "component_inventory": {"Dashboard": ["NavBar", "Card"]},
            "layout_notes": "Clean minimal card layout.",
        })

        set_fake_llm_handler(lambda *a, **k: fake_response)

        result = run_designer(
            sample_initial_state,
            trace_writer=tmp_trace,
            artifact_dir=tmp_artifact_dir,
        )

        assert "design_spec" in result
        assert "proofs" in result
        assert len(result["proofs"]) == 1

        proof = result["proofs"][0]
        assert proof.agent == "designer"
        assert proof.task_id == "T-01"
        assert len(proof.evidence) == 1
        assert proof.evidence[0].type == "design_spec"

        # Validate proof record
        is_valid, errors = validate_proof(proof)
        assert is_valid is True
        assert errors == []

        # Check evidence file persisted
        evidence_file = Path(proof.evidence[0].ref)
        assert evidence_file.exists()
        saved_data = json.loads(evidence_file.read_text(encoding="utf-8"))
        assert saved_data["tokens"]["colors"]["primary"] == "#3B82F6"

        # Trace check
        records = read_trace(tmp_trace.path)
        assert any(r.agent == "designer" and r.event_type == "handoff" for r in records)


# ===========================================================================
# 2. Spec Validation Tests
# ===========================================================================

class TestSpecValidation:
    def test_valid_spec_normalizes_and_passes(self):
        valid_data = {
            "tokens": {
                "color_primary": "#1E40AF",
                "color_background": "#F9FAFB",
                "color_text": "#111827",
                "spacing_unit": "4px",
                "font_family": "Roboto, sans-serif",
            },
            "component_inventory": {"Home": ["Hero", "Footer"]},
            "layout_notes": "Single column layout",
        }
        spec = validate_design_spec(valid_data)
        assert spec.tokens["colors"]["primary"] == "#1E40AF"
        assert spec.tokens["colors"]["background"] == "#F9FAFB"
        assert spec.tokens["colors"]["text"] == "#111827"
        assert spec.tokens["spacing"]["unit"] == "4px"
        assert spec.tokens["type_scale"]["font_family"] == "Roboto, sans-serif"

    def test_missing_tokens_raises_error(self):
        with pytest.raises(ValueError, match="missing required fields.*tokens"):
            validate_design_spec({
                "component_inventory": {"Home": ["Hero"]},
                "layout_notes": "Notes",
            })

    def test_missing_component_inventory_raises_error(self):
        with pytest.raises(ValueError, match="missing required fields.*component_inventory"):
            validate_design_spec({
                "tokens": {"color_primary": "#1E40AF"},
                "layout_notes": "Notes",
            })

    def test_missing_layout_notes_raises_error(self):
        with pytest.raises(ValueError, match="missing required fields.*layout_notes"):
            validate_design_spec({
                "tokens": {"color_primary": "#1E40AF"},
                "component_inventory": {"Home": ["Hero"]},
            })

    def test_empty_tokens_raises_error(self):
        with pytest.raises(ValueError, match="'tokens' must be a non-empty dictionary"):
            validate_design_spec({
                "tokens": {},
                "component_inventory": {"Home": ["Hero"]},
                "layout_notes": "Notes",
            })


# ===========================================================================
# 3. Critic Revision Tests (Contrast Findings)
# ===========================================================================

class TestCriticRevision:
    def test_revision_updates_tokens_and_records_rationale(
        self,
        sample_initial_state: GraphState,
        tmp_artifact_dir: Path,
        tmp_trace: TraceWriter,
    ):
        # Initial design spec with failing contrast (low contrast text #94A3B8 on light #F9FAFB)
        initial_spec = DesignSpec(
            tokens={
                "colors": {
                    "primary": "#3B82F6",
                    "background": "#F9FAFB",
                    "surface": "#FFFFFF",
                    "text": "#94A3B8",  # Low contrast: ~2.8:1
                    "text_muted": "#CBD5E1",
                    "border": "#E5E7EB",
                    "error": "#EF4444",
                    "success": "#10B981",
                },
                "spacing": {"unit": "4px"},
                "type_scale": {"font_family": "Inter, sans-serif"},
            },
            component_inventory={"Dashboard": ["SideBar", "TicketList"]},
            layout_notes="Two-column layout.",
        )
        sample_initial_state.design_spec = initial_spec

        # Critic revision request finding
        contrast_finding = {
            "target_agent": "designer",
            "finding": "Color contrast between text (#94A3B8) and background (#F9FAFB) is 2.8:1, failing WCAG AA (minimum 4.5:1).",
            "failing_pair": {"foreground": "#94A3B8", "background": "#F9FAFB"},
            "reason": "Body text contrast below WCAG AA",
        }
        sample_initial_state.audit_report = AuditReport(
            revision_requests=[contrast_finding],
            accepted=False,
        )

        # Fake LLM response fixing the contrast
        revised_llm_response = json.dumps({
            "tokens": {
                "colors": {
                    "primary": "#3B82F6",
                    "background": "#F9FAFB",
                    "surface": "#FFFFFF",
                    "text": "#1E293B",  # High contrast: > 11:1
                    "text_muted": "#475569",
                    "border": "#E5E7EB",
                    "error": "#EF4444",
                    "success": "#10B981",
                },
                "spacing": {"unit": "4px"},
                "type_scale": {"font_family": "Inter, sans-serif"},
            },
            "revisions": [
                {
                    "finding": contrast_finding["finding"],
                    "change": "Updated body text color from #94A3B8 to #1E293B and muted text to #475569.",
                    "changed_tokens": {
                        "colors.text": "#1E293B",
                        "colors.text_muted": "#475569",
                    },
                    "rationale": "Contrast ratio increased from 2.8:1 to 11.2:1 against #F9FAFB, exceeding WCAG AA minimum requirement of 4.5:1.",
                }
            ],
            "layout_notes": "Two-column layout with high contrast tokens.",
        })

        set_fake_llm_handler(lambda *a, **k: revised_llm_response)

        result = run_designer(
            sample_initial_state,
            trace_writer=tmp_trace,
            artifact_dir=tmp_artifact_dir,
        )

        revised_spec: DesignSpec = result["design_spec"]
        assert revised_spec.tokens["colors"]["text"] == "#1E293B"
        assert revised_spec.tokens["color_text"] == "#1E293B"

        # Verify revision records and rationale
        assert len(revised_spec.revisions) == 1
        rev = revised_spec.revisions[0]
        assert "contrast" in rev.finding.lower()
        assert "#1E293B" in rev.change
        assert "WCAG AA" in rev.rationale
        assert rev.changed_tokens.get("colors.text") == "#1E293B"

        # Verify proof record cites the updated spec file
        proof = result["proofs"][-1]
        assert proof.agent == "designer"
        assert "critic finding" in proof.claim.lower()
        assert Path(proof.evidence[0].ref).exists()
        is_valid, errors = validate_proof(proof)
        assert is_valid is True
        assert errors == []

    def test_revise_design_spec_direct_call(self):
        initial_spec = DesignSpec(
            tokens={"colors": {"primary": "#3B82F6", "background": "#FFFFFF", "text": "#AAAAAA"}},
            component_inventory={"Dashboard": ["Header"]},
            layout_notes="Initial layout",
        )

        findings = ["Contrast failure: text #AAAAAA on #FFFFFF has contrast 2.3:1."]

        llm_response = json.dumps({
            "tokens": {"colors": {"primary": "#3B82F6", "background": "#FFFFFF", "text": "#111827"}},
            "revisions": [{
                "finding": findings[0],
                "change": "Darkened text color to #111827",
                "changed_tokens": {"colors.text": "#111827"},
                "rationale": "Contrast ratio is now 16.1:1, passing WCAG AA and AAA.",
            }],
        })

        set_fake_llm_handler(lambda *a, **k: llm_response)

        revised = revise_design_spec(initial_spec, findings)
        assert revised.tokens["colors"]["text"] == "#111827"
        assert len(revised.revisions) == 1
        assert "16.1:1" in revised.revisions[0].rationale


# ===========================================================================
# 4. Vision-Capable LLM Call Tests
# ===========================================================================

class TestVisionCapableCalls:
    def test_vision_call_when_screenshot_path_provided(
        self,
        tmp_path: Path,
    ):
        initial_spec = DesignSpec(
            tokens={"colors": {"primary": "#1E40AF", "background": "#FFFFFF", "text": "#888888"}},
            component_inventory={"App": ["Main"]},
            layout_notes="Notes",
        )

        # Create a mock screenshot file
        screenshot_file = tmp_path / "screenshot.png"
        screenshot_file.write_bytes(b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR...")

        vision_called = {}

        def fake_handler(agent_name: str, messages: list[dict], **kwargs):
            vision_called["agent_name"] = agent_name
            vision_called["kwargs"] = kwargs
            vision_called["messages"] = messages
            return json.dumps({
                "tokens": {"colors": {"primary": "#1E40AF", "background": "#FFFFFF", "text": "#1E293B"}},
                "revisions": [{
                    "finding": "Visual inspection shows light text illegible against white background.",
                    "change": "Updated text color to #1E293B",
                    "changed_tokens": {"colors.text": "#1E293B"},
                    "rationale": "High contrast dark slate text provides clear visual hierarchy.",
                }],
            })

        set_fake_llm_handler(fake_handler)

        revised = revise_design_spec(
            initial_spec,
            findings=["Visual review indicates low contrast header text."],
            screenshot_path=screenshot_file,
        )

        assert vision_called["agent_name"] == "designer"
        assert vision_called["kwargs"].get("screenshot_path") == str(screenshot_file)

        # Verify multimodal structure in messages
        content = vision_called["messages"][0]["content"]
        assert isinstance(content, list)
        has_image = any(block.get("type") == "image" for block in content)
        assert has_image is True
        assert revised.tokens["colors"]["text"] == "#1E293B"


# ===========================================================================
# 5. Designer Constraint: Does Not Write Application Code
# ===========================================================================

class TestDesignerConstraints:
    def test_designer_does_not_write_code(
        self,
        sample_initial_state: GraphState,
        tmp_artifact_dir: Path,
    ):
        fake_response = json.dumps({
            "tokens": {"colors": {"primary": "#3B82F6", "background": "#FFFFFF", "text": "#111827"}},
            "component_inventory": {"Dashboard": ["Button"]},
            "layout_notes": "Layout notes",
        })
        set_fake_llm_handler(lambda *a, **k: fake_response)

        run_designer(sample_initial_state, artifact_dir=tmp_artifact_dir)

        # Assert no code files (.tsx, .ts, .jsx, .js, .css) were written to artifacts
        code_files = list(tmp_artifact_dir.rglob("*.tsx")) + \
                     list(tmp_artifact_dir.rglob("*.ts")) + \
                     list(tmp_artifact_dir.rglob("*.jsx")) + \
                     list(tmp_artifact_dir.rglob("*.js")) + \
                     list(tmp_artifact_dir.rglob("*.css"))
        assert len(code_files) == 0

        # Only design_spec.json was generated
        json_files = list(tmp_artifact_dir.rglob("*.json"))
        assert any("design_spec.json" in str(f) for f in json_files)
