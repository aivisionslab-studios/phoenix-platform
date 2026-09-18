from __future__ import annotations

import time
from collections import defaultdict
from typing import Any

from phoenix_forge.modules import shadow_outcome_tracking

SCHEMA = "phoenix.forge.shadow-reliability-scorecard/v1"
GATE_SCHEMA = "phoenix.forge.shadow-promotion-gates/v1"

MIN_DIRECT_OBSERVATIONS = 20
MIN_SUPPORT_RATE = 0.90
MAX_HARD_RELIABILITY_FAILURES = 0
MAX_CAPACITY_FAILURE_RATE = 0.20


def capabilities() -> dict[str, Any]:
    return {
        "schema": SCHEMA,
        "status": "READY",
        "scorecard_enabled": True,
        "promotion_gate_evaluation_enabled": True,
        "decision_authority_promoted": False,
        "execution_enabled": False,
        "auto_orchestration_enabled": False,
        "thresholds": {
            "min_direct_observations": MIN_DIRECT_OBSERVATIONS,
            "min_support_rate": MIN_SUPPORT_RATE,
            "max_hard_reliability_failures": MAX_HARD_RELIABILITY_FAILURES,
            "max_capacity_failure_rate": MAX_CAPACITY_FAILURE_RATE,
        },
        "policy": {
            "shadow_only": True,
            "no_dispatch": True,
            "no_provider_actions": True,
            "counterfactual_unresolved_never_counts_as_success": True,
            "only_directly_observed_shadow_divergences_are_scored": True,
            "capacity_is_not_corruption": True,
            "single_failure_is_not_physical_defect_proof": True,
            "promotion_gate_is_advisory_only": True,
            "passing_gate_does_not_enable_execution": True,
            "manual_release_gate_required_for_any_future_authority": True,
        },
    }


def _cohort_key(pred: dict[str, Any]) -> tuple:
    context = int(pred.get("context_tokens") or 0)
    if context <= 0: context_bucket = "unknown"
    elif context <= 4096: context_bucket = "ctx<=4096"
    elif context <= 8192: context_bucket = "ctx<=8192"
    elif context <= 16384: context_bucket = "ctx<=16384"
    elif context <= 32768: context_bucket = "ctx<=32768"
    else: context_bucket = "ctx>32768"
    w,h=int(pred.get("width") or 0),int(pred.get("height") or 0)
    resolution_bucket = f"{w}x{h}" if w and h else "n/a"
    return (
        str(pred.get("model_id") or "*"), str(pred.get("workload") or "unknown"),
        str(pred.get("backend") or "unknown"), str(pred.get("device_key") or "unknown"),
        str(pred.get("driver_version") or "unknown"), str(pred.get("runtime_version") or "unknown"),
        str(pred.get("model_fingerprint") or "unknown"), context_bucket, resolution_bucket,
    )


def _kind(outcome: dict[str, Any]) -> str:
    return str(outcome.get("actual_failure_kind") or "OTHER_FAILURE").upper()


def _gate(stats: dict[str, Any]) -> dict[str, Any]:
    direct=int(stats["direct_observations"])
    rate=float(stats["support_rate"])
    hard=int(stats["hard_reliability_failures"])
    cap_rate=float(stats["capacity_failure_rate"])
    checks={
        "enough_direct_observations": direct >= MIN_DIRECT_OBSERVATIONS,
        "support_rate_sufficient": rate >= MIN_SUPPORT_RATE,
        "no_hard_reliability_failures": hard <= MAX_HARD_RELIABILITY_FAILURES,
        "capacity_failure_rate_acceptable": cap_rate <= MAX_CAPACITY_FAILURE_RATE,
    }
    passed=all(checks.values())
    reasons=[k for k,v in checks.items() if not v]
    return {
        "schema": GATE_SCHEMA,
        "status": "ELIGIBLE_FOR_FUTURE_REVIEW" if passed else "NOT_ELIGIBLE",
        "passed": passed,
        "checks": checks,
        "blocking_reasons": reasons,
        "authority": {
            "advisory_only": True,
            "decision_authority_promoted": False,
            "execution_enabled": False,
            "auto_orchestration_enabled": False,
            "dispatch_performed": False,
        },
    }


def build(*, model_id: str | None = None, limit: int = 5000) -> dict[str, Any]:
    validation=shadow_outcome_tracking.validate(model_id=model_id,limit=limit)
    groups=defaultdict(lambda:{"predictions":0,"divergences":0,"direct_observations":0,"supported":0,"not_supported":0,"capacity_failures":0,"hard_reliability_failures":0,"other_failures":0,"counterfactual_unresolved":0})
    meta={}
    for case in validation.get("cases") or []:
        pred=case.get("prediction") or {}; out=case.get("outcome") or {}
        key=_cohort_key(pred); g=groups[key]; g["predictions"]+=1
        meta[key]={"model_id":key[0],"workload":key[1],"backend":key[2],"device_key":key[3],"driver_version":key[4],"runtime_version":key[5],"model_fingerprint":key[6],"context_bucket":key[7],"resolution_bucket":key[8]}
        if pred.get("shadow_changed"): g["divergences"]+=1
        val=str(out.get("validation") or "")
        if val in {"COUNTERFACTUAL_UNRESOLVED","UNOBSERVED"}: g["counterfactual_unresolved"]+=1
        if pred.get("shadow_changed") and out.get("shadow_matches_actual") is True:
            g["direct_observations"]+=1
            if out.get("actual_success") is True: g["supported"]+=1
            else:
                g["not_supported"]+=1
                kind=_kind(out)
                if kind=="CAPACITY": g["capacity_failures"]+=1
                elif kind in {"CORRUPTION","DEVICE_LOST","HARD_RELIABILITY","DATA_MISMATCH"}: g["hard_reliability_failures"]+=1
                else: g["other_failures"]+=1
    cohorts=[]
    for key,g in groups.items():
        direct=g["direct_observations"]
        g["support_rate"]=(g["supported"]/direct) if direct else 0.0
        g["capacity_failure_rate"]=(g["capacity_failures"]/direct) if direct else 0.0
        if direct >= 20: confidence="HIGH"
        elif direct >= 10: confidence="MEDIUM"
        elif direct >= 3: confidence="LOW"
        else: confidence="INSUFFICIENT"
        row={"cohort":meta[key],"metrics":g,"confidence":confidence}
        row["promotion_gate"]=_gate(g)
        cohorts.append(row)
    cohorts.sort(key=lambda x:(x["cohort"]["model_id"],x["cohort"]["device_key"],x["cohort"]["backend"]))
    eligible=sum(1 for x in cohorts if x["promotion_gate"]["passed"])
    return {
        "schema":SCHEMA,"status":"SCORECARD_READY" if cohorts else "NO_DATA","generated_at":time.time(),
        "summary":{"cohorts":len(cohorts),"eligible_for_future_review":eligible,"authority_promoted":0},
        "cohorts":cohorts,"thresholds":capabilities()["thresholds"],
        "authority":{"scorecard_only":True,"decision_authority_promoted":False,"execution_enabled":False,"auto_orchestration_enabled":False,"dispatch_performed":False},
        "policy":capabilities()["policy"],
    }
