"""Interprets category-1 catalog queries into Finding objects.

One function per rubric checklist bullet (see postgres-database-audit-rubric.md,
"1. Schema Design & Normalization Boundaries"). Each takes a live connection +
config and returns zero or more Findings. Kept separate from queries.py so this
interpretation logic is unit-testable against canned row data without a live
database.
"""

from __future__ import annotations

import re

import psycopg

from integri_audit_tool.config import AuditConfig
from integri_audit_tool.models import Finding, Severity

from . import queries

_INTEGER_FAMILY = {"integer", "bigint", "smallint"}

MIN_REPEATING_COLUMN_GROUP_SIZE = 3
"""Minimum number of same-typed, same-pattern columns before it's flagged as a
likely repeating group -- two columns (e.g. start_date/end_date) is normal
schema design, not a pivoted structure."""

MIN_COLUMN_NAME_TOKEN_COUNT = 2
"""A column name needs at least this many underscore-separated tokens for one
of them to be a "varying position" against a shared prefix/suffix -- a
single-token name has nothing to anchor a pattern to."""

_TEXT_SHAPE_MATCH_FRACTION_THRESHOLD = 0.9
"""Fraction of a column's sampled non-null values that must consistently
match one shape (numeric/date/delimited-list) before it's flagged -- high
enough that a handful of legitimately-mixed rows (a free-text fallback, a
migration artifact) doesn't trigger a false positive."""

_NUMERIC_SHAPE_PATTERN = re.compile(r"^-?\d+(\.\d+)?$")
_DATE_SHAPE_PATTERN = re.compile(r"^\d{4}-\d{2}-\d{2}([ T]\d{2}:\d{2}:\d{2})?$")

MAX_DELIMITED_VALUE_LENGTH = 200
"""A value longer than this is treated as prose, not a delimited list, even
if it happens to contain a comma or semicolon -- avoids flagging free-text
description/notes fields that occasionally use list punctuation."""

_NUMERIC_ENUMERATION_TOKEN_PATTERN = re.compile(r"^[a-z]{0,3}\d+$", re.IGNORECASE)
"""Matches tokens that look like a numbered/dated label (`1`, `01`, `q1`,
`wh3`, `2024`). Requiring the *varying* token to match this is what keeps this
check from flagging ordinary same-suffix columns that aren't a pivot at all --
created_at/updated_at/deleted_at all end in "at", but "created"/"updated"/
"deleted" aren't a numbered enumeration, so that group is never flagged. The
trade-off: a purely alphabetic enumeration (jan_qty/feb_qty/mar_qty) won't be
caught without hardcoding a vocabulary of month/quarter/weekday names, which
this check deliberately avoids."""


def _looks_like_owned_child(parent_table_name: str, child_table_name: str) -> bool:
    """Coarse ownership heuristic: a dependent/child table's name conventionally
    embeds its parent's (order_items, invoice_lines) -- naive de-pluralization
    (strip a trailing 's') so "orders" -> "order" still matches "order_items".
    A child name that doesn't contain the parent's name either way isn't
    obviously an owned relationship, which is what makes ON DELETE CASCADE on
    it worth a second look rather than assumed-correct."""
    parent_lower = parent_table_name.lower()
    child_lower = child_table_name.lower()
    singularized = parent_lower.removesuffix("s")
    return parent_lower in child_lower or singularized in child_lower


