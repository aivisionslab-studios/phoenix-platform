from __future__ import annotations

import time
from collections import Counter
from typing import Any

SCHEMA = "phoenix.forge.configuration-audit/v1"


def _ev_value(node: Any, default=None):
    if isinstance(node, dict) and {"value", "available", "provider", "confidence"}.issubset(node.keys()):
        return node.get("value") if node.get("available") else default
    return node if node is not None else default


def _num(v: Any) -> float | None:
    try:
        if v in (None, ""): return None
        return float(v)
    except Exception:
        return None


def _finding(kind: str, severity: str, title: str, evidence: list[dict[str, Any]], recommendation: str, *, confidence: str = "MEDIUM", scope: str = "SYSTEM", blocking: bool = False) -> dict[str, Any]:
    return {
        "kind": kind, "severity": severity, "title": title, "scope": scope,
        "confidence": confidence, "blocking": blocking,
        "evidence": evidence, "recommendation": recommendation,
    }


def _memory_findings(deep: dict[str, Any]) -> list[dict[str, Any]]:
    findings=[]
    memory=deep.get("memory", {}) if isinstance(deep, dict) else {}
    modules=_ev_value(memory.get("modules"), []) or []
    if not isinstance(modules, list): modules=[]
    populated=[m for m in modules if isinstance(m, dict) and _num(m.get("Capacity")) not in (None,0)]
    if len(populated) >= 2:
        speeds=[int(x) for x in (_num(m.get("ConfiguredClockSpeed")) or _num(m.get("Speed")) for m in populated) if x and x>0]
        distinct=sorted(set(speeds))
        if len(distinct)>1:
            findings.append(_finding(
                "MEMORY_SPEED_ASYMMETRY", "MEDIUM", "DIMMs report different configured/supported speeds",
                [{"provider":"Win32_PhysicalMemory","values_mhz":distinct,"module_count":len(populated)}],
                "Review DIMM population, BIOS memory settings and SPD data before assuming all channels operate at the same rate.",
                confidence="HIGH", scope="MEMORY"))
        caps=[int(_num(m.get("Capacity")) or 0) for m in populated]
        if len(set(caps))>1:
            findings.append(_finding(
                "MEMORY_CAPACITY_ASYMMETRY", "INFO", "Installed DIMMs have different capacities",
                [{"provider":"Win32_PhysicalMemory","capacities_bytes":sorted(set(caps)),"module_count":len(populated)}],
                "Capacity asymmetry is not automatically a fault. Verify channel/interleave mapping before drawing a performance conclusion.",
                confidence="HIGH", scope="MEMORY"))
    spd=memory.get("spd_architecture", {}) if isinstance(memory.get("spd_architecture"), dict) else {}
    if not spd.get("live_smbus_available"):
        findings.append(_finding(
            "SPD_LIVE_EVIDENCE_MISSING", "INFO", "Live SMBus/SPD provider is not available",
            [{"provider":"Forge SPD architecture","live_smbus_available":False}],
            "Keep JEDEC/XMP/EXPO/channel/rank claims UNKNOWN unless supported by an offline SPD dump or a future privileged SMBus provider.",
            confidence="PROVEN", scope="MEMORY"))
    return findings


def _cpu_numa_findings(deep: dict[str, Any]) -> list[dict[str, Any]]:
    findings=[]
    cpu=deep.get("cpu", {}) if isinstance(deep, dict) else {}
    packages=_ev_value(cpu.get("packages"), []) or []
    topo=_ev_value(cpu.get("compute_topology"), {}) or {}
    if not isinstance(packages, list): packages=[]
    socket_count=len([p for p in packages if isinstance(p,dict)])
    numa=topo.get("numa_nodes", []) if isinstance(topo,dict) else []
    groups=topo.get("processor_groups", []) if isinstance(topo,dict) else []
    if socket_count>1 and not numa:
        findings.append(_finding(
            "MULTI_SOCKET_NUMA_UNRESOLVED", "MEDIUM", "Multiple CPU packages detected but NUMA nodes are not proven",
            [{"provider":"CIM","socket_count":socket_count},{"provider":"Compute Fabric","numa_nodes":0}],
            "Do not pin workloads across sockets until NUMA topology is available. Prefer conservative placement and preserve UNKNOWN affinity.",
            confidence="HIGH", scope="CPU_NUMA"))
    if socket_count>1 and numa:
        findings.append(_finding(
            "MULTI_SOCKET_TOPOLOGY_PRESENT", "INFO", "Multi-socket/NUMA topology is present",
            [{"provider":"CIM","socket_count":socket_count},{"provider":"Compute Fabric","numa_nodes":len(numa),"processor_groups":len(groups)}],
            "Use NUMA-aware placement only where CPU/GPU/memory locality has independent evidence.",
            confidence="HIGH", scope="CPU_NUMA"))
    return findings


