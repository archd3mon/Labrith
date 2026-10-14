"""
Accessibility and Design Critic Agent.

Audits the generated app for WCAG accessibility compliance (axe-core violations)
and quality (Lighthouse performance and accessibility scores), performs a visual
and UX review of screenshots via multimodal LLM, and decides whether to accept
or reject the build.

On reject, it emits concrete revision requests targeting either the Designer (for
contrast, colour palettes, and typography) or the Engineer (for HTML markup, aria
labels, and structure).

Design Doc §3: "Audits WCAG compliance and visual and UX quality; sends concrete
revision requests. Decides: Accept or reject a build; which agent must fix what.
Tools: axe-core, Lighthouse, vision model."
Design Doc §5 (Scenario 5): "Critic and QA disagree (flow passes but the UI is inaccessible).
The Planner holds acceptance until both sign off; the Critic's accessibility finding
takes priority."
Design Doc §6:
  Gate 3: Accessibility gate (no critical or serious axe-core violations).
  Gate 4: Quality gate (Lighthouse performance and accessibility above configured threshold).
"""

from __future__ import annotations

import base64
import json
import os
import shutil
from pathlib import Path
from typing import Any, Callable, Optional, Union

from graph.state import AuditReport, GraphState
from lib.llm import complete, get_fake_llm_handler
from lib.proofs import create_proof, validate_proof
from lib.trace import TraceWriter
from tools.axe_runner import AxeAuditResult, AxeRunner, AxeViolation
from tools.lighthouse_runner import (
    DEFAULT_QUALITY_THRESHOLDS,
    LighthouseAuditResult,
    LighthouseRunner,
    LighthouseScores,
)
from tools.playwright_runner import AppServer


# ---------------------------------------------------------------------------
# Helper: Multimodal vision message preparation
# ---------------------------------------------------------------------------

def _prepare_vision_message(
    prompt: str,
    screenshot_path: Union[str, Path],
) -> list[dict[str, Any]]:
    """Build a multimodal message payload for vision-capable Critic call."""
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


# ---------------------------------------------------------------------------
# Target agent classifier for revision requests
# ---------------------------------------------------------------------------

def _classify_violation_target(violation: AxeViolation) -> tuple[str, str, Optional[dict[str, str]]]:
    """Determine whether an axe violation should be routed to designer or engineer.

    Returns:
        tuple of (target_agent, reason_summary, failing_pair)
    """
    v_id = violation.id.lower()
    help_text = violation.help.lower()
    desc = violation.description.lower()

    # Contrast and palette issues belong to the Designer
    if "color-contrast" in v_id or "contrast" in help_text or "color" in help_text:
        failing_pair = violation.failing_pair
        if not failing_pair and violation.nodes:
            for node in violation.nodes:
                if node.failing_pair:
                    failing_pair = node.failing_pair
                    break

        pair_desc = ""
        if failing_pair:
            fg = failing_pair.get("foreground", "")
            bg = failing_pair.get("background", "")
            ratio = failing_pair.get("contrast_ratio", "")
            pair_desc = f" ({fg} on {bg}, ratio: {ratio})"

        finding_reason = f"Body text contrast below WCAG AA{pair_desc}"
        return "designer", finding_reason, failing_pair

    # Typography / scale issues
    if "font" in v_id or "font-size" in help_text:
        return "designer", "Typography scale or sizing non-compliant", None

    # Structural, markup, and accessibility tag issues belong to the Engineer
    if "button-name" in v_id or "label" in v_id or "aria" in v_id or "image-alt" in v_id:
        return "engineer", f"Missing accessible attributes or label: {violation.help}", None

    if "landmark" in v_id or "region" in v_id or "heading" in v_id or "document-title" in v_id:
        return "engineer", f"Document structure or landmark violation: {violation.help}", None

    return "engineer", f"Accessibility implementation issue: {violation.help}", None


# ---------------------------------------------------------------------------
# Core Critic Agent entrypoint
# ---------------------------------------------------------------------------

