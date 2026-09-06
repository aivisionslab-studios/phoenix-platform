from typing import List
from .base_builder import ICommandBuilder
from phoenix_kernel.runtime.contracts.model_contracts import ModelDescriptor, GenerationProfile, MissingComponent

class FluxBuilder(ICommandBuilder):
    def build(self, exe_path: str, desc: ModelDescriptor, profile: GenerationProfile, prompt: str, output_file: str) -> List[str]:
        # Validação obrigatória dos 4 componentes do FLUX
        required = ["vae", "clip_l", "t5xxl"]
        for comp in required:
            if comp not in desc.components or not desc.components[comp].exists():
                raise MissingComponent(f"FLUX requires component '{comp}' which is missing or invalid.")

        # Comandos auditados no rx580-local-ai-guide (leejet/FLUX.1-schnell-gguf)
        return [
            exe_path,
            "--diffusion-model", str(desc.model_path),
            "--vae", str(desc.components["vae"]),
            "--clip_l", str(desc.components["clip_l"]),
            "--t5xxl", str(desc.components["t5xxl"]),
            "-p", prompt,
            "-o", output_file,
            "--steps", str(profile.steps), # README: -s é seed, --steps é o correto
            "--cfg-scale", str(profile.cfg),
            "--clip-on-cpu",
            "--vae-on-cpu",
            "--vae-tiling" # README: Obrigatório para não causar OOM na RX 580
        ]