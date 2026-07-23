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
    from integri_audit_tool.models import AuditReport, CategoryResult, Finding
    from integri_audit_tool.registry import Check, CategoryModule


class AuditReporter(Protocol):
    def category_ready(self, category: "CategoryModule", checks_to_run: list["Check"]) -> None: ...

    def category_not_applicable(self, category: "CategoryModule", reason: str) -> None: ...

    def check_started(self, category: "CategoryModule", check: "Check") -> None: ...

    def check_succeeded(
        self, category: "CategoryModule", check: "Check", findings: list["Finding"]
    ) -> None: ...

    def check_failed(self, category: "CategoryModule", check: "Check", error: Exception) -> None: ...

    def category_completed(self, category: "CategoryModule", result: "CategoryResult") -> None: ...

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

    def category_completed(self, category: "CategoryModule", result: "CategoryResult") -> None:
        pass

    def audit_completed(self, report: "AuditReport") -> None:
        pass


class CompositeReporter:
    """Fans every AuditReporter call out to multiple reporters — e.g. the
    terminal progress UI and a report-writing reporter running side by side,
    each unaware of the other, without either of them needing to know about
    composition at all."""

    def __init__(self, reporters: list["AuditReporter"]) -> None:
        self._reporters = reporters

    def category_ready(self, category: "CategoryModule", checks_to_run: list["Check"]) -> None:
        for reporter in self._reporters:
            reporter.category_ready(category, checks_to_run)

    def category_not_applicable(self, category: "CategoryModule", reason: str) -> None:
        for reporter in self._reporters:
            reporter.category_not_applicable(category, reason)

    def check_started(self, category: "CategoryModule", check: "Check") -> None:
        for reporter in self._reporters:
            reporter.check_started(category, check)

    def check_succeeded(
        self, category: "CategoryModule", check: "Check", findings: list["Finding"]
    ) -> None:
        for reporter in self._reporters:
            reporter.check_succeeded(category, check, findings)

    def check_failed(self, category: "CategoryModule", check: "Check", error: Exception) -> None:
        for reporter in self._reporters:
            reporter.check_failed(category, check, error)

    def category_completed(self, category: "CategoryModule", result: "CategoryResult") -> None:
        for reporter in self._reporters:
            reporter.category_completed(category, result)

    def audit_completed(self, report: "AuditReport") -> None:
        for reporter in self._reporters:
            reporter.audit_completed(report)
