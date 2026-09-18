from __future__ import annotations
import hashlib, json, time
from typing import Any
from phoenix_forge.modules import detect
from phoenix_forge.adapters.sensors import nvidia_smi, libre_hardware_monitor
from phoenix_forge.adapters import intel_level_zero_sysman

SCHEMA="phoenix.forge.gpu-deep-telemetry/v1"
PROVENANCE={"AUTHORITATIVE","DERIVED","FALLBACK","UNKNOWN"}

def _num(v:Any):
    if v is None or isinstance(v,bool): return None
    if isinstance(v,(int,float)): return v
    t=str(v).strip()
    if not t or t.upper() in {"N/A","NA","NONE","UNKNOWN","[NOT SUPPORTED]"}: return None
    try:
        x=float(t); return int(x) if x.is_integer() else x
    except Exception: return None

def _metric(v:Any,unit:str|None,provider:str,provenance:str,confidence:str="HIGH",evidence:str|None=None):
    available=v is not None and str(v).strip() not in {"","N/A","[Not Supported]"}
    return {"available":bool(available),"value":v if available else None,"unit":unit,
            "provider":provider if available else "none",
            "provenance":provenance if available else "UNKNOWN",
            "confidence":confidence if available else "UNKNOWN","evidence":evidence}

def _unknown(reason:str):
    return _metric(None,None,"none","UNKNOWN","UNKNOWN",reason)

def _metadata_hash(vbios:dict[str,Any]|None):
    if not vbios: return None
    raw=json.dumps(vbios,sort_keys=True,ensure_ascii=False,separators=(",",":")).encode()
    return hashlib.sha256(raw).hexdigest().upper()

def _lhm_rows(name:str):
    rows=[]
    n=name.lower()
    try: src=libre_hardware_monitor()
    except Exception: src=[]
    for r in src:
        parent=str(r.get("Parent") or "").lower()
        ident=str(r.get("Identifier") or "").lower()
        if (n and n in parent) or "/gpu" in ident or "gpu" in parent:
            rows.append(r)
    return rows

def _lhm_metric(rows,sensor_type,names):
    for r in rows:
        if str(r.get("SensorType") or "").lower()!=sensor_type.lower(): continue
        name=str(r.get("Name") or "").lower()
        if any(x in name for x in names): return r
    return None

def _fallback_lhm(gpu,metrics):
    rows=_lhm_rows(str(getattr(gpu,"name","") or ""))
    specs={
      "temperature_hotspot_c":("Temperature",("hot spot","hotspot","junction"),"C"),
      "temperature_edge_c":("Temperature",("gpu core","gpu temperature","core"),"C"),
      "fan_rpm":("Fan",("gpu","fan"),"RPM"),
      "core_clock_mhz":("Clock",("gpu core","core"),"MHz"),
      "memory_clock_mhz":("Clock",("gpu memory","memory"),"MHz"),
      "power_w":("Power",("gpu package","gpu","total"),"W"),
    }
    for key,(typ,names,unit) in specs.items():
        if metrics[key]["available"]: continue
        row=_lhm_metric(rows,typ,names)
        val=_num(row.get("Value")) if row else None
        if val is not None:
            metrics[key]=_metric(val,unit,"Phoenix Sensor Intelligence/LHM bridge","FALLBACK","MEDIUM",
                                 str(row.get("Identifier") or row.get("Name")))

