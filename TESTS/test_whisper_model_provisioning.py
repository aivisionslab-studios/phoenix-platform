"""
Teste de regressão pra auditoria 2026-08-20 ("Whisper model provisioning").

Achado real, confirmado numa instalação de produção (log real anexado pelo
usuário): whisper.cpp compilava certinho (common.ps1 clona e builda),
/api/transcribe existia e funcionava - mas NADA no provisionamento baixava
o modelo STT (ggml-base.bin). Toda transcrição falhava com "Nenhum modelo
Whisper encontrado em <workspace>/Models/Audio/" até o usuário baixar
manualmente na mão e descobrir isso por tentativa e erro.

Três correções, três blocos de teste:
  1. ModelManager.download_model() agora valida tamanho > 0 bytes (cache-hit
     E pós-download) - antes um arquivo de 0 bytes (download interrompido)
     virava "cache válido" pra sempre.
  2. catalog/downloads.json ganhou a entrada "whisper-base" (URL real do
     ggml-base.bin), resolvendo destino via PhoenixPaths (destination_folder
     "Audio" -> mesma pasta que WhisperDriver._find_model() já procurava).
  3. Kernel._ensure_default_stt_model() dispara esse download em background
     no boot, mesmo padrão não-bloqueante de _ensure_default_model() (LLM).
  4. WhisperDriver.execute() não mostra mais "B:/Phoenix/..." hardcoded no
     erro - mostra o caminho REAL resolvido por PhoenixPaths nesta máquina.

Rodar com: pytest -q (de dentro de 'PHOENIX 3.0/')
"""
import asyncio
import json
import sys
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from phoenix_kernel.models.model_manager import ModelManager
from phoenix_kernel.runtime.drivers.whisper import WhisperDriver
from core.domain.execution import ExecutionPlan, ExecutionStatus


# ---------------------------------------------------------------------
# 1. catalog/downloads.json - entrada whisper-base existe e está correta
# ---------------------------------------------------------------------

def test_downloads_catalog_has_whisper_base_entry():
    catalog_path = Path(__file__).resolve().parent.parent / "catalog" / "downloads.json"
    catalog = json.loads(catalog_path.read_text(encoding="utf-8"))

    assert "whisper-base" in catalog
    entry = catalog["whisper-base"]
    assert entry["filename"] == "ggml-base.bin"
    assert entry["destination_folder"] == "Audio"
    assert entry["url"].startswith("https://")
    assert "ggml-base.bin" in entry["url"]


# ---------------------------------------------------------------------
# 2. ModelManager.download_model() - resolve via PhoenixPaths, usa .part,
#    valida tamanho > 0 (cache-hit e pós-download).
# ---------------------------------------------------------------------

class _FakeStreamResponse:
    def __init__(self, chunks, status_ok=True):
        self._chunks = chunks
        self._status_ok = status_ok

    def raise_for_status(self):
        if not self._status_ok:
            raise RuntimeError("HTTP error simulado")

    async def aiter_bytes(self):
        for c in self._chunks:
            yield c

    async def __aenter__(self):
        return self

    async def __aexit__(self, *a):
        return False


class _FakeAsyncClient:
    def __init__(self, chunks):
        self._chunks = chunks

    def stream(self, method, url, timeout=None):
        return _FakeStreamResponse(self._chunks)

    async def __aenter__(self):
        return self

    async def __aexit__(self, *a):
        return False


def _make_manager_with_workspace(tmp_path, monkeypatch):
    mm = ModelManager()
    monkeypatch.setattr(
        "phoenix_kernel.models.model_manager.PhoenixPaths.get_models_base",
        lambda: tmp_path / "Models",
    )
    # Catálogo isolado, apontando só pra entrada que o teste quer.
    catalog_path = tmp_path / "downloads.json"
    mm.catalog_path = catalog_path
    return mm, catalog_path


def test_download_model_whisper_base_downloads_via_part_and_validates_size(tmp_path, monkeypatch):
    mm, catalog_path = _make_manager_with_workspace(tmp_path, monkeypatch)
    catalog_path.write_text(json.dumps({
        "whisper-base": {
            "name": "Whisper ggml-base (STT)",
            "url": "https://huggingface.co/ggerganov/whisper.cpp/resolve/main/ggml-base.bin",
            "destination_folder": "Audio",
            "filename": "ggml-base.bin",
        }
    }), encoding="utf-8")

    fake_client = _FakeAsyncClient(chunks=[b"RIFF", b"fake-whisper-model-bytes"])
    with patch("phoenix_kernel.models.model_manager.httpx.AsyncClient", return_value=fake_client):
        result_path = asyncio.run(mm.download_model("whisper-base"))

    assert result_path is not None
    assert result_path.name == "ggml-base.bin"
    assert result_path.parent.name == "Audio"
    assert result_path.exists()
    assert result_path.read_bytes() == b"RIFFfake-whisper-model-bytes"
    # .part não pode sobrar depois de um download bem-sucedido.
    assert not result_path.with_suffix(".bin.part").exists()


