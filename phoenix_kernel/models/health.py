"""
PHX-NEW (2026-08-22, pedido do usuário: "phoenix verifica se faltam llm pra
rodar e se faltar baixa novamente pra evitar erros e assim sempre
garantimos sucessos" + "já organizar api ou common pra verificar todos
modelos baixados"): único lugar que sabe responder duas perguntas sobre
QUALQUER modelo do catálogo:

  1. "esse arquivo está de fato pronto pra uso?" (existe E não é um
     download truncado/corrompido - checagem de TAMANHO MÍNIMO, não só
     Path.exists())
  2. "se não está, dispara o download certo em background sem travar quem
     perguntou"

Antes deste módulo, essa lógica (existe? tamanho mínimo? apaga se
corrompido? dispara download em background?) estava duplicada por
cópia-e-cola em Kernel._ensure_default_model() (LLM) e
Kernel._ensure_default_stt_model() (STT) em phoenix_kernel/kernel.py -
exatamente a MESMA classe de bug (lógica/lista copiada em vez de
compartilhada, saindo de sincronia com o tempo) já achada duas vezes nesta
auditoria em outro lugar (_IMAGE_ARCH_PATTERNS em resident_manager.py vs
MODEL_PROFILES em sd_cpp.py - duas listas de match separadas, uma
atualizada e a outra esquecida, causando dois bugs reais de produção:
confusão VAE/checkpoint e OOM de VRAM no SDXL).

Consolidado aqui e reaproveitado tanto pelo boot do Kernel (decide se
dispara download) quanto pelo novo endpoint GET /api/models/status em
api_server.py (só relata o estado, não baixa nada) - os dois enxergam
EXATAMENTE o mesmo critério de "pronto" ou "não pronto", pela mesma
função, então nunca mais podem divergir um do outro.
"""
from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass, asdict
from pathlib import Path
from typing import Awaitable, Callable, Optional

logger = logging.getLogger(__name__)


@dataclass
class ModelReadiness:
    ready: bool
    path: str
    exists: bool
    size_bytes: int
    min_valid_size_bytes: int
    corrupted_removed: bool = False

    def as_dict(self) -> dict:
        return asdict(self)


def check_model_file(path: Path, min_valid_size_bytes: int, *, remove_if_corrupted: bool = True) -> ModelReadiness:
    """Verifica se `path` existe E tem tamanho >= `min_valid_size_bytes`.

    Um download interrompido ou disco cheio deixa o arquivo PRESENTE, só
    que truncado - Path.exists() sozinho nunca detecta isso. Esse era
    exatamente o bug real da auditoria "Whisper model provisioning"
    (ggml-base.bin de 0 bytes tratado como cache válido pra sempre) -
    generalizado aqui pra qualquer modelo, não só Whisper.

    `remove_if_corrupted=False` (usado pelo endpoint de status, só-leitura)
    nunca apaga nada - só relata. `remove_if_corrupted=True` (usado pelo
    boot, que decide se rebaixa) remove o arquivo truncado antes de
    disparar o download de novo, mesmo comportamento que já existia nos
    dois métodos duplicados do Kernel.
    """
    if not path.exists():
        return ModelReadiness(ready=False, path=str(path), exists=False, size_bytes=0, min_valid_size_bytes=min_valid_size_bytes)

    size = path.stat().st_size
    if size >= min_valid_size_bytes:
        return ModelReadiness(ready=True, path=str(path), exists=True, size_bytes=size, min_valid_size_bytes=min_valid_size_bytes)

    corrupted_removed = False
    if remove_if_corrupted:
        try:
            path.unlink()
            corrupted_removed = True
        except Exception as e:
            logger.error(f"health.check_model_file: falha ao remover '{path}' corrompido ({size} bytes): {e}")

    return ModelReadiness(
        ready=False, path=str(path), exists=True, size_bytes=size,
        min_valid_size_bytes=min_valid_size_bytes, corrupted_removed=corrupted_removed,
    )


