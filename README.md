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

Requires [`uv`](https://docs.astral.sh/uv/) and Python 3.11+ (uv provisions the interpreter automatically). Optionally, [Pandoc](https://pandoc.org/) plus a PDF engine (a LaTeX distribution like MiKTeX/TeX Live, or `wkhtmltopdf`) for PDF report generation — the tool works fine without either, it just skips the PDF step with a clear notice.

**Getting Pandoc + MiKTeX actually working on Windows** (both installed via `winget install --id=JohnMacFarlane.Pandoc` / `winget install --id=MiKTeX.MiKTeX`) took two extra fixes beyond installing them, worth knowing if PDF generation mysteriously fails even with both "installed":
- **MiKTeX's winget package doesn't add its `bin\x64` directory to PATH.** Add it yourself (`[Environment]::SetEnvironmentVariable("Path", $oldPath + ";C:\...\MiKTeX\miktex\bin\x64", "User")`), or `pdflatex` simply won't be found.
- **MiKTeX Basic ships without most LaTeX packages** — they're meant to be fetched on first use, but that requires an interactive prompt, which never happens when pdflatex runs non-interactively (as Pandoc always invokes it), so the very first PDF fails on something like `! LaTeX Error: File 'footnote.sty' not found.` and hangs waiting for input. Fix once: `initexmf --set-config-value=[MPM]AutoInstall=1`.
- **A real, pre-existing, unrelated PATH bug on this machine** caused a much stranger failure first: `C:\Program Files\Git\bin\bash.exe` (a *file*) was listed as a literal PATH *entry*, rather than `C:\Program Files\Git\bin` (the directory). Windows PATH entries must be directories, so this entry was already inert for normal command resolution — but MiKTeX's one-time format-file build walks PATH expecting only directories and crashed hard on it (`GetFileAttributesW` error 267, "the directory name is invalid"), taking every PDF conversion down with it. Removing the malformed entry fixed it; if you ever see MiKTeX failing over a `...bash.exe\` path, check for exactly this.

```bash
uv sync --group dev            # install runtime + dev dependencies

uv run integri-audit list-checks              # list every check id + description, no DB connection needed
uv run integri-audit list-checks -c 3          # ...limited to one category

uv run integri-audit run --dsn "postgresql://user:pass@host:5432/dbname"
uv run integri-audit run --dsn "$INTEGRI_DSN" -c 3 -c 6      # limit to specific rubric category numbers
uv run integri-audit run --dsn "$INTEGRI_DSN" -k 01.04 -k 03.02   # limit to specific check ids
uv run integri-audit run --dsn "$INTEGRI_DSN" --output report.md --no-pdf   # explicit path, Markdown only
```

The DSN can also be supplied via the `INTEGRI_DSN` environment variable instead of `--dsn`. The tool connects read-only and never writes to the audited database.

By default `run` writes `reports/audit-<timestamp>.md` (and a matching `.pdf` if Pandoc + a PDF engine are available) instead of printing to stdout — `--output <path>` overrides where the Markdown goes. A live progress UI (readiness message per category, a progress bar per check, green ✓ / red ✗, an `<alias> completed` line once each category finishes, errors additionally logged to `logs/audit-<timestamp>.log`) is on by default when stderr is a terminal, off otherwise (redirected output, cron, CI) — override either way with `--progress`/`--no-progress`. All of this status output goes to **stderr**; the report itself only ever goes to the file (or, historically, stdout) — `... > /dev/null` never clips the report.

The report file itself is written incrementally, not all at once at the end: it's created as soon as the first category finishes and grows in place as each subsequent category completes (`ia-schema completed` → file appears with category 1's findings → `ia-jsonb completed` → same file now also has category 2's → ...), so it's readable mid-run rather than only after the whole audit finishes. The overall status sequence is: per-category completion lines, then `Audit complete.` once every category is done, then `Generating report.` / `Generated report complete.` bracketing the final authoritative write (executive summary, findings table, and remediation phases all need the complete picture, so that last write recomputes and overwrites the same file one more time — it's the only one that's fully correct start to finish).

Auto-detection also treats Git Bash/MSYS2 as a terminal even when it isn't (checking the `MSYSTEM` env var as a fallback) — `mintty`, Git Bash's terminal emulator, reports `isatty() == False` to Python even in a genuinely interactive session, which would otherwise silently disable the progress UI for exactly the shell this tool is meant to be run from day to day.

For running individual checks by hand repeatedly (e.g. validating against a real client database before scripting a full unattended run), thin Bash wrappers live in `scripts/`:

```bash
export INTEGRI_DSN="postgresql://user:pass@host:5432/dbname"
scripts/list-checks.sh -c 1        # what's available in category 1
scripts/run-check.sh 01.04         # run just that one check
scripts/run-category.sh 1          # run every check in category 1
```
Each forwards any extra arguments to `integri-audit run`, so `--dsn`/`--output`/etc. still work to override `$INTEGRI_DSN`. There's deliberately no "run everything unattended" script yet — that's later work, once individual checks have been manually exercised enough to trust automating them.

For quicker manual runs, `scripts/aliases.sh` defines a terse, category-relevant alias per rubric category (`ia-schema`, `ia-jsonb`, `ia-index`, `ia-fts`, `ia-query`, `ia-quality`, `ia-scale`, `ia-sec`, `ia-backup`, `ia-mon`, `ia-docs`) — each just forwards to `run-category.sh <N>` (and any extra args, e.g. `ia-sec --no-pdf`). Unlike the scripts above, this file must be **sourced**, not executed, since `alias` only affects the current shell:

```bash
source scripts/aliases.sh                                       # for the current shell session
echo 'source /path/to/integri-audit-tool/scripts/aliases.sh' >> ~/.bashrc   # to make them permanent
```

Run `ia --help` any time to list them all without leaving the CLI:

```
Integri Audit Tool — per-category aliases (each forwards extra args to 'integri-audit run')

  Alias       Category
  -----       --------
  ia-schema   1. Schema Design & Normalization Boundaries
  ia-jsonb    2. JSONB Structure & Governance
  ia-index    3. Indexing Strategy
  ia-fts      4. Full-Text & Structured Search Behavior
  ia-query    5. Query Patterns & Application Interaction
  ia-quality  6. Data Quality & Integrity
  ia-scale    7. Scale & Growth Readiness
  ia-sec      8. Security & Access Boundaries
  ia-backup   9. Backup, Recovery & Change Management
  ia-mon      10. Monitoring & Observability
  ia-docs     11. Documentation & Institutional Knowledge

  ia-db-up    Set up/reuse the synthetic test database
  ia-db-down  Tear down the synthetic test database
```

### Running a full client audit: `ia run`

`ia run` (or `./scripts/run-audit.sh` directly) is the entry point for an actual client-facing audit, not just manual check exploration. It prompts for the client's business name and names the report after it plus a unique timestamp-based id — `reports/<slugified-business-name>-<id>.md` — specifically so a report can never be ambiguous about which client it's for, and re-running for the same client never overwrites a prior report:

```bash
export INTEGRI_DSN="postgresql://user:pass@host:5432/dbname"
ia run
Client's business name: Acme Test Co
# -> reports/acme-test-co-20260723120044.md
```

Any extra arguments (`--no-pdf`, `-c`/`-k` filters, etc.) forward to `integri-audit run` the same as every other wrapper script here.

### Trying it out against a synthetic database

`scripts/setup-synthetic-db.sh` spins up a persistent, local Postgres container (`integri-synthetic-db`, port 55432) seeded from `scripts/synthetic-db/seed.sql` with a deliberately messy, client-shaped schema — a `customers`/`orders`/`products`/`sessions` set of tables that intentionally reproduces a specific rubric anti-pattern per bullet (an FK-shaped column with no constraint, JSONB key/type drift, an unused index, a table with no primary key, RLS enabled with zero policies, an unvalidated FK, TOASTed JSONB, dead-tuple bloat with autovacuum disabled, and more), plus a burst of generated query traffic so the `pg_stat_statements`-backed checks (N+1 candidates, OFFSET pagination, slow queries) have something real to find too. It's meant for exercising checks by hand, repeatedly, without needing a real client database:

```bash
./scripts/setup-synthetic-db.sh              # create if missing, else reuse as-is
./scripts/setup-synthetic-db.sh --recreate   # wipe and rebuild from scratch
# or: ia-db-up

export INTEGRI_DSN="postgresql://postgres:synthetic@localhost:55432/synthetic_client"
ia-schema            # or any other ia-* alias / run-check.sh / run-category.sh

./scripts/teardown-synthetic-db.sh   # or: ia-db-down
```

A full run against it currently surfaces genuine findings in every automated category (1–11) — confirmed via manual CLI runs, not just design intent. One gotcha it exists to document: the seeded `sessions` table needs its dead-tuple bloat (07.04/10.03) to survive until an audit actually runs, but Postgres's own autovacuum daemon was cleaning it up within its default ~1-minute naptime before a manual audit got around to it, making those two findings flaky. Fixed by starting the container with `-c autovacuum=off` cluster-wide — deliberately not a per-table `reloptions` override, since 07.04 specifically requires `reloptions IS NULL` to fire (it's checking for bloat on cluster-wide defaults, not a tuned-and-still-struggling table).

