from __future__ import annotations
import json,time
from phoenix_forge.models import StressResult
from phoenix_forge.util import find_native_helper,run_supervised

def execute(kind:str,seconds:int=3,threads:int=0,mb:int=256,passes:int=5,accesses:int=2_000_000,
            native_exe:str|None=None,cancel_event=None,device:int=0)->StressResult:
    exe=find_native_helper(native_exe)
    if not exe:return StressResult(module=f'Phoenix Native / {kind}',passed=False,duration_s=0,metrics={'status':'NATIVE_HELPER_MISSING'})
    commands={'cpu':['cpu-bench','--seconds',str(max(1,seconds)),'--threads',str(max(0,threads))],
      'memory':['memory-bench','--mb',str(max(1,mb)),'--passes',str(max(1,passes))],
      'cache':['cache-bench','--mb',str(max(1,mb)),'--accesses',str(max(10000,accesses))],
      'vram-bandwidth':['vram-bandwidth','--mb',str(max(16,mb)),'--seconds',str(max(1,seconds)),'--device',str(int(device))]}
    if kind not in commands:raise ValueError(f'Unknown native benchmark: {kind}')
    started=time.monotonic();code,out,err,supervision=run_supervised([exe,*commands[kind]],timeout=max(180,seconds+120),cancel_event=cancel_event)
    try:data=json.loads(out)
    except Exception:data={'passed':False,'stdout':out[-4000:],'stderr':err[-4000:]}
    data['supervision']=supervision;data['device_index']=int(device);data['status']='SAFETY_ABORT' if code==125 else ('TIMEOUT' if code==124 else ('PASS' if data.get('passed') and code==0 else 'FAILED'))
    return StressResult(module=f'Phoenix Native / {kind}',passed=data['status']=='PASS',duration_s=time.monotonic()-started,metrics=data,
      warnings=[] if data['status']=='PASS' else ['Benchmark nativo não produziu uma medição válida.'])
