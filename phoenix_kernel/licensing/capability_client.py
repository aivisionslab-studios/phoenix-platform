from __future__ import annotations

import json
import os
import urllib.error
import urllib.request
import urllib.parse
from dataclasses import dataclass
from pathlib import Path

from .capability_protocol import (
    CapabilityVerdict,
    CapabilityVerifier,
    create_challenge,
    machine_fingerprint,
    save_cached_token,
    verify_cached_capability,
)


DEFAULT_SERVER_URL = os.getenv("PHOENIX_LICENSE_SERVER_URL", "").strip()
DEFAULT_LICENSE_ID_PATH = Path("data/license_id.txt")


def _license_id() -> str:
    env = os.getenv("PHOENIX_LICENSE_ID", "").strip()
    if env:
        return env
    try:
        return DEFAULT_LICENSE_ID_PATH.read_text(
            encoding="utf-8", errors="ignore"
        ).strip()
    except Exception:
        return ""


@dataclass
class CapabilityClient:
    verifier: CapabilityVerifier
    server_url: str = DEFAULT_SERVER_URL
    timeout_seconds: float = 8.0

    def _validated_server_url(self) -> str:
        value = (self.server_url or "").strip().rstrip("/")
        if not value:
            return ""
        parsed = urllib.parse.urlparse(value)
        host = (parsed.hostname or "").lower()

        # Produção: HTTPS obrigatório. HTTP só é aceito em loopback para
        # desenvolvimento local do servidor de licenças.
        loopback = host in {"localhost", "127.0.0.1", "::1"}
        if parsed.scheme != "https" and not (parsed.scheme == "http" and loopback):
            raise ValueError(
                "PHOENIX_LICENSE_SERVER_URL deve usar HTTPS "
                "(HTTP só é permitido em localhost)."
            )
        return value

    def refresh(self) -> CapabilityVerdict:
        """
        Online:
          1. gera nonce imprevisível;
          2. envia nonce + machine + license_id;
          3. exige que o token assinado devolva O MESMO nonce;
          4. valida Ed25519 + expiração + machine binding;
          5. só então atualiza cache.

        Se não houver servidor configurado ou ele estiver offline:
          usa APENAS capability previamente assinada e ainda não expirada.
        """
        machine = machine_fingerprint()
        license_id = _license_id()

        try:
            server_url = self._validated_server_url()
        except ValueError as exc:
            return CapabilityVerdict(False, "free", "config", str(exc))

        if not server_url or not license_id:
            return verify_cached_capability(self.verifier)

        nonce = create_challenge()
        body = json.dumps({
            "license_id": license_id,
            "machine": machine,
            "nonce": nonce,
            "client": "phoenix-engine",
        }).encode("utf-8")

        req = urllib.request.Request(
            server_url + "/v1/capability",
            data=body,
            headers={
                "Content-Type": "application/json",
                "Accept": "application/json",
            },
            method="POST",
        )

        try:
            with urllib.request.urlopen(req, timeout=self.timeout_seconds) as r:
                payload = json.loads(r.read().decode("utf-8"))
                token_text = str(payload.get("token", "")).strip()

            verdict = self.verifier.verify(
                token_text,
                expected_machine=machine,
                expected_nonce=nonce,
            )
            if verdict.valid:
                save_cached_token(token_text)
                return CapabilityVerdict(
                    True, verdict.plan, "online", verdict.reason, verdict.token
                )

            return CapabilityVerdict(False, "free", "online", verdict.reason)

        except (urllib.error.URLError, TimeoutError, OSError, ValueError):
            # Falha de rede NÃO libera Pro.
            return verify_cached_capability(self.verifier)


def current_capability(
    public_key_path: str | Path = "config/phoenix_capability_public_key.pem",
) -> CapabilityVerdict:
    verifier = CapabilityVerifier(public_key_path)
    return CapabilityClient(verifier=verifier).refresh()
