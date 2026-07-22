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
    assert any("04.06" in note for note in fulltext_search.out_of_scope)


def test_query_patterns_category_has_expected_checks_and_out_of_scope():
    categories = {c.number: c for c in registry.discover_categories()}
    query_patterns = categories[5]
    assert query_patterns.name == "Query Patterns & Application Interaction"
    check_ids = {c.id for c in query_patterns.checks}
    assert check_ids == {"05.01", "05.03", "05.04", "05.06"}
    assert query_patterns.applicability is None
    out_of_scope_text = " ".join(query_patterns.out_of_scope)
    assert "05.02" in out_of_scope_text
    assert "05.05" in out_of_scope_text


def test_data_quality_category_has_expected_checks():
    categories = {c.number: c for c in registry.discover_categories()}
    data_quality = categories[6]
    assert data_quality.name == "Data Quality & Integrity"
    check_ids = {c.id for c in data_quality.checks}
    assert check_ids == {"06.01", "06.03", "06.04", "06.05", "06.06"}
    assert data_quality.applicability is None


def test_scale_readiness_category_has_all_5_checks():
    categories = {c.number: c for c in registry.discover_categories()}
    scale_readiness = categories[7]
    assert scale_readiness.name == "Scale & Growth Readiness"
    check_ids = {c.id for c in scale_readiness.checks}
    assert check_ids == {"07.01", "07.02", "07.03", "07.04", "07.05"}
    assert scale_readiness.applicability is None
    assert scale_readiness.out_of_scope == []
