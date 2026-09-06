"""Bateria de testes: o limite de caracteres do RAG é um ORÇAMENTO
AGREGADO do repositório inteiro, não um teto por documento isolado.

Achado real do usuário, com análise técnica detalhada trazida por ele
(print de tela + conversa anexada): a implementação anterior aplicava
`max_characters` a CADA documento isoladamente - no Free (150.000.000),
isso significava que os 10 documentos, juntos, podiam somar até 1,5
BILHÃO de caracteres. A regra correta e pretendida é: os 10 documentos
COMPARTILHAM um orçamento único de 150.000.000 caracteres extraídos no
repositório inteiro.

Esta bateria reproduz EXATAMENTE a matriz de operações que o usuário
especificou (via análise técnica anexada) como prova mínima necessária:

    início                          -> total 0
    adicionar A (10.000.000)        -> total 10.000.000
    adicionar B (20.000.000)        -> total 30.000.000
    adicionar C (5.000.000)         -> total 35.000.000
    reindexar B (20M -> 25M)        -> total 40.000.000 (líquido +5M, nunca soma os 20M antigos de novo)
    excluir A                       -> total 30.000.000
    adicionar D (100.000.000)       -> total 130.000.000
    tentar E (25.000.000)           -> REJEITADO (130M + 25M = 155M > 150M)
    após rejeição                   -> total CONTINUA 130.000.000 (nunca muda numa tentativa recusada)

Usa o registry/ledger/consenso REAIS (arquivos temporários) - só a
coleção do ChromaDB em si é substituída por um fake em memória (chromadb
não está disponível neste ambiente de teste). Isso exercita a lógica de
contabilidade de verdade, incluindo as 4 travas de integridade
(autorização, registry, ledger, manifest) - não é um mock raso da conta
em si.
"""
import tempfile
from pathlib import Path

import pytest

from phoenix_kernel.intelligence.chroma_rag_backend import ChromaRagBackend
from phoenix_kernel.security.rag_integrity import RagIntegrityRegistry
from phoenix_kernel.security.rag_usage_ledger import RagUsageLedger
from phoenix_kernel.security.rag_integrity_manifest import RagIntegrityManifest
from phoenix_kernel.security.rag_consensus import RagConsensus


class _FakeChromaCollection:
    """Substitui a coleção real do ChromaDB por um dicionário em memória -
    implementa só os três métodos que chroma_rag_backend.py usa
    (get/upsert/delete), com o formato de retorno real da API do Chroma."""

    def __init__(self):
        self._items: dict[str, dict] = {}  # id -> {"document": str, "metadata": dict}

    def get(self, ids=None, where=None, include=None):
        if ids is not None:
            matched = {i: self._items[i] for i in ids if i in self._items}
        elif where is not None:
            key, value = next(iter(where.items()))
            matched = {i: it for i, it in self._items.items() if it["metadata"].get(key) == value}
        else:
            matched = dict(self._items)
        ids_out = list(matched.keys())
        return {
            "ids": ids_out,
            "documents": [matched[i]["document"] for i in ids_out],
            "metadatas": [matched[i]["metadata"] for i in ids_out],
        }

    def upsert(self, ids, documents, metadatas):
        for i, doc, meta in zip(ids, documents, metadatas):
            self._items[i] = {"document": doc, "metadata": meta}

    def delete(self, ids):
        for i in ids:
            self._items.pop(i, None)

    def count(self):
        return len(self._items)


@pytest.fixture
def backend():
    """Backend real, com registry/ledger/manifest/consenso reais (arquivos
    temporários) e só a coleção do Chroma faked em memória."""
    tmp_dir = Path(tempfile.mkdtemp())
    registry = RagIntegrityRegistry(
        registry_path=tmp_dir / "registry.json",
        key_path=tmp_dir / ".registry.key",
    )
    ledger = RagUsageLedger(ledger_path=tmp_dir / "ledger.json")
    # PHX-NOTE: RagIntegrityManifest reaproveita o MESMO key_path do
    # registry por padrão (mesma chave HMAC pros dois) - sem passar
    # explicitamente aqui, ele cairia no caminho REAL do projeto
    # (data/.rag_user_registry.key), causando falha de verificação por
    # usar uma chave diferente da do registry deste teste.
    manifest = RagIntegrityManifest(manifest_path=tmp_dir / "manifest.json", key_path=tmp_dir / ".registry.key")
    consensus = RagConsensus(registry=registry, ledger=ledger, manifest=manifest)

    # PHX-NOTE: registry e ledger exigem inicialização explícita (fail-closed
    # por padrão, "uninitialized" não é tratado como "vazio e pronto pra
    # usar" - proteção deliberada contra recriação automática silenciosa).
    registry.initialize({})
    ledger.initialize({})

    b = object.__new__(ChromaRagBackend)
    b._unavailable_reason = None
    b._collection = _FakeChromaCollection()
    b._user_registry = registry
    b._user_ledger = ledger
    b._user_consensus = consensus
    return b


