import os
import json
import logging
from pathlib import Path

logger = logging.getLogger(__name__)

# PHX-FIX (2026-09-03, auditoria ChatGPT — detecção de modelos intermitente):
# a raiz do projeto, resolvida a partir da LOCALIZAÇÃO deste arquivo, não do
# diretório de onde o processo foi iniciado. Antes o storage.json de fallback
# era procurado em Path("data/storage.json") RELATIVO ao cwd — se a Phoenix
# fosse iniciada de outra pasta (atalho, serviço, terminal em outro dir), ela
# achava um storage.json diferente ou nenhum, e a detecção de modelos "sumia".
_PROJECT_ROOT = Path(__file__).resolve().parent.parent


class StorageManager:
    """Lê o storage.json gerado pelo Bootstrapper. A Phoenix nunca descobre discos."""
    def __init__(self):
        self.config = self._load_config()

    def reload(self) -> dict:
        """PHX-FIX (auditoria ChatGPT): antes self.config era carregado uma
        única vez no __init__ e NUNCA recarregava — se o storage.json mudasse
        (bootstrapper reescreve, usuário troca a pasta de modelos), a instância
        seguia com o mapa antigo em cache eterno, outra causa da detecção
        intermitente. Agora dá para forçar releitura."""
        self.config = self._load_config()
        return self.config

    def _load_config(self) -> dict:
        storage_candidates = []
        if os.name == "nt":
            programdata = os.environ.get("ProgramData")
            if programdata:
                storage_candidates.append(Path(programdata) / "Phoenix" / "storage.json")
        else:
            storage_candidates.append(Path("/etc/phoenix/storage.json"))

        # caminho ABSOLUTO relativo à raiz do projeto (não ao cwd)
        storage_candidates.append(_PROJECT_ROOT / "data" / "storage.json")
        # compat: ainda tenta o relativo ao cwd por último, para instalações
        # antigas que dependiam desse comportamento
        storage_candidates.append(Path("data/storage.json"))
        
        for p in storage_candidates:
            if p.exists():
                try:
                    with open(p, 'r', encoding='utf-8') as f:
                        data = json.load(f)
                        logger.info(f"StorageManager: Mapa de armazenamento carregado de {p}")
                        return data
                except Exception as e:
                    logger.error(f"StorageManager: Erro ao ler {p} - {e}")
                    
        logger.warning("StorageManager: storage.json não encontrado. Usando padrão local.")
        ws_fallback = str(_PROJECT_ROOT / "data" / "workstations")
        return {
            "workspace": ws_fallback,
            "models": str(Path(ws_fallback) / "Models"),
            "docker": "data/docker",
            "rag": "data/rag",
            "cache": "data/cache",
            "logs": "data/logs"
        }

    def get_workspace(self) -> str:
        return self.config.get("workspace", ".")
        
    def get_models_path(self) -> str:
        path = self.config.get("models", str(Path(self.get_workspace()) / "Models"))
        Path(path).mkdir(parents=True, exist_ok=True)
        return path
        
    def get_apps_path(self) -> str:
        path = os.path.join(self.config.get("workspace", "."), "apps")
        Path(path).mkdir(parents=True, exist_ok=True)
        return path

    def get_rag_path(self) -> str:
        path = self.config.get("rag", "data/rag")
        Path(path).mkdir(parents=True, exist_ok=True)
        return path

storage = StorageManager()