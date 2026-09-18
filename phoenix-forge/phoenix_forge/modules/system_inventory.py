from __future__ import annotations
import os,platform,re,time
from pathlib import Path
from typing import Any
import psutil
from phoenix_forge.util import powershell_json

def _as_list(value:Any)->list[dict[str,Any]]:
    if not value:return []
    return value if isinstance(value,list) else [value]

def _linux_caches()->list[dict[str,Any]]:
    rows=[];root=Path('/sys/devices/system/cpu/cpu0/cache')
    for p in sorted(root.glob('index*')):
        def read(name):
            try:return (p/name).read_text().strip()
            except Exception:return None
        rows.append({'level':read('level'),'type':read('type'),'size':read('size'),'line_size':read('coherency_line_size'),
          'ways':read('ways_of_associativity'),'sets':read('number_of_sets'),'shared_cpu_list':read('shared_cpu_list')})
    return rows

def _windows_inventory()->dict[str,Any]:
    cpu=_as_list(powershell_json("Get-CimInstance Win32_Processor | Select DeviceID,Name,Manufacturer,Architecture,Family,Stepping,Revision,SocketDesignation,NumberOfCores,NumberOfLogicalProcessors,MaxClockSpeed,CurrentClockSpeed,L2CacheSize,L3CacheSize,VirtualizationFirmwareEnabled,VMMonitorModeExtensions | ConvertTo-Json -Compress"))
    cache=_as_list(powershell_json("Get-CimInstance Win32_CacheMemory | Select DeviceID,Level,CacheType,InstalledSize,MaxCacheSize,Associativity,BlockSize,NumberOfBlocks,Status | ConvertTo-Json -Compress"))
    dimms=_as_list(powershell_json("Get-CimInstance Win32_PhysicalMemory | Select DeviceLocator,BankLabel,Manufacturer,PartNumber,SerialNumber,Capacity,Speed,ConfiguredClockSpeed,DataWidth,TotalWidth,FormFactor,MemoryType,SMBIOSMemoryType | ConvertTo-Json -Compress"))
    return {'processors':cpu,'caches':cache,'dimms':dimms}

def collect()->dict[str,Any]:
    started=time.time();freq=psutil.cpu_freq();parts=psutil.virtual_memory()
    base={'schema':'phoenix.forge.system-inventory/v1','provider':'CIM+CPUID/native' if os.name=='nt' else 'sysfs+procfs',
      'platform':platform.platform(),'machine':platform.machine(),'logical_cpus':psutil.cpu_count(True),'physical_cores':psutil.cpu_count(False),
      'frequency_mhz':{'current':freq.current,'min':freq.min,'max':freq.max} if freq else {},
      'memory':{'total_bytes':parts.total,'available_bytes':parts.available},'limitations':[]}
    if os.name=='nt':base.update(_windows_inventory())
    else:base.update({'processors':[{'name':platform.processor()}],'caches':_linux_caches(),'dimms':[]});base['limitations'].append('SPD requires a privileged SMBus provider and is not inferred from generic OS data.')
    base['generated_at']=started;return base

def pcie_health(minutes:int=1440,max_events:int=200)->dict[str,Any]:
    if os.name!='nt':return {'schema':'phoenix.forge.pcie-health/v1','status':'UNAVAILABLE','events':[],'reason':'Windows WHEA provider required'}
    script=f"Get-WinEvent -FilterHashtable @{{LogName='System';ProviderName='Microsoft-Windows-WHEA-Logger';StartTime=(Get-Date).AddMinutes(-{max(1,minutes)})}} -ErrorAction SilentlyContinue | Select-Object -First {max(1,min(max_events,1000))} TimeCreated,Id,LevelDisplayName,Message | ConvertTo-Json -Compress"
    events=_as_list(powershell_json(script));patterns={'PCIE':['pci express','pcie','root port'],'MEMORY':['memory','corrected machine check'],'CPU':['processor core','cache hierarchy','bus/interconnect']};counts={k:0 for k in patterns}
    for event in events:
        msg=str(event.get('Message','')).lower()
        for domain,terms in patterns.items():
            if any(x in msg for x in terms):counts[domain]+=1
    severe=sum(1 for x in events if str(x.get('LevelDisplayName','')).lower() in {'error','critical'})
    return {'schema':'phoenix.forge.pcie-health/v1','status':'DEGRADED' if severe or counts['PCIE'] else 'CLEAR','window_minutes':minutes,'event_count':len(events),'severe_count':severe,'classifications':counts,'events':events}
