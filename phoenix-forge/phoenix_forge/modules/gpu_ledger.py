from __future__ import annotations
import hashlib,json
from pathlib import Path
from typing import Any
from phoenix_forge.models import GPUInfo,StressResult
from phoenix_forge.modules import gpu_safety,workload_state

SCHEMA="phoenix.forge.gpu-health-ledger/v1"
PASS_STATES={"PASS","FULL_SCAN_PASS","QUICK_PASS"}
FAIL_STATES={"MEMORY_ERROR","DRIVER_ERROR","DEVICE_LOST","DATA_MISMATCH","COMPUTE_MISMATCH"}
SETUP_STATES={"NATIVE_ERROR","NATIVE_HELPER_MISSING"}

def _device_by_name(name:str|None=None)->dict[str,Any]|None:
    devices=gpu_safety.load().get("devices",{})
    if not devices:return None
    if name:
        needle=name.casefold()
        for device in devices.values():
            if needle in str(device.get("identity",{}).get("name","")).casefold():return device
        return None
    return next(iter(devices.values()))

def summarize(device_name:str|None=None)->dict[str,Any]:
    device=_device_by_name(device_name)
    if not device:return {"schema":SCHEMA,"classification":"UNVERIFIED","tests":{},"trust_matrix":{},"device":None}
    observations=device.get("observations",[]);tests=[x for x in observations if x.get("kind")=="hardware_test"]
    statuses=[str(x.get("status","UNKNOWN")).upper() for x in tests]
    def external(x:dict[str,Any])->bool:return str(x.get("module","")).startswith("External /") or bool(x.get("evidence",{}).get("external_tool"))
    memory_tests=[x for x in tests if str(x.get("status","")).upper()=="MEMORY_ERROR"]
    phoenix_memory=sum(not external(x) for x in memory_tests);external_memory=sum(external(x) for x in memory_tests)
    memory_failures=phoenix_memory+external_memory
    compute_mismatches=sum(x=="COMPUTE_MISMATCH" for x in statuses)
    passes=sum(x in PASS_STATES for x in statuses)
    setup_errors=sum(x in SETUP_STATES for x in statuses)
    full_scan_passes=sum(x=="FULL_SCAN_PASS" for x in statuses)
    compute=[x for x in tests if "GPU Compute" in str(x.get("module","")) and str(x.get("status","")).upper()=="PASS"]
    compute_correct=sum(bool(x.get("evidence",{}).get("correctness_verified")) for x in compute)
    compute_operational=len(compute)-compute_correct
    if device.get("global_ai_blocked"):classification="AI_COMPUTE_UNSAFE"
    elif memory_failures and passes:classification="VRAM_INTERMITTENT_SUSPECTED"
    elif memory_failures:classification="VRAM_UNSTABLE_SUSPECTED"
    elif compute_mismatches:classification="GPU_COMPUTE_UNRELIABLE"
    elif tests and passes==len(tests):classification="OBSERVED_OK_NOT_CERTIFIED"
    else:classification=device.get("device_health","UNVERIFIED")
    diagnostic=bool(device.get("diagnostic_required") or memory_failures or compute_mismatches)
    reason="historical_vram_failure" if diagnostic else "no_latched_hardware_failure"
    def rule(mode:str,state:str,validation:str)->dict[str,str]:return {"mode":mode,"state":state,"validation":validation,"policy_source":"GPU_HEALTH_LEDGER","reason":reason}
    matrix={
      "llm":rule("CPU" if diagnostic else "GPU","RESTRICTED" if diagnostic else "ALLOWED","TEXT_GATE"),
      "image":rule("GPU_MONITORED" if diagnostic else "GPU","CONDITIONAL" if diagnostic else "ALLOWED","OCR_VISION_GATE"),
      "ocr":rule("CPU" if diagnostic else "GPU","RESTRICTED" if diagnostic else "ALLOWED","REFERENCE_TEXT"),
      "vision":rule("CPU" if diagnostic else "GPU","RESTRICTED" if diagnostic else "ALLOWED","CPU_CONTROL"),
      "video_ai":rule("GPU_MONITORED" if diagnostic else "GPU","CONDITIONAL" if diagnostic else "ALLOWED","FRAME_SAMPLING")}
    return {"schema":SCHEMA,"device":device.get("identity"),"classification":classification,
      "diagnostic_required":diagnostic,"historical_failure_latched":bool(memory_failures or compute_mismatches),
      "tests":{"total":len(tests),"hardware_evidence_total":len(tests)-setup_errors,"passes":passes,
        "memory_error_runs":memory_failures,"phoenix_memory_error_runs":phoenix_memory,
        "external_memory_error_runs":external_memory,"full_scan_passes":full_scan_passes,
        "compute_operational_passes":compute_operational,"compute_correctness_passes":compute_correct,
        "compute_mismatch_runs":compute_mismatches,"setup_errors":setup_errors,"statuses":statuses},"trust_matrix":matrix,
      "authorizations":device.get("authorizations",{}),"last_observations":observations[-20:]}

