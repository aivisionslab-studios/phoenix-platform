import asyncio
import hashlib
import json
import logging
import os
import socket
import uuid
from datetime import datetime, timezone
from pathlib import Path

# Importa os caminhos centralizados do módulo do Kernel
from phoenix_kernel.paths import (
    FIRESTORE_CREDENTIALS, MACHINE_ID_FILE, CONSENT_FLAG, KNOWLEDGE_BASE_JSON,
    INSTALL_LOGS_DIR, SHARED_POOL_CURSOR_FILE,
)

logger = logging.getLogger(__name__)

FIRESTORE_ROOT_COLLECTION = "phoenix_machines"
FIRESTORE_SUBCOLLECTION = "knowledge_base"
SHARED_POOL_COLLECTION = "shared_knowledge_pool"
BATCH_SIZE = 400

# PHX-NEW: allowlist estrito por tipo de registro. Isso não é documentação
# - é a barreira técnica que garante, por construção, que nenhum campo de
# conteúdo de conversa (prompt/response/texto do usuário) chega perto do
# Firestore, mesmo que alguém no futuro tente passar isso sem querer. Ver
# phoenix_data_collection_principles.md, seção 2 ("O que NUNCA é coletado").
_MODEL_RUN_ALLOWED_KEYS = {
    "model_id", "runtime", "task_category", "hardware_fingerprint",
    "tokens_generated", "tokens_per_second", "duration_ms", "success",
}
_SHARED_POOL_ALLOWED_KEYS = {
    "content", "category", "hardware_fingerprint", "phoenix_version", "capivara",
}
# "content" aqui é permitido no pool porque é o TEXTO DA DESCOBERTA TÉCNICA
# (ex: "Flux Q8 da OOM mesmo em 512x512 com offload total"), nunca conteúdo
# de conversa - a distinção é de propósito, não de nome do campo. Categorias
# válidas ficam de fora do allowlist de propósito (fica em _VALID_POOL_CATEGORIES
# abaixo) pra dar erro claro em vez de aceitar categoria inventada.
_VALID_POOL_CATEGORIES = {"sd_failure", "benchmark", "fix", "hardware_quirk", "install_failure"}


class SchemaViolation(ValueError):
    """Levantado quando um payload tenta incluir um campo fora da allowlist
    (ex: 'prompt', 'response', 'text') - impede o envio, não só avisa."""


def _validate_payload(payload: dict, allowed_keys: set, context: str) -> None:
    extra = set(payload.keys()) - allowed_keys
    if extra:
        raise SchemaViolation(
            f"{context}: campo(s) não permitido(s) {sorted(extra)}. "
            f"Campos aceitos: {sorted(allowed_keys)}. Se isso é conteúdo de "
            f"conversa (prompt/resposta), NUNCA deve ir para o Firestore - "
            f"ver phoenix_data_collection_principles.md."
        )


def has_consent() -> bool:
    return CONSENT_FLAG.exists()

def grant_consent() -> None:
    CONSENT_FLAG.parent.mkdir(parents=True, exist_ok=True)
    CONSENT_FLAG.write_text("accepted")

def revoke_consent() -> None:
    if CONSENT_FLAG.exists():
        CONSENT_FLAG.unlink()

def get_or_create_machine_id() -> str:
    """Id estável dessa instalação da Phoenix."""
    if MACHINE_ID_FILE.exists():
        existing = MACHINE_ID_FILE.read_text().strip()
        if existing:
            return existing
    machine_id = str(uuid.uuid4())
    MACHINE_ID_FILE.parent.mkdir(parents=True, exist_ok=True)
    MACHINE_ID_FILE.write_text(machine_id)
    return machine_id


def _content_hash(text: str) -> str:
    return hashlib.sha256(text.strip().lower().encode("utf-8")).hexdigest()[:16]


