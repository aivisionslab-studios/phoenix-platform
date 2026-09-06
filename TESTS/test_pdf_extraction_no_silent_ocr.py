"""
Teste de regressão pra auditoria 2026-08-20, "existem falhas e fallbacks -
rastrear e tirar tudo" (achado real, vindo de log de produção real do
usuário, não de leitura de código): `/api/documents/read` travava no
timeout de 240s do `[DirectDocumentBridge]` (`resident_manager.py`) e
devolvia 422 pra pelo menos dois PDFs reais - e o log mostrava, sob um
cabeçalho `=== Document parser messages ===`, as linhas "Using Tesseract
for OCR processing." e "OCR on page.number=2/3.".

Isso contradizia diretamente a mensagem de erro que `_extract_pdf()` já
lançava há muito tempo ("esta versão da Document Engine não faz OCR") -
uma auditoria anterior (leitura de código) tinha confirmado essa mensagem
como verdadeira, mas o log de produção provou o contrário.

Root cause (confirmado lendo o pacote `pymupdf4llm` REALMENTE instalado,
1.28.2, e reproduzindo localmente): esta versão tem uma "layout engine"
nova, ativa por padrão porque a dependência `pymupdf_layout` está
instalada (`pymupdf4llm/__init__.py:_use_layout`), cujo `to_markdown()`
tem `use_ocr=OCRMode.SELECT_KEEP_OLD` como default IMPLÍCITO - ou seja,
qualquer página "sem texto suficiente" (típico de PDF escaneado) dispara
OCR de verdade via Tesseract, silenciosamente, sem timeout próprio e sem
que `phoenix_kernel/documents/engine.py` jamais tenha pedido isso.

`_extract_pdf()` agora passa `use_ocr=OCRMode.NEVER` explicitamente, o que
restaura o comportamento prometido pela mensagem de erro: extração rápida
e determinística, só do layer de texto nativo.

Rodar com: pytest -q (de dentro de 'PHOENIX 3.0/')
"""
import sys
import time
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from phoenix_kernel.documents.engine import _extract_pdf, DocumentEngineError

pymupdf = pytest.importorskip("pymupdf", reason="PyMuPDF não instalado neste ambiente de teste")
pytest.importorskip("pymupdf4llm", reason="pymupdf4llm não instalado neste ambiente de teste")


def _make_text_pdf(path: Path) -> None:
    doc = pymupdf.open()
    page = doc.new_page()
    page.insert_text((72, 72), "Conteudo real de texto nativo da Phoenix Document Engine.")
    doc.save(str(path))
    doc.close()


def _make_textless_pdf(path: Path) -> None:
    """PDF sem NENHUM texto (só um retângulo desenhado) - o mesmo tipo de
    página que a layout engine do pymupdf4llm classifica como "precisa de
    OCR" (needs_ocr=True) e que disparava Tesseract silenciosamente antes
    do fix."""
    doc = pymupdf.open()
    page = doc.new_page()
    page.draw_rect(pymupdf.Rect(50, 50, 500, 700), fill=(0.9, 0.9, 0.9))
    doc.save(str(path))
    doc.close()


def test_normal_pdf_still_extracts_native_text_correctly(tmp_path):
    pdf_path = tmp_path / "texto.pdf"
    _make_text_pdf(pdf_path)

    text = _extract_pdf(pdf_path)
    assert "Conteudo real de texto nativo" in text


def test_textless_pdf_fails_fast_with_clear_error_instead_of_silent_ocr(tmp_path):
    pdf_path = tmp_path / "sem_texto.pdf"
    _make_textless_pdf(pdf_path)

    t0 = time.monotonic()
    with pytest.raises(DocumentEngineError) as exc_info:
        _extract_pdf(pdf_path)
    elapsed = time.monotonic() - t0

    assert "não faz OCR" in str(exc_info.value)
    # OCR via Tesseract (rendering por página + subprocess) é MUITO mais
    # lento que isto - um teto generoso de 10s garante que não regredimos
    # pro comportamento antigo (que só terminava, se terminasse, depois de
    # gerar imagem de cada página e rodar tesseract nela).
    assert elapsed < 10.0, (
        f"extração de PDF sem texto levou {elapsed:.2f}s - suspeita de OCR "
        "silencioso tendo voltado a rodar (deveria falhar quase instantâneo)"
    )


def test_tesseract_ocr_backend_is_never_invoked_for_textless_pdf(tmp_path, monkeypatch):
    """Prova mais direta que o achado real do log de produção não se repete:
    trava o próprio backend de OCR do pymupdf4llm (tesseract_api.exec_ocr)
    pra explodir se for chamado - se `_extract_pdf` ainda deixasse
    `use_ocr` no default da biblioteca, este teste falharia com o
    AssertionError abaixo em vez do DocumentEngineError esperado."""
    from pymupdf4llm.ocr import tesseract_api

    def _must_not_be_called(*args, **kwargs):
        raise AssertionError(
            "tesseract_api.exec_ocr() foi chamado - _extract_pdf() não está "
            "mais passando use_ocr=OCRMode.NEVER pro pymupdf4llm.to_markdown()"
        )

    monkeypatch.setattr(tesseract_api, "exec_ocr", _must_not_be_called)

    pdf_path = tmp_path / "sem_texto2.pdf"
    _make_textless_pdf(pdf_path)

    with pytest.raises(DocumentEngineError):
        _extract_pdf(pdf_path)


def test_source_explicitly_disables_pymupdf4llm_implicit_ocr_fallback():
    """Guarda de regressão por leitura de fonte: mesmo que o comportamento
    acima passe por acaso numa versão futura do pymupdf4llm, o código-fonte
    precisa continuar passando `use_ocr=OCRMode.NEVER` explicitamente -
    nunca deixar o default implícito de uma dependência de terceiros
    decidir se roda OCR ou não numa extração que se promete "sem OCR"."""
    src = (Path(__file__).resolve().parent.parent / "phoenix_kernel" / "documents" / "engine.py").read_text(encoding="utf-8")
    assert "OCRMode.NEVER" in src
    assert "use_ocr=OCRMode.NEVER" in src
