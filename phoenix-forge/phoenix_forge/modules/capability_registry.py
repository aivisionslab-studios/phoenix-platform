from __future__ import annotations

from typing import Any

SCHEMA = "phoenix.forge.capability-registry/v42"

# Explicit product truth: COMPLETE means implemented in the code path; RUNTIME_DEPENDENT
# means the implementation exists but availability depends on hardware/provider/permissions;
# PLANNED means the architecture reserves the capability but it is not claimed as functional.
CAPABILITIES = [
    {"id":"ahde.evidence_bridge","domain":"hardware","status":"COMPLETE","provider":"Phoenix Engine AHDE -> Forge Evidence Bridge","release":"0.20.8"},
    {"id":"sensors.semantic_fusion","domain":"sensors","status":"COMPLETE","provider":"AHDE + Forge Sensor Fusion v2","release":"0.20.8"},

    {"id":"pcie.negotiated_link","domain":"pcie","status":"RUNTIME_DEPENDENT","provider":"Windows PCIe device properties","release":"0.19.9"},
    {"id":"pcie.rebar","domain":"pcie","status":"RUNTIME_DEPENDENT","provider":"explicit Windows device-property evidence","release":"0.19.9"},
    {"id":"memory.spd.live_smbus","domain":"memory","status":"RUNTIME_DEPENDENT","provider":"Phoenix SMBus Provider ABI v1 + verified read-only Provider Action Runtime","release":"0.21.5.1"},
    {"id":"memory.spd.provider_abi","domain":"memory","status":"COMPLETE","provider":"Phoenix Windows SMBus Provider ABI v1 + user-mode provider foundation","release":"0.21.5.1"},
    {"id":"memory.spd.ddr3_base","domain":"memory","status":"COMPLETE","provider":"Phoenix Memory/SPD parser v3","release":"0.22.0"},
    {"id":"memory.spd.ddr4_geometry","domain":"memory","status":"COMPLETE","provider":"Phoenix Memory/SPD parser v3","release":"0.22.0"},
    {"id":"memory.spd.ddr4_crc","domain":"memory","status":"COMPLETE","provider":"Phoenix Memory/SPD parser v3","release":"0.22.0"},
    {"id":"memory.spd.ddr4_cas_bitmap","domain":"memory","status":"COMPLETE","provider":"Phoenix Memory/SPD parser v3","release":"0.22.0"},
    {"id":"memory.spd.xmp_signature","domain":"memory","status":"COMPLETE","provider":"Phoenix Memory/SPD parser v3 signature-only evidence","release":"0.22.0"},
    {"id":"memory.spd.ddr5_identity","domain":"memory","status":"COMPLETE","provider":"Phoenix Memory/SPD parser v3 conservative identity decode","release":"0.22.0"},
    {"id":"memory.xmp_expo","domain":"memory","status":"COMPLETE","roadmap":"NONE","provider":"Phoenix Memory/SPD parser v4 raw XMP 2.0 / XMP 3.0 / EXPO extension decoder","release":"0.24.0rc1","verification_status":"UNVERIFIED_ON_REAL_XMP_EXPO_HARDWARE","limitation":"Raw SPD advertised profiles only; active BIOS selection and stability are not inferred"},
    {"id":"cpu.aperf_mperf","domain":"cpu","status":"RUNTIME_DEPENDENT","provider":"verified MSR provider via Provider Action Runtime","release":"0.20.7"},
    {"id":"cpu.bclk_multiplier","domain":"cpu","status":"RUNTIME_DEPENDENT","provider":"verified MSR/chipset provider via Provider Action Runtime","release":"0.20.7"},
    {"id":"gpu.vendor_sensor_deep","domain":"gpu","status":"RUNTIME_DEPENDENT","provider":"ADL/NVML/ROCm-SMI/LHM/vendor APIs","release":"existing"},
    {"id":"storage.nvme_deep","domain":"storage","status":"RUNTIME_DEPENDENT","provider":"Windows Storage CIM + Get-StorageReliabilityCounter","release":"0.20.0"},
    {"id":"sensors.fusion","domain":"sensors","status":"COMPLETE","provider":"Phoenix Pulse + vendor fallbacks + evidence normalization","release":"0.20.0"},
    {"id":"sensors.provider_inventory","domain":"sensors","status":"COMPLETE","provider":"Provider Runtime + AHDE + Sensor Fusion coverage audit","release":"0.21.5.1"},
    {"id":"hardware.capability_completion","domain":"governance","status":"COMPLETE","provider":"Capability Completion audit v1","release":"0.21.5.1"},
    {"id":"governance.public_naming","domain":"governance","status":"COMPLETE","provider":"Phoenix Public Surface Naming Policy v1","release":"0.21.5.3"},
    {"id":"audit.gap_tracker","domain":"governance","status":"COMPLETE","provider":"Capability Registry + provider contracts","release":"0.20.0"},
    {"id":"recommendation.evidence_based","domain":"intelligence","status":"COMPLETE","provider":"Configuration Auditor + Evidence Graph + storage/PCIe intelligence","release":"0.20.0"},
    {"id":"telemetry.governance","domain":"governance","status":"COMPLETE","provider":"explicit consent + sanitizer + preview + revoke","release":"0.20.1"},
    {"id":"telemetry.firestore","domain":"telemetry","status":"RUNTIME_DEPENDENT","provider":"HTTPS ingestion gateway or Google Cloud Firestore ADC","release":"0.20.1"},
    {"id":"telemetry.preview_nonblocking","domain":"telemetry","status":"COMPLETE","provider":"Snapshot Cache stale-while-revalidate","release":"0.20.4"},
    {"id":"gpu.identity_registry","domain":"gpu","status":"COMPLETE","provider":"persistent device_key + user-confirmed physical alias","release":"0.20.4"},
    {"id":"providers.runtime_health","domain":"governance","status":"COMPLETE","provider":"Provider Runtime stale-while-revalidate health cache","release":"0.20.5"},
    {"id":"providers.safe_actions","domain":"governance","status":"COMPLETE","provider":"Verified read-only Provider Action Runtime","release":"0.20.6"},
    {"id":"cpu.msr_clock_intelligence","domain":"cpu","status":"COMPLETE","provider":"MSR Clock Intelligence semantic adapter","release":"0.20.7"},
    {"id":"cpu.msr_provider_abi","domain":"cpu","status":"COMPLETE","provider":"Phoenix Windows MSR Provider ABI v1 + user-mode provider foundation","release":"0.20.9"},
    {"id":"cpu.deep.normalized","domain":"cpu","status":"COMPLETE","provider":"Phoenix CPU Deep Inspector v1","release":"0.22.1"},
    {"id":"cpu.intel.vendor_deep","domain":"cpu","status":"RUNTIME_DEPENDENT","roadmap":"NONE","provider":"Phoenix CPU Vendor Deep v1 + Phoenix MSR Provider read-only contract","release":"0.25.0rc1","verification_status":"UNVERIFIED_ON_REAL_INTEL_CPU","limitation":"Privileged Intel MSR telemetry requires a signed Phoenix kernel driver; missing driver is not hardware failure and unexposed registers remain UNKNOWN"},
    {"id":"cpu.amd.vendor_deep","domain":"cpu","status":"RUNTIME_DEPENDENT","roadmap":"NONE","provider":"Phoenix CPU Vendor Deep v1 + Phoenix MSR Provider read-only contract","release":"0.25.0rc1","verification_status":"UNVERIFIED_ON_REAL_AMD_CPU","limitation":"Privileged AMD MSR/CPPC/P-state telemetry requires a signed Phoenix kernel driver or authoritative vendor provider; missing provider is not hardware failure and values remain UNKNOWN"},
    {"id":"provider.privileged.security_contract","domain":"providers","status":"COMPLETE","roadmap":"NONE","provider":"Phoenix Privileged Provider Contract v1","release":"0.25.0rc2","verification_status":"VERIFIED_SYNTHETIC","limitation":"Contract is complete; signed Phoenix kernel driver remains EXTERNAL_REQUIRED and is not bundled"},
    {"id":"provider.privileged.driver_source","domain":"providers","status":"COMPLETE","roadmap":"NONE","provider":"Phoenix Privileged Driver Source v1","release":"0.25.0rc4","verification_status":"VERIFIED_SYNTHETIC","limitation":"Source implements fixed allowlisted APERF/MPERF reads; signed runtime remains EXTERNAL_REQUIRED and reference_mhz remains UNKNOWN"},
    {"id":"provider.privileged.aperf_mperf_source","domain":"providers","status":"COMPLETE","roadmap":"NONE","provider":"Phoenix Privileged Driver APERF/MPERF Source v1","release":"0.25.0rc4","verification_status":"VERIFIED_SYNTHETIC","limitation":"Fixed MSRs 0xE7/0xE8 only; source verified but no signed runtime/hardware verification yet"},
    {"id":"provider.privileged.wdk_diagnostics","domain":"providers","status":"COMPLETE","roadmap":"NONE","provider":"Phoenix WDK Diagnostics v1","release":"0.25.0rc6.post13","verification_status":"VERIFIED_SYNTHETIC","limitation":"Read-only diagnostics distinguish WDK file presence from Visual Studio kernel-toolset integration; real Windows integration remains runtime evidence"},
    {"id":"provider.privileged.wdk_build_project","domain":"providers","status":"COMPLETE","roadmap":"NONE","provider":"Phoenix WDK Build Project v1","release":"0.25.0rc5","verification_status":"VERIFIED_SYNTHETIC","limitation":"Project/preflight verified; actual Windows WDK build remains environment dependent"},
    {"id":"provider.privileged.runtime_handshake","domain":"providers","status":"COMPLETE","roadmap":"NONE","provider":"Phoenix Privileged Runtime Handshake v1","release":"0.25.0rc5","verification_status":"VERIFIED_SYNTHETIC","limitation":"Read-only ABI handshake; signature/trust remains a separate gate"},
    {"id":"provider.privileged.unsigned_build_qualification_tool","domain":"providers","status":"COMPLETE","roadmap":"NONE","provider":"Phoenix Unsigned WDK Build Qualification v1","release":"0.25.0rc6","verification_status":"VERIFIED_SYNTHETIC","limitation":"Build/hash/evidence tooling only; it never installs, starts, signs or promotes the driver"},
    {"id":"provider.privileged.unsigned_build_artifact","domain":"providers","status":"RUNTIME_DEPENDENT","roadmap":"NONE","provider":"Phoenix WDK unsigned build evidence","release":"0.25.0rc6","verification_status":"UNVERIFIED","limitation":"Requires a real Windows WDK build; unsigned artifact is not trusted runtime and does not count as hardware verification"},
    {"id":"provider.privileged.preinstall_hardening","domain":"providers","status":"COMPLETE","roadmap":"NONE","provider":"Phoenix Privileged Driver Pre-Install Hardening v1","release":"0.25.0rc6.post12","verification_status":"VERIFIED_SYNTHETIC","limitation":"Source hardening complete; signed installation/hardware verification remain external gates"},
    {"id":"provider.privileged.trust_gate","domain":"providers","status":"COMPLETE","roadmap":"NONE","provider":"Phoenix Driver Trust Gate v1","release":"0.25.0rc6.post12","verification_status":"VERIFIED_SYNTHETIC","limitation":"Fail-closed signature/thumbprint policy; no signer is approved in source packages"},
    {"id":"provider.privileged.signed_runtime","domain":"providers","status":"EXTERNAL_REQUIRED","roadmap":"BLOCKED","provider":"Phoenix signed Windows kernel driver","release":"0.25.0rc3","verification_status":"UNVERIFIED","limitation":"Requires Windows WDK build plus trusted signing certificate; no signed binary or key is bundled"},
    {"id":"cpu.clock.semantic_separation","domain":"cpu","status":"COMPLETE","provider":"Phoenix CPU Deep Inspector v1","release":"0.22.1"},
    {"id":"cpu.throttling.evidence_gate","domain":"cpu","status":"COMPLETE","provider":"Phoenix CPU Deep Inspector v1","release":"0.22.1"},
    {"id":"telemetry.send_nonblocking","domain":"telemetry","status":"COMPLETE","provider":"Snapshot-backed telemetry send path","release":"0.20.7"},
    {"id":"scheduler.multi_device","domain":"scheduler","status":"COMPLETE","provider":"Forge Multi-Device Scheduler v1 + Compute Fabric + GPU Safety","release":"0.21.0"},
    {"id":"scheduler.execution_policy","domain":"scheduler","status":"COMPLETE","provider":"Scheduler Execution Policy v1 + device leases + result correlation","release":"0.21.1"},
    {"id":"scheduler.backend_executor","domain":"scheduler","status":"COMPLETE","provider":"Phoenix Engine Scheduler Adapter contract","release":"0.21.2"},
    {"id":"scheduler.phoenix_llama_runtime_adapter","domain":"scheduler","status":"COMPLETE","provider":"Phoenix Engine -> Forge Scheduler -> Phoenix Llama Runtime","release":"0.21.2"},
    {"id":"scheduler.phoenix_diffusion_adapter","domain":"scheduler","status":"COMPLETE","provider":"Phoenix Engine -> Forge Scheduler -> Phoenix Diffusion direct adapter","release":"0.21.3.1"},
    {"id":"scheduler.runtime_feedback","domain":"scheduler","status":"COMPLETE","provider":"Scheduler Runtime Feedback v1 (observation-only; decision influence frozen)","release":"0.21.4"},
    {"id":"scheduler.phoenix_lava_adapter","domain":"scheduler","status":"RUNTIME_DEPENDENT","roadmap":"NONE","phase":"FOUNDATION_INTEGRATION","provider":"Phoenix LaVa Foundation Adapter v1 -> Phoenix Llama Runtime","release":"0.25.0rc6.post12","verification_status":"VERIFIED_SYNTHETIC","limitation":"Adapter/profile/runtime policy implemented; foundation GGUF must be present and Phoenix LaVa remains a future Phoenix-trained model"},
    {"id":"scheduler.cooperative_executor","domain":"scheduler","status":"RUNTIME_DEPENDENT","roadmap":"NONE","phase":"EXECUTION_FOUNDATION","provider":"Phoenix Cooperative Executor v1 + registered backend adapter","release":"0.25.0rc6.post12","verification_status":"VERIFIED_SYNTHETIC","limitation":"Core executor is implemented; actual cooperative execution requires a trusted in-process runtime backend adapter"},
    {"id":"scheduler.phoenix_lava_runtime_manager","domain":"scheduler","status":"RUNTIME_DEPENDENT","roadmap":"NONE","phase":"FOUNDATION_RUNTIME","provider":"Phoenix LaVa Runtime Manager v3 + readiness/restart/admission","release":"0.25.0rc6.post12","verification_status":"VERIFIED_SYNTHETIC","limitation":"Actual execution requires Phoenix Llama Runtime and a local Phoenix LaVa foundation GGUF"},
    {"id":"models.phoenix_lava_registry","domain":"models","status":"COMPLETE","roadmap":"NONE","phase":"FOUNDATION_RUNTIME","provider":"Phoenix LaVa Model Registry v2","release":"0.25.0rc6.post12","verification_status":"VERIFIED_SYNTHETIC","limitation":"Registry/download controller is implemented; model artifacts remain external and require explicit operator download"},
    {"id":"benchmark.phoenix_lava_q5_q6","domain":"benchmark","status":"RUNTIME_DEPENDENT","roadmap":"NONE","phase":"FOUNDATION_RUNTIME","provider":"Phoenix LaVa Q5/Q6 Benchmark Suite v2","release":"0.25.0rc6.post12","verification_status":"VERIFIED_SYNTHETIC","limitation":"Benchmark execution requires the corresponding local GGUF and runtime; no quality winner is fabricated without runtime evidence"},
    {"id":"models.phoenix_lava_artifact_verification","domain":"models","status":"COMPLETE","roadmap":"NONE","phase":"FOUNDATION_RUNTIME","provider":"Phoenix LaVa Artifact Verification v1","release":"0.25.0rc6.post12","verification_status":"VERIFIED_SYNTHETIC","limitation":"Hash verification is authoritative only when a Phoenix sidecar exists; source repository checksum is not fabricated"},
    {"id":"scheduler.phoenix_lava_hybrid_admission","domain":"scheduler","status":"RUNTIME_DEPENDENT","roadmap":"NONE","phase":"FOUNDATION_RUNTIME","provider":"Phoenix LaVa Hybrid Admission v1 -> Phoenix Llama Runtime","release":"0.25.0rc6.post12","verification_status":"VERIFIED_SYNTHETIC","limitation":"CPU-only RAM pressure does not block AUTO/HYBRID; actual GPU layer fit remains owned by Phoenix Llama Runtime"},
    {"id":"models.phoenix_lava_gguf_qualification","domain":"models","status":"COMPLETE","roadmap":"NONE","phase":"FOUNDATION_RUNTIME","provider":"Phoenix LaVa GGUF Artifact Qualification v1","release":"0.25.0rc6.post12","verification_status":"VERIFIED_SYNTHETIC","limitation":"Qualification validates canonical GGUF structure/source/hash policy; model quality and runtime correctness still require execution evidence"},
    {"id":"scheduler.phoenix_lava_engine_bridge","domain":"scheduler","status":"RUNTIME_DEPENDENT","roadmap":"NONE","phase":"FOUNDATION_RUNTIME","provider":"Phoenix LaVa Engine Bridge v1","release":"0.25.0rc6.post12","verification_status":"VERIFIED_SYNTHETIC","limitation":"Read-only consolidated state for Engine/Aviary; mutations remain explicit operator actions"},
    {"id":"gpu.deep_telemetry.normalized","domain":"gpu","status":"COMPLETE","provider":"Phoenix GPU Deep Telemetry v1","release":"0.21.6"},
    {"id":"gpu.amd.adl.read_only","domain":"gpu","status":"RUNTIME_DEPENDENT","provider":"AMD ADL read-only query path","release":"0.21.6"},
    {"id":"gpu.nvidia.management_read_only","domain":"gpu","status":"RUNTIME_DEPENDENT","provider":"NVIDIA management CLI read-only query path","release":"0.21.6"},
    {"id":"gpu.intel.vendor_deep","domain":"gpu","status":"RUNTIME_DEPENDENT","roadmap":"NONE","provider":"Phoenix Intel GPU Deep v1 / oneAPI Level Zero Sysman read-only adapter","release":"0.24.0rc2.post1","verification_status":"UNVERIFIED_ON_REAL_INTEL_GPU","limitation":"Runtime requires Level Zero Sysman support; raw temperature sensors are not relabelled as edge/hotspot without authoritative sensor properties; ambiguous multi-GPU ordinal mapping is prohibited"},
    {"id":"gpu.vbios.metadata_hash","domain":"gpu","status":"COMPLETE","provider":"Phoenix GPU Deep Telemetry v1","release":"0.21.6"},
    {"id":"pcie.deep.normalized","domain":"pcie","status":"COMPLETE","provider":"Phoenix PCIe Deep Inspection v1","release":"0.21.7"},
    {"id":"pcie.location.bdf","domain":"pcie","status":"RUNTIME_DEPENDENT","provider":"Windows PnP topology","release":"0.21.7"},
    {"id":"pcie.location.physical_slot","domain":"pcie","status":"MISSING","provider":"none","release":None},
    {"id":"pcie.link.electrical_width","domain":"pcie","status":"MISSING","provider":"none","release":None},
    {"id":"pcie.affinity.gpu_numa","domain":"pcie","status":"RUNTIME_DEPENDENT","roadmap":"NONE","provider":"Windows PnP DEVPKEY_Numa_Proximity_Domain + Kernel32 GetNumaProximityNodeEx","release":"0.24.0rc3","verification_status":"UNVERIFIED_ON_REAL_MULTI_NUMA_HARDWARE","limitation":"Affinity is PROVEN only when firmware/Windows expose a GPU proximity domain that resolves to a NUMA node; PCI root is never substituted; absent evidence remains UNKNOWN"},
    {"id":"pcie.errors.aer_counters","domain":"pcie","status":"MISSING","provider":"none","release":None},
    {"id":"pcie.link.retrain_counter","domain":"pcie","status":"MISSING","provider":"none","release":None},
    {"id":"storage.deep.normalized","domain":"storage","status":"COMPLETE","provider":"Phoenix Storage Inspector / NVMe Deep v2","release":"0.21.8"},
    {"id":"storage.windows.reliability","domain":"storage","status":"RUNTIME_DEPENDENT","provider":"Windows Storage CIM + Get-StorageReliabilityCounter","release":"0.21.8"},
    {"id":"storage.smartctl.read_only","domain":"storage","status":"RUNTIME_DEPENDENT","provider":"optional smartctl JSON query","release":"0.21.8"},
    {"id":"storage.nvme.smart_health_log","domain":"storage","status":"RUNTIME_DEPENDENT","provider":"optional smartctl NVMe SMART health log","release":"0.21.8"},
    {"id":"storage.nvme.pcie_mapping","domain":"storage","status":"RUNTIME_DEPENDENT","roadmap":"NONE","provider":"Phoenix Storage PCIe Mapping v1 / Windows PnP parent-chain resolver","release":"0.24.0","verification_status":"UNVERIFIED_ON_REAL_NVME_PCIE_HARDWARE","limitation":"Mapping requires an authoritative Windows physical-disk identity plus PnP parent chain to a PCI ancestor; model-name-only matching is prohibited; missing BDF/link properties remain UNKNOWN"},
    {"id":"storage.nvme.smartctl_safe_matching","domain":"storage","status":"COMPLETE","provider":"serial exact; unique-model fallback only when Windows serial is absent","release":"0.21.8"},
    {"id":"gpu.vram.physical_chip_mapping","domain":"gpu","status":"IMPOSSIBLE_GENERICALLY","roadmap":"NONE","phase":"CAPABILITY_FIRST","provider":"none","release":"0.21.8.1"},
    {"id":"sensor.intelligence.normalized","domain":"sensors","status":"COMPLETE","provider":"Phoenix Sensor Intelligence Deep v1","release":"0.21.9"},
    {"id":"sensor.intelligence.consensus","domain":"sensors","status":"COMPLETE","provider":"Phoenix Sensor Intelligence Deep v1","release":"0.21.9"},
    {"id":"sensor.intelligence.conflict_detection","domain":"sensors","status":"COMPLETE","provider":"Phoenix Sensor Intelligence Deep v1","release":"0.21.9"},
    {"id":"sensor.intelligence.stale_detection","domain":"sensors","status":"COMPLETE","provider":"Phoenix Sensor Intelligence Deep v1","release":"0.21.9"},
    {"id":"sensor.intelligence.disappearance_detection","domain":"sensors","status":"COMPLETE","provider":"Phoenix Sensor Intelligence Deep v1","release":"0.21.9"},
    {"id":"sensor.intelligence.implausible_filter","domain":"sensors","status":"COMPLETE","provider":"Phoenix Sensor Intelligence Deep v1","release":"0.21.9"},
    {"id":"sensor.super_io","domain":"sensors","status":"RUNTIME_DEPENDENT","provider":"safe active provider required","release":"0.21.9"},
    {"id":"sensor.motherboard.deep","domain":"sensors","status":"RUNTIME_DEPENDENT","provider":"vendor/super-io provider required","release":"0.21.9"},
    {"id":"sensor.vrm.deep","domain":"sensors","status":"RUNTIME_DEPENDENT","provider":"vendor/super-io provider required","release":"0.21.9"},
    {"id":"sensor.voltage_rails.deep","domain":"sensors","status":"RUNTIME_DEPENDENT","provider":"vendor/super-io provider required","release":"0.21.9"},
    {"id":"stress.correctness.unified_taxonomy","domain":"stress","status":"COMPLETE","provider":"Phoenix Stress & Correctness v1","release":"0.22.3"},
    {"id":"stress.correctness.reproducible_corruption","domain":"stress","status":"COMPLETE","provider":"Phoenix Stress & Correctness v1","release":"0.22.3"},
    {"id":"stress.correctness.capacity_separation","domain":"stress","status":"COMPLETE","provider":"Phoenix Stress & Correctness v1","release":"0.22.3"},
    {"id":"stress.correctness.multi_domain","domain":"stress","status":"COMPLETE","provider":"CPU/RAM/VRAM/GPU compute/storage bounded runners","release":"0.22.3"},
    {"id":"release.hygiene.powershell_parser_gate","domain":"release","status":"COMPLETE","provider":"Phoenix PowerShell Parser Gate v1","release":"0.25.0rc6.post12","verification_status":"VERIFIED_SYNTHETIC","limitation":"Windows PowerShell parser executes during release/install validation; non-Windows build hosts may only verify source presence"},
    {"id":"release.hygiene.public_guard","domain":"release","status":"COMPLETE","provider":"Phoenix Public Guard V2 + Forge Project Hygiene v1","release":"0.25.0rc6.post12","verification_status":"VERIFIED_SYNTHETIC","limitation":"Read-only audit identifies release contamination and secrets; local-state removal is never automatic"},
    {"id":"architecture.shadow_tree.audit","domain":"architecture","status":"COMPLETE","provider":"Phoenix Shadow Tree Verifier/Deep Analyzer/Reference Resolver","release":"0.25.0rc6.post12","verification_status":"VERIFIED_SYNTHETIC","limitation":"Audit evidence does not authorize deletion"},
    {"id":"architecture.shadow_tree.quarantine","domain":"architecture","status":"COMPLETE","provider":"Phoenix Shadow Quarantine V4","release":"0.25.0rc6.post12","verification_status":"VERIFIED_SYNTHETIC","limitation":"Explicit operator action only; operational references block quarantine; move-only with rollback, never delete"},
]

