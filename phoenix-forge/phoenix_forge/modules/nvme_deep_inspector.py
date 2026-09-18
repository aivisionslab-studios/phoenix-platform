from __future__ import annotations

import json
import platform
import shutil
import subprocess
import time
from typing import Any

from phoenix_forge.adapters import windows_storage_pcie

SCHEMA="phoenix.forge.nvme-deep-inspector/v3"
PRODUCT="Phoenix Storage Inspector"

def _ps(script:str)->Any:
    try:
        cp=subprocess.run(["powershell.exe","-NoProfile","-Command",script],
                          capture_output=True,text=True,timeout=30)
        if cp.returncode!=0:
            return None
        raw=cp.stdout.strip()
        return json.loads(raw) if raw else None
    except Exception:
        return None

def _rows(v:Any)->list[dict[str,Any]]:
    if isinstance(v,dict):
        return [v]
    return [x for x in (v or []) if isinstance(x,dict)]

def _metric(value:Any, *, unit:str|None, provider:str, provenance:str,
            evidence:str|None=None, confidence:str="HIGH")->dict[str,Any]:
    available=value is not None and value!=""
    return {
        "available":bool(available),
        "value":value if available else None,
        "unit":unit,
        "provider":provider if available else "none",
        "provenance":provenance if available else "UNKNOWN",
        "confidence":confidence if available else "UNKNOWN",
        "evidence":evidence,
    }

def _unknown(reason:str)->dict[str,Any]:
    return _metric(None,unit=None,provider="none",provenance="UNKNOWN",
                   confidence="UNKNOWN",evidence=reason)

def _as_int(v:Any)->int|None:
    if v is None or isinstance(v,bool):
        return None
    try:
        return int(v)
    except Exception:
        try:
            return int(float(str(v).strip()))
        except Exception:
            return None

def _windows_devices()->list[dict[str,Any]]:
    if platform.system().lower()!="windows":
        return []
    script=r"""
$out=@()
Get-PhysicalDisk -ErrorAction SilentlyContinue | ForEach-Object {
  $d=$_
  $r=$null
  try {$r=$d | Get-StorageReliabilityCounter -ErrorAction Stop} catch {}
  $disk=$null
  try {
    $disk=Get-Disk -ErrorAction SilentlyContinue | Where-Object {
      ($d.SerialNumber -and $_.SerialNumber -and ($_.SerialNumber.Trim() -eq $d.SerialNumber.Trim())) -or
      ($_.FriendlyName -eq $d.FriendlyName -and $_.Size -eq $d.Size)
    } | Select-Object -First 1
  } catch {}
  [pscustomobject]@{
    FriendlyName=$d.FriendlyName
    SerialNumber=$d.SerialNumber
    MediaType=[string]$d.MediaType
    BusType=[string]$d.BusType
    HealthStatus=[string]$d.HealthStatus
    OperationalStatus=[string]$d.OperationalStatus
    Size=$d.Size
    FirmwareVersion=$d.FirmwareVersion
    UniqueId=$d.UniqueId
    PhysicalLocation=$d.PhysicalLocation
    CanPool=$d.CanPool
    CannotPoolReason=[string]$d.CannotPoolReason
    DiskNumber=if($disk){$disk.Number}else{$null}
    PartitionStyle=if($disk){[string]$disk.PartitionStyle}else{$null}
    IsBoot=if($disk){$disk.IsBoot}else{$null}
    IsSystem=if($disk){$disk.IsSystem}else{$null}
    DiskPath=if($disk){$disk.Path}else{$null}
    Reliability=if($r){[pscustomobject]@{
      Temperature=$r.Temperature
      TemperatureMax=$r.TemperatureMax
      Wear=$r.Wear
      PowerOnHours=$r.PowerOnHours
      ReadErrorsTotal=$r.ReadErrorsTotal
      WriteErrorsTotal=$r.WriteErrorsTotal
      ReadLatencyMax=$r.ReadLatencyMax
      WriteLatencyMax=$r.WriteLatencyMax
    }}else{$null}
  }
}
$out | ConvertTo-Json -Depth 7 -Compress
"""
    return _rows(_ps(script))

