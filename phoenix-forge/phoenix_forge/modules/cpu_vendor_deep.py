from __future__ import annotations

from typing import Any

from phoenix_forge.modules import cpu_native_inspector, windows_msr_provider

SCHEMA = "phoenix.forge.cpu-vendor-deep/v1"

_VENDOR_MAP = {
    "genuineintel": "INTEL",
    "intel": "INTEL",
    "authenticamd": "AMD",
    "amd": "AMD",
}

_VENDOR_CONTRACTS = {
    "INTEL": {
        "vendor_id": "GenuineIntel",
        "required_provider": "phoenix-msr-windows",
        "evidence": ["CPUID vendor", "Phoenix MSR provider capabilities"],
        "read_only_queries": [
            "clock.aperf_mperf",
            "cpu.intel.thermal_status",
            "cpu.intel.rapl",
            "cpu.intel.perf_status",
        ],
    },
    "AMD": {
        "vendor_id": "AuthenticAMD",
        "required_provider": "phoenix-msr-windows",
        "evidence": ["CPUID vendor", "Phoenix MSR provider capabilities"],
        "read_only_queries": [
            "clock.aperf_mperf",
            "cpu.amd.cppc",
            "cpu.amd.pstate",
            "cpu.amd.telemetry",
        ],
    },
}


def normalize_vendor(value: Any) -> str:
    text = str(value or "").strip().lower()
    if text in _VENDOR_MAP:
        return _VENDOR_MAP[text]
    if "intel" in text:
        return "INTEL"
    if "amd" in text:
        return "AMD"
    return "UNKNOWN"


def capabilities(vendor: str | None = None, provider_status: dict[str, Any] | None = None) -> dict[str, Any]:
    native = cpu_native_inspector.collect()
    raw_vendor = vendor if vendor is not None else (native.get("identity") or {}).get("vendor")
    normalized = normalize_vendor(raw_vendor)
    provider = provider_status if provider_status is not None else windows_msr_provider.status()
    provider_caps = sorted(set(map(str, provider.get("capabilities") or [])))
    contract = _VENDOR_CONTRACTS.get(normalized)

    if normalized == "UNKNOWN":
        status = "UNSUPPORTED_VENDOR"
        vendor_deep_ready = False
        missing = []
    elif provider.get("probe_status") != "READY":
        status = "RUNTIME_DEPENDENT"
        vendor_deep_ready = False
        missing = list(contract["read_only_queries"]) if contract else []
    else:
        supported = set(provider_caps)
        required = set(contract["read_only_queries"] if contract else [])
        # APERF/MPERF can already be served by the current provider. Vendor-only
        # telemetry remains unavailable until the signed Phoenix driver exposes it.
        missing = sorted(required - supported)
        vendor_deep_ready = bool(required) and not missing
        status = "READY" if vendor_deep_ready else "PARTIAL_RUNTIME"

    return {
        "schema": SCHEMA,
        "status": status,
        "vendor": normalized,
        "raw_vendor": raw_vendor,
        "contract": contract,
        "provider": {
            "name": provider.get("provider"),
            "probe_status": provider.get("probe_status"),
            "driver_status": provider.get("driver_status"),
            "abi_version": provider.get("abi_version"),
            "capabilities": provider_caps,
        },
        "vendor_deep_ready": vendor_deep_ready,
        "missing_provider_capabilities": missing,
        "policy": {
            "read_only": True,
            "signed_phoenix_kernel_driver_required_for_privileged_vendor_registers": True,
            "vulnerable_third_party_drivers_forbidden": True,
            "missing_driver_is_not_hardware_failure": True,
            "unknown_vendor_is_not_guessed": True,
            "intel_and_amd_are_first_class_cpu_vendors": True,
            "decision_influence_enabled": False,
            "automatic_dispatch": False,
        },
    }


def collect() -> dict[str, Any]:
    return capabilities()
