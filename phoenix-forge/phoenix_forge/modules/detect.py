from __future__ import annotations
import os, platform, socket, re, json
import psutil
from phoenix_forge.models import DetectReport, GPUInfo
from phoenix_forge.util import powershell_json, which, run, parse_pnp_ids, find_native_helper, parse_cim_date
from phoenix_forge.adapters import amd_adl, capabilities
from phoenix_forge.adapters.native_queries import dxgi_info, cpu_info
from phoenix_forge.modules.compute_fabric import stable_device_key, build as build_compute_fabric

VENDORS={'1002':'AMD','10DE':'NVIDIA','8086':'Intel'}

def _native_vk() -> list[dict]:
    exe=find_native_helper()
    if not exe:return []
    devices=[]
    for i in range(8):
        c,o,_=run([exe,'detect','--device',str(i)],timeout=15)
        if c!=0:
            if i==0:return []
            break
        try:devices.append(json.loads(o))
        except Exception:break
    return devices

def _vulkan_summary() -> tuple[bool,list[dict]]:
    native=_native_vk()
    if native:
        return True,[{'name':x.get('device_name'),'api_version':x.get('api_version'),'vendor_id':f"{int(x.get('vendor_id',0)):04X}",'device_id':f"{int(x.get('device_id',0)):04X}",'device_type':x.get('device_type'),'memory_heaps':x.get('memory_heaps',[]),'memory_types':x.get('memory_types',[]),'queue_families':x.get('queue_families',[]),'limits':x.get('limits',{}),'driver_version_raw':x.get('driver_version')} for x in native]
    exe=which('vulkaninfo')
    if not exe:return False,[]
    code,out,_=run([exe,'--summary'],timeout=20)
    if code!=0:return False,[]
    devices=[];current={}
    for line in out.splitlines():
        s=line.strip();m=re.search(r'deviceName\s*=\s*(.+)',s)
        if m:
            if current:devices.append(current)
            current={'name':m.group(1).strip()}
        m=re.search(r'apiVersion\s*=\s*(.+)',s)
        if m and current is not None:current['api_version']=m.group(1).strip()
    if current:devices.append(current)
    return True,devices

def _primary_local_bytes(heaps:list[dict])->int|None:
    vals=[int(h.get('size_bytes') or 0) for h in heaps if h.get('device_local')]
    return max(vals) if vals else None

def _adl_index(adl:dict, vid:str|None,did:str|None,pnp:str|None)->dict:
    if not adl.get('available'):return {}
    up=(pnp or '').upper()
    for a in adl.get('adapters',[]):
        ap=(a.get('pnp') or '').upper()
        if up and ap and (up in ap or ap in up):return a
    for a in adl.get('adapters',[]):
        if vid=='1002' and int(a.get('vendor_id') or 0) in (0x1002,1002):return a
    return {}

def _dxgi_match(dxgi:dict,vid:str|None,did:str|None,idx:int)->dict:
    rows=dxgi.get('adapters') or []
    try:v=int(vid,16) if vid else None; d=int(did,16) if did else None
    except Exception:v=d=None
    for a in rows:
        if a.get('vendor_id')==v and a.get('device_id')==d:return a
    return rows[idx] if idx<len(rows) else {}

