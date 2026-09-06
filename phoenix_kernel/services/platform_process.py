"""
platform_process.py
====================
Sobe e VIGIA o servidor Node.js da Phoenix Aviary Platform
(platform_source/dist/server.cjs) na porta 3000, como um serviço
gerenciado pela própria Phoenix - igual ela já faz com os containers
Docker. Se o processo cair, reinicia sozinho. O log do Node é
espelhado no LogsEngine da Phoenix, então dá pra acompanhar tudo pelo
painel em vez de uma janela escondida.

Chamado pelo kernel.py durante o boot() e parado no shutdown().
Coloque este arquivo em: phoenix_kernel/07_services/platform_process.py
"""

from __future__ import annotations
import asyncio
import os
import sys
from pathlib import Path

PLATFORM_SOURCE = Path("platform_source")
SERVER_REL_PATH = Path("dist") / "server.cjs"
PLATFORM_PORT = 3000

_process: asyncio.subprocess.Process | None = None
_supervise_task: asyncio.Task | None = None
_stopping = False


def is_available() -> bool:
    return (PLATFORM_SOURCE / SERVER_REL_PATH).exists()


async def _stream_log(stream: asyncio.StreamReader, logs_engine):
    while True:
        line = await stream.readline()
        if not line:
            break
        text = line.decode(errors="replace").rstrip()
        if text:
            logs_engine.add_event("INFO", "AviaryPlatform", text)


async def _supervise(logs_engine):
    global _process, _stopping
    backoff = 3
    while not _stopping:
        logs_engine.add_event(
            "INFO", "PlatformProcess",
            f"Iniciando Aviary Platform (node {SERVER_REL_PATH}) na porta {PLATFORM_PORT}..."
        )
        env = os.environ.copy()
        env["PORT"] = str(PLATFORM_PORT)

        try:
            _process = await asyncio.create_subprocess_exec(
                "node", str(SERVER_REL_PATH),
                cwd=PLATFORM_SOURCE,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.STDOUT,
                env=env,
            )
        except FileNotFoundError:
            logs_engine.add_event("ERROR", "PlatformProcess", "Node.js não encontrado no PATH. Abortando supervisão.")
            return

        await _stream_log(_process.stdout, logs_engine)
        exit_code = await _process.wait()

        if _stopping:
            logs_engine.add_event("INFO", "PlatformProcess", "Platform encerrada (shutdown solicitado).")
            return

        logs_engine.add_event(
            "WARNING", "PlatformProcess",
            f"Processo caiu (código {exit_code}). Reiniciando em {backoff}s..."
        )
        await asyncio.sleep(backoff)


def start_supervised(logs_engine) -> asyncio.Task:
    """Dispara a task de supervisão em background. Não bloqueia o boot."""
    global _supervise_task, _stopping
    _stopping = False
    _supervise_task = asyncio.create_task(_supervise(logs_engine))
    return _supervise_task


async def stop():
    global _process, _supervise_task, _stopping
    _stopping = True
    if _process and _process.returncode is None:
        _process.terminate()
        try:
            await asyncio.wait_for(_process.wait(), timeout=5)
        except asyncio.TimeoutError:
            _process.kill()
    if _supervise_task:
        _supervise_task.cancel()
