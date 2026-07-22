"""Runtime configuration for an audit run."""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class AuditConfig:
    dsn: str
    category_filter: set[int] | None = field(default=None)
    """If set, only these rubric category numbers are run. None means run all discovered categories."""
