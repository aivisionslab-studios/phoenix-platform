"""Testes da Fase 9 do "Document Pipeline V2"
(phoenix_kernel/documents/identity_engine.py) - Identity/Merge/Dedup: quais
Records representam a MESMA entidade real, sem nunca apagar/alterar um
Record original. Ver PHX-NEW no topo daquele arquivo pro contexto e
princípios completos (EAN válido idêntico é o sinal mais forte; EAN válido
diferente e pack_count divergente são BLOQUEIOS que nunca fundem
automaticamente; NCM nunca é identidade sozinho; similaridade textual só
sinaliza, nunca decide; a Fase 6 é reaproveitada integralmente pro cálculo
de confiança por campo depois do merge).

Os cenários abaixo são exatamente os pedidos pelo usuário ao fechar o
desenho da Fase 9, incluindo os dois mais importantes: "merge nunca
modifica Record original" e "A==B e B==C vira um cluster [A,B,C]"."""
from __future__ import annotations

from phoenix_kernel.documents.evidence_engine import build_field_evidence
from phoenix_kernel.documents.identity_engine import (
    IdentityStatus,
    RecordCluster,
    build_canonical_record,
    compare_records,
    find_candidate_pairs,
    resolve_identity,
)
from phoenix_kernel.documents.normalized import Block, BlockType, Candidate, Record

# Dois EANs-13 VÁLIDOS reais, já usados/confirmados nos testes da Fase 4/6
# deste mesmo repositório (dígito verificador batendo de verdade).
_EAN_A = "4006381333931"
_EAN_B = "7891019125302"
_EAN_B_INVALID = "7891019125301"  # mesmo prefixo, último dígito quebra o checksum


def _record(record_id: str, block_ids: list[str], candidate_ids: list[str]) -> Record:
    return Record(record_id=record_id, block_ids=block_ids, candidate_ids=candidate_ids)


def _ean_candidate(cid: str, block_id: str, value: str, valid: bool = True, confidence: float = 0.98) -> Candidate:
    return Candidate(id=cid, field_type="ean", raw_value=value, block_id=block_id,
                      normalized_value=value if valid else None, valid=valid, confidence=confidence,
                      method="label+checksum")


def _ncm_candidate(cid: str, block_id: str, value: str) -> Candidate:
    return Candidate(id=cid, field_type="ncm", raw_value=value, block_id=block_id,
                      normalized_value=value, valid=True, confidence=0.9, method="label")


def _price_candidate(cid: str, block_id: str, value: float) -> Candidate:
    return Candidate(id=cid, field_type="price", raw_value=str(value), block_id=block_id,
                      normalized_value=value, valid=True, confidence=0.95, method="label")


def _weight_candidate(cid: str, block_id: str, normalized: float, unit: str, original_unit: str, parsed: float) -> Candidate:
    return Candidate(id=cid, field_type="weight", raw_value=f"{parsed}{original_unit}", block_id=block_id,
                      normalized_value=normalized, unit=unit, original_unit=original_unit, parsed_value=parsed,
                      valid=True, confidence=0.85, method="label")


# ---------------------------------------------------------------------------
# 1/2/3 - EAN válido é o sinal mais forte, e o bloqueio mais forte
# ---------------------------------------------------------------------------

def test_same_valid_ean_is_auto_merge():
    blocks = {"b1": Block(id="b1", type=BlockType.PARAGRAPH, order=0, text_raw=f"EAN: {_EAN_A}"),
              "b2": Block(id="b2", type=BlockType.PARAGRAPH, order=1, text_raw=f"EAN: {_EAN_A}")}
    candidates = {"c1": _ean_candidate("c1", "b1", _EAN_A), "c2": _ean_candidate("c2", "b2", _EAN_A)}
    record_a = _record("rA", ["b1"], ["c1"])
    record_b = _record("rB", ["b2"], ["c2"])

    decision = compare_records(record_a, record_b, candidates, blocks)

    assert decision.decision == "auto_merge"
    assert not decision.blocking_signals
    assert any(s.type == "ean_equal_valid" for s in decision.signals)


