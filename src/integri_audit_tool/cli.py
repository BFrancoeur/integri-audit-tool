"""Typer CLI entrypoint."""

from __future__ import annotations

import os
import re
import sys
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterator, Optional
from urllib.parse import urlsplit, urlunsplit

import psycopg
import typer
from rich.console import Console

from integri_audit_tool import analytics, db_login, pdf_export, ssh_tunnel
from integri_audit_tool.cli_progress_reporter import CliProgressReporter
from integri_audit_tool.config import AuditConfig
from integri_audit_tool.db import connect_read_only
from integri_audit_tool.models import AuditReport, CategoryResult
from integri_audit_tool.registry import discover_categories
from integri_audit_tool.report.markdown import render
from integri_audit_tool.reporter import AuditReporter, CompositeReporter
from integri_audit_tool.runner import _display_check_id, run_audit

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

    def __init__(self, md_path: Path, target_label: str, client_name: str | None = None) -> None:
        self._md_path = md_path
        self._target_label = target_label
        self._client_name = client_name
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
            client_name=self._client_name,
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


def _looks_like_synthetic_db(dsn: str | None) -> bool:
    """Convenience auto-tag for analytics.py's is_synthetic flag: matches
    the one fixed local synthetic-db setup (scripts/setup-synthetic-db.sh,
    always 127.0.0.1:55432) so everyday ia-schema/ia run testing against it
    doesn't need an explicit flag. This is only a convenience default, not
    the authoritative mechanism — a future corpus of many differently-
    ported/named synthetic databases (randomized seeds, varying sizes) will
    rely on --synthetic being passed explicitly instead, since no DSN
    pattern can generalize to arbitrary generated databases."""
    return dsn is not None and "127.0.0.1:55432" in dsn


def _slugify(name: str) -> str:
    """Lowercase, collapse anything that isn't a-z/0-9 into a single hyphen,
    trim leading/trailing hyphens — safe on any filesystem, still readable."""
    return re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")


