from __future__ import annotations

import json
import os
import secrets
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

SCHEMA = "phoenix.forge.telemetry-governance/v1"
NOTICE_VERSION = "2026-09-14.v1"
DEFAULT_CATEGORIES = {
    "product": True,
    "hardware_summary": True,
    "topology": True,
    "capabilities": True,
    "benchmarks": True,
    "reliability": True,
    "diagnostics": True,
    "storage": True,
    "sensors": True,
}

SENSITIVE_FIELD_FRAGMENTS = {
    "serial", "uuid", "username", "user_name", "path", "filepath", "file_path",
    "prompt", "messages", "message", "text", "content", "document", "ocr_text",
    "expected_text", "token", "password", "secret", "credential", "email", "ip_address",
    "mac_address", "hostname", "computername", "pnp_device_id", "instance_id",
}


def _state_root() -> Path:
    root = os.getenv("PHOENIX_FORGE_STATE_DIR")
    if root:
        return Path(root)
    return Path.home() / ".phoenix-forge"


def _state_path() -> Path:
    return _state_root() / "telemetry-consent.json"


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _default_state() -> dict[str, Any]:
    return {
        "schema": SCHEMA,
        "notice_version": NOTICE_VERSION,
        "consent": False,
        "consented_at": None,
        "revoked_at": None,
        "installation_id": None,
        "categories": dict(DEFAULT_CATEGORIES),
    }


def load() -> dict[str, Any]:
    state = _default_state()
    path = _state_path()
    try:
        if path.exists():
            raw = json.loads(path.read_text(encoding="utf-8"))
            if isinstance(raw, dict):
                state.update(raw)
    except Exception:
        state["state_read_error"] = True
    if not state.get("installation_id"):
        # Random installation pseudonym: never derived from BIOS UUID, serial, MAC or user identity.
        state["installation_id"] = secrets.token_hex(16)
        try:
            save(state)
        except Exception:
            pass
    return state


def save(state: dict[str, Any]) -> None:
    path = _state_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(state, indent=2, sort_keys=True), encoding="utf-8")
    tmp.replace(path)


def privacy_notice() -> dict[str, Any]:
    return {
        "schema": SCHEMA,
        "notice_version": NOTICE_VERSION,
        "title": "Phoenix Forge — aviso de telemetria opcional",
        "summary": (
            "Com sua autorização, o Phoenix Forge pode enviar telemetria técnica para ajudar a medir "
            "compatibilidade, estabilidade, desempenho e falhas de hardware. A coleta fica desligada até o consentimento."
        ),
        "may_collect": [
            "versão do Phoenix Forge e capacidades/providers disponíveis",
            "resumo de CPU/GPU/RAM/placa-mãe sem números de série",
            "topologia agregada: sockets, NUMA, GPUs e estado PCIe quando disponível",
            "resultados de benchmark/stress e classes de falha",
            "temperaturas/cargas agregadas e estado de sensores, quando disponíveis",
            "storage/NVMe health agregado e contadores técnicos permitidos",
            "status de qualification/safety e decisões CPU/GPU/HYBRID sem conteúdo do usuário",
        ],
        "never_collect_by_policy": [
            "prompts, mensagens, documentos ou conteúdo de chat",
            "OCR/transcrições ou texto gerado pelo usuário",
            "senhas, tokens, chaves, credenciais ou cookies",
            "nome de usuário, nome do computador, e-mail, MAC ou endereço IP gravado no payload",
            "caminhos completos de arquivos/modelos",
            "números de série de disco/DIMM/GPU, UUID de BIOS/sistema ou PnP instance IDs completos",
        ],
        "controls": {
            "default": "OFF",
            "preview_before_send": True,
            "revoke_any_time": True,
            "category_controls": True,
        },
    }


def consent(accepted_notice_version: str, categories: dict[str, bool] | None = None) -> dict[str, Any]:
    if accepted_notice_version != NOTICE_VERSION:
        raise ValueError("notice_version_mismatch")
    state = load()
    state["consent"] = True
    state["notice_version"] = NOTICE_VERSION
    state["consented_at"] = _now()
    state["revoked_at"] = None
    if categories:
        merged = dict(DEFAULT_CATEGORIES)
        for key, value in categories.items():
            if key in merged:
                merged[key] = bool(value)
        state["categories"] = merged
    save(state)
    return status()


def revoke() -> dict[str, Any]:
    state = load()
    state["consent"] = False
    state["notice_version"] = NOTICE_VERSION
    state["revoked_at"] = _now()
    save(state)
    return status()


def status() -> dict[str, Any]:
    state = load()
    stored_notice = str(state.get("notice_version") or "")
    version_current = stored_notice == NOTICE_VERSION
    consented = bool(state.get("consent")) and version_current
    explicitly_declined = bool(state.get("revoked_at")) and version_current and not consented
    return {
        "schema": SCHEMA,
        "notice_version": NOTICE_VERSION,
        "stored_notice_version": stored_notice or None,
        "consent": consented,
        "decision": "ACCEPTED" if consented else ("DECLINED" if explicitly_declined else "PENDING"),
        "consented_at": state.get("consented_at"),
        "revoked_at": state.get("revoked_at"),
        "installation_id": state.get("installation_id"),
        "categories": dict(state.get("categories") or DEFAULT_CATEGORIES),
        "collection_enabled": consented,
        "notice_required": not version_current or (not consented and not explicitly_declined),
    }
