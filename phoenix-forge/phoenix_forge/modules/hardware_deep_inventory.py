from __future__ import annotations

import os
import platform
import time
from typing import Any

from phoenix_forge.util import powershell_json
from phoenix_forge.modules import system_inventory, cpu_native_inspector, cpu_runtime_telemetry, memory_spd
from phoenix_forge.adapters import native_queries

SCHEMA = "phoenix.forge.hardware-deep-inventory/v3"


def _list(value: Any) -> list[dict[str, Any]]:
    if not value:
        return []
    if isinstance(value, list):
        return [x for x in value if isinstance(x, dict)]
    return [value] if isinstance(value, dict) else []


def evidence(value: Any, provider: str, confidence: str = "HIGH", *, note: str | None = None) -> dict[str, Any]:
    available = value not in (None, "", [], {})
    out = {
        "value": value,
        "available": available,
        "provider": provider,
        "confidence": confidence if available else "NONE",
    }
    if note:
        out["note"] = note
    return out


def _windows_cpu() -> dict[str, Any]:
    rows = _list(powershell_json(
        "Get-CimInstance Win32_Processor | Select-Object DeviceID,Name,Caption,Description,Manufacturer,ProcessorId,Architecture,AddressWidth,DataWidth,Family,Stepping,Revision,SocketDesignation,NumberOfCores,NumberOfLogicalProcessors,MaxClockSpeed,CurrentClockSpeed,ExtClock,L2CacheSize,L3CacheSize,VirtualizationFirmwareEnabled,VMMonitorModeExtensions | ConvertTo-Json -Compress"
    ))
    reg = powershell_json(
        "Get-ItemProperty 'HKLM:\\HARDWARE\\DESCRIPTION\\System\\CentralProcessor\\0' -ErrorAction SilentlyContinue | Select-Object Identifier,VendorIdentifier,ProcessorNameString,'~MHz',FeatureSet | ConvertTo-Json -Compress"
    ) or {}
    caches = _list(powershell_json(
        "Get-CimInstance Win32_CacheMemory | Select-Object DeviceID,Level,CacheType,InstalledSize,MaxCacheSize,Associativity,BlockSize,NumberOfBlocks,Status,Purpose | ConvertTo-Json -Compress"
    ))
    return {"packages": rows, "registry_identity": reg, "caches": caches}


def _windows_memory() -> dict[str, Any]:
    dimms = _list(powershell_json(
        "Get-CimInstance Win32_PhysicalMemory | Select-Object DeviceLocator,BankLabel,Manufacturer,PartNumber,SerialNumber,Capacity,Speed,ConfiguredClockSpeed,DataWidth,TotalWidth,FormFactor,MemoryType,SMBIOSMemoryType,TypeDetail,InterleavePosition,MinVoltage,MaxVoltage,ConfiguredVoltage | ConvertTo-Json -Compress"
    ))
    arrays = _list(powershell_json(
        "Get-CimInstance Win32_PhysicalMemoryArray | Select-Object MemoryDevices,MaxCapacity,MaxCapacityEx,Location,Use,ErrorCorrection | ConvertTo-Json -Compress"
    ))
    return {"modules": dimms, "arrays": arrays}


def _windows_platform() -> dict[str, Any]:
    board = powershell_json(
        "Get-CimInstance Win32_BaseBoard | Select-Object Manufacturer,Product,Version,SerialNumber,Tag | ConvertTo-Json -Compress"
    ) or {}
    bios = powershell_json(
        "Get-CimInstance Win32_BIOS | Select-Object Manufacturer,Name,SMBIOSBIOSVersion,Version,ReleaseDate,SerialNumber,SMBIOSMajorVersion,SMBIOSMinorVersion,EmbeddedControllerMajorVersion,EmbeddedControllerMinorVersion | ConvertTo-Json -Compress"
    ) or {}
    product = powershell_json(
        "Get-CimInstance Win32_ComputerSystemProduct | Select-Object Vendor,Name,Version,IdentifyingNumber,UUID | ConvertTo-Json -Compress"
    ) or {}
    enclosure = powershell_json(
        "Get-CimInstance Win32_SystemEnclosure | Select-Object Manufacturer,Model,SerialNumber,SMBIOSAssetTag,ChassisTypes | ConvertTo-Json -Compress"
    ) or {}
    return {"baseboard": board, "bios": bios, "system_product": product, "enclosure": enclosure}


