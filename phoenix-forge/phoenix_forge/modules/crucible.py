from __future__ import annotations
import hashlib, multiprocessing as mp, os, time, json
from phoenix_forge.models import StressResult
from phoenix_forge.util import find_native_helper, run, run_supervised

def _tracked_gpu(result:StressResult,device:int=0)->StressResult:
    from phoenix_forge.modules.gpu_safety import record_result
    try:
        from phoenix_forge.modules import detect
        report=detect.collect(); gpu=report.gpus[device] if 0 <= int(device) < len(report.gpus) else None
    except Exception:
        gpu=None
    return record_result(result,gpu)


def _burn(stop:float,q):
    n=0; b=os.urandom(4096)
    while time.monotonic()<stop:
        b=hashlib.sha512(b).digest()*64; n+=1
    q.put(n)


def cpu_stress(duration_s:int=10,workers:int|None=None)->StressResult:
    duration_s=max(1,min(int(duration_s),900)); cpu=os.cpu_count() or 2
    workers=max(1,min(workers or max(1,cpu-1),cpu)); start=time.monotonic(); stop=start+duration_s; q=mp.Queue(); ps=[]
    for _ in range(workers):
        p=mp.Process(target=_burn,args=(stop,q)); p.start(); ps.append(p)
    for p in ps:p.join(duration_s+10)
    loops=sum(q.get() for _ in range(workers) if not q.empty())
    alive=[p.pid for p in ps if p.is_alive()]
    for p in ps:
        if p.is_alive(): p.terminate()
    return StressResult(module='Phoenix Crucible / CPU',passed=not alive,duration_s=time.monotonic()-start,
        metrics={'status':'PASS' if not alive else 'TIMEOUT','workers':workers,'iterations':loops,'hung_workers':alive},warnings=['Bounded workload. Monitor thermals and stop if cooling/power delivery is unsafe.'])


def gpu_stress(duration_s:int=20,mb:int=256,native_exe:str|None=None,device:int=0)->StressResult:
    native_exe=find_native_helper(native_exe)
    if not native_exe:
        return _tracked_gpu(StressResult(module='Phoenix Crucible / GPU',passed=False,duration_s=0,metrics={'status':'NATIVE_HELPER_MISSING','device_index':int(device)},warnings=['Build the native Vulkan helper first.']),device)
    st=time.monotonic(); c,o,e=run([native_exe,'gpu-stress','--seconds',str(max(1,min(duration_s,900))),'--mb',str(max(16,mb)),'--device',str(int(device))],timeout=min(1100,duration_s+120))
    try:d=json.loads(o)
    except Exception:d={'stdout':o[-4000:],'stderr':e[-4000:]}
    if c==124:d['status']='TIMEOUT'
    elif d.get('passed'):d['status']='PASS'
    elif 'allocate' in str(d.get('error','')).lower():d['status']='ALLOCATION_FAILED'
    else:d['status']='NATIVE_ERROR'
    d['device_index']=int(device)
    return _tracked_gpu(StressResult(module='Phoenix Crucible / GPU',passed=(d['status']=='PASS'),duration_s=time.monotonic()-st,metrics=d,warnings=[] if c==0 else ['GPU stress helper returned an error.']),device)


def gpu_compute_stress(duration_s:int=20,mb:int=256,rounds:int=64,native_exe:str|None=None,cancel_event=None,device:int=0)->StressResult:
    native_exe=find_native_helper(native_exe)
    if not native_exe:
        return _tracked_gpu(StressResult(module='Phoenix Crucible / GPU Compute',passed=False,duration_s=0,metrics={'status':'NATIVE_HELPER_MISSING','device_index':int(device)}),device)
    from pathlib import Path
    exe_path=Path(native_exe).resolve();candidates=[exe_path.parent/'stress.spv',exe_path.parent.parent/'stress.spv',
      Path(__file__).resolve().parents[2]/'native'/'build'/'stress.spv']
    shader=next((str(p) for p in candidates if p.is_file()),str(candidates[0]))
    st=time.monotonic(); cmd=[native_exe,'gpu-compute-stress','--seconds',str(max(1,min(duration_s,900))),'--mb',str(max(16,mb)),'--rounds',str(max(1,min(rounds,4096))),'--shader',shader,'--device',str(int(device))]
    c,o,e,supervision=run_supervised(cmd,timeout=min(1200,duration_s+180),cancel_event=cancel_event)
    try:d=json.loads(o)
    except Exception:d={'stdout':o[-4000:],'stderr':e[-4000:]}
    d['supervision']=supervision
    if c==125:d['status']='SAFETY_ABORT'
    elif c==124:d['status']='TIMEOUT'
    elif d.get('passed'):d['status']='PASS'
    elif str(d.get('status','')).upper()=='COMPUTE_MISMATCH':d['status']='COMPUTE_MISMATCH'
    elif 'device lost' in str(d.get('error','')).lower():d['status']='DRIVER_ERROR'
    elif 'allocate' in str(d.get('error','')).lower():d['status']='ALLOCATION_FAILED'
    else:d['status']='NATIVE_ERROR'
    d['device_index']=int(device)
    warning=[] if d['status']=='PASS' else (['Phoenix Forge encerrou a GPU porque o limite de segurança foi atingido.'] if d['status']=='SAFETY_ABORT' else ['Vulkan compute stress did not complete cleanly.'])
    return _tracked_gpu(StressResult(module='Phoenix Crucible / GPU Compute',passed=(d['status']=='PASS'),duration_s=time.monotonic()-st,metrics=d,warnings=warning),device)
