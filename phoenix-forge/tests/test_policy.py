from phoenix_forge.models import DetectReport,GPUInfo,StressResult
from phoenix_forge.modules.autopilot import decide

def report():
    return DetectReport(hostname='x',os='Windows',os_version='x',architecture='AMD64',cpu='x',logical_cpus=8,ram_total_bytes=16*1024**3,vulkan_available=True,gpus=[GPUInfo(name='RX',vendor_id='1002',device_id='6FDF',adapter_ram_bytes=8*1024**3,vulkan_detected=True,vulkan_memory_heaps=[{'size_bytes':8*1024**3,'device_local':True}])])

def test_gpu_policy():
    d=decide(report(),[StressResult(module='Phoenix Memory / VRAM',passed=True,duration_s=1,metrics={'status':'FULL_SCAN_PASS','requested_mb':6144,'passes':2,'full_scan':True,'address_coverage_percent':100.0})])
    assert d.mode=='GPU'
    assert d.policy['validated_vram_mb']==6144
    assert d.policy['gpu_only_allowed'] is True
