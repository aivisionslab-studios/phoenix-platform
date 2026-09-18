"""Phoenix release signing, trust policy, rotation and revocation helpers.

PHASE7L trust model:
- private Ed25519 keys never live in the Phoenix tree;
- installed/external release_trust_store.json is the root of trust;
- keys have validity windows and lifecycle status;
- trust policy versions are monotonic;
- a changed trust store requires release_trust_transition.json signed by an
  already-trusted key from the previous policy;
- the ZIP under verification is never allowed to bootstrap its own trust.
"""
from __future__ import annotations

import base64
import hashlib
import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

MANIFEST_CONTEXT_V1 = b"PHOENIX-RELEASE-MANIFEST-V1\0"
ARCHIVE_CONTEXT_V1 = b"PHOENIX-RELEASE-ARCHIVE-V1\0"
MANIFEST_CONTEXT_V2 = b"PHOENIX-RELEASE-MANIFEST-V2\0"
ARCHIVE_CONTEXT_V2 = b"PHOENIX-RELEASE-ARCHIVE-V2\0"
TRUST_TRANSITION_CONTEXT = b"PHOENIX-TRUST-TRANSITION-V1\0"


def _crypto():
    from cryptography.hazmat.primitives import serialization
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey, Ed25519PublicKey
    return serialization, Ed25519PrivateKey, Ed25519PublicKey


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def canonical_json_bytes(obj: Any) -> bytes:
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")


def _utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _parse_utc(value: str | None, field: str) -> datetime | None:
    if value in (None, ""):
        return None
    if not isinstance(value, str):
        raise ValueError(f"{field} deve ser timestamp UTC ISO-8601")
    text = value.strip()
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(text)
    except Exception as exc:
        raise ValueError(f"{field} invalido: {value}") from exc
    if dt.tzinfo is None:
        raise ValueError(f"{field} deve incluir timezone UTC")
    return dt.astimezone(timezone.utc)


def _timestamp_for_signing(value: str | None = None) -> str:
    text = value or os.environ.get("PHOENIX_RELEASE_SIGNED_AT_UTC") or _utc_now()
    dt = _parse_utc(text, "signed_at_utc")
    assert dt is not None
    return dt.replace(microsecond=0).isoformat().replace("+00:00", "Z")


def load_private_key(path: str | Path, password: bytes | None = None):
    serialization, Ed25519PrivateKey, _ = _crypto()
    data = Path(path).read_bytes()
    key = serialization.load_pem_private_key(data, password=password)
    if not isinstance(key, Ed25519PrivateKey):
        raise ValueError("chave privada deve ser Ed25519")
    return key


def public_key_raw(private_key) -> bytes:
    serialization, _, _ = _crypto()
    return private_key.public_key().public_bytes(serialization.Encoding.Raw, serialization.PublicFormat.Raw)


def key_id_for_public_raw(raw: bytes) -> str:
    return "ed25519-" + hashlib.sha256(raw).hexdigest()[:16]


def _normalize_key(item: dict[str, Any], *, legacy: bool = False) -> dict[str, Any]:
    if item.get("algorithm") != "ed25519":
        raise ValueError("trust store aceita apenas chaves ed25519")
    raw = base64.b64decode(item.get("public_key_base64") or "", validate=True)
    if len(raw) != 32:
        raise ValueError(f"chave publica Ed25519 invalida: {item.get('key_id')}")
    expected = key_id_for_public_raw(raw)
    kid = str(item.get("key_id") or expected)
    if kid != expected:
        raise ValueError(f"key_id nao corresponde a chave publica: {kid}")

    if legacy:
        status = "revoked" if item.get("revoked") is True else "active"
    else:
        status = str(item.get("status") or ("revoked" if item.get("revoked") is True else "active")).lower()
    if status not in {"active", "retiring", "revoked"}:
        raise ValueError(f"status de chave invalido: {kid}:{status}")

    not_before = item.get("not_before")
    not_after = item.get("not_after")
    revoked_at = item.get("revoked_at")
    nb = _parse_utc(not_before, f"{kid}.not_before")
    na = _parse_utc(not_after, f"{kid}.not_after")
    ra = _parse_utc(revoked_at, f"{kid}.revoked_at")
    if nb and na and nb >= na:
        raise ValueError(f"janela de validade invalida para {kid}")
    if status == "revoked" and not revoked_at and not legacy:
        raise ValueError(f"chave revogada exige revoked_at: {kid}")
    revocation_mode = str(item.get("revocation_mode") or ("signed_at_or_after" if legacy else "all_signatures"))
    if revocation_mode not in {"all_signatures", "signed_at_or_after"}:
        raise ValueError(f"revocation_mode invalido: {kid}:{revocation_mode}")

    return {
        "key_id": kid,
        "algorithm": "ed25519",
        "public_key_base64": base64.b64encode(raw).decode("ascii"),
        "status": status,
        "not_before": not_before,
        "not_after": not_after,
        "revoked_at": revoked_at,
        "revocation_reason": item.get("revocation_reason"),
        "revocation_mode": revocation_mode,
    }


