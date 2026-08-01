from __future__ import annotations

import sqlite3

from integri_audit_tool.analytics import AuditDatabaseWriter, _database_name_from_label
from integri_audit_tool.models import CategoryResult, Finding, Severity
from integri_audit_tool.registry import CategoryModule


def _finding(check_id="01.01", check_slug="missing-foreign-keys", severity=Severity.MEDIUM, title="Something found"):
    return Finding(
        check_slug=check_slug,
        category_number=1,
        category_name="Schema Design & Normalization Boundaries",
        check_id=check_id,
        title=title,
        severity=severity,
        observation="obs",
        business_impact="impact",
        recommended_direction="fix it",
    )


def _query_all(db_path, sql):
    with sqlite3.connect(db_path) as conn:
        conn.row_factory = sqlite3.Row
        return [dict(row) for row in conn.execute(sql).fetchall()]


def test_database_name_from_label_extracts_trailing_segment():
    assert _database_name_from_label("127.0.0.1:5432/sample_company") == "sample_company"


def test_database_name_from_label_returns_whole_string_without_slash():
    assert _database_name_from_label("no-slash-here") == "no-slash-here"


def test_category_completed_creates_run_and_finding_rows(tmp_path):
    db_path = tmp_path / "analytics.db"
    writer = AuditDatabaseWriter(
        target_label="127.0.0.1:5432/sample_company", client_name="Sample Company", db_path=db_path
    )
    category = CategoryModule(
        slug="schema-design-and-normalization-boundaries",
        number=1,
        name="Schema Design & Normalization Boundaries",
        checks=[],
    )
    finding = _finding()

    writer.category_completed(
        category, CategoryResult(category_number=1, category_name=category.name, status="completed", findings=[finding])
    )

    runs = _query_all(db_path, "SELECT * FROM audit_runs")
    assert len(runs) == 1
    assert runs[0]["client_name"] == "Sample Company"
    assert runs[0]["database_name"] == "sample_company"
    assert runs[0]["is_synthetic"] == 0

    findings = _query_all(db_path, "SELECT * FROM findings")
    assert len(findings) == 1
    assert findings[0]["check_id"] == "01.01"
    assert findings[0]["severity"] == "Medium"
    assert findings[0]["run_id"] == runs[0]["id"]


def test_category_completed_with_no_findings_does_not_create_a_run_row_yet(tmp_path):
    db_path = tmp_path / "analytics.db"
    writer = AuditDatabaseWriter(target_label="127.0.0.1:5432/sample_company", db_path=db_path)
    category = CategoryModule(slug="a", number=1, name="A", checks=[])

    writer.category_completed(
        category, CategoryResult(category_number=1, category_name="A", status="completed", findings=[])
    )

    # No schema created at all yet -- nothing has ever been written.
    assert not db_path.exists()


def test_audit_completed_creates_a_run_row_even_for_a_fully_clean_audit(tmp_path):
    """A perfect audit (zero findings anywhere) should still leave a record --
    otherwise "ran clean" is indistinguishable from "never ran"."""
    db_path = tmp_path / "analytics.db"
    writer = AuditDatabaseWriter(target_label="127.0.0.1:5432/sample_company", db_path=db_path)

    writer.audit_completed(report=object())

    runs = _query_all(db_path, "SELECT * FROM audit_runs")
    assert len(runs) == 1
    findings = _query_all(db_path, "SELECT * FROM findings")
    assert findings == []


def test_multiple_categories_accumulate_into_the_same_run(tmp_path):
    db_path = tmp_path / "analytics.db"
    writer = AuditDatabaseWriter(target_label="127.0.0.1:5432/sample_company", db_path=db_path)

    writer.category_completed(
        CategoryModule(slug="a", number=1, name="A", checks=[]),
        CategoryResult(
            category_number=1,
            category_name="A",
            status="completed",
            findings=[_finding(check_id="01.01", check_slug="a-check")],
        ),
    )
    writer.category_completed(
        CategoryModule(slug="b", number=2, name="B", checks=[]),
        CategoryResult(
            category_number=2,
            category_name="B",
            status="completed",
            findings=[_finding(check_id="02.01", check_slug="b-check")],
        ),
    )

    runs = _query_all(db_path, "SELECT * FROM audit_runs")
    assert len(runs) == 1  # not a new run per category
    findings = _query_all(db_path, "SELECT * FROM findings ORDER BY check_id")
    assert [f["check_id"] for f in findings] == ["01.01", "02.01"]
    assert all(f["run_id"] == runs[0]["id"] for f in findings)


