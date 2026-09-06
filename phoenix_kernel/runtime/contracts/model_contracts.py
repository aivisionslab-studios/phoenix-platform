from enum import Enum
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, Any, Optional, List

class ModelArchitecture(Enum):
    SD15 = "SD15"
    SDXL = "SDXL"
    SDXL_TURBO = "SDXL-Turbo"
    FLUX = "FLUX"

@dataclass(frozen=True)
class GenerationProfile:
    steps: int = 20
    cfg: float = 7.0
    width: int = 512
    height: int = 512
    seed: int = -1

@dataclass
class ModelDescriptor:
    architecture: ModelArchitecture
    model_path: Path
    components: Dict[str, Path]
    generation_profile: GenerationProfile

@dataclass
class RuntimeCapabilities:
    timeout_seconds: int = 900
    default_backend: str = "vulkan"
    vram_mb: int = 8192

class PhoenixRuntimeError(Exception): pass
class ExecutableNotFound(PhoenixRuntimeError): pass
class ModelNotFound(PhoenixRuntimeError): pass
class MissingComponent(PhoenixRuntimeError): pass
class BuilderNotSupported(PhoenixRuntimeError): pass
class GenerationFailed(PhoenixRuntimeError): pass
class CatalogInconsistency(PhoenixRuntimeError): pass
