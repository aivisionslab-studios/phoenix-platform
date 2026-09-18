from __future__ import annotations

import json, os, time, uuid
from pathlib import Path
from typing import Any

from phoenix_forge.models import StressResult
from phoenix_forge.modules import crucible, memory, storage, gpu_safety, compute_fabric

SCHEMA = "phoenix.forge.stress-correctness/v1"
RUN_SCHEMA = "phoenix.forge.stress-correctness-run/v1"

PASS_STATES = {"PASS", "QUICK_PASS", "FULL_SCAN_PASS"}
CAPACITY_STATES = {"OOM","OUT_OF_MEMORY","OUTOFDEVICEMEMORY","ALLOCATION_FAILED","BUDGET_EXHAUSTED","NATIVE_HELPER_MISSING"}
TIMEOUT_STATES = {"TIMEOUT"}
CORRUPTION_STATES = {"MEMORY_ERROR","DATA_MISMATCH","COMPUTE_MISMATCH"}
INSTABILITY_STATES = {"DEVICE_LOST","DRIVER_ERROR","NATIVE_ERROR","SAFETY_ABORT","CRASH","PROCESS_EXIT"}

def _now()->float: return time.time()
def _state_dir()->Path:
    base=os.environ.get("PHOENIX_FORGE_STATE_DIR")
    if base:return Path(base)
    if os.name=="nt":return Path(os.environ.get("LOCALAPPDATA") or Path.home()/"AppData"/"Local")/"Phoenix"/"Forge"/"state"
    return Path(os.environ.get("XDG_STATE_HOME") or Path.home()/".local"/"state")/"phoenix"/"forge"
def _journal()->Path:return _state_dir()/"stress-correctness.jsonl"
def _status(result:StressResult|dict[str,Any])->str:
    if isinstance(result,StressResult):
        return str((result.metrics or {}).get("status") or ("PASS" if result.passed else "UNKNOWN")).upper()
    metrics=result.get("metrics") if isinstance(result,dict) else None
    return str((metrics or {}).get("status") or result.get("status") or ("PASS" if result.get("passed") else "UNKNOWN")).upper()
def classify_status(status:str)->dict[str,Any]:
    s=str(status or "UNKNOWN").upper()
    if s in PASS_STATES:return {"class":"PASS","severity":"NONE","hardware_proof":False,"repeat_required":False}
    if s in CORRUPTION_STATES:return {"class":"CORRUPTION","severity":"HIGH","hardware_proof":False,"repeat_required":True}
    if s in CAPACITY_STATES:return {"class":"CAPACITY","severity":"INFO","hardware_proof":False,"repeat_required":False}
    if s in TIMEOUT_STATES:return {"class":"CAPACITY_OR_INSTABILITY","severity":"LOW","hardware_proof":False,"repeat_required":True}
    if s in INSTABILITY_STATES:return {"class":"INSTABILITY","severity":"MEDIUM","hardware_proof":False,"repeat_required":True}
    return {"class":"UNKNOWN","severity":"LOW","hardware_proof":False,"repeat_required":True}
def classify_result(result:StressResult|dict[str,Any],*,domain:str|None=None,device_key:str|None=None)->dict[str,Any]:
    s=_status(result); base=classify_status(s)
    raw=result.model_dump() if isinstance(result,StressResult) else dict(result)
    return {"schema":RUN_SCHEMA,"observed_at":_now(),"domain":domain or raw.get("module") or "unknown","device_key":device_key,
            "status":s,**base,"passed":bool(raw.get("passed",s in PASS_STATES)),"duration_s":raw.get("duration_s"),
            "metrics":raw.get("metrics") or {},"warnings":raw.get("warnings") or []}
