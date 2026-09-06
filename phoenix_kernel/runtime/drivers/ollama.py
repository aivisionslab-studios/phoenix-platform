from __future__ import annotations
import asyncio
import logging
import urllib.request
import json
from datetime import datetime, timezone
from typing import Any

from core.domain.execution import ExecutionPlan, ExecutionResult, ExecutionStatus
from core.domain.runtime import RuntimeStatus, RuntimeState

logger = logging.getLogger(__name__)
_UTC = timezone.utc

class OllamaDriver:
    @property
    def name(self) -> str: return "ollama"

    @staticmethod
    def _check_reachable() -> bool:
        try:
            with urllib.request.urlopen("http://localhost:11434/api/version", timeout=2) as r:
                return r.status == 200
        except Exception:
            return False

    async def start(self) -> bool:
        # PHX-FIX (auditoria 31/08, "sucesso fantasma" achado por agente de
        # varredura ampla): esta função retornava `True` incondicionalmente,
        # SEM nenhuma checagem real - diferente de todos os outros drivers
        # do projeto (SdCppDriver/WhisperDriver/LlamaCppDriver), cujo
        # `start()` sempre confere se o binário/serviço está de fato
        # disponível antes de reportar sucesso. `status()`, logo abaixo
        # neste mesmo arquivo, já tinha a checagem real (`GET /api/version`)
        # - só não era chamada por `start()`. Se o serviço Ollama não
        # estivesse rodando, o Kernel achava que o runtime tinha subido com
        # sucesso e só ia descobrir o contrário no primeiro `execute()` que
        # falhasse, ao invés de reportar a falha de start já na hora certa.
        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(None, self._check_reachable)

    async def stop(self) -> bool: return True

    async def status(self) -> RuntimeStatus:
        try:
            loop = asyncio.get_running_loop()
            is_ok = await loop.run_in_executor(None, self._check_reachable)
            return RuntimeStatus(name=self.name, state=RuntimeState.RUNNING if is_ok else RuntimeState.ERROR)
        except: return RuntimeStatus(name=self.name, state=RuntimeState.ERROR)

    async def execute(self, plan: ExecutionPlan) -> ExecutionResult:
        logger.info("OllamaDriver: Executing plan %s", plan.id)

        # PHX-FIX (destravar Ollama como 2ª opção de engine de texto): antes
        # só lia `parameters.get("prompt")` e IGNORAVA `system_prompt` por
        # completo - todo chamador real (ReasoningEngine.plan_mission,
        # RuleEvaluator.evaluate) manda o prompt do usuário em
        # `user_prompt` e as instruções (persona + schema JSON da missão)
        # em `system_prompt`. Uma missão de `resident research` rodando em
        # Ollama, antes desta correção, mandava só a intenção crua, sem
        # NENHUMA instrução de formato - o LLM não tinha como saber que
        # precisava devolver JSON.
        params = plan.parameters or {}
        prompt = params.get("user_prompt", params.get("prompt", ""))
        system_prompt = params.get("system_prompt")

        messages = []
        if system_prompt:
            messages.append({"role": "system", "content": system_prompt})
        messages.append({"role": "user", "content": prompt})

        # PHX-FIX: Usando /api/chat para melhor compatibilidade com modelos instruct (Llama 3)
        payload = {
            "model": plan.model,
            "messages": messages,
            "stream": False,
            "options": {"temperature": params.get("temperature", 0.1)},
        }
        # PHX-NEW: Ollama suporta `"format": "json"` nativamente na API
        # (força o modelo a gerar JSON válido via grammar do lado do
        # servidor). PHX-FIX (auditoria 2026-08-20): o LlamaCppDriver
        # também passou a aplicar `json_format` (via `response_format` no
        # endpoint OpenAI-compatible do llama-server - ver
        # LlamaCppDriver.execute()) - os dois runtimes agora têm blindagem
        # nativa equivalente, mais a camada de extração/retry em
        # ReasoningEngine.plan_mission() como rede de segurança comum aos
        # dois.
        if params.get("json_format"):
            payload["format"] = "json"
        data = json.dumps(payload).encode('utf-8')
        
        try:
            loop = asyncio.get_running_loop()
            def req():
                req = urllib.request.Request("http://localhost:11434/api/chat", data=data, headers={'Content-Type': 'application/json'})
                # PHX-FIX: Timeout aumentado para 600s (10 min) para suportar inferência pesada na CPU
                with urllib.request.urlopen(req, timeout=600) as r:
                    return json.loads(r.read().decode())
            
            res_data = await loop.run_in_executor(None, req)
            
            # A resposta do /api/chat vem dentro de message.content
            output_text = res_data.get("message", {}).get("content", "")

            # PHX-FIX (auditoria 31/08, "sucesso fantasma" achado por agente
            # de varredura ampla): antes, qualquer resposta HTTP 200 virava
            # SUCCESS, mesmo com `output_text` vazio (ex: modelo carregado
            # mas sem resposta, erro silencioso do lado do Ollama que ainda
            # assim devolve 200). WhisperDriver já trata "saída vazia" como
            # falha explícita ("Transcrição vazia...") pelo mesmo motivo -
            # replicado aqui pra manter o mesmo padrão de "não fingir
            # sucesso sem conteúdo real".
            if not output_text.strip():
                logger.error("OllamaDriver: resposta vazia do modelo '%s' (HTTP 200 sem conteúdo em message.content).", plan.model)
                return ExecutionResult(
                    plan_id=plan.id, status=ExecutionStatus.FAILED,
                    errors=[f"Ollama retornou resposta vazia pro modelo '{plan.model}' (sem erro HTTP, mas sem conteúdo)."]
                )

            return ExecutionResult(
                plan_id=plan.id,
                status=ExecutionStatus.SUCCESS,
                output=output_text,
                metrics={"tokens_per_second": res_data.get("eval_count", 0) / max(res_data.get("eval_duration", 1) / 1e9, 0.001)},
                started_at=datetime.now(_UTC),
                finished_at=datetime.now(_UTC)
            )
        except Exception as exc:
            logger.error("OllamaDriver: Execution failed - %s", exc)
            return ExecutionResult(plan_id=plan.id, status=ExecutionStatus.FAILED, errors=[str(exc)])

    async def pull_model(self, model_name: str) -> bool:
        logger.info("OllamaDriver: Pulling model '%s'...", model_name)
        try:
            payload = {"name": model_name}
            data = json.dumps(payload).encode('utf-8')
            req = urllib.request.Request("http://localhost:11434/api/pull", data=data, headers={"Content-Type": "application/json"})
            loop = asyncio.get_running_loop()
            def req_exec():
                with urllib.request.urlopen(req, timeout=600) as r:
                    for line in r: pass
                return True
            return await loop.run_in_executor(None, req_exec)
        except Exception as e:
            logger.error("OllamaDriver: Failed to pull model: %s", e)
            return False

    async def embed(self, model_name: str, text: str) -> list[float]:
        try:
            payload = {"model": model_name, "prompt": text}
            data = json.dumps(payload).encode('utf-8')
            req = urllib.request.Request("http://localhost:11434/api/embeddings", data=data, headers={"Content-Type": "application/json"})
            loop = asyncio.get_running_loop()
            def req_exec():
                with urllib.request.urlopen(req, timeout=30) as r:
                    return json.loads(r.read().decode()).get("embedding", [])
            return await loop.run_in_executor(None, req_exec)
        except Exception as e:
            logger.error("OllamaDriver: Failed to generate embedding: %s", e)
            return []

    async def describe_image(self, model_name: str, prompt: str, image_path: str) -> str:
        import base64
        from pathlib import Path
        if not Path(image_path).exists(): return "Error: Image file not found."
        with open(image_path, "rb") as f: image_b64 = base64.b64encode(f.read()).decode()
        
        payload = {
            "model": model_name, 
            "messages": [{"role": "user", "content": prompt, "images": [image_b64]}], 
            "stream": False
        }
        data = json.dumps(payload).encode('utf-8')
        try:
            req = urllib.request.Request("http://localhost:11434/api/chat", data=data, headers={"Content-Type": "application/json"})
            loop = asyncio.get_running_loop()
            def req_exec():
                with urllib.request.urlopen(req, timeout=600) as r:
                    return json.loads(r.read().decode()).get("message", {}).get("content", "")
            return await loop.run_in_executor(None, req_exec)
        except Exception as e:
            logger.error("OllamaDriver: Image description failed: %s", e)
            return f"Error: {str(e)}"