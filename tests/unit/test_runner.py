from integri_audit_tool import runner
from integri_audit_tool.config import AuditConfig
from integri_audit_tool.models import Severity
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


def test_run_audit_stamps_category_and_check_identity_onto_findings(monkeypatch, make_finding):
    """A check function only ever sets check_slug -- the runner is responsible for
    stamping category_number/category_name/check_id from the category's computed
    number and the check's authored rubric_bullet, overwriting whatever the check
    function's own Finding happened to carry (make_finding's defaults here are
    deliberately different from the stamped values, to prove they get overwritten
    rather than coincidentally matching)."""
    raw_finding = make_finding(check_slug="does-a-thing")
    category = CategoryModule(
        slug="fake-category",
        number=99,
        name="Fake Category",
        checks=[
            Check(slug="does-a-thing", rubric_bullet=1, description="does a thing", fn=lambda conn, cfg: [raw_finding])
        ],
    )
    monkeypatch.setattr(runner.registry, "discover_categories", lambda: [category])

    report = runner.run_audit(conn=object(), config=_config(), target_label="test-db")

    stamped = report.category_results[0].findings[0]
    assert stamped.check_slug == "does-a-thing"
    assert stamped.category_number == 99
    assert stamped.category_name == "Fake Category"
    assert stamped.check_id == "99.01"


def test_run_audit_computes_check_id_from_authored_rubric_bullet(monkeypatch, make_finding):
    """rubric_bullet is authored per check, not derived from list position or
    order -- a category can implement bullets out of order, or with gaps for
    not-yet-built ones, and the displayed id still reflects the real bullet."""
    category = CategoryModule(
        slug="fake-category",
        number=5,
        name="Fake Category",
        checks=[
            Check(
                slug="first", rubric_bullet=1, description="first", fn=lambda conn, cfg: [make_finding(check_slug="first")]
            ),
            Check(
                slug="fourth",
                rubric_bullet=4,
                description="fourth",
                fn=lambda conn, cfg: [make_finding(check_slug="fourth")],
            ),
        ],
    )
    monkeypatch.setattr(runner.registry, "discover_categories", lambda: [category])

    report = runner.run_audit(conn=object(), config=_config(), target_label="test-db")

    check_ids = [f.check_id for f in report.category_results[0].findings]
    assert check_ids == ["05.01", "05.04"]


def test_run_audit_degrades_failing_check_to_informational_finding(monkeypatch):
    def boom(conn, cfg):
        raise RuntimeError("pg_stat_statements not installed")

    category = CategoryModule(
        slug="fake-category",
        number=99,
        name="Fake Category",
        checks=[Check(slug="does-a-thing", rubric_bullet=1, description="does a thing", fn=boom)],
    )
    monkeypatch.setattr(runner.registry, "discover_categories", lambda: [category])

    report = runner.run_audit(conn=object(), config=_config(), target_label="test-db")

    finding = report.category_results[0].findings[0]
    assert finding.severity == Severity.INFORMATIONAL
    assert finding.check_slug == "does-a-thing"
    assert finding.check_id == "99.01"
    assert "pg_stat_statements" in finding.observation


