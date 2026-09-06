"""Testes do RAG fiscal — sugere NCM/CEST de dados auditados, nunca inventa."""
from phoenix_kernel.documents.fiscal_rag import FiscalRAG


def _rag_com_base():
    rag = FiscalRAG()
    rag.add_entry("Tinta Acrílica Suvinil 18L Fosco", ncm="32091010", cest="2400100", source="cat")
    rag.add_entry("Tinta Acrílica Coral 18L Premium", ncm="32091010", cest="2400100", source="cat")
    rag.add_entry("Argamassa AC3 Quartzolit 20kg", ncm="38245000", cest="1000100", source="cat")
    rag.add_entry("Cerveja Heineken Pilsen 330ml", ncm="22030000", cest="0302100", source="cat")
    return rag


def test_recovers_ncm_from_similar_audited_product():
    rag = _rag_com_base()
    sugg = rag.query("Tinta Acrílica Fosca Premium 18L", field_type="ncm")
    assert sugg
    assert sugg[0].value == "32091010"
    assert sugg[0].status == "suggested"        # nunca confirmed
    assert sugg[0].matched_description           # traz de onde veio


def test_consensus_boosts_confidence():
    rag = _rag_com_base()
    # duas tintas com o mesmo NCM -> consenso reforça
    sugg = rag.query("Tinta Acrílica 18L", field_type="ncm")
    assert sugg[0].value == "32091010"
    assert sugg[0].confidence > 0.34


def test_unknown_product_returns_nothing():
    rag = _rag_com_base()
    sugg = rag.query("Componente Eletrônico Raro XZ99", field_type="ncm")
    assert sugg == []                            # melhor vazio que palpite


def test_malformed_fiscal_code_never_enters_base():
    rag = FiscalRAG()
    assert not rag.add_entry("Produto X", ncm="123")      # NCM não tem 8 dígitos
    assert not rag.add_entry("Produto Y", ncm="", cest="") # nada fiscal
    assert len(rag) == 0


def test_suggest_for_row_only_fills_empty():
    rag = _rag_com_base()
    row = {"Descrição": "Tinta Acrílica Fosca 18L", "NCM": "99999999", "CEST": ""}
    out = rag.suggest_for_row(row)
    assert "ncm" not in out          # NCM já preenchido -> não sugere
    # CEST vazio pode receber sugestão
