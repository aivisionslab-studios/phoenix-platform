from __future__ import annotations
import difflib, math, re, struct
from pathlib import Path
from typing import Any
from phoenix_forge.models import GPUInfo
from phoenix_forge.modules import gpu_safety

REPEATED=re.compile(r"(?P<c>[^\s])(?P=c){7,}")
CRASH_CODES={0xC0000005,-1073741819}

def _result(kind:str,score:float,failures:list[str],warnings:list[str],evidence:dict[str,Any])->dict[str,Any]:
    score=max(0.0,min(1.0,score))
    status="REJECTED" if failures else ("WARNING" if warnings else "VALID")
    return {"schema":"phoenix.forge.output-validation/v1","kind":kind,"status":status,"passed":not failures,
      "quality_score":round(score,4),"failures":failures,"warnings":warnings,"evidence":evidence}

def validate_text(text:str|None,*,finish_reason:str|None=None,stream_completed:bool=True,
  process_exit_code:int|None=0,expected_text:str|None=None,min_chars:int=2,
  reject_output_limit:bool=False,semantic_score:float|None=None,
  validator_verdict:str|None=None,runtime_error:str|None=None,
  failure_class:str|None=None)->dict[str,Any]:
    value=text or "";fail=[];warn=[];score=1.0
    classified=(failure_class or "").strip().upper()
    if classified in {"OUT_OF_MEMORY","ALLOCATION_FAILED","TIMEOUT","BUDGET_EXHAUSTED",
                      "DEVICE_LOST","DRIVER_ERROR","MEMORY_ERROR","DATA_MISMATCH","COMPUTE_MISMATCH",
                      "RUNTIME_UNAVAILABLE","RUNTIME_ERROR","RUNTIME_CRASH"}:
        fail.append(classified);score-=.8 if classified in {"DEVICE_LOST","DRIVER_ERROR","MEMORY_ERROR","DATA_MISMATCH","COMPUTE_MISMATCH"} else .5
    elif process_exit_code in CRASH_CODES:fail.append("ACCESS_VIOLATION_0XC0000005");score=0
    elif process_exit_code not in (None,0):fail.append("RUNTIME_CRASH");score-=.7
    if not stream_completed:fail.append("STREAM_INTERRUPTED");score-=.5
    if len(value.strip())<min_chars:fail.append("EMPTY_OR_TOO_SHORT");score-=.7
    if "\ufffd" in value or "\x00" in value:fail.append("INVALID_TEXT_ENCODING");score-=.6
    runs=[m.group(0) for m in REPEATED.finditer(value)]
    suspicious=[r for r in runs if r[0] in "?/0\\|#*_" or len(r)>=16]
    if suspicious:fail.append("DEGENERATE_REPEATED_CHARACTERS");score-=.8
    compact=re.sub(r"\s+","",value)
    if compact:
        top=max((compact.count(ch) for ch in set(compact)),default=0)/len(compact)
        if len(compact)>=16 and top>=.75:fail.append("LOW_CHARACTER_DIVERSITY");score-=.7
    else:top=1.0
    if finish_reason in {"length","max_tokens"}:
        (fail if reject_output_limit else warn).append("OUTPUT_LIMIT_REACHED");score-=.4 if reject_output_limit else 0
    elif finish_reason not in (None,"stop","eos","tool_calls"):warn.append("UNEXPECTED_FINISH_REASON")
    similarity=None
    if expected_text is not None:
        similarity=difflib.SequenceMatcher(None,expected_text.strip().casefold(),value.strip().casefold()).ratio()
        if similarity<.6:fail.append("EXPECTED_TEXT_MISMATCH");score-=.6
    if semantic_score is not None and semantic_score<.4:fail.append("SEMANTIC_VALIDATION_FAILURE");score-=.6
    if validator_verdict and validator_verdict.upper() in {"CORRUPT","TRUNCATED","INVALID","UNUSABLE"}:
        fail.append("TEXT_VALIDATOR_REJECTED_OUTPUT");score-=.7
    return _result("text",score,list(dict.fromkeys(fail)),warn,{"length":len(value),"finish_reason":finish_reason,
      "stream_completed":stream_completed,"process_exit_code":process_exit_code,"dominant_character_ratio":round(top,4),
      "repeated_runs":suspicious[:8],"expected_similarity":similarity,
      "semantic_score":semantic_score,"validator_verdict":validator_verdict,
      "runtime_error":runtime_error,"failure_class":classified or None})

def _image_header(path:Path)->dict[str,Any]:
    raw=path.read_bytes()
    if raw.startswith(b"\x89PNG\r\n\x1a\n") and len(raw)>=24:
        width,height=struct.unpack(">II",raw[16:24]);return {"format":"PNG","width":width,"height":height,"bytes":len(raw)}
    if raw[:2]==b"\xff\xd8":
        i=2
        while i+9<len(raw):
            if raw[i]!=0xff:i+=1;continue
            marker=raw[i+1];length=int.from_bytes(raw[i+2:i+4],"big")
            if marker in range(0xC0,0xC4):
                return {"format":"JPEG","width":int.from_bytes(raw[i+7:i+9],"big"),
                  "height":int.from_bytes(raw[i+5:i+7],"big"),"bytes":len(raw)}
            i+=max(2,length+2)
    raise ValueError("unsupported or corrupt image")

