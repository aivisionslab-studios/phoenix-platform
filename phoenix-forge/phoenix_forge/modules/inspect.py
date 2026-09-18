from __future__ import annotations
from typing import Any
from phoenix_forge.modules import detect, pulse
from phoenix_forge.adapters import amd_adl, capabilities
from phoenix_forge.modules.watchdog import snapshot

def collect() -> dict[str, Any]:
    d=detect.collect(); p=pulse.collect()
    return {
        'schema':'phoenix.forge.inspect/v1',
        'detect':d.model_dump(),
        'capabilities':capabilities.collect(),
        'vendor_providers':{'amd_adl':amd_adl.collect()},
        'pulse':p.model_dump(),
        'watchdog':snapshot(60),
        'provenance':{
            'pci_identity':'Windows PnP/CIM cross-checked with Vulkan',
            'vram_capacity':'Vulkan device-local heap preferred; WMI is fallback only',
            'amd_telemetry':'AMD ADL when available; Windows GPU counters/LHM fallback',
            'capabilities':'API presence/initialization probes, not model-name inference',
        }
    }
