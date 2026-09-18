from __future__ import annotations

import ctypes
import os
import re
from ctypes import wintypes
from typing import Any

from phoenix_forge.util import powershell_json

SCHEMA = "phoenix.forge.windows-topology/v2"

RELATION_NUMA_NODE = 1
RELATION_PROCESSOR_PACKAGE = 3
RELATION_GROUP = 4
ERROR_INSUFFICIENT_BUFFER = 122


def _bit_count(mask: int) -> int:
    try:
        return int(mask).bit_count()
    except Exception:
        return bin(int(mask) & ((1 << 64) - 1)).count("1")


def _native_logical_topology() -> dict[str, Any]:
    """Read Windows logical processor topology with GetLogicalProcessorInformationEx.

    We expose only relationships that can be decoded deterministically. Unsupported
    layouts remain absent rather than being guessed.
    """
    if os.name != "nt":
        return {"available": False, "reason": "NOT_WINDOWS", "processor_groups": [], "numa_nodes": [], "packages": []}

    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    fn = kernel32.GetLogicalProcessorInformationEx
    fn.argtypes = [wintypes.DWORD, ctypes.c_void_p, ctypes.POINTER(wintypes.DWORD)]
    fn.restype = wintypes.BOOL

    length = wintypes.DWORD(0)
    fn(0xFFFF, None, ctypes.byref(length))  # RelationAll
    err = ctypes.get_last_error()
    if not length.value or err not in (0, ERROR_INSUFFICIENT_BUFFER):
        return {"available": False, "reason": f"SIZE_QUERY_FAILED:{err}", "processor_groups": [], "numa_nodes": [], "packages": []}

    buf = ctypes.create_string_buffer(length.value)
    if not fn(0xFFFF, ctypes.byref(buf), ctypes.byref(length)):
        err = ctypes.get_last_error()
        return {"available": False, "reason": f"QUERY_FAILED:{err}", "processor_groups": [], "numa_nodes": [], "packages": []}

    ptr_size = ctypes.sizeof(ctypes.c_void_p)
    affinity_size = ptr_size + 2 + 6  # KAFFINITY + WORD Group + WORD Reserved[3]
    groups: list[dict[str, Any]] = []
    numa: list[dict[str, Any]] = []
    packages: list[dict[str, Any]] = []

    raw = memoryview(buf.raw[: length.value])
    offset = 0
    while offset + 8 <= len(raw):
        relationship = int.from_bytes(raw[offset:offset + 4], "little")
        size = int.from_bytes(raw[offset + 4:offset + 8], "little")
        if size < 8 or offset + size > len(raw):
            break
        body = offset + 8

        if relationship == RELATION_NUMA_NODE and size >= 8 + 24 + affinity_size:
            node = int.from_bytes(raw[body:body + 4], "little")
            ga = body + 24
            mask = int.from_bytes(raw[ga:ga + ptr_size], "little")
            group = int.from_bytes(raw[ga + ptr_size:ga + ptr_size + 2], "little")
            numa.append({
                "node_id": node,
                "group_id": group,
                "processor_mask": f"0x{mask:0{ptr_size * 2}X}",
                "logical_processors": _bit_count(mask),
                "source": "GetLogicalProcessorInformationEx(RelationNumaNode)",
                "confidence": 1.0,
            })

        elif relationship == RELATION_GROUP and size >= 8 + 24:
            maximum_group_count = int.from_bytes(raw[body:body + 2], "little")
            active_group_count = int.from_bytes(raw[body + 2:body + 4], "little")
            gi = body + 24
            group_info_size = 40 + ptr_size
            for group_id in range(active_group_count):
                pos = gi + group_id * group_info_size
                if pos + group_info_size > offset + size:
                    break
                max_count = raw[pos]
                active_count = raw[pos + 1]
                mask = int.from_bytes(raw[pos + 40:pos + 40 + ptr_size], "little")
                groups.append({
                    "group_id": group_id,
                    "maximum_processors": int(max_count),
                    "active_processors": int(active_count),
                    "active_processor_mask": f"0x{mask:0{ptr_size * 2}X}",
                    "source": "GetLogicalProcessorInformationEx(RelationGroup)",
                    "confidence": 1.0,
                    "maximum_group_count": maximum_group_count,
                })

        elif relationship == RELATION_PROCESSOR_PACKAGE:
            packages.append({
                "package_index": len(packages),
                "source": "GetLogicalProcessorInformationEx(RelationProcessorPackage)",
                "confidence": 1.0,
            })

        offset += size

    return {
        "available": True,
        "processor_groups": groups,
        "numa_nodes": numa,
        "packages": packages,
        "source": "kernel32.GetLogicalProcessorInformationEx",
    }



