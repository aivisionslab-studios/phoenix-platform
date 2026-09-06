# setup_ahde.py
# Script de provisionamento da arquitetura AHDE 10/10
# Uso: python setup_ahde.py

import os
from pathlib import Path

# Cores para o terminal
class C:
    OK = '\033[92m'
    INFO = '\033[96m'
    ENDC = '\033[0m'

def p(status, msg):
    color = C.OK if status == "OK" else C.INFO
    print(f"{color}[{status}]{C.ENDC} {msg}")

# Estrutura de diretórios a serem criados
DIRS = [
    "phoenix_kernel/ahde",
    "phoenix_kernel/ahde/repository",
    "phoenix_kernel/ahde/health",
    "phoenix_kernel/ahde/events",
    "phoenix_kernel/ahde/plugins"
]

# Dicionário com os arquivos e seus conteúdos
FILES = {
    "phoenix_kernel/ahde/__init__.py": "# AHDE 10/10 Module",
    
    "phoenix_kernel/ahde/contracts.py": '''# phoenix_kernel/ahde/contracts.py
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
''',

    "phoenix_kernel/ahde/event_bus.py": '''# phoenix_kernel/ahde/event_bus.py
import asyncio
import logging
from typing import Callable, Dict, List, Set, Tuple
from phoenix_kernel.ahde.contracts import EventType, EventPriority, DiscoveryEvent

logger = logging.getLogger(__name__)

class EventBus:
    """Barramento de eventos assíncrono, não-bloqueante, com ciclo de vida e DI."""
    def __init__(self):
        self._subscribers: Dict[EventType, List[Tuple[EventPriority, Callable]]] = {}
        self._active_tasks: Set[asyncio.Task] = set()

    def subscribe(self, event_type: EventType, callback: Callable, priority: EventPriority = EventPriority.NORMAL):
        if event_type not in self._subscribers:
            self._subscribers[event_type] = []
        self._subscribers[event_type].append((priority, callback))
        logger.info(f"EventBus: Assinante registrado para {event_type.name} (Prioridade: {priority.name})")

    def unsubscribe(self, event_type: EventType, callback: Callable):
        if event_type in self._subscribers:
            self._subscribers[event_type] = [
                (p, cb) for p, cb in self._subscribers[event_type] if cb != callback
            ]

    async def publish(self, event_type: EventType, event: DiscoveryEvent):
        if event_type in self._subscribers:
            subs = sorted(self._subscribers[event_type], key=lambda x: x[0].value)
            for priority, callback in subs:
                try:
                    if asyncio.iscoroutinefunction(callback):
                        # Não-bloqueante: cria task isolada e rastreia
                        task = asyncio.create_task(callback(event))
                        self._active_tasks.add(task)
                        task.add_done_callback(self._active_tasks.discard)
                    else:
                        callback(event)
                except Exception as e:
                    logger.error(f"EventBus: Erro ao disparar assinante de {event_type.name}: {e}")

    async def shutdown(self):
        """Aguarda tarefas pendentes e cancela o barramento de forma segura."""
        logger.info("EventBus: Iniciando shutdown. Aguardando tasks pendentes...")
        if self._active_tasks:
            await asyncio.gather(*self._active_tasks, return_exceptions=True)
        self._active_tasks.clear()
        self._subscribers.clear()
        logger.info("EventBus: Shutdown concluído.")
''',

    "phoenix_kernel/ahde/analytics.py": '''# phoenix_kernel/ahde/analytics.py
from typing import Dict
from phoenix_kernel.ahde.contracts import HardwareSnapshot, ChangeSet, CapabilitySnapshot

class SnapshotComparer:
    @staticmethod
    def compare_hardware(old: HardwareSnapshot, new: HardwareSnapshot) -> ChangeSet:
        if not old:
            return ChangeSet(hardware_changed=True, changed_fields=["all"])
        
        changed_fields = []
        if old.hardware != new.hardware: changed_fields.append("hardware")
        if old.drivers != new.drivers: changed_fields.append("drivers")
        if old.services != new.services: changed_fields.append("services")
        if old.models != new.models: changed_fields.append("models")
        if old.capabilities != new.capabilities: changed_fields.append("capabilities")
        
        return ChangeSet(
            hardware_changed=len(changed_fields) > 0,
            changed_fields=changed_fields
        )

class CapabilityEngine:
    @staticmethod
    def extract(raw_data: Dict) -> CapabilitySnapshot:
        backends = raw_data.get("available_backends", [])
        services = raw_data.get("services", {})
        
        return CapabilitySnapshot(
            vulkan="vulkan" in backends,
            cuda="cuda" in backends,
            rocm="rocm" in backends,
            docker=bool(services.get("docker")),
            wsl=bool(services.get("wsl")),
            virtualization=bool(services.get("virtualization")),
            ollama=bool(services.get("ollama")),
            llamacpp=bool(services.get("llamacpp"))
        )
''',

    "phoenix_kernel/ahde/snapshot_engine.py": '''# phoenix_kernel/ahde/snapshot_engine.py
import logging
from datetime import datetime
from phoenix_kernel.ahde.contracts import (
    HardwareSnapshot, TelemetrySnapshot, DiscoveryEvent, 
    EventType, EventPriority, ChangeSet
)
from phoenix_kernel.ahde.event_bus import EventBus
from phoenix_kernel.ahde.repository.base import SnapshotRepository
from phoenix_kernel.ahde.analytics import SnapshotComparer, CapabilityEngine

logger = logging.getLogger(__name__)

class SnapshotEngine:
    def __init__(self, machine_id: str, event_bus: EventBus, repository: SnapshotRepository = None):
        self.machine_id = machine_id
        self.event_bus = event_bus
        self.repository = repository
        self._last_hardware_snapshot: HardwareSnapshot = None

    async def capture_hardware(self, raw_hardware_data: dict):
        capabilities = CapabilityEngine.extract(raw_hardware_data)
        
        snapshot = HardwareSnapshot(
            machine_id=self.machine_id,
            timestamp=datetime.now().isoformat(),
            hardware=raw_hardware_data.get("hardware", {}),
            drivers=raw_hardware_data.get("drivers", {}),
            services=raw_hardware_data.get("services", {}),
            models=raw_hardware_data.get("models", []),
            capabilities=capabilities
        )

        changes = ChangeSet()
        if self._last_hardware_snapshot:
            changes = SnapshotComparer.compare_hardware(self._last_hardware_snapshot, snapshot)

        if self.repository:
            await self.repository.save_hardware(snapshot)

        if changes.hardware_changed:
            event = DiscoveryEvent(
                event_type=EventType.HARDWARE_CHANGED,
                payload=snapshot,
                timestamp=snapshot.timestamp,
                priority=EventPriority.HIGH,
                machine_id=self.machine_id
            )
            await self.event_bus.publish(EventType.HARDWARE_CHANGED, event)

        self._last_hardware_snapshot = snapshot
        return snapshot

    async def capture_telemetry(self, raw_telemetry_data: dict):
        snapshot = TelemetrySnapshot(
            machine_id=self.machine_id,
            timestamp=datetime.now().isoformat(),
            telemetry=raw_telemetry_data
        )

        if self.repository:
            await self.repository.save_telemetry(snapshot)

        event = DiscoveryEvent(
            event_type=EventType.TELEMETRY_UPDATED,
            payload=snapshot,
            timestamp=snapshot.timestamp,
            priority=EventPriority.NORMAL,
            machine_id=self.machine_id
        )
        await self.event_bus.publish(EventType.TELEMETRY_UPDATED, event)
        
        return snapshot
''',

    "phoenix_kernel/ahde/repository/__init__.py": "# Repository Module",
    
    "phoenix_kernel/ahde/repository/base.py": '''# phoenix_kernel/ahde/repository/base.py
from abc import ABC, abstractmethod
from typing import Optional
from phoenix_kernel.ahde.contracts import HardwareSnapshot, TelemetrySnapshot

class SnapshotRepository(ABC):
    """Interface de persistência para o Snapshot Engine."""
    @abstractmethod
    async def save_hardware(self, snapshot: HardwareSnapshot) -> None:
        pass
        
    @abstractmethod
    async def save_telemetry(self, snapshot: TelemetrySnapshot) -> None:
        pass

    @abstractmethod
    async def get_latest_hardware(self, machine_id: str) -> Optional[HardwareSnapshot]:
        pass
''',

    "phoenix_kernel/ahde/health/__init__.py": "# Health Module",
    
    "phoenix_kernel/ahde/health/engine.py": '''# phoenix_kernel/ahde/health/engine.py
import logging
logger = logging.getLogger(__name__)

class HealthEngine:
    """Reserva de namespace para Fase 2. Cálculo de Health Score da máquina."""
    async def evaluate(self, snapshot) -> int:
        # Lógica futura de análise de saúde
        return 100
''',

    "phoenix_kernel/ahde/events/__init__.py": "# Events Module",
    
    "phoenix_kernel/ahde/events/queue.py": '''# phoenix_kernel/ahde/events/queue.py
from abc import ABC, abstractmethod
from phoenix_kernel.ahde.contracts import DiscoveryEvent

class EventQueue(ABC):
    """Interface para fila persistente (Fase 2). Garante que eventos não se percam se a rede cair."""
    @abstractmethod
    async def enqueue(self, event: DiscoveryEvent) -> None:
        pass

    @abstractmethod
    async def dequeue(self) -> DiscoveryEvent:
        pass

class MemoryEventQueue(EventQueue):
    """Implementação temporária em memória para a Fase 1."""
    def __init__(self):
        self._queue = []
        
    async def enqueue(self, event: DiscoveryEvent) -> None:
        self._queue.append(event)
        
    async def dequeue(self) -> DiscoveryEvent:
        if self._queue:
            return self._queue.pop(0)
        return None
''',

    "phoenix_kernel/ahde/plugins/__init__.py": "# Plugins Module",
    
    "phoenix_kernel/ahde/plugins/sdk.py": '''# phoenix_kernel/ahde/plugins/sdk.py
from abc import ABC, abstractmethod
from phoenix_kernel.ahde.contracts import DiscoveryEvent

class AHDEPlugin(ABC):
    """SDK para produtos AIVisions (iDoctor, etc.) se plugarem no AHDE sem alterar o núcleo."""
    @abstractmethod
    async def initialize(self) -> None:
        pass

    @abstractmethod
    async def on_event(self, event: DiscoveryEvent) -> None:
        pass

    @abstractmethod
    async def shutdown(self) -> None:
        pass
'''
}

def main():
    root = Path(__file__).parent.resolve()
    
    p("INFO", "Iniciando provisionamento do AHDE 10/10...")
    
    # 1. Cria diretórios
    for d in DIRS:
        dir_path = root / d
        dir_path.mkdir(parents=True, exist_ok=True)
        p("OK", f"Diretório garantido: {d}")
        
    print()
    
    # 2. Cria arquivos
    for f_path, content in FILES.items():
        file_path = root / f_path
        with open(file_path, "w", encoding="utf-8") as f:
            f.write(content.strip() + "\n")
        p("OK", f"Arquivo criado: {f_path}")
        
    print()
    p("OK", "==================================")
    p("OK", "AHDE 10/10 Provisionado com Sucesso!")
    p("OK", "==================================")

if __name__ == "__main__":
    main()