from __future__ import annotations
import statistics,time
from typing import Any
from phoenix_forge.modules import native_benchmark

def _metric(metrics:dict[str,Any])->float|None:
    for key in ('operations_per_second','bandwidth_gbps','million_accesses_per_second'):
        if metrics.get(key) is not None:return float(metrics[key])
    levels=metrics.get('levels') or []
    if levels and levels[-1].get('million_accesses_per_second') is not None:return float(levels[-1]['million_accesses_per_second'])
    return None

def run(profile:str='standard',native_exe:str|None=None)->dict[str,Any]:
    cfg={'quick':(2,2,64),'standard':(5,3,256),'deep':(15,5,512)}
    if profile not in cfg:raise ValueError('profile must be quick, standard or deep')
    seconds,repeats,mb=cfg[profile];rows=[]
    for kind in ('cpu','memory','cache'):
        samples=[];runs=[]
        for _ in range(repeats):
            r=native_benchmark.execute(kind,seconds=seconds,mb=mb,passes=5,native_exe=native_exe);d=r.model_dump();runs.append(d)
            metric=_metric(d['metrics'])
            if r.passed and metric is not None:samples.append(float(metric))
        mean=statistics.fmean(samples) if samples else 0;cv=statistics.pstdev(samples)/mean if len(samples)>1 and mean else 0
        rows.append({'name':kind,'passed':len(samples)==repeats,'samples':samples,'mean':mean,'peak':max(samples) if samples else None,'cv':cv,'stable':cv<=.10,'runs':runs})
    valid=all(x['passed'] and x['stable'] for x in rows)
    return {'schema':'phoenix.forge.production-benchmark/v1','profile':profile,'generated_at':time.time(),'score_valid':valid,
      'status':'PASS' if valid else 'INVALID','policy':{'repeats':repeats,'maximum_cv':.10,'correctness_required':True},'benchmarks':rows}
