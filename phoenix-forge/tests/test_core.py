from phoenix_forge.util import parse_pnp_ids
from phoenix_forge.models import DetectReport,GPUInfo,StressResult
from phoenix_forge.modules.autopilot import decide

def base(gpu=True,vulkan=True):
    return DetectReport(hostname='x',os='Windows',os_version='10',architecture='AMD64',cpu='x',logical_cpus=8,ram_total_bytes=16*1024**3,vulkan_available=vulkan,gpus=[GPUInfo(name='AMD Radeon RX 580 2048SP',vendor='AMD',vendor_id='1002',device_id='6FDF',adapter_ram_bytes=8*1024**3)] if gpu else [])

def test_parse_pnp():
    x=parse_pnp_ids(r'PCI\VEN_1002&DEV_6FDF&SUBSYS_0B311002&REV_EF')
    assert x['vendor_id']=='1002' and x['device_id']=='6FDF'
    assert x['subsystem_device_id']=='0B31' and x['subsystem_vendor_id']=='1002'

def test_autopilot_gpu():
    assert decide(base(),[]).mode=='HYBRID'

def test_autopilot_vram_failure():
    t=StressResult(module='Phoenix Memory / VRAM',passed=False,duration_s=1)
    assert decide(base(),[t]).mode=='CPU'
    assert decide(base(),[t]).policy['vram_health']=='SUSPECTED_UNSTABLE'

def test_autopilot_cpu():
    assert decide(base(gpu=False,vulkan=False),[]).mode=='CPU'
