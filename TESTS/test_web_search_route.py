"""
Teste de regressão pra achado real do usuário (2026-08-24, screenshot):
digitou "pesquisar acidente com 2 helicópteros no rj em 2026" no chat
normal da Aviary, e o qwen3-8b respondeu direto da própria memória de
treino ("a data de 2026 ainda não chegou, não há registros") - sem NUNCA
buscar nada de verdade na internet.

Causa raiz (achada lendo o código real, não suposição): o Phoenix Engine
já tinha busca real via SearXNG funcionando
(phoenix_kernel/intelligence/web_search.py::search_web(), já usada de
verdade pelo /colaborar via resident_manager.py::run_dual_collab), mas
NENHUMA rota HTTP conectava esse recurso ao chat comum de um único modelo -
`grep -i searxng api_server.py` só achava menções em texto de status, zero
endpoint. Sem endpoint nenhum, o frontend (AviaryApp.tsx) não tinha como
acionar busca real - qualquer "pesquisar X" digitado virava só texto normal
pro LLM, que respondia (incorretamente) da própria memória de treino.

Este teste cobre a nova ponte: POST /api/web-search (api_server.py) chama
search_web() de verdade e nunca inventa sucesso quando a busca falha - erro
real do SearXNG vira HTTPException real (502), nunca um "ok: true" com
resultado vazio ou fabricado (mesma classe de bug já corrigida numa
auditoria anterior desta sessão nas rotas mock-fallback de server.ts).

Rodar com: pytest -q (de dentro de 'PHOENIX 3.0/')
"""
import asyncio
import sys
from pathlib import Path
from unittest.mock import patch

import pytest
from fastapi import HTTPException

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import api_server


async def _fake_search_ok(query: str, max_results: int = 3) -> str:
    return "- Título A: conteúdo relevante A\n- Título B: conteúdo relevante B"


async def _fake_search_no_results(query: str, max_results: int = 3) -> str:
    return "Nenhum resultado encontrado na web."


async def _fake_search_failure(query: str, max_results: int = 3) -> str:
    # Formato real devolvido por search_web() quando o SearXNG está
    # offline/inacessível - nunca levanta exceção, sempre retorna string
    # (ver phoenix_kernel/intelligence/web_search.py linha 39-41).
    return "Falha ao acessar a internet (SearXNG): [Errno 111] Connection refused"


def test_web_search_route_returns_real_results_on_success():
    with patch("phoenix_kernel.intelligence.web_search.search_web", new=_fake_search_ok):
        result = asyncio.run(
            api_server.web_search_route(api_server.WebSearchReq(query="acidente com 2 helicópteros no rj em 2026", max_results=5))
        )
    assert result["ok"] is True
    assert result["query"] == "acidente com 2 helicópteros no rj em 2026"
    assert "Título A" in result["results"]


def test_web_search_route_passes_through_no_results_as_success():
    # "Nenhum resultado encontrado" é uma resposta legítima da busca (só
    # não achou nada) - diferente de uma FALHA de infraestrutura. Não deve
    # virar erro HTTP.
    with patch("phoenix_kernel.intelligence.web_search.search_web", new=_fake_search_no_results):
        result = asyncio.run(api_server.web_search_route(api_server.WebSearchReq(query="algo bem obscuro", max_results=5)))
    assert result["ok"] is True
    assert "Nenhum resultado" in result["results"]


def test_web_search_route_surfaces_real_failure_as_http_error_never_fake_success():
    # Mesma classe de bug já corrigida nas 4 rotas mock-fallback de
    # server.ts numa auditoria anterior desta sessão: erro real de
    # infraestrutura (SearXNG offline) NUNCA pode virar "ok: true" com um
    # resultado vazio/fabricado - precisa estourar como erro real.
    with patch("phoenix_kernel.intelligence.web_search.search_web", new=_fake_search_failure):
        with pytest.raises(HTTPException) as exc_info:
            asyncio.run(api_server.web_search_route(api_server.WebSearchReq(query="teste", max_results=5)))
    assert exc_info.value.status_code == 502
    assert "SearXNG" in exc_info.value.detail


def test_web_search_route_rejects_empty_query_before_calling_search():
    with pytest.raises(HTTPException) as exc_info:
        asyncio.run(api_server.web_search_route(api_server.WebSearchReq(query="   ", max_results=5)))
    assert exc_info.value.status_code == 400
