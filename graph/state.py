"""
Shared graph state for the Labrith supervisor/blackboard pattern.

This is the single pydantic model that every agent reads from and writes to.
The Planner routes based on this state; workers never call each other directly.
See Design Doc §4 (orchestration) and §6 (proof-of-work).
"""

from __future__ import annotations

from typing import Any, Optional

from pydantic import BaseModel, Field

from lib.models import InputRequest, ProofOfWork


# ---------------------------------------------------------------------------
# Sub-models for structured state fields
# ---------------------------------------------------------------------------
class TaskDefinition(BaseModel):
    """A single task in the plan produced by the Planner."""

    task_id: str = Field(..., min_length=1)
    description: str = Field(..., min_length=1)
    assigned_agent: Optional[str] = Field(
        default=None, description="Agent responsible for this task."
    )
    status: str = Field(
        default="pending",
        description="pending | in_progress | done | failed | escalated",
    )
    depends_on: list[str] = Field(
        default_factory=list, description="Task IDs this task depends on."
    )


class DesignSpec(BaseModel):
    """Design tokens and layout produced by the Designer."""

    tokens: dict[str, Any] = Field(
        default_factory=dict,
        description="Design tokens: colours, spacing, type scale.",
    )
    component_inventory: dict[str, Any] = Field(
        default_factory=dict,
        description="Component inventory per page.",
    )
    layout_notes: Optional[str] = Field(
        default=None, description="Free-form layout notes."
    )


class IntegrationReport(BaseModel):
    """Output of the Integration agent."""

    api_client_path: Optional[str] = Field(
        default=None, description="Path to the generated API client."
    )
    request_response_log: list[dict[str, Any]] = Field(
        default_factory=list, description="Captured request/response pairs."
    )
    mismatches: list[dict[str, Any]] = Field(
        default_factory=list, description="Spec mismatches found."
    )


class QAResults(BaseModel):
    """Output of the QA agent."""

    flows: list[dict[str, Any]] = Field(
        default_factory=list, description="Per-flow test results."
    )
    screenshots: list[str] = Field(
        default_factory=list, description="Paths to captured screenshots."
    )
    console_logs: list[str] = Field(
        default_factory=list, description="Paths to captured console logs."
    )


class AuditReport(BaseModel):
    """Output of the Critic (accessibility and design audit)."""

    axe_violations: list[dict[str, Any]] = Field(
        default_factory=list, description="axe-core violations."
    )
    lighthouse_scores: dict[str, float] = Field(
        default_factory=dict, description="Lighthouse metric scores."
    )
    revision_requests: list[dict[str, Any]] = Field(
        default_factory=list,
        description="Concrete revision requests sent to other agents.",
    )
    accepted: Optional[bool] = Field(
        default=None, description="Whether the Critic accepts the build."
    )


class UnresolvedIssue(BaseModel):
    """An issue the Planner could not resolve before the budget ran out."""

    issue: str = Field(..., min_length=1)
    evidence: str = Field(..., min_length=1, description="Path or reference.")
    agent: Optional[str] = Field(
        default=None, description="Agent that last touched this issue."
    )


# ---------------------------------------------------------------------------
# Main shared state
# ---------------------------------------------------------------------------
class GraphState(BaseModel):
    """Shared blackboard state for the LangGraph supervisor pattern.

    Every agent reads and writes to this object.  The Planner uses it to
    decide the next step.  See Design Doc §2 and §4.
    """

    # --- Input ---
    request: InputRequest = Field(..., description="Validated input request.")

    # --- Plan ---
    plan: Optional[list[TaskDefinition]] = Field(
        default=None, description="Ordered task list produced by the Planner."
    )

    # --- Agent outputs ---
    design_spec: Optional[DesignSpec] = Field(
        default=None, description="Design tokens and layout from the Designer."
    )
    code_artifacts: dict[str, Any] = Field(
        default_factory=dict,
        description="Generated file paths and metadata from the Engineer.",
    )
    integration_report: Optional[IntegrationReport] = Field(
        default=None, description="API integration findings."
    )
    qa_results: Optional[QAResults] = Field(
        default=None, description="QA test results."
    )
    audit_report: Optional[AuditReport] = Field(
        default=None, description="Accessibility and quality audit."
    )

    # --- Proof-of-work ---
    proofs: list[ProofOfWork] = Field(
        default_factory=list,
        description="Validated proof-of-work records from all agents.",
    )

    # --- Iteration tracking ---
    iteration_counters: dict[str, int] = Field(
        default_factory=dict,
        description="Iteration count keyed by task_id or 'run_total'.",
    )

    # --- Run status ---
    status: str = Field(
        default="pending",
        description="pending | in_progress | accepted | partial | failed",
    )
    unresolved: list[UnresolvedIssue] = Field(
        default_factory=list,
        description="Issues unresolved when the budget ran out.",
    )
