"""Testes da hierarquia de confiança (desempate sem LLM)."""
from phoenix_kernel.documents.confidence import ConfidenceStatus, FieldEvidence
from phoenix_kernel.documents.confidence_hierarchy import resolve_by_confidence_hierarchy


def _ev(value, status):
    return FieldEvidence(value=value, status=status)


def test_confirmed_beats_probable_without_llm():
    """CONFIRMED (checksum ok) vence PROBABLE (só formato) — economiza LLM."""
    cands = [_ev("111", ConfidenceStatus.PROBABLE), _ev("222", ConfidenceStatus.CONFIRMED)]
    winner, resolved = resolve_by_confidence_hierarchy(cands)
    assert resolved is True
    assert winner.value == "222"


def test_tie_at_top_needs_llm():
    """Dois CONFIRMED empatados — não resolve sozinho, precisa de LLM/auditoria."""
    cands = [_ev("111", ConfidenceStatus.CONFIRMED), _ev("222", ConfidenceStatus.CONFIRMED)]
    winner, resolved = resolve_by_confidence_hierarchy(cands)
    assert resolved is False
    assert winner is None


def test_invalid_never_wins_even_alone():
    """Regra de ouro: um único candidato INVALID não vence sozinho."""
    cands = [_ev("999", ConfidenceStatus.INVALID)]
    winner, resolved = resolve_by_confidence_hierarchy(cands)
    assert resolved is False
    assert winner is None


def test_single_valid_candidate_resolves():
    cands = [_ev("123", ConfidenceStatus.PROBABLE)]
    winner, resolved = resolve_by_confidence_hierarchy(cands)
    assert resolved is True
    assert winner.value == "123"


def test_all_invalid_no_winner():
    cands = [_ev("1", ConfidenceStatus.INVALID), _ev("2", ConfidenceStatus.INVALID)]
    winner, resolved = resolve_by_confidence_hierarchy(cands)
    assert resolved is False
    assert winner is None
