from archeon.core.knowledge import KnowledgeRouter


def test_stable_general_knowledge_can_use_local_model():
    result = KnowledgeRouter().assess("Explícame cómo funciona la fotosíntesis")
    assert "science" in result.domains
    assert result.temporal == "stable"
    assert result.allow_unverified_claims is True


def test_current_news_requires_fresh_sources():
    result = KnowledgeRouter().assess("Dime las últimas noticias de tecnología de hoy")
    assert result.temporal == "changing"
    assert result.requires_fresh_sources is True
    assert result.allow_unverified_claims is False


def test_high_stakes_domains_require_fresh_sources_even_without_today_word():
    for request in ("qué medicamento debo tomar", "qué dice la ley", "en qué acciones invierto"):
        result = KnowledgeRouter().assess(request)
        assert result.risk == "high"
        assert result.requires_fresh_sources is True


def test_broad_taxonomy_routes_multiple_domains():
    result = KnowledgeRouter().assess("Enséñame estadística para analizar un negocio")
    assert {"mathematics", "business", "education"} <= set(result.domains)
