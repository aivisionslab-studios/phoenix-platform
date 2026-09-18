"""
Phoenix Forge — Firestore Telemetry  (0.24.0)
================================================
Ponte entre o Forge e o destino de telemetria.

Modos de transporte (resolvidos por telemetry_mode.resolve()):
  OFF                          — nenhum envio
  DEVELOPMENT_DIRECT_FIRESTORE — Firestore direto via service account local
  PRODUCTION_CLOUD_RELAY       — Phoenix Cloud Relay via HTTPS

Estados visíveis na UI:
  SENT                 — entregue com sucesso
  QUEUED_OFFLINE       — sem internet; item na fila, retry automático
  QUEUED_RETRY         — falha transiente; retry agendado
  QUEUED_SEND_FAILED   — falha permanente do envio (não retentável)
  BLOCKED_NO_CONSENT   — consentimento ausente
  BLOCKED_UNCONFIGURED — destino não configurado
  BLOCKED_MODE_OFF     — telemetria desativada por configuração
  REJECTED_AUTH        — credencial inválida (não retentável)
  REJECTED_SCHEMA      — payload inválido (não retentável)
"""
from __future__ import annotations

import json
import os
import time
from pathlib import Path
from typing import Any
from urllib.request import Request, urlopen

from phoenix_forge.modules import telemetry_governance, telemetry_payload, snapshot_cache

SCHEMA = "phoenix.forge.firestore-telemetry/v3"
DESTINATION_SCHEMA = "phoenix.forge.telemetry-destination/v1"
DEFAULT_PROJECT = "setup-ia-local-rx580-vulkan"
DEFAULT_COLLECTION = "forge_telemetry"
DEFAULT_CREDENTIAL_FILENAME = "firestore_credentials.json"
EXAMPLE_CREDENTIAL_FILENAME = "firestore_credentials.example.json"


def _phoenix_root() -> Path | None:
    explicit = os.getenv("PHOENIX_ROOT", "").strip()
    if explicit:
        p = Path(explicit).expanduser()
        if p.exists():
            return p.resolve()
    # Installed layout: <PHOENIX_ROOT>/phoenix-forge/phoenix_forge/modules/firestore_telemetry.py
    try:
        candidate = Path(__file__).resolve().parents[3]
        if (candidate / "data").exists() or candidate.name.lower().startswith("phoenix"):
            return candidate
    except Exception:
        pass
    return None


def _validate_service_account_file(path: Path) -> tuple[bool, dict[str, Any]]:
    # Never accept the example/template credential file.
    if path.name.lower() == EXAMPLE_CREDENTIAL_FILENAME.lower():
        return False, {"reason": "example_credentials_rejected"}
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:
        return False, {"reason": "invalid_json", "error_class": type(exc).__name__}
    if not isinstance(raw, dict):
        return False, {"reason": "credential_json_not_object"}
    required = ("type", "project_id", "private_key", "client_email", "token_uri")
    missing = [k for k in required if not str(raw.get(k) or "").strip()]
    if str(raw.get("type") or "").strip() != "service_account":
        return False, {"reason": "not_service_account", "missing": missing}
    if missing:
        return False, {"reason": "missing_service_account_fields", "missing": missing}
    # Do not return secret values.
    return True, {"project_id": str(raw.get("project_id")), "client_email_configured": True}


def _discover_phoenix_service_account() -> tuple[Path | None, dict[str, Any]]:
    root = _phoenix_root()
    if root is None:
        return None, {"status": "PHOENIX_ROOT_UNKNOWN"}
    candidate = root / "data" / "config" / DEFAULT_CREDENTIAL_FILENAME
    if not candidate.exists() or not candidate.is_file():
        return None, {"status": "NOT_FOUND", "candidate": str(candidate)}
    valid, meta = _validate_service_account_file(candidate)
    if not valid:
        return None, {"status": "INVALID", "candidate": str(candidate), **meta}
    return candidate.resolve(), {"status": "VALID", "candidate": str(candidate.resolve()), **meta}


def _state_root() -> Path:
    base = os.getenv("PHOENIX_FORGE_STATE_DIR")
    return Path(base) if base else (Path.home() / ".phoenix-forge")


def _queue_dir() -> Path:
    return _state_root() / "telemetry-queue"


def _destination_path() -> Path:
    return _state_root() / "telemetry-destination.json"


