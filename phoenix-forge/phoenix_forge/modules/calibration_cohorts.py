from __future__ import annotations

import hashlib
import math
import time
from collections import defaultdict
from typing import Any

from phoenix_forge.modules import runtime_observation_bridge

SCHEMA = "phoenix.forge.calibration-cohorts/v1"
AGING_SCHEMA = "phoenix.forge.calibration-confidence-aging/v1"

# Conservative evidence-aging windows. Aging reduces confidence; it never turns
# old evidence into a hardware-failure verdict.
FRESH_DAYS = 7.0
AGING_DAYS = 30.0
STALE_DAYS = 90.0


def _norm(v: Any) -> str:
    return str(v or "UNKNOWN").strip() or "UNKNOWN"


def _bucket_context(tokens: int) -> str:
    n = max(0, int(tokens or 0))
    if n <= 0: return "UNKNOWN"
    if n <= 4096: return "<=4K"
    if n <= 8192: return "<=8K"
    if n <= 16384: return "<=16K"
    if n <= 32768: return "<=32K"
    return ">32K"


def _bucket_resolution(width: int, height: int) -> str:
    w,h=max(0,int(width or 0)),max(0,int(height or 0))
    if not w or not h: return "UNKNOWN"
    pixels=w*h
    if pixels <= 512*512: return "<=512SQ"
    if pixels <= 768*768: return "<=768SQ"
    if pixels <= 1024*1024: return "<=1024SQ"
    return ">1024SQ"


def _cohort_dimensions(row: dict[str, Any]) -> dict[str, str]:
    return {
        "model_id": _norm(row.get("model_id")),
        "workload": _norm(row.get("workload")).lower(),
        "backend": _norm(row.get("backend")).lower(),
        "effective_mode": _norm(row.get("effective_mode")).upper(),
        "device_key": _norm(row.get("device_key")),
        "driver_version": _norm(row.get("driver_version")),
        "runtime_version": _norm(row.get("runtime_version")),
        "model_fingerprint": _norm(row.get("model_fingerprint")),
        "context_bucket": _bucket_context(int(row.get("context_tokens") or 0)),
        "resolution_bucket": _bucket_resolution(int(row.get("width") or 0), int(row.get("height") or 0)),
    }


def _cohort_key(dim: dict[str, str]) -> str:
    raw="|".join(dim[k] for k in (
        "model_id","workload","backend","effective_mode","device_key",
        "driver_version","runtime_version","model_fingerprint","context_bucket","resolution_bucket"
    ))
    return hashlib.sha256(raw.encode("utf-8","ignore")).hexdigest()[:24]


def _raw_confidence(sample_count: int, success_count: int, hard_failures: int) -> tuple[str,float]:
    if sample_count <= 0: return "NONE",0.0
    sr=success_count/sample_count
    repetition=min(1.0, math.log2(sample_count+1)/3.25)
    score=repetition*(0.40+0.60*sr)
    if hard_failures:
        score *= max(0.10, 1.0-min(0.80, hard_failures/max(1,sample_count)))
    score=round(max(0.0,min(1.0,score)),3)
    if sample_count >= 8 and sr >= .80 and hard_failures == 0: level="HIGH"
    elif sample_count >= 4 and sr >= .60: level="MEDIUM"
    else: level="LOW"
    return level,score


def _age(latest_timestamp: Any, now_ts: float) -> dict[str, Any]:
    try: ts=float(latest_timestamp)
    except Exception: ts=0.0
    if ts <= 0:
        return {"state":"UNKNOWN","age_days":None,"factor":0.50,"stale":None,"reason":"TIMESTAMP_UNKNOWN"}
    age_days=max(0.0,(now_ts-ts)/86400.0)
    if age_days <= FRESH_DAYS: state,factor="FRESH",1.0
    elif age_days <= AGING_DAYS: state,factor="AGING",0.85
    elif age_days <= STALE_DAYS: state,factor="STALE",0.60
    else: state,factor="EXPIRED",0.30
    return {"state":state,"age_days":round(age_days,3),"factor":factor,"stale":state in {"STALE","EXPIRED"},"reason":f"AGE_{state}"}


def _aged_level(score: float, samples: int) -> str:
    if samples <= 0 or score <= 0: return "NONE"
    if samples >= 8 and score >= .72: return "HIGH"
    if samples >= 4 and score >= .45: return "MEDIUM"
    return "LOW"


def capabilities() -> dict[str, Any]:
    return {
        "schema":SCHEMA,"status":"READY",
        "cohort_dimensions":["model_id","workload","backend","effective_mode","device_key","driver_version","runtime_version","model_fingerprint","context_bucket","resolution_bucket"],
        "aging_windows_days":{"fresh":FRESH_DAYS,"aging":AGING_DAYS,"stale":STALE_DAYS},
        "aging_states":["FRESH","AGING","STALE","EXPIRED","UNKNOWN"],
        "policy":{
            "evidence_only":True,
            "decision_influence_enabled":False,
            "shadow_mode_enabled":False,
            "auto_orchestration_enabled":False,
            "no_dispatch":True,
            "capacity_failure_never_proves_physical_defect":True,
            "hard_reliability_failure_not_collapsed_into_capacity":True,
            "old_evidence_loses_weight":True,
            "environment_change_creates_new_cohort":True,
        },
    }


