from __future__ import annotations

import os
import re
from typing import Any

from phoenix_forge.util import powershell_json

SCHEMA = "phoenix.forge.windows-pcie-link/v1"

_SPEED_MAP = {
    1: (1, 2.5),
    2: (2, 5.0),
    3: (3, 8.0),
    4: (4, 16.0),
    5: (5, 32.0),
    6: (6, 64.0),
    7: (7, 128.0),
}


def normalize_width(value: Any) -> int | None:
    if value is None:
        return None
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        n = int(value)
        return n if 0 < n <= 64 else None
    text = str(value).strip().lower()
    m = re.search(r"(?:^|\b)x\s*(\d{1,2})(?:\b|$)", text)
    if not m:
        m = re.search(r"\b(1|2|4|8|12|16|24|32|48|64)\b", text)
    if not m:
        return None
    n = int(m.group(1))
    return n if 0 < n <= 64 else None


def normalize_speed(value: Any) -> dict[str, Any]:
    out = {"raw": value, "generation": None, "gt_s": None, "status": "UNKNOWN"}
    if value is None or isinstance(value, bool):
        return out
    if isinstance(value, int) and value in _SPEED_MAP:
        gen, gt = _SPEED_MAP[value]
        return {"raw": value, "generation": gen, "gt_s": gt, "status": "PROVEN_ENUM"}
    if isinstance(value, (int, float)):
        f = float(value)
        for gen, gt in _SPEED_MAP.values():
            if abs(f - gt) < 0.05:
                return {"raw": value, "generation": gen, "gt_s": gt, "status": "PROVEN_RATE"}
        return out
    text = str(value).strip().lower()
    mg = re.search(r"(?:gen(?:eration)?\s*)([1-7])", text)
    if mg:
        gen = int(mg.group(1)); gt = _SPEED_MAP.get(gen, (gen, None))[1]
        return {"raw": value, "generation": gen, "gt_s": gt, "status": "PROVEN_TEXT"}
    mr = re.search(r"([0-9]+(?:\.[0-9]+)?)\s*(?:gt/s|gts)", text)
    if mr:
        f = float(mr.group(1))
        for gen, gt in _SPEED_MAP.values():
            if abs(f - gt) < 0.05:
                return {"raw": value, "generation": gen, "gt_s": gt, "status": "PROVEN_TEXT"}
        return {"raw": value, "generation": None, "gt_s": f, "status": "RATE_ONLY"}
    return out


def _rebar_evidence(properties: list[dict[str, Any]]) -> dict[str, Any]:
    hits=[]
    enabled=None
    for p in properties or []:
        key=str(p.get("KeyName") or p.get("key") or "")
        if not re.search(r"resizable|rebar|bar", key, re.I):
            continue
        data=p.get("Data") if "Data" in p else p.get("data")
        hits.append({"key":key,"data":data})
        if isinstance(data,bool) and re.search(r"resizable|rebar",key,re.I):
            enabled=data
    return {
        "status": "PROVEN_ENABLED" if enabled is True else ("PROVEN_DISABLED" if enabled is False else ("EVIDENCE_PRESENT" if hits else "UNKNOWN")),
        "enabled": enabled,
        "properties": hits,
        "confidence": 0.95 if enabled is not None else (0.7 if hits else 0.0),
        "provenance": [x["key"] for x in hits],
    }


def _windows_rows() -> list[dict[str, Any]]:
    if os.name != "nt":
        return []
    script = r'''
$ErrorActionPreference='SilentlyContinue'
$rows=@()
Get-PnpDevice -Class Display -PresentOnly | ForEach-Object {
  $id=$_.InstanceId
  function V($key){
    $p=Get-PnpDeviceProperty -InstanceId $id -KeyName $key -ErrorAction SilentlyContinue
    if($p){ return $p.Data }; return $null
  }
  $all=Get-PnpDeviceProperty -InstanceId $id -ErrorAction SilentlyContinue |
    Where-Object { $_.KeyName -match 'PciDevice|Resizable|ReBAR|BAR|LinkSpeed|LinkWidth' } |
    Select-Object KeyName,Data
  $rows += [pscustomobject]@{
    FriendlyName=$_.FriendlyName
    InstanceId=$id
    CurrentLinkSpeed=(V 'DEVPKEY_PciDevice_CurrentLinkSpeed')
    CurrentLinkWidth=(V 'DEVPKEY_PciDevice_CurrentLinkWidth')
    MaxLinkSpeed=(V 'DEVPKEY_PciDevice_MaxLinkSpeed')
    MaxLinkWidth=(V 'DEVPKEY_PciDevice_MaxLinkWidth')
    ExpressSpecVersion=(V 'DEVPKEY_PciDevice_ExpressSpecVersion')
    AllProperties=@($all)
  }
}
$rows | ConvertTo-Json -Compress -Depth 8
'''
    data = powershell_json(script)
    if not data:
        return []
    return data if isinstance(data, list) else [data]


def collect() -> dict[str, Any]:
    rows=[]
    for row in _windows_rows():
        props=row.get("AllProperties") or []
        if isinstance(props,dict): props=[props]
        current_speed=normalize_speed(row.get("CurrentLinkSpeed"))
        max_speed=normalize_speed(row.get("MaxLinkSpeed"))
        current_width=normalize_width(row.get("CurrentLinkWidth"))
        max_width=normalize_width(row.get("MaxLinkWidth"))
        provenance=[]
        for key,val in [
            ("DEVPKEY_PciDevice_CurrentLinkSpeed",row.get("CurrentLinkSpeed")),
            ("DEVPKEY_PciDevice_CurrentLinkWidth",row.get("CurrentLinkWidth")),
            ("DEVPKEY_PciDevice_MaxLinkSpeed",row.get("MaxLinkSpeed")),
            ("DEVPKEY_PciDevice_MaxLinkWidth",row.get("MaxLinkWidth")),
            ("DEVPKEY_PciDevice_ExpressSpecVersion",row.get("ExpressSpecVersion")),
        ]:
            if val is not None: provenance.append(key)
        rows.append({
            "name":row.get("FriendlyName"),
            "pnp_device_id":row.get("InstanceId"),
            "current_link_speed":current_speed,
            "max_link_speed":max_speed,
            "current_link_width":current_width,
            "max_link_width":max_width,
            "express_spec_version":row.get("ExpressSpecVersion"),
            "resizable_bar":_rebar_evidence(props if isinstance(props,list) else []),
            "raw_properties":props,
            "provenance":provenance,
            "confidence":0.98 if any(x is not None for x in (current_width,max_width,row.get("CurrentLinkSpeed"),row.get("MaxLinkSpeed"))) else 0.0,
        })
    return {
        "schema":SCHEMA,
        "platform":"windows" if os.name=="nt" else os.name,
        "devices":rows,
        "limitations":[
            "Current PCIe generation may downshift at idle; speed-only degradation is not a confirmed bottleneck without load validation.",
            "Lane width is reported only when Windows exposes DEVPKEY_PciDevice_CurrentLinkWidth/MaxLinkWidth.",
            "Resizable BAR is never inferred from VRAM size; only explicit device-property evidence is reported.",
        ],
    }


def match_device(pnp_device_id: str | None, inventory: dict[str, Any]) -> dict[str, Any] | None:
    needle=str(pnp_device_id or "").upper()
    if not needle: return None
    for row in inventory.get("devices",[]):
        cand=str(row.get("pnp_device_id") or "").upper()
        if cand and (cand==needle or cand in needle or needle in cand): return row
    return None
