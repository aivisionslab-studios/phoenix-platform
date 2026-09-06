#phoenix_kernel\intelligence\reasoning_engine.py

import json
import logging
import re
import asyncio
from phoenix_kernel.core.models import Mission, MissionStep
from phoenix_kernel.core.enums import MissionAction, MissionStatus
from phoenix_kernel.intelligence.web_search import search_web
from phoenix_kernel.intelligence.knowledge_engine import KnowledgeEngine
# PHX-FIX: Removida a dependência de rag_service que causava ModuleNotFoundError.
# Vamos instanciar o backend diretamente com proteção.
from core.domain.execution import ExecutionPlan, ExecutionStatus

logger = logging.getLogger(__name__)

# PHX-FIX (Fase 2 - Abstração de Capacidades): DEFAULT_MODEL deixou de ser
# a fonte de verdade. Continua existindo só como FALLBACK - usado quando
# o ReasoningEngine é instanciado sem model_registry (ex: testes
# isolados, uso direto fora do ResidentManager) ou quando o catálogo não
# cobre a role "reasoning" por algum motivo. Em uso normal (via
# ResidentManager), quem decide o modelo é
# self.model_registry.resolve("reasoning") - ver plan_mission() abaixo.
DEFAULT_MODEL = "qwen3:8b"

# PHX-NEW (auditoria 2026-08-20, "Resident Research + llama.cpp JSON
# hardening"): quantas vezes plan_mission() tenta de novo, com um reprompt
# mais estrito, antes de desistir de gerar uma missão a partir de uma
# resposta que não deu pra ler como JSON. 1 retry (2 tentativas no total) -
# suficiente pro caso comum (modelo local esqueceu o formato uma vez sob
# temperatura>0) sem deixar uma falha de verdade do LLM virar um loop longo
# numa rota que já é lenta (busca web + RAG + inferência).
_JSON_RETRY_ATTEMPTS = 2


def _extract_balanced_braces(text: str) -> str | None:
    """Acha a primeira substring '{...}' com chaves balanceadas, andando
    caractere a caractere e ignorando chaves que aparecem DENTRO de uma
    string JSON (ex: um "reasoning" cujo texto contenha um '{' literal não
    pode fechar o objeto antes da hora). Devolve None se não achar um '{'
    ou se as chaves nunca fecharem."""
    start = text.find("{")
    if start == -1:
        return None
    depth = 0
    in_string = False
    escape = False
    for i in range(start, len(text)):
        ch = text[i]
        if in_string:
            if escape:
                escape = False
            elif ch == "\\":
                escape = True
            elif ch == '"':
                in_string = False
            continue
        if ch == '"':
            in_string = True
        elif ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                return text[start:i + 1]
    return None


_JSON_FENCE_RE = re.compile(r"```(?:json)?\s*(\{.*?\})\s*```", re.DOTALL | re.IGNORECASE)

# PHX-FIX (achado do usuário 2026-08-28: fill_spreadsheet_template_direct
# devolvendo "modelo não devolveu um JSON válido... mesmo após 2
# tentativas" com qwen3-8b): modelos "de raciocínio" (thinking) como o
# Qwen3 costumam produzir um bloco <think>...</think> ANTES da resposta
# final. O llama-server às vezes já separa isso em "reasoning_content"
# (ver LlamaCppDriver.execute()), mas quando não separa (build antigo, ou
# o parser dele não reconhece o fechamento), o bloco de pensamento inteiro
# vem junto em "content" - e se esse raciocínio mencionar chaves '{' (ex:
# o modelo "pensando em voz alta" sobre como o JSON deveria ficar),
# _extract_balanced_braces() pode pegar um trecho de DENTRO do
# raciocínio em vez da resposta final de verdade. Removido ANTES de
# qualquer tentativa de parse - mesma técnica já usada em 2 lugares de
# AviaryApp.tsx pra limpar a exibição no chat.
_THINK_BLOCK_RE = re.compile(r"<think>.*?</think>", re.DOTALL | re.IGNORECASE)


def _strip_think_block(text: str) -> str:
    return _THINK_BLOCK_RE.sub("", text).strip()


