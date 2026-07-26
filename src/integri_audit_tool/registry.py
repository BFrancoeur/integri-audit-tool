"""Discovers audit category modules and exposes the Check/CategoryModule contract.

Every package under `integri_audit_tool.categories` (e.g. `03_indexing_strategy`)
must export a module-level `CATEGORY: CategoryModule` from its `__init__.py`.
Discovery is dynamic (pkgutil + importlib), so adding or removing a category
never requires touching this file — folders with a leading digit (e.g.
`03_indexing_strategy`) are not valid Python identifiers, so they're never
referenced via a static `import` statement, only via `importlib.import_module`
with a string name, which has no such restriction (the same pattern Django
uses for migration files like `0001_initial.py`).

Identity vs. display position: a `Check`'s `slug` and a `CategoryModule`'s
`slug` are each chosen once and never renumbered — they're the stable
identity a check/category is referred to by (in analytics, in `--check`
filters, in code). The *displayed* `CategoryModule.number` is not set by
category authors at all; it's computed here, from each category's position
in `_CATEGORY_ORDER`, the single place business-impact ranking lives.
Reordering categories is a one-line edit to that list, not a codebase-wide
renumbering.
"""

from __future__ import annotations

import dataclasses
import importlib
import pkgutil
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Callable

import psycopg

from integri_audit_tool import categories
from integri_audit_tool.models import Finding

if TYPE_CHECKING:
    from integri_audit_tool.config import AuditConfig

CheckFn = Callable[[psycopg.Connection, "AuditConfig"], list[Finding]]

_UNASSIGNED_CATEGORY_NUMBER = 0
"""Placeholder `CategoryModule.number` for a category not yet discovered/ordered —
overwritten by `discover_categories()` before any caller sees the category."""


@dataclass(frozen=True)
class Check:
    slug: str
    """Stable identity, e.g. "missing-foreign-keys" — chosen once, never renumbered."""
    rubric_bullet: int
    """This check's bullet number within its category's rubric checklist (see
    postgres-database-audit-rubric.md) — e.g. 4 for rubric bullet "01.04".
    Categories implement bullets out of a longer list with gaps for
    not-yet-built ones, so this is authored explicitly rather than computed
    from the check's position in `checks`. Combined with the category's
    computed `number` to form the displayed "NN.NN" check id."""
    description: str
    fn: CheckFn


@dataclass(frozen=True)
class CategoryModule:
    slug: str
    """Stable identity, e.g. "schema-design-and-normalization-boundaries" — chosen
    once, never renumbered; matches this category's package/folder name."""
    name: str
    checks: list[Check]
    number: int = _UNASSIGNED_CATEGORY_NUMBER
    """Displayed position (e.g. 1 for "Category 1"). Not set by category authors —
    computed by `discover_categories()` from `_CATEGORY_ORDER`."""
    applicability: Callable[[psycopg.Connection], bool] | None = None
    out_of_scope: list[str] = field(default_factory=list)
    """Rubric bullets this category can never assess via a read-only DB connection —
    e.g. UI/frontend logic — as distinct from bullets that are merely not yet
    implemented. Surfaced in the report's Out of Scope section alongside category 12."""


# The single place business-impact ranking lives. Position (1-indexed) becomes
# each category's displayed `number`. Currently mirrors the tool's original
# build order unchanged — reordering by business impact is deliberately a
# separate, later change, made trivial by this list once it happens.
_CATEGORY_ORDER: list[str] = [
    "schema-design-and-normalization-boundaries",
    "jsonb-structure-and-governance",
    "indexing-strategy",
    "full-text-and-structured-search-behavior",
    "query-patterns-and-application-interaction",
    "data-quality-and-integrity",
    "scale-and-growth-readiness",
    "security-and-access-boundaries",
    "backup-recovery-and-change-management",
    "monitoring-and-observability",
    "documentation-and-institutional-knowledge",
]


def _stamp_category_numbers(
    found: list[CategoryModule], order: list[str]
) -> list[CategoryModule]:
    """Pure ordering/validation step, factored out of `discover_categories()` so
    it's testable against fake categories and a fake order list, without
    needing to monkeypatch pkgutil/importlib to exercise the real 11."""
    discovered_slugs = {category.slug for category in found}
    ordered_slugs = set(order)
    if discovered_slugs != ordered_slugs:
        missing_from_order = sorted(discovered_slugs - ordered_slugs)
        missing_from_discovery = sorted(ordered_slugs - discovered_slugs)
        raise ValueError(
            "_CATEGORY_ORDER is out of sync with discovered categories. "
            f"Discovered but not in _CATEGORY_ORDER: {missing_from_order}. "
            f"In _CATEGORY_ORDER but not discovered: {missing_from_discovery}."
        )

    numbered = [
        dataclasses.replace(category, number=order.index(category.slug) + 1) for category in found
    ]
    return sorted(numbered, key=lambda c: c.number)


def discover_categories() -> list[CategoryModule]:
    """Import every category package, collect its CATEGORY object, and stamp its
    displayed `number` from `_CATEGORY_ORDER`. Returns categories sorted by that number."""
    found: list[CategoryModule] = []
    for module_info in pkgutil.iter_modules(categories.__path__):
        module = importlib.import_module(f"{categories.__name__}.{module_info.name}")
        category = getattr(module, "CATEGORY", None)
        if category is None:
            raise AttributeError(
                f"Category package '{module_info.name}' does not export a CATEGORY object"
            )
        found.append(category)

    return _stamp_category_numbers(found, _CATEGORY_ORDER)
