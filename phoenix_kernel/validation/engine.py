import asyncio
import shutil
import psutil
import logging
from pathlib import Path
from typing import Any
from .interfaces import IValidationService

logger = logging.getLogger(__name__)

# PHX-FIX (varredura 2026-08-21 rodada 2, achado #1): `validate_system()`
# devolvia `{"status": "ok"}` incondicionalmente - não existia nenhum
# caminho de código capaz de produzir um status diferente de "ok", mesmo
# se psutil não conseguisse ler nada. O comando de chat `validate` (ver
# api/engine.py) repassava isso direto pro usuário como
# "Validation Status: ok", uma afirmação sem verificação real por trás.
# Esta classe não tem autoridade pra inventar uma "especificação mínima"
# de negócio (nenhum requisito mínimo documentado existe no projeto hoje -
# ver README/LEIA-ME) - inventar um limiar arbitrário trocaria uma
# fabricação por outra. O que É uma checagem de integridade real e
# honesta: confirmar que as próprias leituras de hardware (via psutil) e o
# disco de trabalho funcionaram - "ok" agora significa "conseguimos medir
# o sistema", "fail" significa "nem isso conseguimos".
class ValidationEngine(IValidationService):
    def __init__(self):
        pass

    async def validate_system(self) -> dict[str, Any]:
        loop = asyncio.get_running_loop()

        def check():
            issues = []
            ram_total_mb = None
            cpu_cores = None
            disk_free_gb = None

            try:
                ram = psutil.virtual_memory()
                ram_total_mb = int(ram.total / (1024 * 1024))
                if ram_total_mb <= 0:
                    issues.append("psutil devolveu RAM total <= 0.")
            except Exception as e:
                issues.append(f"Falha ao ler RAM via psutil: {e}")

            try:
                cpu_cores = psutil.cpu_count(logical=False)
                if not cpu_cores:
                    issues.append("psutil não conseguiu contar núcleos físicos de CPU.")
            except Exception as e:
                issues.append(f"Falha ao ler contagem de CPU via psutil: {e}")

            try:
                usage = shutil.disk_usage(Path.cwd())
                disk_free_gb = round(usage.free / (1024 ** 3), 1)
            except Exception as e:
                issues.append(f"Falha ao ler espaço em disco: {e}")

            return {
                "ram_total_mb": ram_total_mb,
                "cpu_cores": cpu_cores,
                "disk_free_gb": disk_free_gb,
                "issues": issues,
            }

        result = await loop.run_in_executor(None, check)
        status = "ok" if not result["issues"] else "fail"
        if status == "ok":
            logger.info("ValidationEngine: leituras de hardware básicas bem-sucedidas.")
        else:
            logger.warning(f"ValidationEngine: falha ao coletar métricas básicas: {result['issues']}")
        return {"status": status, "checks": result}