def _amd(gpu):
    vd=dict(getattr(gpu,"vendor_details",{}) or {})
    mem=dict(vd.get("memory") or {}); act=dict(vd.get("activity") or {}); vb=dict(vd.get("vbios") or {})
    m={
      "temperature_edge_c":_metric(_num(vd.get("temperature_c")),"C","AMD ADL","AUTHORITATIVE",evidence="ADL_Overdrive5_Temperature_Get"),
      "temperature_hotspot_c":_unknown("hotspot not exposed by active read-only AMD provider"),
      "fan_rpm":_metric(_num(vd.get("fan_rpm")),"RPM","AMD ADL","AUTHORITATIVE",evidence="ADL_Overdrive5_FanSpeed_Get"),
      "fan_percent":_metric(_num(vd.get("fan_percent")),"%","AMD ADL","AUTHORITATIVE",evidence="ADL_Overdrive5_FanSpeed_Get"),
      "core_clock_mhz":_metric(_num(act.get("gpu_clock_mhz")),"MHz","AMD ADL","AUTHORITATIVE",evidence="ADL_Overdrive5_CurrentActivity_Get"),
      "memory_clock_mhz":_metric(_num(act.get("memory_clock_mhz")),"MHz","AMD ADL","AUTHORITATIVE",evidence="ADL_Overdrive5_CurrentActivity_Get"),
      "voltage_mv":_metric(_num(act.get("vddc_mv")),"mV","AMD ADL","AUTHORITATIVE",evidence="ADL_Overdrive5_CurrentActivity_Get"),
      "utilization_percent":_metric(_num(act.get("gpu_util_percent")),"%","AMD ADL","AUTHORITATIVE",evidence="ADL_Overdrive5_CurrentActivity_Get"),
      "power_w":_unknown("board power not exposed by active AMD ADL5 query path"),
      "power_limit_w":_unknown("power limit not exposed by active AMD ADL5 query path"),
      "performance_state":_metric(_num(act.get("current_performance_level")),None,"AMD ADL","AUTHORITATIVE",evidence="ADL_Overdrive5_CurrentActivity_Get"),
      "pcie_lanes_current":_metric(_num(act.get("pcie_lanes")),"lanes","AMD ADL","AUTHORITATIVE",evidence="ADL_Overdrive5_CurrentActivity_Get"),
      "pcie_lanes_max":_metric(_num(act.get("pcie_max_lanes")),"lanes","AMD ADL","AUTHORITATIVE",evidence="ADL_Overdrive5_CurrentActivity_Get"),
    }
    size=_num(mem.get("size_bytes")) or getattr(gpu,"adapter_ram_bytes",None)
    ident={
      "vram_size_bytes":_metric(size,"bytes","AMD ADL" if mem.get("size_bytes") else str(getattr(gpu,"vram_capacity_source",None) or "detect"),
                                "AUTHORITATIVE" if mem.get("size_bytes") else "FALLBACK",evidence="ADL_Adapter_MemoryInfo_Get" if mem.get("size_bytes") else "normalized detect inventory"),
      "vram_type":_metric(mem.get("type"),None,"AMD ADL","AUTHORITATIVE",evidence="ADL_Adapter_MemoryInfo_Get"),
      "vram_bandwidth_mb_s":_metric(_num(mem.get("bandwidth_mb_s")),"MB/s","AMD ADL","AUTHORITATIVE",evidence="ADL_Adapter_MemoryInfo_Get"),
      "vram_vendor":_unknown("physical memory-chip vendor not exposed by active provider"),
      "vram_bus_width_bits":_unknown("memory bus width not exposed by active provider"),
      "vbios_version":_metric(vb.get("version"),None,"AMD ADL","AUTHORITATIVE",evidence="ADL_Adapter_VideoBiosInfo_Get"),
      "vbios_part_number":_metric(vb.get("part_number"),None,"AMD ADL","AUTHORITATIVE",evidence="ADL_Adapter_VideoBiosInfo_Get"),
      "vbios_date":_metric(vb.get("date"),None,"AMD ADL","AUTHORITATIVE",evidence="ADL_Adapter_VideoBiosInfo_Get"),
      "vbios_metadata_sha256":_metric(_metadata_hash(vb),None,"Phoenix Forge","DERIVED",
                                      evidence="SHA-256 over normalized vendor VBIOS metadata; not ROM-binary hash"),
      "vbios_rom_sha256":_unknown("live ROM binary was not read"),
    }
    return m,ident

def _nvrows():
    try:return nvidia_smi()
    except Exception:return []

