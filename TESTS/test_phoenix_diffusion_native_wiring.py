from __future__ import annotations

import inspect
import json
import os
from pathlib import Path

import pytest

from phoenix_kernel.runtime.drivers.phoenix_diffusion import (
    NativeWorkerExitedError,
    PhoenixDiffusionDriver,
    _native_placement_candidates,
    _native_placement_defaults,
)
from phoenix_kernel.runtime.native import phoenix_sd_native


ROOT = Path(__file__).resolve().parents[1]


def test_runtime_registers_native_phoenix_diffusion() -> None:
    source = (ROOT / "phoenix_kernel/runtime/engine.py").read_text(encoding="utf-8")
    assert "from .drivers.phoenix_diffusion import PhoenixDiffusionDriver" in source
    assert '("sdxl", lambda: PhoenixDiffusionDriver(' in source
    assert "SdCppDriver" not in source


def test_driver_has_no_cli_or_http_runtime() -> None:
    source = inspect.getsource(PhoenixDiffusionDriver)
    assert "create_subprocess" not in source
    assert "subprocess.run" not in source
    assert "sd-cli.exe" not in source
    assert "repos/stable-diffusion.cpp" not in source
    assert "multiprocessing.get_context" in source


def test_ctypes_abi_matches_public_header_shape() -> None:
    assert len(phoenix_sd_native._LoadConfig._fields_) == 22
    assert len(phoenix_sd_native._GenerateConfig._fields_) == 16
    header = (ROOT / "src/phoenix-diffusion.cpp/phoenix/include/phoenix_sd_bridge.h").read_text(encoding="utf-8")
    for symbol in ("phx_sd_create", "phx_sd_load_model", "phx_sd_generate", "phx_sd_free_image", "phx_sd_cancel"):
        assert symbol in header
    assert [name for name, _ in phoenix_sd_native._LoadConfig._fields_][-2:] == [
        "llm_path", "vae_format",
    ]


def test_fork_is_self_contained_and_installer_does_not_clone_old_runtime() -> None:
    assert (ROOT / "src/phoenix-diffusion.cpp/ggml/CMakeLists.txt").is_file()
    installer = (ROOT / "install/common.ps1").read_text(encoding="utf-8")
    assert '"stable-diffusion.cpp" = "https://github.com/leejet/stable-diffusion.cpp"' not in installer
    assert "build_windows_rx580.ps1" in installer
    catalog = json.loads((ROOT / "catalog/connectors.json").read_text(encoding="utf-8"))
    assert "stable-diffusion.cpp" not in catalog
    assert catalog["phoenix-diffusion"]["provider"] == "bundled"


def test_launcher_repairs_missing_bridge_before_starting_api() -> None:
    launcher = (ROOT / "Iniciar_Phoenix.bat").read_text(encoding="utf-8")
    build_script = (ROOT / "src/phoenix-diffusion.cpp/scripts/build_windows_rx580.ps1").read_text(encoding="utf-8")
    presets = (ROOT / "src/phoenix-diffusion.cpp/CMakePresets.json").read_text(encoding="utf-8")
    installer = (ROOT / "install/common.ps1").read_text(encoding="utf-8")

    assert 'goto :check_diffusion' in launcher
    assert 'bin\\phoenix_sd_bridge.dll' in launcher
    assert 'build_windows_rx580.ps1' in launcher
    assert ':diffusion_repair_failed' in launcher

    # O reparo usa gerador compatível com a versão instalada do VS, elimina
    # cache de outra pasta e promove a DLL para um caminho estável do runtime.
    assert 'Get-PhoenixVsGenerator' in build_script
    assert 'Remove-Item -Recurse -Force $BuildDir' in build_script
    assert 'Copy-Item -Force $Dll.FullName $StableDll' in build_script
    assert 'PHOENIX_BUILD_BRIDGE=ON' in build_script
    assert 'Join-Path $env:SystemDrive "pxb"' in build_script
    assert 'Join-Path $ShortBuildRoot "phxsd"' in build_script
    assert '$BuildDir = Join-Path $Root "build\\windows-rx580-vulkan"' not in build_script
    assert '-DSD_VULKAN=ON' in build_script
    assert '-DGGML_VULKAN=ON' not in build_script
    assert "'-DCMAKE_CXX_FLAGS=/bigobj /EHsc'" in build_script
    assert '--parallel $Jobs' in build_script
    assert 'verify_bridge.py' in build_script
    assert '"binaryDir": "$env{SystemDrive}/pxb/phxsd"' in presets
    assert '"SD_VULKAN": "ON"' in presets
    assert '"CMAKE_CXX_FLAGS": "/bigobj /EHsc"' in presets
    assert '"jobs": 4' in presets

    # A instalação não pode mais reportar silêncio/OK quando esse core falta.
    assert '$commonWarnings += "Phoenix Diffusion Bridge ausente' in installer
    assert '$commonWarnings += "Phoenix Diffusion Bridge falhou ao compilar' in installer
    assert 'phoenix_diffusion_vulkan' in installer
    assert 'build_windows_rx580.ps1") -Force' in installer
    diffusion_block = installer[installer.index("COMPILAÇÃO DO PHOENIX DIFFUSION NATIVO"):installer.index("COMPILAÇÃO DO WHISPER.CPP")]
    assert '-DSD_VULKAN=ON' in diffusion_block
    assert '-DGGML_VULKAN=ON' not in diffusion_block


