"""
phoenix_kernel/runtime/drivers/whisper.py

WhisperDriver — transcrição de áudio (STT) via whisper.cpp.

Estratégia de localização do binário (mesmo padrão do LlamaCppDriver):
  repos/whisper.cpp/build/bin/Release/whisper-cli.exe (Windows)
  repos/whisper.cpp/build/bin/whisper-cli                (Linux)

Estratégia de localização do modelo:
  B:/Phoenix/Workstations/Models/Audio/*.bin ou *.gguf (via PhoenixPaths)
  Preferência: ggml-medium.bin > ggml-base.bin > qualquer .bin/.gguf

Formatos de áudio suportados: .wav (nativo, sem conversão), qualquer outro
formato que o ffmpeg instalado entenda via conversão automática pra WAV
16kHz mono (_convert_to_wav() abaixo não filtra por extensão - roda
"ffmpeg -i <entrada> ..." genérico). A allowlist que efetivamente limita o
que chega até aqui vive em api_server.py::_ALLOWED_AUDIO_EXTS (rota
/api/transcribe) - hoje .wav/.mp3/.ogg/.m4a/.flac/.aac/.webm; mantenha as
duas listas em sincronia (ver tests/test_audio_upload_consistency.py).
O plan.parameters["audio_path"] deve conter o caminho do arquivo de áudio a
transcrever. Resultado em plan output como string de texto transcrito.

Por que whisper.cpp e não openai-whisper (Python)?
  - Sem dependência de torch/transformers (que pesam 3-4GB)
  - Roda em CPU/Vulkan igual ao llama.cpp
  - Mesmo padrão de binário compilado que o resto dos drivers já usa
"""
from __future__ import annotations

import asyncio
import logging
import platform
import shutil
import tempfile
from pathlib import Path
from datetime import datetime, timezone

from core.domain.execution import ExecutionPlan, ExecutionResult, ExecutionStatus
from core.domain.runtime import RuntimeStatus, RuntimeState
from phoenix_kernel.paths import PhoenixPaths

logger = logging.getLogger(__name__)
_UTC = timezone.utc


