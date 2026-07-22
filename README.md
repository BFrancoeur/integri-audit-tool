# Integri Audit Tool

A read-only diagnostic tool for auditing client Postgres databases — schema design, JSONB governance, indexing, search behavior, query patterns, data quality, scale readiness, security boundaries, backup/recovery posture, monitoring, and documentation.

It automates the first 11 categories of the Postgres Database & Search Audit Rubric (maintained separately in the `pi-docs` project), connecting to a target database with read-only access and producing a findings report scoped and formatted per that rubric.

## What it does

For each of the following categories, the tool inspects the database (schema, `pg_stat_statements`, `EXPLAIN` plans, catalog metadata, role grants, etc.) and surfaces findings with a severity rating (Critical / High / Medium / Low / Informational):

1. Schema Design & Normalization Boundaries
2. JSONB Structure & Governance
3. Indexing Strategy
4. Full-Text & Structured Search Behavior
5. Query Patterns & Application Interaction
6. Data Quality & Integrity
7. Scale & Growth Readiness
8. Security & Access Boundaries
9. Backup, Recovery & Change Management
10. Monitoring & Observability
11. Documentation & Institutional Knowledge

**Category 12 (Compliance & Data Privacy) is explicitly out of scope for this tool.** Per the rubric, that category is almost entirely manual-confirmation / human-verified — legal basis, consent records, DPAs, and breach-notification readiness can't be confirmed by a read-only DB connection. The tool may surface supporting signals (e.g., PII column detection, encryption-at-rest signals, RLS presence) but does not attempt to assess compliance itself.

## Why it matters

Manually working through an 11-category rubric against a live database is slow and error-prone — someone has to hand-run `EXPLAIN ANALYZE`, cross-reference `pg_stat_statements`, inspect JSONB key consistency, and check role grants, all before writing up findings. This tool automates the repeatable, mechanically-checkable parts of that process so a human auditor can focus on judgment calls (severity weighting, business impact, remediation sequencing) instead of data collection.

Findings are produced in the audit phase only — read-only, no writes. Remediation is a separate, subsequent engagement.

## Usage

Requires [`uv`](https://docs.astral.sh/uv/) and Python 3.11+ (uv provisions the interpreter automatically).

```bash
uv sync --group dev            # install runtime + dev dependencies
uv run integri-audit --dsn "postgresql://user:pass@host:5432/dbname"
uv run integri-audit --dsn "$INTEGRI_DSN" --output report.md      # write to a file instead of stdout
uv run integri-audit --dsn "$INTEGRI_DSN" -c 3 -c 6                # limit to specific rubric category numbers
```

The DSN can also be supplied via the `INTEGRI_DSN` environment variable instead of `--dsn`. The tool connects read-only and never writes to the audited database.

Run the tests:

```bash
uv run pytest                  # unit tests (fast, no DB required)
uv run pytest -m integration   # + integration tests against a real Postgres (requires Docker)
```

## Architecture

- **Core** (`src/integri_audit_tool/`) — CLI entrypoint (`cli.py`), read-only DB connection handling (`db.py`), the `Finding`/`Severity`/`AuditReport` data model (`models.py`), dynamic category discovery (`registry.py`), audit orchestration (`runner.py`), and the Markdown report renderer (`report/markdown.py`).
- **Categories** (`src/integri_audit_tool/categories/`) — one package per rubric category, folder-named to mirror the rubric heading (e.g. `03_indexing_strategy` ↔ rubric section "3. Indexing Strategy"). Each exports a `CATEGORY` object the registry discovers automatically — no central list to maintain. Default granularity is one function per rubric checklist bullet; a category only gets extra files (e.g. splitting `queries.py` raw SQL from `checks.py` interpretation logic) when it's complex enough to need it.
- Category folders start with a zero-padded number and are therefore not valid Python identifiers as literal `import` targets — this is intentional and safe, since they're only ever loaded dynamically via `importlib` (see `registry.py`), the same pattern Django uses for migration files (`0001_initial.py`).
- Implemented so far: **Schema Design & Normalization Boundaries** (category 1, 3 of 6 bullets) and **Indexing Strategy** (category 3, 3 of 7 bullets). The remaining 9 categories exist as stub packages (`CATEGORY` with an empty `checks` list) ready to be filled in the same way, incrementally, working down the rubric in order.
- A real bug worth remembering: `information_schema.columns` fields (`column_name`, `data_type`, etc.) are Postgres *domain* types (`sql_identifier`, `character_data`), not plain `text`/`varchar`. `array_agg()` over a domain-typed column produces an array whose element OID psycopg has no decoder for, so it silently comes back as an undecoded wire string instead of a Python list (iterating it then yields characters, not list items) — cast to `::text` before aggregating. Caught by the category-1 integration tests, not the mocked-cursor unit tests, since the unit tests hand back already-parsed Python data. This is exactly why queries.py has its own integration coverage separate from checks.py's unit tests.
- Category 12 (Compliance & Data Privacy) is never a discovered module — it's a static "out of scope" note the report renderer always includes.

## Notes

This README doubles as the running notebook for this project — architecture decisions, gotchas, and other context worth preserving belong here as the tool develops.
