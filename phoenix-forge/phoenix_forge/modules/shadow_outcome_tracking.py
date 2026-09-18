from __future__ import annotations

import json
import os
import time
import uuid
from pathlib import Path
from typing import Any

from phoenix_forge.modules import runtime_observation_bridge

SCHEMA = "phoenix.forge.shadow-outcome-tracking/v1"
PREDICTION_SCHEMA = "phoenix.forge.shadow-prediction/v1"
VALIDATION_SCHEMA = "phoenix.forge.counterfactual-validation/v1"


def _state_dir() -> Path:
    custom = os.getenv("PHOENIX_FORGE_STATE_DIR")
    p = Path(custom).expanduser() if custom else Path.home() / ".phoenix-forge"
    p.mkdir(parents=True, exist_ok=True)
    return p


def _path() -> Path:
    custom = os.getenv("PHOENIX_FORGE_SHADOW_OUTCOME_PATH")
    return Path(custom).expanduser() if custom else _state_dir() / "shadow-predictions.jsonl"


def capabilities() -> dict[str, Any]:
    return {
        "schema": SCHEMA,
        "status": "READY",
        "tracking_enabled": True,
        "counterfactual_validation_enabled": True,
        "execution_enabled": False,
        "auto_orchestration_enabled": False,
        "policy": {
            "shadow_only": True,
            "no_dispatch": True,
            "no_provider_actions": True,
            "prediction_does_not_change_execution": True,
            "counterfactual_is_not_observed_fact": True,
            "only_same_mode_outcome_is_directly_observed": True,
            "unexecuted_shadow_mode_is_never_marked_correct_or_incorrect": True,
            "capacity_is_not_corruption": True,
            "single_failure_is_not_physical_defect_proof": True,
            "no_automatic_promotion_to_decision_authority": True,
            "local_only": True,
        },
    }


def record_prediction(*, execution_id: str | None, model_id: str, workload: str,
                      backend: str, base_recommended_mode: str,
                      shadow_recommended_mode: str, base_scores: dict[str, Any] | None = None,
                      shadow_scores: dict[str, Any] | None = None,
                      device_key: str | None = None, driver_version: str | None = None,
                      runtime_version: str | None = None, model_fingerprint: str | None = None,
                      context_tokens: int = 0, width: int = 0, height: int = 0,
                      evidence_status: str | None = None) -> dict[str, Any]:
    eid = str(execution_id or f"shadow-{uuid.uuid4()}")[:160]
    row = {
        "schema": PREDICTION_SCHEMA,
        "timestamp": time.time(),
        "execution_id": eid,
        "model_id": str(model_id or "*")[:256],
        "workload": str(workload or "unknown").lower()[:80],
        "backend": str(backend or "unknown").lower()[:80],
        "base_recommended_mode": str(base_recommended_mode or "UNKNOWN").upper()[:32],
        "shadow_recommended_mode": str(shadow_recommended_mode or "UNKNOWN").upper()[:32],
        "shadow_changed": str(base_recommended_mode or "").upper() != str(shadow_recommended_mode or "").upper(),
        "base_scores": {str(k): float(v) for k, v in (base_scores or {}).items() if isinstance(v, (int, float))},
        "shadow_scores": {str(k): float(v) for k, v in (shadow_scores or {}).items() if isinstance(v, (int, float))},
        "device_key": str(device_key)[:200] if device_key else None,
        "driver_version": str(driver_version)[:120] if driver_version else None,
        "runtime_version": str(runtime_version)[:120] if runtime_version else None,
        "model_fingerprint": str(model_fingerprint)[:160] if model_fingerprint else None,
        "context_tokens": max(0, int(context_tokens or 0)) or None,
        "width": max(0, int(width or 0)) or None,
        "height": max(0, int(height or 0)) or None,
        "evidence_status": str(evidence_status or "UNKNOWN")[:80],
    }
    p = _path(); p.parent.mkdir(parents=True, exist_ok=True)
    with p.open("a", encoding="utf-8", newline="\n") as h:
        h.write(json.dumps(row, ensure_ascii=False, separators=(",", ":")) + "\n")
    return {"schema": SCHEMA, "status": "PREDICTION_RECORDED", "prediction": row, "policy": capabilities()["policy"]}


def history(*, execution_id: str | None = None, model_id: str | None = None, limit: int = 500) -> dict[str, Any]:
    rows: list[dict[str, Any]] = []
    p = _path()
    if p.exists():
        try:
            for line in p.read_text(encoding="utf-8").splitlines():
                try: row = json.loads(line)
                except Exception: continue
                if not isinstance(row, dict): continue
                if execution_id and row.get("execution_id") != execution_id: continue
                if model_id and row.get("model_id") != model_id: continue
                rows.append(row)
        except OSError:
            pass
    rows = rows[-max(1, min(int(limit or 500), 5000)):]
    return {"schema": SCHEMA, "status": "HISTORY", "count": len(rows), "entries": rows, "policy": capabilities()["policy"]}


