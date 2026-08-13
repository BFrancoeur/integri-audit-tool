"""Loads a per-engagement identity-fingerprint config for the Semantic
Duplicate Detection category — declarative TOML only (stdlib `tomllib`, no
eval/arbitrary code), consistent with this project's "no hardcoded values"
rule by keeping the field list and normalization steps entirely data-driven
rather than baked into the tool. What makes two rows "the same real-world
entity" is business knowledge specific to the engagement; this tool never
guesses it.

TOML rather than YAML deliberately: `tomllib` is stdlib as of Python 3.11+
(this project's minimum), so this needs no new dependency at all.

Current normalization vocabulary (NORMALIZE_PRIMITIVES) is deliberately
limited to simple string cleanup — lowercase, whitespace stripping, digit/
alphanumeric extraction. True semantic/unit normalization (vendor
"dictionaries" mapping product names, naming conventions, and measurement
units/formats onto a canonical form — see integri-db-generator's UNS/DIN/
JIS grade crosswalks for the shape this will eventually take) is
explicitly deferred (2026-08-05 direction): normalizing "1/4 in" ==
"0.25in" == "6.35mm" isn't a fixed-regex problem, and is noted as a strong
future candidate for an LLM-agent-based approach rather than a purely
algorithmic one.
"""

from __future__ import annotations

import tomllib
from dataclasses import dataclass
from pathlib import Path

NORMALIZE_PRIMITIVES = ("lowercase", "strip_whitespace", "digits_only", "alphanumeric_only")
"""Fixed vocabulary of normalization steps -- no arbitrary code/eval. Each
maps to a specific SQL expression in
semantic_duplicate_detection/queries.py's _NORMALIZE_SQL_TEMPLATES."""

DEFAULT_SIMILARITY_THRESHOLD = 0.6
"""pg_trgm similarity (0-1) below which two fingerprints aren't considered a
fuzzy-match candidate at all -- a moderate default; lower catches more
(noisier) candidates, higher misses more real near-duplicates."""


class FingerprintConfigError(ValueError):
    """Raised for a missing, malformed, or invalid fingerprint config file."""


@dataclass(frozen=True)
class FingerprintField:
    column: str
    normalize: tuple[str, ...]


@dataclass(frozen=True)
class FingerprintConfig:
    schema: str
    table: str
    id_column: str
    fields: tuple[FingerprintField, ...]
    similarity_threshold: float = DEFAULT_SIMILARITY_THRESHOLD


def load_fingerprint_config(path: Path) -> FingerprintConfig:
    try:
        raw_text = path.read_text(encoding="utf-8")
    except OSError as exc:
        raise FingerprintConfigError(f"Could not read fingerprint config at {path}: {exc}") from exc

    try:
        raw = tomllib.loads(raw_text)
    except tomllib.TOMLDecodeError as exc:
        raise FingerprintConfigError(f"Invalid TOML in {path}: {exc}") from exc

    for required_key in ("schema", "table", "id_column", "fields"):
        if required_key not in raw:
            raise FingerprintConfigError(f"{path}: missing required key '{required_key}'")

    raw_fields = raw["fields"]
    if not isinstance(raw_fields, list) or not raw_fields:
        raise FingerprintConfigError(f"{path}: 'fields' must be a non-empty list of [[fields]] tables")

    fields = []
    for i, raw_field in enumerate(raw_fields):
        if "column" not in raw_field:
            raise FingerprintConfigError(f"{path}: fields[{i}] is missing 'column'")
        normalize = tuple(raw_field.get("normalize", []))
        unknown_steps = set(normalize) - set(NORMALIZE_PRIMITIVES)
        if unknown_steps:
            raise FingerprintConfigError(
                f"{path}: fields[{i}] ('{raw_field['column']}') uses unknown normalize step(s) "
                f"{sorted(unknown_steps)} — valid steps are {NORMALIZE_PRIMITIVES}"
            )
        fields.append(FingerprintField(column=raw_field["column"], normalize=normalize))

    similarity_threshold = raw.get("similarity_threshold", DEFAULT_SIMILARITY_THRESHOLD)
    if not isinstance(similarity_threshold, (int, float)) or not (0 < similarity_threshold <= 1):
        raise FingerprintConfigError(
            f"{path}: similarity_threshold must be a number in (0, 1], got {similarity_threshold!r}"
        )

    return FingerprintConfig(
        schema=raw["schema"],
        table=raw["table"],
        id_column=raw["id_column"],
        fields=tuple(fields),
        similarity_threshold=float(similarity_threshold),
    )
