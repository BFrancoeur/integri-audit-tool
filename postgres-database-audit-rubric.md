# Postgres Database & Search Audit Rubric

**Purpose:** Standardized diagnostic framework for auditing client Postgres databases — schema design, indexing strategy, JSONB usage, and search/query performance. Produces a fixed-scope findings report, separate from any remediation engagement.

**Engagement boundary:** This rubric governs the **audit phase only** (read-only access, no writes). Remediation is scoped and priced separately based on findings.

---

## How to Use This Document

1. Work through each category in order. Not every category applies to every client — mark N/A where the schema doesn't include that concern (e.g., no JSONB usage).
2. Assign a **severity** to each finding using the scale below.
3. For each finding: state what you observed, why it matters (business impact, not just technical description), and the recommended direction (not full remediation detail — that's the next engagement).
4. Roll findings into a summary table at the front of the report — clients read that first.

### Severity Scale

| Level | Definition | Typical response time |
|---|---|---|
| **Critical** | Active data integrity risk, or search/query failures affecting production users now | Immediate |
| **High** | Will cause incorrect results, significant performance degradation, or data drift as volume grows | Next remediation cycle |
| **Medium** | Inefficiency or inconsistency that increases cognitive load / maintenance cost but isn't user-facing yet | Planned |
| **Low** | Best-practice deviation, no measured impact yet | Opportunistic |
| **Informational** | Worth noting, not a defect (e.g., "you'll want to revisit this at 5M+ rows") | N/A |

---

## 1. Schema Design & Normalization Boundaries

- [ ] Are JSONB columns being used for genuinely variable/sparse attributes, or as a substitute for proper normalization (i.e., "schema-less" as a way to avoid migrations)?
- [ ] Are there columns storing structured data as text that should be typed (dates as strings, numbers as text, comma-separated lists), oversized/unbounded `varchar`, or `money`-typed columns? *(Extended from a client audit SOP, 2026-08-03; that SOP's fourth sub-signal — inconsistent `timestamp` vs. `timestamptz` across related tables — isn't a separate check here, since the schema-drift bullet below already catches it.)*
- [ ] Is there an appropriate split between "core" relational columns (used in joins, constraints, foreign keys) and "flexible" JSONB attributes?
- [ ] Are foreign key constraints present where relationships exist, or is referential integrity being enforced only in application code? *(SOP: also covers `ON DELETE CASCADE` constraints whose child table doesn't look like an owned/dependent relationship by name — worth confirming intentional.)*
- [ ] Is there evidence of schema drift — same concept represented differently across tables or categories (naming, casing, types)?
- [ ] Are primary keys and identity columns used consistently (no ad hoc UUID-vs-serial mixing without reason)?
- [ ] Are there tables where a repeating value (a period, location, or category) has been spread across multiple similarly-named columns instead of normalized into rows (e.g. `jan_qty`/`feb_qty`/`mar_qty`, `warehouse_1_stock`/`warehouse_2_stock`)?

**What "good" looks like:** A clear, documented rationale for every JSONB column — what it's for, what's expected to vary, and what's deliberately kept relational.

---

## 2. JSONB Structure & Governance

- [ ] Is there a governing schema/registry for what keys are valid within JSONB columns (per category, tenant, or type), or is structure emergent from whatever the application happens to write?
- [ ] Are there inconsistent key names for the same concept (`diameter` vs `dia` vs `diameter_in`)?
- [ ] Are there type inconsistencies for the same key (numeric in some rows, string in others)?
- [ ] Is there a validation layer (application-level, trigger, or CHECK constraint) preventing malformed JSONB from being written, or is bad data only caught downstream?
- [ ] How deeply nested is the JSONB in practice — and does query code rely on brittle nested paths that break silently on structural change?
- [ ] Are there orphaned or legacy keys accumulating from deprecated features?

**What "good" looks like:** A registry table or equivalent governance mechanism, enforced at write time, with clear ownership of what's allowed to go into JSONB columns.

---

## 3. Indexing Strategy

- [ ] Do query patterns (from logs, `pg_stat_statements`, or app code) match the indexes that exist? Look for indexes that are never used and filters that never hit an index. *(Extended from a client audit SOP, 2026-08-03: also covers foreign keys with no supporting index — a near-automatic finding, since it forces a full table scan on every parent-row delete/update cascade check — tables scanned sequentially far more than they're indexed into, and composite indexes whose declared column order doesn't match how queries actually filter.)*
- [ ] Is GIN used appropriately for JSONB containment (`@>`) and full-text search — and is `jsonb_path_ops` vs default `jsonb_ops` the right choice for the actual query patterns (containment-only vs key-existence)?
- [ ] Are B-tree indexes present on high-selectivity columns used in equality/range filters, joins, and sort/order-by clauses?
- [ ] Are there redundant or overlapping indexes (e.g., both a composite and a single-column index that make the same query paths dual-covered without benefit)?
- [ ] Are range queries (numeric or date) being run against JSONB fields with no promoted column — a common silent performance killer?
- [ ] Is there an index maintenance concern — high write volume tables with excessive indexing, causing write amplification?
- [ ] Are partial indexes or expression indexes used where they'd meaningfully narrow index size (e.g., indexing only `WHERE active = true`)?

**What "good" looks like:** Every index has a traceable reason tied to an actual query pattern; `EXPLAIN ANALYZE` on representative queries shows index scans, not sequential scans, on non-trivial tables.

---

## 4. Full-Text & Structured Search Behavior

- [ ] If full-text search exists, is it using `tsvector`/`tsquery` with GIN indexing, or is it falling back to `ILIKE '%term%'` (unindexable, won't scale)?
- [ ] Is the tsvector generation reasonable — appropriate `to_tsvector` config (language), sensible field weighting, and kept in sync via generated column or trigger (not manually maintained and prone to going stale)?
- [ ] Are structured filters (JSONB containment) and free-text search combined efficiently in the same query, or are they two separate, un-composed code paths?
- [ ] Does search relevance ranking (`ts_rank` or equivalent) exist, or are results unordered/arbitrarily ordered?
- [ ] Is query input handled through `websearch_to_tsquery` (or equivalent safe parsing) rather than raw string concatenation into `tsquery`?
- [ ] Are facet/filter UI options generated dynamically from actual governed attributes, or hardcoded/inconsistent with what's actually in the data?

**What "good" looks like:** Search combines full-text and structured filtering in a single planned query, uses ranked relevance, and facets are always accurate to what's actually filterable and present in the data.

---

## 5. Query Patterns & Application Interaction

- [ ] Evidence of N+1 query patterns (many small queries per page load instead of one joined/batched query)?
- [ ] Are queries parameterized (protecting against injection) or built via string concatenation?
- [ ] Is pagination implemented efficiently (keyset/cursor-based) or via `OFFSET` at scale (which degrades linearly with offset size)?
- [ ] Are transactions scoped appropriately — neither so broad they hold locks unnecessarily, nor so narrow that multi-step operations risk partial writes?
- [ ] Is connection pooling configured appropriately for the workload (e.g., PgBouncer or equivalent), or is the app opening/closing raw connections per request?
- [ ] Are slow queries logged and monitored (`pg_stat_statements`, `auto_explain`), or is performance only noticed anecdotally?

**What "good" looks like:** Query patterns are observable (logged, monitored), predictable in cost, and pagination/transaction scope match actual usage patterns.

---

## 6. Data Quality & Integrity

- [ ] What percentage of rows have null/empty values in fields expected to be populated?
- [ ] Are there malformed JSONB entries (wrong types, unexpected nesting, empty objects where data was expected)?
- [ ] Are there orphaned foreign key references (soft-deleted parents, missing referential integrity)?
- [ ] Are there duplicate records that should be unique (missing unique constraints allowing drift)?
- [ ] Is there a discrepancy between "what the schema allows" and "what the data actually contains" — evidence the schema isn't being enforced in practice?
- [ ] Are timestamps/audit columns (`created_at`, `updated_at`) consistently populated and reliable for change tracking?
- [ ] *(Added from a client audit SOP, 2026-08-03)* Is there CHECK-constraint or lookup-table coverage for low-cardinality text columns that look like they're standing in for an enum (orphaned/inconsistent enum-like free text)?
- [ ] *(SOP)* Are status/flag-shaped required columns relying on the application layer to supply a default instead of a database-level `DEFAULT`?
- [ ] *(SOP)* Sampling actual rows: do any already violate a declared-but-unvalidated foreign key relationship?

**Explicitly deferred, not designed:** cross-table consistency checks (e.g. a stored `total_price` that should equal `qty * unit_price`) and conflicting data across related tables are genuinely open-ended and client-specific — no generic way to express an arbitrary business formula without per-engagement configuration this tool doesn't yet have a format for.

**What "good" looks like:** Constraints in the schema reflect and enforce the actual rules of the business data — data quality is a schema property, not an ongoing cleanup task.

---

## 6a. Semantic Duplicate Detection

Added from a client audit SOP (2026-08-03) — distinct from `SELECT DISTINCT`-style exact-duplicate detection (already covered elsewhere): the target here is records that are technically unique rows (different primary key, different SKU) but represent the same real-world entity. Requires a per-engagement identity-fingerprint config (`--duplicate-fingerprint-config`, see `examples/duplicate_fingerprint.example.toml`) defining what makes two rows "the same" for this client's data — this category is N/A without one, never guessed.

- [ ] Do any rows share an identical normalized identity fingerprint (the same real-world product, entered more than once)?
- [ ] Do any rows look like the same real-world entity despite non-identical formatting (near-duplicates — a typo, a unit-format difference, an abbreviation)?

**Current scope:** normalization is limited to simple string cleanup (case, whitespace, digit/alphanumeric extraction) — not true semantic or unit normalization ("1/4 in" == "0.25in" == "6.35mm" isn't a fixed-regex problem). Vendor "dictionaries" mapping product names, naming conventions, and measurement units onto a canonical form are planned future work — noted as a strong candidate for an LLM-agent-based approach rather than a purely algorithmic one.

**Human-in-the-loop by design:** exact-match findings are reported directly (the fingerprint rule itself was already human-approved when the config was authored). Fuzzy-match candidates (`pg_trgm` similarity) require interactive confirmation before they're reported as real findings — false positives are expected from a statistical text-similarity signal, and reporting them unconfirmed would damage audit credibility. A non-interactive run ships candidates clearly marked as requiring manual attestation rather than silently dropping or silently confirming them.

**What "good" looks like:** Duplicate/near-duplicate records are identified and resolved (merged or linked) before they fragment inventory, reporting, or reorder logic — quantified by row count and estimated downstream impact, not just flagged as a technical curiosity.

---

## 7. Scale & Growth Readiness

- [ ] At current row counts, are there any operations already showing degraded performance (not hypothetical — measured)?
- [ ] Is table/index size growth tracked, and is there a stated volume threshold where the current architecture will need to change (e.g., partitioning, read replicas)?
- [ ] For multi-tenant or multi-category systems: does the architecture isolate tenant/category data access patterns, or do queries risk scanning across irrelevant partitions of the data?

**What "good" looks like:** Current performance is measured (not assumed), and there's a documented understanding of what will need to change and at what scale — even if that work isn't being done now.

---

## 7a. Storage Health & Maintenance

Added from a client audit SOP (2026-08-03) — table/index bloat and vacuum health are a distinct concern from growth trajectory, not a subset of it, so this is its own category rather than more bullets under Scale & Growth Readiness. Autovacuum-tuning and TOAST-overhead bullets formerly listed under Scale & Growth Readiness (above) live here now.

- [ ] Is table bloat within a healthy range, measured directly (via the `pgstattuple` extension) where possible rather than only estimated?
- [ ] Is B-tree index bloat within a healthy range?
- [ ] Is any index larger than the table it indexes — a red flag worth its own line item regardless of cause?
- [ ] Are large values (JSONB, text, or bytea) causing TOAST-related overhead on frequently-accessed rows?
- [ ] Is TOAST storage strategy (EXTENDED vs. EXTERNAL) appropriate for the column's actual access pattern?
- [ ] Is autovacuum explicitly disabled on any table, as opposed to merely left at defaults?
- [ ] Is a long-running transaction or an abandoned/stalled replication slot holding back the xmin horizon cluster-wide — the common root cause of "why is everything bloated"?

**What "good" looks like:** Bloat is measured, not guessed at; autovacuum is tuned deliberately per table rather than left at defaults or silently disabled; nothing is quietly holding back vacuum cluster-wide.

---

## 8. Security & Access Boundaries

- [ ] Are database roles scoped by least privilege (read-only reporting roles, app roles without superuser, no shared "one login for everything")? *(SOP: also covers superuser roles with no connection limit set — service-account/shared-credential sprawl amplification.)*
- [ ] Is row-level security in use where multi-tenant isolation is required, or is isolation enforced only in application logic? *(SOP: also covers RLS enabled with policies attached but `FORCE ROW LEVEL SECURITY` not set — policies exist but silently don't apply to the table owner.)*
- [ ] Are secrets (connection strings, credentials) stored outside version control and application code?
- [ ] Is sensitive data (PII, payment info) flagged, and encrypted in transit appropriately? *(SOP: also covers `PUBLIC` grants on tables with a PII-shaped column.)*
- [ ] Are audit logs available for who changed what, or is change history unrecoverable?
- [ ] Are elevated or temporary access grants (contractor access, incident response, one-off admin tasks) time-boxed with automatic expiration, or granted indefinitely and relied on someone remembering to revoke?
- [ ] Is there a documented, signed-off authentication & access-control policy, with a named owner (DBA/IT/security contact), or is access governed by informal/undocumented practice?
- [ ] Is there a defined process for detecting and revoking unauthorized access (a compromised credential, an unexpected login), or does that depend on someone noticing by chance?
- [ ] Is there a documented offboarding process that revokes database access when someone with access leaves the company or changes roles?
- [ ] Are secrets/passwords rotated on a defined schedule, and is multi-factor authentication enforced for privileged/human access?
- [ ] Is the database encrypted at rest?

**What "good" looks like:** Access is least-privilege by default, temporary/elevated access expires automatically rather than depending on manual revocation, and the audit trail exists independent of trusting application-layer discipline.

**Scope note:** The first six bullets above are verified directly — the tool reads them from the database itself, no sign-off needed. The last five are confirmed by **attestation**: the client/DBA signs off that each is in place. The tool can't see encryption at rest, a rotation schedule, MFA enforcement, or a policy document from inside Postgres — none of that leaves a trace in the database's own catalogs — but each is still core database security posture, so it stays on the checklist rather than being silently dropped. In plain terms: if it's queryable, it's verified and reported; if it isn't but still matters, it's asked for and the answer (or its absence) is recorded — never independently tested. Authentication/authorization *architecture* (identity provider design, role-hierarchy redesign) is a different matter entirely and is not part of this checklist — see "Explicitly Out of Scope: Network & Authentication Testing" below.

### 8a. Authentication Method Strength

Added from a client audit SOP (2026-08-03) — doesn't map to any bullet above, so it's a fresh addition rather than an extension of bullet 3 (which asks where secrets/config *live*, a genuinely different question from how strong the *configured authentication itself* is).

- [ ] Does `pg_hba.conf` allow `trust` (no authentication at all) or cleartext-capable `password` authentication for any rule?
- [ ] Is `password_encryption` set to `scram-sha-256` rather than the legacy `md5`?

**Access note:** `pg_hba_file_rules` (the catalog view backing the first bullet) is restricted to superuser by default — confirmed empirically that granting `pg_read_all_settings` or even the broad `pg_monitor` role does not unlock it. A read-only audit connection will commonly hit this privilege gap rather than the happy path; the tool reports that gap explicitly rather than silently skipping the check.

---

## 9. Backup, Recovery & Change Management

- [ ] Are backups automated, tested (restore drills, not just "backup exists"), and retained per a defined policy?
- [ ] Is there a documented recovery time objective (RTO) and recovery point objective (RPO), and does current backup cadence actually meet them?
- [ ] Are schema changes (migrations) version-controlled and applied through a repeatable process, or run manually against production?
- [ ] Is there a staging/replica environment that mirrors production closely enough for migration testing to be meaningful?

**What "good" looks like:** Recovery has been tested, not just configured, and schema changes follow a repeatable, reviewable process.

---

## 10. Monitoring & Observability

- [ ] Is `pg_stat_statements` (or equivalent) enabled and actually reviewed?
- [ ] Are there alerts on connection saturation, replication lag, disk usage, and long-running queries?
- [ ] Is index bloat / table bloat monitored, with a maintenance plan (e.g., scheduled `VACUUM FULL` or `pg_repack` where needed)?
- [ ] Is there visibility into query performance trends over time, or only point-in-time snapshots when something breaks?

**What "good" looks like:** Problems are caught by monitoring before they're reported by users.

---

## 11. Documentation & Institutional Knowledge

- [ ] Is the schema documented anywhere outside the schema itself (ERD, data dictionary, README)?
- [ ] Is there a record of *why* key architectural decisions were made (e.g., why JSONB was chosen for a given column), or is that knowledge only in someone's head?
- [ ] Would a new engineer be able to understand the intended structure of JSONB attributes without reverse-engineering it from production data?
- [ ] Is there a change log or migration history that's legible as a narrative, not just a list of diffs?

**What "good" looks like:** The system is legible to someone who didn't build it — which is the actual test of low cognitive load.

---

## 12. Compliance & Data Privacy

- [ ] Are data subject rights supported in practice — access, rectification, deletion/"right to be forgotten," and portability — not just described in a policy document?
- [ ] Is there a documented legal basis / consent record for processing personal data, and is consent (where required) actually tracked at the record level, not assumed?
- [ ] Is there a data retention and minimization policy, and is it enforced (data actually deleted/anonymized on schedule) rather than retained indefinitely by default?
- [ ] If personal data crosses borders (e.g., EU/UK residents' data processed or stored outside the EU/UK), are appropriate transfer safeguards in place (Standard Contractual Clauses or equivalent)?
- [ ] Is there a breach notification process with a defined timeline (GDPR requires notifying supervisory authorities within 72 hours of awareness), and has it been rehearsed rather than just written down?
- [ ] Where SOC2 applies (or is a stated goal), are existing controls mapped to the relevant Trust Services Criteria (security, availability, processing integrity, confidentiality, privacy), with gaps identified rather than assumed covered?
- [ ] Are data processing agreements (DPAs) in place with vendors/subprocessors who touch personal data (e.g., cloud hosting, email providers, analytics)?

**What "good" looks like:** Data-subject rights are operationally exercisable (someone could actually fulfill a deletion request today), retention limits are enforced rather than aspirational, and there's a clear map from GDPR/CCPA obligations and (where applicable) SOC2 criteria to the specific controls that satisfy each one.

**Scope note:** This category is almost entirely **manual-confirmation / human-verified** — a read-only database connection can surface supporting signals (PII column detection, encryption-at-rest signals, RLS presence) but cannot confirm legal basis, consent records, DPAs, or breach-notification readiness on its own. Name it explicitly rather than omitting it, the same way this rubric already handles other out-of-scope items, and expect the first pass to be a human/legal review, not tool output. GDPR compliance covers most of the substance of current US state privacy laws (CCPA/CPRA and similar), which are generally less stringent — but confirm applicability per statute rather than assuming blanket coverage, especially as more states pass their own laws.

---

## Explicitly Out of Scope: Network & Authentication Testing

**This is a database audit — it reads a database with credentials already granted for that purpose. It is not a penetration test, and it does not test, attack, or attempt to defeat any authentication or network control.** The items below are permanently excluded, not because they don't matter, but because testing them requires a different kind of engagement — different authorization, different tooling, different insurance/liability coverage — than reading a database with credentials the client already gave us.

- **Network & infrastructure security** — network access, port scanning, firewall/VPN/bastion configuration, exposed-service enumeration, OS/host-level hardening, or any penetration testing of hosts or infrastructure.
- **Authentication attacks** — brute-force, credential-stuffing, password-spraying, or any attempt to defeat a login, session, or MFA/SSO mechanism.
- **Application/API authentication logic** — reviewing or testing login flows, session/cookie handling, or API auth (JWTs, API keys, middleware) sitting in front of the database.
- **Authentication/authorization architecture design** — identity provider setup, federation, or role-hierarchy redesign. If a gap is evident from Category 8's attestation checklist or elsewhere, it's named as a single finding ("access control design has gaps, recommend a dedicated review") — not audited in depth or fixed here.

**Why this boundary exists, in plain terms:** Attempting to break into a login, a network, or an identity system — even to test it — is a fundamentally different kind of work than reading a database with credentials you've already given us. Doing it without its own separate written authorization would look like unauthorized security testing regardless of intent, and would expose both sides to risk neither party signed up for. If any of this is ever needed, it should be scoped, authorized, and priced as its own engagement — not folded into a database audit.

---

## Report Structure Template

```
1. Executive Summary (1 page max)
   - Overall health assessment
   - Top 3-5 findings by severity
   - Recommended next steps (remediation scoping, not remediation itself)

2. Findings Summary Table
   | # | Category | Finding | Severity | Business Impact |

3. Detailed Findings (per category, per checklist above)
   - Observation
   - Evidence (query plans, row counts, examples — sanitized if needed)
   - Business impact
   - Recommended direction (not implementation detail)

4. Out of Scope / Not Assessed
   - Explicitly name what wasn't covered (app-layer code, infra outside DB, etc.)

5. Suggested Remediation Phases
   - Phase 1: Critical/High severity, low-risk additive changes (new indexes, registry tables)
   - Phase 2: Medium severity, structural changes requiring migration/testing
   - Phase 3: Long-term/scale-readiness items
```

---

## Notes for Reuse

- Treat the checklist items as prompts, not a rigid script — adapt depth to what the client's system actually contains (e.g., skip full-text search section entirely if none exists).
- Keep the audit phase read-only and clearly bounded; this rubric assumes no write access during assessment.
- Severity should reflect *business* impact, not just technical deviation from best practice — a "Low" technical issue that's costing a client real search accuracy should be scored higher.
