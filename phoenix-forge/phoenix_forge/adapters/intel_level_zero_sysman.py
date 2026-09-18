from __future__ import annotations

import ctypes
import ctypes.util
import os
import time
from typing import Any

SCHEMA = "phoenix.forge.intel-level-zero-sysman/v1"
ZE_RESULT_SUCCESS = 0


def _candidate_libraries() -> list[str]:
    if os.name == "nt":
        return ["ze_loader.dll"]
    names=[]
    found=ctypes.util.find_library("ze_loader")
    if found: names.append(found)
    names += ["libze_loader.so.1", "libze_loader.so"]
    out=[]
    for x in names:
        if x and x not in out: out.append(x)
    return out


def _load_library():
    errors=[]
    for name in _candidate_libraries():
        try:
            return ctypes.CDLL(name), name, errors
        except Exception as exc:
            errors.append(f"{name}: {exc}")
    return None, None, errors


def _bind(lib: Any, name: str, argtypes: list[Any]):
    fn=getattr(lib,name,None)
    if fn is None: return None
    fn.restype=ctypes.c_int
    fn.argtypes=argtypes
    return fn


def probe() -> dict[str, Any]:
    """Read-only Level Zero Sysman discovery.

    The adapter intentionally enumerates only read operations. It does not call
    reset, frequency setters, power setters, scheduler setters, diagnostics or
    firmware mutation APIs. Temperature handles are returned as raw sensor
    readings unless a future authoritative property decoder identifies the
    sensor type.
    """
    lib, libname, errors=_load_library()
    base={
        "schema":SCHEMA,"generated_at":time.time(),"provider":"Phoenix Intel GPU Deep / Level Zero Sysman",
        "read_only":True,"library":libname,"devices":[],"errors":errors,
        "policy":{
            "no_mutation_calls":True,
            "untyped_temperature_is_not_relabelled_as_edge_or_hotspot":True,
            "ambiguous_multi_device_mapping_is_not_guessed":True,
            "provider_absence_is_not_hardware_failure":True,
        },
    }
    if lib is None:
        return {**base,"status":"RUNTIME_DEPENDENT","reason":"LEVEL_ZERO_LOADER_NOT_FOUND"}
    pvoid=ctypes.c_void_p
    u32p=ctypes.POINTER(ctypes.c_uint32)
    required={
        "zesInit":_bind(lib,"zesInit",[ctypes.c_uint32]),
        "zesDriverGet":_bind(lib,"zesDriverGet",[u32p,ctypes.POINTER(pvoid)]),
        "zesDeviceGet":_bind(lib,"zesDeviceGet",[pvoid,u32p,ctypes.POINTER(pvoid)]),
        "zesDeviceEnumTemperatureSensors":_bind(lib,"zesDeviceEnumTemperatureSensors",[pvoid,u32p,ctypes.POINTER(pvoid)]),
        "zesTemperatureGetState":_bind(lib,"zesTemperatureGetState",[pvoid,ctypes.POINTER(ctypes.c_double)]),
    }
    missing=[k for k,v in required.items() if v is None]
    if missing:
        return {**base,"status":"RUNTIME_DEPENDENT","reason":"SYSMAN_SYMBOLS_MISSING","missing_symbols":missing}
    try:
        rc=required["zesInit"](0)
        if rc!=ZE_RESULT_SUCCESS:
            return {**base,"status":"RUNTIME_DEPENDENT","reason":"ZES_INIT_FAILED","result_code":int(rc)}
        dc=ctypes.c_uint32(0)
        rc=required["zesDriverGet"](ctypes.byref(dc),None)
        if rc!=ZE_RESULT_SUCCESS or dc.value==0:
            return {**base,"status":"RUNTIME_DEPENDENT","reason":"NO_SYSMAN_DRIVER","result_code":int(rc)}
        drivers=(pvoid*dc.value)()
        rc=required["zesDriverGet"](ctypes.byref(dc),drivers)
        if rc!=ZE_RESULT_SUCCESS:
            return {**base,"status":"RUNTIME_DEPENDENT","reason":"DRIVER_ENUM_FAILED","result_code":int(rc)}
        devices=[]
        for di in range(dc.value):
            count=ctypes.c_uint32(0)
            rc=required["zesDeviceGet"](drivers[di],ctypes.byref(count),None)
            if rc!=ZE_RESULT_SUCCESS: continue
            handles=(pvoid*count.value)() if count.value else []
            if count.value:
                rc=required["zesDeviceGet"](drivers[di],ctypes.byref(count),handles)
                if rc!=ZE_RESULT_SUCCESS: continue
            for ordinal in range(count.value):
                h=handles[ordinal]
                tc=ctypes.c_uint32(0)
                temps=[]
                trc=required["zesDeviceEnumTemperatureSensors"](h,ctypes.byref(tc),None)
                if trc==ZE_RESULT_SUCCESS and tc.value:
                    th=(pvoid*tc.value)()
                    trc=required["zesDeviceEnumTemperatureSensors"](h,ctypes.byref(tc),th)
                    if trc==ZE_RESULT_SUCCESS:
                        for ti in range(tc.value):
                            value=ctypes.c_double(0.0)
                            vrc=required["zesTemperatureGetState"](th[ti],ctypes.byref(value))
                            if vrc==ZE_RESULT_SUCCESS and -50.0 < value.value < 200.0:
                                temps.append(round(float(value.value),3))
                devices.append({
                    "driver_ordinal":di,"device_ordinal":ordinal,
                    "temperature_sensors_c":temps,
                    "temperature_sensor_count":len(temps),
                    "mapping_identity":"UNAVAILABLE_WITHOUT_AUTHORITATIVE_DEVICE_PROPERTY_MATCH",
                })
        return {**base,"status":"READY" if devices else "RUNTIME_DEPENDENT",
                "reason":None if devices else "NO_SYSMAN_DEVICE","devices":devices}
    except Exception as exc:
        return {**base,"status":"RUNTIME_DEPENDENT","reason":"SYSMAN_CALL_ERROR","errors":errors+[repr(exc)]}


def collect_for_gpu(gpu: Any, *, intel_gpu_count: int, probe_result: dict[str,Any] | None=None) -> dict[str,Any]:
    if str(getattr(gpu,"vendor","") or "").upper() != "INTEL":
        return {"schema":SCHEMA,"status":"NOT_INTEL","mapped":False,"telemetry":{},"source":"none"}
    p=probe_result if probe_result is not None else probe()
    rows=list(p.get("devices") or [])
    result={
        "schema":SCHEMA,"status":p.get("status"),"provider":p.get("provider"),"source":"LEVEL_ZERO_SYSMAN",
        "mapped":False,"mapping_status":"UNMAPPED","telemetry":{},"raw_device_count":len(rows),
        "policy":p.get("policy") or {},"reason":p.get("reason"),
    }
    # Deliberately conservative. Without a decoded UUID/BDF/name contract, an
    # ordinal match across multiple GPUs is not evidence of identity.
    if intel_gpu_count==1 and len(rows)==1:
        result["mapped"]=True
        result["mapping_status"]="SINGLE_INTEL_GPU_SINGLE_SYSMAN_DEVICE"
        result["telemetry"]={"temperature_sensors_c":list(rows[0].get("temperature_sensors_c") or [])}
    elif len(rows)>0:
        result["mapping_status"]="AMBIGUOUS_MULTI_DEVICE_MAPPING"
        result["reason"]="authoritative Level Zero device identity mapping not yet available; ordinal matching is prohibited"
    return result