def load_trust_policy_bytes(data: bytes) -> dict[str, Any]:
    obj = json.loads(data.decode("utf-8"))
    schema = int(obj.get("schema_version", 0))
    if schema not in {1, 2}:
        raise ValueError("release_trust_store schema_version invalido")
    product = str(obj.get("product") or "PHOENIX 4.5")
    policy_version = int(obj.get("policy_version", 1))
    if policy_version < 1:
        raise ValueError("trust policy_version deve ser >= 1")
    keys = []
    seen = set()
    for raw_item in obj.get("keys", []):
        item = _normalize_key(dict(raw_item), legacy=(schema == 1))
        if item["key_id"] in seen:
            raise ValueError(f"key_id duplicado no trust store: {item['key_id']}")
        seen.add(item["key_id"])
        keys.append(item)
    return {
        "schema_version": 2,
        "product": product,
        "policy_version": policy_version,
        "keys": keys,
    }


def load_trust_store_bytes(data: bytes) -> dict[str, bytes]:
    """Backward-compatible raw-key view for PHASE7K callers/tests."""
    policy = load_trust_policy_bytes(data)
    out: dict[str, bytes] = {}
    now = datetime.now(timezone.utc)
    for item in policy["keys"]:
        ok, _ = key_usable_at(item, now)
        if ok:
            out[item["key_id"]] = base64.b64decode(item["public_key_base64"])
    return out


def key_usable_at(item: dict[str, Any], when: datetime) -> tuple[bool, str | None]:
    status = item.get("status", "active")
    nb = _parse_utc(item.get("not_before"), "not_before")
    na = _parse_utc(item.get("not_after"), "not_after")
    ra = _parse_utc(item.get("revoked_at"), "revoked_at")
    if nb and when < nb:
        return False, "chave ainda nao valida"
    if na and when > na:
        return False, "chave expirada"
    if status == "revoked":
        mode = item.get("revocation_mode", "all_signatures")
        if mode == "all_signatures" or ra is None or when >= ra:
            return False, "chave revogada"
    return True, None


def _find_key(policy: dict[str, Any], key_id: str) -> dict[str, Any] | None:
    return next((k for k in policy.get("keys", []) if k.get("key_id") == key_id), None)


def _verify_with_policy(message: bytes, signature_b64: str, key_id: str, policy: dict[str, Any], signed_at: str | None) -> list[str]:
    item = _find_key(policy, key_id)
    if item is None:
        return [f"chave de assinatura nao confiavel/desconhecida: {key_id}"]
    when = _parse_utc(signed_at, "signed_at_utc") if signed_at else datetime.now(timezone.utc)
    assert when is not None
    usable, reason = key_usable_at(item, when)
    if not usable:
        return [f"chave de assinatura nao utilizavel em {when.isoformat()}: {key_id} ({reason})"]
    try:
        _, _, Pub = _crypto()
        raw = base64.b64decode(item["public_key_base64"], validate=True)
        Pub.from_public_bytes(raw).verify(base64.b64decode(signature_b64 or "", validate=True), message)
    except Exception:
        return ["assinatura Ed25519 invalida"]
    return []


