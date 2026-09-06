"""Testes do OCREngine (Tesseract) contra o binário REAL — não mockado.
Requer tesseract instalado com o idioma 'eng' (padrão em qualquer install).
"""
import asyncio
import shutil

import pytest

from phoenix_kernel.services.ocr_engine import OCREngine, DEFAULT_OCR_LANG

pytestmark = pytest.mark.skipif(
    shutil.which("tesseract") is None, reason="tesseract não instalado neste ambiente"
)


def _make_test_image(tmp_path, texto: str = "TESTE OCR 12345"):
    from PIL import Image, ImageDraw
    img = Image.new("RGB", (400, 80), color="white")
    d = ImageDraw.Draw(img)
    d.text((10, 25), texto, fill="black")
    caminho = tmp_path / "teste.png"
    img.save(caminho)
    return caminho


def test_extract_text_with_confidence_real_tesseract(tmp_path):
    caminho = _make_test_image(tmp_path, "12345")
    engine = OCREngine()
    result = asyncio.run(engine.extract_text_with_confidence(str(caminho), lang="eng"))
    assert result["ok"] is True
    assert "12345" in result["text"]
    assert result["confidence"] is not None
    assert 0 <= result["confidence"] <= 100


def test_missing_language_pack_fails_cleanly(tmp_path):
    """Achado real: pedir um idioma não instalado (comum pra 'por' em
    ambiente sem o pacote de português) falha com erro claro, nunca
    silenciosamente com resultado vazio ou lixo."""
    caminho = _make_test_image(tmp_path)
    engine = OCREngine()
    result = asyncio.run(engine.extract_text_with_confidence(str(caminho), lang="idioma_que_nao_existe_xyz"))
    assert result["ok"] is False
    assert result["error"]
    assert result["confidence"] is None


def test_nonexistent_image_file():
    engine = OCREngine()
    result = asyncio.run(engine.extract_text_with_confidence("/caminho/que/nao/existe.png"))
    assert result["ok"] is False
    assert "não encontrado" in result["error"].lower()


def test_default_language_constant_is_portuguese_plus_english():
    assert DEFAULT_OCR_LANG == "por+eng"


def test_parse_tsv_ignores_non_word_levels():
    """Linhas de nível 1-4 (página/bloco/parágrafo/linha) têm conf=-1 e
    não têm texto de palavra - só o nível 5 conta."""
    tsv_falso = (
        "level\tpage_num\tblock_num\tpar_num\tline_num\tword_num\tleft\ttop\twidth\theight\tconf\ttext\n"
        "1\t1\t0\t0\t0\t0\t0\t0\t100\t100\t-1\t\n"
        "5\t1\t1\t1\t1\t1\t10\t10\t30\t10\t88.5\tOla\n"
        "5\t1\t1\t1\t1\t2\t45\t10\t30\t10\t91.2\tmundo\n"
    )
    texto, confianca = OCREngine._parse_tsv(tsv_falso)
    assert texto == "Ola mundo"
    assert confianca == pytest.approx((88.5 + 91.2) / 2)


def test_parse_tsv_empty_result_returns_none_confidence():
    tsv_vazio = "level\tpage_num\tblock_num\tpar_num\tline_num\tword_num\tleft\ttop\twidth\theight\tconf\ttext\n"
    texto, confianca = OCREngine._parse_tsv(tsv_vazio)
    assert texto == ""
    assert confianca is None
