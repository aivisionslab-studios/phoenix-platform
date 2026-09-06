"""Testes: hybrid_ocr_direct — Tesseract primeiro, MiniCPM-V como segunda
opinião só quando necessário.

Por quê os dois: Tesseract é determinístico e reporta confiança REAL por
palavra (não é estimativa nossa - vem do próprio motor LSTM); MiniCPM-V é
mais robusto a foto ruim (ângulo, luz), mas pode ALUCINAR - inventar texto
plausível que não está na imagem, com a MESMA confiança aparente de
quando acerta. A ordem importa: nunca ao contrário.
"""
import asyncio
import tempfile
from pathlib import Path
from unittest.mock import AsyncMock, patch

from phoenix_kernel.resident.resident_manager import ResidentManager


def _make_temp_image() -> Path:
    tmp = Path(tempfile.mkdtemp()) / "foto.png"
    tmp.write_bytes(b"fake")
    return tmp


class _FakeResident:
    """Sujeito sob teste: só o hybrid_ocr_direct real, com ocr_image_direct
    (MiniCPM-V) mockado e OCREngine (Tesseract) interceptado via patch."""
    hybrid_ocr_direct = ResidentManager.hybrid_ocr_direct

    def __init__(self, minicpmv_result):
        self._minicpmv_result = minicpmv_result
        self.logs = type("L", (), {"add_event": lambda *a, **k: None})()

    async def ocr_image_direct(self, image_path, model_hint=""):
        return self._minicpmv_result


def _patch_tesseract(tess_result: dict):
    return patch(
        "phoenix_kernel.services.ocr_engine.OCREngine.extract_text_with_confidence",
        new=AsyncMock(return_value=tess_result),
    )


def test_high_confidence_tesseract_used_directly_no_fallback():
    """Confiança alta do Tesseract -> nunca chama o MiniCPM-V (mais lento,
    gasta VRAM à toa)."""
    tmp = _make_temp_image()
    resident = _FakeResident(minicpmv_result={"ok": True, "text": "NUNCA DEVERIA SER USADO"})
    with _patch_tesseract({"ok": True, "text": "NOTA FISCAL 12345", "confidence": 92.0, "error": None}):
        result = asyncio.run(resident.hybrid_ocr_direct(str(tmp)))
    assert result["ok"] is True
    assert result["source"] == "tesseract"
    assert result["text"] == "NOTA FISCAL 12345"
    assert result["fallback_reason"] is None
    assert result["confidence"] == 92.0


def test_low_confidence_falls_back_to_minicpmv():
    """Confiança baixa (foto ruim, ângulo) -> escala pra segunda opinião,
    com o motivo registrado (nunca silencioso)."""
    tmp = _make_temp_image()
    resident = _FakeResident(minicpmv_result={"ok": True, "text": "texto corrigido pela visão", "model": "minicpmv"})
    with _patch_tesseract({"ok": True, "text": "t3xt0 ru1m", "confidence": 35.0, "error": None}):
        result = asyncio.run(resident.hybrid_ocr_direct(str(tmp), min_confidence=70.0))
    assert result["ok"] is True
    assert result["source"] == "minicpmv"
    assert result["text"] == "texto corrigido pela visão"
    assert "confiança do Tesseract abaixo do limite" in result["fallback_reason"]
    assert result["tesseract_confidence"] == 35.0


def test_missing_language_pack_falls_back_to_minicpmv():
    """Idioma ausente (ex.: 'por' não instalado) é uma FALHA do Tesseract,
    não um resultado - trata como motivo de segunda opinião."""
    tmp = _make_temp_image()
    resident = _FakeResident(minicpmv_result={"ok": True, "text": "leu certo mesmo assim"})
    with _patch_tesseract({"ok": False, "text": "", "confidence": None, "error": "Failed loading language 'por'"}):
        result = asyncio.run(resident.hybrid_ocr_direct(str(tmp)))
    assert result["ok"] is True
    assert result["source"] == "minicpmv"
    assert "Tesseract falhou" in result["fallback_reason"]
    assert "por" in result["fallback_reason"]


def test_empty_tesseract_result_falls_back_to_minicpmv():
    """Tesseract roda sem erro mas não reconhece nenhuma palavra (imagem
    difícil, letra manuscrita) -> também escala pra segunda opinião."""
    tmp = _make_temp_image()
    resident = _FakeResident(minicpmv_result={"ok": True, "text": "achei o texto"})
    with _patch_tesseract({"ok": True, "text": "", "confidence": None, "error": None}):
        result = asyncio.run(resident.hybrid_ocr_direct(str(tmp)))
    assert result["ok"] is True
    assert result["source"] == "minicpmv"
    assert "não reconheceu nenhum texto" in result["fallback_reason"]


def test_both_sources_fail_reports_final_error_and_both_reasons():
    """Tesseract E MiniCPM-V falham -> erro final claro, mas o motivo do
    Tesseract fica registrado mesmo assim (auditável)."""
    tmp = _make_temp_image()
    resident = _FakeResident(minicpmv_result={"ok": False, "error": "GPU indisponível."})
    with _patch_tesseract({"ok": False, "text": "", "confidence": None, "error": "timeout"}):
        result = asyncio.run(resident.hybrid_ocr_direct(str(tmp)))
    assert result["ok"] is False
    assert result["error"] == "GPU indisponível."
    assert "timeout" in result["fallback_reason"]


def test_default_language_is_portuguese_plus_english():
    """A ligação usa por+eng por padrão (contexto do projeto é documento
    comercial brasileiro) - confere que o parâmetro é passado pro
    OCREngine, não fica no valor default genérico do tesseract (eng)."""
    tmp = _make_temp_image()
    resident = _FakeResident(minicpmv_result={"ok": True, "text": "x"})
    captured = {}

    async def _fake_tess(self, image_path, lang="por+eng"):
        captured["lang"] = lang
        return {"ok": True, "text": "ok", "confidence": 95.0, "error": None}

    with patch("phoenix_kernel.services.ocr_engine.OCREngine.extract_text_with_confidence", new=_fake_tess):
        asyncio.run(resident.hybrid_ocr_direct(str(tmp)))
    assert captured["lang"] == "por+eng"
