# API — AIVisions Phoenix Engine

## Visão geral

A Phoenix expõe uma API local baseada em FastAPI (`api_server.py`), usada pelo dashboard Mission Control e por integrações externas. O dispatcher de comandos vive em `phoenix_kernel/api/engine.py` (`process_command`).

## Portas de referência

| Serviço | Porta |
|---|---|
| API Phoenix / Dashboard Mission Control | 8000 |
| Serviços de IA (Docker, ex. llama-server/sd-server) | 8081, 7860 |
| SearXNG | 8080 / 8081 |

## Health check

`GET /health` — retorna `200 OK` quando a API está operacional. Usado como verificação padrão pós-instalação.

## Comandos de missão

`POST /api/command` — envia um comando de missão/Terminal Deck para o Resident Manager processar (ex.: `infer`, `ocr`, `search`, `logs`, `aprovar`/`rejeitar`).

## Dashboard Mission Control (`localhost:8000`)

- **System Tuner** — CPU, RAM, GPU, VRAM, backends disponíveis, GPU Score e Machine Class em tempo real
- **Environment** — status de Docker, Python, Vulkan SDK, Ollama
- **Inference** — modelo ativo, uso de VRAM, temperatura e carga da GPU ao vivo
- **Phoenix Status** — documentos indexados no RAG, safety rules, estado do planner
- **Hardware Devices** — inventário completo de dispositivos e sensores
- **System Telemetry** — gráfico ao vivo de CPU/GPU load
- **Terminal Deck** — interface de comando

## Roadmap da API

Rota HTTP `/api/ocr` real (upload de imagem direto do chat) está no roadmap — hoje o OCR é acessado via comando `ocr` no Terminal Deck.

## Autenticação

*A definir formalmente para cenários multiusuário/comerciais.* Na versão atual, a API é local e assume ambiente de confiança (single-user, uso local).