def test_different_valid_ean_never_auto_merges():
    blocks = {"b1": Block(id="b1", type=BlockType.PARAGRAPH, order=0, text_raw=f"EAN: {_EAN_A}"),
              "b2": Block(id="b2", type=BlockType.PARAGRAPH, order=1, text_raw=f"EAN: {_EAN_B}")}
    candidates = {"c1": _ean_candidate("c1", "b1", _EAN_A), "c2": _ean_candidate("c2", "b2", _EAN_B)}
    record_a = _record("rA", ["b1"], ["c1"])
    record_b = _record("rB", ["b2"], ["c2"])

    decision = compare_records(record_a, record_b, candidates, blocks)

    assert decision.decision == "do_not_merge"
    assert any(s.type == "different_valid_ean" for s in decision.blocking_signals)


def test_same_name_and_ncm_but_different_ean_stays_separated():
    """NCM igual e nome idêntico NÃO revertem o bloqueio de EAN diferente
    - identidade nunca é decidida por NCM (pedido explícito: "NCM
    identifica classe fiscal, não produto")."""
    blocks = {
        "b1": Block(id="b1", type=BlockType.PARAGRAPH, order=0, text_raw=f"Cachaca Sao Francisco EAN: {_EAN_A} NCM: 22086000"),
        "b2": Block(id="b2", type=BlockType.PARAGRAPH, order=1, text_raw=f"Cachaca Sao Francisco EAN: {_EAN_B} NCM: 22086000"),
    }
    candidates = {
        "c1": _ean_candidate("c1", "b1", _EAN_A), "c1n": _ncm_candidate("c1n", "b1", "22086000"),
        "c2": _ean_candidate("c2", "b2", _EAN_B), "c2n": _ncm_candidate("c2n", "b2", "22086000"),
    }
    record_a = _record("rA", ["b1"], ["c1", "c1n"])
    record_b = _record("rB", ["b2"], ["c2", "c2n"])

    decision = compare_records(record_a, record_b, candidates, blocks)

    assert decision.decision == "do_not_merge"
    assert any(s.type == "different_valid_ean" for s in decision.blocking_signals)


# ---------------------------------------------------------------------------
# 4/5 - fingerprint textual: sinaliza, nunca decide sozinho
# ---------------------------------------------------------------------------

def test_same_product_written_differently_is_flagged_as_duplicate_candidate_not_silently_merged():
    """"Coca Cola 350ml" vs "Coca-Cola Lata 350 ml" - sem EAN nenhum dos
    dois lados. Similaridade de nome + quantidade equivalente têm que
    sinalizar um candidato forte a duplicata (probable/possible), mas
    NUNCA um `auto_merge` silencioso (isso exigiria confirmação mais
    forte, ex: EAN)."""
    blocks = {"b1": Block(id="b1", type=BlockType.PARAGRAPH, order=0, text_raw="Coca Cola 350ml"),
              "b2": Block(id="b2", type=BlockType.PARAGRAPH, order=1, text_raw="Coca-Cola Lata 350 ml")}
    record_a = _record("rA", ["b1"], [])
    record_b = _record("rB", ["b2"], [])

    decision = compare_records(record_a, record_b, {}, blocks)

    assert decision.decision in ("probable_duplicate", "possible_duplicate")
    assert not decision.blocking_signals


def test_same_brand_different_variant_stays_separated():
    """"Pringles Original 165g" vs "Pringles Paprika 165g" - altíssima
    similaridade textual, mas são produtos DIFERENTES (variante diferente)
    - o peso de similaridade textual sozinho nunca deve alcançar um
    patamar de duplicata forte aqui."""
    blocks = {"b1": Block(id="b1", type=BlockType.PARAGRAPH, order=0, text_raw="Pringles Original 165g"),
              "b2": Block(id="b2", type=BlockType.PARAGRAPH, order=1, text_raw="Pringles Paprika 165g")}
    record_a = _record("rA", ["b1"], [])
    record_b = _record("rB", ["b2"], [])

    decision = compare_records(record_a, record_b, {}, blocks)

    assert decision.decision in ("do_not_merge", "possible_duplicate")
    assert decision.decision != "auto_merge"


