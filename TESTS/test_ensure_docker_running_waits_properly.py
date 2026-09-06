r"""
Teste de regressão pra auditoria 2026-08-21: "phoenix vai aguardar docker
responder e só depois continuar subindo tudo" - achado real de uso real
(log do usuário mostrou "[!] Docker demorou muito para iniciar. Alguns
serviços podem não subir." seguido, na mesma respiração, de "[✓] Phoenix API
rodando").

Dois bugs reais em `ensure_docker_running()`/`api_server.py`:

1. A janela de espera era só 30 tentativas * 2s = 60s - curto demais pro
   Docker Desktop no Windows (especialmente com backend WSL2, que pode
   legitimamente levar 1-3+ minutos num boot frio). Não era "travado", era
   só desistência cedo demais.
2. Quem chamava `ensure_docker_running()` (bloco `if __name__ == "__main__":`)
   nunca checava o valor de retorno - `ensure_docker_running()` sozinho, sem
   `if not ...:` - então mesmo esse "desistir" não mudava nada no fluxo:
   Phoenix sempre imprimia "Phoenix API rodando" e seguia em frente de
   qualquer jeito, com ou sem Docker.

Fix: janela de espera sobe pra 300s (5min) com feedback de progresso; o
`if __name__ == "__main__":` agora captura `docker_ready = ensure_docker_running()`
e reflete o resultado na mensagem final. Docker continua OPCIONAL de
propósito (nunca trava o boot do Engine pra sempre - ver auditoria
2026-08-20 Seção 7, "Docker Desktop virou OPTIONAL"): o teste confirma que a
função ainda devolve False (não trava/lança exceção) quando o Docker
genuinamente nunca responde.

Rodada seguinte (2026-08-21, mesma auditoria, achado novo depois do usuário
testar a correção acima): "phoenix nao chamou docker... nunca chama e
aumentar pra ate 600s". Dois problemas adicionais, confirmados contra a
documentação oficial do Docker (Docker Desktop for Windows - "Permission
requirements"):

3. A janela de espera antiga (300s) precisava subir pra 600s (10min), a
   pedido explícito do usuário.
4. `_find_docker_desktop_exe()` (antes, dois `if`/`os.path.exists()` soltos
   dentro de `ensure_docker_running()`) só checava os DOIS caminhos de
   instalação PARA TODOS OS USUÁRIOS (admin, "C:\Program Files\..."). Docker
   Desktop também suporta instalação SÓ PRO USUÁRIO ATUAL (sem admin), que
   vai pra "%LOCALAPPDATA%\Programs\DockerDesktop\Docker Desktop.exe" - um
   caminho completamente diferente, nunca checado. Se o Docker do usuário
   foi instalado desse jeito, a função desistia IMEDIATAMENTE ("Docker
   Desktop.exe não encontrado") sem NUNCA chamar Popen - exatamente o
   "phoenix nunca chama docker" relatado (o CLI `docker` está no PATH, mas
   o executável gráfico nunca era achado pra abrir). Também endureceu o
   `subprocess.Popen(...)` com try/except - antes, uma falha ali (ex:
   PermissionError) subia sem tratamento e podia derrubar o boot inteiro da
   Phoenix, contrariando "Docker é opcional, nunca trava o boot".

Rodar com: pytest -q (de dentro de 'PHOENIX 3.0/')
"""
import os
import re
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import api_server


def _fake_completed(returncode: int) -> MagicMock:
    result = MagicMock()
    result.returncode = returncode
    return result


def test_wait_window_is_at_least_600_seconds_as_explicitly_requested():
    # Regressão direta dos achados #1 e #3: a janela nova precisa ser bem
    # maior que os 60s antigos (30 tentativas * 2s), e especificamente
    # atingir os 600s (10min) pedidos explicitamente pelo usuário depois de
    # testar a versão de 300s (5min) da rodada anterior.
    total_wait = api_server._DOCKER_WAIT_MAX_SECONDS
    assert total_wait >= 600, (
        f"janela de espera do Docker ({total_wait}s) é menor que os 600s "
        "pedidos explicitamente pelo usuário"
    )


