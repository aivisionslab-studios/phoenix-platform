from __future__ import annotations
import os
from typing import Any
from phoenix_forge.util import powershell_json, which, run


def _lhm_namespace(namespace: str) -> list[dict[str, Any]]:
    if os.name != 'nt':
        return []
    script = rf'''
try {{
  Get-CimInstance -Namespace '{namespace}' -ClassName Sensor -ErrorAction Stop |
    Where-Object {{ $_.SensorType -in @('Temperature','Load','Clock','Fan','Power','Voltage','Data','Throughput') }} |
    Select-Object Name,Identifier,SensorType,Value,Min,Max,Parent |
    ConvertTo-Json -Compress
}} catch {{}}
'''
    data = powershell_json(script)
    if not data:
        return []
    return data if isinstance(data, list) else [data]


def libre_hardware_monitor() -> list[dict[str, Any]]:
    # LHM exposes WMI only when its WMI option/service is enabled.
    return _lhm_namespace(r'root\LibreHardwareMonitor') or _lhm_namespace(r'root\OpenHardwareMonitor')


def nvidia_smi() -> list[dict[str, Any]]:
    exe = which('nvidia-smi')
    if not exe:
        return []
    queries = [
        ('name,uuid,pci.bus_id,vbios_version,pstate,temperature.gpu,utilization.gpu,memory.used,memory.total,clocks.gr,clocks.mem,power.draw,power.limit,fan.speed',
         ['name','uuid','pci_bus_id','vbios_version','pstate','temp_c','util_pct','mem_used_mb','mem_total_mb','core_mhz','mem_mhz','power_w','power_limit_w','fan_pct']),
        ('name,uuid,temperature.gpu,utilization.gpu,memory.used,memory.total,clocks.gr,clocks.mem,power.draw,fan.speed',
         ['name','uuid','temp_c','util_pct','mem_used_mb','mem_total_mb','core_mhz','mem_mhz','power_w','fan_pct']),
    ]
    for q, keys in queries:
        c, o, _ = run([exe, f'--query-gpu={q}', '--format=csv,noheader,nounits'], timeout=10)
        if c:
            continue
        rows=[]
        for ln in o.splitlines():
            if not ln.strip():
                continue
            vals=[v.strip() for v in ln.split(',')]
            if len(vals)==len(keys):
                rows.append(dict(zip(keys, vals)))
        if rows:
            return rows
    return []


def rocm_smi() -> list[dict[str, Any]]:
    exe = which('rocm-smi')
    if not exe:
        return []
    c, o, _ = run([exe, '--showtemp', '--showuse', '--showmemuse', '--showclocks', '--showpower', '--json'], timeout=15)
    if c:
        return []
    import json
    try:
        d = json.loads(o)
        return [{'device': k, **(v if isinstance(v, dict) else {'value': v})} for k,v in d.items()]
    except Exception:
        return [{'raw': o[-8000:]}]