def analyze_runs(runs:list[dict[str,Any]])->dict[str,Any]:
    normalized=[classify_result(x,domain=x.get("domain"),device_key=x.get("device_key")) if x.get("schema")!=RUN_SCHEMA else x for x in runs]
    corruption=[x for x in normalized if x.get("class")=="CORRUPTION"]
    instability=[x for x in normalized if x.get("class") in {"INSTABILITY","CAPACITY_OR_INSTABILITY"}]
    capacity=[x for x in normalized if x.get("class")=="CAPACITY"]
    passed=[x for x in normalized if x.get("class")=="PASS"]
    # Hardware suspicion requires repeatable corruption in the same domain/device scope.
    groups={}
    for x in corruption:
        key=(x.get("domain"),x.get("device_key"))
        groups[key]=groups.get(key,0)+1
    reproducible=[{"domain":k[0],"device_key":k[1],"count":v} for k,v in groups.items() if v>=2]
    if reproducible: verdict="REPRODUCIBLE_CORRUPTION"
    elif corruption: verdict="CORRUPTION_NEEDS_REPEAT"
    elif instability: verdict="INSTABILITY_NEEDS_CORRELATION"
    elif capacity: verdict="CAPACITY_LIMIT_ONLY"
    elif normalized and len(passed)==len(normalized): verdict="PASS_NO_CORRUPTION_OBSERVED"
    else: verdict="INCONCLUSIVE"
    return {"schema":SCHEMA,"status":"ANALYZED","verdict":verdict,"runs":len(normalized),"pass_runs":len(passed),
            "capacity_events":len(capacity),"instability_events":len(instability),"corruption_events":len(corruption),
            "reproducible_corruption":reproducible,"physical_defect_suspected":bool(reproducible),
            "policy":{"oom_is_hardware_proof":False,"timeout_is_hardware_proof":False,"single_mismatch_is_hardware_proof":False,
                      "repeated_same_scope_corruption_required":True,"gpu_identity_uses_device_key":True},"evidence":normalized}
def capabilities()->dict[str,Any]:
    return {"schema":SCHEMA,"status":"READY","domains":["cpu","ram","vram","gpu_compute","storage"],
            "classes":["PASS","CAPACITY","CAPACITY_OR_INSTABILITY","INSTABILITY","CORRUPTION","UNKNOWN"],
            "policy":{"bounded_tests":True,"non_destructive_storage_tempfile":True,"corruption_requires_reproduction":True,
                      "oom_timeout_not_physical_defect":True,"device_index_is_operational_not_identity":True}}
def _append(row:dict[str,Any])->None:
    p=_journal();p.parent.mkdir(parents=True,exist_ok=True)
    with p.open("a",encoding="utf-8",newline="\n") as f:f.write(json.dumps(row,ensure_ascii=False,separators=(",",":"))+"\n")
def history(limit:int=100)->dict[str,Any]:
    try: lines=_journal().read_text(encoding="utf-8").splitlines()
    except OSError: lines=[]
    rows=[]
    for line in lines[-max(1,min(int(limit),500)):]:
        try: rows.append(json.loads(line))
        except Exception: pass
    return {"schema":SCHEMA,"count":len(rows),"entries":rows}
def run(domain:str,*,seconds:int=10,mb:int=256,passes:int=2,device:int=0,rounds:int=64,directory:str|None=None,full_scan:bool=False)->dict[str,Any]:
    domain=domain.strip().lower(); device_key=None
    if domain=="cpu": result=crucible.cpu_stress(seconds)
    elif domain=="ram": result=memory.ram_test(mb,passes)
    elif domain=="vram": result=memory.native_vram_test(mb,passes,full_scan=full_scan,device=device)
    elif domain=="gpu_compute": result=crucible.gpu_compute_stress(seconds,mb,rounds,device=device)
    elif domain=="storage": result=storage.sequential_bench(mb,max(1,min(4,mb)),directory)
    else: raise ValueError("domain must be cpu, ram, vram, gpu_compute or storage")
    if domain in {"vram","gpu_compute"}:
        try:
            from phoenix_forge.modules import detect
            d=detect.collect(); gpu=d.gpus[device] if 0<=device<len(d.gpus) else None
            if gpu: device_key=gpu.device_key or compute_fabric.stable_device_key(gpu)
        except Exception: pass
    row=classify_result(result,domain=domain,device_key=device_key)
    row["run_id"]=str(uuid.uuid4()); _append(row); return row
