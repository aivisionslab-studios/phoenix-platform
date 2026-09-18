from phoenix_forge.models import DetectReport, GPUInfo, StressResult
from phoenix_forge.modules.autopilot import decide
from phoenix_forge.modules.memory import _classify_native


def _report():
    return DetectReport(
        hostname='x', os='Windows', os_version='x', architecture='AMD64', cpu='x',
        logical_cpus=8, ram_total_bytes=16*1024**3, vulkan_available=True,
        gpus=[GPUInfo(name='RX', vendor_id='1002', device_id='6FDF', vulkan_detected=True,
                      vulkan_primary_device_local_bytes=int(7.75*1024**3))])


def test_budget_exhausted_is_inconclusive():
    assert _classify_native(10, {'status':'BUDGET_EXHAUSTED','allocated_mb':5632}, '') == 'BUDGET_EXHAUSTED'
    t=StressResult(module='Phoenix Memory / VRAM Map',passed=False,duration_s=5,metrics={
        'status':'BUDGET_EXHAUSTED','target_mb':6144,'allocated_mb':5632,'validated_mb':5632
    })
    d=decide(_report(),[t])
    assert d.mode == 'HYBRID'
    assert d.policy['validated_vram_mb'] == 5632
    assert any('inconclusive' in r.lower() for r in d.reasons)


def test_memory_error_still_real_failure():
    assert _classify_native(8, {'status':'MEMORY_ERROR','sample_errors':2}, '') == 'MEMORY_ERROR'