def test_missing_bridge_error_points_to_the_real_repair_entrypoint() -> None:
    source = inspect.getsource(PhoenixDiffusionDriver)
    assert "install.ps1" not in source
    assert "Reparar_Phoenix_Diffusion.bat" in source


@pytest.mark.asyncio
async def test_startup_error_is_preserved_for_runtime_engine(monkeypatch: pytest.MonkeyPatch) -> None:
    driver = PhoenixDiffusionDriver()
    monkeypatch.setattr(driver, "_find_bridge", lambda: None)
    assert not await driver.start()
    assert "Reparar_Phoenix_Diffusion.bat" in driver.startup_error


def test_flux_cli_compatibility_flags_are_translated_for_the_c_api() -> None:
    placement = _native_placement_defaults({
        "extra_flags": ["--vae-on-cpu", "--clip-on-cpu", "--offload-to-cpu"],
    })
    assert placement == {
        "backend": "all=gpu,te=cpu,vae=cpu",
        "params_backend": "*=cpu",
        "auto_fit": False,
        "max_vram": None,
        "stream_layers": False,
    }


def test_profile_without_cpu_aliases_keeps_automatic_placement() -> None:
    assert _native_placement_defaults({"extra_flags": []}) == {
        "backend": None,
        "params_backend": None,
        "auto_fit": True,
        "max_vram": "-0.75",
        "stream_layers": True,
    }


def test_flux_ladder_contains_supported_cpu_gpu_hybrid_modes() -> None:
    candidates = _native_placement_candidates(
        {
            "name": "flux1-schnell",
            "extra_flags": ["--vae-on-cpu", "--clip-on-cpu", "--offload-to-cpu"],
            "native_overrides": {"mmap": False, "stream_layers": False},
        },
        {},
    )
    assert [name for name, _ in candidates] == [
        "hybrid-cpu-gpu", "auto-fit", "hybrid-streaming", "text-encoder-disk",
    ]
    compat = candidates[0][1]
    assert compat["params_backend"] == "*=cpu"
    assert compat["max_vram"] is None
    assert compat["stream_layers"] is False
    assert compat["enable_mmap"] is True
    streaming = candidates[2][1]
    assert streaming["backend"] == "all=gpu,te=cpu,vae=cpu"
    assert streaming["params_backend"] == "*=cpu"
    assert streaming["max_vram"] == "-2.0"
    assert streaming["stream_layers"] is True
    assert "gpu&cpu" not in streaming["backend"]


def test_manual_native_placement_disables_flux_ladder() -> None:
    candidates = _native_placement_candidates(
        {"name": "flux1-schnell", "extra_flags": ["--offload-to-cpu"]},
        {"backend": "vulkan0", "params_backend": "disk"},
    )
    assert len(candidates) == 1
    assert candidates[0][0] == "configurado"


