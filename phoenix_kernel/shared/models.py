from dataclasses import dataclass, field
from typing import Optional, List

@dataclass
class CPUInfo:
    model: str = "Unknown"
    physical_cores: int = 0
    logical_cores: int = 0

@dataclass
class GPUInfo:
    model: str = "Unknown"
    vram_mb: int = 0
    vendor: str = "Unknown"
    supports_vulkan: bool = False

@dataclass
class MemoryInfo:
    total_mb: int = 0

@dataclass
class StorageInfo:
    model: str = "Unknown"
    size_gb: float = 0.0
    type: str = "Unknown"
    interface: str = "Unknown"

@dataclass
class MotherboardInfo:
    model: str = "Unknown"
    vendor: str = "Unknown"

@dataclass
class HardwareSnapshot:
    cpu: CPUInfo = None
    gpus: List[GPUInfo] = None
    memory: MemoryInfo = None
    storage: List[StorageInfo] = None
    motherboard: MotherboardInfo = None
    available_backends: List[str] = None

@dataclass
class TelemetrySnapshot:
    cpu_usage_percent: float = 0.0
    ram_used_mb: int = 0
    gpu_temp_celsius: Optional[float] = None
    gpu_load_percent: Optional[float] = None
    gpu_vram_used_mb: Optional[int] = None
