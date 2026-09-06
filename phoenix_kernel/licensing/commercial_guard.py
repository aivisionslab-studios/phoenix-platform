from __future__ import annotations

import threading
import time
from dataclasses import dataclass
from typing import Any

from .capability_client import current_capability
from .capability_protocol import CapabilityVerdict


@dataclass(frozen=True)
class RagLimits:
    max_documents: int | None
    max_upload_bytes: int
    max_extracted_chars: int


FREE_RAG_LIMITS = RagLimits(
    max_documents=10,
    max_upload_bytes=25 * 1024 * 1024,
    # PHX-FIX (2026-09-06, segunda rodada do mesmo achado - usuário testou
    # em produção com o novo limite de 2.500.000 e encontrou um documento
    # real de 7.054.990 caracteres, ainda rejeitado; pediu um número com
    # bem mais margem): 2.500.000 -> 150.000.000. Decisão explícita do
    # usuário, não um cálculo derivado de nenhum documento específico -
    # essa margem cobre folgadamente qualquer documento de texto realista,
    # incluindo o de 7 milhões de caracteres que motivou o pedido.
    max_extracted_chars=150_000_000,
)

PRO_RAG_LIMITS = RagLimits(
    max_documents=None,
    max_upload_bytes=100 * 1024 * 1024,
    # PHX-FIX (2026-09-06): pedido explícito do usuário - "triplo ou
    # quádruplo" do novo Free (150.000.000). Escolhido o quádruplo
    # (600.000.000) - o topo da faixa que ele mencionou, dando mais fôlego
    # pro plano pago sem exigir nova decisão numérica agora.
    max_extracted_chars=600_000_000,
)

# Evita request remoto em cada chunk, mas permite uma ativação/renovação
# aparecer sem reiniciar a Phoenix.
_CACHE_TTL_SECONDS = 60.0
_cache_lock = threading.Lock()
_cached_verdict: CapabilityVerdict | None = None
_cached_at = 0.0


def invalidate_capability_cache() -> None:
    global _cached_verdict, _cached_at
    with _cache_lock:
        _cached_verdict = None
        _cached_at = 0.0


def capability_verdict(*, force_refresh: bool = False) -> CapabilityVerdict:
    global _cached_verdict, _cached_at
    now = time.monotonic()
    with _cache_lock:
        if (
            not force_refresh
            and _cached_verdict is not None
            and (now - _cached_at) < _CACHE_TTL_SECONDS
        ):
            return _cached_verdict

    verdict = current_capability()

    with _cache_lock:
        _cached_verdict = verdict
        _cached_at = time.monotonic()
    return verdict


def product_plan(*, force_refresh: bool = False) -> str:
    verdict = capability_verdict(force_refresh=force_refresh)
    return "pro" if verdict.valid and verdict.plan == "pro" else "free"


def feature_enabled(feature: str, *, force_refresh: bool = False) -> bool:
    verdict = capability_verdict(force_refresh=force_refresh)
    return bool(
        verdict.valid
        and verdict.plan == "pro"
        and verdict.token
        and verdict.token.allows(feature)
    )


def rag_limits(*, force_refresh: bool = False) -> RagLimits:
    return (
        PRO_RAG_LIMITS
        if feature_enabled("rag.pro", force_refresh=force_refresh)
        else FREE_RAG_LIMITS
    )


def authorization_state(*, force_refresh: bool = False) -> dict[str, Any]:
    """Estado comercial consumido pelo consenso e pela API.

    FREE é um estado de produto válido mesmo sem token.
    PRO só existe com capability criptograficamente válida + feature rag.pro.
    """
    verdict = capability_verdict(force_refresh=force_refresh)
    pro = bool(
        verdict.valid
        and verdict.plan == "pro"
        and verdict.token
        and verdict.token.allows("rag.pro")
    )
    return {
        "valid": True if not pro else verdict.valid,
        "plan": "pro" if pro else "free",
        "capability_valid": bool(verdict.valid),
        "source": verdict.source,
        "reason": verdict.reason,
        "features": list(verdict.token.features) if verdict.token else [],
        "expires_at": verdict.token.expires_at if verdict.token else None,
        "epoch": verdict.token.epoch if verdict.token else None,
        "jti": verdict.token.jti if verdict.token else None,
    }


def security_status(*, force_refresh: bool = False) -> dict[str, Any]:
    return authorization_state(force_refresh=force_refresh)
