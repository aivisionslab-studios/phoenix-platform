from __future__ import annotations
from pathlib import Path
from typing import Any
from importlib import metadata as importlib_metadata

from phoenix_forge import __version__
from phoenix_forge.modules import capability_finalization, public_surface, vbios_dossier

SCHEMA = 'phoenix.forge.release-candidate/v1'
REQUIRED_PUBLIC_ENDPOINTS = {
    '/api/public-surface',
    '/api/capability-finalization',
    '/api/vbios-dossier/capabilities',
    '/api/hardware/cpu-deep',
    '/api/hardware/gpu-deep-telemetry',
    '/api/hardware/memory-spd',
    '/api/hardware/pcie-deep-inspection',
    '/api/hardware/storage-deep',
    '/api/stress-correctness/capabilities',
}

def _forge_root() -> Path:
    return Path(__file__).resolve().parents[2]

def _installed_distribution_version() -> str | None:
    try:
        return importlib_metadata.version('phoenix-forge')
    except importlib_metadata.PackageNotFoundError:
        return None

def audit(*, route_paths: set[str] | None = None) -> dict[str, Any]:
    root = _forge_root()
    public = public_surface.build()
    finalization = capability_finalization.audit()
    vbios = vbios_dossier.capabilities()
    route_paths = route_paths or set()
    missing_routes = sorted(REQUIRED_PUBLIC_ENDPOINTS - route_paths) if route_paths else []
    distribution_version = _installed_distribution_version()
    version_metadata_available = distribution_version is not None
    checks = {
        'version_matches_rc': version_metadata_available and __version__ == distribution_version,
        'canonical_root_name': root.name.lower() == 'phoenix-forge',
        'legacy_root_not_active': 'phoenix-forge-v0.12.0' not in str(root).lower(),
        'public_surface_contract': public.get('schema') == 'phoenix.forge.public-surface/v1',
        'capability_finalization_pass': finalization.get('status') == 'PASS',
        'decision_engine_blocked': finalization.get('gate',{}).get('ready_for_decision_engine') is False,
        'vbios_flash_not_exposed': vbios.get('actions',{}).get('firmware_flash') is False,
        'vbios_unlock_not_exposed': vbios.get('actions',{}).get('firmware_unlock') is False,
        'public_surface_no_firmware_write': public.get('policy',{}).get('firmware_write_actions_exposed') is False,
        'required_public_routes_present': not missing_routes,
    }
    blockers=[name for name,ok in checks.items() if not ok]
    return {
        'schema': SCHEMA,
        'product': 'Phoenix Forge',
        'version': __version__,
        'distribution_version': distribution_version,
        'status': 'READY_FOR_RC' if not blockers else 'BLOCKED',
        'forge_root': str(root),
        'checks': checks,
        'missing_public_routes': missing_routes,
        'blockers': blockers,
        'policy': {
            'decision_engine_remains_disabled': True,
            'firmware_write_remains_disabled': True,
            'rc_gate_is_release_quality_only': True,
            'version_check_uses_installed_distribution_metadata': True,
            'rc_gate_does_not_enable_auto_orchestration': True,
        },
    }
