from __future__ import annotations

import uuid
from dataclasses import dataclass
from typing import Any, Callable

from phoenix_forge.models import GPUInfo
from phoenix_forge.modules import gpu_ledger, gpu_safety, result_integrity, workload_state

SCHEMA = "phoenix.forge.delivery-guard/v1"
CAPACITY_FAILURES = {"OUT_OF_MEMORY", "ALLOCATION_FAILED", "BUDGET_EXHAUSTED"}
TRANSIENT_FAILURES = {"TIMEOUT", "RUNTIME_UNAVAILABLE"}
HARDWARE_FAILURES = {"DEVICE_LOST", "DRIVER_ERROR", "MEMORY_ERROR", "DATA_MISMATCH", "COMPUTE_MISMATCH"}
CPU_RETRYABLE_FAILURES = {
    "OUTPUT_LIMIT_REACHED", "EMPTY_OR_TOO_SHORT", "STREAM_INTERRUPTED",
    "RUNTIME_CRASH", "TIMEOUT",
}


@dataclass(frozen=True)
class GuardPolicy:
    max_gpu_attempts: int = 2
    max_cpu_attempts: int = 2
    validate_cpu_output: bool = True


def _notice(code: str, message: str, *, severity: str = "warning") -> dict[str, str]:
    return {"severity": severity, "code": code, "message": message}


def _validate(kind: str, output: dict[str, Any]) -> dict[str, Any]:
    if kind == "text":
        return result_integrity.validate_text(
            output.get("text"), finish_reason=output.get("finish_reason"),
            stream_completed=output.get("stream_completed", True),
            process_exit_code=output.get("process_exit_code", 0),
            expected_text=output.get("expected_text"),
            reject_output_limit=True,
            semantic_score=output.get("semantic_score"),validator_verdict=output.get("validator_verdict"),
            runtime_error=output.get("runtime_error"),failure_class=output.get("failure_class"),
        )
    if kind == "image":
        return result_integrity.validate_image(
            output["path"], prompt=output.get("prompt"), expected_text=output.get("expected_text"),
            ocr_text=output.get("ocr_text"), ocr_confidence=output.get("ocr_confidence"),
            vision_score=output.get("vision_score"), vision_verdict=output.get("vision_verdict"),
            blur_score=output.get("blur_score"), artifact_score=output.get("artifact_score"),
            require_independent_validation=True,
        )
    raise ValueError(f"unsupported output kind: {kind}")


