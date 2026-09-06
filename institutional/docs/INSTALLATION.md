# Instalação — AIVisions Phoenix Engine

## Quick Start

### Windows

```powershell
git clone https://github.com/aivisionslab-studios/phoenix-engine.git
cd phoenix-engine
```

Dê dois cliques em `Iniciar_Phoenix.bat` (ou "Executar como Administrador" — recomendado). Ele detecta sozinho se é a primeira execução: se não houver ambiente virtual, roda o instalador completo primeiro; se já existir, sobe a API direto. Depois de rodar uma vez, um atalho **Phoenix Engine** aparece na Área de Trabalho e no Menu Iniciar.

### Linux (Ubuntu/Debian)

```bash
sudo apt update && sudo apt install -y git
git clone https://github.com/aivisionslab-studios/phoenix-engine.git
cd phoenix-engine
sudo pwsh ./install_phoenix.ps1
```

Depois de instalado, use `./Iniciar_Phoenix.sh` (ou o ícone criado no menu de aplicativos) para subir a API nas próximas vezes, sem reprovisionar tudo de novo.

Nos dois casos, ao final: **http://localhost:8000**

## Sistemas operacionais suportados

- ✅ Windows 10 e Windows 11
- ✅ Ubuntu 24.04+, Ubuntu 26.04 LTS
- ✅ Debian 12+ (qualquer distro baseada em `apt-get`)
- ✅ Windows 10/11 + WSL2 (Ubuntu 22.04 / 26.04 LTS) — ambiente de referência testado

## Windows — o que o `install/windows.ps1` faz

Usa **winget** para provisionar, por categoria:

| Categoria | Pacotes |
|---|---|
| CORE | Docker Desktop, PowerShell 7, .NET SDK 9.0, Node.js LTS |
| BUILD | Visual Studio Build Tools, Vulkan SDK |
| AI | LM Studio |
| UTILITIES | FFmpeg, Tesseract OCR, PowerToys, GitHub Desktop, VLC, Firefox, Chrome |

Também: habilita WSL2 e Virtual Machine Platform, verifica virtualização VT-x/AMD-V e AVX2, libera portas oficiais no Firewall, habilita Developer Mode e Long Paths, ajusta a Execution Policy. Ao final, roda 6 self-tests (Python, Docker, HardwareMonitor, GPU Sensors, Vulkan, LM Studio CLI).

Sensores lidos via **LibreHardwareMonitor** (pythonnet) — componente **primordial**: se a instalação dele falhar, o provisionamento inteiro para.

## Linux — o que o `install/linux.ps1` faz

Usa PowerShell 7 como camada de automação multiplataforma (precisa rodar como root, `sudo pwsh`), provisionando via apt:

```
git (via bootstrap) · docker.io · docker-compose-v2 · build-essential
python3 · python3-venv · python3-pip
vulkan-tools · mesa-vulkan-drivers (RADV)
cmake · ffmpeg · tesseract-ocr
nodejs · npm · lm-sensors · pciutils
```

Sensores lidos via `/proc`, `/sys`, `lm-sensors`, `lspci`, `lsblk`. Validar Vulkan após instalação:

```bash
vulkaninfo --summary
```

## Passo a passo do instalador (`install_phoenix.ps1`)

1. **Git** — garantido primeiro, via winget/apt;
2. **PowerShell 7** — verifica e instala se preciso; se não conseguir confirmar o upgrade, segue em modo degradado;
3. **Scanner de armazenamento** (`storage_scanner.ps1`) — escaneia todos os discos, escolhe o mais rápido com pelo menos 40GB livres (cai para o HDD com mais espaço como último recurso), identifica o disco de sistema automaticamente;
4. **Camada específica do SO** — Windows (winget) ou Linux (apt), com self-tests e atalhos;
5. **Camada comum** (`common.ps1`) — cria o venv Python, clona os 45+ repositórios do ecossistema Aviary, compila o llama.cpp com Vulkan nativo, sobe containers Docker (Ollama, Open WebUI, SearXNG), inicia o Phoenix Studio e a `api_server.py`.

## Aviary WebUI (porta 3000) — Gemini opcional

A interface de chat (`platform_source/`, servida em `http://localhost:3000`) funciona inteiramente
com provedores locais (Ollama/LM Studio/llama-server) sem nenhuma configuração extra. O Gemini
(provedor de nuvem, opcional) **não usa login/senha** — é uma chave de API configurada uma única vez:

1. Gere uma chave em [aistudio.google.com/apikey](https://aistudio.google.com/apikey) (conta Google).
2. Em `platform_source/`, copie `.env.example` para `.env` e defina `GEMINI_API_KEY="<sua chave>"`.
3. Reinicie o processo Node da Aviary — a variável só é lida na subida do servidor.

Sem essa chave, os modelos Gemini simplesmente não aparecem como prontos no seletor e `/api/gemini/chat`
devolve um erro real em vez de falhar silenciosamente; nenhum outro recurso é afetado. Por padrão, o
RAG (documentos indexados pelo usuário) é **bloqueado** para provedores de nuvem mesmo com a chave
configurada — ver ["Privacidade do RAG com provedores de nuvem"](../../README.md#privacidade-do-rag-com-provedores-de-nuvem)
no README principal.

## Validação de instalação (referência real)

Ambiente testado: Windows 11 Pro, CPU Intel Xeon E5-2690 v3 (12c/24t, 3.5GHz), GPU AMD Radeon RX 580 (8GB VRAM), 32GB RAM DDR4 REG ECC, ~2.96TB de armazenamento.

- ✅ Stack SearXNG validado (portas 8080/8081)
- ✅ API FastAPI da Phoenix respondendo 200 OK em `/health` em `localhost:8000`
- ✅ Instalação também validada em Windows 10 e Ubuntu 26.04

Ver [TROUBLESHOOTING.md](./TROUBLESHOOTING.md) para problemas comuns.