def _smartctl_devices()->list[dict[str,Any]]:
    exe=shutil.which("smartctl") or shutil.which("smartctl.exe")
    if not exe:
        return []
    try:
        scan=subprocess.run([exe,"--scan-open","--json"],capture_output=True,text=True,timeout=20)
        parsed=json.loads(scan.stdout or "{}")
    except Exception:
        return []
    out=[]
    for item in parsed.get("devices") or []:
        name=item.get("name")
        if not name:
            continue
        try:
            cp=subprocess.run([exe,"-a",name,"--json"],capture_output=True,text=True,timeout=30)
            data=json.loads(cp.stdout or "{}")
        except Exception:
            continue
        if isinstance(data,dict):
            data["_phoenix_device_path"]=name
            out.append(data)
    return out

def _norm_serial(v:Any)->str:
    return str(v or "").strip().upper()

def _match_smart(win:dict[str,Any], smart:list[dict[str,Any]])->tuple[dict[str,Any]|None,str]:
    serial=_norm_serial(win.get("SerialNumber"))
    if serial:
        for row in smart:
            if _norm_serial(row.get("serial_number"))==serial:
                return row,"SERIAL_EXACT"
        return None,"SERIAL_MISMATCH"
    model=str(win.get("FriendlyName") or "").strip().lower()
    if model:
        candidates=[r for r in smart if not _norm_serial(r.get("serial_number")) and
                    str(r.get("model_name") or r.get("model_family") or "").strip().lower()==model]
        if len(candidates)==1:
            return candidates[0],"MODEL_UNIQUE_NO_SERIAL"
    return None,"UNMATCHED"

def _nvme_log(row:dict[str,Any]|None)->dict[str,Any]:
    if not row:
        return {}
    log=row.get("nvme_smart_health_information_log")
    return log if isinstance(log,dict) else {}