def _gpu_findings(deep: dict[str, Any]) -> list[dict[str, Any]]:
    findings=[]
    gpus=deep.get("gpus", []) if isinstance(deep, dict) else []
    if not isinstance(gpus,list): gpus=[]
    keys=[]
    for i,g in enumerate(gpus):
        if not isinstance(g,dict): continue
        key=g.get("device_key")
        if key: keys.append(key)
        pcie=_ev_value(g.get("pcie"), {}) or {}
        numa=_ev_value(g.get("numa_affinity"), {}) or {}
        if isinstance(pcie,dict) and pcie.get("status") != "PROVEN":
            findings.append(_finding(
                "GPU_PCIE_LOCATION_UNRESOLVED", "INFO", f"GPU {i} PCIe physical location is not proven",
                [{"provider":"Windows PnP location properties","device_key":key,"pcie":pcie}],
                "Do not infer slot, root-complex or NUMA locality from device_index. Preserve runtime selector and persistent identity separately.",
                confidence="HIGH", scope="GPU_PCIE"))
        if isinstance(numa,dict) and numa.get("status") != "PROVEN":
            findings.append(_finding(
                "GPU_NUMA_AFFINITY_UNKNOWN", "INFO", f"GPU {i} NUMA affinity is unknown",
                [{"provider":"Compute Fabric","device_key":key,"numa_affinity":numa}],
                "Do not create a GPU-to-NUMA edge until a provider proves locality.",
                confidence="PROVEN", scope="GPU_NUMA"))
    dup=[k for k,c in Counter(keys).items() if c>1]
    if dup:
        findings.append(_finding(
            "DUPLICATE_DEVICE_KEY", "HIGH", "Persistent GPU identity collision detected",
            [{"provider":"Forge device identity","duplicate_device_keys":dup}],
            "Block historical per-device decisions until identity generation is repaired; device_index must not be used as the persistent substitute.",
            confidence="PROVEN", scope="GPU_IDENTITY", blocking=True))
    return findings



def _pcie_link_findings(pcie: dict[str, Any]) -> list[dict[str, Any]]:
    findings=[]
    for dev in (pcie.get("devices",[]) if isinstance(pcie,dict) else []):
        cls=dev.get("classification",{}) if isinstance(dev,dict) else {}
        name=dev.get("name") or dev.get("pnp_device_id") or "GPU"
        if cls.get("width_state")=="REDUCED":
            cur=(dev.get("current") or {}).get("width"); mx=(dev.get("maximum") or {}).get("width")
            findings.append(_finding(
                "PCIE_NEGOTIATED_WIDTH_REDUCED","MEDIUM",f"{name} is negotiating fewer PCIe lanes than the exposed maximum",
                [{"provider":"PCIe Link Intelligence","current_width":cur,"max_width":mx,"bdf":dev.get("bdf"),"provenance":dev.get("provenance",[])}],
                "Verify slot electrical width, riser/adapter, motherboard lane sharing and BIOS configuration. Treat this as a measured link constraint, not proof of defective hardware.",
                confidence="HIGH",scope="GPU_PCIE"))
        if cls.get("speed_state")=="BELOW_MAX":
            cur=(dev.get("current") or {}).get("generation"); mx=(dev.get("maximum") or {}).get("generation")
            if cls.get("load_validated"):
                sev="MEDIUM"; kind="PCIE_NEGOTIATED_SPEED_REDUCED_UNDER_LOAD"; conf="HIGH"
                recommendation="Validate platform/slot capability and BIOS power/link settings; the lower generation persisted under a validated load."
            else:
                sev="INFO"; kind="PCIE_SPEED_DOWNSHIFT_NEEDS_LOAD_VALIDATION"; conf="HIGH"
                recommendation="Do not call this a bottleneck yet. Re-check negotiated generation during a controlled GPU/PCIe load because idle power management can downshift the link."
            findings.append(_finding(kind,sev,f"{name} current PCIe generation is below the exposed maximum",
                [{"provider":"PCIe Link Intelligence","current_generation":cur,"max_generation":mx,"load_validated":bool(cls.get("load_validated")),"bdf":dev.get("bdf")}],recommendation,confidence=conf,scope="GPU_PCIE"))
    return findings

