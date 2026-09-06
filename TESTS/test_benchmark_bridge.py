"""
Teste de regressão pra auditoria 2026-08-20 ("ResidentManager não pode ser
contornado" — Seção 3 da diretiva de 20 seções).

Achado: POST /api/benchmark em api_server.py montava o próprio
ExecutionPlan (resolvendo o modelo via resident.registry.resolve("chat")
só pra citar no plan) e chamava kernel.runtime.execute() DIRETO - mesmo
anti-padrão já corrigido pra imagem/voz/visão nesta mesma rodada. Trocado
pro bridge dedicado resident.run_token_benchmark_direct().

Nota: isto NÃO cobre a Seção 11 (benchmark não pode fabricar número) -
essa auditoria já estava OK antes desta rodada (a rota só devolve
tokensPerSec/tokensGenerated/durationMs vindos de verdade de
ExecutionResult.metrics, nunca um valor fixo) e continua OK depois. O
achado aqui é só a topologia de chamada (API -> ResidentManager -> Runtime).

Rodar com: pytest -q (de dentro de 'PHOENIX 3.0/')
"""
import asyncio
import sys
from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from core.domain.execution import ExecutionResult, ExecutionStatus
from phoenix_kernel.resident.resident_manager import ResidentManager
from phoenix_kernel.models.registry import ModelRegistry


def _make_resident_for_benchmark_tests() -> ResidentManager:
    resident = object.__new__(ResidentManager)
    resident.registry = ModelRegistry()
    resident.runtime = AsyncMock()
    resident.logs = AsyncMock()
    resident.logs.add_event = lambda *a, **k: None
    resident.ahde = None
    resident._active_models = {}
    return resident


# ---------------------------------------------------------------------
# 1. ResidentManager.run_token_benchmark_direct() isolado
# ---------------------------------------------------------------------

def test_run_token_benchmark_direct_uses_resolved_chat_model_and_tracks_it():
    resident = _make_resident_for_benchmark_tests()
    resident.runtime.execute = AsyncMock(return_value=ExecutionResult(
        plan_id="p1", status=ExecutionStatus.SUCCESS, output="Phoenix Engine operacional. 1 2 3 4 5.",
        metrics={"tokens_per_second": 12.5, "tokens_generated": 20, "duration_ms": 1600},
    ))

    result = asyncio.run(resident.run_token_benchmark_direct())

    assert result["ok"] is True
    resolved = resident.registry.resolve("chat")
    assert result["runtime"] == resolved.runtime
    assert result["model"] == resolved.id
    assert result["metrics"]["tokens_per_second"] == 12.5

    sent_plan = resident.runtime.execute.call_args[0][0]
    assert sent_plan.runtime == resolved.runtime
    assert sent_plan.model == resolved.id
    assert resident._active_models.get(resolved.runtime) == resolved.id


def test_run_token_benchmark_direct_never_fabricates_metrics_on_failure():
    resident = _make_resident_for_benchmark_tests()
    resident.runtime.execute = AsyncMock(return_value=ExecutionResult(
        plan_id="p1", status=ExecutionStatus.FAILED, errors=["LlamaCppDriver: servidor não respondeu."],
    ))

    result = asyncio.run(resident.run_token_benchmark_direct())

    assert result["ok"] is False
    assert "LlamaCppDriver" in result["error"]
    # Nenhum campo de métrica fabricado quando a execução falha de verdade.
    assert "metrics" not in result


# ---------------------------------------------------------------------
# 2. Teto próprio de timeout (auditoria 2026-08-21, "corrigir tudo"):
#    antes desta rodada, `run_token_benchmark_direct()` chamava
#    `self.runtime.execute(plan)` sem nenhum teto próprio - só o timeout
#    interno de cada driver (600s) limitava, bem acima dos 60s que
#    `platform_source/server.ts` esperava antes de abortar a conexão.
#    Comportamento real, de ponta a ponta (não só leitura de fonte -
#    ver tests/test_proxy_backend_timeout_alignment.py pra essa parte).
# ---------------------------------------------------------------------