def evaluate_sequence(*, kind: str, workload: str, gpu_outputs: list[dict[str, Any]],
                      cpu_output: dict[str, Any] | None = None, backend: str = "vulkan",
                      runtime: str = "*", model: str = "*", device_name: str | None = None,
                      gpu: GPUInfo | dict[str, Any] | None = None,
                      execution_id: str | None = None, policy: GuardPolicy | None = None,
                      user_mode: str = "AUTO") -> dict[str, Any]:
    """Evaluate already-produced outputs and return an enforceable delivery/fallback decision."""
    policy = policy or GuardPolicy()
    execution_id = execution_id or str(uuid.uuid4())
    route = gpu_ledger.route(workload, device_name=device_name, user_mode=user_mode,backend=backend,runtime=runtime,model=model)
    trace: list[dict[str, Any]] = []

    if route["effective_mode"] == "CPU":
        if cpu_output is None:
            explicit_cpu = user_mode.upper() == "CPU"
            return {"schema": SCHEMA, "execution_id": execution_id, "status": "CPU_REQUIRED",
                    "deliver": False, "effective_mode": "CPU", "route": route, "trace": trace,
                    "notice": _notice(
                      "CPU_EXECUTION_REQUIRED" if explicit_cpu else "GPU_RESTRICTED_CPU_REQUIRED",
                      "Execute a solicitação via CPU conforme o modo selecionado." if explicit_cpu else
                      "A GPU está restrita para este tipo de inferência. Execute a solicitação via CPU.")}
        validation = _validate(kind, cpu_output)
        trace.append({"attempt": 1, "mode": "CPU", "validation": validation})
        passed=validation["passed"]
        explicit_cpu = user_mode.upper() == "CPU"
        notice=(_notice("CPU_MODE_SELECTED", "Inferência executada via CPU conforme o modo selecionado.")
          if passed and explicit_cpu else _notice("GPU_RESTRICTED_CPU_USED", "Inferência executada via CPU por política de segurança.")
          if passed else _notice("CPU_OUTPUT_REJECTED",
            "A resposta executada via CPU falhou na validação e não será entregue ao usuário.", severity="error"))
        if not passed:
            notice["failures"] = validation.get("failures", [])
        return {"schema": SCHEMA, "execution_id": execution_id,
                "status": "DELIVERED_CPU" if passed else "CPU_OUTPUT_REJECTED",
                "deliver": passed, "effective_mode": "CPU", "route": route,
                "output": cpu_output if passed else None, "trace": trace,
                "notice": notice}

    attempted = gpu_outputs[:max(1, policy.max_gpu_attempts)]
    for index, output in enumerate(attempted, 1):
        validation = _validate(kind, output)
        trace.append({"attempt": index, "mode": "GPU", "validation": validation})
        if validation["passed"]:
            return {"schema": SCHEMA, "execution_id": execution_id, "status": "DELIVERED_GPU",
                    "deliver": True, "effective_mode": "GPU", "route": route, "output": output,
                    "trace": trace, "notice": None}

    if len(attempted) < policy.max_gpu_attempts and cpu_output is None:
        return {"schema": SCHEMA, "execution_id": execution_id, "status": "GPU_RETRY_REQUIRED",
                "deliver": False, "effective_mode": "GPU", "route": route, "trace": trace,
                "notice": _notice("GPU_OUTPUT_REJECTED_RETRY",
                  "A entrega da GPU falhou na validação e será repetida uma vez em ambiente limpo.")}
    if cpu_output is None:
        return {"schema": SCHEMA, "execution_id": execution_id, "status": "CPU_CONTROL_REQUIRED",
                "deliver": False, "effective_mode": "CPU", "route": route, "trace": trace,
                "notice": _notice("GPU_OUTPUT_REJECTED_CPU_CONTROL",
                  "Falhas repetidas na entrega da GPU. É necessário executar um controle via CPU.", severity="error")}

    cpu_validation = _validate(kind, cpu_output)
    trace.append({"attempt": 1, "mode": "CPU_CONTROL", "validation": cpu_validation})
    if not cpu_validation["passed"]:
        return {"schema": SCHEMA, "execution_id": execution_id, "status": "OUTPUT_PIPELINE_FAILURE",
                "deliver": False, "effective_mode": "CPU", "route": route, "trace": trace,
                "notice": _notice("CPU_CONTROL_FAILED",
                  "A saída também falhou via CPU; não há evidência suficiente para atribuir esta falha somente à GPU.", severity="error")}

    failures={failure for item in trace for failure in item.get("validation",{}).get("failures",[])}
    capacity_only=bool(failures) and failures.issubset(CAPACITY_FAILURES | TRANSIENT_FAILURES | {"EMPTY_OR_TOO_SHORT","STREAM_INTERRUPTED","RUNTIME_CRASH"}) and any(x in failures for x in CAPACITY_FAILURES | TRANSIENT_FAILURES)
    if capacity_only:
        runtime_unavailable="RUNTIME_UNAVAILABLE" in failures and not failures.intersection(CAPACITY_FAILURES)
        return {"schema": SCHEMA, "execution_id": execution_id,
                "status": "DELIVERED_CPU_GPU_RUNTIME_FALLBACK" if runtime_unavailable else "DELIVERED_CPU_GPU_CAPACITY_FALLBACK", "deliver": True,
                "effective_mode": "CPU", "route": route, "output": cpu_output,
                "trace": trace, "safety": None,
                "notice": _notice(
                  "GPU_RUNTIME_UNAVAILABLE_CPU_FALLBACK" if runtime_unavailable else "GPU_CAPACITY_FALLBACK_CPU",
                  "O runtime GPU não estava disponível. A tarefa foi concluída via CPU e a falha foi registrada." if runtime_unavailable else
                  "A configuração solicitada não coube ou expirou na GPU. A tarefa foi concluída via CPU sem condenar o hardware.")}
    first_failure=trace[0]["validation"]["failures"][0] if trace and trace[0]["validation"]["failures"] else "QUALITY_FAILURE"
    safety=gpu_safety.record_output_failure(workload=workload, backend=backend, runtime=runtime, model=model,
      reason=first_failure, evidence={"execution_id":execution_id,"gpu_attempts":len(attempted),"trace":trace},
      gpu=gpu, cpu_control_passed=True, reproduced=len(attempted)>=2)
    return {"schema": SCHEMA, "execution_id": execution_id, "status": "DELIVERED_CPU_GPU_SCOPE_BLOCKED",
            "deliver": True, "effective_mode": "CPU", "route": route, "output": cpu_output,
            "trace": trace, "safety": safety,
            "notice": _notice("GPU_DELIVERY_FAILURE_CPU_FALLBACK",
              "A GPU produziu entregas inválidas repetidas. Esta tarefa foi concluída via CPU e o escopo defeituoso foi bloqueado.", severity="error")}


def _finalize(result: dict[str, Any], workload: str) -> dict[str, Any]:
    """Attach persisted workload state without allowing state recording to break delivery."""
    try:
        result["workload_state"] = workload_state.observe_execution(result, workload)
    except Exception as exc:
        result["workload_state"] = {"state": "UNAVAILABLE", "error": str(exc)}
    return result


