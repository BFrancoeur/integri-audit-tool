from integri_audit_tool import registry


def test_discover_categories_returns_all_11_sorted_by_number():
    categories = registry.discover_categories()
    numbers = [c.number for c in categories]
    assert numbers == list(range(1, 12))


def test_indexing_strategy_category_has_expected_checks():
    categories = {c.number: c for c in registry.discover_categories()}
    indexing = categories[3]
    assert indexing.name == "Indexing Strategy"
    check_ids = {c.id for c in indexing.checks}
    assert check_ids == {"03.01", "03.02", "03.04"}


def test_jsonb_governance_category_has_expected_checks_and_applicability():
    categories = {c.number: c for c in registry.discover_categories()}
    jsonb_governance = categories[2]
    assert jsonb_governance.name == "JSONB Structure & Governance"
    check_ids = {c.id for c in jsonb_governance.checks}
    assert check_ids == {"02.02", "02.03", "02.04"}
    assert jsonb_governance.applicability is not None


def test_fulltext_search_category_has_expected_checks_and_applicability():
    categories = {c.number: c for c in registry.discover_categories()}
    fulltext_search = categories[4]
    assert fulltext_search.name == "Full-Text & Structured Search Behavior"
    check_ids = {c.id for c in fulltext_search.checks}
    assert check_ids == {"04.01", "04.02", "04.03", "04.04", "04.05"}
    assert fulltext_search.applicability is not None
