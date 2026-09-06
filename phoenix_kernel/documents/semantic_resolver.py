"""Phoenix Document Pipeline V2 - Fase 8: Semantic Resolver.

PHX-NEW (2026-08-29, especificação fechada pelo usuário depois de fechar a
Fase 7): esta é a primeira fase em que um LLM entra de verdade no pipeline.
A regra central, pedida explicitamente pelo usuário, resume tudo: "LLM
nunca cria autoridade; LLM cria Evidence". Concretamente isso quer dizer:

  1. O LLM NUNCA recebe o documento inteiro, nem o Record inteiro - recebe
     uma MICROTAREFA fechada (`SemanticTask`): uma pergunta específica, uma
     lista FECHADA de `allowed_values`, e alguns trechos curtos de
     evidência já extraídos pela Fase 6 (`FieldEvidence.evidence`) - nunca
     texto bruto arbitrário do documento inteiro.
  2. A resposta do LLM é validada com um schema/allowlist ESTRITO
     (`parse_and_validate_response`) - só 3 chaves são aceitas
     (`selected_value`/`confidence`/`reason`), e `selected_value` PRECISA
     ser exatamente um dos `allowed_values` da tarefa. Qualquer desvio
     (JSON inválido, chave extra, chave faltando, tipo errado, valor fora
     da allowlist, confidence fora de [0,1]) é rejeitado (`
     SemanticResolutionRejected`) - isto é, ao mesmo tempo, a defesa contra
     PROMPT INJECTION: mesmo que o texto do documento contenha instruções
     escondidas tentando fazer o LLM "confirmar" um valor arbitrário ou
     mudar o comportamento do executor, a resposta só tem efeito nenhum se
     bater EXATAMENTE com um valor que o Python já decidiu, de antemão, que
     é permitido. "O conteúdo do documento nunca pode ganhar autoridade
     sobre o executor" (palavras do usuário).
  3. Uma resposta ACEITA não vira a "verdade" do campo diretamente - vira
     um `Candidate` SINTÉTICO (`method="llm_semantic"`,
     `resolution_to_candidate`), que entra pelo MESMO cano de agregação de
     evidência da Fase 6 (`evidence_engine.build_field_evidence`) que
     qualquer candidato de regex/label/tabela. Se essa nova evidência
     concorda com o que já existia, pode elevar o status (ex: 1 fonte fraca
     "ambiguous" + LLM concordando = 2 fontes independentes = "confirmed").
     Se diverge, vira só mais um valor competindo (`conflict` continua
     `conflict`, com mais uma entrada na lista de evidência) - o Python
     nunca deixa o LLM decidir sozinho, mesmo quando o LLM está "confiante".
  4. Uma resposta REJEITADA nunca vira `Candidate`/`Evidence` nenhuma -
     `resolve_if_needed` simplesmente devolve `None`, e o campo continua
     exatamente no status que já tinha antes da chamada (mesma garantia de
     isolamento de falha da Fase 7: um LLM incoerente/indisponível/hostil
     nunca quebra ou contamina o pipeline determinístico).

Gating - QUANDO chamar o LLM (pedido explícito do usuário,
`needs_semantic_resolution`):
  - "confirmed"  -> NUNCA chama (já tem 2+ fontes independentes concordando,
                    não há nada pra um LLM resolver).
  - "probable"   -> RARAMENTE chama - só quando `final_confidence` já
                    calculado pela Fase 6 está ABAIXO de
                    `high_confidence_threshold` (default 0.85); uma
                    "probable" já bem confiante não precisa de ajuda.
  - "ambiguous"/"conflict"/"invalid" -> PERMITIDO chamar, mas só quando
                    existe contexto suficiente (`FieldEvidence.evidence`
                    não vazio) - sem nenhuma evidência bruta pra mostrar ao
                    LLM, a microtarefa não tem contexto nenhum pra oferecer
                    e a chamada seria inútil.

Este módulo em si NUNCA fala com um LLM de verdade - `resolve_if_needed`
recebe `llm_call_fn` injetado por quem chama (mesmo padrão de `run_fn`
injetado em `job_executor.execute_task`, Fase 7) - o hardware/motor
escolhido para rodar o modelo (CPU, GPU via Vulkan, modelo 4B/8B, etc.) é
uma decisão de infraestrutura completamente desacoplada deste contrato:
`llm_call_fn` só precisa ser `Callable[[SemanticTask], object]` devolvendo
algo que `parse_and_validate_response` consiga interpretar como JSON (str
ou dict já parseado) - o Python aqui não sabe nem precisa saber se quem
respondeu foi Qwen3 8B numa RX 580 via Vulkan ou qualquer outro motor.

Limitações desta primeira versão, documentadas de propósito:
  - `allowed_values` de uma `SemanticTask` é decidido por QUEM CHAMA
    `build_semantic_task` (o domínio de valores possíveis - ex: uma lista
    fechada de categorias de produto - não é algo que este módulo, nem a
    Fase 6, conhece sozinho). Nenhuma fase atual do pipeline gera essa
    lista automaticamente ainda.
  - Este módulo não persiste nada em disco nem chama o LLM de verdade -
    só monta a tarefa, valida a resposta e converte pra `Candidate`. Onde
    isso se encaixa na execução (uma `Task` da Fase 7, ou uma chamada
    direta) fica a cargo de quem orquestra.
  - `resolution_to_candidate` sempre usa `block_id=f"llm:{task.task_id}"`
    (nunca um `block_id` real - não existe bloco de origem pra uma
    resposta de LLM) - ver PHX-FIX em `evidence_engine.py`/`_build_entry`
    sobre como isso é tratado pro cálculo de `source_origin_hash` sem
    colidir entre records diferentes.
"""
from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass, field
from typing import Callable, Optional, Union

