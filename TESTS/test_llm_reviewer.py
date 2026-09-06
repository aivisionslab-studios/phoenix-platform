"""Testes do revisor LLM — resolve só campos duvidosos, com trava anti-alucinação."""

import asyncio

import pytest

from phoenix_kernel.documents.evidence_engine import (
    EvidenceEntry, EvidenceStatus, FieldEvidence, ValueGroup,
)
from phoenix_kernel.documents.llm_reviewer import (
    apply_resolutions_to_evidence, review_conflicts,
)


def _conflict_field(record_id="r1", field_type="ncm", values=("111", "222")):
    return FieldEvidence(
        field_type=field_type,
        record_id=record_id,
        status=EvidenceStatus.CONFLICT.value,
        values=[ValueGroup(value=v, evidence_count=1) for v in values],
        evidence=[EvidenceEntry(candidate_id=f"c_{v}", source="doc", value=v, valid=True, confidence=0.5)
                  for v in values],
    )


def _confirmed_field(record_id="r2", field_type="ean"):
    return FieldEvidence(
        field_type=field_type, record_id=record_id,
        status=EvidenceStatus.CONFIRMED.value, value="7891234567895",
        final_confidence=0.99,
    )


def test_only_doubtful_fields_reach_the_llm():
    """Campos confirmed NÃO gastam chamada de LLM; só conflict/ambiguous."""
    calls = []

    async def ask(system, user):
        calls.append(user)
        return '{"selected_value": "111", "confidence": 0.9, "reason": "ok"}'

    ev = {
        "r1": [_conflict_field("r1", "ncm", ("111", "222"))],
        "r2": [_confirmed_field("r2")],  # não deve ir ao LLM
    }
    stats = asyncio.run(review_conflicts(ev, ask_llm=ask))
    assert stats.fields_reviewed == 1       # só o conflito
    assert len(calls) == 1                  # LLM chamado 1x, não 2x
    assert stats.fields_resolved == 1


def test_hallucinated_value_is_rejected():
    """Valor fora da allowlist é REJEITADO — campo segue para auditoria."""
    async def ask(system, user):
        # tenta um valor que NÃO está nas opções
        return '{"selected_value": "999_INVENTADO", "confidence": 0.99, "reason": "x"}'

    ev = {"r1": [_conflict_field("r1", "ncm", ("111", "222"))]}
    stats = asyncio.run(review_conflicts(ev, ask_llm=ask))
    assert stats.fields_reviewed == 1
    assert stats.fields_resolved == 0       # nada aplicado
    assert stats.fields_rejected == 1       # alucinação barrada


def test_valid_choice_is_applied_and_promotes_field():
    async def ask(system, user):
        return '{"selected_value": "222", "confidence": 0.95, "reason": "correto"}'

    ev = {"r1": [_conflict_field("r1", "ncm", ("111", "222"))]}
    stats = asyncio.run(review_conflicts(ev, ask_llm=ask))
    assert stats.fields_resolved == 1

    promoted = apply_resolutions_to_evidence(ev, stats)
    assert promoted == 1
    fe = ev["r1"][0]
    assert fe.status == EvidenceStatus.CONFIRMED.value  # promovido
    assert fe.value == "222"                            # valor escolhido
    assert fe.values is None                            # conflito zerado


def test_llm_failure_does_not_crash_pipeline():
    """Se a chamada ao LLM lança, o campo é rejeitado (vai pra auditoria),
    não derruba a revisão inteira."""
    async def ask(system, user):
        raise RuntimeError("modelo offline")

    ev = {"r1": [_conflict_field("r1", "ncm", ("111", "222"))]}
    stats = asyncio.run(review_conflicts(ev, ask_llm=ask))
    assert stats.fields_rejected == 1
    assert stats.fields_resolved == 0


def test_max_fields_limits_llm_calls():
    calls = []

    async def ask(system, user):
        calls.append(1)
        return '{"selected_value": "111", "confidence": 0.9, "reason": "ok"}'

    ev = {f"r{i}": [_conflict_field(f"r{i}", "ncm", ("111", "222"))] for i in range(10)}
    stats = asyncio.run(review_conflicts(ev, ask_llm=ask, max_fields=3))
    assert len(calls) == 3          # respeitou o teto de custo
    assert stats.fields_reviewed == 3


def test_evidence_view_indexes_by_record_id_so_promotion_works():
    """A view dos canonical precisa indexar por fe.record_id (não canonical_id),
    senão o revisor resolve mas apply_resolutions não promove nada."""
    from phoenix_kernel.documents.identity_engine import CanonicalRecord
    from phoenix_kernel.documents.llm_reviewer import (
        evidence_view_from_canonical, sync_canonical_conflicts,
    )

    fe = _conflict_field("r42", "ncm", ("111", "222"))
    cr = CanonicalRecord(
        canonical_id="cr_r42", source_record_ids=["r42"],
        merge_method="singleton", merge_confidence=1.0,
        fields={"ncm": fe}, conflicts=["ncm"],
    )
    view = evidence_view_from_canonical([cr])
    assert "r42" in view          # indexado por record_id, não "cr_r42"
    assert view["r42"][0] is fe   # MESMO objeto (mutar reflete no canonical)

    async def ask(system, user):
        return '{"selected_value": "222", "confidence": 0.95, "reason": "ok"}'

    stats = asyncio.run(review_conflicts(view, ask_llm=ask))
    promoted = apply_resolutions_to_evidence(view, stats)
    assert stats.fields_resolved == promoted == 1
    # mutação refletiu no canonical (mesmo objeto)
    assert cr.fields["ncm"].value == "222"
    sync_canonical_conflicts([cr])
    assert cr.conflicts == []     # conflito resolvido saiu da lista
