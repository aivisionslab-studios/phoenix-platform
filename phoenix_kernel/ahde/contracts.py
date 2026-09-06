# phoenix_kernel/ahde/contracts.py
import uuid
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum, auto
from typing import Any, Dict, List, Optional

# Versionamento centralizado
CURRENT_SCHEMA_VERSION = "1.0"
CURRENT_ENGINE_VERSION = "10.0"

class EventType(Enum):
    HARDWARE_CHANGED = auto()
    TELEMETRY_UPDATED = auto()
    MODELS_CHANGED = auto()
    SERVICES_CHANGED = auto()
    HEALTH_CHANGED = auto()
    CAPABILITY_CHANGED = auto()

class EventPriority(Enum):
    HIGH = 1
    NORMAL = 2
    LOW = 3

@dataclass(frozen=True, slots=True)
class CapabilitySnapshot:
    """Tipagem forte para capacidades da máquina."""
    vulkan: bool = False
    cuda: bool = False
    rocm: bool = False
    opencl: bool = False
    docker: bool = False
    wsl: bool = False
    virtualization: bool = False
    ollama: bool = False
    llamacpp: bool = False

@dataclass(frozen=True, slots=True)
class HardwareSnapshot:
    """Dados estáticos ou que mudam raramente."""
    machine_id: str
    timestamp: str
    hardware: Dict[str, Any]
    drivers: Dict[str, Any]
    services: Dict[str, Any]
    models: List[Dict[str, Any]]
    capabilities: CapabilitySnapshot
    schema_version: str = CURRENT_SCHEMA_VERSION
    engine_version: str = CURRENT_ENGINE_VERSION
    snapshot_id: str = field(default_factory=lambda: str(uuid.uuid4()))

@dataclass(frozen=True, slots=True)
class TelemetrySnapshot:
    """Dados voláteis que mudam várias vezes por segundo."""
    machine_id: str
    timestamp: str
    telemetry: Dict[str, Any]
    schema_version: str = CURRENT_SCHEMA_VERSION

@dataclass(frozen=True, slots=True)
class ChangeSet:
    hardware_changed: bool = False
    telemetry_changed: bool = False
    models_changed: bool = False
    changed_fields: List[str] = field(default_factory=list)

@dataclass(frozen=True, slots=True)
class DiscoveryEvent:
    event_type: EventType
    payload: Any
    timestamp: str
    priority: EventPriority = EventPriority.NORMAL
    event_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    correlation_id: str = ""
    trace_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    source: str = "AHDE"
    machine_id: str = ""
    schema_version: str = CURRENT_SCHEMA_VERSION
