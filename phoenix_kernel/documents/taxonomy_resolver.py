"""Phoenix Document Pipeline V2 - expansão de vocabulário V2, grupo
"semântico": Taxonomy Resolver (category/subcategory/store_category/
store_subcategory).

PHX-NEW (2026-08-29, especificação fechada pelo usuário depois de fechar
o grupo de preço): primeiro uso real da Fase 8 (`semantic_resolver.py`,
já fechada - este módulo NUNCA a modifica, só a REAPROVEITA) para um caso
que o vocabulário determinístico não resolve sozinho. Diferente de
peso/altura/marca/preço (que aparecem com rótulo explícito, "achar padrão"
basta), a CATEGORIA de um produto quase nunca vem rotulada nos dois
documentos-fonte reais - ela precisa ser INFERIDA a partir de outros
campos já conhecidos (nome do produto, marca, tags, descrição) -
exatamente o tipo de interpretação que a Fase 8 foi desenhada pra cobrir
("LLM entra onde há interpretação real, nunca pra reconhecer rótulo
explícito").

DECISÃO EXPLÍCITA DO USUÁRIO SOBRE A ALLOWLIST (o ponto mais importante
deste módulo, resolvido AQUI, não deixado implícito): a lista de
categorias/subcategorias válidas NUNCA é inferida livremente dos dois
documentos-fonte - eles têm linguagem de estratégia/marketing/exemplo
("Doces e Impulso", "Destilados / Adega", "item estratégico de inclusão")
que pode ou não ser uma categoria comercial de verdade; tratar qualquer
frase que apareça como taxonomia oficial contaminaria a allowlist que o
LLM recebe (e a validação estrita da Fase 8 fica sem sentido se a própria
allowlist já é ruído). Ordem de prioridade da fonte da allowlist,
implementada em `resolve_taxonomy_source` abaixo, do usuário:
  1. categorias oficiais já existentes no ERP/template real de destino
     (`erp_template_values`).
  2. configuração explícita do JobPlan (`job_plan_values`).
  3. catálogo mestre externo fornecido pelo usuário (`external_catalog_values`).
  4. só na AUSÊNCIA de tudo isso: candidatos inferidos dos documentos
     (`inferred_from_documents`) - e mesmo aí sempre marcados
     `origin="provisional"`, nunca tratados como oficiais silenciosamente.
Este módulo NUNCA preenche o nível 4 sozinho a partir de texto de
documento - quem chama precisa passar `inferred_from_documents`
explicitamente, sabendo que está fazendo isso; nenhuma função aqui lê
`NormalizedDocument`/`Block` pra "descobrir" categorias.

HIERARQUIA (pedido explícito): `category`->`subcategory` e
`store_category`->`store_subcategory` são DOIS PARES INDEPENDENTES - o
catálogo do ERP e a vitrine da loja virtual podem ter taxonomias
diferentes; nunca assumir que são a mesma lista, mesmo quando as duas
coincidem no primeiro teste real. Cada par é resolvido em DUAS chamadas
separadas ao LLM, nunca uma allowlist gigante numa pergunta só: primeiro
resolve o nível pai (allowlist fixa, `TaxonomyLevel.allowed_values_for()`
sem argumento), só DEPOIS a allowlist do filho é REDUZIDA pelo valor
escolhido no pai (`allowed_values_for(parent_value)`, via
`values_by_parent`) - "Bebidas" escolhido reduz a allowlist de
subcategoria pra só as opções de bebida, nunca a lista inteira do
catálogo na mesma pergunta (melhora precisão, reduz tokens, dificulta
resposta absurda - exatamente como pedido).

GATING (reaproveita a Fase 8 sem duplicar lógica nenhuma):
`needs_taxonomy_resolution` - se já existe `FieldEvidence` pro próprio
field_type (ex: um rótulo explícito "Categoria: X" que um detector
determinístico futuro capture) e `semantic_resolver.
needs_semantic_resolution` já diz que essa evidência é boa o bastante,
este módulo respeita isso e NUNCA chama o LLM pra aquele nível - "achar
padrão determinístico primeiro, LLM só quando falta" continua valendo
aqui. Quando não existe NENHUM `FieldEvidence` pro campo (caso comum
hoje - nenhum documento rotula categoria explicitamente), a resolução
por contexto (nome/marca/tags/descrição) é o único caminho disponível.

PHX-NEW - LIMITE DOCUMENTADO DE PROPÓSITO (pedido explícito do usuário,
pra ninguém reaproveitar a mesma garantia de segurança fora de
contexto):

    Semantic Resolver V1 (este módulo e a Fase 8)
        -> classificação em espaço FECHADO e PEQUENO
        -> validação estrita por allowlist é uma defesa real

    Semantic Resolver futuro (NÃO implementado aqui)
        -> geração aberta / resumo / texto livre
        -> a MESMA allowlist estrita NÃO SERVE de defesa (não existe
           allowlist pra texto livre) - exigiria outro contrato de
           validação (algo como um golden-set de comparação), nunca
           este mecanismo.

Isso evita que alguém reaproveite amanhã `parse_and_validate_response`/
`allowed_values` pra uma tarefa de geração aberta achando que a mesma
garantia de segurança contra prompt injection continua valendo - ela só
vale enquanto o espaço de resposta é fechado.

O QUE ESTE MÓDULO NÃO FAZ (limitação desta primeira versão, documentada
de propósito, mesmo espírito das fases anteriores): não chama um LLM de
verdade (`llm_call_fn` injetado, mesmo padrão da Fase 8); não decide a
allowlist real do MarketUP sozinho (a lista real ainda não foi extraída/
fornecida - por isso os testes automatizados usam uma fixture pequena e
configurável, ver `TESTS/test_taxonomy_resolver.py`; o smoke test com
Qwen real fica em `taxonomy_resolver_smoke_test.py`, a rodar na máquina
do usuário quando a allowlist real existir); não decide QUAIS campos
formam o contexto de classificação além do default documentado
(`_DEFAULT_CONTEXT_FIELDS`) - isso é configurável via parâmetro."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional

from phoenix_kernel.documents.evidence_engine import FieldEvidence
from phoenix_kernel.documents.normalized import Candidate
from phoenix_kernel.documents.semantic_resolver import (
    SemanticResolutionRejected,
    SemanticTask,
    needs_semantic_resolution,
    parse_and_validate_response,
    resolution_to_candidate,
)

# Mesmo limiar/mesma semântica do `_DEFAULT_HIGH_CONFIDENCE_THRESHOLD` da
# Fase 8 (não importado de lá de propósito - é um nome privado daquele
# módulo; duplicado aqui como constante documentada, mesmo padrão de
# "limiar arbitrário sempre documentado" já usado nas fases anteriores).
_DEFAULT_HIGH_CONFIDENCE_THRESHOLD = 0.85

# Campos de CONTEXTO já resolvidos (Fase 6) usados por padrão pra montar
# os trechos de evidência de uma tarefa de categoria - nunca o documento/
# record inteiro, só o VALOR já resolvido destes poucos campos, mesmo
# espírito de "microtarefa fechada" da Fase 8. Configurável via
# `context_source_fields` em `resolve_taxonomy_pair`.
_DEFAULT_CONTEXT_FIELDS = ("explicit_product_name", "brand", "tags", "description_html")

_PARENT_QUESTION_TEMPLATE = (
    "Qual valor de '{field_type}' melhor descreve este produto, com base nas informações abaixo?"
)
_CHILD_QUESTION_TEMPLATE = (
    "Dado que '{parent_field_type}' já foi resolvido como \"{parent_value}\", qual valor de "
    "'{field_type}' melhor descreve este produto, com base nas informações abaixo?"
)


@dataclass(frozen=True)
class TaxonomySource:
    """Proveniência de uma allowlist - nunca só os valores soltos, sempre
    junto de ONDE vieram (`origin`), pra nunca confundir uma lista oficial
    com uma lista provisória inferida de texto de documento."""

    values: list
    origin: str  # "official_erp" | "job_plan" | "external_catalog" | "provisional" | "none"


def resolve_taxonomy_source(
    *,
    erp_template_values: Optional[list] = None,
    job_plan_values: Optional[list] = None,
    external_catalog_values: Optional[list] = None,
    inferred_from_documents: Optional[list] = None,
) -> TaxonomySource:
    """Implementa a ordem de prioridade pedida explicitamente pelo usuário
    (ver docstring do módulo): a primeira fonte não-vazia, nesta ordem
    exata, vence - `erp_template_values` > `job_plan_values` >
    `external_catalog_values` > `inferred_from_documents`. Só devolve
    `origin="provisional"` quando NENHUMA das três fontes "oficiais" foi
    passada E `inferred_from_documents` foi passado explicitamente por
    quem chama (este módulo nunca preenche esse argumento sozinho).
    `origin="none"` quando nenhuma fonte foi passada - sinal explícito
    pra quem chama de que não há allowlist nenhuma disponível ainda
    (`TaxonomyLevel.allowed_values_for` devolve lista vazia nesse caso,
    e `resolve_taxonomy_pair` pula a resolução em vez de perguntar ao LLM
    sem allowlist nenhuma pra validar a resposta)."""
    if erp_template_values:
        return TaxonomySource(values=list(erp_template_values), origin="official_erp")
    if job_plan_values:
        return TaxonomySource(values=list(job_plan_values), origin="job_plan")
    if external_catalog_values:
        return TaxonomySource(values=list(external_catalog_values), origin="external_catalog")
    if inferred_from_documents:
        return TaxonomySource(values=list(inferred_from_documents), origin="provisional")
    return TaxonomySource(values=[], origin="none")


@dataclass
class TaxonomyLevel:
    """Um nível de taxonomia. Um nível RAIZ (`category`/`store_category`)
    tem uma allowlist FIXA (`source.values`); um nível FILHO
    (`subcategory`/`store_subcategory`, `parent_field_type` preenchido)
    tem uma allowlist DEPENDENTE do valor escolhido no pai
    (`values_by_parent`) - nunca as duas coisas ao mesmo tempo. Isso é o
    que implementa a redução hierárquica pedida: perguntar só as ~6
    subcategorias de "Bebidas", nunca as ~80 subcategorias do catálogo
    inteiro na mesma pergunta."""

    field_type: str
    source: TaxonomySource
    parent_field_type: Optional[str] = None
    values_by_parent: Optional[dict] = None

    def allowed_values_for(self, parent_value: Optional[str] = None) -> list:
        if self.parent_field_type is None:
            return list(self.source.values)
        if parent_value is None or not self.values_by_parent:
            return []
        return list(self.values_by_parent.get(parent_value, []))


def build_context_snippets(
    fields: dict,
    *,
    source_fields: tuple = _DEFAULT_CONTEXT_FIELDS,
    max_snippets: int = 5,
) -> list:
    """Monta os trechos de contexto pra uma tarefa de classificação a
    partir de `FieldEvidence`s JÁ RESOLVIDOS de OUTROS campos (nome do
    produto, marca, tags, descrição) - nunca texto bruto do documento
    inteiro, mesmo espírito de "microtarefa fechada" da Fase 8. Campos
    ausentes ou sem valor (`fe.value` None/vazio) são pulados em
    silêncio - não é erro um produto não ter, por exemplo, `brand`
    resolvido."""
    snippets: list = []
    for field_type in source_fields:
        fe: Optional[FieldEvidence] = fields.get(field_type)
        if fe is None or fe.value in (None, ""):
            continue
        snippets.append(f"{field_type}={fe.value!r}")
        if len(snippets) >= max_snippets:
            break
    return snippets


def needs_taxonomy_resolution(
    existing_field_evidence: Optional[FieldEvidence],
    *,
    high_confidence_threshold: float = _DEFAULT_HIGH_CONFIDENCE_THRESHOLD,
) -> bool:
    """Gating deste módulo: quando NÃO existe nenhum `FieldEvidence` pro
    campo (caso comum hoje - nenhum candidato determinístico pra
    category/subcategory/store_category/store_subcategory), a resolução
    por contexto é o único caminho, então sempre `True`. Quando EXISTE
    (um detector determinístico futuro capturou um rótulo explícito),
    delega inteiramente pro gating já fechado da Fase 8
    (`semantic_resolver.needs_semantic_resolution`) - nunca reimplementa
    a lógica de status confirmed/probable/ambiguous/conflict/invalid
    aqui."""
    if existing_field_evidence is None:
        return True
    return needs_semantic_resolution(
        existing_field_evidence, high_confidence_threshold=high_confidence_threshold
    )


def build_taxonomy_task(
    record_id: str,
    field_type: str,
    allowed_values: list,
    context_snippets: list,
    *,
    question: Optional[str] = None,
    schema_version: str = "v1",
) -> SemanticTask:
    """Monta a `SemanticTask` (Fase 8, tipo reaproveitado sem alteração)
    a partir de contexto de OUTROS campos, não do próprio `FieldEvidence`
    do field_type sendo classificado - diferença deliberada de
    `semantic_resolver.build_semantic_task` (que monta a partir do
    PRÓPRIO field_type, o caso de uso original da Fase 8, onde já existe
    evidência conflitante/ambígua do mesmo campo). `task_id` estável e
    semântico, mesma convenção "nunca sequencial" das fases anteriores."""
    task_id = f"task_{record_id}_taxonomy_{field_type}"
    return SemanticTask(
        task_id=task_id,
        record_id=record_id,
        field_type=field_type,
        question=question or _PARENT_QUESTION_TEMPLATE.format(field_type=field_type),
        allowed_values=list(allowed_values),
        evidence_snippets=list(context_snippets),
        schema_version=schema_version,
    )


@dataclass
class TaxonomyPairResult:
    """Resultado de uma tentativa de resolver um par pai/filho
    (`category`+`subcategory` ou `store_category`+`store_subcategory`).
    `parent_candidate`/`child_candidate` só vêm preenchidos quando o LLM
    foi de fato chamado e a resposta foi ACEITA (mesma garantia de
    isolamento de falha da Fase 8: nunca um valor inventado quando a
    resolução falha/é pulada). `parent_value` sempre reflete o valor
    EFETIVO do pai usado pra reduzir a allowlist do filho, seja ele vindo
    de uma leitura determinística já existente (LLM nem chamado pro pai)
    ou de uma resolução semântica nova."""

    parent_value: Optional[str] = None
    parent_candidate: Optional[Candidate] = None
    child_candidate: Optional[Candidate] = None
    skipped_reasons: list = field(default_factory=list)


def _resolve_one_level(
    record_id: str,
    level: TaxonomyLevel,
    existing_evidence: Optional[FieldEvidence],
    allowed_values: list,
    context_snippets: list,
    llm_call_fn,
    *,
    question: Optional[str] = None,
    model: Optional[str] = None,
    high_confidence_threshold: float,
) -> tuple[Optional[str], Optional[Candidate], Optional[str]]:
    """Helper interno partilhado pelos dois níveis (pai/filho) de
    `resolve_taxonomy_pair` - devolve (valor_efetivo, candidate_novo_ou_None,
    motivo_do_skip_ou_None). Nunca chama o LLM quando já existe leitura
    determinística boa o bastante (`needs_taxonomy_resolution`==False) -
    nesse caso devolve o valor JÁ EXISTENTE, sem `Candidate` novo."""
    if existing_evidence is not None and not needs_taxonomy_resolution(
        existing_evidence, high_confidence_threshold=high_confidence_threshold
    ):
        return existing_evidence.value, None, None

    if not allowed_values:
        return None, None, f"nenhuma allowlist disponível pra '{level.field_type}' (source={level.source.origin})"

    if not context_snippets:
        return None, None, f"sem contexto suficiente (nome/marca/tags/descrição ausentes) pra classificar '{level.field_type}'"

    task = build_taxonomy_task(record_id, level.field_type, allowed_values, context_snippets, question=question)
    raw_response = llm_call_fn(task)
    try:
        resolution = parse_and_validate_response(task, raw_response, model=model)
    except SemanticResolutionRejected as exc:
        return None, None, f"resposta do LLM rejeitada pra '{level.field_type}': {exc}"

    candidate = resolution_to_candidate(task, resolution, model=model)
    return resolution.selected_value, candidate, None


def resolve_taxonomy_pair(
    record_id: str,
    fields: dict,
    parent_level: TaxonomyLevel,
    child_level: TaxonomyLevel,
    llm_call_fn,
    *,
    context_source_fields: tuple = _DEFAULT_CONTEXT_FIELDS,
    model: Optional[str] = None,
    high_confidence_threshold: float = _DEFAULT_HIGH_CONFIDENCE_THRESHOLD,
) -> TaxonomyPairResult:
    """Ponto de entrada principal do grupo semântico: resolve um par
    hierárquico completo (`category`+`subcategory` ou
    `store_category`+`store_subcategory`) em ATÉ DUAS chamadas ao LLM
    (nunca uma allowlist gigante numa pergunta só - ver docstring do
    módulo). `fields` é o dict `field_type -> FieldEvidence` de UM record
    (mesmo formato que `CanonicalRecord.fields`/`identity_engine.
    build_canonical_record` já produz) - usado tanto pra checar se já
    existe leitura determinística de category/subcategory (gating) quanto
    pra montar o contexto (nome/marca/tags/descrição).

    Nunca lança - qualquer motivo de não resolver (sem allowlist, sem
    contexto, resposta rejeitada) fica registrado em
    `TaxonomyPairResult.skipped_reasons`, nunca interrompe o resto do
    pipeline (mesma garantia de isolamento de falha da Fase 7/8). Se o
    nível PAI não resolve (por qualquer motivo), o nível FILHO nem chega
    a ser tentado - não existe allowlist de subcategoria pra reduzir sem
    um valor de categoria."""
    result = TaxonomyPairResult()
    context_snippets = build_context_snippets(fields, source_fields=context_source_fields)

    parent_value, parent_candidate, parent_skip = _resolve_one_level(
        record_id, parent_level, fields.get(parent_level.field_type),
        parent_level.allowed_values_for(), context_snippets, llm_call_fn,
        question=_PARENT_QUESTION_TEMPLATE.format(field_type=parent_level.field_type),
        model=model, high_confidence_threshold=high_confidence_threshold,
    )
    result.parent_value = parent_value
    result.parent_candidate = parent_candidate
    if parent_skip:
        result.skipped_reasons.append(parent_skip)
    if parent_value is None:
        return result

    child_allowed = child_level.allowed_values_for(parent_value)
    _, child_candidate, child_skip = _resolve_one_level(
        record_id, child_level, fields.get(child_level.field_type),
        child_allowed, context_snippets, llm_call_fn,
        question=_CHILD_QUESTION_TEMPLATE.format(
            parent_field_type=parent_level.field_type, parent_value=parent_value, field_type=child_level.field_type,
        ),
        model=model, high_confidence_threshold=high_confidence_threshold,
    )
    result.child_candidate = child_candidate
    if child_skip:
        result.skipped_reasons.append(child_skip)
    return result