def check_missing_foreign_keys(conn: psycopg.Connection, config: AuditConfig) -> list[Finding]:
    """Rubric 01.04 — are FK constraints present where relationships exist?"""
    findings = []
    for row in queries.fetch_fk_like_columns_without_fk(conn):
        findings.append(
            Finding(
                check_slug="missing-foreign-keys",
                title=f"FK-shaped column without a declared constraint: {row['table_name']}.{row['column_name']}",
                severity=Severity.HIGH,
                observation=(
                    f"Column '{row['column_name']}' ({row['data_type']}) on "
                    f"{row['schema_name']}.{row['table_name']} looks like a foreign key reference "
                    "(name ends in '_id') but has no declared FOREIGN KEY constraint."
                ),
                evidence="Detected via information_schema.columns + table_constraints (naming heuristic).",
                business_impact=(
                    "Without a declared constraint, referential integrity depends entirely on "
                    "application code — orphaned or inconsistent references can accumulate silently."
                ),
                recommended_direction=(
                    "If this column does reference another table, add a FOREIGN KEY constraint "
                    "(or confirm intentionally denormalized / soft-referenced and document why)."
                ),
            )
        )

    for row in queries.fetch_on_delete_cascade_constraints(conn):
        if _looks_like_owned_child(row["parent_table_name"], row["table_name"]):
            continue
        findings.append(
            Finding(
                check_slug="missing-foreign-keys",
                title=f"ON DELETE CASCADE on an unexpected relationship: {row['table_name']} -> {row['parent_table_name']}",
                severity=Severity.MEDIUM,
                observation=(
                    f"Constraint '{row['conname']}' on {row['schema_name']}.{row['table_name']} "
                    f"cascades deletes from '{row['parent_table_name']}', but '{row['table_name']}' "
                    f"doesn't look like an owned/dependent child of '{row['parent_table_name']}' by name "
                    "(e.g. order_items owned by orders) — worth confirming this is intentional."
                ),
                evidence="Detected via pg_constraint.confdeltype = 'c' (naming heuristic, not a confirmed misconfiguration).",
                business_impact=(
                    "Deleting a row in the parent table silently deletes every matching row here too — "
                    "if this relationship isn't genuinely an ownership one, that's real data loss "
                    "triggered from an unexpected place."
                ),
                recommended_direction=(
                    "Confirm ON DELETE CASCADE was intentional here; if the relationship is referential "
                    "rather than ownership, RESTRICT or SET NULL is usually safer."
                ),
            )
        )

    return findings


def check_schema_drift(conn: psycopg.Connection, config: AuditConfig) -> list[Finding]:
    """Rubric 01.05 — is there evidence of schema drift (same concept, different naming/types)?"""
    findings = []
    for row in queries.fetch_columns_with_name_or_type_drift(conn):
        type_drift = len(row["observed_types"]) > 1
        severity = Severity.MEDIUM if type_drift else Severity.LOW
        kind = "naming and type" if type_drift else "naming"
        findings.append(
            Finding(
                check_slug="schema-drift",
                title=f"Schema drift ({kind}) for column concept '{row['normalized_name']}'",
                severity=severity,
                observation=(
                    f"The concept '{row['normalized_name']}' appears with names "
                    f"{row['observed_names']} and types {row['observed_types']} across tables "
                    f"{row['tables']}."
                ),
                evidence="Grouped via information_schema.columns on lower(column_name) with underscores stripped.",
                business_impact=(
                    "Inconsistent types for the same concept can cause silent bugs in joins/comparisons; "
                    "inconsistent naming increases onboarding cost and the chance of missed references."
                ),
                recommended_direction=(
                    "Standardize on one name and type for this concept, or document why the variants "
                    "are intentionally different."
                ),
            )
        )
    return findings


def check_primary_key_consistency(conn: psycopg.Connection, config: AuditConfig) -> list[Finding]:
    """Rubric 01.06 — are primary keys/identity columns used consistently?"""
    findings = []

    for row in queries.fetch_tables_without_primary_key(conn):
        findings.append(
            Finding(
                check_slug="primary-key-consistency",
                title=f"Table without a primary key: {row['table_name']}",
                severity=Severity.HIGH,
                observation=f"{row['schema_name']}.{row['table_name']} has no PRIMARY KEY constraint.",
                evidence="Detected via information_schema.table_constraints.",
                business_impact=(
                    "Without a primary key, rows can't be reliably deduplicated or referenced, and "
                    "many replication/CDC tools either can't operate on the table or silently degrade."
                ),
                recommended_direction="Add a primary key (surrogate or natural) unless this table is deliberately append-only/unkeyed.",
            )
        )

    pk_rows = queries.fetch_primary_key_column_types(conn)
    families = {row["data_type"]: _classify_pk_type(row["data_type"]) for row in pk_rows}
    observed_families = set(families.values())
    if len(observed_families) > 1:
        by_family: dict[str, list[str]] = {}
        for row in pk_rows:
            family = _classify_pk_type(row["data_type"])
            by_family.setdefault(family, []).append(f"{row['table_name']} ({row['data_type']})")
        summary = "; ".join(f"{family}: {', '.join(tables)}" for family, tables in sorted(by_family.items()))
        findings.append(
            Finding(
                check_slug="primary-key-consistency",
                title="Mixed primary key type families across the schema",
                severity=Severity.INFORMATIONAL,
                observation=f"Primary keys use more than one type family: {summary}.",
                evidence="Detected via information_schema.table_constraints + key_column_usage.",
                business_impact=(
                    "Mixing UUID and integer/serial primary keys isn't necessarily wrong, but ad hoc "
                    "mixing without a stated reason makes join/FK typing less predictable across the schema."
                ),
                recommended_direction="Confirm the mix is a deliberate choice (e.g. UUID for public-facing entities, serial elsewhere) and document it.",
            )
        )

    return findings


