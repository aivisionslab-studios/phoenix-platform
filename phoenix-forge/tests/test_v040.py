from phoenix_forge.adapters import capabilities
from phoenix_forge.modules import watchdog
from phoenix_forge.models import GPUInfo, DetectReport

def test_capability_schema():
    d=capabilities.collect()
    assert {'vulkan','opencl','cuda','directx'} <= set(d)

def test_whea_non_windows_safe():
    d=watchdog.whea_events(5,5)
    assert 'events' in d

def test_gpu_provenance_fields():
    g=GPUInfo(name='x',sources={'pci':'test'},dxgi={'dedicated_video_memory_bytes':1},vendor_details={'provider':'x'})
    assert g.sources['pci']=='test'
