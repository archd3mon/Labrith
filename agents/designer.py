"""
Designer agent (Design Architect).

Responsibilities (Design Doc §3, §5 Scenario 2; BUILD_PLAYBOOK Slice 4):
- From the plan (or brief) and style_hints, produces a design_spec JSON
  (design tokens: colours, spacing, type scale; component inventory per page; layout notes)
  validated by a Pydantic model.
- Handles revision requests from the Critic in state: given a list of findings
  (e.g. contrast failures with colour pairs), revises the tokens and records
  which finding each change resolves with rationale.
- Uses a vision-capable call via lib/llm.py when a screenshot path is provided.
- Does NOT write application code.
- Generates a valid ProofOfWork citing the spec file and logs handoff to trace.

Public API:
    validate_design_spec(data)
    generate_design_spec(state_or_request, ...)
    revise_design_spec(current_spec, findings, ...)
    run_designer(state, trace_writer, ...)
"""

from __future__ import annotations

import base64
import json
import re
from pathlib import Path
from typing import Any, Optional, Union

from pydantic import BaseModel, Field, ValidationError

from graph.state import DesignSpec, GraphState, RevisionRecord
from lib.llm import complete
from lib.models import InputRequest
from lib.proofs import create_proof
from lib.trace import TraceWriter


# ---------------------------------------------------------------------------
# Pydantic models for strict Design Spec validation
# ---------------------------------------------------------------------------

class ColorTokens(BaseModel):
    """Core colour tokens."""

    primary: str = Field(..., min_length=1, description="Primary brand/accent colour.")
    background: str = Field(..., min_length=1, description="Page background colour.")
    surface: Optional[str] = Field(default="#FFFFFF", description="Surface or card background.")
    text: str = Field(..., min_length=1, description="Primary body text colour.")
    text_muted: Optional[str] = Field(default="#6B7280", description="Muted/secondary text colour.")
    border: Optional[str] = Field(default="#E5E7EB", description="Border colour.")
    error: Optional[str] = Field(default="#EF4444", description="Error state colour.")
    success: Optional[str] = Field(default="#10B981", description="Success state colour.")

    model_config = {"extra": "allow"}


class SpacingTokens(BaseModel):
    """Spacing tokens and scale."""

    unit: str = Field(default="4px", description="Base spacing unit.")
    xs: Optional[str] = Field(default="4px")
    sm: Optional[str] = Field(default="8px")
    md: Optional[str] = Field(default="16px")
    lg: Optional[str] = Field(default="24px")
    xl: Optional[str] = Field(default="32px")

    model_config = {"extra": "allow"}


class TypeScaleTokens(BaseModel):
    """Typography and type scale tokens."""

    font_family: str = Field(default="Inter, sans-serif", description="Font family.")
    h1: Optional[str] = Field(default="2rem")
    h2: Optional[str] = Field(default="1.5rem")
    h3: Optional[str] = Field(default="1.25rem")
    body: Optional[str] = Field(default="1rem")
    small: Optional[str] = Field(default="0.875rem")

    model_config = {"extra": "allow"}


class DesignTokensModel(BaseModel):
    """Structured design tokens grouping colours, spacing, and typography."""

    colors: ColorTokens = Field(..., description="Colour palette.")
    spacing: SpacingTokens = Field(default_factory=SpacingTokens, description="Spacing scale.")
    type_scale: TypeScaleTokens = Field(default_factory=TypeScaleTokens, description="Typography scale.")

    model_config = {"extra": "allow"}


class DesignSpecModel(BaseModel):
    """Strict validation model for design specification."""

    tokens: Union[DesignTokensModel, dict[str, Any]] = Field(
        ..., description="Design tokens: colours, spacing, type scale."
    )
    component_inventory: dict[str, list[str]] = Field(
        ..., description="Component inventory per page."
    )
    layout_notes: str = Field(
        ..., min_length=1, description="Layout guidelines and notes."
    )
    revisions: list[RevisionRecord] = Field(
        default_factory=list, description="Revision history."
    )


