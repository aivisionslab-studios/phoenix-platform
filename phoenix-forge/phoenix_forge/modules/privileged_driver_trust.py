from __future__ import annotations
import hashlib, json, os, subprocess
from pathlib import Path
from typing import Any

SCHEMA="phoenix.forge.privileged-driver-trust/v1"
SERVICE_NAME="PhoenixForgePrivileged"

def _provider_root()->Path:
    return Path(__file__).resolve().parents[2]/"providers"/"phoenix_privileged_driver_windows"

def load_policy()->dict[str,Any]:
    p=_provider_root()/"phoenix_driver_trust_policy.json"
    try: raw=json.loads(p.read_text(encoding="utf-8"))
    except Exception: raw={}
    return {
        "schema":raw.get("schema","phoenix.forge.privileged-driver-trust-policy/v1"),
        "mode":raw.get("mode","production_signature_required"),
        "trusted_signer_thumbprints":[str(x).replace(" ","").upper() for x in raw.get("trusted_signer_thumbprints",[])],
        "allow_unsigned":False,
        "allow_hash_only":False,
    }

def assess(*,signature_status:str|None,thumbprint:str|None,binary_sha256:str|None,policy:dict[str,Any]|None=None)->dict[str,Any]:
    pol=policy or load_policy()
    status=str(signature_status or "UNKNOWN")
    thumb=str(thumbprint or "").replace(" ","").upper()
    trusted=status.upper()=="VALID" and bool(thumb) and thumb in set(pol.get("trusted_signer_thumbprints") or [])
    reason="TRUSTED_SIGNER" if trusted else ("SIGNATURE_NOT_VALID" if status.upper()!="VALID" else "SIGNER_NOT_APPROVED")
    return {"schema":SCHEMA,"trusted_runtime_ready":trusted,"status":"TRUSTED" if trusted else "UNTRUSTED","reason":reason,
            "signature_status":status,"signer_thumbprint":thumb or None,"binary_sha256":binary_sha256,"policy_mode":pol.get("mode"),
            "policy":{"hash_only_trust_forbidden":True,"unsigned_trust_forbidden":True,"automatic_install":False}}

def _service_binary()->Path|None:
    if os.name!="nt": return None
    try:
        import winreg
        with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE,rf"SYSTEM\\CurrentControlSet\\Services\\{SERVICE_NAME}") as k:
            image=winreg.QueryValueEx(k,"ImagePath")[0]
    except Exception:
        return None
    text=str(image).strip().strip('"')
    if text.lower().startswith(r"\\systemroot"):
        root=os.environ.get("SystemRoot",r"C:\\Windows")
        text=root+text[len(r"\\SystemRoot"):]
    p=Path(os.path.expandvars(text))
    return p if p.exists() else None

def probe()->dict[str,Any]:
    if os.name!="nt":
        return {"schema":SCHEMA,"status":"UNSUPPORTED_HOST","trusted_runtime_ready":False,"policy":{"automatic_install":False}}
    path=_service_binary()
    if not path:
        return {"schema":SCHEMA,"status":"DRIVER_SERVICE_OR_BINARY_MISSING","trusted_runtime_ready":False,"service":SERVICE_NAME,
                "policy":{"automatic_install":False,"missing_is_not_hardware_failure":True}}
    sha=hashlib.sha256(path.read_bytes()).hexdigest().upper()
    env=os.environ.copy(); env["PFP_DRIVER_PATH"]=str(path)
    ps = "$s=Get-AuthenticodeSignature -LiteralPath $env:PFP_DRIVER_PATH; " + \
         "[pscustomobject]@{Status=[string]$s.Status;Subject=if($s.SignerCertificate){$s.SignerCertificate.Subject}else{$null};" + \
         "Thumbprint=if($s.SignerCertificate){$s.SignerCertificate.Thumbprint}else{$null}}|ConvertTo-Json -Compress"
    try:
        cp=subprocess.run(["powershell","-NoProfile","-NonInteractive","-Command",ps],capture_output=True,text=True,timeout=4,env=env)
        sig=json.loads(cp.stdout) if cp.returncode==0 and cp.stdout.strip() else {}
    except Exception as exc:
        return {"schema":SCHEMA,"status":"SIGNATURE_PROBE_FAILED","trusted_runtime_ready":False,
                "binary_path":str(path),"binary_sha256":sha,"error":f"{type(exc).__name__}: {exc}"}
    result=assess(signature_status=sig.get("Status"),thumbprint=sig.get("Thumbprint"),binary_sha256=sha)
    result.update({"binary_path":str(path),"signer_subject":sig.get("Subject"),"service":SERVICE_NAME})
    return result