def _evidence_findings(graph: dict[str, Any]) -> list[dict[str, Any]]:
    conflicts=graph.get("conflicts", []) if isinstance(graph,dict) else []
    if not conflicts: return []
    return [_finding(
        "EVIDENCE_CONFLICTS_PRESENT", "MEDIUM", "Hardware providers disagree on one or more fields",
        [{"provider":"Hardware Evidence Graph","conflict_count":len(conflicts),"conflicts":conflicts[:20]}],
        "Keep conflicting values visible and prefer only field-specific, high-confidence evidence. Do not silently merge providers.",
        confidence="PROVEN", scope="EVIDENCE") ]


def audit(inspector: dict[str, Any], graph: dict[str, Any] | None = None, pcie_link: dict[str, Any] | None = None) -> dict[str, Any]:
    from phoenix_forge.modules import evidence_graph, pcie_link_intelligence
    deep=inspector.get("deep_inventory", {}) if isinstance(inspector,dict) else {}
    graph=graph or evidence_graph.build(inspector)
    pcie_link=pcie_link or ((inspector.get("pcie_link") or {}).get("value") if isinstance(inspector.get("pcie_link"),dict) else None) or pcie_link_intelligence.collect(load_validated=False)
    findings=[]
    findings.extend(_memory_findings(deep))
    findings.extend(_cpu_numa_findings(deep))
    findings.extend(_gpu_findings(deep))
    findings.extend(_pcie_link_findings(pcie_link))
    findings.extend(_evidence_findings(graph))

    rank={"CRITICAL":4,"HIGH":3,"MEDIUM":2,"LOW":1,"INFO":0}
    findings.sort(key=lambda x:(-rank.get(x.get("severity","INFO"),0), x.get("kind","")))
    blocking=[f for f in findings if f.get("blocking")]
    attention=[f for f in findings if f.get("severity") in {"CRITICAL","HIGH","MEDIUM"}]
    missing=inspector.get("missing_providers", []) if isinstance(inspector,dict) else []
    status="BLOCKED" if blocking else ("ATTENTION" if attention else ("INCOMPLETE_EVIDENCE" if missing else "CLEAR"))
    return {
        "schema":SCHEMA,"generated_at":time.time(),"status":status,
        "summary":{"findings":len(findings),"blocking":len(blocking),"attention":len(attention),"missing_providers":len(missing or [])},
        "findings":findings,
        "bottleneck_contract":{
            "only_claim_measured_bottlenecks":True,
            "configuration_asymmetry_is_not_damage":True,
            "unknown_affinity_is_not_guessed":True,
            "device_index_is_not_persistent_identity":True,
            "evidence_conflicts_remain_visible":True,
        },
        "limitations":[
            "PCIe negotiated width/speed is not claimed until a provider exposes current link state.",
            "A current PCIe generation below maximum is not promoted to a bottleneck unless revalidated under controlled load.",
            "Memory channel/rank/interleave conclusions require SPD/SMBus or another proven topology provider.",
            "Thermal/power throttling requires controlled load plus appropriate telemetry; idle clocks are not sufficient.",
            "Storage bottlenecks require measured throughput/latency for the actual model/cache path.",
        ],
    }
