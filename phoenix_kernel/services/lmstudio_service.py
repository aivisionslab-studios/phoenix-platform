"""
lmstudio_service.py
====================
Verifica se o LM Studio (servidor local, porta 1234) está no ar e tenta
subir sozinho, do mesmo jeito que a Phoenix já cuida do Ollama (Docker)
e da Aviary Platform (Node supervisionado).

Diferença importante: o LM Studio é um app DESKTOP, não um container.
A Phoenix não pode "instalar e esquecer" 100% como faz com Docker - mas
o LM Studio tem uma CLI oficial (`lms`) que permite ligar o servidor
local sem abrir a interface gráfica na mão. É nisso que a automação
se apoia:

  1. Verifica se o servidor já está respondendo em localhost:1234.
  2. Se não estiver, verifica se a CLI `lms` está disponível no PATH.
  3. Se disponível, tenta `lms server start` sozinha.
  4. Se a CLI não existir (app nunca foi aberto/configurado nessa
     máquina), registra um aviso orientando o usuário - só essa etapa
     não dá pra automatizar sem o app instalado pelo menos uma vez.

Coloque este arquivo em: phoenix_kernel/07_services/lmstudio_service.py
"""

from __future__ import annotations
import asyncio
import sys
import httpx

LMSTUDIO_URL = "http://localhost:1234/v1/models"
LMSTUDIO_TIMEOUT_SEC = 2.0


async def is_running() -> bool:
    try:
        async with httpx.AsyncClient(timeout=LMSTUDIO_TIMEOUT_SEC) as client:
            resp = await client.get(LMSTUDIO_URL)
            return resp.status_code == 200
    except Exception:
        return False


def is_cli_installed() -> bool:
    try:
        import subprocess
        result = subprocess.run(
            ["lms", "--version"], capture_output=True, text=True,
            shell=(sys.platform == "win32"),
        )
        return result.returncode == 0
    except Exception:
        # PHX-FIX (auditoria 2026-08-20, "Runtime policy / LM Studio
        # opcional" - Seção 1/5): antes só pegava FileNotFoundError.
        # try_start_server() (abaixo) documenta "nunca levanta exceção -
        # o boot da Phoenix segue independente" e kernel.py chama
        # try_start_server() SEM try/except ao redor - qualquer exceção
        # não pega aqui (PermissionError, OSError de exec malformado,
        # etc. - não só "comando não existe") vazaria e derrubaria o
        # boot inteiro por causa de um app 100% opcional. LM Studio nunca
        # deve poder quebrar o boot da Phoenix, então qualquer falha ao
        # checar a CLI vira simplesmente "não instalada".
        return False


async def try_start_server(logs_engine) -> tuple[bool, str]:
    """Retorna (sucesso, mensagem). Nunca levanta exceção - o boot da
    Phoenix segue independente do resultado aqui."""
    if await is_running():
        return True, "LM Studio já está respondendo em localhost:1234."

    if not is_cli_installed():
        return False, (
            "CLI 'lms' não encontrada. Abra o app LM Studio pelo menos uma vez "
            "(instala a CLI automaticamente), ou rode 'lms bootstrap' manualmente. "
            "Depois disso a Phoenix consegue ligar o servidor local sozinha nos "
            "próximos boots."
        )

    try:
        proc = await asyncio.create_subprocess_exec(
            "lms", "server", "start", "--port", "1234",
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.STDOUT,
        )
        # 'lms server start' retorna rápido (só dispara o processo em bg);
        # damos um tempo curto pra ele efetivamente responder.
        await asyncio.wait_for(proc.wait(), timeout=10)
    except asyncio.TimeoutError:
        pass  # comando pode ficar "pendurado" em alguns setups; seguimos pro check
    except FileNotFoundError:
        return False, "CLI 'lms' sumiu do PATH entre a checagem e a execução."
    except Exception as e:
        return False, f"Falha ao executar 'lms server start': {e}"

    # Confirma de verdade, não confia só no exit code do comando
    await asyncio.sleep(1.5)
    if await is_running():
        return True, "LM Studio iniciado com sucesso via 'lms server start'."
    return False, (
        "'lms server start' rodou mas o servidor não respondeu em localhost:1234. "
        "Abra o app LM Studio manualmente e confira a aba de servidor local."
    )
