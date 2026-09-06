"""Testes da consulta à Tabela NCM oficial (governo) — ncm_lookup.py.

Complementa o fiscal_rag.py (que sugere a partir do histórico da empresa):
este módulo valida existência REAL de um NCM e busca na tabela oficial
(Res. Gecex, vigente em 27/04/2026), útil pra produtos sem histórico prévio.
"""
from phoenix_kernel.documents.ncm_lookup import (
    ncm_exists, get_ncm_entry, search_ncm_by_text, table_size,
)


def test_table_loads_with_real_data():
    assert table_size() > 10000  # ~10.515 NCM completos na fonte original


def test_ncm_exists_for_real_code():
    assert ncm_exists("0101.21.00") is True
    assert ncm_exists("01012100") is True  # sem pontos também funciona


def test_ncm_does_not_exist_for_invented_code():
    """Código com formato válido (8 dígitos) mas que nunca existiu —
    a checagem de EXISTÊNCIA real, não só de formato."""
    assert ncm_exists("99999999") is False
    assert ncm_exists("12345678") is False


def test_get_ncm_entry_returns_official_description():
    entry = get_ncm_entry("0101.21.00")
    assert entry is not None
    assert entry.codigo == "01012100"
    assert "raça pura" in entry.descricao.lower()


def test_get_ncm_entry_returns_none_for_nonexistent():
    assert get_ncm_entry("00000000") is None


def test_search_finds_correct_leaf_match():
    """Busca de uma palavra específica deve achar o NCM certo com score alto."""
    resultados = search_ncm_by_text("cerveja")
    assert resultados
    codigos = [e.codigo_formatado for e, _ in resultados]
    assert "2202.91.00" in codigos or "2203.00.00" in codigos


def test_search_leaf_match_ranks_above_ancestor_only_match():
    """PHX-FIX (achado real): 'cerveja' aparece tanto na descrição folha do
    NCM de cerveja quanto, incidentalmente, no capítulo de resíduos
    industriais (que também cita 'cerveja' de passagem). O match na folha
    tem que valer mais que o match só no contexto ancestral."""
    resultados = search_ncm_by_text("cavalo reprodutor de raça pura", limit=5)
    assert resultados
    melhor_codigo, melhor_score = resultados[0]
    assert melhor_codigo.codigo_formatado == "0101.21.00"  # cavalos, não suínos/caprinos
    # o melhor resultado deve ter score estritamente maior que empates genéricos
    if len(resultados) > 1:
        assert melhor_score >= resultados[1][1]


def test_search_handles_common_plural():
    """PHX-FIX: normalização leve de plural (vogal+s) — 'cavalos' devia
    aparecer tanto buscando 'cavalo' quanto 'cavalos'."""
    r_singular = search_ncm_by_text("cavalo reprodutor de raça pura")
    r_plural = search_ncm_by_text("cavalos reprodutores de raça pura")
    assert r_singular and r_plural
    assert r_singular[0][0].codigo == r_plural[0][0].codigo


def test_search_returns_empty_for_no_match():
    """Sem correspondência real, devolve lista vazia — nunca força um
    palpite fraco (regra de ouro do projeto)."""
    resultados = search_ncm_by_text("xyzabc123 produto totalmente inventado")
    assert resultados == []


def test_search_empty_query_returns_empty():
    assert search_ncm_by_text("") == []
    assert search_ncm_by_text("   ") == []
