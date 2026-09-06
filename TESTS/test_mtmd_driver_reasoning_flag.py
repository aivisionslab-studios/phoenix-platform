"""Teste: MtmdDriver desliga --reasoning explicitamente na chamada do
llama-mtmd-cli.

PHX-FIX (2026-09-06, achado real lendo o guia oficial de deploy do
MiniCPM-V 4.6 - OpenSQZ/MiniCPM-V-CookBook): builds recentes do llama.cpp
(pós PR #20606) ativam --reasoning=auto por padrão. O checkpoint Instruct
do MiniCPM-V 4.6 nunca emite bloco <think>, mas o chat template dele ativa
"pensamento" mesmo assim - sem desligar explicitamente, a saída sai
quebrada/corrompida (aviso oficial: "Always pass --reasoning off
explicitly on Instruct inference commands").
"""
import asyncio
import tempfile
from pathlib import Path
from unittest.mock import AsyncMock, patch

from core.domain.execution import ExecutionStatus

from core.domain.execution import ExecutionPlan
from phoenix_kernel.runtime.drivers.mtmd_driver import MtmdDriver


def _make_plan(**params) -> ExecutionPlan:
    return ExecutionPlan(
        id="test-plan", runtime="vision", model="minicpmv",
        parameters=params, reasoning="teste",
    )


def test_command_includes_reasoning_off():
    """A flag --reasoning off tem que estar presente no comando montado,
    logo após o valor 'off' correspondente."""
    driver = MtmdDriver()
    tmp_image = Path(tempfile.mkdtemp()) / "foto.png"
    tmp_image.write_bytes(b"fake")

    captured_cmd = {}

    class _FakeProcess:
        returncode = 0
        async def communicate(self):
            return (b"Texto transcrito.", b"")

    async def _fake_subprocess_exec(*cmd, **kwargs):
        captured_cmd["cmd"] = list(cmd)
        return _FakeProcess()

    with patch.object(driver, "_find_executable", return_value="/fake/llama-mtmd-cli"), \
         patch.object(driver, "_find_model_file", return_value=Path("/fake/model.gguf")), \
         patch.object(driver, "_find_mmproj_file", return_value=(Path("/fake/mmproj.gguf"), None)), \
         patch("asyncio.create_subprocess_exec", new=AsyncMock(side_effect=_fake_subprocess_exec)):
        plan = _make_plan(image_path=str(tmp_image), prompt="Descreva.")
        asyncio.run(driver.execute(plan))

    cmd = captured_cmd["cmd"]
    assert "--reasoning" in cmd, f"--reasoning ausente do comando: {cmd}"
    idx = cmd.index("--reasoning")
    assert cmd[idx + 1] == "off", f"--reasoning deveria ser seguido de 'off', veio: {cmd[idx + 1]}"


def test_context_size_matches_official_guidance():
    """Guia oficial recomenda -c 8192 para o MiniCPM-V 4.6 (modelo bem
    menor que a versão 2.6 anterior, comporta contexto maior sem custo
    proibitivo)."""
    driver = MtmdDriver()
    tmp_image = Path(tempfile.mkdtemp()) / "foto.png"
    tmp_image.write_bytes(b"fake")

    captured_cmd = {}

    class _FakeProcess:
        returncode = 0
        async def communicate(self):
            return (b"Texto.", b"")

    async def _fake_subprocess_exec(*cmd, **kwargs):
        captured_cmd["cmd"] = list(cmd)
        return _FakeProcess()

    with patch.object(driver, "_find_executable", return_value="/fake/llama-mtmd-cli"), \
         patch.object(driver, "_find_model_file", return_value=Path("/fake/model.gguf")), \
         patch.object(driver, "_find_mmproj_file", return_value=(Path("/fake/mmproj.gguf"), None)), \
         patch("asyncio.create_subprocess_exec", new=AsyncMock(side_effect=_fake_subprocess_exec)):
        plan = _make_plan(image_path=str(tmp_image), prompt="Descreva.")
        asyncio.run(driver.execute(plan))

    cmd = captured_cmd["cmd"]
    assert "-c" in cmd
    idx = cmd.index("-c")
    assert cmd[idx + 1] == "8192", f"-c deveria ser 8192, veio: {cmd[idx + 1]}"


