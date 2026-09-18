"""PHASE7O - Fast installed-build integrity certification for Phoenix startup."""
from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import os
import sys
import tempfile
from pathlib import Path, PurePosixPath

ROOT = Path(__file__).resolve().parent


def _now() -> dt.datetime:
    return dt.datetime.now(dt.timezone.utc)


def _now_text() -> str:
    return _now().replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def _load_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8-sig"))


def _normalize_rel(value: str) -> str:
    rel = PurePosixPath(str(value).replace("\\", "/").lstrip("/"))
    if ".." in rel.parts or rel.is_absolute():
        raise RuntimeError(f"startup integrity path invalido: {value}")
    return rel.as_posix()


def load_policy(root: Path) -> dict:
    path = root / "startup_integrity_policy.json"
    if not path.is_file():
        raise RuntimeError("startup_integrity_policy.json ausente")
    data = _load_json(path)
    if data.get("schema_version") != 1:
        raise RuntimeError("startup_integrity_policy.json schema_version nao suportado")
    data.setdefault("cache_ttl_seconds", 86400)
    data.setdefault("local_cache", "data/startup_integrity_cache.json")
    return data


def _expected_entries(build: dict) -> dict[str, dict]:
    section = build.get("startup_integrity") or {}
    if section.get("schema_version") != 1:
        raise RuntimeError("release_build_manifest sem startup_integrity schema v1")
    entries = {}
    for item in section.get("files") or []:
        rel = _normalize_rel(item.get("path") or "")
        if not rel or not item.get("sha256"):
            raise RuntimeError("startup_integrity entry invalida na provenance")
        entries[rel] = item
    if not entries:
        raise RuntimeError("startup_integrity sem arquivos criticos na provenance")
    return entries


def _load_release_state(root: Path) -> dict | None:
    path = root / "data" / "update_release_state.json"
    if not path.is_file():
        return None
    data = _load_json(path)
    if data.get("schema_version") != 1:
        raise RuntimeError("update_release_state.json schema_version nao suportado")
    return data


def _load_cache(path: Path) -> dict:
    if not path.is_file():
        return {"schema_version": 1, "files": {}}
    try:
        data = _load_json(path)
    except Exception:
        return {"schema_version": 1, "files": {}}
    if data.get("schema_version") != 1:
        return {"schema_version": 1, "files": {}}
    data.setdefault("files", {})
    return data


def _write_cache(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + f".tmp-{os.getpid()}")
    tmp.write_text(json.dumps(data, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    os.replace(tmp, path)


def _cache_fresh(item: dict, stat: os.stat_result, expected_sha: str, build_id: str, ttl: int, now: dt.datetime) -> bool:
    if item.get("build_id") != build_id or item.get("sha256") != expected_sha:
        return False
    if int(item.get("size", -1)) != int(stat.st_size) or int(item.get("mtime_ns", -1)) != int(stat.st_mtime_ns):
        return False
    try:
        checked = dt.datetime.fromisoformat(str(item.get("verified_at_utc")).replace("Z", "+00:00"))
    except Exception:
        return False
    return (now - checked).total_seconds() < max(0, ttl)


def verify(root: Path, *, refresh: bool = False) -> dict:
    root = root.resolve()
    policy = load_policy(root)
    build_path = root / "release_build_manifest.json"
    release_state = _load_release_state(root)
    accepted = (release_state or {}).get("current") or {}

    if not build_path.is_file():
        if accepted.get("build_id"):
            raise RuntimeError("Instalacao aceita possui update_release_state, mas release_build_manifest.json esta ausente")
        return {"status": "untracked", "reason": "release_build_manifest_absent", "verified": 0, "cached": 0}

    build = _load_json(build_path)
    build_id = str(build.get("build_id") or "")
    if not build_id:
        raise RuntimeError("release_build_manifest.json sem build_id")
    if accepted.get("build_id") and accepted.get("build_id") != build_id:
        raise RuntimeError(f"build_id instalado diverge do estado aceito: manifest={build_id} state={accepted.get('build_id')}")

    entries = _expected_entries(build)
    provenance_policy = (build.get("startup_integrity") or {}).get("policy_sha256")
    actual_policy_sha = _sha256_file(root / "startup_integrity_policy.json")
    if provenance_policy != actual_policy_sha:
        raise RuntimeError("startup_integrity_policy.json diverge da provenance")

    cache_path = root / _normalize_rel(policy.get("local_cache", "data/startup_integrity_cache.json"))
    cache = _load_cache(cache_path)
    cache_files = cache.setdefault("files", {})
    ttl = int(os.environ.get("PHOENIX_STARTUP_INTEGRITY_CACHE_SECONDS", policy.get("cache_ttl_seconds", 86400)))
    now = _now()
    verified = 0
    cached = 0
    failures = []
    refreshed = {}

    for rel, expected in sorted(entries.items()):
        path = root / rel
        if not path.is_file():
            failures.append(f"ausente:{rel}")
            continue
        stat = path.stat()
        expected_size = int(expected.get("size", -1))
        expected_sha = str(expected.get("sha256") or "")
        mode = str(expected.get("mode") or "always")
        if stat.st_size != expected_size:
            failures.append(f"size:{rel}:expected={expected_size}:actual={stat.st_size}")
            continue
        cached_item = cache_files.get(rel) or {}
        use_cache = mode == "cached" and not refresh and _cache_fresh(cached_item, stat, expected_sha, build_id, ttl, now)
        if use_cache:
            cached += 1
            refreshed[rel] = cached_item
            continue
        digest = _sha256_file(path)
        verified += 1
        if digest != expected_sha:
            failures.append(f"sha256:{rel}:expected={expected_sha}:actual={digest}")
            continue
        refreshed[rel] = {
            "build_id": build_id,
            "sha256": expected_sha,
            "size": stat.st_size,
            "mtime_ns": stat.st_mtime_ns,
            "verified_at_utc": _now_text(),
        }

    if failures:
        raise RuntimeError("Startup integrity FAILED: " + " | ".join(failures[:20]))

    cache_out = {
        "schema_version": 1,
        "policy": "startup-integrity-cache-v1",
        "build_id": build_id,
        "last_verified_at_utc": _now_text(),
        "files": refreshed,
    }
    _write_cache(cache_path, cache_out)
    return {
        "status": "certified",
        "build_id": build_id,
        "profile": build.get("profile"),
        "release": build.get("release"),
        "verified": verified,
        "cached": cached,
        "critical_files": len(entries),
        "cache_ttl_seconds": ttl,
    }


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="Phoenix installed-build startup integrity verifier (PHASE7O)")
    p.add_argument("command", choices=["verify"])
    p.add_argument("--root", type=Path, default=ROOT)
    p.add_argument("--refresh", action="store_true", help="Ignore cached heavy-file hashes and recompute SHA-256")
    p.add_argument("--json", action="store_true")
    args = p.parse_args(argv)
    try:
        result = verify(args.root, refresh=args.refresh)
    except Exception as exc:
        if args.json:
            print(json.dumps({"status": "failed", "error": str(exc)}, ensure_ascii=False))
        else:
            print(f"PHOENIX STARTUP INTEGRITY FAILED: {exc}", file=sys.stderr)
        return 2
    if args.json:
        print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    elif result.get("status") == "untracked":
        print("PHOENIX STARTUP INTEGRITY: UNTRACKED SOURCE/DEV TREE")
    else:
        print(f"PHOENIX STARTUP INTEGRITY OK: {result.get('build_id')} | verified={result.get('verified')} cached={result.get('cached')}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
