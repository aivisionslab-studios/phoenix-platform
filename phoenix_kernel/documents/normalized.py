"""Phoenix Document Pipeline V2 - Fase 1: contrato central.

PHX-NEW (2026-08-29, pedido explícito do usuário depois de investigar o
travamento dos 54 pedaços do preenchimento de planilha, alinhado com ele +
ChatGPT ao longo de várias rodadas): esta é a PRIMEIRA peça de uma
reestruturação maior do pipeline documento->planilha (apelidada de
"Document Pipeline V2" nas conversas). O diagnóstico que motivou isso:
hoje um documento inteiro vira uma STRING achatada (ver `_extract_docx` em
`documents/engine.py`, que despeja parágrafos e SÓ DEPOIS todas as
tabelas, fora de ordem, cada linha virando "cel1 | cel2 | cel3" sem
cabeçalho) e essa string é cortada em pedaços por ORÇAMENTO DE CARACTERES
(`_SPREADSHEET_FILL_CHUNK_CHAR_BUDGET` em `resident/resident_manager.py`) -
um pedaço de 22 mil caracteres pode conter dezenas de produtos diferentes,
então se aquele pedaço falhar/travar, todos os produtos dentro dele se
perdem de uma vez. A decisão tomada (não implementada ainda além deste
arquivo) foi trocar isso por um pipeline onde Python faz o trabalho
estrutural pesado (parsing, extração determinística, segmentação,
checkpoint por registro) e o LLM só é chamado pra decisões semânticas
pontuais e pequenas.

Este módulo define SÓ o contrato de dados (schemas), sem nenhuma lógica
de parsing/segmentação/execução ainda - de propósito, pra não travar o
formato numa implementação prematura. Consciente e deliberadamente:
- dataclasses simples (mesmo padrão já usado no resto do projeto - ver
  `phoenix_kernel/shared/models.py` e `runtime/contracts/model_contracts.py`
  - nenhuma dependência nova, sem Pydantic).
- Nenhuma hierarquia de subclasses por tipo de bloco (ParagraphBlock/
  TableBlock/...) - um único `Block` com campos opcionais por tipo, porque
  ainda não existe um parser real usando isso; criar essa hierarquia agora
  seria abstração antecipada sem caso de uso.
- Tabela nunca é achatada em texto aqui dentro - fica como
  `headers`/`rows` estruturados; virar texto pra um prompt de LLM é
  responsabilidade de OUTRA camada (ainda não escrita), nunca deste
  schema.
- `document_id`/`job_id` são identidade (hash de conteúdo ou UUID) -
  NUNCA um caminho absoluto de Windows (pedido explícito do usuário:
  caminho é localização, pode mudar entre máquina/sessão sem o documento
  ter mudado; identidade não pode).
- `Candidate` guarda `raw_value` (exatamente como apareceu no texto) E
  `normalized_value` (forma pronta pro Excel, ex: 1234.56 em vez de
  "R$ 1.234,56") separados - nunca descarta o valor bruto original.
- Checkpoint (`JobState`) é por REGISTRO (record_id), não por chunk de
  caracteres - um record falhando não derruba os outros.

Nenhum arquivo existente foi tocado pra criar este módulo (novo, isolado,
dentro do pacote `documents/` que já existia). As fases seguintes (parser
real de DOCX produzindo isto, motor de candidatos por regex, segmentador,
job planner/executor, resolvedor semântico via LLM, validação/merge,
escritor de XLSX) ainda não foram implementadas.
"""
from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass, field
from enum import Enum
from typing import Optional, Union

# ---------------------------------------------------------------------------
# Block
# ---------------------------------------------------------------------------


class BlockType(str, Enum):
    PARAGRAPH = "paragraph"
    HEADING = "heading"
    TABLE = "table"
    IMAGE = "image"


