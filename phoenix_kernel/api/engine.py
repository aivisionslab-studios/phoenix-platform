import logging
from .interfaces import IApiService

logger = logging.getLogger(__name__)

class ApiEngine(IApiService):
    def __init__(self, state_engine, models_engine, planner_engine, runtime_engine, services_engine, logs_engine, validation_engine, security_engine, resident_manager, ocr_engine=None):
        self.state = state_engine
        self.models = models_engine
        self.planner = planner_engine
        self.runtime = runtime_engine
        self.services = services_engine
        self.logs = logs_engine
        self.validation = validation_engine
        self.security = security_engine
        self.resident = resident_manager
        self.ocr = ocr_engine
        self.machine_context = None

    def set_context(self, machine_context):
        self.machine_context = machine_context

    async def process_command(self, cmd: str) -> dict:
        if not cmd: return {"output": "Comando vazio."}

        cmd_lower = cmd.lower()

        if cmd_lower == "help":
            return {"output": "Comandos disponíveis:\n- help\n- status\n- report\n- license\n- ports\n- vulkan\n- aviary\n- rag\n- models\n- search [query]\n- ocr [caminho da imagem]\n- infer [pergunta]\n- install list\n- install service [nome]\n- install package [nome]\n- logs\n- validate\n- security\n- manager analyze\n- resident research [intencao]\n- resident approve\n- resident reject"}

        if cmd_lower in {"report", "ports", "vulkan", "aviary", "rag"}:
            state = await self.state.get_state()
            if "error" in state:
                return {"output": f"[INDISPONÍVEL] {state['error']}"}
            if cmd_lower == "ports":
                return {"output": "Porta 8000: Phoenix Engine respondeu a este comando.\nPorta 3000: Phoenix Aviary Platform (estado verificado pelo próprio processo Node)."}
            if cmd_lower == "vulkan":
                detected = (state.get("environment") or {}).get("vulkan") is True
                return {"output": f"Vulkan runtime: {'detectado' if detected else 'não detectado'} pelo Engine."}
            if cmd_lower == "aviary":
                return {"output": "Phoenix Aviary Platform: interface e proxy na porta 3000; consulte 'ports' para a topologia."}
            if cmd_lower == "rag":
                from phoenix_kernel.licensing.plans import get_rag_limits
                limits = get_rag_limits()
                maximum = limits.get("max_documents")
                maximum_label = "sem limite numérico" if maximum is None else str(maximum)
                return {"output": f"RAG: {state.get('rag_docs', 0)} documento(s) lógico(s).\nPlano: {limits.get('plan', 'free')} | Limite: {maximum_label}."}
            hardware = state.get("hardware") or {}
            return {"output": (
                "Phoenix Engine 4.5 — relatório atual\n"
                f"CPU: {hardware.get('cpu', 'não informado')}\n"
                f"GPU: {hardware.get('gpu', 'não informado')}\n"
                f"RAM: {hardware.get('ram_mb', 0)} MB | VRAM: {hardware.get('vram_mb', 0)} MB\n"
                f"Backends: {', '.join(hardware.get('backends') or []) or 'nenhum informado'}\n"
                f"RAG: {state.get('rag_docs', 0)} documento(s) lógico(s)"
            )}

        if cmd_lower == "license":
            return {"output": "Phoenix Engine: CC BY-NC 4.0. Componentes de terceiros mantêm suas próprias licenças e avisos; consulte LICENSE.md."}
        
        if cmd_lower == "manager analyze":
            self.logs.add_event("INFO", "API", "Resident Manager solicitado para análise.")
            report = await self.resident.analyze_machine()
            return {"output": report}

        # --- REASONING ENGINE ROUTING ---
        if cmd_lower.startswith("resident research "):
            intent = cmd[18:].strip() # Extrai o texto após "resident research "
            self.logs.add_event("INFO", "API", f"Reasoning Engine solicitado para: {intent}")
            result = await self.resident.process_intent(intent)
            return result
            
        if cmd_lower == "resident approve":
            self.logs.add_event("INFO", "API", "Missão aprovada pelo usuário.")
            result = await self.resident.approve_and_execute()
            return result
            
        if cmd_lower == "resident reject":
            self.logs.add_event("INFO", "API", "Missão rejeitada pelo usuário.")
            try:
                self.resident._mission_kernel.reject_active_mission()
            except Exception:
                pass  # ja nao havia missao pendente
            self.resident._active_mission = None
            return {"output": "Missão rejeitada e descartada."}

        # --- WEB SEARCH ROUTING ---
        if cmd_lower.startswith("search "):
            query = cmd[7:].strip()
            self.logs.add_event("INFO", "API", f"Buscando na web: {query}")
            from phoenix_kernel.intelligence.web_search import search_web
            results = await search_web(query)
            return {"output": f"🌐 Resultados da web para '{query}':\n\n{results}"}

        # --- OCR ROUTING (Tesseract nativo - le imagens coladas/anexadas) ---
        if cmd_lower.startswith("ocr "):
            image_path = cmd[4:].strip()
            if not self.ocr:
                return {"output": "[Erro: Motor de OCR não inicializado no Kernel.]"}
            if not image_path:
                return {"output": "Uso: ocr [caminho da imagem]"}
            self.logs.add_event("INFO", "API", f"OCR solicitado para: {image_path}")
            extracted_text = await self.ocr.extract_text(image_path)
            return {"output": extracted_text}

        if cmd_lower == "status":
            state = await self.state.get_state()
            if "error" in state: return {"output": "Aguardando descoberta de hardware..."}
            t = state['telemetry']
            return {"output": f"CPU: {t['cpu_usage']}% | RAM: {t['ram_used_mb']}MB\nGPU: {state['hardware']['gpu']} | Temp: {t['gpu_temp']}°C"}

        if cmd_lower == "models":
            models_data = await self.models.get_model_and_rag_status()
            return {"output": "Modelos Ollama disponíveis:\n" + "\n".join(models_data.get("models", []))}

        if cmd_lower.startswith("install "):
            args = cmd[8:].strip().split(" ", 1)
            if not args[0]: return {"output": "Uso: install list\n- install service [nome]\n- install package [nome]"}
            action = args[0].lower()
            if action == "list":
                self.logs.add_event("INFO", "API", "Listando pacotes.")
                return {"output": "AIVisions Packages Catalog:\n" + self.services.packages.list_packages()}
            if len(args) < 2: return {"output": "Uso: install service [nome] ou install package [nome]"}
            target = args[1].lower()
            if action == "service":
                return {"output": await self.services.install_service(target)}
            elif action == "package":
                return {"output": await self.services.install_package(target)}
            else: return {"output": "Ação inválida."}

        if cmd_lower == "logs":
            logs = self.logs.get_recent_logs(10)
            if not logs: return {"output": "Nenhum log."}
            return {"output": "\n".join([f"[{l['timestamp']}] [{l['source']}] {l['message']}" for l in logs])}

        if cmd_lower == "validate":
            val_data = await self.validation.validate_system()
            return {"output": f"Validation Status: {val_data.get('status')}\nDetails: {val_data.get('checks')}"}

        if cmd_lower == "security":
            sec_data = await self.security.check_integrity()
            return {"output": f"Security Check:\n- Admin: {sec_data.get('is_admin')}\n- Firewall: {sec_data.get('firewall_status')}"}

        if cmd_lower.startswith("infer "):
            prompt = cmd[6:]
            try:
                # PHX-NEW (destravar Ollama como 2ª opção de engine de
                # texto): antes `infer` nunca consultava a preferência do
                # usuário (nem existia uma) - sempre resolvia pro literal
                # fixo dentro do RuleEvaluator. "" = default do catálogo
                # (llama.cpp); só manda hint="ollama" explicitamente
                # quando o usuário trocou a engine em
                # /api/engine/text-runtime.
                pref = self.resident.get_text_engine_preference() if self.resident else {"engine": "llama.cpp"}
                hint = "" if pref.get("engine") == "llama.cpp" else pref.get("engine", "")
                plan = await self.planner.plan_inference(self.machine_context, user_prompt=prompt, model_hint=hint)
                # PHX-FIX (auditoria 2026-08-20, "ResidentManager não pode
                # ser contornado" - Seção 3): antes, `self.runtime.execute(plan)`
                # era chamado direto aqui - `self.runtime` é o RuntimeEngine
                # cru injetado no ApiEngine, pulando o ResidentManager por
                # completo (sem _thermal_guard, sem _track_model_loaded).
                # Agora passa por resident.run_inference_direct(plan), que
                # aplica as mesmas guardas de toda outra ponte direta
                # (imagem/voz/visão/STT/documento/benchmark) e devolve o
                # mesmo ExecutionResult de antes - contrato inalterado pro
                # resto desta função.
                if self.resident is None:
                    return {"output": "[ERRO] ResidentManager não disponível."}
                result = await self.resident.run_inference_direct(plan)
                if result.status.value == "success": return {"output": f"Modelo: {plan.model} (via {plan.runtime})\n--- Resultado ---\n{result.output}"}
                else: return {"output": f"[ERRO] {result.errors}"}
            except Exception as e: return {"output": f"[ERRO] {str(e)}"}

        return {"output": "Comando não reconhecido. Digite 'help'."}
