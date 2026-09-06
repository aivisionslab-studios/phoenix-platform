"""
Teste de regressão pra auditoria 2026-08-20 ("ResidentManager não pode ser
contornado" — Seção 3 da diretiva de 20 seções).

Achado: POST /api/describe-image em api_server.py resolvia o modelo de
visão via resident.registry.resolve("vision") só pra citar no
ExecutionPlan, mas executava com kernel.runtime.execute() DIRETO -
pulando _thermal_guard e _vram_guard. Sem passar pelo Resident, essas
guardas nunca rodavam de verdade nesse caminho.

PHX-FIX (2026-08-28): na época deste achado (2026-08-20), "vision" ainda
fazia parte de GPU_HEAVY_RUNTIMES em resident_manager.py e o catálogo
declarava vram_mb_estimate=6500 pro minicpmv - ficou desatualizado quando
o driver de visão passou a forçar -ngl 0 (CPU) por política definitiva de
roteamento de hardware (GPU 100% reservada pra geração de imagem). Hoje
"vision" é CPU, igual chat (vram_mb_estimate=0) - o teste abaixo que
checava "vram_mb > 0" foi corrigido pra refletir isso; o ponto que
continua validado é que _vram_guard é CHAMADO com o runtime/modelo certos
(defesa em profundidade, mesmo virando no-op com vram=0 hoje).

Mesmo padrão de teste de tests/test_document_engine_bridge.py e
tests/test_synthesize_speech_bridge.py: nível 1 = bridge do Resident
isolado, nível 2 = rota HTTP provando que chama o bridge, não
kernel.runtime.execute() direto.

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


class _FakeUploadFile:
    def __init__(self, filename: str, data: bytes):
        self.filename = filename
        import io
        self.file = io.BytesIO(data)


def _make_resident_for_vision_tests() -> ResidentManager:
    resident = object.__new__(ResidentManager)
    resident.registry = ModelRegistry()
    resident.runtime = AsyncMock()
    resident.logs = AsyncMock()
    resident.logs.add_event = lambda *a, **k: None
    resident.ahde = None
    resident._active_models = {}
    return resident


# ---------------------------------------------------------------------
# 1. ResidentManager.describe_image_direct() isolado
# ---------------------------------------------------------------------

def test_describe_image_direct_uses_resolved_model_and_tracks_it(tmp_path):
    resident = _make_resident_for_vision_tests()
    img_path = tmp_path / "foto.png"
    img_path.write_bytes(b"\x89PNG\r\n\x1a\nfake")

    resident.runtime.execute = AsyncMock(return_value=ExecutionResult(
        plan_id="p1", status=ExecutionStatus.SUCCESS, output="Uma foto de um gato laranja.",
    ))

    result = asyncio.run(resident.describe_image_direct(str(img_path), "Descreva esta imagem"))

    assert result["ok"] is True
    assert result["text"] == "Uma foto de um gato laranja."
    assert result["model"] == "minicpmv"

    sent_plan = resident.runtime.execute.call_args[0][0]
    resolved = resident.registry.resolve("vision")
    assert sent_plan.runtime == resolved.runtime
    assert sent_plan.model == resolved.id
    assert sent_plan.parameters["image_path"] == str(img_path)
    assert sent_plan.parameters["prompt"] == "Descreva esta imagem"
    # Rastreado como Hot-Swap ativo - o que kernel.runtime.execute() direto
    # (jeito antigo) nunca fazia.
    assert resident._active_models.get(resolved.runtime) == resolved.id


def test_describe_image_direct_missing_file_fails_without_calling_runtime(tmp_path):
    resident = _make_resident_for_vision_tests()
    resident.runtime.execute = AsyncMock()

    result = asyncio.run(resident.describe_image_direct(str(tmp_path / "nao-existe.png"), "Descreva"))

    assert result["ok"] is False
    assert "não encontrado" in result["error"]
    resident.runtime.execute.assert_not_called()


def test_describe_image_direct_empty_path_fails_without_calling_runtime():
    resident = _make_resident_for_vision_tests()
    resident.runtime.execute = AsyncMock()

    result = asyncio.run(resident.describe_image_direct("   ", "Descreva"))

    assert result["ok"] is False
    assert "vazio" in result["error"].lower()
    resident.runtime.execute.assert_not_called()


def test_describe_image_direct_calls_vram_guard_with_correct_runtime_and_model(tmp_path, monkeypatch):
    """_vram_guard precisa ser chamado com o runtime/modelo de visão
    resolvidos, por consistência com generate_image_direct (defesa em
    profundidade caso o driver ganhe offload de GPU no futuro).

    PHX-FIX (2026-08-28): este teste chegou a exigir vram_mb > 0 ("vision"
    era GPU-heavy no catálogo antigo). Hoje o driver de visão força -ngl 0
    (CPU) por política definitiva de roteamento de hardware, e
    catalog/models.json reflete isso com vram_mb_estimate=0 pro minicpmv -
    a chamada ao guard agora é um no-op esperado, igual chat."""
    resident = _make_resident_for_vision_tests()
    img_path = tmp_path / "foto.png"
    img_path.write_bytes(b"fake")

    resident.runtime.execute = AsyncMock(return_value=ExecutionResult(
        plan_id="p1", status=ExecutionStatus.SUCCESS, output="descrição",
    ))
    vram_guard_calls = []

    async def _fake_vram_guard(context, target_runtime, target_model_id, vram_mb_needed):
        vram_guard_calls.append((target_runtime, target_model_id, vram_mb_needed))

    monkeypatch.setattr(resident, "_vram_guard", _fake_vram_guard)

    asyncio.run(resident.describe_image_direct(str(img_path), "Descreva"))

    assert len(vram_guard_calls) == 1
    runtime, model_id, vram_mb = vram_guard_calls[0]
    assert runtime == "vision"
    assert model_id == "minicpmv"
    assert vram_mb == 0  # CPU-only (-ngl 0) - vision não compete mais por VRAM com sdxl


def test_real_vram_guard_does_not_unload_image_model_for_vision(tmp_path):
    """Regressão fim a fim do bug real (2026-08-28): com o _vram_guard de
    VERDADE (não mockado) e um modelo de imagem já rastreado como ativo,
    descrever uma imagem NÃO pode descarregar esse modelo - antes da
    correção, o catálogo dizia que 'vision' precisava de ~6500MB de VRAM,
    o guard achava que não cabia e descarregava 'sdxl' à toa, mesmo a
    análise de imagem nunca tocando a GPU de verdade (-ngl 0 fixo)."""
    resident = _make_resident_for_vision_tests()
    img_path = tmp_path / "foto.png"
    img_path.write_bytes(b"fake")

    resident.runtime.execute = AsyncMock(return_value=ExecutionResult(
        plan_id="p1", status=ExecutionStatus.SUCCESS, output="descrição",
    ))
    resident.runtime.stop = AsyncMock()
    # Simula um modelo de imagem já carregado, ocupando VRAM de verdade.
    resident._active_models = {"sdxl": "flux"}
    # Sem AHDE injetado, _vram_guard normalmente sairia cedo de qualquer
    # forma (linha "AHDE não injetado") - o ponto deste teste é que ele
    # nem CHEGA a essa checagem porque vram_mb_needed já é 0 pra vision.

    asyncio.run(resident.describe_image_direct(str(img_path), "Descreva"))

    resident.runtime.stop.assert_not_called()
    # 'sdxl' continua rastreado como ativo - só 'vision' foi adicionado
    # (describe_image_direct também rastreia o próprio modelo de visão
    # carregado, o que é esperado e não tem relação com este bug).
    assert resident._active_models.get("sdxl") == "flux"


def test_describe_image_direct_runtime_failure_propagates_real_error(tmp_path):
    resident = _make_resident_for_vision_tests()
    img_path = tmp_path / "foto.png"
    img_path.write_bytes(b"fake")

    resident.runtime.execute = AsyncMock(return_value=ExecutionResult(
        plan_id="p1", status=ExecutionStatus.FAILED, errors=["VisionDriver: modelo não encontrado no disco."],
    ))

    result = asyncio.run(resident.describe_image_direct(str(img_path), "Descreva"))

    assert result["ok"] is False
    assert "VisionDriver" in result["error"]


# ---------------------------------------------------------------------
# 2. Rota HTTP em api_server.py — precisa chamar describe_image_direct,
#    nunca kernel.runtime.execute() direto (o bug original desta seção).
# ---------------------------------------------------------------------

def test_describe_image_route_calls_resident_not_runtime_execute_directly(tmp_path, monkeypatch):
    import api_server

    fake_resident = object.__new__(ResidentManager)
    fake_resident.describe_image_direct = AsyncMock(return_value={"ok": True, "text": "uma paisagem", "model": "minicpmv"})
    monkeypatch.setattr(api_server, "kernel", type("K", (), {"resident": fake_resident})())
    monkeypatch.chdir(tmp_path)

    # PHX-FIX (auditoria completa 2026-08-28): a rota ganhou um parâmetro
    # `mode: str = Form("describe")` (PHX-NEW 2026-08-22, suporte a OCR) que
    # não existia quando este teste foi escrito. Chamar a função da rota
    # DIRETO em Python (contornando o ciclo de request do FastAPI, que é
    # quem resolve `Form(...)` pro texto de verdade) deixava `mode` com o
    # valor cru `Form("describe")` (um marcador do FastAPI, não uma string) -
    # `(mode or "").strip()` dentro da rota then quebrava com
    # `'Form' object has no attribute 'strip'`. Numa requisição HTTP real
    # isso nunca acontece; aqui basta passar `mode` explicitamente, como já
    # se faz com `prompt`.
    with patch("api_server.kernel.runtime", create=True) as fake_runtime_execute:
        result = asyncio.run(api_server.describe_image(file=_FakeUploadFile("foto.png", b"fakepng"), prompt="Descreva esta imagem", mode="describe"))

    assert result == {"text": "uma paisagem"}
    fake_resident.describe_image_direct.assert_awaited_once()
    call_args = fake_resident.describe_image_direct.call_args
    assert call_args[0][1] == "Descreva esta imagem"
    fake_runtime_execute.execute.assert_not_called()


def test_describe_image_route_surfaces_resident_error(tmp_path, monkeypatch):
    import api_server

    fake_resident = object.__new__(ResidentManager)
    fake_resident.describe_image_direct = AsyncMock(return_value={"ok": False, "error": "Modelo de visão não instalado."})
    monkeypatch.setattr(api_server, "kernel", type("K", (), {"resident": fake_resident})())
    monkeypatch.chdir(tmp_path)

    result = asyncio.run(api_server.describe_image(file=_FakeUploadFile("foto.png", b"fakepng"), prompt="Descreva", mode="describe"))

    assert result == {"error": "Modelo de visão não instalado."}


def test_describe_image_route_missing_resident_returns_error(tmp_path, monkeypatch):
    import api_server

    monkeypatch.setattr(api_server, "kernel", type("K", (), {"resident": None})())
    monkeypatch.chdir(tmp_path)

    result = asyncio.run(api_server.describe_image(file=_FakeUploadFile("foto.png", b"fakepng"), prompt="Descreva"))

    assert result == {"error": "ResidentManager não encontrado."}


def test_describe_image_route_cleans_temp_file_even_on_error(tmp_path, monkeypatch):
    import api_server

    fake_resident = object.__new__(ResidentManager)
    fake_resident.describe_image_direct = AsyncMock(side_effect=RuntimeError("boom"))
    monkeypatch.setattr(api_server, "kernel", type("K", (), {"resident": fake_resident})())
    monkeypatch.chdir(tmp_path)

    # PHX-FIX (auditoria completa 2026-08-28): sem `mode="describe"` aqui, a
    # rota quebrava ANTES de chamar describe_image_direct (no `mode.strip()`
    # da checagem OCR - ver PHX-FIX acima) - o teste ainda "passava" (a
    # asserção só checa `"error" in result` e a limpeza do temp, sem
    # verificar a mensagem), mas de fato nunca exercitava o `side_effect`
    # RuntimeError("boom") configurado acima. Passando mode explicitamente,
    # o teste volta a testar o que diz testar.
    result = asyncio.run(api_server.describe_image(file=_FakeUploadFile("foto.png", b"fakepng"), prompt="Descreva", mode="describe"))

    assert "error" in result
    # temp/vision/ não pode acumular lixo mesmo quando a ponte explode.
    leftover = list((tmp_path / "temp" / "vision").glob("*"))
    assert leftover == []
