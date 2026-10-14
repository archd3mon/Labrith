"""
Pydantic models and input loader for Labrith.

Mirrors the JSON Schemas in schemas/ and provides a validated loader
that gives clear error messages on invalid input.
"""

from __future__ import annotations

import json
from enum import Enum
from pathlib import Path
from typing import Any, Optional, Union

import jsonschema
from pydantic import BaseModel, Field

# ---------------------------------------------------------------------------
# Path to the schemas directory (resolved at import time)
# ---------------------------------------------------------------------------
_SCHEMAS_DIR = Path(__file__).resolve().parent.parent / "schemas"


# ---------------------------------------------------------------------------
# Enums
# ---------------------------------------------------------------------------
class TargetType(str, Enum):
    """Kind of interface to build (Design Doc §8)."""

    DASHBOARD = "dashboard"
    FORM_APP = "form_app"
    MIXED = "mixed"


class AgentName(str, Enum):
    """Canonical agent identifiers (Design Doc §3)."""

    PLANNER = "planner"
    DESIGNER = "designer"
    ENGINEER = "engineer"
    INTEGRATION = "integration"
    QA = "qa"
    CRITIC = "critic"


class RunStatus(str, Enum):
    """Status of a completed run (Design Doc §9)."""

    ACCEPTED = "accepted"
    PARTIAL = "partial"
    FAILED = "failed"


# ---------------------------------------------------------------------------
# Input models (Design Doc §8)
# ---------------------------------------------------------------------------
class InputRequest(BaseModel):
    """Validated request describing what to build."""

    brief: str = Field(..., min_length=1, description="Plain-language product description.")
    api_spec_url: Union[str, dict[str, Any]] = Field(
        ..., description="URL to an OpenAPI 3 spec, or inline OpenAPI JSON object."
    )
    target: TargetType = Field(..., description="Kind of interface to build.")
    style_hints: Optional[list[str]] = Field(
        default=None, description="Style hints, e.g. 'minimal', 'dark'."
    )
    required_flows: Optional[list[str]] = Field(
        default=None, description="User flows that must pass QA."
    )
    max_iterations: int = Field(
        default=3, ge=1, description="Iteration budget per task."
    )


# ---------------------------------------------------------------------------
# Proof-of-work models (Design Doc §6)
# ---------------------------------------------------------------------------
class EvidenceItem(BaseModel):
    """One piece of evidence backing a proof-of-work claim."""

    type: str = Field(..., min_length=1, description="Kind of evidence.")
    ref: str = Field(..., min_length=1, description="Path to the evidence file.")


class ProofOfWork(BaseModel):
    """Proof-of-work record attached to every agent output."""

    agent: AgentName = Field(..., description="Agent that produced this proof.")
    task_id: str = Field(..., min_length=1, description="Task identifier.")
    claim: str = Field(..., min_length=1, description="What the agent claims.")
    evidence: list[EvidenceItem] = Field(
        ..., min_length=1, description="Evidence items backing the claim."
    )
    reasoning: str = Field(..., min_length=1, description="Decision reasoning.")
    timestamp: str = Field(..., description="ISO 8601 timestamp.")


# ---------------------------------------------------------------------------
# Output / Quality-report models (Design Doc §9)
# ---------------------------------------------------------------------------
class BuildGate(BaseModel):
    passed: bool
    evidence: Optional[str] = None


class TestsGate(BaseModel):
    passed: bool
    flows_passed: Optional[int] = Field(default=None, ge=0)
    flows_total: Optional[int] = Field(default=None, ge=0)


class AccessibilityGate(BaseModel):
    passed: bool
    critical: Optional[int] = Field(default=None, ge=0)
    serious: Optional[int] = Field(default=None, ge=0)


class QualityGate(BaseModel):
    lighthouse_accessibility: Optional[float] = Field(default=None, ge=0, le=100)
    lighthouse_performance: Optional[float] = Field(default=None, ge=0, le=100)


class IntegrationGate(BaseModel):
    passed: bool
    documented_mismatches: Optional[int] = Field(default=None, ge=0)


class GatesSummary(BaseModel):
    build: BuildGate
    tests: TestsGate
    accessibility: AccessibilityGate
    quality: QualityGate
    integration: IntegrationGate


class IterationSummary(BaseModel):
    total: int = Field(..., ge=0)
    by_agent: dict[str, int] = Field(default_factory=dict)


class RevisionItem(BaseModel):
    by: str
    to: str
    reason: str
    resolved: bool


