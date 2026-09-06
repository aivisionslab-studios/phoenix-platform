"""Teste: logical_document_count() nunca conta "documentos fantasma" -
IDs autorizados no registry que não correspondem a nada fisicamente
presente no Chroma.

Achado real do usuário, com dois prints de tela na mesma sessão: o painel
mostrava "INDEXED DOCUMENTS (3)" (a lista visível, vindo de
list_documents()), mas o upload seguinte foi rejeitado com "Limite de
documentos do plano atingido: 10/10" (vindo de logical_document_count())
- uma contradição visível na própria tela, no mesmo instante.

Causa raiz: list_documents() já fazia a interseção entre
_authorized_user_ids() (o que o registry/ledger/manifest autoriza) e
_raw_manual_documents() (o que fisicamente existe no Chroma agora) - só
logical_document_count() ficou de fora dessa mesma checagem, contando o
registry puro. Se o registry acumula IDs "fantasma" (autorizados no
papel, sem chunks correspondentes no Chroma - por um delete antigo
incompleto, corrupção, ou adulteração externa), a contagem que trava o
limite do plano fica inflada em relação ao que o usuário via e podia
gerenciar na tela.
"""
from phoenix_kernel.intelligence.chroma_rag_backend import ChromaRagBackend


def _make_backend(authorized_ids: set[str], raw_documents: list[dict]) -> ChromaRagBackend:
    backend = object.__new__(ChromaRagBackend)
    backend._authorized_user_ids = lambda: authorized_ids
    backend._raw_manual_documents = lambda: raw_documents
    return backend


def test_ghost_authorized_ids_are_not_counted():
    """O cenário exato do print de tela: registry autoriza 10 IDs, mas só
    3 têm chunks reais no Chroma - a contagem tem que refletir os 3 reais,
    não os 10 do registry."""
    authorized = {f"manual::{i}" for i in range(10)}  # 10 "vagas" autorizadas no registry
    raw_reais = [
        {"id": "manual::0", "title": "flux com comfyui.md"},
        {"id": "manual::1", "title": "AMD Intel NVIDIA.docx"},
        {"id": "manual::2", "title": "Geral Pesquisa na Web...docx"},
        # manual::3 até manual::9 são "fantasmas": autorizados no registry,
        # sem nenhum chunk correspondente no Chroma de verdade
    ]
    backend = _make_backend(authorized, raw_reais)
    assert backend.logical_document_count() == 3, (
        "deveria contar só os 3 documentos fisicamente presentes, não os "
        "10 'autorizados' no registry (alguns são fantasmas)"
    )


def test_count_matches_what_list_documents_would_show():
    """A contagem que trava o limite do plano e a lista que o usuário vê
    precisam sempre bater - nunca mais podem discordar como no print de
    tela (contagem dizia 10/10, lista mostrava só 3)."""
    authorized = {"manual::a", "manual::b", "manual::fantasma"}
    raw_reais = [
        {"id": "manual::a", "title": "doc a"},
        {"id": "manual::b", "title": "doc b"},
    ]
    backend = _make_backend(authorized, raw_reais)

    contagem = backend.logical_document_count()
    lista_visivel = ChromaRagBackend.list_documents(backend)

    assert contagem == len(lista_visivel) == 2


def test_no_ghosts_count_matches_authorized_exactly():
    """Caso normal (sem fantasmas): a contagem bate exatamente com o
    número de IDs autorizados, sem perder nenhum documento real."""
    authorized = {"manual::x", "manual::y", "manual::z"}
    raw_reais = [
        {"id": "manual::x", "title": "doc x"},
        {"id": "manual::y", "title": "doc y"},
        {"id": "manual::z", "title": "doc z"},
    ]
    backend = _make_backend(authorized, raw_reais)
    assert backend.logical_document_count() == 3


def test_empty_authorization_returns_zero_without_querying_chroma():
    """Quando o consenso falha (_authorized_user_ids() vazio), a contagem
    é 0 imediatamente - nem precisa consultar o Chroma."""
    chamou_raw = {"sim": False}

    def _raw_que_nao_deveria_ser_chamado():
        chamou_raw["sim"] = True
        return []

    backend = object.__new__(ChromaRagBackend)
    backend._authorized_user_ids = lambda: set()
    backend._raw_manual_documents = _raw_que_nao_deveria_ser_chamado

    assert backend.logical_document_count() == 0
    assert chamou_raw["sim"] is False, (
        "com _authorized_user_ids() vazio (consenso falhou), não precisa "
        "consultar o Chroma - a resposta já é 0"
    )
