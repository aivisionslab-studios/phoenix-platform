#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
BUILD_DIR="${BUILD_DIR:-build-phoenix-vulkan}"
NATIVE_CPU="${NATIVE_CPU:-OFF}"
cd "$ROOT"
echo "Phoenix Llama Runtime Stable - Linux Vulkan build"
echo "GGML_NATIVE=$NATIVE_CPU | BuildDir=$BUILD_DIR"
cmake -S . -B "$BUILD_DIR" -DGGML_VULKAN=ON -DGGML_NATIVE="$NATIVE_CPU" -DCMAKE_BUILD_TYPE=Release
cmake --build "$BUILD_DIR" --config Release -j "$(nproc 2>/dev/null || echo 4)"
SERVER="$ROOT/$BUILD_DIR/bin/llama-server"
python3 "$ROOT/phoenix_runtime/verify_cli_contract.py" --server "$SERVER"
"$SERVER" --list-devices
printf '[OK] Phoenix Llama Runtime Stable compilado: %s\n' "$SERVER"
