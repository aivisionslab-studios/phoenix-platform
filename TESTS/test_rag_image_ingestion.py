"""Testes: ingestão de RAG com imagem solta (foto/print de documento) via
OCR híbrido (Tesseract primeiro, MiniCPM-V como segunda opinião) — achado
real: o pedido original do usuário (22/08, "habilitar todas as funções do
OCR pra qualquer função") tinha sido restringido só a PDF escaneado;
imagem nunca chegou a ser ligada ao fluxo de RAG (só existia via
/api/describe-image?mode=ocr, uma rota de chat).
"""
import asyncio
import tempfile
from pathlib import Path

import pytest

from phoenix_kernel.resident.resident_manager import ResidentManager, RAG_IMAGE_EXTENSIONS


def _make_temp_file(nome: str) -> Path:
    tmp = Path(tempfile.mkdtemp()) / nome
    tmp.write_bytes(b"conteudo-fake")
    return tmp


def test_image_extensions_include_common_formats():
    assert {".png", ".jpg", ".jpeg", ".webp", ".bmp", ".tiff"} <= RAG_IMAGE_EXTENSIONS


def test_image_file_routes_to_hybrid_ocr_not_document_engine():
    """PNG/JPG nunca deve tentar passar pelo extrator de pdf/docx/etc —
    vai direto pro OCR híbrido (Tesseract + MiniCPM-V)."""
    class FakeResident:
        extract_document_full_text_direct = ResidentManager.extract_document_full_text_direct
        chamado_com = None

        async def hybrid_ocr_direct(self, image_path, **kwargs):
            FakeResident.chamado_com = image_path
            return {"ok": True, "text": "NOTA FISCAL Nº 12345", "source": "tesseract"}

    async def rodar():
        tmp = _make_temp_file("foto_nota.png")
        r = FakeResident()
        result = await r.extract_document_full_text_direct(str(tmp), "foto_nota.png")
        assert result["ok"] is True
        assert result["ocr_used"] is True
        assert result["text"] == "NOTA FISCAL Nº 12345"
        assert FakeResident.chamado_com == str(tmp.resolve())

    asyncio.run(rodar())


def test_image_without_visible_text_returns_clear_error():
    class FakeResident:
        extract_document_full_text_direct = ResidentManager.extract_document_full_text_direct
        async def hybrid_ocr_direct(self, image_path, **kwargs):
            return {"ok": True, "text": "(nenhum texto encontrado)", "source": "minicpmv"}

    async def rodar():
        tmp = _make_temp_file("foto_sem_texto.jpg")
        r = FakeResident()
        result = await r.extract_document_full_text_direct(str(tmp), "foto_sem_texto.jpg")
        assert result["ok"] is False
        assert "nenhum texto" in result["error"].lower() or "Nenhum texto" in result["error"]

    asyncio.run(rodar())


def test_hybrid_ocr_failure_propagates_clear_error():
    """Falha das duas fontes de OCR (Tesseract e MiniCPM-V) vira erro claro
    pro usuário — nunca uma exceção não tratada."""
    class FakeResident:
        extract_document_full_text_direct = ResidentManager.extract_document_full_text_direct
        async def hybrid_ocr_direct(self, image_path, **kwargs):
            return {"ok": False, "error": "Modelo de visão indisponível."}

    async def rodar():
        tmp = _make_temp_file("foto.png")
        r = FakeResident()
        result = await r.extract_document_full_text_direct(str(tmp), "foto.png")
        assert result["ok"] is False
        assert result["error"] == "Modelo de visão indisponível."

    asyncio.run(rodar())


def test_non_image_extensions_unaffected():
    """Regressão: .txt/.pdf/.docx continuam pelo caminho normal, nunca
    tentam chamar o OCR de imagem."""
    class FakeResident:
        extract_document_full_text_direct = ResidentManager.extract_document_full_text_direct
        async def hybrid_ocr_direct(self, image_path, **kwargs):
            raise AssertionError("não deveria ser chamado para .txt")

    async def rodar():
        tmp = Path(tempfile.mkdtemp()) / "arquivo.txt"
        tmp.write_text("conteúdo normal", encoding="utf-8")
        r = FakeResident()
        result = await r.extract_document_full_text_direct(str(tmp), "arquivo.txt")
        assert result["ok"] is True
        assert result["text"] == "conteúdo normal"
        assert result["ocr_used"] is False

    asyncio.run(rodar())
