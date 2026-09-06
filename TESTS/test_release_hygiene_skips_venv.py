# TESTS/test_release_hygiene_skips_venv.py
#
# PHX-NEW (2026-08-28, achado do usuário rodando verify_release_clean.py
# na árvore de desenvolvimento real, com .venv/ presente): antes desta
# correção, SECRET_SCAN_SKIP_DIR_NAMES não incluía .venv/venv/env, então
# toda execução varria .venv/Lib/site-packages inteiro e denunciava
# arquivos de bibliotecas de terceiros já instaladas via pip (certifi,
# grpc, google-auth - todos legitimamente contêm strings como
# "-----BEGIN PRIVATE KEY-----" ou "private_key" no próprio código-fonte
# do pacote, sem serem segredo nenhum) como [FALHA]. Isso nunca foi um
# vazamento real - .venv nunca é commitado nem entra no ZIP de release -
# mas o ruído escondia os achados de verdade no meio de dezenas de linhas
# de falso positivo toda vez que alguém rodava o script.
#
# Mesmo padrão de test_release_hygiene_never_publish.py: carrega
# verify_release_clean.py isolado via importlib e monkeypatcha ROOT pra
# uma árvore temporária, sem mexer no ROOT real.

import importlib.util
import sys
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))


def _load_verify_module():
    spec = importlib.util.spec_from_file_location(
        "verify_release_clean", PROJECT_ROOT / "verify_release_clean.py",
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture()
def vrc(monkeypatch, tmp_path):
    module = _load_verify_module()
    monkeypatch.setattr(module, "ROOT", tmp_path)
    return module


@pytest.mark.parametrize("venv_dir_name", [".venv", "venv", "env"])
def test_secret_scan_skips_venv_style_directories(vrc, tmp_path, venv_dir_name):
    """Arquivo de biblioteca pip legítima com marcador de credencial no
    próprio código-fonte (ex.: google-auth definindo a constante de nome
    de campo "private_key", ou um .pem de CA pública como o da certifi)
    não deve ser denunciado quando está dentro de uma pasta de
    virtualenv - isso é reconhecidamente ruído, não vazamento."""
    site_packages = tmp_path / venv_dir_name / "Lib" / "site-packages" / "certifi"
    site_packages.mkdir(parents=True)
    (site_packages / "cacert.pem").write_text("-----BEGIN PRIVATE KEY-----\nfake\n-----END PRIVATE KEY-----\n")

    google_auth = tmp_path / venv_dir_name / "Lib" / "site-packages" / "google" / "auth" / "crypt"
    google_auth.mkdir(parents=True)
    (google_auth / "_python_rsa.py").write_text('"private_key": "algo-nao-vazio-no-codigo-do-pacote"')

    ok, problems = vrc._check_no_leaked_secrets()

    assert ok is True, f"não deveria ter achado nada dentro de {venv_dir_name}/, mas achou: {problems}"
    assert problems == []


def test_secret_scan_still_flags_real_secret_outside_venv(vrc, tmp_path):
    """Confirma que ignorar .venv não é um buraco que também esconde
    segredo de verdade fora dele - o mesmo arquivo, fora de uma pasta de
    venv, continua sendo pego normalmente."""
    data_dir = tmp_path / "data" / "config"
    data_dir.mkdir(parents=True)
    (data_dir / "firestore_credentials.json").write_text("{}")

    ok, problems = vrc._check_no_leaked_secrets()

    assert ok is False
    assert any("firestore_credentials" in p for p in problems)


def test_self_is_excluded_from_its_own_secret_content_scan(vrc, tmp_path):
    """PHX-FIX (achado do usuário 2026-08-28): este próprio arquivo de
    teste escreve os marcadores falsos de credencial como literais de
    string no seu código-fonte (pra simular um arquivo de .venv/) - o que
    fazia verify_release_clean.py se autodenunciar toda vez que o teste
    existia na árvore. Copia o CONTEÚDO REAL deste arquivo (sem mock) pra
    dentro da árvore temporária e confirma que o self-exclude
    (SECRET_SCAN_SELF_EXCLUDE_FILES) cobre isso."""
    real_source = Path(__file__).read_text(encoding="utf-8")
    (tmp_path / "test_release_hygiene_skips_venv.py").write_text(real_source, encoding="utf-8")

    ok, problems = vrc._check_no_leaked_secrets()

    assert ok is True, f"o próprio arquivo de teste não deveria se autodenunciar, mas achou: {problems}"
    assert problems == []
