"""Phoenix Document Pipeline V2 - Fase 6: Evidence / Confidence Model.

PHX-NEW (2026-08-29, especificação fechada pelo usuário depois de fechar a
Fase 5): esta fase muda a pergunta que o pipeline está respondendo. Até
aqui: "o documento contém isso?" (Fase 4, Candidate) e "esses blocos
pertencem à mesma entidade?" (Fase 5, Record). Agora: "tenho vários
candidatos e possivelmente várias fontes apontando pra um valor de campo
dentro de um record - quão confiável é esse valor?"

Continua Python puro, determinístico, ZERO LLM/OCR/visão - pedido
explícito do usuário ("Eu faria a Fase 6 sem LLM ainda. Primeiro só Python
agregando evidências determinísticas e conflitantes"). LLM/OCR/visão
entram só numa fase futura, e mesmo aí como NOVAS EVIDÊNCIAS que competem/
concordam com as demais - nunca como autoridade final (mesma filosofia
"maestro vs especialista" já usada desde a Fase 3).

Este módulo NUNCA decide um valor "no chute" - ele classifica o estado do
campo num vocabulário fechado de 5 status (pedido explícito do usuário):
  - "confirmed"  - um único valor válido, com 2+ FONTES INDEPENDENTES
                   concordando.
  - "probable"   - um único valor válido, só 1 fonte independente, mas
                   com confiança individual alta o bastante.
  - "ambiguous"  - um único valor válido, só 1 fonte independente, com
                   confiança individual baixa (melhor informação
                   disponível, mas não o bastante pra chamar de
                   "probable").
  - "conflict"   - 2+ valores válidos DIFERENTES competindo pelo mesmo
                   campo dentro do mesmo record.
  - "invalid"    - só existem candidatos INVÁLIDOS pra esse campo (nenhum
                   valor confiável disponível) - preservados como
                   evidência (ruído), nunca descartados, igual já era a
                   regra desde a Fase 4/5.

Regra central pedida explicitamente pelo usuário, e o motivo de existir
`EvidenceEntry.source_origin_hash`: "não somar confiança ingenuamente -
três ocorrências repetidas do mesmo trecho não valem três fontes
independentes". `source_origin_hash` é o hash sha256 do TEXTO BRUTO do
bloco de onde a evidência veio - duas evidências com o MESMO hash (ex: o
mesmo parágrafo aparecendo duplicado em outro lugar do documento, um
padrão já confirmado nos dois documentos reais testados na Fase 5, onde a
conversa repete/revisa as mesmas seções mais adiante) contam como UMA
única fonte independente pra fins de confiança - mesmo que gerem duas
`Candidate`s e portanto duas `EvidenceEntry`s (ambas continuam registradas
na lista `evidence`, pela mesma regra de nunca descartar evidência bruta).
`source_block`/`source_record`/`source_method` completam a rastreabilidade
- pedido explícito do usuário, útil desde já e ainda mais quando imagens
duplicadas (mesmo hash de mídia, ver limitação já registrada na Fase 2/4)
entrarem como fonte de evidência numa fase futura.

Cálculo de `final_confidence` pro caso de valor único vencedor
("confirmed"/"probable"/"ambiguous"): agrega UMA confiança por FONTE
INDEPENDENTE (evidências com o mesmo `source_origin_hash` colapsam pra
uma só, usando a MAIOR confiança entre elas - não a soma, não a média das
repetidas), e só then tira a média dessas confidências já deduplicadas.
Isso responde exatamente ao pedido do usuário e bate com o exemplo dele
(duas fontes independentes com confiança 0.99 e 1.0 -> final_confidence
0.995 - média simples de duas fontes DISTINTAS, sem inflar por repetição).

PHX-FIX (2026-08-29, achado real testando esta própria fase contra os
documentos reais): "Peso: 0,600 kg" e "Peso: 600g" no MESMO record
geravam um "conflict" falso, porque `value` comparava 0.6 com 600.0
literalmente - a mesma grandeza física, só em unidades diferentes. A
correção NÃO foi feita aqui - de propósito, pra este módulo continuar sem
saber nada de física/conversão de unidade, só comparando número com
número. A correção foi na ORIGEM do contrato de valor normalizado
(`normalizer.py`/`NormalizationResult` e `Candidate`, Fase 3/4): todo
campo dimensional (massa/comprimento/volume) agora é convertido pra uma
unidade CANÔNICA (kg/m/l) antes de virar `normalized_value` - "600g" e
"0,600 kg" os DOIS chegam aqui já como `0.6`, então `value` bate
naturalmente sem este módulo precisar de regra nova nenhuma.
`EvidenceEntry.unit`/`original_unit` só existem pra AUDITORIA (mostrar
que "600g" virou "0.6 kg"), nunca pra decisão de comparação.

Limitações desta primeira versão, documentadas de propósito:
  - `source` de cada evidência hoje só pode ser "text" (bloco parágrafo/
    heading) ou "table" (bloco tabela) - "ocr"/"vision"/"llm" já existem
    no vocabulário e no código (via prefixo de `Candidate.method`), mas
    NENHUMA fase atual produz Candidate com esses métodos ainda (Tesseract/
    MiniCPM-V/LLM não estão implementados) - o hook existe pronto pra
    quando a Fase 12 (visual enrichment) e a Fase 8 (semantic LLM
    resolver) existirem, mas está sem cobertura de teste com dado real
    até lá.
  - `_PROBABLE_MIN_CONFIDENCE` (0.7) é um limiar arbitrário, documentado
    como tal - mesmo espírito do `_MAX_BLOCKS_WITHOUT_SIGNAL` do Segmenter
    (Fase 5): não veio de nenhuma medição estatística. Com os detectores
    atuais da Fase 4, TODO candidato válido tem confidence >= 0.7 - ou
    seja, o status "ambiguous" é alcançável e testado (sinteticamente),
    mas não deve aparecer na prática com os documentos reais testados até
    agora. Fica pronto pra quando um detector mais fraco (heurística
    frágil, ou uma leitura de OCR/visão com baixa confiança) existir.
  - Um candidato INVÁLIDO do MESMO campo que já tem um valor válido
    vencedor (ex: um EAN inválido perdido perto de um EAN válido no mesmo
    record) hoje NÃO rebaixa o status do valor válido (fica só registrado
    na lista `evidence`, sem efeito no cálculo) - poderia futuramente virar
    um sinal extra de ruído que empurra "confirmed"->"probable" ou
    "probable"->"ambiguous"; decisão adiada de propósito pra não inventar
    uma regra sem caso real que a justifique ainda.
  - Este módulo trabalha SÓ dentro de um `Record` por vez - consolidar o
    MESMO campo entre RECORDS diferentes (ex: o mesmo produto mencionado
    duas vezes no documento, cada menção virando um Record próprio) é
    trabalho da fase de merge/dedupe (Fase 9 no roadmap atual), não desta.
"""
from __future__ import annotations