def _default_destination() -> dict[str, Any]:
    return {
        "schema": DESTINATION_SCHEMA,
        "enabled": True,
        "provider": "FIREBASE_FIRESTORE",
        "project_id": DEFAULT_PROJECT,
        "collection": DEFAULT_COLLECTION,
        "auth_mode": "AUTO",
        "service_account_file": None,
        "configured_by": "phoenix-forge-default",
    }


def load_destination() -> dict[str, Any]:
    cfg = _default_destination()
    path = _destination_path()
    try:
        if path.exists():
            raw = json.loads(path.read_text(encoding="utf-8"))
            if isinstance(raw, dict):
                cfg.update(raw)
    except Exception as exc:
        cfg["config_read_error"] = type(exc).__name__

    # Explicit environment variables always win over persisted config.
    env_project = os.getenv("PHOENIX_FORGE_FIRESTORE_PROJECT", "").strip()
    env_collection = os.getenv("PHOENIX_FORGE_FIRESTORE_COLLECTION", "").strip()
    env_gateway = os.getenv("PHOENIX_FORGE_TELEMETRY_GATEWAY", "").strip()
    env_sa = os.getenv("GOOGLE_APPLICATION_CREDENTIALS", "").strip()
    if env_project:
        cfg["project_id"] = env_project
    if env_collection:
        cfg["collection"] = env_collection
    if env_sa:
        p = Path(env_sa).expanduser()
        valid, meta = _validate_service_account_file(p) if p.exists() else (False, {"reason": "not_found"})
        if valid:
            cfg["service_account_file"] = str(p.resolve())
            cfg["auth_mode"] = "SERVICE_ACCOUNT_FILE"
            cfg["credential_source"] = "GOOGLE_APPLICATION_CREDENTIALS"
        else:
            cfg["credential_discovery_error"] = {"source": "GOOGLE_APPLICATION_CREDENTIALS", **meta}
    elif str(cfg.get("auth_mode") or "AUTO").upper() in {"AUTO", "ADC"} and not cfg.get("service_account_file"):
        discovered, meta = _discover_phoenix_service_account()
        if discovered is not None:
            cfg["service_account_file"] = str(discovered)
            cfg["auth_mode"] = "SERVICE_ACCOUNT_FILE"
            cfg["credential_source"] = "PHOENIX_DATA_CONFIG"
            cfg["credential_discovery"] = meta
        else:
            cfg["credential_discovery"] = meta
            if str(cfg.get("auth_mode") or "AUTO").upper() == "AUTO":
                cfg["auth_mode"] = "ADC"
                cfg["credential_source"] = "ADC_FALLBACK"
    if env_gateway:
        cfg["provider"] = "HTTPS_GATEWAY"
        cfg["gateway_url"] = env_gateway
    return cfg


def save_destination(cfg: dict[str, Any]) -> dict[str, Any]:
    path = _destination_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    safe = dict(cfg)
    # We persist a path reference, never credential JSON or secret material.
    safe.pop("credential_json", None)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(safe, indent=2, sort_keys=True, ensure_ascii=False), encoding="utf-8")
    tmp.replace(path)
    return load_destination()


def configure_destination(*, project_id: str, collection: str = DEFAULT_COLLECTION,
                          auth_mode: str = "AUTO", service_account_file: str | None = None,
                          enabled: bool = True) -> dict[str, Any]:
    project_id = (project_id or "").strip()
    collection = (collection or DEFAULT_COLLECTION).strip() or DEFAULT_COLLECTION
    auth_mode = (auth_mode or "AUTO").strip().upper()
    if not project_id:
        raise ValueError("firestore_project_required")
    if auth_mode not in {"AUTO", "ADC", "SERVICE_ACCOUNT_FILE"}:
        raise ValueError("unsupported_firestore_auth_mode")
    if auth_mode == "AUTO":
        discovered, meta = _discover_phoenix_service_account()
        if discovered is not None:
            auth_mode = "SERVICE_ACCOUNT_FILE"
            service_account_file = str(discovered)
        else:
            auth_mode = "ADC"
            service_account_file = None
    elif auth_mode == "SERVICE_ACCOUNT_FILE":
        if not service_account_file:
            raise ValueError("service_account_file_required")
        p = Path(service_account_file).expanduser()
        if not p.exists() or not p.is_file():
            raise ValueError("service_account_file_not_found")
        valid, meta = _validate_service_account_file(p)
        if not valid:
            raise ValueError(f"invalid_service_account_file:{meta.get('reason')}")
        service_account_file = str(p.resolve())
    else:
        service_account_file = None
    cfg = {
        "schema": DESTINATION_SCHEMA,
        "enabled": bool(enabled),
        "provider": "FIREBASE_FIRESTORE",
        "project_id": project_id,
        "collection": collection,
        "auth_mode": auth_mode,
        "service_account_file": service_account_file,
        "configured_by": "phoenix-forge",
        "configured_at_unix": time.time(),
    }
    save_destination(cfg)
    return configuration(probe=False)