# ---------------------------------------------------------------------------
# 6 - unidade vs caixa fechada: bloqueio, mesmo sem EAN
# ---------------------------------------------------------------------------

def test_single_unit_vs_closed_box_of_twelve_stays_separated():
    blocks = {"b1": Block(id="b1", type=BlockType.PARAGRAPH, order=0, text_raw="Cachaca Sao Francisco 970ml"),
              "b2": Block(id="b2", type=BlockType.PARAGRAPH, order=1, text_raw="Cachaca Sao Francisco 970ml Caixa com 12")}
    record_a = _record("rA", ["b1"], [])
    record_b = _record("rB", ["b2"], [])

    decision = compare_records(record_a, record_b, {}, blocks)

    assert decision.decision == "do_not_merge"
    assert any(s.type == "different_pack_count" for s in decision.blocking_signals)


# ---------------------------------------------------------------------------
# 7 - 600g == 0.600kg (reaproveita a canonicalização dimensional da Fase 3)
# ---------------------------------------------------------------------------

def test_weight_equivalence_reuses_dimensional_canonicalization():
    blocks = {"b1": Block(id="b1", type=BlockType.PARAGRAPH, order=0, text_raw="Produto Generico Peso: 600g"),
              "b2": Block(id="b2", type=BlockType.PARAGRAPH, order=1, text_raw="Produto Generico Peso: 0,600 kg")}
    candidates = {
        "c1": _weight_candidate("c1", "b1", normalized=0.6, unit="kg", original_unit="g", parsed=600.0),
        "c2": _weight_candidate("c2", "b2", normalized=0.6, unit="kg", original_unit="kg", parsed=0.6),
    }
    record_a = _record("rA", ["b1"], ["c1"])
    record_b = _record("rB", ["b2"], ["c2"])

    decision = compare_records(record_a, record_b, candidates, blocks)

    assert any(s.type == "weight_equal" for s in decision.signals)
    assert not any(s.type == "weight_different" for s in decision.signals)


# ---------------------------------------------------------------------------
# 8 - repetição da mesma origem não vira fonte independente, mesmo após o merge
# ---------------------------------------------------------------------------

def test_same_evidence_repeated_across_five_records_does_not_inflate_after_merge():
    same_text = f"EAN: {_EAN_A}"
    blocks = {f"b{i}": Block(id=f"b{i}", type=BlockType.PARAGRAPH, order=i, text_raw=same_text) for i in range(5)}
    candidates = {f"c{i}": _ean_candidate(f"c{i}", f"b{i}", _EAN_A, confidence=0.98) for i in range(5)}
    records_by_id = {f"r{i}": _record(f"r{i}", [f"b{i}"], [f"c{i}"]) for i in range(5)}
    cluster = RecordCluster(cluster_id="cluster_test", record_ids=list(records_by_id.keys()), identity_confidence=1.0)

    canonical = build_canonical_record(cluster, records_by_id, candidates, blocks)

    fe = canonical.fields["ean"]
    assert fe.status == "probable"  # NUNCA "confirmed" só por repetição do mesmo trecho
    assert len(fe.evidence) == 5  # todas as 5 evidências brutas continuam preservadas


# ---------------------------------------------------------------------------
# 9 - identidade confirmada, campo divergente vira conflict (não impede o merge)
# ---------------------------------------------------------------------------

def test_two_identical_records_with_different_price_yields_single_canonical_with_price_conflict():
    blocks = {"b1": Block(id="b1", type=BlockType.PARAGRAPH, order=0, text_raw=f"EAN: {_EAN_A} Preco: R$ 19,90"),
              "b2": Block(id="b2", type=BlockType.PARAGRAPH, order=1, text_raw=f"EAN: {_EAN_A} Preco: R$ 21,90")}
    candidates = {
        "c1": _ean_candidate("c1", "b1", _EAN_A), "c1p": _price_candidate("c1p", "b1", 19.90),
        "c2": _ean_candidate("c2", "b2", _EAN_A), "c2p": _price_candidate("c2p", "b2", 21.90),
    }
    records_by_id = {"rA": _record("rA", ["b1"], ["c1", "c1p"]), "rB": _record("rB", ["b2"], ["c2", "c2p"])}
    cluster = RecordCluster(cluster_id="cluster_test", record_ids=["rA", "rB"], identity_confidence=1.0)

    canonical = build_canonical_record(cluster, records_by_id, candidates, blocks)

    assert len(canonical.source_record_ids) == 2
    assert canonical.fields["ean"].status in ("confirmed", "probable")
    assert canonical.fields["price"].status == "conflict"
    assert "price" in canonical.conflicts
    assert "ean" not in canonical.conflicts


