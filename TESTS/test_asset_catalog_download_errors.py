"""
Testes de regressão pra auditoria 2026-08-20, Seção 14 do LEIA-ME ("catálogo
de imagem/VAE com URLs 401/404").

HISTÓRICO IMPORTANTE (deixado explícito pra não repetir o erro): a Rodada 17
"corrigiu" catalog/assets/flux_vae.json trocando black-forest-labs/FLUX.1-dev
por black-forest-labs/FLUX.1-schnell, assumindo que schnell era não-gated
(com base num comentário de install/common.ps1 que na verdade falava do
CHECKPOINT do repo Unsloth, não deste VAE). A auditoria externa da Rodada 17
provou que estava errado: black-forest-labs/FLUX.1-schnell TAMBÉM é gated no
Hugging Face ("You need to agree to share your contact information to access
this model"), apesar de licenciado apache-2.0 - gated e licença são coisas
independentes lá. A Rodada 18 corrigiu de verdade: flux_vae.json agora aponta
pro mirror comunitário camenduru/FLUX.1-dev (revalidado sem aviso de
gated, contém ae.safetensors de 335MB) - a fonte oficial gated virou
flux_vae_mirror.json, marcada 'requires_auth: true' (nunca baixada
automaticamente). O download "SDXL VAE Fix" de install/common.ps1 usava um
nome de arquivo remoto que não existe no repo madebyollin/sdxl-vae-fp16-fix
(HTTP 404) - isso a auditoria da Rodada 17 confirmou como corrigido e não
mudou nesta rodada.

Duas frentes cobertas aqui:
1. Os CATÁLOGOS em si: flux_vae.json aponta pro mirror não-gated
   confirmado; flux_vae_mirror.json guarda a fonte oficial gated com
   'requires_auth: true'; catalog/assets/sdxl_vae_fix.json com a URL remota
   corrigida (sdxl_vae.safetensors, não sdxl_vae-fp16-fix.safetensors) mas
   mantendo o nome LOCAL que phoenix_kernel/runtime/drivers/sd_cpp.py
   procura por substring.
2. O MECANISMO: Engine/provisioning/download_providers.py::HttpProvider.
   download() agora classifica falhas HTTP (401/403 = autenticação exigida,
   404 = link morto, outros = genérico) em vez de um "Erro -> ..." cru;
   Engine/provisioning/asset_manager.py::AssetManager.get_asset() expõe o
   motivo via self.last_error (sem quebrar o contrato de retorno
   'str | None') e nunca tenta baixar um catálogo marcado
   'requires_auth: true' (evita a tentativa 401 garantida) - testado aqui
   contra os catálogos REAIS do projeto, não só sintéticos.

Rodar com: pytest -q (de dentro de 'PHOENIX 3.0/')
"""
import json
import sys
import urllib.error
from pathlib import Path
from unittest.mock import patch

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from Engine.provisioning.asset_manager import AssetManager
from Engine.provisioning.download_providers import HttpProvider


# ---------------------------------------------------------------------
# 1. Catálogos reais do projeto - garante que os dois achados específicos
#    da Seção 14 não regridem silenciosamente.
# ---------------------------------------------------------------------

_CATALOG_DIR = Path(__file__).resolve().parent.parent / "catalog" / "assets"




def test_install_script_flux_vae_url_does_not_use_official_gated_repo():
    # Mesmo bug, mesma causa raiz, mas no INSTALADOR (não só no catálogo) -
    # install/common.ps1 baixa isto direto, sem passar pelo AssetManager,
    # então precisa da mesma correção separadamente.
    ps1 = (Path(__file__).resolve().parent.parent / "install" / "common.ps1").read_text(encoding="utf-8")
    url_lines = [line for line in ps1.splitlines() if "-Url" in line and "ae.safetensors" in line]
    assert url_lines, "esperava achar a linha -Url do download 'Flux VAE (ae.safetensors)' em install/common.ps1"
    assert all("black-forest-labs" not in line for line in url_lines), (
        f"install/common.ps1 ainda baixa o Flux VAE do namespace oficial gated: {url_lines}"
    )


