"""Typer CLI entrypoint."""

from __future__ import annotations

import os
import re
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional
from urllib.parse import urlsplit, urlunsplit

import typer
from rich.console import Console

from integri_audit_tool import pdf_export
from integri_audit_tool.cli_progress_reporter import CliProgressReporter
from integri_audit_tool.config import AuditConfig
from integri_audit_tool.db import connect_read_only
from integri_audit_tool.models import AuditReport, CategoryResult
from integri_audit_tool.registry import discover_categories
from integri_audit_tool.report.markdown import render
from integri_audit_tool.reporter import AuditReporter, CompositeReporter
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


def _is_interactive_terminal(console: Console) -> bool:
    """rich's Console.is_terminal is Python's isatty() under the hood, which
    mintty (Git Bash's terminal) reports as False even in an interactive
    session — a known mintty/MSYS limitation, not a real "output is
    redirected" case. MSYSTEM is set by Git Bash/MSYS2 specifically (never by
    a real redirect, cron, or CI), so it's a safe fallback signal."""
    return console.is_terminal or "MSYSTEM" in os.environ


class _IncrementalReportWriter:
    """Writes a growing Markdown report to disk as each category finishes,
    so the report file exists (and fills in) from the moment the first
    category completes, instead of only appearing once the entire audit is
    done. The authoritative final render — with correct out-of-scope notes,
    which are only assembled once the whole run is complete — still happens
    once in `run()` after `run_audit()` returns; this just keeps the same
    file path progressively up to date in the meantime.

    Implements only the one AuditReporter method it needs (Protocol
    membership is structural, not every reporter needs every hook) plus a
    couple of no-ops the type checker doesn't require but keep intent clear.
    """

    def __init__(self, md_path: Path, target_label: str) -> None:
        self._md_path = md_path
        self._target_label = target_label
        self._results: list[CategoryResult] = []

    def category_ready(self, category, checks_to_run) -> None:  # noqa: ANN001 - matches Protocol structurally
        pass

    def category_not_applicable(self, category, reason) -> None:  # noqa: ANN001
        pass

    def check_started(self, category, check) -> None:  # noqa: ANN001
        pass

    def check_succeeded(self, category, check, findings) -> None:  # noqa: ANN001
        pass

    def check_failed(self, category, check, error) -> None:  # noqa: ANN001
        pass

    def category_completed(self, category, result: CategoryResult) -> None:  # noqa: ANN001
        self._results.append(result)
        partial_report = AuditReport(
            target_label=self._target_label,
            generated_at=datetime.now(timezone.utc),
            category_results=list(self._results),
            out_of_scope=[],
        )
        self._md_path.write_text(render(partial_report), encoding="utf-8")

    def audit_completed(self, report) -> None:  # noqa: ANN001
        pass


def _sanitize_dsn_for_label(dsn: str) -> str:
    """Strip credentials from a DSN so it's safe to print in a report."""
    parts = urlsplit(dsn)
    netloc = parts.hostname or ""
    if parts.port:
        netloc += f":{parts.port}"
    return urlunsplit((parts.scheme, netloc, parts.path, "", ""))


def _slugify(name: str) -> str:
    """Lowercase, collapse anything that isn't a-z/0-9 into a single hyphen,
    trim leading/trailing hyphens — safe on any filesystem, still readable."""
    return re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")


def _prompt_for_client_report_path() -> Path:
    """Prompts for the client's business name and returns
    reports/<slug>-<timestamp-id>.md — done here, in the same process (and
    via the same input() used by --step's Enter-gates) that will go on to
    read every subsequent keypress, rather than in a wrapping shell script.
    Handing stdin off between a bash `read` and a freshly-spawned Python
    subprocess is exactly the kind of thing that can leak a buffered
    keystroke through under Git Bash/mintty — confirmed live: the Enter that
    submitted the business name was silently satisfying category 1's --step
    gate too, so category 1 ran without ever waiting for a real keypress.
    Keeping the whole interactive sequence in one process's input() calls
    avoids that boundary entirely.
    """
    business_name = input("Client's business name: ").strip()
    if not business_name:
        typer.echo("Client's business name cannot be empty.", err=True)
        raise typer.Exit(code=1)
    slug = _slugify(business_name)
    if not slug:
        typer.echo("Client's business name must contain at least one letter or digit.", err=True)
        raise typer.Exit(code=1)
    timestamp = datetime.now().strftime("%Y%m%d%H%M%S")
    reports_dir = Path("reports")
    reports_dir.mkdir(parents=True, exist_ok=True)
    return reports_dir / f"{slug}-{timestamp}.md"


@app.command()
def run(
    dsn: str = typer.Option(..., "--dsn", envvar="INTEGRI_DSN", help="Postgres connection string."),
    output: Optional[Path] = typer.Option(
        None, "--output", "-o", help="Write the Markdown report here instead of reports/audit-<timestamp>.md."
    ),
    ask_client_name: bool = typer.Option(
        False,
        "--ask-client-name/--no-ask-client-name",
        help=(
            "Prompt for the client's business name and write the report to "
            "reports/<slug>-<id>.md instead of the default. Ignored if --output is given."
        ),
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
        help="Live progress UI. Default: auto-detect based on whether stderr is a terminal (also on under Git Bash/MSYS2).",
    ),
    step: bool = typer.Option(
        False,
        "--step/--no-step",
        help="Pause after each category's readiness message and wait for Enter before running it. Requires the progress UI.",
    ),
    pdf: bool = typer.Option(True, "--pdf/--no-pdf", help="Also generate a PDF via Pandoc if available."),
) -> None:
    """Run the audit against DSN and write a Markdown (and, if possible, PDF) report."""
    config = AuditConfig(
        dsn=dsn,
        category_filter=set(category) if category else None,
        check_filter=set(check) if check else None,
    )

    # Resolved up front (not after the run) so the incremental report writer
    # below has somewhere to write as each category finishes.
    if output is not None:
        md_path = output
    elif ask_client_name:
        md_path = _prompt_for_client_report_path()
    else:
        reports_dir = Path("reports")
        reports_dir.mkdir(parents=True, exist_ok=True)
        timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")
        md_path = reports_dir / f"audit-{timestamp}.md"
    md_path.parent.mkdir(parents=True, exist_ok=True)

    console = Console(stderr=True)
    show_progress = progress if progress is not None else _is_interactive_terminal(console)
    target_label = _sanitize_dsn_for_label(dsn)

    reporters: list[AuditReporter] = [_IncrementalReportWriter(md_path, target_label)]
    if show_progress:
        reporters.append(CliProgressReporter(interactive=step))
    reporter = CompositeReporter(reporters)

    with connect_read_only(dsn) as conn:
        report = run_audit(conn, config, target_label=target_label, reporter=reporter)

    console.print("[bold green]Audit complete.[/bold green]")

    console.print("Generating report.")
    md_path.write_text(render(report), encoding="utf-8")
    console.print(f"Report written to {md_path.resolve()}")
    console.print("Generated report complete.")

    if pdf:
        pdf_path = md_path.with_suffix(".pdf")
        try:
            pdf_export.convert_markdown_to_pdf(md_path, pdf_path, console, show_progress=show_progress)
            console.print(f"[bold]PDF ready:[/bold] {pdf_path.resolve()}")
            console.print(f"  {pdf_path.resolve().as_uri()}")
        except pdf_export.PdfConversionError as exc:
            console.print(f"[yellow]Skipped PDF generation: {exc}[/yellow]")


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
