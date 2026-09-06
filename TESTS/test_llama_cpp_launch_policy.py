"""Regression tests for the 2026-08-30 llama.cpp launch-policy patch.

These tests are intentionally dependency-light: they stub Phoenix domain modules so
this file can validate the driver's argument construction without booting Phoenix.
"""
from __future__ import annotations

import importlib.util
import socket
import sys
import types
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TARGET = ROOT / "phoenix_kernel" / "runtime" / "drivers" / "llama_cpp.py"


def _stub_modules() -> None:
    modules = {
        "core": types.ModuleType("core"),
        "core.domain": types.ModuleType("core.domain"),
        "core.domain.execution": types.ModuleType("core.domain.execution"),
        "core.domain.runtime": types.ModuleType("core.domain.runtime"),
        "phoenix_kernel": types.ModuleType("phoenix_kernel"),
        "phoenix_kernel.paths": types.ModuleType("phoenix_kernel.paths"),
    }
    class Dummy: pass
    modules["core.domain.execution"].ExecutionPlan = Dummy
    modules["core.domain.execution"].ExecutionResult = Dummy
    modules["core.domain.execution"].ExecutionStatus = Dummy
    modules["core.domain.runtime"].RuntimeStatus = Dummy
    modules["core.domain.runtime"].RuntimeState = Dummy
    class PhoenixPaths:
        @staticmethod
        def get_category_path(*_args): return Path(".")
    modules["phoenix_kernel.paths"].PhoenixPaths = PhoenixPaths
    sys.modules.update(modules)


def _load():
    # PHX-FIX (31/08, revisão de segurança): esta função fazia
    # sys.modules.update(...) com módulos FAKE ("core", "phoenix_kernel",
    # "phoenix_kernel.paths" etc) e nunca desfazia isso - qualquer teste que
    # rodasse DEPOIS deste no mesmo processo pytest herdava esses módulos
    # fake no lugar dos reais, quebrando imports legítimos de
    # phoenix_kernel/core em outros arquivos de teste (confirmado: ~13
    # falhas em test_whisper_model_provisioning.py/test_synthesize_speech_
    # bridge.py/etc que só acontecem quando este arquivo roda antes deles na
    # mesma sessão do pytest, e desaparecem rodando cada arquivo isolado).
    # Corrigido salvando e restaurando o estado anterior de sys.modules pras
    # chaves mexidas, sempre - mesmo se exec_module() levantar.
    keys = [
        "core", "core.domain", "core.domain.execution", "core.domain.runtime",
        "phoenix_kernel", "phoenix_kernel.paths",
    ]
    previous = {k: sys.modules.get(k) for k in keys}
    _stub_modules()
    try:
        spec = importlib.util.spec_from_file_location("llama_cpp_under_test", TARGET)
        mod = importlib.util.module_from_spec(spec)
        assert spec and spec.loader
        spec.loader.exec_module(mod)
        return mod
    finally:
        for k, v in previous.items():
            if v is None:
                sys.modules.pop(k, None)
            else:
                sys.modules[k] = v


def test_default_chat_policy_is_unchanged():
    mod = _load()
    d = mod.LlamaCppDriver()
    d._model_alias = "qwen"
    args = d._build_server_args("llama-server", Path("model.gguf"), "0")
    assert "-ngl" in args and args[args.index("-ngl") + 1] == "0"
    assert "--port" in args and args[args.index("--port") + 1] == "8081"
    assert "-c" in args and args[args.index("-c") + 1] == "32768"
    assert "--device" not in args
    assert "-ot" not in args
    assert "--no-op-offload" in args


def test_gpu_worker_arguments_are_explicit_and_local():
    mod = _load()
    d = mod.LlamaCppDriver(
        port=8095,
        force_ngl="999",
        device="Vulkan0",
        tensor_overrides={"output.weight": "CPU", "blk.35.*": "Vulkan0"},
        context_size=4096,
    )
    d._model_alias = "qwen3-8b-q4_k_m"
    args = d._build_server_args("llama-server", Path("qwen.gguf"), "999")
    assert args[args.index("--port") + 1] == "8095"
    assert args[args.index("--device") + 1] == "Vulkan0"
    assert args[args.index("-c") + 1] == "4096"
    override = args[args.index("-ot") + 1]
    assert "output.weight=CPU" in override
    assert "blk.35.*=Vulkan0" in override


def test_dynamic_port_skips_occupied_port():
    mod = _load()
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.bind(("127.0.0.1", 0))
    occupied = sock.getsockname()[1]
    try:
        chosen = mod.find_free_local_port(occupied, min(65535, occupied + 1))
        assert chosen != occupied
    finally:
        sock.close()
