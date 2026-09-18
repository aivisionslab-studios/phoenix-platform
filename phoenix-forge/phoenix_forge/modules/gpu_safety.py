from __future__ import annotations
import hashlib, json, os, re, tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from phoenix_forge.models import DetectReport, GPUInfo, StressResult

SCHEMA="phoenix.forge.gpu-safety/v2"
EVENT_SCHEMA="phoenix.hardware.event/v1"
AI_DOMAINS={"llm","image","ocr","vision","embedding","audio","video_ai"}
HARDWARE_FAILURES={"MEMORY_ERROR","DRIVER_ERROR","DEVICE_LOST","DATA_MISMATCH","COMPUTE_MISMATCH"}
INCONCLUSIVE={"TIMEOUT","ALLOCATION_FAILED","BUDGET_EXHAUSTED","NATIVE_HELPER_MISSING","OUT_OF_MEMORY"}

def _now()->str:return datetime.now(timezone.utc).isoformat()
def _slug(v:str)->str:return re.sub(r"[^a-z0-9]+","-",v.lower()).strip("-") or "unknown"
def _id_part(raw:dict[str,Any],field:str,pattern:str,pnp:str)->str|None:
    value=raw.get(field)
    if value:return str(value).upper().replace("0X","")
    match=re.search(pattern,pnp,re.I)
    return match.group(1).upper() if match else None
def state_dir()->Path:
    if os.environ.get("PHOENIX_FORGE_STATE_DIR"):return Path(os.environ["PHOENIX_FORGE_STATE_DIR"])
    if os.name=="nt":return Path(os.environ.get("LOCALAPPDATA") or Path.home()/"AppData"/"Local")/"Phoenix"/"Forge"/"state"
    return Path(os.environ.get("XDG_STATE_HOME") or Path.home()/".local"/"state")/"phoenix"/"forge"

def gpu_identity(gpu:GPUInfo|dict[str,Any]|None=None,device_name:str|None=None)->dict[str,Any]:
    raw=gpu.model_dump() if hasattr(gpu,"model_dump") else dict(gpu or {})
    pnp=str(raw.get("pnp_device_id") or "").upper();name=str(raw.get("name") or device_name or "Unknown GPU")
    vendor=_id_part(raw,"vendor_id",r"VEN_([0-9A-F]{4})",pnp)
    device=_id_part(raw,"device_id",r"DEV_([0-9A-F]{4})",pnp)
    details="|".join(str(raw.get(x) or "") for x in ("vendor_id","device_id","subsystem_vendor_id","subsystem_device_id","revision_id"))
    fingerprint=pnp or (details if details.replace("|","") else name)
    digest=hashlib.sha256(fingerprint.encode("utf-8")).hexdigest()[:16]
    prefix=f"pci-{vendor or 'unknown'}-{device or 'unknown'}" if pnp or vendor or device else f"gpu-{_slug(name)[:40]}"
    return {"key":f"{prefix.lower()}-{digest}","name_key":_slug(name),"name":name,
      "pnp_device_id":pnp or None,"vendor_id":vendor,"device_id":device,
      "subsystem_vendor_id":raw.get("subsystem_vendor_id"),"subsystem_device_id":raw.get("subsystem_device_id"),
      "revision_id":raw.get("revision_id"),"driver_version":raw.get("driver_version")}

def _empty()->dict[str,Any]:return {"schema":SCHEMA,"updated_at":_now(),"devices":{}}
def _merge_devices(left:dict[str,Any],right:dict[str,Any])->dict[str,Any]:
    merged={**left,**right}
    merged["identity"]={**left.get("identity",{}),**{k:v for k,v in right.get("identity",{}).items() if v}}
    merged["observations"]=(left.get("observations",[])+right.get("observations",[]))[-200:]
    merged["authorizations"]={**left.get("authorizations",{}),**right.get("authorizations",{})}
    merged["scope_failures"]={**left.get("scope_failures",{}),**right.get("scope_failures",{})}
    merged["failure_count"]=max(int(left.get("failure_count",0)),int(right.get("failure_count",0)))
    merged["diagnostic_required"]=bool(left.get("diagnostic_required") or right.get("diagnostic_required"))
    merged["global_ai_blocked"]=bool(left.get("global_ai_blocked") or right.get("global_ai_blocked"))
    return merged
