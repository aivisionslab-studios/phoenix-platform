from __future__ import annotations

import hashlib, json, os, subprocess, time
from pathlib import Path
from typing import Any

SCHEMA = "phoenix.forge.provider-bridge/v1"
ALLOWED_KINDS = {"smbus", "msr", "electrical", "sensor_vendor"}
ALLOWED_CAPABILITIES = {
    "spd.read", "spd.enumerate", "msr.read", "clock.aperf_mperf",
    "clock.bclk_multiplier", "electrical.telemetry", "sensor.vendor_deep",
}


def _provider_root() -> Path:
    configured = os.environ.get("PHOENIX_FORGE_PROVIDER_DIR", "").strip()
    if configured:
        return Path(configured).expanduser().resolve()
    return (Path.home() / ".phoenix_forge" / "providers").resolve()


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest().lower()


def _inside(child: Path, parent: Path) -> bool:
    try:
        child.resolve().relative_to(parent.resolve())
        return True
    except Exception:
        return False


def _load_manifest(path: Path) -> dict[str, Any]:
    raw = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(raw, dict):
        raise ValueError("provider manifest must be an object")
    name = str(raw.get("name") or "").strip()
    kind = str(raw.get("kind") or "").strip().lower()
    executable = str(raw.get("executable") or "").strip()
    expected_hash = str(raw.get("sha256") or "").strip().lower()
    capabilities = [str(x) for x in raw.get("capabilities") or []]
    if not name or kind not in ALLOWED_KINDS or not executable:
        raise ValueError("manifest missing valid name/kind/executable")
    if not expected_hash or len(expected_hash) != 64:
        raise ValueError("manifest sha256 is mandatory")
    if any(c not in ALLOWED_CAPABILITIES for c in capabilities):
        raise ValueError("manifest requests unsupported capability")
    exe = (path.parent / executable).resolve() if not Path(executable).is_absolute() else Path(executable).resolve()
    root = _provider_root()
    if not _inside(path, root) or not _inside(exe, root):
        raise PermissionError("provider and executable must stay inside PHOENIX_FORGE_PROVIDER_DIR")
    if not exe.is_file():
        raise FileNotFoundError(str(exe))
    actual = _sha256(exe)
    if actual != expected_hash:
        raise PermissionError("provider executable sha256 mismatch")
    return {**raw, "name": name, "kind": kind, "capabilities": capabilities, "manifest_path": str(path), "executable_path": str(exe), "verified_sha256": actual}


def discover() -> dict[str, Any]:
    root = _provider_root(); entries=[]
    if root.exists():
        for path in sorted(root.glob("*.provider.json")):
            try:
                m=_load_manifest(path)
                entries.append({"name":m["name"],"kind":m["kind"],"capabilities":m["capabilities"],"status":"VERIFIED","manifest":str(path),"sha256":m["verified_sha256"]})
            except Exception as exc:
                entries.append({"name":path.stem,"status":"REJECTED","manifest":str(path),"error":str(exc)})
    return {"schema":SCHEMA,"provider_root":str(root),"providers":entries,"policy":{"shell":False,"hash_required":True,"root_confinement":True,"capability_allowlist":True}}


def probe(name: str, timeout_s: float = 3.0) -> dict[str, Any]:
    root=_provider_root(); candidates=list(root.glob("*.provider.json")) if root.exists() else []
    target=None
    for p in candidates:
        try:
            m=_load_manifest(p)
            if m["name"] == name: target=m; break
        except Exception:
            continue
    if target is None:
        return {"schema":SCHEMA,"name":name,"status":"NOT_FOUND"}
    started=time.monotonic()
    try:
        cp=subprocess.run([target["executable_path"],"--phoenix-provider-handshake"],capture_output=True,text=True,timeout=max(0.2,min(float(timeout_s),10.0)),shell=False,creationflags=(0x08000000 if os.name=="nt" else 0))
        if cp.returncode != 0:
            return {"schema":SCHEMA,"name":name,"status":"HANDSHAKE_FAILED","exit_code":cp.returncode,"stderr":cp.stderr[-1000:],"elapsed_ms":round((time.monotonic()-started)*1000,1)}
        data=json.loads(cp.stdout)
        if not isinstance(data,dict) or data.get("schema") != "phoenix.forge.provider-handshake/v1":
            raise ValueError("invalid handshake schema")
        reported=set(map(str,data.get("capabilities") or [])); allowed=set(target["capabilities"])
        if not reported.issubset(allowed):
            raise PermissionError("provider reported undeclared capability")
        metadata={k:data.get(k) for k in ("driver_status","abi_version","device_path","driver_version") if k in data}
        return {"schema":SCHEMA,"name":name,"status":"READY","kind":target["kind"],"capabilities":sorted(reported),"provider_version":data.get("version"),"privilege":data.get("privilege","UNKNOWN"),"metadata":metadata,"elapsed_ms":round((time.monotonic()-started)*1000,1)}
    except subprocess.TimeoutExpired:
        return {"schema":SCHEMA,"name":name,"status":"TIMEOUT","elapsed_ms":round((time.monotonic()-started)*1000,1)}
    except Exception as exc:
        return {"schema":SCHEMA,"name":name,"status":"REJECTED","error":str(exc),"elapsed_ms":round((time.monotonic()-started)*1000,1)}
