from integri_audit_tool.cli_progress_reporter import CliProgressReporter
from integri_audit_tool.models import CategoryResult, Finding, Severity
from integri_audit_tool.registry import Check, CategoryModule


def _category(number=1, checks=None):
    return CategoryModule(number=number, name="Test Category", checks=checks or [])


def _check(check_id="01.01"):
    return Check(id=check_id, description="does a thing", fn=lambda conn, cfg: [])


def _result(number=1, status="completed"):
    return CategoryResult(category_number=number, category_name="Test Category", status=status)


def _finding(title="Something found", severity=Severity.MEDIUM, check_id="01.01"):
    return Finding(
        category_number=1,
        category_name="Test Category",
        check_id=check_id,
        title=title,
        severity=severity,
        observation="obs",
    )


def test_check_failed_writes_log_file(tmp_path):
    logs_dir = tmp_path / "logs"
    reporter = CliProgressReporter(logs_dir=logs_dir)
    category = _category(checks=[_check()])
    check = _check()

    reporter.category_ready(category, [check])
    reporter.check_started(category, check)
    reporter.check_failed(category, check, RuntimeError("something broke"))
    reporter.audit_completed(object())

    log_files = list(logs_dir.glob("*.log"))
    assert len(log_files) == 1
    content = log_files[0].read_text(encoding="utf-8")
    assert "01.01" in content
    assert "something broke" in content


def test_no_log_file_created_when_nothing_fails(tmp_path):
    logs_dir = tmp_path / "logs"
    reporter = CliProgressReporter(logs_dir=logs_dir)
    category = _category(checks=[_check()])
    check = _check()

    reporter.category_ready(category, [check])
    reporter.check_started(category, check)
    reporter.check_succeeded(category, check, [])
    reporter.audit_completed(object())

    assert not logs_dir.exists() or list(logs_dir.glob("*.log")) == []


def test_category_not_applicable_and_progress_do_not_raise(tmp_path):
    reporter = CliProgressReporter(logs_dir=tmp_path / "logs")
    category = _category(checks=[])

    reporter.category_ready(category, [])
    reporter.category_not_applicable(category, "no jsonb columns")
    reporter.audit_completed(object())


def test_category_completed_prints_alias_for_an_announced_completed_category(tmp_path, capsys):
    reporter = CliProgressReporter(logs_dir=tmp_path / "logs")
    category = _category(number=1, checks=[_check()])

    reporter.category_ready(category, [_check()])
    reporter.category_completed(category, _result(number=1, status="completed"))

    assert "ia-schema completed" in capsys.readouterr().err


def test_category_completed_falls_back_to_category_number_without_a_known_alias(tmp_path, capsys):
    reporter = CliProgressReporter(logs_dir=tmp_path / "logs")
    category = _category(number=999, checks=[_check()])

    reporter.category_ready(category, [_check()])
    reporter.category_completed(category, _result(number=999, status="completed"))

    assert "Category 999 completed" in capsys.readouterr().err


def test_category_completed_prints_nothing_when_never_announced(tmp_path, capsys):
    """A category the --check filter skipped entirely never got a category_ready
    call, so there's nothing to announce as "completed" either."""
    reporter = CliProgressReporter(logs_dir=tmp_path / "logs")
    category = _category(number=1, checks=[_check()])

    reporter.category_completed(category, _result(number=1, status="completed"))

    assert "completed" not in capsys.readouterr().err


def test_category_completed_prints_nothing_for_not_applicable(tmp_path, capsys):
    """category_not_applicable already announced this — no separate "completed" line."""
    reporter = CliProgressReporter(logs_dir=tmp_path / "logs")
    category = _category(number=1, checks=[])

    reporter.category_ready(category, [])
    reporter.category_not_applicable(category, "no jsonb columns")
    capsys.readouterr()  # drain the not_applicable message before asserting
    reporter.category_completed(category, _result(number=1, status="not_applicable"))

    assert "ia-schema completed" not in capsys.readouterr().err


