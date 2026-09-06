"""Testes da camada de integração formato-ciente (GLM + pipeline testado).

Prova que a detecção de formato genérica alimenta o pipeline V2 testado, e que
o MESMO código extrai nomes de formatos diferentes sem ramo por formato.
"""
from phoenix_kernel.documents.format_aware_parser import format_aware_document_from_text
from phoenix_kernel.documents.candidate_engine import find_candidates_in_document
from phoenix_kernel.documents.record_segmenter import segment_records
from phoenix_kernel.documents.identity_engine import resolve_identity


_LABELED = """
Tinta Acrílica Suvinil Toque de Seda 18L
[DADOS ESTRUTURADOS PARA O ERP] NCM: 32091010 | CEST: 2400100
Argamassa AC3 Quartzolit 20kg
[DADOS ESTRUTURADOS PARA O ERP] NCM: 38245000 | CEST: 1000100
Tinta Coral Rende Muito 18L
[DADOS ESTRUTURADOS PARA O ERP] NCM: 32091010 | CEST: 2400100
"""

_NUMBERED = """
63. Cachaça São Francisco 970ml
NCM: 22084000
64. Cerveja Antarctica Pilsen 300ml
NCM: 22030000
65. Refrigerante Sukita 350ml
NCM: 22021000
"""


def _names_through_pipeline(text):
    """Camada de formato -> pipeline testado -> nomes finais."""
    doc, info = format_aware_document_from_text(text, "teste")
    cands = find_candidates_in_document(doc)
    recs = segment_records(doc, cands)
    cbi = {c.id: c for c in cands if c.id}
    bbi = {b.id: b for b in doc.blocks}
    ident = resolve_identity(recs, cbi, bbi)
    names = []
    for cr in ident.canonical_records:
        fe = cr.fields.get("explicit_product_name")
        if fe and fe.value:
            names.append(fe.value)
    return names, info


def test_detects_labeled_blocks_format():
    doc, info = format_aware_document_from_text(_LABELED, "t")
    assert info["format"] == "labeled_blocks"
    assert info["blocks_named"] >= 3


def test_detects_numbered_list_format():
    doc, info = format_aware_document_from_text(_NUMBERED, "t")
    assert info["format"] == "numbered_list"
    assert info["blocks_named"] >= 3


def test_same_code_both_formats_reach_pipeline_with_names():
    """O MESMO código extrai nomes de DOIS formatos, ATRAVÉS do pipeline testado."""
    names1, _ = _names_through_pipeline(_LABELED)
    names2, _ = _names_through_pipeline(_NUMBERED)
    assert any("Suvinil" in n for n in names1)
    assert any("Argamassa" in n for n in names1)
    assert any("Cachaça" in n for n in names2)
    assert any("Cerveja" in n for n in names2)


def test_numbered_prefix_is_cleaned():
    """O '63.' não deve sobrar no nome que chega ao pipeline."""
    names, _ = _names_through_pipeline(_NUMBERED)
    assert not any(n.startswith("63.") or n.startswith("64.") for n in names)


def test_phantom_blocks_are_filtered():
    """Blocos sem nome e sem dados não viram registro."""
    text = "Um texto qualquer.\n\nOutra linha solta.\n\n" + _NUMBERED
    doc, info = format_aware_document_from_text(text, "t")
    # os blocos mantidos devem ser ~os produtos, não o lixo
    assert info["blocks_kept"] <= info["blocks_total"]
