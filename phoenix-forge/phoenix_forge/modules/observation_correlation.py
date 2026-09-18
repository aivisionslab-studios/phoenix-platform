from __future__ import annotations

import hashlib
import json
import math
import time
from collections import defaultdict
from typing import Any

from phoenix_forge.modules import runtime_observation_bridge

SCHEMA = "phoenix.forge.observation-correlation/v1"
CONFIDENCE_SCHEMA = "phoenix.forge.calibration-confidence/v1"


def _norm(v: Any) -> str:
    return str(v or "UNKNOWN").strip() or "UNKNOWN"


def _context_key(row: dict[str, Any]) -> str:
    # Keep only execution-shape evidence, never prompt/output/user content.
    parts = [
        _norm(row.get("model_id")), _norm(row.get("workload")).lower(),
        _norm(row.get("backend")).lower(), _norm(row.get("effective_mode")).upper(),
        _norm(row.get("device_key")), _norm(row.get("driver_version")),
        _norm(row.get("runtime_version")), _norm(row.get("model_fingerprint")),
        str(int(row.get("context_tokens") or 0)), str(int(row.get("width") or 0)),
        str(int(row.get("height") or 0)),
    ]
    return hashlib.sha256("|".join(parts).encode("utf-8", "ignore")).hexdigest()[:20]


def capabilities() -> dict[str, Any]:
    return {
        "schema": SCHEMA,
        "status": "READY",
        "group_dimensions": ["model_id", "workload", "backend", "effective_mode", "device_key"],
        "staleness_dimensions": ["driver_version", "runtime_version", "model_fingerprint", "context_tokens", "width", "height"],
        "confidence_levels": ["NONE", "LOW", "MEDIUM", "HIGH"],
        "policy": {
            "evidence_only": True,
            "decision_influence_enabled": False,
            "auto_orchestration_enabled": False,
            "no_dispatch": True,
            "hard_reliability_failure_never_treated_as_capacity": True,
            "capacity_failure_never_proves_physical_defect": True,
            "single_success_never_proves_future_fit": True,
        },
    }


def _confidence(sample_count: int, success_count: int, hard_failures: int, capacity_failures: int) -> tuple[str, float]:
    if sample_count <= 0:
        return "NONE", 0.0
    success_rate = success_count / sample_count
    # Conservative confidence: repeated samples matter more than a single high success rate.
    base = min(1.0, math.log2(sample_count + 1) / 3.0)
    score = base * (0.45 + 0.55 * success_rate)
    if hard_failures:
        score *= max(0.15, 1.0 - min(0.75, hard_failures / max(1, sample_count)))
    if sample_count < 3:
        level = "LOW"
    elif sample_count >= 8 and success_rate >= 0.80 and hard_failures == 0:
        level = "HIGH"
    elif sample_count >= 4 and success_rate >= 0.60:
        level = "MEDIUM"
    else:
        level = "LOW"
    return level, round(max(0.0, min(1.0, score)), 3)


def correlate(*, model_id: str | None = None, runtime: str | None = None, limit: int = 2000) -> dict[str, Any]:
    rows = runtime_observation_bridge.history(runtime=runtime, model_id=model_id, limit=limit)["entries"]
    groups: dict[tuple[str, ...], list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        key = (
            _norm(row.get("model_id")), _norm(row.get("workload")).lower(),
            _norm(row.get("backend")).lower(), _norm(row.get("effective_mode")).upper(),
            _norm(row.get("device_key")),
        )
        groups[key].append(row)
    out=[]
    for key, items in groups.items():
        successes=[x for x in items if x.get("failure_kind")=="SUCCESS"]
        capacity=[x for x in items if x.get("failure_kind")=="CAPACITY"]
        hard=[x for x in items if x.get("failure_kind")=="HARD_RELIABILITY"]
        transient=[x for x in items if x.get("failure_kind")=="TRANSIENT"]
        peaks=[int(x.get("peak_vram_mb") or 0) for x in successes if x.get("peak_vram_mb")]
        rams=[int(x.get("peak_ram_mb") or 0) for x in successes if x.get("peak_ram_mb")]
        level, score = _confidence(len(items),len(successes),len(hard),len(capacity))
        signatures=sorted({_context_key(x) for x in items})
        latest=max(items,key=lambda x: float(x.get("timestamp") or 0))
        out.append({
            "group": {"model_id":key[0],"workload":key[1],"backend":key[2],"effective_mode":key[3],"device_key":key[4]},
            "sample_count":len(items),"success_count":len(successes),"capacity_failure_count":len(capacity),
            "hard_reliability_failure_count":len(hard),"transient_failure_count":len(transient),
            "success_rate":round(len(successes)/len(items),3) if items else 0.0,
            "observed_success_peak_vram_mb":max(peaks) if peaks else None,
            "observed_success_peak_ram_mb":max(rams) if rams else None,
            "confidence":{"level":level,"score":score},
            "context_signature_count":len(signatures),"context_signatures":signatures[-20:],
            "latest_context_signature":_context_key(latest),"latest_timestamp":latest.get("timestamp"),
        })
    out.sort(key=lambda x:(x["group"]["model_id"],x["group"]["device_key"],x["group"]["backend"]))
    return {"schema":SCHEMA,"status":"CORRELATED" if out else "NO_OBSERVATIONS","generated_at":time.time(),"group_count":len(out),"groups":out,"policy":capabilities()["policy"]}


def confidence(*, model_id: str, workload: str | None = None, backend: str | None = None,
               effective_mode: str | None = None, device_key: str | None = None,
               driver_version: str | None = None, runtime_version: str | None = None,
               model_fingerprint: str | None = None, context_tokens: int = 0,
               width: int = 0, height: int = 0) -> dict[str, Any]:
    corr=correlate(model_id=model_id)
    candidates=[]
    for g in corr["groups"]:
        k=g["group"]
        if workload and k["workload"] != str(workload).lower(): continue
        if backend and k["backend"] != str(backend).lower(): continue
        if effective_mode and k["effective_mode"] != str(effective_mode).upper(): continue
        if device_key and k["device_key"] != str(device_key): continue
        candidates.append(g)
    if not candidates:
        return {"schema":CONFIDENCE_SCHEMA,"status":"UNKNOWN","model_id":model_id,"confidence":{"level":"NONE","score":0.0},"stale":None,"stale_reasons":["NO_MATCHING_OBSERVATIONS"],"policy":capabilities()["policy"]}
    best=max(candidates,key=lambda g:(g["confidence"]["score"],g["sample_count"]))
    probe={"model_id":model_id,"workload":workload or best["group"]["workload"],"backend":backend or best["group"]["backend"],"effective_mode":effective_mode or best["group"]["effective_mode"],"device_key":device_key or best["group"]["device_key"],"driver_version":driver_version,"runtime_version":runtime_version,"model_fingerprint":model_fingerprint,"context_tokens":context_tokens,"width":width,"height":height}
    current_sig=_context_key(probe)
    supplied=any([driver_version,runtime_version,model_fingerprint,context_tokens,width,height])
    stale_reasons=[]
    if supplied and current_sig not in best.get("context_signatures",[]): stale_reasons.append("EXECUTION_CONTEXT_CHANGED")
    return {"schema":CONFIDENCE_SCHEMA,"status":"EVALUATED","model_id":model_id,"matched_group":best["group"],"confidence":best["confidence"],"sample_count":best["sample_count"],"success_rate":best["success_rate"],"stale":bool(stale_reasons) if supplied else None,"stale_reasons":stale_reasons,"current_context_signature":current_sig if supplied else None,"policy":capabilities()["policy"]}
