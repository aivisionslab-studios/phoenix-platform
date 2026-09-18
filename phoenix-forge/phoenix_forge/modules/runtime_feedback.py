from __future__ import annotations

import json
import statistics
from collections import deque
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from phoenix_forge.modules import gpu_safety

SCHEMA = "phoenix.forge.runtime-feedback/v1"
PROFILE_SCHEMA = "phoenix.forge.runtime-feedback-profile/v1"
EVENT_SCHEMA = "phoenix.forge.runtime-feedback-event/v1"

_SUCCESS = {"SUCCESS", "DELIVERED", "DELIVERED_CPU", "DELIVERED_GPU", "OK"}
_CAPACITY_FAILURES = {"OOM", "OUT_OF_MEMORY", "ALLOCATION_FAILED", "BUDGET_EXHAUSTED", "CAPACITY"}
_HARD_FAILURES = {"CORRUPTION", "DATA_MISMATCH", "DEVICE_LOST", "VALIDATION_FAILED", "PHYSICAL_MISMATCH"}
_USER_CANCEL = {"USER_CANCELLED", "USER_CANCEL", "CANCELLED_BY_USER"}
_CONTENTION = {"DEVICE_BUSY", "RESOURCE_BUSY", "LEASE_BUSY", "CONTENTION"}
_TRANSIENT = {"TIMEOUT", "ENGINE_CANCEL", "RUNTIME_ERROR"}


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _state_dir() -> Path:
    p = gpu_safety.state_dir(); p.mkdir(parents=True, exist_ok=True); return p


def _feedback_path() -> Path: return _state_dir() / "scheduler-runtime-feedback.jsonl"
def _execution_path() -> Path: return _state_dir() / "scheduler-executions.jsonl"


def _parse_iso(value: Any) -> datetime | None:
    if not value: return None
    try: return datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except (ValueError, TypeError): return None


def resolve_assignment_context(execution_id: str, assignment_id: str) -> dict[str, Any]:
    try: lines = _execution_path().read_text(encoding="utf-8").splitlines()
    except OSError: return {}
    for line in reversed(lines):
        try: row = json.loads(line)
        except ValueError: continue
        if row.get("event") != "DISPATCH_PREPARED" or row.get("execution_id") != execution_id: continue
        for assignment in row.get("assignments") or []:
            if assignment.get("assignment_id") == assignment_id:
                return {
                    "workload": row.get("workload") or "unknown",
                    "backend": row.get("backend") or "generic",
                    "effective_mode": row.get("effective_mode"),
                    "target": assignment.get("target"),
                    "device_key": assignment.get("device_key"),
                    "device_index": assignment.get("device_index"),
                    "device_name": assignment.get("name"),
                    "dispatch_created_at": row.get("created_at"),
                    "task_count": row.get("task_count", 1),
                }
        return {
            "workload": row.get("workload") or "unknown",
            "backend": row.get("backend") or "generic",
            "effective_mode": row.get("effective_mode"),
            "dispatch_created_at": row.get("created_at"),
            "task_count": row.get("task_count", 1),
        }
    return {}


def _failure_kind(status: str, failure_class: str | None) -> str:
    s = str(status or "UNKNOWN").upper(); f = str(failure_class or "").upper(); token = f or s
    if s in _SUCCESS: return "SUCCESS"
    if token in _USER_CANCEL or s in _USER_CANCEL: return "NEUTRAL"
    if token in _CAPACITY_FAILURES or any(x in token for x in ("OOM", "MEMORY", "BUDGET", "ALLOC")): return "CAPACITY"
    if token in _HARD_FAILURES or any(x in token for x in ("CORRUPT", "MISMATCH", "DEVICE_LOST")): return "HARD_RELIABILITY"
    if token in _CONTENTION or any(x in token for x in ("BUSY", "CONTENTION")): return "CONTENTION"
    if token in _TRANSIENT or any(x in token for x in ("TIMEOUT", "ENGINE_CANCEL")): return "TRANSIENT"
    if s == "CANCELLED": return "NEUTRAL"  # ambiguous cancellation is never negative training evidence
    return "OTHER_FAILURE"


def record_result(execution_id: str, assignment_id: str, *, status: str,
                  failure_class: str | None = None, detail: str | None = None,
                  training_eligible: bool = True) -> dict[str, Any]:
    context = resolve_assignment_context(execution_id, assignment_id)
    now = datetime.now(timezone.utc); started = _parse_iso(context.get("dispatch_created_at"))
    duration_s = max(0.0, (now-started).total_seconds()) if started else None
    kind = _failure_kind(status, failure_class)
    event = {
        "schema": EVENT_SCHEMA, "recorded_at": now.isoformat(), "execution_id": execution_id,
        "assignment_id": assignment_id, "workload": context.get("workload", "unknown"),
        "backend": context.get("backend", "generic"), "effective_mode": context.get("effective_mode"),
        "target": context.get("target"), "device_key": context.get("device_key"),
        "device_index": context.get("device_index"), "device_name": context.get("device_name"),
        "task_count": context.get("task_count", 1), "status": str(status or "UNKNOWN").upper(),
        "failure_class": failure_class, "failure_kind": kind,
        "duration_s": round(duration_s,6) if duration_s is not None else None,
        "detail_class": (str(detail)[:120] if detail else None),
        "training_eligible": bool(training_eligible and kind != "NEUTRAL"),
    }
    p=_feedback_path(); p.parent.mkdir(parents=True,exist_ok=True)
    with p.open("a",encoding="utf-8",newline="\n") as h:
        h.write(json.dumps(event,ensure_ascii=False,separators=(",",":"))+"\n")
    return event