@dataclass
class BlockSource:
    """De onde, na estrutura ORIGINAL do documento-fonte, um bloco veio.

    Todos os campos são opcionais - cada parser (DOCX/PDF/XLSX/PPTX/TXT,
    mesmo que só o de DOCX vá existir de fato por enquanto) só preenche os
    que fazem sentido pra ele. Um bloco de tabela DOCX preenche
    table_index/row_index; um parágrafo solto preenche só
    paragraph_index; uma imagem embutida preenche relationship_id (o
    rId do XML do DOCX); um bloco de PDF, no futuro, preenche
    page_number. Nenhum campo aqui é obrigatório em lugar nenhum -
    existir com tudo `None` é um estado válido."""

    paragraph_index: Optional[int] = None
    table_index: Optional[int] = None
    row_index: Optional[int] = None
    column_index: Optional[int] = None
    relationship_id: Optional[str] = None
    page_number: Optional[int] = None


@dataclass
class ImageMedia:
    filename: Optional[str] = None
    mime_type: Optional[str] = None


@dataclass
class Block:
    """Unidade estrutural mínima e comum a qualquer parser.

    `type` decide quais campos abaixo fazem sentido:
      paragraph -> text_raw / text_normalized
      heading   -> text_raw / text_normalized + level
      table     -> headers + rows (NUNCA achatado em texto aqui)
      image     -> media (+ text_raw/text_normalized só se um OCR futuro
                   preencher uma transcrição da imagem)

    `order` é a posição real do bloco no documento original (0-based,
    contínua entre parágrafos/tabelas/imagens juntos) - é o que garante
    que reconstruir o documento na ordem certa não dependa de nenhuma
    lógica externa ao schema.
    """

    id: str
    type: BlockType
    order: int
    source: BlockSource = field(default_factory=BlockSource)

    text_raw: Optional[str] = None
    text_normalized: Optional[str] = None

    level: Optional[int] = None

    headers: Optional[list[str]] = None
    rows: Optional[list[list[str]]] = None

    media: Optional[ImageMedia] = None

    def to_dict(self) -> dict:
        d = asdict(self)
        d["type"] = self.type.value if isinstance(self.type, BlockType) else self.type
        return d

    @staticmethod
    def from_dict(data: dict) -> "Block":
        data = dict(data)
        data["type"] = BlockType(data["type"])
        source = data.get("source")
        data["source"] = BlockSource(**source) if source else BlockSource()
        media = data.get("media")
        data["media"] = ImageMedia(**media) if media else None
        return Block(**data)


# ---------------------------------------------------------------------------
# NormalizedDocument
# ---------------------------------------------------------------------------


@dataclass
class DocumentMetadata:
    title: Optional[str] = None
    author: Optional[str] = None
    created_at: Optional[str] = None


@dataclass
class NormalizedDocument:
    """Representação comum de QUALQUER documento-fonte, depois de passar
    pelo parser estrutural dele (Fase 2 em diante - ainda não existe
    nenhum parser real produzindo isto). `document_id` é identidade
    (hash de conteúdo, ver `compute_document_id` abaixo, ou UUID) - nunca
    um caminho de arquivo."""

    document_id: str
    source_name: str
    source_type: str
    metadata: DocumentMetadata = field(default_factory=DocumentMetadata)
    blocks: list[Block] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "document_id": self.document_id,
            "source_name": self.source_name,
            "source_type": self.source_type,
            "metadata": asdict(self.metadata),
            "blocks": [b.to_dict() for b in self.blocks],
        }

    def to_json(self, **kwargs) -> str:
        return json.dumps(self.to_dict(), ensure_ascii=False, **kwargs)

    @staticmethod
    def from_dict(data: dict) -> "NormalizedDocument":
        return NormalizedDocument(
            document_id=data["document_id"],
            source_name=data["source_name"],
            source_type=data["source_type"],
            metadata=DocumentMetadata(**(data.get("metadata") or {})),
            blocks=[Block.from_dict(b) for b in data.get("blocks", [])],
        )

    @staticmethod
    def from_json(raw: str) -> "NormalizedDocument":
        return NormalizedDocument.from_dict(json.loads(raw))


