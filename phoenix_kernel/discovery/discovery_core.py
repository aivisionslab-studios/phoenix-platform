import psutil
import platform
import hashlib
import shutil
import subprocess
import re
import os
import tempfile
import time
from dataclasses import dataclass, field
from typing import Optional, List, Dict, Any

@dataclass
class CPUInfo:
    model: Optional[str] = None
    physical_cores: Optional[int] = None
    logical_cores: Optional[int] = None

@dataclass
class GPUInfo:
    model: Optional[str] = None
    vram_mb: Optional[int] = None
    vendor: Optional[str] = None
    supports_vulkan: bool = False

@dataclass
class MemoryInfo:
    total_mb: Optional[int] = None

@dataclass
class StorageDeviceInfo:
    device: Optional[str] = None        # ex: "C:\\" ou "/dev/sda1"
    model: Optional[str] = None         # nome do disco físico (só Windows/WMI)
    media_type: Optional[str] = None    # "SSD", "HDD" ou None se não detectável
    total_gb: Optional[float] = None
    used_gb: Optional[float] = None
    free_gb: Optional[float] = None
    fstype: Optional[str] = None

@dataclass
class HardwareSnapshot:
    cpu: CPUInfo = field(default_factory=CPUInfo)
    gpus: List[GPUInfo] = field(default_factory=list)
    memory: MemoryInfo = field(default_factory=MemoryInfo)
    storage: List[StorageDeviceInfo] = field(default_factory=list)

@dataclass
class MachineIdentity:
    machine_id: str = "AHDC-UNKNOWN-0000-0000"


