# api_server.py

import os
import sys
import time
import platform
import threading
import webbrowser
import importlib
import base64
import uuid
import shutil
import subprocess
import logging
from dataclasses import asdict, is_dataclass
from enum import Enum
from contextlib import asynccontextmanager
from fastapi import FastAPI, UploadFile, File, Form, HTTPException, Request
from fastapi.responses import FileResponse
from pathlib import Path
from pydantic import BaseModel
from phoenix_kernel.kernel import PhoenixKernel
from phoenix_kernel.cloud_sync import has_consent, grant_consent, revoke_consent
from phoenix_kernel.orchestration.execution_arbiter import default_execution_arbiter

# PHX-NEW (2026-08-22, endpoint /api/models/status): este arquivo já
# importava `logging` mas nunca criava um logger de módulo - cada rota que
# precisava logar usava print() ou self.logs.add_event() via kernel. Um
# logger próprio, mesmo padrão de todo o resto do phoenix_kernel/.
logger = logging.getLogger(__name__)
# PHX-FIX (auditoria 2026-08-20, "ResidentManager não pode ser contornado"
# — Seção 3): ExecutionPlan/ExecutionStatus eram importados aqui pra
# montar planos direto em /api/synthesize-speech e /api/benchmark,
# pulando o ResidentManager. As duas rotas agora chamam bridges dedicados
# do Resident (generate_speech_direct/run_token_benchmark_direct), que já
# montam o ExecutionPlan por dentro — nada neste arquivo usa mais esses
# dois nomes diretamente.

# Importa o core de telemetria dinamicamente
hardware_core = importlib.import_module("phoenix_kernel.telemetry.core")

LICENSE_PATH = "LICENSE.md"
LICENSE_ACCEPTED_FLAG = "data/license_accepted.flag"

# PHX-RAG PRODUCT POLICY (2026-08-27)
# Fonte única de verdade em phoenix_kernel/licensing/plans.py.
from phoenix_kernel.licensing.plans import get_rag_limits
from phoenix_kernel.licensing.commercial_guard import (
    invalidate_capability_cache,
    security_status as capability_security_status,
)


def _current_rag_limits() -> dict:
    return get_rag_limits()


