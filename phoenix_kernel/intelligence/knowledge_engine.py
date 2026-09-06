"""
knowledge_engine.py

O "cérebro de conhecimento" da Phoenix. Única fronteira entre o
ReasoningEngine e as quatro camadas de memória (intrínseca, procedural,
RAG, máquina).

Regra de ouro: o ReasoningEngine NUNCA sabe onde um fato mora. Ele só
chama `build_context(user_intent, machine_state)` e recebe de volta um
bloco de texto pronto para entrar no prompt do LLM.

Responsabilidades deste módulo:
    - carregar a camada intrínseca sempre;
    - rotear procedures/ e machine/ por triggers do manifest.json
      (keyword match direto — sem custo de embedding, previsível);
    - delegar busca semântica fina para o RAG vetorial (ChromaDB),
      quando disponível — nunca fazer keyword match ali, é papel do
      vetorial;
    - registrar de volta (`record_experience`) o resultado de uma
      missão executada em machine/*.json, para a camada de máquina
      crescer sozinha com o uso real da Phoenix.

Este módulo NÃO decide se uma mission deve ser aprovada, NÃO executa
comandos e NÃO fala com o Services Engine — isso é responsabilidade do
ResidentManager / MissionExecutor.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Protocol

try:
    # Quando intelligence/ é importado como pacote (ex: existe __init__.py e o
    # resto do projeto faz "from phoenix_kernel.intelligence import
    # knowledge_engine" ou "from .knowledge_engine import KnowledgeEngine").
    from .memory_loader import MemoryCard, MemoryLoader
except ImportError:
    # Quando o arquivo é rodado/importado isolado (ex: testes soltos de
    # dentro da própria pasta intelligence/, sem pacote pai no path).
    from memory_loader import MemoryCard, MemoryLoader


class RagBackend(Protocol):
    """Interface mínima que um backend vetorial (ex: ChromaDB) precisa
    implementar para ser plugado aqui. Mantém o KnowledgeEngine
    desacoplado da biblioteca de vetor específica.
    """

    def query(self, text: str, n_results: int = 3) -> list[str]:
        ...

    def upsert(self, cards: list[MemoryCard]) -> None:
        ...


class KnowledgeEngine:
    def __init__(
        self,
        knowledge_root: str | Path,
        rag_root: str | Path,
        rag_backend: RagBackend | None = None,
    ):
        self.loader = MemoryLoader(knowledge_root=knowledge_root, rag_root=rag_root)
        self.rag_backend = rag_backend
        self._machine_root = Path(knowledge_root) / "machine"

    # ------------------------------------------------------------------
    # 1. Memória intrínseca — sempre carregada, nunca filtrada
    # ------------------------------------------------------------------

    def load_intrinsic_memory(self) -> list[MemoryCard]:
        return self.loader.load_intrinsic()

    # ------------------------------------------------------------------
    # 2. Roteamento por triggers (procedures/ e machine/)
    #    Keyword match direto no manifest — não é busca semântica.
    # ------------------------------------------------------------------

    def get_execution_recipe(self, user_intent: str) -> list[MemoryCard]:
        """Retorna as procedures cujos triggers batem com a intenção
        detectada. Pode retornar mais de uma (ex: uma missão que
        envolve rodar um LLM e depois transcrever áudio).
        """
        manifest = self.loader.load_manifest()
        matches = []
        intent_lower = user_intent.lower()
        for entry in manifest["load_on_demand"]["procedures"]:
            if any(trigger in intent_lower for trigger in entry["triggers"]):
                matches.append(self.loader.load_procedure(entry["file"]))
        return matches

    def get_machine_context(self, user_intent: str) -> list[MemoryCard]:
        """Retorna os arquivos de experiência de máquina relevantes
        para a intenção — consultado antes de qualquer sugestão de
        configuração, para não repetir testes que já falharam.
        """
        manifest = self.loader.load_manifest()
        matches = []
        intent_lower = user_intent.lower()
        for entry in manifest["load_on_demand"]["machine"]:
            if any(trigger in intent_lower for trigger in entry["triggers"]):
                matches.append(self.loader.load_machine_file(entry["file"]))
        return matches

    # ------------------------------------------------------------------
    # 3. RAG — único ponto que fala com o vetorial (busca semântica fina:
    #    flag exata, erro específico, script). Nunca keyword match aqui.
    # ------------------------------------------------------------------

    def search_rag(self, query: str, n_results: int = 3) -> list[str]:
        if self.rag_backend is None:
            return []
        return self.rag_backend.query(query, n_results=n_results)

    def reingest_rag_sources(self) -> int:
        """Reprocessa rag/source_docs/ inteiro para dentro do vetorial.
        Rodar depois de editar/adicionar um source_doc manualmente.
        Retorna quantos cards foram enviados para upsert.
        """
        if self.rag_backend is None:
            raise RuntimeError("Nenhum rag_backend configurado — não há onde ingerir.")
        cards = self.loader.load_rag_source_docs()
        self.rag_backend.upsert(cards)
        return len(cards)

    # ------------------------------------------------------------------
    # 4. Construção de contexto para o Reasoning Engine
    # ------------------------------------------------------------------

    def build_context(self, user_intent: str, machine_state: dict[str, Any] | None = None) -> str:
        """Monta o bloco de contexto final para o prompt do LLM,
        seguindo a hierarquia de decisão da Phoenix:
        intrínseca (sempre) → procedural (por trigger) →
        máquina (por trigger) → RAG (busca semântica fina).
        """
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

    # ------------------------------------------------------------------
    # 5. Escrita de volta — a camada de máquina aprende com cada execução
    # ------------------------------------------------------------------

    def record_experience(self, machine_file: str, entry: dict[str, Any], list_key: str) -> None:
        """Acrescenta o resultado de uma missão executada a um arquivo
        de machine/*.json, sob a lista indicada por `list_key`
        (ex: "image_models", "text_models", "audio_models").

        Esta é a contrapartida de escrita do fluxo descrito em
        `intrinsic/memory_architecture.md`: "Resultado é registrado de
        volta em machine/*.json — a Phoenix aprende com cada execução."
        """
        path = self._machine_root / machine_file
        data = json.loads(path.read_text(encoding="utf-8"))
        data.setdefault(list_key, []).append(entry)
        path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