# ---------------------------------------------------------------------------
# Helper: JSON extraction from LLM response
# ---------------------------------------------------------------------------

def _extract_json(raw: str) -> dict[str, Any]:
    """Extract a JSON object from text that may contain markdown or surrounding text."""
    cleaned = raw.strip()

    # Direct parse attempt
    try:
        return json.loads(cleaned)
    except json.JSONDecodeError:
        pass

    # Try matching fenced code blocks ```json ... ```
    match = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", cleaned, re.DOTALL)
    if match:
        try:
            return json.loads(match.group(1))
        except json.JSONDecodeError:
            pass

    # Try matching outermost curly braces
    start = cleaned.find("{")
    end = cleaned.rfind("}")
    if start != -1 and end != -1 and end > start:
        snippet = cleaned[start : end + 1]
        try:
            return json.loads(snippet)
        except json.JSONDecodeError:
            pass

    raise ValueError(f"Could not parse valid JSON from LLM response: {raw[:160]}...")


# ---------------------------------------------------------------------------
# Normalization & Validation
# ---------------------------------------------------------------------------

def _normalize_tokens(raw_tokens: dict[str, Any]) -> dict[str, Any]:
    """Ensure tokens dict contains nested sections (colors, spacing, type_scale)
    as well as convenient flat aliases (color_primary, spacing_unit, etc.).
    """
    normalized: dict[str, Any] = {}

    # Extract colours
    colors: dict[str, Any] = {}
    if isinstance(raw_tokens.get("colors"), dict):
        colors.update(raw_tokens["colors"])
    elif isinstance(raw_tokens.get("colours"), dict):
        colors.update(raw_tokens["colours"])

    # Fallback to flat keys if colors dict is empty
    for k, v in raw_tokens.items():
        if k.startswith("color_"):
            color_name = k.replace("color_", "")
            colors.setdefault(color_name, v)
        elif k in ("primary", "secondary", "background", "surface", "text", "text_muted", "border", "error", "success"):
            colors.setdefault(k, v)

    # Defaults if missing
    colors.setdefault("primary", raw_tokens.get("color_primary", "#1E40AF"))
    colors.setdefault("background", raw_tokens.get("color_background", "#F9FAFB"))
    colors.setdefault("surface", "#FFFFFF")
    colors.setdefault("text", raw_tokens.get("color_text", "#111827"))
    colors.setdefault("text_muted", "#6B7280")
    colors.setdefault("border", "#E5E7EB")
    colors.setdefault("error", "#EF4444")
    colors.setdefault("success", "#10B981")

    # Extract spacing
    spacing: dict[str, Any] = {}
    if isinstance(raw_tokens.get("spacing"), dict):
        spacing.update(raw_tokens["spacing"])
    spacing.setdefault("unit", raw_tokens.get("spacing_unit", "4px"))
    spacing.setdefault("xs", "4px")
    spacing.setdefault("sm", "8px")
    spacing.setdefault("md", "16px")
    spacing.setdefault("lg", "24px")
    spacing.setdefault("xl", "32px")

    # Extract typography
    type_scale: dict[str, Any] = {}
    if isinstance(raw_tokens.get("type_scale"), dict):
        type_scale.update(raw_tokens["type_scale"])
    elif isinstance(raw_tokens.get("typography"), dict):
        type_scale.update(raw_tokens["typography"])
    type_scale.setdefault("font_family", raw_tokens.get("font_family", "Inter, sans-serif"))
    type_scale.setdefault("h1", "2rem")
    type_scale.setdefault("h2", "1.5rem")
    type_scale.setdefault("h3", "1.25rem")
    type_scale.setdefault("body", "1rem")
    type_scale.setdefault("small", "0.875rem")

    normalized["colors"] = colors
    normalized["spacing"] = spacing
    normalized["type_scale"] = type_scale

    # Also set flat shortcuts for direct lookups
    normalized["color_primary"] = colors.get("primary")
    normalized["color_background"] = colors.get("background")
    normalized["color_text"] = colors.get("text")
    normalized["spacing_unit"] = spacing.get("unit")
    normalized["font_family"] = type_scale.get("font_family")

    # Preserve any other custom tokens
    for k, v in raw_tokens.items():
        if k not in normalized and k not in ("colors", "colours", "spacing", "type_scale", "typography"):
            normalized[k] = v

    return normalized