def _windows_gpus(vk_devices:list[dict],dxgi:dict,adl:dict) -> list[GPUInfo]:
    data=powershell_json("Get-CimInstance Win32_VideoController | Select-Object Name,PNPDeviceID,DriverVersion,DriverDate,AdapterRAM,VideoProcessor | ConvertTo-Json -Compress")
    if not data:return []
    if isinstance(data,dict):data=[data]
    out=[]
    for idx,x in enumerate(data):
        ids=parse_pnp_ids(x.get('PNPDeviceID'));vid=ids.get('vendor_id');did=ids.get('device_id')
        vk=next((v for v in vk_devices if v.get('vendor_id')==vid and v.get('device_id')==did),None)
        if vk is None and idx<len(vk_devices):vk=vk_devices[idx]
        vk=vk or {}; heaps=vk.get('memory_heaps',[]); primary=_primary_local_bytes(heaps)
        dx=_dxgi_match(dxgi,vid,did,idx); ad=_adl_index(adl,vid,did,x.get('PNPDeviceID'))
        adtel=ad.get('telemetry') or {}; admem=adtel.get('memory') or {}
        capacity = int(dx.get('dedicated_video_memory_bytes') or 0) or int(admem.get('size_bytes') or 0) or primary or (int(x['AdapterRAM']) if x.get('AdapterRAM') is not None else None)
        source = 'DXGI DedicatedVideoMemory' if dx.get('dedicated_video_memory_bytes') else ('AMD ADL MemoryInfo' if admem.get('size_bytes') else ('Vulkan primary device-local heap' if primary else 'WMI AdapterRAM fallback'))
        gpu=GPUInfo(name=x.get('Name') or 'Unknown GPU',device_index=idx,vendor=VENDORS.get(vid),vendor_id=vid,device_id=did,
            subsystem_vendor_id=ids.get('subsystem_vendor_id'),subsystem_device_id=ids.get('subsystem_device_id'),revision_id=ids.get('revision_id'),pnp_device_id=x.get('PNPDeviceID'),driver_version=x.get('DriverVersion'),driver_date=parse_cim_date(x.get('DriverDate')),
            adapter_ram_bytes=capacity,video_processor=x.get('VideoProcessor'),vulkan_detected=bool(vk),vulkan_device_name=vk.get('name'),vulkan_api_version=str(vk.get('api_version') or '') or None,vulkan_memory_heaps=heaps,vulkan_memory_types=vk.get('memory_types',[]),vulkan_queue_families=vk.get('queue_families',[]),vulkan_limits=vk.get('limits',{}),vulkan_primary_device_local_bytes=primary,vram_capacity_source=source,dxgi=dx,vendor_details=adtel,
            sources={'pci':'Windows CIM/PNP','vulkan':'native Vulkan' if vk else None,'vram':source,'vendor':'AMD ADL' if ad else None},raw=x)
        gpu.device_key=stable_device_key(gpu)
        out.append(gpu)
    return out

def _windows_board():
    board=powershell_json('Get-CimInstance Win32_BaseBoard | Select Manufacturer,Product,Version,SerialNumber | ConvertTo-Json -Compress') or {}
    bios=powershell_json('Get-CimInstance Win32_BIOS | Select Manufacturer,SMBIOSBIOSVersion,ReleaseDate | ConvertTo-Json -Compress') or {}
    if isinstance(bios,dict) and 'ReleaseDate' in bios:bios['ReleaseDate']=parse_cim_date(bios.get('ReleaseDate'))
    return board,bios

def _windows_storage()->list[dict]:
    x=powershell_json("Get-CimInstance Win32_DiskDrive | Select Model,InterfaceType,MediaType,Size,FirmwareRevision,SerialNumber,PNPDeviceID | ConvertTo-Json -Compress") if os.name=='nt' else None
    if not x:return []
    return x if isinstance(x,list) else [x]

def _cpu_name()->str:
    if os.name=='nt':
        x=powershell_json('Get-CimInstance Win32_Processor | Select-Object -First 1 Name | ConvertTo-Json -Compress')
        if isinstance(x,dict) and x.get('Name'):return str(x['Name']).strip()
    return platform.processor() or platform.uname().processor or 'Unknown CPU'

def collect()->DetectReport:
    vk,vk_devices=_vulkan_summary(); dx=dxgi_info() if os.name=='nt' else {}; adl=amd_adl.collect() if os.name=='nt' else {}
    gpus=_windows_gpus(vk_devices,dx,adl) if os.name=='nt' else []
    board,bios=_windows_board() if os.name=='nt' else ({},{})
    vm=psutil.virtual_memory(); native=find_native_helper()
    tools={n:which(n) for n in ['vulkaninfo','clinfo','llama-server','sd-server','ffmpeg','amdvbflash','nvidia-smi','rocm-smi']};tools['phoenix-forge-native']=native
    caps=capabilities.collect(); cpui=cpu_info() if native else {}
    report=DetectReport(hostname=socket.gethostname(),os=platform.system(),os_version=platform.version(),architecture=platform.machine(),cpu=_cpu_name(),logical_cpus=psutil.cpu_count(True) or 1,physical_cpus=psutil.cpu_count(False),ram_total_bytes=vm.total,gpus=gpus,vulkan_available=vk,motherboard=board,bios=bios,tools=tools,storage=_windows_storage(),capabilities=caps,cpu_features=cpui)
    report.compute_fabric=build_compute_fabric(report)
    return report