def _numa_node_from_proximity_domain(proximity_domain: int | None) -> dict[str, Any]:
    """Resolve an ACPI/firmware NUMA proximity domain to the Windows NUMA node.

    This is direct locality evidence when the device devnode exposes
    DEVPKEY_Numa_Proximity_Domain. PCI root identity is deliberately not used.
    """
    if proximity_domain is None:
        return {"status": "UNKNOWN", "node_id": None, "confidence": 0.0, "provenance": [], "reason": "PROXIMITY_DOMAIN_NOT_EXPOSED"}
    if os.name != "nt":
        return {"status": "UNKNOWN", "node_id": None, "confidence": 0.0, "provenance": ["DEVPKEY_Numa_Proximity_Domain"], "reason": "NOT_WINDOWS"}
    try:
        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        fn = getattr(kernel32, "GetNumaProximityNodeEx", None)
        if fn is None:
            return {"status": "UNKNOWN", "node_id": None, "confidence": 0.0, "provenance": ["DEVPKEY_Numa_Proximity_Domain"], "reason": "GET_NUMA_PROXIMITY_NODE_EX_UNAVAILABLE"}
        fn.argtypes = [wintypes.ULONG, ctypes.POINTER(wintypes.USHORT)]
        fn.restype = wintypes.BOOL
        node = wintypes.USHORT(0xFFFF)
        ok = bool(fn(wintypes.ULONG(int(proximity_domain)), ctypes.byref(node)))
        if not ok or int(node.value) == 0xFFFF:
            err = ctypes.get_last_error()
            return {
                "status": "UNKNOWN", "node_id": None, "confidence": 0.0,
                "provenance": ["DEVPKEY_Numa_Proximity_Domain", "GetNumaProximityNodeEx"],
                "reason": f"PROXIMITY_DOMAIN_NOT_RESOLVED:{err}",
                "proximity_domain": int(proximity_domain),
            }
        return {
            "status": "PROVEN", "node_id": int(node.value), "confidence": 1.0,
            "provenance": ["DEVPKEY_Numa_Proximity_Domain", "GetNumaProximityNodeEx"],
            "reason": None, "proximity_domain": int(proximity_domain),
        }
    except Exception as exc:
        return {
            "status": "UNKNOWN", "node_id": None, "confidence": 0.0,
            "provenance": ["DEVPKEY_Numa_Proximity_Domain"],
            "reason": f"PROXIMITY_RESOLUTION_ERROR:{type(exc).__name__}",
            "proximity_domain": int(proximity_domain),
        }


def _parse_location_path(path: str | None) -> dict[str, Any]:
    """Parse only the mechanically encoded PCI(device,function) segments.

    Windows location paths such as PCIROOT(0)#PCI(0100)#PCI(0000) encode
    device/function in each PCI(dddd) token. We do not infer bus numbers from
    the path; bus is reported only when Windows exposes DEVPKEY_Device_BusNumber.
    """
    text = str(path or "")
    root = None
    m = re.search(r"PCIROOT\(([0-9A-Fa-f]+)\)", text)
    if m:
        try:
            root = int(m.group(1), 16)
        except ValueError:
            root = None
    segments: list[dict[str, int]] = []
    for token in re.findall(r"PCI\(([0-9A-Fa-f]{4})\)", text):
        value = int(token, 16)
        segments.append({"device": (value >> 8) & 0xFF, "function": value & 0xFF})
    leaf = segments[-1] if segments else None
    return {"pci_root": root, "segments": segments, "leaf": leaf}


