"""Typer CLI entrypoint."""

from __future__ import annotations

from pathlib import Path
from typing import Optional
from urllib.parse import urlsplit, urlunsplit

import typer

from integri_audit_tool.config import AuditConfig
from integri_audit_tool.db import connect_read_only
from integri_audit_tool.report.markdown import render
from integri_audit_tool.runner import run_audit

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
    output: Optional[Path] = typer.Option(None, "--output", "-o", help="Write the report here instead of stdout."),
    category: list[int] = typer.Option(
        None, "--category", "-c", help="Limit to specific rubric category numbers (repeatable)."
    ),
) -> None:
    """Run the audit against DSN and render a Markdown report."""
    config = AuditConfig(dsn=dsn, category_filter=set(category) if category else None)

    with connect_read_only(dsn) as conn:
        report = run_audit(conn, config, target_label=_sanitize_dsn_for_label(dsn))

    rendered = render(report)

    if output:
        output.write_text(rendered, encoding="utf-8")
        typer.echo(f"Report written to {output}")
    else:
        typer.echo(rendered)


if __name__ == "__main__":
    app()
