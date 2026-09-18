from __future__ import annotations

import json
import os
import time
from pathlib import Path
from typing import Any

from phoenix_forge.modules import model_discovery

SCHEMA = "phoenix.forge.runtime-observation-bridge/v1"
EVENT_SCHEMA = "phoenix.forge.runtime-observation/v1"
_ALLOWED_RUNTIMES = {"phoenix-llama-runtime", "phoenix-diffusion"}
_CAPACITY_TOKENS = ("OOM", "OUT_OF_MEMORY", "ALLOCATION", "BUDGET", "CAPACITY", "MEMORY")
_HARD_TOKENS = ("CORRUPTION", "MISMATCH", "DEVICE_LOST", "VALIDATION_FAILED")


def _state_dir() -> Path:
    custom = os.getenv("PHOENIX_FORGE_STATE_DIR")
    p = Path(custom).expanduser() if custom else Path.home() / ".phoenix-forge"
    p.mkdir(parents=True, exist_ok=True)
    return p


def _path() -> Path:
    custom = os.getenv("PHOENIX_FORGE_RUNTIME_OBSERVATION_PATH")
    return Path(custom).expanduser() if custom else _state_dir() / "runtime-observations.jsonl"


def capabilities() -> dict[str, Any]:
    return {
        "schema": SCHEMA,
        "status": "READY",
        "supported_runtimes": sorted(_ALLOWED_RUNTIMES),
        "accepted_metrics": ["duration_s", "peak_vram_mb", "peak_ram_mb", "context_tokens", "width", "height"],
        "accepted_context": ["execution_id", "assignment_id", "workload", "model_id", "backend", "effective_mode", "device_key", "driver_version", "runtime_version", "model_fingerprint", "outcome", "failure_class", "fallback_reason"],
        "policy": {
            "observation_only": True,
            "decision_influence_enabled": False,
            "auto_orchestration_enabled": False,
            "no_dispatch": True,
            "local_only": True,
            "prompts_not_recorded": True,
            "outputs_not_recorded": True,
            "oom_is_capacity_not_corruption": True,
            "single_observation_is_not_future_fit_proof": True,
        },
    }


def _failure_kind(outcome: str, failure_class: str | None) -> str:
    token = f"{outcome} {failure_class or ''}".upper()
    if str(outcome).upper() in {"SUCCESS", "OK", "DELIVERED", "DELIVERED_CPU", "DELIVERED_GPU"}:
        return "SUCCESS"
    if any(x in token for x in _CAPACITY_TOKENS):
        return "CAPACITY"
    if any(x in token for x in _HARD_TOKENS):
        return "HARD_RELIABILITY"
    if "CANCEL" in token:
        return "NEUTRAL"
    if "TIMEOUT" in token or "RUNTIME" in token:
        return "TRANSIENT"
    return "OTHER_FAILURE"


