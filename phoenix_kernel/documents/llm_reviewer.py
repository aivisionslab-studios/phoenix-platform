"""Revisor LLM — resolve SÓ os campos que o pipeline marcou como duvidosos.

Passo 3 da visão do usuário ("resultado nível equipe humana"): depois que o
Document Pipeline V2 roda (determinístico, rápido), sobra um punhado de campos
que ele honestamente NÃO conseguiu decidir sozinho — status `conflict` (2+
valores válidos competindo pelo mesmo campo) ou `ambiguous` (1 valor, fonte
fraca). No catálogo de teste do usuário foram ~25 campos em 497 produtos.

Este módulo roda o LLM como um REVISOR SÊNIOR sobre exatamente esses casos —
nunca sobre os milhares de produtos já resolvidos. Reusa a infraestrutura
`semantic_resolver` que já existe e é segura por design:

  - `SemanticTask` leva ao LLM só a microtarefa (o campo + os valores
    concorrentes), nunca o documento nem o Record inteiro;
  - `allowed_values` é uma ALLOWLIST FECHADA — o LLM é obrigado a escolher
    entre os valores que o pipeline já achou; não pode inventar um valor novo;
  - `parse_and_validate_response` REJEITA qualquer resposta fora da allowlist
    (defesa contra alucinação — "achar um padrão != aceitar como verdade"
    vale também para a saída do próprio LLM).

O resultado é um mapa (record_id, field_type) -> SemanticResolution, que o
chamador aplica de volta na evidência antes de escrever no XLSX. Um campo que
o LLM não resolver com segurança CONTINUA indo pra aba `_PHOENIX_AUDIT` — a
revisão só melhora, nunca degrada a garantia de auditoria.

A chamada ao LLM é injetada como callback `ask_llm` (assíncrono, recebe
system+user prompt, devolve o texto cru). Assim o módulo é testável sem
runtime, e o resident continua dono da política de modelo/timeout.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Awaitable, Callable, Optional

from phoenix_kernel.documents.evidence_engine import EvidenceStatus, FieldEvidence
from phoenix_kernel.documents.semantic_resolver import (
    SemanticResolution,
    SemanticResolutionRejected,
    SemanticTask,
    build_semantic_task,
    needs_semantic_resolution,
    parse_and_validate_response,
)

logger = logging.getLogger(__name__)

# callback: (system_prompt, user_prompt) -> texto cru do modelo (JSON esperado)
AskLLM = Callable[[str, str], Awaitable[str]]

_SYSTEM_PROMPT = (
    "Você é um revisor de dados sênior. Um extrator automático encontrou mais "
    "de um valor possível para UM campo de UM produto e não conseguiu decidir. "
    "Sua tarefa: escolher o valor CORRETO estritamente entre as opções "
    "fornecidas — nunca invente um valor fora da lista. Responda SOMENTE um "
    "objeto JSON: {\"selected_value\": <uma das opções>, \"confidence\": "
    "<0.0 a 1.0>, \"reason\": \"<curta>\"}. Sem texto fora do JSON. /no_think"
)


@dataclass
class ReviewStats:
    """Resumo do que a revisão fez — para log e para o retorno da rota."""
    fields_reviewed: int = 0
    fields_resolved: int = 0
    fields_rejected: int = 0
    fields_skipped_no_options: int = 0
    resolutions: dict = field(default_factory=dict)  # (record_id, field_type) -> SemanticResolution


def _allowed_values_from_evidence(fe: FieldEvidence) -> list:
    """Os valores concorrentes que o LLM pode escolher. Em `conflict`, vêm de
    `values` (os grupos que competem). Em `ambiguous`, é o único valor
    candidato — o LLM confirma ou (por não estar na lista de mais nada) o
    campo segue para auditoria."""
    allowed: list = []
    if fe.values:
        for group in fe.values:
            if group.value is not None and group.value not in allowed:
                allowed.append(group.value)
    if fe.value is not None and fe.value not in allowed:
        allowed.append(fe.value)
    # também aceita os valores válidos presentes na evidência bruta
    for entry in fe.evidence:
        if getattr(entry, "valid", False) and entry.value is not None and entry.value not in allowed:
            allowed.append(entry.value)
    return allowed


async def review_conflicts(
    evidence_by_record: dict[str, list[FieldEvidence]],
    *,
    ask_llm: AskLLM,
    high_confidence_threshold: float = 0.85,
    max_fields: Optional[int] = None,
    model: Optional[str] = None,
) -> ReviewStats:
    """Roda o revisor LLM sobre os campos duvidosos de todos os records.

    `evidence_by_record` é a saída de `build_evidence_for_document`. Só os
    campos que `needs_semantic_resolution` aprova (conflict/ambiguous/probable
    de baixa confiança) chegam ao LLM. `max_fields` limita quantas chamadas
    fazer (proteção de custo em documentos gigantes); None = sem limite.
    """
    stats = ReviewStats()

    # coleta os campos que precisam de revisão, em ordem estável
    pendentes: list[FieldEvidence] = []
    for record_id in sorted(evidence_by_record.keys()):
        for fe in evidence_by_record[record_id]:
            if needs_semantic_resolution(fe, high_confidence_threshold=high_confidence_threshold):
                pendentes.append(fe)

    if max_fields is not None:
        pendentes = pendentes[:max_fields]

    for fe in pendentes:
        stats.fields_reviewed += 1
        allowed = _allowed_values_from_evidence(fe)
        if len(allowed) < 1:
            stats.fields_skipped_no_options += 1
            continue

        task = build_semantic_task(fe, allowed)
        user_prompt = _format_task_prompt(task)

        try:
            raw = await ask_llm(_SYSTEM_PROMPT, user_prompt)
        except Exception as e:
            logger.warning("Revisor LLM: chamada falhou para %s/%s (%s)",
                           fe.record_id, fe.field_type, e)
            stats.fields_rejected += 1
            continue

        try:
            resolution = parse_and_validate_response(task, raw, model=model)
        except SemanticResolutionRejected as e:
            # resposta fora da allowlist ou malformada -> NÃO aplica, campo
            # segue para auditoria (a garantia de auditoria nunca degrada)
            logger.info("Revisor LLM: resposta rejeitada para %s/%s (%s)",
                        fe.record_id, fe.field_type, e)
            stats.fields_rejected += 1
            continue

        stats.fields_resolved += 1
        stats.resolutions[(fe.record_id, fe.field_type)] = resolution

    logger.info(
        "Revisor LLM: %d revisados, %d resolvidos, %d rejeitados, %d sem opção.",
        stats.fields_reviewed, stats.fields_resolved,
        stats.fields_rejected, stats.fields_skipped_no_options,
    )
    return stats


def _format_task_prompt(task: SemanticTask) -> str:
    """Monta o prompt do usuário a partir da microtarefa — só o campo, as
    opções e uns poucos trechos de evidência. Nunca o documento inteiro."""
    opcoes = "\n".join(f"  - {v!r}" for v in task.allowed_values)
    evidencia = "\n".join(f"  {s}" for s in task.evidence_snippets) or "  (sem trechos)"
    return (
        f"Campo: {task.field_type}\n"
        f"Pergunta: {task.question}\n\n"
        f"Opções permitidas (escolha EXATAMENTE uma destas):\n{opcoes}\n\n"
        f"Evidência coletada:\n{evidencia}\n\n"
        f"Responda só o JSON."
    )


def apply_resolutions_to_evidence(
    evidence_by_record: dict[str, list[FieldEvidence]],
    stats: ReviewStats,
) -> int:
    """Aplica as resoluções aceitas de volta na evidência: promove o campo a
    'confirmed' com o valor escolhido pelo revisor. Devolve quantos campos
    foram promovidos. Campos não resolvidos ficam intactos (seguem para
    auditoria como antes)."""
    promoted = 0
    for record_id, fields in evidence_by_record.items():
        for fe in fields:
            resolution = stats.resolutions.get((record_id, fe.field_type))
            if resolution is None:
                continue
            fe.status = EvidenceStatus.CONFIRMED.value
            fe.value = resolution.selected_value
            fe.final_confidence = resolution.confidence
            fe.values = None  # conflito resolvido — não há mais grupos competindo
            promoted += 1
    return promoted


def evidence_view_from_canonical(canonical_records: list) -> dict[str, list[FieldEvidence]]:
    """Constrói o dict record_id -> [FieldEvidence] a partir dos
    CanonicalRecord, usando os MESMOS objetos FieldEvidence que estão dentro
    de cada `CanonicalRecord.fields`.

    IMPORTANTE: `resolve_identity` reconstrói a evidência ao montar os
    CanonicalRecord (build_field_evidence roda de novo por dentro), então os
    FieldEvidence dos canonical são objetos DIFERENTES de um
    build_evidence_for_document paralelo. Para que a promoção do revisor
    reflita no que o writer escreve (o writer lê `record.fields[...]`), a
    revisão precisa operar sobre ESTES objetos. Este helper expõe exatamente
    eles — mutá-los muta o que o writer vê."""
    view: dict[str, list[FieldEvidence]] = {}
    for cr in canonical_records:
        for fe in cr.fields.values():
            # indexa pelo record_id REAL do FieldEvidence — é a chave que
            # review_conflicts usa em stats.resolutions. Usar canonical_id
            # aqui faria apply_resolutions_to_evidence não casar (o revisor
            # resolveria, mas nada seria promovido).
            view.setdefault(fe.record_id, []).append(fe)
    return view


def sync_canonical_conflicts(canonical_records: list) -> None:
    """Depois da revisão, um campo que era 'conflict' e virou 'confirmed' não
    deve mais aparecer em `CanonicalRecord.conflicts`. Recalcula essa lista a
    partir do status atual dos fields (a mesma regra que o identity usa:
    conflicts = field_types cujo status == 'conflict')."""
    for cr in canonical_records:
        cr.conflicts = [
            ft for ft, fe in cr.fields.items()
            if fe.status == EvidenceStatus.CONFLICT.value
        ]