def compute_document_id(content: bytes) -> str:
    """Gera um `document_id` estável a partir do CONTEÚDO do arquivo
    (sha256), nunca do caminho - dois arquivos idênticos (pastas ou
    máquinas diferentes) resolvem pro mesmo id; o mesmo arquivo renomeado
    ou movido mantém o id. Uso esperado:
    `compute_document_id(path.read_bytes())`."""
    return hashlib.sha256(content).hexdigest()


# ---------------------------------------------------------------------------
# Record / Candidate
# ---------------------------------------------------------------------------


class RecordKind(str, Enum):
    PRODUCT = "product"
    CONTRACT = "contract"
    PERSON = "person"
    COMPANY = "company"
    INVOICE = "invoice"
    EVENT = "event"
    UNKNOWN = "unknown"


@dataclass
class Record:
    """Um agrupamento de blocos que o SEGMENTADOR (Fase 5 - ver
    `phoenix_kernel/documents/record_segmenter.py`) acredita representar
    uma entidade útil (um produto, um contrato, uma pessoa...). `kind`
    começa e pode permanecer `UNKNOWN` até outra etapa classificar; não é
    obrigação do segmentador decidir isso de cara - ele SÓ agrupa, nunca
    valida/corrige um Candidate nem decide o que a entidade É (pedido
    explícito do usuário: separar "agrupar" de "interpretar").

    PHX-NEW (2026-08-29, especificação fechada pelo usuário pra Fase 5):
    `candidate_ids` referencia os `Candidate.id` que caíram dentro dos
    blocos deste record (ver `id` novo em `Candidate` abaixo);
    `start_order`/`end_order` são o menor/maior `Block.order` do grupo -
    dá pra saber o "alcance" do record no documento sem reabrir os blocos;
    `segmentation_method` documenta COMO esse agrupamento foi decidido
    (ex: "structural+heuristic" - nunca inventa um método que não usou)."""

    record_id: str
    block_ids: list[str] = field(default_factory=list)
    kind: RecordKind = RecordKind.UNKNOWN
    confidence: float = 0.0
    candidate_ids: list[str] = field(default_factory=list)
    start_order: Optional[int] = None
    end_order: Optional[int] = None
    segmentation_method: Optional[str] = None

    def to_dict(self) -> dict:
        d = asdict(self)
        d["kind"] = self.kind.value if isinstance(self.kind, RecordKind) else self.kind
        return d

    @staticmethod
    def from_dict(data: dict) -> "Record":
        data = dict(data)
        data["kind"] = RecordKind(data.get("kind", "unknown"))
        return Record(**data)


