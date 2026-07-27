"""Renders an AuditReport as Markdown, following the rubric's Report Structure Template."""

from __future__ import annotations

from integri_audit_tool.models import AuditReport, CategoryResult, CheckResult, Finding, Severity

_SEVERITY_RANK = {
    Severity.CRITICAL: 0,
    Severity.HIGH: 1,
    Severity.MEDIUM: 2,
    Severity.LOW: 3,
    Severity.INFORMATIONAL: 4,
}

_CHECK_RESULT_LABELS = {
    "passed": "✓ Passed",
    "findings": "Findings",
    "error": "⚠ Error",
}


def _all_findings(report: AuditReport) -> list[Finding]:
    findings = [f for result in report.category_results for f in result.findings]
    return sorted(findings, key=lambda f: _SEVERITY_RANK[f.severity])


def _all_check_results(report: AuditReport) -> list[CheckResult]:
    return [cr for result in report.category_results for cr in result.check_results]


def _render_executive_summary(report: AuditReport) -> str:
    findings = _all_findings(report)
    counts = {severity: 0 for severity in Severity}
    for finding in findings:
        counts[finding.severity] += 1

    lines = ["## Executive Summary", ""]
    if not findings:
        lines.append(
            f"This audit reviewed {report.target_label} across all assessed categories and "
            "recorded no findings."
        )
        lines.append("")
        lines.append(
            "Recommended next step: scope a remediation engagement for Critical/High findings "
            "first (see Suggested Remediation Phases below); this report covers the audit phase only."
        )
        return "\n".join(lines)

    total = len(findings)
    severity_phrase = ", ".join(
        f"{count} {severity.value}" for severity, count in counts.items() if count
    )
    urgent_count = counts[Severity.CRITICAL] + counts[Severity.HIGH]
    if urgent_count:
        urgency_sentence = (
            f"{urgent_count} of these are Critical or High severity and should be treated as "
            "priorities; the rest are lower-severity items that add up over time rather than "
            "posing immediate risk."
        )
    else:
        urgency_sentence = (
            "None are Critical or High severity — the findings below are worth addressing as "
            "part of routine hardening rather than urgent risk."
        )

    lines.append(
        f"This audit reviewed {report.target_label} across all assessed categories and found "
        f"{total} finding{'s' if total != 1 else ''} ({severity_phrase}). {urgency_sentence}"
    )
    lines.append("")
    lines.append("**What needs attention first:**")
    lines.append("")
    for finding in findings[:5]:
        detail = f" {finding.business_impact}" if finding.business_impact else ""
        lines.append(f"- **{finding.severity.value} — {finding.title}.**{detail}")
    lines.append("")
    lines.append(
        "Recommended next step: scope a remediation engagement for Critical/High findings "
        "first (see Suggested Remediation Phases below); this report covers the audit phase only."
    )
    return "\n".join(lines)


# Pandoc's pipe-table -> LaTeX conversion sizes each column *relative to the
# number of dashes in its separator-row cell*, not to actual content length —
# an equal-width separator ("|---|---|---|---|") renders as four equal-width
# PDF columns regardless of how much text is actually in each one, which is
# what made "Finding" wrap onto 3-4 lines while "#"/"Check"/"Severity" sat
# mostly empty. This is documented Pandoc behavior, not a workaround: give
# the column that actually holds prose (Finding) most of the dashes.
_TABLE_COL_WIDTHS = {"#": 5, "Check": 8, "Finding": 82, "Severity": 16}


def _render_findings_summary_table(report: AuditReport) -> str:
    findings = _all_findings(report)
    header = "| " + " | ".join(_TABLE_COL_WIDTHS) + " |"
    separator = "|" + "|".join("-" * width for width in _TABLE_COL_WIDTHS.values()) + "|"
    lines = [
        "## Findings Summary Table",
        "",
        "A scannable index only — observation, evidence, business impact, and recommended "
        "direction for every finding are in Detailed Findings below, under the matching check id.",
        "",
        header,
        separator,
    ]
    if not findings:
        lines.append("| - | - | No findings | - |")
    for i, finding in enumerate(findings, start=1):
        lines.append(f"| {i} | {finding.check_id} | {finding.title} | {finding.severity.value} |")
    return "\n".join(lines)


_TESTS_TABLE_COL_WIDTHS = {"#": 5, "Test": 75, "Result": 12, "Findings": 8}


def _render_tests_performed(report: AuditReport) -> str:
    check_results = _all_check_results(report)
    header = "| " + " | ".join(_TESTS_TABLE_COL_WIDTHS) + " |"
    separator = "|" + "|".join("-" * width for width in _TESTS_TABLE_COL_WIDTHS.values()) + "|"
    lines = [
        "## Tests Performed",
        "",
        "Every test that ran this audit and its outcome — not just the ones that found "
        "something. Full detail for each finding is in Detailed Findings below.",
        "",
        header,
        separator,
    ]
    if not check_results:
        lines.append("| - | No tests ran | - | - |")
    for cr in check_results:
        result_label = _CHECK_RESULT_LABELS[cr.status]
        lines.append(f"| {cr.check_id} | {cr.description} | {result_label} | {cr.finding_count} |")
    return "\n".join(lines)


def _render_category_detail(result: CategoryResult) -> str:
    lines = [f"### {result.category_number}. {result.category_name}", ""]

    if result.status == "not_applicable":
        lines.append(f"**N/A** — {result.na_reason or 'This category does not apply.'}")
        return "\n".join(lines)

    if result.out_of_scope_notes:
        for note in result.out_of_scope_notes:
            lines.append(f"- {note}")
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


def _database_name_from_label(target_label: str) -> str:
    """target_label is always "host:port/dbname" (see cli.py's
    _sanitize_dsn_for_label / _acquire_connection) — the part after the
    last "/" is the database name."""
    return target_label.rsplit("/", 1)[-1] if "/" in target_label else target_label


def _render_title(report: AuditReport) -> str:
    if report.client_name:
        database_name = _database_name_from_label(report.target_label)
        return f"# {report.client_name} Database and Search Audit for {database_name}"
    # Fallback for runs that never collected a client name (e.g. ad hoc
    # single-category runs via ia-schema et al., not the ia run/
    # --ask-client-name path) — the generic label this always showed before.
    return f"# Postgres Database & Search Audit Report — {report.target_label}"


def render(report: AuditReport) -> str:
    sections = [
        _render_title(report),
        "",
        f"_Generated: {report.generated_at.strftime('%B %d, %Y')}_",
        "",
        _render_executive_summary(report),
        "",
        _render_findings_summary_table(report),
        "",
        _render_tests_performed(report),
        "",
        _render_detailed_findings(report),
        _render_remediation_phases(report),
    ]
    return "\n".join(sections)