def sign_manifest_bytes(manifest_bytes: bytes, private_key, key_id: str | None = None, signed_at_utc: str | None = None) -> dict[str, Any]:
    raw = public_key_raw(private_key)
    kid = key_id or key_id_for_public_raw(raw)
    signed_at = _timestamp_for_signing(signed_at_utc)
    envelope = {
        "schema_version": 2,
        "algorithm": "ed25519",
        "key_id": kid,
        "signed_file": "release_build_manifest.json",
        "signed_sha256": sha256_bytes(manifest_bytes),
        "signed_at_utc": signed_at,
    }
    sig = private_key.sign(MANIFEST_CONTEXT_V2 + canonical_json_bytes(envelope) + b"\0" + manifest_bytes)
    envelope["signature_base64"] = base64.b64encode(sig).decode("ascii")
    return envelope


def verify_manifest_signature(manifest_bytes: bytes, signature: dict, trusted: dict[str, bytes]) -> list[str]:
    """Backward-compatible verifier used by PHASE7K tests/build-time checks."""
    schema = int(signature.get("schema_version", 0))
    problems = []
    if signature.get("algorithm") != "ed25519":
        return ["release signature schema/algorithm invalido"]
    if signature.get("signed_file") != "release_build_manifest.json":
        problems.append("release signature signed_file invalido")
    if signature.get("signed_sha256") != sha256_bytes(manifest_bytes):
        problems.append("release signature signed_sha256 divergente")
    kid = signature.get("key_id")
    raw = trusted.get(kid)
    if raw is None:
        problems.append(f"chave de assinatura nao confiavel/desconhecida: {kid}")
        return problems
    try:
        _, _, Pub = _crypto()
        if schema == 1:
            message = MANIFEST_CONTEXT_V1 + manifest_bytes
        elif schema == 2:
            envelope = {k: signature[k] for k in ("schema_version", "algorithm", "key_id", "signed_file", "signed_sha256", "signed_at_utc")}
            message = MANIFEST_CONTEXT_V2 + canonical_json_bytes(envelope) + b"\0" + manifest_bytes
        else:
            return ["release signature schema/algorithm invalido"]
        Pub.from_public_bytes(raw).verify(base64.b64decode(signature.get("signature_base64") or "", validate=True), message)
    except Exception:
        problems.append("assinatura Ed25519 do release manifest invalida")
    return problems


def verify_manifest_signature_policy(manifest_bytes: bytes, signature: dict, policy: dict[str, Any]) -> list[str]:
    schema = int(signature.get("schema_version", 0))
    problems = []
    if signature.get("algorithm") != "ed25519":
        return ["release signature schema/algorithm invalido"]
    if signature.get("signed_file") != "release_build_manifest.json":
        problems.append("release signature signed_file invalido")
    if signature.get("signed_sha256") != sha256_bytes(manifest_bytes):
        problems.append("release signature signed_sha256 divergente")
    if problems:
        return problems
    if schema == 1:
        message = MANIFEST_CONTEXT_V1 + manifest_bytes
        signed_at = None
    elif schema == 2:
        try:
            envelope = {k: signature[k] for k in ("schema_version", "algorithm", "key_id", "signed_file", "signed_sha256", "signed_at_utc")}
        except KeyError as exc:
            return [f"release signature campo ausente: {exc}"]
        message = MANIFEST_CONTEXT_V2 + canonical_json_bytes(envelope) + b"\0" + manifest_bytes
        signed_at = signature.get("signed_at_utc")
    else:
        return ["release signature schema/algorithm invalido"]
    errs = _verify_with_policy(message, signature.get("signature_base64") or "", str(signature.get("key_id") or ""), policy, signed_at)
    return [e.replace("assinatura Ed25519 invalida", "assinatura Ed25519 do release manifest invalida") for e in errs]


def sign_archive(path: Path, private_key, key_id: str | None = None, signed_at_utc: str | None = None) -> dict[str, Any]:
    raw = public_key_raw(private_key)
    kid = key_id or key_id_for_public_raw(raw)
    digest = sha256_file(path)
    signed_at = _timestamp_for_signing(signed_at_utc)
    envelope = {
        "schema_version": 2,
        "algorithm": "ed25519",
        "key_id": kid,
        "archive_name": path.name,
        "archive_sha256": digest,
        "archive_size": path.stat().st_size,
        "signed_at_utc": signed_at,
    }
    sig = private_key.sign(ARCHIVE_CONTEXT_V2 + canonical_json_bytes(envelope))
    envelope["signature_base64"] = base64.b64encode(sig).decode("ascii")
    return envelope


