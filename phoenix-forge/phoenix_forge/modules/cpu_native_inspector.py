from __future__ import annotations

from typing import Any

from phoenix_forge.adapters import native_queries

SCHEMA = "phoenix.forge.cpu-native-inspector/v1"
EXPECTED_NATIVE_SCHEMA = "phoenix.forge.native-cpu/v1"


def _positive_int(value: Any) -> int | None:
    try:
        n = int(value)
        return n if n > 0 else None
    except (TypeError, ValueError):
        return None


def normalize(raw: dict[str, Any] | None) -> dict[str, Any]:
    raw = raw or {}
    passed = bool(raw.get("passed"))
    schema_ok = raw.get("schema") == EXPECTED_NATIVE_SCHEMA
    features = raw.get("features") if isinstance(raw.get("features"), dict) else {}
    caches = raw.get("caches") if isinstance(raw.get("caches"), list) else []
    topology = raw.get("topology") if isinstance(raw.get("topology"), list) else []
    address = raw.get("address_width") if isinstance(raw.get("address_width"), dict) else {}
    frequency = raw.get("frequency") if isinstance(raw.get("frequency"), dict) else {}

    normalized_caches: list[dict[str, Any]] = []
    for row in caches:
        if not isinstance(row, dict):
            continue
        size = _positive_int(row.get("size_bytes"))
        level = _positive_int(row.get("level"))
        line = _positive_int(row.get("line_size"))
        ways = _positive_int(row.get("ways"))
        sets = _positive_int(row.get("sets"))
        if not all((size, level, line, ways, sets)):
            continue
        normalized_caches.append({**row, "size_bytes": size, "level": level, "line_size": line, "ways": ways, "sets": sets})

    normalized_topology: list[dict[str, Any]] = []
    for row in topology:
        if not isinstance(row, dict):
            continue
        logical = _positive_int(row.get("logical_processors"))
        level_type = _positive_int(row.get("level_type"))
        if logical and level_type:
            normalized_topology.append(dict(row))

    freq_values = {
        "base_mhz": _positive_int(frequency.get("base_mhz")),
        "max_mhz": _positive_int(frequency.get("max_mhz")),
        "bus_mhz": _positive_int(frequency.get("bus_mhz")),
        "tsc_denominator": _positive_int(frequency.get("tsc_denominator")),
        "tsc_numerator": _positive_int(frequency.get("tsc_numerator")),
        "crystal_hz": _positive_int(frequency.get("crystal_hz")),
    }
    frequency_available = any(v is not None for v in freq_values.values())

    if not passed:
        status = "UNAVAILABLE"
    elif not schema_ok:
        status = "LEGACY_HELPER"
    elif normalized_caches and features:
        status = "COMPLETE"
    else:
        status = "PARTIAL"

    return {
        "schema": SCHEMA,
        "native_schema": raw.get("schema"),
        "status": status,
        "passed": passed and schema_ok,
        "provider": raw.get("provider") or "CPUID",
        "identity": {
            "vendor": raw.get("vendor"),
            "brand": raw.get("brand"),
            "signature": raw.get("signature"),
            "family": raw.get("family"),
            "model": raw.get("model"),
            "stepping": raw.get("stepping"),
            "max_basic_leaf": raw.get("max_basic_leaf"),
            "max_extended_leaf": raw.get("max_extended_leaf"),
        },
        "features": {
            "values": features,
            "enabled": sorted(k for k, v in features.items() if v is True),
            "disabled": sorted(k for k, v in features.items() if v is False),
        },
        "caches": normalized_caches,
        "topology": normalized_topology,
        "topology_leaf": raw.get("topology_leaf"),
        "address_width": {
            "physical_bits": _positive_int(address.get("physical_bits")),
            "virtual_bits": _positive_int(address.get("virtual_bits")),
        },
        "frequency": {**freq_values, "available": frequency_available},
        "error": raw.get("error"),
        "invariants": {
            "zero_cpuid_frequency_is_unknown": True,
            "cache_geometry_requires_deterministic_leaf": True,
            "os_topology_and_cpuid_topology_are_independent_evidence": True,
        },
    }


def collect() -> dict[str, Any]:
    return normalize(native_queries.cpu_deep_info())
