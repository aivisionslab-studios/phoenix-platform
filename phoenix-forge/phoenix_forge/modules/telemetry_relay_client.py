"""
Phoenix Forge — Telemetry Relay Client  (0.24.0)
===================================================
Cliente HTTP para o Phoenix Cloud Relay (modo PRODUCTION_CLOUD_RELAY).

Responsabilidades:
  - Enviar payloads sanitizados ao endpoint do relay via HTTPS POST
  - Classificar resposta/exceção em estados estruturados (sem probe separado)
  - Retry schedule com exponential backoff + jitter ±10%
  - Nunca carregar, buscar ou transmitir service account

REMOVIDO em 0.24.0 vs rascunho anterior:
  - socket.setdefaulttimeout() — alterava timeout global do processo
  - _is_online() com DNS probe (8.8.8.8:53) — frágil em VPN/corp
  A conectividade é determinada pela própria tentativa HTTPS.

Estados de retorno (campo "status"):
  SENT                — relay confirmou recebimento (200/201/202/409)
  QUEUED_OFFLINE      — sem conectividade de rede (DNS/connect/SSL falhou)
  QUEUED_RETRY        — falha transiente do relay (5xx, timeout)
  REJECTED_AUTH       — 401; não retentável
  REJECTED_SCHEMA     — 422; payload inválido; não retentável
  REJECTED_POLICY     — 403 ou campo bloqueado; não retentável
  REJECTED_TOO_LARGE  — 413; não retentável
  RELAY_RATE_LIMITED  — 429; retentável após Retry-After
  RELAY_UNAVAILABLE   — 5xx genérico; retentável
  DEAD_LETTER         — esgotou tentativas; não retenta mais
  HTTPS_REQUIRED      — URL não usa HTTPS (localhost exempt); não retentável

Retry schedule padrão (jitter ±10 %):
  tentativa 0 → imediata
  1 → 60 s | 2 → 120 s | 3 → 300 s | 4 → 900 s | 5 → 1800 s | 6+ → 3600 s
"""
from __future__ import annotations

import json
import random
import urllib.error
import urllib.request
from typing import Any

SCHEMA = "phoenix.forge.telemetry-relay-client/v1"

_RELAY_TIMEOUT_S   = 15
_MAX_PAYLOAD_BYTES = 512 * 1024   # 512 KB hard limit antes de enviar
_MAX_ATTEMPTS      = 7
_RETRY_DELAYS      = [60, 120, 300, 900, 1800, 3600]  # segundos
_JITTER_FACTOR     = 0.10         # ±10 %

# Segunda barreira de segurança (além da sanitização do Forge)
_BLOCKED_KEY_FRAGMENTS = frozenset({
    "private_key", "access_token", "refresh_token", "authorization",
    "cookie", "password", "prompt", "response", "user_content",
    "file_content", "home_path", "username", "email", "credential",
    "secret", "bearer", "api_key",
})
_BLOCKED_VALUE_PATTERNS = (
    "-----BEGIN PRIVATE KEY-----",
    "-----BEGIN RSA PRIVATE KEY-----",
    "AIza",    # prefixo de API keys Google
    "Bearer ",
)


# ---------------------------------------------------------------------------
# Utilitários internos
# ---------------------------------------------------------------------------

def _jitter(delay: float) -> float:
    return delay * (1.0 + random.uniform(-_JITTER_FACTOR, _JITTER_FACTOR))


def _forge_version() -> str:
    try:
        import phoenix_forge
        return str(phoenix_forge.__version__)
    except Exception:
        return "unknown"


def _is_localhost_url(url: str) -> bool:
    lower = url.lower()
    return "://localhost" in lower or "://127.0.0.1" in lower or "://[::1]" in lower


def validate_relay_url(url: str) -> dict[str, Any] | None:
    """
    Valida que a URL do relay usa HTTPS (exceto localhost em dev).
    Retorna None se válida, ou dict de erro se inválida.
    """
    if not url:
        return {"status": "HTTPS_REQUIRED", "retryable": False,
                "hint": "PHOENIX_FORGE_TELEMETRY_RELAY_URL não configurada."}
    if url.lower().startswith("https://"):
        return None
    if url.lower().startswith("http://") and _is_localhost_url(url):
        return None  # HTTP permitido apenas para localhost em dev
    return {
        "schema": SCHEMA,
        "status": "HTTPS_REQUIRED",
        "retryable": False,
        "hint": (
            "URL do relay deve usar HTTPS. "
            "HTTP é aceito apenas para localhost (dev). "
            f"URL recebida: {url[:80]}"
        ),
    }