def _normalize(win:dict[str,Any], smart:dict[str,Any]|None, match_mode:str, pcie_map:dict[str,Any]|None=None, pcie_match_mode:str="UNMATCHED")->dict[str,Any]:
    rel=win.get("Reliability") if isinstance(win.get("Reliability"),dict) else {}
    nv=_nvme_log(smart)
    bus=str(win.get("BusType") or "")
    is_nvme=bus.upper()=="NVME"

    def smart_metric(key:str,unit:str|None=None):
        return _metric(nv.get(key),unit=unit,provider="smartctl",provenance="AUTHORITATIVE",
                       evidence=f"nvme_smart_health_information_log.{key}") if key in nv else _unknown(
                       f"{key} not exposed by active NVMe SMART provider")

    health={
      "windows_health_status":_metric(win.get("HealthStatus"),unit=None,provider="Windows Storage CIM",
                                      provenance="AUTHORITATIVE",evidence="Get-PhysicalDisk.HealthStatus"),
      "windows_operational_status":_metric(win.get("OperationalStatus"),unit=None,provider="Windows Storage CIM",
                                           provenance="AUTHORITATIVE",evidence="Get-PhysicalDisk.OperationalStatus"),
      "temperature_c":(
          smart_metric("temperature","C") if "temperature" in nv else
          _metric(rel.get("Temperature"),unit="C",provider="Windows Storage Reliability",
                  provenance="AUTHORITATIVE",evidence="Get-StorageReliabilityCounter.Temperature")
      ),
      "temperature_max_c":_metric(rel.get("TemperatureMax"),unit="C",provider="Windows Storage Reliability",
                                  provenance="AUTHORITATIVE",evidence="Get-StorageReliabilityCounter.TemperatureMax"),
      "wear_raw":_metric(rel.get("Wear"),unit="provider_native",provider="Windows Storage Reliability",
                         provenance="AUTHORITATIVE",evidence="Get-StorageReliabilityCounter.Wear"),
      "percentage_used":smart_metric("percentage_used","%"),
      "available_spare_percent":smart_metric("available_spare","%"),
      "available_spare_threshold_percent":smart_metric("available_spare_threshold","%"),
      "critical_warning":smart_metric("critical_warning",None),
      "power_on_hours":(
          smart_metric("power_on_hours","hours") if "power_on_hours" in nv else
          _metric(rel.get("PowerOnHours"),unit="hours",provider="Windows Storage Reliability",
                  provenance="AUTHORITATIVE",evidence="Get-StorageReliabilityCounter.PowerOnHours")
      ),
      "power_cycles":smart_metric("power_cycles","count"),
      "unsafe_shutdowns":smart_metric("unsafe_shutdowns","count"),
      "media_errors":smart_metric("media_errors","count"),
      "error_log_entries":smart_metric("num_err_log_entries","count"),
      "data_units_read":smart_metric("data_units_read","NVMe_data_units"),
      "data_units_written":smart_metric("data_units_written","NVMe_data_units"),
      "read_errors_total":_metric(rel.get("ReadErrorsTotal"),unit="count",provider="Windows Storage Reliability",
                                  provenance="AUTHORITATIVE",evidence="Get-StorageReliabilityCounter.ReadErrorsTotal"),
      "write_errors_total":_metric(rel.get("WriteErrorsTotal"),unit="count",provider="Windows Storage Reliability",
                                   provenance="AUTHORITATIVE",evidence="Get-StorageReliabilityCounter.WriteErrorsTotal"),
      "read_latency_max_raw":_metric(rel.get("ReadLatencyMax"),unit="provider_native",provider="Windows Storage Reliability",
                                     provenance="AUTHORITATIVE",evidence="Get-StorageReliabilityCounter.ReadLatencyMax"),
      "write_latency_max_raw":_metric(rel.get("WriteLatencyMax"),unit="provider_native",provider="Windows Storage Reliability",
                                      provenance="AUTHORITATIVE",evidence="Get-StorageReliabilityCounter.WriteLatencyMax"),
    }

    identity={
      "model":_metric(win.get("FriendlyName"),unit=None,provider="Windows Storage CIM",
                      provenance="AUTHORITATIVE",evidence="Get-PhysicalDisk.FriendlyName"),
      "serial":_metric(win.get("SerialNumber"),unit=None,provider="Windows Storage CIM",
                       provenance="AUTHORITATIVE",evidence="Get-PhysicalDisk.SerialNumber"),
      "firmware":_metric(win.get("FirmwareVersion") or (smart or {}).get("firmware_version"),unit=None,
                         provider="Windows Storage CIM" if win.get("FirmwareVersion") else "smartctl",
                         provenance="AUTHORITATIVE",evidence="firmware metadata"),
      "size_bytes":_metric(_as_int(win.get("Size")),unit="bytes",provider="Windows Storage CIM",
                           provenance="AUTHORITATIVE",evidence="Get-PhysicalDisk.Size"),
      "bus_type":_metric(bus or None,unit=None,provider="Windows Storage CIM",
                         provenance="AUTHORITATIVE",evidence="Get-PhysicalDisk.BusType"),
      "media_type":_metric(win.get("MediaType"),unit=None,provider="Windows Storage CIM",
                           provenance="AUTHORITATIVE",evidence="Get-PhysicalDisk.MediaType"),
      "disk_number":_metric(win.get("DiskNumber"),unit=None,provider="Windows Storage CIM",
                            provenance="AUTHORITATIVE",evidence="Get-Disk.Number"),
      "is_boot":_metric(win.get("IsBoot"),unit=None,provider="Windows Storage CIM",
                        provenance="AUTHORITATIVE",evidence="Get-Disk.IsBoot"),
      "is_system":_metric(win.get("IsSystem"),unit=None,provider="Windows Storage CIM",
                          provenance="AUTHORITATIVE",evidence="Get-Disk.IsSystem"),
      "physical_location":_metric(win.get("PhysicalLocation"),unit=None,provider="Windows Storage CIM",
                                  provenance="AUTHORITATIVE",evidence="Get-PhysicalDisk.PhysicalLocation"),
      "smart_match_mode":_metric(match_mode if smart else None,unit=None,provider="Phoenix Forge",
                                 provenance="DERIVED",evidence="serial exact preferred; unique model fallback"),
    }

    pci_node=(pcie_map or {}).get("pci") if isinstance((pcie_map or {}).get("pci"),dict) else {}
    pcie_provenance=list(pci_node.get("provenance") or [])
    pcie_provider="Windows PnP storage parent chain"
    pcie={
      "mapping_status":"PROVEN" if pci_node.get("controller_instance_id") else "UNKNOWN",
      "mapping_mode":_metric(pcie_match_mode if pci_node.get("controller_instance_id") else None,unit=None,provider="Phoenix Forge",provenance="DERIVED",evidence="safe physical-disk identity match"),
      "controller_instance_id":_metric(pci_node.get("controller_instance_id"),unit=None,provider=pcie_provider,provenance="AUTHORITATIVE",evidence="DEVPKEY_Device_Parent chain"),
      "controller_name":_metric(pci_node.get("controller_name"),unit=None,provider=pcie_provider,provenance="AUTHORITATIVE",evidence="PCI ancestor devnode"),
      "bdf":_metric(pci_node.get("bdf"),unit=None,provider=pcie_provider,provenance="AUTHORITATIVE",evidence="DEVPKEY_Device_BusNumber + DEVPKEY_Device_LocationPaths") if pci_node.get("bdf") else _unknown("NVMe PCI ancestor BDF not exposed/provable on this machine"),
      "current_generation":_metric(pci_node.get("current_generation"),unit="PCIe_generation",provider=pcie_provider,provenance="AUTHORITATIVE",evidence="DEVPKEY_PciDevice_CurrentLinkSpeed") if pci_node.get("current_generation") is not None else _unknown("PCIe current generation not exposed by mapped storage controller"),
      "current_width":_metric(pci_node.get("current_width"),unit="lanes",provider=pcie_provider,provenance="AUTHORITATIVE",evidence="DEVPKEY_PciDevice_CurrentLinkWidth") if pci_node.get("current_width") is not None else _unknown("PCIe current width not exposed by mapped storage controller"),
      "max_generation":_metric(pci_node.get("max_generation"),unit="PCIe_generation",provider=pcie_provider,provenance="AUTHORITATIVE",evidence="DEVPKEY_PciDevice_MaxLinkSpeed") if pci_node.get("max_generation") is not None else _unknown("PCIe max generation not exposed by mapped storage controller"),
      "max_width":_metric(pci_node.get("max_width"),unit="lanes",provider=pcie_provider,provenance="AUTHORITATIVE",evidence="DEVPKEY_PciDevice_MaxLinkWidth") if pci_node.get("max_width") is not None else _unknown("PCIe max width not exposed by mapped storage controller"),
      "express_spec_version":_metric(pci_node.get("express_spec_version"),unit=None,provider=pcie_provider,provenance="AUTHORITATIVE",evidence="DEVPKEY_PciDevice_ExpressSpecVersion") if pci_node.get("express_spec_version") is not None else _unknown("PCIe express spec version not exposed by mapped storage controller"),
      "provenance":pcie_provenance,
    }

    alerts=[]
    hs=str(win.get("HealthStatus") or "").strip().lower()
    if hs and hs not in {"healthy","ok","unknown"}:
        alerts.append({"kind":"HEALTH_STATUS","severity":"HIGH","evidence":"Windows Storage CIM",
                       "value":win.get("HealthStatus")})
    for key in ("media_errors","critical_warning"):
        m=health[key]
        if m["available"] and _as_int(m["value"]) not in (None,0):
            alerts.append({"kind":key.upper(),"severity":"HIGH","evidence":m["provider"],"value":m["value"]})

    all_metrics=list(health.values())+list(identity.values())
    avail=sum(1 for x in all_metrics if x.get("available"))
    return {
      "product":PRODUCT,
      "name":win.get("FriendlyName"),
      "is_nvme":is_nvme,
      "health":health,
      "identity":identity,
      "pcie":pcie,
      "alerts":alerts,
      "coverage":{"available":avail,"total":len(all_metrics),
                  "percent":round(100.0*avail/len(all_metrics),1) if all_metrics else 0.0},
      "providers":{"windows_storage":True,"windows_reliability":bool(rel),
                   "smartctl":bool(smart),"smart_match_mode":match_mode if smart else None},
    }

