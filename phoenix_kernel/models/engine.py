import asyncio
import urllib.request
import json
import logging
from typing import Any, Optional
from .interfaces import IModelsService
from .model_scanner import ModelScanner

logger = logging.getLogger(__name__)

class ModelsEngine(IModelsService):
    def __init__(self):
        self._knowledge_engine = None  # injetado depois via set_knowledge_engine()

    def set_knowledge_engine(self, knowledge_engine) -> None:
        """Chamado pelo kernel.py depois que o Planner é criado, pra evitar
        que este serviço abra um client ChromaDB concorrente com o do
        KnowledgeEngine — ambos NUNCA devem ter client próprio pra mesma pasta."""
        self._knowledge_engine = knowledge_engine

    async def get_model_and_rag_status(self) -> dict[str, Any]:
        loop = asyncio.get_running_loop()

        # PHX-FIX (varredura 2026-08-21, achado 2): antes, uma falha ao
        # sondar o Ollama (offline/não instalado) virava silenciosamente
        # `models = []` - indistinguível de "genuinamente zero modelos
        # instalados" pra quem consome /api/state. Também nunca incluía os
        # modelos .gguf/.onnx/etc. que o ModelScanner já sabe escanear do
        # disco (usado em outro lugar do projeto, nunca aqui) -
        # sub-representando o que a máquina realmente tem instalado.
        # Agora expõe `ollama_available` explicitamente e mescla o
        # inventário real de disco na lista de nomes.
        def check_models():
            ollama_models = []
            ollama_available = False
            try:
                with urllib.request.urlopen("http://localhost:11434/api/tags", timeout=2) as r:
                    data = json.loads(r.read().decode())
                    ollama_models = [m["name"] for m in data.get("models", [])]
                    ollama_available = True
            except Exception:
                pass

            try:
                disk_models = [m["name"] for m in ModelScanner.scan_all()]
            except Exception as e:
                logger.warning(f"ModelsEngine: falha ao escanear modelos em disco: {e}")
                disk_models = []

            all_models = sorted(set(ollama_models) | set(disk_models))
            return all_models, ollama_available

        models, ollama_available = await loop.run_in_executor(None, check_models)

        rag_docs = 0
        rag_documents = []
        if self._knowledge_engine is not None:
            rag_docs = await loop.run_in_executor(None, self._knowledge_engine.get_document_count)
            # PHX-NEW: lista real de documentos RAG pra UI (substitui o hardcoded no Node)
            try:
                # PHX-FIX (auditoria completa, achado #3 do LEIA-ME): o atributo
                # real em KnowledgeEngine (phoenix_kernel/planner/knowledge_engine.py)
                # é público, `self.rag_backend` — nunca existiu `_rag_backend` com
                # underscore. getattr(..., '_rag_backend', None) sempre retornava o
                # default None, então rag_documents ficava [] pra sempre e o
                # /api/state nunca refletia os documentos reais do ChromaDB. É por
                # isso que o front (EngineMissionControl.tsx) nunca saía dos 4
                # documentos fake hardcoded no useState inicial — o guard
                # `ragDocs.length > 0` nunca via dado real pra sobrescrever.
                backend = getattr(self._knowledge_engine, 'rag_backend', None)
                if backend is not None and hasattr(backend, 'list_documents'):
                    rag_documents = await loop.run_in_executor(None, backend.list_documents, 100)
            except Exception as e:
                logger.warning(f"ModelsEngine: falha ao listar documentos RAG: {e}")
        else:
            logger.warning("ModelsEngine: knowledge_engine ainda não injetado — rag_docs retornando 0.")

        return {
            "models": models,
            "ollama_available": ollama_available,
            "rag_docs": rag_docs,
            "rag_documents": rag_documents,
        }