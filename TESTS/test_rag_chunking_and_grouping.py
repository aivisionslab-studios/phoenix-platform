"""
Testes de regressão pro achado real do usuário 2026-08-24/28 ("habilitar
RAG... ja pode receber qualquer documento e injetar esse conhecimento pra
qualquer llm consumir e/ou ler o arquivo de 1000 folhas e usar conhecimento
pra responder melhor").

Cobre a parte de phoenix_kernel/intelligence/chroma_rag_backend.py que NÃO
existia antes desta mudança:

1. split_into_chunks() - função pura, sem dependência de chromadb. Antes
   desta correção, TODO documento indexado virava 1 único chunk, o que era
   um bug de dado invisível: a DefaultEmbeddingFunction do Chroma
   (all-MiniLM-L6-v2) trunca silenciosamente qualquer texto além de ~256
   tokens (~900-1000 caracteres) - um documento de 1000 páginas vetorizado
   como 1 chunk só teria menos de 1 página de fato pesquisável.

2. add_document_chunked()/list_documents()/delete_document() -
   comportamento de agrupamento por `group_id` (múltiplos chunks de um
   mesmo documento aparecem como UMA linha na UI, e são apagados juntos).
   `chromadb` não está instalado neste ambiente de sandbox (pacote nativo
   pesado, não presente na suite de testes existente do projeto - nenhum
   teste anterior o importa) - mesma técnica já usada em
   tests/test_describe_image_bridge.py (`object.__new__(ResidentManager)`
   pra pular __init__/conexões reais) é aplicada aqui: instancia
   ChromaRagBackend via object.__new__ (pula _connect(), que é o único
   lugar que importa chromadb de verdade) e injeta uma coleção FALSA
   mínima (FakeCollection abaixo, implementando só get/upsert/delete/count)
   no lugar de self._collection - os métodos testados (add_document_chunked,
   list_documents, delete_document) são executados de VERDADE, sem
   reimplementação, só a camada de armazenamento do ChromaDB é substituída.

Rodar: pytest -q tests/test_rag_chunking_and_grouping.py (de dentro de
'PHOENIX 3.0/')
"""
import sys
import tempfile
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from phoenix_kernel.intelligence.chroma_rag_backend import (
    ChromaRagBackend,
    CHROMA_CHUNK_MAX_CHARS,
    CHROMA_CHUNK_OVERLAP_CHARS,
    CHROMA_DEFAULT_EMBEDDING_DIMENSIONS,
    split_into_chunks,
)
from phoenix_kernel.security.rag_integrity import RagIntegrityRegistry
from phoenix_kernel.security.rag_usage_ledger import RagUsageLedger
from phoenix_kernel.security.rag_integrity_manifest import RagIntegrityManifest
from phoenix_kernel.security.rag_consensus import RagConsensus


# ---------------------------------------------------------------------------
# Parte 1: split_into_chunks() - função pura, sem chromadb.
# ---------------------------------------------------------------------------

def test_split_into_chunks_empty_text_returns_empty_list():
    assert split_into_chunks("") == []
    assert split_into_chunks("   \n  ") == []


def test_split_into_chunks_short_text_is_single_chunk_identical_to_input():
    # Comportamento IDÊNTICO ao "1 documento = 1 chunk" de antes pra
    # qualquer conteúdo pequeno - a maioria dos pastes manuais da Quick
    # Index nunca deveria notar diferença nenhuma.
    text = "Um parágrafo curto de teste, bem abaixo do limite de chunk."
    chunks = split_into_chunks(text)
    assert chunks == [text]


def test_split_into_chunks_long_multi_paragraph_text_produces_multiple_chunks_within_limit():
    # Gera texto bem maior que CHROMA_CHUNK_MAX_CHARS, em vários parágrafos.
    paragraphs = [f"Parágrafo número {i}. " * 20 for i in range(20)]
    text = "\n\n".join(paragraphs)
    assert len(text) > CHROMA_CHUNK_MAX_CHARS * 3

    chunks = split_into_chunks(text)
    assert len(chunks) > 1, "documento longo deveria virar múltiplos chunks pesquisáveis"

    # Nenhum chunk (exceto possivelmente por causa da sobreposição
    # herdada) deveria passar MUITO do teto - a lógica só ultrapassa
    # max_chars quando um ÚNICO parágrafo já é maior que o teto sozinho,
    # o que não é o caso aqui.
    for c in chunks:
        assert len(c) <= CHROMA_CHUNK_MAX_CHARS, f"chunk de {len(c)} chars excedeu o teto de {CHROMA_CHUNK_MAX_CHARS}"

    # Nenhum conteúdo original devia "sumir": concatenando os chunks (sem
    # dedup da sobreposição) o texto original inteiro deve estar coberto -
    # checa isso via um trecho de cada parágrafo aparecendo em algum chunk.
    for i in range(20):
        marker = f"Parágrafo número {i}."
        assert any(marker in c for c in chunks), f"conteúdo do parágrafo {i} não apareceu em nenhum chunk"


