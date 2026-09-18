from __future__ import annotations
import threading, time
from typing import Any
from phoenix_forge.models import StressResult
from phoenix_forge.modules import crucible
from phoenix_forge.modules.watchdog import whea_events

def combined_stress(duration_s:int=30, cpu_workers:int|None=None, gpu_mb:int=256)->StressResult:
    """Run bounded CPU and GPU loads concurrently and compare WHEA before/after."""
    duration_s=max(2,min(int(duration_s),900)); start=time.monotonic(); before=whea_events(10)
    results:dict[str,Any]={}
    def cpu(): results['cpu']=crucible.cpu_stress(duration_s,cpu_workers)
    def gpu():
        r=crucible.gpu_compute_stress(duration_s,gpu_mb,64)
        if not r.passed and str(r.metrics.get('status')) in {'NATIVE_ERROR','NATIVE_HELPER_MISSING'}:
            r=crucible.gpu_stress(duration_s,gpu_mb)
        results['gpu']=r
    t1=threading.Thread(target=cpu,daemon=True);t2=threading.Thread(target=gpu,daemon=True)
    t1.start();t2.start();t1.join(duration_s+150);t2.join(duration_s+150)
    after=whea_events(10)
    cpu_r=results.get('cpu'); gpu_r=results.get('gpu')
    before_count=int(before.get('count') or 0); after_count=int(after.get('count') or 0)
    new_whea=max(0,after_count-before_count)
    passed=bool(cpu_r and cpu_r.passed and gpu_r and gpu_r.passed and new_whea==0)
    return StressResult(module='Phoenix Crucible / Combined',passed=passed,duration_s=time.monotonic()-start,
        metrics={'status':'PASS' if passed else 'FAILED','cpu':cpu_r.model_dump() if cpu_r else None,
                 'gpu':gpu_r.model_dump() if gpu_r else None,'whea_before':before_count,'whea_after':after_count,'new_whea_events':new_whea},
        warnings=[] if new_whea==0 else ['New WHEA hardware error events were observed during/after the combined workload.'])
