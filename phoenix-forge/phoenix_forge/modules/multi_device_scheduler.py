from __future__ import annotations

import json
import os
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

from phoenix_forge.models import DetectReport
from phoenix_forge.modules import compute_fabric, gpu_safety

SCHEMA = "phoenix.forge.multi-device-scheduler/v1"
PLAN_SCHEMA = "phoenix.forge.multi-device-plan/v1"
MODES = {"AUTO", "SINGLE", "PARALLEL", "COOPERATIVE", "CPU"}


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _history_path() -> Path:
    return gpu_safety.state_dir() / "scheduler-plans.jsonl"


def _record(plan: dict[str, Any]) -> None:
    path = _history_path(); path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8", newline="\n") as h:
        h.write(json.dumps(plan, ensure_ascii=False, separators=(",", ":")) + "\n")


def _default_safety(gpu: Any, workload: str) -> dict[str, Any]:
    return gpu_safety.status_for_gpu(gpu, workload=workload)


def _gpu_capacity_bytes(gpu: Any) -> int | None:
    vals = [
        getattr(gpu, "vulkan_primary_device_local_bytes", None),
        getattr(gpu, "adapter_ram_bytes", None),
    ]
    dxgi = getattr(gpu, "dxgi", {}) or {}
    vals.extend([dxgi.get("dedicated_video_memory"), dxgi.get("dedicated_vram_bytes")])
    vals = [int(v) for v in vals if isinstance(v, (int, float)) and v > 0]
    return max(vals) if vals else None


def _candidate(gpu: Any, topo: dict[str, Any], workload: str, backend: str, min_vram_bytes: int,
               safety_resolver: Callable[[Any, str], dict[str, Any]]) -> dict[str, Any]:
    safety = safety_resolver(gpu, workload)
    auth = safety.get("authorization", {})
    blocked = str(auth.get("state", "")).upper() == "BLOCKED"
    vram = _gpu_capacity_bytes(gpu)
    vram_short = bool(min_vram_bytes and vram is not None and vram < min_vram_bytes)
    unknown_capacity = bool(min_vram_bytes and vram is None)
    numa = topo.get("numa_affinity", {})
    pcie = topo.get("pcie", {})

    score = 100.0
    reasons: list[str] = []
    if blocked:
        score = 0.0; reasons.append("gpu_safety_blocked")
    else:
        if safety.get("diagnostic_required"):
            score -= 15; reasons.append("diagnostic_required")
        if str(safety.get("device_health", "UNVERIFIED")).upper() == "DEGRADED":
            score -= 20; reasons.append("device_health_degraded")
        if vram_short:
            score = 0.0; reasons.append("insufficient_known_vram")
        elif unknown_capacity:
            score -= 10; reasons.append("vram_capacity_unknown")
        if numa.get("status") == "PROVEN":
            score += 3; reasons.append("numa_affinity_proven")
        else:
            reasons.append("numa_affinity_unknown")
        if pcie.get("status") == "PROVEN":
            score += 2; reasons.append("pcie_location_proven")
        else:
            reasons.append("pcie_location_unknown")
    feedback_adjustment = 0.0  # capability-first phase: historical feedback is observation-only
    score = max(0.0, min(100.0, score))
    return {
        "device_key": topo.get("device_key"),
        "device_index": topo.get("device_index"),
        "name": topo.get("name"),
        "eligible": (not blocked) and (not vram_short),
        "score": round(score, 1),
        "known_vram_bytes": vram,
        "runtime_feedback_adjustment": round(feedback_adjustment, 1),
        "safety": {
            "authorization": auth,
            "device_health": safety.get("device_health", "UNVERIFIED"),
            "diagnostic_required": bool(safety.get("diagnostic_required")),
            "failure_count": int(safety.get("failure_count", 0) or 0),
        },
        "topology": {
            "pcie_bdf": pcie.get("bdf"),
            "pcie_status": pcie.get("status", "UNKNOWN"),
            "numa_node": numa.get("node_id"),
            "numa_status": numa.get("status", "UNKNOWN"),
            "numa_confidence": numa.get("confidence", 0.0),
        },
        "reasons": reasons,
    }


