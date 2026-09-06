# phoenix_kernel/runtime/drivers/mtmd_driver.py
#
# Driver de VISAO NATIVA da Phoenix.
# Usa o llama-mtmd-cli (ja incluso no llama.cpp compilado com Vulkan) -
# nenhum fork/compilacao extra e necessaria. Mesmo padrao de design do
# sd_cpp.py: CLI de um tiro (roda, processa, sai), acha binario e modelo
# sozinho, timeout defensivo.
#
# Gerado automaticamente por setup_vision.py em 2026-08-03T19:03:48

from __future__ import annotations

import asyncio
import logging
import platform
import psutil
from pathlib import Path
from datetime import datetime, timezone

from core.domain.execution import ExecutionPlan, ExecutionResult, ExecutionStatus
from core.domain.runtime import RuntimeStatus, RuntimeState
from phoenix_kernel.paths import PhoenixPaths

logger = logging.getLogger(__name__)
_UTC = timezone.utc


class MtmdDriver:
    """
    Driver para o llama-mtmd-cli (Visao).
    Usa o mesmo binario compilado do llama.cpp (build com GGML_VULKAN=ON),
    mas em modo CLI pontual - nao mantem um servidor HTTP em background.
    """

    def __init__(self, *args, **kwargs) -> None:
        # drivers/ -> runtime/ -> phoenix_kernel/ -> raiz do projeto
        self._project_root = Path(__file__).resolve().parent.parent.parent.parent

    @property
    def name(self) -> str:
        return "mtmd"

    # -----------------------------------------------------------------
    # Descoberta de binario e arquivos de modelo
    # -----------------------------------------------------------------
    def _find_executable(self) -> str | None:
        repo_dir = self._project_root / "repos" / "llama.cpp"
        exe_names = (
            ["llama-mtmd-cli.exe", "llama-mtmd-cli"]
            if platform.system() == "Windows"
            else ["llama-mtmd-cli"]
        )
        for name in exe_names:
            candidates = [
                repo_dir / "build" / "bin" / "Release" / name,
                repo_dir / "build" / "bin" / name,
            ]
            for c in candidates:
                if c.exists():
                    return str(c)
        return None

    def _find_model_file(self, model_name: str) -> Path | None:
        clean = model_name.split(":")[0].replace("/", "-").lower().replace("-", "").replace("_", "")
        chat_dir = PhoenixPaths.get_category_path("Chat", "GGUF")
        if not chat_dir.exists():
            return None
        for match in chat_dir.glob("*.gguf"):
            stem_norm = match.stem.lower().replace("-", "").replace("_", "")
            if clean not in stem_norm:
                continue
            if match.stat().st_size > 50 * 1024 * 1024 and "mmproj" not in match.name.lower():
                return match
        return None

    def _find_mmproj_file(self, model_name: str = "") -> tuple[Path | None, str | None]:
        """Acha o arquivo mmproj (projetor de visão) pra parear com `model_name`.

        PHX-FIX (2026-08-28, investigação de "mtmd-cli falhou (exit 1)... control-looking
        token... provavelmente um bug no modelo" com gemma-4-12b-it-qat-q4_0): a versão
        anterior pegava o PRIMEIRO arquivo "*mmproj*.gguf" que o glob devolvesse, sem
        checar se ele realmente pertence ao modelo resolvido. Cada arquitetura de visão
        (MiniCPM-V, Gemma 3, Qwen2-VL...) tem seu PRÓPRIO encoder visual — são
        incompatíveis entre si. Se o usuário tiver mais de um modelo de visão instalado
        (ex.: baixou um Gemma multimodal manualmente além do MiniCPM-V da Golden
        Baseline), dois arquivos "*mmproj*.gguf" acabam na mesma pasta `Chat/GGUF`, e a
        ordem do glob não é garantida pelo SO — o llama-mtmd-cli podia carregar o modelo A
        com o mmproj do modelo B sem avisar claramente por quê, e o sintoma é exatamente
        esse tipo de erro de tokenizer/init logo no começo do carregamento.

        Retorna (caminho_escolhido, aviso_de_ambiguidade). `aviso_de_ambiguidade` só vem
        preenchido quando mais de um candidato foi encontrado e nenhuma correspondência
        forte pôde ser confirmada — quem chama deve propagar esse aviso pro usuário em vez
        de só logar, porque é exatamente esse tipo de mismatch que costuma causar falhas
        difíceis de diagnosticar sem abrir os logs do servidor.
        """
        chat_dir = PhoenixPaths.get_category_path("Chat", "GGUF")
        if not chat_dir.exists():
            return None, None
        matches = sorted(chat_dir.glob("*mmproj*.gguf"))
        if not matches:
            return None, None
        if len(matches) == 1:
            return matches[0], None

        # Mais de um candidato: tenta achar um cujo nome de arquivo tenha relação
        # direta com o modelo resolvido (comum em quantizações da comunidade, que
        # embutem o nome do modelo no arquivo do mmproj).
        clean = model_name.split(":")[0].replace("/", "-").lower().replace("-", "").replace("_", "")
        if clean:
            for m in matches:
                stem_norm = m.stem.lower().replace("-", "").replace("_", "")
                if clean in stem_norm:
                    return m, None

        # Heurística adicional: nome canônico do mmproj oficial do MiniCPM-V
        # (o único modelo de visão da Golden Baseline, ver setup_vision.py).
        for m in matches:
            if m.name.lower() == "mmproj-model-f16.gguf":
                return m, None

        names = ", ".join(m.name for m in matches)
        warning = (
            f"Encontrados {len(matches)} arquivos mmproj em '{chat_dir}' ({names}) e "
            f"nenhum bateu claramente com o modelo '{model_name or 'desconhecido'}' — "
            f"usando '{matches[0].name}' (ordem alfabética). Se a análise de imagem falhar "
            f"ou vier sem sentido, confira se este é o mmproj correto: cada arquitetura de "
            f"visão (MiniCPM-V, Gemma, Qwen2-VL...) exige o SEU PRÓPRIO mmproj, e usar o "
            f"errado costuma causar falhas de carregamento como esta."
        )
        logger.warning("MtmdDriver: %s", warning)
        return matches[0], warning

    # -----------------------------------------------------------------
    # Ciclo de vida (o runtime "vision" nao mantem processo persistente,
    # entao start/stop/status so reportam disponibilidade do binario)
    # -----------------------------------------------------------------
    async def start(self, plan: ExecutionPlan | None = None) -> bool:
        return self._find_executable() is not None

    async def stop(self) -> bool:
        return True

    async def status(self) -> RuntimeStatus:
        state = RuntimeState.RUNNING if self._find_executable() else RuntimeState.STOPPED
        return RuntimeStatus(name=self.name, state=state)

    # -----------------------------------------------------------------
    # Execucao real: roda o llama-mtmd-cli sobre uma imagem
    # -----------------------------------------------------------------
    async def execute(self, plan: ExecutionPlan) -> ExecutionResult:
        exe_path = self._find_executable()
        if not exe_path:
            return ExecutionResult(
                plan_id=plan.id,
                status=ExecutionStatus.FAILED,
                errors=["llama-mtmd-cli nao encontrado. Compile o llama.cpp com Vulkan (GGML_VULKAN=ON)."],
            )

        model_name = plan.model if plan.model else "minicpmv"
        model_path = self._find_model_file(model_name)
        mmproj_path, mmproj_ambiguity_warning = self._find_mmproj_file(model_name)

        if not model_path or not mmproj_path:
            missing = []
            if not model_path:
                missing.append(f"modelo '{model_name}'")
            if not mmproj_path:
                missing.append("mmproj-model-f16.gguf")
            return ExecutionResult(
                plan_id=plan.id,
                status=ExecutionStatus.FAILED,
                errors=[f"Arquivos de visao ausentes no disco: {', '.join(missing)}"],
            )

        image_path = plan.parameters.get("image_path")
        prompt = plan.parameters.get("prompt", "Descreva esta imagem em detalhes.")
        # PHX-NEW (pedido do usuário 2026-08-22, OCR real via visão): antes,
        # "-n 256" e o timeout de 180s eram fixos - suficiente pra uma
        # legenda curta, mas um "-n" baixo demais TRUNCA uma página inteira
        # de texto transcrito por OCR antes de terminar. Parametrizável via
        # plan.parameters, com o MESMO default de antes (256/180s) quando
        # ausente - descrição de imagem (describe_image_direct) continua
        # idêntica; só quem pede explicitamente (ocr_image_direct) manda
        # valores maiores.
        max_tokens = plan.parameters.get("max_tokens", 256)
        timeout_seconds = float(plan.parameters.get("timeout_seconds", 180.0))

        if not image_path or not Path(image_path).exists():
            return ExecutionResult(
                plan_id=plan.id,
                status=ExecutionStatus.FAILED,
                errors=[f"Imagem nao encontrada em: {image_path}"],
            )

        # PHX-FIX (31/08, mesma investigação RX580/Vulkan que corrigiu
        # llama_cpp.py numa rodada anterior - regressão reintroduzida
        # nesta cópia): "-ngl 999"/"--device Vulkan0" incondicional aqui
        # não tem NENHUM self-test de correctness (ao contrário do worker
        # de documentos/llama_cpp.py, que exige sanity_check() antes de
        # aceitar qualquer saída de uma instância Vulkan) - a política
        # declarada em resident_manager.py (visão/transcrição =
        # GPU_WITH_CPU_FALLBACK só porque mtmd/whisper têm caminho CPU
        # real e testado) fica falsa enquanto este driver força GPU sem
        # rede de segurança. Revertido pro único caminho comprovadamente
        # correto (CPU) até existir aqui um self-test equivalente ao do
        # llama_cpp.py.
        cores = psutil.cpu_count(logical=True) or 8

        def _build_cmd(include_reasoning_flag: bool) -> list[str]:
            cmd = [
                exe_path,
                "-m", str(model_path),
                "--mmproj", str(mmproj_path),
                "--image", str(image_path),
                "-p", prompt,
                "-ngl", "0",
                "-c", "8192",
            ]
            if include_reasoning_flag:
                # PHX-FIX (2026-09-06, achado real lendo o guia oficial de
                # deploy do MiniCPM-V 4.6 - OpenSQZ/MiniCPM-V-CookBook): builds
                # recentes do llama.cpp (pós PR #20606) ativam --reasoning=auto
                # por padrão, lendo do chat template. O checkpoint Instruct do
                # 4.6 NUNCA emite bloco <think>, mas o template dele ativa
                # "pensamento" mesmo assim - sem desligar explicitamente, a
                # saída sai quebrada/corrompida (aviso oficial: "Always pass
                # --reasoning off explicitly on Instruct inference commands").
                cmd += ["--reasoning", "off"]
            cmd += [
                "-t", str(cores),  # Usa todos os núcleos disponíveis
                "-n", str(max_tokens),  # Padrão 256 (legenda curta); OCR pede mais - ver comentário acima
            ]
            return cmd

        # PHX-FIX (2026-09-06, achado real do usuário, com print de tela: em
        # produção, "--reasoning" quebrou o mtmd-cli por completo - "error:
        # invalid argument: --reasoning", exit 1, TODA análise de imagem e
        # OCR parando de funcionar). A suposição de que o binário já
        # compilado suportava a flag (PR #20606 anterior à #26284 já
        # presente no build) estava ERRADA na prática - provavelmente essa
        # flag específica só chegou no mtmd-cli numa PR posterior à #26284,
        # mesmo já existindo no servidor há mais tempo (são binários
        # diferentes, compilados do mesmo repositório). Corrigido pra nunca
        # mais depender de suposição sobre versão: tenta COM a flag primeiro
        # (pega o benefício de evitar raciocínio corrompido quando
        # suportado); se o mtmd-cli rejeitar especificamente por não
        # reconhecer o argumento, tenta de novo SEM ela - a análise de
        # imagem nunca mais fica totalmente fora do ar por causa disso.
        cmd = _build_cmd(include_reasoning_flag=True)

        logger.info("MtmdDriver: executando analise de imagem: %s", " ".join(cmd))

        try:
            process = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                cwd=str(Path(exe_path).parent),
            )

            try:
                stdout, stderr = await asyncio.wait_for(process.communicate(), timeout=timeout_seconds)
            except asyncio.TimeoutError:
                process.kill()
                await process.wait()
                return ExecutionResult(
                    plan_id=plan.id,
                    status=ExecutionStatus.FAILED,
                    errors=[f"Timeout: a analise da imagem demorou mais de {timeout_seconds:.0f}s."],
                )

            err_text_probe = stderr.decode("utf-8", errors="replace").strip()
            if process.returncode != 0 and "invalid argument" in err_text_probe.lower() and "reasoning" in err_text_probe.lower():
                logger.warning(
                    "MtmdDriver: este mtmd-cli nao reconhece '--reasoning' "
                    "(build sem essa flag) - tentando novamente sem ela."
                )
                cmd = _build_cmd(include_reasoning_flag=False)
                logger.info("MtmdDriver: executando analise de imagem (sem --reasoning): %s", " ".join(cmd))
                process = await asyncio.create_subprocess_exec(
                    *cmd,
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.PIPE,
                    cwd=str(Path(exe_path).parent),
                )
                try:
                    stdout, stderr = await asyncio.wait_for(process.communicate(), timeout=timeout_seconds)
                except asyncio.TimeoutError:
                    process.kill()
                    await process.wait()
                    return ExecutionResult(
                        plan_id=plan.id,
                        status=ExecutionStatus.FAILED,
                        errors=[f"Timeout: a analise da imagem demorou mais de {timeout_seconds:.0f}s."],
                    )

            output_text = stdout.decode("utf-8", errors="replace").strip()

            if "ASSISTANT:" in output_text:
                output_text = output_text.split("ASSISTANT:")[-1].strip()

            # PHX-FIX (varredura 2026-08-21 rodada 3, achado #2): mesmo
            # padrão do achado #1 (sd_cpp.py) - `process.returncode` nunca
            # era conferido aqui, o sucesso dependia só de `output_text`
            # não estar vazio. Um `mtmd-cli` que crasha DEPOIS de escrever
            # algo em stdout (ex: segfault no fim, saída parcial antes de
            # morrer) seria reportado como SUCCESS com uma "descrição da
            # imagem" que pode estar truncada/corrompida. Mirando o padrão
            # já usado em whisper.py (`r.returncode == 0 and ...`): agora
            # confere o exit code real antes de aceitar a saída como
            # análise válida.
            err_text = stderr.decode("utf-8", errors="replace").strip()

            if process.returncode == 0 and output_text:
                logger.info("MtmdDriver: imagem analisada com sucesso.")
                return ExecutionResult(
                    plan_id=plan.id,
                    status=ExecutionStatus.SUCCESS,
                    output=output_text,
                    started_at=datetime.now(_UTC),
                    finished_at=datetime.now(_UTC),
                )

            if process.returncode != 0:
                logger.error(
                    "MtmdDriver: mtmd-cli saiu com erro (exit %s). stderr: %s",
                    process.returncode, err_text,
                )
                error_msg = f"mtmd-cli falhou (exit {process.returncode}): {err_text[-500:]}"
                if mmproj_ambiguity_warning:
                    # PHX-FIX (2026-08-28): propaga o aviso de ambiguidade de mmproj pro
                    # chat, não só pro log do servidor — é a pista mais direta pra esse
                    # tipo de falha, e o usuário não necessariamente tem acesso fácil ao
                    # console do processo Python pra achar sozinho.
                    error_msg += f" | Possível causa: {mmproj_ambiguity_warning}"
                return ExecutionResult(
                    plan_id=plan.id,
                    status=ExecutionStatus.FAILED,
                    errors=[error_msg],
                )

            logger.error("MtmdDriver: saida vazia. stderr: %s", err_text)
            return ExecutionResult(
                plan_id=plan.id,
                status=ExecutionStatus.FAILED,
                errors=[f"Saida vazia do mtmd-cli. stderr: {err_text[-500:]}"],
            )

        except Exception as exc:
            logger.exception("MtmdDriver: erro inesperado")
            return ExecutionResult(
                plan_id=plan.id,
                status=ExecutionStatus.FAILED,
                errors=[f"Erro ao executar mtmd-cli: {exc}"],
            )