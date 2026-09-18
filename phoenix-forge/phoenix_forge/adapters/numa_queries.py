from __future__ import annotations

import os
from typing import Any

from phoenix_forge.util import powershell_json
from phoenix_forge.adapters import windows_topology

SCHEMA = "phoenix.forge.numa-query/v2"


def _as_list(value: Any) -> list[dict[str, Any]]:
    if not value:
        return []
    if isinstance(value, list):
        return [x for x in value if isinstance(x, dict)]
    return [value] if isinstance(value, dict) else []


def windows_cpu_sockets() -> list[dict[str, Any]]:
    if os.name != "nt":
        return []
    data = powershell_json(
        "Get-CimInstance Win32_Processor | "
        "Select-Object DeviceID,SocketDesignation,Name,NumberOfCores,NumberOfLogicalProcessors,ProcessorId | "
        "ConvertTo-Json -Compress"
    )
    rows = _as_list(data)
    out: list[dict[str, Any]] = []
    for index, row in enumerate(rows):
        out.append({
            "socket_index": index,
            "device_id": row.get("DeviceID"),
            "socket_designation": row.get("SocketDesignation"),
            "name": row.get("Name"),
            "cores": row.get("NumberOfCores"),
            "logical_processors": row.get("NumberOfLogicalProcessors"),
            "processor_id": row.get("ProcessorId"),
            "source": "Win32_Processor",
            "confidence": 0.95,
        })
    return out


def windows_numa_memory() -> list[dict[str, Any]]:
    if os.name != "nt":
        return []
    data = powershell_json(
        "Get-CimInstance Win32_PerfRawData_Counters_NUMANodeMemory -ErrorAction SilentlyContinue | "
        "Select-Object Name,AvailableMBytes | ConvertTo-Json -Compress"
    )
    rows = _as_list(data)
    out: list[dict[str, Any]] = []
    for row in rows:
        name = str(row.get("Name") or "").strip()
        if not name or name.lower() == "_total":
            continue
        try:
            node_id = int(name)
        except ValueError:
            node_id = None
        available_mb = row.get("AvailableMBytes")
        out.append({
            "node_id": node_id,
            "name": name,
            "available_memory_bytes": int(available_mb) * 1024 * 1024 if available_mb is not None else None,
            "source": "NUMA Node Memory performance counters",
            "confidence": 0.75,
        })
    return out


def _merge_numa(native_nodes: list[dict[str, Any]], memory_nodes: list[dict[str, Any]]) -> list[dict[str, Any]]:
    merged: dict[Any, dict[str, Any]] = {}
    for row in native_nodes:
        merged[row.get("node_id")] = dict(row)
    for row in memory_nodes:
        key = row.get("node_id")
        dst = merged.setdefault(key, {"node_id": key})
        if row.get("available_memory_bytes") is not None:
            dst["available_memory_bytes"] = row["available_memory_bytes"]
        dst.setdefault("memory_source", row.get("source"))
    return [merged[k] for k in sorted(merged, key=lambda x: (x is None, x if isinstance(x, int) else 0))]


def collect() -> dict[str, Any]:
    sockets = windows_cpu_sockets()
    mem_nodes = windows_numa_memory()
    native = windows_topology._native_logical_topology()
    native_nodes = native.get("numa_nodes", []) if native.get("available") else []
    groups = native.get("processor_groups", []) if native.get("available") else []
    numa = _merge_numa(native_nodes, mem_nodes)

    limitations = [
        "GPU-to-NUMA affinity is UNKNOWN unless independently proven.",
        "PCIe root proximity alone is not proof of NUMA locality.",
    ]
    if os.name == "nt" and not native.get("available"):
        limitations.append("Native GetLogicalProcessorInformationEx topology was unavailable; processor-group membership is unknown.")

    return {
        "schema": SCHEMA,
        "platform": "windows" if os.name == "nt" else os.name,
        "cpu_sockets": sockets,
        "numa_nodes": numa,
        "processor_groups": groups,
        "processor_packages": native.get("packages", []) if native.get("available") else [],
        "native_topology_available": bool(native.get("available")),
        "native_topology_reason": native.get("reason"),
        "limitations": limitations,
    }
