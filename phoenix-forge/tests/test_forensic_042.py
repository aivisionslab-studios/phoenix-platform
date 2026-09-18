from pathlib import Path

from phoenix_forge.adapters.amd_adl import _dedupe_adapters
from phoenix_forge.models import DetectReport, GPUInfo, StressResult
from phoenix_forge.modules.autopilot import decide

ROOT = Path(__file__).resolve().parents[1]
CPP = (ROOT / "native" / "src" / "main.cpp").read_text(encoding="utf-8")


def _report():
    return DetectReport(hostname="x", os="Windows", os_version="x", architecture="AMD64",
        cpu="x", logical_cpus=24, ram_total_bytes=32*1024**3, vulkan_available=True,
        gpus=[GPUInfo(name="RX 580 2048SP", vendor_id="1002", device_id="6FDF",
            vulkan_detected=True, vulkan_primary_device_local_bytes=int(7.75*1024**3))])


def test_native_forensic_fields_present():
    for field in ("error_details", "xor_mask_hex", "logical_byte_offset", "differing_bits",
                  "address_coverage_percent", "continue_on_error"):
        assert field in CPP


def test_memory_error_blocks_gpu_only():
    failed = StressResult(module="Phoenix Memory / VRAM Map", passed=False, duration_s=1,
        metrics={"status":"MEMORY_ERROR", "sample_errors":1, "full_scan":True})
    decision = decide(_report(), [failed])
    assert decision.mode == "CPU"
    assert decision.policy["vram_health"] == "SUSPECTED_UNSTABLE"
    assert decision.policy["gpu_only_allowed"] is False


def test_adl_endpoints_are_one_physical_adapter():
    raw=[]
    for index in range(7):
        suffix="" if index==0 else f"&{index+1:02X}"
        raw.append({"index":index,"bus":3,"device":0,"function":0,
            "pnp":f"PCI\\VEN_1002&DEV_6FDF&SUBSYS_0B311002&REV_EF\\4&ABC&0&0010{suffix}",
            "display":f"\\\\.\\DISPLAY{index+1}","udid":str(index)})
    physical=_dedupe_adapters(raw)
    assert len(physical)==1
    assert physical[0]["logical_endpoint_count"]==7
