"""Testes da Fase 6 do "Document Pipeline V2" (phoenix_kernel/documents/
evidence_engine.py) - agrega Candidate(s) referenciados por um Record numa
FieldEvidence por campo, com um vocabulário fechado de status (confirmed/
probable/ambiguous/conflict/invalid). Ver PHX-NEW no topo daquele arquivo
pro contexto e princípios completos (zero LLM/OCR ainda; nunca soma
confiança ingenuamente - fontes com o mesmo `source_origin_hash` colapsam
numa só antes de agregar).

O teste mais importante deste arquivo é
`test_duplicate_same_text_elsewhere_does_not_inflate_to_confirmed` -
pedido explícito do usuário: "três ocorrências repetidas do mesmo trecho
não valem três fontes independentes"."""
from __future__ import annotations

from phoenix_kernel.documents.evidence_engine import (
    build_evidence_for_document,
    build_field_evidence,
)
from phoenix_kernel.documents.normalized import (
    Block,
    BlockType,
    Candidate,
    NormalizedDocument,
    Record,
)


def _doc(blocks: list[Block]) -> NormalizedDocument:
    return NormalizedDocument(document_id="doc1", source_name="teste.docx", source_type="docx", blocks=blocks)


def _record(record_id: str, candidate_ids: list[str]) -> Record:
    return Record(record_id=record_id, candidate_ids=candidate_ids)


# ---------------------------------------------------------------------------
# confirmed / probable / ambiguous (valor único)
# ---------------------------------------------------------------------------

def test_two_independent_sources_agreeing_is_confirmed():
    blocks = [
        Block(id="b1", type=BlockType.PARAGRAPH, order=0, text_raw="EAN: 4006381333931"),
        Block(id="b2", type=BlockType.TABLE, order=1, headers=["EAN"], rows=[["4006381333931"]]),
    ]
    candidates = {
        "c1": Candidate(id="c1", field_type="ean", raw_value="4006381333931", block_id="b1",
                         normalized_value="4006381333931", valid=True, confidence=0.99, method="label+checksum"),
        "c2": Candidate(id="c2", field_type="ean", raw_value="4006381333931", block_id="b2",
                         normalized_value="4006381333931", valid=True, confidence=1.0, method="table_header"),
    }
    doc = _doc(blocks)
    record = _record("r0", ["c1", "c2"])
    results = build_field_evidence(record, candidates, {b.id: b for b in blocks})

    assert len(results) == 1
    fe = results[0]
    assert fe.status == "confirmed"
    assert fe.value == "4006381333931"
    assert fe.final_confidence == 0.995  # média das duas fontes DISTINTAS, sem inflar
    assert len(fe.evidence) == 2


def test_duplicate_same_text_elsewhere_does_not_inflate_to_confirmed():
    """Achado real (Fase 2/5): a conversa repete/revisa as mesmas seções
    em outro lugar do documento - o MESMO parágrafo aparecendo duas vezes
    não pode virar "2 fontes independentes concordando"."""
    same_text = "EAN: 4006381333931"
    blocks = [
        Block(id="b1", type=BlockType.PARAGRAPH, order=0, text_raw=same_text),
        Block(id="b9", type=BlockType.PARAGRAPH, order=50, text_raw=same_text),  # bloco duplicado em outro lugar
    ]
    candidates = {
        "c1": Candidate(id="c1", field_type="ean", raw_value="4006381333931", block_id="b1",
                         normalized_value="4006381333931", valid=True, confidence=0.98, method="label+checksum"),
        "c2": Candidate(id="c2", field_type="ean", raw_value="4006381333931", block_id="b9",
                         normalized_value="4006381333931", valid=True, confidence=0.98, method="label+checksum"),
    }
    doc = _doc(blocks)
    record = _record("r0", ["c1", "c2"])
    results = build_field_evidence(record, candidates, {b.id: b for b in blocks})

    assert len(results) == 1
    fe = results[0]
    assert fe.status == "probable"  # NÃO "confirmed" - mesma fonte repetida, não duas fontes
    assert fe.final_confidence == 0.98
    assert len(fe.evidence) == 2  # as duas evidências brutas continuam preservadas


