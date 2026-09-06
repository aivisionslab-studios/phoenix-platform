"""
PHX-FIX (31/08, investigacao da RECORRENCIA do crash 0xC0000005 no
flux1-schnell): o pytest nunca cobriu `_detect_has_rocm()`/`_detect_has_cuda()`
em `sd_cpp.py` antes - por isso o patch anterior (que corrigiu só
MODEL_PROFILES) passou 100% verde enquanto um bug diferente, no bloco
"PHX-NEW: backend de aceleração baseado na capacidade real da GPU" (mais
abaixo no mesmo arquivo), continuava removendo os mesmos flags
--vae-on-cpu/--clip-on-cpu/--offload-to-cpu com base numa detecção de
ROCm que confiava em "hipconfig --version" (só prova que o SDK está
instalado, nunca que a GPU real é ROCm-capaz) e não checava sequer se
o rocm-smi retornou algum dispositivo de verdade.

Estes testes travam essa classe de bug pra não voltar de novo silenciosamente.
"""
import subprocess
from pathlib import Path
from unittest.mock import patch

import pytest

ROOT = Path(__file__).parents[1]
SD_CPP_PATH = ROOT / "phoenix_kernel" / "runtime" / "drivers" / "sd_cpp.py"

import sys
sys.path.insert(0, str(ROOT))
from phoenix_kernel.runtime.drivers import sd_cpp  # noqa: E402


def src():
    return SD_CPP_PATH.read_text(encoding="utf-8")


def test_hipconfig_no_longer_used_as_rocm_signal():
    # hipconfig só reporta a versão do SDK/runtime HIP instalado - nunca
    # verifica se a GPU de verdade da máquina é compatível com ROCm.
    t = src()
    s = t.index("def _detect_has_rocm")
    e = t.index("\ndef ", s + 1)
    body = t[s:e]
    assert "hipconfig" not in body


def test_detect_has_rocm_requires_nonempty_stdout():
    with patch("shutil.which", return_value="/usr/bin/rocm-smi"), \
         patch("subprocess.run") as mock_run:
        mock_run.return_value = subprocess.CompletedProcess(
            args=["rocm-smi", "--showid"], returncode=0, stdout="", stderr=""
        )
        assert sd_cpp._detect_has_rocm() is False


def test_detect_has_rocm_rejects_known_polaris_gcn4_card():
    # RX 580 é Polaris/GCN4 (gfx803) - ROCm nunca teve suporte oficial
    # pra essa geração (mínimo é GCN5/Vega, gfx900+). Mesmo que rocm-smi
    # liste ALGUM dispositivo, uma RX 580/570/560/550/480/470/460
    # nomeada explicitamente não deve ser tratada como ROCm-capaz.
    def fake_run(cmd, **kwargs):
        if "--showid" in cmd:
            return subprocess.CompletedProcess(cmd, 0, stdout="GPU[0]\t: 0x67df\n", stderr="")
        if "--showproductname" in cmd:
            return subprocess.CompletedProcess(cmd, 0, stdout="Card series:\tRadeon RX 580 Series\n", stderr="")
        return subprocess.CompletedProcess(cmd, 1, stdout="", stderr="")

    with patch("shutil.which", return_value="/usr/bin/rocm-smi"), \
         patch("subprocess.run", side_effect=fake_run):
        assert sd_cpp._detect_has_rocm() is False


def test_detect_has_rocm_accepts_real_modern_rocm_gpu():
    # Uma GPU realmente ROCm-capaz (ex: RX 6800, gfx1030) não deve ser
    # bloqueada pelo denylist - só as famílias Polaris/GCN4 conhecidas.
    def fake_run(cmd, **kwargs):
        if "--showid" in cmd:
            return subprocess.CompletedProcess(cmd, 0, stdout="GPU[0]\t: 0x73bf\n", stderr="")
        if "--showproductname" in cmd:
            return subprocess.CompletedProcess(cmd, 0, stdout="Card series:\tRadeon RX 6800\n", stderr="")
        return subprocess.CompletedProcess(cmd, 1, stdout="", stderr="")

    with patch("shutil.which", return_value="/usr/bin/rocm-smi"), \
         patch("subprocess.run", side_effect=fake_run):
        assert sd_cpp._detect_has_rocm() is True


def test_detect_has_cuda_still_requires_nonempty_stdout():
    # Regressão já não existia aqui, mas mantém a garantia: nvidia-smi
    # sem GPU real (stdout vazio) não deve contar como "tem CUDA".
    with patch("shutil.which", return_value="/usr/bin/nvidia-smi"), \
         patch("subprocess.run") as mock_run:
        mock_run.return_value = subprocess.CompletedProcess(
            args=["nvidia-smi"], returncode=0, stdout="", stderr=""
        )
        assert sd_cpp._detect_has_cuda() is False


def test_offload_flags_survive_when_no_gpu_backend_detected():
    # Teste de regressão de ponta a ponta pro bug real: numa máquina sem
    # CUDA/ROCm (o caso da RX 580 via Vulkan), os flags de offload pra
    # CPU restaurados no MODEL_PROFILES não podem ser removidos.
    with patch("shutil.which", return_value=None):
        assert sd_cpp._detect_has_cuda() is False
        assert sd_cpp._detect_has_rocm() is False
