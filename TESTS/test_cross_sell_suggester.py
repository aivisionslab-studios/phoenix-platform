"""Testes do sugeridor de combo/cross-sell — Passo 2 (determinístico)."""
from phoenix_kernel.documents.business_strategy_extractor import PricingQuadrant
from phoenix_kernel.documents.cross_sell_suggester import (
    match_product_to_quadrant, rank_quadrants_by_margin, suggest_combos,
)


def _quadrantes():
    return [
        PricingQuadrant(number=1, name="O BOI", subtitle="Isca",
                        example_products=["Cerveja de giro (Brahma/Skol)", "Coca-Cola 2L"],
                        margin_label="Margem Mínima", margin_min_pct=5, margin_max_pct=12,
                        role="Trazer o cliente."),
        PricingQuadrant(number=2, name="O CARRINHO", subtitle="Giro médio",
                        example_products=["Pringles 165g"],
                        margin_label="Margem Saudável", margin_min_pct=30, margin_max_pct=45,
                        role="Pagar o custo fixo."),
        PricingQuadrant(number=4, name="PULO DO GATO", subtitle="Invisível",
                        example_products=["Gelo em Cubo"],
                        margin_label="Margem Explosiva", margin_min_pct=100, margin_max_pct=300,
                        role="Segredo do lucro."),
    ]


def test_rank_by_margin_identifies_anchor_as_lowest():
    ranked = rank_quadrants_by_margin(_quadrantes())
    assert ranked[0].name == "O BOI"       # menor margem = âncora
    assert ranked[-1].name == "PULO DO GATO"  # maior margem = último


def test_match_finds_correct_quadrant():
    quads = _quadrantes()
    m = match_product_to_quadrant("Cerveja Heineken Long Neck 330ml", quads)
    assert m is not None
    assert m[0].name == "O BOI"


def test_unrelated_product_has_no_match():
    quads = _quadrantes()
    m = match_product_to_quadrant("Caderno Espiral 200 Folhas", quads)
    assert m is None


def test_suggest_combos_pairs_anchor_with_complementary():
    quads = _quadrantes()
    produtos = [
        {"Descrição": "Cerveja Heineken Long Neck 330ml"},
        {"Descrição": "Batata Pringles Original 114g"},
        {"Descrição": "Gelo em Cubo 2kg"},
    ]
    combos = suggest_combos(produtos, quads, max_suggestions_per_anchor=2)
    assert len(combos) == 2
    assert all(c.anchor_product == "Cerveja Heineken Long Neck 330ml" for c in combos)
    quadrantes_sugeridos = {c.complementary_quadrant for c in combos}
    assert "O CARRINHO" in quadrantes_sugeridos
    assert "PULO DO GATO" in quadrantes_sugeridos


def test_no_quadrants_returns_empty_never_invents():
    """Sem quadrantes capturados, não inventa sugestão nenhuma."""
    combos = suggest_combos([{"Descrição": "Qualquer Produto"}], [])
    assert combos == []


def test_single_quadrant_returns_empty():
    """Só 1 quadrante não dá pra formar combo (precisa de âncora + complementar)."""
    combos = suggest_combos([{"Descrição": "X"}], [_quadrantes()[0]])
    assert combos == []


def test_duplicate_products_not_suggested_twice():
    """Produto duplicado no catálogo-fonte não gera sugestão repetida."""
    quads = _quadrantes()
    produtos = [
        {"Descrição": "Cerveja Heineken Long Neck 330ml"},
        {"Descrição": "Batata Pringles Original 114g"},
        {"Descrição": "Batata Pringles Original 114g"},  # duplicado
    ]
    combos = suggest_combos(produtos, quads, max_suggestions_per_anchor=5)
    complementares = [c.complementary_product for c in combos]
    assert complementares.count("Batata Pringles Original 114g") == 1
