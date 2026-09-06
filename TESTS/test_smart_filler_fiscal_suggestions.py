"""Testes: smart_filler ligado a fiscal_rag/ncm_lookup/cest_lookup — a
guarda-fiscal continua NUNCA preenchendo NCM/CEST/CFOP, mas a pendência
ganha uma sugestão pra acelerar a auditoria humana.
"""
from phoenix_kernel.documents.fiscal_rag import FiscalRAG
from phoenix_kernel.documents.smart_filler import smart_fill_rows


def _pendencia(rep, coluna):
    for _desc, col, motivo, _row_idx in rep.pending:
        if col == coluna:
            return motivo
    return None


def test_fiscal_guard_still_never_fills_cell():
    """A regra de ouro não muda: célula continua vazia mesmo com sugestão."""
    rows = [{"Descrição": "Cimento Portland CP II 50kg", "NCM": "", "CEST": ""}]
    rows, rep = smart_fill_rows(rows)
    assert rows[0]["NCM"] == ""
    assert rows[0]["CEST"] == ""


def test_ncm_suggestion_from_official_table_without_fiscal_rag():
    rows = [{"Descrição": "Cimento Portland CP II 50kg", "NCM": "", "CEST": ""}]
    rows, rep = smart_fill_rows(rows)
    motivo = _pendencia(rep, "NCM")
    assert motivo is not None
    assert "sugestão: NCM" in motivo
    assert "tabela oficial" in motivo


def test_ncm_suggestion_prefers_fiscal_rag_over_official_table():
    """Histórico da empresa tem prioridade sobre a tabela oficial genérica."""
    rag = FiscalRAG()
    rag.add_entry("Cimento Portland CP II 50kg Votoran", ncm="2523.29.10", source="empresa")
    rows = [{"Descrição": "Cimento Portland CP II 50kg", "NCM": "", "CEST": ""}]
    rows, rep = smart_fill_rows(rows, fiscal_rag=rag)
    motivo = _pendencia(rep, "NCM")
    assert "histórico" in motivo
    assert "25232910" in motivo


def test_cest_suggestion_reuses_same_ncm_suggested_for_ncm_field():
    """PHX-FIX (achado real em teste): a sugestão de CEST tem que usar o
    MESMO NCM que acabou de ser sugerido pro campo NCM da mesma linha —
    não buscar de novo por conta própria e arriscar um NCM diferente."""
    rag = FiscalRAG()
    rag.add_entry("Cimento Portland CP II 50kg Votoran", ncm="2523.29.10", source="empresa")
    rows = [{"Descrição": "Cimento Portland CP II 50kg", "NCM": "", "CEST": ""}]
    rows, rep = smart_fill_rows(rows, fiscal_rag=rag)
    motivo_ncm = _pendencia(rep, "NCM")
    motivo_cest = _pendencia(rep, "CEST")
    assert "25232910" in motivo_ncm
    assert "25232910" in motivo_cest  # o mesmo NCM, não outro


def test_cest_suggestion_uses_already_filled_ncm_when_present():
    """Se o documento já trouxe um NCM real, a sugestão de CEST usa ESSE
    NCM (não busca outro por conta própria)."""
    rows = [{"Descrição": "Cimento qualquer", "NCM": "2523.21.00", "CEST": ""}]
    rows, rep = smart_fill_rows(rows)
    assert rows[0]["NCM"] == "2523.21.00"  # NCM preenchido não é a guarda-fiscal, fica
    motivo_cest = _pendencia(rep, "CEST")
    assert motivo_cest is not None
    assert "2523.21.00" in motivo_cest


def test_no_suggestion_for_completely_unmatched_product():
    """Produto sem correspondência em nenhuma fonte — pendência sem
    sugestão, nunca um palpite fraco."""
    rows = [{"Descrição": "xyzabc123 produto totalmente inventado", "NCM": "", "CEST": ""}]
    rows, rep = smart_fill_rows(rows)
    motivo = _pendencia(rep, "NCM")
    assert "sugestão" not in motivo


def test_cfop_never_gets_a_suggestion():
    """Não existe tabela de referência ligada pro CFOP ainda — pendência
    normal, sem sugestão."""
    rows = [{"Descrição": "Cimento Portland CP II 50kg", "CFOP": ""}]
    rows, rep = smart_fill_rows(rows)
    motivo = _pendencia(rep, "CFOP")
    assert motivo is not None
    assert "sugestão" not in motivo
