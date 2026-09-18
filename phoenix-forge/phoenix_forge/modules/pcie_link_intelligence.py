from __future__ import annotations

import time
from typing import Any

from phoenix_forge.adapters import windows_pcie_link, windows_topology

SCHEMA = "phoenix.forge.pcie-link-intelligence/v1"

_PER_LANE_GB_S = {1:0.250,2:0.500,3:0.985,4:1.969,5:3.938,6:7.877,7:15.754}


def _theoretical_gb_s(gen: int | None, width: int | None) -> float | None:
    if gen not in _PER_LANE_GB_S or not width: return None
    return round(_PER_LANE_GB_S[gen] * width, 3)


def classify_link(current_width: int | None, max_width: int | None, current_gen: int | None, max_gen: int | None, *, load_validated: bool=False) -> dict[str, Any]:
    width_state="UNKNOWN"; speed_state="UNKNOWN"; bottleneck="UNKNOWN"; severity="INFO"
    findings=[]
    if current_width and max_width:
        if current_width < max_width:
            width_state="REDUCED"
            findings.append({"kind":"PCIE_WIDTH_BELOW_MAX","current_width":current_width,"max_width":max_width,"measured":True})
            bottleneck="POTENTIAL_MEASURED_LIMIT"; severity="MEDIUM"
        else:
            width_state="AT_MAX"
    if current_gen and max_gen:
        if current_gen < max_gen:
            speed_state="BELOW_MAX"
            findings.append({"kind":"PCIE_SPEED_BELOW_MAX","current_generation":current_gen,"max_generation":max_gen,"load_validated":load_validated})
            if load_validated:
                bottleneck="CONFIRMED_LINK_NEGOTIATION_LIMIT"; severity="MEDIUM"
            elif bottleneck=="UNKNOWN":
                bottleneck="NEEDS_LOAD_VALIDATION"
        else:
            speed_state="AT_MAX"
    if width_state=="AT_MAX" and speed_state=="AT_MAX":
        bottleneck="NO_LINK_DEGRADATION_OBSERVED"; severity="INFO"
    return {"width_state":width_state,"speed_state":speed_state,"bottleneck_status":bottleneck,"severity":severity,"findings":findings,"load_validated":load_validated}


def collect(*, load_validated: bool=False) -> dict[str, Any]:
    link_inv=windows_pcie_link.collect()
    topo=windows_topology.collect()
    devices=[]
    for row in link_inv.get("devices",[]):
        pnp=row.get("pnp_device_id")
        topo_row=windows_topology.match_gpu(pnp,topo) or {}
        cs=row.get("current_link_speed") or {}; ms=row.get("max_link_speed") or {}
        cw=row.get("current_link_width"); mw=row.get("max_link_width")
        cg=cs.get("generation"); mg=ms.get("generation")
        cls=classify_link(cw,mw,cg,mg,load_validated=load_validated)
        devices.append({
            "name":row.get("name"),"pnp_device_id":pnp,
            "bdf":topo_row.get("bdf"),"pci_root":topo_row.get("pci_root"),"parent":topo_row.get("parent"),
            "current":{"generation":cg,"gt_s":cs.get("gt_s"),"width":cw,"theoretical_gb_s_per_direction":_theoretical_gb_s(cg,cw)},
            "maximum":{"generation":mg,"gt_s":ms.get("gt_s"),"width":mw,"theoretical_gb_s_per_direction":_theoretical_gb_s(mg,mw)},
            "classification":cls,
            "resizable_bar":row.get("resizable_bar",{}),
            "express_spec_version":row.get("express_spec_version"),
            "provenance":list(dict.fromkeys((row.get("provenance") or [])+(topo_row.get("provenance") or []))),
            "confidence":max(float(row.get("confidence") or 0.0),float(topo_row.get("confidence") or 0.0)),
        })
    return {
        "schema":SCHEMA,"generated_at":time.time(),"status":"COMPLETE" if devices else "UNAVAILABLE",
        "load_validated":load_validated,"devices":devices,
        "invariants":{
            "idle_speed_downshift_is_not_automatic_bottleneck":True,
            "reduced_width_is_reported_as_measured_potential_limit":True,
            "rebar_requires_explicit_evidence":True,
            "unknown_link_properties_remain_unknown":True,
        },
        "limitations":link_inv.get("limitations",[]),
    }
