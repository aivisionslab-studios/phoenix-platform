"""
phoenix_kernel/models/hardware_fit.py

PHX-NEW (pedido do usuário 2026-08-22: "dois modelos de texto
conversando... um na cpu e outro na gpu... só funciona com modelos que
cabem na cpu com ram e gpu com vram (travar tentativa de rodarem modelos
com o dobro do tamanho porque não é split e sim modelos inteiros dentro
de cada hardware)"): checagem de "cabe inteiro ou não roda" ANTES de
subir um modelo pesado num hardware específico.

Diferente dos guards que já existem em resident_manager.py
(_thermal_guard/_vram_guard - avisam no log mas deixam continuar, de
propósito, porque decidir abortar é uma decisão do usuário, não do
Resident): este módulo é usado SÓ pela colaboração de dois modelos
(run_dual_model_collaboration_direct) e é um bloqueio DE VERDADE, porque
o usuário pediu isso explicitamente. Nunca tenta "fazer caber" um modelo
fatiando entre RAM e VRAM (isso seria split de camadas) - ou o modelo
inteiro cabe no hardware que vai rodá-lo, ou a colaboração nem começa.

Estimativa de necessidade de memória: não existe (e nunca existiu neste
projeto) um "ram_mb_estimate"/"vram_mb_estimate" MEDIDO de verdade para
modelo de texto - catalog/models.json tem vram_mb_estimate=0 para
chat/reasoning, de propósito ("roda em CPU por decisão de design"). A
única fonte honesta de tamanho disponível é o próprio arquivo .gguf em
disco. Aplicamos uma margem de overhead (KV cache, buffers de contexto)
sobre esse tamanho - não é uma medição exata (varia com o tamanho de
contexto/batch configurado), mas é conservadora o suficiente para
bloquear com segurança ANTES de tentar carregar, em vez de descobrir "não
coube" só depois de um OOM/crash do processo de inferência.
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

# Overhead sobre o tamanho do arquivo em disco para cobrir KV cache e
# buffers de contexto - ver aviso no docstring do módulo, é uma
# estimativa conservadora, não uma medição exata.
MODEL_MEMORY_OVERHEAD_FACTOR = 1.35

# PHX-NOTE: mesma matemática da "Regra 6.3GB VRAM" que já existe na UI da
# Aviary (ProcessLauncherBar.tsx, botão "Regra 6.3GB VRAM" - "8.0 GB VRAM
# Total - 1.2 GB Compute Buffer - 0.5 GB Folga = 6.3 GB Peso Máx.") -
# generalizada aqui para o VRAM total REAL detectado (não hardcoded em
# 8GB), em vez de reimplementar outra fórmula com números diferentes.
GPU_COMPUTE_BUFFER_MB = 1200
GPU_SAFETY_MARGIN_MB = 500

# Reserva mínima de RAM para o sistema operacional + o próprio Phoenix
# (kernel Python, Node/Aviary, etc.) continuarem respondendo - nunca
# oferece 100% da RAM "disponível" reportada pelo SO para o modelo.
RAM_SAFETY_RESERVE_MB = 2048


@dataclass
class FitCheckResult:
    fits: bool
    required_mb: int
    usable_mb: int
    detail: str


def estimate_model_memory_mb(model_path: Path) -> int:
    """Estima o consumo de memória de um modelo .gguf a partir do tamanho
    real do arquivo em disco + margem de overhead (ver docstring do
    módulo - é uma estimativa, não uma medição exata)."""
    size_mb = model_path.stat().st_size / (1024 * 1024)
    return int(size_mb * MODEL_MEMORY_OVERHEAD_FACTOR)


def check_ram_fit(required_mb: int) -> FitCheckResult:
    """Bloqueio de verdade (ao contrário dos guards de resident_manager.py
    que só avisam) - usa psutil.virtual_memory() para a RAM DISPONÍVEL
    agora (não o total da máquina)."""
    import psutil

    vm = psutil.virtual_memory()
    available_mb = int(vm.available / (1024 * 1024))
    usable_mb = max(0, available_mb - RAM_SAFETY_RESERVE_MB)
    fits = required_mb <= usable_mb
    detail = (
        f"modelo precisa de ~{required_mb}MB de RAM; disponível agora: {available_mb}MB "
        f"(reservando {RAM_SAFETY_RESERVE_MB}MB para o sistema - sobra útil: {usable_mb}MB)"
    )
    return FitCheckResult(fits=fits, required_mb=required_mb, usable_mb=usable_mb, detail=detail)


def check_vram_fit(required_mb: int, vram_total_mb: int | None, vram_used_mb: int | None) -> FitCheckResult:
    """Bloqueio de verdade para VRAM - mesma matemática da 'Regra 6.3GB
    VRAM' já conhecida da UI, generalizada para o VRAM total real
    detectado. Se o total de VRAM ainda não foi detectado (AHDE não
    reportou hardware ainda), trata como "não cabe" por segurança - nunca
    assume que cabe sem dado nenhum."""
    if vram_total_mb is None:
        return FitCheckResult(
            fits=False, required_mb=required_mb, usable_mb=0,
            detail="VRAM total desconhecida (hardware ainda não foi detectado) - não é seguro assumir que cabe",
        )
    used_mb = vram_used_mb or 0
    usable_mb = max(0, vram_total_mb - GPU_COMPUTE_BUFFER_MB - GPU_SAFETY_MARGIN_MB - used_mb)
    fits = required_mb <= usable_mb
    detail = (
        f"modelo precisa de ~{required_mb}MB de VRAM; VRAM total: {vram_total_mb}MB, já em uso: {used_mb}MB, "
        f"buffer de compute reservado: {GPU_COMPUTE_BUFFER_MB}MB, margem de segurança: {GPU_SAFETY_MARGIN_MB}MB "
        f"- sobra útil: {usable_mb}MB"
    )
    return FitCheckResult(fits=fits, required_mb=required_mb, usable_mb=usable_mb, detail=detail)
