from __future__ import annotations
import os, time
from pathlib import Path
from typing import Any

SCHEMA='phoenix.forge.privileged-provider-contracts/v1'

def _file_env(name:str)->dict[str,Any]:
    raw=os.environ.get(name)
    p=Path(raw) if raw else None
    return {'configured':bool(raw),'path':raw,'exists':bool(p and p.exists()),'provider':'environment contract'}

def collect()->dict[str,Any]:
    providers={
      'smbus_spd':{**_file_env('PHOENIX_FORGE_SMBUS_PROVIDER'),'required_for':['live_spd','xmp_expo','jedec_full','dimm_voltage_tables'],'privilege':'administrator_or_driver'},
      'msr':{**_file_env('PHOENIX_FORGE_MSR_PROVIDER'),'required_for':['aperf_mperf','effective_clock','bclk_multiplier'],'privilege':'administrator_or_driver'},
      'electrical':{**_file_env('PHOENIX_FORGE_ELECTRICAL_PROVIDER'),'required_for':['psu_rails','transients','board_power_crosscheck'],'privilege':'vendor_or_external_sensor'},
    }
    for p in providers.values():
        p['status']='READY' if p['exists'] else ('CONFIGURED_MISSING' if p['configured'] else 'NOT_CONFIGURED')
    return {'schema':SCHEMA,'generated_at':time.time(),'status':'OK','providers':providers,
      'contract':{'absence_is_not_failure':True,'not_configured_is_not_supported_evidence':True,'no_fake_fallback_values':True}}
