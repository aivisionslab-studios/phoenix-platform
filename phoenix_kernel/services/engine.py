#\phoenix_kernel\services\engine.py

import asyncio
import shutil
import urllib.request
import json
import logging
from pathlib import Path
from typing import Any
from .interfaces import IServicesService
from .provisioning import ProvisioningManager
from .package_manager import PackageManager

logger = logging.getLogger(__name__)

def _find_engine_binary(repo_dir: str, names: list[str]) -> bool:
    """Procura um binário compilado nas pastas conhecidas do projeto (Windows/Linux)
    ANTES de cair pro PATH do sistema. Os binários do llama.cpp/Phoenix Diffusion
    são compilados dentro de repos/<projeto>/build/bin/(Release/) e NUNCA são
    adicionados ao PATH do Windows — então shutil.which() sozinho sempre falha aqui,
    mesmo com o binário presente e funcional."""
    for name in names:
        # Windows (Visual Studio / MSVC, config Release)
        if (Path(repo_dir) / "build" / "bin" / "Release" / f"{name}.exe").exists():
            return True
        # Linux (GCC/Clang)
        if (Path(repo_dir) / "build" / "bin" / name).exists():
            return True
        # Fallback: PATH do sistema (caso o usuário tenha instalado globalmente)
        if shutil.which(name):
            return True
    if "phoenix_sd_bridge" in names:
        return any((Path(repo_dir) / relative).exists() for relative in (
            "build/windows-rx580-vulkan/bin/Release/phoenix_sd_bridge.dll",
            "build/windows-rx580-vulkan/bin/phoenix_sd_bridge.dll",
            "build/bin/libphoenix_sd_bridge.so",
            "build/bin/libphoenix_sd_bridge.dylib",
        ))
    return False

class ServicesEngine(IServicesService):
    def __init__(self, budget_engine=None):
        self.provisioning = ProvisioningManager()
        # Injeção do Budget para checar requisitos no futuro
        self.packages = PackageManager(budget_engine)

    async def get_environment_status(self) -> dict[str, Any]:
        loop = asyncio.get_running_loop()
        def check():
            env = {
                "docker": shutil.which("docker") is not None,
                "python": True,
                "vulkan": shutil.which("vulkaninfo") is not None,
                "llama_cpp": _find_engine_binary("repos/llama.cpp", ["llama-server", "llama-cli"]),
                "phoenix_diffusion": _find_engine_binary("src/phoenix-diffusion.cpp", ["phoenix_sd_bridge"]),
                "ollama": False,
                "openai": False,
                "mcp": False
            }
            try:
                with urllib.request.urlopen("http://localhost:11434/api/version", timeout=1) as r:
                    env["ollama"] = r.status == 200
            except: pass
            return env
        return await loop.run_in_executor(None, check)

    async def install_service(self, target: str) -> str:
        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(None, self.provisioning.install, target)

    async def install_package(self, package_name: str) -> str:
        return await self.packages.install_package(package_name)
