"""
setup_platform.py
==================
Automatiza o BUILD da Phoenix Aviary Platform (app exportado do Google
AI Studio) para que o usuário final nunca precise rodar `npm` na mão.

IMPORTANTE (correção de arquitetura): essa Platform NÃO é um site
estático. Ela roda um servidor Node.js próprio (`dist/server.cjs`) que
faz o ping dos provedores (Ollama/LM Studio) do lado do servidor -
por isso ela evita CORS sem precisar mexer no Ollama. Isso significa
que o processo precisa ficar RODANDO, não só "compilado e servido como
arquivo estático". Quem sobe/vigia o processo é o platform_process.py,
chamado pelo kernel.py. Este arquivo aqui cuida só do build.

Fluxo:
  1. Verifica se já existe platform_source/dist/server.cjs -> se sim,
     não builda de novo (custo zero em boots subsequentes).
  2. Verifica/instala Node.js via winget (mesmo padrão do resto da
     Phoenix pra Git/Docker/Vulkan).
  3. Roda `npm install` + `npm run build` dentro de platform_source/.
  4. Confirma que o build gerou dist/server.cjs (se o projeto do AI
     Studio gerar noutro caminho, ajuste SERVER_ENTRY abaixo).
"""

from __future__ import annotations
import subprocess
import sys
from pathlib import Path

PLATFORM_SOURCE = Path("platform_source")
SERVER_ENTRY = PLATFORM_SOURCE / "dist" / "server.cjs"


def _run(cmd: list[str], cwd: Path) -> subprocess.CompletedProcess:
    print(f"[setup_platform] Executando: {' '.join(cmd)} (em {cwd})")
    return subprocess.run(cmd, cwd=cwd, capture_output=True, text=True, shell=(sys.platform == "win32"))


def _server_ts_newer_than_build() -> bool:
    """Retorna True se algum arquivo-fonte (.ts/.tsx/.css) foi modificado
    depois do dist/server.cjs — indica que o build está desatualizado.
    Também detecta mudanças em package.json (nova dependência adicionada).

    PHX-FIX (cross-check contra checklist de auditoria externa 2026-08-20,
    item "instalador precisa sempre detectar build desatualizado"): a
    versão anterior só olhava 4 arquivos fixos (server.ts, package.json,
    src/App.tsx, vite.config.ts) - um allowlist que já nasceu incompleto e
    foi ficando mais errado a cada rodada de correção: nenhuma das rodadas
    6, 7 e 8 desta auditoria (que tocaram AviaryApp.tsx, ChatView.tsx,
    EngineMissionControl.tsx, Header.tsx, types.ts, MetricCards.tsx,
    PortBridgePanel.tsx, AviarySwarmPanel.tsx, etc.) teria disparado
    rebuild nenhum por essa checagem - o instalador reportaria "platform
    já compilada e atualizada" com um dist/server.cjs de meses atrás,
    silenciosamente servindo bugs já corrigidos no fonte. Trocado por um
    rglob real em cima de src/ + os arquivos de nível raiz que importam
    (server.ts, package.json, vite.config.ts) - ainda é só stat(), sem
    ler conteúdo nenhum, então o custo em boots subsequentes continua
    perto de zero mesmo com dezenas de arquivos .ts/.tsx/.css."""
    if not SERVER_ENTRY.exists():
        return False  # não existe → não é "mais novo", é ausente
    build_mtime = SERVER_ENTRY.stat().st_mtime

    root_sources = [
        PLATFORM_SOURCE / "server.ts",
        PLATFORM_SOURCE / "package.json",
        PLATFORM_SOURCE / "vite.config.ts",
    ]
    for src in root_sources:
        if src.exists() and src.stat().st_mtime > build_mtime:
            print(f"[setup_platform] {src.name} foi modificado depois do build — rebuild necessário.")
            return True

    src_dir = PLATFORM_SOURCE / "src"
    if src_dir.exists():
        for pattern in ("*.ts", "*.tsx", "*.css"):
            for src in src_dir.rglob(pattern):
                if src.stat().st_mtime > build_mtime:
                    print(f"[setup_platform] {src.relative_to(PLATFORM_SOURCE)} foi modificado depois do build — rebuild necessário.")
                    return True
    return False


