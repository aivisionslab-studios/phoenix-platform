"""Testes do grupo semântico da expansão de vocabulário V2
(phoenix_kernel/documents/taxonomy_resolver.py) - category/subcategory/
store_category/store_subcategory via Fase 8 (Semantic Resolver),
reaproveitada sem modificação nenhuma. Ver PHX-NEW no topo daquele
arquivo pro contexto completo: ordem de prioridade da allowlist (nunca
inferida livremente dos documentos), hierarquia pai/filho reduzindo a
allowlist do filho, gating que reaproveita a Fase 8, e o limite
documentado sobre reusar a mesma validação por allowlist pra tarefas de
geração aberta.

Como a allowlist REAL do MarketUP ainda não foi extraída/fornecida (pedido
explícito do usuário: "implemente o resolver e os testes com uma fixture
pequena/configurável"), todos os testes abaixo usam uma fixture pequena
(4 categorias, poucas subcategorias por categoria) via `job_plan_values` -
o smoke test com Qwen real e a allowlist real ficam em
`taxonomy_resolver_smoke_test.py`, a rodar na máquina do usuário."""
from __future__ import annotations

from phoenix_kernel.documents.evidence_engine import EvidenceEntry, FieldEvidence
from phoenix_kernel.documents.semantic_resolver import SemanticTask
from phoenix_kernel.documents.taxonomy_resolver import (
    TaxonomyLevel,
    TaxonomySource,
    build_context_snippets,
    build_taxonomy_task,
    needs_taxonomy_resolution,
    resolve_taxonomy_pair,
    resolve_taxonomy_source,
)

CATEGORY_FIXTURE = ["Bebidas", "Alimentos", "Higiene", "Limpeza"]
SUBCATEGORY_BY_CATEGORY_FIXTURE = {
    "Bebidas": ["Cervejas", "Destilados", "Refrigerantes", "Sucos", "Energéticos", "Águas"],
    "Alimentos": ["Enlatados", "Massas"],
    # "Higiene"/"Limpeza" sem subcategorias na fixture de propósito - testa
    # o caso real "categoria resolvida, mas sem subcategoria conhecida".
}


def _category_level() -> TaxonomyLevel:
    return TaxonomyLevel(field_type="category", source=resolve_taxonomy_source(job_plan_values=CATEGORY_FIXTURE))


def _subcategory_level() -> TaxonomyLevel:
    return TaxonomyLevel(
        field_type="subcategory",
        source=resolve_taxonomy_source(job_plan_values=["placeholder - só documenta a origem, allowed_values_for usa values_by_parent"]),
        parent_field_type="category",
        values_by_parent=SUBCATEGORY_BY_CATEGORY_FIXTURE,
    )


def _field_evidence(status: str, *, value=None, final_confidence=None, field_type="category") -> FieldEvidence:
    entry = EvidenceEntry(
        candidate_id="c1", source="text", value=value, valid=True, confidence=final_confidence or 0.6,
        source_block="b1", source_record="r0", source_method="label", source_origin_hash="hash-b1",
    )
    return FieldEvidence(field_type=field_type, record_id="r0", status=status, value=value,
                          final_confidence=final_confidence, evidence=[entry])


def _fields_context(**overrides) -> dict:
    """Monta um dict `field_type -> FieldEvidence` representando um record
    já processado pelas Fases 4-6, com nome/marca/tags/descrição
    resolvidos - o contexto que uma classificação de categoria usa."""
    defaults = {
        "explicit_product_name": _field_evidence("confirmed", value="Pringles Hot & Spicy 165g", field_type="explicit_product_name"),
        "tags": _field_evidence("confirmed", value="snack; batata; picante; aperitivo", field_type="tags"),
        "description_html": _field_evidence("probable", value="Salgadinho tubular sabor picante.", final_confidence=0.7, field_type="description_html"),
    }
    defaults.update(overrides)
    return defaults


def _llm_stub(responses: dict, calls: list = None):
    """`llm_call_fn` falso - devolve a resposta configurada por
    `field_type` (nunca chama LLM de verdade, mesmo padrão de teste já
    usado em TESTS/test_semantic_resolver.py). `calls`, se passado,
    acumula as `SemanticTask`s recebidas - usado pra inspecionar
    `allowed_values`/`question` de cada chamada nos testes de redução
    hierárquica."""
    def _call(task: SemanticTask):
        if calls is not None:
            calls.append(task)
        if task.field_type not in responses:
            raise AssertionError(f"llm_call_fn chamado sem resposta configurada pra field_type={task.field_type!r}")
        return responses[task.field_type]
    return _call


