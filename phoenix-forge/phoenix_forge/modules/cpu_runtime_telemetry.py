from __future__ import annotations

import time
from typing import Any

import psutil

from phoenix_forge.adapters import native_queries

SCHEMA = "phoenix.forge.cpu-runtime-telemetry/v1"
EXPECTED_NATIVE_SCHEMA = "phoenix.forge.native-cpu-runtime/v1"


def _num(value: Any) -> float | None:
    try:
        x = float(value)
        return x if x >= 0 else None
    except (TypeError, ValueError):
        return None


def _fallback_psutil(samples: int, interval_ms: int) -> dict[str, Any]:
    samples = max(1, min(int(samples), 30))
    interval_ms = max(10, min(int(interval_ms), 5000))
    rows: list[list[Any]] = []
    for i in range(samples):
        try:
            freq = psutil.cpu_freq(percpu=True) or []
        except Exception:
            freq = []
        rows.append(freq)
        if i + 1 < samples:
            time.sleep(interval_ms / 1000.0)
    width = max((len(r) for r in rows), default=0)
    processors = []
    for idx in range(width):
        currents, maxima = [], []
        for row in rows:
            if idx >= len(row):
                continue
            current = _num(getattr(row[idx], "current", None))
            maximum = _num(getattr(row[idx], "max", None))
            if current is not None:
                currents.append(current)
            if maximum:
                maxima.append(maximum)
        if currents:
            max_mhz = max(maxima) if maxima else None
            avg = sum(currents) / len(currents)
            processors.append({
                "sample_slot": idx,
                "os_processor_number": idx,
                "max_mhz": max_mhz,
                "mhz_limit": None,
                "current_mhz_min": min(currents),
                "current_mhz_avg": avg,
                "current_mhz_max": max(currents),
                "avg_to_max_ratio": (avg / max_mhz) if max_mhz else None,
            })
    return {
        "passed": bool(processors),
        "schema": "phoenix.forge.psutil-cpu-runtime/v1",
        "provider": "psutil.cpu_freq",
        "sampling": {"samples": samples, "interval_ms": interval_ms},
        "logical_processor_count": len(processors),
        "processor_groups": [],
        "processors": processors,
        "limitations": [
            "Fallback provider; Windows native helper not available or not upgraded",
            "psutil-reported clock is not APERF/MPERF effective clock",
        ],
    }


def normalize(raw: dict[str, Any] | None) -> dict[str, Any]:
    raw = raw or {}
    native = raw.get("schema") == EXPECTED_NATIVE_SCHEMA
    processors = []
    for row in raw.get("processors", []) if isinstance(raw.get("processors"), list) else []:
        if not isinstance(row, dict):
            continue
        avg = _num(row.get("current_mhz_avg"))
        cur_min = _num(row.get("current_mhz_min"))
        cur_max = _num(row.get("current_mhz_max"))
        max_mhz = _num(row.get("max_mhz"))
        if avg is None and cur_min is None and cur_max is None:
            continue
        processors.append({
            **row,
            "current_mhz_avg": avg,
            "current_mhz_min": cur_min,
            "current_mhz_max": cur_max,
            "max_mhz": max_mhz,
            "mhz_limit": _num(row.get("mhz_limit")),
            "avg_to_max_ratio": _num(row.get("avg_to_max_ratio")),
        })

    avgs = [p["current_mhz_avg"] for p in processors if p.get("current_mhz_avg") is not None]
    mins = [p["current_mhz_min"] for p in processors if p.get("current_mhz_min") is not None]
    maxs = [p["current_mhz_max"] for p in processors if p.get("current_mhz_max") is not None]
    advertised = [p["max_mhz"] for p in processors if p.get("max_mhz")]
    status = "COMPLETE" if raw.get("passed") and native and processors else ("PARTIAL" if processors else "UNAVAILABLE")

    return {
        "schema": SCHEMA,
        "native_schema": raw.get("schema"),
        "status": status,
        "passed": bool(processors),
        "provider": raw.get("provider"),
        "sampling": raw.get("sampling", {}),
        "logical_processor_count": raw.get("logical_processor_count") or len(processors),
        "processor_groups": raw.get("processor_groups", []),
        "processors": processors,
        "summary": {
            "observed_min_mhz": min(mins) if mins else None,
            "observed_avg_mhz": (sum(avgs) / len(avgs)) if avgs else None,
            "observed_max_mhz": max(maxs) if maxs else None,
            "advertised_max_mhz": max(advertised) if advertised else None,
            "clock_provider_is_effective_clock": False,
            "throttling_verdict": "INDETERMINATE_WITHOUT_CONTROLLED_LOAD_AND_APERF_MPERF",
        },
        "limitations": raw.get("limitations", []),
        "invariants": {
            "current_mhz_is_os_reported_not_aperf_mperf": True,
            "low_idle_clock_is_not_throttling": True,
            "bclk_is_not_inferred": True,
            "multiplier_is_not_inferred": True,
            "group_affinity_requires_independent_mapping": True,
        },
    }


def collect(samples: int = 5, interval_ms: int = 200) -> dict[str, Any]:
    raw = native_queries.cpu_clock_info(samples=samples, interval_ms=interval_ms)
    if not raw.get("passed") or raw.get("schema") != EXPECTED_NATIVE_SCHEMA:
        raw = _fallback_psutil(samples, interval_ms)
    return normalize(raw)