def test_is_synthetic_flag_is_stored(tmp_path):
    db_path = tmp_path / "analytics.db"
    writer = AuditDatabaseWriter(target_label="127.0.0.1:55432/synthetic_client", is_synthetic=True, db_path=db_path)

    writer.audit_completed(report=object())

    runs = _query_all(db_path, "SELECT * FROM audit_runs")
    assert runs[0]["is_synthetic"] == 1


def test_category_filter_and_check_filter_are_recorded(tmp_path):
    db_path = tmp_path / "analytics.db"
    writer = AuditDatabaseWriter(
        target_label="127.0.0.1:5432/sample_company",
        category_filter="1,6",
        check_filter="01.04,01.05",
        db_path=db_path,
    )

    writer.audit_completed(report=object())

    runs = _query_all(db_path, "SELECT * FROM audit_runs")
    assert runs[0]["category_filter"] == "1,6"
    assert runs[0]["check_filter"] == "01.04,01.05"


def test_category_ready_creates_a_running_run_row(tmp_path):
    """The run row must exist as soon as the run starts, before any
    findings arrive -- otherwise a crash before the first finding leaves
    no record at all that a run was even attempted."""
    db_path = tmp_path / "analytics.db"
    writer = AuditDatabaseWriter(target_label="127.0.0.1:5432/sample_company", db_path=db_path)

    writer.category_ready(CategoryModule(slug="a", number=1, name="A", checks=[]), [])

    runs = _query_all(db_path, "SELECT * FROM audit_runs")
    assert len(runs) == 1
    assert runs[0]["status"] == "running"
    assert runs[0]["completed_at"] is None


def test_audit_completed_marks_the_run_as_completed(tmp_path):
    db_path = tmp_path / "analytics.db"
    writer = AuditDatabaseWriter(target_label="127.0.0.1:5432/sample_company", db_path=db_path)
    writer.category_ready(CategoryModule(slug="a", number=1, name="A", checks=[]), [])

    writer.audit_completed(report=object())

    runs = _query_all(db_path, "SELECT * FROM audit_runs")
    assert runs[0]["status"] == "completed"
    assert runs[0]["completed_at"] is not None


def test_a_crashed_run_stays_running_forever(tmp_path):
    """Simulates a crash: category_ready fires (creating the run row), but
    audit_completed never gets called. An analytics consumer must be able
    to tell this run never finished, rather than it looking complete."""
    db_path = tmp_path / "analytics.db"
    writer = AuditDatabaseWriter(target_label="127.0.0.1:5432/sample_company", db_path=db_path)

    writer.category_ready(CategoryModule(slug="a", number=1, name="A", checks=[]), [])
    # ... process "crashes" here -- audit_completed is deliberately never called.

    runs = _query_all(db_path, "SELECT * FROM audit_runs")
    assert runs[0]["status"] == "running"
    assert runs[0]["completed_at"] is None


def test_existing_database_without_lifecycle_columns_gets_migrated(tmp_path):
    """A pre-existing analytics.db from before status/completed_at existed
    has an audit_runs table without them -- CREATE TABLE IF NOT EXISTS
    alone won't add columns to an existing table, so this must migrate in
    place rather than erroring."""
    db_path = tmp_path / "analytics.db"
    with sqlite3.connect(db_path) as conn:
        conn.execute(
            "CREATE TABLE audit_runs ("
            "id INTEGER PRIMARY KEY AUTOINCREMENT, client_name TEXT, target_label TEXT NOT NULL, "
            "database_name TEXT NOT NULL, generated_at TEXT NOT NULL, is_synthetic INTEGER NOT NULL DEFAULT 0, "
            "category_filter TEXT, check_filter TEXT)"
        )
        conn.commit()

    writer = AuditDatabaseWriter(target_label="127.0.0.1:5432/sample_company", db_path=db_path)
    writer.category_ready(CategoryModule(slug="a", number=1, name="A", checks=[]), [])

    runs = _query_all(db_path, "SELECT * FROM audit_runs")
    assert runs[0]["status"] == "running"


def test_writing_to_an_existing_database_file_does_not_error(tmp_path):
    """Schema creation (CREATE TABLE IF NOT EXISTS) must be safe to run
    repeatedly, since a fresh AuditDatabaseWriter is constructed per
    `integri-audit run` invocation but they all share the same db file."""
    db_path = tmp_path / "analytics.db"
    AuditDatabaseWriter(target_label="a/db1", db_path=db_path).audit_completed(report=object())
    AuditDatabaseWriter(target_label="b/db2", db_path=db_path).audit_completed(report=object())

    runs = _query_all(db_path, "SELECT * FROM audit_runs ORDER BY id")
    assert [r["database_name"] for r in runs] == ["db1", "db2"]