# ---------------------------------------------------------------------------
# resolve_taxonomy_source - ordem de prioridade da allowlist
# ---------------------------------------------------------------------------

def test_taxonomy_source_prefers_erp_template_over_everything():
    source = resolve_taxonomy_source(
        erp_template_values=["A"], job_plan_values=["B"],
        external_catalog_values=["C"], inferred_from_documents=["D"],
    )
    assert source.values == ["A"]
    assert source.origin == "official_erp"


def test_taxonomy_source_prefers_job_plan_over_external_and_inferred():
    source = resolve_taxonomy_source(job_plan_values=["B"], external_catalog_values=["C"], inferred_from_documents=["D"])
    assert source.values == ["B"]
    assert source.origin == "job_plan"


def test_taxonomy_source_prefers_external_catalog_over_inferred():
    source = resolve_taxonomy_source(external_catalog_values=["C"], inferred_from_documents=["D"])
    assert source.values == ["C"]
    assert source.origin == "external_catalog"


def test_taxonomy_source_inferred_from_documents_is_always_provisional():
    """Achado real que motivou esta rodada: texto dos dois documentos tem
    linguagem de estratégia/marketing que pode não ser categoria oficial
    nenhuma - por isso esta é a ÚLTIMA fonte, e sempre marcada
    "provisional", nunca tratada como oficial silenciosamente."""
    source = resolve_taxonomy_source(inferred_from_documents=["Doces e Impulso"])
    assert source.values == ["Doces e Impulso"]
    assert source.origin == "provisional"


def test_taxonomy_source_with_nothing_passed_is_none_origin_and_empty():
    source = resolve_taxonomy_source()
    assert source.values == []
    assert source.origin == "none"


def test_taxonomy_source_never_infers_from_documents_automatically():
    """Nenhuma chamada sem `inferred_from_documents` explícito produz
    origin="provisional" - o módulo nunca preenche isso sozinho."""
    source = resolve_taxonomy_source()
    assert source.origin != "provisional"


# ---------------------------------------------------------------------------
# TaxonomyLevel - allowlist fixa (raiz) vs. reduzida por pai (filho)
# ---------------------------------------------------------------------------

def test_root_level_allowed_values_ignores_parent_value_argument():
    level = _category_level()
    assert level.allowed_values_for() == CATEGORY_FIXTURE
    assert level.allowed_values_for("qualquer coisa") == CATEGORY_FIXTURE


def test_child_level_without_parent_value_has_no_allowed_values():
    level = _subcategory_level()
    assert level.allowed_values_for() == []
    assert level.allowed_values_for(None) == []


def test_child_level_allowed_values_reduced_by_chosen_parent_value():
    level = _subcategory_level()
    assert level.allowed_values_for("Bebidas") == SUBCATEGORY_BY_CATEGORY_FIXTURE["Bebidas"]
    assert level.allowed_values_for("Alimentos") == SUBCATEGORY_BY_CATEGORY_FIXTURE["Alimentos"]


def test_child_level_unknown_parent_value_has_no_allowed_values():
    level = _subcategory_level()
    assert level.allowed_values_for("Higiene") == []


# ---------------------------------------------------------------------------
# build_context_snippets
# ---------------------------------------------------------------------------

def test_context_snippets_uses_default_fields_and_skips_missing():
    fields = _fields_context()
    del fields["description_html"]
    snippets = build_context_snippets(fields)
    assert any("explicit_product_name" in s for s in snippets)
    assert any("tags" in s for s in snippets)
    assert not any("description_html" in s for s in snippets)


def test_context_snippets_skips_empty_value_field():
    fields = _fields_context(brand=_field_evidence("invalid", value=None, field_type="brand"))
    snippets = build_context_snippets(fields, source_fields=("brand", "tags"))
    assert not any("brand=" in s for s in snippets)
    assert any("tags=" in s for s in snippets)


def test_context_snippets_respects_max_snippets():
    fields = _fields_context()
    snippets = build_context_snippets(fields, max_snippets=1)
    assert len(snippets) == 1


def test_context_snippets_empty_when_no_context_field_resolved():
    assert build_context_snippets({}) == []


# ---------------------------------------------------------------------------
# needs_taxonomy_resolution - gating (reaproveita a Fase 8)
# ---------------------------------------------------------------------------

