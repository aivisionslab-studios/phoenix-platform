"""Testes da consulta à Tabela CEST↔NCM oficial — cest_lookup.py."""
from phoenix_kernel.documents.cest_lookup import get_cest_for_ncm, cest_exists, table_size


def test_table_loads_with_real_data():
    assert table_size() > 1000  # ~1.106 pares (CEST, prefixo) na fonte


def test_exact_ncm_match():
    resultados = get_cest_for_ncm("3815.12.10")
    codigos = [m.cest for m in resultados]
    assert "01.001.00" in codigos


def test_prefix_match_shorter_than_full_ncm():
    """CEST registrado só com 4 dígitos (ex.: '3917') deve bater com
    qualquer NCM completo que comece assim."""
    resultados = get_cest_for_ncm("3917.29.00")
    codigos = [m.cest for m in resultados]
    assert "01.002.00" in codigos
    assert "10.006.00" in codigos


def test_same_ncm_can_have_multiple_cest_by_segment():
    """Achado real: o mesmo NCM aparece em CEST diferentes por segmento —
    isso é regra de verdade do ICMS-ST, não erro. A função tem que
    devolver TODOS, não escolher um sozinha."""
    resultados = get_cest_for_ncm("3923.30.00")
    codigos = {m.cest for m in resultados}
    assert len(codigos) > 1


def test_most_specific_match_ranks_first():
    resultados = get_cest_for_ncm("3815.12.10")
    assert resultados[0].especifico is True
    assert resultados[0].ncm_prefixo == "38151210"


def test_apenas_especifico_filters_out_chapter_wide_matches():
    todos = get_cest_for_ncm("3923.30.00")
    especificos = get_cest_for_ncm("3923.30.00", apenas_especifico=True)
    assert len(especificos) < len(todos)
    assert all(m.especifico for m in especificos)


def test_ncm_without_cest_returns_empty():
    """Produto não sujeito a substituição tributária — lista vazia, nunca
    um CEST inventado."""
    assert get_cest_for_ncm("0101.21.00") == []


def test_cest_exists():
    assert cest_exists("01.001.00") is True
    assert cest_exists("99.999.99") is False


def test_empty_ncm_returns_empty():
    assert get_cest_for_ncm("") == []
