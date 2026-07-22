"""Renders an AuditReport as Markdown, following the rubric's Report Structure Template."""

from __future__ import annotations

from integri_audit_tool.models import AuditReport, CategoryResult, Finding, Severity

_SEVERITY_RANK = {
    Severity.CRITICAL: 0,
    Severity.HIGH: 1,
    Severity.MEDIUM: 2,
    Severity.LOW: 3,
    Severity.INFORMATIONAL: 4,
}


def _all_findings(report: AuditReport) -> list[Finding]:
    findings = [f for result in report.category_results for f in result.findings]
    return sorted(findings, key=lambda f: _SEVERITY_RANK[f.severity])


def _render_executive_summary(report: AuditReport) -> str:
    findings = _all_findings(report)
    counts = {severity: 0 for severity in Severity}
    for finding in findings:
        counts[finding.severity] += 1

    lines = ["## Executive Summary", ""]
    if not findings:
        lines.append("No findings were recorded across the assessed categories.")
    else:
        summary_parts = ", ".join(
            f"{count} {severity.value}" for severity, count in counts.items() if count
        )
        lines.append(f"**Findings by severity:** {summary_parts}")
        lines.append("")
        lines.append("**Top findings:**")
        for finding in findings[:5]:
            lines.append(f"- [{finding.severity.value}] {finding.title} ({finding.category_name})")
    lines.append("")
    lines.append(
        "Recommended next step: scope a remediation engagement for Critical/High findings "
        "first (see Suggested Remediation Phases below); this report covers the audit phase only."
    )
    return "\n".join(lines)


def _render_findings_summary_table(report: AuditReport) -> str:
    findings = _all_findings(report)
    lines = [
        "## Findings Summary Table",
        "",
        "| # | Category | Finding | Severity | Business Impact |",
        "|---|---|---|---|---|",
    ]
    if not findings:
        lines.append("| - | - | No findings | - | - |")
    for i, finding in enumerate(findings, start=1):
        lines.append(
            f"| {i} | {finding.category_name} | {finding.title} | {finding.severity.value} "
            f"| {finding.business_impact or '-'} |"
        )
    return "\n".join(lines)


def _render_category_detail(result: CategoryResult) -> str:
    lines = [f"### {result.category_number}. {result.category_name}", ""]

    if result.status == "not_applicable":
        lines.append(f"**N/A** — {result.na_reason or 'This category does not apply.'}")
        return "\n".join(lines)

    if not result.findings:
        lines.append("No findings.")
        return "\n".join(lines)

    for finding in result.findings:
        lines.append(f"#### [{finding.severity.value}] {finding.title} (`{finding.check_id}`)")
        lines.append("")
        lines.append(f"- **Observation:** {finding.observation}")
        if finding.evidence:
            lines.append(f"- **Evidence:** {finding.evidence}")
        if finding.business_impact:
            lines.append(f"- **Business impact:** {finding.business_impact}")
        if finding.recommended_direction:
            lines.append(f"- **Recommended direction:** {finding.recommended_direction}")
        lines.append("")

    return "\n".join(lines)


def _render_detailed_findings(report: AuditReport) -> str:
    lines = ["## Detailed Findings", ""]
    for result in sorted(report.category_results, key=lambda r: r.category_number):
        lines.append(_render_category_detail(result))
        lines.append("")
    return "\n".join(lines)


def _render_out_of_scope(report: AuditReport) -> str:
    lines = ["## Out of Scope / Not Assessed", ""]
    for note in report.out_of_scope:
        lines.append(f"- {note}")
    return "\n".join(lines)


def _render_remediation_phases(report: AuditReport) -> str:
    findings = _all_findings(report)
    phase_1 = [f for f in findings if f.severity in (Severity.CRITICAL, Severity.HIGH)]
    phase_2 = [f for f in findings if f.severity == Severity.MEDIUM]
    phase_3 = [f for f in findings if f.severity in (Severity.LOW, Severity.INFORMATIONAL)]

    def render_phase(title: str, description: str, items: list[Finding]) -> list[str]:
        block = [f"### {title}", "", description, ""]
        if items:
            for finding in items:
                block.append(f"- {finding.title} ({finding.category_name})")
        else:
            block.append("_None._")
        block.append("")
        return block

    lines = ["## Suggested Remediation Phases", ""]
    lines += render_phase("Phase 1", "Critical/High severity, low-risk additive changes.", phase_1)
    lines += render_phase("Phase 2", "Medium severity, structural changes requiring migration/testing.", phase_2)
    lines += render_phase("Phase 3", "Long-term / scale-readiness items.", phase_3)
    return "\n".join(lines)


def render(report: AuditReport) -> str:
    sections = [
        f"# Postgres Database & Search Audit Report — {report.target_label}",
        "",
        f"_Generated: {report.generated_at.isoformat()}_",
        "",
        _render_executive_summary(report),
        "",
        _render_findings_summary_table(report),
        "",
        _render_detailed_findings(report),
        _render_out_of_scope(report),
        "",
        _render_remediation_phases(report),
    ]
    return "\n".join(sections)
