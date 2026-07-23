"""Live terminal UI for an audit run — the "not core" feature.

Implements AuditReporter using rich; runner.py and checks.py never import
this module or know it exists. Everything renders to stderr so stdout stays
clean for the actual Markdown report (`integri-audit run ... > report.md`
still works with this reporter attached).

Kept out of core deliberately: swap this for a different AuditReporter (a
JSON-lines reporter for CI, a silent one for the future automation script)
without touching runner.py at all.
"""

from __future__ import annotations

import logging
import time
from pathlib import Path
from typing import TYPE_CHECKING

from rich.console import Console
from rich.markup import escape

from integri_audit_tool.models import Severity

if TYPE_CHECKING:
    from integri_audit_tool.models import AuditReport, CategoryResult, Finding
    from integri_audit_tool.registry import Check, CategoryModule

_SEVERITY_STYLES = {
    Severity.CRITICAL: "bold red",
    Severity.HIGH: "red",
    Severity.MEDIUM: "yellow",
    Severity.LOW: "cyan",
    Severity.INFORMATIONAL: "dim",
}

# Mirrors scripts/aliases.sh — kept here rather than derived from it since
# that's a shell file, not something Python can introspect. Falls back to
# "Category N" for any category number not listed (future categories added
# to the rubric before an alias exists for them).
_CATEGORY_ALIASES = {
    1: "ia-schema",
    2: "ia-jsonb",
    3: "ia-index",
    4: "ia-fts",
    5: "ia-query",
    6: "ia-quality",
    7: "ia-scale",
    8: "ia-sec",
    9: "ia-backup",
    10: "ia-mon",
    11: "ia-docs",
}


class CliProgressReporter:
    """Concrete AuditReporter: readiness messages, green checkmarks / red X's
    per check with each check's findings (severity + title) listed
    underneath so what was actually found is visible live, and errors
    logged to logs/*.log.

    Deliberately no progress bar: rich's `Progress` renders as a persistent,
    self-redrawing region that interleaves unpredictably with the plain
    `console.print()` calls used for readiness/check/finding lines — in
    practice a prior category's bar could render *after* the next
    category's readiness message. Since every check and its findings are
    already printed line by line, the bar was redundant on top of being
    visually broken; plain sequential output has no such ordering issue.
    """

    def __init__(self, logs_dir: Path | str = "logs", interactive: bool = False) -> None:
        self._console = Console(stderr=True)
        self._announced_categories: set[int] = set()
        self._logs_dir = Path(logs_dir)
        self._logger: logging.Logger | None = None
        self._log_path: Path | None = None
        self._interactive = interactive

    def _ensure_logger(self) -> logging.Logger:
        if self._logger is None:
            self._logs_dir.mkdir(parents=True, exist_ok=True)
            timestamp = time.strftime("%Y%m%d-%H%M%S")
            self._log_path = self._logs_dir / f"audit-{timestamp}.log"
            logger = logging.getLogger(f"integri_audit_tool.cli_progress.{id(self)}")
            logger.setLevel(logging.ERROR)
            logger.propagate = False
            handler = logging.FileHandler(self._log_path, encoding="utf-8")
            handler.setFormatter(logging.Formatter("%(asctime)s %(message)s"))
            logger.addHandler(handler)
            self._logger = logger
        return self._logger

    def category_ready(self, category: "CategoryModule", checks_to_run: list["Check"]) -> None:
        self._console.print(f"\n[bold]Ready to run Category {category.number}: {category.name}[/bold]")
        if self._interactive:
            self._wait_for_enter()
        self._announced_categories.add(category.number)

    def _wait_for_enter(self) -> None:
        self._console.print("[dim]Press Enter to run this category's tests...[/dim]")
        try:
            input()
        except EOFError:
            # No interactive stdin to wait on (piped/non-interactive
            # invocation) — proceed rather than hang or crash.
            pass

    def category_not_applicable(self, category: "CategoryModule", reason: str) -> None:
        self._console.print(f"[yellow]Category {category.number} not applicable:[/yellow] {reason}")

    def check_started(self, category: "CategoryModule", check: "Check") -> None:
        self._console.print(f"Test {check.id} — {check.description}")

    def check_succeeded(
        self, category: "CategoryModule", check: "Check", findings: list["Finding"]
    ) -> None:
        # "Passed" means nothing to flag — a check that ran cleanly but found
        # even a single low-severity issue isn't a pass, it's a completed
        # check with something to address. The severity color-coding on each
        # finding line below is what conveys how urgent it is; the
        # checkmark/X only conveys whether anything was found at all.
        if findings:
            self._console.print(
                f"[bold red]✗ {check.id} completed[/bold red] ({len(findings)} finding(s))"
            )
        else:
            self._console.print(f"[green]✓ {check.id} passed[/green]")
        for finding in findings:
            style = _SEVERITY_STYLES.get(finding.severity, "")
            self._console.print(
                f"    [{style}][{finding.severity.value}][/{style}] {escape(finding.title)}"
            )

    def check_failed(self, category: "CategoryModule", check: "Check", error: Exception) -> None:
        self._console.print(f"[bold red]✗ {check.id} failed[/bold red]: {error}")
        logger = self._ensure_logger()
        logger.error("Check %s (%s) failed: %s", check.id, category.name, error, exc_info=error)

    def category_completed(self, category: "CategoryModule", result: "CategoryResult") -> None:
        # Only announce categories this reporter actually announced in the
        # first place (skips categories the --check filter excluded
        # entirely) and only when checks genuinely ran (not_applicable
        # already printed its own message via category_not_applicable).
        if category.number not in self._announced_categories or result.status != "completed":
            return
        alias = _CATEGORY_ALIASES.get(category.number, f"Category {category.number}")
        self._console.print(f"[bold]{alias} completed[/bold]")

    def audit_completed(self, report: "AuditReport") -> None:
        if self._log_path is not None:
            self._console.print(f"[yellow]Some checks failed — details logged to {self._log_path}[/yellow]")
