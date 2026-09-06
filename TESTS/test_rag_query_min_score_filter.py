"""
Teste de regressão pra auditoria completa 2026-08-28, item "validar o
threshold min_score: 0.15 do RAG".

Contexto honesto: este ambiente de execução bloqueia o download do modelo
de embeddings usado pelo RAG de verdade (tanto a fonte padrão do ChromaDB
quanto o Hugging Face Hub devolvem 403 Forbidden) - então NÃO é possível
rodar uma busca vetorial semântica real aqui pra confirmar que 0.15 é o
valor "certo" pra separar resultado relevante de irrelevante. Isso exige
uso real com hardware/rede sem essa restrição (ver observabilidade
adicionada em AviaryApp.tsx, PHX-RAG console.debug, pra calibrar com dados
de produção).

O que ESTE teste valida, sem precisar de nenhum modelo de embeddings: o
mecanismo de filtro em si - POST /api/rag/query (api_server.py::rag_query)
recebe os hits já pontuados pelo backend (query_user_with_scores) e aplica
`hits = [h for h in hits if float(h.get("score", 0.0)) >= max(0.0, req.min_score)]`.
Fabricando hits com scores conhecidos (sem chamar nenhum embedding real),
confirma que esse filtro corta exatamente o que deveria cortar - inclusive
o caso de borda (score == min_score, que deve ser MANTIDO por usar >=) e a
proteção contra min_score negativo.

Rodar com: pytest -q (de dentro de 'PHOENIX 3.0/')
"""
import asyncio
import sys
from pathlib import Path
from unittest.mock import MagicMock

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))


def _make_kernel_with_backend(backend):
    knowledge = type("Knowledge", (), {"rag_backend": backend})()
    planner = type("Planner", (), {"knowledge": knowledge})()
    return type("Kernel", (), {"planner": planner})()


_FAKE_HITS = [
    {"text": "chunk A - muito relevante", "score": 0.42},
    {"text": "chunk B - na linha do corte real (0.15)", "score": 0.15},
    {"text": "chunk C - um pouco abaixo do corte", "score": 0.1499},
    {"text": "chunk D - claramente irrelevante", "score": 0.02},
    {"text": "chunk E - score zero", "score": 0.0},
]


def test_rag_query_filters_hits_below_min_score(monkeypatch):
    import api_server

    backend = MagicMock()
    backend.query_user_with_scores = MagicMock(return_value=list(_FAKE_HITS))
    monkeypatch.setattr(api_server, "kernel", _make_kernel_with_backend(backend))

    result = asyncio.run(api_server.rag_query(api_server.RagQueryReq(query="teste", min_score=0.15)))

    assert result["ok"] is True
    texts = [h["text"] for h in result["hits"]]
    assert texts == [
        "chunk A - muito relevante",
        "chunk B - na linha do corte real (0.15)",
    ], (
        "min_score=0.15 deveria manter só os hits com score >= 0.15 "
        f"(comparação inclusiva) - resultado real: {texts!r}"
    )


def test_rag_query_boundary_score_equal_to_min_score_is_kept():
    """Caso de borda explícito: o filtro usa `>=`, não `>` - um hit com
    score EXATAMENTE igual a min_score não pode ser descartado."""
    hits = [{"text": "exatamente no corte", "score": 0.15}]
    filtered = [h for h in hits if float(h.get("score", 0.0)) >= max(0.0, 0.15)]
    assert filtered == hits


def test_rag_query_default_min_score_keeps_everything(monkeypatch):
    """min_score default (0.0, quando o cliente não manda nada) não deve
    cortar nenhum hit, mesmo um com score 0.0 exato."""
    import api_server

    backend = MagicMock()
    backend.query_user_with_scores = MagicMock(return_value=list(_FAKE_HITS))
    monkeypatch.setattr(api_server, "kernel", _make_kernel_with_backend(backend))

    result = asyncio.run(api_server.rag_query(api_server.RagQueryReq(query="teste")))

    assert len(result["hits"]) == len(_FAKE_HITS)


def test_rag_query_negative_min_score_is_clamped_to_zero(monkeypatch):
    """`max(0.0, req.min_score)` protege contra um min_score negativo
    (bug de cliente, ou tentativa de bypass) virando "aceita tudo, inclusive
    score negativo" - o piso real continua sendo 0.0."""
    import api_server

    hits_with_negative = list(_FAKE_HITS) + [{"text": "score negativo (não deveria existir, mas não pode vazar)", "score": -0.5}]
    backend = MagicMock()
    backend.query_user_with_scores = MagicMock(return_value=hits_with_negative)
    monkeypatch.setattr(api_server, "kernel", _make_kernel_with_backend(backend))

    result = asyncio.run(api_server.rag_query(api_server.RagQueryReq(query="teste", min_score=-10.0)))

    scores = [h["score"] for h in result["hits"]]
    assert all(s >= 0.0 for s in scores), (
        f"min_score negativo não foi clampado pra 0.0 - hits com score negativo vazaram: {scores!r}"
    )
    assert -0.5 not in scores


def test_rag_query_empty_query_rejected_before_touching_backend(monkeypatch):
    import api_server
    from fastapi import HTTPException

    backend = MagicMock()
    backend.query_user_with_scores = MagicMock()
    monkeypatch.setattr(api_server, "kernel", _make_kernel_with_backend(backend))

    with pytest.raises(HTTPException) as exc_info:
        asyncio.run(api_server.rag_query(api_server.RagQueryReq(query="   ")))

    assert exc_info.value.status_code == 400
    backend.query_user_with_scores.assert_not_called()


def test_rag_query_backend_unavailable_returns_503(monkeypatch):
    import api_server

    monkeypatch.setattr(api_server, "kernel", _make_kernel_with_backend(None))

    with pytest.raises(Exception) as exc_info:
        asyncio.run(api_server.rag_query(api_server.RagQueryReq(query="teste")))

    assert getattr(exc_info.value, "status_code", None) == 503
