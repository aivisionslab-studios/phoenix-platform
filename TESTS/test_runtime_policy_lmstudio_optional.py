"""
Teste de regressão pra auditoria 2026-08-20, Target 1
("Runtime policy / LM Studio opcional / portas corretas").

Achado real, confirmado no log de instalação real anexado pelo usuário e
por leitura de código: a instalação da Phoenix tratava alguns componentes
100% OPCIONAIS (LM Studio, Docker Desktop e, por consequência, os
containers Ollama/Open WebUI/SearXNG que dependem dele) como se fossem
obrigatórios em pontos específicos:

  1. `install/windows.ps1`: "Docker Desktop" estava na categoria CORE com
     Required=$true - se o winget do Docker falhasse, o módulo inteiro
     retornava falha e o bootstrap INTEIRO abortava (achado mais grave
     desta rodada). Corrigido: Docker Desktop virou OPTIONAL, sem
     Required.
  2. `install/common.ps1`, `install/windows.ps1` (Start-DockerDesktop) e
     `install/linux.ps1`: chamavam `& docker ...`/`& docker info` direto,
     sem checar se o comando `docker` existe. Numa máquina sem Docker
     instalado (agora que é opcional, isso é um cenário real e comum),
     PowerShell levanta um erro TERMINANTE de "comando não encontrado"
     (diferente de exit code != 0, que $PSNativeCommandUseErrorAction
     Preference=$false já neutraliza) - o que travaria o script mesmo
     com a correção #1. Corrigido: todos os pontos de chamada de `docker`
     checam disponibilidade antes.
  3. `phoenix_kernel/services/lmstudio_service.py`: `is_cli_installed()`
     só tratava `FileNotFoundError` - qualquer outra exceção ao checar a
     CLI `lms` (PermissionError, etc.) vazaria através de
     `try_start_server()` (que promete no docstring "nunca levanta
     exceção") e através de `PhoenixKernel.boot()` (que chama sem
     try/except, confiando nessa promessa), derrubando o boot inteiro
     por causa de um app 100% opcional.
  4. `install_phoenix.ps1`: o relatório final jogava TODOS os warnings de
     TODOS os módulos numa única linha ilegível, misturando avisos sobre
     componentes opcionais com qualquer coisa mais séria. Corrigido: o
     relatório agora separa CORE STATUS / OPTIONAL STATUS / WARNINGS /
     ACTION REQUIRED (ver tests/test_install_report_classification.ps1
     pra prova em PowerShell real).

Este arquivo cobre a parte Python (itens 3) + a garantia estrutural de
que LM Studio nunca pode se tornar o "text engine" de orquestração da
Phoenix (item estrutural, não uma regressão desta rodada - já valia,
mas nunca tinha um teste dedicado). Os itens 1, 2 e 4 (PowerShell) são
cobertos por tests/test_install_report_classification.ps1 e por
verificação de sintaxe real via `pwsh -NoProfile -Command
[System.Management.Automation.Language.Parser]::ParseFile(...)` em todos
os arquivos .ps1 tocados (não há vitest/PS Pester configurado no projeto
- mesmo padrão de "verificação real disponível, sem framework dedicado"
já usado pra platform_source/ com tsc/build/node --check).

Rodar com: pytest -q (de dentro de 'PHOENIX 3.0/')
"""
import asyncio
import sys
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import phoenix_kernel.services.lmstudio_service as lm_service


# ---------------------------------------------------------------------
# 1. lmstudio_service: nunca levanta exceção, mesmo em cenários hostis
# ---------------------------------------------------------------------

def test_is_cli_installed_returns_false_on_filenotfound():
    with patch("subprocess.run", side_effect=FileNotFoundError()):
        assert lm_service.is_cli_installed() is False


def test_is_cli_installed_returns_false_on_arbitrary_exception():
    # PHX-FIX: antes só FileNotFoundError era pega - PermissionError (ou
    # qualquer outro erro de SO ao tentar rodar 'lms --version') vazaria.
    with patch("subprocess.run", side_effect=PermissionError("sem permissao de execucao")):
        assert lm_service.is_cli_installed() is False


def test_is_cli_installed_true_when_returncode_zero():
    fake_result = MagicMock(returncode=0)
    with patch("subprocess.run", return_value=fake_result):
        assert lm_service.is_cli_installed() is True


def test_try_start_server_returns_true_immediately_when_already_running():
    async def _run():
        with patch.object(lm_service, "is_running", new=AsyncMock(return_value=True)):
            ok, msg = await lm_service.try_start_server(logs_engine=MagicMock())
            return ok, msg
    ok, msg = asyncio.run(_run())
    assert ok is True
    assert "localhost:1234" in msg


def test_try_start_server_warns_without_raising_when_absent_and_cli_missing():
    """Cenário Seção 1/5: LM Studio nao instalado nesta maquina - nunca
    pode virar um erro que impede o boot, so um aviso claro."""
    async def _run():
        with patch.object(lm_service, "is_running", new=AsyncMock(return_value=False)), \
             patch.object(lm_service, "is_cli_installed", return_value=False):
            return await lm_service.try_start_server(logs_engine=MagicMock())
    ok, msg = asyncio.run(_run())
    assert ok is False
    assert "lms" in msg  # orienta o usuário, não trava nada