def test_single_source_high_confidence_is_probable():
    blocks = [Block(id="b1", type=BlockType.PARAGRAPH, order=0, text_raw="NCM: 32091010")]
    candidates = {
        "c1": Candidate(id="c1", field_type="ncm", raw_value="32091010", block_id="b1",
                         normalized_value="32091010", valid=True, confidence=0.9, method="label"),
    }
    record = _record("r0", ["c1"])
    results = build_field_evidence(record, candidates, {b.id: b for b in blocks})

    assert results[0].status == "probable"
    assert results[0].final_confidence == 0.9


def test_single_source_low_confidence_is_ambiguous():
    """Cenário sintético - os detectores atuais da Fase 4 nunca produzem
    confidence < 0.7 num candidato válido (ver limitação documentada no
    módulo), então este teste força o caso à mão pra garantir que o
    status "ambiguous" existe e funciona, pronto pro dia em que um
    detector mais fraco (ou uma leitura de OCR/visão) existir."""
    blocks = [Block(id="b1", type=BlockType.PARAGRAPH, order=0, text_raw="talvez um preço: 10")]
    candidates = {
        "c1": Candidate(id="c1", field_type="price", raw_value="10", block_id="b1",
                         normalized_value=10.0, valid=True, confidence=0.5, method="heuristic-fraca"),
    }
    record = _record("r0", ["c1"])
    results = build_field_evidence(record, candidates, {b.id: b for b in blocks})

    assert results[0].status == "ambiguous"
    assert results[0].final_confidence == 0.5


def test_weight_in_kg_and_grams_for_same_product_is_confirmed_not_conflict():
    """PHX-FIX (achado real testando esta própria fase contra os
    documentos reais): "Peso: 0,600 kg" e "Peso: 600g" no MESMO record
    viravam "conflict" antes da correção dimensional no Normalizer/
    Candidate Engine - agora os dois convergem pro mesmo valor canônico
    (0.6 kg) e o campo fecha como concordância, não conflito."""
    from phoenix_kernel.documents.candidate_engine import find_candidates_in_text

    b1_candidates = find_candidates_in_text("Peso: 0,600 kg", "b1")
    b2_candidates = find_candidates_in_text("Peso: 600g", "b2")
    candidates = {c.id: c for c in [
        *[Candidate(**{**c.to_dict(), "id": "c1"}) for c in b1_candidates if c.field_type == "weight"],
        *[Candidate(**{**c.to_dict(), "id": "c2"}) for c in b2_candidates if c.field_type == "weight"],
    ]}
    blocks = {
        "b1": Block(id="b1", type=BlockType.PARAGRAPH, order=0, text_raw="Peso: 0,600 kg"),
        "b2": Block(id="b2", type=BlockType.PARAGRAPH, order=1, text_raw="Peso: 600g"),
    }
    record = _record("r0", ["c1", "c2"])
    results = build_field_evidence(record, candidates, blocks)

    assert len(results) == 1
    fe = results[0]
    assert fe.status in ("confirmed", "probable")  # nunca mais "conflict"
    assert fe.value == 0.6
    assert {e.original_unit for e in fe.evidence} == {"kg", "g"}  # auditoria preserva a unidade original de cada um


# ---------------------------------------------------------------------------
# conflict
# ---------------------------------------------------------------------------

