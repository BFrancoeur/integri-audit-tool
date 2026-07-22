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


@dataclass(frozen=True)
class Finding:
    category_number: int
    category_name: str
    check_id: str
    title: str
    severity: Severity
    observation: str
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