# ---------------------------------------------------------------------------
# Verificação de segurança no cliente
# ---------------------------------------------------------------------------

def _check_payload_safety(envelope: dict[str, Any]) -> list[str]:
    """Varredura rasa de segurança. Retorna lista de violações (vazia = seguro)."""
    violations: list[str] = []
    raw = json.dumps(envelope, ensure_ascii=False)
    for pattern in _BLOCKED_VALUE_PATTERNS:
        if pattern in raw:
            violations.append(f"blocked_value_pattern:{pattern[:12]}…")

    def _scan_keys(obj: Any, depth: int = 0) -> None:
        if depth > 10:
            return
        if isinstance(obj, dict):
            for k, v in obj.items():
                kl = str(k).lower()
                if any(frag in kl for frag in _BLOCKED_KEY_FRAGMENTS):
                    violations.append(f"blocked_key:{k}")
                _scan_keys(v, depth + 1)
        elif isinstance(obj, list):
            for item in obj[:20]:
                _scan_keys(item, depth + 1)

    _scan_keys(envelope)
    return violations


# ---------------------------------------------------------------------------
# Classificação de resposta HTTP
# ---------------------------------------------------------------------------

def _classify_http(status_code: int, body: str, retry_after: int | None) -> dict[str, Any]:
    """Mapeia código HTTP → status estruturado."""
    if status_code in {200, 201, 202}:
        try:
            data = json.loads(body)
        except Exception:
            data = {}
        return {"status": "SENT", "http_status": status_code, "retryable": False,
                "server_event_id": data.get("event_id"),
                "server_status": data.get("status")}
    if status_code == 401:
        return {"status": "REJECTED_AUTH", "http_status": status_code, "retryable": False,
                "hint": "Relay rejeitou por autenticação; verifique installation_id ou configuração."}
    if status_code == 403:
        return {"status": "REJECTED_POLICY", "http_status": status_code, "retryable": False,
                "hint": "Relay rejeitou por política; payload pode conter campo bloqueado."}
    if status_code == 409:
        # Duplicata idempotente — tratar como SENT
        return {"status": "SENT", "http_status": status_code, "retryable": False,
                "note": "duplicate_idempotent"}
    if status_code == 413:
        return {"status": "REJECTED_TOO_LARGE", "http_status": status_code, "retryable": False,
                "hint": "Payload excede limite do relay; reduza categorias ativas."}
    if status_code == 422:
        return {"status": "REJECTED_SCHEMA", "http_status": status_code, "retryable": False,
                "hint": "Relay rejeitou schema; atualize o Forge."}
    if status_code == 429:
        return {"status": "RELAY_RATE_LIMITED", "http_status": status_code, "retryable": True,
                "retry_after_seconds": retry_after or 120,
                "hint": "Rate limit do relay; retry respeitará Retry-After."}
    if status_code >= 500:
        return {"status": "RELAY_UNAVAILABLE", "http_status": status_code, "retryable": True,
                "hint": "Relay indisponível temporariamente; retry automático agendado."}
    return {"status": "REJECTED_POLICY", "http_status": status_code, "retryable": False,
            "hint": f"Relay retornou {status_code}; não retentável."}


def _classify_network_error(exc: Exception) -> dict[str, Any]:
    """
    Classifica exceção de rede como QUEUED_OFFLINE (problema de conectividade)
    ou RELAY_UNAVAILABLE (relay acessível mas indisponível).
    Não usa probe separado — o próprio erro determina a categoria.
    """
    reason = ""
    if isinstance(exc, urllib.error.URLError):
        reason = str(exc.reason or "")
    elif isinstance(exc, TimeoutError):
        reason = "connection_timeout"
    else:
        reason = type(exc).__name__

    upper = reason.upper()
    # Indicadores de ausência de conectividade de rede
    offline_signals = (
        "NODENAME", "GETADDRINFO", "NAME OR SERVICE",
        "NETWORK IS UNREACHABLE", "NO ROUTE",
        "NAME_NOT_RESOLVED", "ERR_NAME",
        "TEMPORARY FAILURE IN NAME RESOLUTION",
    )
    if any(sig in upper for sig in offline_signals):
        return {
            "schema": SCHEMA, "status": "QUEUED_OFFLINE", "retryable": True,
            "reason": reason[:200],
            "hint": "Sem conectividade de rede; payload permanece na fila. Retry automático quando online.",
        }
    # Timeout ou recusa — relay pode estar temporariamente indisponível
    return {
        "schema": SCHEMA, "status": "RELAY_UNAVAILABLE", "retryable": True,
        "reason": reason[:200],
        "hint": "Falha transiente ao contactar relay; retry automático agendado.",
    }