class UnresolvedItem(BaseModel):
    issue: str
    evidence: str


class QualityReport(BaseModel):
    """Final output quality report (Design Doc §9)."""

    run_id: str = Field(..., min_length=1)
    status: RunStatus
    iterations: IterationSummary
    gates: GatesSummary
    revisions: Optional[list[RevisionItem]] = Field(default=None)
    unresolved: list[UnresolvedItem] = Field(default_factory=list)
    preview_url: Optional[str] = Field(default=None)


# ---------------------------------------------------------------------------
# Planner output models (Design Doc §3, §8)
# ---------------------------------------------------------------------------
class PageDefinition(BaseModel):
    """A page in the planned frontend app."""

    name: str = Field(..., min_length=1, description="Page name (e.g. Dashboard, TicketDetail).")
    route: str = Field(..., min_length=1, description="URL route (e.g. '/', '/tickets/:id').")
    description: str = Field(..., description="Purpose and contents of the page.")
    components: list[str] = Field(
        default_factory=list, description="List of component names on this page."
    )


class UserFlow(BaseModel):
    """A user interaction flow that QA tests."""

    flow_id: str = Field(..., min_length=1, description="Identifier (e.g. F-01).")
    name: str = Field(..., min_length=1, description="Flow title (e.g. filter by priority).")
    description: str = Field(..., description="Steps and expected outcome of the flow.")
    steps: list[str] = Field(default_factory=list, description="Ordered interaction steps.")


class PlanTask(BaseModel):
    """A task in the plan produced by the Planner."""

    task_id: str = Field(..., min_length=1)
    description: str = Field(..., min_length=1)
    assigned_agent: str = Field(..., description="Agent assigned: designer, engineer, integration, qa, critic.")
    status: str = Field(default="pending", description="pending | in_progress | done | failed | escalated")
    depends_on: list[str] = Field(default_factory=list, description="Task IDs this task depends on.")
    required_flows: list[str] = Field(
        default_factory=list, description="User flows verified by or associated with this task."
    )


class PlanOutput(BaseModel):
    """Validated structured plan generated by the Planner agent."""

    pages: list[PageDefinition] = Field(..., min_length=1, description="List of application pages.")
    user_flows: list[UserFlow] = Field(..., min_length=1, description="Derived user flows.")
    tasks: list[PlanTask] = Field(..., min_length=1, description="Ordered tasks.")
    required_flows: list[str] = Field(default_factory=list, description="All required QA flows.")
    reasoning: Optional[str] = Field(default=None, description="Planner reasoning summary.")


# ---------------------------------------------------------------------------
# Input loader with JSON-Schema validation and clear error messages
# ---------------------------------------------------------------------------
def _load_input_schema() -> dict[str, Any]:
    """Load and cache the input JSON Schema."""
    schema_path = _SCHEMAS_DIR / "input.schema.json"
    with open(schema_path, "r", encoding="utf-8") as f:
        return json.load(f)


def load_input_request(data_or_path: Union[dict[str, Any], str, Path]) -> InputRequest:
    """Validate raw data or a JSON file path against input.schema.json and
    return an InputRequest.

    Raises ValueError with clear, itemised error messages on validation failure.
    """
    # Resolve input to a dict
    if isinstance(data_or_path, (str, Path)):
        path = Path(data_or_path)
        if not path.exists():
            raise ValueError(f"Input file not found: {path}")
        with open(path, "r", encoding="utf-8") as f:
            try:
                data = json.load(f)
            except json.JSONDecodeError as exc:
                raise ValueError(f"Invalid JSON in {path}: {exc}") from exc
    elif isinstance(data_or_path, dict):
        data = data_or_path
    else:
        raise TypeError(
            f"Expected dict, str or Path, got {type(data_or_path).__name__}"
        )

    # Validate against JSON Schema first (gives precise field-level errors)
    schema = _load_input_schema()
    validator = jsonschema.Draft202012Validator(schema)
    errors = sorted(validator.iter_errors(data), key=lambda e: list(e.absolute_path))

    if errors:
        messages: list[str] = []
        for err in errors:
            location = " -> ".join(str(p) for p in err.absolute_path) or "(root)"
            messages.append(f"  • {location}: {err.message}")
        raise ValueError(
            "Input validation failed:\n" + "\n".join(messages)
        )

    # Build the pydantic model (acts as a second validation layer)
    return InputRequest(**data)
