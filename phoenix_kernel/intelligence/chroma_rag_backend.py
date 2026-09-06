"""
chroma_rag_backend.py

PHX-FIX (auditoria 2026-08-04): implementação real do `RagBackend` (Protocol
definido em `phoenix_kernel/planner/knowledge_engine.py` e duplicado em
`phoenix_kernel/intelligence/knowledge_engine.py`). Até agora nenhuma classe
concreta existia — os dois `KnowledgeEngine(...)` eram sempre instanciados
sem `rag_backend`, então `search_rag()`/`query_knowledge()` sempre retornavam
`[]`, mesmo com `data/chroma_db` já tendo uma coleção real com 226 documentos
(`aivisions_knowledge_base`, resultado da curadoria de ~91 entradas de
`knowledge_base.json`, expandida em chunks). Esta classe conecta nessa
coleção existente em vez de criar uma nova vazia.

Requer o pacote `chromadb` (já instalado pelo instalador em
install/common.ps1: `pip install ... chromadb ...`).

NOTA IMPORTANTE SOBRE OFFLINE: por padrão o ChromaDB usa sua
`DefaultEmbeddingFunction` (all-MiniLM-L6-v2 em ONNX), que baixa o modelo
(~90MB) de `chroma-onnx-models.s3.amazonaws.com` na PRIMEIRA vez que for
usada, e depois fica em cache local (`~/.cache/chroma/onnx_models/`). Isso
é uma dependência de rede pontual (não recorrente) que vale notar num
projeto pensado para inferência local/offline - se quiser eliminá-la
completamente, dá pra trocar por um embedding function que rode via
llama.cpp localmente, mas isso é uma mudança maior e fica fora do escopo
deste conserto (ver observação no relatório de auditoria).
"""

from __future__ import annotations

import logging
import re
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from phoenix_kernel.intelligence.memory_loader import MemoryCard

logger = logging.getLogger(__name__)

DEFAULT_COLLECTION_NAME = "aivisions_knowledge_base"

# PHX-FIX (auditoria completa, achado #3 do LEIA-ME): 1536 estava hardcoded
# em vários lugares (list_documents() abaixo, server.ts) como se fosse o
# número de dimensões do vetor de embedding — mas 1536 é a dimensão do
# text-embedding-ada-002 da OpenAI, nunca usado aqui. A embedding function
# de fato em uso é a DefaultEmbeddingFunction do Chroma (all-MiniLM-L6-v2,
# ONNX, ver docstring do módulo), que gera vetores de 384 dimensões. Usar
# a constante em vez de literais espalhados evita a mesma inconsistência
# reaparecer se a embedding function mudar no futuro.
CHROMA_DEFAULT_EMBEDDING_DIMENSIONS = 384

# PHX-RAG v57: chunks conservadores para all-MiniLM-L6-v2 (~256 tokens).
# 700 caracteres evita, na prática, jogar páginas inteiras num embedding curto.
RAG_CHUNK_TARGET_CHARS = 700
RAG_CHUNK_OVERLAP_CHARS = 100

# PHX-FIX (31/08): TESTS/test_rag_chunking_and_grouping.py (parte do
# próprio trabalho v57 documentado acima) importa esta lógica como função
# de módulo `split_into_chunks()` + as constantes com o prefixo antigo
# "CHROMA_" - um rename parcial (RAG_ substituindo CHROMA_ nas constantes
# de chunking, mantendo CHROMA_DEFAULT_EMBEDDING_DIMENSIONS como estava)
# deixou o teste importando nomes que nunca existiram neste módulo
# (`ImportError` na coleta, suíte inteira travava). A lógica de chunking em
# si sempre funcionou (usada de verdade via `self._chunk_text` -> ver
# `_chunk_text` abaixo, que virou um staticmethod fino sobre esta função,
# sem duplicar a lógica) - aqui só uma função de módulo pura, sem
# dependência de chromadb/instância da classe, do jeito que o teste (e o
# próprio comentário "função pura, sem dependência de chromadb" dele) já
# esperava.
CHROMA_CHUNK_MAX_CHARS = RAG_CHUNK_TARGET_CHARS
CHROMA_CHUNK_OVERLAP_CHARS = RAG_CHUNK_OVERLAP_CHARS


def split_into_chunks(content: str, target_chars: int = RAG_CHUNK_TARGET_CHARS,
                       overlap_chars: int = RAG_CHUNK_OVERLAP_CHARS) -> list[str]:
    """Chunking determinístico, sem dependência externa de tokenizer nem de
    chromadb - função pura de módulo (ver comentário acima)."""
    text = (content or "").replace("\r\n", "\n").strip()
    if not text:
        return []
    if len(text) <= target_chars:
        return [text]

    chunks: list[str] = []
    pos = 0
    n = len(text)
    while pos < n:
        hard_end = min(n, pos + target_chars)
        end = hard_end
        if hard_end < n:
            window = text[pos:hard_end]
            # Prefere fronteira semântica próxima do final.
            candidates = [
                window.rfind("\n\n"),
                window.rfind("\n"),
                window.rfind(". "),
                window.rfind("; "),
                window.rfind(", "),
                window.rfind(" "),
            ]
            cut = max(candidates)
            if cut >= int(target_chars * 0.55):
                end = pos + cut + (2 if window[cut:cut+2] in (". ", "; ", ", ") else 0)

        chunk = text[pos:end].strip()
        if chunk:
            chunks.append(chunk)
        if end >= n:
            break
        next_pos = max(pos + 1, end - overlap_chars)
        pos = next_pos
    return chunks