def record(*, runtime: str, workload: str, model_id: str, backend: str = "vulkan",
           effective_mode: str = "UNKNOWN", outcome: str = "SUCCESS",
           execution_id: str | None = None, assignment_id: str | None = None,
           device_key: str | None = None, driver_version: str | None = None, runtime_version: str | None = None, model_fingerprint: str | None = None, failure_class: str | None = None,
           fallback_reason: str | None = None, duration_s: float | None = None,
           peak_vram_mb: int = 0, peak_ram_mb: int = 0, context_tokens: int = 0,
           width: int = 0, height: int = 0, evidence_source: str = "PHOENIX_RUNTIME") -> dict[str, Any]:
    runtime_n = str(runtime or "unknown").strip().lower()
    event = {
        "schema": EVENT_SCHEMA,
        "timestamp": time.time(),
        "runtime": runtime_n,
        "runtime_supported": runtime_n in _ALLOWED_RUNTIMES,
        "workload": str(workload or "unknown").lower(),
        "model_id": str(model_id or "*")[:256],
        "backend": str(backend or "unknown")[:80],
        "effective_mode": str(effective_mode or "UNKNOWN").upper()[:32],
        "outcome": str(outcome or "UNKNOWN").upper()[:64],
        "failure_class": (str(failure_class)[:96] if failure_class else None),
        "failure_kind": _failure_kind(outcome, failure_class),
        "fallback_reason": (str(fallback_reason)[:240] if fallback_reason else None),
        "execution_id": (str(execution_id)[:160] if execution_id else None),
        "assignment_id": (str(assignment_id)[:160] if assignment_id else None),
        "device_key": (str(device_key)[:200] if device_key else None),
        "driver_version": (str(driver_version)[:120] if driver_version else None),
        "runtime_version": (str(runtime_version)[:120] if runtime_version else None),
        "model_fingerprint": (str(model_fingerprint)[:160] if model_fingerprint else None),
        "duration_s": round(max(0.0, float(duration_s)), 6) if duration_s is not None else None,
        "peak_vram_mb": max(0, int(peak_vram_mb or 0)) or None,
        "peak_ram_mb": max(0, int(peak_ram_mb or 0)) or None,
        "context_tokens": max(0, int(context_tokens or 0)) or None,
        "width": max(0, int(width or 0)) or None,
        "height": max(0, int(height or 0)) or None,
        "evidence_source": str(evidence_source or "PHOENIX_RUNTIME")[:96],
    }
    p = _path(); p.parent.mkdir(parents=True, exist_ok=True)
    with p.open("a", encoding="utf-8", newline="\n") as h:
        h.write(json.dumps(event, ensure_ascii=False, separators=(",", ":")) + "\n")
    # Feed only structured resource/outcome evidence into the existing calibration journal.
    calibration = model_discovery.record_calibration(
        model_id=event["model_id"], workload=event["workload"],
        observed_peak_vram_mb=peak_vram_mb, observed_peak_ram_mb=peak_ram_mb,
        context_tokens=context_tokens, width=width, height=height,
        backend=event["backend"], outcome="SUCCESS" if event["failure_kind"] == "SUCCESS" else "FAILED",
    )
    return {
        "schema": SCHEMA,
        "status": "RECORDED",
        "event": event,
        "calibration": {"status": calibration.get("status"), "schema": calibration.get("schema")},
        "policy": capabilities()["policy"],
    }


def history(*, runtime: str | None = None, model_id: str | None = None, limit: int = 100) -> dict[str, Any]:
    rows: list[dict[str, Any]] = []
    p = _path()
    if p.exists():
        try:
            for line in p.read_text(encoding="utf-8").splitlines():
                try: row = json.loads(line)
                except Exception: continue
                if not isinstance(row, dict): continue
                if runtime and str(row.get("runtime")) != str(runtime).lower(): continue
                if model_id and row.get("model_id") != model_id: continue
                rows.append(row)
        except OSError:
            pass
    rows = rows[-max(1, min(int(limit or 100), 2000)):]
    return {"schema": SCHEMA, "status": "HISTORY", "count": len(rows), "entries": rows, "policy": capabilities()["policy"]}


def status(limit: int = 500) -> dict[str, Any]:
    rows = history(limit=limit)["entries"]
    return {
        "schema": SCHEMA,
        "status": "READY",
        "observations": len(rows),
        "runtimes": sorted({str(x.get("runtime")) for x in rows if x.get("runtime")}),
        "workloads": sorted({str(x.get("workload")) for x in rows if x.get("workload")}),
        "models": len({str(x.get("model_id")) for x in rows if x.get("model_id")}),
        "policy": capabilities()["policy"],
    }


def observe_guard_result(result: dict[str, Any], *, runtime: str, workload: str, model_id: str) -> dict[str, Any]:
    """Best-effort adapter for Forge guarded runtime results; never records prompt/output bodies."""
    output = result.get("output") if isinstance(result.get("output"), dict) else {}
    route = result.get("route") if isinstance(result.get("route"), dict) else {}
    notice = result.get("notice") if isinstance(result.get("notice"), dict) else {}
    timing = result.get("forge_timing") if isinstance(result.get("forge_timing"), dict) else {}
    delivered = result.get("deliver") is True
    duration = output.get("latency_s") if isinstance(output.get("latency_s"), (int, float)) else timing.get("total_s")
    return record(
        runtime=runtime, workload=workload, model_id=model_id,
        backend=str(route.get("backend") or "vulkan"),
        effective_mode=str(result.get("effective_mode") or route.get("effective_mode") or "UNKNOWN"),
        outcome="SUCCESS" if delivered else "FAILED",
        execution_id=result.get("execution_id"),
        failure_class=None if delivered else str(result.get("status") or "DELIVERY_REJECTED"),
        fallback_reason=(notice.get("message") or route.get("reason")),
        duration_s=duration if isinstance(duration, (int, float)) else None,
        evidence_source="FORGE_GUARDED_RUNTIME",
    )