def _firestore_client(cfg: dict[str, Any]):
    try:
        from google.cloud import firestore
    except Exception as exc:
        return None, {"status": "PROVIDER_MISSING", "provider": "google-cloud-firestore", "error_class": type(exc).__name__}
    project = str(cfg.get("project_id") or "").strip()
    try:
        if str(cfg.get("auth_mode") or "ADC").upper() == "SERVICE_ACCOUNT_FILE":
            from google.oauth2 import service_account
            path = Path(str(cfg.get("service_account_file") or "")).expanduser()
            if not path.exists():
                return None, {"status": "AUTH_ERROR", "error_class": "ServiceAccountFileMissing"}
            valid, meta = _validate_service_account_file(path)
            if not valid:
                return None, {"status": "AUTH_ERROR", "error_class": "InvalidServiceAccountFile", "reason": meta.get("reason")}
            creds = service_account.Credentials.from_service_account_file(str(path))
            return firestore.Client(project=project, credentials=creds), None
        return firestore.Client(project=project), None
    except Exception as exc:
        return None, {"status": "AUTH_ERROR", "error_class": type(exc).__name__, "error": str(exc)[:300]}


def _safe_remote_error(exc: Exception) -> dict[str, Any]:
    """Return actionable error metadata without exposing credentials or payload content."""
    error_class = type(exc).__name__
    code_name = None
    try:
        code_obj = exc.code() if callable(getattr(exc, "code", None)) else getattr(exc, "code", None)
        code_name = getattr(code_obj, "name", None) or (str(code_obj) if code_obj is not None else None)
    except Exception:
        code_name = None
    raw = str(exc or "")
    # Never echo PEM blocks, bearer tokens, or full credential file contents.
    if "-----BEGIN PRIVATE KEY-----" in raw:
        raw = "private_key_redacted"
    raw = raw.replace("\\n", " ").strip()[:500]
    upper = f"{error_class} {code_name or ''} {raw}".upper()
    if "PERMISSION_DENIED" in upper or "403" in upper or error_class == "PermissionDenied":
        reason = "PERMISSION_DENIED"
        hint = "A service account autenticou, mas não tem permissão de escrita no Firestore/projeto/coleção."
        retryable = False
    elif "NOT_FOUND" in upper or "404" in upper or error_class == "NotFound":
        reason = "FIRESTORE_NOT_FOUND"
        hint = "O projeto foi encontrado pelas credenciais, mas o banco Firestore pode não existir/estar inicializado ou o recurso não foi encontrado."
        retryable = False
    elif "UNAUTHENTICATED" in upper or "401" in upper or error_class in {"Unauthenticated", "RefreshError"}:
        reason = "AUTHENTICATION_FAILED"
        hint = "A credencial local existe, porém não conseguiu autenticar no Google Cloud."
        retryable = False
    elif "INVALID_ARGUMENT" in upper or error_class == "InvalidArgument":
        reason = "INVALID_PAYLOAD"
        hint = "O Firestore rejeitou o documento. Verifique tipos/tamanho do payload sanitizado."
        retryable = False
    elif "RESOURCE_EXHAUSTED" in upper or "429" in upper or error_class == "ResourceExhausted":
        reason = "QUOTA_OR_RATE_LIMIT"
        hint = "O Firestore recusou temporariamente por quota/rate limit."
        retryable = True
    elif any(x in upper for x in ("UNAVAILABLE", "DEADLINE_EXCEEDED", "TIMEOUT", "CONNECTION", "DNS")):
        reason = "NETWORK_OR_SERVICE_UNAVAILABLE"
        hint = "Falha temporária de rede/serviço ao acessar o Firestore."
        retryable = True
    else:
        reason = "REMOTE_WRITE_FAILED"
        hint = "A escrita remota falhou; consulte error_class/error_code sem expor credenciais."
        retryable = True
    return {"reason": reason, "error_class": error_class, "error_code": code_name,
            "error": raw or None, "retryable": retryable, "hint": hint}


