from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

SCHEMA = "phoenix.forge.quality-gate/v1"


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def benchmark_gate(suite: dict[str, Any], machine_health: dict[str, Any] | None = None) -> dict[str, Any]:
    reasons: list[str] = []
    warnings: list[str] = []
    rows = list(suite.get("benchmarks") or [])
    if suite.get("cancelled") or str(suite.get("status", "")).upper() == "CANCELLED":
        reasons.append("BENCHMARK_CANCELLED")
    if not suite.get("score_valid"):
        reasons.append("INVALID_SCORE")
    if not rows:
        reasons.append("NO_MEASUREMENTS")
    for row in rows:
        name = str(row.get("name") or "unknown")
        result = row.get("result") or {}
        metrics = result.get("metrics") or {}
        telemetry = row.get("telemetry") or {}
        status = str(metrics.get("status") or "UNKNOWN").upper()
        if row.get("valid_score") is not True:
            reasons.append(f"INVALID_WORKLOAD:{name}")
        if status in {"DATA_MISMATCH", "COMPUTE_MISMATCH", "MEMORY_ERROR", "DEVICE_LOST", "DRIVER_ERROR"}:
            reasons.append(f"CORRUPTION_OR_DEVICE_FAULT:{name}:{status}")
        if metrics.get("correctness_verified") is False:
            reasons.append(f"CORRECTNESS_NOT_VERIFIED:{name}")
        if telemetry.get("abort_requested"):
            reasons.append(f"SAFETY_ABORT:{name}")
        if metrics.get("suspected_throttling"):
            reasons.append(f"THROTTLING:{name}")
        if telemetry.get("safety_violations"):
            reasons.append(f"THERMAL_LIMIT:{name}")
    overall = str((machine_health or {}).get("overall") or "UNVERIFIED").upper()
    if machine_health is not None and overall != "HEALTHY":
        reasons.append(f"MACHINE_{overall}")
    if suite.get("performance_score") is None:
        warnings.append("NO_UNIVERSAL_PERFORMANCE_SCORE")
    reasons = list(dict.fromkeys(reasons))
    eligible = not reasons
    return {
        "schema": SCHEMA,
        "evaluated_at": _now(),
        "kind": "benchmark",
        "status": "PASS" if eligible else "BLOCKED",
        "passed": eligible,
        "score_accepted": eligible,
        "baseline_eligible": eligible,
        "reasons": reasons,
        "warnings": warnings,
        "measurements": len(rows),
    }


def delivery_gate(result: dict[str, Any]) -> dict[str, Any]:
    reasons: list[str] = []
    trace = list(result.get("trace") or [])
    delivered = result.get("deliver") is True
    if not delivered:
        reasons.append("DELIVERY_REJECTED")
    if not trace:
        reasons.append("VALIDATION_TRACE_MISSING")
    final_validation = (trace[-1].get("validation") or {}) if trace else {}
    if final_validation.get("passed") is not True:
        reasons.append("FINAL_OUTPUT_INVALID")
        reasons.extend(str(x) for x in final_validation.get("failures") or [])
    effective = str(result.get("effective_mode") or "UNKNOWN").upper()
    return {
        "schema": SCHEMA,
        "evaluated_at": _now(),
        "kind": "delivery",
        "status": "PASS" if not reasons else "BLOCKED",
        "passed": not reasons,
        "deliver": delivered and not reasons,
        "effective_mode": effective,
        "reasons": list(dict.fromkeys(reasons)),
    }