def is_platform_built() -> bool:
    # Não basta o server.cjs existir - se node_modules/express sumir
    # (ex: zip sem node_modules, ou npm install incompleto), o processo
    # crasha com "Cannot find module" mesmo com server.cjs presente.
    # Checar os dois evita a Phoenix achar que "já está pronto" quando
    # na real falta a dependência.
    # PHX-FIX: também verifica se os fontes (.ts/.tsx) foram modificados
    # depois do build — garante que atualizar o server.ts sempre dispara
    # um rebuild, mesmo com o dist/ antigo ainda presente.
    node_modules_ok = (PLATFORM_SOURCE / "node_modules" / "express").exists()
    if not (SERVER_ENTRY.exists() and node_modules_ok):
        return False
    if _server_ts_newer_than_build():
        return False  # forçar rebuild
    return True


def is_node_installed() -> bool:
    try:
        result = subprocess.run(["node", "--version"], capture_output=True, text=True, shell=(sys.platform == "win32"))
        return result.returncode == 0
    except FileNotFoundError:
        return False


def install_node_via_winget() -> bool:
    """Mesmo padrão já usado pela Phoenix pra Git/Docker/Vulkan SDK -
    winget silencioso, sem prompt pro usuário."""
    print("[setup_platform] Node.js não encontrado. Instalando via winget...")
    result = _run(
        ["winget", "install", "-e", "--id", "OpenJS.NodeJS.LTS",
         "--accept-package-agreements", "--accept-source-agreements", "--silent"],
        cwd=Path("."),
    )
    if result.returncode != 0:
        print(f"[setup_platform] FALHA ao instalar Node.js: {result.stderr}")
        return False
    print("[setup_platform] Node.js instalado com sucesso.")
    return True


def build_platform() -> tuple[bool, str]:
    """Retorna (sucesso, mensagem). Nunca levanta exceção - falhas aqui
    não devem derrubar o boot da Phoenix; a Platform só fica indisponível
    até alguém corrigir (platform_process.py trata isso avisando no log
    em vez de tentar subir um server.cjs que não existe)."""
    if is_platform_built():
        return True, "Platform já compilada e atualizada (dist/server.cjs presente e fontes não modificados), nada a fazer."

    if not PLATFORM_SOURCE.exists():
        return False, (
            f"Pasta '{PLATFORM_SOURCE}' não encontrada. Exporte o projeto do "
            f"Google AI Studio (ZIP/GitHub) e extraia para essa pasta antes de "
            f"rodar o build."
        )

    if not is_node_installed():
        if not install_node_via_winget():
            return False, "Não foi possível instalar o Node.js automaticamente."

    result = _run(["npm", "install"], cwd=PLATFORM_SOURCE)
    if result.returncode != 0:
        return False, f"'npm install' falhou: {result.stderr[-500:]}"

    result = _run(["npm", "run", "build"], cwd=PLATFORM_SOURCE)
    if result.returncode != 0:
        return False, f"'npm run build' falhou: {result.stderr[-500:]}"

    if not SERVER_ENTRY.exists():
        return False, (
            f"Build rodou, mas '{SERVER_ENTRY}' não foi gerado. Verifique o "
            f"comando de build do projeto no AI Studio - pode gerar o server "
            f"noutro caminho, e nesse caso ajuste SERVER_ENTRY neste arquivo "
            f"e PLATFORM_SOURCE/SERVER_REL_PATH em platform_process.py."
        )

    return True, "Platform compilada com sucesso (dist/server.cjs pronto)."


if __name__ == "__main__":
    ok, message = build_platform()
    print(f"[setup_platform] {'OK' if ok else 'FALHA'}: {message}")