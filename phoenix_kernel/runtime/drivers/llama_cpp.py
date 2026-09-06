from __future__ import annotations
import asyncio
import logging
import json
import os
import platform
import urllib.request
import urllib.error
import socket
import httpx
import psutil
from pathlib import Path
from datetime import datetime, timezone

from core.domain.execution import ExecutionPlan, ExecutionResult, ExecutionStatus
from core.domain.runtime import RuntimeStatus, RuntimeState
from phoenix_kernel.paths import PhoenixPaths

logger = logging.getLogger(__name__)
_UTC = timezone.utc


def _discover_project_root(start_file: Path) -> Path:
    current = start_file.resolve()
    for _ in range(8):
        current = current.parent
        candidate = current / "repos" / "llama.cpp"
        if candidate.exists():
            return current
    return start_file.resolve().parent.parent.parent.parent


def find_free_local_port(start: int = 8095, end: int = 8110, host: str = "127.0.0.1") -> int:
    """Retorna a primeira porta TCP livre na faixa inclusiva.

    A checagem é deliberadamente best-effort (não é um lease atômico), mas
    evita o erro real encontrado em 2026-08-30: a porta 8090 estava ocupada
    por ``WsToastNotification`` no Windows e tanto a Arena quanto o worker
    documental tentavam usá-la de forma hardcoded.
    """
    if start <= 0 or end < start or end > 65535:
        raise ValueError(f"faixa de portas inválida: {start}-{end}")
    for port in range(start, end + 1):
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
            sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            try:
                sock.bind((host, port))
            except OSError:
                continue
            return port
    raise RuntimeError(f"nenhuma porta livre em {host}:{start}-{end}")


