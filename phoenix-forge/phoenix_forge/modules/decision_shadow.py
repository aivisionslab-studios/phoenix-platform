from __future__ import annotations
from typing import Any

from phoenix_forge.modules import calibration_cohorts

SCHEMA = "phoenix.forge.decision-shadow-evidence/v1"


def capabilities() -> dict[str, Any]:
    return {
        "schema": SCHEMA,
        "status": "READY",
        "shadow_mode_enabled": True,
        "execution_enabled": False,
        "auto_orchestration_enabled": False,
        "inputs": ["base_preview_scores", "calibration_cohorts", "confidence_aging", "runtime_observation_history"],
        "policy": {
            "shadow_only": True,
            "no_dispatch": True,
            "no_provider_actions": True,
            "does_not_modify_recommended_mode": True,
            "exact_cohort_required_for_score_delta": True,
            "changed_environment_is_neutral": True,
            "expired_positive_evidence_is_neutral": True,
            "capacity_is_not_corruption": True,
            "single_hard_failure_is_not_physical_defect_proof": True,
            "repeated_hard_failure_can_reduce_shadow_confidence": True,
        },
    }


def _delta_for_cohort(mode: str, cohort: dict[str, Any]) -> tuple[float, list[str]]:
    """Return bounded advisory delta. Never emits a hardware-defect verdict."""
    conf = cohort.get("confidence") or {}
    aging = cohort.get("aging") or {}
    aged_score = max(0.0, min(1.0, float(conf.get("aged_score") or 0.0)))
    state = str(aging.get("state") or "UNKNOWN")
    sr = max(0.0, min(1.0, float(cohort.get("success_rate") or 0.0)))
    capacity = max(0, int(cohort.get("capacity_failure_count") or 0))
    hard = max(0, int(cohort.get("hard_reliability_failure_count") or 0))
    reasons: list[str] = []

    # Positive history is deliberately bounded and expires completely.
    positive_weight = 0.0 if state == "EXPIRED" else 18.0 * aged_score
    delta = (sr - 0.50) * 2.0 * positive_weight
    if positive_weight and sr >= 0.80:
        reasons.append(f"{mode}: repeated successful exact-cohort history contributes shadow confidence.")

    # Capacity pressure is a fit/capacity signal, never corruption evidence.
    if capacity:
        cap_penalty = min(12.0, 3.0 * capacity) * max(0.30, aged_score)
        if mode == "GPU": delta -= cap_penalty
        elif mode == "HYBRID": delta -= cap_penalty * 0.35
        reasons.append(f"{mode}: {capacity} capacity event(s) reduce shadow fit confidence only.")

    # One hard event is weak evidence; repeated events carry more negative weight.
    if hard == 1:
        delta -= 6.0 * max(0.30, aged_score)
        reasons.append(f"{mode}: one hard-reliability event is advisory and requires repetition/correlation.")
    elif hard >= 2:
        delta -= min(30.0, 12.0 + 6.0 * hard) * max(0.30, aged_score)
        reasons.append(f"{mode}: repeated hard-reliability events reduce shadow confidence.")

    return round(max(-35.0, min(22.0, delta)), 3), reasons


def assess(*, base_scores: dict[str, float], base_recommendation: str, model_id: str,
           workload: str, backend: str, device_key: str | None = None,
           driver_version: str | None = None, runtime_version: str | None = None,
           model_fingerprint: str | None = None, context_tokens: int = 0,
           width: int = 0, height: int = 0,
           gpu_present: bool = True, gpu_blocked: bool = False,
           physical_defect_suspected: bool = False) -> dict[str, Any]:
    scores = {m: float(base_scores.get(m, 0.0)) for m in ("CPU", "GPU", "HYBRID")}
    deltas = {m: 0.0 for m in scores}
    evidence: dict[str, Any] = {}
    reasons: list[str] = []

    # A wildcard model cannot safely correlate to historical model evidence.
    model_known = bool(model_id and str(model_id).strip() not in {"*", "UNKNOWN", "unknown"})
    for mode in ("CPU", "GPU", "HYBRID"):
        if not model_known:
            evidence[mode] = {"status": "MODEL_ID_UNKNOWN", "compatible_history": False}
            continue
        ev = calibration_cohorts.evaluate(
            model_id=str(model_id), workload=workload, backend=backend,
            effective_mode=mode, device_key=(device_key if mode != "CPU" else None),
            driver_version=(driver_version if mode != "CPU" else None),
            runtime_version=runtime_version, model_fingerprint=model_fingerprint,
            context_tokens=context_tokens, width=width, height=height,
        )
        evidence[mode] = ev
        if ev.get("status") != "EXACT_COHORT" or not ev.get("cohort"):
            if ev.get("status") == "NEW_OR_CHANGED_COHORT":
                reasons.append(f"{mode}: related history exists but environment/context changed; no shadow score delta applied.")
            continue
        d, rs = _delta_for_cohort(mode, ev["cohort"])
        deltas[mode] = d
        scores[mode] = round(scores[mode] + d, 3)
        reasons.extend(rs)

    # Shadow can never bypass base hard-safety exclusions.
    if (not gpu_present) or gpu_blocked or physical_defect_suspected:
        scores["GPU"] = min(scores["GPU"], -50.0)
        scores["HYBRID"] = min(scores["HYBRID"], -25.0)
        reasons.append("Base hard-safety constraints are preserved in shadow evaluation.")

    ranked = sorted(scores.items(), key=lambda kv: (kv[1], {"CPU":2,"HYBRID":1,"GPU":0}.get(kv[0],0)), reverse=True)
    shadow_mode = ranked[0][0]
    margin = round(float(ranked[0][1] - ranked[1][1]), 3) if len(ranked) > 1 else 0.0
    exact_modes = [m for m,e in evidence.items() if e.get("status") == "EXACT_COHORT"]
    return {
        "schema": SCHEMA,
        "status": "SHADOW_EVALUATED" if exact_modes else "SHADOW_NO_EXACT_EVIDENCE",
        "base_recommended_mode": base_recommendation,
        "shadow_recommended_mode": shadow_mode,
        "shadow_changed": shadow_mode != base_recommendation,
        "base_scores": {k: round(v,3) for k,v in base_scores.items()},
        "shadow_scores": {k: round(v,3) for k,v in scores.items()},
        "shadow_deltas": deltas,
        "shadow_margin": margin,
        "exact_cohort_modes": exact_modes,
        "evidence": evidence,
        "reasons": reasons,
        "authority": {
            "shadow_only": True,
            "recommended_mode_unchanged": True,
            "execution_enabled": False,
            "auto_orchestration_enabled": False,
            "dispatch_performed": False,
        },
        "policy": capabilities()["policy"],
    }
