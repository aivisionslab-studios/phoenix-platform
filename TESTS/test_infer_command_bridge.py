"""
Teste de regressão pra auditoria 2026-08-20 ("ResidentManager não pode ser
contornado" — Seção 3 da diretiva de 20 seções). Este é o achado mais
grave da rodada: o comando `infer <prompt>` (ApiEngine.process_command(),
acionado por POST /api/command — o caminho de inferência de texto crua,
fora do chat da Aviary) montava o ExecutionPlan certo via RuleEvaluator,
mas EXECUTAVA com `self.runtime.execute(plan)` DIRETO dentro do próprio
ApiEngine — pulando o ResidentManager por completo (sem _thermal_guard,
sem _track_model_loaded), o único dos 8 itens da Seção 3 que ainda
bypassava o Resident depois dos fixes de imagem/voz/visão/benchmark desta
mesma rodada.

Dois níveis, mesmo padrão das outras baterias desta rodada:
  1. ResidentManager.run_inference_direct(plan) isolado.
  2. ApiEngine.process_command("infer ...") — prova que chama o bridge do
     Resident, não self.runtime.execute() direto.

Rodar com: pytest -q (de dentro de 'PHOENIX 3.0/')
"""
import asyncio
import sys
from pathlib import Path
from unittest.mock import AsyncMock

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from core.domain.execution import ExecutionPlan, ExecutionResult, ExecutionStatus
from core.domain.machine import MachineContext
from phoenix_kernel.resident.resident_manager import ResidentManager
from phoenix_kernel.models.registry import ModelRegistry
from phoenix_kernel.api.engine import ApiEngine


def _make_resident_for_inference_tests() -> ResidentManager:
    resident = object.__new__(ResidentManager)
    resident.registry = ModelRegistry()
    resident.runtime = AsyncMock()
    resident.logs = AsyncMock()
    resident.logs.add_event = lambda *a, **k: None
    resident.ahde = None
    resident._active_models = {}
    return resident


# ---------------------------------------------------------------------
# 1. ResidentManager.run_inference_direct() isolado
# ---------------------------------------------------------------------

def test_run_inference_direct_tracks_model_and_returns_execution_result():
    resident = _make_resident_for_inference_tests()
    resident.runtime.execute = AsyncMock(return_value=ExecutionResult(
        plan_id="p1", status=ExecutionStatus.SUCCESS, output="Resposta do modelo.",
    ))
    plan = ExecutionPlan(runtime="llama.cpp", model="qwen3:8b", parameters={"user_prompt": "oi"})

    result = asyncio.run(resident.run_inference_direct(plan))

    assert isinstance(result, ExecutionResult)
    assert result.status == ExecutionStatus.SUCCESS
    assert result.output == "Resposta do modelo."
    resident.runtime.execute.assert_awaited_once_with(plan)
    # Rastreado como Hot-Swap ativo - o que self.runtime.execute() direto
    # (jeito antigo, dentro do ApiEngine) nunca fazia.
    assert resident._active_models.get("llama.cpp") == "qwen3:8b"


def test_run_inference_direct_does_not_track_model_on_failure():
    resident = _make_resident_for_inference_tests()
    resident.runtime.execute = AsyncMock(return_value=ExecutionResult(
        plan_id="p1", status=ExecutionStatus.FAILED, errors=["LlamaCppDriver: falhou."],
    ))
    plan = ExecutionPlan(runtime="llama.cpp", model="qwen3:8b", parameters={"user_prompt": "oi"})

    result = asyncio.run(resident.run_inference_direct(plan))

    assert result.status == ExecutionStatus.FAILED
    assert "llama.cpp" not in resident._active_models


def test_run_inference_direct_no_runtime_raises_clean_error():
    resident = _make_resident_for_inference_tests()
    resident.runtime = None
    plan = ExecutionPlan(runtime="llama.cpp", model="qwen3:8b", parameters={})

    with pytest.raises(RuntimeError, match="RuntimeEngine"):
        asyncio.run(resident.run_inference_direct(plan))


# ---------------------------------------------------------------------
# 2. ApiEngine.process_command("infer ...") — precisa chamar
#    resident.run_inference_direct(), nunca self.runtime.execute() direto.
# ---------------------------------------------------------------------

def _make_api_engine(resident, planner, runtime_execute_mock):
    """Constrói um ApiEngine real (a lógica de roteamento de comando que
    queremos testar) com todo o resto mockado - self.runtime aqui é o
    RuntimeEngine cru que o bug original chamava direto; precisamos dele
    presente (mas nunca chamado) pra provar que o fix parou de usá-lo."""
    fake_runtime = type("FakeRuntime", (), {"execute": runtime_execute_mock})()
    return ApiEngine(
        state_engine=None, models_engine=None, planner_engine=planner,
        runtime_engine=fake_runtime, services_engine=None, logs_engine=AsyncMock(),
        validation_engine=None, security_engine=None, resident_manager=resident,
    )


def test_infer_command_calls_resident_bridge_not_runtime_execute_directly():
    resident = _make_resident_for_inference_tests()
    resident.get_text_engine_preference = lambda: {"engine": "llama.cpp"}
    resident.run_inference_direct = AsyncMock(return_value=ExecutionResult(
        plan_id="p1", status=ExecutionStatus.SUCCESS, output="Phoenix Engine operacional.",
    ))

    plan = ExecutionPlan(runtime="llama.cpp", model="qwen3:8b", parameters={"user_prompt": "diga oi"})
    fake_planner = type("FakePlanner", (), {"plan_inference": AsyncMock(return_value=plan)})()
    runtime_execute_mock = AsyncMock()  # self.runtime.execute() do ApiEngine - não pode ser chamado

    api = _make_api_engine(resident, fake_planner, runtime_execute_mock)
    api.machine_context = MachineContext(profile=None)

    result = asyncio.run(api.process_command("infer diga oi"))

    assert "Phoenix Engine operacional." in result["output"]
    assert "qwen3:8b" in result["output"]
    resident.run_inference_direct.assert_awaited_once_with(plan)
    runtime_execute_mock.assert_not_called()


def test_infer_command_surfaces_bridge_failure_as_error_output():
    resident = _make_resident_for_inference_tests()
    resident.get_text_engine_preference = lambda: {"engine": "llama.cpp"}
    resident.run_inference_direct = AsyncMock(return_value=ExecutionResult(
        plan_id="p1", status=ExecutionStatus.FAILED, errors=["LlamaCppDriver: servidor não respondeu."],
    ))

    plan = ExecutionPlan(runtime="llama.cpp", model="qwen3:8b", parameters={"user_prompt": "oi"})
    fake_planner = type("FakePlanner", (), {"plan_inference": AsyncMock(return_value=plan)})()
    api = _make_api_engine(resident, fake_planner, AsyncMock())
    api.machine_context = MachineContext(profile=None)

    result = asyncio.run(api.process_command("infer oi"))

    assert "[ERRO]" in result["output"]
    assert "LlamaCppDriver" in result["output"]


def test_infer_command_without_resident_returns_error_without_crashing():
    fake_planner = type("FakePlanner", (), {"plan_inference": AsyncMock(
        return_value=ExecutionPlan(runtime="llama.cpp", model="qwen3:8b", parameters={}))})()
    api = _make_api_engine(None, fake_planner, AsyncMock())
    api.machine_context = MachineContext(profile=None)

    result = asyncio.run(api.process_command("infer oi"))

    assert "[ERRO]" in result["output"]
    assert "ResidentManager" in result["output"]
