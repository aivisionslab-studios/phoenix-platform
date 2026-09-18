from __future__ import annotations
import os, psutil
from phoenix_forge.models import PulseReport
from phoenix_forge.util import powershell_json
from phoenix_forge.adapters.sensors import libre_hardware_monitor, nvidia_smi, rocm_smi
from phoenix_forge.adapters import amd_adl


def _windows_perf_gpu():
    if os.name != 'nt': return []
    script=r'''
$e=Get-Counter '\GPU Engine(*)\Utilization Percentage' -ErrorAction SilentlyContinue
$m=Get-Counter '\GPU Adapter Memory(*)\Dedicated Usage' -ErrorAction SilentlyContinue
$out=@()
if($e){$out += $e.CounterSamples | Where-Object {$_.CookedValue -gt 0.05} | Select-Object @{n='Type';e={'Engine'}},InstanceName,@{n='Value';e={$_.CookedValue}}}
if($m){$out += $m.CounterSamples | Where-Object {$_.CookedValue -gt 0} | Select-Object @{n='Type';e={'DedicatedMemoryBytes'}},InstanceName,@{n='Value';e={$_.CookedValue}}}
$out | ConvertTo-Json -Compress
'''
    x=powershell_json(script)
    if not x:return []
    return x if isinstance(x,list) else [x]


def collect()->PulseReport:
    vm=psutil.virtual_memory(); freq=psutil.cpu_freq(); temps={}
    try:
        for k,arr in (psutil.sensors_temperatures() or {}).items():
            temps[k]=[{'label':x.label,'current':x.current,'high':x.high,'critical':x.critical} for x in arr]
    except Exception: pass
    lhm=libre_hardware_monitor()
    if lhm: temps['libre_hardware_monitor']=lhm
    gpu=nvidia_smi() or rocm_smi()
    if not gpu and os.name=='nt':
        adl=amd_adl.collect()
        gpu=[a.get('telemetry',{}) | {'name':a.get('name'),'pnp':a.get('pnp'),'provider':'AMD ADL'} for a in adl.get('adapters',[]) if a.get('telemetry')]
    if not gpu:
        gpu=_windows_perf_gpu()
    return PulseReport(cpu_percent=psutil.cpu_percent(.25),ram_percent=vm.percent,ram_used_bytes=vm.used,ram_available_bytes=vm.available,
        cpu_freq_mhz=(freq.current if freq else None),temperatures=temps,gpu=gpu)