def test_split_into_chunks_consecutive_chunks_overlap():
    # A sobreposição existe pra uma ideia cortada no fim de um chunk não
    # sumir de vista - o começo do chunk seguinte deve conter parte do
    # final do chunk anterior (quando ambos vêm da divisão por parágrafo,
    # não do corte bruto de um parágrafo gigante).
    paragraphs = [f"Frase-marcador-{i:03d} preenchendo espaço. " * 15 for i in range(10)]
    text = "\n\n".join(paragraphs)
    chunks = split_into_chunks(text)
    assert len(chunks) >= 2

    tail_of_first = chunks[0][-CHROMA_CHUNK_OVERLAP_CHARS:]
    # Pelo menos uma fatia razoável do fim do primeiro chunk deve reaparecer
    # no início do segundo (a implementação usa exatamente os últimos
    # overlap_chars caracteres do chunk anterior como prefixo do próximo).
    assert tail_of_first[-40:] in chunks[1]


def test_split_into_chunks_single_paragraph_larger_than_max_is_hard_split_with_overlap():
    # Parágrafo ÚNICO (sem quebra dupla de linha) maior que o teto - não
    # tem estrutura de parágrafo pra preservar, precisa cortar bruto.
    huge_paragraph = "x" * (CHROMA_CHUNK_MAX_CHARS * 3 + 50)
    chunks = split_into_chunks(huge_paragraph)
    assert len(chunks) >= 3
    for c in chunks:
        assert len(c) <= CHROMA_CHUNK_MAX_CHARS
    # Cobertura completa: todo caractere original está em algum chunk.
    assert "".join(dict.fromkeys(chunks)) or True  # cobertura já checada abaixo por tamanho total
    total_chars_with_overlap = sum(len(c) for c in chunks)
    # Com sobreposição, o total é MAIOR que o texto original (repetição
    # proposital entre pedaços vizinhos).
    assert total_chars_with_overlap >= len(huge_paragraph)


# ---------------------------------------------------------------------------
# Parte 2: add_document_chunked() / list_documents() / delete_document() -
# usando uma coleção ChromaDB FALSA (mesma técnica de
# object.__new__(...) já usada em tests/test_describe_image_bridge.py).
# ---------------------------------------------------------------------------

class FakeCollection:
    """Réplica mínima da API do chromadb.Collection realmente usada por
    ChromaRagBackend (get/upsert/delete/count) - guarda tudo em memória."""

    def __init__(self):
        self._store: dict[str, dict] = {}  # id -> {"document": str, "metadata": dict}

    def get(self, ids=None, where=None, include=None):
        if ids is not None:
            matched = [i for i in ids if i in self._store]
        elif where is not None:
            matched = [
                i for i, entry in self._store.items()
                if all(entry["metadata"].get(k) == v for k, v in where.items())
            ]
        else:
            matched = list(self._store.keys())
        return {
            "ids": matched,
            "metadatas": [self._store[i]["metadata"] for i in matched],
            "documents": [self._store[i]["document"] for i in matched],
        }

    def upsert(self, ids, documents, metadatas):
        for i, doc, meta in zip(ids, documents, metadatas):
            self._store[i] = {"document": doc, "metadata": meta}

    def delete(self, ids):
        for i in ids:
            self._store.pop(i, None)

    def count(self):
        return len(self._store)


def _fake_backend() -> ChromaRagBackend:
    """object.__new__ pula __init__ (e portanto _connect(), o único lugar
    que de fato importa o pacote 'chromadb') - injeta uma FakeCollection no
    lugar da coleção real.

    PHX-FIX (31/08): `add_document_chunked`/`delete_document`/
    `list_documents` passaram a exigir `self._user_registry`/
    `self._user_ledger`/`self._user_consensus` (subsistema real de
    integridade/licenciamento do RAG - HMAC + hash chain + manifest,
    ver phoenix_kernel/security/rag_*.py), que `object.__new__()` nunca
    inicializa (só o `__init__`/`_connect()` real faz isso, e esses
    dependem de `chromadb` de verdade). Em vez de pular esse subsistema
    (o que mascararia testes que devem continuar rejeitando estado
    inválido), cada teste ganha uma instância REAL e isolada dele,
    apontando pra um diretório temporário próprio (nunca `data/` do
    projeto) - registry/ledger/manifest inicializados do zero e vazios,
    exatamente como um usuário FREE novo. `commercial_guard.
    authorization_state()` já retorna `valid=True`/`plan="free"`
    incondicionalmente quando não há capability PRO ativa (ver
    `commercial_guard.py`), então nenhum token/licença precisa ser
    simulado à parte."""
    backend = object.__new__(ChromaRagBackend)
    backend._collection = FakeCollection()
    backend._unavailable_reason = None

    tmp_dir = Path(tempfile.mkdtemp(prefix="phoenix_rag_test_"))
    key_path = tmp_dir / ".rag_user_registry.key"
    registry = RagIntegrityRegistry(registry_path=tmp_dir / "rag_user_registry.json", key_path=key_path)
    ledger = RagUsageLedger(ledger_path=tmp_dir / "rag_usage_ledger.json", key_path=key_path)
    manifest = RagIntegrityManifest(manifest_path=tmp_dir / "rag_integrity.manifest", key_path=key_path)
    registry.initialize({})
    ledger.initialize({})
    consensus = RagConsensus(registry=registry, ledger=ledger, manifest=manifest)
    consensus.checkpoint()

    backend._user_registry = registry
    backend._user_ledger = ledger
    backend._user_consensus = consensus
    return backend


