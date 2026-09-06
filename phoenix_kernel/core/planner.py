import logging
from .models import Mission, MissionStep
from .enums import MissionAction

logger = logging.getLogger(__name__)

class MissionPlanner:
    def _step(self, action: MissionAction, target: str, description: str, **parameters) -> dict:
        return {"action": action, "target": target, "description": description, "parameters": parameters}

    def create(self, intent: str) -> Mission:
        logger.info(f"MissionPlanner: Criando missão para '{intent}'")
        # PHX-FIX (auditoria 2026-08-20, "Golden Baseline"): esta classe NÃO
        # é o planejador real de missões usado em runtime (esse é
        # ReasoningEngine.plan_mission(), acionado via ResidentManager/
        # RuleEvaluator - ver phoenix_kernel/intelligence/reasoning_engine.py)
        # - só é referenciada por tests/test_mission_kernel.py, confirmado
        # por busca de import em toda a árvore. Antes de mexer, era um
        # exemplo exato do padrão de regressão que a Seção 1 pede pra caçar:
        # QUALQUER intent contendo a palavra "chat" (sem menção nenhuma a
        # "ollama") caía direto no branch que instala o Ollama via Docker -
        # ou seja, "chat" == Ollama por default, com llama.cpp nem cogitado.
        # Corrigido pra só instalar Ollama quando o usuário pede Ollama
        # explicitamente; um intent genérico de "chat" agora cai no branch
        # padrão (validar ambiente) - llama.cpp continua sendo o motor de
        # texto assumido, sem precisar de um passo de instalação aqui.
        raw_steps = []
        if "ollama" in intent.lower():
            raw_steps.append(self._step(MissionAction.INSTALL_PACKAGE, "ollama", "Subir container do Ollama", provider="docker"))
        elif "image" in intent.lower() or "comfyui" in intent.lower():
            raw_steps.append(self._step(MissionAction.INSTALL_PACKAGE, "comfyui", "Clonar repositório do ComfyUI", provider="git"))
        else:
            raw_steps.append(self._step(MissionAction.VALIDATE, "environment", "Validar ambiente"))
            
        steps = [MissionStep(step=i + 1, action=s["action"], target=s["target"], description=s["description"], parameters=s.get("parameters", {})) for i, s in enumerate(raw_steps)]
        return Mission(intent=intent, steps=steps)