@dataclass
class Candidate:
    """Um valor que o CANDIDATE ENGINE (Fase 4 - ver
    `phoenix_kernel/documents/candidate_engine.py`) encontrou dentro de um
    bloco - "o documento contém isso", nunca "isso vai pra coluna X" (essa
    segunda decisão cabe à validação/LLM, fases seguintes). `raw_value` e
    `normalized_value` são guardados separados de propósito - o valor
    bruto nunca é descartado, mesmo depois de normalizado.

    PHX-NEW (2026-08-29, especificação fechada pelo usuário pra Fase 4):
    `valid` é preservado mesmo quando `False` - "achar um padrão != aceitar
    como verdade" (achado real do usuário: um EAN de 13 dígitos com dígito
    verificador ERRADO ainda é um CANDIDATE válido de existir, só não é um
    EAN válido; descartar essa ocorrência jogaria fora evidência que uma
    fase futura de conflito/Evidence pode precisar). `start`/`end` são o
    offset de `raw_value` dentro do texto onde foi encontrado (não dentro
    do documento inteiro - dentro do texto daquele bloco/célula
    especificamente); `context_before`/`context_after` são uns poucos
    caracteres ao redor, pra ajudar uma fase semântica futura a desambiguar
    sem precisar reler o bloco inteiro.

    PHX-FIX (2026-08-29, achado real testando a Fase 6/Evidence Engine -
    ver PHX-FIX em `normalizer.py`/`NormalizationResult` pro contexto
    completo): `unit`/`original_unit`/`parsed_value` propagam pra cá o
    mesmo raciocínio dimensional do Normalizer (Fase 3) - `normalized_value`
    de um campo dimensional (ex: `weight`) já vem CONVERTIDO pra unidade
    canônica (`unit`), enquanto `parsed_value`/`original_unit` preservam o
    número e a unidade exatamente como apareceram no texto, antes da
    conversão - nunca descartados, pela mesma regra de nunca jogar fora
    `raw_value`.

    PHX-NEW (2026-08-29, especificação fechada pelo usuário pra Fase 8 -
    Semantic Resolver): `model`/`task_id`/`input_hash`/`output_hash`/
    `schema_version` existem só pra rastreabilidade de um Candidate
    SINTÉTICO criado a partir de uma resposta de LLM
    (`method="llm_semantic"`, ver `semantic_resolver.py`) - todo Candidate
    de qualquer outro método (regex/label/table) deixa esses 5 campos como
    `None`, sem custo nenhum pros métodos determinísticos já existentes
    (extensão estritamente aditiva, mesma disciplina de todas as fases
    anteriores). "LLM nunca cria autoridade; LLM cria Evidence" - por isso
    um Candidate `llm_semantic` passa pelo MESMO `evidence_engine.py`
    (Fase 6) e pela MESMA agregação de confiança/conflito que qualquer
    outra fonte, nunca decidindo um campo sozinho."""

    field_type: str
    raw_value: str
    block_id: str
    normalized_value: Optional[Union[str, float, int]] = None
    method: str = "regex"
    confidence: float = 1.0
    valid: bool = True
    start: Optional[int] = None
    end: Optional[int] = None
    context_before: Optional[str] = None
    context_after: Optional[str] = None
    id: Optional[str] = None
    unit: Optional[str] = None
    original_unit: Optional[str] = None
    parsed_value: Optional[float] = None
    model: Optional[str] = None
    task_id: Optional[str] = None
    input_hash: Optional[str] = None
    output_hash: Optional[str] = None
    schema_version: Optional[str] = None

    def to_dict(self) -> dict:
        return asdict(self)

    @staticmethod
    def from_dict(data: dict) -> "Candidate":
        return Candidate(**data)


# ---------------------------------------------------------------------------
# JobPlan / JobState
# ---------------------------------------------------------------------------


class RecordStatus(str, Enum):
    PENDING = "pending"
    PROCESSING = "processing"
    DONE = "done"
    FAILED = "failed"
    SKIPPED = "skipped"


@dataclass
class JobSource:
    document_id: str


@dataclass
class JobTarget:
    type: str
    path: str


@dataclass
class ColumnMapping:
    """PHX-NEW (2026-08-29, especificação fechada pelo usuário pra Fase 10
    - XLSX Output Writer): liga UMA coluna real de um template de destino
    (`header`, o texto exato da célula de cabeçalho no arquivo real, ex:
    "Código de Barras") a UM `field_type` interno da Phoenix (o mesmo
    vocabulário de `Candidate.field_type`/`FieldEvidence.field_type`, ex:
    "ean"). O Writer (`output_writer.py`) NUNCA infere essa ligação
    sozinho - ela vem de fora, resolvida contra os headers reais do
    template (pedido explícito: "não invente esses valores no código").
    `required=True` não faz o Writer abortar o workbook inteiro quando o
    campo está ausente de um `CanonicalRecord` - só faz a célula ficar
    vazia e gera uma linha de auditoria `missing_required` na aba
    `_PHOENIX_AUDIT` (ver `output_writer.py`)."""

    header: str
    field_type: str
    required: bool = False

    def to_dict(self) -> dict:
        return asdict(self)

    @staticmethod
    def from_dict(data: dict) -> "ColumnMapping":
        return ColumnMapping(**data)


