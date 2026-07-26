"""Data model shared by every audit category: Severity, Finding, CategoryResult, AuditReport."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Literal

CATEGORY_12_OUT_OF_SCOPE_NOTE = (
    "Category 12: Compliance & Data Privacy — manual/legal review only "
    "(not assessable via read-only DB connection; see rubric §12 scope note)."
)


class Severity(str, Enum):
    CRITICAL = "Critical"
    HIGH = "High"
    MEDIUM = "Medium"
    LOW = "Low"
    INFORMATIONAL = "Informational"


_UNSTAMPED_CATEGORY_NUMBER = 0
_UNSTAMPED_CATEGORY_NAME = ""
_UNSTAMPED_CHECK_ID = ""
"""Placeholders for the fields runner.py stamps onto every Finding after a
check function returns it — a check function itself has no way to know its
own category's computed number/name or its own displayed check id, only its
stable `check_slug`."""


@dataclass(frozen=True)
class Finding:
    check_slug: str
    """Stable identity of the check that produced this finding, e.g.
    "missing-foreign-keys" — set by the check function itself, always required."""
    title: str
    severity: Severity
    observation: str
    category_number: int = _UNSTAMPED_CATEGORY_NUMBER
    category_name: str = _UNSTAMPED_CATEGORY_NAME
    check_id: str = _UNSTAMPED_CHECK_ID
    """Displayed "NN.NN" id at the time of this run — computed and stamped by
    runner.py from the category's current position in the rubric, not set by
    the check function."""
    evidence: str | None = None
    business_impact: str = ""
    recommended_direction: str = ""


CategoryStatus = Literal["completed", "not_applicable", "error"]


@dataclass(frozen=True)
class CategoryResult:
    category_number: int
    category_name: str
    status: CategoryStatus
    findings: list[Finding] = field(default_factory=list)
    na_reason: str | None = None


@dataclass(frozen=True)
class AuditReport:
    target_label: str
    generated_at: datetime
    category_results: list[CategoryResult]
    out_of_scope: list[str] = field(default_factory=lambda: [CATEGORY_12_OUT_OF_SCOPE_NOTE])
    client_name: str | None = None
    """The client's business name, if collected (--ask-client-name). Drives the
    report title; falls back to a generic title when not set, e.g. for
    ad hoc single-category runs (ia-schema et al.) that never prompt for it."""
