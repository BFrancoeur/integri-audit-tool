"""Discovers audit category modules and exposes the Check/CategoryModule contract.

Every package under `integri_audit_tool.categories` (e.g. `03_indexing_strategy`)
must export a module-level `CATEGORY: CategoryModule` from its `__init__.py`.
Discovery is dynamic (pkgutil + importlib), so adding, removing, or reordering
a category never requires touching this file — folders with a leading digit
(e.g. `03_indexing_strategy`) are not valid Python identifiers, so they're never
referenced via a static `import` statement, only via `importlib.import_module`
with a string name, which has no such restriction (the same pattern Django
uses for migration files like `0001_initial.py`).
"""

from __future__ import annotations

import importlib
import pkgutil
from dataclasses import dataclass
from typing import TYPE_CHECKING, Callable

import psycopg

from integri_audit_tool import categories
from integri_audit_tool.models import Finding

if TYPE_CHECKING:
    from integri_audit_tool.config import AuditConfig

CheckFn = Callable[[psycopg.Connection, "AuditConfig"], list[Finding]]


@dataclass(frozen=True)
class Check:
    id: str
    description: str
    fn: CheckFn


@dataclass(frozen=True)
class CategoryModule:
    number: int
    name: str
    checks: list[Check]
    applicability: Callable[[psycopg.Connection], bool] | None = None


def discover_categories() -> list[CategoryModule]:
    """Import every category package and collect its CATEGORY object, sorted by number."""
    found: list[CategoryModule] = []
    for module_info in pkgutil.iter_modules(categories.__path__):
        module = importlib.import_module(f"{categories.__name__}.{module_info.name}")
        category = getattr(module, "CATEGORY", None)
        if category is None:
            raise AttributeError(
                f"Category package '{module_info.name}' does not export a CATEGORY object"
            )
        found.append(category)
    return sorted(found, key=lambda c: c.number)