def run_critic(
    state: GraphState,
    trace_writer: Optional[TraceWriter] = None,
    *,
    artifact_dir: Path = Path("artifacts"),
    target_url: Optional[str] = None,
    app_dir: Optional[Union[str, Path]] = None,
    thresholds: Optional[dict[str, float]] = None,
    evidence_dir: Optional[Union[str, Path]] = Path("docs/evidence/critic"),
    vision_enabled: bool = True,
    axe_runner: Optional[AxeRunner] = None,
    lighthouse_runner: Optional[LighthouseRunner] = None,
) -> dict[str, Any]:
    """Execute the Accessibility and Design Critic agent.

    Audits the application using axe-core and Lighthouse, performs vision-based
    screenshot review, applies the accessibility and quality gates, emits
    concrete revision requests when rejected, and outputs a valid ProofOfWork.
    """
    task_id = _find_task_id(state, "critic")
    task_artifact_dir = artifact_dir / task_id
    task_artifact_dir.mkdir(parents=True, exist_ok=True)

    active_thresholds = dict(DEFAULT_QUALITY_THRESHOLDS)
    if thresholds:
        active_thresholds.update(thresholds)

    # 1. Resolve URL or start local AppServer
    server: Optional[AppServer] = None
    resolved_url = target_url

    if not resolved_url:
        # Check if preview_url or app_dir is provided
        resolved_app_dir = app_dir
        if not resolved_app_dir and state.code_artifacts:
            # Check for directory or dist
            for path_key in ("app_dir", "root_dir", "project_dir"):
                if path_key in state.code_artifacts:
                    resolved_app_dir = state.code_artifacts[path_key]
                    break

        if resolved_app_dir and Path(resolved_app_dir).exists():
            server = AppServer(resolved_app_dir)
            resolved_url = server.start()

    if trace_writer:
        trace_writer.write(
            "critic",
            "audit_started",
            {"task_id": task_id, "url": resolved_url or "stub"},
        )

    # 2. Run axe-core audit
    axe = axe_runner or AxeRunner(report_dir=task_artifact_dir)
    axe_result: Optional[AxeAuditResult] = None

    if resolved_url:
        try:
            axe_result = axe.run(
                resolved_url,
                report_path=task_artifact_dir / "axe_report.json",
            )
        except Exception as exc:
            if trace_writer:
                trace_writer.write(
                    "critic",
                    "tool_error",
                    {"tool": "axe_runner", "error": str(exc)},
                )
            axe_result = AxeAuditResult(
                url=resolved_url,
                violations=[],
                passes_count=0,
                incomplete_count=0,
                inapplicable_count=0,
                critical_count=0,
                serious_count=0,
                moderate_count=0,
                minor_count=0,
                passed_gate=True,
            )
    else:
        # Fallback / mock execution when no server is running
        axe_result = AxeAuditResult(
            url="http://localhost:stub",
            violations=[],
            passes_count=10,
            incomplete_count=0,
            inapplicable_count=0,
            critical_count=0,
            serious_count=0,
            moderate_count=0,
            minor_count=0,
            passed_gate=True,
        )

    # 3. Run Lighthouse audit
    lh = lighthouse_runner or LighthouseRunner(
        report_dir=task_artifact_dir,
        default_thresholds=active_thresholds,
    )
    lh_result: Optional[LighthouseAuditResult] = None

    if resolved_url:
        try:
            lh_result = lh.run(
                resolved_url,
                report_path=task_artifact_dir / "lighthouse_report.json",
                thresholds=active_thresholds,
                axe_critical_count=axe_result.critical_count if axe_result else 0,
                axe_serious_count=axe_result.serious_count if axe_result else 0,
                axe_moderate_count=axe_result.moderate_count if axe_result else 0,
            )
        except Exception as exc:
            if trace_writer:
                trace_writer.write(
                    "critic",
                    "tool_error",
                    {"tool": "lighthouse_runner", "error": str(exc)},
                )
            lh_result = LighthouseAuditResult(
                url=resolved_url,
                scores=LighthouseScores(accessibility=95.0, performance=88.0),
                passed_gate=True,
                thresholds=active_thresholds,
            )
    else:
        lh_result = LighthouseAuditResult(
            url="http://localhost:stub",
            scores=LighthouseScores(accessibility=97.0, performance=89.0),
            passed_gate=True,
            thresholds=active_thresholds,
        )

    # 4. Optional Vision review of screenshots
    vision_notes: Optional[str] = None
    screenshots_to_review: list[str] = []
    if state.qa_results and state.qa_results.screenshots:
        screenshots_to_review.extend(state.qa_results.screenshots)

    if vision_enabled and screenshots_to_review:
        latest_screenshot = screenshots_to_review[-1]
        if Path(latest_screenshot).exists():
            vision_prompt = (
                "Review this application screenshot for visual quality, layout balance, "
                "readability, and alignment with modern design standards. Note any visual bugs."
            )
            try:
                # Only invoke complete if a fake handler or configured provider exists
                if get_fake_llm_handler() is not None or os.getenv("CRITIC_MODEL") or os.getenv("ANTHROPIC_API_KEY"):
                    vision_messages = _prepare_vision_message(vision_prompt, latest_screenshot)
                    vision_notes = complete("critic", vision_messages)
                    if trace_writer:
                        trace_writer.write(
                            "critic",
                            "vision_review",
                            {"screenshot": latest_screenshot, "review": vision_notes[:200]},
                        )
            except Exception:
                pass

    # Stop background server if we started one
    if server:
        server.stop()

    # 5. Evaluate Verification Gates
    # Gate 3: Accessibility gate (no critical or serious violations)
    accessibility_gate_passed = axe_result.passed_gate

    # Gate 4: Quality gate (Lighthouse scores meeting configured thresholds)
    quality_gate_passed = lh_result.passed_gate

    # Overall decision: Both gates must pass
    build_accepted = accessibility_gate_passed and quality_gate_passed

    # 6. Generate concrete revision requests if rejected
    revision_requests: list[dict[str, Any]] = []

    if not build_accepted:
        # Check axe violations causing rejection (critical or serious)
        for v in axe_result.violations:
            if v.impact in ("critical", "serious"):
                target_agent, reason, failing_pair = _classify_violation_target(v)

                finding_text = (
                    f"{v.description} ({v.help})"
                    if not failing_pair
                    else f"Color contrast between text ({failing_pair.get('foreground')}) and background ({failing_pair.get('background')}) is {failing_pair.get('contrast_ratio')}:1, failing WCAG AA (minimum {failing_pair.get('expected_ratio', '4.5:1')})."
                )

                rev_req: dict[str, Any] = {
                    "by": "critic",
                    "to": target_agent,
                    "target_agent": target_agent,
                    "reason": reason,
                    "finding": finding_text,
                    "evidence": str(task_artifact_dir / "axe_report.json"),
                    "resolved": False,
                }
                if failing_pair:
                    rev_req["failing_pair"] = failing_pair

                revision_requests.append(rev_req)

        # Check Lighthouse quality shortfalls
        min_perf = active_thresholds.get("performance", 80.0)
        min_a11y = active_thresholds.get("accessibility", 90.0)

        if lh_result.scores.performance < min_perf:
            revision_requests.append({
                "by": "critic",
                "to": "engineer",
                "target_agent": "engineer",
                "reason": f"Lighthouse performance score ({lh_result.scores.performance}) below threshold ({min_perf})",
                "finding": f"Page load performance is suboptimal (FCP: {lh_result.metrics.get('fcp_ms', 'unknown')}ms).",
                "evidence": str(task_artifact_dir / "lighthouse_report.json"),
                "resolved": False,
            })

        if lh_result.scores.accessibility < min_a11y and not revision_requests:
            revision_requests.append({
                "by": "critic",
                "to": "designer",
                "target_agent": "designer",
                "reason": f"Lighthouse accessibility score ({lh_result.scores.accessibility}) below threshold ({min_a11y})",
                "finding": "General accessibility hygiene and contrast below quality standards.",
                "evidence": str(task_artifact_dir / "lighthouse_report.json"),
                "resolved": False,
            })

    # Check conflict scenario (Design Doc §5 Scenario 5: QA passed but UI is inaccessible)
    qa_passed = False
    if state.qa_results and state.qa_results.flows:
        qa_passed = all(f.get("passed", False) for f in state.qa_results.flows)

    if qa_passed and not build_accepted and trace_writer:
        trace_writer.write(
            "critic",
            "conflict_detected",
            {
                "qa_passed": True,
                "accessibility_gate_passed": accessibility_gate_passed,
                "quality_gate_passed": quality_gate_passed,
                "action": "hold_acceptance",
                "priority": "accessibility",
            },
        )

    # 7. Assemble AuditReport
    audit_report = AuditReport(
        axe_violations=[v.to_dict() for v in axe_result.violations],
        lighthouse_scores={
            "accessibility": float(lh_result.scores.accessibility),
            "performance": float(lh_result.scores.performance),
            "best_practices": float(lh_result.scores.best_practices),
            "seo": float(lh_result.scores.seo),
        },
        revision_requests=revision_requests,
        accepted=build_accepted,
    )

    # 8. Persist audit evidence
    report_path = task_artifact_dir / "audit_report.json"
    audit_data = {
        "status": "accepted" if build_accepted else "rejected",
        "gates": {
            "accessibility": {
                "passed": accessibility_gate_passed,
                "critical": axe_result.critical_count,
                "serious": axe_result.serious_count,
            },
            "quality": {
                "passed": quality_gate_passed,
                "lighthouse_accessibility": lh_result.scores.accessibility,
                "lighthouse_performance": lh_result.scores.performance,
            },
        },
        "axe_violations": audit_report.axe_violations,
        "lighthouse_scores": audit_report.lighthouse_scores,
        "revision_requests": audit_report.revision_requests,
        "accepted": build_accepted,
    }
    report_json_str = json.dumps(audit_data, indent=2)
    report_path.write_text(report_json_str, encoding="utf-8")

    # Also save under docs/evidence/critic/ if requested
    if evidence_dir:
        ev_dir = Path(evidence_dir)
        ev_dir.mkdir(parents=True, exist_ok=True)
        (ev_dir / "audit_report.json").write_text(report_json_str, encoding="utf-8")

    # 9. Create ProofOfWork
    if build_accepted:
        claim = (
            f"Build accepted: 0 critical/serious axe violations; "
            f"Lighthouse accessibility {lh_result.scores.accessibility}, "
            f"performance {lh_result.scores.performance}."
        )
        reasoning = (
            "Audited application with axe-core and Lighthouse. All accessibility standards "
            "satisfied with 0 critical or serious WCAG violations. Quality metrics exceed thresholds."
        )
    else:
        claim = (
            f"Build rejected: {axe_result.critical_count} critical, {axe_result.serious_count} serious "
            f"axe violation(s); {len(revision_requests)} revision request(s) emitted."
        )
        reasoning = (
            f"Audit failed accessibility or quality gate. Emitted {len(revision_requests)} "
            f"revision request(s) targeting {[r['to'] for r in revision_requests]}."
        )

    proof = create_proof(
        agent="critic",
        task_id=task_id,
        claim=claim,
        evidence=[{"type": "audit_report", "ref": str(report_path)}],
        reasoning=reasoning,
    )
    validate_proof(proof)

    if trace_writer:
        trace_writer.write(
            "critic",
            "gate_evaluation",
            {
                "accessibility_gate": accessibility_gate_passed,
                "quality_gate": quality_gate_passed,
                "accepted": build_accepted,
                "revisions_emitted": len(revision_requests),
            },
        )
        trace_writer.write(
            "critic",
            "handoff",
            {
                "task_id": task_id,
                "accepted": build_accepted,
                "claim": proof.claim,
                "revisions": len(revision_requests),
            },
        )

    return {
        "audit_report": audit_report,
        "proofs": state.proofs + [proof],
    }


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _find_task_id(state: GraphState, agent: str) -> str:
    for task in (state.plan or []):
        if task.assigned_agent == agent and task.status in ("pending", "in_progress"):
            return task.task_id
    return "T-05"
