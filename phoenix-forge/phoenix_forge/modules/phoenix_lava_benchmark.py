from __future__ import annotations
from phoenix_forge import __version__
import json,time,urllib.request
from pathlib import Path
from typing import Any
import psutil
from phoenix_forge.modules import phoenix_lava_runtime_manager as runtime
SCHEMA='phoenix.forge.phoenix-lava-benchmark/v2'
DEFAULT_SUITE=(
 'Explain in one short paragraph what Phoenix LaVa Foundation is.',
 'List three practical advantages of hybrid CPU/GPU inference, concisely.',
 'Given 17, 29, 41, and 53, compute their sum and explain the arithmetic briefly.',
)
def _results_path()->Path:return runtime._state_dir()/'benchmarks.jsonl'
def _snapshot()->dict[str,Any]:
    vm=psutil.virtual_memory();st=runtime._load_state()
    return {'available_ram_bytes':int(vm.available),'percent_ram_used':float(vm.percent),'runtime_state':{'mode':st.get('mode'),'quantization':st.get('quantization'),'context_tokens':st.get('context_tokens'),'threads':st.get('threads'),'device':st.get('device'),'parallel':st.get('parallel')}}
def _run_one(*,quantization:str,port:int,prompt:str,max_tokens:int,timeout_s:float)->dict[str,Any]:
    url=f'http://127.0.0.1:{int(port)}/v1/chat/completions';body={'model':runtime.DEFAULT_ALIAS,'messages':[{'role':'user','content':str(prompt)}],'max_tokens':max(8,int(max_tokens)),'temperature':0.0,'stream':False};data=json.dumps(body).encode('utf-8');req=urllib.request.Request(url,data=data,headers={'Content-Type':'application/json','User-Agent':f'Phoenix-Forge/{__version__}'},method='POST');started=time.perf_counter()
    with urllib.request.urlopen(req,timeout=max(5.0,float(timeout_s))) as r:raw=r.read(4*1024*1024);code=int(getattr(r,'status',200))
    elapsed=time.perf_counter()-started;parsed=json.loads(raw.decode('utf-8','replace'));usage=parsed.get('usage') or {};timings=parsed.get('timings') or {};ct=int(usage.get('completion_tokens') or timings.get('predicted_n') or 0);pt=int(usage.get('prompt_tokens') or timings.get('prompt_n') or 0);eval_tps=timings.get('predicted_per_second')
    if eval_tps is None and ct>0 and elapsed>0:eval_tps=ct/elapsed
    return {'status':'PASS' if 200<=code<300 else 'HTTP_ERROR','http_status':code,'elapsed_seconds':round(elapsed,4),'prompt_tokens':pt,'completion_tokens':ct,'prompt_eval_tokens_per_second':timings.get('prompt_per_second'),'eval_tokens_per_second':eval_tps,'model':parsed.get('model'),'finish_reason':((parsed.get('choices') or [{}])[0].get('finish_reason')),'response_preview':str(((parsed.get('choices') or [{}])[0].get('message') or {}).get('content') or '')[:500]}
def benchmark_current(*,quantization:str,confirm=False,port=8082,prompt=DEFAULT_SUITE[0],max_tokens=96,timeout_s=300.0)->dict[str,Any]:
    if not confirm:return {'schema':SCHEMA,'status':'CONFIRMATION_REQUIRED','quantization':quantization,'endpoint':f'http://127.0.0.1:{int(port)}/v1/chat/completions','automatic':False}
    q=str(quantization or '').upper()
    if q not in {'Q5_K_M','Q6_K'}:raise ValueError(f'unsupported quantization: {q}')
    managed=runtime.managed_status(port=port)
    if managed.get('endpoint',{}).get('status')!='ONLINE':return {'schema':SCHEMA,'status':'RUNTIME_OFFLINE','managed':managed}
    state=managed.get('state') or {};state_q=str(state.get('quantization') or '').upper()
    if state_q and state_q!=q:return {'schema':SCHEMA,'status':'QUANTIZATION_MISMATCH','requested':q,'running':state_q}
    env=_snapshot();result=_run_one(quantization=q,port=port,prompt=prompt,max_tokens=max_tokens,timeout_s=timeout_s);result.update({'schema':SCHEMA,'timestamp':time.time(),'quantization':q,'port':int(port),'prompt':prompt,'environment':env,'automatic':False})
    p=_results_path();p.parent.mkdir(parents=True,exist_ok=True)
    with p.open('a',encoding='utf-8') as f:f.write(json.dumps(result,ensure_ascii=False)+'\n')
    return result