def _classify_pk_type(data_type: str) -> str:
    if data_type == "uuid":
        return "uuid"
    if data_type in _INTEGER_FAMILY:
        return "integer"
    return "other"


def _classify_text_column_shape(values: list[str]) -> tuple[str, float] | None:
    """Returns (shape, matched_fraction) for the dominant shape among sampled
    values if it clears _TEXT_SHAPE_MATCH_FRACTION_THRESHOLD, else None.
    Priority order (numeric > date > delimited-list) is arbitrary but the
    three shapes are near-mutually-exclusive in practice, so it rarely matters."""
    if len(values) < queries.MIN_SAMPLE_SIZE_FOR_SHAPE_CHECK:
        return None

    total = len(values)
    numeric_fraction = sum(1 for v in values if _NUMERIC_SHAPE_PATTERN.match(v)) / total
    date_fraction = sum(1 for v in values if _DATE_SHAPE_PATTERN.match(v)) / total
    list_fraction = sum(
        1 for v in values if len(v) <= MAX_DELIMITED_VALUE_LENGTH and ("," in v or ";" in v)
    ) / total

    for shape, fraction in (("numeric", numeric_fraction), ("date", date_fraction), ("delimited list", list_fraction)):
        if fraction >= _TEXT_SHAPE_MATCH_FRACTION_THRESHOLD:
            return shape, fraction
    return None


def check_structured_data_stored_as_text(conn: psycopg.Connection, config: AuditConfig) -> list[Finding]:
    """Rubric 01.02 — are there columns storing structured data as text that
    should be typed (dates as strings, numbers as text, comma-separated
    lists), oversized/unbounded varchar, or money-typed columns?
    """
    findings = []

    for row in queries.fetch_text_typed_columns(conn):
        values = queries.fetch_text_column_value_sample(
            conn, row["schema_name"], row["table_name"], row["column_name"]
        )
        classified = _classify_text_column_shape(values)
        if classified is None:
            continue
        shape, fraction = classified
        findings.append(
            Finding(
                check_slug="structured-data-stored-as-text",
                title=f"{shape.capitalize()} data stored as text: {row['table_name']}.{row['column_name']}",
                severity=Severity.MEDIUM,
                observation=(
                    f"{fraction:.0%} of {len(values)} sampled non-null values in "
                    f"{row['schema_name']}.{row['table_name']}.{row['column_name']} look like {shape} data, "
                    "but the column is text-typed."
                ),
                evidence=f"Sampled up to {queries.TEXT_SHAPE_SAMPLE_LIMIT} non-null values (pattern match, not a full-table scan).",
                business_impact=(
                    "Structured data stored as text can't be indexed, sorted, filtered, or validated the "
                    "way its real type would allow — every consumer has to re-parse it, and nothing stops "
                    "a value that doesn't match the expected shape from being written."
                ),
                recommended_direction=(
                    f"If this column is consistently {shape}, migrate it to a properly typed column "
                    "(numeric, date/timestamptz, or a normalized child table for list values)."
                ),
            )
        )

    for row in queries.fetch_varchar_without_length(conn):
        findings.append(
            Finding(
                check_slug="structured-data-stored-as-text",
                title=f"varchar with no declared length: {row['table_name']}.{row['column_name']}",
                severity=Severity.LOW,
                observation=(
                    f"{row['schema_name']}.{row['table_name']}.{row['column_name']} is `character varying` "
                    "with no length specified — functionally identical to `text` but implies a bound that "
                    "was never actually declared."
                ),
                evidence="Detected via information_schema.columns.character_maximum_length IS NULL.",
                business_impact=(
                    "A reader reasonably assumes an unqualified varchar has some intended limit; without "
                    "one, that assumption is false and nothing enforces a bound at the database level."
                ),
                recommended_direction="Either declare an actual length limit or switch to `text` to be explicit that none is intended.",
            )
        )

    for row in queries.fetch_money_type_usage(conn):
        findings.append(
            Finding(
                check_slug="structured-data-stored-as-text",
                title=f"money type usage: {row['table_name']}.{row['column_name']}",
                severity=Severity.LOW,
                observation=f"{row['schema_name']}.{row['table_name']}.{row['column_name']} uses the `money` type.",
                evidence="Detected via information_schema.columns.data_type = 'money'.",
                business_impact=(
                    "`money` is tied to the database's locale-dependent currency formatting and rounding "
                    "behavior, doesn't survive a locale change cleanly, and has looser arithmetic/rounding "
                    "semantics than a fixed-precision numeric type."
                ),
                recommended_direction="Migrate to `numeric(p,s)` with an explicit precision/scale for the currency in use.",
            )
        )

    return findings


