from typing import List
from .base_builder import ICommandBuilder
from phoenix_kernel.runtime.contracts.model_contracts import ModelDescriptor, GenerationProfile, MissingComponent

class SD15Builder(ICommandBuilder):
    def build(self, exe_path: str, desc: ModelDescriptor, profile: GenerationProfile, prompt: str, output_file: str) -> List[str]:
        # PHX-FIX (varredura 2026-08-21 rodada 3, achado secundário -
        # subsistema `runtime/{pipeline,builders,executors,contracts}/`
        # confirmado morto/não-importado pelo sd_cpp.py real, mas corrigido
        # por consistência com o resto do projeto): ao contrário de
        # FluxBuilder (que valida `desc.components[comp].exists()` antes de
        # montar o comando), este builder usava `desc.model_path` sem checar
        # se o arquivo existe - um caminho de modelo inválido só falharia
        # depois, dentro do subprocess do sd-cli, com um erro menos claro.
        # Agora falha cedo com a mesma exceção que FluxBuilder usa.
        if not desc.model_path or not desc.model_path.exists():
            raise MissingComponent(f"SD1.5 requires 'model_path' which is missing or invalid: {desc.model_path}")

        # Comandos auditados para SD 1.5
        return [
            exe_path,
            "-m", str(desc.model_path),
            "-p", prompt,
            "-o", output_file,
            "-H", str(profile.height),
            "-W", str(profile.width),
            "--steps", str(profile.steps) # README: -s é seed, --steps é o correto
        ]