async def ensure_model_ready(
    *, label: str, path: Path, min_valid_size_bytes: int,
    trigger_download: Callable[[], Awaitable[object]],
    log_event: Optional[Callable[[str, str, str], None]] = None,
) -> bool:
    """Versão genérica de Kernel._ensure_default_model()/
    _ensure_default_stt_model(): usa check_model_file() e, se o modelo não
    estiver pronto, dispara `trigger_download()` em background
    (asyncio.create_task) SEM bloquear quem chamou - nunca trava o boot da
    API esperando um download de GBs terminar. Retorna True só quando o
    modelo já está pronto pra uso IMEDIATO; quem precisa esperar o
    download terminar usa o mesmo padrão de polling que
    Kernel._start_llm_engine_when_ready() já usa pro LLM."""
    readiness = check_model_file(path, min_valid_size_bytes, remove_if_corrupted=True)

    def _log(level: str, msg: str) -> None:
        print(f"[ModelHealth] {msg}")
        if log_event:
            log_event(level, "ModelHealth", msg)

    if readiness.ready:
        _log("INFO", f"{label} encontrado no disco ({readiness.size_bytes / 1e6:.1f} MB) - pronto.")
        return True

    if readiness.corrupted_removed:
        _log("WARNING", f"{label} encontrado mas incompleto/corrompido ({readiness.size_bytes} bytes) - removido, baixando de novo.")
    else:
        _log("WARNING", f"{label} ausente no disco. Iniciando download em background...")

    try:
        asyncio.create_task(trigger_download())
    except Exception as e:
        logger.error(f"health.ensure_model_ready: falha ao disparar download de '{label}': {e}")

    return False


# ---------------------------------------------------------------------------
# PHX-NEW: mapeamento EXPLÍCITO - não adivinhado por file_patterns - de cada
# id de catalog/models.json pro arquivo físico que ele resolve HOJE (mesmo
# caminho/nome que os dois sistemas de download reais já usam), mais o
# tamanho mínimo válido conhecido (confirmado via a própria API do
# HuggingFace, não chutado - ver LEIA-ME da entrega). Mantido à mão de
# propósito: ModelManager (catalog/downloads.json) e AssetManager
# (catalog/assets/*.json) têm esquemas de path/schema DIFERENTES demais pra
# derivar isso com segurança sem arriscar apontar pro arquivo errado -
# mesmo tipo de risco que já causou os dois bugs de underscore desta
# auditoria. Só cobre os IDs que já têm uma fonte de download REAL e
# funcionando no projeto (vision/minicpmv e speech_synthesis/piper NÃO
# entram aqui de propósito - não têm um AssetManager/ModelManager
# equivalente hoje, são providos por setup_vision.py/install/common.ps1,
# um instalador separado e não uma checagem de boot; ver LEIA-ME).
KNOWN_MODEL_FILES: dict[str, dict] = {
    "qwen3:8b": {
        "category": "Chat", "subcategory": "GGUF", "filename": "qwen3-8b-q4_k_m.gguf",
        "min_valid_size_bytes": 1_000_000_000,  # real Q4_K_M do Qwen3-8B: ~4.5-5GB
        "role": "chat/reasoning (texto)", "downloader": "ModelManager('qwen3:8b')",
    },
    "whisper-base": {
        "category": "Audio", "subcategory": None, "filename": "ggml-base.bin",
        "min_valid_size_bytes": 100_000_000,  # real: ~148MB
        "role": "speech_to_text", "downloader": "ModelManager('whisper-base')",
    },
    "sdxl": {
        "category": "Image", "subcategory": None, "filename": "sd_xl_base_1.0.safetensors",
        "min_valid_size_bytes": 4_000_000_000,  # real (HF API, stabilityai/stable-diffusion-xl-base-1.0): 6_938_078_334 bytes
        "role": "image_generation (default)", "downloader": "AssetManager.get_asset('sdxl')",
    },
    "sd15": {
        "category": "Image", "subcategory": None, "filename": "sd15-v1-5-pruned-emaonly.safetensors",
        "min_valid_size_bytes": 3_500_000_000,  # real (HF API, stable-diffusion-v1-5/stable-diffusion-v1-5): 4_265_146_304 bytes
        "role": "image_generation (alternativa, mais leve)", "downloader": "AssetManager.get_asset('sd15')",
    },
}


def full_inventory() -> list[dict]:
    """Cruza KNOWN_MODEL_FILES com o disco de verdade, usando o MESMO
    check_model_file() que o boot do Kernel usa pra decidir se rebaixa -
    exposto pro endpoint GET /api/models/status (só-leitura: nunca apaga
    nem baixa nada, `remove_if_corrupted=False`)."""
    from phoenix_kernel.paths import PhoenixPaths

    rows = []
    for model_id, spec in KNOWN_MODEL_FILES.items():
        path = PhoenixPaths.get_category_path(spec["category"], spec.get("subcategory")) / spec["filename"]
        readiness = check_model_file(path, spec["min_valid_size_bytes"], remove_if_corrupted=False)
        rows.append({
            "id": model_id,
            "role": spec["role"],
            "downloader": spec["downloader"],
            **readiness.as_dict(),
        })
    return rows
