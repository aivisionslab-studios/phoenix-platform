"""
Compatibility facade for Phoenix licensing.

V4 commercial authority is the signed capability protocol:
    licensing/capability_protocol.py
    licensing/capability_client.py
    licensing/commercial_guard.py

This module remains because older RAG/security code imports
get_effective_plan() and _machine_fingerprint().
"""

from __future__ import annotations

import hashlib
import platform
import socket
from dataclasses import dataclass
from typing import Any

from phoenix_kernel.licensing.commercial_guard import authorization_state


@dataclass(frozen=True)
class EntitlementResult:
    valid: bool
    plan: str
    reason: str
    payload: dict[str, Any] | None = None


def _machine_fingerprint() -> str:
    """Legacy fingerprint retained ONLY for existing RAG manifest compatibility.

    Capability machine binding uses capability_protocol.machine_fingerprint().
    Keeping this function stable prevents an already-created v1 manifest from
    being invalidated merely by upgrading Phoenix.
    """
    parts = [
        socket.gethostname().strip().lower(),
        platform.system().strip().lower(),
        platform.machine().strip().lower(),
    ]
    return hashlib.sha256("|".join(parts).encode("utf-8")).hexdigest()


def get_effective_plan() -> EntitlementResult:
    state = authorization_state()
    return EntitlementResult(
        valid=bool(state["valid"]),
        plan=str(state["plan"]),
        reason=str(state["reason"]),
        payload=state,
    )


def verify_entitlement(*args, **kwargs) -> EntitlementResult:
    """Alias legado. V4 não confia em entitlement.json local."""
    return get_effective_plan()
