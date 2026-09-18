from __future__ import annotations

from typing import Any

SCHEMA = "phoenix.forge.capability-matrix/v34"


def _available(node: Any) -> bool:
    return isinstance(node, dict) and bool(node.get("available"))


def build(inspector: dict[str, Any]) -> dict[str, Any]:
    deep = inspector.get("deep_inventory", {})
    cpu = deep.get("cpu", inspector.get("cpu", {}))
    memory = deep.get("memory", inspector.get("memory", {}))
    gpus = deep.get("gpus", inspector.get("gpus", []))
    platform = deep.get("platform", {})
    sensors = inspector.get("sensors", {})
    pcie_health = inspector.get("pcie_health", {})
    pcie_link = inspector.get("pcie_link", {})
    pcie_link_value = pcie_link.get("value", {}) if isinstance(pcie_link,dict) else {}
    pcie_link_devices = pcie_link_value.get("devices", []) if isinstance(pcie_link_value,dict) else []
    pcie_current_speed_ok = any((d.get("current") or {}).get("generation") for d in pcie_link_devices if isinstance(d,dict))
    pcie_current_width_ok = any((d.get("current") or {}).get("width") for d in pcie_link_devices if isinstance(d,dict))
    pcie_max_ok = any((d.get("maximum") or {}).get("generation") or (d.get("maximum") or {}).get("width") for d in pcie_link_devices if isinstance(d,dict))
    rebar_ok = any((d.get("resizable_bar") or {}).get("status") not in (None,"UNKNOWN") for d in pcie_link_devices if isinstance(d,dict))

    def item(product: str, category: str, capability: str, state: str, provider: str, note: str = "") -> dict[str, str]:
        return {"product": product, "category": category, "capability": capability, "state": state, "provider": provider, "note": note}

    cpuid_ok = _available(cpu.get("cpuid", {}))
    cpuid_deep_ok = _available(cpu.get("cpuid_deep", {}))
    instruction_ok = _available(cpu.get("instruction_sets", {}))
    native_topology_ok = _available(cpu.get("native_topology", {}))
    address_width_ok = _available(cpu.get("address_width", {}))
    cpuid_frequency_ok = _available(cpu.get("frequency_cpuid", {}))
    runtime_clock_ok = _available(cpu.get("runtime_clock", {}))
    msr_clock_node = inspector.get("msr_clock_intelligence", {})
    msr_clock_value = msr_clock_node.get("value", {}) if isinstance(msr_clock_node, dict) else {}
    aperf_ok = bool((msr_clock_value.get("aperf_mperf") or {}).get("available")) if isinstance(msr_clock_value, dict) else False
    bclk_ok = bool((msr_clock_value.get("bclk_multiplier") or {}).get("available")) if isinstance(msr_clock_value, dict) else False
    cache_ok = _available(cpu.get("caches", {}))
    package_ok = _available(cpu.get("packages", {}))
    topo_ok = _available(cpu.get("compute_topology", {}))
    dimm_ok = _available(memory.get("modules", {}))
    spd_node = memory.get("raw_spd", {})
    spd_arch = memory.get("spd_architecture", {}) if isinstance(memory.get("spd_architecture"), dict) else {}
    spd_raw_ok = _available(spd_node)
    spd_live_ok = bool(spd_arch.get("live_smbus_available"))
    board_ok = _available(platform.get("baseboard", {}))
    bios_ok = _available(platform.get("bios", {}))
    gpu_present = bool(gpus)
    pcie_ok = any(_available(g.get("pcie", {})) for g in gpus)
    vulkan_ok = any(_available(g.get("vulkan", {})) for g in gpus)
    dxgi_ok = any(_available(g.get("dxgi", {})) for g in gpus)
    driver_ok = any(_available(g.get("driver", {})) for g in gpus)
    vram_ok = any(_available(g.get("memory", {})) for g in gpus)
    sensor_ok = _available(sensors)

    rows = [
        # Phoenix CPU Inspector coverage
        item("Phoenix CPU Inspector", "CPU", "Processor name/vendor/socket", "DONE" if package_ok else "PARTIAL", "CIM + OS"),
        item("Phoenix CPU Inspector", "CPU", "Family/model/stepping/revision", "DONE" if package_ok else "PARTIAL", "CIM + CPUID"),
        item("Phoenix CPU Inspector", "CPU", "Processor ID / CPUID leaves", "DONE" if cpuid_deep_ok else ("PARTIAL" if cpuid_ok else "MISSING"), "Forge native CPUID"),
        item("Phoenix CPU Inspector", "CPU", "Instruction set flags", "DONE" if instruction_ok and cpuid_deep_ok else ("PARTIAL" if cpuid_ok else "MISSING"), "Forge native CPUID feature leaves"),
        item("Phoenix CPU Inspector", "CPU", "Physical/virtual address width", "DONE" if address_width_ok else "MISSING", "CPUID 0x80000008"),
        item("Phoenix CPU Inspector", "CPU", "Native SMT/core topology leaves", "DONE" if native_topology_ok else "PARTIAL", "CPUID 0x1F/0x0B", "Windows group/NUMA topology remains an independent source."),
        item("Phoenix CPU Inspector", "CPU", "CPUID base/max/bus frequency enumeration", "DONE" if cpuid_frequency_ok else "PARTIAL", "CPUID 0x15/0x16", "Zero-valued leaves are treated as UNKNOWN, not failure."),
        item("Phoenix CPU Inspector", "CPU", "Core/thread/socket topology", "DONE" if topo_ok and package_ok else "PARTIAL", "Compute Fabric + CIM"),
        item("Phoenix CPU Inspector", "CPU", "Processor Groups / >64 logical CPUs", "DONE" if topo_ok else "PARTIAL", "Windows native topology"),
        item("Phoenix CPU Inspector", "CPU", "NUMA node inventory", "DONE" if topo_ok else "PARTIAL", "Windows native topology"),
        item("Phoenix CPU Inspector", "CPU", "Per-logical-processor current/max clock", "DONE" if runtime_clock_ok else ("PARTIAL" if package_ok else "MISSING"), "Windows CallNtPowerInformation + psutil fallback", "OS-reported clock is not APERF/MPERF effective clock."),
        item("Phoenix CPU Inspector", "CPU", "Clock sampling envelope/min-average-max", "DONE" if runtime_clock_ok else "PARTIAL", "Forge CPU Runtime Telemetry"),
        item("Phoenix CPU Inspector", "CPU", "Normalized CPU Deep evidence view", "DONE" if cpuid_deep_ok and runtime_clock_ok else "PARTIAL", "Phoenix CPU Deep Inspector v1", "Keeps advertised, observed OS and APERF/MPERF effective clocks semantically separate."),
        item("Phoenix CPU Inspector", "CPU", "Throttling evidence gate", "DONE", "Phoenix CPU Deep Inspector v1", "Low idle clock alone never becomes a throttling verdict; thermal/power/control evidence is required."),
        item("Phoenix CPU Inspector", "CPU", "APERF/MPERF effective clock", "DONE" if aperf_ok else "MISSING", "Verified MSR provider via Forge Provider Runtime", "Not inferred from CurrentMhz."),
        item("Phoenix CPU Inspector", "CPU", "BCLK/multiplier precision", "DONE" if bclk_ok else "MISSING", "Verified MSR/chipset provider via Forge Provider Runtime", "Never inferred from advertised/current MHz."),
        item("Phoenix CPU Inspector", "Cache", "Cache hierarchy and sizes", "DONE" if cache_ok else "PARTIAL", "CPUID deterministic cache leaf + CIM fallback"),
        item("Phoenix CPU Inspector", "Cache", "Cache associativity/line/sets/ways", "DONE" if cpuid_deep_ok and cache_ok else ("PARTIAL" if cache_ok else "MISSING"), "CPUID deterministic cache leaf 0x4"),
        item("Phoenix CPU Inspector", "Cache", "Cache sharing/inclusive topology", "DONE" if cpuid_deep_ok and cache_ok else "MISSING", "CPUID deterministic cache leaf 0x4"),
        item("Phoenix CPU Inspector", "Mainboard", "Manufacturer/model/revision", "DONE" if board_ok else "MISSING", "SMBIOS/CIM"),
        item("Phoenix CPU Inspector", "Mainboard", "BIOS vendor/version/date", "DONE" if bios_ok else "MISSING", "SMBIOS/CIM"),
        item("Phoenix Memory Inspector", "Memory", "DIMM identity/capacity/speed", "DONE" if dimm_ok else "MISSING", "SMBIOS/CIM"),
        item("Phoenix Memory Inspector", "Memory", "Configured clock/data width/ECC metadata", "DONE" if dimm_ok else "MISSING", "SMBIOS/CIM"),
        item("Phoenix Memory Inspector", "SPD", "Raw SPD bytes", "DONE" if spd_live_ok else ("PARTIAL" if spd_raw_ok else "MISSING"), "Forge SPD provider", "Offline dumps count as PARTIAL; live slot reads require privileged SMBus access."),
        item("Phoenix Memory Inspector", "SPD", "JEDEC base timing decode", "PARTIAL" if spd_raw_ok else "MISSING", "Forge SPD parser", "DDR3/DDR4 geometry, DDR4 CRC and supported CAS evidence are decoded from raw SPD; active timings remain runtime-only."),
        item("Phoenix Memory Inspector", "SPD", "XMP/EXPO profile decode", "DONE", "Phoenix Memory/SPD parser v4", "Advertised raw SPD profiles only; active BIOS selection and stability are not inferred."),
        item("Phoenix Memory Inspector", "SPD", "DIMM voltage tables", "MISSING", "Privileged SMBus/raw SPD parser required"),

        # Phoenix GPU Inspector coverage
        item("Phoenix GPU Inspector", "GPU", "GPU name/vendor and PCI IDs", "DONE" if gpu_present else "MISSING", "PnP/CIM + Vulkan"),
        item("Phoenix GPU Inspector", "GPU", "Subsystem vendor/device and revision", "DONE" if gpu_present else "MISSING", "PnP hardware ID"),
        item("Phoenix GPU Inspector", "PCIe", "Bus/device/function physical location", "DONE" if pcie_ok else "PARTIAL", "Windows PnP location properties"),
        item("Phoenix GPU Inspector", "PCIe", "Negotiated/current link generation", "DONE" if pcie_current_speed_ok else "PARTIAL", "Windows PCIe device properties", "Current speed may downshift at idle; load validation is required before a bottleneck claim."),
        item("Phoenix GPU Inspector", "PCIe", "Negotiated/current lane width", "DONE" if pcie_current_width_ok else "PARTIAL", "Windows PCIe device properties", "Reported only when the platform exposes current/max width properties."),
        item("Phoenix GPU Inspector", "PCIe", "Maximum link generation/width", "DONE" if pcie_max_ok else "PARTIAL", "Windows PCIe device properties"),
        item("Phoenix GPU Inspector", "PCIe", "Resizable BAR evidence", "DONE" if rebar_ok else "PARTIAL", "Windows explicit device-property evidence", "Never inferred from VRAM capacity."),
        item("Phoenix GPU Inspector", "PCIe", "Persistent device key independent of runtime index", "DONE" if gpu_present else "MISSING", "Forge Compute Fabric"),
        item("Phoenix GPU Inspector", "Driver", "Driver version/date/provider/INF/signature", "DONE" if driver_ok else "PARTIAL", "Win32_PnPSignedDriver"),
        item("Phoenix GPU Inspector", "VRAM", "Dedicated VRAM capacity", "DONE" if vram_ok else "PARTIAL", "DXGI/ADL/Vulkan evidence chain"),
        item("Phoenix GPU Inspector", "VRAM", "Memory vendor/type/bus width", "PARTIAL", "VBIOS/vendor provider", "Requires ROM/vendor-specific provider for authoritative values."),
        item("Phoenix GPU Inspector", "API", "Vulkan version/heaps/types/queues/limits", "DONE" if vulkan_ok else "MISSING", "Forge native Vulkan"),
        item("Phoenix GPU Inspector", "API", "DXGI adapter properties", "DONE" if dxgi_ok else "PARTIAL", "Forge native DXGI"),
        item("Phoenix GPU Inspector", "Sensors", "Clock/temperature/load/fan telemetry", "DONE" if sensor_ok else "PARTIAL", "ADL/LHM/vendor APIs"),
        item("Phoenix GPU Inspector", "VBIOS", "ROM parsing/checksum/PCI ROM/ATOMBIOS metadata", "DONE", "Forge VBIOS parser"),
        item("Phoenix GPU Inspector", "VBIOS", "Live VBIOS dump/lookup per device", "PARTIAL", "Forge VBIOS dump/provider", "Availability depends on platform/permissions."),
        item("Phoenix GPU Inspector", "Topology", "NUMA affinity with evidence/provenance", "PARTIAL", "Compute Fabric", "UNKNOWN is preserved until independently proven."),
        item("Phoenix GPU Inspector", "VRAM", "Physical GDDR chip address mapping", "MISSING", "Not exposed by Vulkan", "Logical allocation windows are not physical DRAM chip addresses."),

        # Phoenix Stress & Correctness coverage
        item("Phoenix Stress & Correctness", "Stress", "CPU sustained stress", "DONE", "Forge Crucible/native benchmark"),
        item("Phoenix Stress & Correctness", "Stress", "RAM correctness/load", "DONE", "Forge Crucible/native memory benchmark"),
        item("Phoenix Stress & Correctness", "Stress", "Combined CPU/RAM load", "DONE", "Forge Crucible"),
        item("Phoenix Stress & Correctness", "GPU", "GPU compute stress", "DONE", "Native Vulkan shader"),
        item("Phoenix Stress & Correctness", "VRAM", "VRAM pattern validation", "DONE", "Native Vulkan"),
        item("Phoenix Stress & Correctness", "VRAM", "VRAM logical window mapping", "DONE", "Native Vulkan"),
        item("Phoenix Stress & Correctness", "GPU", "Device-to-device bandwidth", "DONE", "Native Vulkan"),
        item("Phoenix Stress & Correctness", "Safety", "Thermal limits/cancellation", "DONE", "Benchmark supervisor"),
        item("Phoenix Stress & Correctness", "Platform", "PCIe/WHEA event correlation", "DONE" if _available(pcie_health) else "PARTIAL", "Windows WHEA event log"),
        item("Phoenix Stress & Correctness", "Power", "PSU/power transient specialized stress", "PARTIAL", "Combined workloads", "Dedicated electrical instrumentation is outside generic software visibility."),

        # Forge-only
        item("Phoenix Forge Core", "Intelligence", "Per-workload hardware confidence", "DONE", "GPU ledger + workload state"),
        item("Phoenix Forge Core", "Intelligence", "Validated output delivery and CPU fallback", "DONE", "Delivery Guard"),
        item("Phoenix Forge Core", "Intelligence", "Historical GPU fault correlation", "DONE", "Safety ledger + fault correlator"),
        item("Phoenix Forge Core", "Intelligence", "Persistent GPU identity across runtime index changes", "DONE", "device_key"),
        item("Phoenix Forge Core", "Topology", "Compute Fabric sockets/groups/NUMA/PCIe", "DONE", "Compute Fabric"),
        item("Phoenix Forge Core", "Topology", "Evidence confidence/provenance", "DONE", "Compute Fabric + Hardware Inspector"),
        item("Phoenix Forge Core", "Intelligence", "Hardware Evidence Graph with explicit source conflicts", "DONE", "Evidence Graph v1", "Conflicting providers are surfaced rather than silently merged."),
        item("Phoenix Forge Core", "Intelligence", "Setup-wide evidence-aware analysis", "DONE", "Setup Intelligence v1"),
        item("Phoenix Forge Core", "Qualification", "Pre/post VBIOS flash qualification dossier", "DONE", "GPU qualification"),
        item("Phoenix Forge Core", "Reliability", "OOM/capacity separated from physical corruption", "DONE", "Safety policy"),
        item("Phoenix Forge Core", "Telemetry", "CPU runtime clock telemetry without false throttling verdict", "DONE" if runtime_clock_ok else "PARTIAL", "Native Windows power API + guarded fallback"),
        item("Phoenix Forge Core", "Reliability", "Golden baseline and immutable evidence", "PARTIAL", "Forge baseline/report", "Cryptographic signing remains policy/configuration dependent."),
        item("Phoenix Forge Core", "Storage", "NVMe deep inventory/reliability counters", "DONE", "Windows Storage CIM + reliability counters"),
        item("Phoenix Sensor Intelligence", "Sensors", "Sensor fusion with provenance contract", "DONE", "Phoenix Pulse + vendor fallbacks"),
        item("Phoenix Forge Core", "Governance", "Audit gap tracker / provider contracts", "DONE", "Capability Registry v2"),
        item("Phoenix Forge Core", "Intelligence", "Evidence-based hardware recommendations", "DONE", "Configuration Auditor + Evidence Graph"),
        item("Phoenix Forge Core", "Governance", "Explicit telemetry consent + payload preview + revoke", "DONE", "Telemetry Governance v1"),
        item("Phoenix Forge Core", "Governance", "Outbound telemetry sanitizer / sensitive-field deny policy", "DONE", "Telemetry Sanitizer v1"),
        item("Phoenix Forge Core", "Telemetry", "Firestore/gateway export with local queue", "PARTIAL", "Firestore Telemetry v1", "Delivery requires configured gateway or Google Cloud credentials; collection remains OFF without user consent."),
        item("Phoenix Forge Core", "Telemetry", "Non-blocking telemetry preview with stale-while-revalidate snapshot", "DONE", "Snapshot Cache + Telemetry Payload", "UI never declares Forge offline just because a deep preview is still warming."),
        item("Phoenix Forge Core", "Identity", "Physical GPU alias bound to persistent device_key", "DONE", "GPU Identity Registry v1", "Human label is metadata only; runtime device_index never becomes persistent identity."),
        item("Phoenix Forge Core", "Providers", "Non-blocking privileged-provider health supervision", "DONE", "Provider Runtime v1", "Provider handshake failures/timeouts never block Forge health or UI."),
    ]

    rows.extend([
        item("Phoenix Forge Core", "Intelligence", "Evidence-based configuration auditor", "DONE", "Forge Configuration Auditor", "Flags asymmetry/risk only when supported by provider evidence."),
        item("Phoenix Forge Core", "Intelligence", "Bottleneck claims require measured evidence", "DONE", "Forge Configuration Auditor", "No PCIe/storage/thermal bottleneck is invented from topology alone."),
        item("Phoenix Forge Core", "PCIe", "Idle PCIe speed downshift guarded from false bottleneck claims", "DONE", "PCIe Link Intelligence v1"),
        item("Phoenix Forge Core", "PCIe", "Measured lane-width degradation surfaced separately from speed downshift", "DONE", "PCIe Link Intelligence v1"),
        item("Phoenix Forge Core", "Providers", "Verified read-only privileged provider execution", "DONE", "Provider Action Runtime v1", "Manifest hash + handshake + capability allowlist + shell=false + timeout/circuit breaker."),
    ])

    rows.extend([
        item("Phoenix Forge Core", "CPU", "MSR semantic clock adapter with evidence-only APERF/MPERF", "DONE", "MSR Clock Intelligence v1", "Availability of actual values remains provider-dependent; OS CurrentMhz is never relabeled as effective clock."),
        item("Phoenix Forge Core", "Telemetry", "Non-blocking manual telemetry send path", "DONE", "Snapshot Cache + Firestore Telemetry", "Manual send never blocks the UI waiting for a new deep hardware payload."),
    ])


    rows.extend([
        item("Phoenix Forge Core", "CPU", "Windows MSR provider ABI + APERF/MPERF delta derivation", "DONE", "Phoenix MSR Provider Foundation v1", "Kernel driver is intentionally not bundled; actual MSR access remains runtime-dependent and fail-closed."),
        item("Phoenix Forge Core", "Scheduler", "Evidence-aware multi-device placement planning", "DONE", "Compute Fabric + GPU Safety + workload policy", "SINGLE/PARALLEL planning implemented; COOPERATIVE remains backend-dependent."),
        item("Phoenix Forge Core", "Scheduler", "Device lease + dispatch/result correlation policy", "DONE", "Scheduler Execution Policy v1", "Safety is revalidated before dispatch; device_key leases prevent concurrent claims; backend execution remains a separate adapter."),
        item("Phoenix Forge Core", "Scheduler", "Phoenix Engine scheduler dispatch adapter for Phoenix Llama Runtime", "DONE", "Phoenix Engine + Forge Scheduler Execution Policy", "Engine obtains a verified dispatch before LLM execution and reports completion back to Forge; Phoenix Llama Runtime integration is active."),
        item("Phoenix Forge Core", "Scheduler", "Phoenix LaVa Foundation Adapter", "PARTIAL", "Phoenix LaVa Foundation -> Phoenix Llama Runtime", "Q5_K_M/Q6_K foundation profiles and CPU/GPU/HYBRID/AUTO policy are implemented; model file and runtime/hardware remain external runtime dependencies; no claim of Phoenix-trained weights."),
        item("Phoenix Forge Core", "Scheduler", "Phoenix Diffusion scheduler dispatch adapter", "DONE", "Phoenix Engine + Forge Scheduler Execution Policy + Phoenix Diffusion", "Direct image generation obtains a verified dispatch, forces CPU when required, authorizes GPU when safe, and reports result/lease release back to Forge."),
        item("Phoenix Forge Core", "Scheduler", "Adaptive runtime feedback / evidence-weighted placement", "DONE", "Scheduler Runtime Feedback v1", "Successful and failed executions are correlated by workload/backend/device_key; soft score adjustments guide future placement but never override GPU Safety."),
    ])

    rows.extend([
        item("Phoenix Forge Core", "Memory", "Phoenix SMBus provider ABI for live SPD", "DONE", "Phoenix SMBus Provider Foundation v1", "Kernel driver intentionally not bundled; live reads remain runtime-dependent."),
        item("Phoenix Forge Core", "Memory", "DDR3/DDR4 geometry + CRC/timing evidence", "DONE", "Phoenix Memory/SPD parser v3"),
        item("Phoenix Forge Core", "Memory", "DDR5 conservative SPD identity decode", "DONE", "Phoenix Memory/SPD parser v3", "Full DDR5 timings and XMP/EXPO profile decoding remain explicitly incomplete."),
        item("Phoenix Sensor Intelligence", "Sensors", "Sensor provider coverage inventory", "DONE", "Provider Runtime + AHDE + Sensor Fusion"),
        item("Phoenix Forge Core", "Governance", "Capability completion audit without placement decisions", "DONE", "Capability Completion v1", "Tracks what is complete/runtime-dependent/planned without deciding execution placement."),
    ])

    rows.extend([
        item("Phoenix GPU Inspector", "Telemetry", "Normalized per-device deep telemetry with explicit provenance", "DONE", "Phoenix GPU Deep Telemetry v1"),
        item("Phoenix GPU Inspector", "Telemetry", "AMD read-only vendor telemetry provider", "PARTIAL", "AMD ADL", "Availability and individual fields depend on driver/GPU generation; unavailable fields remain UNKNOWN."),
        item("Phoenix GPU Inspector", "Telemetry", "NVIDIA read-only vendor telemetry provider", "PARTIAL", "NVIDIA management CLI", "Availability depends on installed supported vendor tooling/driver."),
        item("Phoenix GPU Inspector", "Telemetry", "Intel vendor-deep telemetry provider", "PARTIAL", "Phoenix Intel GPU Deep v1 / Level Zero Sysman", "Read-only Sysman provider implemented; runtime/hardware dependent. Untyped sensor readings and ambiguous multi-GPU mapping are not guessed."),
        item("Phoenix GPU Inspector", "VBIOS", "Vendor VBIOS metadata with explicit provenance", "PARTIAL", "Vendor provider", "Only present when exposed by a trustworthy vendor provider."),
        item("Phoenix GPU Inspector", "VBIOS", "VBIOS metadata SHA-256 kept distinct from ROM-binary SHA-256", "DONE", "Phoenix GPU Deep Telemetry v1"),
        item("Phoenix Sensor Intelligence", "GPU", "GPU hotspot/edge/fan/clock/power fallback fusion with provenance", "DONE", "Vendor provider + Sensor Intelligence", "Unsupported values remain UNKNOWN; zero is never invented."),
    ])

    rows.extend([
        item("Phoenix GPU Inspector", "PCIe", "Deep BDF/root/parent-chain inspection with provenance", "DONE", "Phoenix PCIe Deep Inspection v1"),
        item("Phoenix GPU Inspector", "PCIe", "Physical chassis slot identity", "MISSING", "none", "Not inferred from BDF or LocationInfo."),
        item("Phoenix GPU Inspector", "PCIe", "Electrical slot width", "MISSING", "none", "Distinct from negotiated/max lane width; active provider does not expose it."),
        item("Phoenix GPU Inspector", "PCIe", "GPU-to-NUMA locality", "PARTIAL", "Windows PnP proximity domain + GetNumaProximityNodeEx", "Runtime-dependent; PCI root is never treated as NUMA affinity."),
        item("Phoenix GPU Inspector", "PCIe", "Per-device AER error counters", "MISSING", "none", "Requires authoritative provider/counter source."),
        item("Phoenix GPU Inspector", "PCIe", "Link retrain counter", "MISSING", "none", "Requires authoritative provider/counter source."),
        item("Phoenix GPU Inspector", "PCIe", "Current/max theoretical bandwidth derivation", "DONE", "Phoenix PCIe Deep Inspection v1", "Derived from proven generation and lane width only."),
    ])

    rows.extend([
        item("Phoenix Storage Inspector", "Inventory", "Physical disk/NVMe inventory with per-field provenance", "DONE", "Phoenix Storage Inspector v2"),
        item("Phoenix Storage Inspector", "Health", "Windows reliability counters: temperature/wear/power-on/errors/latency", "PARTIAL", "Windows Storage CIM", "Availability varies by controller/driver/device."),
        item("Phoenix Storage Inspector", "NVMe", "NVMe SMART health log via optional read-only provider", "PARTIAL", "smartctl JSON", "Runtime-dependent; unsupported fields remain UNKNOWN."),
        item("Phoenix Storage Inspector", "Safety", "Guarded provider matching: serial exact preferred; unmatched data not merged", "DONE", "Phoenix Storage Inspector v2"),
        item("Phoenix Storage Inspector", "Semantics", "Windows Wear preserved as provider-native rather than silently relabeled", "DONE", "Phoenix Storage Inspector v2"),
        item("Phoenix Storage Inspector", "PCIe", "Authoritative NVMe-to-BDF/link mapping", "PARTIAL", "Phoenix Storage PCIe Mapping v1", "Runtime-dependent Windows PnP parent-chain mapping; model-name-only matching is prohibited and missing link properties remain UNKNOWN."),
        item("Phoenix Storage Inspector", "Correctness", "Bounded sequential/random file validation with readback", "DONE", "Phoenix Storage validation"),
    ])

    rows.extend([
        item("Phoenix Memory Inspector", "SPD", "SPD inventory / parsed DIMM evidence", "PARTIAL", "Phoenix Memory/SPD", "Live SPD remains privileged-provider dependent."),
        item("Phoenix Memory Inspector", "Profiles", "XMP/EXPO decoding", "DONE", "Phoenix Memory/SPD parser v4", "Advertised profiles only; runtime selection is separate evidence."),
        item("Phoenix PCIe Intelligence", "Topology", "BDF/root/parent-chain/link normalization", "DONE", "Phoenix PCIe Deep Inspection"),
        item("Phoenix PCIe Intelligence", "Limits", "Physical slot/electrical width/AER remain explicit when unprovable", "DONE", "Phoenix PCIe Deep Inspection", "GPU NUMA is runtime-dependent on proximity-domain evidence; UNKNOWN is preferred to inference."),
    ])

    rows.extend([
        item("Phoenix Stress & Correctness", "Taxonomy", "Unified PASS/CAPACITY/INSTABILITY/CORRUPTION classification", "DONE", "Phoenix Stress & Correctness v1"),
        item("Phoenix Stress & Correctness", "Evidence", "Reproducible corruption requires at least two same-scope observations", "DONE", "Phoenix Stress & Correctness v1"),
        item("Phoenix Stress & Correctness", "Safety", "OOM/allocation/timeout are not physical-defect proof", "DONE", "Phoenix Stress & Correctness v1"),
        item("Phoenix Stress & Correctness", "CPU", "Bounded CPU stress execution", "DONE", "Phoenix Crucible + Stress & Correctness"),
        item("Phoenix Stress & Correctness", "RAM", "Patterned user-space RAM correctness test", "DONE", "Phoenix Memory + Stress & Correctness"),
        item("Phoenix Stress & Correctness", "VRAM", "Device-local Vulkan VRAM validation with device identity", "DONE" if vulkan_ok else "PARTIAL", "Phoenix Memory + Stress & Correctness"),
        item("Phoenix Stress & Correctness", "GPU", "Vulkan compute correctness / mismatch classification", "DONE" if vulkan_ok else "PARTIAL", "Phoenix Crucible + Stress & Correctness"),
        item("Phoenix Stress & Correctness", "Storage", "Non-destructive tempfile write/read hash validation", "DONE", "Phoenix Storage + Stress & Correctness"),
    ])

    rows.extend([
        item("Phoenix Sensor Intelligence", "Normalization", "Cross-provider sensor identity normalization", "DONE", "Phoenix Sensor Intelligence Deep v1"),
        item("Phoenix Sensor Intelligence", "Consensus", "Multi-source consensus without blind averaging", "DONE", "Phoenix Sensor Intelligence Deep v1"),
        item("Phoenix Sensor Intelligence", "Conflict", "Detect disagreement beyond per-kind tolerance", "DONE", "Phoenix Sensor Intelligence Deep v1"),
        item("Phoenix Sensor Intelligence", "Freshness", "Stale/disappeared sensor detection", "DONE", "Phoenix Sensor Intelligence Deep v1"),
        item("Phoenix Sensor Intelligence", "Plausibility", "Implausible-value filtering with explicit event", "DONE", "Phoenix Sensor Intelligence Deep v1"),
        item("Phoenix Sensor Intelligence", "Motherboard", "Motherboard/chipset/VRM/fan/rail deep telemetry", "PARTIAL", "runtime providers", "Provider and hardware exposure dependent."),
        item("Phoenix Sensor Intelligence", "Super I/O", "Safe Super I/O discovery/provider access", "PARTIAL", "runtime providers", "No generic privileged I/O is exposed."),
    ])

    weights = {"DONE": 1.0, "PARTIAL": 0.5, "MISSING": 0.0}
    products: dict[str, dict[str, Any]] = {}
    for product in sorted({r["product"] for r in rows}):
        own = [r for r in rows if r["product"] == product]
        products[product] = {
            "total": len(own),
            "done": sum(r["state"] == "DONE" for r in own),
            "partial": sum(r["state"] == "PARTIAL" for r in own),
            "missing": sum(r["state"] == "MISSING" for r in own),
            "coverage_percent": round(100 * sum(weights[r["state"]] for r in own) / len(own), 1),
        }

    public_order = [
        "Phoenix Forge Core",
        "Phoenix CPU Inspector",
        "Phoenix GPU Inspector",
        "Phoenix Memory Inspector",
        "Phoenix PCIe Intelligence",
        "Phoenix Sensor Intelligence",
        "Phoenix Storage Inspector",
        "Phoenix Stress & Correctness",
    ]
    ordered_products = {name: products[name] for name in public_order if name in products}
    for name, value in products.items():
        if name not in ordered_products:
            ordered_products[name] = value

    return {
        "schema": SCHEMA,
        "method": "DONE=1, PARTIAL=0.5, MISSING=0",
        "claims": "Phoenix-native hardware capability coverage with evidence, provenance and explicit uncertainty",
        "public_notice": "Capacidades implementadas nativamente pela Phoenix, com proveniência, validação e diagnóstico próprios.",
        "public_order": public_order,
        "subsystems": ordered_products,
        "products": ordered_products,  # compatibility alias for older Aviary renderers
        "capabilities": rows,
    }

