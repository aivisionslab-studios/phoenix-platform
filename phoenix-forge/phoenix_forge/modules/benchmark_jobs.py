from __future__ import annotations
import json,os,threading,uuid
from datetime import datetime,timezone
from typing import Any
from phoenix_forge.modules import baseline,benchmark,detect,gpu_safety,health,quality_gate
SCHEMA="phoenix.forge.benchmark-job/v1";HISTORY_SCHEMA="phoenix.forge.benchmark-history/v1"
_lock=threading.RLock();_jobs:dict[str,dict[str,Any]]={};_cancel:dict[str,threading.Event]={};_active_job_id:str|None=None
def _now()->str:return datetime.now(timezone.utc).isoformat()
def _history_path():return gpu_safety.state_dir()/"benchmark-history.jsonl"
def _public(job):return {k:v for k,v in job.items() if not k.startswith("_")}
def _append(job):
    path=_history_path();path.parent.mkdir(parents=True,exist_ok=True)
    with path.open("a",encoding="utf-8",newline="\n") as h:h.write(json.dumps(_public(job),ensure_ascii=False,separators=(",",":"))+"\n");h.flush();os.fsync(h.fileno())
def _run(job_id:str,limits:dict[str,float]):
    global _active_job_id
    with _lock:job=_jobs[job_id];job.update(status="RUNNING",started_at=_now());event=_cancel[job_id]
    def progress(value):
        with _lock:_jobs[job_id]["progress"]=value
    try:
        report=detect.collect();result=benchmark.suite(job["profile"],job["include_gpu"],limits,event,progress)
        machine_health=health.assess(report,benchmark=result);gate=quality_gate.benchmark_gate(result,machine_health)
        with _lock:job.update(status="CANCELLED" if result.get("cancelled") else "COMPLETED",finished_at=_now(),result=result,health=machine_health,quality_gate=gate,baseline_comparison=baseline.compare(report,result))
    except Exception as exc:
        with _lock:job.update(status="FAILED",finished_at=_now(),error=str(exc))
    finally:
        with _lock:
            _append(job)
            if _active_job_id==job_id:_active_job_id=None
def start(*,profile="quick",include_gpu=False,confirm_gpu_risk=False,cpu_temp_limit=90,gpu_temp_limit=90):
    global _active_job_id
    profile=str(profile).strip().lower()
    if profile not in benchmark.PROFILES:raise ValueError("Unknown benchmark profile")
    if include_gpu:
        safety=gpu_safety.status_for_detect(detect.collect())
        if safety.get("device_health") in {"DEGRADED","AI_COMPUTE_UNSAFE"} and not confirm_gpu_risk:raise PermissionError("GPU benchmark requires explicit confirmation while GPU health is degraded.")
    with _lock:
        if _active_job_id and _jobs.get(_active_job_id,{}).get("status") in {"QUEUED","RUNNING"}:raise RuntimeError(f"Benchmark already running: {_active_job_id}")
        job_id=str(uuid.uuid4());job={"schema":SCHEMA,"job_id":job_id,"created_at":_now(),"started_at":None,"finished_at":None,"status":"QUEUED","profile":profile,"include_gpu":bool(include_gpu),"progress":{"phase":"queued","percent":0},"result":None,"health":None,"quality_gate":None,"baseline_comparison":None,"error":None}
        _jobs[job_id]=job;_cancel[job_id]=threading.Event();_active_job_id=job_id
        threading.Thread(target=_run,args=(job_id,{"cpu_temperature":cpu_temp_limit,"gpu_temperature":gpu_temp_limit}),daemon=True).start();return _public(job)
def status(job_id):
    with _lock:
        if job_id not in _jobs:raise KeyError(job_id)
        return _public(_jobs[job_id])
def cancel(job_id):
    with _lock:
        if job_id not in _jobs:raise KeyError(job_id)
        if _jobs[job_id]["status"] in {"QUEUED","RUNNING"}:_cancel[job_id].set();_jobs[job_id]["progress"]={"phase":"cancelling","percent":_jobs[job_id].get("progress",{}).get("percent",0)}
        return _public(_jobs[job_id])
def recent(limit=20):
    try:lines=_history_path().read_text(encoding="utf-8").splitlines()
    except OSError:lines=[]
    entries=[]
    for line in lines[-max(1,min(int(limit),200)):]:
        try:
            value=json.loads(line)
            if isinstance(value,dict):entries.append(value)
        except json.JSONDecodeError:continue
    return {"schema":HISTORY_SCHEMA,"count":len(entries),"entries":entries}