def _add(backend, title: str, chars: int, max_characters: int = 150_000_000):
    """Chama o fluxo real de add_document_chunked, com um teto alto de
    documentos (não é o que este teste está verificando)."""
    conteudo = "x" * chars
    import phoenix_kernel.licensing.plans as plans_module
    original = plans_module.get_rag_limits
    plans_module.get_rag_limits = lambda: {"max_documents": 10, "max_characters": max_characters}
    try:
        return backend.add_document_chunked(title, conteudo, "TXT")
    finally:
        plans_module.get_rag_limits = original


def test_full_lifecycle_matches_exact_matrix_specified_by_user(backend):
    """A matriz de operações exata especificada na análise técnica do
    usuário - cada passo confere o total agregado esperado."""
    assert backend.total_extracted_characters() == 0

    _add(backend, "A", 10_000_000)
    assert backend.total_extracted_characters() == 10_000_000

    _add(backend, "B", 20_000_000)
    assert backend.total_extracted_characters() == 30_000_000

    _add(backend, "C", 5_000_000)
    assert backend.total_extracted_characters() == 35_000_000

    # reindexar B (20M -> 25M): líquido +5M, NUNCA soma os 20M antigos de novo
    _add(backend, "B", 25_000_000)
    assert backend.total_extracted_characters() == 40_000_000, (
        "reindexar B deveria dar +5.000.000 líquido (25M novo - 20M antigo), "
        "não somar os 25M por cima dos 20M já contados"
    )

    # excluir A
    parent_id_a = backend.manual_document_id("A")
    assert backend.delete_document(parent_id_a) is True
    assert backend.total_extracted_characters() == 30_000_000

    _add(backend, "D", 100_000_000)
    assert backend.total_extracted_characters() == 130_000_000

    # tentar E (25M): 130M + 25M = 155M > 150M -> REJEITADO
    with pytest.raises(ValueError, match="orçamento total"):
        _add(backend, "E", 25_000_000)

    # ACHADO CRÍTICO da análise: uma tentativa recusada NUNCA pode alterar o total
    assert backend.total_extracted_characters() == 130_000_000, (
        "uma tentativa de upload REJEITADA não pode mudar o total agregado - "
        "'E' nunca deveria ter chegado a ser contado"
    )


def test_reconciliation_sum_of_individual_documents_matches_total(backend):
    """Prova de reconciliação pedida explicitamente: somar os documentos
    individualmente (fora da Phoenix) tem que bater com o total que o
    backend reporta - exatamente a conta que o usuário pediu pra poder
    conferir com os próprios números."""
    _add(backend, "Documento A.docx", 7_054_990)
    _add(backend, "Documento B.docx", 1_148_465)
    _add(backend, "Documento C.md", 743_393)

    soma_individual = 7_054_990 + 1_148_465 + 743_393
    assert soma_individual == 8_946_848

    assert backend.total_extracted_characters() == soma_individual == 8_946_848


def test_chunk_overlap_never_inflates_the_total(backend):
    """Guarda explícita do achado do usuário: a soma NUNCA pode vir dos
    chunks armazenados no Chroma (que podem ter overlap e contar texto
    repetido) - sempre do texto extraído ORIGINAL, guardado uma vez só no
    registry no momento da indexação."""
    texto_original = "x" * 1_000_000
    _add(backend, "Doc com overlap", 1_000_000)

    # confirma que o Chroma de fato tem MAIS caracteres armazenados em
    # chunks (por causa do overlap) do que o texto original - provando
    # que se a soma fosse feita a partir dos chunks, o resultado estaria
    # inflado
    total_chars_nos_chunks = sum(
        len(item["document"]) for item in backend._collection._items.values()
    )
    assert total_chars_nos_chunks > 1_000_000, (
        "o teste não está provando nada se o overlap não gerar excesso real nos chunks"
    )

    # o total reportado tem que ser o ORIGINAL, não a soma inflada dos chunks
    assert backend.total_extracted_characters() == 1_000_000


def test_document_within_budget_after_others_exist_still_succeeds(backend):
    """Regressão: um documento legítimo, dentro do orçamento restante,
    continua sendo aceito normalmente mesmo com outros já indexados."""
    _add(backend, "Existente", 100_000_000)
    _add(backend, "Novo", 40_000_000)  # 100M + 40M = 140M, ainda dentro de 150M
    assert backend.total_extracted_characters() == 140_000_000
