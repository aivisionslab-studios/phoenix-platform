from __future__ import annotations
import re, time
from typing import Any
from phoenix_forge.adapters import windows_pcie_link, windows_topology

SCHEMA="phoenix.forge.pcie-deep-inspection/v2"

_PER_LANE_GB_S={1:0.250,2:0.500,3:0.985,4:1.969,5:3.938,6:7.877,7:15.754}

def _metric(value:Any, *, provider:str, provenance:str, evidence:str|None=None, confidence:str="HIGH"):
    available=value is not None and value!=""
    return {"available":available,"value":value if available else None,
            "provider":provider if available else "none",
            "provenance":provenance if available else "UNKNOWN",
            "confidence":confidence if available else "UNKNOWN","evidence":evidence}

def _unknown(reason:str):
    return _metric(None,provider="none",provenance="UNKNOWN",evidence=reason,confidence="UNKNOWN")

def _bandwidth(gen:int|None,width:int|None):
    if gen not in _PER_LANE_GB_S or not width:return None
    return round(_PER_LANE_GB_S[gen]*int(width),3)

def _parent_chain(path:str|None):
    text=str(path or "")
    root=None
    m=re.search(r"PCIROOT\(([0-9A-Fa-f]+)\)",text)
    if m:
        try:root=int(m.group(1),16)
        except Exception:root=None
    seg=[]
    for token in re.findall(r"PCI\(([0-9A-Fa-f]{4})\)",text):
        v=int(token,16);seg.append({"device":(v>>8)&0xFF,"function":v&0xFF,"token":token.upper()})
    return {"root":root,"segments":seg,"depth":len(seg)}

