from __future__ import annotations

from typing import Any

from phoenix_kernel.licensing.commercial_guard import (
    authorization_state,
    rag_limits as _guard_rag_limits,
)


# PHX-CAPABILITY-V4 HOTFIX 01
# Mantido por compatibilidade com:
#   phoenix_kernel/licensing/__init__.py
#   from .plans import RAG_PLAN_LIMITS, get_rag_limits
#
# Esta constante NÃO decide mais se a instalação é Free ou Pro.
# Ela expõe somente os limites nominais dos planos. A autoridade comercial
# real continua sendo commercial_guard -> capability assinada.
RAG_PLAN_LIMITS: dict[str, dict[str, Any]] = {
    "free": {
        "max_documents": 10,
        "max_upload_bytes": 25 * 1024 * 1024,
        # PHX-FIX (2026-09-06, segunda rodada): mantido em sincronia com
        # FREE_RAG_LIMITS em commercial_guard.py (a fonte de verdade real) -
        # 2.500.000 -> 150.000.000, pedido explícito do usuário depois de
        # testar em produção com um documento real de 7.054.990 caracteres.
        "max_characters": 150_000_000,
    },
    "pro": {
        "max_documents": None,
        "max_upload_bytes": 100 * 1024 * 1024,
        "max_characters": 600_000_000,
    },
}


def get_rag_limits(*, force_refresh: bool = False) -> dict[str, Any]:
    """Single source of truth para limites comerciais do RAG (Capability V4).

    RAG_PLAN_LIMITS permanece disponível para compatibilidade de imports,
    porém o plano efetivo NÃO é lido dessa constante nem de entitlement.json.
    """
    auth = authorization_state(force_refresh=force_refresh)
    limits = _guard_rag_limits(force_refresh=False)

    return {
        "plan": auth["plan"],
        "max_documents": limits.max_documents,
        "max_upload_bytes": limits.max_upload_bytes,
        "max_characters": limits.max_extracted_chars,

        # Campos legados preservados para API/UI existentes.
        "entitlement_valid": auth["capability_valid"],
        "entitlement_reason": auth["reason"],

        # Capability V4.
        "authorization_valid": auth["valid"],
        "capability_valid": auth["capability_valid"],
        "capability_source": auth["source"],
        "capability_expires_at": auth["expires_at"],
        "capability_epoch": auth["epoch"],
        "features": auth["features"],
    }
