import dataclasses

import pytest

from integri_audit_tool.models import CATEGORY_12_OUT_OF_SCOPE_NOTE, AuditReport
from datetime import datetime, timezone


def test_audit_report_defaults_out_of_scope_to_category_12():
    report = AuditReport(target_label="db", generated_at=datetime.now(timezone.utc), category_results=[])
    assert report.out_of_scope == [CATEGORY_12_OUT_OF_SCOPE_NOTE]


def test_finding_is_frozen(make_finding):
    finding = make_finding()
    with pytest.raises(dataclasses.FrozenInstanceError):
        finding.title = "changed"
