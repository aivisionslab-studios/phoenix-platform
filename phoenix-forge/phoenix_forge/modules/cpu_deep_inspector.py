from __future__ import annotations

import time
from typing import Any

from phoenix_forge.modules import (
    cpu_native_inspector,
    cpu_runtime_telemetry,
    msr_clock_intelligence,
    windows_msr_provider,
    snapshot_cache,
    detect,
    compute_fabric,
)
from phoenix_forge.adapters import native_queries

SCHEMA = "phoenix.forge.cpu-deep-inspector/v1"


def _status(native: dict[str, Any], runtime: dict[str, Any], msr: dict[str, Any]) -> str:
    native_ok = native.get("status") == "COMPLETE"
    runtime_ok = runtime.get("status") == "COMPLETE"
    effective = bool((msr.get("aperf_mperf") or {}).get("available"))
    bclk = bool((msr.get("bclk_multiplier") or {}).get("available"))
    if native_ok and runtime_ok and effective and bclk:
        return "COMPLETE"
    if native_ok or runtime_ok or effective or bclk:
        return "PARTIAL"
    return "UNAVAILABLE"


def _build(samples: int = 5, interval_ms: int = 200) -> dict[str, Any]:
    started = time.monotonic()
    native = cpu_native_inspector.normalize(native_queries.cpu_deep_info())
    runtime = cpu_runtime_telemetry.collect(samples=samples, interval_ms=interval_ms)
    msr = msr_clock_intelligence.collect(timeout_s=2.5)
    provider = windows_msr_provider.status()
    try:
        detected = detect.collect()
        fabric = detected.compute_fabric or compute_fabric.build(detected)
        fabric_cpu = {
            "processor_packages": fabric.get("processor_packages", []),
            "processor_groups": fabric.get("processor_groups", []),
            "numa_nodes": fabric.get("numa_nodes", []),
            "links": [x for x in (fabric.get("links") or []) if str(x.get("source", "")).lower().startswith(("cpu", "socket", "numa")) or str(x.get("target", "")).lower().startswith(("cpu", "socket", "numa"))],
        }
    except Exception as exc:
        fabric_cpu = {"processor_packages": [], "processor_groups": [], "numa_nodes": [], "links": [], "status": "UNAVAILABLE", "error_class": type(exc).__name__}

    effective = msr.get("aperf_mperf") or {}
    bclk = msr.get("bclk_multiplier") or {}
    observed = runtime.get("summary") or {}
    advertised = native.get("frequency") or {}

    return {
        "schema": SCHEMA,
        "generated_at": time.time(),
        "status": _status(native, runtime, msr),
        "identity": native.get("identity", {}),
        "features": native.get("features", {}),
        "caches": native.get("caches", []),
        "topology": {
            "cpuid_leaf": native.get("topology_leaf"),
            "cpuid_levels": native.get("topology", []),
            "processor_groups": runtime.get("processor_groups", []),
            "logical_processor_count": runtime.get("logical_processor_count"),
            "compute_fabric": fabric_cpu,
            "sources_are_independent": True,
        },
        "address_width": native.get("address_width", {}),
        "clocks": {
            "advertised_cpuid": advertised,
            "observed_os": observed,
            "effective_aperf_mperf": effective,
            "bclk_multiplier": bclk,
            "semantics": {
                "advertised_is_not_observed": True,
                "os_current_mhz_is_not_effective_clock": True,
                "effective_clock_requires_aperf_mperf": True,
                "bclk_multiplier_requires_verified_provider": True,
                "low_idle_clock_is_not_throttling": True,
            },
        },
        "provider": {
            "msr": provider,
            "kernel_driver_required_for_privileged_msr": True,
            "kernel_driver_bundled": False,
        },
        "evidence": {
            "cpuid": "Phoenix Forge Native/CPUID",
            "runtime_clock": runtime.get("provider"),
            "effective_clock": effective.get("provider") if effective.get("available") else None,
            "bclk_multiplier": bclk.get("provider") if bclk.get("available") else None,
        },
        "limitations": [
            "APERF/MPERF effective clock remains RUNTIME_DEPENDENT when the verified MSR kernel provider is unavailable.",
            "BCLK/multiplier is never inferred from advertised or OS-reported MHz.",
            "Thermal/power-limit throttling requires correlated sensor/control evidence and is not diagnosed from a low clock alone.",
        ],
        "elapsed_ms": round((time.monotonic() - started) * 1000, 1),
    }


def collect(samples: int = 5, interval_ms: int = 200, max_age_s: float = 15.0) -> dict[str, Any]:
    samples = max(1, min(int(samples), 30))
    interval_ms = max(10, min(int(interval_ms), 2000))
    key = f"cpu-deep:{samples}:{interval_ms}"
    snap = snapshot_cache.get(key, lambda: _build(samples, interval_ms), max_age_s=max_age_s, wait_first_s=0.35)
    if snap.get("value") is None:
        return {
            "schema": SCHEMA,
            "generated_at": time.time(),
            "status": "WARMING",
            "partial": True,
            "snapshot": snap.get("snapshot"),
            "message": "CPU deep evidence is being collected in background; no throttling or hardware failure is inferred.",
        }
    out = dict(snap["value"])
    out["snapshot"] = snap.get("snapshot")
    out["partial"] = out.get("status") != "COMPLETE"
    return out