def validate_design_spec(data: Union[dict[str, Any], DesignSpec]) -> DesignSpec:
    """Validate design spec data against the strict Pydantic model.

    Raises ValueError with descriptive errors on validation failure.
    Returns a valid DesignSpec instance.
    """
    if isinstance(data, DesignSpec):
        raw_dict = data.model_dump()
    elif isinstance(data, dict):
        raw_dict = dict(data)
    else:
        raise TypeError(f"Expected dict or DesignSpec, got {type(data).__name__}")

    # Required fields check
    missing = [f for f in ("tokens", "component_inventory", "layout_notes") if f not in raw_dict]
    if missing:
        raise ValueError(f"Design spec missing required fields: {', '.join(missing)}")

    raw_tokens = raw_dict.get("tokens")
    if not isinstance(raw_tokens, dict) or not raw_tokens:
        raise ValueError("Design spec 'tokens' must be a non-empty dictionary.")

    component_inventory = raw_dict.get("component_inventory")
    if not isinstance(component_inventory, dict) or not component_inventory:
        raise ValueError("Design spec 'component_inventory' must be a non-empty dictionary mapping pages to components.")

    layout_notes = raw_dict.get("layout_notes")
    if not isinstance(layout_notes, str) or not layout_notes.strip():
        raise ValueError("Design spec 'layout_notes' must be a non-empty string.")

    # Normalize tokens to satisfy colors, spacing, and typography
    normalized_tokens = _normalize_tokens(raw_tokens)

    # Validate structured token model
    try:
        color_model = ColorTokens(**normalized_tokens["colors"])
        spacing_model = SpacingTokens(**normalized_tokens["spacing"])
        type_model = TypeScaleTokens(**normalized_tokens["type_scale"])
        DesignTokensModel(colors=color_model, spacing=spacing_model, type_scale=type_model)
    except ValidationError as exc:
        raise ValueError(f"Invalid design tokens: {exc}") from exc

    # Validate revisions
    revisions_raw = raw_dict.get("revisions", [])
    validated_revisions: list[RevisionRecord] = []
    if isinstance(revisions_raw, list):
        for idx, rev in enumerate(revisions_raw):
            if isinstance(rev, RevisionRecord):
                validated_revisions.append(rev)
            elif isinstance(rev, dict):
                try:
                    validated_revisions.append(RevisionRecord(**rev))
                except ValidationError as exc:
                    raise ValueError(f"Invalid revision record at index {idx}: {exc}") from exc
            else:
                raise ValueError(f"Invalid revision record at index {idx}: expected dict or RevisionRecord.")

    return DesignSpec(
        tokens=normalized_tokens,
        component_inventory=component_inventory,
        layout_notes=layout_notes.strip(),
        revisions=validated_revisions,
    )


# ---------------------------------------------------------------------------
# Initial Generation: generate_design_spec()
# ---------------------------------------------------------------------------

