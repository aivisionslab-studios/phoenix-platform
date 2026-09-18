from __future__ import annotations

import time
from typing import Any

from phoenix_forge.modules import provider_actions, provider_runtime, msr_effective_clock

SCHEMA = "phoenix.forge.msr-clock-intelligence/v1"


def _provider_for(capability: str) -> str | None:
    health = provider_runtime.health(max_age_s=20.0)
    for row in health.get("providers") or []:
        if row.get("status") != "VERIFIED":
            continue
        probe = row.get("probe") or {}
        if row.get("runtime_status") != "READY" and probe.get("status") != "READY":
            continue
        caps = set(map(str, probe.get("capabilities") or row.get("capabilities") or []))
        if capability in caps:
            return str(row.get("name") or probe.get("name") or "") or None
    return None


def _normalize_aperf(result: dict[str, Any]) -> dict[str, Any]:
    if result.get("status") not in {"OK", "PARTIAL"}:
        return {"available": False, "raw_available": False, "status": result.get("status", "UNAVAILABLE"), "provider_result": result}
    data = result.get("data") or {}
    if not isinstance(data, dict):
        return {"available": False, "raw_available": False, "status": "INVALID_PROVIDER_DATA", "provider_result": result}
    raw_samples = data.get("samples") if isinstance(data.get("samples"), list) else (data.get("per_cpu") if isinstance(data.get("per_cpu"), list) else [])
    raw_samples = [x for x in raw_samples if isinstance(x, dict)]
    raw_available = any(isinstance(x.get("aperf_delta"), (int, float)) and isinstance(x.get("mperf_delta"), (int, float)) for x in raw_samples)
    derived = msr_effective_clock.derive_from_deltas(data)
    per_cpu = derived.get("per_cpu") if derived.get("available") else raw_samples
    effective = derived.get("effective_mhz") if derived.get("available") else data.get("effective_mhz")
    available = isinstance(effective, (int, float)) or any(isinstance(x, dict) and isinstance(x.get("effective_mhz"), (int, float)) for x in per_cpu)
    status = "AVAILABLE" if available else ("RAW_COUNTERS_AVAILABLE" if raw_available else "PARTIAL_NO_EFFECTIVE_CLOCK")
    return {"available": bool(available),"raw_available": bool(raw_available),"status": status,
            "effective_mhz": effective if isinstance(effective, (int, float)) else None,
            "per_cpu": per_cpu,"raw_samples": raw_samples,
            "sampling_ms": derived.get("sampling_ms") if derived.get("available") else data.get("sampling_ms"),
            "derivation": derived.get("schema") if derived.get("available") else "REFERENCE_MHZ_UNKNOWN",
            "provider": result.get("provider"),"provider_version": result.get("provider_version"),
            "privilege": result.get("privilege"),"evidence": result.get("evidence") or []}


def _normalize_bclk(result: dict[str, Any]) -> dict[str, Any]:
    if result.get("status") not in {"OK", "PARTIAL"}:
        return {"available": False, "status": result.get("status", "UNAVAILABLE")}
    data = result.get("data") or {}
    if not isinstance(data, dict):
        return {"available": False, "status": "INVALID_PROVIDER_DATA"}
    bclk = data.get("bclk_mhz")
    mult = data.get("multiplier")
    available = isinstance(bclk, (int, float)) or isinstance(mult, (int, float))
    return {
        "available": bool(available),
        "status": "AVAILABLE" if available else "PARTIAL_NO_BCLK_MULTIPLIER",
        "bclk_mhz": bclk if isinstance(bclk, (int, float)) else None,
        "multiplier": mult if isinstance(mult, (int, float)) else None,
        "provider": result.get("provider"),
        "provider_version": result.get("provider_version"),
        "evidence": result.get("evidence") or [],
    }


def collect(timeout_s: float = 3.0) -> dict[str, Any]:
    """Collect effective-clock evidence from verified privileged providers.

    This module never estimates APERF/MPERF from OS-reported CurrentMhz and never
    fabricates BCLK/multiplier. Without a verified provider, values remain UNKNOWN.
    """
    started = time.monotonic()
    aperf_provider = _provider_for("clock.aperf_mperf")
    bclk_provider = _provider_for("clock.bclk_multiplier")

    aperf = {"available": False, "status": "PROVIDER_UNAVAILABLE"}
    bclk = {"available": False, "status": "PROVIDER_UNAVAILABLE"}

    if aperf_provider:
        aperf = _normalize_aperf(provider_actions.call(aperf_provider, "clock.aperf_mperf", {}, timeout_s=timeout_s))
    if bclk_provider:
        bclk = _normalize_bclk(provider_actions.call(bclk_provider, "clock.bclk_multiplier", {}, timeout_s=timeout_s))

    if aperf.get("available") and bclk.get("available"):
        status = "COMPLETE"
    elif aperf.get("available") or aperf.get("raw_available") or bclk.get("available"):
        status = "PARTIAL"
    else:
        status = "UNAVAILABLE"

    return {
        "schema": SCHEMA,
        "generated_at": time.time(),
        "status": status,
        "aperf_mperf": aperf,
        "bclk_multiplier": bclk,
        "elapsed_ms": round((time.monotonic() - started) * 1000, 1),
        "invariants": {
            "os_current_mhz_is_not_effective_clock": True,
            "missing_provider_means_unknown": True,
            "bclk_multiplier_is_never_inferred": True,
            "provider_must_be_verified_and_ready": True,
            "raw_aperf_mperf_is_preserved_when_reference_mhz_is_unknown": True,
        },
    }