def decode_report(payload:bytes)->tuple[dict[str,Any],str]:
    if payload.startswith((b"\xff\xfe",b"\xfe\xff")):candidates=["utf-16"]
    elif payload.startswith(b"\xef\xbb\xbf"):candidates=["utf-8-sig"]
    else:candidates=["utf-8-sig","utf-16-le","utf-16-be"]
    errors=[]
    for encoding in candidates:
        try:
            text=payload.decode(encoding).strip();return json.loads(text),encoding
        except (UnicodeError,json.JSONDecodeError) as exc:errors.append(f"{encoding}: {exc}")
    raise ValueError("JSON report could not be decoded ("+"; ".join(errors)+")")

def ingest_report(path:str,device_name:str|None=None)->dict[str,Any]:
    source=Path(path);payload=source.read_bytes();raw,encoding=decode_report(payload)
    canonical=json.dumps(raw,ensure_ascii=False,sort_keys=True,separators=(",",":")).encode("utf-8")
    digest=hashlib.sha256(canonical).hexdigest();metrics=dict(raw.get("metrics",raw))
    module=str(raw.get("module") or "Phoenix Forge / Imported Report")
    status=str(metrics.get("status") or ("PASS" if raw.get("passed") else "UNKNOWN")).upper()
    passed=bool(raw.get("passed",metrics.get("passed",status in PASS_STATES)))
    gpu=GPUInfo(name=device_name or metrics.get("device_name") or "Unknown GPU")
    existing=_device_by_name(gpu.name)
    if existing and any(digest in {x.get("evidence",{}).get("report_sha256"),x.get("evidence",{}).get("report_content_sha256")} for x in existing.get("observations",[])):
        return {**summarize(gpu.name),"ingest":"DUPLICATE_SKIPPED","report_sha256":digest}
    metrics.update({"report_sha256":digest,"report_content_sha256":digest,"source_encoding":encoding})
    gpu_safety.record_result(StressResult(module=module,passed=passed,
      duration_s=float(raw.get("duration_s") or metrics.get("duration_s") or 0),metrics=metrics),gpu)
    return {**summarize(gpu.name),"ingest":"RECORDED","report_sha256":digest}

def record_external(*,device_name:str,tool:str,status:str,error_count:int=0,evidence:str|None=None)->dict[str,Any]:
    normalized=status.upper();failed=error_count>0 or normalized in FAIL_STATES or normalized in {"FAILED","ERROR"}
    fingerprint=hashlib.sha256(json.dumps([device_name,tool,normalized,error_count,evidence],ensure_ascii=False).encode()).hexdigest()
    existing=_device_by_name(device_name)
    if existing and any(x.get("evidence",{}).get("external_evidence_id")==fingerprint for x in existing.get("observations",[])):
        return {**summarize(device_name),"ingest":"DUPLICATE_SKIPPED","external_evidence_id":fingerprint}
    metrics={"status":"MEMORY_ERROR" if failed and "MEM" in normalized else ("DATA_MISMATCH" if failed else "PASS"),
      "device_name":device_name,"external_tool":tool,"sample_errors":error_count,"evidence":evidence,"external_evidence_id":fingerprint}
    gpu_safety.record_result(StressResult(module=f"External / {tool}",passed=not failed,duration_s=0,metrics=metrics),GPUInfo(name=device_name))
    return {**summarize(device_name),"ingest":"RECORDED","external_evidence_id":fingerprint}

def route(workload:str,*,device_name:str|None=None,user_mode:str="AUTO",backend:str="vulkan",
          runtime:str="*",model:str="*")->dict[str,Any]:
    report=summarize(device_name);rule=report.get("trust_matrix",{}).get(workload,{"mode":"AUTO","state":"UNKNOWN","validation":"REQUIRED"})
    device=_device_by_name(device_name)
    scoped=gpu_safety.status_for_gpu(device.get("identity") if device else None,workload=workload,
      backend=backend,runtime=runtime,model=model)["authorization"] if device else None
    requested=user_mode.upper();effective=rule["mode"] if requested=="AUTO" else requested
    overridden=False
    if scoped and scoped.get("state")=="BLOCKED":effective="CPU";overridden=requested!="CPU"
    elif requested in {"GPU","HYBRID"} and rule["state"]=="RESTRICTED":effective="CPU";overridden=True
    result={"schema":"phoenix.forge.execution-route/v1","workload":workload,"requested_mode":requested,
      "effective_mode":effective,"safety_override":overridden,"rule":rule,"classification":report["classification"],
      "scoped_authorization":scoped,"notify_user":overridden or rule["state"] in {"RESTRICTED","CONDITIONAL"}}
    result["workload_state"]=workload_state.observe_route(result)
    return result
