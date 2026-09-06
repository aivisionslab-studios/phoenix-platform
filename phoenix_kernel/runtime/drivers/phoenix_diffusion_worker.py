"""Processo isolado que hospeda a bridge nativa Phoenix Diffusion.

Uma falha de driver Vulkan/C++ não pode derrubar o servidor FastAPI. Por isso a
DLL/SO e o modelo residente vivem neste processo, nunca no processo principal.
"""

from __future__ import annotations

from multiprocessing.connection import Connection
from typing import Any

from phoenix_kernel.runtime.native.phoenix_sd_native import (
    GenerationConfig,
    ModelConfig,
    PhoenixSdNative,
)


def run_worker(connection: Connection, library_path: str) -> None:
    native: PhoenixSdNative | None = None
    try:
        native = PhoenixSdNative(library_path)
        connection.send({
            "ok": True,
            "event": "ready",
            "version": native.version,
            "system_info": native.system_info,
        })
        while True:
            request: dict[str, Any] = connection.recv()
            command = request.get("command")
            try:
                if command == "load":
                    native.load_model(ModelConfig(**request["config"]))
                    connection.send({"ok": True, "loaded": native.is_loaded})
                elif command == "generate":
                    image = native.generate(GenerationConfig(**request["config"]))
                    image.save_png(request["output_file"])
                    connection.send({
                        "ok": True,
                        "width": image.width,
                        "height": image.height,
                        "channels": image.channels,
                    })
                elif command == "status":
                    connection.send({"ok": True, "loaded": native.is_loaded})
                elif command == "unload":
                    native.unload_model()
                    connection.send({"ok": True, "loaded": False})
                elif command == "close":
                    connection.send({"ok": True})
                    return
                else:
                    connection.send({"ok": False, "error": f"comando desconhecido: {command}"})
            except BaseException as exc:
                connection.send({"ok": False, "error": f"{type(exc).__name__}: {exc}"})
    except BaseException as exc:
        try:
            connection.send({"ok": False, "event": "startup", "error": f"{type(exc).__name__}: {exc}"})
        except BaseException:
            pass
    finally:
        if native is not None:
            native.close()
        connection.close()