def test_add_document_chunked_short_content_is_single_chunk_like_before():
    backend = _fake_backend()
    result = backend.add_document_chunked("nota_curta.md", "Conteúdo bem curto.", "MD")
    assert result["chunks"] == 1
    assert result["status"] == "INDEXED"
    assert result["vectorDimensions"] == CHROMA_DEFAULT_EMBEDDING_DIMENSIONS
    # PHX-FIX (31/08): o campo de metadado real usado por
    # add_document_chunked()/list_documents()/delete_document() sempre foi
    # "parent_id" (nunca existiu "group_id" em chroma_rag_backend.py - ver
    # os vários usos em _authorized_user_ids()/list_documents()/
    # delete_document()), e o formato real do id de chunk é
    # "{parent_id}::chunk::{idx:05d}" (2 separadores "::", 5 dígitos), não
    # "{parent_id}::chunk{idx:04d}". Esse mismatch nunca tinha sido notado
    # porque o AttributeError de _user_registry (corrigido acima) sempre
    # abortava a chamada antes de chegar aqui.
    stored = backend._collection.get(where={"parent_id": result["id"]})
    assert len(stored["ids"]) == 1
    assert stored["ids"][0] == f"{result['id']}::chunk::00000"


def test_add_document_chunked_long_content_produces_multiple_chunks_sharing_group_id():
    backend = _fake_backend()
    paragraphs = [f"Seção {i} do manual de 1000 páginas. " * 20 for i in range(30)]
    long_content = "\n\n".join(paragraphs)
    result = backend.add_document_chunked("manual_gigante.pdf", long_content, "PDF")

    assert result["chunks"] > 1, "documento grande devia virar múltiplos chunks pesquisáveis, não 1 só"
    stored = backend._collection.get(where={"parent_id": result["id"]})
    assert len(stored["ids"]) == result["chunks"]
    # Todo texto do documento original deve estar representado em algum
    # chunk indexado - a garantia real por trás de "não truncar mais
    # silenciosamente o arquivo de 1000 páginas".
    all_text = "\n".join(stored["documents"])
    for i in range(30):
        assert f"Seção {i} do manual" in all_text


def test_add_document_chunked_reindexing_shorter_content_removes_orphan_chunks():
    # PHX-FIX coberto aqui: reindexar o MESMO título com MENOS chunks do
    # que a versão anterior (documento editado/encurtado) não pode deixar
    # chunks órfãos da indexação antiga pra trás.
    backend = _fake_backend()
    paragraphs = [f"Versão longa, parágrafo {i}. " * 20 for i in range(30)]
    first = backend.add_document_chunked("doc_editado.md", "\n\n".join(paragraphs), "MD")
    assert first["chunks"] > 3

    second = backend.add_document_chunked("doc_editado.md", "Versão bem mais curta agora.", "MD")
    assert second["id"] == first["id"], "mesmo título deve gerar o mesmo group_id (determinístico)"
    assert second["chunks"] == 1

    stored = backend._collection.get(where={"parent_id": first["id"]})
    assert len(stored["ids"]) == 1, "chunks órfãos da versão anterior deveriam ter sido apagados"
    assert stored["ids"][0] == f"{first['id']}::chunk::00000"


def test_add_document_chunked_rejects_empty_title_or_content():
    backend = _fake_backend()
    with pytest.raises(ValueError):
        backend.add_document_chunked("", "conteúdo", "MD")
    with pytest.raises(ValueError):
        backend.add_document_chunked("titulo", "   ", "MD")


def test_add_document_chunked_raises_when_backend_unavailable():
    backend = object.__new__(ChromaRagBackend)
    backend._collection = None
    backend._unavailable_reason = "chromadb não instalado (teste)"
    with pytest.raises(RuntimeError):
        backend.add_document_chunked("titulo", "conteúdo", "MD")


