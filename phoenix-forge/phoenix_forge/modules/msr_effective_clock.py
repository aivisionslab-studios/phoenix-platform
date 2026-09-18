from __future__ import annotations

from typing import Any

SCHEMA = "phoenix.forge.msr-effective-clock/v1"


def _number(value: Any) -> float | None:
    return float(value) if isinstance(value, (int, float)) and not isinstance(value, bool) else None


def derive_from_deltas(data: dict[str, Any]) -> dict[str, Any]:
    """Derive effective MHz from provider-supplied APERF/MPERF deltas.

    The provider must supply a measured reference_mhz for each logical CPU (or a
    top-level reference_mhz). Forge never substitutes OS CurrentMhz or advertised
    boost clocks for that reference.
    """
    if not isinstance(data, dict):
        return {"schema": SCHEMA, "status": "INVALID", "available": False, "reason": "DATA_NOT_OBJECT"}
    top_ref = _number(data.get("reference_mhz"))
    rows = data.get("samples") if isinstance(data.get("samples"), list) else data.get("per_cpu")
    if not isinstance(rows, list):
        return {"schema": SCHEMA, "status": "UNAVAILABLE", "available": False, "reason": "NO_COUNTER_SAMPLES"}

    out = []
    rejected = []
    for idx, row in enumerate(rows):
        if not isinstance(row, dict):
            rejected.append({"index": idx, "reason": "NOT_OBJECT"}); continue
        aperf = _number(row.get("aperf_delta"))
        mperf = _number(row.get("mperf_delta"))
        ref = _number(row.get("reference_mhz")) or top_ref
        if aperf is None or mperf is None:
            # Already-derived provider values are preserved but not re-labeled as raw evidence.
            eff = _number(row.get("effective_mhz"))
            if eff is not None:
                out.append({**row, "effective_mhz": round(eff, 3), "derivation": "PROVIDER_DERIVED"})
            else:
                rejected.append({"index": idx, "reason": "COUNTERS_MISSING"})
            continue
        if aperf < 0 or mperf <= 0:
            rejected.append({"index": idx, "reason": "INVALID_COUNTER_DELTA"}); continue
        if ref is None or ref <= 0:
            rejected.append({"index": idx, "reason": "REFERENCE_MHZ_MISSING"}); continue
        ratio = aperf / mperf
        # Very large ratios are treated as corrupt provider data, not CPU behavior.
        if ratio < 0 or ratio > 8.0:
            rejected.append({"index": idx, "reason": "COUNTER_RATIO_OUT_OF_RANGE", "ratio": ratio}); continue
        eff = ref * ratio
        out.append({
            "logical_cpu": row.get("logical_cpu", idx),
            "processor_group": row.get("processor_group"),
            "processor_number": row.get("processor_number"),
            "aperf_delta": int(aperf),
            "mperf_delta": int(mperf),
            "reference_mhz": round(ref, 3),
            "ratio": round(ratio, 6),
            "effective_mhz": round(eff, 3),
            "derivation": "APERF_MPERF_DELTA",
        })

    values = [r["effective_mhz"] for r in out if isinstance(r.get("effective_mhz"), (int, float))]
    return {
        "schema": SCHEMA,
        "status": "AVAILABLE" if values else "UNAVAILABLE",
        "available": bool(values),
        "effective_mhz": round(sum(values) / len(values), 3) if values else None,
        "min_mhz": round(min(values), 3) if values else None,
        "max_mhz": round(max(values), 3) if values else None,
        "per_cpu": out,
        "rejected": rejected,
        "sampling_ms": data.get("sampling_ms"),
        "invariants": {
            "reference_frequency_must_be_provider_measured": True,
            "os_current_mhz_is_not_used_as_reference": True,
            "invalid_counter_deltas_are_rejected": True,
        },
    }
