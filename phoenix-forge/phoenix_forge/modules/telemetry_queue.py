"""
Phoenix Forge — Telemetry Queue  (0.24.0)
============================================
Fila local persistente de itens de telemetria com metadados de retry.

Cada item é um arquivo JSON em ~/.phoenix-forge/telemetry-queue/ com schema:

  {
    "queue_schema": "phoenix.forge.telemetry-queue-item/v1",
    "event_id": "<UUIDv4>",
    "created_at": "<ISO8601>",
    "attempts": 0,
    "next_retry_at": null,
    "last_status": "PENDING",
    "transport_mode": "PRODUCTION_CLOUD_RELAY",
    "envelope": { <payload sanitizado> }
  }

Compatibilidade retroativa:
  Itens antigos (sem "queue_schema") são tratados como envelope puro —
  são lidos e migrados automaticamente para o novo formato ao serem
  processados pelo retry worker.

Invariants:
  - event_id é gerado no cliente e imutável; permite idempotência no relay
  - A fila existe apenas em disco; nunca em memória como estrutura mutable
  - Falhas de I/O nunca propagam exceção para o caller
  - Telemetria falhar NUNCA derruba Forge, Engine ou chat
"""
from __future__ import annotations

import json
import os
import secrets
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
import threading

QUEUE_ITEM_SCHEMA = "phoenix.forge.telemetry-queue-item/v2"
_CLAIM_LEASE_S = 120
_MAX_QUEUE_SIZE   = 500   # itens máximos na fila (FIFO: descarta os mais antigos)


def _state_root() -> Path:
    base = os.getenv("PHOENIX_FORGE_STATE_DIR")
    return Path(base) if base else (Path.home() / ".phoenix-forge")


def _queue_dir() -> Path:
    return _state_root() / "telemetry-queue"


def _dead_letter_dir() -> Path:
    return _state_root() / "telemetry-dead-letter"

def _inflight_dir() -> Path:
    return _state_root() / "telemetry-inflight"


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _new_event_id() -> str:
    return secrets.token_hex(16)  # 128-bit aleatório; não baseado em hardware


# ---------------------------------------------------------------------------
# Enqueue
# ---------------------------------------------------------------------------

def enqueue(envelope: dict[str, Any], transport_mode: str = "UNKNOWN") -> Path | None:
    """
    Persiste *envelope* na fila local ANTES de qualquer tentativa de envio.
    Retorna Path do arquivo criado, ou None em caso de falha de I/O.

    Garante espaço: se a fila exceder _MAX_QUEUE_SIZE, remove os mais antigos.
    """
    try:
        q = _queue_dir()
        q.mkdir(parents=True, exist_ok=True)

        # Limitar tamanho
        existing = sorted(q.glob("*.json"))
        if len(existing) >= _MAX_QUEUE_SIZE:
            for old in existing[:len(existing) - _MAX_QUEUE_SIZE + 1]:
                try:
                    old.unlink()
                except Exception:
                    pass

        event_id = _new_event_id()
        item: dict[str, Any] = {
            "queue_schema": QUEUE_ITEM_SCHEMA,
            "event_id": event_id,
            "created_at": _now_iso(),
            "attempts": 0,
            "next_retry_at": None,
            "last_status": "PENDING",
            "transport_mode": transport_mode,
            "envelope": envelope,
        }
        ts_ms = int(time.time() * 1000)
        path = q / f"{ts_ms}-{event_id[:8]}.json"
        path.write_text(json.dumps(item, ensure_ascii=False, sort_keys=False), encoding="utf-8")
        return path
    except Exception:
        return None


# ---------------------------------------------------------------------------
# Leitura e migração
# ---------------------------------------------------------------------------

def _load_item(path: Path) -> dict[str, Any] | None:
    """
    Carrega item da fila.
    Itens antigos sem queue_schema são migrados automaticamente para o novo formato.
    """
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(raw, dict):
            return None
        if raw.get("queue_schema") == QUEUE_ITEM_SCHEMA:
            return raw
        # Migração: envelope puro (formato antigo)
        return {
            "queue_schema": QUEUE_ITEM_SCHEMA,
            "event_id": raw.get("event_id") or _new_event_id(),
            "created_at": raw.get("created_at") or _now_iso(),
            "attempts": 0,
            "next_retry_at": None,
            "last_status": "PENDING",
            "transport_mode": "UNKNOWN",
            "envelope": raw,  # envelope é o próprio dict
        }
    except Exception:
        return None


def list_pending(max_items: int = 100) -> list[tuple[Path, dict[str, Any]]]:
    """
    Retorna lista de (Path, item) prontos para envio (next_retry_at <= agora).
    Itens dead-letter são excluídos.
    """
    recover_expired_claims()
    q = _queue_dir()
    if not q.exists():
        return []
    now = time.time()
    result: list[tuple[Path, dict[str, Any]]] = []
    for path in sorted(q.glob("*.json"))[:max(1, min(int(max_items), 500))]:
        item = _load_item(path)
        if item is None:
            continue
        if item.get("last_status") == "DEAD_LETTER":
            continue
        next_retry = item.get("next_retry_at")
        if next_retry is not None:
            try:
                if float(next_retry) > now:
                    continue  # ainda aguardando backoff
            except (TypeError, ValueError):
                pass
        result.append((path, item))
    return result


# ---------------------------------------------------------------------------
# Atualização de estado
# ---------------------------------------------------------------------------

def mark_sent(path: Path) -> None:
    """Remove item da fila após envio confirmado."""
    try:
        path.unlink()
    except Exception:
        pass