class LlamaCppDriver:
    """Driver do llama.cpp com política de lançamento explícita e isolável.

    Os defaults preservam o motor compartilhado do chat: porta 8081, NGL
    vindo de ``PHOENIX_LLM_NGL`` (hoje 0) e contexto 16384. Instâncias
    temporárias podem, sem alterar variáveis globais, escolher device, NGL,
    contexto e ``--override-tensor``. Isso é necessário porque os testes
    reais na RX 580/Polaris provaram que *detectar Vulkan não garante
    correctness*: ``-ngl 1`` corrompeu a saída quando ``output.weight`` foi
    para Vulkan, enquanto ``-ot output.weight=CPU`` restaurou a resposta.
    """
    def __init__(
        self,
        *args,
        port: int = 8081,
        force_ngl: str | None = None,
        device: str | None = None,
        tensor_overrides: dict[str, str] | None = None,
        context_size: int = 32768,
        no_op_offload: bool = True,
        **kwargs,
    ) -> None:
        if not (1 <= int(port) <= 65535):
            raise ValueError(f"porta inválida para llama-server: {port}")
        if int(context_size) < 256:
            raise ValueError(f"context_size muito pequeno: {context_size}")
        self._project_root = _discover_project_root(Path(__file__))
        self._process = None
        self._port = int(port)
        self._model_path = None
        self._model_alias = None
        self._force_ngl = force_ngl
        self._device = (device or "").strip() or None
        self._tensor_overrides = {str(k): str(v) for k, v in (tensor_overrides or {}).items()}
        self._context_size = int(context_size)
        self._no_op_offload = bool(no_op_offload)

    @property
    def port(self) -> int:
        return self._port

    @property
    def model_alias(self) -> str | None:
        return self._model_alias

    @property
    def model_path(self) -> Path | None:
        return self._model_path

    def _build_server_args(self, exe_path: str, model_path: Path, ngl: str) -> list[str]:
        """Monta argumentos do subprocesso de forma testável e determinística."""
        args = [
            exe_path, '-m', str(model_path), '--alias', self._model_alias or model_path.stem,
            '--host', '127.0.0.1', '--port', str(self._port),
            '-ngl', str(ngl), '-c', str(self._context_size),
            # PHX-FIX (2026-09-06, achado real do usuário: "qualquer resposta
            # do modelo... fica cortada" - acontecia com QUALQUER provedor,
            # sem erro nenhum, e não era timeout de rede - investigação
            # revelou a causa real): sem --jinja explícito, a separação de
            # "pensamento" (<think>...</think>) de modelos como Qwen3 fica a
            # critério do padrão da build - quando falha, o texto vem com a
            # tag <think> EMBUTIDA no campo content. O front-end (AviaryApp.
            # tsx) tenta remover isso com um regex que exige a tag ABRIR E
            # FECHAR - se a resposta for cortada por qualquer limite ENQUANTO
            # o modelo ainda está "pensando" (a tag nunca fecha), o regex não
            # acha nada pra remover e o raciocínio bruto vaza pra tela
            # (parece "corta no meio"), ou o pensamento consome a maior parte
            # do orçamento e a resposta visível final fica curta demais
            # (parece "termina normal mas é curta"). --jinja explícito
            # garante o motor de template correto ativo (confirmado: com
            # --jinja, llama-server separa corretamente <think> do Qwen3 num
            # campo `reasoning_content` à parte, nunca embutido em
            # `content`) - resolve na origem, não só remendando o sintoma no
            # front-end (esse remendo continua existindo como rede de
            # segurança, ver AviaryApp.tsx).
            '--jinja',
        ]
        if self._device:
            args += ['--device', self._device]
        if self._tensor_overrides:
            override_spec = ','.join(f"{pattern}={buffer_type}" for pattern, buffer_type in self._tensor_overrides.items())
            args += ['-ot', override_spec]
        if self._no_op_offload:
            args.append('--no-op-offload')
        return args

    @property
    def name(self) -> str: 
        return 'llama.cpp'

    def _find_executable(self) -> str | None:
        """Resolve o llama-server compilado pela própria Phoenix em Windows/Linux."""
        build_bin = self._project_root / "repos" / "llama.cpp" / "build" / "bin"

        candidates = [
            build_bin / "Release" / "llama-server.exe",
            build_bin / "llama-server.exe",
            build_bin / "llama-server",
            build_bin / "Release" / "llama-server",
        ]

        for candidate in candidates:
            try:
                if candidate.is_file() and candidate.stat().st_size > 0:
                    if os.name != "nt" and not os.access(candidate, os.X_OK):
                        logger.warning(
                            f"LlamaCppDriver: binário encontrado mas sem permissão de execução: {candidate}"
                        )
                        continue
                    logger.info(f"LlamaCppDriver: llama-server encontrado no projeto: {candidate}")
                    return str(candidate)
            except OSError:
                continue

        import shutil
        global_exe = shutil.which("llama-server") or shutil.which("main")
        if global_exe:
            logger.info(f"LlamaCppDriver: usando llama-server disponível no PATH: {global_exe}")
            return global_exe

        logger.error(
            "LlamaCppDriver: llama-server não encontrado em "
            f"{build_bin} nem no PATH."
        )
        return None

    def _find_model_file(self, model_name: str) -> Path | None:
        clean_name = model_name.split(":")[0].replace("/", "-").lower()
        
        def search_in_dir(dir_path: Path) -> Path | None:
            if not dir_path.exists(): return None
            matches = list(dir_path.glob(f"*{clean_name}*.gguf"))
            for match in matches:
                if match.stat().st_size > 50 * 1024 * 1024: 
                    return match
            return None

        # 1. Tenta o caminho relativo do projeto
        found = search_in_dir(PhoenixPaths.get_category_path("Chat", "GGUF"))
        if found: return found

        # 2. Tenta ler o arquivo de configuração dinâmico do sistema
        storage_candidates = []
        programdata = os.environ.get("ProgramData")
        if programdata:
            storage_candidates.append(Path(programdata) / "Phoenix" / "storage.json")
        storage_candidates.append(self._project_root / "data" / "storage.json")

        for s_path in storage_candidates:
            if s_path.exists():
                try:
                    storage = json.loads(s_path.read_text(encoding="utf-8"))
                    workspace = storage.get("workspace")
                    if workspace:
                        found = search_in_dir(Path(workspace) / "Models" / "Chat" / "GGUF")
                        if found: return found
                except Exception:
                    pass

        # 3. Se nada funcionar, varre TODOS os discos físicos conectados à máquina
        logger.info(f"LlamaCppDriver: Varrendo discos físicos para encontrar o modelo '{model_name}'...")
        for partition in psutil.disk_partitions(all=False):
            mountpoint = partition.mountpoint
            try:
                dynamic_path = Path(mountpoint) / "Phoenix" / "Workstations" / "Models" / "Chat" / "GGUF"
                found = search_in_dir(dynamic_path)
                if found: 
                    logger.info(f"LlamaCppDriver: Modelo encontrado em {dynamic_path}")
                    return found
                
                found = search_in_dir(Path(mountpoint) / "Models" / "Chat" / "GGUF")
                if found: 
                    logger.info(f"LlamaCppDriver: Modelo encontrado em {Path(mountpoint)}")
                    return found

            except PermissionError:
                continue

        logger.error(f"LlamaCppDriver: modelo '{model_name}' não encontrado em nenhum disco.")
        return None

    def find_model_file_path(self, model_name: str) -> Path | None:
        """Wrapper público de _find_model_file() - PHX-NEW (colaboração de
        dois modelos): resident_manager.py precisa localizar o mesmo
        arquivo .gguf que este driver usaria, só para ESTIMAR memória
        necessária (hardware_fit.py) antes de decidir se sobe a instância
        de GPU dedicada - sem duplicar a lógica de busca em disco aqui."""
        return self._find_model_file(model_name)

    async def _check_health(self) -> bool:
        try:
            def check():
                try:
                    with urllib.request.urlopen(f"http://127.0.0.1:{self._port}/health", timeout=2) as r:
                        return r.status == 200
                except: return False
            loop = asyncio.get_running_loop()
            return await loop.run_in_executor(None, check)
        except: return False

    async def start(self, plan: ExecutionPlan | None = None) -> bool:
        model_name = plan.model if plan and plan.model else "qwen3:8b"
        requested_model_path = self._find_model_file(model_name)

        # PHX-FIX: antes, se JÁ tivesse um processo rodando, start()
        # retornava True na hora, sem checar se era o modelo CERTO - pedir
        # pra trocar de modelo (LOAD_MODEL) nunca trocava nada de verdade,
        # só confirmava que "algum" llama-server estava de pé. Agora
        # compara o arquivo do modelo pedido com o que está carregado; só
        # reaproveita o processo se for exatamente o mesmo arquivo -
        # senão para o antigo e carrega o novo.
        if self._process and self._process.returncode is None:
            if requested_model_path and self._model_path and requested_model_path == self._model_path:
                return True  # já é o modelo certo, nada a fazer
            logger.info(
                f"LlamaCppDriver: troca de modelo pedida "
                f"('{self._model_path.name if self._model_path else '?'}' -> '{model_name}') - recarregando."
            )
            await self.stop()

        if not requested_model_path:
            logger.error(f"LlamaCppDriver: modelo '{model_name}' não encontrado em nenhum disco.")
            return False
        model_path = requested_model_path

        exe_path = self._find_executable()
        if not exe_path:
            logger.error("LlamaCppDriver: BINARIO llama-server NAO ENCONTRADO.")
            return False

        self._model_path = model_path

        # PHX-FIX (achado real via screenshot do usuário: seletor
        # "[LLAMA-SERVER] B:\Phoenix\...\qwen3-8b-q4_k_m.gguf" falhava com
        # 404 "File Not Found" do PRÓPRIO llama-server em TODA mensagem,
        # inclusive um "ola" sem nenhuma relação com imagem): sem `--alias`,
        # o llama-server usa o CAMINHO ABSOLUTO do arquivo (com barra
        # invertida, letra de unidade etc.) como o "id" que ele mesmo
        # devolve em /v1/models - e é essa mesma string que
        # server.ts:/api/proxy/chat (que fala DIRETO com
        # http://127.0.0.1:8081/v1/chat/completions, sem passar pelo
        # phoenix_kernel) manda de volta no campo "model" de cada request.
        # O llama-server não reconhece de forma confiável esse caminho bruto
        # como o modelo que ele mesmo tem carregado e responde com o 404
        # nativo dele ("not_found_error"). Um `--alias` fixo, curto e
        # determinístico (derivado do próprio arquivo que está sendo
        # carregado, não do model_name pedido) faz o llama-server reportar
        # e aceitar esse mesmo id estável em vez do caminho bruto do disco -
        # elimina a dependência de o request bater exatamente com barras/
        # maiúsculas/letra de unidade do caminho absoluto.
        self._model_alias = model_path.stem

        ngl = self._force_ngl if self._force_ngl is not None else os.environ.get("PHOENIX_LLM_NGL", "0")
        logger.info(
            "LlamaCppDriver: Iniciando motor nativo. Modelo: %s (alias: %s), NGL: %s, "
            "device=%s, context=%s, overrides=%s",
            model_path.name, self._model_alias, ngl, self._device or "auto", self._context_size,
            self._tensor_overrides or {},
        )

        try:
            env = os.environ.copy()
            cwd = str(Path(exe_path).parent)

            # PHX-FIX: Contexto aumentado para 8192 para evitar Erro 500 (Context size exceeded)
            #
            # PHX-FIX (achado real do usuário 2026-08-24, "aumentar contexto
            # de caracteres... deixar em aberto pra livre resposta de cada
            # modelo"): 8192 tokens era o teto REAL do llama-server nesta
            # máquina - mas o frontend (AviaryApp.tsx) sempre alegou
            # "128000" de janela de contexto pra qualquer provedor local, um
            # número nunca verificado contra o que o processo real usa (o
            # mesmo padrão de dado fabricado já corrigido em outras partes
            # desta auditoria). 8192 já era um risco antes da v52: cada
            # mensagem reenvia o HISTÓRICO INTEIRO da conversa (ver
            # sendToProvider() em AviaryApp.tsx), e a v52 passou a injetar
            # blocos de resultado de busca real no meio dessa história -
            # ambos crescem o consumo de contexto por turno. Aumentado pra
            # 16384 (dobro), alinhado ao `contextWindow: 16384` que o
            # frontend já declarava como padrão (mas nunca era o valor
            # usado de verdade aqui) - dá margem real pra conversas mais
            # longas com busca na web sem reintroduzir o "Erro 500 (Context
            # size exceeded)" que motivou o valor anterior. RAM real desta
            # máquina (32GB) tem folga de sobra pro KV cache adicional de um
            # modelo 8B em CPU.
            #
            # PHX-UPDATE (2026-09-06, mesmo achado recorrendo - usuário
            # relatou de novo "qualquer resposta do modelo... fica cortada":
            # aumentado outra vez, de 16384 pra 32768 (dobro), a pedido
            # explícito do usuário depois de confirmar o trade-off de RAM.
            # Motivo de ter voltado a acontecer mesmo com 16384: NÃO existe
            # nenhum corte/trim do histórico de conversa em nenhum lugar do
            # projeto (nem em AviaryApp.tsx nem em server.ts) - cada mensagem
            # reenvia a conversa INTEIRA (ver sendToProvider()), então uma
            # conversa longa o suficiente sempre acaba esbarrando de novo no
            # teto, não importa o quão alto - só empurra o problema pra mais
            # tarde. Dobrar o contexto dá bastante mais fôlego, mas o corte
            # de histórico continua como o próximo passo mais robusto se o
            # sintoma voltar de novo depois deste aumento.
            launch_args = self._build_server_args(exe_path, model_path, str(ngl))
            self._process = await asyncio.create_subprocess_exec(
                *launch_args,
                stdout=asyncio.subprocess.DEVNULL, stderr=asyncio.subprocess.PIPE, env=env, cwd=cwd
            )
            
            for _ in range(120):
                if await self._check_health(): return True
                if self._process.returncode is not None:
                    stderr_data = await self._process.stderr.read()
                    err_msg = stderr_data.decode('utf-8', errors='replace').strip()
                    logger.error(f"LlamaCppDriver: Processo morreu. STDERR do llama-server: {err_msg[-500:]}")
                    return False
                await asyncio.sleep(1)
            return False
        except Exception as exc:
            logger.error(f"LlamaCppDriver: erro inesperado ao iniciar - {exc}")
            return False

    async def sanity_check(
        self,
        expected: str = "PHOENIX_OK",
        *,
        timeout: float = 90.0,
    ) -> tuple[bool, str]:
        """Valida *correctness* do backend, não apenas health/VRAM.

        O bug real de Polaris respondia HTTP 200, ocupava VRAM e apresentava
        throughput normal enquanto devolvia ``????``/tokens repetidos. Por
        isso ``/health`` sozinho é insuficiente para autorizar um worker GPU.
        """
        if not await self._check_health():
            return False, "llama-server não saudável"
        marker = (expected or "PHOENIX_OK").strip()
        payload = {
            "model": self._model_alias or (self._model_path.stem if self._model_path else ""),
            "messages": [
                {"role": "system", "content": "Siga a instrução literalmente. /no_think"},
                {"role": "user", "content": f"Responda somente: {marker}"},
            ],
            "temperature": 0.0,
            "max_tokens": 24,
        }
        try:
            async with httpx.AsyncClient(timeout=timeout) as client:
                response = await client.post(
                    f"http://127.0.0.1:{self._port}/v1/chat/completions",
                    json=payload,
                    headers={"Content-Type": "application/json"},
                )
                response.raise_for_status()
                data = response.json()
            choice = (data.get("choices") or [{}])[0]
            message = choice.get("message") or {}
            text = str(message.get("content") or "").strip()
            if text == marker:
                return True, text
            return False, f"resposta inesperada do self-test: {text[:160]!r}"
        except Exception as exc:
            detail = str(exc).strip() or type(exc).__name__
            return False, f"self-test falhou: {type(exc).__name__}: {detail}"

    async def stop(self) -> bool:
        if self._process and self._process.returncode is None:
            self._process.terminate()
            await self._process.wait()
        self._process = None
        return True

    async def status(self) -> RuntimeStatus:
        if self._process and self._process.returncode is None:
            return RuntimeStatus(name=self.name, state=RuntimeState.RUNNING if await self._check_health() else RuntimeState.ERROR)
        return RuntimeStatus(name=self.name, state=RuntimeState.STOPPED)

    async def execute(self, plan: ExecutionPlan) -> ExecutionResult:
        if not await self._check_health():
            if not await self.start(plan):
                return ExecutionResult(plan_id=plan.id, status=ExecutionStatus.FAILED, errors=["Failed to start llama.cpp server"])

        params = plan.parameters or {}
        prompt = params.get("user_prompt", params.get("prompt", ""))
        system_prompt = params.get("system_prompt", "Você é um assistente útil.")

        model_label = self._model_path.name if self._model_path else "?"
        preview = prompt[:120] + ("..." if len(prompt) > 120 else "")
        logger.info(f"LlamaCppDriver: Enviando prompt para '{model_label}' via HTTP: \"{preview}\"")

        payload = {
            "messages": [{"role": "system", "content": system_prompt}, {"role": "user", "content": prompt}],
            "temperature": params.get("temperature", 0.1),
        }
        # PHX-FIX 2026-08-30: ResidentManager já enviava
        # parameters["unlimited_output"]=True para criação/transformação de
        # documentos, mas este driver ignorava o sinal e sempre mandava
        # max_tokens=1024. Agora o campo é realmente omitido quando solicitado,
        # deixando o servidor/modelo terminar por EOS/limite físico de contexto.
        _unlimited_output = bool(params.get("unlimited_output"))
        if not _unlimited_output:
            payload["max_tokens"] = params.get("max_tokens", 1024)
        # PHX-FIX (auditoria 2026-08-20, "Resident Research + llama.cpp JSON
        # hardening"): antes, `json_format` no ExecutionPlan.parameters era
        # lido pelo OllamaDriver (payload["format"]="json", grammar nativa
        # do lado do servidor) mas NUNCA pelo LlamaCppDriver - o comentário
        # em ollama.py já documentava isso como pendência ("json_format do
        # ExecutionPlan ainda não é aplicado - ver LlamaCppDriver.execute()").
        # O resultado prático: `resident research` rodando em llama.cpp
        # dependia 100% da instrução em texto no system_prompt ("Responda
        # SEMPRE com JSON") - zero blindagem técnica, só convenção.
        # `response_format: {"type": "json_object"}` é o mesmo campo do
        # endpoint OpenAI-compatible que o llama-server implementa (força a
        # amostragem de tokens a só produzir JSON válido via grammar interna
        # - não é só um prompt melhor, é uma restrição real na geração).
        # Isso sozinho não cobre 100% dos casos (binários muito antigos de
        # llama-server podem ignorar o campo; um "JSON válido" ainda pode
        # vir sem as chaves "steps"/"response" esperadas) - por isso o
        # ReasoningEngine.plan_mission() (reasoning_engine.py) tem uma
        # segunda camada: extração tolerante a cercas ```json``` / texto
        # antes do JSON, e um retry com reprompt mais estrito antes de
        # desistir. Nenhuma das duas camadas sozinha era suficiente; juntas,
        # uma resposta que não é JSON não vira missão registrada em nenhum
        # dos dois runtimes agora.
        if params.get("json_format"):
            payload["response_format"] = {"type": "json_object"}

        # PHX-FIX: started_at precisa ser capturado ANTES da chamada HTTP,
        # não depois - antes disso, started_at e finished_at eram gerados
        # na mesma linha, os dois DEPOIS da resposta já ter voltado, então
        # a duração real da inferência (que pode levar minutos em CPU)
        # nunca era capturada - sempre dava ~0ms.
        started_at = datetime.now(_UTC)

        # PHX-FIX V5: 600s era insuficiente para geração documental longa
        # com modelos >=12B em CPU/híbrido. O timeout HTTP deve ser maior que
        # o tempo esperado de inferência e menor/igual ao teto do Resident.
        #
        # PHX-FIX (pedido explícito do usuário 2026-08-28, testando Gemma 4
        # 12B com pesquisa web + PDF longo): o llama-server é chamado sem
        # streaming (`stream: false` no payload acima) - o modelo gera a
        # resposta INTEIRA antes de devolver qualquer byte, então o cliente
        # HTTP fica esperando em silêncio até o fim, não importa quanto
        # demore. 29min deixou de ser suficiente pra um relatório longo
        # num modelo grande rodando bastante em CPU - subido pra bater com
        # o novo DOCUMENT_CREATE_TIMEOUT_LARGE_SECONDS=3600s (1h) do
        # Resident (resident_manager.py). Continua com a mesma regra de
        # sempre: este piso só AUMENTA o timeout calculado, nunca reduz (ver
        # `_explicit_timeout` abaixo) - e continua sendo um teto de
        # segurança contra travamento real, não um limite de tamanho de
        # resposta.
        _model_lower = str(plan.model or "").lower()
        _max_tokens = 4096 if _unlimited_output else int(params.get("max_tokens", 1024) or 1024)
        _large_model = any(m in _model_lower for m in ("12b", "14b", "20b", "27b", "30b", "32b", "35b", "70b"))
        if _large_model and _max_tokens >= 2048:
            _http_timeout = 3540.0   # 59 min; Resident corta em 60 min
        elif _max_tokens >= 2048:
            _http_timeout = 1140.0   # 19 min; Resident corta em 20 min
        else:
            _http_timeout = 600.0

        # PHX-FIX (achado do usuário 2026-08-28: "Erro na inferência do
        # llama.cpp:" sem NADA depois dos dois-pontos, usando
        # fill_spreadsheet_template_direct): a heurística acima só olha o
        # NOME do modelo e max_tokens de SAÍDA - um modelo "8b" (fora da
        # lista de "modelo grande") com max_tokens=1024 (padrão) sempre caía
        # no piso de 600s, mesmo o Resident já orçando até 1200s
        # (DOCUMENT_CREATE_TIMEOUT_MEDIUM_SECONDS) pra essa mesma chamada.
        # Numa máquina rodando o modelo majoritariamente em CPU (VRAM
        # insuficiente pra offload completo), mapear um documento inteiro
        # pras colunas de um template facilmente passa de 600s sem o modelo
        # ser "grande" nem pedir muitos tokens de saída - só é uma tarefa
        # mais lenta de processar (prompt de entrada grande, não geração
        # longa). Quem chama execute() agora pode declarar seu próprio
        # orçamento via parameters["timeout_seconds"] em vez de depender só
        # da heurística por nome/tamanho - isso só AUMENTA o timeout em
        # relação ao piso calculado acima, nunca reduz.
        _explicit_timeout = params.get("timeout_seconds")
        if _explicit_timeout:
            try:
                _http_timeout = max(_http_timeout, float(_explicit_timeout))
            except (TypeError, ValueError):
                pass

        try:
            async with httpx.AsyncClient(timeout=_http_timeout) as client:
                response = await client.post(
                    f'http://127.0.0.1:{self._port}/v1/chat/completions',
                    json=payload,
                    headers={'Content-Type': 'application/json'}
                )
                response.raise_for_status()
                res_data = response.json()

            finished_at = datetime.now(_UTC)
            message = res_data.get("choices", [{}])[0].get("message", {}) or {}
            content_text = message.get("content") or ""
            # PHX-FIX (2026-08-22, achado real do usuário: numa colaboração de
            # dois modelos de raciocínio - CPU com Qwen3-4B, GPU com
            # DeepSeek-R1-Distill-7B -, o lado CPU voltou com resposta VAZIA em
            # 6 rodadas seguidas, enquanto o lado GPU sempre respondeu normal).
            # Builds recentes do llama-server (endpoint compatível OpenAI)
            # separam a saída de modelos de raciocínio em DOIS campos:
            # "content" (a resposta final) e "reasoning_content" (o
            # pensamento dentro de <think>...</think>) - quando o parser de
            # raciocínio do servidor reconhece o modelo mas a resposta dele
            # não chega a fechar o bloco de pensamento de um jeito que o
            # parser reconhece como "aqui começa a resposta final", TUDO cai
            # em "reasoning_content" e "content" fica vazio, mesmo com a
            # requisição tendo dado certo (status 200, sem erro nenhum) - por
            # isso `cpu_execute`/`gpu_execute` nunca levantavam exceção, o
            # "resultado" só era uma string vazia de verdade. Antes, só
            # "content" era lido - qualquer resposta inteira que caísse em
            # "reasoning_content" era descartada silenciosamente. Isso é uma
            # HIPÓTESE bem fundamentada (esse split é um comportamento real e
            # documentado do llama-server pra modelos de raciocínio), não uma
            # certeza sobre o build específico do usuário - por isso o log
            # abaixo grava o tamanho de cada campo separadamente, pra
            # confirmar (ou descartar) isso com evidência real do próximo teste,
            # em vez de só assumir que resolveu.
            reasoning_text = message.get("reasoning_content") or ""
            used_reasoning_fallback = False
            output_text = content_text
            if not content_text.strip() and reasoning_text.strip():
                output_text = reasoning_text
                used_reasoning_fallback = True
            finish_reason = res_data.get("choices", [{}])[0].get("finish_reason", "?")
            logger.info(
                f"LlamaCppDriver ({model_label}): resposta recebida - "
                f"content={len(content_text)} char(s), reasoning_content={len(reasoning_text)} char(s), "
                f"finish_reason='{finish_reason}'"
                + (" - CONTENT VAZIO, usando reasoning_content como fallback" if used_reasoning_fallback else "")
                + (" - AMBOS OS CAMPOS VAZIOS (resposta genuinamente sem conteúdo)" if not output_text.strip() else "")
            )

            # PHX-NEW: o llama-server (endpoint compatível OpenAI) já
            # devolve "usage" com completion_tokens/prompt_tokens - isso
            # era descartado antes, só output_text era extraído. Sem isso,
            # ExecutionResult.metrics ficava sempre vazio e não dava pra
            # saber tokens/s de nenhuma execução real.
            usage = res_data.get("usage") or {}
            completion_tokens = usage.get("completion_tokens", 0)
            elapsed_s = (finished_at - started_at).total_seconds()
            tokens_per_second = round(completion_tokens / elapsed_s, 2) if elapsed_s > 0 and completion_tokens else 0.0

            return ExecutionResult(
                plan_id=plan.id, status=ExecutionStatus.SUCCESS, output=output_text,
                metrics={
                    "tokens_generated": completion_tokens,
                    "tokens_per_second": tokens_per_second,
                    "prompt_tokens": usage.get("prompt_tokens", 0),
                    # PHX-FIX (2026-09-06, achado real do usuário: o pipeline
                    # de criação/transformação de documento entregou o
                    # RACIOCÍNIO BRUTO do modelo (em inglês, tipo "Okay, I
                    # need to convert...") como se fosse o conteúdo final do
                    # arquivo - exatamente o cenário que este fallback (PHX-
                    # FIX 2026-08-22, logo acima) cobre, só que NUNCA tinha
                    # sido exposto pra quem chama saber que aconteceu. Antes
                    # desta correção, content vazio + reasoning_content cheio
                    # virava "sucesso" indistinguível de uma resposta real -
                    # nenhum consumidor (criação de documento, colaboração
                    # CPU/GPU, chat) conseguia reagir diferente. Agora o
                    # sinal chega em metrics; quem consome decide (ver
                    # create_document_direct, que passou a tratar isso como
                    # falha clara em vez de aceitar o raciocínio como
                    # documento).
                    "used_reasoning_fallback": used_reasoning_fallback,
                    "duration_ms": round(elapsed_s * 1000),
                },
                started_at=started_at, finished_at=finished_at,
            )

        except Exception as exc:
            # PHX-FIX (achado do usuário 2026-08-28): exceções de timeout do
            # httpx (ReadTimeout/ConnectTimeout/PoolTimeout) costumam ter
            # str(exc) VAZIO - antes disso, a mensagem virava literalmente
            # "Erro na inferência do llama.cpp: " (nada depois dos
            # dois-pontos, exatamente como apareceu na tela do usuário), sem
            # dizer NEM o tipo do erro. Incluir type(exc).__name__ garante
            # que sempre sobra alguma pista, mesmo quando a biblioteca não
            # dá detalhe nenhum - e como o timeout é o suspeito mais comum
            # pra uma mensagem vazia, o texto de fallback já aponta pra ele
            # em vez de deixar a pessoa adivinhando.
            detail = str(exc).strip()
            if detail:
                detail = f"{type(exc).__name__}: {detail}"
            else:
                detail = (
                    f"{type(exc).__name__} sem mensagem adicional - provavelmente timeout "
                    f"({_http_timeout:.0f}s) ou conexão perdida com o llama-server (porta {self._port})"
                )
            return ExecutionResult(plan_id=plan.id, status=ExecutionStatus.FAILED, errors=[f"Erro na inferência do llama.cpp: {detail}"])