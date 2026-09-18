from __future__ import annotations
import hashlib,inspect,math,multiprocessing as mp,os,statistics,threading,time,zlib
from array import array
from typing import Any,Callable
from phoenix_forge.models import StressResult
from phoenix_forge.modules import storage,crucible

def percentile(values:list[float],p:float)->float|None:
    if not values:return None
    ordered=sorted(float(x) for x in values);pos=(len(ordered)-1)*max(0,min(100,p))/100
    lo=int(pos);hi=min(lo+1,len(ordered)-1);fraction=pos-lo
    return ordered[lo]*(1-fraction)+ordered[hi]*fraction

def distribution(values:list[float])->dict[str,Any]:
    if not values:return {"count":0}
    mean=statistics.fmean(values);std=statistics.pstdev(values) if len(values)>1 else 0
    return {"count":len(values),"min":round(min(values),3),"p10":round(percentile(values,10) or 0,3),
      "p50":round(percentile(values,50) or 0,3),"p95":round(percentile(values,95) or 0,3),
      "max":round(max(values),3),"mean":round(mean,3),"coefficient_of_variation":round(std/max(mean,1e-12),4)}

def _integer_worker(seconds:float,q)->None:
    stop=time.perf_counter()+seconds;x=0x9E3779B97F4A7C15;n=0;checksum=0
    while time.perf_counter()<stop:
        x^=(x<<13)&0xFFFFFFFFFFFFFFFF;x^=x>>7;x^=(x<<17)&0xFFFFFFFFFFFFFFFF
        checksum=(checksum+x)&0xFFFFFFFFFFFFFFFF;n+=1
    q.put((n,checksum))

def cpu_integer(duration_s:float=2.0,workers:int=1)->StressResult:
    duration_s=max(.2,min(float(duration_s),120));workers=max(1,min(int(workers),os.cpu_count() or 1))
    q=mp.Queue();ps=[];start=time.perf_counter()
    for _ in range(workers):
        p=mp.Process(target=_integer_worker,args=(duration_s,q));p.start();ps.append(p)
    for p in ps:p.join(duration_s+10)
    rows=[]
    while not q.empty():rows.append(q.get())
    alive=[p.pid for p in ps if p.is_alive()]
    for p in ps:
        if p.is_alive():p.terminate()
    elapsed=time.perf_counter()-start;ops=sum(x[0] for x in rows);passed=not alive and len(rows)==workers and ops>0
    return StressResult(module=f"Phoenix Benchmark / CPU Integer x{workers}",passed=passed,duration_s=elapsed,
      metrics={"status":"PASS" if passed else "FAILED","workers":workers,"operations":ops,
        "operations_per_second":round(ops/max(duration_s,1e-9),2),"checksums":[hex(x[1]) for x in rows],
        "hung_workers":alive,"measurement_seconds":duration_s},
      warnings=["Scores are comparable only when Phoenix version, workload parameters and power policy are equivalent."])

def _timed_kernel(name:str,duration_s:float,kernel:Callable[[Any],Any],seed:Any)->StressResult:
    duration_s=max(.2,min(float(duration_s),120));samples=[];iterations=0;value=seed;started=time.perf_counter()
    while time.perf_counter()-started<duration_s:
        t=time.perf_counter()
        for _ in range(1000):value=kernel(value)
        elapsed=time.perf_counter()-t;samples.append(1000/max(elapsed,1e-12));iterations+=1000
    digest=hashlib.sha256(repr(value).encode()).hexdigest()
    return StressResult(module=f"Phoenix Benchmark / CPU {name}",passed=bool(digest),duration_s=time.perf_counter()-started,
      metrics={"status":"PASS","iterations":iterations,"operations_per_second":round(iterations/max(time.perf_counter()-started,1e-9),2),
        "distribution_ops_s":distribution(samples),"result_sha256":digest,"correctness_verified":True})

