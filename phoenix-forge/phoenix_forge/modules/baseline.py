from __future__ import annotations
import hashlib,json,os,tempfile
from datetime import datetime,timezone
from pathlib import Path
from typing import Any
from phoenix_forge.models import DetectReport
from phoenix_forge.modules.gpu_safety import state_dir
from phoenix_forge.modules import quality_gate

SCHEMA="phoenix.forge.golden-baseline/v1"
def _now()->str:return datetime.now(timezone.utc).isoformat()
def fingerprint(d:DetectReport)->str:
    g=[{"pnp":x.pnp_device_id,"device":x.device_id,"subsystem":x.subsystem_device_id} for x in d.gpus]
    stable={"cpu":d.cpu,"logical_cpus":d.logical_cpus,"ram_total_bytes":d.ram_total_bytes,"motherboard":d.motherboard,"gpus":g}
    return hashlib.sha256(json.dumps(stable,sort_keys=True,ensure_ascii=True).encode()).hexdigest()
def path_for(d:DetectReport)->Path:return state_dir()/"baselines"/f"{fingerprint(d)}.json"
def _atomic(path:Path,data:dict[str,Any])->None:
    path.parent.mkdir(parents=True,exist_ok=True);fd,tmp=tempfile.mkstemp(prefix=path.name+".",suffix=".tmp",dir=path.parent)
    try:
        with os.fdopen(fd,"w",encoding="utf-8") as h:json.dump(data,h,indent=2,ensure_ascii=False);h.write("\n");h.flush();os.fsync(h.fileno())
        os.replace(tmp,path)
    finally:
        try:os.unlink(tmp)
        except FileNotFoundError:pass
def create(d:DetectReport,benchmark:dict[str,Any],health:dict[str,Any])->dict[str,Any]:
    path=path_for(d)
    if path.exists():raise FileExistsError("Golden Baseline already exists and cannot be overwritten automatically.")
    gate=quality_gate.benchmark_gate(benchmark,health)
    if not gate["baseline_eligible"]:raise ValueError("Golden Baseline blocked by Quality Gate: "+", ".join(gate["reasons"]))
    data={"schema":SCHEMA,"created_at":_now(),"fingerprint":fingerprint(d),"hardware":d.model_dump(),
      "benchmark":benchmark,"health":health,"quality_gate":gate,"immutable":True}
    _atomic(path,data);return {"created":True,"path":str(path),"baseline":data}
def read(d:DetectReport)->dict[str,Any]|None:
    try:
        data=json.loads(path_for(d).read_text(encoding="utf-8"))
        return data if data.get("schema")==SCHEMA else None
    except (OSError,ValueError):return None
def _metrics(suite:dict[str,Any])->dict[str,float]:
    out={}
    for row in suite.get("benchmarks",[]):
        name=row.get("name","unknown");m=row.get("result",{}).get("metrics",{})
        for key in ("operations_per_second","median_mb_s","read_mb_s","write_mb_s","throughput_mb_s",
                    "nanoseconds_per_access","million_accesses_per_second","read_iops","write_iops",
                    "first_to_last_percent"):
            if isinstance(m.get(key),(int,float)):out[f"{name}.{key}"]=float(m[key])
        for group in ("distribution_ops_s","distribution_mb_s","compress_mb_s","decompress_mb_s","read_latency","write_latency"):
            values=m.get(group,{})
            if isinstance(values,dict):
                for stat in ("p50","p95","p50_ms","p95_ms","mean","avg_ms"):
                    if isinstance(values.get(stat),(int,float)):out[f"{name}.{group}.{stat}"]=float(values[stat])
    return out
def compare(d:DetectReport,current:dict[str,Any])->dict[str,Any]:
    base=read(d)
    if not base:return {"schema":"phoenix.forge.baseline-comparison/v1","available":False,"reason":"baseline_not_found"}
    old=_metrics(base.get("benchmark",{}));new=_metrics(current);rows=[]
    for key,value in new.items():
        before=old.get(key);delta=None if before in (None,0) else round((value-before)/before*100,2)
        lower_is_better=any(token in key for token in ("nanoseconds_per_access","latency","_ms"))
        regression=bool(delta is not None and (delta>=10 if lower_is_better else delta<=-10))
        rows.append({"metric":key,"baseline":before,"current":value,"delta_percent":delta,
          "direction":"lower_is_better" if lower_is_better else "higher_is_better","regression":regression})
    return {"schema":"phoenix.forge.baseline-comparison/v1","available":True,
      "fingerprint_match":base.get("fingerprint")==fingerprint(d),"current_score_valid":bool(current.get("score_valid")),
      "regressions":[x for x in rows if x["regression"]],"metrics":rows}
