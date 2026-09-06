"""
Integrity registry for user RAG documents.

Purpose:
- Prevent a direct ChromaDB insert from becoming an authorized Phoenix user-RAG
  document automatically.
- Keep an allowlist of logical parent_ids admitted through the Phoenix flow.
- Protect the allowlist against casual/manual editing with HMAC-SHA256.

Threat model:
This is defense-in-depth for a local application. A local administrator who can
patch Python/binaries or extract the local HMAC key can still bypass local
controls. Strong commercial enforcement ultimately requires a remote entitlement
service. This module specifically closes the trivial "write straight into
ChromaDB and get an 11th document" path.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import logging
import os
import secrets
from dataclasses import dataclass
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

DEFAULT_REGISTRY_PATH = Path("data/rag_user_registry.json")
DEFAULT_KEY_PATH = Path("data/.rag_user_registry.key")


@dataclass(frozen=True)
class RegistryState:
    valid: bool
    initialized: bool
    reason: str
    documents: dict[str, dict[str, Any]]


class RagIntegrityRegistry:
    def __init__(
        self,
        registry_path: Path = DEFAULT_REGISTRY_PATH,
        key_path: Path = DEFAULT_KEY_PATH,
    ) -> None:
        self.registry_path = Path(registry_path)
        self.key_path = Path(key_path)

    @staticmethod
    def _canonical(documents: dict[str, dict[str, Any]]) -> bytes:
        payload = {"version": 1, "documents": documents}
        return json.dumps(
            payload,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")

    @staticmethod
    def _mac(key: bytes, documents: dict[str, dict[str, Any]]) -> str:
        return hmac.new(key, RagIntegrityRegistry._canonical(documents), hashlib.sha256).hexdigest()

    def _read_key(self) -> bytes:
        return self.key_path.read_bytes()

    def load(self) -> RegistryState:
        reg_exists = self.registry_path.exists()
        key_exists = self.key_path.exists()

        if not reg_exists and not key_exists:
            return RegistryState(True, False, "uninitialized", {})

        # One side missing means the state was deleted/corrupted/tampered.
        if reg_exists != key_exists:
            return RegistryState(False, True, "registry_key_mismatch", {})

        try:
            key = self._read_key()
            if len(key) < 32:
                return RegistryState(False, True, "registry_key_invalid", {})
            raw = json.loads(self.registry_path.read_text(encoding="utf-8"))
            documents = raw.get("documents")
            stored_mac = raw.get("hmac")
            if not isinstance(documents, dict) or not isinstance(stored_mac, str):
                return RegistryState(False, True, "registry_shape_invalid", {})
            expected = self._mac(key, documents)
            if not hmac.compare_digest(stored_mac, expected):
                return RegistryState(False, True, "registry_hmac_invalid", {})
            return RegistryState(True, True, "ok", documents)
        except Exception as e:
            logger.warning("RAG integrity registry inválido: %s", e)
            return RegistryState(False, True, "registry_read_error", {})

    def initialize(self, documents: dict[str, dict[str, Any]]) -> None:
        state = self.load()
        if state.initialized:
            raise RuntimeError(
                f"RAG integrity registry já inicializado ({state.reason}); "
                "não será recriado automaticamente."
            )

        self.registry_path.parent.mkdir(parents=True, exist_ok=True)
        self.key_path.parent.mkdir(parents=True, exist_ok=True)

        key = secrets.token_bytes(32)
        # Exclusive create: evita sobrescrever uma key criada em corrida.
        with self.key_path.open("xb") as f:
            f.write(key)
        try:
            if os.name != "nt":
                os.chmod(self.key_path, 0o600)
        except OSError:
            pass

        self._write_with_key(key, documents)

    def _write_with_key(self, key: bytes, documents: dict[str, dict[str, Any]]) -> None:
        payload = {
            "version": 1,
            "documents": documents,
            "hmac": self._mac(key, documents),
        }
        tmp = self.registry_path.with_suffix(self.registry_path.suffix + ".tmp")
        tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        tmp.replace(self.registry_path)

    def _mutate(self, fn) -> None:
        state = self.load()
        if not state.valid or not state.initialized:
            raise RuntimeError(
                f"RAG integrity registry indisponível ({state.reason}); fail-closed."
            )
        documents = dict(state.documents)
        fn(documents)
        self._write_with_key(self._read_key(), documents)

    def authorize(self, parent_id: str, metadata: dict[str, Any]) -> None:
        parent_id = str(parent_id or "").strip()
        if not parent_id:
            raise ValueError("parent_id vazio")

        def op(documents):
            documents[parent_id] = {
                "title": str(metadata.get("title") or ""),
                "source_type": str(metadata.get("source_type") or "DOC"),
                "date_added": str(metadata.get("date_added") or ""),
                # PHX-FIX (2026-09-06, correção conceitual do usuário: o
                # limite de caracteres do plano precisa ser um orçamento
                # AGREGADO do repositório, não um teto por documento -
                # exige saber quantos caracteres cada documento autorizado
                # contribui, pra somar todos e comparar contra o teto).
                # Sem este campo, chroma_rag_backend.py podia passar
                # `extracted_characters` no dict de metadata, mas esta
                # função descartava silenciosamente qualquer chave que não
                # fosse title/source_type/date_added - o valor nunca
                # chegava a ser persistido.
                "extracted_characters": int(metadata.get("extracted_characters") or 0),
            }

        self._mutate(op)

    def revoke(self, parent_id: str) -> None:
        def op(documents):
            documents.pop(parent_id, None)
        self._mutate(op)

    def authorized_ids(self) -> set[str]:
        state = self.load()
        if not state.valid or not state.initialized:
            return set()
        return set(state.documents.keys())

    def status(self) -> dict[str, Any]:
        state = self.load()
        return {
            "valid": state.valid,
            "initialized": state.initialized,
            "reason": state.reason,
            "authorized_documents": len(state.documents) if state.valid else 0,
        }