def _extract_json_object(text: str) -> dict | None:
    """Tenta ler um objeto JSON de `text`, tolerando os formatos mais
    comuns que um LLM local produz mesmo com instrução explícita de
    "responda só com JSON" (a mesma limitação que motivou esta auditoria):
      1. JSON puro, sem nada em volta (caso ideal).
      2. JSON dentro de uma cerca de código markdown (```json ... ``` ou
         ``` ... ```), comum quando o modelo trata a pergunta como "me dê
         um bloco de código".
      3. JSON com texto de preâmbulo e/ou posfácio ("Claro, aqui está o
         plano: {...} Espero que ajude!") - extraído via bracket-matching
         ciente de strings, não regex ganancioso.

    Devolve o dict só se alguma tentativa produzir JSON válido E o
    resultado for de fato um objeto (dict) - uma lista ou escalar JSON
    válido não conta, já que o contrato de plan_mission() espera um objeto
    com "reasoning"/"steps"/"response". Nunca levanta exceção, nunca
    inventa ou completa um dict parcial - na dúvida, devolve None e quem
    chama decide (retry ou falha limpa)."""
    if not text or not text.strip():
        return None

    stripped = _strip_think_block(text.strip()) or text.strip()
    candidates = [stripped]

    fence_match = _JSON_FENCE_RE.search(stripped)
    if fence_match:
        candidates.append(fence_match.group(1).strip())

    balanced = _extract_balanced_braces(stripped)
    if balanced:
        candidates.append(balanced)

    for candidate in candidates:
        try:
            parsed = json.loads(candidate)
        except (json.JSONDecodeError, TypeError, ValueError):
            continue
        if isinstance(parsed, dict):
            return parsed
    return None

# O System Prompt agora é mais limpo. A identidade e as regras de hardware
# vêm do KnowledgeEngine (intrinsic/phoenix_identity.md).
SYSTEM_PROMPT = """Você é o Phoenix OS, o cérebro orquestrador de uma plataforma de IA local.
Sua função é analisar o pedido do usuário e o contexto fornecido, e criar um PLANO DE AÇÃO (Mission).
Você NÃO executa comandos. Você apenas desenha o plano em formato JSON.

Ferramentas (Actions) que você pode usar:
- VALIDATE_ENVIRONMENT: Checar se um software (target) está pronto (ex: target="docker").
- INSTALL_PACKAGE: Instalar um PACOTE DE SOFTWARE externo (ex: target="comfyui"). Phoenix Diffusion já vem incluído e nunca deve ser clonado.
- DOWNLOAD_MODEL: Baixar um ARQUIVO .gguf de um modelo de IA (target="qwen3:8b", target="flux").
- SWITCH_RUNTIME: Garantir que o motor de inferência de TEXTO nativo está ativo (target="llama.cpp" - único runtime de texto desta Phoenix).
- LOAD_MODEL: Trocar o MODELO de texto carregado no motor llama.cpp, mantendo o mesmo runtime (target=nome do modelo, ex: "qwen2.5-coder:32b" para código, "deepseek-r1:8b" para raciocínio complexo). Use quando a tarefa pedida claramente se beneficia de um modelo diferente do que está ativo. NÃO troque de modelo pra conversas simples.
- UNLOAD_MODEL: Descarregar o modelo de texto atual (target="llama.cpp"), liberando RAM.
- GENERATE_IMAGE: Rodar a inferência de um modelo de IMAGEM já baixado (target=id do modelo no catálogo, ex: "flux", "sdxl", "sd15"; parameters={"prompt": "..."}).

REGRA CRÍTICA DE GERAÇÃO DE IMAGEM:
- DOWNLOAD_MODEL sozinho NUNCA gera uma imagem. Se o usuário quer VER/CRIAR uma imagem, o plano PRECISA terminar com um passo GENERATE_IMAGE.
- Sequência correta para pedidos de imagem: VALIDATE_ENVIRONMENT(phoenix_diffusion) -> DOWNLOAD_MODEL(flux) -> GENERATE_IMAGE(mesmo target, com prompt em parameters).

REGRA CRÍTICA DE AÇÕES (NUNCA CONFUNDA):
- INSTALL_PACKAGE é apenas para instalar SOFTWARE externo. Nunca use esta ação para Phoenix Diffusion.
- DOWNLOAD_MODEL é apenas para baixar ARQUIVOS .gguf de modelos de IA.
- NUNCA use DOWNLOAD_MODEL para baixar software.
- O llama.cpp É O ÚNICO RUNTIME DE TEXTO DA PHOENIX. NUNCA sugira INSTALL_PACKAGE para "llama.cpp".
- NUNCA sugira "ollama" como target de nenhuma action.

REGRA DE HARDWARE CRÍTICA:
- Se a GPU for AMD (como RX 580 / Polaris) e o backend for Vulkan, NUNCA sugira ComfyUI, AUTOMATIC1111 ou Forge.
- Para geração de imagens em AMD Legacy, SEMPRE use Phoenix Diffusion pelo runtime "sdxl" (alias compatível da bridge nativa).

Regras Gerais:
1. Seja eficiente. Não instale o que já está instalado.
2. Responda SEMPRE com um JSON válido contendo "reasoning" e "steps".

Exemplo de Resposta (texto):
{
  "reasoning": "O usuário quer rodar IA local. A máquina tem GPU. O llama.cpp já está pronto, só falta baixar o modelo.",
  "steps": [
    {"action": "VALIDATE_ENVIRONMENT", "target": "docker", "description": "Checar se o Docker está ativo"},
    {"action": "DOWNLOAD_MODEL", "target": "qwen3:8b", "description": "Baixar o modelo Qwen 3 8B"}
  ]
}

Exemplo de Resposta (conversa direta):
Se a intenção do usuário for só uma pergunta ou conversa, devolva "steps" vazio e preencha "response":
{
  "reasoning": "Usuário só quer conversar.",
  "steps": [],
  "response": "Oi! Sou o Resident da Phoenix Engine. Como posso ajudar?"
}
"""


