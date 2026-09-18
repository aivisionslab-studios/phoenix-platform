from __future__ import annotations

import hashlib, json, os, tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from phoenix_forge.modules import gpu_safety, compute_fabric, gpu_identity_registry

SCHEMA = "phoenix.forge.gpu-qualification/v1"
HARDWARE_FAILURES = {"MEMORY_ERROR", "DATA_MISMATCH", "COMPUTE_MISMATCH"}
CAPACITY_FAILURES = {"OOM", "OUT_OF_MEMORY", "OUTOFDEVICEMEMORY", "TIMEOUT", "ALLOCATION_FAILED", "BUDGET_EXHAUSTED"}

def _now() -> str:return datetime.now(timezone.utc).isoformat()
def _path() -> Path:return gpu_safety.state_dir()/"gpu-qualification.jsonl"
def _append(entry:dict[str,Any])->None:
    path=_path();path.parent.mkdir(parents=True,exist_ok=True)
    with path.open("a",encoding="utf-8",newline="\n") as h:h.write(json.dumps(entry,ensure_ascii=False,separators=(",",":"))+"\n");h.flush();os.fsync(h.fileno())
def _rom(path:str|None)->dict[str,Any]:
    if not path:return {"provided":False,"sha256":None,"size_bytes":None}
    source=Path(path);payload=source.read_bytes()
    if len(payload)<65536 or payload[:2]!=b"\x55\xaa":raise ValueError("ROM inválida: cabeçalho 55 AA ou tamanho mínimo ausente.")
    return {"provided":True,"name":source.name,"sha256":hashlib.sha256(payload).hexdigest(),"size_bytes":len(payload)}
def _identity(gpu)->dict[str,Any]:
    return {"name":gpu.name,"pnp_device_id":gpu.pnp_device_id,"vendor_id":gpu.vendor_id,"device_id":gpu.device_id,
      "subsystem_vendor_id":gpu.subsystem_vendor_id,"subsystem_device_id":gpu.subsystem_device_id,"revision_id":gpu.revision_id,
      "driver_version":gpu.driver_version,"driver_date":gpu.driver_date,"vram_bytes":gpu.adapter_ram_bytes}
def _legacy_key(device_label:str)->str:return hashlib.sha256(device_label.strip().casefold().encode("utf-8")).hexdigest()[:24]
def capture(*,gpu,device_label:str,phase:str,vbios_path:str|None=None,memory_clock_mhz:int|None=None,notes:str|None=None)->dict[str,Any]:
    phase=phase.upper();
    if phase not in {"PRE_FLASH","POST_FLASH"}:raise ValueError("phase deve ser PRE_FLASH ou POST_FLASH")
    label=device_label.strip()
    if not label:raise ValueError("device_label é obrigatório para não misturar placas físicas.")
    identity=_identity(gpu);rom=_rom(vbios_path)
    persistent_key = gpu.device_key or compute_fabric.stable_device_key(gpu)
    gpu_identity_registry.bind(persistent_key, label, evidence={"name":gpu.name,"vendor_id":gpu.vendor_id,"device_id":gpu.device_id,"pnp_device_id":gpu.pnp_device_id})
    entry={"schema":SCHEMA,"captured_at":_now(),"phase":phase,"device_label":label,"device_key":persistent_key,"legacy_label_key":_legacy_key(label),"identity":identity,"rom":rom,
      "memory_clock_mhz":memory_clock_mhz,"notes":notes,"immutable_record":True}
    entry["record_sha256"]=hashlib.sha256(json.dumps(entry,sort_keys=True,ensure_ascii=False,separators=(",",":")).encode()).hexdigest()
    _append(entry);return entry
def history(device_key:str|None=None,limit:int=50)->dict[str,Any]:
    try:lines=_path().read_text(encoding="utf-8").splitlines()
    except OSError:lines=[]
    rows=[]
    legacy_for_key=None
    if device_key:
        reg=gpu_identity_registry.resolve(device_key)
        if reg and reg.get("physical_alias"):
            legacy_for_key=_legacy_key(str(reg.get("physical_alias")))
    for line in lines:
        try:
            row=json.loads(line)
            if not isinstance(row,dict):
                continue
            if not device_key or row.get("device_key")==device_key or row.get("legacy_label_key")==device_key or (legacy_for_key and row.get("device_key")==legacy_for_key):
                rows.append(row)
        except json.JSONDecodeError:continue
    rows=rows[-max(1,min(int(limit),200)):]
    return {"schema":SCHEMA,"count":len(rows),"entries":rows}
def compare(device_key:str)->dict[str,Any]:
    rows=history(device_key,200)["entries"];pre=next((x for x in reversed(rows) if x.get("phase")=="PRE_FLASH"),None);post=next((x for x in reversed(rows) if x.get("phase")=="POST_FLASH"),None)
    if not pre or not post:return {"schema":"phoenix.forge.gpu-qualification-comparison/v1","status":"INCOMPLETE","device_key":device_key,"missing":[x for x,v in (("PRE_FLASH",pre),("POST_FLASH",post)) if not v]}
    same_pci=all(pre["identity"].get(k)==post["identity"].get(k) for k in ("vendor_id","device_id","subsystem_vendor_id","subsystem_device_id","revision_id"))
    before=pre.get("rom",{}).get("sha256");after=post.get("rom",{}).get("sha256")
    return {"schema":"phoenix.forge.gpu-qualification-comparison/v1","status":"READY_FOR_CONTROLLED_TESTS" if same_pci else "IDENTITY_MISMATCH",
      "device_key":device_key,"same_pci_identity":same_pci,"rom_changed":bool(before and after and before!=after),"driver_changed":pre["identity"].get("driver_version")!=post["identity"].get("driver_version"),
      "pre":pre,"post":post,"next_tests":["vram_full_scan_repeated","vram_bandwidth_verified","gpu_compute_verified","workload_llm","workload_sd15","workload_sdxl"],
      "diagnostic_rule":"Only reproducible data mismatch is hardware evidence; OOM, timeout and allocation failures are capacity evidence."}
def classify_statuses(statuses:list[str])->dict[str,Any]:
    normalized=[str(x).upper() for x in statuses];hardware=sum(x in HARDWARE_FAILURES for x in normalized);capacity=sum(any(token in x for token in CAPACITY_FAILURES) for x in normalized)
    reproduced=hardware>=2
    return {"classification":"REPRODUCIBLE_DATA_CORRUPTION" if reproduced else ("SINGLE_MISMATCH_NEEDS_REPEAT" if hardware else ("CAPACITY_LIMIT_NOT_HARDWARE_PROOF" if capacity else "NO_HARDWARE_EVIDENCE")),
      "hardware_evidence_runs":hardware,"capacity_events":capacity,"physical_defect_suspected":reproduced,"capacity_failure_is_hardware_proof":False}