def check_repeating_column_groups(conn: psycopg.Connection, config: AuditConfig) -> list[Finding]:
    """Rubric 01.07 -- is a repeating value (period, location, category) spread
    across multiple similarly-named columns instead of normalized into rows?
    """
    findings = []
    columns_by_table = _group_columns_by_table(queries.fetch_all_columns(conn))
    for (schema_name, table_name), columns in columns_by_table.items():
        for family in _find_repeating_column_families(columns):
            column_list = ", ".join(family["columns"])
            findings.append(
                Finding(
                    check_slug="repeating-column-groups",
                    title=f"Repeating column group on {table_name}: {family['pattern']}",
                    severity=Severity.MEDIUM,
                    observation=(
                        f"{schema_name}.{table_name} has {len(family['columns'])} {family['data_type']} "
                        f"columns ({column_list}) whose names differ only by a numbered/dated token -- "
                        "consistent with a repeating value (a period, warehouse, or category) spread "
                        "across columns instead of normalized into rows."
                    ),
                    evidence="Detected via information_schema.columns (naming/type pattern heuristic).",
                    business_impact=(
                        "Data modeled as repeating columns instead of rows doesn't scale (adding a new "
                        "period or location requires a schema migration, not a data insert), resists "
                        "ordinary aggregation/filtering without UNIONing every column, and tends to "
                        "accumulate NULLs as the enumeration grows."
                    ),
                    recommended_direction=(
                        "If this represents a repeating concept, consider normalizing it into its own "
                        "table with one row per value, unless there's a specific, documented performance "
                        "reason to keep it wide."
                    ),
                )
            )
    return findings


def _group_columns_by_table(rows: list[dict]) -> dict[tuple[str, str], list[dict]]:
    grouped: dict[tuple[str, str], list[dict]] = {}
    for row in rows:
        grouped.setdefault((row["schema_name"], row["table_name"]), []).append(row)
    return grouped


def _find_repeating_column_families(columns: list[dict]) -> list[dict]:
    """Groups same-typed columns on one table by their underscore-separated
    tokens, and flags any group of >= MIN_REPEATING_COLUMN_GROUP_SIZE columns
    whose names are identical except at exactly one token position, where the
    varying tokens all look like a numbered/dated enumeration. Deduplicates by
    exact column set so a family isn't reported once per matching position.
    """
    families: dict[frozenset, dict] = {}
    by_type: dict[str, list[dict]] = {}
    for col in columns:
        by_type.setdefault(col["data_type"], []).append(col)

    for data_type, same_type_columns in by_type.items():
        tokenized = [
            (col["column_name"], col["column_name"].split("_"))
            for col in same_type_columns
            if len(col["column_name"].split("_")) >= MIN_COLUMN_NAME_TOKEN_COUNT
        ]
        by_token_count: dict[int, list[tuple[str, list[str]]]] = {}
        for name, tokens in tokenized:
            by_token_count.setdefault(len(tokens), []).append((name, tokens))

        for entries in by_token_count.values():
            token_count = len(entries[0][1])
            for position in range(token_count):
                by_skeleton: dict[tuple[str, ...], list[tuple[str, str]]] = {}
                for name, tokens in entries:
                    skeleton = tuple(tok if i != position else "*" for i, tok in enumerate(tokens))
                    by_skeleton.setdefault(skeleton, []).append((name, tokens[position]))

                for skeleton, matches in by_skeleton.items():
                    if len(matches) < MIN_REPEATING_COLUMN_GROUP_SIZE:
                        continue
                    if not all(_NUMERIC_ENUMERATION_TOKEN_PATTERN.match(tok) for _, tok in matches):
                        continue
                    names = sorted(name for name, _ in matches)
                    key = frozenset(names)
                    families.setdefault(
                        key,
                        {"columns": names, "data_type": data_type, "pattern": "_".join(skeleton)},
                    )

    return list(families.values())