def _normalize_column(column: Union[str, "ColumnMapping", dict]) -> "ColumnMapping":
    """Aceita tanto o formato antigo (string solta, ex: "ean" - uso já
    existente desde a Fase 1/7, ver `TESTS/test_job_executor.py`) quanto o
    novo `ColumnMapping` explícito, sem quebrar quem já chama
    `JobMapping(columns=["ean", "price"])`. Uma string solta vira
    `ColumnMapping(header=x, field_type=x, required=False)` - o nome da
    coluna e o field_type são o mesmo texto, exatamente o comportamento
    implícito que já existia antes deste campo ficar explícito."""
    if isinstance(column, ColumnMapping):
        return column
    if isinstance(column, dict):
        return ColumnMapping(**column)
    return ColumnMapping(header=column, field_type=column, required=False)


@dataclass
class JobMapping:
    # PHX-FIX (2026-08-29, especificação fechada pelo usuário pra Fase 10):
    # aceita `list[str | ColumnMapping]` - mantido como `list` bruta aqui
    # (sem normalizar no __init__) de propósito, pra `to_dict`/`from_dict`/
    # comparação direta (`==`) contra `JobMapping(columns=["ean"])`, como já
    # usado em `TESTS/test_job_executor.py`, continuarem funcionando
    # IDÊNTICOS a antes. `resolved_columns()` é o ponto único de
    # normalização - use-o em vez de iterar `columns` direto sempre que o
    # tipo (`ColumnMapping`) importar.
    columns: list[Union[str, "ColumnMapping"]] = field(default_factory=list)

    def resolved_columns(self) -> list["ColumnMapping"]:
        return [_normalize_column(c) for c in self.columns]


@dataclass
class JobStrategy:
    preserve_structure: bool = True
    deterministic_first: bool = True
    llm_fallback: bool = True
    checkpoint: bool = True
    deduplicate: bool = True
    # PHX-NEW (2026-08-29, especificação fechada pelo usuário pra Fase 10):
    # como o Writer trata um campo `conflict`/`invalid`/`missing_required`.
    # "blank" (default) = célula vazia + linha em `_PHOENIX_AUDIT` (o único
    # comportamento de fato IMPLEMENTADO pelo Writer nesta fase - pedido
    # explícito do usuário: "nesta Fase 10 o padrão deve ser: blank +
    # audit"). "skip_row"/"error" ficam reservados no vocabulário pra uma
    # fase futura configurar sem mudar o contrato - `output_writer.py`
    # levanta `NotImplementedError` se receber qualquer valor diferente de
    # "blank", nunca finge suportar silenciosamente.
    conflict_policy: str = "blank"


@dataclass
class JobPlan:
    """O plano formal que a Phoenix vai montar internamente (Fase 7, Job
    Planner/Executor - ver `job_executor.py` pra a parte de EXECUÇÃO,
    já implementada; a parte de gerar este `JobPlan` a partir de um
    pedido em linguagem natural continua fora de escopo, não pedida
    ainda) quando o usuário pede algo tipo "leia a conversa e preencha a
    planilha". `sources` referencia `document_id`, nunca caminho absoluto
    - mesma regra do `NormalizedDocument`."""

    job_id: str
    operation: str
    sources: list[JobSource]
    target: JobTarget
    mapping: JobMapping = field(default_factory=JobMapping)
    strategy: JobStrategy = field(default_factory=JobStrategy)

    def to_dict(self) -> dict:
        return {
            "job_id": self.job_id,
            "operation": self.operation,
            "sources": [asdict(s) for s in self.sources],
            "target": asdict(self.target),
            "mapping": asdict(self.mapping),
            "strategy": asdict(self.strategy),
        }

    @staticmethod
    def from_dict(data: dict) -> "JobPlan":
        return JobPlan(
            job_id=data["job_id"],
            operation=data["operation"],
            sources=[JobSource(**s) for s in data.get("sources", [])],
            target=JobTarget(**data["target"]),
            mapping=JobMapping(**(data.get("mapping") or {})),
            strategy=JobStrategy(**(data.get("strategy") or {})),
        )


@dataclass
class RecordState:
    status: RecordStatus = RecordStatus.PENDING
    attempts: int = 0


