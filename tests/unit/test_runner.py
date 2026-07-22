from integri_audit_tool import runner
from integri_audit_tool.config import AuditConfig
from integri_audit_tool.models import CATEGORY_12_OUT_OF_SCOPE_NOTE, Severity
from integri_audit_tool.registry import Check, CategoryModule


def _config(**overrides) -> AuditConfig:
    return AuditConfig(dsn="postgresql://example", **overrides)


def test_run_audit_collects_findings_from_checks(monkeypatch, make_finding):
    finding = make_finding(check_id="99.01")
    category = CategoryModule(
        number=99,
        name="Fake Category",
        checks=[Check(id="99.01", description="does a thing", fn=lambda conn, cfg: [finding])],
    )
    monkeypatch.setattr(runner.registry, "discover_categories", lambda: [category])

    report = runner.run_audit(conn=object(), config=_config(), target_label="test-db")

    assert len(report.category_results) == 1
    result = report.category_results[0]
    assert result.status == "completed"
    assert result.findings == [finding]


def test_run_audit_degrades_failing_check_to_informational_finding(monkeypatch):
    def boom(conn, cfg):
        raise RuntimeError("pg_stat_statements not installed")

    category = CategoryModule(
        number=99,
        name="Fake Category",
        checks=[Check(id="99.01", description="does a thing", fn=boom)],
    )
    monkeypatch.setattr(runner.registry, "discover_categories", lambda: [category])

    report = runner.run_audit(conn=object(), config=_config(), target_label="test-db")

    finding = report.category_results[0].findings[0]
    assert finding.severity == Severity.INFORMATIONAL
    assert "pg_stat_statements" in finding.observation


def test_run_audit_marks_category_not_applicable(monkeypatch):
    category = CategoryModule(
        number=99,
        name="Fake Category",
        checks=[],
        applicability=lambda conn: False,
    )
    monkeypatch.setattr(runner.registry, "discover_categories", lambda: [category])

    report = runner.run_audit(conn=object(), config=_config(), target_label="test-db")

    result = report.category_results[0]
    assert result.status == "not_applicable"
    assert result.findings == []


def test_run_audit_respects_category_filter(monkeypatch):
    included = CategoryModule(number=1, name="A", checks=[])
    excluded = CategoryModule(number=2, name="B", checks=[])
    monkeypatch.setattr(runner.registry, "discover_categories", lambda: [included, excluded])

    report = runner.run_audit(conn=object(), config=_config(category_filter={1}), target_label="test-db")

    assert [r.category_number for r in report.category_results] == [1]


def test_run_audit_always_includes_category_12_out_of_scope_note(monkeypatch):
    monkeypatch.setattr(runner.registry, "discover_categories", lambda: [])

    report = runner.run_audit(conn=object(), config=_config(), target_label="test-db")

    assert report.out_of_scope == [CATEGORY_12_OUT_OF_SCOPE_NOTE]


def test_run_audit_collects_out_of_scope_notes_from_all_categories_regardless_of_filter(monkeypatch):
    """Out-of-scope notes are permanent tool limitations, not properties of a given run —
    they show up the same way category 12's note always does, whether or not the category
    that owns them was included in --category filtering.
    """
    included = CategoryModule(number=1, name="A", checks=[], out_of_scope=["A's bullet is UI-only."])
    excluded = CategoryModule(number=2, name="B", checks=[], out_of_scope=["B's bullet is UI-only."])
    monkeypatch.setattr(runner.registry, "discover_categories", lambda: [included, excluded])

    report = runner.run_audit(conn=object(), config=_config(category_filter={1}), target_label="test-db")

    assert "A's bullet is UI-only." in report.out_of_scope
    assert "B's bullet is UI-only." in report.out_of_scope
    assert CATEGORY_12_OUT_OF_SCOPE_NOTE in report.out_of_scope
    # but which categories actually *run* still respects the filter
    assert [r.category_number for r in report.category_results] == [1]