def mark_retry(path: Path, item: dict[str, Any], status: str, delay_s: float) -> None:
    """Persiste retry; claims são devolvidos atomicamente à fila."""
    if path.parent == _inflight_dir():
        release_claim_for_retry(path, item, status, delay_s)
        return
    try:
        item = dict(item)
        item["attempts"] = int(item.get("attempts", 0)) + 1
        item["last_status"] = status
        item["next_retry_at"] = time.time() + delay_s
        item["last_attempt_at"] = _now_iso()
        path.write_text(json.dumps(item, ensure_ascii=False, sort_keys=False), encoding="utf-8")
    except Exception:
        pass


def mark_dead_letter(path: Path, item: dict[str, Any], last_status: str) -> None:
    """Move item para dead-letter (não será retentado automaticamente)."""
    try:
        dl = _dead_letter_dir()
        dl.mkdir(parents=True, exist_ok=True)
        item = dict(item)
        item["last_status"] = "DEAD_LETTER"
        item["dead_lettered_at"] = _now_iso()
        item["dead_letter_reason"] = last_status
        dl_path = dl / path.name
        dl_path.write_text(json.dumps(item, ensure_ascii=False, sort_keys=False), encoding="utf-8")
        try:
            path.unlink()
        except Exception:
            pass
    except Exception:
        pass



# ---------------------------------------------------------------------------
# Claim / lease atômico
# ---------------------------------------------------------------------------

def recover_expired_claims() -> int:
    """Retorna claims expirados para a fila. Seguro após crash/reboot."""
    recovered = 0
    inflight = _inflight_dir()
    if not inflight.exists():
        return 0
    now = time.time()
    q = _queue_dir(); q.mkdir(parents=True, exist_ok=True)
    for path in inflight.glob("*.json"):
        item = _load_item(path)
        if item is None:
            continue
        try:
            lease_until = float(item.get("lease_until") or 0)
        except Exception:
            lease_until = 0
        if lease_until and lease_until > now:
            continue
        try:
            item = dict(item)
            item["last_status"] = "QUEUED_RETRY"
            item["claim_owner"] = None
            item["claimed_at"] = None
            item["lease_until"] = None
            path.write_text(json.dumps(item, ensure_ascii=False), encoding="utf-8")
            os.replace(path, q / path.name)
            recovered += 1
        except Exception:
            pass
    return recovered


def claim(path: Path, owner: str, lease_s: int = _CLAIM_LEASE_S) -> tuple[Path, dict[str, Any]] | None:
    """Reivindica um item via os.replace() atômico. Só um consumidor vence."""
    try:
        inflight = _inflight_dir(); inflight.mkdir(parents=True, exist_ok=True)
        claimed = inflight / path.name
        os.replace(path, claimed)
        item = _load_item(claimed)
        if item is None:
            try: os.replace(claimed, _queue_dir() / path.name)
            except Exception: pass
            return None
        item = dict(item)
        now = time.time()
        item["last_status"] = "SENDING"
        item["claim_owner"] = owner
        item["claimed_at"] = _now_iso()
        item["lease_until"] = now + max(15, int(lease_s))
        claimed.write_text(json.dumps(item, ensure_ascii=False), encoding="utf-8")
        return claimed, item
    except FileNotFoundError:
        return None
    except Exception:
        return None


def release_claim_for_retry(path: Path, item: dict[str, Any], status: str, delay_s: float) -> None:
    """Atualiza retry e devolve o item claimed à fila."""
    try:
        q = _queue_dir(); q.mkdir(parents=True, exist_ok=True)
        item = dict(item)
        item["attempts"] = int(item.get("attempts", 0)) + 1
        item["last_status"] = status
        item["next_retry_at"] = time.time() + max(0.0, float(delay_s))
        item["last_attempt_at"] = _now_iso()
        item["claim_owner"] = None; item["claimed_at"] = None; item["lease_until"] = None
        path.write_text(json.dumps(item, ensure_ascii=False), encoding="utf-8")
        os.replace(path, q / path.name)
    except Exception:
        pass

# ---------------------------------------------------------------------------
# Inspeção
# ---------------------------------------------------------------------------

def queue_summary() -> dict[str, Any]:
    """Resumo do estado da fila para status() e UI."""
    recover_expired_claims()
    q = _queue_dir()
    dl = _dead_letter_dir()
    inflight_dir = _inflight_dir()
    pending = 0
    waiting_backoff = 0
    now = time.time()
    oldest_ts: float | None = None

    if q.exists():
        for path in q.glob("*.json"):
            item = _load_item(path)
            if item is None:
                continue
            next_retry = item.get("next_retry_at")
            if next_retry is not None:
                try:
                    if float(next_retry) > now:
                        waiting_backoff += 1
                        continue
                except (TypeError, ValueError):
                    pass
            pending += 1
            try:
                created = path.stat().st_mtime
                if oldest_ts is None or created < oldest_ts:
                    oldest_ts = created
            except Exception:
                pass

    dead_letters = len(list(dl.glob("*.json"))) if dl.exists() else 0
    inflight = len(list(inflight_dir.glob("*.json"))) if inflight_dir.exists() else 0
    return {
        "schema": QUEUE_ITEM_SCHEMA,
        "pending": pending,
        "waiting_backoff": waiting_backoff,
        "total_queued": pending + waiting_backoff,
        "dead_letters": dead_letters,
        "inflight": inflight,
        "oldest_queued_seconds": int(now - oldest_ts) if oldest_ts else None,
        "queue_dir": str(q),
    }


def clear_queue() -> dict[str, Any]:
    """Remove todos os itens da fila (não move para dead-letter)."""
    q = _queue_dir()
    removed = 0
    if q.exists():
        for p in q.glob("*.json"):
            try:
                p.unlink()
                removed += 1
            except Exception:
                pass
    return {"schema": QUEUE_ITEM_SCHEMA, "status": "QUEUE_CLEARED", "removed": removed}