def collect()->dict[str,Any]:
    if platform.system().lower()!="windows":
        return {
          "schema":SCHEMA,"product":PRODUCT,"generated_at":time.time(),"status":"UNAVAILABLE",
          "devices":[],"unmatched_smartctl_devices":[],"provider_status":{"windows_storage":"UNAVAILABLE",
          "smartctl":"RUNTIME_DEPENDENT"},"limitations":["Windows Storage provider is Windows-only in this release."],
          "policy":{"read_only":True,"capability_first":True,"makes_placement_decisions":False,
                    "missing_is_unknown":True,"smartctl_is_optional":True}}
    win=_windows_devices()
    smart=_smartctl_devices()
    storage_pcie=windows_storage_pcie.collect()
    used=set()
    devices=[]
    for w in win:
        sm,mode=_match_smart(w,smart)
        if sm is not None:
            used.add(id(sm))
        pmap,pmode=windows_storage_pcie.match_physical_disk(w,storage_pcie) if str(w.get("BusType") or "").upper()=="NVME" else (None,"NOT_NVME")
        devices.append(_normalize(w,sm,mode,pmap,pmode))
    unmatched=[{
        "device_path":r.get("_phoenix_device_path"),
        "model":r.get("model_name"),
        "serial":r.get("serial_number"),
        "protocol":r.get("device",{}).get("protocol") if isinstance(r.get("device"),dict) else None,
        "reason":"not merged because no safe exact/unique match to Windows physical disk inventory"
    } for r in smart if id(r) not in used]
    nvme_count=sum(1 for d in devices if d["is_nvme"])
    return {
      "schema":SCHEMA,"product":PRODUCT,"generated_at":time.time(),
      "status":"READY" if devices else "PARTIAL",
      "summary":{"physical_disks":len(devices),"nvme_devices":nvme_count,
                 "windows_reliability_devices":sum(1 for d in devices if d["providers"]["windows_reliability"]),
                 "smartctl_matched_devices":sum(1 for d in devices if d["providers"]["smartctl"]),
                 "smartctl_unmatched_devices":len(unmatched),
                 "nvme_pcie_mapped_devices":sum(1 for d in devices if d.get("is_nvme") and (d.get("pcie") or {}).get("mapping_status")=="PROVEN"),
                 "nvme_pcie_bdf_devices":sum(1 for d in devices if d.get("is_nvme") and ((d.get("pcie") or {}).get("bdf") or {}).get("available"))},
      "devices":devices,
      "unmatched_smartctl_devices":unmatched,
      "provider_status":{"windows_storage":"READY" if devices else "PARTIAL",
                         "smartctl":"READY" if smart else "RUNTIME_DEPENDENT",
                         "storage_pcie_mapping":storage_pcie.get("status","UNAVAILABLE")},
      "limitations":[
        "Full NVMe SMART/health fields depend on driver and optional read-only smartctl availability.",
        "Windows Wear is preserved as provider-native raw semantics; Forge does not silently relabel it as NVMe percentage-used.",
        "NVMe-to-PCIe mapping follows the Windows PnP parent chain; BDF/link fields remain UNKNOWN when the PCI ancestor or required properties are not exposed.",
        "Unmatched smartctl devices are not silently attached to Windows disks."
      ],
      "policy":{"read_only":True,"capability_first":True,"makes_placement_decisions":False,
                "missing_is_unknown":True,"smartctl_is_optional":True,
                "serial_exact_match_preferred":True,"unmatched_provider_data_is_not_merged":True,
                "windows_wear_is_not_relabelled":True,
                "nvme_pcie_model_only_matching_prohibited":True,
                "nvme_pcie_parent_chain_required":True}
    }
