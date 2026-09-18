from __future__ import annotations
from typing import Any
from phoenix_forge.models import DetectReport,StressResult
from phoenix_forge.modules import gpu_safety

RANK={"HEALTHY":0,"UNVERIFIED":1,"WARNING":2,"DEGRADED":3,"UNSAFE":4}
def _worst(states:list[str])->str:return max(states,key=lambda x:RANK.get(x,2)) if states else "UNVERIFIED"
def _tests_for(tests:list[StressResult],tokens:tuple[str,...])->list[StressResult]:
    return [t for t in tests if any(x in t.module.upper() for x in tokens)]
def _subsystem(tests:list[StressResult],tokens:tuple[str,...])->dict[str,Any]:
    rows=_tests_for(tests,tokens)
    if not rows:return {"health":"UNVERIFIED","tests":0,"passed":0,"failures":[]}
    failures=[{"module":t.module,"status":str(t.metrics.get("status") or "FAILED")} for t in rows if not t.passed]
    hard=[x for x in failures if x["status"].upper() not in gpu_safety.INCONCLUSIVE]
    return {"health":"DEGRADED" if hard else ("WARNING" if failures else "HEALTHY"),"tests":len(rows),
      "passed":sum(t.passed for t in rows),"failures":failures}
def assess(detect:DetectReport,tests:list[StressResult]|None=None,benchmark:dict[str,Any]|None=None)->dict[str,Any]:
    tests=list(tests or [])
    if benchmark:
        for row in benchmark.get('benchmarks',[]):
            try:tests.append(StressResult.model_validate(row.get('result',{})))
            except Exception:pass
    gpu_state=gpu_safety.status_for_detect(detect)
    cpu=_subsystem(tests,("CPU",));ram=_subsystem(tests,("RAM","MEMORY COPY"));storage=_subsystem(tests,("STORAGE",))
    gpu=_subsystem(tests,("GPU","VRAM"))
    if gpu_state.get("global_ai_blocked"):gpu["health"]="UNSAFE"
    elif gpu_state.get("diagnostic_required") and RANK[gpu["health"]]<RANK["DEGRADED"]:gpu["health"]="DEGRADED"
    gpu.update({"display":"OPERATIONAL" if detect.gpus else "NOT_PRESENT","ai_compute":gpu_state.get("device_health"),
      "global_ai_blocked":gpu_state.get("global_ai_blocked",False),"authorizations":gpu_state.get("authorizations",{})})
    bench_state="UNVERIFIED"
    if benchmark:bench_state="HEALTHY" if benchmark.get("score_valid") else "DEGRADED"
    overall=_worst([cpu["health"],ram["health"],gpu["health"],storage["health"],bench_state])
    findings=[]
    if benchmark and not benchmark.get("score_valid"):findings.append("Benchmark score invalidated because at least one workload failed correctness or execution.")
    if benchmark:
        if any(row.get('result',{}).get('metrics',{}).get('suspected_throttling') for row in benchmark.get('benchmarks',[])):
            findings.append('Sustained throughput suggests throttling; correlate the sensor timeline before assigning a hardware cause.')
        if any(row.get('telemetry',{}).get('abort_requested') for row in benchmark.get('benchmarks',[])):
            findings.append('A configured safety limit was exceeded; the score is invalid and the workload must be stopped by the supervising runtime.')
    if gpu_state.get("global_ai_blocked"):findings.append("GPU display may remain operational, but Phoenix AI inference is forced to CPU.")
    elif gpu_state.get("diagnostic_required"):findings.append("GPU/VRAM evidence requires deeper diagnosis; workload authorizations remain independent.")
    return {"schema":"phoenix.forge.machine-health/v1","overall":overall,
      "subsystems":{"cpu":cpu,"ram":ram,"gpu":gpu,"storage":storage,"benchmark":{"health":bench_state}},
      "findings":findings,"recommended_mode":"CPU" if gpu_state.get("global_ai_blocked") else "WORKLOAD_POLICY"}