def plan(report: DetectReport, *, workload: str = "llm", mode: str = "AUTO", backend: str = "generic",
         parallelizable: bool = False, min_vram_bytes: int = 0,
         safety_resolver: Callable[[Any, str], dict[str, Any]] | None = None,
         record: bool = True) -> dict[str, Any]:
    requested = str(mode or "AUTO").upper()
    if requested not in MODES:
        raise ValueError(f"Unsupported scheduler mode: {requested}")
    resolver = safety_resolver or _default_safety
    fabric = compute_fabric.build(report)
    by_key = {x.get("device_key"): x for x in fabric.get("gpus", [])}
    candidates = []
    for gpu in report.gpus:
        key = gpu.device_key or compute_fabric.stable_device_key(gpu)
        topo = by_key.get(key) or {
            "device_key": key, "device_index": gpu.device_index, "name": gpu.name,
            "pcie": {"status":"UNKNOWN"},
            "numa_affinity": {"status":"UNKNOWN","node_id":None,"confidence":0.0},
        }
        candidates.append(_candidate(gpu, topo, workload, backend, int(min_vram_bytes or 0), resolver))
    candidates.sort(key=lambda x: (-float(x["score"]), int(x["device_index"] or 0)))
    eligible = [c for c in candidates if c["eligible"]]

    effective = requested
    selected: list[dict[str, Any]] = []
    execution_ready = True
    notes: list[str] = []

    if requested == "CPU":
        effective = "CPU"; notes.append("cpu_explicitly_requested")
    elif requested == "SINGLE":
        if eligible: selected = [eligible[0]]
        else: effective = "CPU"; notes.append("no_eligible_gpu_cpu_fallback")
    elif requested == "PARALLEL":
        if not parallelizable:
            effective = "SINGLE" if eligible else "CPU"
            selected = [eligible[0]] if eligible else []
            notes.append("workload_not_declared_parallelizable")
        elif len(eligible) >= 2:
            selected = eligible
        elif len(eligible) == 1:
            effective = "SINGLE"; selected = [eligible[0]]; notes.append("only_one_eligible_gpu")
        else:
            effective = "CPU"; notes.append("no_eligible_gpu_cpu_fallback")
    elif requested == "COOPERATIVE":
        if len(eligible) >= 2:
            selected = eligible
            execution_ready = False
            notes.append("cooperative_requires_backend_specific_executor")
        elif len(eligible) == 1:
            effective = "SINGLE"; selected = [eligible[0]]; notes.append("cooperative_requires_multiple_eligible_gpus")
        else:
            effective = "CPU"; notes.append("no_eligible_gpu_cpu_fallback")
    else:  # AUTO
        if eligible:
            effective = "SINGLE"; selected = [eligible[0]]
            notes.append("auto_prefers_best_safe_single_gpu")
        else:
            effective = "CPU"; notes.append("auto_cpu_fallback_no_eligible_gpu")

    out = {
        "schema": PLAN_SCHEMA,
        "generated_at": _now(),
        "workload": workload,
        "backend": backend,
        "requested_mode": requested,
        "effective_mode": effective,
        "parallelizable": bool(parallelizable),
        "execution_ready": bool(execution_ready),
        "selected": selected,
        "candidates": candidates,
        "cpu_fallback": {"eligible": True, "reason": "universal_fallback_candidate"},
        "notes": notes,
        "invariants": {
            "gpu_safety_overrides_scheduler": True,
            "device_key_is_persistent_identity": True,
            "device_index_is_runtime_selector_only": True,
            "unknown_numa_affinity_is_not_guessed": True,
            "cooperative_mode_requires_backend_executor": True,
            "scheduler_plan_does_not_execute_workload": True,
            "runtime_feedback_observation_only": True,
            "runtime_feedback_decision_influence_enabled": False,
        },
    }
    if record:
        try: _record(out)
        except OSError: pass
    return out


def history(limit: int = 50) -> dict[str, Any]:
    rows: list[dict[str, Any]] = []
    try:
        lines = _history_path().read_text(encoding="utf-8").splitlines()
        for line in lines[-max(1, min(int(limit), 500)):]:
            try: rows.append(json.loads(line))
            except ValueError: pass
    except OSError:
        pass
    return {"schema":"phoenix.forge.multi-device-scheduler-history/v1", "count":len(rows), "plans":rows}


def capabilities() -> dict[str, Any]:
    return {
        "schema": SCHEMA,
        "status": "READY",
        "planning_modes": ["AUTO","CPU","SINGLE","PARALLEL","COOPERATIVE"],
        "execution": {
            "single": "PLAN_READY",
            "parallel": "PLAN_READY_FOR_PARALLELIZABLE_WORKLOADS",
            "cooperative": "READY_WHEN_COOPERATIVE_BACKEND_REGISTERED",
        },
        "evidence_inputs": ["Compute Fabric","GPU Safety","VRAM capacity","PCIe location","NUMA affinity"],
        "policy": {
            "blocked_gpu_never_selected": True,
            "cpu_fallback_always_available": True,
            "auto_does_not_assume_parallelism": True,
            "unknown_topology_is_preserved": True,
        },
    }
