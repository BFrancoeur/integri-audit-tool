"""Rubric category 11: Documentation & Institutional Knowledge.

3 of the rubric's 4 checklist bullets are implemented, all reading
pg_description (COMMENT ON TABLE/COLUMN) and pg_class — the only form of
"documentation" visible from inside the database at all:
- 11.01 no table has a COMMENT ON TABLE set anywhere in the schema
- 11.02 JSONB columns with no column comment explaining the "why" behind the
  choice (distinct from category 8's 08.04, which only checks PII-heuristic
  column names, not JSONB columns generally)
- 11.03 JSONB columns exist but no companion schema/registry table is found
  by name — closes the loop on category 2's 02.01 (JSONB governance
  registry), which was deferred there as follow-up work; this is that
  follow-up, from the institutional-knowledge angle

11.04 (a change log/migration history legible as a narrative, not just a
list of diffs) is declared via `out_of_scope`: assessing whether migration
entries read as a coherent story vs. bare version numbers would mean parsing
arbitrary content across a dozen different migration tools' table schemas
(see category 9's 09.03 for the tools this tool already recognizes by name)
— not something reliably doable from read-only catalog access.

No `applicability` — every database has tables, so this category is never
N/A; 11.02/11.03 internally no-op when there are no JSONB columns to ask
the question about.
"""

from integri_audit_tool.registry import Check, CategoryModule

from . import checks

CATEGORY = CategoryModule(
    slug="documentation-and-institutional-knowledge",
    name="Documentation & Institutional Knowledge",
    checks=[
        Check(
            slug="table-documentation-coverage",
            rubric_bullet=1,
            description="Is the schema documented anywhere outside the schema itself (ERD, data dictionary, README)?",
            fn=checks.check_table_documentation_coverage,
        ),
        Check(
            slug="undocumented-jsonb-column-rationale",
            rubric_bullet=2,
            description="Is there a record of why key architectural decisions (e.g. JSONB) were made?",
            fn=checks.check_undocumented_jsonb_column_rationale,
        ),
        Check(
            slug="jsonb-without-schema-registry",
            rubric_bullet=3,
            description="Would a new engineer understand the intended structure of JSONB attributes without reverse-engineering it from data?",
            fn=checks.check_jsonb_without_schema_registry,
        ),
    ],
    out_of_scope=[
        "Documentation & Institutional Knowledge, bullet 4 (is there a change log or migration history that's legible as a "
        "narrative, not just a list of diffs?) — assessing whether migration entries read as a coherent "
        "story vs. bare version numbers means parsing arbitrary content across a dozen different "
        "migration tools' table schemas, not something reliably doable from read-only catalog access.",
    ],
)