# ---------------------------------------------------------------------------
# 10 - EAN inválido preservado na auditoria, nunca desaparece
# ---------------------------------------------------------------------------

def test_invalid_and_valid_ean_across_records_both_preserved_valid_wins_status():
    blocks = {"b1": Block(id="b1", type=BlockType.PARAGRAPH, order=0, text_raw=f"EAN: {_EAN_B}"),
              "b2": Block(id="b2", type=BlockType.PARAGRAPH, order=1, text_raw=f"EAN: {_EAN_B_INVALID}")}
    candidates = {
        "c1": _ean_candidate("c1", "b1", _EAN_B, valid=True),
        "c2": _ean_candidate("c2", "b2", _EAN_B_INVALID, valid=False, confidence=0.55),
    }
    records_by_id = {"rA": _record("rA", ["b1"], ["c1"]), "rB": _record("rB", ["b2"], ["c2"])}
    cluster = RecordCluster(cluster_id="cluster_test", record_ids=["rA", "rB"], identity_confidence=1.0)

    canonical = build_canonical_record(cluster, records_by_id, candidates, blocks)

    fe = canonical.fields["ean"]
    assert fe.status == "probable"  # só a leitura válida conta como fonte de valor
    assert fe.value == _EAN_B
    assert len(fe.evidence) == 2  # a leitura inválida continua na auditoria
    assert any(e.valid is False for e in fe.evidence)


# ---------------------------------------------------------------------------
# 11 - A==B e B==C vira UM cluster [A,B,C], nunca merge par-a-par destrutivo
# ---------------------------------------------------------------------------

def test_transitive_matches_form_a_single_cluster():
    blocks = {f"b{i}": Block(id=f"b{i}", type=BlockType.PARAGRAPH, order=i, text_raw=f"EAN: {_EAN_A}") for i in range(3)}
    candidates = {f"c{i}": _ean_candidate(f"c{i}", f"b{i}", _EAN_A) for i in range(3)}
    records = [_record(f"r{i}", [f"b{i}"], [f"c{i}"]) for i in range(3)]

    resolution = resolve_identity(records, candidates, blocks)

    assert len(resolution.clusters) == 1
    assert sorted(resolution.clusters[0].record_ids) == ["r0", "r1", "r2"]
    assert len(resolution.canonical_records) == 1
    assert all(resolution.identity_status_by_record[r.record_id] == IdentityStatus.DUPLICATE_CONFIRMED.value for r in records)


# ---------------------------------------------------------------------------
# 12 - sem sinal suficiente, permanece separado
# ---------------------------------------------------------------------------

def test_records_without_any_strong_signal_stay_unique():
    blocks = {"b1": Block(id="b1", type=BlockType.PARAGRAPH, order=0, text_raw="Um parafuso qualquer sem nome claro"),
              "b2": Block(id="b2", type=BlockType.PARAGRAPH, order=1, text_raw="Uma correia totalmente diferente")}
    records = [_record("rA", ["b1"], []), _record("rB", ["b2"], [])]

    resolution = resolve_identity(records, {}, blocks)

    assert resolution.clusters == []
    # PHX-FIX (hotfix): mesmo sem cluster nenhum, todo record de entrada
    # ainda vira um CanonicalRecord singleton - "unique" não é mais
    # sinônimo de "sem CanonicalRecord".
    assert len(resolution.canonical_records) == 2
    assert {cr.canonical_id for cr in resolution.canonical_records} == {"cr_rA", "cr_rB"}
    assert all(cr.merge_method == "single_record" for cr in resolution.canonical_records)
    assert resolution.identity_status_by_record["rA"] == IdentityStatus.UNIQUE.value
    assert resolution.identity_status_by_record["rB"] == IdentityStatus.UNIQUE.value


