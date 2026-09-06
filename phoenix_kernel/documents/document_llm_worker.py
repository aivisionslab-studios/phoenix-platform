"""Phoenix Document Pipeline V2 - worker semântico CPU/GPU seguro.

Estado validado em hardware real (RX 580 2048SP / Vulkan):
- o binário llama-server enumera Vulkan0 e realmente executa na GPU;
- health HTTP, uso de VRAM e throughput NÃO bastam para provar correctness;
- ``-ngl 1`` com ``output.weight`` em Vulkan corrompeu a geração;
- ``-ngl 1 -ot output.weight=CPU`` restaurou a resposta correta;
- full offload ainda apresentou corrupção em outras operações.

Por isso este módulo nunca autoriza um worker GPU só porque ele subiu. O
worker usa porta dinâmica, configurações locais (sem alterar o chatbot :8081),
executa um self-test de correctness e, por padrão, faz fallback para CPU se a
GPU não passar. ``taxonomy_resolver.py`` e ``semantic_resolver.py`` continuam
agnósticos de backend: recebem apenas ``llm_call_fn``.

O modo CPU fala com o llama-server compartilhado na porta 8081 e não inicia ou
encerra esse processo. O modo GPU cria uma instância temporária independente e
sempre libera o processo/VRAM ao sair do ``async with``.
"""
from __future__ import annotations

import asyncio
import json
import logging
import socket
import time
import urllib.error
import urllib.request
from typing import Literal, Optional

from core.domain.execution import ExecutionPlan
from phoenix_kernel.documents.semantic_resolver import SemanticTask
from phoenix_kernel.runtime.drivers.llama_cpp import LlamaCppDriver, find_free_local_port
from phoenix_kernel.orchestration.execution_arbiter import ResourcePolicy

logger = logging.getLogger(__name__)

# Parâmetros LOCAIS do worker GPU documental. A faixa começa em 8095 porque
# 8090 foi encontrada ocupada por um componente do Windows em teste real.
# Nada aqui altera PHOENIX_LLM_NGL nem a política global do chatbot.
DOCUMENT_GPU_PORT_START = 8095
DOCUMENT_GPU_PORT_END = 8110
# PHX-FIX (31/08): estava "999" (full offload), contradizendo o próprio
# docstring do topo deste arquivo (linhas 6-8), que documenta que full
# offload SOZINHO ainda corrompeu a geração em teste real, e que a
# combinação que restaurou correctness foi ngl=1 + override abaixo.
DOCUMENT_GPU_NGL = "1"
DOCUMENT_GPU_CONTEXT_HINT = 16384
DOCUMENT_GPU_DEVICE = "Vulkan0"

# O override abaixo é conhecido-bom SOMENTE para isolar a projeção de saída
# na RX 580: -ngl 1 + output.weight=CPU restaurou correctness. Ele NÃO torna
# full-offload seguro por si só (ngl=999 ainda apresentou corrupção em teste
# real), portanto o self-test abaixo continua obrigatório antes de liberar a
# instância GPU para um job.
# PHX-FIX (31/08): estava {} (vazio) - a combinação que o docstring do topo
# deste arquivo documenta como validada (linha 7) é justamente esta.
DOCUMENT_GPU_TENSOR_OVERRIDES = {"output.weight": "CPU"}

# Porta do motor CPU compartilhado. Este módulo NUNCA inicia nem para
# esse processo - quem faz isso é o Kernel, no boot da Phoenix. Em
# mode="cpu" este módulo só assume que já está de pé e fala HTTP direto
# com ele, exatamente como taxonomy_benchmark_run.py já faz hoje.
DOCUMENT_CPU_PORT = 8081

_DEFAULT_SYSTEM_PROMPT = (
    "Você é um classificador determinístico dentro de um pipeline automatizado. "
    "Responda ESTRITAMENTE em JSON, sem nenhum texto fora do JSON, sem markdown, "
    "sem bloco de pensamento, no formato exato: "
    '{"selected_value": <um item EXATAMENTE igual a um dos valores permitidos>, '
    '"confidence": <número entre 0 e 1>, "reason": <string curta>}. '
    "Nunca inclua nenhuma chave além dessas três. Nunca invente um valor fora "
    "da lista de valores permitidos, mesmo que o texto de evidência sugira outra coisa. "
    "Se a evidência for genuinamente ambígua entre mais de um valor permitido, escolha o "
    "mais provável mas reporte um confidence BAIXO - nunca infle a confiança pra parecer certo."
)


