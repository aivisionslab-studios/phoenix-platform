from __future__ import annotations

"""Read-only AMD ADL provider.

This adapter intentionally uses only documented/query-style ADL entry points.  It
never calls tuning, overclock, voltage, fan-set, I2C-write, or flash functions.
Failures are isolated and returned as capability/provenance records instead of
crashing Phoenix Forge.
"""

import ctypes as C
import os
import re
from typing import Any

ADL_OK = 0
ADL_MAX_PATH = 256
ADL_DL_FANCTRL_SPEED_TYPE_PERCENT = 1
ADL_DL_FANCTRL_SPEED_TYPE_RPM = 2

class AdapterInfo(C.Structure):
    _fields_ = [
        ("iSize", C.c_int), ("iAdapterIndex", C.c_int),
        ("strUDID", C.c_char * ADL_MAX_PATH),
        ("iBusNumber", C.c_int), ("iDeviceNumber", C.c_int),
        ("iFunctionNumber", C.c_int), ("iVendorID", C.c_int),
        ("strAdapterName", C.c_char * ADL_MAX_PATH),
        ("strDisplayName", C.c_char * ADL_MAX_PATH),
        ("iPresent", C.c_int), ("iExist", C.c_int),
        ("strDriverPath", C.c_char * ADL_MAX_PATH),
        ("strDriverPathExt", C.c_char * ADL_MAX_PATH),
        ("strPNPString", C.c_char * ADL_MAX_PATH),
        ("iOSDisplayIndex", C.c_int),
    ]

class ADLMemoryInfo(C.Structure):
    _fields_ = [("iMemorySize", C.c_longlong),
                ("strMemoryType", C.c_char * ADL_MAX_PATH),
                ("iMemoryBandwidth", C.c_longlong)]

class ADLBiosInfo(C.Structure):
    _fields_ = [("strPartNumber", C.c_char * ADL_MAX_PATH),
                ("strVersion", C.c_char * ADL_MAX_PATH),
                ("strDate", C.c_char * ADL_MAX_PATH)]

class ADLTemperature(C.Structure):
    _fields_ = [("iSize", C.c_int), ("iTemperature", C.c_int)]

class ADLPMActivity(C.Structure):
    # Public ADL Overdrive5 structure. Clock units are 10 kHz.
    _fields_ = [
        ("iSize", C.c_int), ("iEngineClock", C.c_int),
        ("iMemoryClock", C.c_int), ("iVddc", C.c_int),
        ("iActivityPercent", C.c_int), ("iCurrentPerformanceLevel", C.c_int),
        ("iCurrentBusSpeed", C.c_int), ("iCurrentBusLanes", C.c_int),
        ("iMaximumBusLanes", C.c_int), ("iReserved", C.c_int),
    ]

class ADLFanSpeedValue(C.Structure):
    _fields_ = [("iSize", C.c_int), ("iSpeedType", C.c_int),
                ("iFanSpeed", C.c_int), ("iFlags", C.c_int)]

_MALLOC_CB = C.CFUNCTYPE(C.c_void_p, C.c_int)
_allocations: dict[int, Any] = {}

def _alloc(n: int):
    buf = C.create_string_buffer(max(1, n))
    ptr = C.addressof(buf); _allocations[ptr] = buf
    return ptr

_malloc_cb = _MALLOC_CB(_alloc)

def _text(v: bytes) -> str:
    return v.split(b"\0", 1)[0].decode("utf-8", "replace").strip()

