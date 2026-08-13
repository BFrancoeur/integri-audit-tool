from __future__ import annotations

from pathlib import Path

import pytest

from integri_audit_tool.fingerprint_config import (
    DEFAULT_SIMILARITY_THRESHOLD,
    FingerprintConfigError,
    load_fingerprint_config,
)

_FIELDS_BLOCK = """
[[fields]]
column = "material_grade"
normalize = ["lowercase", "strip_whitespace"]

[[fields]]
column = "diameter_in"
normalize = ["digits_only"]
"""

# TOML gotcha, worth documenting for future editors of this file: any bare
# `key = value` line appended *after* a [[fields]] block is parsed as
# belonging to the *last* table in that array, not the top-level document --
# so any additional top-level key (like similarity_threshold) MUST be
# inserted before _FIELDS_BLOCK, never appended after it.
_BASE_CONFIG = """
schema = "public"
table = "parts"
id_column = "id"
"""

_VALID_CONFIG = _BASE_CONFIG + _FIELDS_BLOCK


def _write(tmp_path, content, name="config.toml"):
    path = tmp_path / name
    path.write_text(content, encoding="utf-8")
    return path


def test_load_fingerprint_config_parses_valid_config(tmp_path):
    path = _write(tmp_path, _VALID_CONFIG)

    config = load_fingerprint_config(path)

    assert config.schema == "public"
    assert config.table == "parts"
    assert config.id_column == "id"
    assert len(config.fields) == 2
    assert config.fields[0].column == "material_grade"
    assert config.fields[0].normalize == ("lowercase", "strip_whitespace")
    assert config.fields[1].normalize == ("digits_only",)


def test_load_fingerprint_config_defaults_similarity_threshold(tmp_path):
    path = _write(tmp_path, _VALID_CONFIG)
    config = load_fingerprint_config(path)
    assert config.similarity_threshold == DEFAULT_SIMILARITY_THRESHOLD


def test_load_fingerprint_config_respects_explicit_similarity_threshold(tmp_path):
    path = _write(tmp_path, _BASE_CONFIG + "similarity_threshold = 0.8\n" + _FIELDS_BLOCK)
    config = load_fingerprint_config(path)
    assert config.similarity_threshold == 0.8


def test_load_fingerprint_config_rejects_missing_file(tmp_path):
    with pytest.raises(FingerprintConfigError):
        load_fingerprint_config(tmp_path / "does_not_exist.toml")


def test_load_fingerprint_config_rejects_invalid_toml(tmp_path):
    path = _write(tmp_path, "this is not [valid toml")
    with pytest.raises(FingerprintConfigError):
        load_fingerprint_config(path)


@pytest.mark.parametrize("missing_key", ["schema", "table", "id_column", "fields"])
def test_load_fingerprint_config_rejects_missing_required_key(tmp_path, missing_key):
    lines = [
        line
        for line in _VALID_CONFIG.strip().splitlines()
        if not line.startswith(f"{missing_key} =")
    ]
    content = "\n".join(lines)
    if missing_key == "fields":
        content = 'schema = "public"\ntable = "parts"\nid_column = "id"\n'
    path = _write(tmp_path, content)

    with pytest.raises(FingerprintConfigError, match=missing_key):
        load_fingerprint_config(path)


def test_load_fingerprint_config_rejects_empty_fields_list(tmp_path):
    path = _write(tmp_path, 'schema = "public"\ntable = "parts"\nid_column = "id"\nfields = []\n')
    with pytest.raises(FingerprintConfigError):
        load_fingerprint_config(path)


def test_load_fingerprint_config_rejects_field_missing_column(tmp_path):
    path = _write(
        tmp_path,
        'schema = "public"\ntable = "parts"\nid_column = "id"\n\n[[fields]]\nnormalize = ["lowercase"]\n',
    )
    with pytest.raises(FingerprintConfigError, match="column"):
        load_fingerprint_config(path)


def test_load_fingerprint_config_rejects_unknown_normalize_step(tmp_path):
    path = _write(
        tmp_path,
        'schema = "public"\ntable = "parts"\nid_column = "id"\n\n[[fields]]\ncolumn = "grade"\n'
        'normalize = ["shout_loudly"]\n',
    )
    with pytest.raises(FingerprintConfigError, match="shout_loudly"):
        load_fingerprint_config(path)


def test_load_fingerprint_config_field_with_no_normalize_steps_is_allowed(tmp_path):
    path = _write(
        tmp_path,
        'schema = "public"\ntable = "parts"\nid_column = "id"\n\n[[fields]]\ncolumn = "grade"\n',
    )
    config = load_fingerprint_config(path)
    assert config.fields[0].normalize == ()


@pytest.mark.parametrize("bad_threshold", [0, -0.1, 1.5, 1.0001])
def test_load_fingerprint_config_rejects_out_of_range_similarity_threshold(tmp_path, bad_threshold):
    path = _write(tmp_path, _BASE_CONFIG + f"similarity_threshold = {bad_threshold}\n" + _FIELDS_BLOCK)
    with pytest.raises(FingerprintConfigError, match="similarity_threshold"):
        load_fingerprint_config(path)


def test_load_fingerprint_config_allows_similarity_threshold_of_exactly_one(tmp_path):
    path = _write(tmp_path, _BASE_CONFIG + "similarity_threshold = 1.0\n" + _FIELDS_BLOCK)
    config = load_fingerprint_config(path)
    assert config.similarity_threshold == 1.0


def test_shipped_example_config_is_itself_valid():
    """The example file (examples/duplicate_fingerprint.example.toml) is the
    first thing a user copies to get started -- it must parse cleanly under
    the tool's own loader, not just look plausible."""
    example_path = Path(__file__).parent.parent.parent / "examples" / "duplicate_fingerprint.example.toml"
    config = load_fingerprint_config(example_path)
    assert config.schema == "public"
    assert config.table == "parts"
    assert len(config.fields) >= 1