def _normalize_capability(c: dict[str, Any]) -> dict[str, Any]:
    c=dict(c)
    c.setdefault("status","MISSING")
    c.setdefault("roadmap","NONE")
    c.setdefault("phase","CAPABILITY_FIRST")
    c.setdefault("dependency_class","NONE")
    c.setdefault("verification_state","BUILT")
    c.setdefault("verification_status", "UNVERIFIED_ON_REAL_HARDWARE" if c.get("status")=="COMPLETE" else "NOT_APPLICABLE_OR_RUNTIME_DEPENDENT")

    cid=str(c.get("id") or "")
    if cid=="telemetry.firestore":
        c["status"]="EXTERNAL_REQUIRED"
        c["dependency_class"]="EXTERNAL_SERVICE_DEPENDENT"

    if cid in {"cpu.msr_aperf_mperf","cpu.bclk_multiplier","memory.spd_live","cpu.intel.vendor_deep","cpu.amd.vendor_deep"}:
        c["dependency_class"]="PRIVILEGED_PROVIDER_DEPENDENT"
    elif cid.startswith("gpu.amd") or cid.startswith("gpu.nvidia") or cid.startswith("gpu.intel"):
        c["dependency_class"]="RUNTIME_VENDOR_DEPENDENT"
    elif cid in {"pcie.link.negotiated","pcie.resizable_bar","pcie.location.bdf","pcie.affinity.gpu_numa"}:
        c["dependency_class"]="RUNTIME_FIRMWARE_OS_DEPENDENT" if cid=="pcie.affinity.gpu_numa" else "RUNTIME_DRIVER_DEPENDENT"
    elif cid in {"storage.smartctl.read_only","storage.nvme.smart_health_log"}:
        c["dependency_class"]="EXTERNAL_SOFTWARE_DEPENDENT"
    elif cid=="storage.nvme.pcie_mapping":
        c["dependency_class"]="RUNTIME_FIRMWARE_OS_DEPENDENT"

    if cid=="gpu.vram.physical_chip_mapping":
        c["status"]="IMPOSSIBLE_GENERICALLY"
        c["roadmap"]="NONE"
        c["dependency_class"]="HARDWARE_INTERFACE_LIMIT"

    # 0.22.3 classification closure: these capabilities are not silently called
    # MISSING when the generic Phoenix stack cannot prove them without an
    # authoritative firmware/kernel/vendor source.
    external_required = {
        "pcie.location.physical_slot": "FIRMWARE_OR_VENDOR_DEPENDENT",
        "pcie.link.electrical_width": "FIRMWARE_OR_VENDOR_DEPENDENT",
        "pcie.errors.aer_counters": "KERNEL_OR_PLATFORM_DEPENDENT",
        "pcie.link.retrain_counter": "KERNEL_OR_PLATFORM_DEPENDENT",
    }
    if cid in external_required:
        c["status"]="EXTERNAL_REQUIRED"
        c["roadmap"]="NONE"
        c["dependency_class"]=external_required[cid]

    c.setdefault("source_contract", c.get("provider") or "none")
    c.setdefault("evidence_contract", "provider evidence required; UNKNOWN is preserved when unavailable")
    c.setdefault("test_contract", "synthetic/regression self-test plus runtime verification when hardware-dependent")
    c.setdefault("confidence_policy", "no confidence inflation without provider evidence")
    c.setdefault("limitation", "none declared" if c.get("status")=="COMPLETE" else "availability/coverage follows capability status")

    if c["status"] in {"COMPLETE","PARTIAL","RUNTIME_DEPENDENT","EXTERNAL_REQUIRED","IMPOSSIBLE_GENERICALLY"}:
        c["implementation_state"]="IMPLEMENTED_OR_RESOLVED"
    else:
        c["implementation_state"]="NOT_IMPLEMENTED"
    return c

def build() -> dict[str, Any]:
    caps=[_normalize_capability(x) for x in CAPABILITIES]
    summary={}
    for row in caps:
        summary[row["status"]]=summary.get(row["status"],0)+1
    return {
        "schema":SCHEMA,
        "status":"OK",
        "summary":summary,
        "capabilities":caps,
        "invariants":{
            "planned_is_development_axis_not_capability_state":True,
            "planned_is_not_claimed_functional":True,
            "runtime_dependent_requires_provider_evidence":True,
            "unknown_is_not_guessed":True,
            "future_execution_is_separate_phase":True,
        },
    }
