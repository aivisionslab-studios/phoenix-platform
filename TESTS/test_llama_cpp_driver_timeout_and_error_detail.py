# TESTS/test_llama_cpp_driver_timeout_and_error_detail.py
#
# PHX-NEW (achado real do usuário 2026-08-28: "Erro na inferência do
# llama.cpp:" aparecendo no chat SEM NADA depois dos dois-pontos, usando
# o recurso novo fill_spreadsheet_template_direct).
#
# Rastreamento feito com o usuário: a string vazia atravessa intacta
# api_server.py -> ResidentManager.fill_spreadsheet_template_direct ->
# LlamaCppDriver.execute() -> exceção capturada em `except Exception as
# exc: ... f"...{str(exc)}"`. Exceções de timeout do httpx
# (ReadTimeout/ConnectTimeout/PoolTimeout) costumam ter str(exc) VAZIO -
# é exatamente isso que produz a mensagem em branco.
#
# Causa raiz encontrada: o timeout HTTP do driver é calculado só por
# NOME do modelo + max_tokens de saída (linha ~330) - um modelo "8b" (não
# é "modelo grande") com max_tokens padrão (1024) sempre cai no piso de
# 600s, mesmo fill_spreadsheet_template_direct já orçando até 1200s
# (DOCUMENT_CREATE_TIMEOUT_MEDIUM_SECONDS) pra si mesmo. Numa máquina
# rodando o modelo majoritariamente em CPU, mapear um documento inteiro
# pras colunas de um template pode passar de 600s sem ser "grande" nem
# pedir muitos tokens de SAÍDA (o prompt de ENTRADA que é grande).
#
# Corrigido: (1) quem chama execute() pode declarar
# parameters["timeout_seconds"] pra elevar o piso calculado (nunca
# reduzir); (2) o `except Exception` nunca mais devolve uma mensagem
# vazia - inclui pelo menos type(exc).__name__, com uma nota específica
# apontando timeout/conexão perdida quando a biblioteca não dá detalhe
# nenhum.
#
# Testes com httpx.AsyncClient mockado (não sobe um llama-server de
# verdade) - o objetivo aqui é comportamento do DRIVER em si (parsing de
# resposta, tratamento de exceção, cálculo de timeout), não uma inferência
# real.
#
# Rodar com: pytest -q (de dentro de 'PHOENIX 3.0/')

import sys
from pathlib import Path
from unittest.mock import AsyncMock, patch

import httpx
import pytest

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from core.domain.execution import ExecutionPlan, ExecutionStatus  # noqa: E402
from phoenix_kernel.runtime.drivers.llama_cpp import LlamaCppDriver  # noqa: E402


def _make_driver() -> LlamaCppDriver:
    driver = LlamaCppDriver()
    driver._model_path = Path("qwen3-8b-q4_k_m.gguf")
    return driver


class _FakeAsyncClient:
    """Substitui httpx.AsyncClient - simula tanto o timeout vazio real
    quanto uma resposta OK, e registra o `timeout=` recebido pra a
    verificação do cálculo de _http_timeout."""

    captured_timeouts: list[float] = []

    def __init__(self, timeout=None, **kwargs):
        self.timeout = timeout
        _FakeAsyncClient.captured_timeouts.append(timeout)

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc_info):
        return False

    async def post(self, *args, **kwargs):
        raise httpx.ReadTimeout("")  # PHX: mensagem vazia de propósito - reproduz o achado real


@pytest.fixture(autouse=True)
def _reset_captured_timeouts():
    _FakeAsyncClient.captured_timeouts = []
    yield


@pytest.mark.asyncio
async def test_empty_exception_message_still_produces_useful_error(monkeypatch):
    """O achado original: a exceção de timeout do httpx tem str() vazio -
    a mensagem final NUNCA pode terminar em branco depois dos
    dois-pontos, e precisa pelo menos citar o tipo da exceção."""
    driver = _make_driver()
    monkeypatch.setattr(driver, "_check_health", AsyncMock(return_value=True))

    with patch("phoenix_kernel.runtime.drivers.llama_cpp.httpx.AsyncClient", _FakeAsyncClient):
        plan = ExecutionPlan(runtime="llama.cpp", model="qwen3:8b", parameters={"user_prompt": "oi"})
        result = await driver.execute(plan)

    assert result.status == ExecutionStatus.FAILED
    assert result.errors
    msg = result.errors[0]
    assert msg.strip() != "Erro na inferência do llama.cpp:", (
        "a mensagem não pode voltar vazia - foi exatamente isso que apareceu na tela do usuário"
    )
    assert "ReadTimeout" in msg, f"esperava o tipo da exceção na mensagem, veio: {msg!r}"


