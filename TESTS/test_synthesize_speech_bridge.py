"""
Teste de regressão pra auditoria 2026-08-20 ("ResidentManager não pode ser
contornado" — Seção 3 da diretiva de 20 seções), ATUALIZADO em 2026-08-23
pra refletir a troca do motor de voz padrão de Piper pra Kokoro-82M
(pedido do usuário: "kokoro será motor pra transformar texto em áudio,
assim como whisper é motor de áudio pra texto e piper lê texto que llm
cospe" - Kokoro substitui o Piper como motor de TODA a síntese de voz da
Phoenix, não só do audiolivro).

Achado original (2026-08-20): POST /api/synthesize-speech em api_server.py
montava seu próprio ExecutionPlan(runtime="piper", ...) e chamava
kernel.runtime.execute() DIRETO — pulando o ResidentManager por completo
(sem _thermal_guard, sem resolução de voz, sem _track_model_loaded). O
pior: ResidentManager.generate_speech_direct() já existia, pronto, com o
mesmo padrão de generate_image_direct/transcribe_direct — mas nada o
chamava, era código morto. Corrigido usando o bridge existente.

Mudança de 2026-08-23: generate_speech_direct() por dentro não usa mais
`self.runtime.execute()`/PiperDriver - chama
`kokoro_tts.get_kokoro_engine()` direto (mesmo padrão já usado por
generate_audiobook_direct()), com detecção automática de idioma
(phoenix_kernel/documents/audiobook.detect_language) quando `voice_hint`
vier vazio ou não reconhecido. A rota HTTP em si (api_server.py) NÃO
mudou - continua chamando generate_speech_direct(), então os testes de
nível 2 (a rota) seguem os mesmos, só com valores de fixture atualizados
pra refletir vozes Kokoro em vez de Piper.

Esta bateria cobre dois níveis, mesmo padrão de
tests/test_document_engine_bridge.py:
  1. ResidentManager.generate_speech_direct() isolado (thermal guard não
     impede, resolução de idioma/voz Kokoro, tracking do modelo ativo,
     propagação de erro, engine não instalado).
  2. api_server.synthesize_speech() (a rota HTTP) — prova que ela chama o
     bridge do Resident, não kernel.runtime.execute() direto.

Rodar com: pytest -q (de dentro de 'PHOENIX 3.0/')
"""
import asyncio
import base64
import sys
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from phoenix_kernel.resident.resident_manager import ResidentManager
from phoenix_kernel.models.registry import ModelRegistry


def _make_resident_for_speech_tests() -> ResidentManager:
    """Mesmo padrão de _make_resident_for_document_tests() em
    test_document_engine_bridge.py: ResidentManager real (registry real),
    runtime mockado (não é mais usado pela ponte de voz, mas outras pontes
    do mesmo objeto ainda podem precisar dele) — não sobe um Kokoro de
    verdade só pra testar a ponte."""
    resident = object.__new__(ResidentManager)
    resident.registry = ModelRegistry()
    resident.runtime = AsyncMock()
    resident.logs = AsyncMock()
    resident.logs.add_event = lambda *a, **k: None
    resident.ahde = None
    resident._active_models = {}
    return resident


def _fake_kokoro_engine(*, installed=True, voice="pf_dora", espeak="pt-br", samples=None, sample_rate=24000, raise_on_synthesize=None):
    """Constrói um substituto (não um mock genérico) do objeto devolvido
    por get_kokoro_engine() - só os métodos que generate_speech_direct()
    realmente chama (is_installed, resolve_voice, synthesize)."""
    import numpy as np

    engine = MagicMock()
    engine.is_installed.return_value = installed
    engine.resolve_voice.return_value = (voice, espeak)
    if raise_on_synthesize is not None:
        engine.synthesize.side_effect = raise_on_synthesize
    else:
        engine.synthesize.return_value = (samples if samples is not None else np.zeros(2400, dtype="float32"), sample_rate)
    return engine


# ---------------------------------------------------------------------
# 1. ResidentManager.generate_speech_direct() isolado (motor Kokoro)
# ---------------------------------------------------------------------

