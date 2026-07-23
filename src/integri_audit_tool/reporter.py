"""The seam between audit orchestration and anything that wants to observe it.

`runner.py` calls these hooks as it works but never depends on how (or
whether) they're implemented — `NullReporter` is the default, a pure no-op,
so every existing caller of `run_audit()` keeps today's behavior unchanged.
A concrete, presentation-heavy implementation (colors, progress bars) lives
entirely outside core, in `cli_progress_reporter.py`.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Protocol

if TYPE_CHECKING:
    from integri_audit_tool.models import AuditReport, Finding
    from integri_audit_tool.registry import Check, CategoryModule


class AuditReporter(Protocol):
    def category_ready(self, category: "CategoryModule", checks_to_run: list["Check"]) -> None: ...

    def category_not_applicable(self, category: "CategoryModule", reason: str) -> None: ...

    def check_started(self, category: "CategoryModule", check: "Check") -> None: ...

    def check_succeeded(
        self, category: "CategoryModule", check: "Check", findings: list["Finding"]
    ) -> None: ...

    def check_failed(self, category: "CategoryModule", check: "Check", error: Exception) -> None: ...

    def audit_completed(self, report: "AuditReport") -> None: ...


class NullReporter:
    """No-op implementation of AuditReporter — every method does nothing."""

    def category_ready(self, category: "CategoryModule", checks_to_run: list["Check"]) -> None:
        pass

    def category_not_applicable(self, category: "CategoryModule", reason: str) -> None:
        pass

    def check_started(self, category: "CategoryModule", check: "Check") -> None:
        pass

    def check_succeeded(
        self, category: "CategoryModule", check: "Check", findings: list["Finding"]
    ) -> None:
        pass

    def check_failed(self, category: "CategoryModule", check: "Check", error: Exception) -> None:
        pass

    def audit_completed(self, report: "AuditReport") -> None:
        pass
