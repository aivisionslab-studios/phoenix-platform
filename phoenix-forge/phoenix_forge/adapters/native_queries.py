from __future__ import annotations
import json
from typing import Any
from phoenix_forge.util import find_native_helper, run

def _query(command:str, timeout:int=15)->dict[str,Any]:
    exe=find_native_helper()
    if not exe:return {'passed':False,'error':'native helper missing'}
    c,o,e=run([exe,command],timeout=timeout)
    try:d=json.loads(o)
    except Exception:d={'passed':False,'stdout':o[-4000:],'stderr':e[-4000:]}
    d.setdefault('exit_code',c)
    return d

def _query_args(args:list[str], timeout:int=15)->dict[str,Any]:
    exe=find_native_helper()
    if not exe:return {'passed':False,'error':'native helper missing'}
    c,o,e=run([exe,*args],timeout=timeout)
    try:d=json.loads(o)
    except Exception:d={'passed':False,'stdout':o[-4000:],'stderr':e[-4000:]}
    d.setdefault('exit_code',c)
    return d

def dxgi_info()->dict[str,Any]: return _query('dxgi-info')
def cpu_info()->dict[str,Any]: return _query('cpu-info')

def cpu_deep_info()->dict[str,Any]: return _query('cpu-deep-info')


def cpu_clock_info(samples:int=5, interval_ms:int=200)->dict[str,Any]:
    samples=max(1,min(int(samples),120)); interval_ms=max(10,min(int(interval_ms),5000))
    return _query_args(['cpu-clock-info','--samples',str(samples),'--interval-ms',str(interval_ms)], timeout=max(15, int(samples*interval_ms/1000)+10))