def test_run_audit_marks_category_not_applicable(monkeypatch):
    category = CategoryModule(
        slug="fake-category",
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
    included = CategoryModule(slug="a", number=1, name="A", checks=[])
    excluded = CategoryModule(slug="b", number=2, name="B", checks=[])
    monkeypatch.setattr(runner.registry, "discover_categories", lambda: [included, excluded])

    report = runner.run_audit(conn=object(), config=_config(category_filter={1}), target_label="test-db")

    assert [r.category_number for r in report.category_results] == [1]


def test_run_audit_omits_out_of_scope_category_when_none_discovered(monkeypatch):
    """Fake category sets that don't model an out_of_scope_only category (most of
    this file's tests) shouldn't need to — the runner treats it as optional."""
    monkeypatch.setattr(runner.registry, "discover_categories", lambda: [])

    report = runner.run_audit(conn=object(), config=_config(), target_label="test-db")

    assert report.category_results == []


def test_run_audit_always_includes_the_out_of_scope_category_regardless_of_filter(monkeypatch):
    """Out-of-scope notes are permanent tool limitations, not properties of a given run —
    the Out of Scope category always shows up with every category's out_of_scope bullets
    collected onto it, whether or not --category/--check filtering would otherwise have
    excluded it or the categories that own those bullets.
    """
    included = CategoryModule(slug="a", number=1, name="A", checks=[], out_of_scope=["A's bullet is UI-only."])
    excluded = CategoryModule(slug="b", number=2, name="B", checks=[], out_of_scope=["B's bullet is UI-only."])
    out_of_scope = CategoryModule(
        slug="out-of-scope", number=3, name="Out of Scope", checks=[], out_of_scope_only=True
    )
    monkeypatch.setattr(runner.registry, "discover_categories", lambda: [included, excluded, out_of_scope])

    report = runner.run_audit(conn=object(), config=_config(category_filter={1}), target_label="test-db")

    oos_result = next(r for r in report.category_results if r.category_number == 3)
    assert "A's bullet is UI-only." in oos_result.out_of_scope_notes
    assert "B's bullet is UI-only." in oos_result.out_of_scope_notes
    # but which categories actually *run* still respects the filter
    assert [r.category_number for r in report.category_results if r.category_number != 3] == [1]


def test_run_audit_always_includes_the_out_of_scope_category_even_with_a_check_filter(monkeypatch, make_finding):
    matching = CategoryModule(
        slug="a",
        number=1,
        name="A",
        checks=[Check(slug="does-a-thing", rubric_bullet=1, description="d", fn=lambda conn, cfg: [])],
    )
    out_of_scope = CategoryModule(
        slug="out-of-scope",
        number=3,
        name="Out of Scope",
        checks=[],
        out_of_scope_only=True,
        out_of_scope=["Permanent tool limitation."],
    )
    monkeypatch.setattr(runner.registry, "discover_categories", lambda: [matching, out_of_scope])

    report = runner.run_audit(conn=object(), config=_config(check_filter={"01.01"}), target_label="test-db")

    oos_result = next(r for r in report.category_results if r.category_number == 3)
    assert oos_result.out_of_scope_notes == ["Permanent tool limitation."]


def test_run_audit_stamps_check_results_for_passed_findings_and_error_outcomes(monkeypatch, make_finding):
    def boom(conn, cfg):
        raise RuntimeError("boom")

    category = CategoryModule(
        slug="fake-category",
        number=99,
        name="Fake Category",
        checks=[
            Check(slug="clean", rubric_bullet=1, description="Clean check", fn=lambda conn, cfg: []),
            Check(
                slug="dirty",
                rubric_bullet=2,
                description="Dirty check",
                fn=lambda conn, cfg: [make_finding(check_slug="dirty"), make_finding(check_slug="dirty")],
            ),
            Check(slug="broken", rubric_bullet=3, description="Broken check", fn=boom),
        ],
    )
    monkeypatch.setattr(runner.registry, "discover_categories", lambda: [category])

    report = runner.run_audit(conn=object(), config=_config(), target_label="test-db")

    check_results = {cr.check_slug: cr for cr in report.category_results[0].check_results}
    assert check_results["clean"].status == "passed"
    assert check_results["clean"].finding_count == 0
    assert check_results["clean"].check_id == "99.01"
    assert check_results["clean"].description == "Clean check"
    assert check_results["dirty"].status == "findings"
    assert check_results["dirty"].finding_count == 2
    assert check_results["broken"].status == "error"
    assert check_results["broken"].finding_count == 0
    assert check_results["broken"].error_message == "boom"


def test_run_audit_respects_check_filter_by_computed_display_id(monkeypatch, make_finding):
    category = CategoryModule(
        slug="fake-category",
        number=99,
        name="Fake Category",
        checks=[
            Check(
                slug="included",
                rubric_bullet=1,
                description="does a thing",
                fn=lambda conn, cfg: [make_finding(check_slug="included")],
            ),
            Check(
                slug="excluded",
                rubric_bullet=2,
                description="does another thing",
                fn=lambda conn, cfg: [make_finding(check_slug="excluded")],
            ),
        ],
    )
    monkeypatch.setattr(runner.registry, "discover_categories", lambda: [category])

    report = runner.run_audit(conn=object(), config=_config(check_filter={"99.01"}), target_label="test-db")

    assert [f.check_slug for f in report.category_results[0].findings] == ["included"]


def test_run_audit_respects_check_filter_by_stable_slug(monkeypatch, make_finding):
    """The same filter also has to work by a check's stable slug, not just its
    currently-displayed id — muscle memory (-k 01.04) and the stable form
    (-k missing-foreign-keys) both need to keep working."""
    category = CategoryModule(
        slug="fake-category",
        number=99,
        name="Fake Category",
        checks=[
            Check(
                slug="included",
                rubric_bullet=1,
                description="does a thing",
                fn=lambda conn, cfg: [make_finding(check_slug="included")],
            ),
            Check(
                slug="excluded",
                rubric_bullet=2,
                description="does another thing",
                fn=lambda conn, cfg: [make_finding(check_slug="excluded")],
            ),
        ],
    )
    monkeypatch.setattr(runner.registry, "discover_categories", lambda: [category])

    report = runner.run_audit(conn=object(), config=_config(check_filter={"included"}), target_label="test-db")

    assert [f.check_slug for f in report.category_results[0].findings] == ["included"]


class _RecordingReporter:
    def __init__(self):
        self.events: list[tuple] = []

    def category_ready(self, category, checks_to_run):
        self.events.append(("category_ready", category.number, [c.slug for c in checks_to_run]))

    def category_not_applicable(self, category, reason):
        self.events.append(("category_not_applicable", category.number, reason))

    def check_started(self, category, check):
        self.events.append(("check_started", check.slug))

    def check_succeeded(self, category, check, findings):
        self.events.append(("check_succeeded", check.slug, len(findings)))

    def check_failed(self, category, check, error):
        self.events.append(("check_failed", check.slug, str(error)))

    def category_completed(self, category, result):
        self.events.append(("category_completed", category.number, result.status))

    def audit_completed(self, report):
        self.events.append(("audit_completed",))


def test_run_audit_calls_reporter_hooks_in_order(monkeypatch, make_finding):
    def boom(conn, cfg):
        raise RuntimeError("nope")

    category = CategoryModule(
        slug="fake-category",
        number=99,
        name="Fake Category",
        checks=[
            Check(
                slug="ok-check",
                rubric_bullet=1,
                description="ok check",
                fn=lambda conn, cfg: [make_finding(check_slug="ok-check")],
            ),
            Check(slug="bad-check", rubric_bullet=2, description="bad check", fn=boom),
        ],
    )
    monkeypatch.setattr(runner.registry, "discover_categories", lambda: [category])
    reporter = _RecordingReporter()

    runner.run_audit(conn=object(), config=_config(), target_label="test-db", reporter=reporter)

    assert reporter.events == [
        ("category_ready", 99, ["ok-check", "bad-check"]),
        ("check_started", "ok-check"),
        ("check_succeeded", "ok-check", 1),
        ("check_started", "bad-check"),
        ("check_failed", "bad-check", "nope"),
        ("category_completed", 99, "completed"),
        ("audit_completed",),
    ]


def test_run_audit_calls_reporter_category_not_applicable(monkeypatch):
    category = CategoryModule(
        slug="fake-category", number=99, name="Fake Category", checks=[], applicability=lambda conn: False
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
    matching = CategoryModule(
        slug="matches",
        number=1,
        name="Matches",
        checks=[
            Check(
                slug="does-a-thing",
                rubric_bullet=1,
                description="does a thing",
                fn=lambda conn, cfg: [make_finding(check_slug="does-a-thing")],
            )
        ],
    )
    applicability_calls = []
    non_matching = CategoryModule(
        slug="doesnt-match",
        number=2,
        name="Doesn't match",
        checks=[Check(slug="unrelated", rubric_bullet=1, description="unrelated", fn=lambda conn, cfg: [])],
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