def _filtered_rows(*, workload: str|None=None, backend: str|None=None, device_key: str|None=None,
                   target: str|None=None, limit: int=500, training_only: bool=True) -> list[dict[str,Any]]:
    """Filter first, then apply the per-profile history window."""
    try: lines=_feedback_path().read_text(encoding="utf-8").splitlines()
    except OSError: return []
    window=deque(maxlen=max(1,min(int(limit),5000)))
    for line in lines:
        try: r=json.loads(line)
        except ValueError: continue
        if not isinstance(r,dict): continue
        if workload and str(r.get("workload"))!=str(workload): continue
        if backend and str(r.get("backend"))!=str(backend): continue
        if device_key is not None and r.get("device_key")!=device_key: continue
        if target and str(r.get("target","")).upper()!=str(target).upper(): continue
        if training_only and r.get("training_eligible", True) is False: continue
        window.append(r)
    return list(window)


def profile(*, workload: str|None=None, backend: str|None=None, device_key: str|None=None,
            target: str|None=None, limit: int=500) -> dict[str,Any]:
    rows=_filtered_rows(workload=workload,backend=backend,device_key=device_key,target=target,limit=limit,training_only=True)
    successes=sum(1 for r in rows if r.get("failure_kind")=="SUCCESS")
    capacity=sum(1 for r in rows if r.get("failure_kind")=="CAPACITY")
    hard=sum(1 for r in rows if r.get("failure_kind")=="HARD_RELIABILITY")
    transient=sum(1 for r in rows if r.get("failure_kind")=="TRANSIENT")
    contention=sum(1 for r in rows if r.get("failure_kind")=="CONTENTION")
    neutral=sum(1 for r in rows if r.get("failure_kind")=="NEUTRAL")
    other=max(0,len(rows)-successes-capacity-hard-transient-contention-neutral)
    durations=[float(r["duration_s"]) for r in rows if isinstance(r.get("duration_s"),(int,float)) and r["duration_s"]>=0]
    success_rate=(successes/len(rows)) if rows else None
    confidence="HIGH" if len(rows)>=10 else "MEDIUM" if len(rows)>=3 else "LOW" if rows else "NONE"
    # Capability-first phase: calculate observations only. No placement score is changed.
    observed_signal=0.0
    if len(rows)>=3 and success_rate is not None:
        if success_rate>=.90: observed_signal+=8.0
        elif success_rate>=.75: observed_signal+=4.0
        elif success_rate<=.40: observed_signal-=12.0
        elif success_rate<=.60: observed_signal-=6.0
        observed_signal-=min(6.0,capacity*1.5); observed_signal-=min(12.0,hard*4.0); observed_signal-=min(4.0,transient*.5)
    observed_signal=max(-20.0,min(10.0,observed_signal))
    failure_classes={}
    for row in rows:
        if row.get("failure_kind")=="SUCCESS": continue
        fc=str(row.get("failure_class") or row.get("failure_kind") or "UNKNOWN")
        failure_classes[fc]=failure_classes.get(fc,0)+1
    return {
        "schema":PROFILE_SCHEMA,"generated_at":_now_iso(),
        "filters":{"workload":workload,"backend":backend,"device_key":device_key,"target":target},
        "samples":len(rows),"successes":successes,"success_rate":round(success_rate,4) if success_rate is not None else None,
        "capacity_failures":capacity,"hard_reliability_failures":hard,"transient_failures":transient,
        "contention_events":contention,"neutral_events":neutral,"other_failures":other,
        "median_duration_s":round(statistics.median(durations),6) if durations else None,"confidence":confidence,
        "observed_preference_signal":round(observed_signal,1),"scheduler_score_adjustment":0.0,
        "failure_classes":failure_classes,
        "policy":{"observation_only":True,"decision_influence_enabled":False,"gpu_safety_has_absolute_precedence":True,
                  "oom_is_capacity_not_physical_corruption":True,"filter_before_history_window":True,
                  "user_cancel_is_neutral":True,"synthetic_events_can_be_training_ineligible":True}
    }


def preference_adjustment(workload: str, backend: str, device_key: str|None) -> float:
    # Frozen until Capability Matrix reaches decision-ready state.
    return 0.0


def status(limit: int=500) -> dict[str,Any]:
    rows=_filtered_rows(limit=limit,training_only=False)
    return {"schema":SCHEMA,"status":"READY","events":len(rows),
            "devices":sorted({str(r.get("device_key")) for r in rows if r.get("device_key")}),
            "backends":sorted({str(r.get("backend")) for r in rows if r.get("backend")}),
            "workloads":sorted({str(r.get("workload")) for r in rows if r.get("workload")}),
            "policy":{"local_only":True,"observation_only":True,"decision_influence_enabled":False,
                      "capacity_failure_is_not_corruption":True,"user_cancel_is_neutral":True}}
