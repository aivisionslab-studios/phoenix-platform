# phoenix_kernel/ahde/repository/base.py
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
