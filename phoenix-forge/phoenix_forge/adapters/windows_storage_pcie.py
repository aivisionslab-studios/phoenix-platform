from __future__ import annotations

import os
import re
from typing import Any

from phoenix_forge.util import powershell_json
from phoenix_forge.adapters import windows_pcie_link

SCHEMA = "phoenix.forge.windows-storage-pcie/v1"


def _as_int(v: Any) -> int | None:
    if v is None or isinstance(v, bool):
        return None
    try:
        return int(v)
    except Exception:
        try:
            return int(float(str(v).strip()))
        except Exception:
            return None


def _norm_serial(v: Any) -> str:
    return re.sub(r"\s+", "", str(v or "")).upper()


def _parse_location_path(path: str | None) -> dict[str, Any]:
    text = str(path or "")
    root = None
    m = re.search(r"PCIROOT\(([0-9A-Fa-f]+)\)", text)
    if m:
        try:
            root = int(m.group(1), 16)
        except Exception:
            root = None
    segments: list[dict[str, int]] = []
    for token in re.findall(r"PCI\(([0-9A-Fa-f]{4})\)", text):
        value = int(token, 16)
        segments.append({"device": (value >> 8) & 0xFF, "function": value & 0xFF})
    return {"pci_root": root, "segments": segments, "leaf": segments[-1] if segments else None}


def _windows_rows() -> list[dict[str, Any]]:
    if os.name != "nt":
        return []
    script = r'''
$ErrorActionPreference='SilentlyContinue'
$rows=@()
Get-CimInstance Win32_DiskDrive | ForEach-Object {
  $d=$_
  $current=$d.PNPDeviceID
  $chain=@()
  $pci=$null
  for($i=0; $i -lt 16 -and $current; $i++) {
    $dev=Get-PnpDevice -InstanceId $current -ErrorAction SilentlyContinue
    function V([string]$id,[string]$key) {
      $p=Get-PnpDeviceProperty -InstanceId $id -KeyName $key -ErrorAction SilentlyContinue
      if($p){ return $p.Data }; return $null
    }
    $parent=V $current 'DEVPKEY_Device_Parent'
    $chain += [pscustomobject]@{InstanceId=$current; Parent=$parent; Class=if($dev){$dev.Class}else{$null}; FriendlyName=if($dev){$dev.FriendlyName}else{$null}}
    if($current -like 'PCI\VEN_*') {
      $all=Get-PnpDeviceProperty -InstanceId $current -ErrorAction SilentlyContinue |
        Where-Object { $_.KeyName -match 'PciDevice|LinkSpeed|LinkWidth' } |
        Select-Object KeyName,Data
      $pci=[pscustomobject]@{
        InstanceId=$current
        FriendlyName=if($dev){$dev.FriendlyName}else{$null}
        LocationPaths=(V $current 'DEVPKEY_Device_LocationPaths')
        LocationInfo=(V $current 'DEVPKEY_Device_LocationInfo')
        BusNumber=(V $current 'DEVPKEY_Device_BusNumber')
        Address=(V $current 'DEVPKEY_Device_Address')
        CurrentLinkSpeed=(V $current 'DEVPKEY_PciDevice_CurrentLinkSpeed')
        CurrentLinkWidth=(V $current 'DEVPKEY_PciDevice_CurrentLinkWidth')
        MaxLinkSpeed=(V $current 'DEVPKEY_PciDevice_MaxLinkSpeed')
        MaxLinkWidth=(V $current 'DEVPKEY_PciDevice_MaxLinkWidth')
        ExpressSpecVersion=(V $current 'DEVPKEY_PciDevice_ExpressSpecVersion')
        AllProperties=@($all)
      }
      break
    }
    if(-not $parent -or $parent -eq $current){ break }
    $current=$parent
  }
  $rows += [pscustomobject]@{
    DiskNumber=$d.Index
    DeviceID=$d.DeviceID
    Model=$d.Model
    SerialNumber=$d.SerialNumber
    Size=$d.Size
    InterfaceType=$d.InterfaceType
    PNPDeviceID=$d.PNPDeviceID
    ParentChain=@($chain)
    PciAncestor=$pci
  }
}
$rows | ConvertTo-Json -Compress -Depth 10
'''
    data = powershell_json(script)
    if not data:
        return []
    return data if isinstance(data, list) else [data]


