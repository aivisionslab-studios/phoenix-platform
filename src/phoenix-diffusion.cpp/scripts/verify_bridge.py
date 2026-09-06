"""Valida carregamento e ABI mínima da Phoenix Diffusion compilada."""

from __future__ import annotations

import ctypes
import sys
from pathlib import Path


EXPECTED_BRIDGE_VERSION = "phoenix-sdcpp-native/0.2.0"


def main() -> int:
    if len(sys.argv) != 2:
        print("[ERRO] Uso: verify_bridge.py <phoenix_sd_bridge.dll>")
        return 2

    library_path = Path(sys.argv[1]).resolve()
    if not library_path.is_file() or library_path.stat().st_size <= 0:
        print(f"[ERRO] DLL ausente ou vazia: {library_path}")
        return 3

    try:
        dll = ctypes.CDLL(str(library_path))
        dll.phx_sd_bridge_version.restype = ctypes.c_char_p
        dll.phx_sd_system_info.restype = ctypes.c_char_p
        dll.phx_sd_create.restype = ctypes.c_void_p
        dll.phx_sd_destroy.argtypes = [ctypes.c_void_p]

        version_raw = dll.phx_sd_bridge_version()
        version = version_raw.decode("utf-8", "replace") if version_raw else "desconhecida"
        if version != EXPECTED_BRIDGE_VERSION:
            raise RuntimeError(
                f"ABI incompatível: encontrada {version!r}; "
                f"esperada {EXPECTED_BRIDGE_VERSION!r}"
            )
        handle = dll.phx_sd_create()
        if not handle:
            raise RuntimeError("phx_sd_create retornou ponteiro nulo")
        dll.phx_sd_destroy(handle)

        # Também força o registro dos backends estáticos. Uma falha ao carregar
        # Vulkan ou outra dependência do GGML aparece aqui, antes de abrir a API.
        dll.phx_sd_system_info()
        print(f"[PASS] ABI Phoenix Diffusion carregada: {version}")
        return 0
    except BaseException as exc:
        print(f"[ERRO] Não foi possível carregar/testar {library_path}: {type(exc).__name__}: {exc}")
        return 4


if __name__ == "__main__":
    raise SystemExit(main())
