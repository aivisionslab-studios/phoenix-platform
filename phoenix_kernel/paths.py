r"""
PhoenixPaths — Resolução dinâmica de caminhos.
Nenhum código Python deve conter C:\, D:\, E:\ ou /opt.
Tudo passa por aqui.
"""
from __future__ import annotations
import json
import os
import platform
from pathlib import Path


class PhoenixPaths:
    _manifest = None
    # PHX-FIX (2026-09-03, auditoria ChatGPT — detecção de modelos
    # intermitente): a raiz do projeto pela LOCALIZAÇÃO deste arquivo, não pelo
    # cwd. Este era o SEGUNDO resolvedor de storage independente (o outro é
    # StorageManager), e tinha os mesmos dois defeitos: procurava
    # "data/storage.json" relativo ao diretório de execução, e cacheava o
    # manifesto para sempre. Ambos causavam a pasta de modelos "sumir" quando a
    # Phoenix era iniciada de outro diretório ou quando o storage.json mudava.
    _PROJECT_ROOT = Path(__file__).resolve().parent.parent

    @classmethod
    def reset_cache(cls) -> None:
        """Força reler o storage.json na próxima resolução — para quando o
        bootstrapper reescreve o mapa ou o usuário troca a pasta de modelos."""
        cls._manifest = None

    @classmethod
    def _load_manifest(cls) -> dict:
        if cls._manifest is not None:
            return cls._manifest

        storage_candidates = []
        if platform.system() == "Windows":
            programdata = os.environ.get("ProgramData")
            if programdata:
                storage_candidates.append(Path(programdata) / "Phoenix" / "storage.json")
        else:
            storage_candidates.append(Path("/etc/phoenix/storage.json"))

        # caminho ABSOLUTO relativo à raiz do projeto (não ao cwd); mantém o
        # relativo por último para compatibilidade com instalações antigas
        storage_candidates.append(cls._PROJECT_ROOT / "data" / "storage.json")
        storage_candidates.append(Path("data/storage.json"))

        for p in storage_candidates:
            if p.exists():
                try:
                    with open(p, "r", encoding="utf-8") as f:
                        cls._manifest = json.load(f)
                        return cls._manifest
                except Exception:
                    pass

        cls._manifest = {"workspace": str(cls._PROJECT_ROOT / "data" / "workstations")}
        return cls._manifest

    @classmethod
    def get_workspace(cls) -> Path:
        ws = Path(cls._load_manifest().get("workspace", "."))
        if ws.is_absolute():
            ws.mkdir(parents=True, exist_ok=True)
            return ws
        # Fallback seguro
        fallback = Path("data/workstations").resolve()
        fallback.mkdir(parents=True, exist_ok=True)
        return fallback

    @classmethod
    def get_models_base(cls) -> Path:
        return cls.get_workspace() / "Models"

    @classmethod
    def get_category_path(cls, category: str, subcategory: str = None) -> Path:
        base = cls.get_models_base() / category
        return base / subcategory if subcategory else base

    @classmethod
    def get_model_path(cls, category: str, subcategory: str, filename: str) -> Path:
        return cls.get_category_path(category, subcategory) / filename

    @classmethod
    def get_cache_dir(cls) -> Path:
        return cls.get_workspace().parent / "Cache"

    @classmethod
    def get_temp_dir(cls) -> Path:
        return cls.get_workspace().parent / "Temp"

    @classmethod
    def get_downloads_dir(cls) -> Path:
        return cls.get_workspace().parent / "Downloads"

    @classmethod
    def get_outputs_dir(cls) -> Path:
        return cls.get_workspace().parent / "Outputs"

    @classmethod
    def get_documents_dir(cls, bucket: str = "Created") -> Path:
        """Diretório canônico de documentos gerados/transformados.

        Fica sob Outputs/Documents e funciona igual em Windows/Linux porque
        parte sempre do workspace resolvido por storage.json.
        """
        safe_bucket = "".join(ch for ch in (bucket or "Created") if ch.isalnum() or ch in ("-", "_")) or "Created"
        target = cls.get_outputs_dir() / "Documents" / safe_bucket
        target.mkdir(parents=True, exist_ok=True)
        return target

    @classmethod
    def get_inventory_db(cls) -> Path:
        return cls.get_workspace().parent / "data" / "models_inventory.json"


# --- CONSTANTES DE SISTEMA E CLOUD SYNC ---
PROJECT_ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = PROJECT_ROOT / "data"
CONFIG_DIR = DATA_DIR / "config"

FIRESTORE_CREDENTIALS = CONFIG_DIR / "firestore_credentials.json"
MACHINE_ID_FILE = DATA_DIR / "machine_id.json"
CONSENT_FLAG = DATA_DIR / "telemetry_consent.flag"
KNOWLEDGE_BASE_JSON = DATA_DIR / "knowledge_base.json"
# PHX-NEW (destravar Ollama como 2ª opção de engine de texto): guarda a
# escolha do usuário entre "llama.cpp" (nativo, default) e "ollama"
# (Docker, porta 11434, mais lento) - persistida em disco pra sobreviver a
# um restart do api_server.py. Ver ResidentManager.get/set_text_engine_preference().
TEXT_ENGINE_PREFERENCE_FILE = DATA_DIR / "text_engine_preference.json"

# PHX-NEW: pasta onde install_phoenix.ps1/common.ps1 já escrevem os
# relatórios de instalação (install_TIMESTAMP.log/.json) - cloud_sync.py
# passa a ler daqui pra sincronizar automaticamente, em vez desses logs
# ficarem só locais sem nunca virar conhecimento compartilhado.
INSTALL_LOGS_DIR = PROJECT_ROOT / "logs" / "install"

# PHX-NEW: cursor local do último pull do shared_knowledge_pool - guarda
# só um timestamp, pra pull_shared_knowledge_base() não rebaixar o pool
# inteiro toda vez, só o que mudou desde a última sincronização.
SHARED_POOL_CURSOR_FILE = DATA_DIR / "shared_pool_last_pull.json"