def verify_archive_sidecar(path: Path, sidecar: dict, trusted: dict[str, bytes]) -> list[str]:
    problems = []
    digest = sha256_file(path)
    schema = int(sidecar.get("schema_version", 0))
    if sidecar.get("algorithm") != "ed25519" or schema not in {1, 2}:
        return ["archive sidecar schema/algorithm invalido"]
    if sidecar.get("archive_name") != path.name:
        problems.append("archive sidecar filename divergente")
    if sidecar.get("archive_sha256") != digest:
        problems.append("archive SHA-256 divergente da assinatura destacada")
    if int(sidecar.get("archive_size", -1)) != path.stat().st_size:
        problems.append("archive size divergente da assinatura destacada")
    kid = sidecar.get("key_id")
    raw = trusted.get(kid)
    if raw is None:
        problems.append(f"chave de assinatura nao confiavel/desconhecida: {kid}")
        return problems
    try:
        _, _, Pub = _crypto()
        if schema == 1:
            message = ARCHIVE_CONTEXT_V1 + bytes.fromhex(digest)
        else:
            envelope = {k: sidecar[k] for k in ("schema_version", "algorithm", "key_id", "archive_name", "archive_sha256", "archive_size", "signed_at_utc")}
            message = ARCHIVE_CONTEXT_V2 + canonical_json_bytes(envelope)
        Pub.from_public_bytes(raw).verify(base64.b64decode(sidecar.get("signature_base64") or "", validate=True), message)
    except Exception:
        problems.append("assinatura Ed25519 destacada do ZIP invalida")
    return problems


def verify_archive_sidecar_policy(path: Path, sidecar: dict, policy: dict[str, Any]) -> list[str]:
    digest = sha256_file(path)
    schema = int(sidecar.get("schema_version", 0))
    problems = []
    if sidecar.get("algorithm") != "ed25519" or schema not in {1, 2}:
        return ["archive sidecar schema/algorithm invalido"]
    if sidecar.get("archive_name") != path.name:
        problems.append("archive sidecar filename divergente")
    if sidecar.get("archive_sha256") != digest:
        problems.append("archive SHA-256 divergente da assinatura destacada")
    if int(sidecar.get("archive_size", -1)) != path.stat().st_size:
        problems.append("archive size divergente da assinatura destacada")
    if problems:
        return problems
    if schema == 1:
        message = ARCHIVE_CONTEXT_V1 + bytes.fromhex(digest)
        signed_at = None
    else:
        try:
            envelope = {k: sidecar[k] for k in ("schema_version", "algorithm", "key_id", "archive_name", "archive_sha256", "archive_size", "signed_at_utc")}
        except KeyError as exc:
            return [f"archive sidecar campo ausente: {exc}"]
        message = ARCHIVE_CONTEXT_V2 + canonical_json_bytes(envelope)
        signed_at = sidecar.get("signed_at_utc")
    errs = _verify_with_policy(message, sidecar.get("signature_base64") or "", str(sidecar.get("key_id") or ""), policy, signed_at)
    return [e.replace("assinatura Ed25519 invalida", "assinatura Ed25519 destacada do ZIP invalida") for e in errs]


def _transition_body(from_policy: int, to_policy: int, target_sha: str, authorized_at: str, key_id: str) -> dict[str, Any]:
    return {
        "schema_version": 1,
        "product": "PHOENIX 4.5",
        "from_policy_version": int(from_policy),
        "to_policy_version": int(to_policy),
        "target_trust_store_sha256": target_sha,
        "authorized_at_utc": authorized_at,
        "signing_key_id": key_id,
    }