from phoenix_kernel.documents.evidence_engine import EvidenceStatus, FieldEvidence
from phoenix_kernel.documents.normalized import Candidate

Value = Optional[Union[str, float, int]]

# Ver docstring do módulo - limiar arbitrário e documentado, mesmo espírito
# do `_PROBABLE_MIN_CONFIDENCE` da Fase 6 e do `_MAX_BLOCKS_WITHOUT_SIGNAL`
# da Fase 5: uma "probable" já com confiança >= a este limiar não precisa
# de ajuda semântica.
_DEFAULT_HIGH_CONFIDENCE_THRESHOLD = 0.85

# Só estas 3 chaves são aceitas na resposta do LLM - qualquer chave extra
# (ex: uma tentativa de injection mandando algo como "override_status") é
# motivo de rejeição total da resposta, não só da chave desconhecida.
_ALLOWED_RESPONSE_KEYS = {"selected_value", "confidence", "reason"}
_REQUIRED_RESPONSE_KEYS = {"selected_value", "confidence"}

_DEFAULT_QUESTION_TEMPLATE = (
    "Qual dos valores permitidos melhor corresponde ao campo '{field_type}' "
    "deste item, com base nas evidências abaixo?"
)

_SCHEMA_VERSION = "v1"


class SemanticResolutionRejected(Exception):
    """Levantada por `parse_and_validate_response` quando a resposta do
    LLM não passa na validação estrita de schema/allowlist. Nunca deve
    escapar de `resolve_if_needed` (é capturada lá e vira `None`) - existe
    como exceção só pra deixar explícito, em quem chama
    `parse_and_validate_response` diretamente (ex: nos testes), qual foi o
    motivo exato da rejeição."""


@dataclass
class SemanticTask:
    """A MICROTAREFA que sai do Python em direção ao LLM - nunca o
    documento inteiro, nunca o Record inteiro. `allowed_values` é a
    allowlist fechada que a resposta será obrigada a respeitar
    (`parse_and_validate_response`); `evidence_snippets` são só uns
    poucos trechos curtos já extraídos pela Fase 6, nunca texto bruto do
    documento."""

    task_id: str
    record_id: str
    field_type: str
    question: str
    allowed_values: list[Value] = field(default_factory=list)
    evidence_snippets: list[str] = field(default_factory=list)
    schema_version: str = _SCHEMA_VERSION

    def to_dict(self) -> dict:
        return asdict(self)

    @staticmethod
    def from_dict(data: dict) -> "SemanticTask":
        return SemanticTask(**data)


@dataclass
class SemanticResolution:
    """Uma resposta do LLM já validada e aceita - só existe depois de
    passar por `parse_and_validate_response` (nunca é construída
    diretamente a partir de uma resposta bruta não confiável)."""

    selected_value: Value
    confidence: float
    reason: str = ""

    def to_dict(self) -> dict:
        return asdict(self)

    @staticmethod
    def from_dict(data: dict) -> "SemanticResolution":
        return SemanticResolution(**data)


