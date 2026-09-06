from __future__ import annotations
import base64
import json
import time

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from cryptography.hazmat.primitives import serialization

from phoenix_kernel.licensing.capability_protocol import CapabilityVerifier, canonical_json


def b64u(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")


def make_token(private, machine="M1", nonce="N1", plan="pro", features=None, exp_delta=3600):
    now = int(time.time())
    header = {"alg": "EdDSA", "typ": "PHX-CAP"}
    payload = {
        "v": 1, "iss": "aivisionslab", "aud": "phoenix-engine",
        "license_id": "LIC-1", "machine": machine, "plan": plan,
        "features": features if features is not None else ["rag.pro"],
        "iat": now, "nbf": now - 1, "exp": now + exp_delta,
        "epoch": 1, "nonce": nonce, "jti": "JTI-1",
        "policy_digest": "abc", "metadata": {},
    }
    eh, ep = b64u(canonical_json(header)), b64u(canonical_json(payload))
    signed = f"{eh}.{ep}".encode("ascii")
    return f"{eh}.{ep}.{b64u(private.sign(signed))}"


def test_signature_nonce_machine_and_feature(tmp_path):
    private = Ed25519PrivateKey.generate()
    public = private.public_key()
    pub_path = tmp_path / "pub.pem"
    pub_path.write_bytes(public.public_bytes(
        serialization.Encoding.PEM,
        serialization.PublicFormat.SubjectPublicKeyInfo,
    ))
    verifier = CapabilityVerifier(pub_path)
    token = make_token(private)

    ok = verifier.verify(token, expected_machine="M1", expected_nonce="N1")
    assert ok.valid and ok.plan == "pro" and ok.token.allows("rag.pro")

    assert not verifier.verify(token, expected_machine="M2", expected_nonce="N1").valid
    assert not verifier.verify(token, expected_machine="M1", expected_nonce="N2").valid


def test_tampered_payload_rejected(tmp_path):
    private = Ed25519PrivateKey.generate()
    pub_path = tmp_path / "pub.pem"
    pub_path.write_bytes(private.public_key().public_bytes(
        serialization.Encoding.PEM,
        serialization.PublicFormat.SubjectPublicKeyInfo,
    ))
    token = make_token(private, features=[])
    h, payload, sig = token.split(".")
    obj = json.loads(base64.urlsafe_b64decode(payload + "="*((4-len(payload)%4)%4)))
    obj["features"] = ["rag.pro", "*"]
    tampered = f"{h}.{b64u(canonical_json(obj))}.{sig}"
    assert not CapabilityVerifier(pub_path).verify(
        tampered, expected_machine="M1", expected_nonce="N1"
    ).valid


def test_expired_rejected(tmp_path):
    private = Ed25519PrivateKey.generate()
    pub_path = tmp_path / "pub.pem"
    pub_path.write_bytes(private.public_key().public_bytes(
        serialization.Encoding.PEM,
        serialization.PublicFormat.SubjectPublicKeyInfo,
    ))
    token = make_token(private, exp_delta=-300)
    assert not CapabilityVerifier(pub_path, clock_skew_seconds=0).verify(
        token, expected_machine="M1", expected_nonce="N1"
    ).valid