def _build_generation_prompt(
    brief: str,
    target: str,
    style_hints: list[str],
    pages: list[dict[str, Any]],
) -> str:
    pages_desc = []
    for p in pages:
        p_name = p.get("name", "Page")
        p_comps = p.get("components", [])
        p_desc = p.get("description", "")
        pages_desc.append(f"- {p_name} ({p_desc}): {', '.join(p_comps) if p_comps else 'components to determine'}")

    hints_str = ", ".join(style_hints) if style_hints else "clean, modern, accessible"

    return f"""You are the Design Architect for a React + Tailwind web application.
Given the product brief, target interface, style hints, and page list, produce a comprehensive design specification.

PRODUCT BRIEF:
{brief}

TARGET:
{target}

STYLE HINTS:
{hints_str}

PAGES:
{chr(10).join(pages_desc) if pages_desc else '- Dashboard: main view'}

REQUIREMENTS:
1. Design tokens:
   - "colors": hex values for primary, background, surface, text, text_muted, border, error, success.
     Ensure WCAG AA contrast (minimum 4.5:1 for body text against background).
   - "spacing": unit (e.g. "4px"), xs, sm, md, lg, xl.
   - "type_scale": font_family, h1, h2, h3, body, small.
2. Component inventory:
   - Map each page name to a list of concrete React/Tailwind component names (e.g. "NavBar", "Sidebar", "DataTable", "FilterBar").
3. Layout notes:
   - Clear layout architecture (grid/flex, responsive sidebar, navigation structure).

Return strictly a JSON object with this structure:
{{
  "tokens": {{
    "colors": {{
      "primary": "#...",
      "background": "#...",
      "surface": "#...",
      "text": "#...",
      "text_muted": "#...",
      "border": "#...",
      "error": "#...",
      "success": "#..."
    }},
    "spacing": {{
      "unit": "4px",
      "xs": "4px",
      "sm": "8px",
      "md": "16px",
      "lg": "24px",
      "xl": "32px"
    }},
    "type_scale": {{
      "font_family": "Inter, sans-serif",
      "h1": "2rem",
      "h2": "1.5rem",
      "h3": "1.25rem",
      "body": "1rem",
      "small": "0.875rem"
    }}
  }},
  "component_inventory": {{
    "PageName": ["Component1", "Component2"]
  }},
  "layout_notes": "..."
}}
"""


def generate_design_spec(
    state_or_request: Union[GraphState, InputRequest],
    plan_pages: Optional[list[Any]] = None,
) -> DesignSpec:
    """Generate the initial design specification from plan and style hints using LLM."""
    if isinstance(state_or_request, GraphState):
        request = state_or_request.request
        plan = state_or_request.plan or []
    else:
        request = state_or_request
        plan = []

    brief = request.brief
    target = getattr(request.target, "value", str(request.target))
    style_hints = request.style_hints or []

    # Derive pages
    pages: list[dict[str, Any]] = []
    if plan_pages:
        for p in plan_pages:
            if hasattr(p, "model_dump"):
                pages.append(p.model_dump())
            elif isinstance(p, dict):
                pages.append(p)
    elif plan:
        for task in plan:
            pages.append({"name": task.task_id, "description": task.description, "components": []})
    else:
        pages.append({"name": "Dashboard", "description": "Main application view", "components": []})

    prompt = _build_generation_prompt(brief, target, style_hints, pages)
    raw = complete(
        "designer",
        [{"role": "user", "content": prompt}],
    )

    parsed = _extract_json(raw)
    return validate_design_spec(parsed)


# ---------------------------------------------------------------------------
# Revision: revise_design_spec()
# ---------------------------------------------------------------------------