def benchmark_suite_current(*,quantization:str,confirm=False,port=8082,max_tokens=96,timeout_s=300.0,prompts:list[str]|None=None)->dict[str,Any]:
    if not confirm:return {'schema':'phoenix.forge.phoenix-lava-benchmark-suite/v1','status':'CONFIRMATION_REQUIRED','quantization':quantization,'automatic':False}
    prompts=list(prompts or DEFAULT_SUITE);rows=[];started=time.perf_counter()
    for prompt in prompts:rows.append(benchmark_current(quantization=quantization,confirm=True,port=port,prompt=prompt,max_tokens=max_tokens,timeout_s=timeout_s))
    passed=[r for r in rows if r.get('status')=='PASS'];avg=sum(float(r.get('eval_tokens_per_second') or 0) for r in passed)/len(passed) if passed else None
    return {'schema':'phoenix.forge.phoenix-lava-benchmark-suite/v1','status':'PASS' if len(passed)==len(rows) else 'PARTIAL','quantization':quantization,'cases':rows,'case_count':len(rows),'pass_count':len(passed),'average_eval_tokens_per_second':avg,'elapsed_seconds':round(time.perf_counter()-started,3),'quality_winner':None,'policy':{'no_quality_winner_from_speed_only':True,'responses_recorded_for_manual_or_future_quality_evaluation':True}}
def history(limit=50)->dict[str,Any]:
    p=_results_path();rows=[]
    if p.is_file():
        for line in p.read_text(encoding='utf-8',errors='replace').splitlines():
            try:rows.append(json.loads(line))
            except Exception:pass
    rows=rows[-max(1,min(int(limit),1000)):];return {'schema':'phoenix.forge.phoenix-lava-benchmark-history/v1','status':'READY','count':len(rows),'results':rows}
def compare_latest()->dict[str,Any]:
    rows=history(1000)['results'];latest={}
    for row in rows:
        q=row.get('quantization')
        if q in {'Q5_K_M','Q6_K'} and row.get('status')=='PASS':latest[q]=row
    delta=None
    if len(latest)==2:
        a=float(latest['Q5_K_M'].get('eval_tokens_per_second') or 0);b=float(latest['Q6_K'].get('eval_tokens_per_second') or 0)
        if a>0:delta=((b-a)/a)*100.0
    return {'schema':'phoenix.forge.phoenix-lava-benchmark-comparison/v2','status':'READY' if len(latest)==2 else 'MORE_EVIDENCE_REQUIRED','latest':latest,'q6_vs_q5_eval_tps_delta_percent':delta,'quality_winner':None,'policy':{'no_quality_winner_from_speed_only':True,'same_prompt_and_runtime_conditions_recommended':True}}
def capabilities()->dict[str,Any]:return {'schema':SCHEMA,'status':'RUNTIME_DEPENDENT','features':['CURRENT_ENDPOINT_BENCHMARK','MULTI_PROMPT_SUITE','ENVIRONMENT_SNAPSHOT','TIMINGS_CAPTURE','JSONL_HISTORY','Q5_Q6_SIDE_BY_SIDE'],'policy':{'explicit_confirmation_required':True,'no_automatic_model_switch':True,'no_quality_winner_from_speed_only':True,'localhost_only':True}}
