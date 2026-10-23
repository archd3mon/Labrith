"""
graph/gates.py — The five verification gates and quality report generator.

Design Doc §6 ("Verification gates a build must pass before the Planner accepts it"):
  1. Build gate: npm run build and the type checker exit cleanly (Engineer evidence: build log).
  2. Test gate: the generated app's own unit tests pass, and every required user flow passes in Playwright (QA evidence: results, screenshots).
  3. Accessibility gate: no critical or serious axe-core violations (Critic evidence: audit report).
  4. Quality gate: Lighthouse performance and accessibility above the configured threshold (Critic evidence: scores).
  5. Integration gate: every API call in the generated client matches the spec, or each mismatch is documented (Integration evidence: mismatch report).

Design Doc §9 & schemas/output.schema.json:
  Produces quality_report.json strictly matching schemas/output.schema.json.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Optional, Union

import jsonschema

from graph.state import GraphState


# Default quality score thresholds per Design Doc §6 Gate 4
DEFAULT_ACCESSIBILITY_THRESHOLD = 90.0
DEFAULT_PERFORMANCE_THRESHOLD = 80.0

SCHEMA_PATH = Path(__file__).resolve().parent.parent / "schemas" / "output.schema.json"


# ---------------------------------------------------------------------------
# Individual Verification Gates
# ---------------------------------------------------------------------------

def evaluate_build_gate(state: GraphState) -> dict[str, Any]:
    """Gate 1: Build gate.

    npm run build and the type checker exit cleanly (Engineer evidence: build log).
    Schema: {"passed": bool, "evidence"?: str}
    """
    passed = False
    evidence: Optional[str] = None

    # Check code_artifacts for successful build log
    if state.code_artifacts:
        for key, val in state.code_artifacts.items():
            if isinstance(val, dict):
                if val.get("status") == "success":
                    passed = True
                    log_file = val.get("build_log")
                    if log_file:
                        evidence = str(log_file)
                        break

    # Also check proofs for Engineer evidence if not found in code_artifacts
    if not passed:
        for proof in state.proofs:
            agent_str = str(proof.agent.value if hasattr(proof.agent, "value") else proof.agent)
            if agent_str == "engineer" and "built cleanly" in proof.claim.lower():
                passed = True
                for ev in proof.evidence:
                    if "build" in ev.type.lower() or "log" in ev.type.lower():
                        evidence = ev.ref
                        break
                if passed:
                    break

    res: dict[str, Any] = {"passed": passed}
    if evidence:
        res["evidence"] = evidence
    return res


def evaluate_tests_gate(state: GraphState) -> dict[str, Any]:
    """Gate 2: Test gate.

    The generated app's own unit tests pass, and every required user flow
    passes in Playwright (QA evidence: results, screenshots).
    Schema: {"passed": bool, "flows_passed"?: int, "flows_total"?: int}
    """
    flows_passed = 0
    flows_total = 0
    passed = False

    if state.qa_results and state.qa_results.flows:
        flows_total = len(state.qa_results.flows)
        flows_passed = sum(
            1 for f in state.qa_results.flows
            if f.get("passed") is True or f.get("status") in ("pass", "passed")
        )
        passed = (flows_total > 0 and flows_passed == flows_total)
    else:
        # Check QA proofs
        qa_proofs = [
            p for p in state.proofs
            if str(p.agent.value if hasattr(p.agent, "value") else p.agent) == "qa"
        ]
        required_count = len(state.request.required_flows or [])
        if required_count > 0 and len(qa_proofs) >= required_count:
            flows_total = required_count
            flows_passed = sum(1 for p in qa_proofs if "pass" in p.claim.lower())
            passed = (flows_passed >= flows_total)
        elif qa_proofs:
            flows_total = len(qa_proofs)
            flows_passed = sum(1 for p in qa_proofs if "pass" in p.claim.lower())
            passed = (flows_passed == flows_total and flows_total > 0)

    return {
        "passed": passed,
        "flows_passed": flows_passed,
        "flows_total": flows_total,
    }


def evaluate_accessibility_gate(state: GraphState) -> dict[str, Any]:
    """Gate 3: Accessibility gate.

    No critical or serious axe-core violations (Critic evidence: audit report).
    Schema: {"passed": bool, "critical"?: int, "serious"?: int}
    """
    critical = 0
    serious = 0
    passed = False

    if state.audit_report is not None:
        for viol in state.audit_report.axe_violations:
            impact = viol.get("impact", "").lower()
            if impact == "critical":
                critical += 1
            elif impact == "serious":
                serious += 1

        passed = (critical == 0 and serious == 0 and state.audit_report.accepted is not False)
    else:
        # Check Critic proofs
        for proof in state.proofs:
            agent_str = str(proof.agent.value if hasattr(proof.agent, "value") else proof.agent)
            if agent_str == "critic" and ("accepted" in proof.claim.lower() or "passed" in proof.claim.lower()):
                passed = True
                break

    return {
        "passed": passed,
        "critical": critical,
        "serious": serious,
    }


def evaluate_quality_gate(state: GraphState) -> dict[str, Any]:
    """Gate 4: Quality gate.

    Lighthouse performance and accessibility above the configured threshold (Critic evidence: scores).
    Schema: {"lighthouse_accessibility"?: float, "lighthouse_performance"?: float}
    Note: 'passed' is not a field in schemas/output.schema.json quality gate definition.
    """
    lh_acc = 0.0
    lh_perf = 0.0

    if state.audit_report and state.audit_report.lighthouse_scores:
        lh_acc = float(state.audit_report.lighthouse_scores.get("accessibility", 0.0))
        lh_perf = float(state.audit_report.lighthouse_scores.get("performance", 0.0))
    # If no real audit data exists, leave scores at 0.0 — do not fabricate values.

    res: dict[str, Any] = {}
    if lh_acc > 0.0:
        res["lighthouse_accessibility"] = round(lh_acc, 1)
    if lh_perf > 0.0:
        res["lighthouse_performance"] = round(lh_perf, 1)

    return res


def evaluate_integration_gate(state: GraphState) -> dict[str, Any]:
    """Gate 5: Integration gate.

    Every API call in the generated client matches the spec, or each mismatch
    is documented (Integration evidence: mismatch report).
    Schema: {"passed": bool, "documented_mismatches"?: int}
    """
    passed = False
    documented_mismatches = 0

    if state.integration_report is not None:
        documented_mismatches = len(state.integration_report.mismatches)
        # Passed if report explicitly passed or if mismatches are documented
        if state.integration_report.passed is not None:
            passed = state.integration_report.passed
        else:
            passed = True  # Mismatches documented
    else:
        # Check Integration proofs — only pass if proof claim indicates success
        for proof in state.proofs:
            agent_str = str(proof.agent.value if hasattr(proof.agent, "value") else proof.agent)
            if agent_str == "integration" and (
                "matched" in proof.claim.lower()
                or "verified" in proof.claim.lower()
                or "zero mismatch" in proof.claim.lower()
                or "passed" in proof.claim.lower()
            ):
                passed = True
                break

    return {
        "passed": passed,
        "documented_mismatches": documented_mismatches,
    }


# ---------------------------------------------------------------------------
# Master Evaluator & Checker
# ---------------------------------------------------------------------------

def evaluate_gates(state: GraphState) -> dict[str, Any]:
    """Evaluate all five verification gates from the shared blackboard state.

    Returns a dictionary conforming to the 'gates' property of schemas/output.schema.json.
    """
    return {
        "build": evaluate_build_gate(state),
        "tests": evaluate_tests_gate(state),
        "accessibility": evaluate_accessibility_gate(state),
        "quality": evaluate_quality_gate(state),
        "integration": evaluate_integration_gate(state),
    }


def all_gates_passed(
    gates: dict[str, Any],
    accessibility_threshold: float = DEFAULT_ACCESSIBILITY_THRESHOLD,
    performance_threshold: float = DEFAULT_PERFORMANCE_THRESHOLD,
) -> bool:
    """Return True if all five gates passed their criteria."""
    if not gates.get("build", {}).get("passed", False):
        return False
    if not gates.get("tests", {}).get("passed", False):
        return False
    if not gates.get("accessibility", {}).get("passed", False):
        return False
    if not gates.get("integration", {}).get("passed", False):
        return False

    quality = gates.get("quality", {})
    acc = quality.get("lighthouse_accessibility", 0.0)
    perf = quality.get("lighthouse_performance", 0.0)
    if acc < accessibility_threshold or perf < performance_threshold:
        return False

    return True


# ---------------------------------------------------------------------------
# Quality Report Generator & Validator
# ---------------------------------------------------------------------------

def generate_quality_report(
    state: GraphState,
    run_id: str,
    preview_url: Optional[str] = None,
) -> dict[str, Any]:
    """Construct a full quality report dictionary matching schemas/output.schema.json.

    Validates iteration counts, gates, revisions, and unresolved issues.
    """
    gates = evaluate_gates(state)

    # 1. Determine run status
    status = state.status
    if status not in ("accepted", "partial", "failed"):
        status = "accepted" if all_gates_passed(gates) else "partial"

    # 2. Compute iteration statistics
    total_iterations = state.iteration_counters.get("run_total", 0)
    by_agent: dict[str, int] = {
        "planner": 0,
        "designer": 0,
        "engineer": 0,
        "integration": 0,
        "qa": 0,
        "critic": 0,
    }

    # Count agent iterations from proofs
    for proof in state.proofs:
        agent_str = str(proof.agent.value if hasattr(proof.agent, "value") else proof.agent).lower()
        if agent_str in by_agent:
            by_agent[agent_str] += 1

    # Planner calls at least once for initial plan
    if by_agent["planner"] == 0:
        by_agent["planner"] = 1

    # Ensure total is at least the sum of worker calls
    proof_total = sum(by_agent.values())
    if total_iterations < proof_total:
        total_iterations = proof_total

    # 3. Extract revisions
    revisions: list[dict[str, Any]] = []
    if state.design_spec and state.design_spec.revisions:
        for rev in state.design_spec.revisions:
            revisions.append({
                "by": "critic",
                "to": "designer",
                "reason": rev.finding,
                "resolved": True,
            })
    elif state.audit_report and state.audit_report.revision_requests:
        for req in state.audit_report.revision_requests:
            revisions.append({
                "by": req.get("by", "critic"),
                "to": req.get("to") or req.get("target_agent", "designer"),
                "reason": req.get("reason", "Accessibility revision requested"),
                "resolved": bool(req.get("resolved", True)),
            })

    # 4. Extract unresolved issues
    unresolved: list[dict[str, Any]] = []
    for issue in state.unresolved:
        unresolved.append({
            "issue": issue.issue,
            "evidence": issue.evidence,
        })

    report: dict[str, Any] = {
        "run_id": run_id,
        "status": status,
        "iterations": {
            "total": total_iterations,
            "by_agent": by_agent,
        },
        "gates": gates,
        "unresolved": unresolved,
    }

    if revisions:
        report["revisions"] = revisions

    resolved_preview = preview_url or state.code_artifacts.get("preview_url")
    if resolved_preview:
        report["preview_url"] = str(resolved_preview)

    # Validate against JSON schema
    validate_quality_report(report)

    return report


def validate_quality_report(report: dict[str, Any]) -> None:
    """Validate report dictionary against schemas/output.schema.json."""
    if SCHEMA_PATH.exists():
        with open(SCHEMA_PATH, "r", encoding="utf-8") as f:
            schema = json.load(f)
        jsonschema.validate(instance=report, schema=schema)


def save_quality_report(report: dict[str, Any], output_path: Union[str, Path]) -> Path:
    """Save quality report JSON to disk and return Path."""
    path = Path(output_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(report, f, indent=2)
    return path