def _normalize_row(row: dict[str, Any]) -> dict[str, Any]:
    pci = row.get("PciAncestor") if isinstance(row.get("PciAncestor"), dict) else None
    out = {
        "disk_number": _as_int(row.get("DiskNumber")),
        "device_id": row.get("DeviceID"),
        "model": row.get("Model"),
        "serial": row.get("SerialNumber"),
        "size_bytes": _as_int(row.get("Size")),
        "interface_type": row.get("InterfaceType"),
        "disk_pnp_device_id": row.get("PNPDeviceID"),
        "parent_chain": row.get("ParentChain") if isinstance(row.get("ParentChain"), list) else [],
        "pci": None,
    }
    if not pci:
        return out
    paths = pci.get("LocationPaths")
    if isinstance(paths, str):
        paths = [paths]
    elif not isinstance(paths, list):
        paths = []
    primary = paths[0] if paths else None
    parsed = _parse_location_path(primary)
    bus = _as_int(pci.get("BusNumber"))
    leaf = parsed.get("leaf") or {}
    dev = leaf.get("device")
    fn = leaf.get("function")
    bdf = f"{bus:02x}:{dev:02x}.{fn:x}" if bus is not None and dev is not None and fn is not None else None
    current_speed = windows_pcie_link.normalize_speed(pci.get("CurrentLinkSpeed"))
    max_speed = windows_pcie_link.normalize_speed(pci.get("MaxLinkSpeed"))
    out["pci"] = {
        "controller_instance_id": pci.get("InstanceId"),
        "controller_name": pci.get("FriendlyName"),
        "location_paths": paths,
        "location_info": pci.get("LocationInfo"),
        "bus_number": bus,
        "pci_root": parsed.get("pci_root"),
        "device_number": dev,
        "function_number": fn,
        "bdf": bdf,
        "current_generation": current_speed.get("generation"),
        "current_gt_s": current_speed.get("gt_s"),
        "current_width": windows_pcie_link.normalize_width(pci.get("CurrentLinkWidth")),
        "max_generation": max_speed.get("generation"),
        "max_gt_s": max_speed.get("gt_s"),
        "max_width": windows_pcie_link.normalize_width(pci.get("MaxLinkWidth")),
        "express_spec_version": pci.get("ExpressSpecVersion"),
        "provenance": [
            "Win32_DiskDrive.PNPDeviceID",
            "DEVPKEY_Device_Parent chain",
            *(["DEVPKEY_Device_LocationPaths"] if primary else []),
            *(["DEVPKEY_Device_BusNumber"] if bus is not None else []),
        ],
    }
    return out


def collect() -> dict[str, Any]:
    rows = [_normalize_row(x) for x in _windows_rows()]
    mapped = sum(1 for x in rows if isinstance(x.get("pci"), dict) and x["pci"].get("controller_instance_id"))
    bdf = sum(1 for x in rows if isinstance(x.get("pci"), dict) and x["pci"].get("bdf"))
    return {
        "schema": SCHEMA,
        "status": "READY" if rows else ("UNAVAILABLE" if os.name != "nt" else "PARTIAL"),
        "devices": rows,
        "summary": {"disk_devices": len(rows), "pci_ancestor_mapped": mapped, "bdf_mapped": bdf},
        "policy": {
            "read_only": True,
            "parent_chain_required": True,
            "model_only_matching_prohibited": True,
            "serial_conflicts_are_not_merged": True,
            "unknown_is_not_guessed": True,
        },
        "limitations": [
            "The mapping follows the Windows PnP parent chain from the physical disk devnode to the first PCI ancestor.",
            "BDF is emitted only when the PCI ancestor exposes bus number plus a parseable PCI location path.",
            "No model-name-only mapping is accepted.",
        ],
    }


def match_physical_disk(win: dict[str, Any], inventory: dict[str, Any]) -> tuple[dict[str, Any] | None, str]:
    rows = [x for x in (inventory.get("devices") or []) if isinstance(x, dict)]
    disk_no = _as_int(win.get("DiskNumber"))
    serial = _norm_serial(win.get("SerialNumber"))
    if disk_no is not None:
        matches = [x for x in rows if _as_int(x.get("disk_number")) == disk_no]
        if len(matches) == 1:
            row = matches[0]
            other = _norm_serial(row.get("serial"))
            if serial and other and serial != other:
                return None, "DISK_NUMBER_SERIAL_CONFLICT"
            return row, "DISK_NUMBER_SERIAL_EXACT" if serial and other else "PHYSICALDRIVE_INDEX_EXACT"
    if serial:
        matches = [x for x in rows if _norm_serial(x.get("serial")) == serial]
        if len(matches) == 1:
            return matches[0], "SERIAL_EXACT"
    return None, "UNMATCHED"
