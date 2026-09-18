from __future__ import annotations

import time
from typing import Any

from phoenix_forge.modules import detect, pulse, storage, system_inventory, hardware_deep_inventory, pcie_link_intelligence, nvme_deep_inspector, sensor_fusion, privileged_provider_contracts, msr_clock_intelligence, memory_spd, windows_smbus_provider, sensor_provider_inventory


def _field(value: Any, provider: str, confidence: str = "HIGH") -> dict[str, Any]:
    available = value not in (None, "", [], {})
    return {"value": value, "available": available, "provider": provider, "confidence": confidence if available else "NONE"}


def collect(detected=None) -> dict[str, Any]:
    """Evidence-oriented Hardware Inspector v4.

    The deep inventory is authoritative for identity/topology fields. Live sensors and
    health data remain separate because transient telemetry must not overwrite static identity.
    """
    detected = detected or detect.collect()
    deep = hardware_deep_inventory.collect(detected, detected.compute_fabric)
    live = pulse.collect()
    disks = storage.health_inventory()
    nvme = nvme_deep_inspector.collect()
    fused = sensor_fusion.collect()
    privileged = privileged_provider_contracts.collect()
    msr_clock = msr_clock_intelligence.collect()
    spd = memory_spd.collect()
    smbus = windows_smbus_provider.status()
    sensor_inventory = sensor_provider_inventory.collect()
    pcie = system_inventory.pcie_health(minutes=1440, max_events=200)
    pcie_link = pcie_link_intelligence.collect(load_validated=False)

    missing = list(deep.get("missing_providers", []))
    if not live.gpu:
        missing.append("live_gpu_sensors")
    if not detected.vulkan_available:
        missing.append("vulkan_device_properties")

    return {
        "schema": "phoenix.forge.hardware-inspector/v7",
        "generated_at": time.time(),
        "status": "COMPLETE" if not missing else "PARTIAL",
        "absence_is_failure": False,
        "deep_inventory": deep,
        # Compatibility views retained for Aviary/older clients.
        "cpu": deep.get("cpu", {}),
        "memory": deep.get("memory", {}),
        "motherboard": deep.get("platform", {}).get("baseboard", {}),
        "bios": deep.get("platform", {}).get("bios", {}),
        "gpus": deep.get("gpus", []),
        "sensors": _field(live.model_dump(), "OS/vendor sensor providers", "MEDIUM"),
        "storage": _field(disks, "OS/storage providers", "MEDIUM"),
        "nvme_deep": _field(nvme, "Windows Storage CIM + reliability counters", "HIGH" if nvme.get("devices") else "NONE"),
        "sensor_fusion": _field(fused, "Phoenix Pulse + vendor provider fusion", "MEDIUM"),
        "privileged_provider_contracts": privileged,
        "msr_clock_intelligence": _field(msr_clock, "Verified privileged MSR provider", "HIGH" if msr_clock.get("status") in {"COMPLETE", "PARTIAL"} else "NONE"),
        "memory_spd": _field(spd, "Forge SPD parser + verified SMBus provider", "HIGH" if spd.get("raw_spd_available") else "NONE"),
        "smbus_provider_windows": smbus,
        "sensor_provider_inventory": sensor_inventory,
        "pcie_health": _field(pcie, "Windows WHEA event log", "MEDIUM"),
        "pcie_link": _field(pcie_link, "Windows PCIe device properties + Forge link classifier", "HIGH" if pcie_link.get("devices") else "NONE"),
        "missing_providers": sorted(set(missing)),
        "limitations": [
            "Live SPD requires a verified read-only SMBus provider/driver; offline dump parsing remains available.",
            "Physical GDDR chip addresses are not exposed by Vulkan.",
            "A missing sensor/provider is UNKNOWN, not evidence of damage.",
            "PCIe proximity is not treated as proof of NUMA affinity.",
            "CPUID frequency leaves may legitimately return zero and are then treated as UNKNOWN.",
            "PCIe current generation can downshift at idle and is not a bottleneck verdict without load validation.",
            "Privileged SMBus/MSR/electrical providers are explicit contracts; absence does not become fabricated telemetry.",
        ],
    }
