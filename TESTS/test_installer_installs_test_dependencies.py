# TESTS/test_installer_installs_test_dependencies.py
#
# PHX-NEW (achado real do usuário 2026-08-28, na sequência da auditoria de
# segurança/qualidade completa): rodou `.venv\Scripts\python.exe -m pytest`
# num fix entregue e tomou "No module named 'pytest'" - mesmo com a pasta
# TESTS/ tendo mais de 250 testes (incluindo vários adicionados por esta
# própria auditoria, ao longo de várias correções). O usuário então pediu,
# corretamente, pra Phoenix resolver isso sozinha em vez de exigir um
# `pip install` manual toda vez.
#
# Causa raiz confirmada (não suposta): nenhum install/*.ps1 nem
# requirements.txt jamais declarou pytest/pytest-asyncio. Diferente de
# google-auth/cryptography/huggingface_hub - que PARECEM ausentes da lista
# de install/common.ps1 mas na prática já chegam como dependência
# TRANSITIVA de chromadb/google-cloud-firestore (confirmado nesta sessão
# com `pip install --dry-run --report` contra a lista real do instalador,
# antes de mexer em qualquer coisa, pra não "corrigir" algo que já
# funcionava) - pytest e pytest-asyncio são só ferramenta de teste, então
# nenhum pacote de produção os traz de brinde. Resultado real: toda
# instalação feita via install/common.ps1 (a .venv é recriada do zero em
# toda instalação - PHX-RECREATE) ficava sem conseguir rodar a própria
# suíte de testes do projeto.
#
# Como install/*.ps1 é PowerShell (não dá pra executar de verdade neste
# sandbox Linux), os testes aqui validam o TEXTO do script - mesma
# abordagem já usada por test_kokoro_gpu_install_option.py e
# test_asset_catalog_download_errors.py pros arquivos .ps1 do projeto.
#
# Rodar com: pytest -q (de dentro de 'PHOENIX 3.0/')

import re
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent
_COMMON = (_ROOT / "install" / "common.ps1").read_text(encoding="utf-8")
_REQUIREMENTS = (_ROOT / "requirements.txt").read_text(encoding="utf-8")


def test_common_installer_installs_pytest_and_pytest_asyncio():
    assert re.search(r"pip install[^\n]*\bpytest\b", _COMMON), (
        "install/common.ps1 precisa instalar 'pytest' dentro da .venv do projeto "
        "- sem isso, ninguém que rodar o instalador oficial consegue rodar TESTS/"
    )
    assert re.search(r"pip install[^\n]*\bpytest-asyncio\b", _COMMON), (
        "install/common.ps1 precisa instalar 'pytest-asyncio' junto - vários "
        "testes do projeto usam @pytest.mark.asyncio (ex: "
        "test_llama_cpp_driver_timeout_and_error_detail.py)"
    )


def test_pytest_install_happens_inside_the_activated_venv_block():
    # Garante que a instalação acontece DEPOIS de ". $VenvActivate" (dentro
    # da mesma .venv onde fastapi/chromadb/etc são instalados) - instalar
    # antes disso instalaria no Python global da máquina, não na venv que
    # o usuário de fato ativa pra rodar `python -m pytest`.
    venv_activate_pos = _COMMON.index(". $VenvActivate")
    pytest_install_match = re.search(r"pip install[^\n]*\bpytest-asyncio\b", _COMMON)
    assert pytest_install_match, "esperava achar a linha de instalação do pytest-asyncio"
    assert pytest_install_match.start() > venv_activate_pos, (
        "a instalação de pytest/pytest-asyncio precisa vir depois de '. $VenvActivate', "
        "senão instala no Python global em vez da .venv do projeto"
    )


def test_requirements_txt_also_lists_pytest_for_ci_and_manual_setup():
    # requirements.txt é a fonte de verdade pra CI/setup manual/container
    # (install/common.ps1 não o lê - ver comentário no topo do próprio
    # arquivo) - sem pytest/pytest-asyncio aqui também, esses caminhos
    # ficam sem conseguir rodar TESTS/ mesmo depois do fix no instalador.
    assert re.search(r"(?m)^pytest\s*(>=|==)", _REQUIREMENTS), (
        "requirements.txt precisa listar 'pytest' explicitamente"
    )
    assert re.search(r"(?m)^pytest-asyncio\s*(>=|==)", _REQUIREMENTS), (
        "requirements.txt precisa listar 'pytest-asyncio' explicitamente"
    )