def test_needs_resolution_true_when_no_existing_evidence_at_all():
    """Caso comum hoje: nenhum documento rotula categoria explicitamente,
    então não existe FieldEvidence nenhum pra 'category' - resolução por
    contexto é o único caminho."""
    assert needs_taxonomy_resolution(None) is True


def test_needs_resolution_false_when_existing_evidence_already_confirmed():
    fe = _field_evidence("confirmed", value="Bebidas", final_confidence=0.99)
    assert needs_taxonomy_resolution(fe) is False


def test_needs_resolution_true_when_existing_evidence_is_weak_probable():
    fe = _field_evidence("probable", value="Bebidas", final_confidence=0.6)
    assert needs_taxonomy_resolution(fe, high_confidence_threshold=0.85) is True


# ---------------------------------------------------------------------------
# resolve_taxonomy_pair - fluxo hierárquico completo
# ---------------------------------------------------------------------------

def test_happy_path_resolves_category_then_reduces_subcategory_allowlist():
    calls: list = []
    llm = _llm_stub(
        {
            "category": {"selected_value": "Bebidas", "confidence": 0.92, "reason": "snack de batata picante costuma ficar perto de bebidas na prateleira? não - mas o exemplo é só ilustrativo"},
            "subcategory": {"selected_value": "Refrigerantes", "confidence": 0.7, "reason": "..."},
        },
        calls=calls,
    )
    result = resolve_taxonomy_pair("r0", _fields_context(), _category_level(), _subcategory_level(), llm)

    assert result.parent_value == "Bebidas"
    assert result.parent_candidate.field_type == "category"
    assert result.parent_candidate.normalized_value == "Bebidas"
    assert result.parent_candidate.method == "llm_semantic"
    assert result.child_candidate.field_type == "subcategory"
    assert result.child_candidate.normalized_value == "Refrigerantes"
    assert result.skipped_reasons == []

    # a allowlist que a tarefa de subcategoria recebeu já veio REDUZIDA
    # pela categoria escolhida - nunca a lista inteira do catálogo.
    assert len(calls) == 2
    category_task, subcategory_task = calls
    assert category_task.allowed_values == CATEGORY_FIXTURE
    assert subcategory_task.allowed_values == SUBCATEGORY_BY_CATEGORY_FIXTURE["Bebidas"]
    assert "Bebidas" in subcategory_task.question


def test_no_context_available_skips_both_levels_without_calling_llm():
    calls: list = []
    llm = _llm_stub({"category": {"selected_value": "Bebidas", "confidence": 0.9}}, calls=calls)
    result = resolve_taxonomy_pair("r0", {}, _category_level(), _subcategory_level(), llm)

    assert result.parent_value is None
    assert result.parent_candidate is None
    assert result.child_candidate is None
    assert len(result.skipped_reasons) == 1
    assert "contexto" in result.skipped_reasons[0]
    assert calls == []  # LLM nunca chamado sem contexto nenhum pra oferecer


def test_no_allowlist_available_skips_without_calling_llm():
    empty_level = TaxonomyLevel(field_type="category", source=resolve_taxonomy_source())
    calls: list = []
    llm = _llm_stub({}, calls=calls)
    result = resolve_taxonomy_pair("r0", _fields_context(), empty_level, _subcategory_level(), llm)

    assert result.parent_value is None
    assert "allowlist" in result.skipped_reasons[0]
    assert calls == []


def test_existing_confirmed_category_skips_llm_but_still_resolves_subcategory():
    """Guarda pedida explicitamente pelo usuário: se já existe leitura
    determinística boa o bastante pra 'category' (ex: um rótulo explícito
    futuro), NÃO chama o LLM pra ela - mas o valor já existente ainda
    reduz a allowlist da subcategoria normalmente."""
    fields = _fields_context(category=_field_evidence("confirmed", value="Alimentos", final_confidence=0.99, field_type="category"))
    calls: list = []
    llm = _llm_stub({"subcategory": {"selected_value": "Massas", "confidence": 0.8}}, calls=calls)
    result = resolve_taxonomy_pair("r0", fields, _category_level(), _subcategory_level(), llm)

    assert result.parent_value == "Alimentos"
    assert result.parent_candidate is None  # LLM não foi chamado pro pai
    assert result.child_candidate.normalized_value == "Massas"
    assert len(calls) == 1  # só a chamada de subcategoria
    assert calls[0].field_type == "subcategory"
    assert calls[0].allowed_values == SUBCATEGORY_BY_CATEGORY_FIXTURE["Alimentos"]