def _last_error_path() -> Path:
    return _state_root() / "telemetry-last-error.json"


def _record_last_error(details: dict[str, Any] | None) -> None:
    path = _last_error_path()
    try:
        if details is None:
            if path.exists(): path.unlink()
            return
        path.parent.mkdir(parents=True, exist_ok=True)
        safe = {"schema": SCHEMA, "recorded_at_unix": time.time(), **details}
        path.write_text(json.dumps(safe, indent=2, ensure_ascii=False, sort_keys=True), encoding="utf-8")
    except Exception:
        pass


def last_error() -> dict[str, Any] | None:
    try:
        p = _last_error_path()
        if p.exists():
            raw = json.loads(p.read_text(encoding="utf-8"))
            return raw if isinstance(raw, dict) else None
    except Exception:
        pass
    return None


def test_write_destination(preserve: bool = False) -> dict[str, Any]:
    """Explicit Firestore write probe.

    By default the probe document is deleted after a successful write.
    With preserve=True a deterministic visible probe document is kept in the
    configured collection so a human can verify it in the Firestore console.
    No user content or secret material is written.
    """
    cfg = load_destination()
    public_cfg = configuration(False)
    if not public_cfg.get("configured"):
        return {"schema": SCHEMA, "status": "FIRESTORE_UNCONFIGURED", "send_enabled": False,
                "configuration": public_cfg}
    if cfg.get("provider") == "HTTPS_GATEWAY":
        return {"schema": SCHEMA, "status": "WRITE_PROBE_NOT_APPLICABLE_GATEWAY", "send_enabled": True}
    client, err = _firestore_client(cfg)
    if err:
        return {"schema": SCHEMA, "status": "WRITE_PROBE_AUTH_BLOCKED", "send_enabled": False,
                "configuration": public_cfg, **err}
    collection_name = str(cfg.get("collection") or DEFAULT_COLLECTION)
    # The preserved probe uses a stable document id to avoid cluttering the
    # user's Firestore project with a new document on every verification run.
    ref = (client.collection(collection_name).document("phoenix-forge-live-write-probe")
           if preserve else client.collection(collection_name).document())
    probe = {"schema": "phoenix.forge.firestore-write-probe/v2", "product": "Phoenix Forge",
             "version": __import__('phoenix_forge').__version__, "probe": True,
             "visible_probe": bool(preserve), "created_at_unix": time.time(),
             "contains_user_content": False, "contains_secret_material": False}
    try:
        ref.set(probe)
    except Exception as exc:
        details = _safe_remote_error(exc); _record_last_error(details)
        return {"schema": SCHEMA, "status": "FIRESTORE_WRITE_PROBE_FAILED", "send_enabled": False,
                "project_id": cfg.get("project_id"), "collection": cfg.get("collection"), **details}
    cleanup_ok = None; cleanup_error = None
    if not preserve:
        cleanup_ok = True
        try:
            ref.delete()
        except Exception as exc:
            cleanup_ok = False; cleanup_error = _safe_remote_error(exc)
    _record_last_error(None)
    return {"schema": SCHEMA,
            "status": "FIRESTORE_VISIBLE_WRITE_READY" if preserve else "FIRESTORE_WRITE_READY",
            "send_enabled": True, "project_id": cfg.get("project_id"),
            "collection": collection_name, "document_id": ref.id,
            "preserved": bool(preserve), "cleanup_ok": cleanup_ok,
            "cleanup_error": cleanup_error, "contains_user_content": False,
            "contains_secret_material": False}


def test_write_visible() -> dict[str, Any]:
    """Write a visible, non-secret probe document for manual Firestore verification."""
    return test_write_destination(preserve=True)