Run the tests:

```bash
uv run pytest                  # unit tests (fast, no DB required)
uv run pytest -m integration   # + integration tests against a real Postgres (requires Docker)
```

## Architecture

- **Core** (`src/integri_audit_tool/`) — CLI entrypoint (`cli.py`), read-only DB connection handling (`db.py`), the `Finding`/`Severity`/`AuditReport` data model (`models.py`), dynamic category discovery (`registry.py`), audit orchestration (`runner.py`), and the Markdown report renderer (`report/markdown.py`).
- **Categories** (`src/integri_audit_tool/categories/`) — one package per rubric category, folder-named to mirror the rubric heading (e.g. `03_indexing_strategy` ↔ rubric section "3. Indexing Strategy"). Each exports a `CATEGORY` object the registry discovers automatically — no central list to maintain. Default granularity is one function per rubric checklist bullet; a category only gets extra files (e.g. splitting `queries.py` raw SQL from `checks.py` interpretation logic) when it's complex enough to need it.
- Category folders start with a zero-padded number and are therefore not valid Python identifiers as literal `import` targets — this is intentional and safe, since they're only ever loaded dynamically via `importlib` (see `registry.py`), the same pattern Django uses for migration files (`0001_initial.py`).
- **Live progress UI + per-check CLI selection + PDF export** are a deliberate case study in keeping a feature "not core": `reporter.py` defines an `AuditReporter` Protocol (category/check start/success/failure/complete hooks, plus `category_completed` — fired once per category regardless of outcome, the one hook every reporter below actually needs) and a `NullReporter` no-op default — `runner.py` calls these hooks but never imports anything presentation-related, so every existing test that calls `run_audit()` without a `reporter` argument is untouched. The actual colors/progress-bars/error-logging implementation (`cli_progress_reporter.py`, using `rich`) and PDF conversion (`pdf_export.py`, shelling out to `pandoc` — a system binary, not a Python dependency, since it has no PDF renderer of its own without a separately-installed engine) live entirely outside core; swapping in a different `AuditReporter` (a JSON-lines one for CI, say) never touches `runner.py`. `AuditConfig.check_filter` extends the existing `category_filter` pattern one level down, to individual check ids (`-k 01.04`), backing `scripts/run-check.sh`/`run-category.sh` — thin Bash wrappers, since that's the shell the tool is meant to be driven from day to day.
  - Two reporters now run side by side on every `run`, combined via `reporter.py`'s `CompositeReporter` (fans every call out to a list of reporters — neither needs to know the other exists): `CliProgressReporter` (optional, terminal-only) and `cli.py`'s `_IncrementalReportWriter` (always on, regardless of `--progress`), which re-renders and overwrites the same report path after every `category_completed` call so the file exists and grows from the first finished category onward, rather than only appearing once the whole audit is done. It deliberately doesn't try to be a true single-pass append — the executive summary, findings table, and remediation phases all need every category's results to compute correctly, so `cli.py` still does one more authoritative `render()` + write after `run_audit()` returns, using the complete `AuditReport` (with correct out-of-scope notes, which the incremental writer omits since they're not fully known until the run finishes). Mid-run reads of the file are honest partial snapshots; only the final write is guaranteed complete.
  - Two real bugs found via live testing, not unit tests (which don't render anything real): (1) Windows consoles often don't default stdout/stderr to UTF-8, so the ✓/✗/em-dashes this feature prints came back as literal escaped text or mangled replacement characters — fixed by reconfiguring both streams to UTF-8 at the top of `cli.py`, before any `rich.Console` is constructed against them. (2) Running a single check via `--check` still announced (and drew an empty 0/N progress bar for) every *other* category, since `category_ready` fired unconditionally — fixed by computing which checks actually match the filter *before* deciding whether to announce a category at all, and skipping categories that contribute nothing under the filter without even evaluating their `applicability()` (avoids a wasted DB round-trip for a category that was never going to run anything).
- **All 11 automatable rubric categories are now implemented**, each covered by unit tests, live-Postgres integration tests, and a manual CLI run: **Schema Design & Normalization Boundaries** (category 1, 3 of 6 bullets), **JSONB Structure & Governance** (category 2, 3 of 6), **Indexing Strategy** (category 3, 3 of 7), **Full-Text & Structured Search Behavior** (category 4, 5 of 6), **Query Patterns & Application Interaction** (category 5, 4 of 6), **Data Quality & Integrity** (category 6, 5 of 6), **Scale & Growth Readiness** (category 7, 5 of 5 — the only category with zero deferred/out-of-scope bullets), **Security & Access Boundaries** (category 8, 5 of 6), **Backup, Recovery & Change Management** (category 9, 4 of 4), **Monitoring & Observability** (category 10, 3 of 4), and **Documentation & Institutional Knowledge** (category 11, 3 of 4). Category 12 (Compliance & Data Privacy) was out of scope by design from the start (see README intro). Next work on this tool is either filling in each category's remaining deferred bullets, or moving on to something beyond the rubric's 12 categories.
- Category 11 closes a loop left open in category 2: 02.01 (a governing schema/registry for JSONB keys) was deferred there as follow-up work; category 11's 11.03 is that follow-up, asked from the institutional-knowledge angle instead — same underlying signal (a heuristically-named registry table), different rubric bullet. 11.02 is deliberately broader than category 8's 08.04 (which only checks PII-*named* columns for missing comments): 11.02 checks *every* JSONB column, since the rubric bullet here is about documenting an architectural choice (why JSONB), not flagging sensitive data.
- Category 10's 10.02 check ("alerts on connection saturation, replication lag, disk usage, and long-running queries") is narrowed to two of those four: current connection count vs `max_connections`, and currently-active queries past a duration threshold — both real, current-state signals, escalating to High at higher severity thresholds. Disk usage isn't visible to Postgres at all (OS-level), and replication lag only matters if replicas are connected, which category 9's 09.04 already reports on. 10.03 (bloat monitored with a maintenance plan) is deliberately distinct from category 7's 07.04: 07.04 flags bloat + no per-table autovacuum *configuration*, while 10.03 flags bloat + no vacuum *activity* recorded recently — a table can be perfectly configured and still show 10.03 if autovacuum is failing or starved cluster-wide, so the two catch different failure modes on the same underlying `pg_stat_user_tables` data.
- Testing 10.02's long-running-query detection needed real concurrency, not just canned data: the production threshold is 5 minutes, far too long to wait out in a test. `fetch_long_running_active_queries` took an optional `min_duration` parameter (default: the real threshold) so the integration test could pass `timedelta(0)` and catch a `pg_sleep(3)` query run on a background thread almost immediately, instead of needing to fake elapsed time.
- Category 9 is the most process-heavy category yet — most of what it asks (tested restores, a documented RTO/RPO, a retention policy, whether staging mirrors production closely enough to matter) is external tooling/process invisible to a DB connection. Rather than force weak heuristics into hard verdicts, most of its checks surface honest partial evidence instead: `pg_stat_archiver` for WAL archiving health (09.01 is the one check with real teeth — an *actively* failing `archive_command` is a concrete, current problem, escalated to High; historical-only failures stay Medium), 09.02 always emits one Informational finding with the last-successful-archive timestamp regardless of whether anything's wrong (so an auditor has a concrete number to compare against a documented RPO once one exists — same "always report status" pattern as 07.02's largest-tables check), a heuristic table-name match against ~10 common migration tools' tracking tables (Flyway, Django, Alembic, Rails, Knex, Prisma, EF Core, Goose, Sequelize) for 09.03, and `pg_stat_replication` row count for 09.04. None of the four claim to fully answer their rubric bullet — evidence text says so explicitly in each.
- Category 8's 08.02 ("is RLS in use where multi-tenant isolation is required") looks like a duplicate of category 7's 07.03 ("tenant-shaped columns without RLS enabled"), but they check different failure modes rather than repeating the same query: 07.03 finds tables that never turned RLS on at all; 08.02 finds tables where RLS *is* enabled but has zero policies attached (a common "ran ENABLE ROW LEVEL SECURITY, forgot CREATE POLICY" misconfiguration). Worth remembering as precedent for other rubric bullets that read as near-duplicates across categories — a different query, not a repeated one.
- Category 7's 07.05 check (large JSONB causing TOAST overhead) went through a real redesign mid-implementation, caught by integration testing: the first version used `pg_stats.avg_width` to spot "large" JSONB values, on the assumption a big average width means big stored values. That's backwards for exactly the rows that matter — once a value is large enough to actually get TOASTed out-of-line, the in-row datum ANALYZE measures shrinks to a TOAST pointer (~18 bytes) or a compressed blob, so avg_width goes *down*, not up, precisely when out-of-line storage is happening. Confirmed empirically: `repeat('x', 3000)` (highly compressible) produced `avg_width` of 70, and even genuinely random 3.2KB values came back at 18 (external TOAST pointer). Replaced with a direct measurement — `pg_total_relation_size()` on the table's own TOAST relation (`pg_class.reltoastrelid`) — which isn't fooled by compression or externalization since it measures actual bytes stored, not an inferred-from-a-sample column statistic.
- Category 6 introduces a third data source, cheaper than the other two: instead of scanning row data (category 2's approach) or reading `pg_stat_statements` (categories 4/5), most of its checks read `pg_stats`/`pg_stat_user_tables` — planner statistics Postgres already collects via `ANALYZE`. Reading them is as cheap and catalog-only as categories 1/3, at the cost of being *estimates from a sample*, not exhaustive counts, and being entirely absent for a table that's never been analyzed (a real gotcha for the integration tests — see below). 06.01 (high null fraction) and 06.05 (nullable column that's never actually null) are literally opposite readings of the same `null_frac` data, sharing one query. 06.04's near-uniqueness check has to branch in Python (not SQL) on `pg_stats.n_distinct`'s sign: positive is an absolute distinct-value count, negative is *minus* the fraction of rows that are distinct (e.g. `-1` means "every row distinct").
- Category 4's first two checks (04.01/04.02) are catalog-only. Its other three bullets (04.03 combining structured+free-text filters, 04.04 relevance ranking, 04.05 safe query parsing) describe *application query* behavior, invisible to schema metadata — but they leave a trace in `pg_stat_statements` (if installed), which logs the actual normalized SQL text the app has run. Querying it is a plain read-only `SELECT`, exactly as safe as everything else this tool does (see `db.py`'s enforced `TRANSACTION READ ONLY`, which makes Postgres itself reject any write regardless of what SQL a check builds). Each of these three checks degrades to an Informational finding, not an error, when the extension isn't installed — verified against both a database with it enabled and one without.
- Testing `pg_stat_statements` needed one infrastructure change: it can only be loaded via `shared_preload_libraries` at server start, not `CREATE EXTENSION` alone. `tests/integration/conftest.py`'s `postgres_container` fixture now starts the container with `PostgresContainer(...).with_command("postgres -c shared_preload_libraries=pg_stat_statements -c pg_stat_statements.track=all")` — harmless for every other category's tests, confirmed by re-running the full integration suite after the change.
- `CategoryModule.out_of_scope` (`registry.py`) declares rubric bullets a category can *never* assess via a read-only DB connection — distinct from bullets that are just "not yet implemented." Category 4's 04.06 (facets generated from governed attributes vs hardcoded) is the first user: pure UI/frontend logic, unreachable no matter how much SQL introspection this tool grows. These notes are folded into `AuditReport.out_of_scope` alongside the static category-12 note, and — like category 12's note — always shown regardless of `--category` filtering, since they're permanent properties of the tool, not of a given run. Verified with a CLI run limited to `-c 1` that still shows category 4's 04.06 note.
- Categories 1 and 3 only need catalog metadata (`information_schema`, `pg_*` catalogs). Category 2 is the first to need actual row *data* (JSONB keys and value types live inside the documents, not the catalog) — its `queries.py` builds per-column SQL with `psycopg.sql.Identifier` for safe interpolation and runs against a bounded row sample (`SAMPLE_ROW_LIMIT`) rather than scanning whole tables.
- Category 2 is also the first to use `CategoryModule.applicability` for real: a database with zero JSONB columns marks the whole category N/A in the report rather than a clean pass, per the rubric's own "skip full-text search entirely if none exists" guidance. Verified against a live JSONB-free database, not just unit-tested.
- Category 5 mixes two kinds of checks: 05.01 (N+1 candidates) and 05.03 (OFFSET pagination) lean on `pg_stat_statements`, same as category 4, degrading to Informational if it's not installed. 05.04 (idle-in-transaction sessions, via `pg_stat_activity`) and 05.06 (slow-query monitoring presence, via `pg_settings`/`pg_extension`) need no extension at all — always available on any Postgres. It's also the first category with two `out_of_scope` bullets from a single category: 05.02 (parameterized vs concatenated queries) turns out to have the *same* fundamental limitation as tsquery in category 4 — pg_stat_statements normalizes literal constants into placeholders based on the parsed query tree, regardless of whether they arrived as a bind parameter or were concatenated into the SQL text before being sent, so the two produce identical stored query text. 05.05 (connection pooling configured vs raw per-request connections) has no reliable single-snapshot signal either.
- Real bugs worth remembering, all caught by integration tests rather than the mocked-cursor unit tests (which hand back already-parsed Python data, so they can't catch decoding or self-referential issues) — this is exactly why queries.py has its own integration coverage separate from checks.py's unit tests:
  - `information_schema.columns` fields (`column_name`, `data_type`, etc.) are Postgres *domain* types (`sql_identifier`, `character_data`), not plain `text`/`varchar`. `array_agg()` over a domain-typed column produces an array whose element OID psycopg has no decoder for, so it silently comes back as an undecoded wire string instead of a Python list (iterating it then yields characters, not list items) — cast to `::text` before aggregating.
  - `lower(column_name)` alone doesn't normalize snake_case vs camelCase (`lower('created_at')` = `'created_at'`, `lower('createdAt')` = `'createdat'` — different strings). Strip underscores too (`lower(replace(column_name, '_', ''))`) if the goal is catching naming-convention drift between the two styles.
  - **Self-pollution via pg_stat_statements**: category 5's OFFSET-pagination query originally aliased a column `offset_statement_count`. Once that query itself ran and got recorded in `pg_stat_statements`, its own stored query text — including the alias — matched its own `ILIKE '%OFFSET%'` filter on the next run, polluting the "example queries" evidence with the tool's own introspection SQL instead of real application queries. Caught via a manual CLI smoke test against a live database, not the integration suite (which uses fresh per-test tables but the same long-lived `pg_stat_statements` accumulator, so a single test run doesn't naturally re-trigger a query enough times to notice). Any `pg_stat_statements`-based check needs its own SQL text to avoid containing the substring it searches for — worth checking for on every new one of these checks, not just this one. Fixed by renaming to `matched_statement_count`.
  - Named psycopg parameters (`%(name)s`) and literal `%` in `ILIKE '%word%'` patterns don't mix without escaping: once you pass a params dict to `cur.execute()`, psycopg parses the whole query for placeholders, and any literal `%` not part of one must be doubled (`%%word%%`) or it's misparsed. Queries executed with **no** params dict skip this entirely — several existing queries rely on that already. Only `fetch_n_plus_one_candidates` (which parameterizes the call-count threshold) needed the escaping.
  - Not a bug so much as a required habit for anything reading `pg_stats` (category 6): the view is only populated by `ANALYZE`, so every integration test that creates a table and inserts rows has to explicitly `ANALYZE` it afterward — without that, the table simply doesn't appear in `pg_stats` at all (not zero rows, no rows), and a check silently finds nothing rather than erroring.
- Category 12 (Compliance & Data Privacy) is never a discovered module — it's a static "out of scope" note the report renderer always includes.

## Notes

This README doubles as the running notebook for this project — architecture decisions, gotchas, and other context worth preserving belong here as the tool develops.