def _pixel_metrics(path:Path)->dict[str,Any]:
    try:
        from PIL import Image,ImageStat
        with Image.open(path) as im:
            im.verify()
        with Image.open(path) as im:
            gray=im.convert("L").resize((128,128));stat=ImageStat.Stat(gray)
            hist=gray.histogram();total=sum(hist);entropy=-sum((n/total)*math.log2(n/total) for n in hist if n)
            return {"decode_verified":True,"mean_luma":round(stat.mean[0],3),"luma_stddev":round(stat.stddev[0],3),
              "entropy":round(entropy,3)}
    except ImportError:return {"decode_verified":None}
    except Exception as exc:return {"decode_verified":False,"decode_error":str(exc)}

def validate_image(path:str|Path,*,prompt:str|None=None,expected_text:str|None=None,ocr_text:str|None=None,
  ocr_confidence:float|None=None,vision_score:float|None=None,vision_verdict:str|None=None,
  blur_score:float|None=None,artifact_score:float|None=None,min_width:int=64,min_height:int=64,
  require_independent_validation:bool=False)->dict[str,Any]:
    fail=[];warn=[];score=1.0;p=Path(path)
    try:header=_image_header(p)
    except (OSError,ValueError) as exc:
        return _result("image",0,["IMAGE_DECODE_OR_HEADER_FAILURE"],[],{"path":str(p),"error":str(exc)})
    pixels=_pixel_metrics(p)
    if header["width"]<min_width or header["height"]<min_height:fail.append("INVALID_IMAGE_DIMENSIONS");score-=.8
    if pixels.get("decode_verified") is False:fail.append("IMAGE_DECODE_FAILURE");score-=1
    if pixels.get("luma_stddev") is not None and pixels["luma_stddev"]<2:fail.append("NEAR_UNIFORM_IMAGE");score-=.8
    if pixels.get("entropy") is not None and pixels["entropy"]<1:fail.append("VERY_LOW_IMAGE_INFORMATION");score-=.6
    if blur_score is not None and blur_score<.2:fail.append("EXCESSIVE_BLUR");score-=.5
    if artifact_score is not None and artifact_score>.75:fail.append("SEVERE_VISUAL_ARTIFACTS");score-=.7
    similarity=None
    if expected_text is not None:
        if ocr_text is None:fail.append("OCR_RESULT_MISSING");score-=.4
        else:
            similarity=difflib.SequenceMatcher(None,expected_text.casefold().strip(),ocr_text.casefold().strip()).ratio()
            if similarity<.7:fail.append("OCR_TEXT_MISMATCH");score-=.6
    if ocr_confidence is not None and ocr_confidence<.4:warn.append("LOW_OCR_CONFIDENCE")
    if vision_score is not None and vision_score<.4:fail.append("VISION_QUALITY_FAILURE");score-=.6
    if vision_verdict and vision_verdict.upper() in {"CORRUPT","UNUSABLE","DEPLORABLE","INVALID"}:
        fail.append("VISION_REJECTED_OUTPUT");score-=.7
    independent=vision_score is not None or vision_verdict is not None or ocr_text is not None or blur_score is not None or artifact_score is not None
    if require_independent_validation and not independent:
        fail.append("INDEPENDENT_VALIDATOR_MISSING");score-=.5
    return _result("image",score,list(dict.fromkeys(fail)),warn,{"path":str(p),"prompt":prompt,"header":header,
      "pixels":pixels,"ocr_text":ocr_text,"ocr_confidence":ocr_confidence,"expected_text_similarity":similarity,
      "vision_score":vision_score,"vision_verdict":vision_verdict,"blur_score":blur_score,"artifact_score":artifact_score})

def action(validation:dict[str,Any],*,attempt:int=1,cpu_control_passed:bool=False)->dict[str,Any]:
    if validation["passed"]:return {"deliver":True,"action":"DELIVER","effective_mode":None,"notify_user":False}
    if attempt<2:return {"deliver":False,"action":"RETRY_SAME_GPU_CLEAN","effective_mode":"GPU","notify_user":True}
    if not cpu_control_passed:return {"deliver":False,"action":"RUN_CPU_CONTROL","effective_mode":"CPU","notify_user":True}
    return {"deliver":False,"action":"FALLBACK_CPU_AND_BLOCK_SCOPE","effective_mode":"CPU","notify_user":True}

def evaluate_and_record(validation:dict[str,Any],*,workload:str,backend:str="vulkan",runtime:str="*",
  model:str="*",attempt:int=1,cpu_control_passed:bool=False,gpu:GPUInfo|dict[str,Any]|None=None)->dict[str,Any]:
    decision=action(validation,attempt=attempt,cpu_control_passed=cpu_control_passed)
    safety=None
    if not validation["passed"]:
        safety=gpu_safety.record_output_failure(workload=workload,backend=backend,runtime=runtime,model=model,
          reason=validation["failures"][0] if validation["failures"] else "QUALITY_FAILURE",evidence=validation,
          gpu=gpu,cpu_control_passed=cpu_control_passed,reproduced=attempt>=2)
    return {"validation":validation,"decision":decision,"safety":safety}
