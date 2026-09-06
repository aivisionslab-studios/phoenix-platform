"""Desempate por hierarquia de confiança — Camada C, proposta do GLM (avaliada
e adaptada).

Quando o `field_extractor` produz mais de um candidato `FieldEvidence` para o
mesmo campo (ex.: um valor achado por rótulo e outro por posição de tabela),
o desempate mais barato é por STATUS: um CONFIRMED (passou checksum/tabela
oficial) vence um PROBABLE (só formato) sem gastar chamada de LLM. Só sobe
para o LLM (ou fica em conflito) quando há empate real no nível mais alto —
dois CONFIRMED competindo, ou dois PROBABLE competindo.

Isso é puramente uma OTIMIZAÇÃO DE CUSTO — não muda a garantia da regra de
ouro: um candidato INVALID nunca vence, mesmo sozinho no topo (nesse caso o
campo fica sem vencedor e vai para auditoria, igual ao comportamento atual).
"""

from __future__ import annotations

from typing import Optional

from phoenix_kernel.documents.confidence import ConfidenceStatus, FieldEvidence

_STATUS_WEIGHT = {
    ConfidenceStatus.CONFIRMED: 3,
    ConfidenceStatus.PROBABLE: 2,
    ConfidenceStatus.AMBIGUOUS: 1,
    ConfidenceStatus.CONFLICT: 1,
    ConfidenceStatus.INVALID: 0,
}


def resolve_by_confidence_hierarchy(
    candidates: list[FieldEvidence],
) -> tuple[Optional[FieldEvidence], bool]:
    """Tenta resolver por hierarquia de status, sem LLM.

    Devolve (vencedor_ou_None, resolvido). `resolvido=True` quando um
    candidato venceu com clareza (evita a chamada de LLM/auditoria); `False`
    quando há empate real no topo e o chamador deve seguir para o próximo
    passo (LLM cirúrgico ou auditoria).

    Um candidato INVALID nunca é devolvido como vencedor — mesmo sozinho no
    topo, `resolvido` vem False (a regra de ouro não é enfraquecida por esta
    otimização de custo).
    """
    if not candidates:
        return None, False
    if len(candidates) == 1:
        only = candidates[0]
        if only.status == ConfidenceStatus.INVALID:
            return None, False
        return only, True

    highest = max(_STATUS_WEIGHT.get(c.status, 0) for c in candidates)
    if highest == 0:
        # todos INVALID — não há vencedor determinístico
        return None, False

    winners = [c for c in candidates if _STATUS_WEIGHT.get(c.status, 0) == highest]
    if len(winners) == 1:
        return winners[0], True

    # empate no topo — precisa de LLM ou vai para auditoria
    return None, False
