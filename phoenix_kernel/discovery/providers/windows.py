import os
import shutil
import logging
import platform
from .base import IDiscoveryProvider
from phoenix_kernel.shared.models import HardwareSnapshot, CPUInfo, GPUInfo, MemoryInfo, StorageInfo, MotherboardInfo

logger = logging.getLogger(__name__)


def _get_cpu_info() -> CPUInfo:
    """
    Nome de CPU amigável via WMI. platform.processor() no Windows devolve a
    string crua da CPUID (ex: "Intel64 Family 6 Model 63 Stepping 2,
    GenuineIntel") — é exatamente essa string feia que aparecia no painel
    em vez de "Intel Xeon E5-2690 v3". Win32_Processor.Name tem o nome
    comercial de verdade.
    """
    model = platform.processor() or "Unknown CPU"
    cores = None
    logical = None
    try:
        import wmi
        c = wmi.WMI()
        for cpu in c.Win32_Processor():
            model = (getattr(cpu, "Name", None) or model).strip()
            cores = getattr(cpu, "NumberOfCores", None)
            logical = getattr(cpu, "NumberOfLogicalProcessors", None)
            break
    except Exception as e:
        logger.warning(f"WindowsDiscoveryProvider: falha ao ler CPU via WMI - {e}")

    fallback = os.cpu_count() or 1
    return CPUInfo(
        model=model,
        physical_cores=cores or fallback,
        logical_cores=logical or fallback,
    )


def _get_memory_info() -> MemoryInfo:
    try:
        import psutil
        return MemoryInfo(total_mb=int(psutil.virtual_memory().total / (1024 * 1024)))
    except Exception as e:
        logger.warning(f"WindowsDiscoveryProvider: falha ao ler memória - {e}")
        return MemoryInfo(total_mb=0)


def _classify_vendor(name: str) -> str:
    n = name.lower()
    if "amd" in n or "radeon" in n:
        return "AMD"
    if "nvidia" in n or "geforce" in n or "rtx" in n or "gtx" in n:
        return "NVIDIA"
    if "intel" in n:
        return "Intel"
    return "Unknown"


def _get_gpu_info() -> list:
    """
    GPU e VRAM total via HardwareMonitor — a MESMA fonte que a telemetria já
    usa e que já funciona (36 sensores lidos, GPU Memory Total = 8192.0 nos
    logs). NÃO via WMI Win32_VideoController.AdapterRAM, que é um inteiro
    de 32 bits e estoura em qualquer GPU com mais de 4GB de VRAM — essa era
    a causa raiz do "GPU: Unknown / VRAM: 0MB" no painel.
    """
    gpus = []
    try:
        import importlib
        hardware_core = importlib.import_module("phoenix_kernel.telemetry.core")
        specs = hardware_core.get_gpu_static_specs()
        supports_vulkan = shutil.which("vulkaninfo") is not None
        for s in specs:
            model = s.get("model", "Unknown GPU")
            gpus.append(GPUInfo(
                model=model,
                vram_mb=s.get("vram_mb", 0),
                vendor=_classify_vendor(model),
                supports_vulkan=supports_vulkan,
            ))
    except Exception as e:
        logger.warning(f"WindowsDiscoveryProvider: falha ao ler GPU via HardwareMonitor - {e}")
    return gpus


def _get_storage_and_motherboard() -> tuple:
    storage = []
    motherboard = MotherboardInfo(model="Unknown", vendor="Unknown")
    try:
        import wmi
        c = wmi.WMI()

        for disk in c.Win32_DiskDrive():
            model_name = (getattr(disk, "Model", None) or "Unknown Disk").strip()
            size_bytes = getattr(disk, "Size", 0)
            try:
                size_gb = round(int(size_bytes) / (1024 ** 3), 1) if size_bytes else 0.0
            except (TypeError, ValueError):
                size_gb = 0.0

            media_type = str(getattr(disk, "MediaType", "") or "")
            interface = str(getattr(disk, "InterfaceType", "") or "Unknown")

            disk_type = "HDD"
            if "SSD" in media_type.upper() or "SSD" in model_name.upper():
                disk_type = "SSD"
            if "NVME" in interface.upper() or "NVME" in model_name.upper():
                disk_type = "NVMe"

            storage.append(StorageInfo(model=model_name, size_gb=size_gb, type=disk_type, interface=interface))

        for mb in c.Win32_BaseBoard():
            motherboard = MotherboardInfo(
                model=(getattr(mb, "Product", None) or "Unknown"),
                vendor=(getattr(mb, "Manufacturer", None) or "Unknown"),
            )
    except Exception as e:
        logger.warning(f"WindowsDiscoveryProvider: falha ao ler discos/placa-mãe via WMI - {e}")

    return storage, motherboard


class WindowsDiscoveryProvider(IDiscoveryProvider):
    def discover(self) -> HardwareSnapshot:
        cpu = _get_cpu_info()
        memory = _get_memory_info()
        gpus = _get_gpu_info()
        storage, motherboard = _get_storage_and_motherboard()

        return HardwareSnapshot(
            cpu=cpu,
            gpus=gpus,
            memory=memory,
            storage=storage,
            motherboard=motherboard,
            available_backends=["cpu", "vulkan"] if any(g.supports_vulkan for g in gpus) else ["cpu"],
        )