def sign_trust_transition(previous_policy_bytes: bytes, candidate_policy_bytes: bytes, private_key, key_id: str | None = None, authorized_at_utc: str | None = None) -> dict[str, Any]:
    previous = load_trust_policy_bytes(previous_policy_bytes)
    candidate = load_trust_policy_bytes(candidate_policy_bytes)
    if candidate["product"] != previous["product"]:
        raise ValueError("trust transition product divergente")
    if candidate["policy_version"] <= previous["policy_version"]:
        raise ValueError("trust transition exige policy_version crescente")
    raw = public_key_raw(private_key)
    kid = key_id or key_id_for_public_raw(raw)
    when = _timestamp_for_signing(authorized_at_utc)
    body = _transition_body(previous["policy_version"], candidate["policy_version"], sha256_bytes(candidate_policy_bytes), when, kid)
    # Transition authority is checked against the already-installed policy.
    item = _find_key(previous, kid)
    if item is None:
        raise ValueError(f"chave de transicao nao pertence ao trust store anterior: {kid}")
    usable, reason = key_usable_at(item, _parse_utc(when, "authorized_at_utc") or datetime.now(timezone.utc))
    if not usable:
        raise ValueError(f"chave de transicao nao utilizavel: {kid} ({reason})")
    signature = private_key.sign(TRUST_TRANSITION_CONTEXT + canonical_json_bytes(body))
    body["signature_base64"] = base64.b64encode(signature).decode("ascii")
    return body


def _validate_no_unrevocation(previous: dict[str, Any], candidate: dict[str, Any]) -> list[str]:
    problems = []
    cand = {k["key_id"]: k for k in candidate.get("keys", [])}
    for old in previous.get("keys", []):
        if old.get("status") != "revoked":
            continue
        new = cand.get(old["key_id"])
        if new is None:
            problems.append(f"politica nova remove historico de chave revogada: {old['key_id']}")
            continue
        if new.get("public_key_base64") != old.get("public_key_base64") or new.get("status") != "revoked":
            problems.append(f"politica nova tenta desrevogar/redefinir chave: {old['key_id']}")
    return problems


def verify_trust_transition(previous_policy: dict[str, Any], candidate_policy_bytes: bytes, transition: dict[str, Any]) -> list[str]:
    problems = []
    try:
        candidate = load_trust_policy_bytes(candidate_policy_bytes)
    except Exception as exc:
        return [f"candidate trust store invalido: {exc}"]
    if transition.get("schema_version") != 1 or transition.get("product") != previous_policy.get("product"):
        problems.append("trust transition schema/product invalido")
    if int(transition.get("from_policy_version", -1)) != int(previous_policy.get("policy_version", -2)):
        problems.append("trust transition from_policy_version divergente")
    if int(transition.get("to_policy_version", -1)) != int(candidate.get("policy_version", -2)):
        problems.append("trust transition to_policy_version divergente")
    if candidate["policy_version"] <= previous_policy["policy_version"]:
        problems.append("trust policy rollback/non-monotonic update rejeitado")
    if transition.get("target_trust_store_sha256") != sha256_bytes(candidate_policy_bytes):
        problems.append("trust transition target store SHA-256 divergente")
    problems.extend(_validate_no_unrevocation(previous_policy, candidate))
    if problems:
        return problems
    try:
        body = {k: transition[k] for k in ("schema_version", "product", "from_policy_version", "to_policy_version", "target_trust_store_sha256", "authorized_at_utc", "signing_key_id")}
    except KeyError as exc:
        return [f"trust transition campo ausente: {exc}"]
    errs = _verify_with_policy(
        TRUST_TRANSITION_CONTEXT + canonical_json_bytes(body),
        transition.get("signature_base64") or "",
        str(transition.get("signing_key_id") or ""),
        previous_policy,
        transition.get("authorized_at_utc"),
    )
    return [e.replace("assinatura Ed25519 invalida", "assinatura Ed25519 da trust transition invalida") for e in errs]


