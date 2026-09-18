from __future__ import annotations

import base64
import os
import time
import uuid
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

import httpx

from phoenix_forge.models import GPUInfo
from phoenix_forge.modules import delivery_guard, gpu_safety, quality_providers

SCHEMA="phoenix.forge.guarded-runtime/v2"


def _classify_runtime_error(exc: Exception | str) -> str:
    """Normalize runtime/driver failures without declaring hardware corruption from OOM alone."""
    text=str(exc).lower()
    if any(x in text for x in ("outofdevicememory", "out of device memory", "out of memory", "vk_error_out_of_device_memory", "device memory allocation")):
        return "OUT_OF_MEMORY"
    if any(x in text for x in ("failed to allocate", "allocation failed", "cannot allocate", "failed to allocate buffer")):
        return "ALLOCATION_FAILED"
    if any(x in text for x in ("device lost", "vk_error_device_lost")):
        return "DEVICE_LOST"
    if any(x in text for x in ("driver crash", "driver reset", "display driver stopped", "amdkmdag", "atikmdag")):
        return "DRIVER_ERROR"
    if any(x in text for x in ("timed out", "timeout", "read timeout", "connect timeout")):
        return "TIMEOUT"
    if any(x in text for x in ("connection refused", "actively refused", "all connection attempts failed")):
        return "RUNTIME_UNAVAILABLE"
    if any(x in text for x in ("0xc0000374", "heap corruption", "0xc0000005", "access violation")):
        return "RUNTIME_CRASH"
    return "RUNTIME_ERROR"


def _endpoint(value:str)->str:
    parsed=urlparse(value)
    allowed={"127.0.0.1","localhost","::1"}
    if parsed.scheme not in {"http","https"} or not parsed.hostname:raise ValueError("invalid runtime endpoint")
    if parsed.hostname not in allowed and os.environ.get("PHOENIX_ALLOW_REMOTE_RUNTIME")!="1":
        raise ValueError("remote runtime endpoint blocked; set PHOENIX_ALLOW_REMOTE_RUNTIME=1 to authorize it")
    return value.rstrip("/")


def _chat_once(base_url:str,*,model:str,messages:list[dict[str,Any]],max_tokens:int,
               temperature:float,timeout_s:float)->dict[str,Any]:
    started=time.monotonic()
    try:
        response=httpx.post(_endpoint(base_url)+"/chat/completions",json={"model":model,"messages":messages,
          "max_tokens":max_tokens,"temperature":temperature,"stream":False},timeout=timeout_s)
        response.raise_for_status();raw=response.json();choice=raw["choices"][0]
        message=choice.get("message") or {}
        # Never promote private reasoning to user-visible content.  Some
        # reasoning models legitimately return an empty content field while
        # exposing only reasoning_content; the Delivery Guard must reject that
        # incomplete delivery instead of leaking chain-of-thought as an answer.
        return {"text":str(message.get("content") or ""),
          "reasoning_content":str(message.get("reasoning_content") or ""),
          "finish_reason":choice.get("finish_reason"),"stream_completed":True,"process_exit_code":0,
          "latency_s":round(time.monotonic()-started,3),"usage":raw.get("usage",{}),
          "runtime_message":{"role":message.get("role","assistant")},"runtime_error":None}
    except Exception as exc:
        detail=str(exc)
        if isinstance(exc,httpx.HTTPStatusError):
            try:
                body=(exc.response.text or "")[:4000]
                if body: detail=f"{detail} | response={body}"
            except Exception:
                pass
        failure_class=_classify_runtime_error(detail)
        return {"text":"","reasoning_content":"","finish_reason":"runtime_error",
          "stream_completed":False,"process_exit_code":1,
          "latency_s":round(time.monotonic()-started,3),"usage":{},
          "runtime_error":detail,"failure_class":failure_class}


