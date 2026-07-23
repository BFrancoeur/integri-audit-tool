"""Typer CLI entrypoint."""

from __future__ import annotations

import sys
from datetime import datetime
from pathlib import Path
from typing import Optional
from urllib.parse import urlsplit, urlunsplit

import typer
from rich.console import Console

from integri_audit_tool import pdf_export
from integri_audit_tool.cli_progress_reporter import CliProgressReporter
from integri_audit_tool.config import AuditConfig
from integri_audit_tool.db import connect_read_only
from integri_audit_tool.registry import discover_categories
from integri_audit_tool.report.markdown import render
from integri_audit_tool.runner import run_audit

# Some Windows consoles default stdout/stderr to a legacy codepage rather than
# UTF-8, which mangles the checkmarks/em-dashes the progress UI prints (a
# checkmark can come back as the literal text "✓", or an em-dash as a
# replacement character). Reconfigure both streams before anything constructs
# a rich Console against them.
for _stream in (sys.stdout, sys.stderr):
    if hasattr(_stream, "reconfigure"):
        try:
            _stream.reconfigure(encoding="utf-8", errors="replace")
        except Exception:  # noqa: BLE001 - best-effort; fall back to default encoding
            pass

app = typer.Typer(help="Read-only Postgres database & search audit tool.")


def _sanitize_dsn_for_label(dsn: str) -> str:
    """Strip credentials from a DSN so it's safe to print in a report."""
    parts = urlsplit(dsn)
    netloc = parts.hostname or ""
    if parts.port:
        netloc += f":{parts.port}"
    return urlunsplit((parts.scheme, netloc, parts.path, "", ""))


@app.command()
def run(
    dsn: str = typer.Option(..., "--dsn", envvar="INTEGRI_DSN", help="Postgres connection string."),
    output: Optional[Path] = typer.Option(
        None, "--output", "-o", help="Write the Markdown report here instead of reports/audit-<timestamp>.md."
    ),
    category: list[int] = typer.Option(
        None, "--category", "-c", help="Limit to specific rubric category numbers (repeatable)."
    ),
    check: list[str] = typer.Option(
        None, "--check", "-k", help='Limit to specific check ids, e.g. "01.04" (repeatable).'
    ),
    progress: Optional[bool] = typer.Option(
        None,
        "--progress/--no-progress",
        help="Live progress UI. Default: auto-detect based on whether stderr is a terminal.",
    ),
    pdf: bool = typer.Option(True, "--pdf/--no-pdf", help="Also generate a PDF via Pandoc if available."),
) -> None:
    """Run the audit against DSN and write a Markdown (and, if possible, PDF) report."""
    config = AuditConfig(
        dsn=dsn,
        category_filter=set(category) if category else None,
        check_filter=set(check) if check else None,
    )

    console = Console(stderr=True)
    show_progress = progress if progress is not None else console.is_terminal
    reporter = CliProgressReporter() if show_progress else None

    with connect_read_only(dsn) as conn:
        report = run_audit(conn, config, target_label=_sanitize_dsn_for_label(dsn), reporter=reporter)

    rendered = render(report)

    if output is not None:
        md_path = output
    else:
        reports_dir = Path("reports")
        reports_dir.mkdir(parents=True, exist_ok=True)
        timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")
        md_path = reports_dir / f"audit-{timestamp}.md"

    md_path.parent.mkdir(parents=True, exist_ok=True)
    md_path.write_text(rendered, encoding="utf-8")
    console.print(f"Report written to {md_path.resolve()}")

    if pdf:
        pdf_path = md_path.with_suffix(".pdf")
        try:
            pdf_export.convert_markdown_to_pdf(md_path, pdf_path, console, show_progress=show_progress)
            console.print(f"[bold]PDF ready:[/bold] {pdf_path.resolve()}")
            console.print(f"  {pdf_path.resolve().as_uri()}")
        except pdf_export.PdfConversionError as exc:
            console.print(f"[yellow]Skipped PDF generation: {exc}[/yellow]")

    console.print("[bold green]Audit complete.[/bold green]")


@app.command(name="list-checks")
def list_checks(
    category: list[int] = typer.Option(
        None, "--category", "-c", help="Limit to specific rubric category numbers (repeatable)."
    ),
) -> None:
    """List every implemented check id and description. No database connection needed."""
    filter_set = set(category) if category else None
    for cat in discover_categories():
        if filter_set is not None and cat.number not in filter_set:
            continue
        typer.echo(f"Category {cat.number}: {cat.name}")
        if not cat.checks:
            typer.echo("  (no checks implemented yet)")
        for c in cat.checks:
            typer.echo(f"  {c.id}  {c.description}")
        typer.echo("")


if __name__ == "__main__":
    app()
