from __future__ import annotations

import hashlib
import hmac
import json
import logging
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

DEFAULT_LEDGER_PATH = Path("data/rag_usage_ledger.json")
DEFAULT_KEY_PATH = Path("data/.rag_user_registry.key")


@dataclass(frozen=True)
class LedgerState:
    valid: bool
    reason: str
    generation: int
    events: list[dict[str, Any]]
    active_documents: dict[str, dict[str, Any]]
    tip_hash: str


class RagUsageLedger:
    """Cadeia local de eventos authorize/reindex/revoke + HMAC do arquivo."""

    def __init__(
        self,
        ledger_path: Path = DEFAULT_LEDGER_PATH,
        key_path: Path = DEFAULT_KEY_PATH,
    ) -> None:
        self.ledger_path = Path(ledger_path)
        self.key_path = Path(key_path)

    @staticmethod
    def _canonical_event_payload(event: dict[str, Any]) -> bytes:
        payload = {k: v for k, v in event.items() if k != "event_hash"}
        return json.dumps(
            payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")
        ).encode("utf-8")

    @staticmethod
    def _event_hash(event: dict[str, Any]) -> str:
        return hashlib.sha256(RagUsageLedger._canonical_event_payload(event)).hexdigest()

    @staticmethod
    def _canonical_file(generation: int, events: list[dict[str, Any]]) -> bytes:
        return json.dumps(
            {"version": 1, "generation": generation, "events": events},
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")

    @staticmethod
    def _file_hmac(key: bytes, generation: int, events: list[dict[str, Any]]) -> str:
        return hmac.new(
            key,
            RagUsageLedger._canonical_file(generation, events),
            hashlib.sha256,
        ).hexdigest()

    def _key(self) -> bytes:
        return self.key_path.read_bytes()

    def _derive_active(self, events: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
        active: dict[str, dict[str, Any]] = {}
        for ev in events:
            action = str(ev.get("action") or "")
            pid = str(ev.get("parent_id") or "")
            if not pid:
                continue
            if action in {"authorize", "reindex"}:
                active[pid] = {
                    "title": str(ev.get("title") or ""),
                    "source_type": str(ev.get("source_type") or "DOC"),
                    "generation": int(ev.get("generation") or 0),
                    "event_hash": str(ev.get("event_hash") or ""),
                }
            elif action == "revoke":
                active.pop(pid, None)
        return active

    def load(self) -> LedgerState:
        if not self.ledger_path.exists():
            return LedgerState(False, "ledger_missing", 0, [], {}, "")
        if not self.key_path.exists():
            return LedgerState(False, "ledger_key_missing", 0, [], {}, "")

        try:
            raw = json.loads(self.ledger_path.read_text(encoding="utf-8"))
            generation = int(raw.get("generation") or 0)
            events = raw.get("events")
            stored_hmac = raw.get("hmac")
            if not isinstance(events, list) or not isinstance(stored_hmac, str):
                return LedgerState(False, "ledger_shape_invalid", 0, [], {}, "")

            previous_hash = "GENESIS"
            last_generation = 0

            for ev in events:
                if not isinstance(ev, dict):
                    return LedgerState(False, "ledger_event_invalid", 0, [], {}, "")
                if str(ev.get("previous_hash") or "") != previous_hash:
                    return LedgerState(False, "ledger_chain_broken", 0, [], {}, "")

                expected_hash = self._event_hash(ev)
                if str(ev.get("event_hash") or "") != expected_hash:
                    return LedgerState(False, "ledger_event_hash_invalid", 0, [], {}, "")

                ev_generation = int(ev.get("generation") or 0)
                if ev_generation <= last_generation:
                    return LedgerState(False, "ledger_generation_invalid", 0, [], {}, "")

                last_generation = ev_generation
                previous_hash = expected_hash

            if generation != last_generation:
                return LedgerState(False, "ledger_generation_mismatch", 0, [], {}, "")

            expected_hmac = self._file_hmac(self._key(), generation, events)
            if not hmac.compare_digest(stored_hmac, expected_hmac):
                return LedgerState(False, "ledger_hmac_invalid", 0, [], {}, "")

            return LedgerState(
                True,
                "ok",
                generation,
                events,
                self._derive_active(events),
                previous_hash if events else "GENESIS",
            )
        except Exception as e:
            logger.warning("RAG usage ledger inválido: %s", e)
            return LedgerState(False, "ledger_read_error", 0, [], {}, "")

    def initialize(self, seed_documents: dict[str, dict[str, Any]]) -> None:
        if self.ledger_path.exists():
            raise RuntimeError("RAG usage ledger já existe; não será sobrescrito.")
        if not self.key_path.exists():
            raise RuntimeError("Registry key ausente; ledger não pode ser inicializado.")

        events: list[dict[str, Any]] = []
        previous_hash = "GENESIS"
        generation = 0

        for parent_id, meta in seed_documents.items():
            generation += 1
            ev = {
                "generation": generation,
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "action": "authorize",
                "parent_id": parent_id,
                "title": str(meta.get("title") or ""),
                "source_type": str(meta.get("source_type") or "DOC"),
                "previous_hash": previous_hash,
            }
            ev["event_hash"] = self._event_hash(ev)
            previous_hash = ev["event_hash"]
            events.append(ev)

        self._write(generation, events)

    def _write(self, generation: int, events: list[dict[str, Any]]) -> None:
        payload = {
            "version": 1,
            "generation": generation,
            "events": events,
            "hmac": self._file_hmac(self._key(), generation, events),
        }
        tmp = self.ledger_path.with_suffix(self.ledger_path.suffix + ".tmp")
        tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        tmp.replace(self.ledger_path)

    def append(
        self,
        action: str,
        parent_id: str,
        title: str = "",
        source_type: str = "DOC",
    ) -> dict[str, Any]:
        state = self.load()
        if not state.valid:
            raise RuntimeError(f"RAG ledger inválido ({state.reason}); fail-closed.")
        if action not in {"authorize", "reindex", "revoke"}:
            raise ValueError("Ação de ledger inválida.")

        generation = state.generation + 1
        ev = {
            "generation": generation,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "action": action,
            "parent_id": str(parent_id),
            "title": str(title),
            "source_type": str(source_type or "DOC"),
            "previous_hash": state.tip_hash,
        }
        ev["event_hash"] = self._event_hash(ev)

        events = list(state.events) + [ev]
        self._write(generation, events)
        return ev
