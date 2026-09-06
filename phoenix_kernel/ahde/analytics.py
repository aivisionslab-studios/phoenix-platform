# phoenix_kernel/ahde/analytics.py
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