class FirestoreSync:
    def __init__(self):
        self._client = None
        self.machine_id = get_or_create_machine_id()

    def _get_client(self):
        if self._client is not None:
            return self._client

        from google.cloud import firestore
        from google.oauth2 import service_account

        env_json = os.environ.get("FIREBASE_SERVICE_ACCOUNT_JSON")
        env_path = os.environ.get("GOOGLE_APPLICATION_CREDENTIALS")

        if env_json:
            info = json.loads(env_json)
            credentials = service_account.Credentials.from_service_account_info(info)
            project_id = info.get("project_id")
        elif env_path and Path(env_path).exists():
            credentials = service_account.Credentials.from_service_account_file(env_path)
            project_id = json.loads(Path(env_path).read_text(encoding="utf-8")).get("project_id")
        else:
            if not FIRESTORE_CREDENTIALS.exists():
                raise FileNotFoundError(
                    f"Nenhuma credencial do Firebase encontrada. Rodando local: salva o JSON "
                    f"de service account em '{FIRESTORE_CREDENTIALS}'. Em produção/deploy: "
                    f"defina a variável de ambiente FIREBASE_SERVICE_ACCOUNT_JSON."
                )
            credentials = service_account.Credentials.from_service_account_file(str(FIRESTORE_CREDENTIALS))
            project_id = json.loads(FIRESTORE_CREDENTIALS.read_text(encoding="utf-8")).get("project_id")

        self._client = firestore.Client(project=project_id, credentials=credentials)
        return self._client

    # ------------------------------------------------------------------
    # Métodos originais - idênticos ao cloud_sync.py anterior, sem mudança
    # ------------------------------------------------------------------

    async def sync_knowledge_base(self) -> int:
        if not has_consent(): return 0
        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(None, self._sync_kb_blocking)

    def _sync_kb_blocking(self) -> int:
        if not KNOWLEDGE_BASE_JSON.exists(): return 0

        with open(KNOWLEDGE_BASE_JSON, "r", encoding="utf-8") as f:
            documents = json.load(f)
        if isinstance(documents, dict): documents = [documents]
        if not documents: return 0

        try:
            client = self._get_client()
            from google.cloud import firestore
            collection = client.collection(FIRESTORE_ROOT_COLLECTION).document(self.machine_id).collection(FIRESTORE_SUBCOLLECTION)

            sent = 0
            batch = client.batch()
            pending = 0
            for doc in documents:
                doc_id = doc.get("id")
                if not doc_id: continue
                batch.set(collection.document(doc_id), doc)
                sent += 1
                pending += 1
                if pending >= BATCH_SIZE:
                    batch.commit(); batch = client.batch(); pending = 0
            if pending: batch.commit()

            client.collection(FIRESTORE_ROOT_COLLECTION).document(self.machine_id).set(
                {"last_synced_at": firestore.SERVER_TIMESTAMP, "document_count": sent}, merge=True
            )
            logger.info(f"FirestoreSync: {sent} documento(s) do RAG sincronizado(s).")
            return sent
        except Exception as e:
            logger.error(f"FirestoreSync: Falha ao sincronizar RAG - {e}")
            return 0

    async def sync_machine_state(self, state_data: dict):
        if not has_consent(): return
        loop = asyncio.get_running_loop()
        await loop.run_in_executor(None, self._sync_state_blocking, state_data)

    def _sync_state_blocking(self, state_data: dict):
        try:
            client = self._get_client()
            from google.cloud import firestore
            doc_ref = client.collection(FIRESTORE_ROOT_COLLECTION).document(self.machine_id)
            doc_ref.set({
                "hostname": socket.gethostname(),
                "online": True,
                "last_seen": firestore.SERVER_TIMESTAMP,
                "phoenix_version": "4.5.0",
                "hardware": state_data.get("hardware", {}),
                "budget": state_data.get("budget", {}),
                "telemetry_enabled": True
            }, merge=True)
            telemetry = state_data.get("telemetry", {})
            if telemetry:
                doc_ref.collection("telemetry").add({**telemetry, "timestamp": firestore.SERVER_TIMESTAMP})
        except Exception as e:
            logger.debug(f"FirestoreSync: Erro ao sincronizar telemetria - {e}")

    async def add_log(self, level: str, service: str, message: str):
        if not has_consent(): return
        loop = asyncio.get_running_loop()
        await loop.run_in_executor(None, self._add_log_blocking, level, service, message)

    def _add_log_blocking(self, level: str, service: str, message: str):
        try:
            client = self._get_client()
            from google.cloud import firestore
            doc_ref = client.collection(FIRESTORE_ROOT_COLLECTION).document(self.machine_id)
            doc_ref.collection("logs").add({
                "level": level, "service": service, "message": message, "timestamp": firestore.SERVER_TIMESTAMP
            })
        except Exception:
            pass

    def shutdown(self):
        if not has_consent(): return
        try:
            client = self._get_client()
            from google.cloud import firestore
            doc_ref = client.collection(FIRESTORE_ROOT_COLLECTION).document(self.machine_id)
            doc_ref.set({"online": False, "last_seen": firestore.SERVER_TIMESTAMP}, merge=True)
        except Exception:
            pass

    # ------------------------------------------------------------------
    # PHX-NEW: desempenho de modelo (nunca conteúdo - ver allowlist acima)
    # ------------------------------------------------------------------

    async def push_model_run(self, run: dict) -> bool:
        """
        run deve conter só: model_id, runtime, task_category,
        hardware_fingerprint, tokens_generated, tokens_per_second,
        duration_ms, success. NUNCA prompt/response/content - levanta
        SchemaViolation se tentar.
        """
        _validate_payload(run, _MODEL_RUN_ALLOWED_KEYS, "push_model_run")
        if not has_consent(): return False
        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(None, self._push_model_run_blocking, run)

    def _push_model_run_blocking(self, run: dict) -> bool:
        try:
            client = self._get_client()
            from google.cloud import firestore
            doc_ref = client.collection(FIRESTORE_ROOT_COLLECTION).document(self.machine_id)
            doc_ref.collection("model_runs").add({**run, "timestamp": firestore.SERVER_TIMESTAMP})
            return True
        except Exception as e:
            logger.debug(f"FirestoreSync: Erro ao registrar model_run - {e}")
            return False

    # ------------------------------------------------------------------
    # PHX-NEW: relatórios de instalação - lê o que install_phoenix.ps1/
    # common.ps1 já escrevem em logs/install/*.json e sincroniza. Falhas
    # (success=false ou error_code != PX000) também alimentam o pool
    # compartilhado como category="install_failure" - é o mesmo padrão dos
    # 4 logs que já vimos (PX012, os 6 códigos de winget repetidos).
    # ------------------------------------------------------------------

    async def sync_install_reports(self) -> int:
        if not has_consent(): return 0
        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(None, self._sync_install_reports_blocking)

    def _sync_install_reports_blocking(self) -> int:
        if not INSTALL_LOGS_DIR.exists(): return 0

        synced_marker = INSTALL_LOGS_DIR / ".synced.json"
        already_synced = set()
        if synced_marker.exists():
            try:
                already_synced = set(json.loads(synced_marker.read_text(encoding="utf-8")))
            except Exception:
                already_synced = set()

        report_files = sorted(INSTALL_LOGS_DIR.glob("install_*.json"))
        new_files = [f for f in report_files if f.name not in already_synced]
        if not new_files:
            return 0

        try:
            client = self._get_client()
            from google.cloud import firestore
            doc_ref = client.collection(FIRESTORE_ROOT_COLLECTION).document(self.machine_id)
            reports_collection = doc_ref.collection("install_reports")

            sent = 0
            for report_file in new_files:
                try:
                    # PHX-FIX (auditoria 2026-08-09): estava lendo com
                    # encoding="utf-8" puro. O PowerShell no Windows grava
                    # esses install_*.json com BOM (Byte Order Mark) por
                    # padrão em várias versões/comandos (Out-File,
                    # Set-Content), e "utf-8" comum não remove o BOM - ele
                    # vira um caractere \ufeff colado no início da primeira
                    # linha, quebrando json.loads() nela com exatamente o
                    # erro visto no log: "Unexpected UTF-8 BOM (decode
                    # using utf-8-sig)". "utf-8-sig" remove o BOM se
                    # existir e funciona igual em arquivos sem BOM, então é
                    # estritamente mais seguro aqui - sem efeito colateral.
                    lines = [
                        json.loads(line) for line in report_file.read_text(encoding="utf-8-sig").splitlines()
                        if line.strip()
                    ]
                except Exception as e:
                    logger.warning(f"FirestoreSync: falha ao ler {report_file.name}: {e}")
                    continue

                for record in lines:
                    reports_collection.add({
                        **record,
                        "report_file": report_file.name,
                        "synced_at": firestore.SERVER_TIMESTAMP,
                    })
                    sent += 1
                    # Falha real (não PX000) vira achado compartilhável -
                    # exatamente o padrão dos códigos que já vimos repetir
                    # (PX012, winget -1978335189/-1978335226).
                    if not record.get("success", True) or record.get("error_code") not in (None, "PX000"):
                        self._push_to_shared_pool_blocking({
                            "content": (
                                f"Módulo '{record.get('module', '?')}' falhou com "
                                f"error_code={record.get('error_code', '?')}. "
                                f"Warnings: {record.get('warnings', [])}"
                            ),
                            "category": "install_failure",
                            "hardware_fingerprint": {},
                            "phoenix_version": "4.5.0",
                        })

                already_synced.add(report_file.name)

            synced_marker.write_text(json.dumps(sorted(already_synced)), encoding="utf-8")
            logger.info(f"FirestoreSync: {sent} registro(s) de instalação sincronizado(s).")
            return sent
        except Exception as e:
            logger.error(f"FirestoreSync: Falha ao sincronizar relatórios de instalação - {e}")
            return 0

    # ------------------------------------------------------------------
    # PHX-NEW: pool compartilhado - push com dedup por content_hash,
    # pull incremental. Ver phoenix_kernel_shared_rag_spec.md.
    # ------------------------------------------------------------------

    async def push_to_shared_pool(self, entry: dict) -> bool:
        """
        entry: {"content": str, "category": str (ver _VALID_POOL_CATEGORIES),
        "hardware_fingerprint": dict, "phoenix_version": str,
        "capivara": dict (opcional)}. NUNCA aceita campo fora da allowlist.
        """
        _validate_payload(entry, _SHARED_POOL_ALLOWED_KEYS, "push_to_shared_pool")
        if entry.get("category") not in _VALID_POOL_CATEGORIES:
            raise SchemaViolation(
                f"push_to_shared_pool: category '{entry.get('category')}' inválida. "
                f"Válidas: {sorted(_VALID_POOL_CATEGORIES)}."
            )
        if not entry.get("content", "").strip():
            raise SchemaViolation("push_to_shared_pool: 'content' vazio.")
        if not has_consent(): return False
        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(None, self._push_to_shared_pool_blocking, entry)

    def _push_to_shared_pool_blocking(self, entry: dict) -> bool:
        try:
            client = self._get_client()
            from google.cloud import firestore
            doc_id = _content_hash(entry["content"])
            doc_ref = client.collection(SHARED_POOL_COLLECTION).document(doc_id)
            doc_ref.set({
                "content": entry["content"],
                "category": entry["category"],
                "hardware_fingerprint": entry.get("hardware_fingerprint", {}),
                "phoenix_version": entry.get("phoenix_version", "unknown"),
                "capivara": entry.get("capivara", {}),
                "confirmed_by_count": firestore.Increment(1),
                "last_confirmed_at": firestore.SERVER_TIMESTAMP,
            }, merge=True)
            # first_seen_at só grava se o doc ainda não existir - merge=True
            # com create() falharia se já existir, então faz um set()
            # condicional separado usando um sentinel.
            snapshot = doc_ref.get()
            if snapshot.exists and "first_seen_at" not in (snapshot.to_dict() or {}):
                doc_ref.set({"first_seen_at": firestore.SERVER_TIMESTAMP}, merge=True)
            return True
        except Exception as e:
            logger.error(f"FirestoreSync: Falha ao enviar para shared_knowledge_pool - {e}")
            return False

    async def pull_shared_knowledge_base(self, force_full: bool = False) -> list[dict]:
        """
        Baixa o pool compartilhado. Por padrão incremental (só o que mudou
        desde o último pull, via SHARED_POOL_CURSOR_FILE); force_full=True
        baixa tudo (usar no primeiro boot / clone novo, quando ainda não
        existe knowledge_base.json local).
        """
        if not has_consent(): return []
        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(None, self._pull_shared_pool_blocking, force_full)

    def _pull_shared_pool_blocking(self, force_full: bool) -> list[dict]:
        try:
            client = self._get_client()
            collection = client.collection(SHARED_POOL_COLLECTION)

            since = None
            if not force_full and SHARED_POOL_CURSOR_FILE.exists():
                try:
                    cursor = json.loads(SHARED_POOL_CURSOR_FILE.read_text(encoding="utf-8"))
                    since = datetime.fromisoformat(cursor["last_pull_at"])
                except Exception:
                    since = None

            query = collection
            if since is not None:
                query = query.where("last_confirmed_at", ">", since)

            docs = list(query.stream())
            results = [d.to_dict() | {"id": d.id} for d in docs]

            SHARED_POOL_CURSOR_FILE.parent.mkdir(parents=True, exist_ok=True)
            SHARED_POOL_CURSOR_FILE.write_text(
                json.dumps({"last_pull_at": datetime.now(timezone.utc).isoformat()}),
                encoding="utf-8",
            )
            logger.info(f"FirestoreSync: {len(results)} documento(s) baixado(s) do pool compartilhado.")
            return results
        except Exception as e:
            logger.error(f"FirestoreSync: Falha ao baixar pool compartilhado - {e}")
            return []
