from __future__ import annotations
from typing import Any

SCHEMA = 'phoenix.forge.public-surface/v1'
SECTIONS = [
    ('overview','Overview','/api/report'),
    ('cpu','CPU Deep','/api/hardware/cpu-deep'),
    ('gpu','GPU Deep','/api/hardware/gpu-deep-telemetry'),
    ('memory','Memory / SPD','/api/hardware/memory-spd'),
    ('pcie','PCIe','/api/hardware/pcie-deep-inspection'),
    ('storage','Storage','/api/hardware/storage-deep'),
    ('sensors','Sensors','/api/hardware/sensor-intelligence/capabilities'),
    ('stress','Stress & Correctness','/api/stress-correctness/capabilities'),
    ('vbios','BIOS Test / VBIOS Dossier','/api/vbios-dossier/capabilities'),
    ('capabilities','Capability Matrix','/api/capability-matrix'),
    ('readiness','Readiness','/api/readiness'),
    ('finalization','Capability Finalization','/api/capability-finalization'),
    ('rc','Release Candidate','/api/release-candidate'),
    ('decision-preview','Decision Preview','/api/decision-preview/capabilities'),
    ('decision-shadow','Decision Preview Shadow Evidence','/api/decision-preview/shadow-capabilities'),
    ('shadow-outcomes','Shadow Reliability Scorecard / Promotion Gates','/api/decision-preview/shadow-outcomes/capabilities'),
    ('workload-profile','Workload Profiling / Model Fit','/api/workload-profile'),
    ('model-discovery','Runtime Model Discovery / Fit Calibration','/api/models/discover'),
    ('runtime-observation','Runtime Observation Bridge','/api/runtime-observations/capabilities'),
    ('observation-correlation','Observation Correlation / Calibration Confidence','/api/runtime-observations/correlation'),
    ('calibration-cohorts','Calibration Cohorts / Confidence Aging','/api/calibration-cohorts'),
]

def build() -> dict[str, Any]:
    return {
        'schema': SCHEMA,
        'product': 'Phoenix Forge',
        'surface_version': 1,
        'sections': [{'id':i,'title':t,'endpoint':e} for i,t,e in SECTIONS],
        'policy': {
            'public_names_are_phoenix_owned': True,
            'legacy_aliases_are_not_ui_contracts': True,
            'decision_engine_enabled': False,
            'decision_preview_enabled': True,
            'firmware_write_actions_exposed': False,
        },
    }