def _latest_observation_by_execution(limit: int = 5000) -> dict[str, dict[str, Any]]:
    observations = runtime_observation_bridge.history(limit=limit).get("entries") or []
    by_id: dict[str, dict[str, Any]] = {}
    for row in observations:
        eid = row.get("execution_id")
        if not eid: continue
        prev = by_id.get(str(eid))
        if prev is None or float(row.get("timestamp") or 0) >= float(prev.get("timestamp") or 0):
            by_id[str(eid)] = row
    return by_id


def _classify(pred: dict[str, Any], obs: dict[str, Any] | None) -> dict[str, Any]:
    base = str(pred.get("base_recommended_mode") or "UNKNOWN").upper()
    shadow = str(pred.get("shadow_recommended_mode") or "UNKNOWN").upper()
    if obs is None:
        return {
            "status": "AWAITING_OUTCOME",
            "validation": "UNOBSERVED",
            "actual_mode": None,
            "actual_failure_kind": None,
            "actual_success": None,
            "counterfactual_resolved": False,
            "reason": "No runtime observation with the same execution_id is available yet.",
        }
    actual = str(obs.get("effective_mode") or "UNKNOWN").upper()
    failure_kind = str(obs.get("failure_kind") or "OTHER_FAILURE")
    success = failure_kind == "SUCCESS"
    if shadow == base:
        validation = "NO_SHADOW_DIVERGENCE"
        reason = "Base and shadow recommended the same mode; there is no divergent counterfactual to test."
        resolved = actual == shadow
    elif actual == shadow:
        validation = "SHADOW_DIRECTLY_OBSERVED_SUPPORTED" if success else "SHADOW_DIRECTLY_OBSERVED_NOT_SUPPORTED"
        reason = "The mode selected by shadow was actually executed, so its outcome is directly observed."
        resolved = True
    else:
        validation = "COUNTERFACTUAL_UNRESOLVED"
        reason = "Shadow proposed a different mode from the one actually executed; its hypothetical outcome was not observed."
        resolved = False
    return {
        "status": "OUTCOME_MATCHED",
        "validation": validation,
        "actual_mode": actual,
        "actual_failure_kind": failure_kind,
        "actual_success": success,
        "base_matches_actual": base == actual,
        "shadow_matches_actual": shadow == actual,
        "counterfactual_resolved": resolved,
        "reason": reason,
        "observation_timestamp": obs.get("timestamp"),
    }


def validate(*, execution_id: str | None = None, model_id: str | None = None,
             limit: int = 1000) -> dict[str, Any]:
    predictions = history(execution_id=execution_id, model_id=model_id, limit=limit).get("entries") or []
    obs_by_id = _latest_observation_by_execution(limit=max(5000, limit * 4))
    cases: list[dict[str, Any]] = []
    for pred in predictions:
        outcome = _classify(pred, obs_by_id.get(str(pred.get("execution_id"))))
        cases.append({"prediction": pred, "outcome": outcome})
    matched = [x for x in cases if x["outcome"]["status"] == "OUTCOME_MATCHED"]
    divergent = [x for x in cases if bool(x["prediction"].get("shadow_changed"))]
    direct_shadow = [x for x in matched if x["outcome"].get("shadow_matches_actual") is True and x["prediction"].get("shadow_changed")]
    supported = [x for x in direct_shadow if x["outcome"].get("actual_success") is True]
    not_supported = [x for x in direct_shadow if x["outcome"].get("actual_success") is False]
    unresolved = [x for x in divergent if x["outcome"].get("validation") in {"COUNTERFACTUAL_UNRESOLVED", "UNOBSERVED"}]
    return {
        "schema": VALIDATION_SCHEMA,
        "status": "VALIDATED" if cases else "NO_PREDICTIONS",
        "generated_at": time.time(),
        "summary": {
            "predictions": len(cases),
            "matched_outcomes": len(matched),
            "shadow_divergences": len(divergent),
            "directly_observed_shadow_divergences": len(direct_shadow),
            "shadow_supported_direct_observations": len(supported),
            "shadow_not_supported_direct_observations": len(not_supported),
            "counterfactual_unresolved": len(unresolved),
        },
        "cases": cases,
        "authority": {
            "validation_only": True,
            "execution_enabled": False,
            "auto_orchestration_enabled": False,
            "dispatch_performed": False,
            "decision_authority_promoted": False,
        },
        "policy": capabilities()["policy"],
    }