def test_sdxl_vae_fix_catalog_exists_with_correct_remote_filename():
    # Regressão do achado #2 da Seção 14: o nome remoto errado
    # ("sdxl_vae-fp16-fix.safetensors") não existe no repo madebyollin -
    # o arquivo real lá se chama "sdxl_vae.safetensors".
    path = _CATALOG_DIR / "sdxl_vae_fix.json"
    assert path.exists(), "catalog/assets/sdxl_vae_fix.json precisa existir (Seção 14)"
    catalog = json.loads(path.read_text(encoding="utf-8"))
    url = catalog["provider_data"]["url"]
    assert url.endswith("/sdxl_vae.safetensors")
    assert "sdxl_vae-fp16-fix.safetensors" not in url
    # O nome LOCAL continua com "fp16-fix" de propósito - é a substring que
    # sd_cpp.py._find_component() procura pro perfil "sdxl-checkpoint".
    assert "fp16-fix" in catalog["filename"] or "sdxl-vae" in catalog["filename"]


def test_install_script_sdxl_vae_fix_url_matches_real_remote_filename():
    # Checa só a linha "-Url ..." de verdade (não os comentários que
    # DESCREVEM o bug antigo, que ainda mencionam o nome errado de
    # propósito, como explicação histórica).
    ps1 = (Path(__file__).resolve().parent.parent / "install" / "common.ps1").read_text(encoding="utf-8")
    url_lines = [line for line in ps1.splitlines() if "-Url" in line and "sdxl_vae" in line]
    assert url_lines, "esperava achar a linha -Url do download 'SDXL VAE Fix' em install/common.ps1"
    assert all("sdxl_vae-fp16-fix.safetensors" not in line for line in url_lines), (
        f"install/common.ps1 ainda usa o nome de arquivo remoto que dá 404: {url_lines}"
    )
    assert any("sdxl_vae.safetensors" in line for line in url_lines)


# ---------------------------------------------------------------------
# 2. HttpProvider.download() - classificação de erro HTTP (401/403/404 vs
#    genérico), sem precisar de rede de verdade (urlopen mockado).
# ---------------------------------------------------------------------

def _http_error(code, reason="erro"):
    return urllib.error.HTTPError(url="https://exemplo/x", code=code, msg=reason, hdrs=None, fp=None)


def test_http_provider_classifies_401_as_auth_required(tmp_path):
    target = tmp_path / "arquivo.safetensors"
    with patch("Engine.provisioning.download_providers.urllib.request.urlopen", side_effect=_http_error(401, "Unauthorized")):
        ok, reason = HttpProvider.download({"url": "https://exemplo/gated.safetensors"}, target)

    assert ok is False
    assert "autoriza" in reason.lower() or "autentic" in reason.lower()
    assert not target.exists()
    assert not target.with_name(target.name + ".part").exists()


def test_http_provider_classifies_404_as_dead_link(tmp_path):
    target = tmp_path / "arquivo.safetensors"
    with patch("Engine.provisioning.download_providers.urllib.request.urlopen", side_effect=_http_error(404, "Not Found")):
        ok, reason = HttpProvider.download({"url": "https://exemplo/sumiu.safetensors"}, target)

    assert ok is False
    assert "404" in reason
    assert "morto" in reason.lower() or "não encontrado" in reason.lower()


def test_http_provider_success_still_writes_file_and_returns_no_reason(tmp_path):
    import io

    target = tmp_path / "arquivo.bin"
    fake_response = io.BytesIO(b"conteudo de teste")

    class _CtxResp:
        def __enter__(self_inner):
            return fake_response

        def __exit__(self_inner, *a):
            return False

    with patch("Engine.provisioning.download_providers.urllib.request.urlopen", return_value=_CtxResp()):
        ok, reason = HttpProvider.download({"url": "https://exemplo/ok.bin"}, target)

    assert ok is True
    assert reason is None
    assert target.exists()
    assert target.read_bytes() == b"conteudo de teste"


# ---------------------------------------------------------------------
# 3. AssetManager.get_asset() - last_error propagado, requires_auth nunca
#    tenta a requisição HTTP.
# ---------------------------------------------------------------------