def resolve_effective_trust(current_policy_bytes: bytes, candidate_policy_bytes: bytes | None, transition_bytes: bytes | None) -> tuple[dict[str, Any], list[str], bool]:
    """Resolve trust for one release without ever trusting the ZIP by itself.

    Returns (effective_policy, problems, policy_changed).
    """
    current = load_trust_policy_bytes(current_policy_bytes)
    if candidate_policy_bytes is None:
        return current, [], False
    candidate = load_trust_policy_bytes(candidate_policy_bytes)
    if candidate["product"] != current["product"]:
        return current, ["candidate trust store product divergente"], False
    current_canon = canonical_json_bytes(current)
    candidate_canon = canonical_json_bytes(candidate)
    if candidate["policy_version"] < current["policy_version"]:
        return current, [f"trust policy rollback rejeitado: {candidate['policy_version']} < {current['policy_version']}"], False
    if candidate["policy_version"] == current["policy_version"]:
        if candidate_canon != current_canon:
            return current, ["trust store mudou sem incrementar policy_version"], False
        return current, [], False
    if transition_bytes is None:
        return current, ["trust store mudou sem release_trust_transition.json autorizada"], False
    try:
        transition = json.loads(transition_bytes.decode("utf-8"))
    except Exception as exc:
        return current, [f"release_trust_transition.json invalido: {exc}"], False
    problems = verify_trust_transition(current, candidate_policy_bytes, transition)
    if problems:
        return current, problems, False
    return candidate, [], True


def generate_private_key_file(path: Path) -> dict[str, Any]:
    serialization, Priv, _ = _crypto()
    root = Path(__file__).resolve().parent
    dest = path.expanduser().resolve()
    try:
        dest.relative_to(root)
        raise ValueError("recusado: chave privada nao pode ser criada dentro da arvore Phoenix")
    except ValueError as exc:
        if str(exc).startswith("recusado:"):
            raise
    dest.parent.mkdir(parents=True, exist_ok=True)
    if dest.exists():
        raise FileExistsError(f"arquivo ja existe: {dest}")
    key = Priv.generate()
    pem = key.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.NoEncryption())
    dest.write_bytes(pem)
    try:
        os.chmod(dest, 0o600)
    except Exception:
        pass
    raw = public_key_raw(key)
    kid = key_id_for_public_raw(raw)
    return {
        "key_id": kid,
        "algorithm": "ed25519",
        "public_key_base64": base64.b64encode(raw).decode("ascii"),
        "status": "active",
        "not_before": None,
        "not_after": None,
        "revoked_at": None,
        "revocation_reason": None,
        "revocation_mode": "all_signatures",
    }


