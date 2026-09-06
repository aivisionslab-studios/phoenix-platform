# phoenix_kernel/ahde/snapshot_engine.py
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