class ChromaRagBackend:
    """Implementação de `RagBackend` sobre um ChromaDB persistente local.

    Satisfaz o Protocol definido em ambas as cópias de `KnowledgeEngine`:
        def query(self, text: str, n_results: int = 3) -> list[str]: ...
        def upsert(self, cards: list[MemoryCard]) -> None: ...
    """

    def __init__(
        self,
        persist_dir: str | Path = "data/chroma_db",
        collection_name: str = DEFAULT_COLLECTION_NAME,
        embedding_function=None,
    ) -> None:
        self._persist_dir = Path(persist_dir)
        self._collection_name = collection_name
        self._embedding_function = embedding_function
        self._client = None
        self._collection = None
        self._unavailable_reason: str | None = None

        from phoenix_kernel.security.rag_integrity import RagIntegrityRegistry
        from phoenix_kernel.security.rag_usage_ledger import RagUsageLedger
        from phoenix_kernel.security.rag_integrity_manifest import RagIntegrityManifest
        from phoenix_kernel.security.rag_consensus import RagConsensus

        self._user_registry = RagIntegrityRegistry()
        self._user_ledger = RagUsageLedger()
        self._user_manifest = RagIntegrityManifest()
        self._user_consensus = RagConsensus(
            registry=self._user_registry,
            ledger=self._user_ledger,
            manifest=self._user_manifest,
        )

        self._connect()
        if self.available:
            self._bootstrap_user_integrity_once()

    def _connect(self) -> None:
        try:
            import chromadb  # import tardio: não derruba o boot se faltar o pacote
        except ImportError:
            self._unavailable_reason = (
                "Pacote 'chromadb' não instalado. Rode: pip install chromadb"
            )
            logger.warning("ChromaRagBackend: %s", self._unavailable_reason)
            return

        try:
            self._persist_dir.mkdir(parents=True, exist_ok=True)
            self._client = chromadb.PersistentClient(path=str(self._persist_dir))
            # get_or_create: conecta na coleção já existente (226 docs) se
            # houver, ou cria uma nova vazia na primeira execução limpa.
            kwargs = {"name": self._collection_name, "metadata": {"hnsw:space": "cosine"}}
            if self._embedding_function is not None:
                kwargs["embedding_function"] = self._embedding_function
            self._collection = self._client.get_or_create_collection(**kwargs)
            doc_count = self._collection.count()
            logger.info(
                "ChromaRagBackend: conectado a '%s' em %s (%d documentos).",
                self._collection_name, self._persist_dir, doc_count,
            )

            # PHX-FIX (achado real em produção): a coleção pode já ter sido
            # criada por outro pipeline de ingestão usando uma embedding
            # function diferente (ex: nomic-embed-text/bge-base, 768 dims),
            # enquanto get_or_create_collection() aqui, sem embedding_function
            # explícita, usa o DefaultEmbeddingFunction do Chroma (all-MiniLM
            # -L6-v2, 384 dims). Nesse caso TODA chamada a .query() explode
            # com "InvalidArgumentError: dimension of 768, got 384" - e como
            # o método query() abaixo tem um try/except amplo, isso virava
            # um crash-loop silencioso (uma inferência ONNX inteira + um
            # traceback completo a cada chamada, sem nunca dizer o motivo
            # real). Faz um probe de verdade AGORA, uma única vez, pra falhar
            # cedo com uma mensagem clara em vez de repetir o erro sempre.
            if doc_count > 0:
                try:
                    self._collection.query(query_texts=["probe de dimensão de embedding"], n_results=1)
                except Exception as probe_exc:
                    dim_match = re.search(r"dimension of (\d+), got (\d+)", str(probe_exc))
                    if dim_match:
                        self._unavailable_reason = (
                            f"Coleção '{self._collection_name}' foi criada com embeddings de "
                            f"{dim_match.group(1)} dimensões, mas a embedding function atual gera "
                            f"{dim_match.group(2)} dimensões (provavelmente um outro script de "
                            f"ingestão usou um modelo de embedding diferente). Os "
                            f"{doc_count} documentos existentes ficam inacessíveis até você: "
                            f"(1) reconectar com a embedding_function original que gerou os "
                            f"{dim_match.group(1)}-dim vectors, ou (2) apagar '{self._persist_dir}' "
                            f"e reingerir do zero com a embedding function atual."
                        )
                    else:
                        self._unavailable_reason = f"Probe de conexão falhou: {probe_exc}"
                    logger.error("ChromaRagBackend: %s", self._unavailable_reason)
                    self._collection = None
        except Exception as e:
            self._unavailable_reason = f"Falha ao conectar no ChromaDB em {self._persist_dir}: {e}"
            logger.error("ChromaRagBackend: %s", self._unavailable_reason, exc_info=True)
            self._client = None
            self._collection = None

    @property
    def available(self) -> bool:
        return self._collection is not None

    def count(self) -> int:
        if not self.available:
            return 0
        try:
            return self._collection.count()
        except Exception:
            logger.warning("ChromaRagBackend: falha ao contar documentos.", exc_info=True)
            return 0

    @staticmethod
    def _chunk_text(content: str, target_chars: int = RAG_CHUNK_TARGET_CHARS,
                    overlap_chars: int = RAG_CHUNK_OVERLAP_CHARS) -> list[str]:
        """Chunking determinístico, sem dependência externa de tokenizer.

        PHX-FIX (31/08): a lógica em si foi movida pra `split_into_chunks()`
        (função de módulo, ver comentário completo lá) - este staticmethod
        vira um wrapper fino, mantido só pra não quebrar o único caller
        interno (`self._chunk_text(content)` mais abaixo)."""
        return split_into_chunks(content, target_chars=target_chars, overlap_chars=overlap_chars)

    def _raw_manual_documents(self) -> list[dict]:
        """Lê documentos manuais detectados no Chroma sem aplicar licença."""
        if not self.available:
            return []
        try:
            result = self._collection.get(include=["metadatas"])
            ids = result.get("ids", []) or []
            metadatas = result.get("metadatas") or [{}] * len(ids)

            grouped: dict[str, dict] = {}
            for i, item_id in enumerate(ids):
                meta = metadatas[i] if i < len(metadatas) and metadatas[i] else {}
                parent_id = str(meta.get("parent_id") or item_id)
                is_manual = (
                    str(meta.get("layer") or "").lower() == "manual"
                    or parent_id.startswith("manual::")
                )
                if not is_manual:
                    continue
                if parent_id not in grouped:
                    grouped[parent_id] = {
                        "id": parent_id,
                        "title": meta.get("source", meta.get("title", parent_id)),
                        "sourceType": meta.get("source_type", "DOC"),
                        "dateAdded": meta.get("date_added", ""),
                        "sizeKb": meta.get("size_kb", 0),
                        "chunks": int(meta.get("chunk_count", meta.get("chunks", 1)) or 1),
                        "status": "INDEXED",
                        "vectorDimensions": meta.get("vector_dimensions", CHROMA_DEFAULT_EMBEDDING_DIMENSIONS),
                    }
                else:
                    grouped[parent_id]["chunks"] = max(
                        grouped[parent_id]["chunks"],
                        int(meta.get("chunk_count", meta.get("chunks", 1)) or 1),
                    )
            return list(grouped.values())
        except Exception as e:
            logger.warning("ChromaRagBackend._raw_manual_documents falhou: %s", e)
            return []

    def _bootstrap_user_integrity_once(self) -> None:
        """Migração única de estado legado para registry + ledger + manifest."""
        reg = self._user_registry.load()
        ledger_exists = self._user_ledger.ledger_path.exists()
        manifest_exists = self._user_manifest.manifest_path.exists()

        # Estado parcial NÃO é reconstruído automaticamente.
        if reg.initialized or ledger_exists or manifest_exists:
            state = self._user_consensus.validate()
            if not state.valid:
                logger.error(
                    "ChromaRagBackend: consenso RAG inválido no boot (%s). "
                    "Knowledge Repository do usuário ficará fail-closed.",
                    state.reason,
                )
            return

        from phoenix_kernel.licensing.plans import get_rag_limits
        limits = get_rag_limits()

        docs = sorted(
            self._raw_manual_documents(),
            key=lambda d: (str(d.get("dateAdded") or ""), str(d.get("id") or "")),
        )

        max_docs = limits.get("max_documents")
        if max_docs is not None:
            docs = docs[:max_docs]

        seed: dict[str, dict] = {}
        for d in docs:
            seed[str(d["id"])] = {
                "title": str(d.get("title") or ""),
                "source_type": str(d.get("sourceType") or "DOC"),
                "date_added": str(d.get("dateAdded") or ""),
            }

        try:
            self._user_registry.initialize(seed)
            self._user_ledger.initialize(seed)
            self._user_consensus.checkpoint()
            state = self._user_consensus.validate()
            if not state.valid:
                raise RuntimeError(state.reason)
            logger.info(
                "ChromaRagBackend: consenso RAG inicializado com %d documento(s).",
                len(seed),
            )
        except Exception as e:
            logger.error("ChromaRagBackend: falha ao inicializar consenso RAG: %s", e)

    def _authorized_user_ids(self) -> set[str]:
        """Allowlist final: consenso 4/4 + reaplicação do limite do plano."""
        state = self._user_consensus.validate()
        if not state.valid:
            logger.error(
                "ChromaRagBackend: user RAG bloqueado por consenso (%s).",
                state.reason,
            )
            return set()

        ids = sorted(state.authorized_ids)
        from phoenix_kernel.licensing.plans import get_rag_limits
        limits = get_rag_limits()
        max_docs = limits.get("max_documents")
        if max_docs is not None:
            ids = ids[:max_docs]
        return set(ids)

    def list_documents(self, limit: int = 100) -> list[dict]:
        """Lista SOMENTE documentos do usuário autorizados pelo registry.

        A UI do Knowledge Repository nunca usa documentos inseridos diretamente
        no ChromaDB sem passar pelo fluxo autorizado da Phoenix.
        """
        authorized = self._authorized_user_ids()
        if not authorized:
            return []
        raw = self._raw_manual_documents()
        return [d for d in raw if str(d.get("id")) in authorized][:limit]

    def logical_document_count(self) -> int:
        """Conta vagas comerciais autorizadas E fisicamente presentes no Chroma.

        PHX-FIX (2026-09-06, achado real do usuário, com print de tela: o
        painel mostrava "INDEXED DOCUMENTS (3)" mas o upload seguinte foi
        rejeitado com "Limite de documentos do plano atingido: 10/10" -
        uma contradição visível na própria tela). Antes, esta função
        devolvia `len(self._authorized_user_ids())` puro - só o que o
        registry/ledger/manifest (a allowlist de autorização comercial)
        diz que está autorizado, SEM checar se esses IDs ainda
        correspondem a algo fisicamente presente no Chroma. `list_documents()`
        (a função que alimenta a lista visível na UI) já faz essa
        interseção com `_raw_manual_documents()` - só esta função ficou
        de fora dessa mesma checagem, apesar de ser a que decide se um
        novo upload é aceito ou rejeitado. Se um documento é removido do
        Chroma sem que o registry seja limpo em conjunto (registro
        corrompido antigo, falha parcial num delete de uma versão anterior,
        adulteração externa), o registry fica com IDs "fantasma" -
        autorizados no papel, inexistentes na prática - e a contagem usada
        pra aplicar o limite do plano ficava inflada em relação ao que o
        usuário via e podia gerenciar na tela. Agora as duas fontes (lista
        visível e contagem que trava o limite) usam exatamente a mesma
        base - nunca mais podem discordar."""
        authorized = self._authorized_user_ids()
        if not authorized:
            return 0
        raw = self._raw_manual_documents()
        raw_ids = {str(d.get("id")) for d in raw}
        return len(authorized & raw_ids)

    def _extracted_characters_for(self, parent_id: str) -> int:
        """Caracteres extraídos armazenados pra um parent_id específico -
        0 se o documento não existe no registry. Usado por
        `validate_product_limits()` pra descontar a contribuição ANTIGA
        de um documento sendo reindexado, antes de somar a nova (nunca
        conta a mesma vaga duas vezes)."""
        reg_state = self._user_registry.load()
        if not reg_state.valid:
            return 0
        meta = reg_state.documents.get(str(parent_id)) or {}
        return int(meta.get("extracted_characters") or 0)

    def total_extracted_characters(self) -> int:
        """Soma de caracteres extraídos de TODOS os documentos atualmente
        autorizados - a fonte única de verdade pro orçamento agregado do
        plano (2026-09-06, correção conceitual: o limite de caracteres é
        um teto do REPOSITÓRIO inteiro, não de cada arquivo isolado).

        Recalculada do zero a cada chamada (nunca um contador incremental
        mantido à parte) - com no máximo ~10 documentos autorizados no
        Free, o custo é irrelevante, e uma soma sempre recalculada nunca
        pode dessincronizar da realidade (ao contrário de um acumulador
        que precisaria de lógica de +/- em cada operação e correria risco
        de drift). Mesma interseção com o que existe fisicamente no
        Chroma usada em `logical_document_count()` - um documento
        "fantasma" (autorizado no registry, sem chunks reais) não pode
        inflar o orçamento usado, do mesmo jeito que não pode inflar a
        contagem de vagas.

        Soma o texto extraído ORIGINAL de cada documento (guardado em
        `extracted_characters` no momento da indexação) - nunca a soma
        dos chunks armazenados no Chroma, que pode ter overlap e contar
        texto repetido várias vezes."""
        authorized = self._authorized_user_ids()
        if not authorized:
            return 0
        raw = self._raw_manual_documents()
        raw_ids = {str(d.get("id")) for d in raw}
        valid_ids = authorized & raw_ids
        if not valid_ids:
            return 0
        reg_state = self._user_registry.load()
        if not reg_state.valid:
            return 0
        return sum(
            int(reg_state.documents.get(doc_id, {}).get("extracted_characters") or 0)
            for doc_id in valid_ids
        )

    def user_repository_security_status(self) -> dict:
        raw = self._raw_manual_documents()
        raw_ids = {str(d.get("id")) for d in raw}
        consensus = self._user_consensus.validate()
        authorized = self._authorized_user_ids() if consensus.valid else set()

        return {
            "integrity_valid": consensus.valid,
            "reason": consensus.reason,
            "checks": consensus.checks,
            "authorized_documents": len(authorized),
            "detected_manual_documents": len(raw_ids),
            "locked_or_unregistered_documents": len(raw_ids - authorized),
            "details": consensus.details,
        }

    def query_with_scores(self, text: str, n_results: int = 5) -> list[dict]:
        """Busca geral/legada do RAG interno da Phoenix.

        NÃO é usada pelo Knowledge Repository do usuário; preserva Planner/RAG
        interno, inclusive documentos técnicos não sujeitos ao plano comercial.
        """
        if not self.available or not text or not text.strip():
            return []
        try:
            count = self._collection.count()
            if count <= 0:
                return []
            result = self._collection.query(
                query_texts=[text],
                n_results=min(max(1, n_results), count),
                include=["documents", "metadatas", "distances"],
            )
        except Exception:
            logger.error("ChromaRagBackend.query_with_scores: falha ao consultar ChromaDB.", exc_info=True)
            return []

        docs = (result.get("documents") or [[]])[0]
        metas = (result.get("metadatas") or [[]])[0]
        dists = (result.get("distances") or [[]])[0]
        ids = (result.get("ids") or [[]])[0]
        hits = []
        for i, doc in enumerate(docs):
            meta = metas[i] if i < len(metas) and metas[i] else {}
            dist = float(dists[i]) if i < len(dists) and dists[i] is not None else 1.0
            hits.append({
                "id": ids[i] if i < len(ids) else "",
                "parent_id": meta.get("parent_id", ids[i] if i < len(ids) else ""),
                "title": meta.get("source", meta.get("title", "")),
                "source_type": meta.get("source_type", "DOC"),
                "chunk_index": int(meta.get("chunk_index", 0) or 0),
                "chunk_count": int(meta.get("chunk_count", meta.get("chunks", 1)) or 1),
                "text": doc,
                "distance": dist,
                "score": max(0.0, min(1.0, 1.0 - dist)),
            })
        return hits

    def query_user_with_scores(self, text: str, n_results: int = 5) -> list[dict]:
        """Consulta APENAS chunks pertencentes a documentos autorizados do usuário."""
        if not self.available or not text or not text.strip():
            return []

        authorized = sorted(self._authorized_user_ids())
        if not authorized:
            return []

        # Chroma $in impede que um 11º documento injetado diretamente dispute
        # ranking semântico com os documentos autorizados.
        try:
            count = self._collection.count()
            if count <= 0:
                return []
            result = self._collection.query(
                query_texts=[text],
                n_results=min(max(1, n_results), count),
                where={"parent_id": {"$in": authorized}},
                include=["documents", "metadatas", "distances"],
            )
        except Exception:
            logger.error(
                "ChromaRagBackend.query_user_with_scores: falha na consulta autorizada.",
                exc_info=True,
            )
            return []

        docs = (result.get("documents") or [[]])[0]
        metas = (result.get("metadatas") or [[]])[0]
        dists = (result.get("distances") or [[]])[0]
        ids = (result.get("ids") or [[]])[0]

        hits = []
        for i, doc in enumerate(docs):
            meta = metas[i] if i < len(metas) and metas[i] else {}
            parent_id = str(meta.get("parent_id") or "")
            if parent_id not in authorized:
                continue

            ledger_state = self._user_ledger.load()
            active = ledger_state.active_documents.get(parent_id) if ledger_state.valid else None
            if not active:
                continue
            if int(meta.get("ledger_generation") or -1) != int(active.get("generation") or -2):
                continue
            if str(meta.get("ledger_event_hash") or "") != str(active.get("event_hash") or ""):
                continue
            if str(meta.get("registry_parent_id") or "") != parent_id:
                continue

            dist = float(dists[i]) if i < len(dists) and dists[i] is not None else 1.0
            hits.append({
                "id": ids[i] if i < len(ids) else "",
                "parent_id": parent_id,
                "title": meta.get("source", meta.get("title", "")),
                "source_type": meta.get("source_type", "DOC"),
                "chunk_index": int(meta.get("chunk_index", 0) or 0),
                "chunk_count": int(meta.get("chunk_count", meta.get("chunks", 1)) or 1),
                "text": doc,
                "distance": dist,
                "score": max(0.0, min(1.0, 1.0 - dist)),
            })
        return hits

    def query(self, text: str, n_results: int = 3) -> list[str]:
        """Contrato legado: RAG interno da Phoenix, não o repositório comercial."""
        return [hit["text"] for hit in self.query_with_scores(text, n_results=n_results)]

    def upsert(self, cards: "list[MemoryCard]") -> None:
        """Insere/atualiza os MemoryCards no ChromaDB. Usa `source_id`
        (caminho relativo estável) como id do documento, garantindo que
        reingestões subsequentes atualizem em vez de duplicar."""
        if not self.available:
            raise RuntimeError(
                f"ChromaRagBackend indisponível para upsert: {self._unavailable_reason or 'motivo desconhecido'}"
            )
        if not cards:
            return

        import datetime

        ids: list[str] = []
        documents: list[str] = []
        metadatas: list[dict] = []
        for card in cards:
            ids.append(card.source_id)
            documents.append(card.content)
            # ChromaDB não aceita valores None/list/dict em metadata - só
            # str/int/float/bool. Achata tags em string e descarta o resto
            # do metadata livre (fica só no MemoryCard, não precisa ir pro
            # índice vetorial).
            # PHX-FIX (auditoria completa, achado #3 do LEIA-ME): antes só
            # gravava layer/title/tags - list_documents() lia size_kb/chunks/
            # vector_dimensions/source_type/date_added, que nunca eram
            # escritos aqui, então TODO documento (inclusive os 226 reais já
            # indexados antes deste fix) voltava com os defaults do
            # list_documents() em vez do dado real. Grava os campos de
            # verdade agora, calculados a partir do próprio card.
            metadatas.append({
                "layer": card.layer,
                "title": card.title,
                "tags": ",".join(card.tags) if card.tags else "",
                "source": card.title,
                "source_type": (card.metadata or {}).get("source_type", "MD") if hasattr(card, "metadata") else "MD",
                "size_kb": round(len(card.content.encode("utf-8")) / 1024, 1),
                "chunks": 1,
                "vector_dimensions": CHROMA_DEFAULT_EMBEDDING_DIMENSIONS,
                "date_added": datetime.datetime.now().isoformat(timespec="seconds"),
            })

        try:
            self._collection.upsert(ids=ids, documents=documents, metadatas=metadatas)
        except Exception as e:
            raise RuntimeError(f"Falha ao fazer upsert de {len(cards)} card(s) no ChromaDB: {e}") from e

    @staticmethod
    def manual_document_id(title: str) -> str:
        """ID lógico estável usado pelo RAG de documentos do usuário.

        PHX-FIX (auditoria completa 2026-08-28): antes normalizava só com
        `.strip()`, sem baixar a caixa - só o frontend (RagDrawer.tsx,
        `d.title.trim().toLowerCase() === newTitle.trim().toLowerCase()`)
        decidia se um upload era "reindexação" (não conta na cota) comparando
        títulos ignorando maiúsculas/minúsculas. Resultado: um título como
        "Manual.pdf" (já indexado) e um novo upload "manual.pdf" eram tratados
        pela UI como o MESMO documento (reindexação livre, sem checar cota),
        mas geravam parent_id diferentes aqui (hash calculado sobre texto com
        caixa diferente) - o backend via como documento NOVO e aplicava
        validate_product_limits() como tal, podendo rejeitar por cota cheia
        mesmo a UI já tendo "aprovado" a operação como reindexação, sem
        explicação clara na tela. Agora os dois lados usam exatamente a mesma
        regra de identidade (strip + lower).
        """
        import hashlib
        normalized = (title or "").strip().lower()
        return f"manual::{hashlib.sha1(normalized.encode('utf-8')).hexdigest()[:16]}"

    def document_exists_by_title(self, title: str) -> bool:
        """Só considera existente se o documento estiver na allowlist íntegra."""
        if not self.available or not (title or "").strip():
            return False
        parent_id = self.manual_document_id(title)
        return parent_id in self._authorized_user_ids()

    def validate_product_limits(
        self,
        title: str,
        content: str,
        *,
        max_documents: int | None,
        max_characters: int | None,
    ) -> None:
        """Última barreira de produto antes de gerar embeddings.

        PHX-FIX (2026-09-06, correção conceitual do usuário, com análise
        técnica detalhada trazida por ele): antes, `max_characters` era
        aplicado por DOCUMENTO isolado (`len(content) > max_characters`) -
        no Free, isso significava que CADA um dos 10 documentos podia ter
        até 150M caracteres, uma capacidade potencial de até 1,5 BILHÃO de
        caracteres no plano gratuito - dez vezes maior que a arquitetura
        comercial pretendida. A regra correta é um ORÇAMENTO AGREGADO: os
        10 documentos, juntos, compartilham um teto único de caracteres
        extraídos no repositório inteiro.

        Reindexação tratada corretamente: a contribuição ATUAL do mesmo
        documento (se já existir) é descontada antes de projetar o novo
        total - nunca conta a mesma vaga duas vezes só porque o título já
        estava indexado com um tamanho diferente."""
        if max_documents is not None and not self.document_exists_by_title(title):
            current = self.logical_document_count()
            if current >= max_documents:
                raise ValueError(
                    f"Limite de documentos do plano atingido: {current}/{max_documents}. "
                    "Remova um documento ou use um plano com limite maior."
                )

        if max_characters is not None:
            parent_id = self.manual_document_id(title)
            current_total = self.total_extracted_characters()
            previous_contribution = self._extracted_characters_for(parent_id)
            projected_total = current_total - previous_contribution + len(content)
            if projected_total > max_characters:
                raise ValueError(
                    f"Documento excede o orçamento total de caracteres do plano: "
                    f"este arquivo adicionaria {len(content):,} caracteres ao repositório "
                    f"(uso atual: {current_total:,}/{max_characters:,}); "
                    f"o novo total ({projected_total:,}) ultrapassaria o limite em "
                    f"{projected_total - max_characters:,} caracteres."
                )

    def add_document_chunked(self, title: str, content: str, source_type: str = "MD") -> dict:
        """Indexa um documento do usuário em vários chunks reais."""
        if not self.available:
            raise RuntimeError(
                f"ChromaRagBackend indisponível para add_document_chunked: {self._unavailable_reason or 'motivo desconhecido'}"
            )
        title = (title or "").strip()
        content = (content or "").strip()
        if not title:
            raise ValueError("title não pode ser vazio")
        if not content:
            raise ValueError("content não pode ser vazio")

        import datetime

        # Defesa em profundidade: mesmo uma chamada direta ao backend precisa
        # respeitar licença/limites; não depende da API FastAPI.
        from phoenix_kernel.licensing.plans import get_rag_limits
        limits = get_rag_limits()
        self.validate_product_limits(
            title,
            content,
            max_documents=limits.get("max_documents"),
            max_characters=limits.get("max_characters"),
        )

        parent_id = self.manual_document_id(title)
        chunks = self._chunk_text(content)
        if not chunks:
            raise ValueError("documento não produziu nenhum chunk")

        # Reingestão substitui todos os chunks anteriores desse documento.
        try:
            previous = self._collection.get(where={"parent_id": parent_id}, include=["metadatas"])
            previous_ids = previous.get("ids", []) or []
            if previous_ids:
                self._collection.delete(ids=previous_ids)
            # Compatibilidade: versão antiga usava o próprio parent_id como id único.
            legacy = self._collection.get(ids=[parent_id], include=["metadatas"])
            if legacy.get("ids"):
                self._collection.delete(ids=[parent_id])
        except Exception as e:
            raise RuntimeError(f"Falha ao preparar reindexação de '{title}': {e}") from e

        size_kb = round(len(content.encode("utf-8")) / 1024, 1)
        date_added = datetime.datetime.now().isoformat(timespec="seconds")
        ids, docs, metas = [], [], []
        for idx, chunk in enumerate(chunks):
            chunk_id = f"{parent_id}::chunk::{idx:05d}"
            ids.append(chunk_id)
            docs.append(chunk)
            metas.append({
                "layer": "manual",
                "title": title,
                "tags": "",
                "source": title,
                "source_type": source_type or "DOC",
                "size_kb": size_kb,
                "chunks": len(chunks),
                "chunk_count": len(chunks),
                "chunk_index": idx,
                "parent_id": parent_id,
                "vector_dimensions": CHROMA_DEFAULT_EMBEDDING_DIMENSIONS,
                "date_added": date_added,
            })

        # PHX-FIX (2026-09-03, auditoria ChatGPT — RAG lento): antes o
        # documento era vetorizado DUAS vezes. Um primeiro upsert gravava os
        # chunks; depois o registry/ledger rodava e um SEGUNDO upsert
        # re-gravava os MESMOS chunks só para anexar 3 campos de cross-link ao
        # metadata. Cada upsert faz o ChromaDB recomputar o embedding de todos
        # os documents, então em documentos grandes isso DOBRAVA o tempo e o
        # custo (o "anexa com extrema lentidão" relatado). Agora o ledger/
        # registry roda ANTES, os cross-links entram no metadata inicial, e há
        # UM upsert só — a vetorização acontece uma única vez.
        try:
            existed_before = parent_id in self._authorized_user_ids()

            self._user_registry.authorize(parent_id, {
                "title": title,
                "source_type": source_type or "DOC",
                "date_added": date_added,
                # PHX-FIX (2026-09-06, correção conceitual do usuário, com
                # análise técnica detalhada: o limite de caracteres do plano
                # tinha sido implementado como um teto POR DOCUMENTO
                # ("cada um dos 10 pode ter até 150M" = até 1,5 bilhão no
                # Free), quando a regra correta é um ORÇAMENTO AGREGADO do
                # repositório inteiro (150M no total, somando todos os
                # documentos). Guardado aqui, no MESMO dict que `authorize()`
                # já sobrescreve por parent_id - reindexar o mesmo título
                # atualiza este valor automaticamente, sem contar a
                # contribuição antiga duas vezes (não precisa de lógica de
                # "subtrai o antigo, soma o novo" no chamador - a
                # sobrescrita do dict já faz isso por construção). Guarda o
                # texto extraído ORIGINAL (antes do chunking) - nunca a soma
                # dos chunks, que pode ter overlap e contar texto repetido.
                "extracted_characters": len(content),
            })

            event = self._user_ledger.append(
                "reindex" if existed_before else "authorize",
                parent_id,
                title=title,
                source_type=source_type or "DOC",
            )

            # cross-links entram no metadata ANTES de vetorizar (upsert único)
            for idx in range(len(metas)):
                metas[idx]["ledger_generation"] = int(event["generation"])
                metas[idx]["ledger_event_hash"] = str(event["event_hash"])
                metas[idx]["registry_parent_id"] = parent_id

            # ÚNICO upsert — vetoriza cada chunk uma vez só. Lotes evitam
            # chamadas gigantes para documentos enormes.
            batch_size = 128
            for i in range(0, len(ids), batch_size):
                self._collection.upsert(
                    ids=ids[i:i+batch_size],
                    documents=docs[i:i+batch_size],
                    metadatas=metas[i:i+batch_size],
                )

            self._user_consensus.checkpoint()
            consensus = self._user_consensus.validate()
            if not consensus.valid:
                raise RuntimeError(consensus.reason)

        except Exception as e:
            try:
                self._collection.delete(ids=ids)
            except Exception:
                logger.error("Rollback de chunks falhou após erro no consenso.", exc_info=True)
            raise RuntimeError(
                f"Documento '{title}' não pôde ser indexado/autorizado: {e}"
            ) from e

        return {
            "id": parent_id,
            "title": title,
            "sourceType": source_type or "DOC",
            "dateAdded": date_added,
            "sizeKb": size_kb,
            "chunks": len(chunks),
            "status": "INDEXED",
            "vectorDimensions": CHROMA_DEFAULT_EMBEDDING_DIMENSIONS,
        }

    def add_document(self, title: str, content: str, source_type: str = "MD") -> dict:
        """Compatibilidade com callers antigos; agora usa chunking real."""
        return self.add_document_chunked(title, content, source_type)

    def delete_document(self, doc_id: str) -> bool:
        """Remove documento lógico e todos os seus chunks.

        PHX-FIX (auditoria completa 2026-08-28): a ordem antiga apagava os
        chunks do Chroma PRIMEIRO e só depois tentava revoke()/ledger/
        checkpoint() do registry - se essa segunda etapa falhasse (disco
        cheio, registry corrompido), o conteúdo já tinha sumido do índice,
        mas `doc_id` continuava em `registry_ids`, e `_authorized_user_ids()`
        (que deriva de `self._user_consensus.validate().authorized_ids`, não
        do que está fisicamente no Chroma) continuava contando esse
        documento fantasma contra `max_documents` do plano - uma vaga da
        licença ficava presa sem nenhum chunk correspondente, sem
        reconciliação automática. Invertido: revoke/ledger/checkpoint
        primeiro. Como TODO caminho de leitura (list_documents(),
        logical_document_count(), query_user_with_scores() via
        _authorized_user_ids()) já filtra estritamente pela allowlist do
        consenso - nunca pelo que existe fisicamente no Chroma - assim que o
        revoke() é confirmado o documento já está invisível e não conta mais
        na cota, mesmo que a limpeza física dos chunks abaixo venha a falhar
        (nesse caso, só fica lixo em disco nunca mais consultável - não uma
        vaga de licença presa nem um risco de conteúdo revogado ainda
        aparecer em buscas).
        """
        if not self.available:
            raise RuntimeError(
                f"ChromaRagBackend indisponível para delete_document: {self._unavailable_reason or 'motivo desconhecido'}"
            )
        if not doc_id:
            return False
        try:
            ids_to_delete: list[str] = []
            grouped = self._collection.get(where={"parent_id": doc_id}, include=["metadatas"])
            ids_to_delete.extend(grouped.get("ids", []) or [])
            direct = self._collection.get(ids=[doc_id], include=["metadatas"])
            ids_to_delete.extend(direct.get("ids", []) or [])
            ids_to_delete = list(dict.fromkeys(ids_to_delete))
            if not ids_to_delete:
                return False

            try:
                self._user_registry.revoke(doc_id)
                self._user_ledger.append("revoke", doc_id)
                self._user_consensus.checkpoint()

                consensus = self._user_consensus.validate()
                if not consensus.valid:
                    raise RuntimeError(consensus.reason)
            except Exception as e:
                logger.error(
                    "Falha ao revogar documento '%s' no consenso de integridade - chunks NÃO foram apagados "
                    "do Chroma (nada mudou, operação abortada com segurança): %s",
                    doc_id, e,
                )
                raise RuntimeError(
                    "Falha ao atualizar o consenso de integridade antes de remover o documento. "
                    "Nada foi apagado - tente novamente."
                ) from e

            try:
                self._collection.delete(ids=ids_to_delete)
            except Exception as e:
                logger.error(
                    "Documento '%s' já revogado no consenso (não conta mais na cota nem aparece em buscas), "
                    "mas a limpeza física dos chunks no Chroma falhou - ficará como lixo em disco: %s",
                    doc_id, e,
                )

            return True
        except Exception as e:
            raise RuntimeError(f"Falha ao remover documento '{doc_id}' do ChromaDB: {e}") from e