def test_retries_without_reasoning_flag_when_binary_does_not_support_it():
    """PHX-FIX (2026-09-06, achado real do usuário, com print de tela em
    produção): o mtmd-cli real dessa máquina rejeitou --reasoning com
    'error: invalid argument: --reasoning' (exit 1) - a suposição de que
    o binário já compilado suportava a flag estava errada na prática, e
    isso derrubou TODA análise de imagem e OCR. O driver tem que detectar
    esse erro específico e tentar de novo sem a flag, nunca falhar por
    completo por causa disso."""
    driver = MtmdDriver()
    tmp_image = Path(tempfile.mkdtemp()) / "foto.png"
    tmp_image.write_bytes(b"fake")

    captured_cmds = []
    call_count = {"n": 0}

    class _FakeProcessInvalidArg:
        returncode = 1
        async def communicate(self):
            return (b"", b"error: invalid argument: --reasoning\n")

    class _FakeProcessSuccess:
        returncode = 0
        async def communicate(self):
            return (b"Uma bela paisagem com montanhas.", b"")

    async def _fake_subprocess_exec(*cmd, **kwargs):
        captured_cmds.append(list(cmd))
        call_count["n"] += 1
        if call_count["n"] == 1:
            return _FakeProcessInvalidArg()  # binário real: rejeita --reasoning
        return _FakeProcessSuccess()  # segunda tentativa, sem a flag, funciona

    with patch.object(driver, "_find_executable", return_value="/fake/llama-mtmd-cli"), \
         patch.object(driver, "_find_model_file", return_value=Path("/fake/model.gguf")), \
         patch.object(driver, "_find_mmproj_file", return_value=(Path("/fake/mmproj.gguf"), None)), \
         patch("asyncio.create_subprocess_exec", new=AsyncMock(side_effect=_fake_subprocess_exec)):
        plan = _make_plan(image_path=str(tmp_image), prompt="Descreva.")
        result = asyncio.run(driver.execute(plan))

    assert call_count["n"] == 2, "deveria ter tentado exatamente 2 vezes (com a flag, depois sem)"
    assert "--reasoning" in captured_cmds[0], "primeira tentativa deve incluir a flag (pega o benefício quando suportada)"
    assert "--reasoning" not in captured_cmds[1], "segunda tentativa NÃO deve incluir a flag (binário não suporta)"
    assert result.status == ExecutionStatus.SUCCESS
    assert result.output == "Uma bela paisagem com montanhas."


def test_does_not_retry_for_unrelated_errors():
    """Um erro qualquer (não relacionado a --reasoning) não deve disparar
    a segunda tentativa - só o caso específico de argumento não
    reconhecido."""
    driver = MtmdDriver()
    tmp_image = Path(tempfile.mkdtemp()) / "foto.png"
    tmp_image.write_bytes(b"fake")

    call_count = {"n": 0}

    class _FakeProcessOtherError:
        returncode = 1
        async def communicate(self):
            return (b"", b"error: model file not found or corrupted\n")

    async def _fake_subprocess_exec(*cmd, **kwargs):
        call_count["n"] += 1
        return _FakeProcessOtherError()

    with patch.object(driver, "_find_executable", return_value="/fake/llama-mtmd-cli"), \
         patch.object(driver, "_find_model_file", return_value=Path("/fake/model.gguf")), \
         patch.object(driver, "_find_mmproj_file", return_value=(Path("/fake/mmproj.gguf"), None)), \
         patch("asyncio.create_subprocess_exec", new=AsyncMock(side_effect=_fake_subprocess_exec)):
        plan = _make_plan(image_path=str(tmp_image), prompt="Descreva.")
        result = asyncio.run(driver.execute(plan))

    assert call_count["n"] == 1, "erro não relacionado a --reasoning não deve disparar segunda tentativa"
    assert result.status == ExecutionStatus.FAILED
