from __future__ import annotations
import statistics, time, httpx
from phoenix_forge.models import AIBenchResult


def bench_openai_chat(base_url='http://127.0.0.1:8081/v1',model='local',prompt='Explain Vulkan compute in exactly thirty words.',max_tokens=128,runs:int=3,warmup:bool=True)->AIBenchResult:
    url=base_url.rstrip('/')+'/chat/completions'; payload={'model':model,'messages':[{'role':'user','content':prompt}],'temperature':0,'max_tokens':max_tokens}
    samples=[]; usages=[]; total_start=time.monotonic()
    try:
        with httpx.Client(timeout=240) as c:
            count=max(1,min(int(runs),10)) + (1 if warmup else 0)
            for i in range(count):
                st=time.monotonic(); r=c.post(url,json=payload); r.raise_for_status(); d=r.json(); el=time.monotonic()-st
                if warmup and i==0: continue
                u=d.get('usage') or {}; tok=u.get('completion_tokens')
                samples.append({'latency_s':el,'tokens':tok,'tps':(tok/el if tok and el else None)})
                usages.append(u)
        tps=[x['tps'] for x in samples if x['tps'] is not None]; lat=[x['latency_s'] for x in samples]
        return AIBenchResult(backend=url,passed=True,latency_s=statistics.mean(lat),tokens_per_second=(statistics.mean(tps) if tps else None),details={'runs':samples,'usage':usages,'model':model,'wall_s':time.monotonic()-total_start})
    except Exception as e:return AIBenchResult(backend=url,passed=False,latency_s=time.monotonic()-total_start,details={'error':str(e)})


def bench_sd_api(base_url='http://127.0.0.1:7860',prompt='a phoenix forged from molten metal, technical benchmark image',width=512,height=512,steps=10,runs:int=1)->AIBenchResult:
    url=base_url.rstrip('/')+'/sdapi/v1/txt2img'; samples=[]; st0=time.monotonic()
    try:
        with httpx.Client(timeout=1200) as c:
            for _ in range(max(1,min(int(runs),5))):
                st=time.monotonic();r=c.post(url,json={'prompt':prompt,'width':width,'height':height,'steps':steps,'batch_size':1});r.raise_for_status();d=r.json();el=time.monotonic()-st
                samples.append({'latency_s':el,'images':len(d.get('images',[]))})
        return AIBenchResult(backend=url,passed=all(x['images']>0 for x in samples),latency_s=statistics.mean(x['latency_s'] for x in samples),details={'width':width,'height':height,'steps':steps,'runs':samples})
    except Exception as e:return AIBenchResult(backend=url,passed=False,latency_s=time.monotonic()-st0,details={'error':str(e)})