def cohorts(*, model_id: str|None=None, runtime: str|None=None, limit: int=3000, now_ts: float|None=None) -> dict[str,Any]:
    now=float(now_ts if now_ts is not None else time.time())
    rows=runtime_observation_bridge.history(runtime=runtime,model_id=model_id,limit=limit)["entries"]
    groups: dict[str,list[dict[str,Any]]]=defaultdict(list)
    dims: dict[str,dict[str,str]]={}
    for row in rows:
        d=_cohort_dimensions(row); k=_cohort_key(d); groups[k].append(row); dims[k]=d
    result=[]
    for key,items in groups.items():
        successes=[x for x in items if x.get("failure_kind")=="SUCCESS"]
        capacity=[x for x in items if x.get("failure_kind")=="CAPACITY"]
        hard=[x for x in items if x.get("failure_kind")=="HARD_RELIABILITY"]
        transient=[x for x in items if x.get("failure_kind")=="TRANSIENT"]
        latest=max(items,key=lambda x:float(x.get("timestamp") or 0))
        raw_level,raw_score=_raw_confidence(len(items),len(successes),len(hard))
        aging=_age(latest.get("timestamp"),now)
        aged_score=round(raw_score*float(aging["factor"]),3)
        peaks=[int(x.get("peak_vram_mb") or 0) for x in successes if x.get("peak_vram_mb")]
        rams=[int(x.get("peak_ram_mb") or 0) for x in successes if x.get("peak_ram_mb")]
        result.append({
            "cohort_id":key,"dimensions":dims[key],"sample_count":len(items),"success_count":len(successes),
            "success_rate":round(len(successes)/len(items),3) if items else 0.0,
            "capacity_failure_count":len(capacity),"hard_reliability_failure_count":len(hard),"transient_failure_count":len(transient),
            "observed_success_peak_vram_mb":max(peaks) if peaks else None,"observed_success_peak_ram_mb":max(rams) if rams else None,
            "confidence":{"raw_level":raw_level,"raw_score":raw_score,"aged_level":_aged_level(aged_score,len(items)),"aged_score":aged_score},
            "aging":aging,"latest_timestamp":latest.get("timestamp"),
        })
    result.sort(key=lambda x:(x["dimensions"]["model_id"],x["dimensions"]["device_key"],x["cohort_id"]))
    return {"schema":SCHEMA,"status":"COHORTED" if result else "NO_OBSERVATIONS","generated_at":now,"cohort_count":len(result),"cohorts":result,"policy":capabilities()["policy"]}


def evaluate(*, model_id: str, workload: str|None=None, backend: str|None=None, effective_mode: str|None=None,
             device_key: str|None=None, driver_version: str|None=None, runtime_version: str|None=None,
             model_fingerprint: str|None=None, context_tokens: int=0, width: int=0, height: int=0,
             now_ts: float|None=None) -> dict[str,Any]:
    allc=cohorts(model_id=model_id,now_ts=now_ts)
    probe={"model_id":model_id,"workload":workload,"backend":backend,"effective_mode":effective_mode,"device_key":device_key,
           "driver_version":driver_version,"runtime_version":runtime_version,"model_fingerprint":model_fingerprint,
           "context_tokens":context_tokens,"width":width,"height":height}
    pd=_cohort_dimensions(probe); exact_id=_cohort_key(pd)
    exact=next((c for c in allc["cohorts"] if c["cohort_id"]==exact_id),None)
    if exact:
        return {"schema":AGING_SCHEMA,"status":"EXACT_COHORT","model_id":model_id,"cohort":exact,"compatible_history":True,
                "stale":exact["aging"]["stale"],"stale_reasons":[exact["aging"]["reason"]] if exact["aging"]["stale"] else [],"policy":capabilities()["policy"]}
    # Find same hardware/model execution family but different environment/context.
    related=[]
    for c in allc["cohorts"]:
        d=c["dimensions"]
        if workload and d["workload"]!=str(workload).lower(): continue
        if backend and d["backend"]!=str(backend).lower(): continue
        if effective_mode and d["effective_mode"]!=str(effective_mode).upper(): continue
        if device_key and d["device_key"]!=str(device_key): continue
        related.append(c)
    related.sort(key=lambda c:(c["confidence"]["aged_score"],c["sample_count"]),reverse=True)
    return {"schema":AGING_SCHEMA,"status":"NEW_OR_CHANGED_COHORT" if related else "UNKNOWN","model_id":model_id,
            "cohort":None,"compatible_history":False,"related_cohort_count":len(related),"best_related_cohort":related[0] if related else None,
            "stale":True if related else None,"stale_reasons":["ENVIRONMENT_OR_CONTEXT_CHANGED"] if related else ["NO_MATCHING_COHORT"],
            "policy":capabilities()["policy"]}
