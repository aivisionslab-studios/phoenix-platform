# Roadmap — AIVisions Phoenix Engine

## Implementado

- ✅ Kernel modular com boot sequence
- ✅ Discovery Engine (Windows + Linux)
- ✅ Telemetria ao vivo com sensores reais
- ✅ Runtime Engine (llama.cpp, Ollama, stable-diffusion.cpp, whisper.cpp)
- ✅ Planner + RAG local
- ✅ Gerente Residente
- ✅ App Store — Missões
- ✅ Dashboard Mission Control com accordion de sensores
- ✅ OCR nativo via Tesseract (comando `ocr`)
- ✅ Instalador multiplataforma (Windows 10/11 + Ubuntu/Debian) com bootstrap de Git, fallback PS 5.1 e self-tests
- ✅ Scanner de armazenamento com prioridade NVMe > SSD > HDD e detecção automática de disco de sistema
- ✅ Atalhos automáticos de Desktop/Menu Iniciar (Windows) e `.desktop` (Linux)
- ✅ Vulkan backend RX 580 / Polaris

## Próximos

- Rota HTTP `/api/ocr` real no `api_server.py` (upload de imagem direto do chat)
- Execution Guard — aprovação visual antes de instalar
- Auto-tuning de modelos por benchmark real
- Hardware Service centralizado com cache de snapshot
- Phoenix Knowledge Cloud — telemetria agregada
- Release pública estável

## Metodologia

Mudanças que quebram compatibilidade seguem a "Errata Evolutiva" (ver [PHILOSOPHY.md](./PHILOSOPHY.md)): documentadas de forma transparente no `CHANGELOG.md`, com aviso prévio quando possível.
