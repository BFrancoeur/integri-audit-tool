from integri_audit_tool import runner
from integri_audit_tool.config import AuditConfig
from integri_audit_tool.models import CATEGORY_12_OUT_OF_SCOPE_NOTE, Severity
from integri_audit_tool.registry import Check, CategoryModule


def _config(**overrides) -> AuditConfig:
    return AuditConfig(dsn="postgresql://example", **overrides)


def test_run_audit_passes_client_name_through_to_the_report(monkeypatch):
    monkeypatch.setattr(runner.registry, "discover_categories", lambda: [])

    report = runner.run_audit(
        conn=object(), config=_config(), target_label="test-db", client_name="Sample Company"
    )

    assert report.client_name == "Sample Company"


def test_run_audit_client_name_defaults_to_none(monkeypatch):
    monkeypatch.setattr(runner.registry, "discover_categories", lambda: [])

    report = runner.run_audit(conn=object(), config=_config(), target_label="test-db")

    assert report.client_name is None


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


def test_run_audit_respects_check_filter(monkeypatch, make_finding):
    included_finding = make_finding(check_id="99.01")
    excluded_finding = make_finding(check_id="99.02")
    category = CategoryModule(
        number=99,
        name="Fake Category",
        checks=[
            Check(id="99.01", description="does a thing", fn=lambda conn, cfg: [included_finding]),
            Check(id="99.02", description="does another thing", fn=lambda conn, cfg: [excluded_finding]),
        ],
    )
    monkeypatch.setattr(runner.registry, "discover_categories", lambda: [category])

    report = runner.run_audit(conn=object(), config=_config(check_filter={"99.01"}), target_label="test-db")

    assert report.category_results[0].findings == [included_finding]


class _RecordingReporter:
    def __init__(self):
        self.events: list[tuple] = []

    def category_ready(self, category, checks_to_run):
        self.events.append(("category_ready", category.number, [c.id for c in checks_to_run]))

    def category_not_applicable(self, category, reason):
        self.events.append(("category_not_applicable", category.number, reason))

    def check_started(self, category, check):
        self.events.append(("check_started", check.id))

    def check_succeeded(self, category, check, findings):
        self.events.append(("check_succeeded", check.id, len(findings)))

    def check_failed(self, category, check, error):
        self.events.append(("check_failed", check.id, str(error)))

    def category_completed(self, category, result):
        self.events.append(("category_completed", category.number, result.status))

    def audit_completed(self, report):
        self.events.append(("audit_completed",))


def test_run_audit_calls_reporter_hooks_in_order(monkeypatch, make_finding):
    finding = make_finding(check_id="99.01")

    def boom(conn, cfg):
        raise RuntimeError("nope")

    category = CategoryModule(
        number=99,
        name="Fake Category",
        checks=[
            Check(id="99.01", description="ok check", fn=lambda conn, cfg: [finding]),
            Check(id="99.02", description="bad check", fn=boom),
        ],
    )
    monkeypatch.setattr(runner.registry, "discover_categories", lambda: [category])
    reporter = _RecordingReporter()

    runner.run_audit(conn=object(), config=_config(), target_label="test-db", reporter=reporter)

    assert reporter.events == [
        ("category_ready", 99, ["99.01", "99.02"]),
        ("check_started", "99.01"),
        ("check_succeeded", "99.01", 1),
        ("check_started", "99.02"),
        ("check_failed", "99.02", "nope"),
        ("category_completed", 99, "completed"),
        ("audit_completed",),
    ]


def test_run_audit_calls_reporter_category_not_applicable(monkeypatch):
    category = CategoryModule(
        number=99, name="Fake Category", checks=[], applicability=lambda conn: False
    )
    monkeypatch.setattr(runner.registry, "discover_categories", lambda: [category])
    reporter = _RecordingReporter()

    runner.run_audit(conn=object(), config=_config(), target_label="test-db", reporter=reporter)

    assert ("category_ready", 99, []) in reporter.events
    assert any(event[0] == "category_not_applicable" for event in reporter.events)
    assert ("category_completed", 99, "not_applicable") in reporter.events
    assert reporter.events[-1] == ("audit_completed",)


def test_run_audit_does_not_announce_category_with_no_matching_checks(monkeypatch, make_finding):
    """When a --check filter is active, a category with none of the requested checks
    shouldn't be announced to the reporter at all — no empty progress bar noise, and
    applicability isn't even evaluated for it."""
    finding = make_finding(check_id="01.01")
    matching = CategoryModule(
        number=1,
        name="Matches",
        checks=[Check(id="01.01", description="does a thing", fn=lambda conn, cfg: [finding])],
    )
    applicability_calls = []
    non_matching = CategoryModule(
        number=2,
        name="Doesn't match",
        checks=[Check(id="02.01", description="unrelated", fn=lambda conn, cfg: [])],
        applicability=lambda conn: applicability_calls.append(1) or True,
    )
    monkeypatch.setattr(runner.registry, "discover_categories", lambda: [matching, non_matching])
    reporter = _RecordingReporter()

    report = runner.run_audit(
        conn=object(), config=_config(check_filter={"01.01"}), target_label="test-db", reporter=reporter
    )

    category_ready_numbers = [e[1] for e in reporter.events if e[0] == "category_ready"]
    assert category_ready_numbers == [1]
    assert applicability_calls == []  # never evaluated for the non-matching category
    assert [r.category_number for r in report.category_results] == [1, 2]  # still both in the report
    # category_completed fires for every category regardless of announcement,
    # so an incremental report writer always learns the final outcome.
    category_completed_numbers = [e[1] for e in reporter.events if e[0] == "category_completed"]
    assert category_completed_numbers == [1, 2]