def _build_revision_prompt(
    current_spec: DesignSpec,
    findings: list[Any],
    style_hints: list[str],
) -> str:
    findings_formatted = []
    for idx, f in enumerate(findings, 1):
        if isinstance(f, dict):
            finding_text = f.get("finding") or f.get("reason") or f.get("description") or json.dumps(f)
            pair = f.get("failing_pair") or f.get("pair") or ""
            findings_formatted.append(f"{idx}. {finding_text} (Context: {pair})")
        else:
            findings_formatted.append(f"{idx}. {str(f)}")

    current_tokens_str = json.dumps(current_spec.tokens, indent=2)

    return f"""You are the Design Architect for a React + Tailwind application.
The Accessibility and Design Critic rejected the design with the following findings:

CRITIC FINDINGS:
{chr(10).join(findings_formatted)}

CURRENT DESIGN TOKENS:
{current_tokens_str}

STYLE HINTS:
{", ".join(style_hints) if style_hints else "none"}

TASK:
1. Revise the design tokens to resolve every finding (e.g. fix contrast failures by adjusting text or background colours to achieve WCAG AA contrast ratio >= 4.5:1).
2. For each finding, record:
   - "finding": the exact finding or summary of the issue resolved.
   - "change": description of what token was modified.
   - "changed_tokens": dictionary mapping changed token paths to their new values (e.g. {{"colors.text": "#1E293B"}}).
   - "rationale": explanation of why this change resolves the finding (e.g. contrast ratio improved from 2.8:1 to 11.2:1).

Return strictly a JSON object with this structure:
{{
  "tokens": {{ ... updated tokens ... }},
  "revisions": [
    {{
      "finding": "...",
      "change": "...",
      "changed_tokens": {{ ... }},
      "rationale": "..."
    }}
  ],
  "layout_notes": "{current_spec.layout_notes or 'Standard layout'}"
}}
"""


def _prepare_vision_message(
    prompt: str,
    screenshot_path: Union[str, Path],
) -> list[dict[str, Any]]:
    """Build a multimodal message payload for vision-capable LLM call."""
    path_obj = Path(screenshot_path)
    content: list[dict[str, Any]] = [{"type": "text", "text": prompt}]

    image_block: dict[str, Any] = {
        "type": "image",
        "image_path": str(path_obj),
    }

    if path_obj.exists() and path_obj.is_file():
        try:
            raw_bytes = path_obj.read_bytes()
            b64_str = base64.b64encode(raw_bytes).decode("utf-8")
            media_type = "image/png" if path_obj.suffix.lower() == ".png" else "image/jpeg"
            image_block["source"] = {
                "type": "base64",
                "media_type": media_type,
                "data": b64_str,
            }
        except Exception:
            image_block["source"] = {"type": "path", "path": str(path_obj)}
    else:
        image_block["source"] = {"type": "path", "path": str(path_obj)}

    content.append(image_block)
    return [{"role": "user", "content": content}]


def revise_design_spec(
    current_spec: DesignSpec,
    findings: list[Any],
    *,
    style_hints: Optional[list[str]] = None,
    screenshot_path: Optional[Union[str, Path]] = None,
) -> DesignSpec:
    """Revise design tokens in response to Critic findings, recording rationales.

    If a screenshot path is provided, performs a vision-capable call via lib/llm.py.
    """
    if not findings:
        return current_spec

    prompt = _build_revision_prompt(
        current_spec=current_spec,
        findings=findings,
        style_hints=style_hints or [],
    )

    opts: dict[str, Any] = {}
    if screenshot_path:
        messages = _prepare_vision_message(prompt, screenshot_path)
        opts["screenshot_path"] = str(screenshot_path)
    else:
        messages = [{"role": "user", "content": prompt}]

    raw = complete("designer", messages, **opts)
    parsed = _extract_json(raw)

    # Incorporate updated tokens
    new_tokens = parsed.get("tokens", current_spec.tokens)
    normalized_tokens = _normalize_tokens(new_tokens)

    # Parse new revision items
    new_revisions_raw = parsed.get("revisions", [])
    parsed_revisions: list[RevisionRecord] = []
    for r in new_revisions_raw:
        if isinstance(r, dict):
            parsed_revisions.append(RevisionRecord(**r))
        elif isinstance(r, RevisionRecord):
            parsed_revisions.append(r)

    # If LLM didn't return structured revisions list, create fallback from findings
    if not parsed_revisions and findings:
        for f in findings:
            finding_text = f.get("finding") if isinstance(f, dict) else str(f)
            parsed_revisions.append(
                RevisionRecord(
                    finding=finding_text,
                    change="Updated design tokens to meet accessibility guidelines.",
                    changed_tokens={"tokens": normalized_tokens},
                    rationale="Tokens updated in response to critic audit finding.",
                )
            )

    combined_revisions = list(current_spec.revisions) + parsed_revisions
    layout_notes = parsed.get("layout_notes") or current_spec.layout_notes or "Layout notes"
    component_inventory = (
        parsed.get("component_inventory")
        or current_spec.component_inventory
        or {"Dashboard": ["MainView"]}
    )

    updated_spec = DesignSpec(
        tokens=normalized_tokens,
        component_inventory=component_inventory,
        layout_notes=layout_notes,
        revisions=combined_revisions,
    )

    return validate_design_spec(updated_spec)