class HardwareDiscoveryCore:
    def __init__(self):
        self._profile = None

    # ------------------------------------------------------------------
    # GPU DISCOVERY
    # ------------------------------------------------------------------
    def _get_gpu_raw(self) -> List[Dict[str, Any]]:
        results = []
        try:
            import wmi
            c = wmi.WMI()
            for gpu in c.Win32_VideoController():
                name = getattr(gpu, "Name", None)
                if not name:
                    continue

                # 1. Tenta ler a VRAM via WMI (limitado a 4GB no Windows,
                #    porque AdapterRAM é um campo de 32 bits)
                vram_bytes = getattr(gpu, "AdapterRAM", None)
                if vram_bytes and vram_bytes < 0:
                    vram_bytes = vram_bytes + (1 << 32)

                vram_mb = int(vram_bytes / (1024 * 1024)) if vram_bytes else None

                # 2. Se o WMI travou em ~4GB (ou não retornou nada),
                #    usa o dxdiag -- a MESMA fonte que o Gerenciador de
                #    Tarefas usa para mostrar "Memória da GPU dedicada".
                #    Isso evita o limite de 32 bits do WMI e não depende
                #    do Vulkan SDK estar instalado.
                if vram_mb is None or vram_mb <= 4096:
                    dxdiag_vram = self._get_vram_via_dxdiag(name)
                    if dxdiag_vram:
                        vram_mb = dxdiag_vram

                results.append({
                    "name": name,
                    "vram_mb": vram_mb
                })
        except Exception:
            pass
        return results

    def _get_vram_via_dxdiag(self, gpu_name: str) -> Optional[int]:
        """
        Roda 'dxdiag /t <arquivo>' e extrai 'Dedicated Memory' do bloco
        correspondente à GPU pelo nome. Retorna VRAM em MB ou None.

        Resultado é cacheado em disco (%TEMP%/aivisions_vram_cache.json),
        já que a VRAM real não muda entre execuções na mesma máquina e o
        dxdiag sem a flag /x faz uma varredura completa do sistema
        (pode levar 30-60s).
        """
        cache_path = os.path.join(tempfile.gettempdir(), "aivisions_vram_cache.json")
        try:
            if os.path.exists(cache_path):
                import json
                with open(cache_path, 'r', encoding='utf-8') as f:
                    cache = json.load(f)
                if gpu_name in cache:
                    return cache[gpu_name]
        except Exception:
            pass

        tmp_path = os.path.join(tempfile.gettempdir(), "aivisions_dxdiag.txt")
        try:
            if os.path.exists(tmp_path):
                os.remove(tmp_path)

            subprocess.run(
                ['dxdiag', '/t', tmp_path],
                timeout=30,
                creationflags=0x08000000  # CREATE_NO_WINDOW
            )

            # dxdiag escreve o arquivo de forma assíncrona internamente;
            # espera até 10s pelo arquivo aparecer e ter conteúdo.
            for _ in range(20):
                if os.path.exists(tmp_path) and os.path.getsize(tmp_path) > 0:
                    break
                time.sleep(0.5)

            if not os.path.exists(tmp_path):
                return None

            with open(tmp_path, 'r', encoding='utf-8', errors='ignore') as f:
                dxdiag_text = f.read()

            # O relatório tem um bloco por dispositivo de vídeo, iniciado
            # por "Card name: <nome>". Divide o texto nesses blocos e
            # procura o que corresponde à GPU que estamos processando.
            blocks = dxdiag_text.split("Card name:")
            gpu_key = gpu_name.split()[0].lower()  # ex: "AMD" ou "NVIDIA"

            for block in blocks[1:]:
                first_line = block.strip().splitlines()[0].lower() if block.strip() else ""
                if gpu_key in first_line or gpu_name.lower() in block.lower()[:300]:
                    match = re.search(r'Dedicated Memory:\s*(\d+)\s*MB', block)
                    if match:
                        vram_mb = int(match.group(1))
                        self._save_vram_cache(cache_path, gpu_name, vram_mb)
                        return vram_mb

            return None
        except Exception:
            return None
        finally:
            try:
                if os.path.exists(tmp_path):
                    os.remove(tmp_path)
            except Exception:
                pass

    @staticmethod
    def _save_vram_cache(cache_path: str, gpu_name: str, vram_mb: int) -> None:
        import json
        try:
            cache = {}
            if os.path.exists(cache_path):
                with open(cache_path, 'r', encoding='utf-8') as f:
                    cache = json.load(f)
            cache[gpu_name] = vram_mb
            with open(cache_path, 'w', encoding='utf-8') as f:
                json.dump(cache, f)
        except Exception:
            pass

    def _get_physical_disks_raw(self) -> List[Dict[str, Any]]:
        """
        Modelo e tipo de mídia (SSD/HDD) dos discos físicos via WMI, no
        namespace root\\Microsoft\\Windows\\Storage — a MESMA fonte que o
        Get-PhysicalDisk do PowerShell usa (MediaType 3=HDD, 4=SSD).
        Só funciona no Windows; em qualquer outro caso (SO diferente, WMI
        indisponível) devolve lista vazia, e _get_storage_raw() ainda
        funciona com o que o psutil dá (sem saber SSD ou HDD).
        """
        results = []
        try:
            import wmi
            c = wmi.WMI(namespace="root\\Microsoft\\Windows\\Storage")
            media_type_map = {0: "Unspecified", 3: "HDD", 4: "SSD", 5: "SCM"}
            for disk in c.MSFT_PhysicalDisk():
                # BUG CORRIGIDO: o WMI devolve campos UINT64 (como 'Size')
                # como STRING, não número — sem essa conversão, size_bytes
                # ficava string e quebrava mais na frente na hora de dividir
                # por (1024 ** 3) (TypeError: str / int).
                raw_size = getattr(disk, "Size", None)
                try:
                    size_bytes = int(raw_size) if raw_size is not None else None
                except (TypeError, ValueError):
                    size_bytes = None

                results.append({
                    "model": getattr(disk, "FriendlyName", None),
                    "media_type": media_type_map.get(getattr(disk, "MediaType", 0), "Unknown"),
                    "size_bytes": size_bytes,
                })
        except Exception:
            pass
        return results

    def _get_storage_raw(self) -> List["StorageDeviceInfo"]:
        """
        Junta as partições montadas (psutil.disk_partitions — funciona em
        qualquer SO, dá device/fstype/espaço usado-livre) com modelo e
        tipo de mídia dos discos físicos (WMI, só Windows). Como não tem
        um jeito barato de casar "letra de drive" -> "disco físico" sem
        WMI mais pesado (Win32_LogicalDiskToPartition), a correspondência
        aqui é por tamanho aproximado — é uma heurística simples, não
        garantia, mas suficiente pra rotular SSD vs HDD na maioria dos
        casos com poucos discos.
        """
        physical = self._get_physical_disks_raw()

        try:
            partitions = psutil.disk_partitions(all=False)
        except Exception:
            partitions = []

        devices = []
        for p in partitions:
            try:
                usage = psutil.disk_usage(p.mountpoint)
            except Exception:
                continue

            model, media_type = None, None
            total_gb = usage.total / (1024 ** 3)
            for disk in physical:
                size_gb = (disk.get("size_bytes") or 0) / (1024 ** 3)
                if size_gb and abs(size_gb - total_gb) < size_gb * 0.15:
                    model = disk.get("model")
                    media_type = disk.get("media_type")
                    break

            devices.append(StorageDeviceInfo(
                device=p.device,
                model=model,
                media_type=media_type,
                total_gb=round(total_gb, 1),
                used_gb=round(usage.used / (1024 ** 3), 1),
                free_gb=round(usage.free / (1024 ** 3), 1),
                fstype=p.fstype,
            ))

        return devices

    # ------------------------------------------------------------------
    # FULL DISCOVERY
    # ------------------------------------------------------------------
    def discover(self):
        vm = psutil.virtual_memory()
        raw_gpus = self._get_gpu_raw()
        gpus = []
        for g in raw_gpus:
            name = g.get("name", "")
            vendor = "Unknown"
            if "nvidia" in name.lower() or "geforce" in name.lower():
                vendor = "NVIDIA"
            if "amd" in name.lower() or "radeon" in name.lower():
                vendor = "AMD"
            if "intel" in name.lower():
                vendor = "Intel"

            gpus.append(GPUInfo(
                model=name,
                vram_mb=g.get("vram_mb"),
                vendor=vendor,
                # PHX-FIX (varredura 2026-08-21, achado 3): isto checa só a
                # PRESENÇA do binário `vulkaninfo` no PATH, não se o
                # driver/GPU de fato suporta e roda Vulkan de verdade - uma
                # máquina com o binário instalado mas um stack Vulkan quebrado
                # reportaria True; uma com Vulkan funcional mas sem o binário
                # de diagnóstico reportaria False. Acerta na maioria dos
                # casos reais, mas o nome do campo promete mais do que esta
                # checagem garante - documentado aqui pra quem for usar este
                # campo mais adiante.
                supports_vulkan=shutil.which("vulkaninfo") is not None
            ))

        cpu_info = CPUInfo(
            model=platform.processor(),
            physical_cores=psutil.cpu_count(logical=False),
            logical_cores=psutil.cpu_count(logical=True)
        )

        hardware = HardwareSnapshot(
            cpu=cpu_info,
            gpus=gpus,
            memory=MemoryInfo(total_mb=int(vm.total / (1024 * 1024))),
            storage=self._get_storage_raw(),
        )

        machine_id = self._compute_identity(hardware)
        self._profile = type(
            'Profile', (), {'hardware': hardware, 'machine_identity': MachineIdentity(machine_id)}
        )()
        return self._profile

    def _compute_identity(self, hardware: HardwareSnapshot) -> str:
        components = [
            hardware.cpu.model or "unknown",
            str(hardware.memory.total_mb or 0),
            hardware.gpus[0].model if hardware.gpus else "no_gpu"
        ]
        raw = "|".join(components).lower()
        digest = hashlib.sha256(raw.encode('utf-8')).hexdigest().upper()
        return "AHDC-" + "-".join([digest[i:i + 4] for i in range(0, 16, 4)])

    def machine_identity(self) -> str:
        if not self._profile:
            return "AHDC-UNKNOWN-0000-0000"
        return self._profile.machine_identity.machine_id

    def hardware_hash(self) -> str:
        if not self._profile:
            return "sha256:unknown"
        import json
        from dataclasses import asdict
        data = asdict(self._profile.hardware)
        data.pop("generated_at", None)
        return "sha256:" + hashlib.sha256(json.dumps(data, sort_keys=True).encode('utf-8')).hexdigest()