from __future__ import annotations

from typing import Any
import httpx


def _post(base_url:str,route:str,payload:dict[str,Any],timeout_s:float)->dict[str,Any]:
    response=httpx.post(base_url.rstrip("/")+route,json=payload,timeout=timeout_s)
    response.raise_for_status()
    data=response.json()
    if not isinstance(data,dict):raise ValueError("quality provider returned a non-object response")
    return data


def enrich_image(output:dict[str,Any],*,ocr_url:str|None=None,vision_url:str|None=None,
                 timeout_s:float=60)->dict[str,Any]:
    """Attach OCR/vision evidence supplied by TrOCR, MiniCPM-V or compatible Phoenix adapters."""
    enriched=dict(output);errors=[]
    if ocr_url:
        try:
            data=_post(ocr_url,"/v1/ocr",{"path":output["path"],"expected_text":output.get("expected_text")},timeout_s)
            enriched["ocr_text"]=data.get("text");enriched["ocr_confidence"]=data.get("confidence")
        except Exception as exc:errors.append({"provider":"ocr","error":str(exc)})
    if vision_url:
        try:
            data=_post(vision_url,"/v1/vision/quality",{"path":output["path"],"prompt":output.get("prompt")},timeout_s)
            enriched["vision_score"]=data.get("score");enriched["vision_verdict"]=data.get("verdict")
            enriched["blur_score"]=data.get("blur_score");enriched["artifact_score"]=data.get("artifact_score")
        except Exception as exc:errors.append({"provider":"vision","error":str(exc)})
    enriched["quality_provider_errors"]=errors
    return enriched


def enrich_text(output:dict[str,Any],*,validator_url:str,timeout_s:float=60)->dict[str,Any]:
    """Attach a CPU-side semantic/completeness verdict from a Phoenix-compatible validator."""
    enriched=dict(output)
    try:
        data=_post(validator_url,"/v1/text/quality",{"text":output.get("text"),
          "expected_text":output.get("expected_text")},timeout_s)
        enriched["semantic_score"]=data.get("score");enriched["validator_verdict"]=data.get("verdict")
        enriched["quality_provider_errors"]=[]
    except Exception as exc:enriched["quality_provider_errors"]=[{"provider":"text","error":str(exc)}]
    return enriched


def builtin_image_metrics(path:str)->dict[str,float|str]:
    """Dependency-light local blur evidence; semantic validation remains the VLM's job."""
    try:
        from PIL import Image,ImageFilter,ImageStat
        with Image.open(path) as image:
            gray=image.convert("L").resize((256,256));edges=gray.filter(ImageFilter.FIND_EDGES)
            edge_std=float(ImageStat.Stat(edges).stddev[0])
        return {"blur_score":round(max(0.0,min(1.0,edge_std/32.0)),4),"metric_source":"CPU_PIL_EDGE_STDDEV"}
    except Exception as exc:return {"metric_source":"UNAVAILABLE","metric_error":str(exc)}
