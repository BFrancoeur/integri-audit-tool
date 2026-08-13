import dataclasses

import pytest


def test_finding_is_frozen(make_finding):
    finding = make_finding()
    with pytest.raises(dataclasses.FrozenInstanceError):
        finding.title = "changed"


def test_finding_measurement_and_attestation_fields_default_to_unset(make_finding):
    finding = make_finding()
    assert finding.measurement_method is None
    assert finding.requires_attestation is False
    assert finding.attested_by is None
    assert finding.attestation_outcome is None
