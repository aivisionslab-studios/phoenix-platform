from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from phoenix_forge.modules import execution_journal, gpu_ledger, gpu_safety

SCHEMA = "phoenix.forge.gpu-fault-correlation/v1"


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _tokens(value: Any) -> str:
    return str(value or "").upper().replace("-", "_").replace(" ", "_")


def analyze(device_name: str | None = None, limit: int = 100) -> dict[str, Any]:
    ledger = gpu_ledger.summarize(device_name)
    executions = execution_journal.recent(limit).get("entries", [])
    observations = ledger.get("last_observations", [])
    buckets = {k: 0 for k in ("vram", "compute", "device_lost", "driver", "capacity", "thermal", "quality")}
    affected: set[str] = set()
    evidence: list[dict[str, Any]] = []

    def record(text: str, source: str, workload: str | None = None) -> None:
        normalized = _tokens(text)
        matched: list[str] = []
        mapping = {
            "vram": ("MEMORY_ERROR", "DATA_MISMATCH", "VRAM"),
            "compute": ("COMPUTE_MISMATCH", "GPU_COMPUTE_UNRELIABLE"),
            "device_lost": ("DEVICE_LOST", "VK_ERROR_DEVICE_LOST"),
            "driver": ("DRIVER_ERROR", "ACCESS_VIOLATION", "0X00000005"),
            "capacity": ("OUT_OF_MEMORY", "OUTOFDEVICEMEMORY", "OOM", "TIMEOUT"),
            "thermal": ("SAFETY_ABORT", "THERMAL", "TEMPERATURE"),
            "quality": ("OUTPUT_REJECTED", "TRUNCATED", "BLUR", "ARTIFACT", "QUALITY_FAILURE"),
        }
        for group, needles in mapping.items():
            if any(token in normalized for token in needles):
                buckets[group] += 1
                matched.append(group)
        if matched:
            if workload:
                affected.add(str(workload))
            evidence.append({"source": source, "workload": workload, "classes": matched, "value": text[:500]})

    for item in observations:
        record(" ".join(map(str, [item.get("status"), item.get("module"), item.get("reason"), item.get("evidence")])), "gpu_ledger", item.get("workload"))
    for item in executions:
        workload = item.get("workload")
        record(" ".join(map(str, [item.get("status"), item.get("notice")])), "execution", workload)
        for attempt in item.get("attempts") or []:
            record(" ".join(map(str, [attempt.get("status"), attempt.get("failures"), attempt.get("evidence")])), "validation", workload)

    hardware_count = buckets["vram"] + buckets["compute"] + buckets["device_lost"] + buckets["driver"] + buckets["thermal"]
    capacity_only = buckets["capacity"] > 0 and hardware_count == 0
    if buckets["vram"]:
        cause = "VRAM_INTERMITTENT_OR_UNSTABLE"
    elif buckets["device_lost"] or buckets["driver"]:
        cause = "GPU_OR_DRIVER_INSTABILITY"
    elif buckets["compute"]:
        cause = "GPU_COMPUTE_CORRUPTION"
    elif buckets["thermal"]:
        cause = "THERMAL_SAFETY_EVENT"
    elif capacity_only:
        cause = "GPU_CAPACITY_LIMIT_NOT_HARDWARE_PROOF"
    elif buckets["quality"]:
        cause = "OUTPUT_QUALITY_FAILURE_UNATTRIBUTED"
    else:
        cause = "NO_CORRELATED_GPU_FAULT"
    total = sum(buckets.values())
    confidence = min(0.98, round(0.35 + total * 0.08 + (0.15 if len([x for x in buckets.values() if x]) >= 2 else 0), 2)) if total else 0.0
    severity = "CRITICAL" if ledger.get("classification") == "AI_COMPUTE_UNSAFE" else ("DEGRADED" if hardware_count else ("WARNING" if total else "CLEAR"))
    return {
        "schema": SCHEMA,
        "generated_at": _now(),
        "device": ledger.get("device"),
        "classification": ledger.get("classification"),
        "severity": severity,
        "probable_cause": cause,
        "confidence": confidence,
        "counts": buckets,
        "affected_workloads": sorted(affected),
        "capacity_failure_is_hardware_proof": False,
        "evidence": evidence[-50:],
    }