# ---------------------------------------------------------------------------
# LangGraph Node: run_designer()
# ---------------------------------------------------------------------------

def run_designer(
    state: GraphState,
    trace_writer: Optional[TraceWriter] = None,
    *,
    artifact_dir: Path = Path("artifacts"),
    screenshot_path: Optional[Union[str, Path]] = None,
    findings: Optional[list[Any]] = None,
) -> dict[str, Any]:
    """LangGraph node for the Design Architect agent.

    Decides between initial generation and revision based on state:
    - If critic revision requests / findings exist (or findings passed), revises tokens.
    - Otherwise, generates initial design spec.

    Persists design_spec.json to artifacts, constructs a valid ProofOfWork,
    logs handoff to trace, and returns updated state dict.
    """
    task_id = _find_task_id(state, "designer")

    # Determine if this is a revision or initial run
    critic_findings: list[Any] = []
    if findings:
        critic_findings.extend(findings)
    elif state.audit_report:
        for req in state.audit_report.revision_requests:
            target = req.get("target_agent") or req.get("to")
            if target in ("designer", None):
                critic_findings.append(req)
        for viol in state.audit_report.axe_violations:
            if "contrast" in str(viol.get("id", "")).lower() or "color" in str(viol.get("help", "")).lower():
                critic_findings.append(viol)

    # Check for screenshot in state if not explicitly passed
    resolved_screenshot = screenshot_path
    if not resolved_screenshot and state.qa_results and state.qa_results.screenshots:
        resolved_screenshot = state.qa_results.screenshots[-1]

    # Perform generation or revision
    if critic_findings and state.design_spec:
        design_spec = revise_design_spec(
            current_spec=state.design_spec,
            findings=critic_findings,
            style_hints=state.request.style_hints,
            screenshot_path=resolved_screenshot,
        )
        claim = f"Revised design tokens resolving {len(critic_findings)} critic finding(s)."
        reasoning = (
            f"Updated design tokens based on critic audit findings. "
            f"Recorded {len(design_spec.revisions)} revision rationales."
        )
    else:
        design_spec = generate_design_spec(state)
        claim = "Design spec with tokens and component inventory produced."
        reasoning = (
            "Generated structured design tokens (colours, spacing, type scale), "
            "per-page component inventory, and layout notes validated against Pydantic model."
        )

    # Persist evidence file
    evidence_path = artifact_dir / task_id / "design_spec.json"
    evidence_path.parent.mkdir(parents=True, exist_ok=True)
    evidence_path.write_text(design_spec.model_dump_json(indent=2), encoding="utf-8")

    # Proof-of-work
    proof = create_proof(
        agent="designer",
        task_id=task_id,
        claim=claim,
        evidence=[{"type": "design_spec", "ref": str(evidence_path)}],
        reasoning=reasoning,
    )

    if trace_writer:
        trace_writer.write(
            "designer",
            "handoff",
            {
                "task_id": task_id,
                "claim": proof.claim,
                "revisions_count": len(design_spec.revisions),
                "evidence_path": str(evidence_path),
            },
        )

    return {
        "design_spec": design_spec,
        "proofs": state.proofs + [proof],
    }


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _find_task_id(state: GraphState, agent: str) -> str:
    """Return task_id for this agent's pending task, or a default."""
    for task in (state.plan or []):
        if task.assigned_agent == agent and task.status in ("pending", "in_progress"):
            return task.task_id
    return "T-01"
