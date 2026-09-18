from __future__ import annotations

import time
from typing import Any
from phoenix_forge.modules import capability_registry, windows_msr_provider, windows_smbus_provider, memory_spd, sensor_provider_inventory, gpu_deep_telemetry, pcie_deep_inspection, nvme_deep_inspector, readiness_model, sensor_intelligence_deep, cpu_deep_inspector, stress_correctness
from phoenix_forge.adapters import intel_level_zero_sysman, windows_storage_pcie

SCHEMA = "phoenix.forge.capability-completion/v12"

def build() -> dict[str, Any]:
    reg=capability_registry.build()
    caps=reg.get("capabilities") or []
    by_status={}
    for row in caps:
        st=row.get("status","UNKNOWN")
        by_status[st]=by_status.get(st,0)+1
    msr=windows_msr_provider.status()
    smbus=windows_smbus_provider.status()
    spd=memory_spd.collect()
    sensors=sensor_provider_inventory.collect()
    gpu_deep=gpu_deep_telemetry.collect()
    pcie_deep=pcie_deep_inspection.collect()
    storage_deep=nvme_deep_inspector.collect()
    readiness=readiness_model.build()
    sensor_deep=sensor_intelligence_deep.capability_summary()
    cpu_deep=cpu_deep_inspector.collect(samples=2, interval_ms=50)
    stress_caps=stress_correctness.capabilities()
    intel_gpu_provider=intel_level_zero_sysman.probe()
    blockers=[]
    if not msr.get("effective_clock_ready"):
        blockers.append({"id":"cpu.aperf_mperf.runtime","status":"RUNTIME_DEPENDENT","reason":"signed/read-only PhoenixForgeMsr kernel provider absent or capability unavailable"})
    if not smbus.get("live_spd_ready"):
        blockers.append({"id":"memory.spd.live_smbus.runtime","status":"RUNTIME_DEPENDENT","reason":"PhoenixForgeSmbus kernel provider absent or capability unavailable"})
    if not spd.get("capabilities",{}).get("xmp_expo_decode"):
        blockers.append({"id":"memory.xmp_expo","status":"MISSING","roadmap":"PLANNED","reason":"raw extension decoder not implemented"})
    if not sensors.get("coverage",{}).get("vendor_deep_provider"):
        blockers.append({"id":"gpu.vendor_sensor_deep.runtime","status":"RUNTIME_DEPENDENT","reason":"vendor-deep provider not present on this machine"})
    if intel_gpu_provider.get("status")!="READY":
        blockers.append({"id":"gpu.intel.vendor_deep.runtime","status":"RUNTIME_DEPENDENT","reason":intel_gpu_provider.get("reason") or "Intel Level Zero Sysman runtime/hardware not available on this machine"})
    if pcie_deep.get("devices"):
        blockers.extend([
            {"id":"pcie.location.physical_slot","status":"EXTERNAL_REQUIRED","reason":"generic Windows provider does not prove chassis slot identity; authoritative firmware/vendor source required"},
            {"id":"pcie.link.electrical_width","status":"EXTERNAL_REQUIRED","reason":"electrical slot width is not inferred from negotiated/max lanes; authoritative firmware/vendor source required"},
            {"id":"pcie.errors.aer_counters","status":"EXTERNAL_REQUIRED","reason":"per-device AER counters require authoritative kernel/platform telemetry"},
            {"id":"pcie.link.retrain_counter","status":"EXTERNAL_REQUIRED","reason":"link retrain counter requires authoritative kernel/platform telemetry"},
        ])
    pcie_numa_rows=[]
    for d in (pcie_deep.get("devices") or []):
        loc=d.get("location") or {}
        nm=loc.get("numa_node") or {}
        pcie_numa_rows.append({"name":d.get("name"),"node_id":nm.get("value"),"available":bool(nm.get("available")),"evidence":nm.get("evidence")})
    if pcie_deep.get("devices") and not any(x.get("available") for x in pcie_numa_rows):
        blockers.append({"id":"pcie.affinity.gpu_numa.runtime","status":"RUNTIME_DEPENDENT","reason":"GPU devnode/firmware did not expose a resolvable DEVPKEY_Numa_Proximity_Domain on this machine"})
    storage_pcie=windows_storage_pcie.collect()
    if storage_deep.get("devices"):
        if storage_deep.get("provider_status",{}).get("smartctl")!="READY":
            blockers.append({"id":"storage.nvme.smart_health_log","status":"RUNTIME_DEPENDENT",
                             "reason":"optional read-only smartctl provider not available; Windows reliability data still used"})
        nvme_count=int((storage_deep.get("summary") or {}).get("nvme_devices") or 0)
        mapped_count=int((storage_deep.get("summary") or {}).get("nvme_pcie_mapped_devices") or 0)
        if nvme_count and mapped_count < nvme_count:
            blockers.append({"id":"storage.nvme.pcie_mapping.runtime","status":"RUNTIME_DEPENDENT",
                             "reason":"one or more NVMe devices did not expose a safely matched Windows PnP parent chain to a PCI ancestor"})
    return {
        "schema": SCHEMA,
        "generated_at": time.time(),
        "status": "AUDITED",
        "registry_summary": by_status,
        "runtime_readiness": {
            "msr": msr,
            "smbus_spd": smbus,
            "sensor_providers": sensors.get("coverage"),
            "gpu_deep_telemetry": [{"device_key":d.get("device_key"),"vendor":d.get("vendor"),"provider_status":d.get("provider_status"),"coverage":d.get("coverage")} for d in (gpu_deep.get("devices") or [])],
            "pcie_deep_inspection": [{"name":d.get("name"),"bdf":((d.get("location") or {}).get("bdf") or {}).get("value"),"current_width":((d.get("link") or {}).get("current_width") or {}).get("value"),"max_width":((d.get("link") or {}).get("max_width") or {}).get("value"),"numa_node":((d.get("location") or {}).get("numa_node") or {}).get("value"),"numa_affinity_available":bool(((d.get("location") or {}).get("numa_node") or {}).get("available"))} for d in (pcie_deep.get("devices") or [])],
            "gpu_numa_affinity": pcie_numa_rows,
            "storage_deep": {"status":storage_deep.get("status"),"summary":storage_deep.get("summary"),"provider_status":storage_deep.get("provider_status")},
            "storage_pcie_mapping": {"status":storage_pcie.get("status"),"summary":storage_pcie.get("summary"),"policy":storage_pcie.get("policy")},
            "readiness": readiness,
            "sensor_intelligence_deep": sensor_deep,
            "cpu_deep": {"status":cpu_deep.get("status"),"clocks":cpu_deep.get("clocks"),"provider":cpu_deep.get("provider")},
            "stress_correctness": stress_caps,
            "intel_gpu_deep": {"status":intel_gpu_provider.get("status"),"provider":intel_gpu_provider.get("provider"),"device_count":len(intel_gpu_provider.get("devices") or []),"reason":intel_gpu_provider.get("reason")},
        },
        "open_capability_gaps": blockers,
        "capability_closure": {
            "release_train": "0.24.0 Capability Completion",
            "gate": "24D",
            "target": "storage.nvme.pcie_mapping",
            "implementation_status": "RUNTIME_DEPENDENT",
            "verification_status": "UNVERIFIED_ON_REAL_NVME_PCIE_HARDWARE",
            "decision_influence": "DISABLED",
        },
        "policy": {
            "this_module_does_not_make_runtime_placement_decisions": True,
            "decision_engine_phase_enabled": False,
            "capability_completion_precedes_policy_engine": True,
            "unknown_is_not_guessed": True,
            "runtime_dependent_is_not_complete": True,
            "external_instrumentation_is_reported_not_fabricated": True,
        },
    }
