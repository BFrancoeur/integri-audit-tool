"""Runtime configuration for an audit run."""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class AuditConfig:
    dsn: str | None
    """None when connecting via --ssh-connect rather than a direct DSN — no
    check currently reads this field, but it's kept accurate rather than a
    placeholder in case one ever needs to."""
    category_filter: set[int] | None = field(default=None)
    """If set, only these rubric category numbers are run. None means run all discovered categories."""
    check_filter: set[str] | None = field(default=None)
    """If set, only checks matching one of these values are run — either a stable
    slug (e.g. "missing-foreign-keys") or the currently-displayed "NN.NN" id
    (e.g. "01.04"). None means no filtering by check."""
