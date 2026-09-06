# TESTS/test_release_hygiene_never_publish.py
#
# PHX-NEW (auditoria 2026-08-28, achado GRAVE do usuário no repositório
# público real): `private_server_reference/` (com seu próprio
# README_PRIVATE.txt dizendo "NÃO coloque... no repositório público") e
# um backup órfão de hotfix (`plans.py.before_hotfix_20260827_194334`)
# foram publicados em github.com/aivisionslab-studios/phoenix-engine. A
# checagem de segredo por CONTEÚDO que já existia em
# verify_release_clean.py (`_check_no_leaked_secrets`, Rodada 15) não
# pegou nenhum dos dois - nem private_server_reference/ tinha credencial
# embutida (só o desenho do esquema de licenciamento), nem o backup de
# hotfix é credencial. `_check_never_publish_paths()` (nova) cobre essa
# categoria: pastas/padrões de nome inteiros que nunca devem ir pra um
# release, independente do conteúdo.
#
# Roda a checagem de verdade (sem mock) contra uma árvore de arquivos
# temporária, monkeypatchando verify_release_clean.ROOT - mesmo padrão
# de "sem mock, arquivo real" já usado em test_fill_xlsx_template_engine.py
# pra funções puras de I/O de arquivo.

import importlib.util
import sys
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))


def _load_verify_module():
    """Carrega verify_release_clean.py como módulo isolado - ele não tem
    __init__.py/pacote (é um script de raiz), então importlib direto por
    caminho de arquivo evita depender de sys.path apontar pra raiz certa."""
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


def test_clean_tree_passes(vrc, tmp_path):
    (tmp_path / "api_server.py").write_text("# nada aqui")
    ok, problems = vrc._check_never_publish_paths()
    assert ok is True
    assert problems == []


def test_flags_private_server_reference_directory(vrc, tmp_path):
    priv = tmp_path / "private_server_reference"
    priv.mkdir()
    (priv / "README_PRIVATE.txt").write_text("NAO PUBLICAR")
    (priv / "license_server_reference.py").write_text("# referencia")

    ok, problems = vrc._check_never_publish_paths()

    assert ok is False
    assert any("private_server_reference" in p for p in problems)


def test_flags_nested_private_server_reference_directory(tmp_path, vrc):
    """A pasta pode estar em qualquer profundidade (ex: dentro de um
    subdiretório de patches/arquivo) - a checagem usa rglob, não só o
    nível raiz."""
    nested = tmp_path / "algum_subdir" / "private_server_reference"
    nested.mkdir(parents=True)
    (nested / "x.txt").write_text("x")

    ok, problems = vrc._check_never_publish_paths()

    assert ok is False
    assert any("private_server_reference" in p for p in problems)


def test_flags_before_hotfix_backup_file(vrc, tmp_path):
    licensing_dir = tmp_path / "phoenix_kernel" / "licensing"
    licensing_dir.mkdir(parents=True)
    (licensing_dir / "plans.py.before_hotfix_20260827_194334").write_text("# backup velho")

    ok, problems = vrc._check_never_publish_paths()

    assert ok is False
    assert any("before_hotfix" in p for p in problems)


def test_does_not_flag_unrelated_files(vrc, tmp_path):
    (tmp_path / "phoenix_kernel").mkdir()
    (tmp_path / "phoenix_kernel" / "plans.py").write_text("# arquivo normal, sem sufixo de backup")
    (tmp_path / "server_reference_notes.txt").write_text("nome parecido mas não é a pasta exata")

    ok, problems = vrc._check_never_publish_paths()

    assert ok is True
    assert problems == []


def test_skips_git_and_node_modules_directories(vrc, tmp_path):
    """Mesmo se um clone/checkout tiver o nome dentro de .git ou
    node_modules (empacotado por outra dependência, por exemplo), não é
    isso que a checagem quer sinalizar - mesma lista SECRET_SCAN_SKIP_DIR_NAMES
    já usada por _check_no_leaked_secrets."""
    for skip_dir in ("node_modules", ".git"):
        nested = tmp_path / skip_dir / "alguma_lib" / "private_server_reference"
        nested.mkdir(parents=True)
        (nested / "x.txt").write_text("x")

    ok, problems = vrc._check_never_publish_paths()

    assert ok is True
    assert problems == []


def test_full_check_exits_nonzero_when_never_publish_path_present(vrc, tmp_path, capsys, monkeypatch):
    """Teste de integração leve: roda o fluxo principal (main()) contra a
    árvore temporária e confere que o processo falharia de verdade (código
    de saída 1) se private_server_reference/ estivesse presente - não só
    a função isolada, mas o comportamento observável de quem roda
    `python3 verify_release_clean.py` antes de gerar um release."""
    (tmp_path / ".gitignore").write_text(
        "data/text_engine_preference.json\ndata/engine_preference.json\n!platform_source/.env.example\n"
    )
    priv = tmp_path / "private_server_reference"
    priv.mkdir()
    (priv / "README_PRIVATE.txt").write_text("NAO PUBLICAR")

    # LEGACY_PATHS_TO_DELETE é montada com o ROOT real no import do módulo
    # (antes do monkeypatch de ROOT acima) - main() chamaria
    # path.relative_to(ROOT-de-teste) num Path que nem é subcaminho dele.
    # Irrelevante pro que este teste verifica (o novo check
    # NEVER_PUBLISH_*), então esvazia pra não interferir.
    monkeypatch.setattr(vrc, "LEGACY_PATHS_TO_DELETE", [])

    exit_code = vrc.main()

    assert exit_code == 1
    out = capsys.readouterr().out
    assert "private_server_reference" in out
    assert "FALHA" in out
