from __future__ import annotations

import copy
import threading
import time
from typing import Any, Callable

SCHEMA = "phoenix.forge.snapshot-cache/v1"

_lock = threading.RLock()
_entries: dict[str, dict[str, Any]] = {}


def _entry(name: str) -> dict[str, Any]:
    with _lock:
        return _entries.setdefault(name, {
            "value": None,
            "updated_at": 0.0,
            "refresh_started_at": 0.0,
            "refreshing": False,
            "last_error": None,
            "last_error_at": None,
            "generation": 0,
        })


def _worker(name: str, builder: Callable[[], Any]) -> None:
    e = _entry(name)
    try:
        value = builder()
        now = time.time()
        with _lock:
            e["value"] = value
            e["updated_at"] = now
            e["last_error"] = None
            e["last_error_at"] = None
            e["generation"] = int(e.get("generation") or 0) + 1
    except Exception as exc:
        with _lock:
            e["last_error"] = f"{type(exc).__name__}: {exc}"
            e["last_error_at"] = time.time()
    finally:
        with _lock:
            e["refreshing"] = False


def refresh_async(name: str, builder: Callable[[], Any]) -> bool:
    e = _entry(name)
    with _lock:
        if e["refreshing"]:
            return False
        e["refreshing"] = True
        e["refresh_started_at"] = time.time()
    t = threading.Thread(target=_worker, args=(name, builder), daemon=True, name=f"forge-snapshot-{name}")
    t.start()
    return True


def get(name: str, builder: Callable[[], Any], *, max_age_s: float, wait_first_s: float = 0.0) -> dict[str, Any]:
    e = _entry(name)
    now = time.time()
    with _lock:
        value = e["value"]
        updated_at = float(e.get("updated_at") or 0.0)
        refreshing = bool(e.get("refreshing"))
    age = None if not updated_at else max(0.0, now - updated_at)
    fresh = value is not None and age is not None and age <= max_age_s
    if not fresh and not refreshing:
        refresh_async(name, builder)
    if value is None and wait_first_s > 0:
        deadline = time.monotonic() + wait_first_s
        while time.monotonic() < deadline:
            time.sleep(0.02)
            with _lock:
                if e["value"] is not None:
                    value = e["value"]
                    updated_at = float(e.get("updated_at") or 0.0)
                    age = max(0.0, time.time() - updated_at) if updated_at else None
                    fresh = age is not None and age <= max_age_s
                    break
    with _lock:
        meta = {
            "schema": SCHEMA,
            "name": name,
            "available": e["value"] is not None,
            "fresh": bool(fresh),
            "stale": bool(e["value"] is not None and not fresh),
            "refreshing": bool(e["refreshing"]),
            "updated_at": e["updated_at"] or None,
            "age_s": round(age, 3) if age is not None else None,
            "generation": e["generation"],
            "last_error": e["last_error"],
            "last_error_at": e["last_error_at"],
        }
        current = copy.deepcopy(e["value"])
    return {"value": current, "snapshot": meta}


def status() -> dict[str, Any]:
    with _lock:
        out = {}
        now = time.time()
        for name, e in _entries.items():
            updated = float(e.get("updated_at") or 0.0)
            out[name] = {
                "available": e.get("value") is not None,
                "refreshing": bool(e.get("refreshing")),
                "updated_at": updated or None,
                "age_s": round(max(0.0, now-updated),3) if updated else None,
                "generation": int(e.get("generation") or 0),
                "last_error": e.get("last_error"),
            }
        return {"schema": SCHEMA, "entries": out}
