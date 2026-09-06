# Arquitetura — AIVisions Phoenix Engine

## Visão geral

A Phoenix não compete com llama.cpp, Ollama, ComfyUI ou OpenWebUI. Ela opera **uma camada acima**: detecta o hardware da máquina, entende o que ele consegue executar, provisiona a stack correta, e mantém tudo rodando — sem que o usuário precise saber uma única flag de compilação.

```
Usuário ──► Clica em "Iniciar_Phoenix"

Phoenix ──► Garante Git (bootstrap)
        ──► Escaneia todos os discos, escolhe o mais rápido com espaço
        ──► Detecta hardware (CPU, GPU, VRAM, RAM)
        ──► Provisiona dependências do SO (winget / apt)
        ──► Clona e compila os motores de inferência
        ──► Sobe containers, cria atalhos, roda self-tests
        ──► Ambiente pronto
```

## Fluxo de decisão

```
                    ┌─────────────────────┐
                    │   Hardware Scanner   │
                    │  CPU · GPU · VRAM    │
                    │  RAM · Storage       │
                    └──────────┬──────────┘
                               │
                    ┌──────────▼──────────┐
                    │  Classification      │
                    │  GPU Score           │
                    │  Machine Class       │
                    │  LOW / MEDIUM / HIGH │
                    └──────────┬──────────┘
                               │
                    ┌──────────▼──────────┐
                    │   Model Catalog      │
                    │  Recomendação por    │
                    │  tier de hardware    │
                    └──────────┬──────────┘
                               │
              ┌────────────────┼───────────────┐
              ▼                ▼               ▼
        llama.cpp /      stable-diffusion   whisper.cpp
          Ollama              .cpp
       (chat / coder)      (imagens)        (áudio)
              │                │               │
              └────────────────┴───────────────┘
                               │
                    ┌──────────▼──────────┐
                    │   Mission Control    │
                    │   Dashboard Web      │
                    │   localhost:8000     │
                    └─────────────────────┘
```

A decisão de qual backend usar é feita automaticamente com base no hardware detectado. O usuário vê o resultado — não o processo.

**Política de roteamento de hardware (definitiva):** modelos de texto (LLM/chat) rodam 100% em CPU via llama.cpp; modelos de imagem (SD 1.5/SDXL) rodam 100% em GPU via stable-diffusion.cpp/Vulkan. Isso evita as duas cargas disputarem VRAM ao mesmo tempo.

## Componentes principais

| Módulo | Responsabilidade |
|---|---|
| `api_server.py` | Backend FastAPI — API principal da plataforma |
| `phoenix_kernel/` | Núcleo da plataforma |
| `phoenix_kernel/discovery/` | Detecção de hardware (Windows: WMI/HardwareMonitor · Linux: lspci/lsblk/sysfs) |
| `phoenix_kernel/telemetry/` | Telemetria ao vivo — temperatura, carga, VRAM, fans |
| `phoenix_kernel/models/` | Catálogo, compatibilidade hardware/modelo, downloads |
| `phoenix_kernel/planner/` | Planejamento de missões e RAG |
| `phoenix_kernel/runtime/` | Execução dos motores de IA |
| `phoenix_kernel/resident/` | Gerente Residente — análise e decisão autônoma |
| `phoenix_kernel/services/` | Serviços auxiliares e provisioning (inclui `ocr_engine.py` — Tesseract nativo) |
| `phoenix_kernel/security/` | Regras de segurança |
| `phoenix_kernel/logs/` | Motor de eventos (histórico recente, comando `logs`) |
| `phoenix_kernel/api/` | Dispatcher de comandos (`process_command`) usado pela API |
| `core/` | Núcleo base compartilhado |
| `install/` | Instaladores multiplataforma (PowerShell) |
| `web/` | Dashboard Mission Control |
| `platform_source/` | Phoenix Aviary — interface de inferência |
| `catalog/` | Catálogo de modelos e regras de recomendação |
| `assets/` | Ícones da aplicação (`.ico` Windows / `.png` Linux) |

## Instalação por sistema operacional

O instalador é dividido em `install_phoenix.ps1` (bootstrap) + `install/windows.ps1` / `install/linux.ps1` / `install/common.ps1` / `install/storage_scanner.ps1` / `install/powershell.ps1`, validado ponta a ponta em Windows 10/11 e Ubuntu/Debian. Ver [INSTALLATION.md](./INSTALLATION.md).

## GitHub como fonte do projeto

Repositório oficial: [github.com/aivisionslab-studios/phoenix-engine](https://github.com/aivisionslab-studios/phoenix-engine). A prova de conceito original (RX 580 + Vulkan, sem CUDA/ROCm) está documentada em [rx580-local-ai-guide](https://github.com/aivisionslab-studios/rx580-local-ai-guide).