def _nvidia(gpu,row):
    m={
      "temperature_edge_c":_metric(_num(row.get("temp_c")),"C","NVIDIA management CLI","AUTHORITATIVE",evidence="read-only query-gpu"),
      "temperature_hotspot_c":_unknown("hotspot unavailable in current normalized NVIDIA query"),
      "fan_rpm":_unknown("fan RPM unavailable in current normalized NVIDIA query"),
      "fan_percent":_metric(_num(row.get("fan_pct")),"%","NVIDIA management CLI","AUTHORITATIVE",evidence="read-only query-gpu"),
      "core_clock_mhz":_metric(_num(row.get("core_mhz")),"MHz","NVIDIA management CLI","AUTHORITATIVE",evidence="read-only query-gpu"),
      "memory_clock_mhz":_metric(_num(row.get("mem_mhz")),"MHz","NVIDIA management CLI","AUTHORITATIVE",evidence="read-only query-gpu"),
      "voltage_mv":_unknown("voltage unavailable in current normalized NVIDIA query"),
      "utilization_percent":_metric(_num(row.get("util_pct")),"%","NVIDIA management CLI","AUTHORITATIVE",evidence="read-only query-gpu"),
      "power_w":_metric(_num(row.get("power_w")),"W","NVIDIA management CLI","AUTHORITATIVE",evidence="read-only query-gpu"),
      "power_limit_w":_metric(_num(row.get("power_limit_w")),"W","NVIDIA management CLI","AUTHORITATIVE",evidence="read-only query-gpu"),
      "performance_state":_metric(row.get("pstate"),None,"NVIDIA management CLI","AUTHORITATIVE",evidence="read-only query-gpu"),
      "pcie_lanes_current":_unknown("not queried by current NVIDIA provider"),
      "pcie_lanes_max":_unknown("not queried by current NVIDIA provider"),
    }
    total=_num(row.get("mem_total_mb"))
    vb={"version":row.get("vbios_version")} if row.get("vbios_version") else {}
    ident={
      "vram_size_bytes":_metric(int(total*1024*1024) if total is not None else getattr(gpu,"adapter_ram_bytes",None),
                                "bytes","NVIDIA management CLI" if total is not None else str(getattr(gpu,"vram_capacity_source",None) or "detect"),
                                "AUTHORITATIVE" if total is not None else "FALLBACK",evidence="read-only query-gpu" if total is not None else "normalized detect inventory"),
      "vram_type":_unknown("memory type unavailable in current normalized NVIDIA query"),
      "vram_bandwidth_mb_s":_unknown("memory bandwidth unavailable in current normalized NVIDIA query"),
      "vram_vendor":_unknown("physical memory-chip vendor unavailable in current normalized NVIDIA query"),
      "vram_bus_width_bits":_unknown("memory bus width unavailable in current normalized NVIDIA query"),
      "vbios_version":_metric(row.get("vbios_version"),None,"NVIDIA management CLI","AUTHORITATIVE",evidence="read-only query-gpu"),
      "vbios_part_number":_unknown("not exposed by current provider"),
      "vbios_date":_unknown("not exposed by current provider"),
      "vbios_metadata_sha256":_metric(_metadata_hash(vb),None,"Phoenix Forge","DERIVED",
                                      evidence="SHA-256 over normalized vendor VBIOS metadata; not ROM-binary hash"),
      "vbios_rom_sha256":_unknown("live ROM binary was not read"),
    }
    return m,ident