def _windows_pcie_display_devices() -> list[dict[str, Any]]:
    if os.name != "nt":
        return []
    # Property access is intentionally best-effort. Missing keys remain null.
    script = r"""
$ErrorActionPreference='SilentlyContinue'
$rows=@()
Get-PnpDevice -Class Display -PresentOnly | ForEach-Object {
  $id=$_.InstanceId
  function V($key){
    $p=Get-PnpDeviceProperty -InstanceId $id -KeyName $key -ErrorAction SilentlyContinue
    if($p){ return $p.Data }; return $null
  }
  $rows += [pscustomobject]@{
    FriendlyName=$_.FriendlyName
    InstanceId=$id
    Status=$_.Status
    Class=$_.Class
    LocationPaths=(V 'DEVPKEY_Device_LocationPaths')
    LocationInfo=(V 'DEVPKEY_Device_LocationInfo')
    BusNumber=(V 'DEVPKEY_Device_BusNumber')
    Address=(V 'DEVPKEY_Device_Address')
    Parent=(V 'DEVPKEY_Device_Parent')
    ContainerId=(V 'DEVPKEY_Device_ContainerId')
    NumaProximityDomain=(V 'DEVPKEY_Numa_Proximity_Domain')
  }
}
$rows | ConvertTo-Json -Compress -Depth 5
"""
    data = powershell_json(script)
    if not data:
        return []
    rows = data if isinstance(data, list) else [data]
    out: list[dict[str, Any]] = []
    for row in rows:
        paths = row.get("LocationPaths")
        if isinstance(paths, str):
            paths = [paths]
        elif not isinstance(paths, list):
            paths = []
        primary = paths[0] if paths else None
        parsed = _parse_location_path(primary)
        bus = row.get("BusNumber")
        address = row.get("Address")
        try:
            bus = int(bus) if bus is not None else None
        except Exception:
            bus = None
        try:
            address = int(address) if address is not None else None
        except Exception:
            address = None
        proximity_domain = row.get("NumaProximityDomain")
        try:
            proximity_domain = int(proximity_domain) if proximity_domain is not None else None
        except Exception:
            proximity_domain = None
        numa_affinity = _numa_node_from_proximity_domain(proximity_domain)
        leaf = parsed.get("leaf") or {}
        device = leaf.get("device")
        function = leaf.get("function")
        bdf = None
        if bus is not None and device is not None and function is not None:
            bdf = f"{bus:02x}:{device:02x}.{function:x}"
        evidence = []
        if primary:
            evidence.append("DEVPKEY_Device_LocationPaths")
        if bus is not None:
            evidence.append("DEVPKEY_Device_BusNumber")
        if address is not None:
            evidence.append("DEVPKEY_Device_Address")
        if proximity_domain is not None:
            evidence.append("DEVPKEY_Numa_Proximity_Domain")
        out.append({
            "name": row.get("FriendlyName"),
            "pnp_device_id": row.get("InstanceId"),
            "status": row.get("Status"),
            "location_paths": paths,
            "location_info": row.get("LocationInfo"),
            "bus_number": bus,
            "address": address,
            "parent": row.get("Parent"),
            "container_id": str(row.get("ContainerId")) if row.get("ContainerId") is not None else None,
            "pci_root": parsed.get("pci_root"),
            "pci_segments": parsed.get("segments", []),
            "device_number": device,
            "function_number": function,
            "bdf": bdf,
            "numa_proximity_domain": proximity_domain,
            "numa_affinity": numa_affinity,
            "provenance": evidence,
            "confidence": 0.95 if bdf else (0.8 if primary else 0.5),
        })
    return out


def collect() -> dict[str, Any]:
    native = _native_logical_topology()
    display = _windows_pcie_display_devices()
    return {
        "schema": SCHEMA,
        "platform": "windows" if os.name == "nt" else os.name,
        "native_logical_topology": native,
        "pcie_display_devices": display,
        "limitations": [
            "PCIe BDF is emitted only when Windows exposes bus plus a parseable PCI location path.",
            "GPU-to-NUMA affinity is PROVEN only when the GPU devnode exposes DEVPKEY_Numa_Proximity_Domain and Windows resolves it with GetNumaProximityNodeEx; otherwise it remains UNKNOWN.",
            "PCIe root identity is not treated as NUMA affinity.",
        ],
    }


def match_gpu(pnp_device_id: str | None, inventory: dict[str, Any]) -> dict[str, Any] | None:
    needle = str(pnp_device_id or "").upper()
    if not needle:
        return None
    for row in inventory.get("pcie_display_devices", []):
        candidate = str(row.get("pnp_device_id") or "").upper()
        if candidate and (candidate == needle or candidate in needle or needle in candidate):
            return row
    return None