def test_check_succeeded_prints_each_finding_severity_and_title(tmp_path, capsys):
    reporter = CliProgressReporter(logs_dir=tmp_path / "logs")
    category = _category(checks=[_check()])
    check = _check()
    findings = [
        _finding(title="High severity thing", severity=Severity.HIGH),
        _finding(title="Low severity thing", severity=Severity.LOW),
    ]

    reporter.category_ready(category, [check])
    reporter.check_started(category, check)
    reporter.check_succeeded(category, check, findings)

    out = capsys.readouterr().err
    assert "High severity thing" in out
    assert "[High]" in out
    assert "Low severity thing" in out
    assert "[Low]" in out


def test_check_succeeded_prints_green_passed_when_no_findings(tmp_path, capsys):
    reporter = CliProgressReporter(logs_dir=tmp_path / "logs")
    category = _category(checks=[_check()])
    check = _check()

    reporter.category_ready(category, [check])
    reporter.check_started(category, check)
    reporter.check_succeeded(category, check, [])

    out = capsys.readouterr().err
    assert "✓ 01.01 passed" in out
    assert "✗" not in out
    assert "completed" not in out


def test_check_succeeded_prints_red_x_completed_when_findings_exist_even_low_severity(tmp_path, capsys):
    """A check that runs cleanly but turns up even one low-severity finding is not
    a "pass" — the severity color-coding on the finding line conveys urgency;
    the checkmark/X only conveys whether anything needs addressing at all."""
    reporter = CliProgressReporter(logs_dir=tmp_path / "logs")
    category = _category(checks=[_check()])
    check = _check()
    findings = [_finding(title="Minor thing", severity=Severity.LOW)]

    reporter.category_ready(category, [check])
    reporter.check_started(category, check)
    reporter.check_succeeded(category, check, findings)

    out = capsys.readouterr().err
    assert "✗ 01.01 completed" in out
    assert "(1 finding(s))" in out
    assert "✓" not in out
    assert "passed" not in out


def test_check_succeeded_escapes_markup_characters_in_finding_titles(tmp_path, capsys):
    """A title containing literal square brackets must not be interpreted as rich
    markup (which could garble output or raise a MarkupError) — e.g. a title that
    happens to embed a Python list repr like "['a', 'b']"."""
    reporter = CliProgressReporter(logs_dir=tmp_path / "logs")
    category = _category(checks=[_check()])
    check = _check()
    finding = _finding(title="Drift for ['a', 'b']")

    reporter.category_ready(category, [check])
    reporter.check_started(category, check)
    reporter.check_succeeded(category, check, [finding])  # must not raise

    assert "Drift for ['a', 'b']" in capsys.readouterr().err


def test_category_ready_does_not_block_by_default(tmp_path, capsys, monkeypatch):
    def _fail_if_called():
        raise AssertionError("input() should not be called when interactive=False")

    monkeypatch.setattr("builtins.input", lambda: _fail_if_called())
    reporter = CliProgressReporter(logs_dir=tmp_path / "logs")
    category = _category(number=1, checks=[_check()])

    reporter.category_ready(category, [_check()])  # must not raise / must not block

    assert "Press Enter" not in capsys.readouterr().err


def test_category_ready_waits_for_enter_when_interactive(tmp_path, capsys, monkeypatch):
    calls = []
    monkeypatch.setattr("builtins.input", lambda: calls.append(1))
    reporter = CliProgressReporter(logs_dir=tmp_path / "logs", interactive=True)
    category = _category(number=1, checks=[_check()])

    reporter.category_ready(category, [_check()])

    assert calls == [1]
    assert "Press Enter to run this category's tests..." in capsys.readouterr().err


def test_category_ready_interactive_survives_eof(tmp_path, capsys, monkeypatch):
    """A non-interactive invocation (piped/closed stdin) with --step set shouldn't
    hang or crash — it should just proceed."""

    def _raise_eof():
        raise EOFError

    monkeypatch.setattr("builtins.input", lambda: _raise_eof())
    reporter = CliProgressReporter(logs_dir=tmp_path / "logs", interactive=True)
    category = _category(number=1, checks=[_check()])

    reporter.category_ready(category, [_check()])  # must not raise


def test_audit_completed_no_longer_prints_its_own_banner(tmp_path, capsys):
    """The "Audit complete." message moved to cli.py, printed once, unconditionally —
    CliProgressReporter.audit_completed now only reports the failure log path, if any."""
    reporter = CliProgressReporter(logs_dir=tmp_path / "logs")

    reporter.audit_completed(object())

    assert "Audit complete" not in capsys.readouterr().err
