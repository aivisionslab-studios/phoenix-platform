import os
import psutil
import subprocess
import logging

logger = logging.getLogger(__name__)

class InstallTargetSelector:
    def __init__(self):
        self.workspace_name = "AIVisions_Workspace"
        self.apps_dir = "apps"
        self.models_dir = "models"
        self._workspace_path = None

    def _get_disk_priorities(self) -> dict:
        """
        Usa PowerShell para mapear a letra do drive (ex: C:) para a 
        pontuação da interface (NVMe=100, SSD=80, HDD=10).
        Retorna um dict vazio se o PowerShell falhar (fallback seguro).
        """
        priorities = {}
        try:
            ps_cmd = "Get-PhysicalDisk | Select-Object DeviceId, MediaType | ConvertTo-Json"
            res = subprocess.run(["powershell", "-Command", ps_cmd], capture_output=True, text=True, timeout=5)
            if res.returncode == 0 and res.stdout.strip():
                import json
                disks = json.loads(res.stdout)
                if not isinstance(disks, list): disks = [disks]
                
                # Mapeia o DeviceId do disco físico para a pontuação
                disk_scores = {}
                for d in disks:
                    dev_id = str(d.get("DeviceId", "")).upper()
                    media_type = str(d.get("MediaType", "")).lower()
                    score = 10
                    if "nvme" in media_type or "3" in media_type: score = 100
                    elif "ssd" in media_type or "4" in media_type: score = 80
                    disk_scores[dev_id] = score

                # Mapeia as partições (letras) aos discos físicos
                ps_cmd2 = "Get-Partition | Select-Object DriveLetter, DiskId | ConvertTo-Json"
                res2 = subprocess.run(["powershell", "-Command", ps_cmd2], capture_output=True, text=True, timeout=5)
                if res2.returncode == 0 and res2.stdout.strip():
                    partitions = json.loads(res2.stdout)
                    if not isinstance(partitions, list): partitions = [partitions]
                    
                    for p in partitions:
                        drive_letter = str(p.get("DriveLetter", "")).upper()
                        disk_id = str(p.get("DiskId", "")).upper()
                        if drive_letter and disk_id in disk_scores:
                            priorities[f"{drive_letter}\\"] = disk_scores[disk_id]
        except Exception as e:
            logger.debug(f"InstallTargetSelector: PowerShell WMI query failed, falling back to space. Err: {e}")
        return priorities

    def get_best_workspace_path(self) -> str:
        if self._workspace_path:
            return self._workspace_path

        best_drive = None
        max_score = -1
        max_free_space = -1

        priorities = self._get_disk_priorities()

        for part in psutil.disk_partitions(all=False):
            if 'cdrom' in part.opts or part.fstype == '':
                continue
            try:
                usage = psutil.disk_usage(part.mountpoint)
                
                # Pega a pontuação da interface (se detectada), senão 0
                score = priorities.get(part.mountpoint.upper(), 0)
                
                # Desempate ou fallback: espaço livre
                if score > max_score or (score == max_score and usage.free > max_free_space):
                    max_score = score
                    max_free_space = usage.free
                    best_drive = part.mountpoint
            except Exception:
                continue
        
        if not best_drive:
            best_drive = "C:\\"

        base_path = os.path.join(best_drive, self.workspace_name)
        apps_path = os.path.join(base_path, self.apps_dir)
        models_path = os.path.join(base_path, self.models_dir)
        os.makedirs(apps_path, exist_ok=True)
        os.makedirs(models_path, exist_ok=True)
        
        self._workspace_path = base_path
        logger.info(f"InstallTargetSelector: Workspace definido em {base_path} (Score: {max_score}, Espaço livre: {max_free_space / (1024**3):.2f} GB)")
        return base_path

    def get_apps_path(self) -> str:
        return os.path.join(self.get_best_workspace_path(), self.apps_dir)