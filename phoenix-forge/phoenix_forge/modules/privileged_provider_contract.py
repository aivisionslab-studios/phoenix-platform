from __future__ import annotations

from typing import Any

SCHEMA = "phoenix.forge.privileged-provider-contract/v1"

# This contract intentionally does NOT expose arbitrary MSR addresses, arbitrary
# physical memory, arbitrary I/O ports, arbitrary PCI config writes, or raw
# kernel memory. The provider is capability-based and read-only.
_ALLOWED_CAPABILITIES = {
    "INTEL": {
        "clock.aperf_mperf",
        "cpu.intel.thermal_status",
        "cpu.intel.rapl",
        "cpu.intel.perf_status",
    },
    "AMD": {
        "clock.aperf_mperf",
        "cpu.amd.cppc",
        "cpu.amd.pstate",
        "cpu.amd.telemetry",
    },
    "COMMON": {
        "memory.spd.read",
        "platform.smbus.read",
    },
}

_FORBIDDEN_REQUEST_CLASSES = {
    "raw_msr_address",
    "raw_port_io",
    "physical_memory",
    "kernel_memory",
    "pci_config_write",
    "msr_write",
    "smbus_write",
    "firmware_write",
    "flash_write",
}


def capability_catalog() -> dict[str, Any]:
    return {
        "schema": SCHEMA,
        "capabilities": {
            vendor: sorted(values)
            for vendor, values in _ALLOWED_CAPABILITIES.items()
        },
        "forbidden_request_classes": sorted(_FORBIDDEN_REQUEST_CLASSES),
        "policy": {
            "read_only": True,
            "capability_based_not_address_based": True,
            "signed_phoenix_driver_required": True,
            "vulnerable_third_party_drivers_forbidden": True,
            "arbitrary_ring0_access_forbidden": True,
            "unknown_requests_denied": True,
            "writes_forbidden": True,
            "missing_driver_is_not_hardware_failure": True,
            "decision_influence_enabled": False,
            "automatic_dispatch": False,
            "automatic_orchestration": False,
        },
    }


def evaluate_request(request: dict[str, Any] | None) -> dict[str, Any]:
    req = request if isinstance(request, dict) else {}
    vendor = str(req.get("vendor") or "COMMON").strip().upper()
    capability = str(req.get("capability") or "").strip()
    request_class = str(req.get("request_class") or "capability").strip().lower()

    if request_class in _FORBIDDEN_REQUEST_CLASSES:
        return {
            "schema": SCHEMA,
            "allowed": False,
            "reason": "FORBIDDEN_REQUEST_CLASS",
            "vendor": vendor,
            "capability": capability or None,
        }

    if request_class != "capability":
        return {
            "schema": SCHEMA,
            "allowed": False,
            "reason": "UNKNOWN_REQUEST_CLASS",
            "vendor": vendor,
            "capability": capability or None,
        }

    allowed = set(_ALLOWED_CAPABILITIES.get(vendor, set()))
    if vendor in {"INTEL","AMD"}:
        allowed |= _ALLOWED_CAPABILITIES["COMMON"]

    if not capability:
        return {
            "schema": SCHEMA,
            "allowed": False,
            "reason": "MISSING_CAPABILITY",
            "vendor": vendor,
            "capability": None,
        }

    if capability not in allowed:
        return {
            "schema": SCHEMA,
            "allowed": False,
            "reason": "CAPABILITY_NOT_ALLOWLISTED",
            "vendor": vendor,
            "capability": capability,
        }

    return {
        "schema": SCHEMA,
        "allowed": True,
        "reason": "ALLOWLISTED_READ_ONLY_CAPABILITY",
        "vendor": vendor,
        "capability": capability,
    }


def provider_requirements() -> dict[str, Any]:
    return {
        "schema": SCHEMA,
        "driver": {
            "vendor": "Phoenix",
            "signed_required": True,
            "read_only_required": True,
            "arbitrary_address_interface_allowed": False,
            "arbitrary_io_interface_allowed": False,
            "write_interface_allowed": False,
            "installation_status": "EXTERNAL_REQUIRED",
        },
        "user_mode_provider": {
            "capability_negotiation_required": True,
            "manifest_hash_required": True,
            "abi_version_required": True,
            "driver_presence_optional": True,
        },
        "status": "CONTRACT_READY_DRIVER_EXTERNAL_REQUIRED",
    }