def execute_guarded(*, kind: str, workload: str, gpu_runner: Callable[[], dict[str, Any]],
                    cpu_runner: Callable[[], dict[str, Any]], backend: str = "vulkan",
                    runtime: str = "*", model: str = "*", device_name: str | None = None,
                    gpu: GPUInfo | dict[str, Any] | None = None,
                    policy: GuardPolicy | None = None, user_mode: str = "AUTO") -> dict[str, Any]:
    """Execute, validate and fall back while converting failures into Forge evidence/state.

    The Forge detects/classifies. The Engine consumes effective_mode/status and owns
    orchestration. OOM/capacity never condemns hardware. Reproducible hardware-class
    failures can block the affected GPU scope and force CPU until requalification.
    """
    policy=policy or GuardPolicy()
    route=gpu_ledger.route(workload,device_name=device_name,user_mode=user_mode,backend=backend,runtime=runtime,model=model)
    if route["effective_mode"]=="CPU":
        combined_trace=[];result=None
        for attempt in range(1,max(1,policy.max_cpu_attempts)+1):
            result=evaluate_sequence(kind=kind,workload=workload,gpu_outputs=[],cpu_output=cpu_runner(),
              backend=backend,runtime=runtime,model=model,device_name=device_name,gpu=gpu,
              policy=policy,user_mode=user_mode)
            validation=(result.get("trace") or [{}])[-1].get("validation",{})
            combined_trace.append({"attempt":attempt,"mode":"CPU","validation":validation})
            if result.get("deliver"):
                result["trace"]=combined_trace
                if attempt>1:
                    result["status"]="DELIVERED_CPU_AFTER_RETRY"
                    result["notice"]=_notice("CPU_RECOVERED_AFTER_RETRY",
                      "A primeira tentativa não produziu uma entrega válida; o Forge recuperou a execução via CPU.")
                    result["retry_used"]=True
                return _finalize(result, workload)
            failures=set(validation.get("failures",[]))
            if attempt>=policy.max_cpu_attempts or not failures.intersection(CPU_RETRYABLE_FAILURES | {"RUNTIME_UNAVAILABLE","RUNTIME_ERROR"}):
                break
        assert result is not None
        result["trace"]=combined_trace
        result["retry_used"]=len(combined_trace)>1
        validation=combined_trace[-1].get("validation",{})
        runtime_error=str((validation.get("evidence") or {}).get("runtime_error") or "")
        if runtime_error:
            result["status"]="RUNTIME_UNAVAILABLE"
            result["notice"]=_notice("RUNTIME_UNAVAILABLE",
              "O runtime CPU não ficou pronto após a tentativa de recuperação; nenhuma resposta foi entregue.",severity="error")
            result["notice"]["runtime_error"]=runtime_error
            result["notice"]["failures"]=validation.get("failures",[])
        return _finalize(result, workload)

    attempts=[]
    observed_failure_classes=[]
    for _ in range(policy.max_gpu_attempts):
        output=gpu_runner();attempts.append(output)
        partial=evaluate_sequence(kind=kind,workload=workload,gpu_outputs=attempts,backend=backend,
          runtime=runtime,model=model,device_name=device_name,gpu=gpu,policy=policy,user_mode=user_mode)
        if partial["deliver"]:
            return _finalize(partial, workload)
        validation=partial.get("trace", [{}])[-1].get("validation", {}) if partial.get("trace") else {}
        failures=set(validation.get("failures", []))
        observed_failure_classes.extend(sorted(failures))
        for failure in sorted(failures.intersection(CAPACITY_FAILURES | TRANSIENT_FAILURES | HARDWARE_FAILURES | {"RUNTIME_ERROR","RUNTIME_CRASH"})):
            try:
                gpu_safety.record_runtime_failure(
                    workload=workload, backend=backend, runtime=runtime, model=model,
                    failure_class=failure,
                    evidence={"validation":validation,"attempt":len(attempts),"device_name":device_name},
                    gpu=gpu,
                )
            except Exception:
                pass
        # Capacity/transient failures must immediately change architecture; repeating
        # the same GPU allocation is not useful. Hardware-class failures also switch
        # away immediately for this request, but persistent blocking still requires
        # corroborating/reproduced evidence in gpu_safety.
        if failures.intersection(CAPACITY_FAILURES | TRANSIENT_FAILURES | HARDWARE_FAILURES):
            break

    result=evaluate_sequence(kind=kind,workload=workload,gpu_outputs=attempts,cpu_output=cpu_runner(),
      backend=backend,runtime=runtime,model=model,device_name=device_name,gpu=gpu,policy=policy,user_mode=user_mode)
    result["failure_interception"]={
        "detected": bool(observed_failure_classes),
        "classes": list(dict.fromkeys(observed_failure_classes)),
        "architecture_changed": result.get("effective_mode")=="CPU",
        "requested_mode": user_mode.upper(),
        "effective_mode": result.get("effective_mode"),
    }
    return _finalize(result, workload)
