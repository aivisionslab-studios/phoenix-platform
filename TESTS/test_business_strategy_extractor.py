"""Testes do extrator de estratégia comercial — captura em vez de descartar."""
from phoenix_kernel.documents.business_strategy_extractor import (
    extract_pricing_quadrants, is_quadrant_title,
)


_TEXTO_REAL = """
1. Quadrante: O BOI (Volume / Isca)
Produtos: Cerveja de giro (Brahma/Skol/Antarctica), Coca-Cola 2L, Cigarros.
Estratégia: Margem Mínima (5% a 12%).
Função: Trazer o cliente para dentro. Aqui você não ganha dinheiro, você ganha o cliente.

2. Quadrante: O CARRINHO (Conveniência / Giro Médio)
Produtos: Pringles 165g, Salame Fatiado 100g, Energéticos (Monster/TNT), Chocolates Lacta.
Estratégia: Margem Saudável (30% a 45%).
Função: Pagar o custo fixo.
"""


def test_extracts_all_quadrants():
    quads = extract_pricing_quadrants(_TEXTO_REAL)
    assert len(quads) == 2
    assert quads[0].name == "O BOI"
    assert quads[1].name == "O CARRINHO"


def test_extracts_subtitle():
    quads = extract_pricing_quadrants(_TEXTO_REAL)
    assert quads[0].subtitle == "Volume / Isca"


def test_extracts_example_products():
    quads = extract_pricing_quadrants(_TEXTO_REAL)
    assert "Coca-Cola 2L" in quads[0].example_products
    assert "Pringles 165g" in quads[1].example_products


def test_extracts_margin_range():
    quads = extract_pricing_quadrants(_TEXTO_REAL)
    assert quads[0].margin_min_pct == 5.0
    assert quads[0].margin_max_pct == 12.0
    assert quads[1].margin_min_pct == 30.0
    assert quads[1].margin_max_pct == 45.0


def test_extracts_role_text():
    quads = extract_pricing_quadrants(_TEXTO_REAL)
    assert "Trazer o cliente" in quads[0].role


def test_no_quadrants_found_returns_empty_not_invented():
    """Documento sem 'Quadrante' -> lista vazia, nunca inventa regra."""
    quads = extract_pricing_quadrants("Isso aqui é só um texto qualquer sobre produtos.")
    assert quads == []


def test_is_quadrant_title_recognizes_pattern():
    assert is_quadrant_title("1. Quadrante: O BOI (Volume / Isca)")
    assert is_quadrant_title("2. Quadrante: O CARRINHO (Conveniência / Giro Médio)")
    assert not is_quadrant_title("63. Cachaça São Francisco 970ml")
