from __future__ import annotations

import json
import os
import subprocess
import threading
import time
import uuid
from pathlib import Path
from typing import Any

from phoenix_forge.modules import provider_bridge, privileged_driver_trust

SCHEMA = "phoenix.forge.provider-action-runtime/v1"
REQUEST_SCHEMA = "phoenix.forge.provider-request/v1"
RESPONSE_SCHEMA = "phoenix.forge.provider-response/v1"

# 0.20.6 intentionally exposes only read-only telemetry/inspection capabilities.
READ_ONLY_CAPABILITIES = {
    "spd.read",
    "spd.enumerate",
    "msr.read",
    "clock.aperf_mperf",
    "clock.bclk_multiplier",
    "electrical.telemetry",
    "sensor.vendor_deep",
}
MAX_REQUEST_BYTES = 64 * 1024
MAX_RESPONSE_BYTES = 1024 * 1024
DEFAULT_TIMEOUT_S = 5.0
FAILURES_TO_OPEN = 3
OPEN_SECONDS = 60.0

_LOCK = threading.Lock()
_BREAKERS: dict[str, dict[str, Any]] = {}


def _audit_path() -> Path:
    root = Path.home() / ".phoenix_forge"
    root.mkdir(parents=True, exist_ok=True)
    return root / "provider_audit.jsonl"


def _audit(event: dict[str, Any]) -> None:
    # Do not write params/results: the audit trail is operational metadata only.
    safe = {
        "at_unix": time.time(),
        "request_id": event.get("request_id"),
        "provider": event.get("provider"),
        "capability": event.get("capability"),
        "status": event.get("status"),
        "elapsed_ms": event.get("elapsed_ms"),
        "error_class": event.get("error_class"),
    }
    try:
        with _audit_path().open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(safe, ensure_ascii=False, separators=(",", ":")) + "\n")
    except Exception:
        pass


def _find_manifest(name: str) -> dict[str, Any]:
    root = provider_bridge._provider_root()  # validated again by _load_manifest
    if not root.exists():
        raise FileNotFoundError("provider root does not exist")
    for path in root.glob("*.provider.json"):
        try:
            manifest = provider_bridge._load_manifest(path)
        except Exception:
            continue
        if manifest.get("name") == name:
            return manifest
    raise FileNotFoundError(f"provider not found: {name}")


def _json_size(value: Any) -> int:
    return len(json.dumps(value, ensure_ascii=False, separators=(",", ":")).encode("utf-8"))


def _validate_request(provider: str, capability: str, params: Any) -> None:
    if not provider or len(provider) > 128:
        raise ValueError("invalid provider name")
    if capability not in READ_ONLY_CAPABILITIES:
        raise PermissionError("capability is not allowed by read-only provider runtime")
    if params is None:
        params = {}
    if not isinstance(params, dict):
        raise ValueError("params must be a JSON object")
    if _json_size(params) > MAX_REQUEST_BYTES:
        raise ValueError("provider request exceeds size limit")


def _breaker_state(name: str) -> dict[str, Any]:
    now = time.monotonic()
    with _LOCK:
        state = _BREAKERS.setdefault(name, {"failures": 0, "opened_until": 0.0})
        if state["opened_until"] and now >= state["opened_until"]:
            state.update({"failures": 0, "opened_until": 0.0})
        return dict(state)


def _record_success(name: str) -> None:
    with _LOCK:
        _BREAKERS[name] = {"failures": 0, "opened_until": 0.0}


def _record_failure(name: str) -> dict[str, Any]:
    now = time.monotonic()
    with _LOCK:
        state = _BREAKERS.setdefault(name, {"failures": 0, "opened_until": 0.0})
        state["failures"] = int(state.get("failures", 0)) + 1
        if state["failures"] >= FAILURES_TO_OPEN:
            state["opened_until"] = now + OPEN_SECONDS
        return dict(state)


def breaker_status() -> dict[str, Any]:
    now = time.monotonic()
    with _LOCK:
        rows = {}
        for name, raw in _BREAKERS.items():
            opened_until = float(raw.get("opened_until") or 0.0)
            rows[name] = {
                "failures": int(raw.get("failures") or 0),
                "state": "OPEN" if opened_until > now else "CLOSED",
                "retry_after_s": round(max(0.0, opened_until - now), 3),
            }
    return {"schema": SCHEMA, "providers": rows}


