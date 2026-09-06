from __future__ import annotations
import logging
import re
from core.domain.machine import MachineContext
from core.domain.execution import ExecutionPlan

logger = logging.getLogger(__name__)

SYSTEM_PROMPT = (
    "Você é a Phoenix, o motor de orquestração de IA da AIVisions Platform 3.0 — "
    "um projeto de 'Hardware Revival': provar que GPUs e CPUs consideradas "
    "obsoletas pelo mercado (como a RX 580, um Xeon de servidor antigo) ainda "
    "têm gás pra rodar IA moderna, sem CUDA, sem ROCm, só com Vulkan e "
    "engenharia teimosa. Você fala como alguém que genuinamente curte esse "
    "tipo de desafio — entusiasmado com hardware velho fazendo coisa grande, "
    "com senso de humor seco de quem já apanhou de driver quebrado às 3 da "
    "manhã e sobreviveu. Pode brincar, fazer graça, soltar uma piada sobre "
    "o barulho do cooler ou sobre placas de vídeo 'aposentadas' que ainda "
    "trabalham mais que muita GPU nova.\n\n"
    "Mas ATENÇÃO — isso nunca pode custar precisão técnica:\n"
    "- Nunca invente números de hardware (VRAM, tokens/s, temperatura). Se não tiver a informação exata no contexto abaixo, diga abertamente 'não tenho esse dado exato aqui'.\n"
    "- Nunca invente funcionalidades, telas, botões ou comandos da AIVisions Platform que não estejam descritos no contexto.\n"
    "- Se o contexto do projeto abaixo não for relevante para a pergunta, ignore-o e responda com seu conhecimento geral, deixando claro que é conhecimento geral.\n"
    "- Precisão técnica sempre vem antes de graça. Divirta-se com o tom, nunca com o fato."
)

class RuleEvaluator:
    def __init__(self, knowledge_engine, model_registry=None):
        self._knowledge = knowledge_engine
        # PHX-FIX (destravar Ollama como 2ª opção de engine de texto):
        # antes `runtime`/`model_name` eram literais fixos
        # ("llama.cpp"/"qwen3:8b") direto no corpo de evaluate() - nunca
        # passavam pelo ModelRegistry (a "Fase 2 - Abstração de
        # Capacidades" que o resto do projeto já usa), então o comando
        # `infer` nunca respeitava nem o default_for_roles do catálogo
        # nem uma preferência de engine trocada pelo usuário. Injetável
        # (mesmo padrão do knowledge_engine acima) pra facilitar teste com
        # um catálogo fake; None é um estado válido (cai pro literal fixo
        # como rede de segurança, nunca quebra o /infer por falta de
        # catálogo).
        self._registry = model_registry

    async def evaluate(self, context: MachineContext, user_prompt: str = "", model_hint: str = "") -> ExecutionPlan:
        if not context.profile:
            return ExecutionPlan(strategy='fallback', reasoning='No hardware profile.')

        gpus = context.profile.gpus
        has_gpu = len(gpus) > 0
        vram_mb = gpus[0].get('vram_mb', 0) if has_gpu else 0
        backends = context.profile.available_backends

        # Verifica se a GPU tem VRAM suficiente (4GB+) e suporta Vulkan
        gpu_capable_for_llamacpp = has_gpu and vram_mb >= 4000 and 'vulkan' in backends

        # PHX-FIX: resolve pela capacidade "chat" no catálogo em vez de
        # literal fixo. `model_hint` normalmente vem da preferência salva
        # em ResidentManager.get_text_engine_preference() ("" = default
        # declarado no catálogo = llama.cpp; "ollama" = segunda opção via
        # Docker, porta 11434 - ver catalog/models.json).
        resolved = self._registry.resolve("chat", hint=model_hint) if self._registry else None
        runtime = resolved.runtime if resolved else "llama.cpp"
        model_name = resolved.id if resolved else "qwen3:8b"  # rede de segurança sem catálogo

        query = user_prompt if user_prompt else "identidade e propósito da AIVisions Platform"
        
        try:
            # PHX-FIX (auditoria 2026-08-04): query_knowledge() é síncrono
            # (list[str] de chunks de texto do RAG) — o "await" aqui sempre
            # levantava TypeError ("object list can't be used in 'await'
            # expression"), caía direto no except, e o RAG nunca era
            # realmente consultado. O `recommendation.get(...)` logo abaixo
            # também presumia um dict que o RAG nunca retornou.
            rag_hits = self._knowledge.query_knowledge(query)
        except Exception as e:
            logger.warning(f"RuleEvaluator: Falha ao consultar RAG ({e}), usando prompt padrão.")
            rag_hits = []

        context_text = ""
        if rag_hits:
            context_text = "\n\n".join(f"- {hit}" for hit in rag_hits)

            # Tenta extrair o nome de um modelo .gguf mencionado nos trechos
            # de RAG retornados (ex: benchmarks/procedures que citam o
            # comando usado), se houver. Só se aplica ao llama.cpp - um
            # nome de arquivo .gguf não significa nada pro Ollama, que
            # identifica modelo por tag (ex: "qwen3:8b"), não por caminho
            # de arquivo.
            if runtime != "ollama":
                model_match = re.search(r'-m\s+([^\s]+\.gguf)', context_text)
                if model_match:
                    model_name = model_match.group(1)

            logger.info("RuleEvaluator: Contexto RAG injetado no prompt com sucesso.")

        final_prompt = f"{SYSTEM_PROMPT}\n\n"
        if context_text:
            final_prompt += f"Contexto do Projeto (use apenas se for estritamente relevante para a pergunta):\n{context_text}\n\n"
        final_prompt += f"Pergunta do Usuário: {user_prompt}"

        parameters = {'prompt': final_prompt, 'max_tokens': 300}

        # PHX-NEW (destravar Ollama como 2ª opção): se a preferência do
        # usuário resolveu pra "ollama", nem entra na decisão
        # Vulkan/CPU do llama.cpp abaixo - Ollama gerencia o próprio
        # backend (CPU/GPU) internamente, o Phoenix não escolhe isso.
        if runtime == "ollama":
            logger.info(f"RuleEvaluator: Executando via Ollama (Docker, porta 11434) com modelo {model_name}.")
            return ExecutionPlan(
                runtime='ollama',
                backend='ollama_docker',
                model=model_name,
                strategy='ollama_docker',
                parameters=parameters,
                confidence=0.7,
                reasoning="Engine de texto trocado pelo usuário para Ollama (Docker) - mais lento que o llama.cpp nativo, usado como segunda opção."
            )

        # Decide a estratégia (Vulkan/GPU ou CPU fallback) baseado no hardware
        if gpu_capable_for_llamacpp:
            logger.info(f"RuleEvaluator: Executando via llama.cpp (Vulkan/GPU) com modelo {model_name}.")
            return ExecutionPlan(
                runtime='llama.cpp', 
                backend='vulkan', 
                model=model_name, 
                strategy='gpu_vulkan',
                parameters=parameters, 
                confidence=0.99, 
                reasoning="Hardware suporta Vulkan e VRAM é suficiente."
            )
        else:
            logger.info(f"RuleEvaluator: Executando via llama.cpp (CPU) com modelo {model_name}.")
            return ExecutionPlan(
                runtime='llama.cpp', 
                backend='cpu', 
                model=model_name, 
                strategy='cpu_inference',
                parameters=parameters, 
                confidence=0.8, 
                reasoning="Fallback para CPU por falta de VRAM/Vulkan adequados."
            )