@pytest.mark.asyncio
async def test_small_model_default_timeout_is_600s_without_override():
    """Confirma o piso de 600s pra modelo pequeno/max_tokens padrão -
    comportamento antigo, preservado quando ninguém pede mais tempo."""
    driver = _make_driver()
    driver._check_health = AsyncMock(return_value=True)

    with patch("phoenix_kernel.runtime.drivers.llama_cpp.httpx.AsyncClient", _FakeAsyncClient):
        plan = ExecutionPlan(runtime="llama.cpp", model="qwen3:8b", parameters={"user_prompt": "oi"})
        await driver.execute(plan)

    assert _FakeAsyncClient.captured_timeouts == [600.0]


@pytest.mark.asyncio
async def test_timeout_seconds_param_raises_the_http_timeout():
    """PHX-FIX: fill_spreadsheet_template_direct (e qualquer chamador
    futuro) pode pedir mais tempo via parameters["timeout_seconds"] -
    isso precisa realmente chegar no timeout do httpx.AsyncClient."""
    driver = _make_driver()
    driver._check_health = AsyncMock(return_value=True)

    with patch("phoenix_kernel.runtime.drivers.llama_cpp.httpx.AsyncClient", _FakeAsyncClient):
        plan = ExecutionPlan(
            runtime="llama.cpp", model="qwen3:8b",
            parameters={"user_prompt": "oi", "timeout_seconds": 1140},
        )
        await driver.execute(plan)

    assert _FakeAsyncClient.captured_timeouts == [1140.0]


@pytest.mark.asyncio
async def test_timeout_seconds_never_reduces_the_heuristic_floor():
    """timeout_seconds só pode AUMENTAR o timeout calculado pela
    heurística - um valor menor que o piso (ex: alguém passando 30s por
    engano) não pode encurtar o timeout de um modelo grande."""
    driver = _make_driver()
    driver._check_health = AsyncMock(return_value=True)

    with patch("phoenix_kernel.runtime.drivers.llama_cpp.httpx.AsyncClient", _FakeAsyncClient):
        plan = ExecutionPlan(
            runtime="llama.cpp", model="qwen3:12b",
            parameters={"user_prompt": "oi", "max_tokens": 4096, "timeout_seconds": 30},
        )
        await driver.execute(plan)

    # PHX-FIX (pedido explícito do usuário 2026-08-28, testando Gemma 4
    # 12B com relatório longo via pesquisa web + PDF): piso de modelo
    # grande subiu de 1740.0s (29min) pra 3540.0s (59min) - llama-server
    # não faz streaming, então um documento longo num modelo 12b+ rodando
    # em CPU pode legitimamente passar dos 29min antigos sem travar. 30s
    # continua não podendo reduzir isso.
    assert _FakeAsyncClient.captured_timeouts == [3540.0]


def test_fill_spreadsheet_template_direct_passes_timeout_seconds_to_plan():
    """Garante que resident_manager.py realmente repassa um orçamento
    real pro driver nesse fluxo específico - sem isso, os testes acima
    provam que o mecanismo FUNCIONA, mas não que ele é USADO onde
    importa. Verificação estática do código-fonte real (mesmo padrão de
    test_llama_server_context_size.py), não uma execução completa do
    método (que exigiria um RuntimeEngine/ResidentManager inteiros).

    PHX-FIX (achado real do usuário 2026-08-28, verificando os "30
    minutos" espalhados pelo código depois do fix de chunking): o
    orçamento passado deixou de ser sempre DOCUMENT_CREATE_TIMEOUT_
    MEDIUM_SECONDS fixo - agora escala com o tamanho do modelo (variável
    _chunk_document_timeout, mesma lógica que create_document_direct já
    usava) pra não repetir, dentro desta função, o mesmo descompasso que
    o driver (llama_cpp.py) já documentava pra modelos grandes. Ver
    TESTS/test_fill_spreadsheet_template_chunking.py pros testes de
    comportamento real (modelo pequeno continua em 1140s; modelo 12b+
    passa a usar 1740s)."""
    src = (PROJECT_ROOT / "phoenix_kernel" / "resident" / "resident_manager.py").read_text(encoding="utf-8")
    assert "_chunk_document_timeout - 60" in src, (
        'esperava parameters={"timeout_seconds": _chunk_document_timeout - 60, ...} '
        "dentro de fill_spreadsheet_template_direct"
    )

    # Confirma que está DENTRO do método certo, não em outro lugar do arquivo.
    method_start = src.index("async def fill_spreadsheet_template_direct")
    method_end = src.index("\n    async def ", method_start + 10)
    method_body = src[method_start:method_end]
    assert "timeout_seconds" in method_body, (
        "_chunk_document_timeout - 60 existe no arquivo, mas não dentro de "
        "fill_spreadsheet_template_direct"
    )
    assert "_chunk_document_timeout = (" in method_body, (
        "esperava o cálculo de _chunk_document_timeout (LARGE se modelo 12b+, senão MEDIUM) "
        "dentro do próprio método, igual create_document_direct já faz"
    )
    assert "DOCUMENT_CREATE_TIMEOUT_LARGE_SECONDS" in method_body, (
        "fill_spreadsheet_template_direct precisa considerar o teto LARGE (30min) pra "
        "modelos grandes, não só o MEDIUM (20min) fixo de antes desta correção"
    )