import hashlib
from dataclasses import asdict, dataclass, field
from enum import Enum
from typing import Optional, Union

from phoenix_kernel.documents.normalized import Block, BlockType, Candidate, NormalizedDocument, Record

Value = Optional[Union[str, float, int]]


class EvidenceStatus(str, Enum):
    CONFIRMED = "confirmed"
    PROBABLE = "probable"
    AMBIGUOUS = "ambiguous"
    CONFLICT = "conflict"
    INVALID = "invalid"


# Ver docstring do módulo - limiar arbitrário e documentado, mesmo espírito
# do `_MAX_BLOCKS_WITHOUT_SIGNAL` já usado no Record Segmenter (Fase 5).
_PROBABLE_MIN_CONFIDENCE = 0.7

# Prefixos de `Candidate.method` reservados pra fontes que ainda não
# existem de verdade (ver limitação no docstring do módulo) - o hook fica
# pronto, sem nenhuma fase atual produzindo esses métodos.
_RESERVED_METHOD_SOURCES = ("ocr", "vision", "llm")


def _hash_text(text: Optional[str]) -> str:
    """Hash estável do texto BRUTO de origem de uma evidência - usado
    pra detectar "mesmo trecho repetido em outro lugar do documento"
    (ver PHX-NEW no topo do módulo). Texto vazio/None ainda gera um hash
    válido (de string vazia), nunca quebra."""
    return hashlib.sha256((text or "").encode("utf-8")).hexdigest()