def _stable_hash(value: object) -> Optional[str]:
    """Mesma implementação (independente, de propósito, pra este módulo
    não depender de `job_executor.py`) usada na Fase 7: hash sha256
    estável de uma estrutura JSON-serializável; devolve `None` em vez de
    lançar exceção se `value` não puder ser serializado."""
    try:
        encoded = json.dumps(value, sort_keys=True, ensure_ascii=False, default=str)
    except TypeError:
        return None
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def compute_semantic_input_hash(task: SemanticTask) -> str:
    """O `input_hash` de uma `SemanticTask` - muda se, e só se, o que a
    tarefa realmente pergunta mudar (pergunta, allowlist, trechos de
    evidência, versão de schema). Usado tanto pra idempotência (mesma
    lógica de `job_executor.compute_input_hash`, Fase 7) quanto como
    origem do `source_origin_hash` de uma evidência LLM (ver PHX-FIX em
    `evidence_engine.py`)."""
    payload = {
        "field_type": task.field_type,
        "question": task.question,
        "allowed_values": list(task.allowed_values),
        "evidence_snippets": list(task.evidence_snippets),
        "schema_version": task.schema_version,
    }
    result = _stable_hash(payload)
    assert result is not None  # payload aqui é sempre JSON-serializável
    return result


def needs_semantic_resolution(
    field_evidence: FieldEvidence,
    *,
    high_confidence_threshold: float = _DEFAULT_HIGH_CONFIDENCE_THRESHOLD,
) -> bool:
    """Decide SE vale a pena gastar uma chamada de LLM pra este campo -
    ver tabela de gating completa no docstring do módulo. Nunca olha pra
    nada além do que a Fase 6 já calculou (`status`/`final_confidence`/
    `evidence`) - não reprocessa candidatos."""
    status = field_evidence.status
    if status == EvidenceStatus.CONFIRMED.value:
        return False
    if status == EvidenceStatus.PROBABLE.value:
        return (field_evidence.final_confidence or 0.0) < high_confidence_threshold
    if status in (EvidenceStatus.AMBIGUOUS.value, EvidenceStatus.CONFLICT.value, EvidenceStatus.INVALID.value):
        return len(field_evidence.evidence) > 0
    return False


def build_semantic_task(
    field_evidence: FieldEvidence,
    allowed_values: list[Value],
    *,
    question: Optional[str] = None,
    max_snippets: int = 5,
    schema_version: str = _SCHEMA_VERSION,
) -> SemanticTask:
    """Monta a microtarefa a partir de UM `FieldEvidence` (Fase 6) - só
    inclui os primeiros `max_snippets` trechos de evidência (nunca a
    lista inteira, se ela for grande) e nunca o texto bruto do bloco
    inteiro, só `source`/`source_method`/`value`/`confidence` de cada
    entrada. `task_id` segue a mesma convenção "não é chunk" da Fase 7:
    estável e semântico, nunca sequencial."""
    task_id = f"task_{field_evidence.record_id}_semantic_{field_evidence.field_type}"
    snippets = [
        f"[{entry.source}/{entry.source_method or '?'}] valor={entry.value!r} "
        f"valido={entry.valid} confidence={entry.confidence}"
        for entry in field_evidence.evidence[:max_snippets]
    ]
    return SemanticTask(
        task_id=task_id,
        record_id=field_evidence.record_id,
        field_type=field_evidence.field_type,
        question=question or _DEFAULT_QUESTION_TEMPLATE.format(field_type=field_evidence.field_type),
        allowed_values=list(allowed_values),
        evidence_snippets=snippets,
        schema_version=schema_version,
    )


