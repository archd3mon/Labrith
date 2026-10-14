"""
Axe-core Accessibility Runner Tool.

Runs axe-core audits on web applications using Playwright, returns structured
findings (violations categorized by impact with affected DOM nodes and failing
contrast color pairs), and evaluates the accessibility gate.

Design Doc §3: "Accessibility and Design Critic: Audits WCAG compliance and visual and UX quality... Tools: axe-core, Lighthouse, vision model."
Design Doc §6: "3. Accessibility gate: no critical or serious axe-core violations (Critic evidence: audit report)."
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Optional, Union
import urllib.request

from playwright.sync_api import Browser, BrowserContext, Page, sync_playwright

AXE_CDN_URL = "https://cdnjs.cloudflare.com/ajax/libs/axe-core/4.9.1/axe.min.js"
LOCAL_AXE_PATH = Path(__file__).resolve().parent / "assets" / "axe.min.js"


@dataclass
class AxeNode:
    """A single DOM node affected by an axe-core rule violation."""

    target: list[str]
    html: str
    failure_summary: str
    failing_pair: Optional[dict[str, str]] = None
    data: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class AxeViolation:
    """A single rule violation reported by axe-core."""

    id: str
    impact: str  # "critical" | "serious" | "moderate" | "minor"
    description: str
    help: str
    help_url: Optional[str] = None
    tags: list[str] = field(default_factory=list)
    nodes: list[AxeNode] = field(default_factory=list)
    failing_pair: Optional[dict[str, str]] = None

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        d["nodes"] = [n.to_dict() if isinstance(n, AxeNode) else n for n in self.nodes]
        return d


@dataclass
class AxeAuditResult:
    """Overall outcome of an axe-core audit."""

    url: str
    violations: list[AxeViolation]
    passes_count: int
    incomplete_count: int
    inapplicable_count: int
    critical_count: int
    serious_count: int
    moderate_count: int
    minor_count: int
    passed_gate: bool  # True if critical_count == 0 and serious_count == 0
    report_path: Optional[str] = None
    raw_data: Optional[dict[str, Any]] = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "url": self.url,
            "violations": [v.to_dict() for v in self.violations],
            "passes_count": self.passes_count,
            "incomplete_count": self.incomplete_count,
            "inapplicable_count": self.inapplicable_count,
            "critical_count": self.critical_count,
            "serious_count": self.serious_count,
            "moderate_count": self.moderate_count,
            "minor_count": self.minor_count,
            "passed_gate": self.passed_gate,
            "report_path": self.report_path,
        }


def get_axe_script() -> str:
    """Load the axe-core JS bundle from local assets or download if missing."""
    if LOCAL_AXE_PATH.exists():
        try:
            return LOCAL_AXE_PATH.read_text(encoding="utf-8")
        except Exception:
            pass

    # Download and cache locally if possible
    try:
        LOCAL_AXE_PATH.parent.mkdir(parents=True, exist_ok=True)
        req = urllib.request.Request(AXE_CDN_URL, headers={"User-Agent": "LabrithAxeRunner"})
        with urllib.request.urlopen(req, timeout=10) as resp:
            content = resp.read().decode("utf-8")
            LOCAL_AXE_PATH.write_text(content, encoding="utf-8")
            return content
    except Exception as exc:
        raise RuntimeError(f"Failed to load or download axe-core script: {exc}") from exc


def _extract_contrast_pair(node_dict: dict[str, Any]) -> Optional[dict[str, str]]:
    """Extract foreground and background colors from axe contrast check node data."""
    checks = []
    checks.extend(node_dict.get("any", []))
    checks.extend(node_dict.get("all", []))
    checks.extend(node_dict.get("none", []))

    for check in checks:
        if check.get("id") == "color-contrast":
            data = check.get("data") or {}
            fg = data.get("fgColor")
            bg = data.get("bgColor")
            if fg and bg:
                return {
                    "foreground": str(fg),
                    "background": str(bg),
                    "contrast_ratio": str(data.get("contrastRatio", "")),
                    "expected_ratio": str(data.get("expectedContrastRatio", "4.5:1")),
                }
    return None


def parse_axe_results(raw_results: dict[str, Any], url: str = "") -> AxeAuditResult:
    """Parse raw axe-core JSON output into structured models."""
    raw_violations = raw_results.get("violations", [])
    violations: list[AxeViolation] = []

    critical_count = 0
    serious_count = 0
    moderate_count = 0
    minor_count = 0

    for raw_v in raw_violations:
        impact = str(raw_v.get("impact", "minor")).lower()
        if impact == "critical":
            critical_count += 1
        elif impact == "serious":
            serious_count += 1
        elif impact == "moderate":
            moderate_count += 1
        else:
            minor_count += 1

        nodes: list[AxeNode] = []
        overall_failing_pair: Optional[dict[str, str]] = None

        for raw_node in raw_v.get("nodes", []):
            failing_pair = _extract_contrast_pair(raw_node)
            if failing_pair and not overall_failing_pair:
                overall_failing_pair = failing_pair

            nodes.append(
                AxeNode(
                    target=list(raw_node.get("target", [])),
                    html=str(raw_node.get("html", "")),
                    failure_summary=str(raw_node.get("failureSummary", "")),
                    failing_pair=failing_pair,
                    data=raw_node.get("data", {}) or {},
                )
            )

        violations.append(
            AxeViolation(
                id=str(raw_v.get("id", "")),
                impact=impact,
                description=str(raw_v.get("description", "")),
                help=str(raw_v.get("help", "")),
                help_url=raw_v.get("helpUrl"),
                tags=list(raw_v.get("tags", [])),
                nodes=nodes,
                failing_pair=overall_failing_pair,
            )
        )

    # Accessibility gate: no critical or serious axe-core violations
    passed_gate = (critical_count == 0 and serious_count == 0)

    return AxeAuditResult(
        url=url,
        violations=violations,
        passes_count=len(raw_results.get("passes", [])),
        incomplete_count=len(raw_results.get("incomplete", [])),
        inapplicable_count=len(raw_results.get("inapplicable", [])),
        critical_count=critical_count,
        serious_count=serious_count,
        moderate_count=moderate_count,
        minor_count=minor_count,
        passed_gate=passed_gate,
        raw_data=raw_results,
    )


def audit_page(
    page: Page,
    *,
    context_selector: Optional[str] = None,
    options: Optional[dict[str, Any]] = None,
) -> dict[str, Any]:
    """Inject axe-core into an active Playwright page and run the audit."""
    axe_script = get_axe_script()
    page.evaluate(f"() => {{ {axe_script} }}")

    run_opts = options or {}
    if context_selector:
        eval_script = f"() => window.axe.run('{context_selector}', {json.dumps(run_opts)})"
    else:
        eval_script = f"() => window.axe.run(document, {json.dumps(run_opts)})"

    raw_results = page.evaluate(eval_script)
    return raw_results


class AxeRunner:
    """Tool for executing axe-core audits against URLs or local servers."""

    def __init__(
        self,
        headless: bool = True,
        report_dir: Optional[Union[str, Path]] = None,
    ) -> None:
        self.headless = headless
        self.report_dir = Path(report_dir) if report_dir else None

    def run(
        self,
        target: Union[str, Page],
        *,
        report_path: Optional[Union[str, Path]] = None,
        timeout: float = 30.0,
        options: Optional[dict[str, Any]] = None,
    ) -> AxeAuditResult:
        """Run axe-core on a target URL or existing Playwright Page.

        Args:
            target: Either an HTTP(S) URL or an existing Playwright Page object.
            report_path: Optional path to save the structured JSON report.
            timeout: Maximum navigation/audit timeout in seconds.
            options: Optional axe.run() options dictionary.

        Returns:
            Structured AxeAuditResult including gate status and itemized violations.
        """
        if isinstance(target, Page):
            raw_data = audit_page(target, options=options)
            result = parse_axe_results(raw_data, url=target.url)
        else:
            url = str(target)
            with sync_playwright() as pw:
                browser: Browser = pw.chromium.launch(headless=self.headless)
                context: BrowserContext = browser.new_context()
                page: Page = context.new_page()
                try:
                    page.goto(url, wait_until="load", timeout=int(timeout * 1000))
                    raw_data = audit_page(page, options=options)
                    result = parse_axe_results(raw_data, url=url)
                finally:
                    context.close()
                    browser.close()

        # Save report if requested
        dest_path = report_path or (
            (self.report_dir / "axe_report.json") if self.report_dir else None
        )
        if dest_path:
            p = Path(dest_path)
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text(json.dumps(result.to_dict(), indent=2), encoding="utf-8")
            result.report_path = str(p)

        return result
