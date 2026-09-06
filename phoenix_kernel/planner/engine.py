import logging
from core.domain.machine import MachineContext
from core.domain.execution import ExecutionPlan
from .interfaces import IPlannerService
from .knowledge_engine import KnowledgeEngine
from .evaluator import RuleEvaluator
from phoenix_kernel.intelligence.chroma_rag_backend import get_shared_chroma_backend
from phoenix_kernel.models.registry import ModelRegistry

logger = logging.getLogger(__name__)

class PlannerEngine(IPlannerService):
    def __init__(self, event_bus, kernel):
        # PHX-FIX (auditoria 2026-08-04): antes disso o comentário dizia
        # "Instancia o KnowledgeEngine real (ChromaDB)", mas nenhum
        # rag_backend era de fato passado — ficava sempre None, e
        # search_rag()/query_knowledge() sempre retornavam [] silenciosamente.
        # ChromaRagBackend nunca levanta exceção na conexão (fica apenas
        # .available == False e loga um warning), então isto é seguro mesmo
        # se o chromadb não estiver instalado ou o diretório não existir.
        # PHX-FIX (auditoria 2026-08-09): usa a instância compartilhada em
        # vez de abrir um ChromaRagBackend próprio - ReasoningEngine aponta
        # pro mesmo data/chroma_db, e dois clientes persistentes separados
        # no mesmo path dentro do processo arriscam corromper o índice HNSW.
        rag_backend = get_shared_chroma_backend(persist_dir="data/chroma_db")
        self.knowledge = KnowledgeEngine(event_bus, kernel, rag_backend=rag_backend)
        # PHX-NEW (destravar Ollama como 2ª opção de engine de texto):
        # ModelRegistry próprio (mesmo padrão que ResidentManager já usa
        # quando ninguém injeta um - só relê o catalog/models.json
        # estático, instanciar duas vezes no processo é inofensivo). Sem
        # isso, RuleEvaluator (usado pelo comando `infer`) não tinha como
        # saber que "ollama" existe como alternativa - tinha "llama.cpp"
        # e "qwen3:8b" hardcoded direto no meio da lógica.
        self.registry = ModelRegistry()
        self.evaluator = RuleEvaluator(self.knowledge, model_registry=self.registry)
        self.machine_context = None

    def set_context(self, context):
        self.machine_context = context

    async def initialize(self):
        # O initialize do KnowledgeEngine vai tentar garantir o modelo de embedding.
        # Se não conseguir (porque o Ollama foi removido), ele loga um aviso e
        # desativa o RAG internamente, mas NÃO QUEBRA a inicialização da Phoenix.
        await self.knowledge.initialize()

    async def plan_inference(self, context, user_prompt: str, model_hint: str = "") -> ExecutionPlan:
        return await self.evaluator.evaluate(context, user_prompt=user_prompt, model_hint=model_hint)

    async def resolve_package(self, pkg: dict) -> dict:
        """Retorna os metadados do pacote."""
        if not pkg: return None
        resolved = pkg.copy()
        resolved["resolved_models"] = ["Ver Catálogo"]
        return resolved