def test_destination() -> dict[str, Any]:
    cfg = load_destination()
    if not cfg.get("enabled") or not cfg.get("project_id"):
        return {"schema": SCHEMA, "status": "FIRESTORE_UNCONFIGURED", "send_enabled": False, "configuration": configuration(False)}
    if cfg.get("provider") == "HTTPS_GATEWAY":
        return {"schema": SCHEMA, "status": "GATEWAY_CONFIGURED", "send_enabled": True, "configuration": configuration(False)}
    client, err = _firestore_client(cfg)
    if err:
        return {"schema": SCHEMA, "send_enabled": False, "configuration": configuration(False), **err}
    try:
        # Read-only authentication/network probe. At most one document is read.
        list(client.collection(str(cfg.get("collection") or DEFAULT_COLLECTION)).limit(1).stream())
        return {"schema": SCHEMA, "status": "FIRESTORE_READY", "send_enabled": True,
                "project_id": cfg.get("project_id"), "collection": cfg.get("collection"),
                "auth_mode": cfg.get("auth_mode")}
    except Exception as exc:
        return {"schema": SCHEMA, "status": "FIRESTORE_AUTH_OR_NETWORK_ERROR", "send_enabled": False,
                "error_class": type(exc).__name__, "error": str(exc)[:300], "configuration": configuration(False)}


def configuration(probe: bool = False) -> dict[str, Any]:
    cfg = load_destination()
    gateway = str(cfg.get("gateway_url") or "").strip()
    project = str(cfg.get("project_id") or "").strip()
    collection = str(cfg.get("collection") or DEFAULT_COLLECTION).strip() or DEFAULT_COLLECTION
    provider = str(cfg.get("provider") or "FIREBASE_FIRESTORE")
    configured = bool(cfg.get("enabled")) and bool(gateway or project)
    mode = "HTTPS_GATEWAY" if provider == "HTTPS_GATEWAY" and gateway else (
        "FIRESTORE_SERVICE_ACCOUNT" if configured and str(cfg.get("auth_mode") or "ADC").upper() == "SERVICE_ACCOUNT_FILE" else (
            "FIRESTORE_ADC" if configured else "UNCONFIGURED"
        )
    )
    out = {
        "schema": SCHEMA,
        "destination_schema": DESTINATION_SCHEMA,
        "provider": provider,
        "mode": mode,
        "state": "FIRESTORE_CONFIGURED" if configured and provider == "FIREBASE_FIRESTORE" else ("GATEWAY_CONFIGURED" if configured else "FIRESTORE_UNCONFIGURED"),
        "configured": configured,
        "enabled": bool(cfg.get("enabled")),
        "send_enabled": configured,
        "gateway_configured": bool(gateway),
        "firestore_project_configured": bool(project),
        "project_id": project or None,
        "collection": collection,
        "auth_mode": cfg.get("auth_mode") if provider == "FIREBASE_FIRESTORE" else None,
        "service_account_file_configured": bool(cfg.get("service_account_file")),
        "service_account_file": cfg.get("service_account_file"),
        "credential_source": cfg.get("credential_source"),
        "credential_discovery": cfg.get("credential_discovery"),
        "config_file": str(_destination_path()),
        "secrets_bundled": False,
        "public_client_policy": "Firebase/Firestore destination is configured persistently; credentials remain external to Phoenix Forge.",
    }
    if probe and provider == "FIREBASE_FIRESTORE" and configured:
        out["probe"] = test_destination()
        out["send_enabled"] = bool(out["probe"].get("send_enabled"))
    return out


def _get_installation_id() -> str | None:
    """Retorna installation_id da governance (nunca baseado em hardware)."""
    try:
        return telemetry_governance.status().get("installation_id")
    except Exception:
        return None


def _send_firestore_direct(envelope: dict[str, Any]) -> dict[str, Any]:
    """
    Envia envelope diretamente ao Firestore (modo DEV).
    Usada pelo retry worker para evitar dependência circular com send_now().
    """
    cfg = load_destination()
    client, err = _firestore_client(cfg)
    if err:
        return {**err, "retryable": False}
    try:
        ref = client.collection(str(cfg.get("collection") or DEFAULT_COLLECTION)).document()
        ref.set(envelope)
        return {"status": "SENT", "provider": "google-cloud-firestore",
                "document_id": ref.id, "project_id": cfg.get("project_id")}
    except Exception as exc:
        return _safe_remote_error(exc)


def preview() -> dict[str, Any]:
    st = telemetry_governance.status()
    built = telemetry_payload.build()
    return {"schema": SCHEMA, "status": "READY", "consent": st["consent"],
            "notice_version": st["notice_version"], "configuration": configuration(), "payload": built}