def _write_policy_candidate(source_path: Path, out_path: Path, mutate) -> dict[str, Any]:
    source_bytes = source_path.read_bytes()
    policy = load_trust_policy_bytes(source_bytes)
    candidate = json.loads(json.dumps(policy))
    mutate(candidate)
    candidate["schema_version"] = 2
    candidate["policy_version"] = int(policy["policy_version"]) + 1
    # Re-validate canonical candidate before writing.
    normalized = load_trust_policy_bytes((json.dumps(candidate, sort_keys=True) + "\n").encode("utf-8"))
    out_path.parent.mkdir(parents=True, exist_ok=True)
    if out_path.resolve() == source_path.resolve():
        raise ValueError("recusado: use um novo arquivo para a policy candidata; nao edite trust store in-place")
    out_path.write_text(json.dumps(candidate, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return normalized


def _load_public_entry(path: Path) -> dict[str, Any]:
    obj = json.loads(path.read_text(encoding="utf-8"))
    return _normalize_key(obj, legacy=False)


def _main() -> int:
    import argparse
    ap = argparse.ArgumentParser(description=__doc__)
    sub = ap.add_subparsers(dest="command", required=True)

    kg = sub.add_parser("keygen", help="gera chave Ed25519 fora da arvore Phoenix e imprime entrada publica")
    kg.add_argument("--private-out", required=True)

    pe = sub.add_parser("public-entry", help="imprime entrada publica para uma chave privada existente")
    pe.add_argument("--private-key", required=True)

    vs = sub.add_parser("validate-store", help="valida estrutura, IDs, janelas e lifecycle do trust store")
    vs.add_argument("--trust-store", required=True)

    ak = sub.add_parser("add-key", help="gera nova policy adicionando uma entrada publica")
    ak.add_argument("--trust-store", required=True)
    ak.add_argument("--public-entry", required=True)
    ak.add_argument("--out", required=True)
    ak.add_argument("--status", choices=["active", "retiring"], default="active")
    ak.add_argument("--not-before")
    ak.add_argument("--not-after")

    rk = sub.add_parser("retire-key", help="gera nova policy marcando chave para retirada planejada")
    rk.add_argument("--trust-store", required=True)
    rk.add_argument("--key-id", required=True)
    rk.add_argument("--not-after", required=True)
    rk.add_argument("--out", required=True)

    rv = sub.add_parser("revoke-key", help="gera nova policy revogando uma chave")
    rv.add_argument("--trust-store", required=True)
    rv.add_argument("--key-id", required=True)
    rv.add_argument("--revoked-at", default=None)
    rv.add_argument("--reason", required=True)
    rv.add_argument("--mode", choices=["all_signatures", "signed_at_or_after"], default="all_signatures")
    rv.add_argument("--out", required=True)

    mt = sub.add_parser("make-transition", help="assina transicao de uma policy confiada para uma candidata")
    mt.add_argument("--previous-trust-store", required=True)
    mt.add_argument("--candidate-trust-store", required=True)
    mt.add_argument("--private-key", required=True)
    mt.add_argument("--key-id")
    mt.add_argument("--authorized-at")
    mt.add_argument("--out", required=True)

    ns = ap.parse_args()
    password = (os.environ.get("PHOENIX_RELEASE_SIGNING_KEY_PASSWORD") or "").encode() or None

    if ns.command == "keygen":
        result = generate_private_key_file(Path(ns.private_out))
    elif ns.command == "public-entry":
        key = load_private_key(ns.private_key, password=password)
        raw = public_key_raw(key)
        result = {
            "key_id": key_id_for_public_raw(raw), "algorithm": "ed25519", "public_key_base64": base64.b64encode(raw).decode("ascii"),
            "status": "active", "not_before": None, "not_after": None, "revoked_at": None, "revocation_reason": None, "revocation_mode": "all_signatures",
        }
    elif ns.command == "validate-store":
        policy = load_trust_policy_bytes(Path(ns.trust_store).read_bytes())
        result = {"status": "valid", "product": policy["product"], "policy_version": policy["policy_version"], "keys": len(policy["keys"])}
    elif ns.command == "add-key":
        entry = _load_public_entry(Path(ns.public_entry))
        entry["status"] = ns.status
        if ns.not_before is not None: entry["not_before"] = ns.not_before
        if ns.not_after is not None: entry["not_after"] = ns.not_after
        def mutate(policy):
            if any(k["key_id"] == entry["key_id"] for k in policy["keys"]):
                raise ValueError(f"key_id ja existe: {entry['key_id']}")
            policy["keys"].append(entry)
        result = _write_policy_candidate(Path(ns.trust_store), Path(ns.out), mutate)
    elif ns.command == "retire-key":
        def mutate(policy):
            item = next((k for k in policy["keys"] if k["key_id"] == ns.key_id), None)
            if item is None: raise ValueError(f"key_id inexistente: {ns.key_id}")
            if item.get("status") == "revoked": raise ValueError("chave revogada nao pode voltar para retiring")
            item["status"] = "retiring"; item["not_after"] = ns.not_after
        result = _write_policy_candidate(Path(ns.trust_store), Path(ns.out), mutate)
    elif ns.command == "revoke-key":
        revoked_at = ns.revoked_at or _utc_now()
        def mutate(policy):
            item = next((k for k in policy["keys"] if k["key_id"] == ns.key_id), None)
            if item is None: raise ValueError(f"key_id inexistente: {ns.key_id}")
            item["status"] = "revoked"; item["revoked_at"] = revoked_at; item["revocation_reason"] = ns.reason; item["revocation_mode"] = ns.mode
        result = _write_policy_candidate(Path(ns.trust_store), Path(ns.out), mutate)
    else:
        key = load_private_key(ns.private_key, password=password)
        result = sign_trust_transition(
            Path(ns.previous_trust_store).read_bytes(), Path(ns.candidate_trust_store).read_bytes(), key, ns.key_id, ns.authorized_at
        )
        Path(ns.out).write_text(json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8")

    print(json.dumps(result, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(_main())
