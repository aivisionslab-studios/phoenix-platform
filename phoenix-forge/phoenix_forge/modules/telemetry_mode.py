"""
Phoenix Forge — Telemetry Transport Mode  (0.24.0)
=====================================================
Formaliza os três modos de transporte de telemetria.

  OFF                        — telemetria desativada; nenhum envio ocorre
  DEVELOPMENT_DIRECT_FIRESTORE — Firestore direto via service account local
                                 (apenas ambiente de desenvolvimento/admin)
  PRODUCTION_CLOUD_RELAY     — envia ao Phoenix Cloud Relay via HTTPS;
                                 nunca usa service account no cliente

Ordem de resolução (maior precedência primeiro):
  1. Variável PHOENIX_FORGE_TELEMETRY_MODE (OFF / DEV / PROD)
  2. PHOENIX_FORGE_TELEMETRY_RELAY_URL presente → PRODUCTION_CLOUD_RELAY
  3. PHOENIX_FORGE_TELEMETRY_GATEWAY presente   → PRODUCTION_CLOUD_RELAY
  4. Service account local encontrada e válida  → DEVELOPMENT_DIRECT_FIRESTORE
  5. Fallback                                   → OFF

Invariant de segurança:
  - PRODUCTION_CLOUD_RELAY NUNCA carrega service account local.
  - DEVELOPMENT_DIRECT_FIRESTORE é bloqueado se MODE=PROD estiver definido.
"""
from __future__ import annotations

import os
from typing import Literal

SCHEMA = "phoenix.forge.telemetry-mode/v1"

TransportMode = Literal[
    "OFF",
    "DEVELOPMENT_DIRECT_FIRESTORE",
    "PRODUCTION_CLOUD_RELAY",
]

_ENV_MODE      = "PHOENIX_FORGE_TELEMETRY_MODE"
_ENV_RELAY_URL = "PHOENIX_FORGE_TELEMETRY_RELAY_URL"
_ENV_GATEWAY   = "PHOENIX_FORGE_TELEMETRY_GATEWAY"  # alias legado


def _env(key: str) -> str:
    return os.environ.get(key, "").strip()


def relay_url() -> str | None:
    """URL do relay configurada via env (nova ou legada)."""
    return _env(_ENV_RELAY_URL) or _env(_ENV_GATEWAY) or None


def resolve() -> TransportMode:
    """
    Resolve o modo de transporte ativo.
    Chamada é barata (só lê env vars); pode ser invocada a cada send_now().
    """
    explicit = _env(_ENV_MODE).upper()
    if explicit in {"OFF", "0", "FALSE", "DISABLED"}:
        return "OFF"
    if explicit in {"PROD", "PRODUCTION", "PRODUCTION_CLOUD_RELAY", "RELAY"}:
        return "PRODUCTION_CLOUD_RELAY"
    if explicit in {"DEV", "DEVELOPMENT", "DEVELOPMENT_DIRECT_FIRESTORE", "DIRECT"}:
        return "DEVELOPMENT_DIRECT_FIRESTORE"

    # Sem override explícito: relay URL presente → PROD
    if relay_url():
        return "PRODUCTION_CLOUD_RELAY"

    # Destino Firestore local explicitamente configurado → DEV.
    # Isso preserva ADC/configuração de desenvolvimento sem exigir service account local.
    try:
        from phoenix_forge.modules.firestore_telemetry import configuration
        cfg = configuration(False)
        if cfg.get("configured") and cfg.get("enabled", True):
            return "DEVELOPMENT_DIRECT_FIRESTORE"
    except Exception:
        pass

    # Service account local disponível → DEV
    try:
        from phoenix_forge.modules.firestore_telemetry import _discover_phoenix_service_account
        path, _ = _discover_phoenix_service_account()
        if path is not None:
            return "DEVELOPMENT_DIRECT_FIRESTORE"
    except Exception:
        pass

    return "OFF"


def describe(mode: TransportMode | None = None) -> dict:
    """Retorna descrição pública do modo sem expor credenciais."""
    m = mode if mode is not None else resolve()
    url = relay_url()
    return {
        "schema": SCHEMA,
        "mode": m,
        "relay_url_configured": bool(url) and m == "PRODUCTION_CLOUD_RELAY",
        "relay_url": url if m == "PRODUCTION_CLOUD_RELAY" else None,
        "service_account_used": m == "DEVELOPMENT_DIRECT_FIRESTORE",
        "send_enabled": m != "OFF",
        "production_safe": m != "DEVELOPMENT_DIRECT_FIRESTORE",
        "description": {
            "OFF": "Telemetria desativada; nenhum dado é enviado.",
            "DEVELOPMENT_DIRECT_FIRESTORE": (
                "Modo de desenvolvimento: grava diretamente no Firestore via "
                "service account local. Não distribuir em instalações públicas."
            ),
            "PRODUCTION_CLOUD_RELAY": (
                "Modo de produção: envia ao Phoenix Cloud Relay via HTTPS. "
                "Nenhuma service account fica no cliente."
            ),
        }.get(m, ""),
    }