def preview_cached() -> dict[str, Any]:
    st = telemetry_governance.status()
    snap = snapshot_cache.get("telemetry-preview", telemetry_payload.build, max_age_s=20.0, wait_first_s=0.20)
    built = snap.get("value")
    if built is None:
        return {"schema": SCHEMA, "status": "WARMING", "consent": st["consent"],
                "notice_version": st["notice_version"], "configuration": configuration(), "payload": None,
                "snapshot": snap.get("snapshot", {}), "message": "Telemetry preview is being prepared in background."}
    return {"schema": SCHEMA, "status": "READY" if snap.get("snapshot", {}).get("fresh") else "STALE_REFRESHING",
            "consent": st["consent"], "notice_version": st["notice_version"], "configuration": configuration(),
            "payload": built, "snapshot": snap.get("snapshot", {})}


def _send_gateway(url: str, envelope: dict[str, Any]) -> dict[str, Any]:
    data = json.dumps(envelope, ensure_ascii=False).encode("utf-8")
    req = Request(url, data=data, headers={"Content-Type": "application/json", "User-Agent": "Phoenix-Forge-Telemetry/0.24.0"}, method="POST")
    with urlopen(req, timeout=15) as resp:
        body = resp.read(4096).decode("utf-8", "replace")
        return {"status": "SENT", "http_status": getattr(resp, "status", 200), "response_preview": body[:512]}


def _send_firestore(cfg: dict[str, Any], envelope: dict[str, Any]) -> dict[str, Any]:
    client, err = _firestore_client(cfg)
    if err:
        return err
    ref = client.collection(str(cfg.get("collection") or DEFAULT_COLLECTION)).document()
    ref.set(envelope)
    return {"status": "SENT", "provider": "google-cloud-firestore", "document_id": ref.id,
            "project_id": cfg.get("project_id"), "collection": cfg.get("collection")}