# ---------------------------------------------------------------------------
# Envio principal
# ---------------------------------------------------------------------------

def send(url: str, envelope: dict[str, Any], installation_id: str | None = None, event_id: str | None = None) -> dict[str, Any]:
    """
    Envia *envelope* (já sanitizado pelo Forge) ao relay em *url*.

    Retorna dict com campo 'status'. Nunca lança exceção.
    A conectividade é determinada pela própria tentativa HTTPS —
    não há probe separado que possa gerar falsos negativos.
    """
    # 1. HTTPS obrigatório
    url_err = validate_relay_url(url)
    if url_err:
        return {**url_err, "schema": SCHEMA}

    # 2. Verificação de segurança local
    violations = _check_payload_safety(envelope)
    if violations:
        return {
            "schema": SCHEMA, "status": "REJECTED_POLICY", "retryable": False,
            "reason": "client_safety_check_failed",
            "violations": violations[:10],
            "hint": "Payload contém campos bloqueados; não enviado.",
        }

    # 3. Serializar e verificar tamanho
    try:
        wire_payload = {"event_id": event_id, "installation_id": installation_id, "envelope": envelope}
        body_bytes = json.dumps(wire_payload, ensure_ascii=False).encode("utf-8")
    except Exception as exc:
        return {"schema": SCHEMA, "status": "REJECTED_SCHEMA", "retryable": False,
                "reason": "serialization_error", "error_class": type(exc).__name__}

    if len(body_bytes) > _MAX_PAYLOAD_BYTES:
        return {"schema": SCHEMA, "status": "REJECTED_TOO_LARGE", "retryable": False,
                "size_bytes": len(body_bytes), "limit_bytes": _MAX_PAYLOAD_BYTES}

    # 4. Envio HTTP — timeout por conexão, não global
    headers = {
        "Content-Type": "application/json; charset=utf-8",
        "User-Agent": f"Phoenix-Forge/{_forge_version()} TelemetryRelayClient/1",
        "X-Forge-Schema": str(envelope.get("schema", ""))[:64],
        "X-Forge-Version": _forge_version(),
    }
    if installation_id:
        headers["X-Forge-Installation-Id"] = str(installation_id)[:64]
    if event_id:
        headers["X-Forge-Event-Id"] = str(event_id)[:128]

    req = urllib.request.Request(url, data=body_bytes, headers=headers, method="POST")
    try:
        # timeout aqui é por conexão, não altera socket.getdefaulttimeout()
        with urllib.request.urlopen(req, timeout=_RELAY_TIMEOUT_S) as resp:
            status_code = resp.status
            raw_body = resp.read(8192).decode("utf-8", "replace")
            retry_after = None
            try:
                retry_after = int(resp.headers.get("Retry-After", ""))
            except Exception:
                pass
            result = _classify_http(status_code, raw_body, retry_after)
            result["schema"] = SCHEMA
            return result
    except urllib.error.HTTPError as exc:
        retry_after = None
        try:
            retry_after = int(exc.headers.get("Retry-After", ""))
        except Exception:
            pass
        raw_body = ""
        try:
            raw_body = exc.read(2048).decode("utf-8", "replace")
        except Exception:
            pass
        result = _classify_http(exc.code, raw_body, retry_after)
        result["schema"] = SCHEMA
        return result
    except Exception as exc:
        return _classify_network_error(exc)


# ---------------------------------------------------------------------------
# Retry schedule
# ---------------------------------------------------------------------------

def next_retry_delay(attempt: int) -> float:
    """
    Delay (segundos) para a tentativa *attempt* (base 0).
    Tentativa 0 = imediata (0.0). Jitter ±10%.
    """
    if attempt <= 0:
        return 0.0
    idx = min(attempt - 1, len(_RETRY_DELAYS) - 1)
    return _jitter(_RETRY_DELAYS[idx])


def should_retry(result: dict[str, Any], attempt: int, max_attempts: int = _MAX_ATTEMPTS) -> bool:
    """True se deve retentrar (resultado retentável e abaixo do máximo)."""
    if attempt >= max_attempts:
        return False
    return bool(result.get("retryable"))


def dead_letter_status(queue_file: str, last_result: dict[str, Any]) -> dict[str, Any]:
    """Envelope de dead-letter para item que esgotou tentativas."""
    return {
        "schema": SCHEMA,
        "status": "DEAD_LETTER",
        "retryable": False,
        "queue_file": queue_file,
        "last_result": last_result,
        "hint": "Esgotou tentativas; item em dead-letter. Limpe a fila manualmente se necessário.",
    }