def _device(row:dict[str,Any], topo_row:dict[str,Any]):
    cs=row.get("current_link_speed") or {};ms=row.get("max_link_speed") or {}
    cg=cs.get("generation");mg=ms.get("generation")
    cw=row.get("current_link_width");mw=row.get("max_link_width")
    paths=topo_row.get("location_paths") or []
    primary=paths[0] if paths else None
    chain=_parent_chain(primary)
    rebar=row.get("resizable_bar") or {}
    current_bw=_bandwidth(cg,cw);max_bw=_bandwidth(mg,mw)
    width_ratio=round(float(cw)/float(mw),4) if cw and mw else None
    gen_ratio=round(float(cg)/float(mg),4) if cg and mg else None
    numa=topo_row.get("numa_affinity") or {}
    numa_metric = (_metric(numa.get("node_id"), provider="Windows PnP NUMA proximity", provenance="AUTHORITATIVE", evidence="DEVPKEY_Numa_Proximity_Domain -> GetNumaProximityNodeEx")
                   if numa.get("status") == "PROVEN" and numa.get("node_id") is not None
                   else _unknown(numa.get("reason") or "GPU devnode does not expose resolvable NUMA proximity evidence"))
    return {
      "name":row.get("name"),"pnp_device_id":row.get("pnp_device_id"),
      "location":{
        "bdf":_metric(topo_row.get("bdf"),provider="Windows PnP topology",provenance="AUTHORITATIVE",evidence="BusNumber + LocationPaths"),
        "bus_number":_metric(topo_row.get("bus_number"),provider="Windows PnP topology",provenance="AUTHORITATIVE",evidence="DEVPKEY_Device_BusNumber"),
        "device_number":_metric(topo_row.get("device_number"),provider="Windows PnP topology",provenance="DERIVED",evidence="parsed PCI LocationPaths"),
        "function_number":_metric(topo_row.get("function_number"),provider="Windows PnP topology",provenance="DERIVED",evidence="parsed PCI LocationPaths"),
        "pci_root":_metric(topo_row.get("pci_root"),provider="Windows PnP topology",provenance="DERIVED",evidence="PCIROOT token"),
        "parent_pnp":_metric(topo_row.get("parent"),provider="Windows PnP topology",provenance="AUTHORITATIVE",evidence="DEVPKEY_Device_Parent"),
        "location_info":_metric(topo_row.get("location_info"),provider="Windows PnP topology",provenance="AUTHORITATIVE",evidence="DEVPKEY_Device_LocationInfo"),
        "location_path":_metric(primary,provider="Windows PnP topology",provenance="AUTHORITATIVE",evidence="DEVPKEY_Device_LocationPaths"),
        "parent_chain":_metric(chain if primary else None,provider="Phoenix Forge",provenance="DERIVED",evidence="mechanical decode of LocationPaths"),
        "physical_slot":_unknown("physical chassis slot is not inferred from bus/device/function or LocationInfo"),
        "numa_node":numa_metric,
        "numa_proximity_domain":_metric(numa.get("proximity_domain"),provider="Windows PnP topology",provenance="AUTHORITATIVE",evidence="DEVPKEY_Numa_Proximity_Domain") if numa.get("proximity_domain") is not None else _unknown("NUMA proximity domain not exposed by GPU devnode"),
      },
      "link":{
        "current_generation":_metric(cg,provider="Windows PCIe properties",provenance="AUTHORITATIVE",evidence=cs.get("status")),
        "current_gt_s":_metric(cs.get("gt_s"),provider="Windows PCIe properties",provenance="AUTHORITATIVE",evidence=cs.get("status")),
        "current_width":_metric(cw,provider="Windows PCIe properties",provenance="AUTHORITATIVE",evidence="DEVPKEY_PciDevice_CurrentLinkWidth"),
        "max_generation":_metric(mg,provider="Windows PCIe properties",provenance="AUTHORITATIVE",evidence=ms.get("status")),
        "max_gt_s":_metric(ms.get("gt_s"),provider="Windows PCIe properties",provenance="AUTHORITATIVE",evidence=ms.get("status")),
        "max_width":_metric(mw,provider="Windows PCIe properties",provenance="AUTHORITATIVE",evidence="DEVPKEY_PciDevice_MaxLinkWidth"),
        "electrical_width":_unknown("electrical slot width is distinct from negotiated/max lane width and is not exposed by the active provider"),
        "current_theoretical_gb_s_per_direction":_metric(current_bw,provider="Phoenix Forge",provenance="DERIVED",evidence="generation × lane-width theoretical encoding rate"),
        "max_theoretical_gb_s_per_direction":_metric(max_bw,provider="Phoenix Forge",provenance="DERIVED",evidence="generation × lane-width theoretical encoding rate"),
        "width_ratio":_metric(width_ratio,provider="Phoenix Forge",provenance="DERIVED",evidence="current_width/max_width"),
        "generation_ratio":_metric(gen_ratio,provider="Phoenix Forge",provenance="DERIVED",evidence="current_generation/max_generation"),
        "express_spec_version":_metric(row.get("express_spec_version"),provider="Windows PCIe properties",provenance="AUTHORITATIVE",evidence="DEVPKEY_PciDevice_ExpressSpecVersion"),
      },
      "features":{
        "resizable_bar":{"available":rebar.get("status") not in (None,"UNKNOWN"),"status":rebar.get("status","UNKNOWN"),"enabled":rebar.get("enabled"),"provider":"Windows PnP properties" if rebar.get("status") not in (None,"UNKNOWN") else "none","provenance":"AUTHORITATIVE" if rebar.get("enabled") is not None else ("FALLBACK" if rebar.get("properties") else "UNKNOWN"),"evidence":rebar.get("properties") or []},
        "aer_error_counters":_unknown("per-device PCIe AER counters are not exposed by the active generic Windows provider"),
        "retrain_counter":_unknown("link retrain counter is not exposed by the active generic Windows provider"),
      },
      "assessment":{
        "width_below_max":bool(cw and mw and cw<mw),
        "generation_below_max":bool(cg and mg and cg<mg),
        "idle_downshift_warning":bool(cg and mg and cg<mg),
        "confirmed_bottleneck":False,
        "reason":"current generation below maximum requires load validation before bottleneck classification" if cg and mg and cg<mg else None,
      }
    }

def collect():
    links=windows_pcie_link.collect();topo=windows_topology.collect();devices=[]
    for row in links.get("devices") or []:
        tr=windows_topology.match_gpu(row.get("pnp_device_id"),topo) or {}
        devices.append(_device(row,tr))
    return {"schema":SCHEMA,"generated_at":time.time(),"status":"READY" if devices else "UNAVAILABLE","devices":devices,
      "policy":{"read_only":True,"capability_first":True,"makes_placement_decisions":False,"unknown_is_not_zero":True,
                "physical_slot_is_not_inferred":True,"pcie_root_is_not_numa_affinity":True,"idle_speed_downshift_is_not_confirmed_bottleneck":True,
                "electrical_width_is_distinct_from_negotiated_width":True},
      "limitations":links.get("limitations") or []}
