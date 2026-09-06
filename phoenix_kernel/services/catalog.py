import json
import logging
from pathlib import Path

logger = logging.getLogger(__name__)

class CatalogEngine:
    def __init__(self):
        self.base_path = Path("catalog")
        self.categories = ["essentials", "studios", "suites", "addons"]
        self.connectors = self._load_connectors()
        self.packages = self._load_packages()

    def _load_connectors(self) -> dict:
        file_path = self.base_path / "connectors.json"
        if not file_path.exists(): return {}
        try:
            with open(file_path, 'r', encoding='utf-8') as f: return json.load(f)
        except Exception as e:
            logger.error(f"Catalog: Erro ao ler connectors.json: {e}")
            return {}

    def _load_packages(self) -> dict:
        packages = {}
        for category in self.categories:
            cat_path = self.base_path / category
            if not cat_path.exists(): continue
            
            for pkg_file in cat_path.glob("*.json"):
                try:
                    with open(pkg_file, 'r', encoding='utf-8') as f:
                        pkg_data = json.load(f)
                    pkg_id = pkg_data.get("id", pkg_file.stem)
                    pkg_data["category"] = category
                    packages[pkg_id] = pkg_data
                except Exception as e:
                    logger.error(f"Catalog: Erro ao ler {pkg_file}: {e}")
        return packages

    def get_package(self, package_name: str) -> dict:
        return self.packages.get(package_name)

    def get_connector(self, connector_name: str) -> dict:
        return self.connectors.get(connector_name)

    def list_packages(self) -> str:
        if not self.packages: return "Nenhum pacote encontrado no catálogo."
        
        output = ["===== AIVisions Official Catalog ====="]
        for category in self.categories:
            cat_pkgs = [p for p in self.packages.values() if p.get("category") == category]
            if not cat_pkgs: continue
            
            output.append(f"\n--- {category.upper()} ---")
            for pkg in cat_pkgs:
                output.append(f"  [{pkg.get('id')}] {pkg.get('name')}")
                output.append(f"    {pkg.get('description', '')}")
        
        return "\n".join(output)