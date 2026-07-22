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
