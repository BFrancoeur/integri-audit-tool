from integri_audit_tool import registry
from integri_audit_tool.registry import Check, CategoryModule


def _category(slug: str, checks: list[Check] | None = None) -> CategoryModule:
    return CategoryModule(slug=slug, name=slug, checks=checks or [])


def test_stamp_category_numbers_assigns_position_in_order():
    a = _category("a")
    b = _category("b")
    c = _category("c")

    numbered = registry._stamp_category_numbers([c, a, b], order=["a", "b", "c"])

    assert [cat.slug for cat in numbered] == ["a", "b", "c"]
    assert [cat.number for cat in numbered] == [1, 2, 3]


def test_stamp_category_numbers_reflects_reordered_list():
    """The whole point of the decoupling: changing `order` alone changes the
    displayed numbers, with no other code touched."""
    a = _category("a")
    b = _category("b")

    numbered = registry._stamp_category_numbers([a, b], order=["b", "a"])

    assert {cat.slug: cat.number for cat in numbered} == {"a": 2, "b": 1}


def test_stamp_category_numbers_raises_when_discovered_category_missing_from_order():
    stray = _category("stray")

    try:
        registry._stamp_category_numbers([stray], order=["a"])
        assert False, "expected ValueError"
    except ValueError as exc:
        assert "stray" in str(exc)


def test_stamp_category_numbers_raises_when_order_lists_a_category_never_discovered():
    a = _category("a")

    try:
        registry._stamp_category_numbers([a], order=["a", "ghost"])
        assert False, "expected ValueError"
    except ValueError as exc:
        assert "ghost" in str(exc)


def test_discover_categories_returns_all_13_sorted_by_number():
    found = registry.discover_categories()
    numbers = [c.number for c in found]
    assert numbers == list(range(1, 14))


def test_lot_and_certification_traceability_category_has_expected_checks_and_applicability():
    categories = {c.slug: c for c in registry.discover_categories()}
    lot_and_cert = categories["lot-and-certification-traceability"]
    assert lot_and_cert.name == "Lot & Certification Traceability"
    check_slugs = {c.slug for c in lot_and_cert.checks}
    assert check_slugs == {
        "lot-columns-poorly-populated",
        "orphaned-lot-certification-links",
        "duplicate-lot-numbers",
        "ungoverned-certification-data",
    }
    assert lot_and_cert.applicability is not None
    assert lot_and_cert.out_of_scope != []


def test_out_of_scope_category_has_no_checks_and_is_marked_out_of_scope_only():
    categories = {c.slug: c for c in registry.discover_categories()}
    out_of_scope = categories["out-of-scope"]
    assert out_of_scope.name == "Out of Scope"
    assert out_of_scope.checks == []
    assert out_of_scope.out_of_scope_only is True
    assert any("Compliance" in note for note in out_of_scope.out_of_scope)
    assert any("Network" in note for note in out_of_scope.out_of_scope)


def test_schema_design_category_has_expected_checks_and_out_of_scope():
    categories = {c.slug: c for c in registry.discover_categories()}
    schema_design = categories["schema-design-and-normalization-boundaries"]
    assert schema_design.name == "Schema Design & Normalization Boundaries"
    check_slugs = {c.slug for c in schema_design.checks}
    assert check_slugs == {"missing-foreign-keys", "schema-drift", "primary-key-consistency"}
    assert any("bullet 1" in note for note in schema_design.out_of_scope)
    assert any("bullet 3" in note for note in schema_design.out_of_scope)


def test_indexing_strategy_category_has_expected_checks():
    categories = {c.slug: c for c in registry.discover_categories()}
    indexing = categories["indexing-strategy"]
    assert indexing.name == "Indexing Strategy"
    check_slugs = {c.slug for c in indexing.checks}
    assert check_slugs == {"unused-indexes", "gin-usage", "redundant-indexes"}


def test_jsonb_governance_category_has_expected_checks_and_applicability():
    categories = {c.slug: c for c in registry.discover_categories()}
    jsonb_governance = categories["jsonb-structure-and-governance"]
    assert jsonb_governance.name == "JSONB Structure & Governance"
    check_slugs = {c.slug for c in jsonb_governance.checks}
    assert check_slugs == {"key-naming-drift", "key-type-inconsistency", "missing-validation-layer"}
    assert jsonb_governance.applicability is not None
    assert any("bullet 5" in note for note in jsonb_governance.out_of_scope)