def _windows_display_drivers() -> list[dict[str, Any]]:
    return _list(powershell_json(
        "Get-CimInstance Win32_PnPSignedDriver | Where-Object {$_.DeviceClass -eq 'DISPLAY'} | Select-Object DeviceName,DeviceID,Manufacturer,DriverProviderName,DriverVersion,DriverDate,InfName,IsSigned,Signer | ConvertTo-Json -Compress"
    ))


def _driver_for_gpu(pnp: str | None, drivers: list[dict[str, Any]]) -> dict[str, Any]:
    if not pnp:
        return {}
    target = pnp.upper()
    for row in drivers:
        device_id = str(row.get("DeviceID") or "").upper()
        if device_id and (device_id == target or device_id in target or target in device_id):
            return row
    return {}


def _gpu_rows(detected, fabric: dict[str, Any]) -> list[dict[str, Any]]:
    by_key = {g.get("device_key"): g for g in fabric.get("gpus", []) if g.get("device_key")}
    drivers = _windows_display_drivers() if os.name == "nt" else []
    out = []
    for gpu in detected.gpus:
        fabric_gpu = by_key.get(gpu.device_key or "", {})
        signed = _driver_for_gpu(gpu.pnp_device_id, drivers)
        out.append({
            "device_key": gpu.device_key,
            "runtime_selector": evidence(
                {"kind": "device_index", "value": gpu.device_index},
                "Forge Detect/Vulkan enumeration",
                "HIGH",
                note="Runtime selector is transient and is not persistent identity.",
            ),
            "identity": evidence({
                "name": gpu.name,
                "vendor": gpu.vendor,
                "vendor_id": gpu.vendor_id,
                "device_id": gpu.device_id,
                "subsystem_vendor_id": gpu.subsystem_vendor_id,
                "subsystem_device_id": gpu.subsystem_device_id,
                "revision_id": gpu.revision_id,
                "pnp_device_id": gpu.pnp_device_id,
            }, "Windows PnP/CIM", "HIGH"),
            "pcie": evidence(fabric_gpu.get("pcie", {}), "Windows PnP location properties", "HIGH" if fabric_gpu.get("pcie", {}).get("status") == "PROVEN" else "LOW"),
            "driver": evidence({
                "version": gpu.driver_version,
                "date": gpu.driver_date,
                "provider": signed.get("DriverProviderName"),
                "inf": signed.get("InfName"),
                "signed": signed.get("IsSigned"),
                "signer": signed.get("Signer"),
            }, "Win32_VideoController + Win32_PnPSignedDriver", "HIGH"),
            "memory": evidence({
                "capacity_bytes": gpu.adapter_ram_bytes,
                "capacity_source": gpu.vram_capacity_source,
                "vulkan_device_local_bytes": gpu.vulkan_primary_device_local_bytes,
                "heaps": gpu.vulkan_memory_heaps,
                "memory_types": gpu.vulkan_memory_types,
            }, gpu.vram_capacity_source or "Forge GPU inventory", "MEDIUM"),
            "vulkan": evidence({
                "detected": gpu.vulkan_detected,
                "device_name": gpu.vulkan_device_name,
                "api_version": gpu.vulkan_api_version,
                "queue_families": gpu.vulkan_queue_families,
                "limits": gpu.vulkan_limits,
            }, "Phoenix Forge Native/Vulkan", "HIGH" if gpu.vulkan_detected else "NONE"),
            "dxgi": evidence(gpu.dxgi, "Phoenix Forge Native/DXGI", "HIGH" if gpu.dxgi else "NONE"),
            "vendor_telemetry": evidence(gpu.vendor_details, gpu.sources.get("vendor") or "Vendor API", "MEDIUM"),
            "numa_affinity": evidence(fabric_gpu.get("numa_affinity", {}), "Compute Fabric evidence", "HIGH" if fabric_gpu.get("numa_affinity", {}).get("status") == "PROVEN" else "LOW", note="UNKNOWN is preserved when affinity cannot be proven."),
            "vbios": evidence(None, "Forge VBIOS parser", "NONE", note="A ROM dump/path is required; Forge never invents a VBIOS version from GPU name."),
        })
    return out