def test_z_image_uses_modern_llm_abi_and_hybrid_fallback() -> None:
    from phoenix_kernel.runtime.drivers.sd_cpp import _select_profile

    profile = _select_profile("z_image_turbo-Q4_K.gguf")
    assert profile["name"] == "z-image-turbo"
    assert ("--llm", ["qwen3-4b-instruct-2507", "qwen_3_4b"]) in profile["components"]
    assert profile["vae_format"] == 0
    assert profile["default_steps"] == 8
    candidates = _native_placement_candidates(profile, {})
    assert candidates[0][0] == "hybrid-cpu-gpu"
    assert candidates[0][1]["backend"] == "all=gpu,te=cpu,vae=cpu"
    assert candidates[2][0] == "hybrid-streaming"

    asset = json.loads(
        (ROOT / "catalog/assets/z-image-turbo.json").read_text(encoding="utf-8")
    )
    assert asset["filename"] == "z_image_turbo-Q4_K.gguf"
    assert asset["dependencies"] == ["flux_vae", "z-image-qwen3-4b"]


def test_worker_exit_error_is_never_blank() -> None:
    error = NativeWorkerExitedError("processo nativo encerrou: 0xC0000005")
    assert str(error)


def test_model_change_restarts_the_isolated_worker() -> None:
    source = inspect.getsource(PhoenixDiffusionDriver.execute)
    switch = source[source.index("if signature != self._loaded_signature"):
                    source.index("output_dir = self._project_root")]
    assert "await self.stop()" in switch
    assert "await self.start(plan)" in switch
    assert "liberar integralmente contexto, DLL e estado Vulkan" in switch


def test_active_installer_and_knowledge_base_use_current_sd_cmake_option() -> None:
    installer = (ROOT / "install/common.ps1").read_text(encoding="utf-8")
    block = installer[installer.index("COMPILAÇÃO DO PHOENIX DIFFUSION NATIVO"):installer.index("COMPILAÇÃO DO WHISPER.CPP")]
    assert "-DSD_VULKAN=ON" in block
    assert "-DGGML_VULKAN=ON" not in block
    knowledge = json.loads((ROOT / "data/knowledge_base.json").read_text(encoding="utf-8"))
    stable = next(item for item in knowledge if item.get("id") == "config_003_sdcpp_compilar_vulkan")
    assert "-DSD_VULKAN=ON" in stable["flags"]["cmake_build"]


def test_image_pipeline_messages_are_not_attributed_to_the_chat_llm() -> None:
    source = (ROOT / "platform_source/src/components/aviary/AviaryApp.tsx").read_text(encoding="utf-8")
    image_branch = source[source.index("if (isImageGenerationIntent)"):source.index("await sendToProvider(updatedMessages)")]
    assert image_branch.count("modelId: 'Phoenix Diffusion'") == 2
    assert image_branch.count("excludeFromHistory: true") == 2


def test_driver_name_and_version_are_phoenix_45() -> None:
    assert PhoenixDiffusionDriver().name == "phoenix-diffusion"
    api = (ROOT / "api_server.py").read_text(encoding="utf-8")
    runtime = (ROOT / "phoenix_kernel/runtime/engine.py").read_text(encoding="utf-8")
    assert 'version="4.5.0"' in api
    assert 'version="4.5.0"' in runtime


@pytest.mark.asyncio
async def test_real_bridge_starts_in_isolated_worker_when_available(monkeypatch: pytest.MonkeyPatch) -> None:
    library = os.environ.get("PHOENIX_SD_BRIDGE_TEST_LIBRARY")
    if not library:
        pytest.skip("bridge compilada não fornecida para este ambiente")
    monkeypatch.setenv("PHOENIX_SD_BRIDGE", library)
    driver = PhoenixDiffusionDriver()
    try:
        assert await driver.start()
        status = await driver.status()
        assert status.health == "healthy"
        assert str(status.metrics.get("version", "")).startswith("phoenix-sdcpp-native/")
    finally:
        assert await driver.stop()