def _migrate(data:dict[str,Any])->dict[str,Any]:
    if data.get("schema") not in {SCHEMA,"phoenix.forge.gpu-safety/v1"}:return _empty()
    if data.get("schema")!="phoenix.forge.gpu-safety/v2":
        for d in data.get("devices",{}).values():
            old=bool(d.pop("latched",False));d["device_health"]="DEGRADED" if old else d.get("health","UNVERIFIED")
            d.update({"diagnostic_required":old,"global_ai_blocked":False,"authorizations":{},"scope_failures":{}})
            d.pop("required_runtime_mode",None);d.pop("user_alert",None)
    migrated:dict[str,Any]={}
    for old_key,d in data.get("devices",{}).items():
        ident=gpu_identity(d.get("identity",{}));new_key=ident["key"]
        d["identity"]={**d.get("identity",{}),**{k:v for k,v in ident.items() if v}}
        d.setdefault("identity_history",[])
        if old_key!=new_key and old_key not in d["identity_history"]:d["identity_history"].append(old_key)
        migrated[new_key]=_merge_devices(migrated[new_key],d) if new_key in migrated else d
    data["devices"]=migrated;data["schema"]=SCHEMA;return data
def load()->dict[str,Any]:
    try:
        path=state_dir()/"gpu-safety.json";raw=json.loads(path.read_text(encoding="utf-8"));before=json.dumps(raw,sort_keys=True)
        data=_migrate(raw)
        if json.dumps(data,sort_keys=True)!=before:_write(data)
        return data
    except (OSError,ValueError,TypeError):return _empty()
def _write(data:dict[str,Any])->None:
    path=state_dir()/"gpu-safety.json";path.parent.mkdir(parents=True,exist_ok=True)
    fd,tmp=tempfile.mkstemp(prefix=path.name+".",suffix=".tmp",dir=path.parent)
    try:
        with os.fdopen(fd,"w",encoding="utf-8",newline="\n") as h:
            json.dump(data,h,indent=2,ensure_ascii=False);h.write("\n");h.flush();os.fsync(h.fileno())
        os.replace(tmp,path)
    finally:
        try:os.unlink(tmp)
        except FileNotFoundError:pass
def _event(payload:dict[str,Any])->None:
    path=state_dir()/"hardware-events.jsonl";path.parent.mkdir(parents=True,exist_ok=True)
    with path.open("a",encoding="utf-8",newline="\n") as h:
        h.write(json.dumps(payload,ensure_ascii=False,separators=(",",":"))+"\n");h.flush();os.fsync(h.fileno())
def _match(devices:dict[str,Any],ident:dict[str,Any])->tuple[str,dict[str,Any]|None]:
    if ident["key"] in devices:return ident["key"],devices[ident["key"]]
    if ident.get("pnp_device_id"):
        for k,d in devices.items():
            if d.get("identity",{}).get("pnp_device_id")==ident["pnp_device_id"]:return k,d
        return ident["key"],None
    matches=[(k,d) for k,d in devices.items() if d.get("identity",{}).get("name_key")==ident["name_key"]]
    if len(matches)==1:return matches[0]
    return ident["key"],None
def _device(data:dict[str,Any],ident:dict[str,Any])->tuple[str,dict[str,Any]]:
    key,d=_match(data["devices"],ident)
    d=d or {"identity":ident,"device_health":"UNVERIFIED","diagnostic_required":False,"global_ai_blocked":False,
      "authorizations":{},"scope_failures":{},"observations":[],"failure_count":0}
    d["identity"]={**d.get("identity",{}),**{k:v for k,v in ident.items() if v}}
    return key,d
def scope_key(workload:str,backend:str="vulkan",runtime:str="*",model:str="*")->str:
    return ".".join(map(_slug,(workload,backend,runtime,model)))

def _alert(d:dict[str,Any],workload:str|None=None)->dict[str,Any]|None:
    if d.get("global_ai_blocked"):return {"severity":"critical","code":"GPU_AI_INFERENCE_BLOCKED",
      "title":"GPU bloqueada para inferência de IA",
      "message":"A GPU falhou em múltiplos tipos de inferência. Todas as cargas de IA foram transferidas para CPU. A saída de vídeo pode continuar funcionando.",
      "action":"Execute o diagnóstico profundo do Phoenix Forge antes de reativar inferência na GPU."}
    if workload and any(k.startswith(_slug(workload)+".") and v.get("state")=="BLOCKED" for k,v in d.get("authorizations",{}).items()):
        return {"severity":"error","code":"GPU_WORKLOAD_BLOCKED","title":f"GPU bloqueada para {workload}",
          "message":f"Resultados inválidos foram reproduzidos em {workload}; esse workload será executado em CPU.",
          "action":"Outras funções da GPU permanecem independentes e serão validadas separadamente."}
    if d.get("diagnostic_required"):return {"severity":"warning","code":"GPU_DEGRADED","title":"GPU requer diagnóstico",
      "message":"Há evidências de instabilidade de GPU/VRAM. Workloads ainda autorizados permanecem monitorados.",
      "action":"Execute VRAM map, compute correctness e validação de entrega."}
    return None