def test_fulltext_search_category_has_expected_checks_and_applicability():
    categories = {c.slug: c for c in registry.discover_categories()}
    fulltext_search = categories["full-text-and-structured-search-behavior"]
    assert fulltext_search.name == "Full-Text & Structured Search Behavior"
    check_slugs = {c.slug for c in fulltext_search.checks}
    assert check_slugs == {
        "missing-fulltext-index",
        "tsvector-sync-mechanism",
        "combined-structured-and-freetext-queries",
        "relevance-ranking",
        "safe-tsquery-parsing",
    }
    assert fulltext_search.applicability is not None
    assert any("bullet 6" in note for note in fulltext_search.out_of_scope)


def test_query_patterns_category_has_expected_checks_and_out_of_scope():
    categories = {c.slug: c for c in registry.discover_categories()}
    query_patterns = categories["query-patterns-and-application-interaction"]
    assert query_patterns.name == "Query Patterns & Application Interaction"
    check_slugs = {c.slug for c in query_patterns.checks}
    assert check_slugs == {
        "n-plus-one-candidates",
        "offset-pagination",
        "idle-in-transaction-sessions",
        "slow-query-monitoring",
    }
    assert query_patterns.applicability is None
    out_of_scope_text = " ".join(query_patterns.out_of_scope)
    assert "bullet 2" in out_of_scope_text
    assert "bullet 5" in out_of_scope_text


def test_data_quality_category_has_expected_checks():
    categories = {c.slug: c for c in registry.discover_categories()}
    data_quality = categories["data-quality-and-integrity"]
    assert data_quality.name == "Data Quality & Integrity"
    check_slugs = {c.slug for c in data_quality.checks}
    assert check_slugs == {
        "high-null-fraction-columns",
        "unvalidated-foreign-keys",
        "near-unique-columns-without-constraint",
        "never-null-nullable-columns",
        "audit-timestamp-columns-have-nulls",
    }
    assert data_quality.applicability is None


def test_scale_readiness_category_has_all_5_checks():
    categories = {c.slug: c for c in registry.discover_categories()}
    scale_readiness = categories["scale-and-growth-readiness"]
    assert scale_readiness.name == "Scale & Growth Readiness"
    check_slugs = {c.slug for c in scale_readiness.checks}
    assert check_slugs == {
        "slow-queries",
        "largest-tables",
        "tenant-columns-without-rls",
        "high-bloat-tables-without-tuning",
        "large-jsonb-on-hot-tables",
    }
    assert scale_readiness.applicability is None
    assert scale_readiness.out_of_scope == []


def test_security_boundaries_category_has_expected_checks_and_out_of_scope():
    categories = {c.slug: c for c in registry.discover_categories()}
    security = categories["security-and-access-boundaries"]
    assert security.name == "Security & Access Boundaries"
    check_slugs = {c.slug for c in security.checks}
    assert check_slugs == {
        "login-superuser-roles",
        "rls-enabled-without-policies",
        "undocumented-pii-and-ssl",
        "audit-trail-availability",
        "superuser-roles-without-expiration",
    }
    assert security.applicability is None
    assert any("bullet 3" in note for note in security.out_of_scope)


def test_backup_recovery_category_has_all_4_checks():
    categories = {c.slug: c for c in registry.discover_categories()}
    backup_recovery = categories["backup-recovery-and-change-management"]
    assert backup_recovery.name == "Backup, Recovery & Change Management"
    check_slugs = {c.slug for c in backup_recovery.checks}
    assert check_slugs == {
        "wal-archiving-failures",
        "wal-archiving-status-summary",
        "migration-tracking-table-absent",
        "replica-topology-absent",
    }
    assert backup_recovery.applicability is None
    assert backup_recovery.out_of_scope == []


def test_monitoring_category_has_expected_checks_and_out_of_scope():
    categories = {c.slug: c for c in registry.discover_categories()}
    monitoring = categories["monitoring-and-observability"]
    assert monitoring.name == "Monitoring & Observability"
    check_slugs = {c.slug for c in monitoring.checks}
    assert check_slugs == {
        "pg-stat-statements-installed",
        "connection-saturation",
        "bloated-tables-without-recent-vacuum",
    }
    assert monitoring.applicability is None
    assert any("bullet 4" in note for note in monitoring.out_of_scope)


def test_documentation_category_has_expected_checks_and_out_of_scope():
    categories = {c.slug: c for c in registry.discover_categories()}
    documentation = categories["documentation-and-institutional-knowledge"]
    assert documentation.name == "Documentation & Institutional Knowledge"
    check_slugs = {c.slug for c in documentation.checks}
    assert check_slugs == {
        "table-documentation-coverage",
        "undocumented-jsonb-column-rationale",
        "jsonb-without-schema-registry",
    }
    assert documentation.applicability is None
    assert any("bullet 4" in note for note in documentation.out_of_scope)
