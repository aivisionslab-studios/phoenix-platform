from __future__ import annotations
import hashlib
from pathlib import Path
from typing import Any
from phoenix_forge.modules import detect, compute_fabric, gpu_qualification, post_flash_qualification, vbios, vbios_dump

SCHEMA='phoenix.forge.vbios-dossier/v1'

def capabilities() -> dict[str, Any]:
    return {
        'schema': SCHEMA,
        'status': 'READY',
        'actions': {
            'analyze_rom': True,
            'read_only_amd_dump_when_tool_available': True,
            'pre_post_snapshot': True,
            'post_flash_qualification': True,
            'firmware_flash': False,
            'firmware_unlock': False,
        },
        'policy': {
            'read_only': True,
            'flash_never_automatic': True,
            'device_key_is_identity': True,
            'device_index_is_operational_only': True,
            'oom_is_not_corruption': True,
            'single_mismatch_is_not_physical_defect_proof': True,
        },
    }

def analyze(path: str | Path) -> dict[str, Any]:
    p=Path(path)
    report=vbios.parse_vbios(p)
    report.update({'schema':SCHEMA,'mode':'ROM_FILE_ANALYSIS','read_only':True})
    return report

def inventory() -> dict[str, Any]:
    d=detect.collect(); rows=[]
    for index,gpu in enumerate(d.gpus):
        key=gpu.device_key or compute_fabric.stable_device_key(gpu)
        rows.append({'device_index':index,'device_key':key,'name':gpu.name,'vendor_id':gpu.vendor_id,'device_id':gpu.device_id,
                     'subsystem_vendor_id':gpu.subsystem_vendor_id,'subsystem_device_id':gpu.subsystem_device_id,
                     'driver_version':gpu.driver_version,'vram_bytes':gpu.adapter_ram_bytes})
    return {'schema':SCHEMA,'status':'READY','devices':rows,'count':len(rows),'read_only':True}

def capture(*,device_label:str,phase:str,device_index:int=0,vbios_path:str|None=None,memory_clock_mhz:int|None=None,notes:str|None=None)->dict[str,Any]:
    d=detect.collect()
    if device_index < 0 or device_index >= len(d.gpus): raise ValueError('GPU index not found')
    return gpu_qualification.capture(gpu=d.gpus[device_index],device_label=device_label,phase=phase,vbios_path=vbios_path,memory_clock_mhz=memory_clock_mhz,notes=notes)

def compare(device_key:str)->dict[str,Any]: return gpu_qualification.compare(device_key)
def history(device_key:str|None=None,limit:int=50)->dict[str,Any]: return gpu_qualification.history(device_key,limit)
def qualification_plan(device_label:str,device_index:int=0,profile:str='standard')->dict[str,Any]: return post_flash_qualification.plan(device_label,device_index,profile)
def qualification_run(device_label:str,device_index:int=0,profile:str='standard')->dict[str,Any]: return post_flash_qualification.run(device_label,device_index,profile)
def dump_amd_read_only(adapter:int=0,out_path:str='reports/vbios_adapter0.rom')->dict[str,Any]:
    ok,log=vbios_dump.dump_amd(adapter,out_path)
    result={'schema':SCHEMA,'status':'SAVED' if ok else 'UNAVAILABLE','read_only':True,'path':out_path if ok else None,'log':log}
    if ok:
        data=Path(out_path).read_bytes(); result['sha256']=hashlib.sha256(data).hexdigest(); result['size_bytes']=len(data)
    return result