def test_two_different_valid_values_is_conflict():
    blocks = [
        Block(id="b1", type=BlockType.PARAGRAPH, order=0, text_raw="Preço: R$ 19,90"),
        Block(id="b2", type=BlockType.PARAGRAPH, order=1, text_raw="Preço: R$ 24,90"),
    ]
    candidates = {
        "c1": Candidate(id="c1", field_type="price", raw_value="19,90", block_id="b1",
                         normalized_value=19.90, valid=True, confidence=0.95, method="label"),
        "c2": Candidate(id="c2", field_type="price", raw_value="24,90", block_id="b2",
                         normalized_value=24.90, valid=True, confidence=0.95, method="label"),
    }
    record = _record("r0", ["c1", "c2"])
    results = build_field_evidence(record, candidates, {b.id: b for b in blocks})

    assert len(results) == 1
    fe = results[0]
    assert fe.status == "conflict"
    assert fe.value is None
    assert fe.final_confidence is None
    assert {v.value for v in fe.values} == {19.90, 24.90}
    assert all(v.evidence_count == 1 for v in fe.values)


def test_conflict_evidence_count_deduplicates_repeated_source_per_value():
    same_text = "Preço: R$ 19,90"
    blocks = [
        Block(id="b1", type=BlockType.PARAGRAPH, order=0, text_raw=same_text),
        Block(id="b2", type=BlockType.PARAGRAPH, order=1, text_raw=same_text),  # duplicado, mesma fonte
        Block(id="b3", type=BlockType.PARAGRAPH, order=2, text_raw="Preço: R$ 24,90"),
    ]
    candidates = {
        "c1": Candidate(id="c1", field_type="price", raw_value="19,90", block_id="b1",
                         normalized_value=19.90, valid=True, confidence=0.95, method="label"),
        "c2": Candidate(id="c2", field_type="price", raw_value="19,90", block_id="b2",
                         normalized_value=19.90, valid=True, confidence=0.95, method="label"),
        "c3": Candidate(id="c3", field_type="price", raw_value="24,90", block_id="b3",
                         normalized_value=24.90, valid=True, confidence=0.95, method="label"),
    }
    record = _record("r0", ["c1", "c2", "c3"])
    results = build_field_evidence(record, candidates, {b.id: b for b in blocks})

    fe = results[0]
    counts = {v.value: v.evidence_count for v in fe.values}
    assert counts[19.90] == 1  # as duas evidências de 19,90 vêm do MESMO texto - 1 fonte só
    assert counts[24.90] == 1


# ---------------------------------------------------------------------------
# invalid
# ---------------------------------------------------------------------------

def test_only_invalid_candidates_yields_invalid_status_and_preserves_evidence():
    blocks = [Block(id="b1", type=BlockType.PARAGRAPH, order=0, text_raw="EAN: 7891019125301")]
    candidates = {
        "c1": Candidate(id="c1", field_type="ean", raw_value="7891019125301", block_id="b1",
                         normalized_value=None, valid=False, confidence=0.55, method="label+checksum"),
    }
    record = _record("r0", ["c1"])
    results = build_field_evidence(record, candidates, {b.id: b for b in blocks})

    assert len(results) == 1
    fe = results[0]
    assert fe.status == "invalid"
    assert fe.value is None
    assert fe.final_confidence == 0.0
    assert len(fe.evidence) == 1
    assert fe.evidence[0].valid is False
    assert fe.evidence[0].value == "7891019125301"  # valor bruto preservado, nunca descartado


# ---------------------------------------------------------------------------
# rastreabilidade / categorização de fonte
# ---------------------------------------------------------------------------

def test_evidence_entries_carry_full_traceability_fields():
    blocks = [Block(id="b1", type=BlockType.PARAGRAPH, order=0, text_raw="NCM: 32091010")]
    candidates = {
        "c1": Candidate(id="c1", field_type="ncm", raw_value="32091010", block_id="b1",
                         normalized_value="32091010", valid=True, confidence=0.9, method="label"),
    }
    record = _record("r7", ["c1"])
    results = build_field_evidence(record, candidates, {b.id: b for b in blocks})
    entry = results[0].evidence[0]

    assert entry.candidate_id == "c1"
    assert entry.source_block == "b1"
    assert entry.source_record == "r7"
    assert entry.source_method == "label"
    assert entry.source_origin_hash is not None