@dataclass
class EvidenceEntry:
    """Um pedaço de evidência bruta - SEMPRE preservado na lista
    `FieldEvidence.evidence`, com ou sem influência no status/confiança
    final (ex: uma evidência inválida sempre aparece aqui, mesmo quando
    existe um valor válido vencedor). Rastreabilidade completa pedida
    explicitamente pelo usuário: `source_block`/`source_record`/
    `source_method`/`source_origin_hash`."""

    candidate_id: Optional[str]
    source: str
    value: Value
    valid: bool
    confidence: float
    source_block: Optional[str] = None
    source_record: Optional[str] = None
    source_method: Optional[str] = None
    source_origin_hash: Optional[str] = None
    # PHX-FIX (2026-08-29, achado real testando esta própria fase contra
    # os documentos reais): ver PHX-FIX em normalizer.py/NormalizationResult
    # - `value` de um campo dimensional (ex: weight) já vem CONVERTIDO pra
    # unidade canônica, então comparar `value` nunca precisa saber de
    # unidade; `unit`/`original_unit` só existem aqui pra AUDITORIA (saber
    # que "600g" virou "0.6 kg", não pra decisão nenhuma deste módulo).
    unit: Optional[str] = None
    original_unit: Optional[str] = None
    # PHX-NEW (2026-08-29, especificação fechada pelo usuário pra Fase 8 -
    # Semantic Resolver): mesma ideia do PHX-NEW em normalized.py/Candidate
    # - só populados quando `source_method == "llm_semantic"`; qualquer
    # outra fonte (regex/label/table) deixa esses 5 campos `None`, sem
    # custo pro que já existia.
    model: Optional[str] = None
    task_id: Optional[str] = None
    input_hash: Optional[str] = None
    output_hash: Optional[str] = None
    schema_version: Optional[str] = None

    def to_dict(self) -> dict:
        return asdict(self)

    @staticmethod
    def from_dict(data: dict) -> "EvidenceEntry":
        return EvidenceEntry(**data)


@dataclass
class ValueGroup:
    """Um dos valores competindo num campo em estado "conflict" -
    `evidence_count` já é a contagem de FONTES INDEPENDENTES (deduplicada
    por `source_origin_hash`), nunca a contagem bruta de `Candidate`s."""

    value: Value
    evidence_count: int
    confidence: Optional[float] = None

    def to_dict(self) -> dict:
        return asdict(self)

    @staticmethod
    def from_dict(data: dict) -> "ValueGroup":
        return ValueGroup(**data)


@dataclass
class FieldEvidence:
    """Resultado da agregação de evidências de UM campo dentro de UM
    record. `value`/`final_confidence` só fazem sentido quando existe um
    único valor válido vencedor (status confirmed/probable/ambiguous);
    `values` só é preenchido em "conflict". `evidence` é SEMPRE a lista
    completa e bruta (nunca filtrada), pra auditoria/depuração e pra
    fases futuras (merge entre records, visual enrichment) reaproveitarem
    sem reprocessar os candidatos originais."""

    field_type: str
    record_id: str
    status: str
    value: Value = None
    final_confidence: Optional[float] = None
    values: Optional[list[ValueGroup]] = None
    evidence: list[EvidenceEntry] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "field_type": self.field_type,
            "record_id": self.record_id,
            "status": self.status,
            "value": self.value,
            "final_confidence": self.final_confidence,
            "values": [v.to_dict() for v in self.values] if self.values is not None else None,
            "evidence": [e.to_dict() for e in self.evidence],
        }

    @staticmethod
    def from_dict(data: dict) -> "FieldEvidence":
        data = dict(data)
        values = data.get("values")
        data["values"] = [ValueGroup.from_dict(v) for v in values] if values is not None else None
        data["evidence"] = [EvidenceEntry.from_dict(e) for e in data.get("evidence", [])]
        return FieldEvidence(**data)


def _source_for_candidate(candidate: Candidate, block: Optional[Block]) -> str:
    """"text" ou "table" hoje sempre - ver limitação documentada no topo
    do módulo sobre "ocr"/"vision"/"llm" ainda não existirem de verdade."""
    method = candidate.method or ""
    for prefix in _RESERVED_METHOD_SOURCES:
        if method.startswith(prefix):
            return prefix
    if block is not None and block.type == BlockType.TABLE:
        return "table"
    return "text"


def _build_entry(candidate: Candidate, record_id: str, block: Optional[Block]) -> EvidenceEntry:
    # PHX-FIX (2026-08-29, achado durante o design da Fase 8 - Semantic
    # Resolver): um Candidate sintético `method="llm_semantic"` não tem
    # bloco de origem real (`block is None`, ver `resolution_to_candidate`
    # em `semantic_resolver.py`) - usar `None` aqui faria TODAS as
    # evidências de LLM colidirem no mesmo `_hash_text(None)` (hash de
    # string vazia), tratando resoluções de records DIFERENTES como "a
    # mesma fonte repetida" pela regra de `source_origin_hash` (ver
    # PHX-NEW no topo do módulo) - inflação por colisão, não por repetição
    # real. Correção: cai pra `candidate.input_hash` (o hash do que a
    # tarefa semântica realmente consumiu, ver `compute_semantic_input_hash`)
    # quando não existe bloco real de onde tirar o texto.
    if block is not None:
        origin_text = block.text_raw
    else:
        origin_text = candidate.input_hash
    return EvidenceEntry(
        candidate_id=candidate.id,
        source=_source_for_candidate(candidate, block),
        value=candidate.normalized_value if candidate.valid else candidate.raw_value,
        valid=candidate.valid,
        confidence=candidate.confidence,
        source_block=candidate.block_id,
        source_record=record_id,
        source_method=candidate.method,
        source_origin_hash=_hash_text(origin_text),
        unit=candidate.unit,
        original_unit=candidate.original_unit,
        model=candidate.model,
        task_id=candidate.task_id,
        input_hash=candidate.input_hash,
        output_hash=candidate.output_hash,
        schema_version=candidate.schema_version,
    )