def test_finds_per_user_docker_desktop_install_when_admin_paths_missing(monkeypatch):
    # Regressão direta do achado #4: instalação SÓ PRO USUÁRIO ATUAL (sem
    # admin) fica em %LOCALAPPDATA%\Programs\DockerDesktop\, nunca checada
    # antes - a função tinha só os dois caminhos "para todos os usuários"
    # (Program Files) e desistia sem nunca tentar abrir o Docker se o
    # usuário tivesse instalado sem privilégio de admin.
    # os.path.join() usa o separador do SO onde o teste está rodando (este
    # sandbox é Linux) - constrói o esperado do mesmo jeito que o código
    # real constrói, em vez de hardcodar barra invertida (que só bateria
    # rodando em Windows de verdade).
    fake_local_appdata = str(Path("/fake/LocalAppData"))
    monkeypatch.setenv("LOCALAPPDATA", fake_local_appdata)
    expected_path = os.path.join(fake_local_appdata, "Programs", "DockerDesktop", "Docker Desktop.exe")

    def _exists_side_effect(path):
        return path == expected_path

    with patch.object(api_server.os.path, "exists", side_effect=_exists_side_effect):
        found = api_server._find_docker_desktop_exe()

    assert found == expected_path


def test_ensure_docker_running_actually_calls_popen_for_per_user_install(monkeypatch):
    # Mesmo achado #4, mas de ponta a ponta: confirma que
    # ensure_docker_running() de fato chama Popen no caminho per-user
    # achado - não só que _find_docker_desktop_exe() sozinho acha o
    # caminho certo.
    # Mesmo cuidado de portabilidade da função de teste anterior: constrói o
    # caminho esperado com os.path.join() (separador do SO onde o teste
    # roda), em vez de hardcodar barra invertida.
    fake_local_appdata = str(Path("/fake/LocalAppData"))
    monkeypatch.setenv("LOCALAPPDATA", fake_local_appdata)
    per_user_path = os.path.join(fake_local_appdata, "Programs", "DockerDesktop", "Docker Desktop.exe")

    def _exists_side_effect(path):
        return path == per_user_path

    with patch.object(api_server.shutil, "which", return_value="/usr/bin/docker"), \
         patch.object(api_server.subprocess, "run", side_effect=TimeoutError("offline")), \
         patch.object(api_server.os.path, "exists", side_effect=_exists_side_effect), \
         patch.object(api_server.subprocess, "Popen") as mock_popen, \
         patch.object(api_server.time, "sleep"):
        api_server.ensure_docker_running()

    mock_popen.assert_called_once_with([per_user_path])


def test_popen_failure_returns_false_cleanly_instead_of_crashing_boot():
    # Regressão do endurecimento do Popen: antes, uma exceção aqui (ex:
    # PermissionError) subia sem tratamento e podia derrubar o processo
    # inteiro da Phoenix, contrariando "Docker é opcional, nunca trava o
    # boot".
    with patch.object(api_server.shutil, "which", return_value="/usr/bin/docker"), \
         patch.object(api_server.subprocess, "run", side_effect=TimeoutError("offline")), \
         patch.object(api_server.os.path, "exists", return_value=True), \
         patch.object(api_server.subprocess, "Popen", side_effect=PermissionError("negado")), \
         patch.object(api_server.time, "sleep") as mock_sleep:
        result = api_server.ensure_docker_running()

    assert result is False
    # Uma falha ao ABRIR o Docker não deveria gastar tempo esperando por um
    # processo que nunca chegou a existir.
    mock_sleep.assert_not_called()


def test_returns_true_immediately_when_docker_already_running():
    with patch.object(api_server.shutil, "which", return_value="/usr/bin/docker"), \
         patch.object(api_server.subprocess, "run", return_value=_fake_completed(0)) as mock_run, \
         patch.object(api_server.subprocess, "Popen") as mock_popen, \
         patch.object(api_server.time, "sleep") as mock_sleep:
        result = api_server.ensure_docker_running()

    assert result is True
    # Docker já respondeu no primeiro "docker info" - nunca deveria tentar
    # abrir o Docker Desktop.exe nem esperar.
    mock_popen.assert_not_called()
    mock_sleep.assert_not_called()