@dataclass
class Task:
    """PHX-NEW (2026-08-29, especificação fechada pelo usuário pra Fase 7
    - Job Planner/Executor): a unidade de trabalho real do Executor -
    NUNCA um chunk de caracteres ("Task não é Chunk", regra explícita
    dele). `task_id` é determinístico e ESTÁVEL
    (`f"task_{record_id}_{operation}"`, montado por
    `job_executor.create_tasks_from_job_plan`), nunca sequencial
    (`task_00001`, `task_00002`...) - rodar o planejamento do MESMO job
    duas vezes produz exatamente os MESMOS `task_id`s, o que é o que torna
    checkpoint/resume possível.

    `dependencies` referencia outros `task_id`s que precisam estar `DONE`
    antes desta tarefa poder rodar - a Fase 7 nunca cria dependência
    nenhuma ainda (cada `Record` é independente, mesma filosofia de
    checkpoint por registro desde a Fase 1), mas o campo já existe pronto
    pra quando um job precisar de um pipeline de várias etapas por record
    (ex: `task_r0042_extract` -> `task_r0042_map` -> `task_r0042_validate`
    -> `task_r0042_write`, exemplo dado pelo usuário).

    `input_hash`/`output_hash` são o mecanismo de IDEMPOTÊNCIA pedido
    explicitamente (ver `job_executor.compute_input_hash`/
    `merge_with_previous_state`): reexecutar o planejamento com o MESMO
    `input_hash` de uma tarefa já `DONE` reaproveita o resultado anterior
    em vez de refazer o trabalho; um `input_hash` diferente significa que
    a entrada mudou de verdade e a tarefa precisa ser refeita."""

    task_id: str
    job_id: str
    record_id: str
    operation: str
    status: RecordStatus = RecordStatus.PENDING
    dependencies: list[str] = field(default_factory=list)
    attempts: int = 0
    input_hash: Optional[str] = None
    output_hash: Optional[str] = None

    def to_dict(self) -> dict:
        d = asdict(self)
        d["status"] = self.status.value if isinstance(self.status, RecordStatus) else self.status
        return d

    @staticmethod
    def from_dict(data: dict) -> "Task":
        data = dict(data)
        data["status"] = RecordStatus(data.get("status", "pending"))
        return Task(**data)


@dataclass
class JobState:
    """Estado retomável de um job. `records` (Fase 1 original) rastreia
    status/tentativas por REGISTRO (`record_id`) - mantido por
    compatibilidade, sem nenhuma mudança de comportamento. `tasks` (Fase
    7, NOVO - PHX-NEW 2026-08-29) é o que o Job Executor de fato lê/
    escreve: um dict `task_id -> Task`, com a granularidade mais rica que
    a Fase 7 precisa (dependências, hashes de idempotência). Achado
    central de toda a rodada de alinhamento que motivou este módulo desde
    a Fase 1: um chunk grande falhando derruba N produtos de uma vez; uma
    tarefa falhando derruba só ela, o resto do job continua."""

    job_id: str
    records: dict[str, RecordState] = field(default_factory=dict)
    tasks: dict[str, Task] = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {
            "job_id": self.job_id,
            "records": {
                rid: {"status": rs.status.value, "attempts": rs.attempts}
                for rid, rs in self.records.items()
            },
            "tasks": {tid: t.to_dict() for tid, t in self.tasks.items()},
        }

    def to_json(self, **kwargs) -> str:
        return json.dumps(self.to_dict(), ensure_ascii=False, **kwargs)

    @staticmethod
    def from_dict(data: dict) -> "JobState":
        return JobState(
            job_id=data["job_id"],
            records={
                rid: RecordState(status=RecordStatus(rs["status"]), attempts=rs.get("attempts", 0))
                for rid, rs in (data.get("records") or {}).items()
            },
            tasks={
                tid: Task.from_dict(t) for tid, t in (data.get("tasks") or {}).items()
            },
        )

    @staticmethod
    def from_json(raw: str) -> "JobState":
        return JobState.from_dict(json.loads(raw))