class WhisperDriver:
    def __init__(self, *args, **kwargs) -> None:
        self._project_root = Path(__file__).resolve().parent.parent.parent.parent

    @property
    def name(self) -> str:
        return "whisper"

    def _find_executable(self) -> str | None:
        """Procura o whisper-cli no repo compilado ou no PATH do sistema."""
        repo_dir = self._project_root / "repos" / "whisper.cpp"
        is_win = platform.system() == "Windows"
        exe_names = ["whisper-cli.exe", "main.exe"] if is_win else ["whisper-cli", "main"]

        candidates = []
        for name in exe_names:
            candidates.extend([
                repo_dir / "build" / "bin" / "Release" / name,
                repo_dir / "build" / "bin" / name,
                repo_dir / "build" / name,
            ])

        for c in candidates:
            if c.exists() and c.stat().st_size > 0:
                return str(c)

        # Fallback: PATH do sistema (ex: instalado via apt/brew)
        for name in (["whisper-cli", "whisper"] if not is_win else ["whisper-cli.exe"]):
            found = shutil.which(name)
            if found:
                return found

        return None

    def _find_model(self) -> Path | None:
        """Procura modelo Whisper no diretório de áudio da Phoenix."""
        try:
            audio_dir = PhoenixPaths.get_category_path("Audio")
        except Exception:
            return None

        if not audio_dir.exists():
            return None

        # Preferência de modelos por tamanho/qualidade
        preferred = [
            "ggml-medium.bin",
            "ggml-medium-q5_0.gguf",
            "ggml-base.bin",
            "ggml-base-q5_1.gguf",
            "ggml-small.bin",
            "ggml-tiny.bin",
        ]
        for name in preferred:
            p = audio_dir / name
            if p.exists():
                return p

        # Qualquer .bin ou .gguf de Whisper que encontrar
        for ext in ("*.bin", "*.gguf"):
            matches = [f for f in audio_dir.glob(ext) if "ggml" in f.name.lower() or "whisper" in f.name.lower()]
            if matches:
                return sorted(matches)[0]

        return None

    def _convert_to_wav(self, input_path: Path, out_dir: Path) -> Path | None:
        """Converte áudio pra WAV 16kHz mono via ffmpeg, se disponível."""
        if input_path.suffix.lower() == ".wav":
            return input_path

        if not shutil.which("ffmpeg"):
            logger.warning("WhisperDriver: ffmpeg não encontrado — só .wav é suportado sem conversão.")
            return None

        out_path = out_dir / f"whisper_input_{input_path.stem}.wav"
        try:
            import subprocess
            r = subprocess.run(
                ["ffmpeg", "-y", "-i", str(input_path), "-ar", "16000", "-ac", "1", "-f", "wav", str(out_path)],
                capture_output=True, timeout=120
            )
            if r.returncode == 0 and out_path.exists():
                return out_path
            logger.error(f"WhisperDriver: ffmpeg falhou: {r.stderr.decode(errors='replace')[:200]}")
        except Exception as e:
            logger.error(f"WhisperDriver: ffmpeg erro: {e}")
        return None

    async def start(self, plan: ExecutionPlan | None = None) -> bool:
        return self._find_executable() is not None

    async def stop(self) -> bool:
        return True

    async def status(self) -> RuntimeStatus:
        state = RuntimeState.RUNNING if self._find_executable() else RuntimeState.STOPPED
        return RuntimeStatus(name=self.name, state=state)

    async def execute(self, plan: ExecutionPlan) -> ExecutionResult:
        started = datetime.now(_UTC)

        exe_path = self._find_executable()
        if not exe_path:
            return ExecutionResult(
                plan_id=plan.id, status=ExecutionStatus.FAILED,
                errors=["whisper-cli não encontrado. Compile whisper.cpp em repos/whisper.cpp/ "
                        "(cmake -B build -DGGML_VULKAN=ON && cmake --build build) "
                        "ou instale via PATH."]
            )

        model_path = self._find_model()
        if not model_path:
            # PHX-FIX (auditoria 2026-08-20, "Whisper model provisioning"):
            # a mensagem de erro tinha "B:/Phoenix/..." hardcoded - só por
            # coincidência batia com a instalação real onde esse bug foi
            # encontrado (o instalador escolheu B:\ como NVMe). Em qualquer
            # outra máquina (C:\, D:\, /home/...) a dica mostraria um
            # caminho que não existe nesse disco. Agora mostra o caminho
            # REAL resolvido por PhoenixPaths (o mesmo que _find_model()
            # acabou de checar) e o comando de reparo pronto pra colar.
            try:
                real_audio_dir = PhoenixPaths.get_category_path("Audio")
            except Exception:
                real_audio_dir = None
            dir_str = str(real_audio_dir) if real_audio_dir else "<workspace>/Models/Audio"
            return ExecutionResult(
                plan_id=plan.id, status=ExecutionStatus.FAILED,
                errors=[
                    f"Nenhum modelo Whisper encontrado em {dir_str}. "
                    f"A Phoenix já tenta baixar 'ggml-base.bin' sozinha em segundo plano no boot "
                    f"(ver Kernel._ensure_default_stt_model()) - se o download ainda não terminou, "
                    f"aguarde e tente de novo. Para baixar na mão agora: "
                    f'curl.exe -L "https://huggingface.co/ggerganov/whisper.cpp/resolve/main/ggml-base.bin" '
                    f'-o "{dir_str}/ggml-base.bin"'
                ]
            )

        audio_path_str = (plan.parameters or {}).get("audio_path", "")
        if not audio_path_str:
            return ExecutionResult(
                plan_id=plan.id, status=ExecutionStatus.FAILED,
                errors=["Parâmetro 'audio_path' ausente no plan.parameters."]
            )

        audio_path = Path(audio_path_str)
        if not audio_path.exists():
            return ExecutionResult(
                plan_id=plan.id, status=ExecutionStatus.FAILED,
                errors=[f"Arquivo de áudio não encontrado: {audio_path}"]
            )

        language = (plan.parameters or {}).get("language", "pt")
        # PHX-FIX (31/08, mesma investigação RX580/Vulkan que corrigiu
        # llama_cpp.py numa rodada anterior - regressão reintroduzida
        # nesta cópia): "threads=1" + env GPU forçado não tem NENHUM
        # self-test de correctness (só confere se o texto não veio vazio -
        # insuficiente nesta GPU, ver sanity_check() de llama_cpp.py) - a
        # política declarada em resident_manager.py (transcrição =
        # GPU_WITH_CPU_FALLBACK só porque whisper tem caminho CPU real e
        # testado) fica falsa enquanto este driver força GPU sem rede de
        # segurança. Revertido pro único caminho comprovadamente correto.
        threads = (plan.parameters or {}).get("threads", "4")

        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)

            # Converte pra WAV se necessário
            wav_path = self._convert_to_wav(audio_path, tmp_path)
            if wav_path is None:
                return ExecutionResult(
                    plan_id=plan.id, status=ExecutionStatus.FAILED,
                    errors=[f"Não foi possível converter '{audio_path.suffix}' pra WAV. "
                            "Instale ffmpeg ou use um arquivo .wav diretamente."]
                )

            output_txt = tmp_path / "output"
            cmd = [
                exe_path,
                "-m", str(model_path),
                "-f", str(wav_path),
                "-l", language,
                "-t", str(threads),
                "--output-txt",
                "-of", str(output_txt),
                "--no-timestamps",
            ]

            logger.info(f"WhisperDriver: Transcrevendo '{audio_path.name}' ({language}) com '{model_path.name}'...")
            try:
                process = await asyncio.create_subprocess_exec(
                    *cmd,
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.PIPE,
                )
                # Timeout: 10 min (arquivo de áudio longo + CPU)
                stdout, stderr = await asyncio.wait_for(process.communicate(), timeout=600)
            except asyncio.TimeoutError:
                try:
                    process.kill()
                except Exception:
                    pass
                return ExecutionResult(
                    plan_id=plan.id, status=ExecutionStatus.FAILED,
                    errors=["Timeout de 10 minutos na transcrição. Arquivo muito longo ou modelo muito grande."]
                )
            except Exception as e:
                return ExecutionResult(
                    plan_id=plan.id, status=ExecutionStatus.FAILED,
                    errors=[f"Erro ao executar whisper-cli: {e}"]
                )

            if process.returncode != 0:
                err = stderr.decode(errors="replace")[:400]
                return ExecutionResult(
                    plan_id=plan.id, status=ExecutionStatus.FAILED,
                    errors=[f"whisper-cli falhou (exit {process.returncode}): {err}"]
                )

            # Lê o arquivo de saída .txt
            txt_file = tmp_path / "output.txt"
            if txt_file.exists():
                transcription = txt_file.read_text(encoding="utf-8", errors="replace").strip()
            else:
                # Fallback: usa stdout
                transcription = stdout.decode(errors="replace").strip()

            if not transcription:
                return ExecutionResult(
                    plan_id=plan.id, status=ExecutionStatus.FAILED,
                    errors=["Transcrição vazia — arquivo de áudio sem fala ou modelo inadequado."]
                )

            logger.info(f"WhisperDriver: Transcrição concluída ({len(transcription)} chars).")
            return ExecutionResult(
                plan_id=plan.id,
                status=ExecutionStatus.SUCCESS,
                output=transcription,
                metrics={"audio_file": audio_path.name, "model": model_path.name, "language": language},
                started_at=started,
                finished_at=datetime.now(_UTC),
            )
