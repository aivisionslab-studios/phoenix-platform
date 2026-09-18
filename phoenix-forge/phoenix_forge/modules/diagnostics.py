from __future__ import annotations
from typing import Any

def plan(machine_health:dict[str,Any],benchmark:dict[str,Any]|None=None,storage_health:dict[str,Any]|None=None)->dict[str,Any]:
    actions=[];evidence=[]
    for row in (benchmark or {}).get("benchmarks",[]):
        name=row.get("name");result=row.get("result",{});metrics=result.get("metrics",{})
        if not row.get("valid_score"):
            actions.append({"priority":"IMMEDIATE","component":name,"action":"Do not publish this score; repeat after inspecting correctness and safety evidence."})
            evidence.append({"component":name,"reason":row.get("invalid_reason"),"status":metrics.get("status")})
        if metrics.get("suspected_throttling"):
            actions.append({"priority":"HIGH","component":name,"action":"Correlate clock, power and temperature timelines; inspect cooling and power limits."})
        violations=row.get("telemetry",{}).get("safety_violations",[])
        if violations:
            actions.append({"priority":"IMMEDIATE","component":name,"action":"Stop supervised workload and keep the device idle until temperature is safe."})
            evidence.extend(violations)
    gpu=machine_health.get("subsystems",{}).get("gpu",{})
    if gpu.get("global_ai_blocked"):
        actions.append({"priority":"IMMEDIATE","component":"gpu","action":"Keep every Phoenix AI workload on CPU; preserve display use only and run Forge deep diagnostics."})
    elif gpu.get("health")=="DEGRADED":
        actions.append({"priority":"HIGH","component":"gpu","action":"Run full VRAM map, GPU correctness and workload-specific CPU controls."})
    for disk in (storage_health or {}).get("devices",[]):
        status=str(disk.get("HealthStatus") or disk.get("smart_status",{}).get("passed","")).upper()
        if status and status not in {"HEALTHY","TRUE","OK"}:
            actions.append({"priority":"HIGH","component":"storage","action":"Back up data and inspect SMART/NVMe health before sustained benchmarks."})
            evidence.append({"component":"storage","device":disk.get("FriendlyName") or disk.get("model_name"),"status":status})
    order={"IMMEDIATE":0,"HIGH":1,"MEDIUM":2,"INFO":3};actions.sort(key=lambda x:order.get(x["priority"],9))
    return {"schema":"phoenix.forge.diagnostic-plan/v1","machine_state":machine_health.get("overall"),
      "safe_to_continue":not any(x["priority"]=="IMMEDIATE" for x in actions),"actions":actions,"evidence":evidence}
