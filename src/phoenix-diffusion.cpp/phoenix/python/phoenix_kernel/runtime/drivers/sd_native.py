from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from phoenix_kernel.runtime.native.phoenix_sd_native import (
    GenerationConfig,
    ModelConfig,
    PhoenixSdNative,
)


@dataclass(slots=True)
class ImageResourcePlan:
    """Resource decisions made upstream by Phoenix orchestration."""
    backend: str = ""
    params_backend: str = ""
    max_vram: str = ""
    split_mode: str = ""
    auto_fit: bool = False
    stream_layers: bool = False


class SdNativeDriver:
    """Resident stable-diffusion.cpp runtime for Phoenix.

    This driver deliberately contains no hardware policy. The central Phoenix
    planner supplies an ImageResourcePlan after inspecting intent, model,
    hardware, and current resource state.
    """

    runtime_name = "sd-native"

    def __init__(self, bridge_dll: str | Path):
        self.native = PhoenixSdNative(bridge_dll)
        self._model_key: Optional[tuple] = None

    def load(self, *, model_path: str = "", diffusion_model_path: str = "",
             clip_l_path: str = "", clip_g_path: str = "", t5xxl_path: str = "",
             vae_path: str = "", resource_plan: ImageResourcePlan | None = None,
             n_threads: int = -1) -> None:
        rp = resource_plan or ImageResourcePlan()
        key = (
            model_path, diffusion_model_path, clip_l_path, clip_g_path, t5xxl_path, vae_path,
            rp.backend, rp.params_backend, rp.max_vram, rp.split_mode, rp.auto_fit, rp.stream_layers,
        )
        if self.native.is_loaded and self._model_key == key:
            return

        self.native.load_model(ModelConfig(
            model_path=model_path or None,
            diffusion_model_path=diffusion_model_path or None,
            clip_l_path=clip_l_path or None,
            clip_g_path=clip_g_path or None,
            t5xxl_path=t5xxl_path or None,
            vae_path=vae_path or None,
            backend=rp.backend or None,
            params_backend=rp.params_backend or None,
            max_vram=rp.max_vram or None,
            split_mode=rp.split_mode or None,
            auto_fit=rp.auto_fit,
            stream_layers=rp.stream_layers,
            n_threads=n_threads,
        ))
        self._model_key = key

    def generate(self, prompt: str, *, output_path: str | Path,
                 negative_prompt: str = "", width: int = 512, height: int = 512,
                 steps: int = 20, cfg_scale: float = 7.0, seed: int = 42,
                 sampler: str = "", scheduler: str = "", vae_tiling: bool = False) -> Path:
        image = self.native.generate(GenerationConfig(
            prompt=prompt,
            negative_prompt=negative_prompt,
            width=width,
            height=height,
            steps=steps,
            cfg_scale=cfg_scale,
            seed=seed,
            sampler=sampler,
            scheduler=scheduler,
            vae_tiling=vae_tiling,
        ))
        output = Path(output_path)
        output.parent.mkdir(parents=True, exist_ok=True)
        image.save_png(output)
        return output

    def unload(self) -> None:
        self.native.unload_model()
        self._model_key = None

    def stop(self) -> None:
        self.unload()

    def close(self) -> None:
        self.native.close()