# ---------------------------------------------------------------------------
# 15/16/17/18 - PHX-FIX (hotfix pedido pelo usuário 29/08, depois de validar
# a Fase 10 contra o XLSX real): resolve_identity DEVE materializar um
# CanonicalRecord para TODO record de entrada, não só pros clusters de
# auto_merge - "N Records de entrada -> N ou menos CanonicalRecords de
# saída", nenhum record desaparece, cada source_record_id aparece em
# exatamente um CanonicalRecord.
# ---------------------------------------------------------------------------

def test_three_unique_records_produce_three_canonical_records():
    blocks = {
        "b1": Block(id="b1", type=BlockType.PARAGRAPH, order=0, text_raw="Produto Alfa totalmente distinto"),
        "b2": Block(id="b2", type=BlockType.PARAGRAPH, order=1, text_raw="Produto Beta totalmente distinto"),
        "b3": Block(id="b3", type=BlockType.PARAGRAPH, order=2, text_raw="Produto Gama totalmente distinto"),
    }
    records = [_record("r1", ["b1"], []), _record("r2", ["b2"], []), _record("r3", ["b3"], [])]

    resolution = resolve_identity(records, {}, blocks)

    assert resolution.clusters == []
    assert len(resolution.canonical_records) == 3
    assert {cr.canonical_id for cr in resolution.canonical_records} == {"cr_r1", "cr_r2", "cr_r3"}
    all_source_ids = [rid for cr in resolution.canonical_records for rid in cr.source_record_ids]
    assert sorted(all_source_ids) == ["r1", "r2", "r3"]  # nenhum duplicado, nenhum ausente


def test_two_unique_plus_one_cluster_of_two_produces_three_canonical_records():
    blocks = {
        "b1": Block(id="b1", type=BlockType.PARAGRAPH, order=0, text_raw="Produto solo Um"),
        "b2": Block(id="b2", type=BlockType.PARAGRAPH, order=1, text_raw=f"EAN: {_EAN_A}"),
        "b3": Block(id="b3", type=BlockType.PARAGRAPH, order=2, text_raw=f"EAN: {_EAN_A}"),
        "b4": Block(id="b4", type=BlockType.PARAGRAPH, order=3, text_raw="Produto solo Dois"),
    }
    candidates = {
        "c2": _ean_candidate("c2", "b2", _EAN_A),
        "c3": _ean_candidate("c3", "b3", _EAN_A),
    }
    records = [
        _record("r1", ["b1"], []),
        _record("r2", ["b2"], ["c2"]),
        _record("r3", ["b3"], ["c3"]),
        _record("r4", ["b4"], []),
    ]

    resolution = resolve_identity(records, candidates, blocks)

    assert len(resolution.clusters) == 1
    assert sorted(resolution.clusters[0].record_ids) == ["r2", "r3"]
    # 2 singletons (r1, r4) + 1 consolidado (r2+r3) = 3 CanonicalRecords,
    # nunca 4 (nenhum record duplicado) nem 2 (nenhum record desaparecido).
    assert len(resolution.canonical_records) == 3

    all_source_ids = [rid for cr in resolution.canonical_records for rid in cr.source_record_ids]
    assert sorted(all_source_ids) == ["r1", "r2", "r3", "r4"]

    # cada source_record_id aparece em EXATAMENTE um CanonicalRecord.
    owners_by_record = {}
    for cr in resolution.canonical_records:
        for rid in cr.source_record_ids:
            owners_by_record.setdefault(rid, []).append(cr.canonical_id)
    assert all(len(owners) == 1 for owners in owners_by_record.values())


