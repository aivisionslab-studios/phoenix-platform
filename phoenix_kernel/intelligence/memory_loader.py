"""
memory_loader.py

Responsável ÚNICA E EXCLUSIVAMENTE por ler o disco e transformar os
arquivos de `knowledge/` e `rag/source_docs/` em objetos MemoryCard.

Este módulo NÃO decide o que é relevante, NÃO monta contexto para o
LLM e NÃO fala com o ChromaDB diretamente — isso é responsabilidade
do KnowledgeEngine. O loader só sabe ler e parsear.

Layout esperado (relativo a `knowledge_root`):

    knowledge/
        manifest.json
        intrinsic/*.md
        procedures/*.md
        machine/*.json
    rag/
        source_docs/*.json | *.py | *.md
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable, Literal

MemoryLayer = Literal["intrinsic", "procedural", "rag", "machine"]

_FRONTMATTER_RE = re.compile(r"^---\n(.*?)\n---\n(.*)$", re.DOTALL)


@dataclass
class MemoryCard:
    """Unidade de conhecimento comum às quatro camadas.

    Toda camada — intrínseca, procedural, RAG ou de máquina — é
    normalizada para este formato, de modo que o KnowledgeEngine possa
    filtrar/rankear/montar contexto com uma única interface, sem saber
    de onde cada card veio.
    """

    layer: MemoryLayer
    path: Path
    title: str
    content: str
    tags: list[str] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)

    @property
    def source_id(self) -> str:
        """Caminho relativo estável, usado como referência em logs/missions."""
        return str(self.path)

    def matches(self, query_terms: Iterable[str]) -> bool:
        """Match simples por substring nas tags e no título.

        Usado pelo roteamento por `triggers` do manifest.json — não é
        busca semântica (isso é papel do ChromaDB / camada RAG).
        """
        haystack = " ".join([self.title.lower(), *[t.lower() for t in self.tags]])
        return any(term.lower() in haystack for term in query_terms)


class MemoryLoader:
    """Lê `knowledge/` e `rag/source_docs/` do disco e produz MemoryCards."""

    def __init__(self, knowledge_root: str | Path, rag_root: str | Path):
        self.knowledge_root = Path(knowledge_root)
        self.rag_root = Path(rag_root)
        self._manifest: dict[str, Any] | None = None

    # ------------------------------------------------------------------
    # Manifest (roteamento de triggers)
    # ------------------------------------------------------------------

    def load_manifest(self) -> dict[str, Any]:
        if self._manifest is None:
            manifest_path = self.knowledge_root / "manifest.json"
            self._manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        return self._manifest

    # ------------------------------------------------------------------
    # Camada intrínseca — sempre carregada
    # ------------------------------------------------------------------

    def load_intrinsic(self) -> list[MemoryCard]:
        manifest = self.load_manifest()
        cards = []
        for rel_path in manifest["load_always"]:
            cards.append(self._parse_markdown(self.knowledge_root / rel_path, layer="intrinsic"))
        return cards

    # ------------------------------------------------------------------
    # Camada procedural — sob demanda
    # ------------------------------------------------------------------

    def load_procedure(self, rel_path: str) -> MemoryCard:
        return self._parse_markdown(self.knowledge_root / rel_path, layer="procedural")

    def load_all_procedures(self) -> list[MemoryCard]:
        manifest = self.load_manifest()
        return [
            self.load_procedure(entry["file"])
            for entry in manifest["load_on_demand"]["procedures"]
        ]

    # ------------------------------------------------------------------
    # Camada de máquina — sob demanda
    # ------------------------------------------------------------------

    def load_machine_file(self, rel_path: str) -> MemoryCard:
        return self._parse_json(self.knowledge_root / rel_path, layer="machine")

    def load_all_machine(self) -> list[MemoryCard]:
        manifest = self.load_manifest()
        return [
            self.load_machine_file(entry["file"])
            for entry in manifest["load_on_demand"]["machine"]
        ]

    # ------------------------------------------------------------------
    # Camada RAG — os arquivos crus, ANTES de ingerir no ChromaDB.
    # O KnowledgeEngine usa isto só para (re)ingestão, não para leitura
    # direta em tempo de resposta — busca semântica é feita no vetorial.
    # ------------------------------------------------------------------

    def load_rag_source_docs(self) -> list[MemoryCard]:
        cards = []
        for path in sorted(self.rag_root.glob("*")):
            if path.suffix == ".json":
                cards.append(self._parse_json(path, layer="rag"))
            elif path.suffix in (".md", ".py"):
                cards.append(self._parse_plain(path, layer="rag"))
        return cards

    # ------------------------------------------------------------------
    # Parsers internos
    # ------------------------------------------------------------------

    def _parse_markdown(self, path: Path, layer: MemoryLayer) -> MemoryCard:
        raw = path.read_text(encoding="utf-8")
        match = _FRONTMATTER_RE.match(raw)
        metadata: dict[str, Any] = {}
        body = raw
        if match:
            metadata = self._parse_simple_yaml(match.group(1))
            body = match.group(2).strip()

        title = metadata.get("procedure_id") or path.stem
        tags = list(metadata.get("triggers", []))
        return MemoryCard(layer=layer, path=path, title=title, content=body, tags=tags, metadata=metadata)

    def _parse_json(self, path: Path, layer: MemoryLayer) -> MemoryCard:
        data = json.loads(path.read_text(encoding="utf-8"))
        title = data.get("topic") or data.get("description") or path.stem
        tags: list[str] = []
        # arquivos de máquina/RAG não têm 'triggers' embutido salvo quando
        # vieram do manifest — tags aqui servem só como fallback de busca.
        if isinstance(data.get("entries"), list):
            tags = [e.get("component", "") for e in data["entries"] if isinstance(e, dict)]
        return MemoryCard(
            layer=layer,
            path=path,
            title=title,
            content=json.dumps(data, ensure_ascii=False, indent=2),
            tags=[t for t in tags if t],
            metadata=data,
        )

    def _parse_plain(self, path: Path, layer: MemoryLayer) -> MemoryCard:
        content = path.read_text(encoding="utf-8")
        return MemoryCard(layer=layer, path=path, title=path.stem, content=content, tags=[], metadata={})

    @staticmethod
    def _parse_simple_yaml(block: str) -> dict[str, Any]:
        """Parser mínimo para o front-matter usado nestes arquivos.

        Suporta apenas `chave: valor` e `chave: ["a", "b"]` — suficiente
        para os arquivos desta base. Se o front-matter crescer em
        complexidade, trocar por PyYAML.
        """
        result: dict[str, Any] = {}
        for line in block.splitlines():
            if ":" not in line:
                continue
            key, _, value = line.partition(":")
            key, value = key.strip(), value.strip()
            if value.startswith("[") and value.endswith("]"):
                items = [v.strip().strip('"').strip("'") for v in value[1:-1].split(",") if v.strip()]
                result[key] = items
            else:
                result[key] = value.strip('"').strip("'")
        return result
