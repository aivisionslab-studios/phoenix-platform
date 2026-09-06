"""
Teste de regressão pra um bug real achado nesta sessão (2026-08-23), durante
o teste end-to-end do novo auto-download do Kokoro (catalog/assets/
kokoro_model.json, endpoint /api/tts/kokoro/download): um download de
verdade contra o GitHub (não simulado) terminou o loop de leitura de
HttpProvider.download() sem nenhuma exceção, mas gravou só 64739264 de
325532387 bytes esperados - a conexão caiu no meio, e response.read()
simplesmente voltou a devolver b"" mais cedo do que devia, sem erro.

Antes desta correção, esse .part virava o arquivo "final" (>0 bytes, sem
exceção) e o AssetManager (get_asset) tratava como cache válido pra sempre -
a MESMA classe de bug já documentada em test_asset_catalog_download_errors.py
(o "flux1-schnell corrompido" original), só que causada por EOF prematuro em
vez de HTTP error explícito.

Correção: quando o servidor informa Content-Length, HttpProvider.download()
agora conta os bytes de verdade escritos e rejeita (sem deixar nenhum
arquivo "final" no disco) se não bater com o esperado. Quando o servidor NÃO
informa Content-Length (streaming/chunked), o comportamento antigo continua
(não dá pra validar o que não foi anunciado).

Rodar com: pytest -q (de dentro de 'PHOENIX 3.0/')
"""
import io
import sys
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from Engine.provisioning.asset_manager import AssetManager
from Engine.provisioning.download_providers import HttpProvider


class _FakeHeaders(dict):
    """Simula email.message.Message (o que urllib de verdade usa pra
    response.headers) - só precisa do .get() usado pelo código."""
    pass


class _TruncatedResponse:
    """Anuncia Content-Length de 1000 bytes mas só entrega 200 - reproduz
    de verdade o formato de resposta que causou o bug (conexão caindo no
    meio, sem exceção nenhuma)."""

    def __init__(self, announced_size: int, actual_bytes: bytes):
        self.headers = _FakeHeaders({"Content-Length": str(announced_size)})
        self._buf = io.BytesIO(actual_bytes)

    def read(self, n=-1):
        return self._buf.read(n)

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


class _CompleteResponse(_TruncatedResponse):
    def __init__(self, data: bytes):
        super().__init__(len(data), data)


def test_http_provider_rejects_truncated_download_when_content_length_known(tmp_path):
    target = tmp_path / "modelo.onnx"
    # Anuncia 1000 bytes, só entrega 200 - exatamente o formato do bug real
    # (conexão caindo no meio, response.read() nunca lança exceção).
    fake = _TruncatedResponse(announced_size=1000, actual_bytes=b"x" * 200)

    with patch("Engine.provisioning.download_providers.urllib.request.urlopen", return_value=fake):
        ok, reason = HttpProvider.download({"url": "https://exemplo/modelo.onnx"}, target)

    assert ok is False, "download truncado (200 de 1000 bytes anunciados) não pode ser reportado como sucesso"
    assert "200" in reason and "1000" in reason
    assert not target.exists(), "arquivo truncado não pode ficar no destino final (seria tratado como cache válido pra sempre)"
    assert not target.with_name(target.name + ".part").exists(), ".part precisa ser limpo, não deixado pra trás"


def test_http_provider_accepts_complete_download_matching_content_length(tmp_path):
    target = tmp_path / "modelo.onnx"
    data = b"y" * 500
    fake = _CompleteResponse(data)

    with patch("Engine.provisioning.download_providers.urllib.request.urlopen", return_value=fake):
        ok, reason = HttpProvider.download({"url": "https://exemplo/modelo.onnx"}, target)

    assert ok is True
    assert reason is None
    assert target.read_bytes() == data


def test_http_provider_skips_validation_when_no_content_length_header(tmp_path):
    # Servidor streaming/chunked sem anunciar tamanho - não dá pra validar
    # o que não foi prometido, então mantém o comportamento antigo (aceita
    # o que vier, contanto que não esteja vazio).
    target = tmp_path / "modelo.onnx"

    class _NoHeaderResponse:
        headers = _FakeHeaders({})  # sem 'Content-Length'

        def __init__(self, data):
            self._buf = io.BytesIO(data)

        def read(self, n=-1):
            return self._buf.read(n)

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

    with patch("Engine.provisioning.download_providers.urllib.request.urlopen", return_value=_NoHeaderResponse(b"conteudo sem tamanho anunciado")):
        ok, reason = HttpProvider.download({"url": "https://exemplo/streaming.bin"}, target)

    assert ok is True
    assert target.read_bytes() == b"conteudo sem tamanho anunciado"


def test_get_asset_never_caches_a_truncated_download(tmp_path):
    # Ponta a ponta via AssetManager (não só HttpProvider isolado): um
    # download truncado não pode deixar NENHUM arquivo em disco que uma
    # segunda chamada a get_asset() trataria como "já baixado, reutilizando".
    catalog_dir = tmp_path / "assets"
    out_dir = tmp_path / "out"
    catalog_dir.mkdir(parents=True)
    import json
    (catalog_dir / "modelo_truncado.json").write_text(json.dumps({
        "schema": "1.0", "type": "asset", "name": "Modelo Truncado", "provider": "http",
        "provider_data": {"url": "https://exemplo/modelo.onnx"},
        "filename": "modelo.onnx", "target_dir": str(out_dir),
    }), encoding="utf-8")
    manager = AssetManager(catalog_path=str(catalog_dir))

    fake = _TruncatedResponse(announced_size=325532387, actual_bytes=b"z" * 64739264)
    with patch("Engine.provisioning.download_providers.urllib.request.urlopen", return_value=fake):
        result = manager.get_asset("modelo_truncado")

    assert result is None
    assert manager.last_error is not None
    assert "interromp" in manager.last_error.lower() or "64739264" in manager.last_error
    assert not (out_dir / "modelo.onnx").exists()