def _write_catalog(catalog_dir: Path, asset_name: str, data: dict):
    catalog_dir.mkdir(parents=True, exist_ok=True)
    (catalog_dir / f"{asset_name}.json").write_text(json.dumps(data), encoding="utf-8")


def test_get_asset_exposes_classified_reason_on_404(tmp_path):
    catalog_dir = tmp_path / "assets"
    _write_catalog(catalog_dir, "modelo_morto", {
        "schema": "1.0", "type": "asset", "name": "Modelo Morto", "provider": "http",
        "provider_data": {"url": "https://exemplo/morto.safetensors"},
        "filename": "morto.safetensors", "target_dir": str(tmp_path / "out"),
    })
    manager = AssetManager(catalog_path=str(catalog_dir))

    with patch("Engine.provisioning.download_providers.urllib.request.urlopen", side_effect=_http_error(404)):
        result = manager.get_asset("modelo_morto")

    assert result is None
    assert manager.last_error is not None
    assert "404" in manager.last_error


def test_get_asset_never_attempts_download_when_requires_auth(tmp_path):
    catalog_dir = tmp_path / "assets"
    _write_catalog(catalog_dir, "modelo_gated", {
        "schema": "1.0", "type": "asset", "name": "Modelo Gated", "provider": "http",
        "provider_data": {"url": "https://exemplo/gated.safetensors"},
        "filename": "gated.safetensors", "target_dir": str(tmp_path / "out"),
        "requires_auth": True,
    })
    manager = AssetManager(catalog_path=str(catalog_dir))

    with patch("Engine.provisioning.download_providers.urllib.request.urlopen") as mock_urlopen:
        result = manager.get_asset("modelo_gated")

    assert result is None
    mock_urlopen.assert_not_called()  # nunca tenta a requisição - saberia que ia dar 401/403
    assert manager.last_error is not None
    assert "autentic" in manager.last_error.lower() or "licença" in manager.last_error.lower()



def test_get_asset_success_clears_previous_last_error(tmp_path):
    catalog_dir = tmp_path / "assets"
    out_dir = tmp_path / "out"
    _write_catalog(catalog_dir, "modelo_ok", {
        "schema": "1.0", "type": "asset", "name": "Modelo OK", "provider": "http",
        "provider_data": {"url": "https://exemplo/ok.safetensors"},
        "filename": "ok.safetensors", "target_dir": str(out_dir),
    })
    manager = AssetManager(catalog_path=str(catalog_dir))
    manager.last_error = "erro de uma chamada anterior"

    import io

    class _CtxResp:
        def __enter__(self_inner):
            return io.BytesIO(b"dados")

        def __exit__(self_inner, *a):
            return False

    with patch("Engine.provisioning.download_providers.urllib.request.urlopen", return_value=_CtxResp()):
        result = manager.get_asset("modelo_ok")

    assert result is not None
    assert manager.last_error is None


def test_get_asset_downloads_declared_dependencies_before_main_asset(tmp_path):
    catalog_dir = tmp_path / "assets"
    out_dir = tmp_path / "out"
    for name in ("vae", "encoder"):
        _write_catalog(catalog_dir, name, {
            "schema": "1.0", "type": "asset", "name": name,
            "provider": "http", "provider_data": {"url": f"https://exemplo/{name}.bin"},
            "filename": f"{name}.bin", "target_dir": str(out_dir),
        })
    _write_catalog(catalog_dir, "modelo", {
        "schema": "1.0", "type": "asset", "name": "modelo",
        "provider": "http", "provider_data": {"url": "https://exemplo/modelo.bin"},
        "filename": "modelo.bin", "target_dir": str(out_dir),
        "dependencies": ["vae", "encoder"],
    })
    manager = AssetManager(catalog_path=str(catalog_dir))

    import io

    class _CtxResp:
        def __enter__(self_inner):
            return io.BytesIO(b"dados")

        def __exit__(self_inner, *a):
            return False

    with patch(
        "Engine.provisioning.download_providers.urllib.request.urlopen",
        return_value=_CtxResp(),
    ) as mocked:
        result = manager.get_asset("modelo")

    assert result == str(out_dir / "modelo.bin")
    assert mocked.call_count == 3
    assert (out_dir / "vae.bin").is_file()
    assert (out_dir / "encoder.bin").is_file()