def test_generate_speech_direct_uses_kokoro_and_tracks_it(monkeypatch, tmp_path):
    resident = _make_resident_for_speech_tests()
    fake_engine = _fake_kokoro_engine(voice="pf_dora")

    monkeypatch.setattr(
        "phoenix_kernel.runtime.drivers.kokoro_tts.get_kokoro_engine",
        lambda: fake_engine,
    )
    # Texto longo o suficiente pra py3langid detectar com confiança - não é
    # mockado, é detecção real (mesmo princípio do resto desta auditoria:
    # só mocka a fronteira cara/com I/O real, o Kokoro; a detecção de
    # idioma é pura CPU e roda de verdade no teste).
    result = asyncio.run(resident.generate_speech_direct(
        "Olá, mundo! Este é um texto de teste em português para a síntese de voz.", "",
    ))

    assert result["ok"] is True
    assert result["voice"] == "pf_dora"
    assert result["path"].endswith(".wav")
    assert Path(result["path"]).exists(), "o WAV precisa ter sido escrito de verdade em disco"

    # engine.synthesize foi chamado com o idioma detectado (português) -
    # prova que a ponte passou pelo fluxo real de detecção, não um valor
    # fixo/hardcoded.
    fake_engine.synthesize.assert_called_once()
    called_text, called_lang = fake_engine.synthesize.call_args[0]
    assert called_lang == "pt"

    assert resident._active_models.get("kokoro") == "pf_dora"

    Path(result["path"]).unlink(missing_ok=True)


def test_generate_speech_direct_voice_hint_overrides_detection(monkeypatch):
    """Um voice_hint explícito (ID de voz OU código de idioma) tem
    prioridade sobre a detecção automática - o usuário escolheu manualmente
    no seletor da UI, a detecção não deve sobrepor essa escolha."""
    resident = _make_resident_for_speech_tests()
    fake_engine = _fake_kokoro_engine(voice="af_heart")
    monkeypatch.setattr(
        "phoenix_kernel.runtime.drivers.kokoro_tts.get_kokoro_engine",
        lambda: fake_engine,
    )

    # Texto em português, mas o usuário forçou a voz em inglês manualmente -
    # a detecção automática (que acharia "pt") não deve ser usada aqui.
    result = asyncio.run(resident.generate_speech_direct("Isto está em português.", "af_heart"))

    assert result["ok"] is True
    called_text, called_lang = fake_engine.synthesize.call_args[0]
    assert called_lang == "en", "voice_hint='af_heart' deveria resolver pra idioma 'en', não pro idioma detectado do texto"

    Path(result["path"]).unlink(missing_ok=True)


def test_generate_speech_direct_empty_text_fails_without_calling_engine(monkeypatch):
    resident = _make_resident_for_speech_tests()
    fake_engine = _fake_kokoro_engine()
    monkeypatch.setattr(
        "phoenix_kernel.runtime.drivers.kokoro_tts.get_kokoro_engine",
        lambda: fake_engine,
    )

    result = asyncio.run(resident.generate_speech_direct("   ", ""))

    assert result["ok"] is False
    assert "vazio" in result["error"].lower()
    fake_engine.synthesize.assert_not_called()


def test_generate_speech_direct_engine_not_installed_returns_honest_error(monkeypatch):
    resident = _make_resident_for_speech_tests()
    fake_engine = _fake_kokoro_engine(installed=False)
    monkeypatch.setattr(
        "phoenix_kernel.runtime.drivers.kokoro_tts.get_kokoro_engine",
        lambda: fake_engine,
    )

    result = asyncio.run(resident.generate_speech_direct("Olá.", ""))

    assert result["ok"] is False
    assert "kokoro" in result["error"].lower()
    assert "não está instalado" in result["error"].lower()
    # Modelo não instalado -> não tenta sintetizar nada (nem fabrica áudio).
    fake_engine.synthesize.assert_not_called()


def test_generate_speech_direct_synthesis_failure_propagates_real_error(monkeypatch):
    resident = _make_resident_for_speech_tests()
    fake_engine = _fake_kokoro_engine(raise_on_synthesize=RuntimeError("ONNXRuntimeError: sessão corrompida"))
    monkeypatch.setattr(
        "phoenix_kernel.runtime.drivers.kokoro_tts.get_kokoro_engine",
        lambda: fake_engine,
    )

    result = asyncio.run(resident.generate_speech_direct("Olá.", ""))

    assert result["ok"] is False
    assert "ONNXRuntimeError" in result["error"]


# ---------------------------------------------------------------------
# 2. Rota HTTP em api_server.py — precisa chamar generate_speech_direct,
#    nunca kernel.runtime.execute() direto (o bug original desta seção).
#    Estes testes mockam generate_speech_direct() na fronteira, então não
#    dependem de qual motor está por dentro - continuam válidos como estão,
#    só com valores de fixture atualizados pra vozes Kokoro.
# ---------------------------------------------------------------------