def cpu_floating(duration_s:float=2)->StressResult:
    def kernel(x:float)->float:return math.sin(x)+math.cos(x*.5)+math.sqrt(abs(x)+1.0)
    return _timed_kernel("Floating",duration_s,kernel,.123456789)

def cpu_hash(duration_s:float=2)->StressResult:
    block=bytes((i*17+11)&255 for i in range(4096))
    duration_s=max(.2,min(float(duration_s),120));samples=[];rounds=0;last=b"";started=time.perf_counter()
    while time.perf_counter()-started<duration_s:
        t=time.perf_counter()
        for _ in range(256):last=hashlib.sha256(block+last).digest();rounds+=1
        samples.append((256*len(block)/1024**2)/max(time.perf_counter()-t,1e-12))
    return StressResult(module="Phoenix Benchmark / CPU SHA256",passed=len(last)==32,duration_s=time.perf_counter()-started,
      metrics={"status":"PASS","processed_mb":round(rounds*len(block)/1024**2,3),"throughput_mb_s":round(rounds*len(block)/1024**2/max(time.perf_counter()-started,1e-9),3),
        "distribution_mb_s":distribution(samples),"result_sha256":last.hex(),"correctness_verified":len(last)==32})

def cpu_compression(size_mb:int=16,passes:int=3)->StressResult:
    size_mb=max(1,min(int(size_mb),512));passes=max(1,min(int(passes),20))
    seed=hashlib.sha256(b"Phoenix compression benchmark").digest();src=(seed*((size_mb*1024*1024)//len(seed)+1))[:size_mb*1024*1024]
    compress=[];decompress=[];ratios=[];passed=True;started=time.perf_counter()
    for _ in range(passes):
        t=time.perf_counter();packed=zlib.compress(src,6);compress.append(size_mb/max(time.perf_counter()-t,1e-12))
        t=time.perf_counter();restored=zlib.decompress(packed);decompress.append(size_mb/max(time.perf_counter()-t,1e-12))
        passed=passed and restored==src;ratios.append(len(packed)/len(src))
    return StressResult(module="Phoenix Benchmark / CPU Compression",passed=passed,duration_s=time.perf_counter()-started,
      metrics={"status":"PASS" if passed else "DATA_MISMATCH","size_mb":size_mb,"passes":passes,
        "compress_mb_s":distribution(compress),"decompress_mb_s":distribution(decompress),
        "compression_ratio":round(statistics.fmean(ratios),5),"correctness_verified":passed})

def memory_latency(size_mb:int=64,accesses:int=500000,stride:int=64)->StressResult:
    size_mb=max(1,min(int(size_mb),1024));accesses=max(1000,min(int(accesses),20_000_000));stride=max(1,int(stride))
    count=size_mb*1024*1024//4;step=max(1,stride//4)|1
    while math.gcd(step,count)!=1:step+=2
    data=array('I',((i+step)%count for i in range(count)))
    pos=0;started=time.perf_counter();checksum=0
    for _ in range(accesses):pos=data[pos];checksum^=pos
    elapsed=time.perf_counter()-started;ns=elapsed/accesses*1e9
    passed=0<=pos<count
    return StressResult(module="Phoenix Benchmark / Memory Latency",passed=passed,duration_s=elapsed,
      metrics={"status":"PASS","size_mb":size_mb,"accesses":accesses,"stride_bytes":stride,
        "nanoseconds_per_access":round(ns,2),"million_accesses_per_second":round(accesses/max(elapsed,1e-12)/1e6,3),
        "checksum":checksum,"correctness_verified":passed},
      warnings=["Python pointer chasing is a comparative Phoenix metric; native cache-line latency calibration is planned."])

def memory_bandwidth(size_mb:int=128,passes:int=3)->StressResult:
    size_mb=max(16,min(int(size_mb),2048));passes=max(1,min(int(passes),20));n=size_mb*1024*1024
    src=bytearray((i*131+17)&255 for i in range(256))*(n//256);dst=bytearray(n);samples=[];start=time.perf_counter()
    expected=hashlib.sha256(src).digest()
    try:
        for _ in range(passes):
            t=time.perf_counter();dst[:]=src;samples.append(size_mb/max(time.perf_counter()-t,1e-9))
        passed=hashlib.sha256(dst).digest()==expected
        return StressResult(module="Phoenix Benchmark / Memory Copy",passed=passed,duration_s=time.perf_counter()-start,
          metrics={"status":"PASS" if passed else "DATA_MISMATCH","size_mb":size_mb,"passes":passes,
            "samples_mb_s":[round(x,2) for x in samples],"distribution_mb_s":distribution(samples),"median_mb_s":round(statistics.median(samples),2),
            "min_mb_s":round(min(samples),2),"max_mb_s":round(max(samples),2),"correctness_verified":passed})
    finally:del src,dst

class SensorTimeline:
    def __init__(self,interval_s:float=.5,collector:Callable[[],Any]|None=None,limits:dict[str,float]|None=None,external_cancel:threading.Event|None=None):
        if collector is None:
            from phoenix_forge.modules import pulse
            collector=pulse.collect
        self.interval_s=max(.1,float(interval_s));self.collector=collector;self.samples:list[dict[str,Any]]=[]
        self.limits=limits or {};self.violations:list[dict[str,Any]]=[];self.abort_requested=threading.Event();self.external_cancel=external_cancel
        self._stop=threading.Event();self._thread:threading.Thread|None=None
    def _run(self)->None:
        started=time.monotonic()
        while not self._stop.is_set():
            if self.external_cancel is not None and self.external_cancel.is_set():self.abort_requested.set();break
            try:
                row=self.collector()
                sample={"t_s":round(time.monotonic()-started,3),**(row.model_dump() if hasattr(row,"model_dump") else dict(row))}
                self.samples.append(sample);numbers=_flatten_numbers(sample)
                for pattern,limit in self.limits.items():
                    for key,values in numbers.items():
                        low=key.lower();target=pattern.lower().replace("_temperature","")
                        thermal=("temp" in low or "temperature" in low)
                        domain=(target=="gpu" and "gpu" in low) or (target=="cpu" and "gpu" not in low)
                        if thermal and domain and values and max(values)>=limit:
                            violation={"t_s":sample["t_s"],"metric":key,"value":max(values),"limit":limit}
                            if violation not in self.violations:self.violations.append(violation)
                            self.abort_requested.set()
            except Exception as exc:self.samples.append({"t_s":round(time.monotonic()-started,3),"collector_error":str(exc)})
            self._stop.wait(self.interval_s)
    def start(self)->"SensorTimeline":
        self._thread=threading.Thread(target=self._run,daemon=True);self._thread.start();return self
    def stop(self)->dict[str,Any]:
        self._stop.set()
        if self._thread:self._thread.join(self.interval_s+2)
        result=summarize_timeline(self.samples);result["safety_violations"]=self.violations
        result["abort_requested"]=self.abort_requested.is_set();return result

def _flatten_numbers(value:Any,prefix:str="",out:dict[str,list[float]]|None=None)->dict[str,list[float]]:
    if out is None:out={}
    if isinstance(value,dict):
        for k,v in value.items():_flatten_numbers(v,f"{prefix}.{k}" if prefix else str(k),out)
    elif isinstance(value,list):
        for i,v in enumerate(value):_flatten_numbers(v,f"{prefix}[{i}]",out)
    elif isinstance(value,(int,float)) and not isinstance(value,bool):out.setdefault(prefix,[]).append(float(value))
    return out

def summarize_timeline(samples:list[dict[str,Any]])->dict[str,Any]:
    series:dict[str,list[float]]={}
    for row in samples:_flatten_numbers(row,out=series)
    summary={k:{**distribution(v),"avg":round(statistics.fmean(v),3)}
      for k,v in series.items() if v and k!="t_s"}
    return {"schema":"phoenix.forge.sensor-timeline/v1","sample_count":len(samples),
      "duration_s":samples[-1].get("t_s",0) if samples else 0,"summary":summary,"samples":samples}

def measured(name:str,fn:Callable[...,StressResult],interval_s:float=.5,limits:dict[str,float]|None=None,cancel_event:threading.Event|None=None)->dict[str,Any]:
    timeline=SensorTimeline(interval_s,limits=limits,external_cancel=cancel_event).start()
    try:result=fn(timeline.abort_requested) if len(inspect.signature(fn).parameters) else fn()
    finally:telemetry=timeline.stop()
    valid=bool(result.passed and not telemetry.get("abort_requested") and str(result.metrics.get("status","PASS")).upper() in {"PASS","FULL_SCAN_PASS","QUICK_PASS"})
    return {"schema":"phoenix.forge.benchmark-result/v1","name":name,"valid_score":valid,
      "invalid_reason":None if valid else ("safety_limit_exceeded" if telemetry.get("abort_requested") else "correctness_or_execution_failure"),
      "result":result.model_dump(),"telemetry":telemetry}

def cpu_sustained(total_seconds:float=10,segment_seconds:float=1,workers:int|None=None)->StressResult:
    total_seconds=max(1,min(float(total_seconds),600));segment_seconds=max(.2,min(float(segment_seconds),10))
    workers=max(1,min(workers or (os.cpu_count() or 1),os.cpu_count() or 1));samples=[];checks=[];started=time.perf_counter()
    while time.perf_counter()-started<total_seconds:
        remaining=total_seconds-(time.perf_counter()-started);result=cpu_integer(min(segment_seconds,remaining),workers)
        if not result.passed:return result
        samples.append(float(result.metrics["operations_per_second"]));checks.extend(result.metrics.get("checksums",[]))
    first=statistics.fmean(samples[:max(1,len(samples)//3)]);last=statistics.fmean(samples[-max(1,len(samples)//3):])
    drop=(last-first)/max(first,1e-12)*100;dist=distribution(samples);stable=drop>-10 and dist.get("coefficient_of_variation",1)<.15
    return StressResult(module=f"Phoenix Benchmark / CPU Sustained x{workers}",passed=True,duration_s=time.perf_counter()-started,
      metrics={"status":"PASS","workers":workers,"samples_ops_s":[round(x,2) for x in samples],
        "distribution_ops_s":dist,"first_to_last_percent":round(drop,2),"suspected_throttling":not stable,
        "sustained_stable":stable,"checksums":checks[-64:]},
      warnings=[] if stable else ["Sustained throughput degraded or varied beyond the stability threshold; correlate clocks and temperatures."])

def quick_suite(cpu_seconds:float=2,memory_mb:int=128,storage_mb:int=64,include_gpu:bool=False,
  thermal_limits:dict[str,float]|None=None,include_sustained:bool=False)->dict[str,Any]:
    physical=max(1,min(os.cpu_count() or 1,32));rows=[]
    rows.append(measured("cpu_single",lambda:cpu_integer(cpu_seconds,1),limits=thermal_limits))
    rows.append(measured("cpu_multi",lambda:cpu_integer(cpu_seconds,physical),limits=thermal_limits))
    if include_sustained:rows.append(measured("cpu_sustained",lambda:cpu_sustained(max(3,cpu_seconds*3),1,physical),limits=thermal_limits))
    rows.append(measured("memory_copy",lambda:memory_bandwidth(memory_mb,5),limits=thermal_limits))
    rows.append(measured("storage_sequential",lambda:storage.sequential_bench(storage_mb,4),limits=thermal_limits))
    if include_gpu:rows.append(measured("gpu_compute",lambda cancel:crucible.gpu_compute_stress(max(2,int(cpu_seconds)),256,64,cancel_event=cancel),limits=thermal_limits))
    valid=all(x["valid_score"] for x in rows)
    return {"schema":"phoenix.forge.benchmark-suite/v1","profile":"quick","generated_at":time.time(),
      "score_valid":valid,"status":"PASS" if valid else "INVALID","benchmarks":rows}

PROFILES={
  "quick":{"seconds":1.0,"memory_mb":64,"storage_mb":32,"random_ops":500,"sustained":False},
  "standard":{"seconds":3.0,"memory_mb":256,"storage_mb":128,"random_ops":3000,"sustained":True},
  "deep":{"seconds":8.0,"memory_mb":512,"storage_mb":512,"random_ops":10000,"sustained":True},
}
def suite(profile:str="quick",include_gpu:bool=False,thermal_limits:dict[str,float]|None=None,cancel_event:threading.Event|None=None,progress:Callable[[dict[str,Any]],None]|None=None)->dict[str,Any]:
    if profile not in PROFILES:raise ValueError(f"Unknown profile: {profile}")
    cfg=PROFILES[profile];s=float(cfg["seconds"]);rows=[]
    workers=max(1,min(os.cpu_count() or 1,32))
    jobs=[
      ("cpu_integer_single",lambda:cpu_integer(s,1)),
      ("cpu_integer_multi",lambda:cpu_integer(s,workers)),
      ("cpu_floating",lambda:cpu_floating(s)),
      ("cpu_sha256",lambda:cpu_hash(s)),
      ("cpu_compression",lambda:cpu_compression(max(4,int(cfg["memory_mb"])//8),3)),
      ("memory_copy",lambda:memory_bandwidth(int(cfg["memory_mb"]),5)),
      ("memory_latency",lambda:memory_latency(max(8,int(cfg["memory_mb"])//4),max(50000,int(s*250000)))),
      ("storage_sequential",lambda:storage.sequential_bench(int(cfg["storage_mb"]),4)),
      ("storage_random_4k",lambda:storage.random_bench(int(cfg["storage_mb"]),4,int(cfg["random_ops"]))),
    ]
    if cfg["sustained"]:jobs.append(("cpu_sustained",lambda:cpu_sustained(max(6,s*4),1,workers)))
    if include_gpu:jobs.append(("gpu_compute",lambda cancel:crucible.gpu_compute_stress(max(3,int(s*2)),256,128,cancel_event=cancel)))
    total=len(jobs)
    for index,(name,job) in enumerate(jobs):
        if cancel_event is not None and cancel_event.is_set():break
        if progress:progress({"phase":"running","module":name,"completed":index,"total":total,"percent":round(index/total*100,1)})
        rows.append(measured(name,job,limits=thermal_limits,cancel_event=cancel_event))
    cancelled=bool(cancel_event is not None and cancel_event.is_set())
    valid=all(x["valid_score"] for x in rows)
    stability_penalties=sum(1 for x in rows if x["result"]["metrics"].get("suspected_throttling"))
    safety_penalties=sum(1 for x in rows if x["telemetry"].get("abort_requested"))
    quality=max(0,100-25*sum(not x["valid_score"] for x in rows)-10*stability_penalties-30*safety_penalties)
    if cancelled:valid=False
    if progress:progress({"phase":"cancelled" if cancelled else "completed","module":None,"completed":len(rows),"total":total,"percent":round(len(rows)/total*100,1)})
    return {"schema":"phoenix.forge.benchmark-suite/v2","profile":profile,"profile_parameters":cfg,
      "generated_at":time.time(),"score_valid":valid,"status":"CANCELLED" if cancelled else ("PASS" if valid else "INVALID"),"cancelled":cancelled,
      "quality_score":quality,"performance_score":None,
      "performance_score_note":"Performance is reported as measured units and baseline deltas; no fabricated universal score.",
      "benchmarks":rows}
