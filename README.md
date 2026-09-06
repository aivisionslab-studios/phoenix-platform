# 🔥 Phoenix Engine

```
██████╗ ██╗  ██╗ ██████╗ ███████╗███╗   ██╗██╗██╗  ██╗
██╔══██╗██║  ██║██╔═══██╗██╔════╝████╗  ██║██║╚██╗██╔╝
██████╔╝███████║██║   ██║█████╗  ██╔██╗ ██║██║ ╚███╔╝
██╔═══╝ ██╔══██║██║   ██║██╔══╝  ██║╚██╗██║██║ ██╔██╗
██║     ██║  ██║╚██████╔╝███████╗██║ ╚████║██║██╔╝ ██╗
╚═╝     ╚═╝  ╚═╝ ╚═════╝ ╚══════╝╚═╝  ╚═══╝╚═╝╚═╝  ╚═╝
```

**AIVisionsLab Studio Group · Creative & Tech Solutions**
*O futuro não espera. A gente constrói.*

**Local AI Orchestration Platform · 2026**

*"Hardware não morre — só espera o software certo."*

[![License: CC BY-NC 4.0](https://img.shields.io/badge/License-CC%20BY--NC%204.0-lightgrey.svg)](https://creativecommons.org/licenses/by-nc/4.0/)
![Backend](https://img.shields.io/badge/Backend-Vulkan%20%7C%20CPU-red)
![OS](https://img.shields.io/badge/OS-Windows%2010%2F11%20%7C%20Ubuntu%20%7C%20Debian-blue)
![Status](https://img.shields.io/badge/Status-Em%20desenvolvimento%20ativo-yellow)
![Build](https://img.shields.io/badge/Última%20auditoria-2026--09--03-success)

---

> **Nota de estado (2026-09-03):** Phoenix 4.5 integra a plataforma web e o runtime local.
> A geração de imagem usa o fork incluído **Phoenix Diffusion** por uma bridge C ABI em processo
> isolado; usa **SD 1.5 e SDXL** (Flux e SD3.5 foram removidos por crashar na RX 580 — ver
> [CHANGELOG](./docs/CHANGELOG.md)). O RAG mantém a trava de privacidade para provedores de nuvem,
> vetoriza cada documento uma única vez, e o Kokoro é o único motor TTS gerenciado. Esta versão
> adiciona o **pipeline determinístico de documentos e planilhas** (ver
> [DOCUMENT_PIPELINE](./docs/DOCUMENT_PIPELINE.md)): lê documentos e preenche planilhas em segundos,
> sem LLM na cola do dado, com guarda-fiscal e auditoria humana para NCM/CEST e código de barras.
> Suíte de testes: **612 passed, 2 skipped**.

---

## O que é o Phoenix Engine

A Phoenix não compete com llama.cpp, Ollama, ComfyUI ou OpenWebUI.

Ela opera **uma camada acima**: detecta o hardware da máquina, entende o que ele consegue executar, provisiona a stack correta, e mantém tudo rodando — sem que o usuário precise saber uma única flag de compilação.

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

O projeto nasceu de testes reais com uma AMD RX 580 8GB de 2017, executando LLMs e geração de imagem via Vulkan em 2026 — sem CUDA, sem ROCm, sem nuvem. O guia técnico completo dessa prova está em [rx580-local-ai-guide](https://github.com/aivisionslab-studios/rx580-local-ai-guide). A Phoenix é o próximo passo: transformar esse conhecimento específico em uma plataforma que se adapta a qualquer hardware.

---

## Índice

- [Hardware de referência](#hardware-de-referência-testado)
- [Arquitetura](#arquitetura)
- [Componentes principais](#componentes-principais)
- [Dashboard — Mission Control](#dashboard--mission-control)
- [RAG Knowledge Repository — planos e limites](#rag-knowledge-repository--planos-e-limites)
- [Phoenix Aviary — Chat, Voz, Busca e Colaboração](#phoenix-aviary--chat-voz-busca-e-colaboração)
- [App Store — Missões](#app-store--missões)
- [Catálogo de modelos por hardware](#catálogo-de-modelos-por-hardware)
- [Quick Start](#quick-start)
- [Windows](#windows)
- [Linux (Ubuntu / Debian)](#linux-ubuntu--debian)
- [O que o instalador faz, passo a passo](#o-que-o-instalador-faz-passo-a-passo)
- [Repos de terceiros](#repos-de-terceiros)
- [Estrutura do repositório](#estrutura-do-repositório)
- [Gerando um release/ZIP para auditoria](#gerando-um-releasezip-para-auditoria)
- [Troubleshooting](#troubleshooting)
- [Roadmap](#roadmap)
- [Créditos](#créditos)
- [Licença](#licença)

---

## Hardware de referência (testado)

| Componente | Especificação |
|---|---|
| CPU | Intel Xeon E5-2690 v3 · 12c/24t · 3.5GHz (2014) |
| GPU | AMD Radeon RX 580 2048SP · 8GB GDDR5 (Polaris/GCN4) |
| RAM | 32GB DDR4 REG ECC Quad Channel |
| Storage | NVMe + HDD (o instalador escolhe automaticamente o disco mais rápido com espaço suficiente) |
| Backends | CPU, Vulkan |
| OS | Windows 10/11 + WSL2 Ubuntu 22.04 / Ubuntu 26.04 LTS |
| Vulkan SDK | 1.4.341.1 |
| Driver AMD | 31.0.21924.61 |

> A Phoenix não é exclusiva para esse hardware. Foi desenhada para classificar e se adaptar a qualquer combinação de CPU/GPU/RAM. Esse é o ambiente onde é desenvolvida e validada primeiro.

---

## Arquitetura

A Phoenix opera como um **orquestrador puro**. Ela não reimplementa inferência — ela detecta, decide, configura e consome ferramentas já consolidadas como módulos plugáveis.

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
        llama.cpp /      Phoenix Diffusion  whisper.cpp
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

A decisão de qual backend usar (Vulkan, CPU, híbrido) é feita automaticamente com base no hardware detectado. O usuário vê o resultado — não o processo.

**Política de roteamento de hardware (definitiva):** modelos de texto (LLM/chat) rodam em CPU via llama.cpp; modelos de imagem (SD 1.5/SDXL) rodam pela bridge nativa Phoenix Diffusion/Vulkan. Isso evita as duas cargas disputarem VRAM ao mesmo tempo.

---

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
| `platform_source/` | Phoenix Aviary, Mission Control e proxy integrado (porta 3000) |
| `catalog/` | Catálogo de modelos e regras de recomendação |
| `assets/` | Ícones da aplicação (`.ico` Windows / `.png` Linux) |

---

## Dashboard — Mission Control

O Phoenix Engine roda um dashboard local (`localhost:8000`) com:

- **System Tuner** — CPU, RAM, GPU, VRAM, backends disponíveis, GPU Score e Machine Class em tempo real
- **Environment** — status de Docker, Python, Vulkan SDK, Ollama
- **Inference** — modelo ativo, uso de VRAM, temperatura e carga da GPU ao vivo
- **Phoenix Status** — documentos indexados no RAG, safety rules, estado do planner
- **Hardware Devices** — inventário completo de dispositivos e sensores (accordion por dispositivo)
- **System Telemetry** — gráfico ao vivo de CPU/GPU load
- **Terminal Deck** — interface de comando (`phoenix> infer <pergunta>`, `phoenix> ocr <caminho da imagem>`, `phoenix> search <busca>`)

---


## RAG Knowledge Repository — planos e limites

A Phoenix possui um **RAG Knowledge Repository local** para conhecimento fornecido pelo próprio
usuário. Documentos adicionados ao repositório são extraídos no backend, divididos em chunks,
vetorizados localmente no ChromaDB e consultados automaticamente pelo chat da Aviary quando houver
trechos semanticamente relevantes.

**Formatos aceitos pelo RAG:** `PDF`, `DOCX`, `XLSX`, `PPTX`, `TXT` e `MD`.
`RTF` não é suportado nesta versão. Em drag & drop com arquivos misturados, arquivos incompatíveis
são ignorados sem cancelar os documentos compatíveis do mesmo lote.

### Limites de produto

| Recurso | Phoenix Free | Phoenix Pro |
|---|---:|---:|
| Documentos lógicos no RAG | **10** | **Sem limite artificial de quantidade** |
| Upload máximo por arquivo | **25 MB** | **100 MB** |
| Texto extraído total no RAG | **150.000.000 caracteres** | **600.000.000 caracteres** |
| Chunking | Automático | Automático |
| Consulta pelo chat | Automática | Automática |

**Regra de contagem:** um documento lógico ocupa **uma vaga**, independentemente da quantidade de
chunks internos. Exemplo: um manual com 1.254 chunks continua contando como **1 documento**.

**Orçamento de caracteres é agregado, não por arquivo:** os documentos autorizados compartilham
um único total de texto extraído (150.000.000 no Free, 600.000.000 no Pro) — não é um teto
individual por documento. Exemplo no Free: um documento com 18.000.000 de caracteres e outro com
7.500.000 juntos consomem 25.500.000 do orçamento total; um terceiro documento só é aceito se
ainda houver espaço nos 150.000.000. Reindexar um documento já existente atualiza sua contribuição
para o total (a contagem antiga sai, a nova entra) — nunca soma as duas.

Os limites são aplicados pelo **Phoenix Engine (Python/FastAPI) antes da geração de embeddings**,
não apenas pela interface. A UI também mostra o uso atual (`N/10 FREE`), filtra formatos suportados,
aplica o limite de tamanho antes do upload e, em um lote maior que as vagas disponíveis, envia apenas
os documentos que cabem. Reindexar um documento já existente não consome uma nova vaga.

Arquivos que ultrapassam o limite de texto extraído são **rejeitados**, não truncados silenciosamente.
Documentos já indexados permanecem preservados; atingir o limite impede apenas a criação de novos
documentos lógicos até liberar uma vaga ou usar um plano com capacidade maior.

> **Ativação Pro:** a build pública opera como **Free por padrão**. O modo Pro exige um
> entitlement Ed25519 assinado pela AIVisionsLab. A chave privada não é distribuída com a Phoenix.
> Entitlements inválidos, expirados ou alterados falham de forma fechada para Free.

> **Propagação de cancelamento/downgrade:** como a Phoenix valida o entitlement localmente (pensado
> pra uso 100% offline), cancelar ou rebaixar uma licença Pro não derruba o acesso instantaneamente
> numa máquina sem conexão - o token assinado continua válido localmente até sua própria expiração
> (`exp`). Isso é uma decisão de design consciente pra manter o produto funcional offline, não uma
> falha do cache de verificação de 60s (que só evita chamadas repetidas em memória e nunca estende
> prazo nenhum). Na prática, uma máquina que nunca mais se conecta pode manter acesso Pro por até o
> tempo de vida do último token emitido.
>
> **Decisão confirmada (2026-08-28):** ao revisar este trade-off durante a auditoria completa, o
> dono do produto optou explicitamente por manter a prioridade **offline-first** - ou seja, aceitar
> essa janela de propagação como o comportamento pretendido, em vez de reduzir o TTL do token ou
> adicionar verificação online periódica. Revisitar isso é uma decisão de produto, não uma correção
> de bug pendente.



### Hardening contra bypass de limites

A Phoenix Free/Pro é aplicada no **Phoenix Engine**, não apenas na UI.

- o modo Pro exige **entitlement Ed25519 assinado**;
- a chave privada de assinatura nunca acompanha o software;
- somente a chave pública de verificação é distribuída;
- entitlement inválido, alterado, expirado ou incompatível com a máquina falha para **Free**;
- não existe `PHOENIX_PRODUCT_PLAN=pro` como desbloqueio de produção;
- número de documentos, tamanho e caracteres são revalidados no backend antes dos embeddings;
- a licença pode ser vinculada à máquina;
- o Node continua com teto físico de upload e o Python é a autoridade final.

Como a Phoenix roda localmente, nenhum mecanismo puramente local é literalmente inviolável contra
alguém que controle a máquina e modifique o programa. Para proteção comercial forte, a assinatura
local deve ser combinada futuramente com um serviço autenticado de entitlement, revogação e renovação.



#### Proteção contra inserção direta no ChromaDB

O limite Free não é verificado apenas no momento do upload. O Knowledge Repository mantém um
**registry local de documentos autorizados**, protegido por HMAC-SHA256. Um documento inserido
diretamente no `data/chroma_db` sem passar pelo fluxo autorizado:

- não entra no contador `N/10 FREE`;
- não aparece como documento ativo no Knowledge Repository;
- não é retornado por `/api/rag/query`;
- não é injetado automaticamente no chat;
- aparece na telemetria de segurança como `locked_or_unregistered_documents`.

O `ChromaRagBackend.add_document_chunked()` também reaplica os limites do plano diretamente, então
chamar o backend sem passar pela rota HTTP não remove a política Free/Pro.

O RAG interno da Phoenix continua separado logicamente: consultas internas do Planner podem usar a
base técnica da Engine, enquanto `/api/rag/query` é restrito à allowlist do repositório do usuário.

> O HMAC é defesa em profundidade local, não uma promessa de inviolabilidade. Um administrador com
> controle total da máquina ainda pode patchar código ou extrair segredos locais. Licenciamento
> comercial forte deve continuar usando entitlement Ed25519 e, futuramente, validação remota.



#### Phoenix RAG Integrity Chain — consenso local 4/4

As travas anteriores continuam ativas e agora são cruzadas por uma cadeia de integridade local:

1. **Entitlement/plan state** — Free/Pro + assinatura Ed25519 + machine binding opcional.
2. **RAG User Registry** — allowlist dos documentos autorizados, protegida por HMAC-SHA256.
3. **RAG Usage Ledger** — cadeia `authorize/reindex/revoke`, com `previous_hash`, `event_hash`,
   geração monotônica e HMAC do arquivo inteiro.
4. **Integrity Manifest** — checkpoint que referencia hashes do registry e ledger, machine fingerprint,
   estado do entitlement e hash do manifest anterior.

A regra é **4/4 obrigatório**. Não existe quorum 3/4.

Qualquer divergência coloca somente o Knowledge Repository do usuário em **fail-closed**:
os dados não são apagados e o chat normal continua funcionando, mas o RAG do usuário não injeta
conhecimento enquanto os quatro estados não voltarem a concordar.

Cada chunk novo do Chroma recebe referências cruzadas:
`ledger_generation`, `ledger_event_hash` e `registry_parent_id`. A consulta valida essas referências
antes de aceitar o chunk.

Isso se soma às travas já existentes:
- 10 documentos / 25 MB / 150.000.000 caracteres no Free;
- limites reaplicados no FastAPI e no próprio ChromaRagBackend;
- allowlist contra inserção direta no ChromaDB;
- entitlement Ed25519;
- registry HMAC;
- machine binding opcional;
- fail-closed em corrupção/adulteração.

> É inspirado em encadeamento de hashes, mas não é Bitcoin/blockchain distribuída. Todos os estados
> continuam locais. Um administrador que controle totalmente a máquina ainda pode patchar o software.



#### Privacidade do RAG com provedores de nuvem

Desde a v57, o RAG é consultado automaticamente em **toda mensagem** do chat, pra **qualquer**
provedor selecionado — inclusive um provedor de nuvem (hoje só Gemini). Isso significa que, sem
nenhuma proteção, trechos dos seus documentos indexados sairiam da sua máquina sempre que você
conversasse com o Gemini com RAG ativo.

Por isso existe uma trava dedicada, **ligada por padrão**:

- **`Bloquear RAG em provedores de nuvem`** (Parâmetros do chat, na Aviary) — quando ligada (padrão) e
  o provedor ativo é de nuvem, a consulta ao `/api/rag/query` **nem é feita**: a proteção é não fazer
  a chamada de rede, não só descartar o resultado depois.
- Um indicativo visual permanente (`RAG bloqueado (nuvem)`) aparece ao lado do seletor de modelo
  sempre que a trava estiver ativa nesse provedor — não é um aviso que aparece uma vez e some.
- Provedores locais (Ollama, llama-server, LM Studio) nunca são afetados por esta flag — o RAG sempre
  funciona neles, porque o contexto já fica 100% na sua máquina.
- Você pode desligar essa trava explicitamente em Parâmetros se quiser usar RAG com um provedor de
  nuvem mesmo assim (por exemplo, pra documentos que você já considera não sensíveis).

O limiar de relevância do RAG (`min_score: 0.15`, usado pra decidir se um trecho é relevante o
suficiente pra entrar no contexto) ainda não foi validado empiricamente com uso real — o chat registra
(`console.debug`, aba Console do navegador) quando uma consulta encontra resultado, não encontra nada,
ou falha, especificamente para permitir essa calibração com dados reais.


## Phoenix Aviary — Chat, Voz, Busca e Colaboração

A **Phoenix Aviary** (`platform_source/`) é a interface de conversa/inferência real (rota `/api/proxy/*`
no `server.ts`, servida na porta 3000 e proxiada via 8000). É o app onde o usuário efetivamente conversa
com um modelo, gera imagem, ouve voz e roda a Arena. Capacidades confirmadas em código e testadas de
ponta a ponta nesta rodada de auditoria (v31→v57 + auditoria completa de 2026-08-28):

- **Chat de texto** — roteamento CPU (llama.cpp/Ollama) definido por política fixa; contexto do
  `llama-server` em **16384 tokens** (subiu de 8192 na v54); timeout do proxy de chat agora escala
  dinamicamente com o limite de tokens do pedido em vez de um teto fixo de 300s (bug do `undici`
  corrigido na v56 — respostas longas em CPU pura, ~4,6 tok/s medidos, passavam fácil dos 5 minutos).
- **Geração de imagem** — SD1.5/SDXL/FLUX via Phoenix Diffusion/Vulkan; seletor de
  modelo lê a pasta `Models/Image` de verdade (sem lista fixa) e filtra componentes auxiliares (VAE/
  CLIP/T5) da lista principal.
- **Voz (Kokoro-82M, ONNX)** — motor único de voz desde a v47; identificadores internos antigos ainda
  preservam o nome `piper` apenas por compatibilidade de API. Detecção automática de idioma
  via `py3langid`, 8 idiomas + modo Automático. Ferramenta dedicada "Texto → Áudio" e conversor
  "Documento → Audiolivro" (PDF/DOCX/PPTX/TXT/MD → um único MP3/WAV, troca de voz automática por
  frase quando o idioma muda dentro do documento). Download do modelo (~340MB) e verificação de
  integridade automáticos pelo próprio app. **Aceleração GPU (DirectML) testada e descartada** — a
  RX 580 falha de forma reprodutível numa camada do vocoder (`ConvTranspose`) por limitação do driver,
  não do código da Phoenix; padrão é CPU.
- **Busca web real (SearXNG)** — desde a v52, mensagens começando com um verbo de busca explícito
  ("pesquisar", "busca", "procure", "search for"...) disparam uma consulta real ao SearXNG (porta 8080)
  antes de o modelo responder, com os resultados exibidos na tela. Antes disso a busca só existia
  dentro da Arena.
- **Arena — colaboração entre dois modelos (`dual_collab.py`)** — dois modelos (tipicamente um CPU e um
  GPU) debatem/revisam uma proposta em rodadas, com um **verificador objetivo** (`patch_verification.py`)
  que roda o código proposto de verdade em subprocesso isolado (nunca `exec()` no processo principal,
  timeout de 10s, denylist baseado em AST contra `import os`/`subprocess`/introspecção via dunder) em
  vez de aceitar a opinião dos modelos entre si. Guarda-corpos confirmados por teste real:
  - Encerramento mútuo (`PROJETO_CONCLUIDO` dos dois lados) só vira `✅ Concluída` em tópicos
    verificáveis se o **último veredito for um `CONFIRMADO` explícito** — `FALHOU` ou silêncio não
    fecham mais a sessão (fechado na v40; era um item pendente de rodadas anteriores da auditoria).
  - Guarda de repetição (`difflib`, 80% de similaridade / 80+ caracteres, mesmo lado) interrompe a
    colaboração em vez de girar em `max_rounds` reciclando o mesmo texto.
  - Instrução de idioma explícita (PT-BR) no início do prompt — reforço, não garantia; modelo pequeno
    ainda pode deslizar ocasionalmente para inglês, sobretudo em tarefas de código.
  - Progresso incremental: cada rodada aparece na tela assim que termina (polling a cada 1,5s), não
    só no final das 6 rodadas.
  - `formatCollabResultForChat()` (botão "Enviar resultado pro chat") sempre inclui o veredito real
    (🧪 confirmado / ⚠️ não confirmado) — antes dependia do modelo repetir a linha por acaso.
  - Limitações documentadas e **não** resolvidas: crítica forçada contra design estruturalmente errado
    (qualidade de raciocínio, não veracidade do veredito) e o harness só cobre função solta isolada.
- **RAG (base de conhecimento local, ChromaDB)** — desde a v57, **qualquer modelo no chat normal**
  (local ou de nuvem) consulta automaticamente o RAG Knowledge Repository do usuário em toda mensagem,
  não só o agente autônomo (Resident/Missões). Aceita `PDF`/`DOCX`/`XLSX`/`PPTX`/`TXT`/`MD` com
  chunking real (documentos grandes não ficam mais truncados num único chunk). Ver seção dedicada
  ["RAG Knowledge Repository — planos e limites"](#rag-knowledge-repository--planos-e-limites)
  acima, incluindo a **trava de privacidade que bloqueia o RAG por padrão em provedores de nuvem**
  (ex.: Gemini) — só desliga se o usuário quiser explicitamente.

### Configurando o Gemini (opcional)

O Gemini **não usa login/senha** dentro da Phoenix — é configurado uma única vez com uma chave de API
num arquivo local. Sem essa chave, `/api/gemini/chat` devolve um erro real (nunca finge sucesso) e a
Aviary funciona normalmente com qualquer provedor local (Ollama/LM Studio/llama-server).

1. Gere uma chave em [aistudio.google.com/apikey](https://aistudio.google.com/apikey) com sua conta
   Google — clique em "Create API key". Se for a primeira vez usando o Google AI Studio, ele cria um
   projeto de Google Cloud padrão automaticamente, sem precisar configurar faturamento antes.
2. Dentro de `platform_source/`, copie `.env.example` para `.env` (se ainda não existir) e edite a
   linha `GEMINI_API_KEY="MY_GEMINI_API_KEY"`, substituindo pela chave gerada.
3. Reinicie o processo Node da Aviary (`npm run dev` ou o processo em produção) — a variável só é lida
   na subida do servidor.
4. Os modelos Gemini passam a aparecer no seletor do chat automaticamente (`hasGeminiKey`, checado por
   `server.ts`).

> Chaves "Standard" mais antigas do Google AI Studio deixam de funcionar em setembro de 2026; gerando
> a chave pelo link acima você já recebe o formato novo ("auth key").

---

## App Store — Missões

Em vez de instalar peça por peça, a Phoenix oferece **missões**: pacotes coerentes de ferramentas + modelos para um objetivo específico.

| Missão | O que provisiona | Tempo | Tamanho |
|---|---|---|---|
| 🧠 Assistente Pessoal | LLM + RAG para estudos e produtividade | 20–40 min | 15 GB |
| 💬 Conversar com IA | Stack completa de chat local | 15–30 min | 10 GB |
| 🖥️ Modo CPU Only | Para máquinas sem GPU dedicada | 10 min | 5 GB |
| 💻 Ambiente Dev | Ferramentas de programação + IA | 15–20 min | 10 GB |
| 🎨 Criar Imagens | Geração de imagens + workflows | 20–40 min | 25 GB |
| 🔍 Pesquisa Inteligente | Busca privada + RAG local | 10–15 min | 5 GB |
| 🎙️ Studio de Voz Offline | STT, TTS e clonagem de voz | 15–20 min | 8 GB |
| 🚀 Plataforma Completa | Tudo que o hardware suporta | 60+ min | 50+ GB |
| ⚡ RX 580 Revival | Otimizado para Polaris/GCN4 via Vulkan | 20–30 min | 15 GB |

---

## Catálogo de modelos por hardware

A Phoenix classifica o hardware detectado e recomenda modelos compatíveis — sem tentativa e erro:

```
VRAM detectada: 8192 MB
Machine Class: MEDIUM
GPU Score: 94%

Modelos recomendados:
★★★★★ qwen3:8b           — assistente geral, cabe 100% em VRAM
★★★★★ gemma3:4b          — muito rápido, baixo consumo
★★★★☆ qwen2.5-coder:7b   — programação
★★★★☆ llama3.2:3b        — uso geral / português

Modelos híbridos (VRAM + RAM):
★★★☆☆ deepseek-r1:14b    — raciocínio, offload parcial necessário

Não recomendado para este hardware:
✗ qwen3:30b
✗ llama3.3:70b
✗ deepseek-r1:671b
```

O catálogo completo (regras de classificação, VRAM mínima, estratégia de offload) vive em [`catalog/`](./catalog).

---

## Quick Start

### Windows

```powershell
git clone https://github.com/aivisionslab-studios/phoenix-platform.git
cd phoenix-engine
```

Dê **dois cliques em `Iniciar_Phoenix.bat`** (ou "Executar como Administrador" — recomendado). Ele detecta sozinho se é a primeira execução: se não houver ambiente virtual ainda, roda o instalador completo primeiro. Quando a `.venv` já existe, o launcher também verifica a bridge nativa de imagens antes de subir a API; se `phoenix_sd_bridge.dll` estiver ausente, recompila apenas a Phoenix Diffusion e promove a DLL para `bin/`, sem reinstalar modelos, RAG ou Python. Depois de rodar uma vez, um atalho **Phoenix Engine** aparece na Área de Trabalho e no Menu Iniciar — clique nele nas próximas vezes.

Se quiser forçar somente esse reparo, feche a Phoenix e execute
`Reparar_Phoenix_Diffusion.bat`. A última mensagem do reparador informa
explicitamente se falta CMake, Visual Studio C++ Build Tools ou Vulkan SDK.
O sub-build temporário do gerador de shaders usa `C:\pxb\phxsd` para evitar
o erro `FTK1011` do MSBuild em caminhos profundos; a DLL utilizável continua
dentro do projeto, em `bin\phoenix_sd_bridge.dll`.

### Linux (Ubuntu/Debian)

```bash
sudo apt update && sudo apt install -y git
git clone https://github.com/aivisionslab-studios/phoenix-platform.git
cd phoenix-engine
sudo pwsh ./install_phoenix.ps1
```

Depois de instalado, use `./Iniciar_Phoenix.sh` (ou o ícone criado no menu de aplicativos / Área de Trabalho) para subir a API nas próximas vezes, sem reprovisionar tudo de novo.

Nos dois casos, ao final: **http://localhost:8000**

---

## Windows

Compatível com **Windows 10 e Windows 11**.

O bootstrap (`install_phoenix.ps1`) garante **Git** via winget como primeiro passo — antes de qualquer outra coisa, inclusive antes de confirmar PowerShell 7. Se o ambiente ainda estiver no Windows PowerShell 5.1 nesse ponto, o instalador reconhece isso automaticamente (PS 5.1 só existe no Windows) e segue mesmo assim em modo degradado, em vez de travar.

O `install/windows.ps1` então usa **winget** para provisionar, por categoria:

<!-- PHX-FIX (auditoria 2026-08-20, "política final de runtimes"): esta
tabela ainda mostrava Docker Desktop dentro de CORE e uma categoria "AI"
genérica pra LM Studio - defasada em relação ao próprio código de
install/windows.ps1 (`$PackageCategories`), que já tinha corrigido isso
numa auditoria anterior (Docker virou OPTIONAL, "AI" virou
OPTIONAL_RUNTIMES) - a correção estava documentada em LEIA-ME_PRIMEIRO.md,
mas nunca tinha chegado até aqui. -->

| Categoria | Pacotes | Obrigatório? |
|---|---|---|
| CORE | PowerShell 7, .NET SDK 9.0, Node.js LTS | Sim — falha aqui interrompe a instalação inteira. |
| BUILD | Visual Studio Build Tools, Vulkan SDK | Sim. |
| OPTIONAL_RUNTIMES | LM Studio | Não. LM Studio nunca é o motor de orquestração da Phoenix (`ResidentManager` só aceita `llama.cpp`/`ollama` como runtime de texto) — existe só como opção manual no seletor de provedores do Aviary. Falha no winget vira aviso, não bloqueio. |
| OPTIONAL | Docker Desktop | Não. Só é usado pelos containers opcionais (Ollama/Open WebUI/SearXNG, ver `common.ps1`) — o llama.cpp nativo (o runtime padrão de verdade) não depende disso. Falha no winget vira aviso, não bloqueio. |
| UTILITIES | FFmpeg, Tesseract OCR (com fallback de download direto se o winget falhar), PowerToys, GitHub Desktop, VLC, Firefox, Chrome | Não. |

Além disso, configura o Windows: habilita WSL2 e Virtual Machine Platform (se ainda não estiverem), verifica virtualização VT-x/AMD-V e suporte a AVX2, libera as portas oficiais da Phoenix no Firewall, habilita Developer Mode e Long Paths (necessário pros 45+ repositórios clonados), e ajusta a Execution Policy.

Ao final, roda 6 self-tests (Python, Docker, HardwareMonitor, GPU Sensors, Vulkan, LM Studio CLI) e cria os atalhos de Desktop/Menu Iniciar.

Sensores de hardware lidos via **LibreHardwareMonitor** (pythonnet) — é tratado como componente **primordial**: se a instalação dele falhar, o provisionamento inteiro para (não é só um aviso), porque sem ele a Phoenix não enxerga a GPU.

```powershell
# Recomendado: clique com o botão direito em Iniciar_Phoenix.bat -> "Executar como administrador"
.\Iniciar_Phoenix.bat
```

---

## Linux (Ubuntu / Debian)

Compatível com **Ubuntu 24.04+**, **Ubuntu 26.04 LTS** e **Debian 12+** (qualquer distro baseada em `apt-get`).

O instalador usa **PowerShell 7** como camada de automação multiplataforma — precisa rodar como root (`sudo pwsh`), porque provisiona pacotes de sistema. O `install/linux.ps1` provisiona via apt:

```
git (via bootstrap, antes do resto)
docker.io · docker-compose-v2 · build-essential
python3 · python3-venv · python3-pip
vulkan-tools · mesa-vulkan-drivers (RADV)
cmake · ffmpeg · tesseract-ocr
nodejs · npm · lm-sensors · pciutils
```

Instalação:

```bash
sudo apt update && sudo apt install -y git
git clone https://github.com/aivisionslab-studios/phoenix-platform.git
cd phoenix-engine
sudo pwsh ./install_phoenix.ps1
```

Ao final, cria um atalho `.desktop` no menu de aplicativos e (se existir) na Área de Trabalho — resolvendo o usuário real por trás do `sudo` (via `SUDO_USER`), não o `root`, e respeitando o nome localizado da pasta (`~/Área de Trabalho` em PT-BR, não só `~/Desktop`).

Sensores de hardware lidos via **/proc**, **/sys**, **lm-sensors**, **lspci** e **lsblk**. GPU AMD com driver Mesa RADV expõe temperatura e VRAM via sysfs.

Validar Vulkan após instalação:

```bash
vulkaninfo --summary
```

Resultado esperado com RX 580:

```
GPU0: AMD Radeon RX 580 | DRIVER_ID_MESA_RADV | driverInfo: Mesa 26.x
```

---

## O que o instalador faz, passo a passo

1. **Git** — garantido primeiro, via winget/apt, antes de qualquer outra dependência (nada mais funciona sem ele).
2. **PowerShell 7** — verifica e instala se preciso; se não conseguir confirmar o upgrade, segue em modo degradado em vez de travar.
3. **Scanner de armazenamento** — escaneia todos os discos (`NVMe`/`SSD`/`HDD` reais, não por suposição de barramento), escolhe o mais rápido com pelo menos 40GB livres; se nenhum tiver, cai pro HDD com mais espaço como último recurso. Identifica o disco de sistema sozinho (`IsBoot` no Windows / mountpoint `/` no Linux) — nunca assume letra de unidade fixa.
4. **Camada específica do SO** — Windows (winget) ou Linux (apt), categorizada, com self-tests e atalhos de Desktop/Menu.
5. **Camada comum** — cria o venv Python, clona os 45+ repositórios do ecossistema Aviary, compila o llama.cpp com Vulkan nativo, sobe os containers Docker (Ollama, Open WebUI, SearXNG), inicia o Phoenix Studio (Node.js) e a `api_server.py`.

Se qualquer etapa exigir reinício (ex: Docker Desktop recém-instalado, WSL2 recém-habilitado), o instalador para ali, avisa, e pede pra rodar de novo depois do reinício — em vez de seguir tentando usar algo que ainda não terminou de subir.

---

## Repos de terceiros

A Phoenix usa dependências externas e também inclui o código-fonte vendorizado do Phoenix Diffusion/GGML. Cada projeto mantém sua própria licença; os avisos dos componentes incluídos ficam preservados em `src/phoenix-diffusion.cpp/`. Outros motores são provisionados de suas fontes oficiais. Exemplos:

| Categoria | Projetos |
|---|---|
| Runtime de Inferência | [llama.cpp](https://github.com/ggml-org/llama.cpp), [Ollama](https://github.com/ollama/ollama), [vLLM](https://github.com/vllm-project/vllm), [KoboldCpp](https://github.com/LostRuins/koboldcpp), [LocalAI](https://github.com/mudler/LocalAI), [ExLlamaV2](https://github.com/turboderp-org/exllamav2), [MLC-LLM](https://github.com/mlc-ai/mlc-llm), [SGLang](https://github.com/sgl-project/sglang) |
| Geração de Imagem | Phoenix Diffusion (fork incluído; base atribuída a [stable-diffusion.cpp](https://github.com/leejet/stable-diffusion.cpp)), ComfyUI opcional |
| Áudio | [whisper.cpp](https://github.com/ggml-org/whisper.cpp), [faster-whisper](https://github.com/SYSTRAN/faster-whisper), [Kokoro](https://github.com/hexgrad/kokoro), [Coqui-TTS](https://github.com/idiap/coqui-ai-TTS), [Applio](https://github.com/IAHispano/Applio) |
| Interfaces | [OpenWebUI](https://github.com/open-webui/open-webui), [LibreChat](https://github.com/danny-avila/LibreChat), [SillyTavern](https://github.com/SillyTavern/SillyTavern), [LobeChat](https://github.com/lobehub/lobe-chat), [Big-AGI](https://github.com/enricoros/big-AGI) |
| Agentes / AI OS | [CrewAI](https://github.com/crewAIInc/crewAI), [AutoGen](https://github.com/microsoft/autogen), [LangGraph](https://github.com/langchain-ai/langgraph), [Open Interpreter](https://github.com/OpenInterpreter/open-interpreter), [OpenHands](https://github.com/All-Hands-AI/OpenHands) |
| Hardware (Windows) | [LibreHardwareMonitor](https://github.com/LibreHardwareMonitor/LibreHardwareMonitor) — componente primordial, clonado só no Windows |
| Busca | [SearXNG](https://github.com/searxng/searxng) — não clonado, roda via Docker |

Lista completa e sempre atualizada: [`install/common.ps1`](./install/common.ps1) (dicionário `$Repos`).

---

## Estrutura do repositório

```
phoenix-engine/
│
├── install_phoenix.ps1        # Bootstrap: Git -> PS7 -> Storage -> SO -> Common
├── Iniciar_Phoenix.bat        # Launcher único Windows (instala/repara o runtime e inicia)
├── Reparar_Phoenix_Diffusion.bat # Recompila somente a bridge nativa Vulkan
├── Iniciar_Phoenix.sh         # Launcher de uso diario Linux
│
├── install/
│   ├── storage_scanner.ps1    # Escaneia discos, escolhe o melhor, identifica disco de sistema
│   ├── windows.ps1            # Provisionamento Windows 10/11 (winget, categorizado)
│   ├── linux.ps1               # Provisionamento Ubuntu/Debian (apt)
│   ├── common.ps1              # Camada comum (venv, 45+ repos, compilacao, containers)
│   └── powershell.ps1          # Garante PowerShell 7
│
├── assets/
│   ├── phoenix_engine.ico     # Icone Windows (Desktop/Menu Iniciar)
│   └── phoenix_engine.png     # Icone Linux (.desktop)
│
├── phoenix_kernel/
│   ├── kernel.py               # Boot e orquestracao (Composition Root)
│   ├── discovery/              # Deteccao de hardware
│   ├── telemetry/              # Sensores ao vivo
│   ├── models/                 # Catalogo e gerenciamento de modelos
│   ├── planner/                # Planejamento e RAG
│   ├── runtime/                # Execucao dos motores de IA
│   ├── resident/                # Gerente Residente autonomo
│   ├── services/
│   │   ├── engine.py            # ServicesEngine
│   │   └── ocr_engine.py        # OCR nativo via Tesseract
│   ├── security/                # Regras de seguranca
│   ├── logs/                    # Motor de eventos (comando "logs")
│   ├── api/
│   │   └── engine.py             # Dispatcher de comandos (process_command)
│   └── core/                    # Tipos e enums base
│
├── core/                       # Nucleo base compartilhado
├── catalog/                    # Catalogo de modelos e pacotes
├── web/                        # Dashboard Mission Control
├── platform_source/            # Phoenix Aviary Platform
├── data/                       # Estado local (nao versionado)
├── docs/                       # Documentacao de arquitetura
├── tools/                      # Scripts auxiliares
├── api_server.py               # Backend FastAPI
├── setup_environment.py        # Setup do ambiente Python
├── LICENSE.md
└── README.md
```

---

## Gerando um release/ZIP para auditoria

Este projeto é distribuído como **release de código-fonte**: `platform_source/dist/`
(o build do Node) e `platform_source/node_modules/` **nunca** vão dentro de um ZIP de
release (estão no `.gitignore` de propósito) — quem recebe o pacote roda `npm install`
seguido de `npm run build` dentro de `platform_source/` (ou simplesmente usa
`install_phoenix.ps1`, que já faz isso sozinho). Se você abrir um ZIP de release e tentar
`npm run build` direto sem `npm install` antes, o erro `vite: not found` é esperado — não
é um bug, é falta desse passo.

Pra gerar um ZIP de release (rodar de dentro da raiz do projeto):

```bash
python3 build_release_zip.py --out /caminho/para/PHOENIX-4.5.zip
```

Esse script (novo a partir da Rodada 15, depois de um ZIP anterior ter vazado uma
credencial real por engano) monta o pacote a partir de um **allowlist real via
`.gitignore`** (usando `git add -A` + `git ls-files` num repositório git descartável,
nunca deixado no projeto) — não de "pasta inteira menos uma lista de exclusão manual".
Isso garante que nenhum segredo (`data/config/firestore_credentials.json`, `.env`, etc.)
ou estado local (`data/hardware.db`, IDs de máquina, logs de instalação) vai pro pacote,
mesmo que alguém esqueça de atualizar uma lista de exclusão manual no futuro. Ele também
varre o resultado final por conteúdo de credencial real antes de zipar e **recusa gerar
o ZIP** se achar alguma. Rodar só `python3 verify_release_clean.py` continua útil como
checagem rápida contra a árvore de trabalho, mas o gerador oficial de release é o
`build_release_zip.py`.

---

## Troubleshooting

**Dashboard não sobe em `localhost:8000`**
Confirme que `api_server.py` está rodando e que a porta não está em uso.

**"Sistema operacional nao suportado" logo no início, no Windows**
Sintoma de o upgrade automático pro PowerShell 7 não ter completado (ex: winget do PS7 falhou silenciosamente). O `install_phoenix.ps1` atual já trata esse caso — se ainda estiver no PS 5.1 depois da tentativa, segue em modo degradado em vez de travar. Se persistir, confirme manualmente: `winget install Microsoft.PowerShell` e rode `pwsh ./install_phoenix.ps1` direto.

**GPU não aparece no System Tuner (Windows)**
O processo precisa ser executado como Administrador — sensores de GPU via LibreHardwareMonitor exigem elevação. Rode `Iniciar_Phoenix.bat` como Admin. Se a instalação do LibreHardwareMonitor falhar, o instalador para com erro (é tratado como componente primordial, não apenas um aviso).

**GPU não aparece no System Tuner (Linux)**
Confirme que o driver Mesa RADV está instalado: `vulkaninfo --summary`. Para temperatura, verifique se lm-sensors está configurado: `sensors`.

**`ModuleNotFoundError: No module named 'phoenix_kernel.logs'` (ou qualquer outro submódulo)**
Confirme se essa pasta não está sendo capturada por engano pelo `.gitignore`. Um padrão como `logs/` (sem `/` na frente) ignora **qualquer** pasta chamada `logs` no repositório inteiro, não só a da raiz — inclusive `phoenix_kernel/logs/`. Rode `git check-ignore -v phoenix_kernel/logs/engine.py` pra confirmar, e ancore o padrão com `/logs/` no `.gitignore` se for o caso.

**RAG mostrando 0 documentos**
O arquivo `data/knowledge_base.json` precisa existir. O índice vetorial (`data/chroma_db/`) é gerado localmente a partir dele e não vem no clone.

**Ícone de Desktop não aparece (Linux)**
O instalador roda como root via `sudo`, então precisa resolver o usuário real via `$SUDO_USER` — se você rodou como root "de verdade" (não via sudo, ex: já logado como root), o instalador usa `$HOME` atual e avisa no log. Confirme rodando `sudo pwsh ./install_phoenix.ps1` como usuário normal, não logado direto como root.

**Docker não consegue alcançar llama-server ou sd-server**
Windows Defender bloqueia a subnet Docker (172.x.x.x) por padrão. O instalador já libera as portas oficiais da Phoenix automaticamente (seção de configuração do Windows); se precisar liberar manualmente:
```powershell
New-NetFirewallRule -DisplayName "Phoenix AI Services" `
  -Direction Inbound -Protocol TCP -LocalPort 8081,7860 -Action Allow
```

---

## Roadmap

**Implementado**

- ✅ Kernel modular com boot sequence
- ✅ Discovery Engine (Windows + Linux) + **AHDE** (Adaptive Hardware Discovery Engine — boot-time
  ingest, polling de telemetria a cada 5s, shutdown gracioso)
- ✅ Telemetria ao vivo com sensores reais
- ✅ Runtime Engine (llama.cpp, Ollama opcional, Phoenix Diffusion, Kokoro-82M/ONNX, whisper.cpp)
- ✅ Todos os 6 pipelines multimodais confirmados em produção: leitura de documento (.docx/.pdf/.xlsx
  via PyMuPDF/Tika/ONLYOFFICE), descrição de imagem (MiniCPM-V), transcrição de áudio (Whisper,
  MP3/WAV), geração de imagem (SD 1.5 e SDXL) e voz (Kokoro-82M)
- ✅ Planner + RAG local (ChromaDB) — desde a v57, disponível também no chat normal (não só para o
  agente Resident), com chunking real multi-documento e trava de privacidade para provedores de
  nuvem (ver seção ["RAG Knowledge Repository"](#rag-knowledge-repository--planos-e-limites) acima)
- ✅ Gerente Residente
- ✅ **Arena** — colaboração entre dois modelos com verificação objetiva por execução real de código
  (não opinião de IA), guarda de repetição, gate de conclusão `CONFIRMADO`-obrigatório e progresso
  incremental na tela
- ✅ Busca web real via SearXNG no chat normal (antes só existia na Arena)
- ✅ App Store — Missões
- ✅ Dashboard Mission Control com accordion de sensores
- ✅ OCR nativo via Tesseract (comando `ocr`) + MiniCPM-V para imagens
- ✅ Instalador multiplataforma (Windows 10/11 + Ubuntu/Debian) com bootstrap de Git, fallback PS 5.1 e self-tests
- ✅ Scanner de armazenamento com prioridade NVMe > SSD > HDD e detecção automática de disco de sistema
- ✅ Atalhos automáticos de Desktop/Menu Iniciar (Windows) e `.desktop` (Linux)
- ✅ Vulkan backend RX 580 / Polaris
- ✅ Rebuild automático do frontend quando `dist/server.cjs` fica mais antigo que os fontes
  (`setup_platform.py` compara timestamps contra `server.ts`/`package.json`/`App.tsx`/`vite.config.ts`)
- ✅ `build_release_zip.py` — gerador oficial de ZIP de release via allowlist real do `.gitignore`
  (repositório git descartável), com varredura anti-credencial antes de zipar
- ✅ Criação/transformação de documentos (`/api/documents/create`) — PDF/DOCX/XLSX/PPTX/TXT/MD,
  com ou sem arquivo-fonte, com opção de injetar resultado de busca web no conteúdo gerado

**Em andamento**

- 🟡 Correções de plataforma Linux (`llama-server` path, auto-recuperação do `storage.json` e
  auto-reparo do `.venv`) — corrigidas e testadas em simulação nesta auditoria, **pendentes de
  validação em Ubuntu real**; comportamento no Windows preservado sem alteração.
  Ver [`docs/PHOENIX_STATUS.md`](./docs/PHOENIX_STATUS.md#linux--runtime--storage-recovery-auditoria-2026-08-27).
- 🟡 Calibração empírica do limiar de relevância do RAG (`min_score: 0.15`) com uso real — o RAG
  multi-documento em si já está entregue (v57, ver acima); só essa calibração fina depende de dados
  reais de uso que não dá pra gerar no ambiente de auditoria.
  Ver [`docs/PHOENIX_STATUS.md`](./docs/PHOENIX_STATUS.md#rag-multi-documento-no-chat-normal--entregue-v57-concluído-em-2026-08-28).

**Próximos**

- Validar em Ubuntu real as duas correções de plataforma Linux acima
- **Grounding de busca web (prioridade P0)** — hoje nada impede um modelo de citar URL fora do que a
  busca real (SearXNG) retornou; proposta de IDs de fonte (`[S1]`...) com allowlist e rejeição de
  citação fora da lista. Ver [`docs/PHOENIX_STATUS.md`](./docs/PHOENIX_STATUS.md#próxima-prioridade-real-grounding-da-busca-web-p0).
- Roteador de intenção de geração de imagem mais robusto (hoje depende da palavra literal "imagem"
  no prompt)
- Rota HTTP `/api/ocr` real no `api_server.py` (upload de imagem direto do chat)
- Execution Guard — aprovação visual antes de instalar
- Auto-tuning de modelos por benchmark real
- Hardware Service centralizado com cache de snapshot
- Crítica forçada na Arena contra design estruturalmente errado (qualidade de raciocínio — distinto
  do gate de veracidade `CONFIRMADO`, que já está resolvido)
- Mistura de vozes / correção fonética por palavra isolada em outro idioma (Kokoro)
- Phoenix Knowledge Cloud — telemetria agregada
- Release pública estável

---

## Créditos

Projeto do **AIVisionsLab Studio Group**. Construído sobre o trabalho de [ggerganov](https://github.com/ggerganov) (llama.cpp, whisper.cpp), [leejet](https://github.com/leejet) (stable-diffusion.cpp), e as comunidades de Ollama, OpenWebUI e ComfyUI.

A prova de conceito original — LLM + imagem via Vulkan no RX 580, sem CUDA — foi documentada por [艾米心 Amihart](https://medium.com/@amihart) (primeiro LLM via Vulkan no RX 580, Jan 2025) e [DadHacks](https://dadhacks.org) (stable-diffusion.cpp via Vulkan, Dez 2025).

---

## Licença

**Creative Commons Atribuição-NãoComercial 4.0 Internacional (CC BY-NC 4.0)**

Copyright © 2026 AIVisionsLab Studio Group — Creative & Tech Solutions

Uso livre para fins pessoais e educacionais com atribuição. Uso comercial requer autorização expressa por escrito.

A Phoenix preserva as licenças originais dos componentes externos e vendorizados. Consulte `LICENSE.md` e os arquivos de licença dentro de `src/phoenix-diffusion.cpp/`.

Texto completo: [`LICENSE.md`](./LICENSE.md) · [creativecommons.org/licenses/by-nc/4.0](https://creativecommons.org/licenses/by-nc/4.0/deed.pt-BR)

---

*Construído em São Paulo, Brasil 🇧🇷*

**AIVisionsLab Studio Group · Creative & Tech Solutions**
*O futuro não espera. A gente constrói.*