def test_download_model_rejects_empty_response_and_leaves_no_partial_file(tmp_path, monkeypatch):
    mm, catalog_path = _make_manager_with_workspace(tmp_path, monkeypatch)
    catalog_path.write_text(json.dumps({
        "whisper-base": {
            "url": "https://example.invalid/ggml-base.bin",
            "destination_folder": "Audio",
            "filename": "ggml-base.bin",
        }
    }), encoding="utf-8")

    fake_client = _FakeAsyncClient(chunks=[])  # corpo vazio - servidor "sucesso" mas 0 bytes
    with patch("phoenix_kernel.models.model_manager.httpx.AsyncClient", return_value=fake_client):
        result_path = asyncio.run(mm.download_model("whisper-base"))

    assert result_path is None
    dest_dir = tmp_path / "Models" / "Audio"
    leftover = list(dest_dir.glob("*")) if dest_dir.exists() else []
    assert leftover == [], f"não pode sobrar arquivo (nem .part) de um download vazio: {leftover}"


def test_download_model_treats_existing_zero_byte_file_as_invalid_cache(tmp_path, monkeypatch):
    mm, catalog_path = _make_manager_with_workspace(tmp_path, monkeypatch)
    catalog_path.write_text(json.dumps({
        "whisper-base": {
            "url": "https://huggingface.co/ggerganov/whisper.cpp/resolve/main/ggml-base.bin",
            "destination_folder": "Audio",
            "filename": "ggml-base.bin",
        }
    }), encoding="utf-8")

    # Simula um resíduo de rodada anterior: arquivo "existe" mas tem 0 bytes.
    dest_dir = tmp_path / "Models" / "Audio"
    dest_dir.mkdir(parents=True)
    (dest_dir / "ggml-base.bin").write_bytes(b"")

    fake_client = _FakeAsyncClient(chunks=[b"conteudo-real-desta-vez"])
    with patch("phoenix_kernel.models.model_manager.httpx.AsyncClient", return_value=fake_client):
        result_path = asyncio.run(mm.download_model("whisper-base"))

    assert result_path is not None
    assert result_path.read_bytes() == b"conteudo-real-desta-vez"


def test_download_model_reuses_valid_nonzero_cache_without_re_downloading(tmp_path, monkeypatch):
    mm, catalog_path = _make_manager_with_workspace(tmp_path, monkeypatch)
    catalog_path.write_text(json.dumps({
        "whisper-base": {
            "url": "https://huggingface.co/ggerganov/whisper.cpp/resolve/main/ggml-base.bin",
            "destination_folder": "Audio",
            "filename": "ggml-base.bin",
        }
    }), encoding="utf-8")

    dest_dir = tmp_path / "Models" / "Audio"
    dest_dir.mkdir(parents=True)
    (dest_dir / "ggml-base.bin").write_bytes(b"modelo ja baixado, 20+ bytes de conteudo real")

    with patch("phoenix_kernel.models.model_manager.httpx.AsyncClient") as client_cls:
        result_path = asyncio.run(mm.download_model("whisper-base"))
        client_cls.assert_not_called()  # cache válido -> nenhuma tentativa de rede

    assert result_path is not None
    assert result_path.read_bytes() == b"modelo ja baixado, 20+ bytes de conteudo real"


# ---------------------------------------------------------------------
# 3. Kernel._ensure_default_stt_model() - boot não-bloqueante
# ---------------------------------------------------------------------

def _make_kernel_stub():
    from phoenix_kernel.kernel import PhoenixKernel
    kernel = object.__new__(PhoenixKernel)
    kernel.logs = MagicMock()
    kernel.logs.add_event = lambda *a, **k: None
    return kernel


