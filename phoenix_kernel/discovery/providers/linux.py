import glob
import os
import re
import json
import shutil
import subprocess
import logging
from .base import IDiscoveryProvider
from phoenix_kernel.shared.models import HardwareSnapshot, CPUInfo, GPUInfo, MemoryInfo, StorageInfo, MotherboardInfo

logger = logging.getLogger(__name__)


def _run(cmd: list) -> str:
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=5)
        return result.stdout
    except Exception as e:
        logger.debug(f"LinuxDiscoveryProvider: comando {cmd} falhou - {e}")
        return ""


def _get_cpu_info() -> CPUInfo:
    model = "Unknown CPU"
    try:
        with open("/proc/cpuinfo", "r") as f:
            for line in f:
                if line.lower().startswith("model name"):
                    model = line.split(":", 1)[1].strip()
                    break
    except Exception as e:
        logger.warning(f"LinuxDiscoveryProvider: falha ao ler /proc/cpuinfo - {e}")

    logical = os.cpu_count() or 1
    physical = logical
    try:
        import psutil
        physical = psutil.cpu_count(logical=False) or logical
    except Exception:
        pass

    return CPUInfo(model=model, physical_cores=physical, logical_cores=logical)


def _get_memory_info() -> MemoryInfo:
    try:
        import psutil
        return MemoryInfo(total_mb=int(psutil.virtual_memory().total / (1024 * 1024)))
    except Exception as e:
        logger.warning(f"LinuxDiscoveryProvider: falha ao ler memória via psutil - {e}")
        # fallback sem psutil: /proc/meminfo
        try:
            with open("/proc/meminfo") as f:
                for line in f:
                    if line.startswith("MemTotal:"):
                        kb = int(line.split()[1])
                        return MemoryInfo(total_mb=kb // 1024)
        except Exception:
            pass
        return MemoryInfo(total_mb=0)


def _classify_vendor(name: str) -> str:
    n = name.lower()
    if "amd" in n or "ati" in n or "radeon" in n:
        return "AMD"
    if "nvidia" in n:
        return "NVIDIA"
    if "intel" in n:
        return "Intel"
    return "Unknown"


def _clean_pci_name(raw: str) -> str:
    """lspci -mm devolve nome com IDs de PCI colados entre colchetes (ex:
    'Advanced Micro Devices, Inc. [AMD/ATI] [1002]') — tira isso pra ficar
    um nome limpo de mostrar no painel."""
    return re.sub(r"\s*\[[0-9a-fA-F]{4}\]", "", raw).strip()


def _get_gpu_info() -> list:
    """
    Modelo via `lspci -mm` (formato estável, com aspas, sem parsing frágil
    de coluna). VRAM total via sysfs (/sys/class/drm/cardN/device/
    mem_info_vram_total) — só existe pra GPUs AMD com driver amdgpu;
    NVIDIA/Intel ficam sem VRAM aqui (precisariam de nvidia-smi/outra
    fonte, fora de escopo por agora — fica None em vez de inventar valor).
    """
    gpus = []
    output = _run(["lspci", "-mm"])
    for line in output.splitlines():
        if "VGA compatible controller" not in line and "3D controller" not in line:
            continue
        parts = re.findall(r'"([^"]*)"', line)
        if len(parts) < 3:
            continue
        vendor_raw, device_raw = _clean_pci_name(parts[1]), _clean_pci_name(parts[2])
        model = f"{vendor_raw} {device_raw}".strip()
        gpus.append({"model": model, "vendor": _classify_vendor(vendor_raw)})

    # Varre TODOS os cards DRM (não só card0..card3) em vez de assumir um
    # limite fixo. Importante: o índice do card DRM (cardN) não tem
    # relação garantida com a ordem em que o lspci lista os dispositivos
    # PCI — numa máquina com GPU integrada + discreta, a AMD pode muito
    # bem ser card1 (como confirmado em log real de instalação) enquanto
    # o lspci a lista em primeiro. Por isso a VRAM é atribuída por vendor
    # (AMD), não pelo índice "primeira GPU da lista".
    vram_mb = 0
    for vram_path in sorted(glob.glob("/sys/class/drm/card[0-9]*/device/mem_info_vram_total")):
        try:
            with open(vram_path) as f:
                found_vram = int(f.read().strip()) // (1024 * 1024)
            if found_vram > 0:
                vram_mb = found_vram
                break
        except Exception as e:
            logger.debug(f"LinuxDiscoveryProvider: falha lendo {vram_path} - {e}")

    supports_vulkan = shutil.which("vulkaninfo") is not None
    result = []
    amd_vram_assigned = False
    for g in gpus:
        gpu_vram = 0
        if g["vendor"] == "AMD" and not amd_vram_assigned:
            gpu_vram = vram_mb
            amd_vram_assigned = True
        result.append(GPUInfo(
            model=g["model"],
            vram_mb=gpu_vram,
            vendor=g["vendor"],
            supports_vulkan=supports_vulkan,
        ))
    return result


def _get_storage_info() -> list:
    """Discos físicos via `lsblk -J` (JSON nativo do próprio lsblk, não
    parsing de texto tabular frágil)."""
    storage = []
    output = _run(["lsblk", "-b", "-d", "-J", "-o", "NAME,SIZE,ROTA,MODEL,TRAN"])
    if not output:
        return storage
    try:
        data = json.loads(output)
        for dev in data.get("blockdevices", []):
            size_bytes = dev.get("size") or 0
            try:
                size_gb = round(int(size_bytes) / (1024 ** 3), 1)
            except (TypeError, ValueError):
                size_gb = 0.0

            tran = (dev.get("tran") or "").lower()
            rota = dev.get("rota")
            if tran == "nvme":
                disk_type = "NVMe"
            elif rota in (True, "1", 1):
                disk_type = "HDD"
            else:
                disk_type = "SSD"

            storage.append(StorageInfo(
                model=(dev.get("model") or "Unknown Disk").strip(),
                size_gb=size_gb,
                type=disk_type,
                interface=tran.upper() if tran else "Unknown",
            ))
    except Exception as e:
        logger.warning(f"LinuxDiscoveryProvider: falha ao interpretar saída do lsblk - {e}")
    return storage


def _get_motherboard_info() -> MotherboardInfo:
    """/sys/class/dmi/id costuma ser legível sem root na maioria das
    distros, mas em algumas fica restrito — sem sudo isso só cai em
    'Unknown' (não quebra nada)."""
    vendor = "Unknown"
    model = "Unknown"
    try:
        with open("/sys/class/dmi/id/board_vendor") as f:
            vendor = f.read().strip() or vendor
    except Exception:
        pass
    try:
        with open("/sys/class/dmi/id/board_name") as f:
            model = f.read().strip() or model
    except Exception:
        pass
    return MotherboardInfo(model=model, vendor=vendor)


class LinuxDiscoveryProvider(IDiscoveryProvider):
    def discover(self) -> HardwareSnapshot:
        gpus = _get_gpu_info()
        return HardwareSnapshot(
            cpu=_get_cpu_info(),
            gpus=gpus,
            memory=_get_memory_info(),
            storage=_get_storage_info(),
            motherboard=_get_motherboard_info(),
            available_backends=["cpu", "vulkan"] if any(g.supports_vulkan for g in gpus) else ["cpu"],
        )
