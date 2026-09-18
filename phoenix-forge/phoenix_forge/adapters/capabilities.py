from __future__ import annotations
import ctypes as C
import os, shutil
from typing import Any
from phoenix_forge.util import run, which

def _dll_probe(names: list[str]) -> dict[str, Any]:
    for n in names:
        try:
            C.WinDLL(n) if os.name == 'nt' else C.CDLL(n)
            return {'available': True, 'library': n}
        except Exception:
            pass
    return {'available': False, 'library': None}

def opencl_probe() -> dict[str, Any]:
    if os.name != 'nt':
        lib = None
        for n in ('libOpenCL.so.1','libOpenCL.so'):
            try: lib=C.CDLL(n); break
            except Exception: pass
    else:
        try: lib=C.WinDLL('OpenCL.dll')
        except Exception: lib=None
    if not lib: return {'available': False, 'platform_count': 0}
    try:
        fn=lib.clGetPlatformIDs; fn.argtypes=[C.c_uint,C.c_void_p,C.POINTER(C.c_uint)];fn.restype=C.c_int
        n=C.c_uint(); rc=fn(0,None,C.byref(n))
        return {'available': rc==0 and n.value>0, 'platform_count': int(n.value), 'status': int(rc)}
    except Exception as e:return {'available':False,'platform_count':0,'error':str(e)}

def cuda_probe() -> dict[str, Any]:
    if os.name != 'nt': return _dll_probe(['libcuda.so.1','libcuda.so'])
    return _dll_probe(['nvcuda.dll'])

def directx_probe() -> dict[str, Any]:
    if os.name != 'nt': return {'available':False}
    d3d12=_dll_probe(['d3d12.dll']); dxgi=_dll_probe(['dxgi.dll']); dml=_dll_probe(['DirectML.dll'])
    return {'available': bool(d3d12['available'] and dxgi['available']), 'd3d12':d3d12,'dxgi':dxgi,'directml':dml}

def vulkan_probe() -> dict[str, Any]:
    exe=which('vulkaninfo')
    if not exe:return {'available':False}
    c,o,e=run([exe,'--summary'],timeout=20)
    return {'available':c==0,'tool':exe,'summary':o[-12000:] if c==0 else '', 'error':e[-2000:] if c else ''}

def collect() -> dict[str, Any]:
    return {'vulkan':vulkan_probe(),'opencl':opencl_probe(),'cuda':cuda_probe(),'directx':directx_probe()}