def send_now() -> dict[str, Any]:
    """
    Envia telemetria usando o modo de transporte ativo.

    Roteamento:
      OFF                          → BLOCKED_MODE_OFF
      PRODUCTION_CLOUD_RELAY       → telemetry_relay_client.send()
      DEVELOPMENT_DIRECT_FIRESTORE → Firestore SDK direto
    """
    # 0. Resolver modo antes de qualquer outra coisa
    from phoenix_forge.modules import telemetry_mode, telemetry_relay_client

    mode = telemetry_mode.resolve()
    if mode == "OFF":
        return {
            "schema": SCHEMA, "status": "BLOCKED_MODE_OFF", "send_enabled": False,
            "mode": mode,
            "message": "Telemetria desativada (PHOENIX_FORGE_TELEMETRY_MODE=OFF).",
        }

    # 1. Consentimento
    st = telemetry_governance.status()
    if not st["consent"]:
        return {"schema": SCHEMA, "status": "BLOCKED_NO_CONSENT", "notice_required": True,
                "send_enabled": False, "message": "Telemetria não enviada: consentimento não está ativo."}

    # 2. Configuração de destino (necessária apenas para DEV; PROD usa relay_url)
    cfg = load_destination()
    public_cfg = configuration(False)
    relay_url = telemetry_mode.relay_url()

    if mode == "PRODUCTION_CLOUD_RELAY" and not relay_url:
        return {"schema": SCHEMA, "status": "BLOCKED_UNCONFIGURED", "send_enabled": False,
                "mode": mode,
                "message": "PRODUCTION_CLOUD_RELAY ativo mas PHOENIX_FORGE_TELEMETRY_RELAY_URL não configurada."}

    if mode == "DEVELOPMENT_DIRECT_FIRESTORE" and not public_cfg.get("configured"):
        return {"schema": SCHEMA, "status": "BLOCKED_UNCONFIGURED", "send_enabled": False,
                "configuration": public_cfg,
                "message": "Configure o destino Firebase / Firestore antes de enviar."}

    # 3. Construir payload
    snap = snapshot_cache.get("telemetry-preview", telemetry_payload.build, max_age_s=30.0, wait_first_s=0.20)
    built = snap.get("value")
    if built is None:
        snapshot_cache.refresh_async("telemetry-preview", telemetry_payload.build)
        return {"schema": SCHEMA, "status": "SEND_DEFERRED_WARMING", "retryable": True,
                "send_enabled": True,
                "message": "Payload de telemetria está sendo preparado; tente novamente em instantes."}
    if not built.get("policy_ok"):
        return {"schema": SCHEMA, "status": "BLOCKED_SANITIZER_POLICY",
                "violations": built.get("policy_violations", []),
                "send_enabled": False, "message": "Envio bloqueado pela política de sanitização."}

    envelope = {
        "schema": SCHEMA,
        "notice_version": st["notice_version"],
        "forge_version": __import__("phoenix_forge").__version__,
        "mode": mode,
        "telemetry": built["payload"],
    }

    # 4. Enfileirar ANTES de tentar enviar (persistência + metadados de retry)
    from phoenix_forge.modules import telemetry_queue, telemetry_retry_worker
    queued = telemetry_queue.enqueue(envelope, transport_mode=mode)
    queue_item = telemetry_queue._load_item(queued) if queued else None
    claimed = telemetry_queue.claim(queued, "send_now") if queued else None
    if claimed:
        queued, queue_item = claimed

    # Worker também sobe no startup do Forge; esta chamada é idempotente.
    telemetry_retry_worker.ensure_started()

    # ---------- PRODUCTION_CLOUD_RELAY ----------
    if mode == "PRODUCTION_CLOUD_RELAY":
        installation_id = _get_installation_id()
        result = telemetry_relay_client.send(relay_url, envelope, installation_id=installation_id, event_id=(queue_item or {}).get("event_id"))
        status = result.get("status", "RELAY_UNAVAILABLE")

        # Renomear RELAY_UNAVAILABLE → QUEUED_RETRY para consistência de UI
        if status == "RELAY_UNAVAILABLE":
            status = "QUEUED_RETRY"
            result["status"] = status
            result["message"] = "Relay indisponível; retry automático agendado."

        if status == "QUEUED_OFFLINE":
            result["message"] = result.get(
                "hint", "Sem internet; payload na fila local. Retry automático quando online.")

        if status == "SENT":
            _record_last_error(None)
            if queued:
                telemetry_queue.mark_sent(queued)
            return {"schema": SCHEMA, "send_enabled": True,
                    "queue_file": None, "mode": mode,
                    "message": "Telemetria enviada ao Phoenix Cloud Relay.", **result}

        # Falhas não retentáveis → dead-letter imediato
        if not result.get("retryable", True):
            _record_last_error(result)
            if queued and queue_item:
                telemetry_queue.mark_dead_letter(queued, queue_item, status)
            return {"schema": SCHEMA, "status": status, "send_enabled": True,
                    "queue_file": queued.name if queued else None, "mode": mode, **result}

        # Retentável (QUEUED_OFFLINE ou QUEUED_RETRY): agendar próxima tentativa
        _record_last_error(result)
        if queued and queue_item:
            if status == "RELAY_RATE_LIMITED":
                delay = float(result.get("retry_after_seconds", 120))
            else:
                delay = telemetry_relay_client.next_retry_delay(1)
            telemetry_queue.mark_retry(queued, queue_item, status, delay)
        return {"schema": SCHEMA, "status": status, "send_enabled": True,
                "queue_file": queued.name if queued else None, "mode": mode, **result}

    # ---------- DEVELOPMENT_DIRECT_FIRESTORE ----------
    try:
        result_dev = _send_firestore_direct(envelope)
    except Exception as exc:
        result_dev = _safe_remote_error(exc)

    if result_dev.get("status") == "SENT":
        _record_last_error(None)
        if queued:
            telemetry_queue.mark_sent(queued)
        return {"schema": SCHEMA, "status": "SENT", "send_enabled": True,
                "queue_file": None, "mode": mode,
                "message": "Telemetria enviada ao Firebase / Firestore.", **result_dev}

    _record_last_error(result_dev)
    retryable = result_dev.get("retryable", True)
    status_out = "QUEUED_RETRY" if retryable else "QUEUED_SEND_FAILED"
    if queued and queue_item:
        if retryable:
            telemetry_queue.mark_retry(queued, queue_item, status_out,
                                       telemetry_relay_client.next_retry_delay(1))
        else:
            telemetry_queue.mark_dead_letter(queued, queue_item, status_out)
    return {"schema": SCHEMA, "status": status_out, "send_enabled": True,
            "queue_file": queued.name if queued else None, "mode": mode,
            "message": "Firestore está configurado, mas o envio falhou; payload mantido na fila local.",
            **result_dev}


