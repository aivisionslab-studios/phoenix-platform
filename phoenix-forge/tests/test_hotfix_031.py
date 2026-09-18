from phoenix_forge.util import adaptive_vram_timeout, parse_cim_date
from phoenix_forge.models import DetectReport, GPUInfo, StressResult
from phoenix_forge.modules.autopilot import decide


def test_adaptive_timeout_scales_for_full_scan():
    assert adaptive_vram_timeout(2048,1,True) > 330
    assert adaptive_vram_timeout(3072,1,True) > adaptive_vram_timeout(2048,1,True)


def test_cim_date_conversion():
    assert parse_cim_date('/Date(1779235200000)/') == '2026-05-20'


def _report():
    return DetectReport(hostname='x',os='Windows',os_version='x',architecture='AMD64',cpu='x',logical_cpus=8,ram_total_bytes=16*1024**3,vulkan_available=True,gpus=[GPUInfo(name='RX',vendor_id='1002',device_id='6FDF',vulkan_detected=True,vulkan_primary_device_local_bytes=int(7.75*1024**3))])


def test_timeout_is_inconclusive_not_memory_corruption():
    t=StressResult(module='Phoenix Memory / VRAM',passed=False,duration_s=330,metrics={'status':'TIMEOUT','requested_mb':2048})
    d=decide(_report(),[t])
    assert d.mode == 'HYBRID'
    assert any('inconclusive' in r.lower() for r in d.reasons)


def test_confirmed_memory_error_is_failure():
    t=StressResult(module='Phoenix Memory / VRAM',passed=False,duration_s=1,metrics={'status':'MEMORY_ERROR','sample_errors':4})
    d=decide(_report(),[t])
    assert d.mode == 'CPU'
    assert any('confirmed instability' in r.lower() for r in d.reasons)
