from __future__ import annotations

import hashlib
from typing import Any

from phoenix_forge.adapters import numa_queries, windows_topology
from phoenix_forge.models import DetectReport, GPUInfo

SCHEMA = "phoenix.forge.compute-fabric/v2"


def stable_device_key(gpu: GPUInfo) -> str:
    """Persistent identity key; never derived from device_index alone."""
    parts = [
        (gpu.vendor_id or "").upper(),
        (gpu.device_id or "").upper(),
        (gpu.subsystem_vendor_id or "").upper(),
        (gpu.subsystem_device_id or "").upper(),
        (gpu.revision_id or "").upper(),
        (gpu.pnp_device_id or "").upper(),
    ]
    evidence = "|".join(parts).strip("|")
    if not evidence:
        evidence = (gpu.name or "UNKNOWN_GPU").upper()
    digest = hashlib.sha256(evidence.encode("utf-8", errors="replace")).hexdigest()[:16]
    vendor = (gpu.vendor_id or "unknown").lower()
    device = (gpu.device_id or "unknown").lower()
    return f"pci-{vendor}-{device}-{digest}"


def _gpu_node(gpu: GPUInfo, detected_position: int, hw: dict[str, Any]) -> dict[str, Any]:
    key = gpu.device_key or stable_device_key(gpu)
    runtime_index = gpu.device_index if gpu.device_index is not None else detected_position
    pcie = windows_topology.match_gpu(gpu.pnp_device_id, hw)
    pcie_view = {
        "status": "PROVEN" if pcie else "UNKNOWN",
        "bdf": pcie.get("bdf") if pcie else None,
        "bus_number": pcie.get("bus_number") if pcie else None,
        "device_number": pcie.get("device_number") if pcie else None,
        "function_number": pcie.get("function_number") if pcie else None,
        "pci_root": pcie.get("pci_root") if pcie else None,
        "location_paths": pcie.get("location_paths", []) if pcie else [],
        "parent": pcie.get("parent") if pcie else None,
        "container_id": pcie.get("container_id") if pcie else None,
        "confidence": pcie.get("confidence", 0.0) if pcie else 0.0,
        "provenance": pcie.get("provenance", []) if pcie else [],
    }
    direct_numa = (pcie or {}).get("numa_affinity") if pcie else None
    if isinstance(direct_numa, dict) and direct_numa.get("status") == "PROVEN":
        numa_view = {
            "node_id": direct_numa.get("node_id"),
            "status": "PROVEN",
            "confidence": float(direct_numa.get("confidence") or 1.0),
            "provenance": list(direct_numa.get("provenance") or []),
            "proximity_domain": direct_numa.get("proximity_domain"),
            "reason": direct_numa.get("reason"),
        }
    else:
        numa_view = {
            "node_id": gpu.numa_node,
            "status": gpu.affinity_status or "UNKNOWN",
            "confidence": gpu.affinity_confidence or 0.0,
            "provenance": list(gpu.affinity_provenance or []),
            "proximity_domain": (direct_numa or {}).get("proximity_domain") if isinstance(direct_numa, dict) else None,
            "reason": (direct_numa or {}).get("reason") if isinstance(direct_numa, dict) else "NO_DIRECT_NUMA_EVIDENCE",
        }
    return {
        "node_type": "gpu",
        "device_key": key,
        "device_index": runtime_index,
        "name": gpu.name,
        "vendor": gpu.vendor,
        "pci_identity": {
            "vendor_id": gpu.vendor_id,
            "device_id": gpu.device_id,
            "subsystem_vendor_id": gpu.subsystem_vendor_id,
            "subsystem_device_id": gpu.subsystem_device_id,
            "revision_id": gpu.revision_id,
            "pnp_device_id": gpu.pnp_device_id,
        },
        "pcie": pcie_view,
        "runtime_selector": {"kind": "device_index", "value": runtime_index},
        "numa_affinity": numa_view,
    }


def build(report: DetectReport) -> dict[str, Any]:
    topo = numa_queries.collect()
    hw = windows_topology.collect()
    sockets = topo.get("cpu_sockets", [])
    numa_nodes = topo.get("numa_nodes", [])
    groups = topo.get("processor_groups", [])
    packages = topo.get("processor_packages", [])
    gpus = [_gpu_node(gpu, idx, hw) for idx, gpu in enumerate(report.gpus)]

    edges: list[dict[str, Any]] = []
    for gpu in gpus:
        affinity = gpu["numa_affinity"]
        if affinity.get("status") == "PROVEN" and affinity.get("node_id") is not None and affinity.get("provenance"):
            edges.append({
                "from": gpu["device_key"],
                "to": f"numa-{affinity['node_id']}",
                "relation": "NUMA_AFFINITY",
                "confidence": affinity.get("confidence", 0.0),
                "provenance": affinity.get("provenance", []),
            })
        pcie = gpu["pcie"]
        if pcie.get("status") == "PROVEN" and pcie.get("pci_root") is not None:
            edges.append({
                "from": gpu["device_key"],
                "to": f"pci-root-{pcie['pci_root']}",
                "relation": "PCI_ROOT_PATH",
                "confidence": pcie.get("confidence", 0.0),
                "provenance": pcie.get("provenance", []),
            })

    return {
        "schema": SCHEMA,
        "host": {
            "hostname": report.hostname,
            "architecture": report.architecture,
            "logical_cpus": report.logical_cpus,
            "physical_cpus": report.physical_cpus,
            "ram_total_bytes": report.ram_total_bytes,
        },
        "cpu_sockets": sockets,
        "processor_packages": packages,
        "processor_groups": groups,
        "numa_nodes": numa_nodes,
        "gpus": gpus,
        "pcie_inventory": hw.get("pcie_display_devices", []),
        "edges": edges,
        "invariants": {
            "device_index": "TRANSIENT_RUNTIME_SELECTOR",
            "device_key": "PERSISTENT_IDENTITY",
            "unproven_affinity": "UNKNOWN",
            "pcie_root_is_numa_affinity": False,
            "capacity_failure_is_hardware_fault": False,
        },
        "confidence": {
            "socket_inventory": "HIGH" if sockets else "UNKNOWN",
            "processor_groups": "HIGH" if groups else "UNKNOWN",
            "numa_inventory": "HIGH" if topo.get("native_topology_available") and numa_nodes else ("MEDIUM" if numa_nodes else "UNKNOWN"),
            "gpu_pcie_location": "EVIDENCE_ONLY",
            "gpu_numa_affinity": "EVIDENCE_ONLY",
        },
        "limitations": list(dict.fromkeys(topo.get("limitations", []) + hw.get("limitations", []))),
    }


def placement_candidates(report: DetectReport, *, workload: str = "llm") -> dict[str, Any]:
    fabric = build(report)
    candidates = []
    for gpu in fabric["gpus"]:
        candidates.append({
            "device_key": gpu["device_key"],
            "device_index": gpu["device_index"],
            "workload": workload,
            "pcie_bdf": gpu["pcie"].get("bdf"),
            "numa_node": gpu["numa_affinity"].get("node_id"),
            "affinity_status": gpu["numa_affinity"].get("status", "UNKNOWN"),
            "affinity_confidence": gpu["numa_affinity"].get("confidence", 0.0),
            "eligible": True,
            "reason": "Topology candidate only; health/workload policy must be applied separately.",
        })
    return {
        "schema": "phoenix.forge.compute-fabric-placement/v2",
        "workload": workload,
        "mode": "TOPOLOGY_ONLY",
        "candidates": candidates,
        "policy_note": "Compute Fabric does not override GPU Safety or workload qualification.",
    }