def test_run_token_benchmark_direct_times_out_with_controlled_error_instead_of_hanging():
    from phoenix_kernel.resident import resident_manager as resident_manager_module

    resident = _make_resident_for_benchmark_tests()

    async def _never_finishes(plan):
        # Simula um cold start/inferência travada que nunca retorna - sem
        # o teto próprio, isto pendura o coroutine indefinidamente.
        await asyncio.sleep(3600)

    resident.runtime.execute = _never_finishes

    # Isola o teste do valor real de BENCHMARK_EXECUTE_TIMEOUT_SECONDS
    # (300s) - não queremos que o teste em si demore 5 minutos pra rodar.
    original_timeout = resident_manager_module.BENCHMARK_EXECUTE_TIMEOUT_SECONDS
    resident_manager_module.BENCHMARK_EXECUTE_TIMEOUT_SECONDS = 0.05
    try:
        # Rede de segurança do próprio teste: se o guard interno não
        # existisse (regressão), isto travaria - o wait_for externo com
        # timeout generoso garante que o teste falha rápido em vez de
        # pendurar o pytest inteiro.
        result = asyncio.run(asyncio.wait_for(resident.run_token_benchmark_direct(), timeout=5))
    finally:
        resident_manager_module.BENCHMARK_EXECUTE_TIMEOUT_SECONDS = original_timeout

    assert result["ok"] is False
    assert "benchmark" in result["error"].lower()
    assert "cold start" in result["error"].lower()


def test_run_token_benchmark_direct_no_runtime_fails_cleanly():
    resident = _make_resident_for_benchmark_tests()
    resident.runtime = None

    result = asyncio.run(resident.run_token_benchmark_direct())

    assert result["ok"] is False
    assert "RuntimeEngine" in result["error"]


# ---------------------------------------------------------------------
# 2. Rota HTTP em api_server.py — precisa chamar run_token_benchmark_direct,
#    nunca kernel.runtime.execute() direto (o bug original desta seção).
# ---------------------------------------------------------------------

def test_benchmark_route_calls_resident_not_runtime_execute_directly(monkeypatch):
    import api_server

    fake_resident = object.__new__(ResidentManager)
    fake_resident.run_token_benchmark_direct = AsyncMock(return_value={
        "ok": True, "runtime": "llama.cpp", "model": "qwen3:8b",
        "metrics": {"tokens_per_second": 8.3, "tokens_generated": 15, "duration_ms": 1800},
    })
    monkeypatch.setattr(api_server, "kernel", type("K", (), {"resident": fake_resident})())

    with patch("api_server.kernel.runtime", create=True) as fake_runtime_execute:
        result = asyncio.run(api_server.run_benchmark())

    assert result["ok"] is True
    assert result["results"]["tokensPerSec"] == 8.3
    assert result["results"]["status"] == "MEASURED"
    fake_resident.run_token_benchmark_direct.assert_awaited_once()
    fake_runtime_execute.execute.assert_not_called()


def test_benchmark_route_surfaces_resident_error_as_502(monkeypatch):
    import api_server
    from fastapi import HTTPException

    fake_resident = object.__new__(ResidentManager)
    fake_resident.run_token_benchmark_direct = AsyncMock(return_value={
        "ok": False, "error": "LlamaCppDriver: servidor não respondeu.",
    })
    monkeypatch.setattr(api_server, "kernel", type("K", (), {"resident": fake_resident})())

    with pytest.raises(HTTPException) as exc_info:
        asyncio.run(api_server.run_benchmark())

    assert exc_info.value.status_code == 502
    assert exc_info.value.detail == "LlamaCppDriver: servidor não respondeu."


def test_benchmark_route_missing_resident_returns_503(monkeypatch):
    import api_server
    from fastapi import HTTPException

    monkeypatch.setattr(api_server, "kernel", type("K", (), {"resident": None})())

    with pytest.raises(HTTPException) as exc_info:
        asyncio.run(api_server.run_benchmark())

    assert exc_info.value.status_code == 503