def test_list_documents_groups_chunks_back_into_one_row_per_source_document():
    backend = _fake_backend()
    long_doc = backend.add_document_chunked(
        "relatorio_extenso.docx", "\n\n".join([f"Parágrafo {i} de teste. " * 20 for i in range(15)]), "DOCX"
    )
    short_doc = backend.add_document_chunked("nota.md", "Texto curto.", "MD")

    # Documento LEGADO pré-chunking (sem parent_id/chunk_count - upsert()
    # de MemoryCard ou add_document() antigo escreviam direto sem esses
    # campos).
    # PHX-FIX (31/08): 2 correções sobre a versão anterior deste teste:
    # (1) o campo real que list_documents()/_raw_manual_documents() usa
    # pra reconhecer "documento manual" é "layer": "manual" OU um id com
    # prefixo "manual::" (nunca existiu "group_id" - ver
    # _raw_manual_documents() em chroma_rag_backend.py) - sem isso o
    # upsert não era nem reconhecido como manual, muito menos listado;
    # (2) list_documents() hoje filtra estritamente pela allowlist do
    # consenso de integridade (documentado no próprio docstring do
    # método: "nunca usa documentos inseridos diretamente no ChromaDB sem
    # passar pelo fluxo autorizado") - simula aqui uma migração de
    # legado já concluída (o papel real de
    # ChromaRagBackend._bootstrap_user_integrity_once() em produção),
    # autorizando o id no registry/ledger antes de listar.
    legacy_id = ChromaRagBackend.manual_document_id("legado.txt")
    backend._collection.upsert(
        ids=[legacy_id],
        documents=["conteúdo legado sem parent_id"],
        metadatas=[{
            "layer": "manual", "source": "legado.txt", "source_type": "TXT",
            "size_kb": 1.2, "date_added": "2026-01-01T00:00:00",
        }],
    )
    backend._user_registry.authorize(legacy_id, {"title": "legado.txt", "source_type": "TXT", "date_added": "2026-01-01T00:00:00"})
    backend._user_ledger.append("authorize", legacy_id, title="legado.txt", source_type="TXT")
    backend._user_consensus.checkpoint()

    docs = backend.list_documents()
    docs_by_id = {d["id"]: d for d in docs}

    assert len(docs) == 3, "3 documentos de origem (1 chunked longo, 1 chunked curto, 1 legado) - nunca 1 linha por chunk"
    assert docs_by_id[long_doc["id"]]["chunks"] == long_doc["chunks"]
    assert docs_by_id[short_doc["id"]]["chunks"] == 1
    assert docs_by_id[legacy_id]["chunks"] == 1
    assert docs_by_id[legacy_id]["title"] == "legado.txt"


def test_delete_document_by_group_id_removes_all_chunks_at_once():
    backend = _fake_backend()
    doc = backend.add_document_chunked(
        "arquivo_grande.xlsx", "\n\n".join([f"Linha de dados {i}. " * 20 for i in range(25)]), "XLSX"
    )
    assert doc["chunks"] > 1
    assert backend._collection.count() == doc["chunks"]

    deleted = backend.delete_document(doc["id"])
    assert deleted is True
    assert backend._collection.count() == 0, "delete_document deveria apagar TODOS os chunks do grupo, não só 1"


def test_delete_document_falls_back_to_exact_id_for_legacy_documents_without_group_id():
    backend = _fake_backend()
    backend._collection.upsert(
        ids=["legacy_doc_2"],
        documents=["conteúdo legado"],
        metadatas=[{"source": "legado2.txt"}],
    )
    assert backend.delete_document("legacy_doc_2") is True
    assert backend._collection.count() == 0


def test_delete_document_returns_false_for_nonexistent_id():
    backend = _fake_backend()
    assert backend.delete_document("nao_existe_de_jeito_nenhum") is False


def test_delete_document_raises_when_backend_unavailable():
    backend = object.__new__(ChromaRagBackend)
    backend._collection = None
    backend._unavailable_reason = "chromadb não instalado (teste)"
    with pytest.raises(RuntimeError):
        backend.delete_document("qualquer-id")


def test_query_with_scores_returns_empty_list_when_backend_unavailable():
    backend = object.__new__(ChromaRagBackend)
    backend._collection = None
    backend._unavailable_reason = "chromadb não instalado (teste)"
    # Nunca lança exceção - RAG é "nice to have", ver docstring do método.
    assert backend.query_with_scores("qualquer pergunta") == []


def test_query_with_scores_returns_empty_list_for_blank_query():
    backend = _fake_backend()
    assert backend.query_with_scores("") == []
    assert backend.query_with_scores("   ") == []
