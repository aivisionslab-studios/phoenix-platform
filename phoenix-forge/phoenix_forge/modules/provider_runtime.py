from __future__ import annotations

import threading
import time
from typing import Any

from phoenix_forge.modules import provider_bridge

SCHEMA = "phoenix.forge.provider-runtime/v1"
_LOCK = threading.Lock()
_CACHE: dict[str, Any] = {"at": 0.0, "value": None, "refreshing": False}


def _collect() -> dict[str, Any]:
    discovered = provider_bridge.discover()
    rows = []
    for item in discovered.get("providers") or []:
        if item.get("status") != "VERIFIED":
            rows.append(dict(item))
            continue
        name = str(item.get("name") or "")
        probe = provider_bridge.probe(name, timeout_s=2.0)
        rows.append({**item, "probe": probe, "runtime_status": probe.get("status", "UNKNOWN")})
    return {
        "schema": SCHEMA,
        "status": "OK",
        "providers": rows,
        "provider_root": discovered.get("provider_root"),
        "policy": {
            **(discovered.get("policy") or {}),
            "health_probe_timeout_s": 2.0,
            "stale_while_revalidate": True,
            "provider_failure_does_not_block_forge": True,
        },
        "collected_at_unix": time.time(),
    }


def _refresh_worker() -> None:
    try:
        value = _collect()
        with _LOCK:
            _CACHE["value"] = value
            _CACHE["at"] = time.monotonic()
    finally:
        with _LOCK:
            _CACHE["refreshing"] = False


def refresh_async() -> bool:
    with _LOCK:
        if _CACHE["refreshing"]:
            return False
        _CACHE["refreshing"] = True
    threading.Thread(target=_refresh_worker, name="forge-provider-health", daemon=True).start()
    return True


def health(max_age_s: float = 30.0) -> dict[str, Any]:
    now = time.monotonic()
    with _LOCK:
        value = _CACHE["value"]
        age = (now - float(_CACHE["at"])) if value is not None else None
        refreshing = bool(_CACHE["refreshing"])
    if value is None:
        refresh_async()
        return {"schema": SCHEMA, "status": "WARMING", "providers": [], "refreshing": True, "age_s": None}
    stale = age is not None and age > max_age_s
    if stale and not refreshing:
        refresh_async()
        refreshing = True
    return {**value, "status": "STALE" if stale else "OK", "refreshing": refreshing, "age_s": round(age or 0.0, 3)}