class ReasoningEngine:
    def __init__(self, state_engine=None, runtime_engine=None, logs_engine=None, model_registry=None):
        self.state = state_engine
        self.runtime = runtime_engine
        self.logs = logs_engine
        self.model_registry = model_registry
        self.last_error: str | None = None
        self.last_response: str | None = None
        # PHX-NEW (destravar Ollama como 2ª opção de engine de texto):
        # hint pro ModelRegistry.resolve() em plan_mission() abaixo - ""
        # (default) resolve pro llama.cpp nativo, "ollama" resolve pro
        # mesmo modelo servido via Docker/Ollama. ResidentManager (dono
        # desta instância) escreve aqui direto em
        # set_text_engine_preference() - não existe setter próprio porque
        # os dois já vivem no mesmo processo/arquivo de decisão.
        self.text_engine_hint: str = ""
        
        # PHX-FIX: Instancia o ChromaRagBackend diretamente com proteção.
        # Se o banco de dados estiver corrompido (ex: mismatch de 768 vs 384 dims),
        # ele retorna None em vez de derrubar a API inteira.
        # PHX-FIX (auditoria 2026-08-09): usa get_shared_chroma_backend() em
        # vez de instanciar ChromaRagBackend direto - PlannerEngine aponta
        # pro mesmo data/chroma_db, e dois clientes persistentes separados
        # no mesmo path dentro do processo arriscam corromper o índice HNSW
        # (mesma classe de problema que já forçou isolar os testes de boot
        # em diretório temporário).
        _rag_backend = None
        try:
            from phoenix_kernel.intelligence.chroma_rag_backend import get_shared_chroma_backend
            _rag_backend = get_shared_chroma_backend(persist_dir="data/chroma_db")
        except Exception as e:
            logger.warning(f"ReasoningEngine: RAG backend indisponível ({e}). Seguindo sem RAG.")

        self.knowledge = KnowledgeEngine(
            knowledge_root="phoenix_kernel/knowledge",
            rag_root="phoenix_kernel/rag/source_docs",
            rag_backend=_rag_backend,
        )

    def _log(self, level: str, msg: str) -> None:
        getattr(logger, level.lower(), logger.info)(f"[Reasoning] {msg}")
        if self.logs:
            try:
                self.logs.add_event(level.upper(), "ReasoningEngine", msg)
            except Exception as e:
                # PHX-FIX (varredura 2026-08-21 rodada 2, achado #6): a
                # falha ao gravar no painel de logs desaparecia por
                # completo - o logger.info/error acima ainda registra o
                # evento real, mas um "sumiço" no painel de logs (ex: disco
                # cheio, LogsEngine quebrado) ficava sem nenhum rastro.
                logger.debug(f"ReasoningEngine._log: falha ao gravar evento no LogsEngine: {e}")

    def _get_hardware_context(self) -> str:
        if not self.state:
            return "Hardware info indisponível."
        try:
            hw = self.state.get_state_sync().get("hardware", {})
            budget = self.state.get_state_sync().get("budget", {})
            return f"CPU: {hw.get('cpu', 'Unknown')}, RAM: {hw.get('ram_mb', 0)}MB, GPU: {hw.get('gpu', 'None')} ({hw.get('vram_mb', 0)}MB VRAM), Classe: {budget.get('class', 'Unknown')}"
        except Exception:
            return "Hardware em inicialização."

    async def plan_mission(self, user_intent: str):
        self._log("INFO", f"Pensando sobre: '{user_intent}'...")
        hw_context = self._get_hardware_context()

        # 1. Busca contexto na internet
        self._log("INFO", "Buscando contexto na internet...")
        web_context = await search_web(user_intent, max_results=2)

        # 2. Busca no KnowledgeEngine (Intrinsic + Machine + Procedures + RAG)
        # PHX-FIX: Proteção total para não travar a API se o RAG falhar.
        self._log("INFO", "Consultando a base de conhecimento (RAG)...")
        knowledge_context = ""
        try:
            loop = asyncio.get_running_loop()
            knowledge_context = await loop.run_in_executor(None, self.knowledge.build_context, user_intent)
        except Exception as e:
            self._log("WARNING", f"Falha ao consultar conhecimento (ignorado): {e}")

        # 3. Monta o prompt final com todas as fontes
        user_prompt = (
            f"Contexto da Máquina:\n{hw_context}\n\n"
            f"Contexto de Conhecimento (Identidade, Hardware, Receitas):\n{knowledge_context}\n\n"
            f"Contexto da Internet (use se for útil):\n{web_context}\n\n"
            f"Intenção do Usuário: {user_intent}"
        )

        if not self.runtime:
            self.last_error = "RuntimeEngine não injetado no ResidentManager."
            self._log("ERROR", self.last_error)
            return None

        # PHX-NEW (Fase 2): resolve o modelo de raciocínio pela capacidade
        # "reasoning" no catálogo, em vez do DEFAULT_MODEL fixo. Se o
        # registry não foi injetado (ex: uso isolado do ReasoningEngine
        # fora do ResidentManager) ou não resolveu nada, cai pro
        # DEFAULT_MODEL como rede de segurança - nunca quebra o plano por
        # falta de catálogo.
        resolved = self.model_registry.resolve("reasoning", hint=self.text_engine_hint) if self.model_registry else None
        plan_model = resolved.id if resolved else DEFAULT_MODEL
        plan_runtime = resolved.runtime if resolved else "llama.cpp"

        # PHX-FIX (auditoria 2026-08-20, "Resident Research + llama.cpp JSON
        # hardening"): antes, esta função montava UM ExecutionPlan e fazia
        # `json.loads(content)` direto no texto bruto - qualquer desvio do
        # formato ideal (cerca ```json```, uma frase antes do JSON, etc.,
        # todos comuns em modelos locais mesmo com a instrução explícita no
        # SYSTEM_PROMPT) derrubava a missão inteira sem segunda chance,
        # mesmo quando o próprio LlamaCppDriver/OllamaDriver já tinham
        # blindagem nativa aplicada (ver `response_format`/`format` nos
        # drivers). Agora: (1) o LLM_plan pede json_format=True, que os dois
        # drivers já traduzem pra blindagem nativa do backend; (2) a
        # resposta passa por `_extract_json_object()` (tolera cerca
        # markdown e texto de preâmbulo/posfácio); (3) se isso falhar,
        # tenta de novo com um reprompt que nomeia o erro, até
        # `_JSON_RETRY_ATTEMPTS` vezes; (4) se ainda assim falhar, NENHUMA
        # missão é registrada - `last_error` é setado e a função devolve
        # None, exatamente como antes no caso de falha total.
        plan: dict | None = None
        last_raw_content = ""

        try:
            for attempt in range(1, _JSON_RETRY_ATTEMPTS + 1):
                if attempt == 1:
                    current_plan = ExecutionPlan(
                        runtime=plan_runtime,
                        model=plan_model,
                        parameters={
                            "system_prompt": SYSTEM_PROMPT,
                            "user_prompt": user_prompt,
                            "json_format": True
                        },
                        reasoning="Gerar plano de missão em JSON"
                    )
                    attempt_label = ""
                else:
                    current_plan = ExecutionPlan(
                        runtime=plan_runtime,
                        model=plan_model,
                        parameters={
                            "system_prompt": SYSTEM_PROMPT,
                            "user_prompt": (
                                f"{user_prompt}\n\n"
                                "ATENÇÃO: sua resposta anterior não pôde ser lida como JSON "
                                f"(início do que você respondeu: {last_raw_content[:300]!r}). "
                                "Responda OBRIGATORIAMENTE com um único objeto JSON válido, "
                                "sem nenhum texto antes ou depois, sem bloco de código "
                                "markdown (sem ```)."
                            ),
                            "json_format": True
                        },
                        reasoning="Gerar plano de missão em JSON (retry após resposta não-JSON)"
                    )
                    attempt_label = f" [tentativa {attempt}/{_JSON_RETRY_ATTEMPTS}]"

                self._log("INFO", f"Consultando o cérebro nativo ({current_plan.model} via {current_plan.runtime}){attempt_label}...")
                loop_start = loop.time()
                result = await self.runtime.execute(current_plan)
                elapsed = loop.time() - loop_start

                if result.status != ExecutionStatus.SUCCESS:
                    self.last_error = "; ".join(result.errors) if result.errors else "erro desconhecido"
                    self._log("ERROR", f"Runtime falhou ao gerar plano ({elapsed:.1f}s): {self.last_error}")
                    return None  # falha de runtime (rede/processo) não é a mesma classe de erro que resposta não-JSON - não retenta aqui

                self._log("INFO", f"Resposta do cérebro recebida em {elapsed:.1f}s.")
                last_raw_content = result.output or ""
                logger.info(f"[Reasoning] Resposta bruta do LLM{attempt_label}: {last_raw_content}")

                plan = _extract_json_object(last_raw_content)
                if plan is not None:
                    break

                self._log(
                    "WARNING",
                    f"Tentativa {attempt}/{_JSON_RETRY_ATTEMPTS}: resposta não é JSON válido "
                    "(nem puro, nem em cerca markdown, nem via extração de chaves balanceadas)."
                )

            if plan is None:
                self.last_error = (
                    f"Resposta do LLM não é um JSON válido, mesmo após {_JSON_RETRY_ATTEMPTS} "
                    "tentativa(s). Nenhuma missão foi registrada."
                )
                self._log("ERROR", self.last_error)
                return None

            reasoning = plan.get("reasoning", "Sem explicação.")
            raw_steps = plan.get("steps", [])
            direct_response = (plan.get("response") or "").strip()

            if not raw_steps:
                if direct_response:
                    self.last_response = direct_response
                    self._log("INFO", f"Resposta direta gerada (sem missão): \"{direct_response[:80]}\"")
                    return None

                self.last_error = "JSON válido, mas sem 'steps' nem 'response'."
                self._log("ERROR", self.last_error)
                return None

            self.last_response = None

            steps = []
            for i, s in enumerate(raw_steps, 1):
                action_str = s.get("action", "VALIDATE_ENVIRONMENT").upper()
                try:
                    action_enum = MissionAction(action_str)
                except ValueError:
                    logger.warning(f"[Reasoning] Ação '{action_str}' inválida. Usando VALIDATE_ENVIRONMENT.")
                    action_enum = MissionAction.VALIDATE_ENVIRONMENT

                steps.append(MissionStep(
                    step=i,
                    action=action_enum,
                    target=s.get("target", "unknown"),
                    description=s.get("description", ""),
                    parameters=s.get("parameters", {}) or {},
                ))

            mission = Mission(
                intent=user_intent,
                status=MissionStatus.CREATED,
                steps=steps,
                metadata={"llm_reasoning": reasoning}
            )
            self._log("INFO", f"Missão criada com {len(steps)} passo(s).")
            return mission

        except Exception as e:
            # PHX-FIX (mesma auditoria): removido o `except json.JSONDecodeError`
            # que existia aqui antes - ficou morto depois desta mudança, já
            # que `_extract_json_object()` nunca deixa um JSONDecodeError
            # escapar (ela mesma captura e devolve None). Qualquer erro
            # inesperado (rede, atributo, o que for) cai aqui, igual antes.
            self.last_error = f"{type(e).__name__}: {str(e)}"
            self._log("ERROR", f"Falha inesperada: {self.last_error}")
            return None