def _json_safe(value):
    """Converte dataclasses/enums do AHDE em JSON sem fabricar dados."""
    if is_dataclass(value):
        return _json_safe(asdict(value))
    if isinstance(value, Enum):
        return value.name
    if isinstance(value, dict):
        return {str(k): _json_safe(v) for k, v in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [_json_safe(v) for v in value]
    return value


def _ahde_device_category(device_type: str) -> str:
    name = (device_type or "").lower()
    if "cpu" in name: return "cpu"
    if "gpu" in name: return "gpu"
    if "memory" in name or "ram" in name: return "memory"
    if any(part in name for part in ("storage", "disk", "hdd", "ssd", "nvme")): return "storage"
    return "motherboard"


def _normalize_ahde_devices(raw_devices: list | None) -> list[dict]:
    """Adapta a saída real de telemetry.core ao contrato do painel web."""
    normalized = []
    for device_index, raw_device in enumerate(raw_devices or []):
        device = raw_device if isinstance(raw_device, dict) else {}
        name = str(device.get("name") or f"Device {device_index + 1}")
        device_type = str(device.get("type") or "Unknown")
        category = _ahde_device_category(device_type)
        sensors = []
        for sensor_index, raw_sensor in enumerate(device.get("sensors") or []):
            sensor = raw_sensor if isinstance(raw_sensor, dict) else {}
            sensor_name = str(sensor.get("name") or f"Sensor {sensor_index + 1}")
            sensors.append({
                "id": f"{device_index}:{sensor_index}:{sensor_name}",
                "name": sensor_name,
                "category": category,
                "type": str(sensor.get("type") or "Status"),
                "value": sensor.get("value", "indisponível"),
                "unit": sensor.get("unit", ""),
                "min": sensor.get("min"),
                "max": sensor.get("max"),
                "criticalThreshold": sensor.get("criticalThreshold"),
                "warningThreshold": sensor.get("warningThreshold"),
                "device": name,
                "updatedAt": sensor.get("updatedAt"),
            })
        normalized.append({
            "name": name,
            "type": device_type,
            "vendor": device.get("vendor"),
            "model": device.get("model"),
            "category": category,
            "sensors": sensors,
        })
    return normalized


def _read_normalized_ahde_devices() -> list[dict]:
    return _normalize_ahde_devices(hardware_core.get_all_hardware_sensors())


# PHX-FIX: Nova sintaxe de Lifespan do FastAPI (resolve o DeprecationWarning)
@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup
    await kernel.boot()
    yield
    # Shutdown
    await kernel.shutdown()

app = FastAPI(title="Phoenix Engine API", version="4.5.0", lifespan=lifespan)
kernel = PhoenixKernel()
app.start_time = time.monotonic()

# PHX-NEW 2026-08-30 — PRIMEIRO PORTÃO.
# Esta middleware roda ANTES dos handlers antigos. Ela não consome body/multipart;
# faz apenas o claim estrutural pela rota. Rotas que não pertencem ao árbitro
# recebem NOT_CLAIMED e o código legado está explicitamente liberado.
@app.middleware("http")
async def execution_arbiter_first_gate(request: Request, call_next):
    decision = default_execution_arbiter.preflight_path(request.url.path, request.method)
    request.state.execution_arbiter_preflight = decision
    if decision.claimed:
        logger.debug(
            "ExecutionArbiter FIRST_GATE CLAIMED path=%s intent=%s resource=%s",
            request.url.path, decision.intent, decision.resource_policy.value,
        )
    else:
        logger.debug(
            "ExecutionArbiter FIRST_GATE NOT_CLAIMED path=%s — legado liberado",
            request.url.path,
        )
    return await call_next(request)


class IntentInterceptReq(BaseModel):
    text: str = ""
    attachments: list[dict] = []
    requested_operation: str = ""
    output_format: str = ""
    source_chars: int = 0
    max_tokens: int | None = None
    unlimited_output: bool = False
    use_web: bool = False
    runtime_hint: str = ""


@app.post("/api/intent/intercept")
async def intent_intercept(req: IntentInterceptReq):
    """Diagnóstico/cliente do árbitro. NOT_CLAIMED significa: fluxo legado pode seguir."""
    decision = default_execution_arbiter.intercept(
        req.text, attachments=req.attachments,
        requested_operation=req.requested_operation or None,
        output_format=req.output_format or None, source_chars=req.source_chars,
        max_tokens=req.max_tokens, unlimited_output=req.unlimited_output,
        use_web=req.use_web, runtime_hint=req.runtime_hint or None,
    )
    return decision.to_dict()

@app.get("/")
async def get_index():
    # PHX-FIX: a pasta web/ foi removida. O frontend agora roda em
    # platform_source/ (porta 3000, servidor Node/Vite). O api_server.py
    # (porta 8000) é exclusivamente API — redireciona pro Aviary.
    from fastapi.responses import RedirectResponse
    return RedirectResponse(url="http://localhost:3000", status_code=302)

@app.get("/health")
async def health_check():
    """Endpoint de Health Check para o Bootstrapper."""
    return {
        "status": "healthy",
        "version": "4.5.0",
        "python": platform.python_version(),
        "engine": "Phoenix",
        "uptime": time.monotonic() - app.start_time
    }

@app.get("/api/state")
async def get_state():
    state_data = await kernel.state.get_state()
    if "error" in state_data:
        raise HTTPException(status_code=503, detail=state_data["error"])
    return state_data

# PHX-NEW (2026-08-22, achado real via relato do usuário: "baixei
# DeepSeek-R1-Distill-Qwen-7B-Q6_K.gguf, mas nao consigo usar porque nao
# aparece na phoenix" - o arquivo já estava na pasta certa, Models/Chat/
# GGUF, ao lado do qwen3-8b-q4_k_m.gguf que aparecia normalmente):
# investigando, o ModelScanner (phoenix_kernel/models/model_scanner.py) já
# varre esse diretório certinho e já inclui o arquivo novo em
# ModelScanner.scan_all() - isso já ia parar em /api/state (campo
# "models", via ModelsEngine.get_model_and_rag_status()) e depois em
# /api/engine/models (campo "phoenixModels" do server.ts). O problema é
# que AviaryApp.tsx (handleScanAllProviders) NUNCA lê "phoenixModels" -
# só reage a "ollamaModels"/"lmstudioModels"/"llamaServerModels", que vêm
# de perguntar pro llama-server QUAL MODELO ELE JÁ TEM CARREGADO AGORA
# (via /v1/models dele, porta 8081) - não uma varredura de disco. Como o
# llama-server só roda UM modelo por vez (LlamaCppDriver inicia com
# `-m <arquivo> --alias <nome>`, nunca com `--models-dir`), só o modelo
# que já foi carregado alguma vez nesta sessão aparece - um arquivo novo,
# nunca carregado, fica invisível no seletor do Chat e do Arena mesmo
# estando 100% certo no disco.
#
# Esse endpoint expõe só os arquivos REALMENTE utilizáveis como modelo de
# chat pelo llama-server: categoria "Chat", formato GGUF, e EXCLUINDO
# arquivos "mmproj-*" (o projetor de visão de um modelo multimodal, ex.
# MiniCPM-V - não é um modelo de chat sozinho; carregá-lo com `-m` faria o
# llama-server falhar). O nome devolvido (stem do arquivo) é exatamente o
# que LlamaCppDriver._find_model_file() já sabe casar de volta pro
# arquivo certo (glob case-insensitive por substring), então selecionar
# um destes nomes no Chat/Arena e mandar uma mensagem já é suficiente
# pra carregar o modelo de verdade - nenhuma mudança no motor de carga,
# só no que fica visível pra escolher.
@app.get("/api/models/chat-gguf")
async def get_chat_gguf_models():
    try:
        from phoenix_kernel.models.model_scanner import ModelScanner
        records = ModelScanner.scan_all()
    except Exception as e:
        logger.warning(f"/api/models/chat-gguf: falha ao escanear disco: {e}")
        return {"models": []}

    names = sorted({
        r["name"] for r in records
        if r.get("category") == "Chat"
        and r.get("format") == "GGUF"
        and "mmproj" not in r.get("name", "").lower()
    })
    return {"models": names}

# PHX-NEW (2026-08-22, pedido do usuário: "api ou common baixar alguns
# modelos pra pasta padrão dos modelos compatíveis com llama e ollama" -
# depois de descobrir, junto com o achado acima, que baixar um .gguf na
# mão via PowerShell/huggingface_hub CLI era a única forma de conseguir um
# modelo novo até agora): um jeito de baixar, DE DENTRO do Phoenix, um
# .gguf real pra pasta certa (Models/Chat/GGUF) sem precisar mexer em
# PowerShell. Só um preset pequeno e curado de modelos REAIS (nada
# inventado - repo_id/filename abaixo foram conferidos direto no Hugging
# Face antes de entrar aqui), pensados pro hardware relatado pelo usuário
# nesta mesma sessão (RX 580 8GB, ~5.5GB de VRAM útil - qwen3-8b-q4_k_m
# sozinho já não cabia com folga, então os dois presets abaixo são
# deliberadamente menores que isso, pra sobrar espaço pro lado GPU de uma
# Colaboração de dois modelos).
#
# Todo arquivo baixado aqui é um .gguf padrão - funciona em QUALQUER motor
# que fale esse formato (llama.cpp/llama-server, LM Studio, e também
# Ollama via `ollama create -f Modelfile <caminho>`, que empacota um GGUF
# solto num modelo Ollama). Este endpoint não automatiza esse empacotamento
# do Ollama (o próprio Phoenix já prioriza llama-server sobre Ollama desde
# o PHX-FIX anterior "evita erros" citado no chat) - o arquivo cai pronto
# pro llama-server nativo, que é o motor que a Colaboração e o Chat já
# usam por padrão.
#
# Download roda em thread de fundo porque um .gguf de alguns GB pode levar
# minutos numa conexão doméstica - o job é consultado por polling
# (/api/models/download/status), nunca held numa única requisição HTTP
# longa demais pra sobreviver a um proxy/timeout de navegador.
RECOMMENDED_CHAT_MODELS = {
    "gemma4-12b-qat-q4_0": {
        "repo_id": "google/gemma-4-12B-it-qat-q4_0-gguf",
        "filename": "gemma-4-12b-it-qat-q4_0.gguf",
        "label": "Gemma 4 12B IT QAT (Q4_0, 6.98GB)",
        "note": (
            "Google Gemma 4 12B Instruct com Quantization-Aware Training em Q4_0. "
            "Recomendado para comparação com o Qwen3 8B em documentos, pesquisa web, "
            "raciocínio e respostas longas. Compatível com llama.cpp. Na RX 580 8GB, "
            "preservar a política conservadora de CPU/híbrido da Phoenix."
        ),
        "sha256": "93567e57a8fe10b23569b9d9ec38cd005deedf71e29477c421a4b83f418a538b",
        "size_bytes": 6980000000,
        "compare_with": "qwen3-8b-q4_k_m.gguf",
    },
    "qwen3-4b-q4km": {
        "repo_id": "unsloth/Qwen3-4B-GGUF",
        "filename": "Qwen3-4B-Q4_K_M.gguf",
        "label": "Qwen3 4B (Q4_K_M, ~2.5GB)",
        "note": "Rápido e leve - cabe com folga na GPU de 8GB, ótimo pro lado GPU de uma Colaboração de dois modelos.",
    },
    "deepseek-r1-distill-qwen-7b-q3km": {
        "repo_id": "bartowski/DeepSeek-R1-Distill-Qwen-7B-GGUF",
        "filename": "DeepSeek-R1-Distill-Qwen-7B-Q3_K_M.gguf",
        "label": "DeepSeek-R1-Distill-Qwen-7B (Q3_K_M, ~3.8GB)",
        "note": "Focado em raciocínio - ainda cabe na GPU de 8GB, mais pesado que o Qwen3 4B acima.",
    },
}

_download_jobs: dict = {}
_download_jobs_lock = threading.Lock()

@app.get("/api/models/recommended-downloads")
async def get_recommended_downloads():
    try:
        from phoenix_kernel.models.model_scanner import ModelScanner
        disk_names = {r["name"].lower() for r in ModelScanner.scan_all()}
    except Exception as e:
        logger.warning(f"/api/models/recommended-downloads: falha ao escanear disco: {e}")
        disk_names = set()

    items = []
    for key, info in RECOMMENDED_CHAT_MODELS.items():
        stem = Path(info["filename"]).stem
        items.append({
            "key": key,
            "label": info["label"],
            "note": info["note"],
            "repo_id": info["repo_id"],
            "filename": info["filename"],
            "already_downloaded": stem.lower() in disk_names,
            "size_bytes": info.get("size_bytes"),
            "sha256": info.get("sha256"),
            "compare_with": info.get("compare_with"),
        })
    return {"models": items}


class DownloadModelRequest(BaseModel):
    key: str


@app.post("/api/models/download")
async def start_model_download(body: DownloadModelRequest):
    info = RECOMMENDED_CHAT_MODELS.get(body.key)
    if info is None:
        raise HTTPException(status_code=404, detail=f"'{body.key}' não é um dos modelos recomendados conhecidos.")

    from phoenix_kernel.paths import PhoenixPaths
    dest_dir = PhoenixPaths.get_category_path("Chat", "GGUF")
    dest_path = dest_dir / info["filename"]
    # PHX-FIX: sem esta checagem, clicar duas vezes em "Baixar" (ou baixar
    # de novo depois de já ter o arquivo) reiniciaria o download do zero -
    # um arquivo de alguns GB já presente e íntegro (>10MB é suficiente pra
    # distinguir de um download travado/incompleto) não precisa ser baixado
    # de novo.
    if dest_path.exists() and dest_path.stat().st_size > 10 * 1024 * 1024:
        return {"ok": True, "already_downloaded": True, "job_id": None, "path": str(dest_path)}

    job_id = uuid.uuid4().hex
    with _download_jobs_lock:
        _download_jobs[job_id] = {
            "status": "downloading",
            "key": body.key,
            "filename": info["filename"],
            "error": None,
            "path": None,
            "started_at": time.monotonic(),
        }

    def worker():
        try:
            try:
                import huggingface_hub
            except ImportError:
                # PHX-NEW: mesmo padrão já usado em
                # phoenix_kernel/services/provisioning.py::_install_pip -
                # tenta instalar sozinho antes de desistir, pra não obrigar
                # o usuário a abrir um terminal só pra isso.
                result = subprocess.run(
                    [sys.executable, "-m", "pip", "install", "-U", "huggingface_hub"],
                    capture_output=True, text=True, timeout=120,
                )
                if result.returncode != 0:
                    raise RuntimeError(
                        "huggingface_hub não estava instalado e a instalação automática falhou "
                        f"(código {result.returncode}): {(result.stderr or result.stdout).strip()[:500]} "
                        "- rode manualmente: pip install -U huggingface_hub"
                    )
                import huggingface_hub  # tenta de novo, agora deve existir

            dest_dir.mkdir(parents=True, exist_ok=True)
            downloaded_path = huggingface_hub.hf_hub_download(
                repo_id=info["repo_id"], filename=info["filename"], local_dir=str(dest_dir),
            )
            with _download_jobs_lock:
                _download_jobs[job_id]["status"] = "done"
                _download_jobs[job_id]["path"] = str(downloaded_path)
        except Exception as e:
            with _download_jobs_lock:
                _download_jobs[job_id]["status"] = "error"
                _download_jobs[job_id]["error"] = str(e)

    threading.Thread(target=worker, daemon=True).start()
    return {"ok": True, "already_downloaded": False, "job_id": job_id}


@app.get("/api/models/download/status")
async def get_model_download_status(job_id: str):
    with _download_jobs_lock:
        job = _download_jobs.get(job_id)
        if job is None:
            raise HTTPException(status_code=404, detail="job_id desconhecido (expirou ou o backend reiniciou).")
        job_copy = dict(job)
    job_copy["elapsed_seconds"] = round(time.monotonic() - job_copy["started_at"], 1)
    return job_copy

# PHX-NEW (2026-08-23, pedido do usuário: "achei que a phoenix instalaria o
# programa" - ele viu a tela "Documento -> Audiolivro" recusar com uma
# mensagem mandando baixar 2 arquivos manualmente no GitHub e colar numa
# pasta, e esperava que a Phoenix baixasse sozinha, como já faz pra outros
# modelos - ex: SD1.5/SDXL/Whisper via AssetManager + catalog/assets/*.json).
# Kokoro precisa de DOIS arquivos (kokoro-v1.0.onnx ~310MB + voices-v1.0.bin
# ~27MB, catálogos novos: catalog/assets/kokoro_model.json e
# kokoro_voices.json) - por isso não dá pra reaproveitar o endpoint
# /api/models/download (que baixa 1 arquivo .gguf por vez via
# huggingface_hub). Reaproveita sim o AssetManager já existente
# (kernel.resident.asset_manager) pela lógica de download em si (cache se já
# existe, escreve em .part antes de renomear, erros HTTP estruturados) - só
# o "job" de progresso e o endpoint são novos, no mesmo padrão de
# thread-de-fundo + polling do bloco de download de GGUF acima (2 arquivos
# de ~340MB juntos podem legitimamente levar minutos numa conexão doméstica,
# não dá pra segurar numa única requisição HTTP).
_kokoro_download_jobs: dict = {}
_kokoro_download_jobs_lock = threading.Lock()


@app.get("/api/tts/kokoro/status")
async def get_kokoro_install_status():
    from phoenix_kernel.runtime.drivers.kokoro_tts import get_kokoro_engine
    engine = get_kokoro_engine()
    return {"installed": engine.is_installed()}


@app.post("/api/tts/kokoro/download")
async def start_kokoro_download():
    from phoenix_kernel.runtime.drivers.kokoro_tts import get_kokoro_engine
    if get_kokoro_engine().is_installed():
        return {"ok": True, "already_downloaded": True, "job_id": None}

    job_id = uuid.uuid4().hex
    with _kokoro_download_jobs_lock:
        _kokoro_download_jobs[job_id] = {
            "status": "downloading",
            "phase": "Baixando modelo Kokoro-82M (1/2, ~310MB)...",
            "error": None,
            "started_at": time.monotonic(),
        }

    def worker():
        asset_manager = kernel.resident.asset_manager
        try:
            model_path = asset_manager.get_asset("kokoro_model")
            if not model_path:
                reason = asset_manager.last_error or "falha desconhecida ao baixar o modelo Kokoro."
                with _kokoro_download_jobs_lock:
                    _kokoro_download_jobs[job_id]["status"] = "error"
                    _kokoro_download_jobs[job_id]["error"] = reason
                return

            with _kokoro_download_jobs_lock:
                _kokoro_download_jobs[job_id]["phase"] = "Baixando banco de vozes Kokoro (2/2, ~27MB)..."

            voices_path = asset_manager.get_asset("kokoro_voices")
            if not voices_path:
                reason = asset_manager.last_error or "falha desconhecida ao baixar o banco de vozes Kokoro."
                with _kokoro_download_jobs_lock:
                    _kokoro_download_jobs[job_id]["status"] = "error"
                    _kokoro_download_jobs[job_id]["error"] = reason
                return

            with _kokoro_download_jobs_lock:
                _kokoro_download_jobs[job_id]["status"] = "done"
                _kokoro_download_jobs[job_id]["phase"] = "Concluído."
        except Exception as e:
            with _kokoro_download_jobs_lock:
                _kokoro_download_jobs[job_id]["status"] = "error"
                _kokoro_download_jobs[job_id]["error"] = str(e)

    threading.Thread(target=worker, daemon=True).start()
    return {"ok": True, "already_downloaded": False, "job_id": job_id}


@app.get("/api/tts/kokoro/download/status")
async def get_kokoro_download_status(job_id: str):
    with _kokoro_download_jobs_lock:
        job = _kokoro_download_jobs.get(job_id)
        if job is None:
            raise HTTPException(status_code=404, detail="job_id desconhecido (expirou ou o backend reiniciou).")
        job_copy = dict(job)
    job_copy["elapsed_seconds"] = round(time.monotonic() - job_copy["started_at"], 1)
    return job_copy


@app.get("/api/chat/pending")
async def get_pending_chat_messages():
    messages = kernel.resident.pending_chat_messages
    kernel.resident.pending_chat_messages = []
    return {"messages": messages}

@app.get("/api/hardware/all")
async def get_hardware_all():
    try:
        devices = hardware_core.get_all_hardware_sensors()
        return {"devices": devices}
    except Exception as e:
        return {"devices": [], "error": str(e)}


@app.get("/api/ahde/sensors")
async def get_ahde_sensors():
    """Sensores reais, normalizados para o contrato do Hardware Drawer."""
    try:
        return {"devices": _read_normalized_ahde_devices()}
    except Exception as e:
        logger.warning("/api/ahde/sensors: falha na leitura: %s", e)
        raise HTTPException(status_code=503, detail=f"Sensores AHDE indisponíveis: {e}")


@app.get("/api/ahde/events")
async def get_ahde_events(limit: int = 50):
    events = kernel.ahde.event_bus.recent_events(limit)
    return {"events": _json_safe(events)}


@app.get("/api/ahde/snapshot")
async def get_ahde_snapshot():
    snapshot = kernel.ahde.get_latest_hardware_snapshot()
    telemetry_snapshot = kernel.ahde.get_latest_telemetry_snapshot()
    if snapshot is None:
        raise HTTPException(status_code=503, detail="AHDE ainda não capturou o snapshot inicial.")

    payload = _json_safe(snapshot)
    # O identificador persistente da máquina é deliberadamente redigido na API.
    payload["machine_id"] = "local"
    payload["devices"] = _read_normalized_ahde_devices()
    payload["telemetry"] = _json_safe(telemetry_snapshot.telemetry) if telemetry_snapshot else None
    # HealthEngine.evaluate() ainda é placeholder; não expomos 100 como medição.
    payload["health_score"] = None
    payload["health_status"] = "not_calculated"
    return payload


@app.post("/api/ahde/scan")
async def scan_ahde_hardware():
    """Executa descoberta real e atualiza o snapshot AHDE em memória."""
    try:
        hardware = await kernel.discovery.discover_hardware()
        snapshot = await kernel.ahde.ingest_hardware(
            await kernel._build_ahde_hardware_payload(hardware)
        )
        events = kernel.ahde.event_bus.recent_events(1)
        return {
            "ok": True,
            "snapshot_id": snapshot.snapshot_id,
            "devices": _read_normalized_ahde_devices(),
            "event": _json_safe(events[0]) if events else None,
        }
    except Exception as e:
        logger.exception("/api/ahde/scan: descoberta falhou")
        raise HTTPException(status_code=503, detail=f"Varredura AHDE falhou: {e}")


@app.get("/api/system/report")
async def get_system_report():
    """Relatório verificável da instalação; campos ausentes permanecem ausentes."""
    from phoenix_kernel.paths import PhoenixPaths

    state_data = await kernel.state.get_state()
    if "error" in state_data:
        raise HTTPException(status_code=503, detail=state_data["error"])

    workspace = PhoenixPaths.get_workspace()
    try:
        disk = shutil.disk_usage(workspace)
        storage = {
            "workspace": str(workspace),
            "total_bytes": disk.total,
            "used_bytes": disk.used,
            "free_bytes": disk.free,
        }
    except OSError as e:
        storage = {"workspace": str(workspace), "error": str(e)}

    limits = _current_rag_limits()
    environment = state_data.get("environment") or {}
    return {
        "generated_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "status": "reported",
        "engine": {
            "name": "Phoenix Engine",
            "version": "4.5.0",
            "uptime_seconds": round(time.monotonic() - app.start_time, 3),
            "python": platform.python_version(),
        },
        "hardware": state_data.get("hardware") or {},
        "environment": [
            {"name": name, "available": bool(available)}
            for name, available in sorted(environment.items())
        ],
        "storage": storage,
        "rag": {
            "document_count": state_data.get("rag_docs", 0),
            "plan": limits.get("plan", "free"),
            "max_documents": limits.get("max_documents"),
            "max_upload_bytes": limits.get("max_upload_bytes"),
            "max_characters": limits.get("max_characters"),
        },
        "ahde": {
            **(state_data.get("ahde") or {"available": False}),
            "health_score": None,
            "health_status": "not_calculated",
        },
        "license": {
            "project": "CC BY-NC 4.0",
            "third_party_components": "Licenças e avisos próprios preservados em LICENSE.md e nos fontes vendorizados.",
        },
    }

# PHX-NEW (2026-08-22, pedido do usuário: "já organizar api ou common pra
# verificar todos modelos baixados"): inventário real de tudo que o
# Phoenix sabe baixar (catalog/models.json, cruzado com
# phoenix_kernel/models/health.py - o mesmo módulo que o boot do Kernel
# usa pra decidir se rebaixa um modelo corrompido/ausente), mais o que
# ResidentManager._discover_installed_image_models() enxerga de verdade no
# disco de Imagem agora (esse já lida com nomes de arquivo reais, incluindo
# os que não batem 1:1 com o nome "oficial" do catálogo). Só-leitura -
# nunca dispara download nenhum (isso é decisão do boot ou de uma missão
# aprovada, não de uma chamada GET).
@app.get("/api/models/status")
async def get_models_status():
    from phoenix_kernel.models import health

    inventory = health.full_inventory()

    installed_image_files: list[dict] = []
    resident = getattr(kernel, "resident", None)
    if resident is not None:
        try:
            installed_image_files = [
                {"name": m["name"], "architecture": m["architecture"], "path": str(m["path"])}
                for m in resident._discover_installed_image_models()
            ]
        except Exception as e:
            logger.warning(f"/api/models/status: falha ao escanear modelos de imagem instalados: {e}")

    return {
        "catalog": inventory,
        "installed_image_files_on_disk": installed_image_files,
        "note": (
            "Cobre chat/reasoning (qwen3:8b), speech_to_text (whisper-base) e "
            "image_generation (flux/sdxl/sd15) - os IDs com download automático "
            "real hoje (ModelManager ou AssetManager). vision (minicpmv) e "
            "speech_synthesis (pt_BR-faber-medium) são provisionados por "
            "setup_vision.py / install/common.ps1 (instalador separado), não "
            "por uma checagem de boot - não aparecem aqui ainda."
        ),
    }

class CommandRequest(BaseModel):
    command: str

# PHX-FIX (auditoria 2026-08-20, "ResidentManager não pode ser
# contornado" — Seção 3): esta rota resolvia o modelo de visão via
# resident.registry.resolve("vision") só pra citar no plan, mas executava
# com kernel.runtime.execute() DIRETO - sem _thermal_guard e sem
# _vram_guard (vision é GPU-pesado, junto de "sdxl", pra efeito de
# hot-swap na RX 580 8GB - ver _vram_guard() em resident_manager.py).
# Trocado pro bridge dedicado resident.describe_image_direct(), mesmo
# padrão de /api/generate-image, /api/transcribe e /api/synthesize-speech
# acima (API -> ResidentManager -> Runtime).
# PHX-NEW (pedido do usuário 2026-08-22: "habilitar todas as funçoes do
# modelo de ocr pra qualquer função"): `mode` opcional além de `prompt` -
# "describe" (padrão, comportamento inalterado) ou "ocr" (transcrição de
# texto real via resident.ocr_image_direct(), prompt fixo - ver comentário
# completo em resident_manager.py). Front-end (AviaryApp.tsx) detecta
# intenção de OCR no texto do usuário quando uma imagem é anexada no chat
# e manda mode=ocr; sem isso, comportamento é sempre "describe" como já era.
@app.post("/api/describe-image")
async def describe_image(file: UploadFile = File(...), prompt: str = Form("Descreva esta imagem"), mode: str = Form("describe")):
    """Recebe uma imagem, salva temporariamente e usa o MiniCPM-V para
    descrevê-la (mode=describe, padrão) ou transcrever seu texto via OCR
    real (mode=ocr)."""
    _ALLOWED_IMAGE_EXTS = {".jpg", ".jpeg", ".png", ".webp", ".gif", ".bmp", ".tiff"}
    _raw_name = (file.filename or "upload").strip()
    _safe_ext = Path(_raw_name).suffix.lower()
    if _safe_ext not in _ALLOWED_IMAGE_EXTS:
        _safe_ext = ".bin"
    _safe_filename = f"{uuid.uuid4()}{_safe_ext}"

    temp_dir = Path("temp/vision")
    temp_dir.mkdir(parents=True, exist_ok=True)
    temp_file = temp_dir / _safe_filename

    resident = getattr(kernel, "resident", None)
    if resident is None:
        return {"error": "ResidentManager não encontrado."}

    try:
        with temp_file.open("wb") as buffer:
            shutil.copyfileobj(file.file, buffer)

        if (mode or "").strip().lower() == "ocr":
            # PHX-UPDATE (2026-09-06): OCR híbrido (Tesseract primeiro,
            # MiniCPM-V como segunda opinião) — ver
            # resident_manager.hybrid_ocr_direct.
            result = await resident.hybrid_ocr_direct(str(temp_file.resolve()))
        else:
            result = await resident.describe_image_direct(str(temp_file.resolve()), prompt)

        if result.get("ok"):
            return {"text": result.get("text")}
        return {"error": result.get("error", "Erro desconhecido")}

    except Exception as e:
        return {"error": str(e)}
    finally:
        if temp_file.exists():
            temp_file.unlink()


class SynthesizeSpeechReq(BaseModel):
    text: str
    voice: str = ""
    length_scale: float | None = None

# PHX-FIX (auditoria 2026-08-20, "ResidentManager não pode ser
# contornado" — Seção 3): esta rota montava seu próprio ExecutionPlan
# (runtime="piper") e chamava kernel.runtime.execute() DIRETO, pulando o
# ResidentManager por completo - sem _thermal_guard, sem resolução de voz
# via ModelRegistry, sem _track_model_loaded. Isso quebrava exatamente o
# padrão que /api/generate-image, /api/transcribe e /api/agents/dispatch
# já seguem (API -> ResidentManager -> Runtime). O mais grave: o
# ResidentManager já tinha um bridge pronto pra isso -
# `generate_speech_direct()` (mesmo padrão de generate_image_direct/
# transcribe_direct, com thermal guard e resolução de voz via catálogo) -
# só que NADA o chamava; ficou morto desde que foi escrito. Trocado pra
# usar o bridge existente em vez de duplicar a lógica de execução aqui.
# `length_scale` (parâmetro extra que só esta rota tinha) não é suportado
# pelo bridge - documentado como limitação conhecida, não fabricado.
#
# PHX-NEW (2026-08-23): o bridge `generate_speech_direct()` chamado por esta
# rota não usa mais o Piper por dentro - foi trocado pelo motor neural
# Kokoro-82M (mesmo motor do audiolivro), com detecção automática de idioma
# quando `voice` vier vazio/"auto". Esta rota em si não mudou nada.
@app.post("/api/synthesize-speech")
async def synthesize_speech(req: SynthesizeSpeechReq):
    text = req.text.strip()
    if not text:
        raise HTTPException(status_code=422, detail="Campo 'text' vazio.")

    resident = getattr(kernel, "resident", None)
    if resident is None:
        raise HTTPException(status_code=503, detail="ResidentManager não encontrado.")

    try:
        result = await resident.generate_speech_direct(text, req.voice)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Erro inesperado na ponte de TTS: {e}")

    if not result.get("ok"):
        raise HTTPException(status_code=422, detail=result.get("error", "Falha ao sintetizar voz."))

    audio_path = Path(result["path"])
    if not audio_path.exists():
        raise HTTPException(status_code=500, detail=f"ResidentManager reportou sucesso mas o áudio não foi encontrado ({audio_path}).")

    with open(audio_path, "rb") as f:
        audio_b64 = base64.b64encode(f.read()).decode("ascii")

    return {"ok": True, "voice": result.get("voice") or req.voice or "pf_dora", "path": str(audio_path), "audio_base64": audio_b64, "mime_type": "audio/wav"}

# PHX-NEW (auditoria completa, achado #4 do LEIA-ME): antes desta rota,
# WhisperDriver já estava registrado em runtime/engine.py e no
# catalog/models.json (role speech_to_text), e o common.ps1 passou a
# compilar o binário (outro fix deste mesmo pacote) - mas nada na API ou na
# UI chamava runtime="whisper" em lugar nenhum, então STT continuava
# inacessível mesmo com tudo compilado. Segue o mesmo padrão de
# /api/generate-image: grava o upload num arquivo temporário e chama a
# ponte direta do ResidentManager (transcribe_direct), que roteia pro
# WhisperDriver via kernel.runtime.
# PHX-FIX (auditoria 2026-08-20, "áudio no ChatView/Aviary"): faltava
# ".aac" aqui - o frontend (ChatView.tsx, regex isAudio) já aceitava e
# roteava .aac pro /api/transcribe desde a correção anterior, mas esta
# lista no backend não incluía ".aac", então um .aac chegava até aqui e
# tomava 422 "Extensão não suportada" - o WhisperDriver não tem nenhuma
# restrição própria de formato: converte QUALQUER entrada não-.wav via
# ffmpeg (ver phoenix_kernel/runtime/drivers/whisper.py::_convert_to_wav,
# "ffmpeg -i <entrada> ..." genérico, sem checar extensão), então .aac já
# funcionava no driver - só faltava permitir aqui.
_ALLOWED_AUDIO_EXTS = {".wav", ".mp3", ".ogg", ".m4a", ".flac", ".aac", ".webm"}

@app.post("/api/transcribe")
async def transcribe_audio(file: UploadFile = File(...), language: str = Form("pt")):
    _raw_name = (file.filename or "audio").strip()
    _ext = Path(_raw_name).suffix.lower()
    if _ext not in _ALLOWED_AUDIO_EXTS:
        raise HTTPException(
            status_code=422,
            detail=f"Extensão '{_ext}' não suportada. Use: {', '.join(sorted(_ALLOWED_AUDIO_EXTS))}",
        )

    resident = getattr(kernel, "resident", None)
    if resident is None:
        raise HTTPException(status_code=503, detail="ResidentManager não encontrado.")

    temp_dir = Path("temp/audio")
    temp_dir.mkdir(parents=True, exist_ok=True)
    temp_file = temp_dir / f"{uuid.uuid4()}{_ext}"
    try:
        with temp_file.open("wb") as buffer:
            shutil.copyfileobj(file.file, buffer)
        result = await resident.transcribe_direct(str(temp_file), language)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Erro inesperado na ponte de transcrição: {e}")
    finally:
        if temp_file.exists():
            temp_file.unlink()

    if not result.get("ok"):
        raise HTTPException(status_code=422, detail=result.get("error", "Falha desconhecida ao transcrever áudio."))

    return {
        "ok": True,
        "text": result.get("text", ""),
        "model": result.get("model"),
        "metrics": result.get("metrics", {}),
    }

@app.post("/api/command")
async def handle_command(req: CommandRequest):
    return await kernel.api.process_command(req.command.strip())

# PHX-NEW (Aviary Swarm virar real): antes desta rota, o painel
# AviarySwarmPanel.tsx (Port 3000) despachava tarefas pra 4 personas de
# agente que não existiam de verdade - server.ts chamava
# POST /api/agents/dispatch mas o Phoenix Engine não tinha essa rota, e o
# handleDispatchAgentTask() do painel só simulava conclusão com um
# setTimeout local. Agora a rota existe e chama
# resident.dispatch_agent_task_direct(), que roteia cada persona pra uma
# capacidade REAL do kernel (analyze_machine, process_intent, inferência
# de código via llama.cpp, busca RAG) - ver resident_manager.py. Segue o
# mesmo padrão de /api/generate-image e /api/transcribe acima: 422 com o
# erro real do kernel quando a ponte falha, nunca um "sucesso" fabricado.
class AgentDispatchReq(BaseModel):
    agent_id: str
    task: str

@app.post("/api/agents/dispatch")
async def dispatch_agent(req: AgentDispatchReq):
    resident = getattr(kernel, "resident", None)
    if resident is None:
        raise HTTPException(status_code=503, detail="ResidentManager não encontrado.")
    try:
        result = await resident.dispatch_agent_task_direct(req.agent_id, req.task)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Erro inesperado na ponte do Aviary Swarm: {e}")

    if not result.get("ok"):
        raise HTTPException(status_code=422, detail=result.get("error", "Falha desconhecida no despacho do agente."))

    return result

# PHX-NEW (destravar Ollama como 2ª opção de engine de texto, a pedido
# explícito): expõe a preferência de engine (llama.cpp nativo vs Ollama
# via Docker) que `infer`, `resident research` e o Aviary Architect do
# Swarm passam a consultar. GET devolve o estado atual + opções válidas;
# POST troca e persiste em disco (resident.set_text_engine_preference).
class TextEngineReq(BaseModel):
    engine: str

@app.get("/api/engine/text-runtime")
async def get_text_engine():
    resident = getattr(kernel, "resident", None)
    if resident is None:
        raise HTTPException(status_code=503, detail="ResidentManager não encontrado.")
    return resident.get_text_engine_preference()

@app.post("/api/engine/text-runtime")
async def set_text_engine(req: TextEngineReq):
    resident = getattr(kernel, "resident", None)
    if resident is None:
        raise HTTPException(status_code=503, detail="ResidentManager não encontrado.")
    result = resident.set_text_engine_preference(req.engine)
    if not result.get("ok"):
        raise HTTPException(status_code=422, detail=result.get("error", "Falha ao trocar engine de texto."))
    return result


class RuntimeRecoverReq(BaseModel):
    runtime: str = "llama.cpp"


# PHX-NEW (achado real via screenshot do usuário: "[LLAMA-SERVER]
# qwen3-8b-q4_k_m" falhava com 404 "File Not Found" em TODA mensagem, até
# um "ola" - pedido explícito do usuário: "qualquer comando deveria matar
# processo e subir modelo padrao e nao dar erro"): endpoint dedicado pra
# forçar o runtime nativo de volta pro estado conhecido-bom (modelo
# default do catálogo), chamado pelo server.ts como recuperação
# automática ANTES de mostrar erro pro usuário - ver /api/proxy/chat em
# server.ts, que chama isto e tenta a mensagem de novo uma vez só.
@app.post("/api/engine/runtime/recover")
async def recover_runtime(req: RuntimeRecoverReq):
    resident = getattr(kernel, "resident", None)
    if resident is None:
        raise HTTPException(status_code=503, detail="ResidentManager não encontrado.")
    result = await resident.recover_text_runtime(req.runtime)
    if not result.get("ok"):
        raise HTTPException(status_code=502, detail=result.get("error", "Falha ao recuperar o runtime."))
    return result

@app.get("/api/missions")
async def get_missions():
    # PHX-FIX (varredura 2026-08-21, achado 2): `except:` genérico
    # convertia qualquer falha (catálogo corrompido/não carregado) em
    # "zero missões", 200 OK, sem log e sem campo de erro - idêntico a um
    # catálogo genuinamente vazio. Agora loga a causa real e propaga um
    # 500 honesto em vez de mascarar como lista vazia.
    try:
        return list(kernel.services.packages.catalog.packages.values())
    except Exception as e:
        logging.getLogger(__name__).error(f"/api/missions: falha ao ler catálogo: {e}")
        raise HTTPException(status_code=500, detail=f"Falha ao carregar catálogo de missões: {e}")

@app.get("/api/missions/{package_id}")
async def resolve_mission(package_id: str):
    try:
        resolved = await kernel.planner.resolve_package(package_id)
        if not resolved:
            raise HTTPException(status_code=404, detail="Missão não encontrada")
        return resolved
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

class InstallReq(BaseModel):
    package_id: str

@app.post("/api/missions/install")
async def install_mission(req: InstallReq):
    # PHX-FIX (varredura 2026-08-21, achado 1.4): em falha, devolvia
    # {"output": str(e)} com HTTP 200 - o mesmo formato de uma instalação
    # bem-sucedida, então o chamador não tinha como distinguir "instalou
    # e isto é o log" de "quebrou e isto é o traceback". Todas as outras
    # rotas de mutação deste arquivo (/api/generate-image, /api/benchmark,
    # etc.) já usam HTTPException em caso de erro - esta ficou pra trás.
    try:
        result = await kernel.services.install_package(req.package_id)
        return {"output": result}
    except Exception as e:
        raise HTTPException(status_code=502, detail=str(e))

# PHX-FIX (2026-08-22, achado real do usuário: "foi usado somente flux
# porque é o unico modelo baixado" - o seletor de imagem do chat não lia a
# pasta correta): expõe o mesmo scan de disco que o backend já usa pra
# escolher modelo de imagem sozinho (ResidentManager._discover_installed_image_models,
# via o novo list_installed_image_models()) - agora o frontend pode montar
# o seletor "IMAGEM" com o que está REALMENTE baixado, em vez de 3 opções
# fixas (Flux/SDXL/SD1.5) que ficavam cegas pra qualquer outro modelo.
@app.get("/api/models/image-models")
async def get_image_models():
    resident = getattr(kernel, "resident", None)
    if resident is None:
        return {"models": [], "ready": False}
    try:
        return {"models": resident.list_installed_image_models(), "ready": True}
    except Exception as e:
        logger.warning(f"/api/models/image-models: falha ao escanear disco: {e}")
        return {"models": [], "ready": False}

class GenerateImageReq(BaseModel):
    prompt: str
    model_hint: str = ""

@app.post("/api/generate-image")
async def generate_image(req: GenerateImageReq):
    resident = getattr(kernel, "resident", None)
    if resident is None:
        raise HTTPException(status_code=503, detail="ResidentManager não encontrado.")
    try:
        result = await resident.generate_image_direct(req.prompt, req.model_hint)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Erro inesperado na ponte de imagem: {e}")

    if not result.get("ok"):
        raise HTTPException(status_code=422, detail=result.get("error", "Falha desconhecida ao gerar imagem."))

    img_path = Path(result["path"])
    if not img_path.exists():
        raise HTTPException(status_code=500, detail=f"Driver reportou sucesso mas o arquivo não existe em disco: {img_path}")

    with open(img_path, "rb") as f:
        image_b64 = base64.b64encode(f.read()).decode("ascii")

    return {"ok": True, "model": result.get("model"), "path": str(img_path), "image_base64": image_b64, "mime_type": "image/png"}

# PHX-NEW (achado real do usuário 2026-08-24: digitou "pesquisar acidente
# com 2 helicópteros no rj em 2026" no chat de texto normal, e o qwen3-8b
# respondeu direto da própria "cabeça" - "a data de 2026 ainda não chegou,
# não há registros" - sem nunca buscar nada de verdade). Causa raiz
# confirmada lendo o código: `phoenix_kernel/intelligence/web_search.py`
# (search_web(), via SearXNG local em localhost:8080) já existe e já
# funciona de verdade - mas só está conectado ao /colaborar (dual_collab.py,
# ver resident_manager.py::run_dual_collab -> search_fn), nunca ao chat
# normal de um único modelo. Diferente do Open WebUI (guia genérico enviado
# pelo usuário - projeto completamente diferente, com toggle manual de
# "Web Search" por conversa em um Admin Panel que a Aviary não tem e não
# usa), aqui a busca é acionada por INTENÇÃO no próprio texto (mesmo padrão
# de isImageGenerationIntent/isOcrIntent no frontend) - ver
# AviaryApp.tsx::isWebSearchIntent. Esta rota só expõe o search_web() já
# existente pro frontend chamar antes de repassar a pergunta pro modelo de
# texto - nenhuma lógica de busca nova, só a conexão que faltava.
class WebSearchReq(BaseModel):
    query: str
    max_results: int = 5

@app.post("/api/web-search")
async def web_search_route(req: WebSearchReq):
    from phoenix_kernel.intelligence.web_search import search_web

    query = req.query.strip()
    if not query:
        raise HTTPException(status_code=400, detail="Query de busca vazia.")

    result_text = await search_web(query, max_results=req.max_results)

    # search_web() nunca levanta exceção - erros de rede/SearXNG offline
    # voltam como uma string começando com este prefixo (ver
    # web_search.py). Trata isso como erro real de verdade (nunca inventa
    # sucesso) - mesmo padrão já aplicado nas 4 rotas de mock-fallback do
    # server.ts corrigidas numa auditoria anterior desta mesma sessão.
    if result_text.startswith("Falha ao acessar a internet (SearXNG):"):
        raise HTTPException(status_code=502, detail=result_text)

    return {"ok": True, "query": query, "results": result_text}

# ==========================================
# DOCUMENT ENGINE - READ e EDIT
# ==========================================
# PHX-FIX (auditoria 2026-08-20, achados #2 e #3): existiam DOIS fluxos de
# documento em paralelo - o /api/documents/ingest antigo (só PDF/TXT, lia
# com PyMuPDF cru e chamava kernel.runtime.execute() direto) e os novos
# /api/documents/read e /api/documents/edit (todos os 4 formatos via
# phoenix_kernel.documents.engine). Os dois também bypassavam o
# ResidentManager - resolviam o modelo com resident.registry.resolve() só
# pra decidir o plan, mas executavam com kernel.runtime.execute() direto,
# nunca passando por resident.read_document_direct()/edit_document_direct()
# (que nem existiam). Isso quebrava a arquitetura que toda outra
# capacidade multimodal já segue (imagem, voz, STT): API -> ResidentManager
# -> Runtime, com _thermal_guard e _track_model_loaded no meio.
#
# Agora: as duas rotas só salvam o upload e chamam o Resident, que faz
# extração + resolução de modelo + execução + rastreamento. E
# /api/documents/ingest virou um alias fino de /api/documents/read (mesmo
# fluxo real, PDF/DOCX/XLSX/PPTX/TXT/MD em vez de só PDF/TXT) - não existe
# mais lógica própria/paralela pra manter sincronizada.
_ALLOWED_DOCUMENT_EXTS = {".pdf", ".docx", ".xlsx", ".pptx", ".txt", ".md"}


async def _save_document_upload(file: UploadFile) -> tuple[Path, str]:
    """Sanitiza o nome, valida a extensão e grava o upload em temp/documents/.
    Devolve (caminho_do_arquivo_temporario, nome_original_sanitizado)."""
    _raw_name = (file.filename or "upload").strip()
    _safe_ext = Path(_raw_name).suffix.lower()
    if _safe_ext not in _ALLOWED_DOCUMENT_EXTS:
        raise HTTPException(status_code=422, detail=f"Extensão '{_safe_ext}' não suportada.")
    _safe_filename = f"{uuid.uuid4()}{_safe_ext}"
    temp_dir = Path("temp/documents")
    temp_dir.mkdir(parents=True, exist_ok=True)
    temp_file = temp_dir / _safe_filename
    with temp_file.open("wb") as buffer:
        shutil.copyfileobj(file.file, buffer)
    return temp_file, Path(_raw_name).name


@app.post("/api/documents/read")
async def read_document(file: UploadFile = File(...), question: str = Form("")):
    """Recebe documento + pergunta opcional, usa a ponte direta do
    ResidentManager (Document Engine + Qwen) e devolve a análise."""
    resident = getattr(kernel, "resident", None)
    if resident is None:
        raise HTTPException(status_code=503, detail="ResidentManager não encontrado.")

    temp_file, original_name = await _save_document_upload(file)
    try:
        # PHX-FIX (achado real do usuário testando ao vivo com um .xlsx): o
        # nome original já era resolvido aqui (`original_name`, usado no
        # "file" da resposta HTTP abaixo) mas NUNCA era passado pro
        # ResidentManager - a ponte só recebia o caminho do arquivo
        # temporário (nome UUID). O TEXTO gerado pela IA (result["text"])
        # citava esse UUID como se fosse o nome do documento sempre que o
        # próprio conteúdo não tinha um título melhor pra usar (típico de
        # resumo estrutural de planilha) - ver PHX-FIX completo em
        # resident_manager.py:read_document_direct.
        result = await resident.read_document_direct(str(temp_file.resolve()), question, original_name=original_name)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Erro inesperado na ponte de documento: {e}")
    finally:
        if temp_file.exists():
            temp_file.unlink()

    if not result.get("ok"):
        raise HTTPException(status_code=422, detail=result.get("error", "Falha desconhecida ao ler o documento."))

    return {"ok": True, "text": result["text"], "extracted_length": result.get("extracted_length", 0), "file": original_name}


@app.post("/api/documents/ingest")
async def ingest_document(file: UploadFile = File(...)):
    """PHX-FIX (auditoria 2026-08-20, achado #2): alias interno de
    /api/documents/read - a rota antiga tinha um fluxo paralelo inferior
    (só PDF/TXT, chamava kernel.runtime.execute() direto). Mantida só por
    compatibilidade com qualquer chamador antigo; não tem lógica própria."""
    return await read_document(file=file, question="")


@app.post("/api/documents/edit")
async def edit_document(
    file: UploadFile = File(...),
    instruction: str = Form(...),
    reference: UploadFile | None = File(None),
):
    """Recebe documento + instrução de edição, usa a ponte direta do
    ResidentManager e devolve o arquivo editado em base64.

    PHX-NEW (pedido do usuário 2026-08-28): aceita um segundo arquivo
    opcional ("reference") - um segundo documento cujo conteúdo extraído
    é dobrado no prompt como contexto extra (ex: "edite este contrato
    usando os dados deste outro documento"). Não é fusão estrutural, só
    texto adicional pro modelo considerar - ver docstring de
    edit_document_direct."""
    if not instruction.strip():
        raise HTTPException(status_code=400, detail="Campo 'instruction' é obrigatório.")

    resident = getattr(kernel, "resident", None)
    if resident is None:
        raise HTTPException(status_code=503, detail="ResidentManager não encontrado.")

    temp_file, original_name = await _save_document_upload(file)
    ref_temp_file, ref_original_name = (None, None)
    # PHX-FIX: usa isinstance em vez de "is not None" - quando esta rota é
    # chamada diretamente (fora do ciclo de request do FastAPI, como em
    # teste unitário) sem passar `reference`, o valor do parâmetro é o
    # próprio sentinel `File(None)` (uma instância de fastapi.params.File),
    # não o `None` puro que só a injeção de dependência do FastAPI resolve
    # numa request HTTP real - "is not None" tratava esse sentinel como um
    # arquivo de referência de verdade e quebrava com AttributeError.
    if isinstance(reference, UploadFile):
        ref_temp_file, ref_original_name = await _save_document_upload(reference)
    try:
        # PHX-FIX: mesmo conserto de read_document_direct acima - o nome
        # original agora chega até o prompt da IA e até o nome do arquivo
        # editado gerado, em vez do UUID do arquivo temporário.
        result = await resident.edit_document_direct(
            str(temp_file.resolve()),
            instruction,
            original_name=original_name,
            reference_file_path=str(ref_temp_file.resolve()) if ref_temp_file else None,
            reference_name=ref_original_name,
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Erro inesperado na ponte de documento: {e}")
    finally:
        if temp_file.exists():
            temp_file.unlink()
        if ref_temp_file is not None and ref_temp_file.exists():
            ref_temp_file.unlink()

    if not result.get("ok"):
        raise HTTPException(status_code=422, detail=result.get("error", "Falha desconhecida ao editar o documento."))

    out_path = Path(result["file_path"])
    if not out_path.exists():
        raise HTTPException(status_code=500, detail=f"Resident reportou sucesso mas o arquivo não existe em disco: {out_path}")

    try:
        with open(out_path, "rb") as f:
            file_b64 = base64.b64encode(f.read()).decode("ascii")
    finally:
        out_path.unlink(missing_ok=True)

    out_ext = out_path.suffix.lower()
    _mime = {".pdf": "application/pdf",
             ".docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
             ".xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
             ".pptx": "application/vnd.openxmlformats-officedocument.presentationml.presentation",
             ".txt": "text/plain", ".md": "text/markdown"}
    return {"ok": True, "file_name": result["file_name"], "file_base64": file_b64,
            "mime_type": _mime.get(out_ext, "application/octet-stream")}


_DOCUMENT_MIME = {
    ".pdf": "application/pdf",
    ".docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    ".xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    ".pptx": "application/vnd.openxmlformats-officedocument.presentationml.presentation",
    ".txt": "text/plain",
    ".md": "text/markdown",
}


@app.post("/api/documents/create")
async def create_document(
    instruction: str = Form(...),
    output_format: str = Form(...),
    filename: str = Form(""),
    use_web: bool = Form(False),
    web_query: str = Form(""),
    model_hint: str = Form(""),
    file: UploadFile | None = File(None),
):
    """Cria documento do zero OU transforma um documento-base.

    Fonte opcional: PDF/DOCX/XLSX/PPTX/TXT/MD.
    Saída: PDF/DOCX/XLSX/PPTX/TXT/MD.
    Pode pesquisar na web antes de compor o conteúdo.
    """
    if not instruction.strip():
        raise HTTPException(status_code=400, detail="Campo 'instruction' é obrigatório.")

    fmt = output_format.strip().lower().lstrip(".")
    if fmt not in {"pdf", "docx", "xlsx", "pptx", "txt", "md"}:
        raise HTTPException(status_code=422, detail=f"Formato de saída '{fmt}' não suportado.")

    resident = getattr(kernel, "resident", None)
    if resident is None:
        raise HTTPException(status_code=503, detail="ResidentManager não encontrado.")

    temp_file = None
    original_name = None
    if file is not None:
        temp_file, original_name = await _save_document_upload(file)

    try:
        result = await resident.create_document_direct(
            instruction=instruction,
            output_format=fmt,
            filename=filename,
            source_file_path=str(temp_file.resolve()) if temp_file else None,
            source_name=original_name,
            use_web=use_web,
            web_query=web_query,
            model_hint=model_hint,
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Erro inesperado criando/transformando documento: {e}")
    finally:
        if temp_file is not None and temp_file.exists():
            temp_file.unlink()

    if not result.get("ok"):
        raise HTTPException(status_code=422, detail=result.get("error", "Falha desconhecida ao criar o documento."))

    out_path = Path(result["file_path"])
    if not out_path.exists() or out_path.stat().st_size <= 0:
        raise HTTPException(status_code=500, detail=f"Arquivo final não foi materializado corretamente: {out_path}")

    with out_path.open("rb") as f:
        file_b64 = base64.b64encode(f.read()).decode("ascii")

    return {
        "ok": True,
        "file_name": result["file_name"],
        "file_base64": file_b64,
        "mime_type": _DOCUMENT_MIME.get(out_path.suffix.lower(), "application/octet-stream"),
        "format": result.get("format", fmt),
        "source_file": result.get("source_file"),
        "web_used": result.get("web_used", False),
        "model": result.get("model"),
        "runtime": result.get("runtime"),
        "ocr_used": result.get("ocr_used", False),
        "ocr_pages_processed": result.get("ocr_pages_processed"),
        "ocr_pages_total": result.get("ocr_pages_total"),
        "ocr_truncated": result.get("ocr_truncated", False),
    }


@app.post("/api/documents/fill-template")
async def fill_spreadsheet_template(
    source: UploadFile = File(...),
    template: UploadFile = File(...),
    instruction: str = Form(""),
    use_web: bool = Form(False),
    web_query: str = Form(""),
    model_hint: str = Form(""),
):
    """PHX-NEW (pedido do usuário 2026-08-28: "aceitar dois arquivos - um
    fonte, um template alvo - e editar o segundo em vez de gerar do
    zero"). Recebe um documento-fonte (qualquer formato que a Phoenix já
    lê: pdf/docx/xlsx/pptx/txt/md) e uma planilha .xlsx-modelo, extrai os
    dados do primeiro e PREENCHE o segundo no lugar - preservando outras
    planilhas, fórmulas e formatação do template em vez de recriar o
    arquivo do zero como /api/documents/create faz. Ver
    ResidentManager.fill_spreadsheet_template_direct e
    phoenix_kernel.documents.engine.fill_xlsx_template."""
    resident = getattr(kernel, "resident", None)
    if resident is None:
        raise HTTPException(status_code=503, detail="ResidentManager não encontrado.")

    if Path(template.filename or "").suffix.lower() != ".xlsx":
        raise HTTPException(status_code=422, detail="O template precisa ser um arquivo .xlsx.")

    source_temp, source_name = await _save_document_upload(source)
    template_temp, template_name = await _save_document_upload(template)
    try:
        result = await resident.fill_spreadsheet_template_direct(
            str(source_temp.resolve()),
            str(template_temp.resolve()),
            instruction=instruction,
            source_name=source_name,
            template_name=template_name,
            use_web=use_web,
            web_query=web_query,
            model_hint=model_hint,
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Erro inesperado preenchendo a planilha: {e}")
    finally:
        if source_temp.exists():
            source_temp.unlink()
        if template_temp.exists():
            template_temp.unlink()

    if not result.get("ok"):
        raise HTTPException(status_code=422, detail=result.get("error", "Falha desconhecida ao preencher a planilha."))

    out_path = Path(result["file_path"])
    if not out_path.exists():
        raise HTTPException(status_code=500, detail=f"Resident reportou sucesso mas o arquivo não existe em disco: {out_path}")

    try:
        with open(out_path, "rb") as f:
            file_b64 = base64.b64encode(f.read()).decode("ascii")
    finally:
        out_path.unlink(missing_ok=True)

    return {
        "ok": True,
        "file_name": result["file_name"],
        "file_base64": file_b64,
        "mime_type": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        "rows_written": result.get("rows_written", 0),
        "sheet_used": result.get("sheet_used"),
        "auto_created_columns": result.get("auto_created_columns", {}),
        "source_file": result.get("source_file"),
        "template_file": result.get("template_file"),
        "web_used": result.get("web_used", False),
        "model": result.get("model"),
        "runtime": result.get("runtime"),
    }


@app.post("/api/documents/pipeline-fill")
async def pipeline_fill_xlsx(
    source: UploadFile = File(...),
    template: UploadFile = File(...),
    source_name: str = Form(""),
    template_name: str = Form(""),
):
    """PHX-NEW (2026-09-03): preenchimento DETERMINÍSTICO de planilha — a Phoenix
    lê o documento e preenche o template 100% em Python (Document Pipeline V2 +
    Smart Filler), SEM LLM. Existe porque o caminho por LLM (/fill-template)
    passou de 90min num catálogo real e virou processo órfão. Este roda em
    segundos. Mesmo contrato de entrada (source + template), devolve o xlsx
    preenchido em base64 + o relatório do que foi feito."""
    resident = getattr(kernel, "resident", None)
    if resident is None:
        raise HTTPException(status_code=503, detail="ResidentManager não encontrado.")
    if Path(template.filename or "").suffix.lower() != ".xlsx":
        raise HTTPException(status_code=422, detail="O template precisa ser um arquivo .xlsx.")

    source_temp, s_name = await _save_document_upload(source)
    template_temp, t_name = await _save_document_upload(template)
    try:
        result = await resident.pipeline_fill_xlsx_direct(
            str(source_temp.resolve()),
            str(template_temp.resolve()),
            source_name=source_name or s_name,
            template_name=template_name or t_name,
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Erro inesperado no preenchimento determinístico: {e}")
    finally:
        if source_temp.exists():
            source_temp.unlink()
        if template_temp.exists():
            template_temp.unlink()

    if not result.get("ok"):
        raise HTTPException(status_code=422, detail=result.get("error", "Falha ao preencher a planilha."))

    out_path = Path(result["file_path"])
    if not out_path.exists():
        raise HTTPException(status_code=500, detail=f"Pipeline reportou sucesso mas o arquivo não existe: {out_path}")
    try:
        with open(out_path, "rb") as f:
            file_b64 = base64.b64encode(f.read()).decode("ascii")
    finally:
        out_path.unlink(missing_ok=True)

    return {
        "ok": True,
        "file_name": result["file_name"],
        "file_base64": file_b64,
        "mime_type": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        "rows_written": result.get("rows_written", 0),
        "records_total": result.get("records_total", 0),
        "columns_mapped": result.get("columns_mapped", []),
        "smart_fill": result.get("smart_fill"),
        "method": result.get("method"),
        "source_file": result.get("source_file"),
        "template_file": result.get("template_file"),
    }


@app.post("/api/documents/extract-raw")
async def extract_document_raw(file: UploadFile = File(...)):
    """PHX-NEW (pedido do usuário 2026-08-22: anexo de arquivo na aba
    Colaboração do Arena, "igual no chatbot"): extrai o texto CRU de um
    documento (pdf/docx/xlsx/pptx), SEM nenhuma chamada de LLM - ao
    contrário de /api/documents/read, que sempre gasta uma chamada de IA
    inteira só pra responder/resumir. Aqui o texto extraído volta puro
    pro frontend, que injeta ele no "topic" mandado pro
    /api/dual-collab - os dois modelos da colaboração leem o conteúdo
    como parte do próprio tema deles, sem essa terceira chamada de
    modelo no meio. Mesmo padrão de upload/limpeza de /api/documents/read
    acima (grava em temp/documents/, sempre apaga no finally)."""
    resident = getattr(kernel, "resident", None)
    if resident is None:
        raise HTTPException(status_code=503, detail="ResidentManager não encontrado.")

    temp_file, original_name = await _save_document_upload(file)
    try:
        result = await resident.extract_document_raw_direct(str(temp_file.resolve()), original_name=original_name)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Erro inesperado na extração de documento: {e}")
    finally:
        if temp_file.exists():
            temp_file.unlink()

    if not result.get("ok"):
        raise HTTPException(status_code=422, detail=result.get("error", "Falha desconhecida ao extrair o documento."))

    return {"ok": True, "text": result["text"], "file": result.get("file", original_name),
            "ocr_used": result.get("ocr_used", False)}


# ==========================================
# DOCUMENTO LONGO -> AUDIOLIVRO (Kokoro-82M)
# ==========================================
# PHX-NEW (pedido do usuário 2026-08-23: "pegar um arquivo doc, pdf de 40
# folhas e fazer áudio com voz neural com prosódia bacana tanto em
# português qto em inglês ou outra língua"). Mesmo padrão de
# BLOQUEANTE+PROGRESSO já usado em /api/dual-collab acima: esta rota roda
# até terminar (pode legitimamente levar dezenas de minutos - ver
# AUDIOBOOK_TOTAL_TIME_BUDGET_SECONDS em resident_manager.py), enquanto
# GET /api/documents/synthesize-audiobook/progress (abaixo) é chamada em
# polling pelo frontend PARA MOSTRAR uma barra de progresso real em vez de
# uma tela travada sem feedback nenhum.
@app.post("/api/documents/synthesize-audiobook")
async def synthesize_audiobook(file: UploadFile = File(...)):
    resident = getattr(kernel, "resident", None)
    if resident is None:
        raise HTTPException(status_code=503, detail="ResidentManager não encontrado.")

    temp_file, original_name = await _save_document_upload(file)
    try:
        result = await resident.generate_audiobook_direct(str(temp_file.resolve()), original_name=original_name)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Erro inesperado gerando o audiolivro: {e}")
    finally:
        if temp_file.exists():
            temp_file.unlink()

    if not result.get("ok"):
        raise HTTPException(status_code=422, detail=result.get("error", "Falha desconhecida ao gerar o audiolivro."))

    audio_path = Path(result["path"])
    if not audio_path.exists():
        raise HTTPException(status_code=500, detail=f"Geração reportou sucesso mas o arquivo final não foi encontrado ({audio_path}).")

    with open(audio_path, "rb") as f:
        audio_b64 = base64.b64encode(f.read()).decode("ascii")

    return {
        "ok": True,
        "file_name": audio_path.name,
        "mime_type": result.get("mime_type", "audio/wav"),
        "audio_base64": audio_b64,
        "duration_seconds": result.get("duration_seconds"),
        "chunks_synthesized": result.get("chunks_synthesized"),
        "chunks_total": result.get("chunks_total"),
        "languages_used": result.get("languages_used"),
        "document_language": result.get("document_language"),
        "timed_out": result.get("timed_out", False),
    }


# PHX-NEW (mesmo padrão de GET /api/dual-collab/progress acima): leitura
# RÁPIDA e sempre não-bloqueante do progresso do audiolivro em andamento -
# pensada pra ser chamada em polling (a cada 1-2s) pelo frontend ENQUANTO
# POST /api/documents/synthesize-audiobook acima ainda está processando.
@app.get("/api/documents/synthesize-audiobook/progress")
async def synthesize_audiobook_progress():
    resident = getattr(kernel, "resident", None)
    if resident is None:
        raise HTTPException(status_code=503, detail="ResidentManager não encontrado.")
    return resident.get_audiobook_progress()


# ==========================================
# COLABORAÇÃO ENTRE DOIS MODELOS (CPU + GPU)
# ==========================================
# PHX-NEW (pedido do usuário 2026-08-22): dois modelos de texto
# colaborando num projeto - um inteiro na CPU, outro inteiro na GPU via
# Vulkan (nunca split de camadas), com acesso real à internet quando
# precisarem. Bloqueante - pode levar vários minutos (ver
# dual_collab.TOTAL_TIME_BUDGET_SECONDS=1200s/20min); o proxy Node
# (server.ts) tem um AbortController generoso o suficiente pra isso.
class DualCollabRequest(BaseModel):
    topic: str
    max_rounds: int = 6
    # PHX-NEW (2026-08-22, modelo padrão de raciocínio não coube na VRAM
    # útil do usuário com a margem de segurança): opcionais - vazios
    # preservam o comportamento original (os dois lados usam o mesmo
    # modelo padrão da Phoenix).
    cpu_model: str = ""
    gpu_model: str = ""


@app.post("/api/dual-collab")
async def dual_collab_endpoint(req: DualCollabRequest):
    resident = getattr(kernel, "resident", None)
    if resident is None:
        raise HTTPException(status_code=503, detail="ResidentManager não encontrado.")

    result = await resident.run_dual_model_collaboration_direct(
        req.topic, max_rounds=req.max_rounds,
        cpu_model_hint=req.cpu_model, gpu_model_hint=req.gpu_model,
    )
    if not result.get("ok"):
        raise HTTPException(status_code=422, detail=result.get("error", "Falha desconhecida na colaboração."))
    return result


# PHX-NEW (2026-08-22, pedido do usuário depois de ver a Arena com a
# ampulheta piscando o tempo inteiro até as 6 rodadas terminarem TODAS de
# uma vez, dando a impressão de que travou): leitura RÁPIDA e sempre
# não-bloqueante do progresso da colaboração em andamento - pensada pra
# ser chamada em POLLING (a cada 1-2s) pelo frontend ENQUANTO a chamada
# bloqueante acima (`POST /api/dual-collab`) ainda está rodando, pra
# mostrar cada rodada assim que ela termina, em vez de só no final. Nunca
# inicia nem cancela nada - só lê o que já está publicado.
@app.get("/api/dual-collab/progress")
async def dual_collab_progress_endpoint():
    resident = getattr(kernel, "resident", None)
    if resident is None:
        raise HTTPException(status_code=503, detail="ResidentManager não encontrado.")
    return resident.get_dual_collab_progress()


# PHX-FIX (auditoria completa, achado #2 do LEIA-ME): esta rota não existia
# no lado Python - server.ts (Node) respondia sozinho a POST /api/benchmark
# com números fixos hardcoded (sempre os mesmos: 6.17 TFLOPs, 224.0 GB/s,
# score 87.4%), enquanto o botão "Vulkan Bench (RX 580)" no frontend
# (ProcessLauncherBar.tsx) prometia "benchmark real de shaders Vulkan".
# Implementar um benchmark de shader Vulkan de verdade (TFLOPs, largura de
# banda de memória, latência) seria uma feature nova - exigiria dispatch de
# compute shaders SPIR-V dedicados, isso não existe em nenhum lugar do
# projeto hoje e ficaria fora do escopo de um conserto de bug. O que dá pra
# medir de verdade com a infraestrutura já existente é o throughput de
# geração de tokens: dispara uma inferência curta real via kernel.runtime
# (o mesmo runtime usado por chat/missions/document engine) e mede tokens/s
# de verdade a partir do ExecutionResult.metrics (tokens_per_second, já
# calculado com started_at/finished_at reais em runtime/drivers/llama_cpp.py
# - ver comentário PHX-FIX lá sobre esse cálculo). Os campos que exigiriam
# medição de shader Vulkan simplesmente não aparecem mais na resposta -
# nada fica fabricado no lugar deles.
#
# PHX-FIX (auditoria 2026-08-20, "ResidentManager não pode ser
# contornado" — Seção 3): esta rota montava o próprio ExecutionPlan e
# chamava kernel.runtime.execute() DIRETO - mesmo anti-padrão já
# corrigido pra imagem/voz/visão acima (sem _thermal_guard, sem
# _track_model_loaded). Trocado pro bridge dedicado
# resident.run_token_benchmark_direct() — mede exatamente a mesma coisa
# de antes (throughput real de tokens/s), só que agora passando pelo
# Resident.
@app.post("/api/benchmark")
async def run_benchmark():
    resident = getattr(kernel, "resident", None)
    if resident is None:
        raise HTTPException(status_code=503, detail="ResidentManager não encontrado.")

    try:
        result = await resident.run_token_benchmark_direct()
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"Falha ao executar benchmark: {e}")

    if not result.get("ok"):
        raise HTTPException(status_code=502, detail=result.get("error", "Benchmark falhou."))

    metrics = result.get("metrics") or {}
    return {
        "ok": True,
        "results": {
            "runtime": result.get("runtime"),
            "model": result.get("model"),
            "tokensPerSec": metrics.get("tokens_per_second", 0.0),
            "tokensGenerated": metrics.get("tokens_generated", 0),
            "durationMs": metrics.get("duration_ms", 0),
            "status": "MEASURED",
        },
        "note": (
            "Medição real de throughput de geração de tokens via uma inferência "
            "curta no runtime configurado. TFLOPs, largura de banda de memória e "
            "latência de shader Vulkan não são medidos aqui — exigiriam um compute "
            "shader dedicado que não existe no projeto ainda."
        ),
    }



@app.get("/api/licensing/status")
async def licensing_status():
    """Estado comercial sem expor nonce, token ou machine fingerprint."""
    return {"ok": True, "licensing": capability_security_status()}


@app.post("/api/licensing/refresh")
async def licensing_refresh():
    """Força nova negociação de capability sem reiniciar a Phoenix."""
    invalidate_capability_cache()
    limits = get_rag_limits(force_refresh=True)
    return {
        "ok": True,
        "plan": limits["plan"],
        "capability_valid": limits.get("capability_valid", False),
        "capability_source": limits.get("capability_source", "unknown"),
        "capability_expires_at": limits.get("capability_expires_at"),
        "features": limits.get("features", []),
    }


@app.get("/api/rag/security-status")
async def rag_security_status():
    backend = getattr(
        getattr(getattr(kernel, "planner", None), "knowledge", None),
        "rag_backend",
        None,
    )
    if backend is None:
        raise HTTPException(status_code=503, detail="RAG backend indisponível.")
    return {"ok": True, "security": backend.user_repository_security_status()}


@app.get("/api/rag/limits")
async def rag_limits():
    backend = getattr(getattr(getattr(kernel, "planner", None), "knowledge", None), "rag_backend", None)
    current_documents = 0
    # PHX-FIX (2026-09-06, correção conceitual do usuário: o limite de
    # caracteres é um orçamento AGREGADO do repositório, não um teto por
    # documento isolado) - expõe o uso atual desse orçamento, não só a
    # contagem de documentos, pra a UI mostrar "X / 150.000.000
    # caracteres" em vez de um número fixo sem contexto de uso real.
    current_characters = 0
    if backend is not None:
        try:
            import asyncio as _asyncio
            current_documents = await _asyncio.get_event_loop().run_in_executor(
                None, backend.logical_document_count
            )
            current_characters = await _asyncio.get_event_loop().run_in_executor(
                None, backend.total_extracted_characters
            )
        except Exception as e:
            logger.warning("/api/rag/limits: falha ao contar documentos/caracteres: %s", e)

    limits = _current_rag_limits()
    return {
        "ok": True,
        "plan": limits["plan"],
        "current_documents": current_documents,
        "max_documents": limits["max_documents"],
        "max_upload_bytes": limits["max_upload_bytes"],
        "max_upload_mb": round(limits["max_upload_bytes"] / (1024 * 1024)),
        "max_characters": limits["max_characters"],
        "current_characters": current_characters,
        "remaining_characters": max(0, limits["max_characters"] - current_characters) if limits["max_characters"] is not None else None,
        "counting_rule": "1 documento lógico = 1 vaga; chunks não contam. Caracteres: orçamento agregado do repositório inteiro, não por documento.",
        "entitlement_valid": limits.get("entitlement_valid", False),
        "entitlement_reason": limits.get("entitlement_reason", "unknown"),
        "capability_valid": limits.get("capability_valid", False),
        "capability_source": limits.get("capability_source", "unknown"),
        "capability_expires_at": limits.get("capability_expires_at"),
        "capability_epoch": limits.get("capability_epoch"),
        "features": limits.get("features", []),
        "repository_security": backend.user_repository_security_status() if backend is not None else {
            "integrity_valid": False,
            "reason": "backend_unavailable",
            "authorized_documents": 0,
            "detected_manual_documents": 0,
            "locked_or_unregistered_documents": 0,
        },
    }


# PHX-NEW (2026-09-06, pedido explícito do usuário, com análise técnica
# detalhada: "o ideal para o Phoenix 4.5 é ter inclusive um endpoint tipo
# GET /api/rag/usage... A UI só apresenta isso. Ela não calcula a regra
# comercial por conta própria."): endpoint dedicado, formato exato
# especificado por ele - complementa /api/rag/limits (que mantém todos os
# campos legados, pra não quebrar quem já consome) com uma resposta mais
# enxuta, pensada especificamente pra auditoria/reconciliação do
# orçamento agregado de caracteres.
@app.get("/api/rag/usage")
async def rag_usage():
    backend = getattr(getattr(getattr(kernel, "planner", None), "knowledge", None), "rag_backend", None)
    current_documents = 0
    current_characters = 0
    integrity = "unavailable"
    if backend is not None:
        try:
            import asyncio as _asyncio
            current_documents = await _asyncio.get_event_loop().run_in_executor(
                None, backend.logical_document_count
            )
            current_characters = await _asyncio.get_event_loop().run_in_executor(
                None, backend.total_extracted_characters
            )
            security = backend.user_repository_security_status()
            integrity = "ok" if security.get("integrity_valid") else security.get("reason", "failed")
        except Exception as e:
            logger.warning("/api/rag/usage: falha ao calcular uso do RAG: %s", e)
            integrity = "error"

    limits = _current_rag_limits()
    max_chars = limits.get("max_characters")
    max_docs = limits.get("max_documents")
    return {
        "plan": limits["plan"],
        "documents": {
            "used": current_documents,
            "limit": max_docs,
        },
        "characters": {
            "used": current_characters,
            "limit": max_chars,
            "remaining": max(0, max_chars - current_characters) if max_chars is not None else None,
        },
        "max_file_bytes": limits.get("max_upload_bytes"),
        "integrity": integrity,
    }


class RagAddDocumentReq(BaseModel):
    title: str
    content: str
    source_type: str = "MD"


# PHX-NEW (auditoria completa, achado #3 do LEIA-ME): antes desta rota, o
# server.ts (Node) tentava chamar POST /api/rag/add nesta API e, como ela
# simplesmente não existia (404), caía num fallback que fabricava
# `status: "INDEXED"` e `vectorDimensions: 1536` sem ter indexado nada de
# verdade. Agora existe a rota real: indexa no ChromaDB via
# KnowledgeEngine.rag_backend (ChromaRagBackend.add_document, ver
# phoenix_kernel/intelligence/chroma_rag_backend.py). Sem chunking (mesma
# arquitetura 1-doc-1-chunk usada pelos 226 documentos já existentes) -
# `chunks` retornado é sempre 1, honestamente.
@app.post("/api/rag/add")
async def rag_add_document(req: RagAddDocumentReq):
    if not req.title.strip() or not req.content.strip():
        raise HTTPException(status_code=400, detail="Campos 'title' e 'content' são obrigatórios.")
    planner = getattr(kernel, "planner", None)
    backend = getattr(getattr(planner, "knowledge", None), "rag_backend", None)
    if backend is None:
        raise HTTPException(status_code=503, detail="RAG backend indisponível (ChromaDB não conectado).")
    try:
        import asyncio as _asyncio
        limits = _current_rag_limits()
        await _asyncio.get_event_loop().run_in_executor(
            None,
            lambda: backend.validate_product_limits(
                req.title,
                req.content,
                max_documents=limits["max_documents"],
                max_characters=limits["max_characters"],
            ),
        )
        result = await _asyncio.get_event_loop().run_in_executor(
            None, backend.add_document_chunked, req.title, req.content, req.source_type
        )
        return {"ok": True, "document": result}
    except ValueError as e:
        # PHX-FIX (2026-09-06, mesmo achado do usuário corrigido em
        # /api/rag/add-file logo abaixo - achado real, não hipotético:
        # esta rota IRMÃ tinha o MESMO bug, só que aqui o ValueError já
        # era capturado explicitamente e AINDA ASSIM virava 500 - a
        # distinção "isto é uma rejeição de regra de negócio previsível,
        # não uma falha de servidor" nunca chegou até o status HTTP,
        # mesmo já sabendo diferenciar o tipo da exceção): limite de
        # produto excedido (documentos/caracteres) é 422, não 500.
        raise HTTPException(status_code=422, detail=str(e))
    except RuntimeError as e:
        # Falha de infraestrutura de verdade (backend indisponível) -
        # continua sendo um erro de servidor, mas 503 é mais preciso que
        # 500 genérico (mesmo padrão já usado em outras rotas deste
        # arquivo pra "RAG backend indisponível").
        raise HTTPException(status_code=503, detail=str(e))


class RagQueryReq(BaseModel):
    query: str
    n_results: int = 5
    min_score: float = 0.0


@app.post("/api/rag/query")
async def rag_query(req: RagQueryReq):
    query = (req.query or "").strip()
    if not query:
        raise HTTPException(status_code=400, detail="Query RAG vazia.")
    backend = getattr(getattr(getattr(kernel, "planner", None), "knowledge", None), "rag_backend", None)
    if backend is None:
        raise HTTPException(status_code=503, detail="RAG backend indisponível (ChromaDB não conectado).")
    import asyncio as _asyncio
    hits = await _asyncio.get_event_loop().run_in_executor(
        None, backend.query_user_with_scores, query, max(1, min(req.n_results, 12))
    )
    hits = [h for h in hits if float(h.get("score", 0.0)) >= max(0.0, req.min_score)]
    return {"ok": True, "query": query, "hits": hits}


@app.post("/api/rag/add-file")
async def rag_add_file(file: UploadFile = File(...)):
    """Ingere documento real: upload -> Document Engine/OCR -> chunking -> ChromaDB."""
    resident = getattr(kernel, "resident", None)
    if resident is None:
        raise HTTPException(status_code=503, detail="ResidentManager não encontrado.")
    backend = getattr(getattr(getattr(kernel, "planner", None), "knowledge", None), "rag_backend", None)
    if backend is None:
        raise HTTPException(status_code=503, detail="RAG backend indisponível (ChromaDB não conectado).")

    temp_file, original_name = await _save_document_upload(file)
    try:
        limits = _current_rag_limits()
        upload_bytes = temp_file.stat().st_size
        if upload_bytes > limits["max_upload_bytes"]:
            raise HTTPException(
                status_code=413,
                detail=(
                    f"Arquivo excede o limite do plano {limits['plan'].upper()}: "
                    f"{upload_bytes / (1024 * 1024):.1f} MB; máximo "
                    f"{limits['max_upload_bytes'] / (1024 * 1024):.0f} MB."
                ),
            )

        extracted = await resident.extract_document_full_text_direct(str(temp_file.resolve()), original_name)
        if not extracted.get("ok"):
            raise HTTPException(status_code=422, detail=extracted.get("error", "Falha ao extrair documento para RAG."))
        text = str(extracted.get("text") or "").strip()
        if not text:
            raise HTTPException(status_code=422, detail="Documento não contém texto indexável.")

        import asyncio as _asyncio
        # PHX-FIX (2026-09-06, achado real do usuário + análise técnica
        # detalhada: "documento não deveria simplesmente terminar numa
        # sensação de 'deu erro'... exceder limite de produto não deveria
        # virar HTTP 500, porque não é falha interna do servidor. É uma
        # rejeição prevista pela regra de negócio"): `validate_product_
        # limits()` sempre levantou um ValueError CLARO e específico
        # ("Documento excede o limite do plano: X caracteres extraídos;
        # máximo permitido: Y" / "Limite de documentos do plano atingido:
        # X/Y") - mas nada aqui capturava esse ValueError, então o FastAPI
        # o tratava como exceção não prevista e devolvia 500 Internal
        # Server Error genérico, escondendo a mensagem específica que já
        # existia. Corrigido: mesma mensagem, agora como 422 (rejeição de
        # regra de negócio previsível, não falha de servidor).
        try:
            await _asyncio.get_event_loop().run_in_executor(
                None,
                lambda: backend.validate_product_limits(
                    original_name,
                    text,
                    max_documents=limits["max_documents"],
                    max_characters=limits["max_characters"],
                ),
            )
        except ValueError as e:
            raise HTTPException(status_code=422, detail=str(e))
        doc = await _asyncio.get_event_loop().run_in_executor(
            None, backend.add_document_chunked, original_name, text, temp_file.suffix.lstrip(".").upper()
        )
        return {
            "ok": True,
            "document": doc,
            "ocr_used": extracted.get("ocr_used", False),
            "ocr_pages_processed": extracted.get("ocr_pages_processed"),
            "ocr_pages_total": extracted.get("ocr_pages_total"),
            "ocr_truncated": extracted.get("ocr_truncated", False),
        }
    finally:
        if temp_file.exists():
            temp_file.unlink()


# PHX-NEW (auditoria completa, achado #3 do LEIA-ME): antes não existia
# NENHUM delete real - handleDeleteDocument no front só tirava da lista
# local em memória (EngineMissionControl.tsx), o documento continuava no
# ChromaDB pra sempre. Agora remove de verdade via
# ChromaRagBackend.delete_document.
@app.delete("/api/rag/{doc_id}")
async def rag_delete_document(doc_id: str):
    planner = getattr(kernel, "planner", None)
    backend = getattr(getattr(planner, "knowledge", None), "rag_backend", None)
    if backend is None:
        raise HTTPException(status_code=503, detail="RAG backend indisponível (ChromaDB não conectado).")
    try:
        import asyncio as _asyncio
        deleted = await _asyncio.get_event_loop().run_in_executor(None, backend.delete_document, doc_id)
        if not deleted:
            raise HTTPException(status_code=404, detail=f"Documento '{doc_id}' não encontrado.")
        return {"ok": True, "id": doc_id}
    except HTTPException:
        raise
    except RuntimeError as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/license")
async def get_license():
    # PHX-FIX (varredura 2026-08-21, achado 2): `except:` genérico
    # transformava QUALQUER falha (permissão negada, encoding inválido,
    # disco cheio) na mesma mensagem de "não encontrado" - o texto
    # devolvido é honesto sobre o caso comum (arquivo ausente), mas
    # mascara a causa real quando o problema é outro. Agora distingue
    # arquivo ausente (esperado, mensagem mantida) de qualquer outra
    # falha (logada de verdade).
    try:
        with open(LICENSE_PATH, "r", encoding="utf-8") as f:
            text = f.read()
    except FileNotFoundError:
        text = "License file not found."
    except Exception as e:
        logging.getLogger(__name__).error(f"/api/license: falha ao ler {LICENSE_PATH}: {e}")
        text = f"Falha ao ler o arquivo de licença: {e}"
    accepted = os.path.exists(LICENSE_ACCEPTED_FLAG)
    return {"text": text, "accepted": accepted}

@app.post("/api/license/accept")
async def accept_license():
    os.makedirs(os.path.dirname(LICENSE_ACCEPTED_FLAG), exist_ok=True)
    with open(LICENSE_ACCEPTED_FLAG, "w") as f:
        f.write("accepted")
    return {"ok": True}

# --- Endpoints de Telemetria e Firestore ---

@app.get("/api/telemetry/consent")
async def get_telemetry_consent():
    return {"consent": has_consent()}

@app.post("/api/telemetry/consent/accept")
async def accept_telemetry_consent():
    # PHX-FIX (varredura 2026-08-21, achado 2): o `consent: True` devolvido
    # é factualmente correto (o consentimento foi mesmo concedido), mas o
    # `except: pass` escondia se o sync que acontece na sequência
    # funcionou ou não - a rota vizinha /api/telemetry/sync (linha 621)
    # já faz isso certo, devolvendo o resultado do sync; agora esta rota
    # segue o mesmo padrão.
    grant_consent()
    sync_error = None
    try:
        await kernel.cloud_sync.sync_knowledge_base()
    except Exception as e:
        sync_error = str(e)
    result = {"consent": True}
    if sync_error:
        result["sync_error"] = sync_error
    return result

@app.post("/api/telemetry/consent/decline")
async def decline_telemetry_consent():
    revoke_consent()
    return {"consent": False}

@app.post("/api/telemetry/sync")
async def trigger_telemetry_sync():
    if not has_consent():
        return {"sent": 0, "consent": False, "error": "Consentimento não concedido."}
    try:
        sent = await kernel.cloud_sync.sync_knowledge_base()
        state_data = await kernel.state.get_state()
        await kernel.cloud_sync.sync_machine_state(state_data)
        return {"sent": sent, "consent": True}
    except Exception as e:
        return {"sent": 0, "consent": True, "error": str(e)}

# PHX-FIX (auditoria 2026-08-21, "consertar... phoenix vai aguardar docker
# responder e só depois continuar subindo tudo" - achado real de uso real:
# log do usuário mostrou "[!] Docker demorou muito para iniciar. Alguns
# serviços podem não subir." seguido, na mesma respiração, de "[✓] Phoenix
# API rodando" - ou seja, Phoenix já estava desistindo de esperar o Docker E
# o valor de retorno de ensure_docker_running() nunca era checado por quem
# chamava (linha "ensure_docker_running()" sozinha, sem `if not ...:`), então
# mesmo esse "desistir" não tinha efeito nenhum no fluxo - Phoenix sempre
# seguia em frente de qualquer forma.
#
# Root cause do "demorou muito": a janela de espera era só 30 tentativas *
# 2s = 60s. Docker Desktop no Windows, especialmente com o backend WSL2
# (que precisa montar o disco virtual, checar atualização do kernel WSL,
# reservar memória/CPU) pode legitimamente levar 1-3+ minutos pra ficar
# pronto num boot frio - 60s não é "travado", é só cedo demais pra desistir.
#
# Fix: MAX_WAIT_SECONDS sobe de 60s pra 600s (10min - a pedido explícito do
# usuário depois de testar a Rodada 23 com 5min), com feedback de progresso
# a cada ~30s (a espera silenciosa de antes parecia travada, sem nenhuma
# pista de que ainda estava tentando). Docker continua OPCIONAL de propósito
# (auditoria 2026-08-20, Seção 7 - "Docker Desktop virou OPTIONAL, sem
# Required... o módulo inteiro retornava falha e o bootstrap INTEIRO
# abortava" era o bug ORIGINAL que motivou tornar Docker opcional): se o
# Docker genuinamente não vier (não instalado, quebrado, usuário nunca quis
# usar Ollama via container), Phoenix ainda precisa conseguir subir sozinho
# depois do timeout - só que agora o timeout é generoso o bastante pra um
# Docker saudável, só lento, ter uma chance real de terminar de subir antes
# do Engine core (porta 8000/3000) seguir em frente.
_DOCKER_WAIT_INTERVAL_SECONDS = 5
_DOCKER_WAIT_MAX_SECONDS = 600

# PHX-FIX (auditoria 2026-08-21, "phoenix nao chamou docker... nunca chama" -
# achado real de uso real, depois da Rodada 23): o usuário relatou que
# Phoenix nunca chega a ABRIR o Docker Desktop de jeito nenhum (nem a
# mensagem "Tentando iniciar..." aparecia mais em consistência). Root
# cause, confirmado contra a documentação oficial do Docker (Docker Desktop
# for Windows - "Permission requirements"): esta lista só tinha os dois
# caminhos de instalação PARA TODOS OS USUÁRIOS (admin) -
# "C:\Program Files\Docker\Docker\Docker Desktop.exe" e a variante x86 -
# mas o Docker Desktop também suporta instalação SÓ PRO USUÁRIO ATUAL (sem
# privilégio de admin), que vai pra um caminho COMPLETAMENTE diferente:
# "%LOCALAPPDATA%\Programs\DockerDesktop\". Se o Docker do usuário foi
# instalado desse jeito (comum em máquina sem permissão de admin, ou por
# escolha), `os.path.exists()` retornava False pros dois caminhos antigos,
# e a função desistia IMEDIATAMENTE com "Docker Desktop.exe não encontrado.
# Inicie manualmente." - sem NUNCA chamar Popen, sem esperar nada. É
# exatamente o "nunca chama" relatado: o CLI `docker` estava no PATH (por
# isso a checagem `shutil.which("docker")` no topo da função passava), mas
# o executável GRÁFICO nunca era achado pra ser aberto.
_DOCKER_DESKTOP_EXE_CANDIDATES = [
    r"C:\Program Files\Docker\Docker\Docker Desktop.exe",
    r"C:\Program Files (x86)\Docker\Docker\Docker Desktop.exe",
]


def _find_docker_desktop_exe():
    """Procura o executável do Docker Desktop nos caminhos conhecidos de
    instalação - tanto pra-todos-os-usuários (admin, Program Files) quanto
    só-pro-usuário-atual (sem admin, %LOCALAPPDATA%). Devolve None se não
    achar em nenhum."""
    candidates = list(_DOCKER_DESKTOP_EXE_CANDIDATES)
    local_appdata = os.environ.get("LOCALAPPDATA")
    if local_appdata:
        candidates.append(os.path.join(local_appdata, "Programs", "DockerDesktop", "Docker Desktop.exe"))
    for candidate in candidates:
        if os.path.exists(candidate):
            return candidate
    return None


def ensure_docker_running():
    """Verifica se o Docker está online. Se não estiver, tenta iniciar o
    Docker Desktop e ESPERA de verdade (até 10min, com progresso) antes de
    devolver o controle - Docker continua opcional (nunca trava o boot do
    Engine pra sempre), mas não desiste mais cedo demais."""
    if not shutil.which("docker"):
        print("[!] Docker não encontrado no PATH. Instale o Docker Desktop.")
        return False

    try:
        result = subprocess.run(["docker", "info"], capture_output=True, text=True, timeout=5)
        if result.returncode == 0:
            print("[✓] Docker já está rodando.")
            return True
    except:
        pass

    print("[*] Docker Desktop offline. Tentando iniciar...")
    docker_exe = _find_docker_desktop_exe()

    if docker_exe:
        # PHX-FIX (mesma rodada): Popen sem try/except podia levantar uma
        # exceção não tratada aqui (ex: PermissionError, race condition
        # entre o os.path.exists() acima e o Popen) e derrubar o boot
        # INTEIRO da Phoenix com um traceback cru - o oposto do "Docker é
        # opcional, nunca trava o boot". Agora uma falha ao abrir o
        # executável vira um retorno limpo (False) com mensagem clara, sem
        # gastar os 10min de espera tentando falar com um processo que
        # nunca chegou a abrir.
        try:
            subprocess.Popen([docker_exe])
        except Exception as e:
            print(f"[!] Falha ao abrir o Docker Desktop ({docker_exe}): {e}")
            return False

        max_attempts = _DOCKER_WAIT_MAX_SECONDS // _DOCKER_WAIT_INTERVAL_SECONDS
        progress_every = max(1, round(30 / _DOCKER_WAIT_INTERVAL_SECONDS))
        for attempt in range(1, max_attempts + 1):
            time.sleep(_DOCKER_WAIT_INTERVAL_SECONDS)
            try:
                result = subprocess.run(["docker", "info"], capture_output=True, text=True, timeout=2)
                if result.returncode == 0:
                    print(f"[✓] Docker Desktop iniciado com sucesso ({attempt * _DOCKER_WAIT_INTERVAL_SECONDS}s).")
                    return True
            except:
                pass
            if attempt % progress_every == 0:
                elapsed = attempt * _DOCKER_WAIT_INTERVAL_SECONDS
                print(f"[*] Ainda aguardando o Docker Desktop responder... ({elapsed}s/{_DOCKER_WAIT_MAX_SECONDS}s)")
        print(
            f"[!] Docker não respondeu em {_DOCKER_WAIT_MAX_SECONDS}s. Continuando sem ele - "
            "serviços que dependem de container (Ollama/Open WebUI/SearXNG, se configurados) "
            "podem não subir; llama.cpp (motor padrão) não depende do Docker."
        )
        return False
    else:
        print(
            "[!] Docker Desktop.exe não encontrado em nenhum dos caminhos conhecidos "
            "(instalação para todos os usuários ou só pro usuário atual). "
            "Inicie manualmente."
        )
        return False

def open_browser():
    webbrowser.open_new("http://localhost:8000")

if __name__ == "__main__":
    import uvicorn

    # Garante que o Docker esteja rodando antes de ligar a Phoenix - espera
    # de verdade (até 10min, ver ensure_docker_running() acima), então tudo
    # abaixo daqui só roda DEPOIS que o Docker respondeu ou desistiu.
    docker_ready = ensure_docker_running()

    print("\n[✓] Phoenix API rodando em http://localhost:8000")
    if docker_ready:
        print("[✓] Phoenix Aviary Platform em http://localhost:3000")
    else:
        print(
            "[✓] Phoenix Aviary Platform em http://localhost:3000 "
            "(sem Docker - Ollama/Open WebUI/SearXNG indisponíveis se configurados)"
        )
    threading.Timer(1.5, open_browser).start()
    try:
        uvicorn.run(app, host="localhost", port=8000)
    except KeyboardInterrupt:
        print("\n[✓] Desligando Phoenix API...")
