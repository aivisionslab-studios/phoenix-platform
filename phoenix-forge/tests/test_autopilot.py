from phoenix_forge.models import DetectReport, GPUInfo
from phoenix_forge.modules.autopilot import decide


def test_unvalidated_8gb_vulkan_is_hybrid():
    d = DetectReport(hostname="x", os="Windows", os_version="x", architecture="AMD64", cpu="x", logical_cpus=8,
                     ram_total_bytes=16*1024**3, vulkan_available=True,
                     gpus=[GPUInfo(name="AMD Radeon RX 580", vendor="AMD", adapter_ram_bytes=8*1024**3, vulkan_detected=True)])
    result=decide(d)
    assert result.mode == "HYBRID"
    assert result.policy["gpu_only_allowed"] is False