def record_runtime_failure(*, workload:str, backend:str, runtime:str="*", model:str="*",
  failure_class:str, evidence:dict[str,Any]|None=None, gpu:GPUInfo|dict[str,Any]|None=None)->dict[str,Any]:
    """Persist runtime/hardware failure evidence without conflating capacity with corruption.

    Capacity/transient failures are evidence and may force this execution to CPU, but do
    not condemn hardware. Hardware-class failures mark the device DEGRADED and require
    diagnostics; persistent/reproduced scope blocking remains owned by
    record_output_failure() after a CPU control succeeds.
    """
    reason=str(failure_class or "RUNTIME_ERROR").upper()
    ident=gpu_identity(gpu,(evidence or {}).get("device_name"));data=load();key,d=_device(data,ident)
    scope=scope_key(workload,backend,runtime,model)
    hardware=reason in HARDWARE_FAILURES
    inconclusive=reason in INCONCLUSIVE or reason in {"RUNTIME_UNAVAILABLE","RUNTIME_ERROR","RUNTIME_CRASH"}
    obs={"observed_at":_now(),"kind":"runtime_failure","scope":scope,"workload":_slug(workload),
      "backend":_slug(backend),"runtime":runtime,"model":model,"reason":reason,
      "hardware_failure":hardware,"inconclusive":inconclusive,"evidence":evidence or {}}
    d["observations"]=(d.get("observations",[])+[obs])[-200:]
    if hardware:
        d["diagnostic_required"]=True
        if d.get("device_health") not in {"AI_COMPUTE_UNSAFE"}:d["device_health"]="DEGRADED"
    data["devices"][key]=d;data["updated_at"]=_now();_write(data)
    _event({"schema":EVENT_SCHEMA,"event_id":f"runtime-fault-{ident['key']}-{int(datetime.now().timestamp()*1000)}",
      "occurred_at":_now(),"type":"runtime.gpu.failure","severity":"error" if hardware else "warning",
      "source":"phoenix-forge","device":d["identity"],"scope":scope,"reason":reason,
      "hardware_condemned":False,"diagnostic_required":bool(d.get("diagnostic_required")),
      "recommended_fallback":"CPU","evidence":evidence or {}})
    return status_for_gpu(ident,workload=workload,backend=backend,runtime=runtime,model=model)

def record_output_failure(*,workload:str,backend:str,runtime:str="*",model:str="*",reason:str,
  evidence:dict[str,Any]|None=None,gpu:GPUInfo|dict[str,Any]|None=None,cpu_control_passed:bool=False,
  reproduced:bool=False)->dict[str,Any]:
    ident=gpu_identity(gpu,(evidence or {}).get("device_name"));data=load();key,d=_device(data,ident)
    scope=scope_key(workload,backend,runtime,model);count=int(d["scope_failures"].get(scope,0))+1;d["scope_failures"][scope]=count
    confirmed=bool(cpu_control_passed and (reproduced or count>=2))
    obs={"observed_at":_now(),"kind":"output_validation","scope":scope,"workload":_slug(workload),"backend":_slug(backend),
      "runtime":runtime,"model":model,"reason":reason,"cpu_control_passed":cpu_control_passed,
      "reproduced":reproduced,"confirmed_gpu_failure":confirmed,"evidence":evidence or {}}
    d["observations"]=(d.get("observations",[])+[obs])[-200:]
    if confirmed:
        d["authorizations"][scope]={"state":"BLOCKED","fallback":"CPU","reason":reason,"updated_at":_now()}
        d["device_health"]="DEGRADED";d["failure_count"]=int(d.get("failure_count",0))+1
        domains={k.split(".",1)[0] for k,v in d["authorizations"].items() if v.get("state")=="BLOCKED" and k.split(".",1)[0] in AI_DOMAINS}
        if len(domains)>=2:d["global_ai_blocked"]=True;d["device_health"]="AI_COMPUTE_UNSAFE"
        _event({"schema":EVENT_SCHEMA,"event_id":f"output-fault-{ident['key']}-{int(datetime.now().timestamp()*1000)}",
          "occurred_at":_now(),"type":"hardware.gpu.output_failure","severity":"critical" if d["global_ai_blocked"] else "error",
          "source":"phoenix-forge","device":d["identity"],"scope":scope,"reason":reason,"required_runtime_mode":"CPU",
          "global_ai_blocked":d["global_ai_blocked"],"evidence":evidence or {}})
    data["devices"][key]=d;data["updated_at"]=_now();_write(data)
    return status_for_gpu(ident,workload=workload,backend=backend,runtime=runtime,model=model)

