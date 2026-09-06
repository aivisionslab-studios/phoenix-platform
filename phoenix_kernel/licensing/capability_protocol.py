from __future__ import annotations

import base64
import hashlib
import json
import os
import platform
import secrets
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey
from cryptography.hazmat.primitives import serialization


TOKEN_AUDIENCE = "phoenix-engine"
TOKEN_ISSUER = "aivisionslab"
PROTOCOL_VERSION = 1

# O cliente só conhece a chave pública.
DEFAULT_PUBLIC_KEY_PATH = Path(
    os.getenv("PHOENIX_CAPABILITY_PUBLIC_KEY", "config/phoenix_capability_public_key.pem")
)
DEFAULT_CACHE_PATH = Path(
    os.getenv("PHOENIX_CAPABILITY_CACHE", "data/capability_token.json")
)


def _b64u_encode(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")


def _b64u_decode(value: str) -> bytes:
    padding = "=" * ((4 - len(value) % 4) % 4)
    return base64.urlsafe_b64decode((value + padding).encode("ascii"))


def canonical_json(value: Any) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")


def machine_fingerprint() -> str:
    """Retorna um identificador estável usado SOMENTE para machine binding.

    Ordem:
    1. PHOENIX_MACHINE_ID explícito;
    2. machine_id já criado pela própria Phoenix;
    3. Windows MachineGuid;
    4. Linux machine-id;
    5. fallback de plataforma + MAC.

    O valor final é SHA-256; nenhum identificador cru é enviado.
    """
    explicit = os.getenv("PHOENIX_MACHINE_ID", "").strip()
    if explicit:
        raw = f"explicit:{explicit}"
        return hashlib.sha256(raw.encode("utf-8")).hexdigest()

    for candidate in (
        Path("data/config/machine_id.json"),
        Path("data/machine_id.json"),
        Path("data/machine_id.txt"),
    ):
        try:
            if not candidate.exists():
                continue
            if candidate.suffix.lower() == ".json":
                obj = json.loads(candidate.read_text(encoding="utf-8", errors="ignore"))
                for key in ("machine_id", "id", "fingerprint", "uuid"):
                    value = str(obj.get(key) or "").strip()
                    if value:
                        raw = f"phoenix:{value}"
                        return hashlib.sha256(raw.encode("utf-8")).hexdigest()
            else:
                value = candidate.read_text(encoding="utf-8", errors="ignore").strip()
                if value:
                    raw = f"phoenix:{value}"
                    return hashlib.sha256(raw.encode("utf-8")).hexdigest()
        except Exception:
            pass

    if os.name == "nt":
        try:
            import winreg
            with winreg.OpenKey(
                winreg.HKEY_LOCAL_MACHINE,
                r"SOFTWARE\Microsoft\Cryptography",
                0,
                winreg.KEY_READ | getattr(winreg, "KEY_WOW64_64KEY", 0),
            ) as key:
                value, _ = winreg.QueryValueEx(key, "MachineGuid")
                value = str(value or "").strip()
                if value:
                    raw = f"windows:{value}"
                    return hashlib.sha256(raw.encode("utf-8")).hexdigest()
        except Exception:
            pass

    for candidate in (Path("/etc/machine-id"), Path("/var/lib/dbus/machine-id")):
        try:
            value = candidate.read_text(encoding="utf-8", errors="ignore").strip()
            if value:
                raw = f"linux:{value}"
                return hashlib.sha256(raw.encode("utf-8")).hexdigest()
        except Exception:
            pass

    raw = "|".join([
        "fallback",
        platform.system(),
        platform.machine(),
        platform.node(),
        str(uuid.getnode()),
    ])
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


@dataclass(frozen=True)
class CapabilityToken:
    version: int
    issuer: str
    audience: str
    license_id: str
    machine: str
    plan: str
    features: tuple[str, ...]
    issued_at: int
    not_before: int
    expires_at: int
    epoch: int
    nonce: str
    jti: str
    policy_digest: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_payload(cls, payload: dict[str, Any]) -> "CapabilityToken":
        return cls(
            version=int(payload.get("v", 0)),
            issuer=str(payload.get("iss", "")),
            audience=str(payload.get("aud", "")),
            license_id=str(payload.get("license_id", "")),
            machine=str(payload.get("machine", "")),
            plan=str(payload.get("plan", "free")).lower(),
            features=tuple(str(x) for x in payload.get("features", [])),
            issued_at=int(payload.get("iat", 0)),
            not_before=int(payload.get("nbf", 0)),
            expires_at=int(payload.get("exp", 0)),
            epoch=int(payload.get("epoch", 0)),
            nonce=str(payload.get("nonce", "")),
            jti=str(payload.get("jti", "")),
            policy_digest=str(payload.get("policy_digest", "")),
            metadata=dict(payload.get("metadata") or {}),
        )

    def allows(self, feature: str) -> bool:
        return self.plan == "pro" and (
            "*" in self.features or feature in self.features
        )


@dataclass(frozen=True)
class CapabilityVerdict:
    valid: bool
    plan: str
    source: str
    reason: str
    token: CapabilityToken | None = None

    def allows(self, feature: str) -> bool:
        return bool(self.valid and self.token and self.token.allows(feature))


class CapabilityVerifier:
    """
    Verifica tokens assinados pelo servidor.

    Formato:
        base64url(header).base64url(payload).base64url(signature)

    A assinatura cobre exatamente:
        encoded_header + "." + encoded_payload

    O servidor pode mudar nonce/epoch/jti a cada resposta. Observar milhares
    de tokens não permite produzir o próximo sem a chave privada Ed25519.
    """

    def __init__(
        self,
        public_key_path: str | Path = DEFAULT_PUBLIC_KEY_PATH,
        *,
        audience: str = TOKEN_AUDIENCE,
        issuer: str = TOKEN_ISSUER,
        clock_skew_seconds: int = 120,
    ):
        self.public_key_path = Path(public_key_path)
        self.audience = audience
        self.issuer = issuer
        self.clock_skew_seconds = max(0, int(clock_skew_seconds))

    def _load_public_key(self) -> Ed25519PublicKey:
        pem = self.public_key_path.read_bytes()
        key = serialization.load_pem_public_key(pem)
        if not isinstance(key, Ed25519PublicKey):
            raise TypeError("A chave pública configurada não é Ed25519.")
        return key

    def verify(
        self,
        token_text: str,
        *,
        expected_machine: str | None = None,
        expected_nonce: str | None = None,
        now: int | None = None,
    ) -> CapabilityVerdict:
        try:
            parts = token_text.strip().split(".")
            if len(parts) != 3:
                return CapabilityVerdict(False, "free", "token", "formato inválido")

            enc_header, enc_payload, enc_sig = parts
            header = json.loads(_b64u_decode(enc_header))
            payload = json.loads(_b64u_decode(enc_payload))
            signature = _b64u_decode(enc_sig)

            if header.get("alg") != "EdDSA" or header.get("typ") != "PHX-CAP":
                return CapabilityVerdict(False, "free", "token", "header inválido")

            signed = f"{enc_header}.{enc_payload}".encode("ascii")
            self._load_public_key().verify(signature, signed)

            cap = CapabilityToken.from_payload(payload)
            current = int(time.time()) if now is None else int(now)

            if cap.version != PROTOCOL_VERSION:
                return CapabilityVerdict(False, "free", "token", "versão incompatível")
            if cap.issuer != self.issuer:
                return CapabilityVerdict(False, "free", "token", "issuer inválido")
            if cap.audience != self.audience:
                return CapabilityVerdict(False, "free", "token", "audience inválido")
            if not cap.license_id or not cap.jti:
                return CapabilityVerdict(False, "free", "token", "identificadores ausentes")
            if current + self.clock_skew_seconds < cap.not_before:
                return CapabilityVerdict(False, "free", "token", "token ainda não válido")
            if current - self.clock_skew_seconds >= cap.expires_at:
                return CapabilityVerdict(False, "free", "token", "token expirado")

            machine = expected_machine or machine_fingerprint()
            if not secrets.compare_digest(cap.machine, machine):
                return CapabilityVerdict(False, "free", "token", "machine binding divergente")

            if expected_nonce is not None:
                if not expected_nonce or not cap.nonce:
                    return CapabilityVerdict(False, "free", "token", "nonce ausente")
                if not secrets.compare_digest(cap.nonce, expected_nonce):
                    return CapabilityVerdict(False, "free", "token", "challenge divergente")

            if cap.plan != "pro":
                return CapabilityVerdict(True, "free", "token", "token válido sem Pro", cap)

            return CapabilityVerdict(True, "pro", "token", "capability Pro válida", cap)

        except FileNotFoundError:
            return CapabilityVerdict(False, "free", "token", "chave pública ausente")
        except InvalidSignature:
            return CapabilityVerdict(False, "free", "token", "assinatura inválida")
        except Exception as exc:
            return CapabilityVerdict(False, "free", "token", f"token inválido: {exc}")


def create_challenge() -> str:
    # 256 bits aleatórios por desafio.
    return secrets.token_urlsafe(32)


def save_cached_token(token_text: str, path: str | Path = DEFAULT_CACHE_PATH) -> None:
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_suffix(p.suffix + ".tmp")
    tmp.write_text(
        json.dumps({"token": token_text}, separators=(",", ":")),
        encoding="utf-8",
    )
    os.replace(tmp, p)
    try:
        os.chmod(p, 0o600)
    except Exception:
        pass


def load_cached_token(path: str | Path = DEFAULT_CACHE_PATH) -> str | None:
    p = Path(path)
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
        value = str(data.get("token", "")).strip()
        return value or None
    except Exception:
        return None


def verify_cached_capability(
    verifier: CapabilityVerifier,
    *,
    cache_path: str | Path = DEFAULT_CACHE_PATH,
) -> CapabilityVerdict:
    text = load_cached_token(cache_path)
    if not text:
        return CapabilityVerdict(False, "free", "cache", "nenhuma capability em cache")

    verdict = verifier.verify(text, expected_machine=machine_fingerprint())
    if verdict.valid:
        return CapabilityVerdict(
            True,
            verdict.plan,
            "cache",
            verdict.reason,
            verdict.token,
        )
    return CapabilityVerdict(False, "free", "cache", verdict.reason)
