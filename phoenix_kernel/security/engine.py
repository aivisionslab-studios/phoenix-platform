import os
import platform
import subprocess
import shutil
import logging
from typing import Any
from .interfaces import ISecurityService

logger = logging.getLogger(__name__)

# PHX-FIX (varredura 2026-08-21 rodada 2, achado #2): duas falhas juntas -
# (1) `except:` genérico ao redor da checagem de admin, exclusiva do
# Windows (`ctypes.windll`), engolia SEMPRE em Linux/macOS (windll não
# existe nesses SOs), reportando `is_admin: False` de um jeito
# indistinguível de "checamos e você não é admin"; e (2)
# `firewall_status: "unknown"` era um literal fixo - nenhum código em
# lugar nenhum jamais tentava checar o firewall de verdade. Agora checa
# admin por plataforma (Windows via ctypes, POSIX via os.geteuid()) e
# tenta uma checagem real de firewall por SO antes de cair pra
# "desconhecido" (agora um resultado honesto de "tentamos e não deu",
# não mais um valor que nunca foi sequer tentado).
class SecurityEngine(ISecurityService):
    def __init__(self):
        pass

    def _check_admin(self) -> tuple[bool, str | None]:
        try:
            if platform.system() == "Windows":
                import ctypes
                return ctypes.windll.shell32.IsUserAnAdmin() != 0, None
            else:
                return os.geteuid() == 0, None
        except Exception as e:
            return False, str(e)

    def _check_firewall(self) -> str:
        system = platform.system()
        try:
            if system == "Windows":
                result = subprocess.run(
                    ["netsh", "advfirewall", "show", "allprofiles", "state"],
                    capture_output=True, text=True, timeout=5,
                )
                if result.returncode == 0:
                    out = result.stdout.upper()
                    if "ON" in out and "OFF" not in out:
                        return "ativo"
                    if "OFF" in out and "ON" not in out:
                        return "inativo"
                    return "misto"  # perfis com estados diferentes
                return "desconhecido"
            elif system == "Linux":
                if shutil.which("ufw"):
                    result = subprocess.run(["ufw", "status"], capture_output=True, text=True, timeout=5)
                    if result.returncode == 0:
                        return "ativo" if "Status: active" in result.stdout else "inativo"
                if shutil.which("firewall-cmd"):
                    result = subprocess.run(["firewall-cmd", "--state"], capture_output=True, text=True, timeout=5)
                    if result.returncode == 0:
                        return "ativo" if result.stdout.strip() == "running" else "inativo"
                return "desconhecido"  # nenhuma ferramenta conhecida (ufw/firewalld) presente
            else:
                return "desconhecido"
        except Exception as e:
            logger.warning(f"SecurityEngine: falha ao checar firewall: {e}")
            return "desconhecido"

    async def check_integrity(self) -> dict[str, Any]:
        is_admin, admin_error = self._check_admin()
        if admin_error:
            logger.warning(f"SecurityEngine: falha ao checar privilégios de admin: {admin_error}")
        firewall_status = self._check_firewall()

        logger.info(f"SecurityEngine: Admin privileges: {is_admin} | Firewall: {firewall_status}")
        return {"is_admin": is_admin, "firewall_status": firewall_status}
