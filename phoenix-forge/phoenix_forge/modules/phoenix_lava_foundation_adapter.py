from __future__ import annotations

import os
from pathlib import Path
from typing import Any

SCHEMA = "phoenix.forge.phoenix-lava-foundation-adapter/v1"
MODEL_ID = "phoenix-lava-foundation-mistral-small-3.2-24b"
FAMILY = "Mistral-Small-3.2-24B-Instruct-2506-ultra-uncensored-heretic"
RUNTIME = "phoenix-llama-runtime"

VARIANTS: dict[str, dict[str, Any]] = {
    "Q5_K_M": {
        "tier": "BALANCED",
        "filename": "Mistral-Small-3.2-24B-Instruct-2506-ultra-uncensored-heretic.Q5_K_M.gguf",
        "approx_size_gb": 16.8,
        "source_url": "https://huggingface.co/mradermacher/Mistral-Small-3.2-24B-Instruct-2506-ultra-uncensored-heretic-GGUF/resolve/main/Mistral-Small-3.2-24B-Instruct-2506-ultra-uncensored-heretic.Q5_K_M.gguf?download=true",
        "default": True,
    },
    "Q6_K": {
        "tier": "QUALITY",
        "filename": "Mistral-Small-3.2-24B-Instruct-2506-ultra-uncensored-heretic.Q6_K.gguf",
        "approx_size_gb": 19.3,
        "source_url": "https://huggingface.co/mradermacher/Mistral-Small-3.2-24B-Instruct-2506-ultra-uncensored-heretic-GGUF/resolve/main/Mistral-Small-3.2-24B-Instruct-2506-ultra-uncensored-heretic.Q6_K.gguf?download=true",
        "default": False,
    },
}


def capabilities() -> dict[str, Any]:
    return {
        "schema": SCHEMA,
        "status": "RUNTIME_DEPENDENT",
        "product": "Phoenix LaVa Foundation",
        "model_id": MODEL_ID,
        "family": FAMILY,
        "runtime": RUNTIME,
        "training_status": "FOUNDATION_MODEL_NOT_PHOENIX_TRAINED",
        "supported_modes": ["AUTO", "CPU", "GPU", "HYBRID"],
        "variants": {k: dict(v) for k, v in VARIANTS.items()},
        "policy": {
            "foundation_model_is_not_claimed_as_phoenix_trained": True,
            "phoenix_llama_runtime_owns_cpu_gpu_placement": True,
            "forge_authorizes_devices_but_does_not_guess_layer_count": True,
            "auto_hybrid_uses_runtime_fit": True,
            "cpu_fallback_supported": True,
            "gpu_full_offload_is_not_assumed_to_fit": True,
            "model_download_is_not_performed_by_forge": True,
            "no_shell_execution": True,
        },
    }


def variant(name: str = "Q5_K_M") -> dict[str, Any]:
    key = str(name or "Q5_K_M").upper()
    if key not in VARIANTS:
        raise ValueError(f"unsupported Phoenix LaVa foundation quant: {key}")
    return {"model_id": MODEL_ID, "family": FAMILY, "quantization": key, **VARIANTS[key]}


def candidate_roots() -> list[Path]:
    roots: list[Path] = []
    for env_name in ("PHOENIX_MODELS", "PHOENIX_MODEL_DIR"):
        if os.getenv(env_name): roots.append(Path(os.environ[env_name]).expanduser())
    root = os.getenv("PHOENIX_ROOT") or os.getenv("PHOENIX_HOME")
    if root:
        rp=Path(root).expanduser(); roots.extend([rp/"models"/"lava", rp/"models"])
    p=Path(__file__).resolve()
    for parent in p.parents:
        if parent.name.lower()=="phoenix-forge":
            roots.extend([parent.parent/"models"/"lava", parent.parent/"models"]); break
    out=[]; seen=set()
    for r in roots:
        k=str(r).lower()
        if k not in seen: seen.add(k); out.append(r)
    return out


def discover() -> dict[str, Any]:
    found=[]
    for quant, meta in VARIANTS.items():
        for root in candidate_roots():
            p=root/meta["filename"]
            if p.is_file():
                found.append({"quantization":quant,"path":str(p),"size_bytes":p.stat().st_size,"tier":meta["tier"]}); break
    return {
        "schema":"phoenix.forge.phoenix-lava-foundation-discovery/v1",
        "status":"READY" if found else "MODEL_REQUIRED",
        "model_id":MODEL_ID,
        "found":found,
        "found_count":len(found),
        "searched_roots":[str(x) for x in candidate_roots()],
    }


def runtime_policy(*, mode: str = "AUTO", quantization: str = "Q5_K_M", context_tokens: int = 8192,
                   threads: int = 12, device: str = "Vulkan0", parallel: int = 1, port: int = 8082) -> dict[str, Any]:
    requested=str(mode or "AUTO").upper()
    if requested not in {"AUTO","CPU","GPU","HYBRID"}: raise ValueError(f"unsupported mode: {requested}")
    q=variant(quantization); ctx=max(512,int(context_tokens or 8192)); th=max(1,int(threads or 1)); par=max(1,int(parallel or 1))
    common=["-c",str(ctx),"--parallel",str(par),"-t",str(th),"--jinja","--host","127.0.0.1","--port",str(int(port))]
    if requested=="CPU":
        placement=["-ngl","0","--device","none","--fit","off","--no-op-offload"]
        effective="CPU"
    elif requested=="GPU":
        placement=["--device",device,"-ngl","all","--fit","off"]
        effective="GPU_REQUESTED"
    else: # AUTO and HYBRID intentionally let Phoenix Llama Runtime fit layers to current memory
        placement=["--device",device,"-ngl","auto","--fit","on","--fit-target","0","--fit-ctx",str(ctx)]
        effective="AUTO_FIT" if requested=="AUTO" else "HYBRID_AUTO_FIT"
    return {
        "schema":"phoenix.forge.phoenix-lava-runtime-policy/v1",
        "status":"POLICY_READY",
        "model":q,
        "runtime":RUNTIME,
        "requested_mode":requested,
        "effective_runtime_policy":effective,
        "arguments":placement+common,
        "port":int(port),
        "policy":capabilities()["policy"],
    }


def scheduler_context(dispatch: dict[str, Any], *, quantization: str = "Q5_K_M", context_tokens: int = 8192,
                      threads: int = 12, device: str = "Vulkan0", port: int = 8082) -> dict[str, Any]:
    if not isinstance(dispatch,dict) or not dispatch.get("execution_ready"):
        raise ValueError("Forge dispatch absent or not execution_ready")
    mode=str(dispatch.get("effective_mode") or "CPU").upper()
    assignments=list(dispatch.get("assignments") or [])
    if mode=="CPU": runtime_mode="CPU"
    elif mode=="SINGLE": runtime_mode="HYBRID"  # selected GPU is authorized; Phoenix Llama Runtime decides fitted offload
    else:
        raise ValueError(f"Phoenix LaVa foundation direct adapter does not execute scheduler mode {mode}")
    pol=runtime_policy(mode=runtime_mode,quantization=quantization,context_tokens=context_tokens,threads=threads,device=device,port=port)
    pol["execution_id"]=dispatch.get("execution_id")
    pol["authorized_device_keys"]=[str(x.get("device_key")) for x in assignments if x.get("device_key")]
    pol["scheduler_effective_mode"]=mode
    return pol