def test_synthesize_speech_route_calls_resident_not_runtime_execute_directly(tmp_path, monkeypatch):
    import api_server

    fake_resident = object.__new__(ResidentManager)
    fake_resident.generate_speech_direct = AsyncMock(return_value={
        "ok": True, "path": str(tmp_path / "audio.wav"), "voice": "pf_dora",
    })
    (tmp_path / "audio.wav").write_bytes(b"RIFF....WAVEfake")
    monkeypatch.setattr(api_server, "kernel", type("K", (), {"resident": fake_resident})())

    with patch("api_server.kernel.runtime", create=True) as fake_runtime_execute:
        req = api_server.SynthesizeSpeechReq(text="Bom dia.", voice="")
        result = asyncio.run(api_server.synthesize_speech(req))

    assert result["ok"] is True
    fake_resident.generate_speech_direct.assert_awaited_once_with("Bom dia.", "")
    fake_runtime_execute.execute.assert_not_called()


def test_synthesize_speech_route_empty_text_422_without_calling_resident(monkeypatch):
    import api_server
    from fastapi import HTTPException

    fake_resident = object.__new__(ResidentManager)
    fake_resident.generate_speech_direct = AsyncMock()
    monkeypatch.setattr(api_server, "kernel", type("K", (), {"resident": fake_resident})())

    with pytest.raises(HTTPException) as exc_info:
        req = api_server.SynthesizeSpeechReq(text="   ", voice="")
        asyncio.run(api_server.synthesize_speech(req))

    assert exc_info.value.status_code == 422
    fake_resident.generate_speech_direct.assert_not_called()


def test_synthesize_speech_route_surfaces_resident_error_as_422(monkeypatch):
    import api_server
    from fastapi import HTTPException

    fake_resident = object.__new__(ResidentManager)
    fake_resident.generate_speech_direct = AsyncMock(return_value={
        "ok": False, "error": "Modelo de voz neural Kokoro não está instalado no disco.",
    })
    monkeypatch.setattr(api_server, "kernel", type("K", (), {"resident": fake_resident})())

    with pytest.raises(HTTPException) as exc_info:
        req = api_server.SynthesizeSpeechReq(text="Oi.", voice="")
        asyncio.run(api_server.synthesize_speech(req))

    assert exc_info.value.status_code == 422
    assert exc_info.value.detail == "Modelo de voz neural Kokoro não está instalado no disco."


def test_synthesize_speech_route_missing_resident_returns_503(monkeypatch):
    import api_server

    monkeypatch.setattr(api_server, "kernel", type("K", (), {"resident": None})())

    from fastapi import HTTPException
    with pytest.raises(HTTPException) as exc_info:
        req = api_server.SynthesizeSpeechReq(text="Oi.", voice="")
        asyncio.run(api_server.synthesize_speech(req))

    assert exc_info.value.status_code == 503


def test_synthesize_speech_route_success_returns_base64_audio(tmp_path, monkeypatch):
    import api_server

    audio_bytes = b"RIFF1234WAVEfmt fake audio payload"
    audio_path = tmp_path / "saida.wav"
    audio_path.write_bytes(audio_bytes)

    fake_resident = object.__new__(ResidentManager)
    fake_resident.generate_speech_direct = AsyncMock(return_value={
        "ok": True, "path": str(audio_path), "voice": "pf_dora",
    })
    monkeypatch.setattr(api_server, "kernel", type("K", (), {"resident": fake_resident})())

    req = api_server.SynthesizeSpeechReq(text="Teste de áudio.", voice="")
    result = asyncio.run(api_server.synthesize_speech(req))

    assert result["ok"] is True
    assert result["mime_type"] == "audio/wav"
    assert result["voice"] == "pf_dora"
    assert base64.b64decode(result["audio_base64"]) == audio_bytes


def test_synthesize_speech_route_missing_output_file_returns_500(tmp_path, monkeypatch):
    import api_server
    from fastapi import HTTPException

    fake_resident = object.__new__(ResidentManager)
    fake_resident.generate_speech_direct = AsyncMock(return_value={
        "ok": True, "path": str(tmp_path / "nao-existe.wav"), "voice": "pf_dora",
    })
    monkeypatch.setattr(api_server, "kernel", type("K", (), {"resident": fake_resident})())

    with pytest.raises(HTTPException) as exc_info:
        req = api_server.SynthesizeSpeechReq(text="Oi.", voice="")
        asyncio.run(api_server.synthesize_speech(req))

    assert exc_info.value.status_code == 500