def _intel(gpu, intel_gpu_count:int):
    raw=intel_level_zero_sysman.collect_for_gpu(gpu,intel_gpu_count=intel_gpu_count)
    metrics={k:_unknown("Intel Level Zero Sysman metric not authoritatively typed/exposed by current adapter") for k in
             ("temperature_edge_c","temperature_hotspot_c","fan_rpm","fan_percent","core_clock_mhz","memory_clock_mhz","voltage_mv","utilization_percent","power_w","power_limit_w","performance_state","pcie_lanes_current","pcie_lanes_max")}
    identity={k:_unknown("Intel Level Zero Sysman identity field not exposed by current safe adapter") for k in
             ("vram_size_bytes","vram_type","vram_bandwidth_mb_s","vram_vendor","vram_bus_width_bits","vbios_version","vbios_part_number","vbios_date","vbios_metadata_sha256","vbios_rom_sha256")}
    if getattr(gpu,"adapter_ram_bytes",None):
        identity["vram_size_bytes"]=_metric(gpu.adapter_ram_bytes,"bytes",str(gpu.vram_capacity_source or "detect"),"FALLBACK","MEDIUM","normalized detect inventory")
    # Raw Sysman temperature sensors are intentionally NOT relabelled as edge/hotspot
    # until sensor properties are decoded. They remain available in vendor_raw.
    status="READY_RAW" if raw.get("mapped") and raw.get("telemetry") else (raw.get("status") or "RUNTIME_DEPENDENT")
    return metrics,identity,status,raw

def collect():
    d=detect.collect(); nv=_nvrows(); devices=[]
    intel_gpu_count=sum(1 for g in d.gpus if str(g.vendor or "").upper()=="INTEL")
    for idx,gpu in enumerate(d.gpus):
        vendor=str(gpu.vendor or "UNKNOWN").upper()
        if vendor=="AMD":
            metrics,identity=_amd(gpu); provider_status="READY" if gpu.vendor_details else "PARTIAL"
            vendor_raw=None
        elif vendor=="NVIDIA":
            row=next((x for x in nv if str(gpu.name).lower() in str(x.get("name","")).lower() or str(x.get("name","")).lower() in str(gpu.name).lower()), nv[idx] if idx<len(nv) else {})
            metrics,identity=_nvidia(gpu,row); provider_status="READY" if row else "PARTIAL"
            vendor_raw=None
        elif vendor=="INTEL":
            metrics,identity,provider_status,vendor_raw=_intel(gpu,intel_gpu_count)
        else:
            metrics={k:_unknown("no vendor-deep provider available for this GPU") for k in
                     ("temperature_edge_c","temperature_hotspot_c","fan_rpm","fan_percent","core_clock_mhz","memory_clock_mhz","voltage_mv","utilization_percent","power_w","power_limit_w","performance_state","pcie_lanes_current","pcie_lanes_max")}
            identity={k:_unknown("no vendor-deep provider available for this GPU") for k in
                     ("vram_size_bytes","vram_type","vram_bandwidth_mb_s","vram_vendor","vram_bus_width_bits","vbios_version","vbios_part_number","vbios_date","vbios_metadata_sha256","vbios_rom_sha256")}
            if getattr(gpu,"adapter_ram_bytes",None):
                identity["vram_size_bytes"]=_metric(gpu.adapter_ram_bytes,"bytes",str(gpu.vram_capacity_source or "detect"),"FALLBACK","MEDIUM","normalized detect inventory")
            provider_status="RUNTIME_DEPENDENT"
            vendor_raw=None
        _fallback_lhm(gpu,metrics)
        allm=list(metrics.values())+list(identity.values())
        available=sum(1 for x in allm if x["available"])
        devices.append({"device_key":gpu.device_key,"device_index":gpu.device_index,"name":gpu.name,"vendor":gpu.vendor,
                        "vendor_id":gpu.vendor_id,"device_id":gpu.device_id,"provider_status":provider_status,
                        "telemetry":metrics,"identity":identity,"vendor_raw":vendor_raw,
                        "coverage":{"available":available,"total":len(allm),"percent":round(100*available/len(allm),1) if allm else 0.0}})
    return {"schema":SCHEMA,"generated_at":time.time(),"status":"READY" if devices else "NO_GPU","devices":devices,
            "policy":{"read_only":True,"capability_first":True,"makes_placement_decisions":False,
                      "missing_is_unknown":True,"metadata_hash_is_not_rom_hash":True,
                      "provider_provenance_required":True,"unsupported_metric_is_not_zero":True}}