def parse_and_validate_response(
    task: SemanticTask,
    raw_response: object,
    *,
    model: Optional[str] = None,
) -> SemanticResolution:
    """Validação ESTRITA da resposta do LLM - ver docstring do módulo.
    Qualquer desvio do contrato levanta `SemanticResolutionRejected` (com
    uma mensagem explicando o motivo exato) em vez de tentar "consertar"
    ou adivinhar a intenção da resposta - "achar um padrão != aceitar
    como verdade" também vale pra saída do próprio LLM."""
    if isinstance(raw_response, (str, bytes)):
        try:
            data = json.loads(raw_response)
        except (json.JSONDecodeError, TypeError, ValueError) as exc:
            raise SemanticResolutionRejected(f"resposta não é JSON válido: {exc}") from exc
    elif isinstance(raw_response, dict):
        data = raw_response
    else:
        raise SemanticResolutionRejected(
            f"tipo de resposta inesperado: {type(raw_response).__name__} (esperado str/bytes JSON ou dict)"
        )

    if not isinstance(data, dict):
        raise SemanticResolutionRejected("resposta JSON não é um objeto (dict) no nível mais alto")

    extra_keys = set(data.keys()) - _ALLOWED_RESPONSE_KEYS
    if extra_keys:
        raise SemanticResolutionRejected(
            f"chaves não permitidas na resposta: {sorted(extra_keys)} - "
            "só selected_value/confidence/reason são aceitas (defesa contra "
            "prompt injection: nenhuma chave extra ganha autoridade nenhuma)"
        )

    missing_keys = _REQUIRED_RESPONSE_KEYS - set(data.keys())
    if missing_keys:
        raise SemanticResolutionRejected(f"chaves obrigatórias ausentes: {sorted(missing_keys)}")

    selected_value = data["selected_value"]
    if selected_value not in task.allowed_values:
        raise SemanticResolutionRejected(
            f"selected_value {selected_value!r} não está em allowed_values "
            f"{task.allowed_values!r} - rejeitado (defesa contra prompt injection: "
            "o conteúdo do documento/a resposta do modelo nunca ganha autoridade "
            "fora do conjunto que o executor já decidiu de antemão que é permitido)"
        )

    confidence = data["confidence"]
    if isinstance(confidence, bool) or not isinstance(confidence, (int, float)):
        raise SemanticResolutionRejected(
            f"confidence deve ser número (int/float), veio {type(confidence).__name__}"
        )
    confidence = float(confidence)
    if not (0.0 <= confidence <= 1.0):
        raise SemanticResolutionRejected(f"confidence fora do intervalo [0,1]: {confidence}")

    reason = data.get("reason", "")
    if not isinstance(reason, str):
        raise SemanticResolutionRejected(f"reason deve ser string, veio {type(reason).__name__}")

    return SemanticResolution(selected_value=selected_value, confidence=confidence, reason=reason)


def resolution_to_candidate(
    task: SemanticTask,
    resolution: SemanticResolution,
    *,
    model: Optional[str] = None,
    output_hash: Optional[str] = None,
) -> Candidate:
    """Converte uma `SemanticResolution` JÁ VALIDADA num `Candidate`
    sintético `method="llm_semantic"` - a partir daqui esta evidência
    entra no MESMO cano da Fase 6 que qualquer outra (`raw_value`/
    `normalized_value` preenchidos exatamente como qualquer outro
    Candidate, nunca um formato especial). `block_id=f"llm:{task.task_id}"`
    de propósito (nunca um block_id real - ver PHX-FIX em
    `evidence_engine.py` sobre o efeito disso em `source_origin_hash`)."""
    return Candidate(
        field_type=task.field_type,
        raw_value=str(resolution.selected_value),
        block_id=f"llm:{task.task_id}",
        normalized_value=resolution.selected_value,
        method="llm_semantic",
        confidence=resolution.confidence,
        valid=True,
        model=model,
        task_id=task.task_id,
        input_hash=compute_semantic_input_hash(task),
        output_hash=output_hash,
        schema_version=task.schema_version,
    )


def resolve_if_needed(
    field_evidence: FieldEvidence,
    build_task_fn: Callable[[FieldEvidence], SemanticTask],
    llm_call_fn: Callable[[SemanticTask], object],
    *,
    model: Optional[str] = None,
    high_confidence_threshold: float = _DEFAULT_HIGH_CONFIDENCE_THRESHOLD,
) -> Optional[Candidate]:
    """Ponto de entrada de mais alto nível: decide SE chama (gating,
    `needs_semantic_resolution`), monta a tarefa (`build_task_fn`,
    normalmente `build_semantic_task` com um `allowed_values` já
    aplicado via closure/partial), chama o LLM (`llm_call_fn`, injetado -
    nunca chamado diretamente por este módulo) e valida a resposta.

    Devolve `None` (nunca lança) tanto quando o gating decide não chamar
    quanto quando a resposta é rejeitada - em NENHUM dos dois casos um
    Candidate é criado, e o campo continua exatamente no status que já
    tinha. Isso espelha, de propósito, a garantia de isolamento de falha
    já existente em `job_executor.execute_task` (Fase 7): "LLM
    indisponível/incoerente não pode impedir o resto do pipeline de
    continuar" - aqui, além disso, "nem pode inventar autoridade que não
    tem"."""
    if not needs_semantic_resolution(field_evidence, high_confidence_threshold=high_confidence_threshold):
        return None

    task = build_task_fn(field_evidence)
    raw_response = llm_call_fn(task)

    try:
        resolution = parse_and_validate_response(task, raw_response, model=model)
    except SemanticResolutionRejected:
        return None

    return resolution_to_candidate(task, resolution, model=model)