def collect(detected=None, fabric: dict[str, Any] | None = None) -> dict[str, Any]:
    from phoenix_forge.modules import detect, compute_fabric

    detected = detected or detect.collect()
    fabric = fabric or detected.compute_fabric or compute_fabric.build(detected)
    inv = system_inventory.collect()

    cpu_native_legacy = detected.cpu_features or {}
    cpu_native_deep_raw = native_queries.cpu_deep_info()
    cpu_native_deep = cpu_native_inspector.normalize(cpu_native_deep_raw)
    cpu_native = cpu_native_deep_raw if cpu_native_deep.get("passed") else cpu_native_legacy
    cpu_runtime = cpu_runtime_telemetry.collect(samples=1, interval_ms=10)
    spd = memory_spd.collect()
    if os.name == "nt":
        cpu_os = _windows_cpu()
        memory = _windows_memory()
        platform_rows = _windows_platform()
    else:
        cpu_os = {
            "packages": inv.get("processors", []),
            "registry_identity": {},
            "caches": inv.get("caches", []),
        }
        memory = {"modules": inv.get("dimms", []), "arrays": []}
        platform_rows = {"baseboard": detected.motherboard, "bios": detected.bios, "system_product": {}, "enclosure": {}}

    missing: list[str] = []
    if not cpu_native_legacy.get("passed"):
        missing.append("native_cpuid")
    if not cpu_native_deep.get("passed"):
        missing.append("native_cpuid_deep")
    if cpu_runtime.get("status") != "COMPLETE":
        missing.append("native_cpu_runtime_clock")
    if not memory.get("modules"):
        missing.append("memory_module_inventory")
    # Raw SPD requires an evidence-bearing provider. Dump files are accepted for lab/offline parsing;
    # live slot reads still require a privileged SMBus provider.
    if not spd.get("raw_spd_available"):
        missing.append("raw_spd")
    if not spd.get("live_smbus_available"):
        missing.append("raw_spd_smbus")

    return {
        "schema": SCHEMA,
        "generated_at": time.time(),
        "host": {
            "hostname": detected.hostname,
            "os": detected.os,
            "os_version": detected.os_version,
            "architecture": detected.architecture,
            "platform": platform.platform(),
        },
        "cpu": {
            "identity": evidence(detected.cpu, "OS inventory", "HIGH"),
            "packages": evidence(cpu_os.get("packages", []), "Windows CIM" if os.name == "nt" else "OS/sysfs", "HIGH"),
            "registry_identity": evidence(cpu_os.get("registry_identity", {}), "Windows hardware registry", "MEDIUM"),
            "cpuid": evidence(cpu_native, "Phoenix Forge Native/CPUID", "HIGH" if cpu_native.get("passed") else "NONE"),
            "cpuid_legacy": evidence(cpu_native_legacy, "Phoenix Forge Native/CPUID legacy", "HIGH" if cpu_native_legacy.get("passed") else "NONE"),
            "cpuid_deep": evidence(cpu_native_deep, "Phoenix Forge Native/CPUID deep", "HIGH" if cpu_native_deep.get("passed") else "NONE", note="Requires phoenix-forge-native 0.19.4+; older helper remains usable through cpu-info fallback."),
            "caches": evidence(cpu_native_deep.get("caches") if cpu_native_deep.get("passed") and cpu_native_deep.get("caches") else cpu_os.get("caches", []), "CPUID deterministic cache leaf" if cpu_native_deep.get("passed") and cpu_native_deep.get("caches") else ("Win32_CacheMemory" if os.name == "nt" else "sysfs"), "HIGH" if cpu_native_deep.get("passed") and cpu_native_deep.get("caches") else "MEDIUM"),
            "instruction_sets": evidence(cpu_native_deep.get("features", {}).get("values") if cpu_native_deep.get("passed") else {k:v for k,v in cpu_native_legacy.items() if isinstance(v,bool)}, "CPUID feature leaves", "HIGH" if cpu_native_deep.get("passed") else "MEDIUM"),
            "address_width": evidence(cpu_native_deep.get("address_width") if cpu_native_deep.get("passed") else None, "CPUID 0x80000008", "HIGH"),
            "frequency_cpuid": evidence(cpu_native_deep.get("frequency") if cpu_native_deep.get("passed") and cpu_native_deep.get("frequency", {}).get("available") else None, "CPUID 0x15/0x16", "HIGH", note="Zero values mean the processor does not enumerate frequency through these CPUID leaves."),
            "runtime_clock": evidence(cpu_runtime if cpu_runtime.get("passed") else None, cpu_runtime.get("provider") or "CPU runtime clock provider", "HIGH" if cpu_runtime.get("status") == "COMPLETE" else "MEDIUM", note="OS-reported CurrentMhz is not APERF/MPERF effective clock; low idle clock is not diagnosed as throttling."),
            "native_topology": evidence(cpu_native_deep.get("topology") if cpu_native_deep.get("passed") else None, "CPUID 0x1F/0x0B", "HIGH"),
            "compute_topology": evidence({
                "processor_packages": fabric.get("processor_packages", []),
                "processor_groups": fabric.get("processor_groups", []),
                "numa_nodes": fabric.get("numa_nodes", []),
            }, "Compute Fabric / Windows native topology", "HIGH"),
        },
        "memory": {
            "modules": evidence(memory.get("modules", []), "SMBIOS/CIM", "MEDIUM"),
            "arrays": evidence(memory.get("arrays", []), "SMBIOS/CIM", "MEDIUM"),
            "raw_spd": evidence(spd if spd.get("raw_spd_available") else None, spd.get("provider") or "SMBus privileged provider", "MEDIUM" if spd.get("raw_spd_available") else "NONE", note="Offline raw dumps can be parsed; live SMBus slot reads are not implemented yet and no SPD value is fabricated."),
            "spd_architecture": spd,
        },
        "platform": {
            "baseboard": evidence(platform_rows.get("baseboard", {}), "SMBIOS/CIM", "HIGH"),
            "bios": evidence(platform_rows.get("bios", {}), "SMBIOS/CIM", "HIGH"),
            "system_product": evidence(platform_rows.get("system_product", {}), "SMBIOS/CIM", "HIGH"),
            "enclosure": evidence(platform_rows.get("enclosure", {}), "SMBIOS/CIM", "MEDIUM"),
        },
        "gpus": _gpu_rows(detected, fabric),
        "compute_fabric": fabric,
        "missing_providers": sorted(set(missing)),
        "invariants": {
            "unknown_is_not_failure": True,
            "device_key_is_persistent_identity": True,
            "device_index_is_runtime_selector": True,
            "pcie_proximity_does_not_prove_numa_affinity": True,
            "spd_values_are_never_inferred": True,
            "cpuid_zero_frequency_is_unknown_not_failure": True,
            "native_cache_geometry_is_preferred_over_cim_when_available": True,
            "os_reported_clock_is_not_aperf_mperf_effective_clock": True,
            "low_idle_clock_is_not_throttling": True,
        },
    }
