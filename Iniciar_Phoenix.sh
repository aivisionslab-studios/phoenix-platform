#!/usr/bin/env bash
set -u
cd "$(dirname "$0")" || exit 1

VENV_PYTHON=".venv/bin/python"
STORAGE_JSON="/etc/phoenix/storage.json"
INSTALLER="./install_phoenix.ps1"

pause_on_error() {
    if [ -t 0 ]; then
        read -rp "Pressione Enter para sair..."
    fi
}

validate_venv() {
    [ -f "$VENV_PYTHON" ] && "$VENV_PYTHON" --version >/dev/null 2>&1
}

validate_storage() {
    [ -f "$STORAGE_JSON" ] || return 1

    "$VENV_PYTHON" - "$STORAGE_JSON" <<'PY' >/dev/null 2>&1
import json
import os
import sys
from pathlib import Path

storage_file = Path(sys.argv[1])
try:
    data = json.loads(storage_file.read_text(encoding="utf-8"))
except Exception:
    raise SystemExit(1)

workspace = data.get("workspace")
if not isinstance(workspace, str) or not workspace.strip():
    raise SystemExit(1)

path = Path(workspace).expanduser()
if not path.is_dir():
    raise SystemExit(1)

if not os.access(path, os.R_OK | os.X_OK):
    raise SystemExit(1)

raise SystemExit(0)
PY
}

repair_once() {
    echo ""
    echo "[!] Estado da Phoenix precisa ser reparado."
    echo "    Executando o instalador uma vez para redetectar/recriar o ambiente..."
    echo ""

    [ -f "$INSTALLER" ] || {
        echo "[X] Instalador nao encontrado: $INSTALLER"
        return 1
    }

    command -v pwsh >/dev/null 2>&1 || {
        echo "[X] PowerShell 7 (pwsh) nao encontrado."
        return 1
    }

    if [ "$(id -u)" -eq 0 ]; then
        pwsh "$INSTALLER"
    else
        command -v sudo >/dev/null 2>&1 || {
            echo "[X] sudo nao encontrado. Rode manualmente:"
            echo "    sudo pwsh ./install_phoenix.ps1"
            return 1
        }
        sudo pwsh "$INSTALLER"
    fi
}

if ! validate_venv; then
    echo ""
    echo "[!] Ambiente virtual ausente ou quebrado. Tentando recriar..."
    if ! repair_once || ! validate_venv; then
        echo "[X] Nao foi possivel reparar o ambiente virtual."
        pause_on_error
        exit 1
    fi
fi

if ! validate_storage; then
    echo ""
    echo "[!] storage.json ausente, corrompido ou apontando para um workspace inacessivel."
    echo "    Redetectando o melhor disco (NVMe/SSD/HDD)..."

    if ! repair_once; then
        echo "[X] Falha ao executar o reparo do storage."
        pause_on_error
        exit 1
    fi

    if ! validate_storage; then
        echo "[X] storage.json continua invalido depois do reparo."
        echo "    Arquivo esperado: $STORAGE_JSON"
        echo "    O launcher nao tentara reinstalar novamente nesta execucao."
        pause_on_error
        exit 1
    fi

    echo "[OK] storage.json reparado e workspace validado."
fi

echo ""
echo "[i] Iniciando Phoenix Engine..."
"$VENV_PYTHON" api_server.py
status=$?

if [ "$status" -ne 0 ]; then
    echo ""
    echo "[X] A Phoenix encerrou com erro (codigo $status). Veja as mensagens acima."
    pause_on_error
fi

exit "$status"