def test_try_start_server_never_raises_even_if_subprocess_blows_up():
    """Mesmo se 'lms server start' falhar de um jeito inesperado
    (exceção genérica no create_subprocess_exec), try_start_server()
    devolve (False, msg) - nunca propaga."""
    async def _run():
        with patch.object(lm_service, "is_running", new=AsyncMock(return_value=False)), \
             patch.object(lm_service, "is_cli_installed", return_value=True), \
             patch("asyncio.create_subprocess_exec", new=AsyncMock(side_effect=OSError("boom"))):
            return await lm_service.try_start_server(logs_engine=MagicMock())
    ok, msg = asyncio.run(_run())
    assert ok is False
    assert "Falha ao executar" in msg


def test_try_start_server_offline_after_attempt_still_returns_gracefully():
    """CLI existe, comando roda, mas o servidor continua sem responder -
    ainda assim so um aviso, nunca uma exceção."""
    async def _run():
        with patch.object(lm_service, "is_running", new=AsyncMock(return_value=False)), \
             patch.object(lm_service, "is_cli_installed", return_value=True), \
             patch("asyncio.create_subprocess_exec", new=AsyncMock(return_value=MagicMock(wait=AsyncMock(return_value=0)))), \
             patch("asyncio.sleep", new=AsyncMock(return_value=None)):
            return await lm_service.try_start_server(logs_engine=MagicMock())
    ok, msg = asyncio.run(_run())
    assert ok is False
    assert "servidor não respondeu" in msg


# ---------------------------------------------------------------------
# 2. Garantia estrutural: LM Studio NUNCA pode virar o "text engine" da
#    orquestração real (ResidentManager/ReasoningEngine) - só existe como
#    opção manual no seletor de provedores do Aviary (frontend).
# ---------------------------------------------------------------------

def test_lmstudio_is_not_a_valid_text_engine_value():
    import phoenix_kernel.resident.resident_manager as rm_module
    ResidentManager = rm_module.ResidentManager
    r = object.__new__(ResidentManager)
    r._VALID_TEXT_ENGINES = ResidentManager._VALID_TEXT_ENGINES
    assert "lmstudio" not in r._VALID_TEXT_ENGINES
    assert "lm_studio" not in r._VALID_TEXT_ENGINES
    assert "lm-studio" not in r._VALID_TEXT_ENGINES
    assert r._VALID_TEXT_ENGINES == ("llama.cpp", "ollama")


def test_set_text_engine_preference_rejects_lmstudio(tmp_path):
    import phoenix_kernel.resident.resident_manager as rm_module
    ResidentManager = rm_module.ResidentManager
    r = object.__new__(ResidentManager)
    r._VALID_TEXT_ENGINES = ResidentManager._VALID_TEXT_ENGINES
    r._text_engine_preference = "llama.cpp"
    r.reasoning = MagicMock()

    pref_path = tmp_path / "text_engine_preference.json"
    with patch.object(rm_module._paths_module, "TEXT_ENGINE_PREFERENCE_FILE", pref_path):
        result = r.set_text_engine_preference("lmstudio")

    assert result["ok"] is False
    assert "llama.cpp" in result["error"] and "ollama" in result["error"]
    # Nunca escreveu nada em disco pra um valor invalido
    assert not pref_path.exists()


def test_text_engine_preference_defaults_to_llama_cpp_when_file_absent(tmp_path):
    import phoenix_kernel.resident.resident_manager as rm_module
    ResidentManager = rm_module.ResidentManager
    r = object.__new__(ResidentManager)
    pref_path = tmp_path / "does_not_exist.json"
    with patch.object(rm_module._paths_module, "TEXT_ENGINE_PREFERENCE_FILE", pref_path):
        assert r._load_text_engine_preference() == "llama.cpp"


def test_text_engine_preference_falls_back_to_llama_cpp_when_file_has_lmstudio(tmp_path):
    """Mesmo se alguém escrever manualmente {"engine":"lmstudio"} no
    arquivo em disco (fora do fluxo normal), a leitura recusa e cai no
    default seguro - nunca deixa "lmstudio" vazar pro ReasoningEngine."""
    import phoenix_kernel.resident.resident_manager as rm_module
    ResidentManager = rm_module.ResidentManager
    r = object.__new__(ResidentManager)
    pref_path = tmp_path / "text_engine_preference.json"
    pref_path.write_text('{"engine": "lmstudio"}', encoding="utf-8")
    with patch.object(rm_module._paths_module, "TEXT_ENGINE_PREFERENCE_FILE", pref_path):
        assert r._load_text_engine_preference() == "llama.cpp"


def test_text_engine_preference_falls_back_to_llama_cpp_on_malformed_json(tmp_path):
    import phoenix_kernel.resident.resident_manager as rm_module
    ResidentManager = rm_module.ResidentManager
    r = object.__new__(ResidentManager)
    pref_path = tmp_path / "text_engine_preference.json"
    pref_path.write_text("{not valid json", encoding="utf-8")
    with patch.object(rm_module._paths_module, "TEXT_ENGINE_PREFERENCE_FILE", pref_path):
        assert r._load_text_engine_preference() == "llama.cpp"


def test_ollama_is_valid_but_never_default_unless_set(tmp_path):
    """Ollama e uma segunda opcao valida - mas so quando o usuario troca
    explicitamente (arquivo ausente == llama.cpp, nao ollama)."""
    import phoenix_kernel.resident.resident_manager as rm_module
    ResidentManager = rm_module.ResidentManager
    r = object.__new__(ResidentManager)
    assert "ollama" in ResidentManager._VALID_TEXT_ENGINES

    pref_path = tmp_path / "does_not_exist.json"
    with patch.object(rm_module._paths_module, "TEXT_ENGINE_PREFERENCE_FILE", pref_path):
        assert r._load_text_engine_preference() != "ollama"
        assert r._load_text_engine_preference() == "llama.cpp"
