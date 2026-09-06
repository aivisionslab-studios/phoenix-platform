from __future__ import annotations

import hashlib
import hmac
import json
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

DEFAULT_MANIFEST_PATH = Path("data/rag_integrity.manifest")
DEFAULT_KEY_PATH = Path("data/.rag_user_registry.key")


class RagIntegrityManifest:
    """Checkpoint cross-linked: registry + ledger + machine.\n\n    V2 deliberately does NOT bind the manifest to Free/Pro. A legitimate\n    activation, expiration or renewal must not look like RAG tampering.\n    Commercial authorization is independently verified by Capability V4.\n    """

    def __init__(
        self,
        manifest_path: Path = DEFAULT_MANIFEST_PATH,
        key_path: Path = DEFAULT_KEY_PATH,
    ) -> None:
        self.manifest_path = Path(manifest_path)
        self.key_path = Path(key_path)

    @staticmethod
    def _canonical(data: dict[str, Any]) -> bytes:
        payload = {
            k: v for k, v in data.items()
            if k not in {"hmac", "manifest_hash"}
        }
        return json.dumps(
            payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")
        ).encode("utf-8")

    @staticmethod
    def _digest_json_file(path: Path) -> str:
        if not path.exists():
            return ""
        try:
            obj = json.loads(path.read_text(encoding="utf-8"))
            canonical = json.dumps(
                obj, ensure_ascii=False, sort_keys=True, separators=(",", ":")
            ).encode("utf-8")
            return hashlib.sha256(canonical).hexdigest()
        except Exception:
            return "INVALID"

    def _key(self) -> bytes:
        return self.key_path.read_bytes()

    def build_current(
        self,
        registry_path: Path,
        ledger_path: Path,
        entitlement: dict[str, Any],
    ) -> dict[str, Any]:
        from phoenix_kernel.licensing.entitlements import _machine_fingerprint

        previous_hash = "GENESIS"
        generation = 1

        if self.manifest_path.exists():
            try:
                old = json.loads(self.manifest_path.read_text(encoding="utf-8"))
                previous_hash = str(old.get("manifest_hash") or "INVALID")
                generation = int(old.get("generation") or 0) + 1
            except Exception:
                previous_hash = "INVALID"

        return {
            "version": 2,
            "generation": generation,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "registry_digest": self._digest_json_file(registry_path),
            "ledger_digest": self._digest_json_file(ledger_path),
            "machine_fingerprint": _machine_fingerprint(),
            "authorization_protocol": "capability-v4",
            "previous_manifest_hash": previous_hash,
        }

    def write(
        self,
        registry_path: Path,
        ledger_path: Path,
        entitlement: dict[str, Any],
    ) -> dict[str, Any]:
        if not self.key_path.exists():
            raise RuntimeError("Manifest key ausente.")

        data = self.build_current(registry_path, ledger_path, entitlement)
        stored_hmac = hmac.new(self._key(), self._canonical(data), hashlib.sha256).hexdigest()
        data["hmac"] = stored_hmac
        data["manifest_hash"] = hashlib.sha256(
            self._canonical(data) + stored_hmac.encode("ascii")
        ).hexdigest()

        tmp = self.manifest_path.with_suffix(self.manifest_path.suffix + ".tmp")
        tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
        tmp.replace(self.manifest_path)
        return data

    def verify(
        self,
        registry_path: Path,
        ledger_path: Path,
        entitlement: dict[str, Any],
    ) -> tuple[bool, str, dict[str, Any]]:
        if not self.manifest_path.exists():
            return False, "manifest_missing", {}
        if not self.key_path.exists():
            return False, "manifest_key_missing", {}

        try:
            data = json.loads(self.manifest_path.read_text(encoding="utf-8"))
            stored_hmac = str(data.get("hmac") or "")
            expected_hmac = hmac.new(
                self._key(), self._canonical(data), hashlib.sha256
            ).hexdigest()
            if not hmac.compare_digest(stored_hmac, expected_hmac):
                return False, "manifest_hmac_invalid", data

            expected_hash = hashlib.sha256(
                self._canonical(data) + stored_hmac.encode("ascii")
            ).hexdigest()
            if str(data.get("manifest_hash") or "") != expected_hash:
                return False, "manifest_hash_invalid", data

            if str(data.get("registry_digest") or "") != self._digest_json_file(registry_path):
                return False, "manifest_registry_mismatch", data

            if str(data.get("ledger_digest") or "") != self._digest_json_file(ledger_path):
                return False, "manifest_ledger_mismatch", data

            from phoenix_kernel.licensing.entitlements import _machine_fingerprint
            if str(data.get("machine_fingerprint") or "") != _machine_fingerprint():
                return False, "manifest_machine_mismatch", data

            # V1 manifests contained entitlement_plan/entitlement_valid.
            # Those fields remain HMAC-protected but are no longer compared
            # against the CURRENT plan. This allows a legitimate Free<->Pro
            # transition without invalidating registry/ledger integrity.
            # The next checkpoint writes V2 and drops those obsolete fields.
            return True, "ok", data
        except Exception as e:
            logger.warning("RAG integrity manifest inválido: %s", e)
            return False, "manifest_read_error", {}