def test_singleton_canonical_record_preserves_evidence_like_a_normal_merge():
    blocks = {"b1": Block(id="b1", type=BlockType.PARAGRAPH, order=0, text_raw=f"EAN: {_EAN_A}")}
    candidates = {"c1": _ean_candidate("c1", "b1", _EAN_A)}
    records = [_record("r1", ["b1"], ["c1"])]

    resolution = resolve_identity(records, candidates, blocks)

    assert len(resolution.canonical_records) == 1
    canonical = resolution.canonical_records[0]
    assert canonical.canonical_id == "cr_r1"
    assert canonical.source_record_ids == ["r1"]
    assert canonical.merge_method == "single_record"
    # Evidence recalculada exatamente como num merge de verdade - mesmo
    # `build_field_evidence` da Fase 6, sem atalho nenhum pro caso singleton.
    fe = canonical.fields["ean"]
    assert fe.value == _EAN_A
    assert fe.status in ("probable", "confirmed", "ambiguous")
    assert len(fe.evidence) == 1


# ---------------------------------------------------------------------------
# 13/14 - proveniência preservada, merge NUNCA modifica o Record original
# ---------------------------------------------------------------------------

def test_merge_never_modifies_original_records_and_preserves_order():
    blocks = {"b1": Block(id="b1", type=BlockType.PARAGRAPH, order=0, text_raw=f"EAN: {_EAN_A}"),
              "b2": Block(id="b2", type=BlockType.PARAGRAPH, order=1, text_raw=f"EAN: {_EAN_A}")}
    candidates = {"c1": _ean_candidate("c1", "b1", _EAN_A), "c2": _ean_candidate("c2", "b2", _EAN_A)}
    record_a = _record("rA", ["b1"], ["c1"])
    record_b = _record("rB", ["b2"], ["c2"])
    records_by_id = {"rA": record_a, "rB": record_b}

    snapshot_a = record_a.to_dict()
    snapshot_b = record_b.to_dict()

    cluster = RecordCluster(cluster_id="cluster_test", record_ids=["rA", "rB"], identity_confidence=1.0)
    canonical = build_canonical_record(cluster, records_by_id, candidates, blocks)

    assert record_a.to_dict() == snapshot_a  # Record original intocado
    assert record_b.to_dict() == snapshot_b
    assert canonical.source_record_ids == ["rA", "rB"]  # ordem preservada


# ---------------------------------------------------------------------------
# blocking / escala - não compara tudo contra tudo
# ---------------------------------------------------------------------------

def test_find_candidate_pairs_only_compares_records_sharing_a_bucket():
    blocks = {
        "b1": Block(id="b1", type=BlockType.PARAGRAPH, order=0, text_raw=f"EAN: {_EAN_A}"),
        "b2": Block(id="b2", type=BlockType.PARAGRAPH, order=1, text_raw=f"EAN: {_EAN_A}"),
        "b3": Block(id="b3", type=BlockType.PARAGRAPH, order=2, text_raw="Produto completamente nao relacionado"),
    }
    candidates = {"c1": _ean_candidate("c1", "b1", _EAN_A), "c2": _ean_candidate("c2", "b2", _EAN_A)}
    records = [_record("rA", ["b1"], ["c1"]), _record("rB", ["b2"], ["c2"]), _record("rC", ["b3"], [])]

    pairs = find_candidate_pairs(records, candidates, blocks)

    assert pairs == [("rA", "rB")]  # rC não compartilha bucket nenhum com rA/rB


def test_field_evidence_after_merge_matches_direct_evidence_engine_call():
    """A Fase 9 não reimplementa nada da Fase 6 - o resultado de
    `build_canonical_record` pra um único record "cluster" de 1 elemento
    (via chamada direta, ignorando o filtro normal de >=2 membros) tem que
    bater exatamente com uma chamada direta a `build_field_evidence`."""
    blocks = {"b1": Block(id="b1", type=BlockType.PARAGRAPH, order=0, text_raw=f"EAN: {_EAN_A}")}
    candidates = {"c1": _ean_candidate("c1", "b1", _EAN_A)}
    record = _record("rA", ["b1"], ["c1"])

    direct = build_field_evidence(Record(record_id="x", candidate_ids=["c1"]), candidates, blocks)
    cluster = RecordCluster(cluster_id="x", record_ids=["rA"], identity_confidence=1.0)
    canonical = build_canonical_record(cluster, {"rA": record}, candidates, blocks)

    assert canonical.fields["ean"].status == direct[0].status
    assert canonical.fields["ean"].value == direct[0].value
