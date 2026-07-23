from integri_audit_tool.cli_progress_reporter import CliProgressReporter
from integri_audit_tool.registry import Check, CategoryModule


def _category(number=1, checks=None):
    return CategoryModule(number=number, name="Test Category", checks=checks or [])


def _check(check_id="01.01"):
    return Check(id=check_id, description="does a thing", fn=lambda conn, cfg: [])


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
