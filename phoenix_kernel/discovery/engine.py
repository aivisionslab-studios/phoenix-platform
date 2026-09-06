import asyncio
import logging
import platform
from typing import Any
from .interfaces import IDiscoveryService
from .providers.factory import get_discovery_provider

logger = logging.getLogger(__name__)

class DiscoveryEngine(IDiscoveryService):
    def __init__(self):
        self.provider = get_discovery_provider()
        self._profile = None

    async def discover_hardware(self) -> dict[str, Any]:
        logger.info("Kernel Discovery: Iniciando descoberta via Provider...")
        loop = asyncio.get_running_loop()
        
        snapshot = await loop.run_in_executor(None, self.provider.discover)
        
        data = {
            'os': {
                'system': platform.system(),
                'release': platform.release(),
                'machine': platform.machine(),
                'processor': snapshot.cpu.model
            },
            'cpu': {
                'model': snapshot.cpu.model or 'Unknown CPU', 
                'cores': snapshot.cpu.physical_cores or 1
            },
            'memory': {
                'total_mb': snapshot.memory.total_mb or 0
            },
            'gpus': [
                {
                    'model': g.model,
                    'vram_mb': g.vram_mb,
                    'vendor': g.vendor,
                    'supports_vulkan': g.supports_vulkan
                } for g in (snapshot.gpus or [])
            ],
            'storage': [
                {
                    'model': s.model,
                    'size_gb': s.size_gb,
                    'type': s.type,
                    'interface': s.interface
                } for s in (snapshot.storage or [])
            ],
            'motherboard': {
                'model': snapshot.motherboard.model if snapshot.motherboard else 'Unknown',
                'vendor': snapshot.motherboard.vendor if snapshot.motherboard else 'Unknown'
            },
            'available_backends': snapshot.available_backends
        }
        
        return data