def test_ensure_default_stt_model_returns_true_when_valid_file_present(tmp_path, monkeypatch):
    kernel = _make_kernel_stub()
    audio_dir = tmp_path / "Audio"
    audio_dir.mkdir(parents=True)
    (audio_dir / "ggml-base.bin").write_bytes(b"x" * 100_000_001)  # acima do minimo (~100MB)

    monkeypatch.setattr(
        "phoenix_kernel.paths.PhoenixPaths.get_category_path",
        lambda category, subcategory=None: audio_dir if category == "Audio" else Path("/nao-usado"),
    )

    ready = asyncio.run(kernel._ensure_default_stt_model())

    assert ready is True


def test_ensure_default_stt_model_triggers_background_download_when_missing(tmp_path, monkeypatch):
    kernel = _make_kernel_stub()
    audio_dir = tmp_path / "Audio"  # não existe ainda

    monkeypatch.setattr(
        "phoenix_kernel.paths.PhoenixPaths.get_category_path",
        lambda category, subcategory=None: audio_dir if category == "Audio" else Path("/nao-usado"),
    )

    created_tasks = []

    def _fake_create_task(coro):
        created_tasks.append(coro)
        coro.close()  # evita "coroutine was never awaited" - só queremos provar que foi disparado
        return MagicMock()

    with patch("phoenix_kernel.kernel.asyncio.create_task", side_effect=_fake_create_task):
        ready = asyncio.run(kernel._ensure_default_stt_model())

    assert ready is False
    assert len(created_tasks) == 1


def test_ensure_default_stt_model_redownloads_corrupted_small_file(tmp_path, monkeypatch):
    kernel = _make_kernel_stub()
    audio_dir = tmp_path / "Audio"
    audio_dir.mkdir(parents=True)
    corrupted = audio_dir / "ggml-base.bin"
    corrupted.write_bytes(b"x" * 1000)  # bem abaixo do minimo esperado

    monkeypatch.setattr(
        "phoenix_kernel.paths.PhoenixPaths.get_category_path",
        lambda category, subcategory=None: audio_dir if category == "Audio" else Path("/nao-usado"),
    )

    def _fake_create_task(coro):
        coro.close()
        return MagicMock()

    with patch("phoenix_kernel.kernel.asyncio.create_task", side_effect=_fake_create_task):
        ready = asyncio.run(kernel._ensure_default_stt_model())

    assert ready is False
    assert not corrupted.exists()  # arquivo corrompido foi removido, não deixado pra confundir


# ---------------------------------------------------------------------
# 4. WhisperDriver - erro mostra caminho REAL (não "B:/Phoenix/..." fixo)
# ---------------------------------------------------------------------

def test_whisper_driver_missing_model_error_shows_real_resolved_path(tmp_path, monkeypatch):
    driver = WhisperDriver()
    monkeypatch.setattr(driver, "_find_executable", lambda: "/usr/bin/whisper-cli")
    monkeypatch.setattr(driver, "_find_model", lambda: None)

    fake_audio_dir = tmp_path / "MeuWorkspaceCustomizado" / "Models" / "Audio"
    monkeypatch.setattr(
        "phoenix_kernel.runtime.drivers.whisper.PhoenixPaths.get_category_path",
        lambda category, subcategory=None: fake_audio_dir,
    )

    plan = ExecutionPlan(runtime="whisper", model="whisper-base", parameters={"audio_path": "audio.wav"})
    result = asyncio.run(driver.execute(plan))

    assert result.status == ExecutionStatus.FAILED
    error_text = result.errors[0]
    assert "MeuWorkspaceCustomizado" in error_text  # caminho real, não hardcoded
    assert "B:/Phoenix" not in error_text
    assert "ggml-base.bin" in error_text  # comando de reparo pronto pra colar


def test_whisper_driver_present_model_proceeds_past_the_model_check(tmp_path, monkeypatch):
    driver = WhisperDriver()
    monkeypatch.setattr(driver, "_find_executable", lambda: "/usr/bin/whisper-cli")
    fake_model = tmp_path / "ggml-base.bin"
    fake_model.write_bytes(b"x" * 1000)
    monkeypatch.setattr(driver, "_find_model", lambda: fake_model)

    # Sem audio_path -> deve falhar DEPOIS do check de modelo, não antes
    # (prova que o modelo foi considerado presente e o fluxo avançou).
    plan = ExecutionPlan(runtime="whisper", model="whisper-base", parameters={})
    result = asyncio.run(driver.execute(plan))

    assert result.status == ExecutionStatus.FAILED
    assert "audio_path" in result.errors[0]
    assert "Nenhum modelo Whisper" not in result.errors[0]