def retry_queue(limit: int = 20) -> dict[str, Any]:
    """
    Retry manual de itens na fila (usado pelo comando forge retry-queue).
    Roteia pelo modo de transporte atual via telemetry_mode.resolve(),
    nunca pelo campo legado 'provider' da config de destino.
    """
    from phoenix_forge.modules import telemetry_mode, telemetry_queue, telemetry_relay_client, telemetry_retry_worker

    mode = telemetry_mode.resolve()
    if mode == "OFF":
        return {"schema": SCHEMA, "status": "BLOCKED_MODE_OFF", "send_enabled": False,
                "queued": 0, "message": "Telemetria desativada; retry não executado."}

    relay_url = telemetry_mode.relay_url() if mode == "PRODUCTION_CLOUD_RELAY" else None
    if mode == "PRODUCTION_CLOUD_RELAY" and not relay_url:
        return {"schema": SCHEMA, "status": "BLOCKED_UNCONFIGURED", "send_enabled": False,
                "message": "PRODUCTION_CLOUD_RELAY ativo mas RELAY_URL não configurada."}

    if mode == "DEVELOPMENT_DIRECT_FIRESTORE":
        public_cfg = configuration(False)
        if not public_cfg.get("configured"):
            return {"schema": SCHEMA, "status": "BLOCKED_UNCONFIGURED", "send_enabled": False,
                    "configuration": public_cfg}

    # Usar telemetry_queue para leitura e update de metadados
    pending = telemetry_queue.list_pending(max_items=max(1, min(int(limit), 100)))
    sent = 0; failed = 0; failures = []

    for path, _item in pending:
        claimed = telemetry_queue.claim(path, "manual-retry")
        if not claimed:
            continue
        path, item = claimed
        envelope = item.get("envelope", {})
        attempts = int(item.get("attempts", 0))
        try:
            if mode == "PRODUCTION_CLOUD_RELAY":
                result = telemetry_relay_client.send(relay_url, envelope,
                                                     installation_id=_get_installation_id(),
                                                     event_id=item.get("event_id"))
            else:
                result = _send_firestore_direct(envelope)

            if result.get("status") == "SENT":
                telemetry_queue.mark_sent(path)
                sent += 1
            elif result.get("retryable", True):
                delay = telemetry_relay_client.next_retry_delay(attempts + 1)
                telemetry_queue.mark_retry(path, item, result.get("status", "QUEUED_RETRY"), delay)
                failed += 1
                failures.append({"queue_file": path.name, "status": result.get("status")})
            else:
                telemetry_queue.mark_dead_letter(path, item, result.get("status", "DEAD_LETTER"))
                failed += 1
                failures.append({"queue_file": path.name, "status": result.get("status"),
                                  "dead_lettered": True})
        except Exception as exc:
            failed += 1
            details = _safe_remote_error(exc)
            _record_last_error(details)
            failures.append({"queue_file": path.name, **details})

    q_summary = telemetry_queue.queue_summary()
    if failed == 0 and sent > 0:
        _record_last_error(None)
    telemetry_retry_worker.ensure_started()
    return {"schema": SCHEMA,
            "status": "QUEUE_RETRY_COMPLETE" if failed == 0 else "QUEUE_RETRY_PARTIAL_FAILURE",
            "mode": mode, "attempted": len(pending), "sent": sent, "failed": failed,
            "remaining": q_summary.get("total_queued", 0), "failures": failures[:10]}

def clear_queue() -> dict[str, Any]:
    q = _queue_dir(); removed = 0
    if q.exists():
        for p in q.glob("*.json"):
            try: p.unlink(); removed += 1
            except Exception: pass
    return {"schema": SCHEMA, "status": "QUEUE_CLEARED", "removed": removed}


def status() -> dict[str, Any]:
    from phoenix_forge.modules import telemetry_mode, telemetry_queue, telemetry_retry_worker
    mode_info = telemetry_mode.describe()
    q_summary = telemetry_queue.queue_summary()
    return {
        "schema": SCHEMA,
        "consent": telemetry_governance.status(),
        "configuration": configuration(),
        "transport_mode": mode_info,
        "queue": q_summary,
        "queued": q_summary.get("total_queued", 0),
        "retry_worker": telemetry_retry_worker.worker_status(),
        "last_remote_error": last_error(),
    }
