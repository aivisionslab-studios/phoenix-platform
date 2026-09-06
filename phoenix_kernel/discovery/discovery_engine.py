import asyncio
import logging
from typing import Any
from .interfaces import IDiscoveryService

# O import mudou: agora lê o discovery_core.py que está na mesma pasta
from .discovery_core import HardwareDiscoveryCore

logger = logging.getLogger(__name__)

class DiscoveryEngine(IDiscoveryService):
    def __init__(self):
        self._core = HardwareDiscoveryCore()
        self._profile = None

    async def discover_hardware(self) -> dict[str, Any]:
        logger.info("Kernel Discovery: Iniciando descoberta via HardwareDiscoveryCore...")
        loop = asyncio.get_running_loop()
        
        # Roda o bloqueio do WMI/dxdiag numa thread separada para não travar o Kernel
        self._profile = await loop.run_in_executor(None, self._core.discover)
        
        hw = self._profile.hardware
        
        backends = ["cpu"]
        if any(g.supports_vulkan for g in hw.gpus):
            backends.append("vulkan")

        data = {
            'os': {
                'system': hw.operating_system.name if hasattr(hw, 'operating_system') and hw.operating_system else 'Unknown', 
                'release': hw.operating_system.version if hasattr(hw, 'operating_system') and hw.operating_system else 'Unknown',
                'machine': hw.operating_system.architecture if hasattr(hw, 'operating_system') and hw.operating_system else 'Unknown',
                'processor': hw.cpu.model
            },
            'cpu': {
                'model': hw.cpu.model or 'Unknown CPU', 
                'cores': hw.cpu.physical_cores or 1
            },
            'memory': {
                'total_mb': hw.memory.total_mb or 0
            },
            'gpus': [
                {
                    'model': g.model,
                    'vram_mb': g.vram_mb,
                    'vendor': g.vendor,
                    'supports_vulkan': g.supports_vulkan
                } for g in hw.gpus
            ],
            'available_backends': backends
        }
        
        # Extrai o Machine ID com segurança do objeto profile
        machine_id = "UNKNOWN"
        if hasattr(self._profile, 'machine_identity') and self._profile.machine_identity:
            machine_id = self._profile.machine_identity.machine_id
            
        logger.info(f"Kernel Discovery: Machine ID: {machine_id}")
        return data

    def get_machine_id(self) -> str:
        """Id estável da máquina (hash de CPU+RAM+GPU, calculado em
        discovery_core.py). Usado pelo FirestoreSync pra separar os dados
        de cada instalação da Phoenix dentro do mesmo projeto Firestore."""
        if self._profile and hasattr(self._profile, "machine_identity") and self._profile.machine_identity:
            return self._profile.machine_identity.machine_id
        return "AHDC-UNKNOWN-0000-0000"