def test_table_block_source_is_table_paragraph_source_is_text():
    blocks = [
        Block(id="b1", type=BlockType.PARAGRAPH, order=0, text_raw="EAN: 4006381333931"),
        Block(id="b2", type=BlockType.TABLE, order=1, headers=["EAN"], rows=[["4006381333931"]]),
    ]
    candidates = {
        "c1": Candidate(id="c1", field_type="ean", raw_value="4006381333931", block_id="b1",
                         normalized_value="4006381333931", valid=True, confidence=0.98, method="label+checksum"),
        "c2": Candidate(id="c2", field_type="ean", raw_value="4006381333931", block_id="b2",
                         normalized_value="4006381333931", valid=True, confidence=0.97, method="table_header"),
    }
    record = _record("r0", ["c1", "c2"])
    results = build_field_evidence(record, candidates, {b.id: b for b in blocks})
    sources = {e.source_block: e.source for e in results[0].evidence}

    assert sources["b1"] == "text"
    assert sources["b2"] == "table"


# ---------------------------------------------------------------------------
# múltiplos campos / documento inteiro
# ---------------------------------------------------------------------------

def test_multiple_field_types_in_same_record_each_get_their_own_field_evidence():
    blocks = [Block(id="b1", type=BlockType.PARAGRAPH, order=0, text_raw="NCM: 32091010 | Preço: R$ 10,00")]
    candidates = {
        "c1": Candidate(id="c1", field_type="ncm", raw_value="32091010", block_id="b1",
                         normalized_value="32091010", valid=True, confidence=0.9, method="label"),
        "c2": Candidate(id="c2", field_type="price", raw_value="10,00", block_id="b1",
                         normalized_value=10.0, valid=True, confidence=0.95, method="label"),
    }
    record = _record("r0", ["c1", "c2"])
    results = build_field_evidence(record, candidates, {b.id: b for b in blocks})

    field_types = {fe.field_type for fe in results}
    assert field_types == {"ncm", "price"}


def test_build_evidence_for_document_maps_by_record_id():
    blocks = [
        Block(id="b1", type=BlockType.PARAGRAPH, order=0, text_raw="1. Produto A"),
        Block(id="b2", type=BlockType.PARAGRAPH, order=1, text_raw="NCM: 32091010"),
    ]
    doc = _doc(blocks)
    candidate = Candidate(id="c1", field_type="ncm", raw_value="32091010", block_id="b2",
                           normalized_value="32091010", valid=True, confidence=0.9, method="label")
    record = _record("r0000", ["c1"])

    result = build_evidence_for_document(doc, [candidate], [record])

    assert list(result.keys()) == ["r0000"]
    assert result["r0000"][0].field_type == "ncm"


def test_record_with_no_matching_candidates_yields_no_field_evidence():
    doc = _doc([])
    record = _record("r0", ["c_inexistente"])
    result = build_evidence_for_document(doc, [], [record])
    assert result["r0"] == []


# ---------------------------------------------------------------------------
# roundtrip to_dict/from_dict
# ---------------------------------------------------------------------------

def test_field_evidence_roundtrip_through_dict():
    from phoenix_kernel.documents.evidence_engine import FieldEvidence

    blocks = [Block(id="b1", type=BlockType.PARAGRAPH, order=0, text_raw="NCM: 32091010")]
    candidates = {
        "c1": Candidate(id="c1", field_type="ncm", raw_value="32091010", block_id="b1",
                         normalized_value="32091010", valid=True, confidence=0.9, method="label"),
    }
    record = _record("r0", ["c1"])
    original = build_field_evidence(record, candidates, {b.id: b for b in blocks})[0]

    restored = FieldEvidence.from_dict(original.to_dict())
    assert restored == original