# PHX-FIX (auditoria 2026-08-09): PlannerEngine (phoenix_kernel/planner/engine.py)
# e ReasoningEngine (phoenix_kernel/intelligence/reasoning_engine.py) cada um
# instanciava seu próprio `ChromaRagBackend(persist_dir="data/chroma_db")`
# de forma independente - dois clientes ChromaDB persistentes separados
# (cada um com seu próprio handle de SQLite/HNSW) apontando pro MESMO
# diretório, dentro do MESMO processo. ChromaDB PersistentClient não foi
# desenhado pra múltiplas instâncias concorrentes no mesmo path dentro de
# um processo (é o motivo pelo qual os testes de boot já precisam rodar em
# diretório isolado pra não corromper o índice HNSW - ver regra do projeto).
# Se `infer` e `resident research` forem usados em sequência rápida, os dois
# clientes competem pelo mesmo lock de SQLite. Esta função dá um singleton
# por processo por (persist_dir, collection_name), pra qualquer parte do
# kernel que precise de RAG reusar a mesma conexão em vez de abrir outra.
_shared_backends: dict[tuple[str, str], "ChromaRagBackend"] = {}


def get_shared_chroma_backend(
    persist_dir: str | Path = "data/chroma_db",
    collection_name: str = DEFAULT_COLLECTION_NAME,
) -> "ChromaRagBackend":
    """Retorna uma instância única de ChromaRagBackend por (persist_dir,
    collection_name) dentro do processo atual. Use isto em vez de
    `ChromaRagBackend(...)` diretamente sempre que mais de um subsistema
    (planner, resident/reasoning, etc.) puder precisar do mesmo índice."""
    key = (str(Path(persist_dir)), collection_name)
    if key not in _shared_backends:
        _shared_backends[key] = ChromaRagBackend(
            persist_dir=persist_dir, collection_name=collection_name
        )
    return _shared_backends[key]