def _preview(value: Optional[str], limit: int) -> Optional[str]:
    """Trunca uma string longa pra telemetria/diagnóstico (nunca pra
    lógica de validação - `parse_and_validate_response` continua sendo
    quem decide o que é aceito). `None`/string vazia viram `None`, pra
    não poluir `last_call_diagnostics` com campos vazios."""
    if not value:
        return None
    if len(value) <= limit:
        return value
    return f"{value[:limit]}...<truncado, {len(value)} chars no total>"


def _port_in_use(port: int, host: str = "127.0.0.1") -> bool:
    """Checagem BEST-EFFORT de porta ocupada - NÃO é uma trava real
    contra corrida (ver aviso de conflito com a Arena na docstring do
    módulo). Só serve para falhar rápido e com mensagem clara quando
    algo já está escutando na porta antes de tentarmos subir por cima,
    em vez de deixar o `LlamaCppDriver.start()` tentar e falhar de um
    jeito mais confuso mais adiante."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.settimeout(0.5)
        return sock.connect_ex((host, port)) == 0


class DocumentLLMWorker:
    """Context manager assíncrono que EXECUTA uma política já decidida.

    O Phoenix Execution Arbiter é a única autoridade para escolher CPU/GPU.
    Este worker recebe `mode`/`resource_policy` e apenas cumpre a decisão;
    nunca infere intenção, nunca escolhe recurso por conta própria.

    Para UMA sessão de trabalho do pipeline documental, as chamadas semânticas
    (`llm_call_fn` injetado em `resolve_taxonomy_pair`/outros
    resolvedores da Fase 8) rodam no motor CPU compartilhado (porta
    8081, sempre de pé, gerenciado pelo Kernel) ou num worker GPU
    dedicado e temporário (porta dinâmica na faixa 8095-8110). Antes de autorizar o job, o worker executa self-test de correctness; em falha, cai para CPU por padrão.

    mode="cpu" (default): não inicia nem para nenhum processo - assume
    que o motor compartilhado da Phoenix já está de pé em 8081.

    mode="gpu": em `__aenter__`, sobe uma instância SEPARADA e dedicada
    do llama-server (mesmo padrão de
    `resident_manager.py::run_dual_model_collaboration_direct`, mas
    nunca importando nem alterando esse arquivo); em `__aexit__`,
    SEMPRE derruba essa instância (mesmo em caso de exceção dentro do
    bloco `async with`), devolvendo a VRAM pra imagem/visão - a mesma
    garantia operacional que a Arena já tem hoje.

    `.call(task)` é a função que se passa como `llm_call_fn` para
    `resolve_taxonomy_pair`/`_resolve_one_level` - assinatura síncrona
    (`SemanticTask -> str`), IDÊNTICA em todos os modos. Deliberadamente
    não usa `LlamaCppDriver.execute()` internamente: faz sua própria
    chamada HTTP mínima e isolada (mesmo padrão já usado em
    `taxonomy_benchmark_run.py`/`taxonomy_resolver_smoke_test.py`) -
    o driver, aqui, serve só para SUBIR/DERRUBAR o processo GPU, nunca
    para conversar com ele.
    """

    def __init__(
        self,
        mode: Literal["cpu", "gpu"] = "cpu",
        *,
        model_hint: str = "qwen3:8b",
        model_label: str | None = None,
        system_prompt: str = _DEFAULT_SYSTEM_PROMPT,
        no_think: bool = True,
        max_tokens: int = 2000,
        timeout: float = 600.0,
        gpu_port: int | None = None,
        gpu_ngl: str = DOCUMENT_GPU_NGL,
        gpu_device: str | None = DOCUMENT_GPU_DEVICE,
        gpu_context_size: int = DOCUMENT_GPU_CONTEXT_HINT,
        gpu_tensor_overrides: dict[str, str] | None = None,
        gpu_self_test: bool = True,
        fallback_to_cpu: bool | None = None,
        resource_policy: ResourcePolicy | str | None = None,
    ) -> None:
        policy = None
        if resource_policy is not None:
            policy = resource_policy if isinstance(resource_policy, ResourcePolicy) else ResourcePolicy(str(resource_policy))
            if policy == ResourcePolicy.CPU:
                mode = "cpu"
            elif policy in {ResourcePolicy.GPU, ResourcePolicy.GPU_WITH_CPU_FALLBACK, ResourcePolicy.HYBRID, ResourcePolicy.CPU_WITH_GPU_BURST}:
                mode = "gpu"
            elif policy == ResourcePolicy.LEGACY:
                # LEGACY significa: o árbitro não reclamou a requisição; caller explícito continua mandando.
                pass
        if mode not in ("cpu", "gpu"):
            raise ValueError(f"DocumentLLMWorker: mode inválido {mode!r} (esperado 'cpu' ou 'gpu').")
        self.resource_policy = policy
        self.mode = mode  # política já escolhida pelo chamador/árbitro
        self._effective_mode = mode
        self._model_hint = model_hint
        self._model_label = (model_label or "").strip() or None
        self._effective_model_label = self._model_label
        self._system_prompt = system_prompt + (" /no_think" if no_think else "")
        self._max_tokens = max_tokens
        self._timeout = timeout
        self._gpu_port = int(gpu_port) if gpu_port is not None else None
        self._gpu_ngl = str(gpu_ngl)
        self._gpu_device = (gpu_device or "").strip() or None
        self._gpu_context_size = int(gpu_context_size)
        self._gpu_tensor_overrides = dict(DOCUMENT_GPU_TENSOR_OVERRIDES if gpu_tensor_overrides is None else gpu_tensor_overrides)
        self._gpu_self_test = bool(gpu_self_test)
        if fallback_to_cpu is None:
            self._fallback_to_cpu = bool(
                policy in {ResourcePolicy.GPU_WITH_CPU_FALLBACK, ResourcePolicy.HYBRID, ResourcePolicy.CPU_WITH_GPU_BURST}
                if policy is not None else True
            )
        else:
            # Compatibilidade: caller antigo pode continuar explícito, mas o worker não decide sozinho.
            self._fallback_to_cpu = bool(fallback_to_cpu)
        self._driver: Optional[LlamaCppDriver] = None
        self._port = DOCUMENT_CPU_PORT if mode == "cpu" else (self._gpu_port or 0)
        # Telemetria pura, indexada por field_type - nunca lida por
        # parse_and_validate_response nem por nenhuma regra de Evidence.
        # Só existe pra quem chamou este worker conseguir reportar
        # latência/tokens depois (ver document_llm_worker_smoke_test.py).
        self.last_call_diagnostics: dict = {}

    @property
    def effective_mode(self) -> str:
        return self._effective_mode

    @property
    def port(self) -> int:
        return self._port

    def _select_gpu_port(self) -> int:
        if self._gpu_port is not None:
            if _port_in_use(self._gpu_port):
                raise RuntimeError(f"porta GPU solicitada já está em uso: {self._gpu_port}")
            return self._gpu_port
        return find_free_local_port(DOCUMENT_GPU_PORT_START, DOCUMENT_GPU_PORT_END)

    def _discover_model_label(self) -> str | None:
        """Consulta /v1/models para evitar model_hint/model_label divergentes."""
        try:
            with urllib.request.urlopen(f"http://127.0.0.1:{self._port}/v1/models", timeout=3) as response:
                data = json.loads(response.read().decode("utf-8"))
            models = data.get("data") or []
            if models and isinstance(models[0], dict):
                model_id = str(models[0].get("id") or "").strip()
                if model_id:
                    return model_id
        except Exception:
            pass
        return None

    async def _fallback_cpu(self, reason: str) -> "DocumentLLMWorker":
        if self._driver is not None:
            await self._driver.stop()
            self._driver = None
        if not self._fallback_to_cpu:
            raise RuntimeError(reason)
        logger.warning("DocumentLLMWorker: GPU rejeitada (%s). Fallback CPU foi AUTORIZADO pela política recebida; usando :%s.", reason, DOCUMENT_CPU_PORT)
        self._effective_mode = "cpu_fallback"
        self._port = DOCUMENT_CPU_PORT
        self._effective_model_label = await asyncio.to_thread(self._discover_model_label) or self._model_label
        return self

    async def __aenter__(self) -> "DocumentLLMWorker":
        if self.mode == "cpu":
            self._effective_mode = "cpu"
            self._port = DOCUMENT_CPU_PORT
            self._effective_model_label = await asyncio.to_thread(self._discover_model_label) or self._model_label
            return self

        try:
            selected_port = self._select_gpu_port()
        except Exception as exc:
            return await self._fallback_cpu(f"não foi possível reservar porta de worker: {exc}")

        self._gpu_port = selected_port
        self._port = selected_port
        logger.info(
            "DocumentLLMWorker: subindo worker GPU dedicado (porta %s, ngl=%s, device=%s, context=%s, overrides=%s, modelo=%s)...",
            self._gpu_port, self._gpu_ngl, self._gpu_device or "auto", self._gpu_context_size,
            self._gpu_tensor_overrides, self._model_hint,
        )
        driver = LlamaCppDriver(
            port=self._gpu_port,
            force_ngl=self._gpu_ngl,
            device=self._gpu_device,
            tensor_overrides=self._gpu_tensor_overrides,
            context_size=self._gpu_context_size,
        )
        # Guarda a referência ANTES de start(): se o processo nascer mas o
        # healthcheck nunca ficar pronto, o fallback ainda consegue terminá-lo.
        self._driver = driver
        started_ok = await driver.start(
            ExecutionPlan(runtime="llama.cpp", model=self._model_hint, parameters={})
        )
        if not started_ok:
            return await self._fallback_cpu(
                f"falha ao iniciar worker GPU dedicado na porta {self._gpu_port}"
            )
        self._effective_model_label = driver.model_alias or await asyncio.to_thread(self._discover_model_label) or self._model_label

        if self._gpu_self_test:
            ok, detail = await driver.sanity_check(timeout=min(90.0, self._timeout))
            if not ok:
                return await self._fallback_cpu(
                    "self-test de correctness Vulkan falhou; backend não autorizado para documentos: " + detail
                )

        self._effective_mode = "gpu"
        return self

    async def __aexit__(self, exc_type, exc, tb) -> None:
        if self._driver is not None:
            logger.info(f"DocumentLLMWorker: derrubando worker GPU dedicado (porta {self._gpu_port})...")
            await self._driver.stop()
            self._driver = None

    def call(self, task: SemanticTask) -> str:
        """Assinatura EXATA que `resolve_taxonomy_pair`/`_resolve_one_level`
        esperam de `llm_call_fn`: função síncrona, recebe o `SemanticTask`
        inteiro, devolve o texto bruto da resposta (`parse_and_validate_response`
        é quem valida/interpreta esse texto - nunca este módulo)."""
        user_content = (
            f"Pergunta: {task.question}\n"
            f"Valores permitidos (allowed_values): {json.dumps(list(task.allowed_values), ensure_ascii=False)}\n"
            "Evidências disponíveis:\n" + "\n".join(f"- {s}" for s in task.evidence_snippets)
        )
        model_label = self._effective_model_label or self._discover_model_label() or self._model_label
        payload = {
            "model": model_label,
            "messages": [
                {"role": "system", "content": self._system_prompt},
                {"role": "user", "content": user_content},
            ],
            "temperature": 0.0,
            "max_tokens": self._max_tokens,
        }
        body = json.dumps(payload).encode("utf-8")
        url = f"http://127.0.0.1:{self._port}/v1/chat/completions"
        request = urllib.request.Request(url, data=body, headers={"Content-Type": "application/json"}, method="POST")
        start = time.monotonic()
        try:
            with urllib.request.urlopen(request, timeout=self._timeout) as response:
                raw = response.read().decode("utf-8")
        except (urllib.error.URLError, TimeoutError, OSError) as exc:
            raise RuntimeError(
                f"DocumentLLMWorker.call() (mode='{self.mode}', porta {self._port}, "
                f"field_type='{task.field_type}'): falha ao chamar o llama-server - {type(exc).__name__}: {exc}"
            ) from exc
        elapsed = time.monotonic() - start
        data = json.loads(raw)
        choice = data["choices"][0]
        message = choice.get("message") or {}
        text = message.get("content") or ""
        usage = data.get("usage") or {}
        # PHX-DIAG (30/08, achado real de calibração CPU-vs-GPU): em pelo
        # menos um caso real (Lipton, mode="gpu", porta 8095/8090),
        # `completion_tokens` bateu o teto de `max_tokens` (finish_reason
        # "length") mas `message["content"]" veio vazio - o parser downstream
        # (`parse_and_validate_response`, Fase 8) só reporta "resposta não é
        # JSON válido: ... char 0", sem revelar O QUE o modelo realmente
        # gerou. Isso é telemetria PURA (nunca lida por validação/Evidence,
        # só existe pra quem chamou este worker inspecionar depois - ver
        # document_llm_worker_smoke_test.py) para diferenciar hipóteses:
        # (a) o modelo ficou preso em bloco de raciocínio que o build do
        # llama-server separa em `message["reasoning_content"]` (aí
        # `content` fica vazio de propósito no protocolo, não é bug de
        # geração); (b) o modelo gerou algo em `content` mas fora do
        # formato JSON esperado; (c) resposta genuinamente vazia/quebrada.
        # Não muda nenhum comportamento existente - só adiciona campos.
        self.last_call_diagnostics[task.field_type] = {
            "port": self._port,
            "mode": self.mode,
            "effective_mode": self._effective_mode,
            "model": model_label,
            "elapsed": elapsed,
            "prompt_tokens": usage.get("prompt_tokens"),
            "completion_tokens": usage.get("completion_tokens"),
            "finish_reason": choice.get("finish_reason"),
            "content_length": len(text),
            "message_keys": sorted(message.keys()),
            "content_preview": _preview(text, 2000),
            "reasoning_content_preview": _preview(message.get("reasoning_content"), 2000),
            "raw_response_preview": _preview(raw, 4000),
        }
        return text