def record_result(result:StressResult,gpu:GPUInfo|dict[str,Any]|None=None)->StressResult:
    status=str(result.metrics.get("status") or ("PASS" if result.passed else "UNKNOWN")).upper()
    ident=gpu_identity(gpu,result.metrics.get("device_name"));data=load();key,d=_device(data,ident)
    evidence={k:result.metrics[k] for k in ("target_mb","validated_mb","sample_errors","full_scan","address_coverage_percent","error_details","error","external_tool","evidence","correctness_verified","mode","dispatches","verification_samples","bandwidth_gbps","report_sha256","report_content_sha256","source_encoding","external_evidence_id") if k in result.metrics}
    d["observations"]=(d.get("observations",[])+[{"observed_at":_now(),"kind":"hardware_test","module":result.module,
      "status":status,"passed":result.passed,"evidence":evidence}])[-200:]
    if status in HARDWARE_FAILURES:
        d["device_health"]="DEGRADED";d["diagnostic_required"]=True;d["failure_count"]=int(d.get("failure_count",0))+1
        _event({"schema":EVENT_SCHEMA,"event_id":f"gpu-hw-{ident['key']}-{int(datetime.now().timestamp()*1000)}",
          "occurred_at":_now(),"type":"hardware.gpu.diagnostic_required","severity":"critical","source":"phoenix-forge",
          "device":d["identity"],"status":status,"evidence":evidence})
    elif status not in INCONCLUSIVE and not d.get("diagnostic_required"):d["device_health"]="OBSERVED_OK" if result.passed else "SUSPECT"
    data["devices"][key]=d;data["updated_at"]=_now();_write(data);return result

def status_for_gpu(gpu_or_ident:GPUInfo|dict[str,Any]|None,*,workload:str|None=None,backend:str="vulkan",
  runtime:str="*",model:str="*")->dict[str,Any]:
    ident=gpu_or_ident if isinstance(gpu_or_ident,dict) and "key" in gpu_or_ident else gpu_identity(gpu_or_ident)
    _,d=_match(load()["devices"],ident)
    d=d or {"identity":ident,"device_health":"UNVERIFIED","diagnostic_required":False,"global_ai_blocked":False,
      "authorizations":{},"scope_failures":{},"failure_count":0}
    auth={"state":"ALLOWED_MONITORED" if d.get("diagnostic_required") else "ALLOWED","effective_mode":"GPU","reason":None}
    if d.get("global_ai_blocked") and (not workload or _slug(workload) in AI_DOMAINS):
        auth={"state":"BLOCKED","effective_mode":"CPU","reason":"multiple_gpu_output_domains_failed"}
    elif workload:
        keys=[scope_key(workload,backend,runtime,model),scope_key(workload,backend,"*","*"),scope_key(workload,"*","*","*")]
        rule=next((d.get("authorizations",{}).get(k) for k in keys if d.get("authorizations",{}).get(k)),None)
        if rule and rule.get("state")=="BLOCKED":auth={"state":"BLOCKED","effective_mode":"CPU","reason":rule.get("reason")}
    return {"schema":SCHEMA,"device":d.get("identity",ident),"device_health":d.get("device_health","UNVERIFIED"),
      "diagnostic_required":bool(d.get("diagnostic_required")),"global_ai_blocked":bool(d.get("global_ai_blocked")),
      "failure_count":d.get("failure_count",0),"authorizations":d.get("authorizations",{}),
      "scope_failures":d.get("scope_failures",{}),"authorization":auth,"alert":_alert(d,workload)}
def status_for_detect(report:DetectReport,**scope:Any)->dict[str,Any]:
    if not report.gpus:return {"schema":SCHEMA,"device_health":"NO_GPU","global_ai_blocked":True,
      "authorization":{"state":"BLOCKED","effective_mode":"CPU","reason":"no_gpu"},"alert":None}
    return status_for_gpu(report.gpus[0],**scope)
def authorize(gpu:GPUInfo|dict[str,Any]|None,**scope:Any)->dict[str,Any]:return status_for_gpu(gpu,**scope)["authorization"]

def record_external_fault(kind:str,message:str,gpu:GPUInfo|dict[str,Any]|None=None,evidence:dict[str,Any]|None=None,
  workload:str="llm",backend:str="vulkan",runtime:str="*",model:str="*",cpu_control_passed:bool=True,
  reproduced:bool=True)->dict[str,Any]:
    status=kind.strip().upper().replace("-","_")
    if status in HARDWARE_FAILURES:
        record_result(StressResult(module="Phoenix Runtime / External GPU Fault",passed=False,duration_s=0,
          metrics={"status":status,"error":message,**(evidence or {})}),gpu)
    return record_output_failure(workload=workload,backend=backend,runtime=runtime,model=model,reason=status,
      evidence={"message":message,**(evidence or {})},gpu=gpu,cpu_control_passed=cpu_control_passed,reproduced=reproduced)
