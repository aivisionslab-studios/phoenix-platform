import json
import logging
import asyncio
from pathlib import Path
from .provisioning import ProvisioningManager
from .catalog import CatalogEngine

logger = logging.getLogger(__name__)

class PackageManager:
    # PHX-FIX (varredura 2026-08-21 rodada 2, achado extra encontrado ao
    # consertar o `except: pass` de list_packages() abaixo): catalog_path
    # apontava pra "catalog/packages/<categoria>/", uma árvore de
    # diretórios que existe mas está completamente VAZIA neste projeto -
    # o catálogo real de missões vive em "catalog/<categoria>/" (mesmo
    # caminho que CatalogEngine, em catalog.py, já usa corretamente e que
    # backeia GET /api/missions). Resultado prático: `_find_package()`
    # NUNCA encontrava nenhuma missão real - `install_package()` sempre
    # devolvia "[ERRO] ... não encontrada", mesmo pra missões que existem
    # de verdade no catálogo (ex: catalog/essentials/chat.json). Não era
    # uma fabricação de sucesso (o erro era honesto), mas quebrava a
    # funcionalidade de instalação de missão inteira, silenciosamente.
    def __init__(self, budget_engine=None):
        self.catalog_path = Path("catalog")
        self.categories = ["essentials", "studios", "suites", "addons"]
        self.catalog = CatalogEngine()
        self.provisioning = ProvisioningManager()
        self.budget = budget_engine

    def _find_package(self, package_name: str) -> Path | None:
        for category in self.categories:
            pkg_file = self.catalog_path / category / f"{package_name}.json"
            if pkg_file.exists(): return pkg_file
        return None

    def list_packages(self) -> str:
        output_lines = []
        for category in self.categories:
            cat_path = self.catalog_path / category
            if not cat_path.exists(): continue
            files = list(cat_path.glob("*.json"))
            if not files: continue
            output_lines.append(f"\n=== {category.upper()} ===")
            for f in files:
                try:
                    with open(f, 'r', encoding='utf-8') as file:
                        pkg = json.load(file)
                    output_lines.append(f"- {pkg.get('id', f.stem)}: {pkg.get('name', 'Sem nome')}")
                except Exception as e:
                    # PHX-FIX (varredura 2026-08-21 rodada 2, achado #7): um
                    # JSON malformado era descartado da listagem em silêncio -
                    # o usuário não tinha como saber que um pacote existe mas
                    # está quebrado. Agora aparece na lista com o erro.
                    logger.warning(f"PackageManager: falha ao ler pacote '{f}': {e}")
                    output_lines.append(f"- {f.stem}: [ERRO ao ler pacote: {e}]")
        return "\n".join(output_lines) if output_lines else "Nenhum pacote encontrado."

    async def install_package(self, package_name: str) -> str:
        pkg_file = self._find_package(package_name)
        if not pkg_file: return f"[ERRO] Missão '{package_name}' não encontrada."

        with open(pkg_file, 'r', encoding='utf-8') as f:
            pkg = json.load(f)

        logger.info(f"PackageManager: Iniciando missão '{pkg.get('name')}'...")
        results = []
        connectors = pkg.get("connectors", [])
        loop = asyncio.get_running_loop()

        for conn_name in connectors:
            logger.info(f"PackageManager: Provisionando conector '{conn_name}'...")
            # RODA EM THREAD SEPARADA PARA NÃO TRAVAR A TELA
            result = await loop.run_in_executor(None, self.provisioning.install, conn_name)
            results.append(f"- {conn_name}: {result}")

        # PHX-FIX (varredura 2026-08-21 rodada 2, achado encontrado ao
        # testar o conserto #1 de verdade, com o daemon do Docker
        # desligado neste sandbox): o cabeçalho dizia "concluída!"
        # incondicionalmente, mesmo com TODOS os conectores tendo falhado
        # de verdade (cada `result` já honesto, começando com "[ERRO]"
        # depois do conserto da Parte 1) - a mesma classe de problema do
        # achado #1, só que um nível acima. Agora o cabeçalho reflete se
        # algum conector realmente falhou.
        failed = [r for r in results if "[ERRO]" in r]
        if failed and len(failed) == len(results):
            header = f"Missão '{pkg.get('name')}' FALHOU - nenhum conector subiu."
        elif failed:
            header = f"Missão '{pkg.get('name')}' concluída parcialmente ({len(results) - len(failed)}/{len(results)} conectores OK)."
        else:
            header = f"Missão '{pkg.get('name')}' concluída!"
        return f"{header}\n" + "\n".join(results)