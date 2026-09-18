"""
Phoenix Forge — Telemetry Retry Worker  (0.24.0)
===================================================
Daemon singleton thread que processa a fila local de telemetria,
reenviando itens pendentes ao relay (PRODUCTION_CLOUD_RELAY) ou
ao Firestore direto (DEVELOPMENT_DIRECT_FIRESTORE).

Responsabilidades:
  - Iniciar uma única thread daemon (idempotente, thread-safe)
  - Poliar telemetry_queue.list_pending() periodicamente
  - Despachar via telemetry_mode.resolve() — nunca pelo campo legado "provider"
  - Atualizar metadados da fila: attempts, next_retry_at, last_status
  - Mover para dead-letter após esgotar tentativas
  - Nunca propagar exceção para fora da thread

Invariants:
  - Worker crash nunca derruba Forge, Engine ou chat
  - Thread é daemon=True: encerra automaticamente quando o processo principal termina
  - Apenas uma thread por processo (lock global + flag)
  - Não persiste estado além dos arquivos da fila (telemetry_queue.py)
"""
from __future__ import annotations

import threading
import time
import traceback
from typing import Any

# Intervalo de polling da fila (segundos)
_POLL_INTERVAL_S = 30
# Itens por ciclo de polling (evita burst)
_BATCH_SIZE = 20

_worker_lock = threading.Lock()
_worker_started = False
_worker_thread: threading.Thread | None = None


# ---------------------------------------------------------------------------
# Inicialização (pública)
# ---------------------------------------------------------------------------

def ensure_started() -> bool:
    """
    Garante que o worker daemon está rodando.
    Idempotente: chamadas subsequentes são no-op.
    Retorna True se o thread foi criado agora, False se já existia.
    """
    global _worker_started, _worker_thread

    with _worker_lock:
        if _worker_started and _worker_thread is not None and _worker_thread.is_alive():
            return False  # já rodando
        _worker_thread = threading.Thread(
            target=_worker_loop,
            name="forge-telemetry-retry-worker",
            daemon=True,
        )
        _worker_thread.start()
        _worker_started = True
        return True


def is_running() -> bool:
    """True se o worker daemon está vivo."""
    with _worker_lock:
        return _worker_thread is not None and _worker_thread.is_alive()


# ---------------------------------------------------------------------------
# Loop principal (privado)
# ---------------------------------------------------------------------------

def _worker_loop() -> None:
    """
    Loop principal do worker daemon.
    Qualquer exceção não capturada dentro de _process_batch() é absorvida aqui.
    """
    while True:
        try:
            _process_batch()
        except Exception:
            # Absorve tudo: worker crash não propaga
            pass
        time.sleep(_POLL_INTERVAL_S)


def _process_batch() -> None:
    """
    Processa um lote de itens pendentes da fila.
    Determina o modo de transporte atual e despacha cada item.
    """
    from phoenix_forge.modules import telemetry_queue
    from phoenix_forge.modules import telemetry_mode
    from phoenix_forge.modules import telemetry_relay_client

    mode = telemetry_mode.resolve()

    # Nada a fazer se telemetria está desativada
    if mode == "OFF":
        return

    relay_url = telemetry_mode.relay_url() if mode == "PRODUCTION_CLOUD_RELAY" else None

    pending = telemetry_queue.list_pending(max_items=_BATCH_SIZE)
    owner = f"worker-{threading.get_ident()}"
    for path, _item in pending:
        claimed = telemetry_queue.claim(path, owner)
        if not claimed:
            continue
        claimed_path, item = claimed
        try:
            _dispatch_item(claimed_path, item, mode, relay_url, telemetry_queue, telemetry_relay_client)
        except Exception:
            # Item individual falhou sem update: ignora, tenta no próximo ciclo
            pass


def _dispatch_item(
    path: Any,
    item: dict[str, Any],
    mode: str,
    relay_url: str | None,
    telemetry_queue: Any,
    telemetry_relay_client: Any,
) -> None:
    """
    Despacha um único item da fila de acordo com o modo de transporte.
    Atualiza os metadados do item com o resultado.
    """
    attempts = int(item.get("attempts", 0))
    envelope = item.get("envelope", {})

    if mode == "PRODUCTION_CLOUD_RELAY":
        result = _send_via_relay(envelope, relay_url, telemetry_relay_client, event_id=item.get("event_id"))
    elif mode == "DEVELOPMENT_DIRECT_FIRESTORE":
        result = _send_via_firestore(envelope)
    else:
        # Modo desconhecido: skip silencioso
        return

    status = result.get("status", "UNKNOWN")

    # Sucesso
    if status == "SENT":
        telemetry_queue.mark_sent(path)
        return

    # Verificar se deve retenviar
    if telemetry_relay_client.should_retry(result, attempts + 1):
        # Rate limited com Retry-After explícito
        if status == "RELAY_RATE_LIMITED":
            delay = float(result.get("retry_after_seconds", 120))
        else:
            delay = telemetry_relay_client.next_retry_delay(attempts + 1)
        telemetry_queue.mark_retry(path, item, status, delay)
    else:
        # Não retentável ou esgotou tentativas → dead-letter
        dl = telemetry_relay_client.dead_letter_status(str(path), result)
        telemetry_queue.mark_dead_letter(path, item, dl.get("status", "DEAD_LETTER"))


def _send_via_relay(
    envelope: dict[str, Any],
    relay_url: str | None,
    telemetry_relay_client: Any,
    event_id: str | None = None,
) -> dict[str, Any]:
    """Envia envelope ao Phoenix Cloud Relay."""
    if not relay_url:
        return {
            "status": "BLOCKED_UNCONFIGURED",
            "retryable": False,
            "hint": "PHOENIX_FORGE_TELEMETRY_RELAY_URL não configurada.",
        }
    try:
        from phoenix_forge.modules import firestore_telemetry as ft
        installation_id = ft._get_installation_id() if hasattr(ft, "_get_installation_id") else None
    except Exception:
        installation_id = None

    return telemetry_relay_client.send(relay_url, envelope, installation_id=installation_id, event_id=event_id)


def _send_via_firestore(envelope: dict[str, Any]) -> dict[str, Any]:
    """
    Envia envelope diretamente ao Firestore (modo DEV).
    Delega ao firestore_telemetry sem criar dependência circular:
    usa _send_firestore_direct() se disponível, senão send_now() com guarda de modo.
    """
    try:
        from phoenix_forge.modules import firestore_telemetry as ft
        if hasattr(ft, "_send_firestore_direct"):
            return ft._send_firestore_direct(envelope)
        # Fallback: send_now() só roda em DEV neste ponto (mode já verificado)
        return ft.send_now()
    except Exception as exc:
        return {
            "status": "QUEUED_SEND_FAILED",
            "retryable": False,
            "error_class": type(exc).__name__,
        }


# ---------------------------------------------------------------------------
# Diagnóstico
# ---------------------------------------------------------------------------

def worker_status() -> dict[str, Any]:
    """Retorna estado do worker para status() e UI."""
    return {
        "schema": "phoenix.forge.telemetry-retry-worker/v1",
        "running": is_running(),
        "poll_interval_seconds": _POLL_INTERVAL_S,
        "batch_size": _BATCH_SIZE,
    }
