import dataclasses

import pytest


def test_finding_is_frozen(make_finding):
    finding = make_finding()
    with pytest.raises(dataclasses.FrozenInstanceError):
        finding.title = "changed"
