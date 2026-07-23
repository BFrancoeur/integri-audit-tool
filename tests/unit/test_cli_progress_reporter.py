from integri_audit_tool.cli_progress_reporter import CliProgressReporter
from integri_audit_tool.models import CategoryResult
from integri_audit_tool.registry import Check, CategoryModule


def _category(number=1, checks=None):
    return CategoryModule(number=number, name="Test Category", checks=checks or [])


def _check(check_id="01.01"):
    return Check(id=check_id, description="does a thing", fn=lambda conn, cfg: [])


def _result(number=1, status="completed"):
    return CategoryResult(category_number=number, category_name="Test Category", status=status)


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


def test_audit_completed_no_longer_prints_its_own_banner(tmp_path, capsys):
    """The "Audit complete." message moved to cli.py, printed once, unconditionally —
    CliProgressReporter.audit_completed now only stops the progress bar and reports
    the failure log path, if any."""
    reporter = CliProgressReporter(logs_dir=tmp_path / "logs")

    reporter.audit_completed(object())

    assert "Audit complete" not in capsys.readouterr().err
