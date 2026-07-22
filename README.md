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

_TBD — usage instructions will be added here as the tool is built out._

## Notes

This README doubles as the running notebook for this project — architecture decisions, gotchas, and other context worth preserving belong here as the tool develops.
