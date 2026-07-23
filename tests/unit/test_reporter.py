from integri_audit_tool.registry import Check, CategoryModule
from integri_audit_tool.reporter import NullReporter


def test_null_reporter_methods_are_all_no_ops():
    reporter = NullReporter()
    category = CategoryModule(number=1, name="Test", checks=[])
    check = Check(id="01.01", description="does a thing", fn=lambda conn, cfg: [])

    # None of these should raise or return anything meaningful.
    assert reporter.category_ready(category, [check]) is None
    assert reporter.category_not_applicable(category, "reason") is None
    assert reporter.check_started(category, check) is None
    assert reporter.check_succeeded(category, check, []) is None
    assert reporter.check_failed(category, check, RuntimeError("boom")) is None
    assert reporter.audit_completed(object()) is None
