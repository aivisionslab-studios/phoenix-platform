from __future__ import annotations
import json
import time
from phoenix_forge.models import StressResult
from phoenix_forge.util import find_native_helper, run, adaptive_vram_timeout

def _tracked(result:StressResult,device:int=0)->StressResult:
    from phoenix_forge.modules.gpu_safety import record_result
    try:
        from phoenix_forge.modules import detect
        report=detect.collect(); gpu=report.gpus[device] if 0 <= int(device) < len(report.gpus) else None
    except Exception:
        gpu=None
    return record_result(result,gpu)


def ram_test(size_mb:int=256,passes:int=2)->StressResult:
    size_mb=max(16,min(int(size_mb),8192)); passes=max(1,min(int(passes),50)); n=size_mb*1024*1024; start=time.monotonic()
    buf=bytearray(n); patterns=[0x00,0xFF,0xAA,0x55,0x33,0xCC]
    try:
        for pno in range(passes):
            for pat in patterns:
                buf[:] = bytes([pat])*n
                step=max(1,n//1048576)
                for i in range(0,n,step):
                    if buf[i]!=pat:
                        return StressResult(module='Phoenix Memory / RAM',passed=False,duration_s=time.monotonic()-start,metrics={'status':'MEMORY_ERROR','size_mb':size_mb,'pass':pno,'offset':i,'expected':pat,'actual':buf[i]})
        return StressResult(module='Phoenix Memory / RAM',passed=True,duration_s=time.monotonic()-start,metrics={'status':'PASS','size_mb':size_mb,'passes':passes,'patterns':patterns},warnings=['User-space allocation test; it does not replace boot-time exhaustive RAM diagnostics.'])
    finally: del buf


def _classify_native(code:int,data:dict,stderr:str)->str:
    if code==124:return 'TIMEOUT'
    explicit=data.get('status')
    if explicit:return str(explicit)
    if data.get('passed'):return 'PASS'
    err=str(data.get('error') or stderr or '').lower()
    if 'budget' in err:return 'BUDGET_EXHAUSTED'
    if 'allocate' in err:return 'ALLOCATION_FAILED'
    if int(data.get('sample_errors') or 0)>0:return 'MEMORY_ERROR'
    if 'driver' in err or 'device lost' in err:return 'DRIVER_ERROR'
    return 'NATIVE_ERROR'


def _warnings_for_status(status:str)->list[str]:
    if status=='QUICK_PASS':
        return ['Quick sampled validation found no mismatch, but this is not proof of healthy VRAM. Run a full scan for stronger evidence.']
    if status=='FULL_SCAN_PASS':
        return ['A full address scan completed without mismatch for this run. Repetition and advanced patterns are still required before certifying VRAM health.']
    if status=='TIMEOUT':
        return ['Native VRAM validation timed out; timeout alone is not evidence of defective memory.']
    if status=='ALLOCATION_FAILED':
        return ['Vulkan allocation failed before a useful test could be performed; this is not proof of defective VRAM.']
    if status=='BUDGET_EXHAUSTED':
        return ['The requested resident VRAM target could not be fully reserved. The successfully validated resident portion remains useful evidence.']
    if status=='DRIVER_ERROR':
        return ['The GPU/driver reported an execution failure. Re-test at a smaller target and inspect system logs before classifying hardware.']
    if status=='MEMORY_ERROR':
        return ['One or more data mismatches were detected during readback validation. Re-run to confirm reproducibility before drawing a hardware conclusion.']
    return []


def native_vram_test(size_mb:int=512,passes:int=2,native_exe:str|None=None,full_scan:bool=False,device:int=0,continue_on_error:bool=False,max_errors:int=64)->StressResult:
    native_exe=find_native_helper(native_exe)
    if not native_exe:
        return _tracked(StressResult(module='Phoenix Memory / VRAM',passed=False,duration_s=0,metrics={'status':'NATIVE_HELPER_MISSING','device_index':int(device)},warnings=['Build native/ with Vulkan SDK to enable device-local VRAM validation.']),device)
    start=time.monotonic(); cmd=[native_exe,'vram-test','--mb',str(size_mb),'--passes',str(passes),'--device',str(device)]
    if full_scan: cmd.append('--full-scan')
    if continue_on_error: cmd.append('--continue-on-error')
    cmd.extend(['--max-errors',str(max(0,min(int(max_errors),4096)))])
    timeout=adaptive_vram_timeout(size_mb,passes,full_scan)
    c,o,e=run(cmd,timeout=timeout)
    try:data=json.loads(o)
    except Exception:data={'stdout':o[-4000:],'stderr':e[-4000:]}
    data['status']=_classify_native(c,data,e);data['timeout_s']=timeout;data['device_index']=int(device)
    warnings=_warnings_for_status(data['status'])
    if c!=0 and not warnings:warnings.append('Native device-local VRAM test returned an error.')
    return _tracked(StressResult(module='Phoenix Memory / VRAM',passed=(data['status'] in {'PASS','QUICK_PASS','FULL_SCAN_PASS'}),duration_s=time.monotonic()-start,metrics=data,warnings=warnings),device)


def vram_sweep(start_mb:int=256,stop_mb:int=4096,step_mb:int=256,passes:int=1,native_exe:str|None=None,full_scan:bool=False,device:int=0)->StressResult:
    native_exe=find_native_helper(native_exe); st=time.monotonic(); rows=[]; max_stable=0
    if not native_exe:return StressResult(module='Phoenix Memory / VRAM Sweep',passed=False,duration_s=0,metrics={'status':'NATIVE_HELPER_MISSING'})
    for mb in range(max(16,start_mb),max(start_mb,stop_mb)+1,max(16,step_mb)):
        r=native_vram_test(mb,passes,native_exe,full_scan,device=device)
        rows.append({'mb':mb,'passed':r.passed,'status':r.metrics.get('status'),'details':r.metrics})
        if r.passed:max_stable=mb
        else:break
    return StressResult(module='Phoenix Memory / VRAM Sweep',passed=max_stable>=start_mb,duration_s=time.monotonic()-st,metrics={'status':'PASS' if max_stable>=start_mb else 'FAILED','max_stable_mb':max_stable,'steps':rows})


def vram_map(chunk_mb:int=256,target_mb:int=0,passes:int=1,native_exe:str|None=None,full_scan:bool=False,device:int=0,adaptive:bool=False,min_chunk_mb:int=128,reserve_mb:int=512,continue_on_error:bool=False,max_errors:int=64)->StressResult:
    """Validate logical windows while keeping multiple Vulkan allocations resident.

    The map is logical, not a physical GDDR IC/address map. Phoenix Forge uses multiple
    resident device-local allocations so targets larger than a single-allocation
    limit can be exercised. When adaptive=True, allocation size is reduced down
    to min_chunk_mb after allocation failures.
    """
    native_exe=find_native_helper(native_exe); st=time.monotonic()
    if not native_exe:return _tracked(StressResult(module='Phoenix Memory / VRAM Map',passed=False,duration_s=0,metrics={'status':'NATIVE_HELPER_MISSING','device_index':int(device)}),device)
    chunk_mb=max(16,int(chunk_mb)); target_mb=max(0,int(target_mb)); passes=max(1,int(passes)); min_chunk_mb=max(16,min(int(min_chunk_mb),chunk_mb)); reserve_mb=max(0,int(reserve_mb))
    cmd=[native_exe,'vram-map','--chunk-mb',str(chunk_mb),'--target-mb',str(target_mb),'--passes',str(passes),'--device',str(device),'--min-chunk-mb',str(min_chunk_mb),'--reserve-mb',str(reserve_mb)]
    if full_scan:cmd.append('--full-scan')
    if adaptive:cmd.append('--adaptive')
    if continue_on_error:cmd.append('--continue-on-error')
    cmd.extend(['--max-errors',str(max(0,min(int(max_errors),4096)))])
    effective_target=target_mb if target_mb>0 else 6144
    # Multi-allocation full scans can be long. Keep a generous but finite guard.
    timeout=min(21600,max(420,int(240+effective_target*0.50*passes if full_scan else 360+effective_target*0.10*passes)))
    c,o,e=run(cmd,timeout=timeout)
    try:data=json.loads(o)
    except Exception:data={'stdout':o[-12000:],'stderr':e[-12000:]}
    status=_classify_native(c,data,e); data['status']=status; data['timeout_s']=timeout; data['device_index']=int(device)
    warnings=['Ranges are logical Vulkan allocation windows; they are not guaranteed to correspond to physical GDDR chip addresses.']
    warnings.extend(_warnings_for_status(status))
    if data.get('allocated_mb') is not None and data.get('target_mb') is not None and int(data.get('allocated_mb') or 0) < int(data.get('target_mb') or 0):
        warnings.append('Only part of the requested target became resident; use allocated_mb/validated_mb when computing a safe runtime budget.')
    return _tracked(StressResult(module='Phoenix Memory / VRAM Map',passed=(status in {'PASS','QUICK_PASS','FULL_SCAN_PASS'}),duration_s=time.monotonic()-st,metrics=data,warnings=warnings),device)
