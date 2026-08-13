"""Runtime configuration for an audit run."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path


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
    interactive: bool = False
    """Whether a Check with interactive=True should actually prompt for
    attestation (see attestation.py/runner.py's _apply_attestation). False
    (the default, e.g. CI/scripted runs) ships every requires_attestation
    finding unconfirmed rather than blocking on stdin."""
    duplicate_fingerprint_config: Path | None = None
    """Path to a per-engagement identity-fingerprint config (see
    fingerprint_config.py) defining what makes two rows the "same" business
    entity for semantic-duplicate-detection. None means that category is N/A
    for this run -- never guess business-identity fields."""