class ADLSession:
    def __init__(self):
        self.dll = None; self.initialized = False; self.error = None
        if os.name != "nt":
            self.error = "ADL is a Windows provider in this build"; return
        for name in ("atiadlxx.dll", "atiadlxy.dll"):
            try:
                self.dll = C.WinDLL(name)
                break
            except OSError:
                pass
        if not self.dll:
            self.error = "AMD ADL library not found"; return
        try:
            fn = self.dll.ADL_Main_Control_Create
            fn.argtypes = [_MALLOC_CB, C.c_int]; fn.restype = C.c_int
            rc = fn(_malloc_cb, 1)
            if rc != ADL_OK:
                self.error = f"ADL_Main_Control_Create returned {rc}"; return
            self.initialized = True
        except Exception as exc:
            self.error = f"ADL initialization failed: {exc}"

    def close(self):
        if self.initialized and self.dll:
            try: self.dll.ADL_Main_Control_Destroy()
            except Exception: pass
        self.initialized = False

    def _fn(self, name: str, argtypes, restype=C.c_int):
        if not self.dll: return None
        try: fn = getattr(self.dll, name)
        except AttributeError: return None
        fn.argtypes = argtypes; fn.restype = restype
        return fn

    def adapters(self) -> list[dict[str, Any]]:
        if not self.initialized: return []
        count = C.c_int()
        fcount = self._fn("ADL_Adapter_NumberOfAdapters_Get", [C.POINTER(C.c_int)])
        finfo = self._fn("ADL_Adapter_AdapterInfo_Get", [C.POINTER(AdapterInfo), C.c_int])
        if not fcount or not finfo or fcount(C.byref(count)) != ADL_OK or count.value <= 0:
            return []
        arr = (AdapterInfo * count.value)()
        for a in arr: a.iSize = C.sizeof(AdapterInfo)
        if finfo(arr, C.sizeof(arr)) != ADL_OK: return []
        return [dict(index=a.iAdapterIndex, name=_text(a.strAdapterName), udid=_text(a.strUDID),
                     pnp=_text(a.strPNPString), bus=a.iBusNumber, device=a.iDeviceNumber,
                     function=a.iFunctionNumber, vendor_id=a.iVendorID, present=bool(a.iPresent),
                     display=_text(a.strDisplayName)) for a in arr]

    def query_adapter(self, index: int) -> dict[str, Any]:
        out: dict[str, Any] = {"adapter_index": index, "provider": "AMD ADL", "read_only": True}
        if not self.initialized:
            out["available"] = False; out["error"] = self.error; return out
        out["available"] = True
        fmem = self._fn("ADL_Adapter_MemoryInfo_Get", [C.c_int, C.POINTER(ADLMemoryInfo)])
        if fmem:
            m = ADLMemoryInfo()
            rc = fmem(index, C.byref(m))
            if rc == ADL_OK:
                out["memory"] = {"size_bytes": int(m.iMemorySize), "type": _text(m.strMemoryType),
                                 "bandwidth_mb_s": int(m.iMemoryBandwidth)}
        fbios = self._fn("ADL_Adapter_VideoBiosInfo_Get", [C.c_int, C.POINTER(ADLBiosInfo)])
        if fbios:
            b = ADLBiosInfo()
            rc = fbios(index, C.byref(b))
            if rc == ADL_OK:
                out["vbios"] = {"part_number": _text(b.strPartNumber),
                                "version": _text(b.strVersion),
                                "date": _text(b.strDate)}
        fact = self._fn("ADL_Overdrive5_CurrentActivity_Get", [C.c_int, C.POINTER(ADLPMActivity)])
        if fact:
            a = ADLPMActivity(); a.iSize = C.sizeof(a)
            rc = fact(index, C.byref(a))
            if rc == ADL_OK:
                out["activity"] = {"gpu_clock_mhz": a.iEngineClock / 100.0,
                                   "memory_clock_mhz": a.iMemoryClock / 100.0,
                                   "vddc_mv": a.iVddc, "gpu_util_percent": a.iActivityPercent,
                                   "pcie_speed_code": a.iCurrentBusSpeed,
                                   "pcie_lanes": a.iCurrentBusLanes,
                                   "pcie_max_lanes": a.iMaximumBusLanes}
        ftemp = self._fn("ADL_Overdrive5_Temperature_Get", [C.c_int, C.c_int, C.POINTER(ADLTemperature)])
        if ftemp:
            t = ADLTemperature(); t.iSize = C.sizeof(t)
            rc = ftemp(index, 0, C.byref(t))
            if rc == ADL_OK: out["temperature_c"] = t.iTemperature / 1000.0
        ffan = self._fn("ADL_Overdrive5_FanSpeed_Get", [C.c_int, C.c_int, C.POINTER(ADLFanSpeedValue)])
        if ffan:
            fan = ADLFanSpeedValue(); fan.iSize = C.sizeof(fan)
            fan.iSpeedType = ADL_DL_FANCTRL_SPEED_TYPE_RPM
            rc = ffan(index, 0, C.byref(fan))
            if rc == ADL_OK: out["fan_rpm"] = fan.iFanSpeed
            fan2 = ADLFanSpeedValue(); fan2.iSize = C.sizeof(fan2); fan2.iSpeedType = ADL_DL_FANCTRL_SPEED_TYPE_PERCENT
            rc = ffan(index, 0, C.byref(fan2))
            if rc == ADL_OK: out["fan_percent"] = fan2.iFanSpeed
        return out

def _dedupe_adapters(raw: list[dict[str, Any]]) -> list[dict[str, Any]]:
    groups: dict[tuple[int, int, int, str], list[dict[str, Any]]] = {}
    for adapter in raw:
        # ADL can expose one physical board once per display endpoint.
        # Preserve the endpoints, but collapse them for physical inventory.
        pnp = str(adapter.get("pnp") or "").upper()
        pnp_base = re.sub(r"&0&[0-9A-F]{4}(?:&[0-9A-F]{2})?$", "", pnp)
        key = (int(adapter.get("bus") or -1), int(adapter.get("device") or -1),
               int(adapter.get("function") or -1), pnp_base)
        groups.setdefault(key, []).append(adapter)
    ads = []
    for endpoints in groups.values():
        primary = dict(endpoints[0])
        primary["display_endpoints"] = [
            {"adapter_index": x.get("index"), "display": x.get("display"),
             "udid": x.get("udid"), "pnp": x.get("pnp")}
            for x in endpoints
        ]
        primary["logical_endpoint_count"] = len(endpoints)
        ads.append(primary)
    return ads

def collect() -> dict[str, Any]:
    s = ADLSession()
    try:
        raw = s.adapters()
        ads = _dedupe_adapters(raw)
        return {"provider": "AMD ADL", "available": s.initialized, "error": s.error,
                "raw_adapter_count": len(raw), "physical_adapter_count": len(ads),
                "adapters": [{**a, "telemetry": s.query_adapter(a["index"])} for a in ads]}
    finally:
        s.close()
