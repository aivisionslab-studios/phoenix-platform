from __future__ import annotations

import hashlib
from typing import Any

from phoenix_forge.modules import telemetry_governance

SCHEMA = "phoenix.forge.telemetry-sanitizer/v1"

# Extra defense in depth: these keys are stripped recursively even if a producer accidentally adds them.
DENY_EXACT = {
    "serial", "serial_number", "serialnumber", "uuid", "system_uuid", "bios_uuid",
    "username", "user", "hostname", "computer_name", "computername", "mac", "mac_address",
    "path", "filepath", "file_path", "model_path", "vbios_path", "source_path",
    "prompt", "negative_prompt", "messages", "message", "text", "content", "ocr_text",
    "expected_text", "email", "token", "access_token", "password", "secret", "credential",
    "pnp_device_id", "instance_id", "device_instance_id",
}


def _key_denied(key: str) -> bool:
    k = key.strip().lower()
    if k in DENY_EXACT:
        return True
    return any(fragment in k for fragment in telemetry_governance.SENSITIVE_FIELD_FRAGMENTS)


def _hash_identifier(value: str, installation_id: str) -> str:
    raw = f"{installation_id}|{value}".encode("utf-8", "ignore")
    return "sha256:" + hashlib.sha256(raw).hexdigest()[:24]


def sanitize(value: Any, *, installation_id: str, key: str | None = None, depth: int = 0) -> Any:
    if depth > 16:
        return "[DEPTH_LIMIT]"
    if key and _key_denied(key):
        return None
    if isinstance(value, dict):
        out = {}
        for k, v in value.items():
            if _key_denied(str(k)):
                continue
            sv = sanitize(v, installation_id=installation_id, key=str(k), depth=depth + 1)
            if sv is not None:
                out[str(k)] = sv
        return out
    if isinstance(value, list):
        return [x for x in (sanitize(v, installation_id=installation_id, depth=depth + 1) for v in value) if x is not None]
    if isinstance(value, tuple):
        return [x for x in (sanitize(v, installation_id=installation_id, depth=depth + 1) for v in value) if x is not None]
    if isinstance(value, (str, int, float, bool)) or value is None:
        # device_key can be useful operationally but should not leave the host as the raw persistent identifier.
        if key == "device_key" and isinstance(value, str):
            return _hash_identifier(value, installation_id)
        if isinstance(value, str) and len(value) > 4096:
            return value[:4096] + "[TRUNCATED]"
        return value
    return str(value)[:512]


def assert_no_sensitive_keys(payload: Any) -> list[str]:
    bad: list[str] = []
    def walk(node: Any, prefix: str = "") -> None:
        if isinstance(node, dict):
            for k, v in node.items():
                path = f"{prefix}.{k}" if prefix else str(k)
                if _key_denied(str(k)):
                    bad.append(path)
                walk(v, path)
        elif isinstance(node, list):
            for i, v in enumerate(node):
                walk(v, f"{prefix}[{i}]")
    walk(payload)
    return bad
