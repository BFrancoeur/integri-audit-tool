from integri_audit_tool.models import CategoryResult
from integri_audit_tool.registry import Check, CategoryModule
from integri_audit_tool.reporter import CompositeReporter, NullReporter


def test_null_reporter_methods_are_all_no_ops():
    reporter = NullReporter()
    category = CategoryModule(slug="test", number=1, name="Test", checks=[])
    check = Check(slug="does-a-thing", rubric_bullet=1, description="does a thing", fn=lambda conn, cfg: [])
    result = CategoryResult(category_number=1, category_name="Test", status="completed")

    # None of these should raise or return anything meaningful.
    assert reporter.category_ready(category, [check]) is None
    assert reporter.category_not_applicable(category, "reason") is None
    assert reporter.check_started(category, check) is None
    assert reporter.check_succeeded(category, check, []) is None
    assert reporter.check_failed(category, check, RuntimeError("boom")) is None
    assert reporter.category_completed(category, result) is None
    assert reporter.audit_completed(object()) is None


class _RecordingReporter:
    def __init__(self):
        self.events: list[tuple] = []

    def category_ready(self, category, checks_to_run):
        self.events.append(("category_ready", category.number))

    def category_not_applicable(self, category, reason):
        self.events.append(("category_not_applicable", category.number))

    def check_started(self, category, check):
        self.events.append(("check_started", check.slug))

    def check_succeeded(self, category, check, findings):
        self.events.append(("check_succeeded", check.slug))

    def check_failed(self, category, check, error):
        self.events.append(("check_failed", check.slug))

    def category_completed(self, category, result):
        self.events.append(("category_completed", category.number))

    def audit_completed(self, report):
        self.events.append(("audit_completed",))


def test_composite_reporter_fans_every_call_out_to_all_reporters():
    a, b = _RecordingReporter(), _RecordingReporter()
    composite = CompositeReporter([a, b])
    category = CategoryModule(slug="test", number=1, name="Test", checks=[])
    check = Check(slug="does-a-thing", rubric_bullet=1, description="does a thing", fn=lambda conn, cfg: [])
    result = CategoryResult(category_number=1, category_name="Test", status="completed")

    composite.category_ready(category, [check])
    composite.category_not_applicable(category, "reason")
    composite.check_started(category, check)
    composite.check_succeeded(category, check, [])
    composite.check_failed(category, check, RuntimeError("boom"))
    composite.category_completed(category, result)
    composite.audit_completed(object())

    expected = [
        ("category_ready", 1),
        ("category_not_applicable", 1),
        ("check_started", "does-a-thing"),
        ("check_succeeded", "does-a-thing"),
        ("check_failed", "does-a-thing"),
        ("category_completed", 1),
        ("audit_completed",),
    ]
    assert a.events == expected
    assert b.events == expected
