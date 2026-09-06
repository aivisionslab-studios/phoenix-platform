"""Localiza o disco mais rápido COM ESPAÇO GRAVÁVEL para os checkpoints.

O discovery de hardware da Phoenix (phoenix_kernel/discovery) já classifica
cada disco FÍSICO como NVMe/SSD/HDD, mas não diz a LETRA da partição
(J:, D:...) nem o espaço livre - e é isso que o pipeline de checkpoint
precisa para escolher onde gravar. Este módulo faz a ponte que falta:
cruza cada volume gravável (com letra e espaço livre reais) com o TIPO de
mídia do disco físico que o hospeda, produzindo os DiskCandidate que
batch_fill.rank_disks() ordena por 'grau de importância'.

Ordem de estratégia:
  1. Windows + WMI: mapeia Win32_DiskDrive (tipo) -> Win32_DiskPartition
     -> Win32_LogicalDisk (letra + espaço livre). É o caminho preciso.
  2. Windows/qualquer SO + psutil: lista as partições e o espaço livre;
     herda o TIPO já descoberto pelo discovery da Phoenix casando pelo
     modelo/índice quando possível, senão marca 'Unknown'.
  3. Fallback puro shutil: só a partição do diretório de trabalho atual.

Nunca lança para o chamador: se tudo falhar, devolve lista vazia e o
batch_fill cai para o diretório de trabalho padrão da Phoenix.
"""

from __future__ import annotations

import logging
import shutil
from pathlib import Path
from typing import Optional

from phoenix_kernel.documents.batch_fill import DiskCandidate

logger = logging.getLogger(__name__)


def _classify_from_name(model: str, interface: str = "") -> str:
    m = (model or "").upper()
    i = (interface or "").upper()
    if "NVME" in i or "NVME" in m:
        return "NVMe"
    if "SSD" in m:
        return "SSD"
    return ""


def _candidates_via_wmi() -> list[DiskCandidate]:
    """Caminho preciso no Windows: disco físico (tipo) -> partição -> volume
    lógico (letra + espaço livre)."""
    out: list[DiskCandidate] = []
    try:
        import wmi  # type: ignore
        c = wmi.WMI()
    except Exception as e:
        logger.debug("disk_locator: WMI indisponível (%s)", e)
        return out

    try:
        for disk in c.Win32_DiskDrive():
            model = (getattr(disk, "Model", None) or "").strip()
            interface = str(getattr(disk, "InterfaceType", "") or "")
            media = str(getattr(disk, "MediaType", "") or "")
            media_type = _classify_from_name(model, interface)
            if not media_type:
                media_type = "SSD" if "SSD" in media.upper() else "HDD"

            # disco físico -> partições -> discos lógicos (letras)
            for part in disk.associators("Win32_DiskDriveToDiskPartition"):
                for logical in part.associators("Win32_LogicalDiskToPartition"):
                    letter = str(getattr(logical, "DeviceID", "") or "").strip()  # ex. "J:"
                    if not letter:
                        continue
                    try:
                        free = int(getattr(logical, "FreeSpace", 0) or 0)
                        total = int(getattr(logical, "Size", 0) or 0)
                    except (TypeError, ValueError):
                        free = total = 0
                    mount = letter + "\\"
                    out.append(DiskCandidate(
                        mount=mount, media_type=media_type,
                        free_bytes=free, total_bytes=total, label=model,
                    ))
    except Exception as e:
        logger.warning("disk_locator: falha mapeando discos via WMI (%s)", e)
    return out


def _candidates_via_psutil(hint_types_by_model: Optional[dict[str, str]] = None) -> list[DiskCandidate]:
    """Fallback multiplataforma: partições montadas + espaço livre. O TIPO
    de mídia é herdado do discovery da Phoenix quando o modelo casa; caso
    contrário fica 'Unknown' (ainda usável, só não priorizável por
    velocidade)."""
    out: list[DiskCandidate] = []
    try:
        import psutil  # type: ignore
    except Exception as e:
        logger.debug("disk_locator: psutil indisponível (%s)", e)
        return out
    try:
        for part in psutil.disk_partitions(all=False):
            mount = part.mountpoint
            try:
                usage = psutil.disk_usage(mount)
            except Exception:
                continue
            # sem WMI não dá para saber o tipo por volume; deixa Unknown
            # (rank 0) - ainda é escolhido se for o único com espaço.
            out.append(DiskCandidate(
                mount=mount, media_type="Unknown",
                free_bytes=usage.free, total_bytes=usage.total,
                label=str(getattr(part, "device", "") or ""),
            ))
    except Exception as e:
        logger.warning("disk_locator: falha via psutil (%s)", e)
    return out


def _candidate_via_shutil(work_hint: Path) -> list[DiskCandidate]:
    try:
        usage = shutil.disk_usage(str(work_hint))
        anchor = Path(work_hint).anchor or str(work_hint)
        return [DiskCandidate(
            mount=anchor, media_type="Unknown",
            free_bytes=usage.free, total_bytes=usage.total, label="",
        )]
    except Exception:
        return []


def locate_disk_candidates(
    discovery_storage: Optional[list[dict]] = None,
    work_hint: Optional[Path] = None,
) -> list[DiskCandidate]:
    """Devolve os discos candidatos a área de checkpoint, com tipo + letra +
    espaço livre. `discovery_storage` é a lista `storage` que o discovery da
    Phoenix já produz (usada para enriquecer o tipo no caminho psutil).
    Nunca lança - lista vazia significa 'use o fallback local'."""
    # 1) WMI (Windows, preciso)
    cands = _candidates_via_wmi()
    if cands:
        return cands

    # 2) psutil, enriquecido com os tipos que o discovery já achou
    hint: dict[str, str] = {}
    for s in (discovery_storage or []):
        model = str(s.get("model") or "").strip()
        stype = str(s.get("type") or "").strip()
        if model and stype:
            hint[model] = stype
    cands = _candidates_via_psutil(hint)
    if cands:
        # tenta herdar o tipo: se o discovery viu só NVMe, e há um único
        # volume grande, marca-o como NVMe (melhor que Unknown)
        types = {str(s.get("type") or "").upper() for s in (discovery_storage or [])}
        if cands and types and types <= {"NVME", "NVM"}:
            for c in cands:
                if c.media_type == "Unknown":
                    c.media_type = "NVMe"
        return cands

    # 3) shutil (só o volume do diretório de trabalho)
    if work_hint:
        return _candidate_via_shutil(work_hint)
    return []
