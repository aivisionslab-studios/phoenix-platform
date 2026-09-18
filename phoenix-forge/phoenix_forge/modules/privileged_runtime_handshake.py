from __future__ import annotations
import ctypes, os, platform
from ctypes import wintypes
SCHEMA="phoenix.forge.privileged-runtime-handshake/v1"
DEVICE=r"\\.\PhoenixForgeMsr"
ABI_VERSION=1
CAP_APERF_MPERF=1
IOCTL_GET_INFO=((0x8337<<16)|(1<<14)|(0x800<<2))
class INFO(ctypes.Structure):
    _pack_=1
    _fields_=[("abi_version",ctypes.c_uint32),("struct_size",ctypes.c_uint32),("capability_bits",ctypes.c_uint64)]
def probe():
    out={"schema":SCHEMA,"device":DEVICE,"status":"MISSING","driver_present":False,"abi_match":False,"capabilities":[],"trusted_runtime_ready":False,"policy":{"read_only_probe":True,"no_install":True,"no_service_start":True,"no_signing_bypass":True,"missing_driver_is_not_hardware_failure":True,"decision_influence_enabled":False}}
    if os.name!="nt": out["status"]="UNSUPPORTED_HOST";out["host"]=platform.system();return out
    k=ctypes.WinDLL("kernel32",use_last_error=True)
    h=k.CreateFileW(DEVICE,0x80000000,3,None,3,0x80,None)
    if h==ctypes.c_void_p(-1).value: out["windows_error"]=ctypes.get_last_error();return out
    try:
        out["driver_present"]=True; info=INFO(); ret=wintypes.DWORD()
        ok=k.DeviceIoControl(h,IOCTL_GET_INFO,None,0,ctypes.byref(info),ctypes.sizeof(info),ctypes.byref(ret),None)
        if not ok: out["status"]="HANDSHAKE_FAILED";out["windows_error"]=ctypes.get_last_error();return out
        out["abi_version"]=int(info.abi_version);out["capability_bits"]=int(info.capability_bits);out["abi_match"]=info.abi_version==ABI_VERSION and info.struct_size==ctypes.sizeof(INFO)
        if info.capability_bits & CAP_APERF_MPERF: out["capabilities"].append("clock.aperf_mperf")
        out["status"]="ABI_READY_UNTRUSTED" if out["abi_match"] else "ABI_MISMATCH";return out
    finally: k.CloseHandle(h)