def test_rejected_parent_response_never_attempts_child():
    """Resposta fora da allowlist é rejeitada pela MESMA validação
    estrita da Fase 8 (defesa contra prompt injection) - sem um valor de
    categoria válido, não existe allowlist de subcategoria pra reduzir,
    então o filho nem é tentado."""
    calls: list = []
    llm = _llm_stub({"category": {"selected_value": "Eletrônicos", "confidence": 0.9}}, calls=calls)
    result = resolve_taxonomy_pair("r0", _fields_context(), _category_level(), _subcategory_level(), llm)

    assert result.parent_value is None
    assert result.parent_candidate is None
    assert result.child_candidate is None
    assert "rejeitada" in result.skipped_reasons[0]
    assert len(calls) == 1  # nunca chegou a montar a tarefa de subcategoria


def test_child_without_known_values_for_chosen_parent_is_skipped_but_parent_still_resolved():
    """"Higiene"/"Limpeza" não têm subcategoria na fixture (achado real
    esperado: nem toda categoria tem uma lista de subcategorias fechada
    ainda) - a categoria resolve normalmente, a subcategoria é pulada com
    motivo explícito, nunca inventada."""
    calls: list = []
    llm = _llm_stub({"category": {"selected_value": "Higiene", "confidence": 0.85}}, calls=calls)
    result = resolve_taxonomy_pair("r0", _fields_context(), _category_level(), _subcategory_level(), llm)

    assert result.parent_value == "Higiene"
    assert result.parent_candidate.normalized_value == "Higiene"
    assert result.child_candidate is None
    assert any("subcategory" in reason for reason in result.skipped_reasons)
    assert len(calls) == 1  # só a chamada de categoria - filho nunca chega a perguntar ao LLM


def test_rejected_child_response_outside_reduced_allowlist_is_rejected():
    """A validação estrita da Fase 8 vale IGUAL pra allowlist reduzida do
    filho - um valor de fora do subconjunto de "Bebidas" (ex: "Massas",
    que só existe em "Alimentos") é rejeitado mesmo estando na lista
    MAIOR de todas as subcategorias conhecidas."""
    llm = _llm_stub({
        "category": {"selected_value": "Bebidas", "confidence": 0.9},
        "subcategory": {"selected_value": "Massas", "confidence": 0.9},
    })
    result = resolve_taxonomy_pair("r0", _fields_context(), _category_level(), _subcategory_level(), llm)

    assert result.parent_value == "Bebidas"
    assert result.child_candidate is None
    assert any("rejeitada" in reason for reason in result.skipped_reasons)


def test_store_category_pair_is_independent_from_category_pair():
    """Pedido explícito do usuário: category/subcategory (ERP) e
    store_category/store_subcategory (loja virtual) são DOIS PARES
    INDEPENDENTES - mesmo usando fixtures parecidas aqui, nada nesta
    função assume que as duas taxonomias coincidem."""
    store_category_level = TaxonomyLevel(
        field_type="store_category", source=resolve_taxonomy_source(job_plan_values=["Mercearia", "Bebidas e Petiscos"])
    )
    store_subcategory_level = TaxonomyLevel(
        field_type="store_subcategory", source=resolve_taxonomy_source(job_plan_values=["placeholder"]),
        parent_field_type="store_category",
        values_by_parent={"Bebidas e Petiscos": ["Cervejas Artesanais", "Snacks"]},
    )
    llm = _llm_stub({
        "store_category": {"selected_value": "Bebidas e Petiscos", "confidence": 0.8},
        "store_subcategory": {"selected_value": "Snacks", "confidence": 0.75},
    })
    result = resolve_taxonomy_pair("r0", _fields_context(), store_category_level, store_subcategory_level, llm)

    assert result.parent_value == "Bebidas e Petiscos"
    assert result.parent_candidate.field_type == "store_category"
    assert result.child_candidate.field_type == "store_subcategory"
    assert result.child_candidate.normalized_value == "Snacks"


# ---------------------------------------------------------------------------
# build_taxonomy_task - proveniência da tarefa
# ---------------------------------------------------------------------------

def test_build_taxonomy_task_has_stable_semantic_task_id():
    task = build_taxonomy_task("r0", "category", CATEGORY_FIXTURE, ["explicit_product_name='X'"])
    assert task.task_id == "task_r0_taxonomy_category"
    assert task.record_id == "r0"
    assert task.allowed_values == CATEGORY_FIXTURE
    assert task.evidence_snippets == ["explicit_product_name='X'"]