def call(provider: str, capability: str, params: dict[str, Any] | None = None, timeout_s: float = DEFAULT_TIMEOUT_S) -> dict[str, Any]:
    params = params or {}
    _validate_request(provider, capability, params)
    request_id = str(uuid.uuid4())
    started = time.monotonic()

    breaker = _breaker_state(provider)
    retry_after = max(0.0, float(breaker.get("opened_until") or 0.0) - time.monotonic())
    if retry_after > 0:
        result = {
            "schema": SCHEMA,
            "request_id": request_id,
            "provider": provider,
            "capability": capability,
            "status": "CIRCUIT_OPEN",
            "retry_after_s": round(retry_after, 3),
        }
        _audit(result)
        return result

    try:
        if provider == "phoenix-msr-windows" and capability in {"clock.aperf_mperf", "clock.bclk_multiplier", "msr.read"}:
            trust = privileged_driver_trust.probe()
            if not trust.get("trusted_runtime_ready"):
                raise PermissionError(f"privileged driver trust gate not ready: {trust.get('status')}/{trust.get('reason')}")

        manifest = _find_manifest(provider)
        declared = set(map(str, manifest.get("capabilities") or []))
        if capability not in declared:
            raise PermissionError("capability not declared by provider manifest")

        handshake = provider_bridge.probe(provider, timeout_s=min(2.0, float(timeout_s)))
        if handshake.get("status") != "READY":
            raise RuntimeError(f"provider handshake is not READY: {handshake.get('status')}")
        if capability not in set(map(str, handshake.get("capabilities") or [])):
            raise PermissionError("capability not reported by provider handshake")

        request = {
            "schema": REQUEST_SCHEMA,
            "request_id": request_id,
            "capability": capability,
            "params": params,
        }
        request_text = json.dumps(request, ensure_ascii=False, separators=(",", ":"))
        timeout = max(0.2, min(float(timeout_s), 30.0))
        cp = subprocess.run(
            [manifest["executable_path"], "--phoenix-provider-call", capability],
            input=request_text,
            capture_output=True,
            text=True,
            timeout=timeout,
            shell=False,
            creationflags=(0x08000000 if os.name == "nt" else 0),
        )
        stdout_bytes = cp.stdout.encode("utf-8", errors="replace")
        if len(stdout_bytes) > MAX_RESPONSE_BYTES:
            raise ValueError("provider response exceeds size limit")
        if cp.returncode != 0:
            raise RuntimeError(f"provider exit code {cp.returncode}")
        response = json.loads(cp.stdout)
        if not isinstance(response, dict) or response.get("schema") != RESPONSE_SCHEMA:
            raise ValueError("invalid provider response schema")
        if response.get("request_id") != request_id:
            raise ValueError("provider response request_id mismatch")
        if response.get("capability") != capability:
            raise ValueError("provider response capability mismatch")
        if response.get("status") not in {"OK", "UNAVAILABLE", "PARTIAL", "ERROR"}:
            raise ValueError("invalid provider response status")

        _record_success(provider)
        elapsed = round((time.monotonic() - started) * 1000, 1)
        result = {
            "schema": SCHEMA,
            "request_id": request_id,
            "provider": provider,
            "capability": capability,
            "status": response.get("status"),
            "data": response.get("data"),
            "evidence": response.get("evidence") or [],
            "provider_version": handshake.get("provider_version"),
            "privilege": handshake.get("privilege", "UNKNOWN"),
            "elapsed_ms": elapsed,
            "policy": {"shell": False, "read_only": True, "response_limit_bytes": MAX_RESPONSE_BYTES},
        }
        _audit(result)
        return result
    except subprocess.TimeoutExpired:
        state = _record_failure(provider)
        result = {
            "schema": SCHEMA,
            "request_id": request_id,
            "provider": provider,
            "capability": capability,
            "status": "TIMEOUT",
            "error_class": "TimeoutExpired",
            "circuit_failures": state.get("failures"),
            "elapsed_ms": round((time.monotonic() - started) * 1000, 1),
        }
        _audit(result)
        return result
    except Exception as exc:
        state = _record_failure(provider)
        result = {
            "schema": SCHEMA,
            "request_id": request_id,
            "provider": provider,
            "capability": capability,
            "status": "REJECTED" if isinstance(exc, (PermissionError, ValueError)) else "FAILED",
            "error": str(exc),
            "error_class": type(exc).__name__,
            "circuit_failures": state.get("failures"),
            "elapsed_ms": round((time.monotonic() - started) * 1000, 1),
        }
        _audit(result)
        return result
