"""
knowledge_engine.py

O "cérebro de conhecimento" da Phoenix. Única fronteira entre o
ReasoningEngine e as quatro camadas de memória (intrínseca, procedural,
RAG, máquina).
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any, Protocol

logger = logging.getLogger(__name__)

try:
    # PHX-FIX: memory_loader reside em intelligence, não em planner.
    from phoenix_kernel.intelligence.memory_loader import MemoryCard, MemoryLoader
except ImportError:
    # Fallback para execução direta de script
    from intelligence.memory_loader import MemoryCard, MemoryLoader


class RagBackend(Protocol):
    def query(self, text: str, n_results: int = 3) -> list[str]:
        ...

    def upsert(self, cards: list[MemoryCard]) -> None:
        ...


class KnowledgeEngine:
    def __init__(
        self,
        event_bus=None,
        kernel=None,
        rag_backend: RagBackend | None = None,
    ):
        """PHX-FIX: planner/engine.py chama KnowledgeEngine(event_bus, kernel).
        Resolvemos os caminhos de memória internamente para não quebrar o contrato."""
        knowledge_root = "phoenix_kernel/knowledge"
        rag_root = "phoenix_kernel/rag/source_docs"
        
        self.loader = MemoryLoader(knowledge_root=knowledge_root, rag_root=rag_root)
        self.rag_backend = rag_backend
        self._machine_root = Path(knowledge_root) / "machine"

    async def initialize(self) -> None:
        """Método seguro para satisfazer o contrato do PlannerEngine."""
        pass

    def get_document_count(self) -> int:
        """PHX-FIX: Adicionado para satisfazer a chamada em models/engine.py.
        Retorna a contagem de documentos no RAG (ou 0 se não houver backend).

        PHX-FIX (varredura 2026-08-21 rodada 2, achado #5): o `except:`
        genérico escondia qualquer falha real (índice Chroma corrompido,
        etc.) atrás do mesmo 0 que uma coleção genuinamente vazia
        produziria - quem consome isso não tinha como distinguir "RAG
        vazio" de "RAG quebrado". Agora loga a causa real antes de cair
        pro 0 (o valor de retorno continua 0 porque a assinatura é `int`,
        sem espaço pra um terceiro estado - mas ao menos a causa fica
        registrada em vez de desaparecer)."""
        if self.rag_backend is None:
            return 0
        try:
            if hasattr(self.rag_backend, "count"):
                return self.rag_backend.count()
            if hasattr(self.rag_backend, "_collection") and hasattr(self.rag_backend._collection, "count"):
                return self.rag_backend._collection.count()
        except Exception as e:
            logger.warning(f"KnowledgeEngine.get_document_count: falha ao contar documentos RAG: {e}")
        return 0

    def load_intrinsic_memory(self) -> list[MemoryCard]:
        return self.loader.load_intrinsic()

    def get_execution_recipe(self, user_intent: str) -> list[MemoryCard]:
        manifest = self.loader.load_manifest()
        matches = []
        intent_lower = user_intent.lower()
        for entry in manifest["load_on_demand"]["procedures"]:
            if any(trigger in intent_lower for trigger in entry["triggers"]):
                matches.append(self.loader.load_procedure(entry["file"]))
        return matches

    def get_machine_context(self, user_intent: str) -> list[MemoryCard]:
        manifest = self.loader.load_manifest()
        matches = []
        intent_lower = user_intent.lower()
        for entry in manifest["load_on_demand"]["machine"]:
            if any(trigger in intent_lower for trigger in entry["triggers"]):
                matches.append(self.loader.load_machine_file(entry["file"]))
        return matches

    def search_rag(self, query: str, n_results: int = 3) -> list[str]:
        if self.rag_backend is None:
            return []
        return self.rag_backend.query(query, n_results=n_results)

    def query_knowledge(self, query: str, n_results: int = 3) -> list[str]:
        """PHX-FIX: Alias esperado pelo ReasoningEngine para evitar erro no Terminal."""
        return self.search_rag(query, n_results)

    def reingest_rag_sources(self) -> int:
        if self.rag_backend is None:
            raise RuntimeError("Nenhum rag_backend configurado — não há onde ingerir.")
        cards = self.loader.load_rag_source_docs()
        self.rag_backend.upsert(cards)
        return len(cards)

    def build_context(self, user_intent: str, machine_state: dict[str, Any] | None = None) -> str:
        sections: list[str] = []

        intrinsic = self.load_intrinsic_memory()
        sections.append(self._render_section("IDENTIDADE E REGRAS (sempre válidas)", intrinsic))

        recipes = self.get_execution_recipe(user_intent)
        if recipes:
            sections.append(self._render_section("COMO FAZER (procedures aplicáveis)", recipes))

        machine = self.get_machine_context(user_intent)
        if machine:
            sections.append(self._render_section("O QUE JÁ SABEMOS SOBRE ESTA MÁQUINA", machine))

        rag_hits = self.search_rag(user_intent)
        if rag_hits:
            rag_block = "\n\n".join(f"- {hit}" for hit in rag_hits)
            sections.append(f"## DETALHES TÉCNICOS ESPECÍFICOS (RAG)\n\n{rag_block}")

        if machine_state:
            sections.append(
                "## ESTADO ATUAL DA MÁQUINA (runtime)\n\n"
                + json.dumps(machine_state, ensure_ascii=False, indent=2)
            )

        return "\n\n".join(sections)

    @staticmethod
    def _render_section(header: str, cards: list[MemoryCard]) -> str:
        body = "\n\n".join(f"### {c.title}\n{c.content}" for c in cards)
        return f"## {header}\n\n{body}"

    def record_experience(self, machine_file: str, entry: dict[str, Any], list_key: str) -> None:
        path = self._machine_root / machine_file
        data = json.loads(path.read_text(encoding="utf-8"))
        data.setdefault(list_key, []).append(entry)
        path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")