def build_field_evidence(
    record: Record,
    candidates_by_id: dict[str, Candidate],
    blocks_by_id: dict[str, Block],
) -> list[FieldEvidence]:
    """Ponto de entrada por record. `candidates_by_id` deve conter (no
    mínimo) os candidatos referenciados em `record.candidate_ids` - vem
    tipicamente de `{c.id: c for c in find_candidates_in_document(doc)}`.
    Nunca reordena nem inventa candidato - só agrega o que já existe."""
    by_field: dict[str, list[Candidate]] = {}
    for candidate_id in record.candidate_ids:
        candidate = candidates_by_id.get(candidate_id)
        if candidate is None:
            continue
        by_field.setdefault(candidate.field_type, []).append(candidate)

    results: list[FieldEvidence] = []
    for field_type, field_candidates in by_field.items():
        entries = [_build_entry(c, record.record_id, blocks_by_id.get(c.block_id)) for c in field_candidates]
        valid_entries = [e for e in entries if e.valid]

        if not valid_entries:
            # só existe ruído (candidato(s) inválido(s)) pra este campo -
            # preservado como evidência, nunca descartado, mas sem valor
            # confiável pra oferecer.
            results.append(FieldEvidence(
                field_type=field_type,
                record_id=record.record_id,
                status=EvidenceStatus.INVALID.value,
                value=None,
                final_confidence=0.0,
                evidence=entries,
            ))
            continue

        by_value: dict[Value, list[EvidenceEntry]] = {}
        for entry in valid_entries:
            by_value.setdefault(entry.value, []).append(entry)

        if len(by_value) > 1:
            values = []
            for value, group in by_value.items():
                distinct_sources = {e.source_origin_hash for e in group}
                avg_confidence = sum(e.confidence for e in group) / len(group)
                values.append(ValueGroup(
                    value=value,
                    evidence_count=len(distinct_sources),
                    confidence=round(avg_confidence, 4),
                ))
            values.sort(key=lambda v: v.evidence_count, reverse=True)
            results.append(FieldEvidence(
                field_type=field_type,
                record_id=record.record_id,
                status=EvidenceStatus.CONFLICT.value,
                values=values,
                evidence=entries,
            ))
            continue

        (winning_value, group), = by_value.items()

        # PHX-NEW: uma confiança POR FONTE INDEPENDENTE (mesmo
        # source_origin_hash colapsa pra uma, usando a MAIOR confiança
        # entre as repetidas daquela mesma fonte) - nunca soma
        # ingenuamente. Só depois disso tira a média entre as fontes já
        # deduplicadas.
        confidence_by_source: dict[Optional[str], float] = {}
        for entry in group:
            key = entry.source_origin_hash
            confidence_by_source[key] = max(confidence_by_source.get(key, 0.0), entry.confidence)
        independent_source_count = len(confidence_by_source)
        final_confidence = sum(confidence_by_source.values()) / independent_source_count

        if independent_source_count >= 2:
            status = EvidenceStatus.CONFIRMED
        elif final_confidence >= _PROBABLE_MIN_CONFIDENCE:
            status = EvidenceStatus.PROBABLE
        else:
            status = EvidenceStatus.AMBIGUOUS

        results.append(FieldEvidence(
            field_type=field_type,
            record_id=record.record_id,
            status=status.value,
            value=winning_value,
            final_confidence=round(final_confidence, 4),
            evidence=entries,
        ))

    return results


def build_evidence_for_document(
    document: NormalizedDocument,
    candidates: list[Candidate],
    records: list[Record],
) -> dict[str, list[FieldEvidence]]:
    """Roda `build_field_evidence` pra TODOS os records de um documento de
    uma vez. Devolve um dict `record_id -> list[FieldEvidence]` (nunca uma
    lista achatada) - cada record continua sendo a unidade de checkpoint/
    trabalho, igual já é desde a Fase 1 (`JobState` por `record_id`)."""
    candidates_by_id = {c.id: c for c in candidates if c.id}
    blocks_by_id = {b.id: b for b in document.blocks}
    return {
        record.record_id: build_field_evidence(record, candidates_by_id, blocks_by_id)
        for record in records
    }