def guarded_chat(*,gpu_url:str,cpu_url:str,model:str,messages:list[dict[str,Any]],
                 device_name:str|None=None,gpu:GPUInfo|dict[str,Any]|None=None,
                 max_tokens:int=512,temperature:float=.2,timeout_s:float=300,
                 validator_url:str|None=None,user_mode:str="AUTO")->dict[str,Any]:
    deadline=time.monotonic()+max(1.0,timeout_s)
    cpu_attempts=0
    previous_cpu_output:dict[str,Any]|None=None

    def run(url:str,*,cpu:bool=False)->dict[str,Any]:
        nonlocal cpu_attempts,previous_cpu_output
        retry_messages=messages;retry_max_tokens=max_tokens
        if cpu:
            cpu_attempts+=1
            if cpu_attempts>1 and previous_cpu_output is not None:
                if previous_cpu_output.get("finish_reason")=="length":
                    retry_messages=[dict(item) for item in messages]
                    for index in range(len(retry_messages)-1,-1,-1):
                        if retry_messages[index].get("role")=="user":
                            content=str(retry_messages[index].get("content") or "")
                            if not content.lstrip().startswith("/no_think"):
                                retry_messages[index]["content"]="/no_think\n"+content
                            break
                    retry_max_tokens=min(4096,max(512,max_tokens*2))
                elif previous_cpu_output.get("runtime_error"):
                    remaining=max(0.0,deadline-time.monotonic())
                    time.sleep(min(1.5,max(0.0,remaining-1.0)))
        attempt_timeout=max(1.0,deadline-time.monotonic())
        output=_chat_once(url,model=model,messages=retry_messages,max_tokens=retry_max_tokens,
          temperature=temperature,timeout_s=attempt_timeout)
        if cpu:previous_cpu_output=output
        return quality_providers.enrich_text(output,validator_url=validator_url,timeout_s=timeout_s) if validator_url else output
    result=delivery_guard.execute_guarded(kind="text",workload="llm",gpu_runner=lambda:run(gpu_url),
      cpu_runner=lambda:run(cpu_url,cpu=True),backend="vulkan",runtime="phoenix-llama-runtime",model=model,
      device_name=device_name,gpu=gpu,user_mode=user_mode)
    result["runtime_schema"]=SCHEMA
    return result


def _output_dir()->Path:
    path=gpu_safety.state_dir()/"quarantine";path.mkdir(parents=True,exist_ok=True);return path


def _image_once(base_url:str,*,prompt:str,negative_prompt:str,width:int,height:int,steps:int,
                timeout_s:float,ocr_url:str|None,vision_url:str|None,expected_text:str|None)->dict[str,Any]:
    started=time.monotonic()
    try:
        response=httpx.post(_endpoint(base_url)+"/sdapi/v1/txt2img",json={"prompt":prompt,
          "negative_prompt":negative_prompt,"width":width,"height":height,"steps":steps},timeout=timeout_s)
        response.raise_for_status();raw=response.json();encoded=raw.get("images",[])[0]
        if "," in encoded:encoded=encoded.split(",",1)[1]
        path=_output_dir()/f"guard-{uuid.uuid4().hex}.png";path.write_bytes(base64.b64decode(encoded,validate=True))
        output={"path":str(path),"prompt":prompt,"expected_text":expected_text,
          "latency_s":round(time.monotonic()-started,3),"runtime_error":None}
        output.update(quality_providers.builtin_image_metrics(str(path)))
        return quality_providers.enrich_image(output,ocr_url=ocr_url,vision_url=vision_url,timeout_s=timeout_s)
    except Exception as exc:
        return {"path":str(_output_dir()/f"failed-{uuid.uuid4().hex}.png"),"prompt":prompt,
          "expected_text":expected_text,"latency_s":round(time.monotonic()-started,3),"runtime_error":str(exc)}


def guarded_image(*,gpu_url:str,cpu_url:str,prompt:str,device_name:str|None=None,
                  gpu:GPUInfo|dict[str,Any]|None=None,negative_prompt:str="",
                  width:int=512,height:int=512,steps:int=20,timeout_s:float=1800,
                  ocr_url:str|None=None,vision_url:str|None=None,expected_text:str|None=None,
                  model:str="stable-diffusion",user_mode:str="AUTO")->dict[str,Any]:
    kwargs={"prompt":prompt,"negative_prompt":negative_prompt,"width":width,"height":height,
      "steps":steps,"timeout_s":timeout_s,"ocr_url":ocr_url,"vision_url":vision_url,"expected_text":expected_text}
    result=delivery_guard.execute_guarded(kind="image",workload="image",
      gpu_runner=lambda:_image_once(gpu_url,**kwargs),cpu_runner=lambda:_image_once(cpu_url,**kwargs),
      backend="vulkan",runtime="phoenix-diffusion",model=model,device_name=device_name,gpu=gpu,
      user_mode=user_mode)
    result["runtime_schema"]=SCHEMA
    return result