def _prompt_for_client_report_path() -> tuple[Path, str]:
    """Prompts for the client's business name and returns
    (reports/<slug>-<timestamp-id>.md, business_name) — done here, in the
    same process (and via the same input() used by --step's Enter-gates)
    that will go on to read every subsequent keypress, rather than in a
    wrapping shell script. Handing stdin off between a bash `read` and a
    freshly-spawned Python subprocess is exactly the kind of thing that can
    leak a buffered keystroke through under Git Bash/mintty — confirmed
    live: the Enter that submitted the business name was silently
    satisfying category 1's --step gate too, so category 1 ran without ever
    waiting for a real keypress. Keeping the whole interactive sequence in
    one process's input() calls avoids that boundary entirely.

    The business name is also threaded into the report's title (see
    report/markdown.py) — not just used to build the filename — so the
    same value collected here shows up in the actual deliverable.
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
    return reports_dir / f"{slug}-{timestamp}.md", business_name


@contextmanager
def _acquire_connection(
    dsn: str | None, ssh_connect: bool, console: Console
) -> Iterator[tuple[psycopg.Connection, str]]:
    """Yields (connection, target_label) via one of two paths:

    - --ssh-connect: prompts for a bastion-host SSH tunnel (ssh_tunnel.py),
      then Postgres-level credentials over that tunnel (db_login.py) — two
      separate modules since they're genuinely separate concerns (transport
      vs. database auth). target_label uses the *real* remote host/port the
      client would recognize, not the ephemeral 127.0.0.1:<local port> the
      tunnel happens to forward through, which would be a meaningless label
      in the report.
    - plain --dsn/$INTEGRI_DSN: the existing direct-connection path,
      unchanged.

    Either way, the actual read-only guarantee comes from db.py's
    connect_read_only alone — this function only ever decides how the DSN
    given to it gets built, never anything about connection safety.
    """
    if ssh_connect:
        tunnel_config = ssh_tunnel.prompt_for_ssh_tunnel_config()
        with ssh_tunnel.open_tunnel(tunnel_config) as local_port:
            login_config = db_login.prompt_for_db_login(default_host="127.0.0.1", default_port=local_port)
            with db_login.connect(login_config) as conn:
                console.print("[bold green]Database connection success.[/bold green]")
                target_label = f"{tunnel_config.remote_host}:{tunnel_config.remote_port}/{login_config.database}"
                yield conn, target_label
        return

    if not dsn:
        typer.echo("Either --dsn (or $INTEGRI_DSN) or --ssh-connect is required.", err=True)
        raise typer.Exit(code=1)
    with connect_read_only(dsn) as conn:
        yield conn, _sanitize_dsn_for_label(dsn)


@app.command()
def run(
    dsn: Optional[str] = typer.Option(
        None, "--dsn", envvar="INTEGRI_DSN", help="Postgres connection string. Required unless --ssh-connect is used."
    ),
    ssh_connect: bool = typer.Option(
        False,
        "--ssh-connect/--no-ssh-connect",
        help=(
            "Connect via an SSH tunnel to a bastion/jump host instead of a direct DSN — prompts "
            "for the bastion, an SSH key path, and Postgres credentials. Takes priority over --dsn."
        ),
    ),
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
        None,
        "--check",
        "-k",
        help='Limit to specific checks, by displayed id (e.g. "01.04") or stable slug '
        '(e.g. "missing-foreign-keys") (repeatable).',
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
    analytics_enabled: bool = typer.Option(
        True,
        "--analytics/--no-analytics",
        help="Persist this run's findings to the local analytics database (analytics.db) for cross-run analysis.",
    ),
    synthetic: bool = typer.Option(
        False,
        "--synthetic/--no-synthetic",
        help=(
            "Tag this run as synthetic/training data in the analytics database, rather than a real "
            "client audit. Auto-detected for the standard local synthetic db (127.0.0.1:55432); pass "
            "explicitly for any other synthetic/test database."
        ),
    ),
    analytics_db: Path = typer.Option(
        analytics.DEFAULT_DB_PATH, "--analytics-db", help="Path to the analytics SQLite database."
    ),
) -> None:
    """Run the audit against DSN (or an SSH-tunneled connection) and write a
    Markdown (and, if possible, PDF) report."""
    console = Console(stderr=True)
    show_progress = progress if progress is not None else _is_interactive_terminal(console)

    client_name: Optional[str] = None
    if output is not None:
        md_path = output
    elif ask_client_name:
        md_path, client_name = _prompt_for_client_report_path()
    else:
        reports_dir = Path("reports")
        reports_dir.mkdir(parents=True, exist_ok=True)
        timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")
        md_path = reports_dir / f"audit-{timestamp}.md"
    md_path.parent.mkdir(parents=True, exist_ok=True)

    with _acquire_connection(dsn, ssh_connect, console) as (conn, target_label):
        config = AuditConfig(
            dsn=dsn,
            category_filter=set(category) if category else None,
            check_filter=set(check) if check else None,
        )

        reporters: list[AuditReporter] = [_IncrementalReportWriter(md_path, target_label, client_name=client_name)]
        if show_progress:
            reporters.append(CliProgressReporter(interactive=step))
        if analytics_enabled:
            reporters.append(
                analytics.AuditDatabaseWriter(
                    target_label,
                    client_name=client_name,
                    is_synthetic=synthetic or _looks_like_synthetic_db(dsn),
                    category_filter=",".join(str(c) for c in category) if category else None,
                    check_filter=",".join(check) if check else None,
                    db_path=analytics_db,
                )
            )
        reporter = CompositeReporter(reporters)

        report = run_audit(conn, config, target_label=target_label, reporter=reporter, client_name=client_name)

    console.print("[bold green]Audit complete.[/bold green]")
    if analytics_enabled:
        tag = "synthetic/training" if (synthetic or _looks_like_synthetic_db(dsn)) else "client"
        console.print(f"Findings recorded to {analytics_db.resolve()} (tagged: {tag}).")

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
            display_id = _display_check_id(cat.number, c.rubric_bullet)
            typer.echo(f"  {display_id}  ({c.slug})  {c.description}")
        typer.echo("")


if __name__ == "__main__":
    app()