def test_returns_false_without_hanging_when_docker_binary_missing():
    with patch.object(api_server.shutil, "which", return_value=None):
        result = api_server.ensure_docker_running()
    assert result is False


def test_waits_through_the_full_window_and_recovers_if_docker_comes_up_late():
    """O caso central do achado: Docker demora, mas ACABA respondendo -
    dentro da janela nova, isso precisa contar como sucesso (o bug antigo
    desistia aos 60s mesmo quando o Docker ia responder logo depois)."""
    # docker.exe "existe" no primeiro caminho checado.
    attempts_before_success = (api_server._DOCKER_WAIT_MAX_SECONDS // api_server._DOCKER_WAIT_INTERVAL_SECONDS) - 2
    assert attempts_before_success > 30, (
        "este teste só faz sentido se a janela nova permitir esperar além "
        "dos 60s antigos (30 tentativas de 2s) - ajuste o teste se as "
        "constantes mudarem de novo"
    )

    call_count = {"n": 0}

    def _run_side_effect(cmd, **kwargs):
        if cmd == ["docker", "info"]:
            call_count["n"] += 1
            # A primeira chamada (checagem inicial, antes do loop de espera)
            # falha; dentro do loop, só "sucede" perto do fim da janela -
            # bem depois de onde os 60s antigos teriam desistido.
            if call_count["n"] > attempts_before_success:
                return _fake_completed(0)
            raise TimeoutError("docker ainda não respondeu")
        raise AssertionError(f"comando inesperado: {cmd}")

    with patch.object(api_server.shutil, "which", return_value="/usr/bin/docker"), \
         patch.object(api_server.os.path, "exists", return_value=True), \
         patch.object(api_server.subprocess, "run", side_effect=_run_side_effect), \
         patch.object(api_server.subprocess, "Popen") as mock_popen, \
         patch.object(api_server.time, "sleep") as mock_sleep:
        result = api_server.ensure_docker_running()

    assert result is True
    mock_popen.assert_called_once()
    # Confirma que realmente esperou várias vezes (não desistiu cedo) -
    # mais chamadas de sleep do que a janela antiga (30) permitiria.
    assert mock_sleep.call_count > 30


def test_gives_up_after_full_window_without_raising_and_docker_stays_optional():
    """Mesmo com a janela maior, o Docker continua OPCIONAL - se ele nunca
    responder, `ensure_docker_running()` precisa devolver False de forma
    limpa (nunca travar o processo, nunca lançar exceção) - regressão do
    bug corrigido na auditoria 2026-08-20 Seção 7 ("Docker Desktop virou
    OPTIONAL... bootstrap INTEIRO abortava" era o problema original)."""
    with patch.object(api_server.shutil, "which", return_value="/usr/bin/docker"), \
         patch.object(api_server.os.path, "exists", return_value=True), \
         patch.object(api_server.subprocess, "run", side_effect=TimeoutError("nunca responde")), \
         patch.object(api_server.subprocess, "Popen"), \
         patch.object(api_server.time, "sleep"):
        result = api_server.ensure_docker_running()

    assert result is False


def test_main_block_captures_the_return_value_instead_of_discarding_it():
    # Regressão do achado #2: leitura de fonte confirmando que o bloco
    # `if __name__ == "__main__":` não chama mais `ensure_docker_running()`
    # sozinho (valor de retorno jogado fora) - precisa capturar o resultado
    # e usá-lo, senão a espera mais longa da função não muda nada no
    # comportamento observável do usuário.
    src = Path(api_server.__file__).read_text(encoding="utf-8")
    main_block_start = src.index('if __name__ == "__main__":')
    main_block = src[main_block_start:main_block_start + 800]

    assert re.search(r"^\s*ensure_docker_running\(\)\s*$", main_block, re.MULTILINE) is None, (
        "o bloco principal ainda chama ensure_docker_running() sem capturar "
        "o retorno - a espera mais longa não teria efeito observável nenhum"
    )
    assert re.search(r"\w+\s*=\s*ensure_docker_running\(\)", main_block), (
        "o bloco principal precisa capturar o retorno de ensure_docker_running() "
        "numa variável e usá-lo"
    )
