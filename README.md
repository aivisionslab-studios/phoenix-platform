# 🔥 Phoenix Platform 4.5

**AIVisionsLab Studio Group · Creative & Tech Solutions**

**Local AI Orchestration · Hardware Intelligence · Runtime Qualification · Local LLMs · Image Generation · RAG · Automation**

> **Hardware não morre — só espera o software certo.**

Phoenix é uma plataforma de IA local criada para descobrir o hardware disponível,
qualificar o que ele realmente consegue executar e coordenar workloads de IA
entre CPU, GPU e execução híbrida.

A filosofia central da Phoenix é:

> **não basta detectar hardware — é preciso provar que ele funciona para a carga real.**

A plataforma reúne:

- execução local de LLMs;
- geração de imagens;
- RAG;
- documentos e OCR;
- voz e áudio;
- hardware discovery;
- benchmark;
- stress e correctness validation;
- failure interception;
- automatic fallback;
- model qualification;
- observabilidade;
- release integrity.

A Phoenix procura responder:

```text
Qual hardware existe?
        ↓
Qual runtime consegue utilizá-lo?
        ↓
O modelo cabe?
        ↓
CPU, GPU ou HYBRID?
        ↓
A execução ocorreu realmente nesse modo?
        ↓
O resultado é válido?
        ↓
A arquitetura continua adequada?
        ↓
Continuar, mudar de rota ou bloquear?
```

---

## Visão geral

Phoenix não trata CPU, GPU, memória, storage e runtimes como componentes isolados.

A plataforma procura entender o sistema como um conjunto de capabilities que precisam
ser descobertas, qualificadas e observadas continuamente.

```text
hardware
   ↓
discovery
   ↓
qualification
   ↓
capability evidence
   ↓
execution strategy
   ↓
runtime observation
   ↓
result validation
   ↓
promotion / fallback / block
```

O objetivo é reduzir configuração manual e impedir que a interface declare uma
capability como funcional apenas porque algum arquivo, endpoint ou módulo existe.

---

# Arquitetura

```text
┌─────────────────────────────────────────────┐
│               Phoenix Aviary                │
│          Interface / UX / Workflows         │
└──────────────────────┬──────────────────────┘
                       │
                       ▼
┌─────────────────────────────────────────────┐
│               Phoenix Engine                │
│      Orchestration · RAG · Dispatch         │
│      Runtime Control · Fallback             │
└──────────────────────┬──────────────────────┘
                       │
                       ▼
┌─────────────────────────────────────────────┐
│               Phoenix Forge                 │
│ Hardware Intelligence · Qualification       │
│ Evidence · Benchmark · Reliability          │
└──────────────────────┬──────────────────────┘
                       │
              ┌────────┴────────┐
              ▼                 ▼
┌─────────────────────┐  ┌─────────────────────┐
│ Phoenix Llama       │  │ Phoenix Diffusion   │
│ Runtime             │  │                     │
│ Local LLMs          │  │ Image Generation    │
└─────────────────────┘  └─────────────────────┘
```

## Phoenix Aviary

Interface principal da plataforma.

Inclui:

- chat com LLMs locais;
- Arena;
- geração de imagens;
- documentos;
- RAG;
- voz e áudio;
- gerenciamento de modelos;
- hardware;
- benchmarks;
- diagnósticos;
- observabilidade.

Endereço padrão:

```text
http://localhost:3000
```

## Phoenix Engine

Camada central de orquestração.

Responsável por:

- API principal;
- workflows;
- dispatch;
- controle de runtimes;
- RAG;
- processamento de documentos;
- seleção de arquitetura;
- fallback;
- estado operacional;
- integração com a Aviary;
- decisão de execução efetiva.

O Engine decide **como uma carga deve ser executada**.

O Forge qualifica e fornece evidência; o Engine usa essa evidência para tomar decisões
de execução.

## Phoenix Forge

Phoenix Forge é a camada de:

```text
hardware intelligence
qualification
evidence
benchmark
reliability
runtime observation
failure classification
```

Ele não existe apenas para listar CPU e GPU.

O Forge procura determinar o que a máquina **realmente consegue fazer**.

Entre as áreas trabalhadas estão:

- hardware discovery;
- identidade persistente de dispositivos;
- CPU topology;
- GPU identity;
- Vulkan discovery;
- VRAM qualification;
- VRAM bandwidth;
- GPU Safety;
- GPU Ledger;
- runtime observations;
- workload profiling;
- model fit;
- calibration;
- PCIe intelligence;
- storage/NVMe inspection;
- sensor fusion;
- benchmark;
- stress;
- correctness validation;
- Capability Registry;
- Capability Matrix;
- Evidence Graph;
- provenance;
- failure interception;
- fallback evidence;
- release integrity.

Regra central:

```text
arquivo existe
      ≠
capability funciona
```

Uma capability só deve ser promovida quando houver evidência suficiente e
reproduzível.

## Phoenix Forge 0.25.0rc6.post15

A linha atual consolidou novos mecanismos de verification e runtime safety.

Entre eles:

```text
Windows Evidence Promotion
Runtime Failure Interception
Architecture Fallback
Dynamic Verification Counts
Release Metadata Truth
Release Integrity
Project Hygiene
WDK Diagnostics
Privileged Provider Contracts
APERF/MPERF Source
```

A Phoenix separa níveis diferentes de prova:

```text
VERIFIED_SYNTHETIC
WINDOWS_VERIFIED
HARDWARE_VERIFIED
UNVERIFIED
```

Um self-test não deve ser apresentado como hardware qualification real.

A existência de código, mocks, contratos ou testes sintéticos também não deve ser
promovida para `HARDWARE_VERIFIED` sem evidência correspondente.

## Phoenix Llama Runtime

Runtime local da Phoenix para execução de LLMs.

Pode operar em:

```text
CPU
GPU
HYBRID
AUTO
```

e utilizar aceleração Vulkan quando disponível.

O runtime é separado do modelo:

```text
Phoenix Llama Runtime
        =
motor de execução
```

Modelos GGUF compatíveis podem ser carregados conforme memória, backend,
qualification e disponibilidade de storage.

## Phoenix LaVa

**Phoenix LaVa** é o projeto de LLM próprio da Phoenix.

Enquanto o modelo próprio não estiver treinado ou customizado pela plataforma,
modelos externos utilizados pela Phoenix continuam identificados como
**foundation models**, sem serem apresentados como modelos proprietários da Phoenix.

Isso inclui modelos maiores usados atualmente para qualification e validação da
arquitetura.

## Phoenix Diffusion

Camada de geração local de imagens.

A linha principal atual prioriza:

- **Stable Diffusion 1.5**
- **SDXL 1.0**

A execução pode utilizar CPU, GPU ou estratégia híbrida, conforme backend,
memória e qualification.

---

# Hardware Intelligence

A Phoenix foi criada com atenção especial a hardware que costuma receber menos
suporte de stacks modernas.

Uma das plataformas de desenvolvimento utiliza:

```text
CPU     Intel Xeon E5-2690 v3
RAM     32 GB DDR4 REG ECC
GPU     AMD Radeon RX 580 8 GB
Backend Vulkan
```

A arquitetura, porém, **não é exclusiva da RX 580 ou de GPUs AMD**.

O objetivo do Forge é trabalhar com capabilities e providers que permitam suporte
progressivo a:

- AMD;
- NVIDIA;
- Intel;
- outros dispositivos compatíveis com os runtimes disponíveis.

## Vulkan

Vulkan é um dos caminhos principais utilizados pela Phoenix para aceleração local.

A plataforma não foi desenhada em torno de uma única stack proprietária.

A disponibilidade real depende de:

```text
GPU
driver
backend
runtime
modelo
VRAM
RAM
workload
qualification
```

---

# Qualification / Evidence

Phoenix diferencia discovery de qualification.

```text
DETECTED
   ↓
SUPPORTED
   ↓
TESTED
   ↓
VERIFIED
   ↓
PROMOTED
```

Uma capability pode ser detectada e ainda assim não estar qualificada para execução
real.

A evidência pode vir de diferentes fontes:

```text
synthetic tests
runtime observations
native provider
driver evidence
hardware counters
stress
correctness validation
real workload execution
```

O Forge registra evidência; o Engine consome essa informação.

---

# CPU / GPU / HYBRID / AUTO

Phoenix trabalha com quatro modalidades principais:

| Modo | Comportamento |
|---|---|
| **CPU** | Execução estrita em CPU |
| **GPU** | Execução em GPU quando suportada e qualificada |
| **HYBRID** | Distribuição controlada entre CPU e GPU |
| **AUTO** | Seleção automática baseada em hardware, memória, runtime e evidência |

No modo `AUTO`, a Phoenix pode considerar:

```text
CPU
GPU
VRAM
RAM
modelo
contexto
runtime
storage
telemetria
qualification
evidência histórica
health state
```

Uma regra essencial é separar:

```text
requested_mode
        ≠
effective_mode
```

A Phoenix deve informar o **modo efetivo** de execução, e não apenas o modo
solicitado.

Exemplo:

```text
requested_mode = AUTO
effective_mode = HYBRID
```

ou:

```text
requested_mode = GPU
effective_mode = CPU_ONLY
reason = FALLBACK
```

---

# Large Models

Phoenix também está sendo desenvolvida para executar modelos maiores que a
VRAM disponível em uma única GPU.

O primeiro foundation model grande qualificado em hardware real foi:

```text
Mistral Small 3.2 24B Instruct 2506
Q4_K_M
```

Arquivo testado:

```text
Mistral-Small-3.2-24B-Instruct-2506-ultra-uncensored-heretic.Q4_K_M.gguf
```

Como o modelo ainda não é treinado ou customizado pela Phoenix, seu estado é:

```text
FOUNDATION_MODEL_NOT_PHOENIX_TRAINED
```

## HYBRID real

Configuração utilizada:

```text
--device Vulkan0
-ngl auto
--fit on
--fit-target 0
--fit-ctx 8192
-c 8192
--parallel 1
-t 12
--jinja
--flash-attn off
```

Resultado observado:

```text
generation      ~2.68 tok/s
VRAM            ~7.3–7.4 GB / 8 GB
RAM             ~25.8 GB / 31.8 GB
```

Esse teste demonstrou execução real com divisão de carga entre GPU e memória do
sistema, dentro das limitações do hardware utilizado.

## CPU-only real

Configuração:

```text
-ngl 0
--device none
--fit off
--no-op-offload
-c 8192
--parallel 1
-t 12
--jinja
--flash-attn off
```

Resultado observado:

```text
generation      ~2.02 tok/s
prompt eval     ~11.58 tok/s
GPU             0%
VRAM residual   ~0.5–0.6 GB
RAM             ~30.2–30.3 GB / 31.8 GB
```

A execução CPU-only completou o fluxo end-to-end.

Estado observado:

```text
CPU_ONLY            READY
FALLBACK_AVAILABLE  true
RAM_PRESSURE        CRITICAL_HIGH
```

O fato de o fluxo completar não elimina a necessidade de classificar pressão de
memória e limites de capacidade.

---

# Dynamic Model Storage

Phoenix não depende de letras fixas de unidade.

O contrato de armazenamento é baseado em role:

```text
storage_role:
PHOENIX_MODELS

canonical_relative_path:
Phoenix\Workstations\Models

volume_binding:
DYNAMIC
```

Para GGUF:

```text
Phoenix\Workstations\Models\Chat\GGUF
```

Portanto caminhos como:

```text
D:\Phoenix\Workstations\Models\Chat\GGUF
E:\Phoenix\Workstations\Models\Chat\GGUF
J:\Phoenix\Workstations\Models\Chat\GGUF
```

são apenas resoluções físicas diferentes do mesmo storage role.

Isso permite que o Engine e os runtimes trabalhem com uma identidade lógica estável
sem hardcode da letra da unidade.

---

# Artifact Qualification

Um arquivo existir no disco não significa que o modelo esteja válido.

O fluxo de aquisição deve ser:

```text
MODEL_REQUIRED
↓
resolve PHOENIX_MODELS
↓
download/import
↓
.part
↓
size validation
↓
SHA-256
↓
GGUF structural qualification
↓
atomic rename
↓
QUALIFIED
↓
Model Registry
```

A qualificação não deve validar apenas o magic `GGUF`.

Ela também precisa detectar:

```text
ARTIFACT_CORRUPTED
DOWNLOAD_INCOMPLETE
GGUF_TENSOR_OUT_OF_FILE_BOUNDS
```

Durante os testes foi encontrado um arquivo Q5_K_M incompleto que resultou em:

```text
tensor data is not within the file bounds
```

Esse evento é um problema de artefato/download, e não uma falha de GPU.

A Phoenix deve impedir que artefatos incompletos sejam promovidos para o Model
Registry como modelos utilizáveis.

---

# Runtime Failure Interception

Phoenix diferencia falhas de capacidade, runtime, transporte, artefato e
confiabilidade de hardware.

Classes relevantes incluem:

```text
GPU_MEMORY_ALLOCATION_FAILED
CAPACITY_LIMIT
RUNTIME_FAILURE
CLIENT_STREAM_DISCONNECTED
GPU_RELIABILITY_FAILURE
ARTIFACT_CORRUPTED
DOWNLOAD_INCOMPLETE
GGUF_TENSOR_OUT_OF_FILE_BOUNDS
RAM_PRESSURE
```

Regra fundamental:

```text
OUT_OF_MEMORY
≠
HARDWARE_CORRUPTION
```

OOM normalmente representa limite de capacidade.

Exemplo:

```text
AUTO
↓
HYBRID
↓
GPU_MEMORY_ALLOCATION_FAILED
↓
CAPACITY_LIMIT
↓
CPU_ONLY
```

Uma falha de confiabilidade comprovada segue caminho diferente:

```text
GPU_RELIABILITY_FAILURE
↓
DEGRADED / BLOCKED / QUARANTINED
↓
CPU_ONLY
↓
REQUALIFICATION_REQUIRED
```

## Client stream disconnect

Durante um teste real do Mistral 24B em HYBRID, a interface mostrou:

```text
Reconnecting to the stream...
```

enquanto o runtime continuava gerando tokens.

Esse evento deve ser classificado como:

```text
CLIENT_STREAM_DISCONNECTED
```

e não automaticamente como:

```text
GPU_FAILURE
```

Perder o cliente ou o stream não constitui evidência suficiente para condenar
a GPU.

---

# Automatic Fallback

Fallback é tratado como parte da arquitetura, não como um remendo invisível.

Exemplo de capacidade:

```text
GPU/HYBRID
   ↓
runtime failure
   ↓
classification
   ↓
architecture fallback
   ↓
CPU_ONLY
   ↓
validation
   ↓
result
```

A Phoenix deve registrar:

```text
requested mode
effective mode
failure class
fallback reason
target architecture
validation result
```

O usuário não deve receber uma resposta dizendo “GPU” quando a execução real
ocorreu em CPU.

---

# Benchmarks reais

Benchmarks da Phoenix são usados como evidência operacional.

Eles podem incluir:

- VRAM map;
- VRAM bandwidth;
- CPU throughput;
- GPU throughput;
- runtime latency;
- prompt evaluation;
- token generation;
- storage throughput;
- stress;
- correctness validation;
- workload-specific qualification.

Resultados sintéticos e reais devem permanecer separados.

```text
synthetic benchmark
        ≠
hardware qualification
```

A promoção de capability deve depender do tipo de evidência exigido para aquela
capability.

---

# RAG

Phoenix possui um Knowledge Repository local para consulta contextual.

Formatos trabalhados incluem:

- PDF;
- DOCX;
- XLSX;
- PPTX;
- TXT;
- Markdown;
- imagens compatíveis com OCR.

O pipeline considera:

```text
authorization
integrity
consistency
transaction
rollback
reconciliation
```

Quando o estado do repositório não pode ser validado, a política preferida é:

```text
FAIL-CLOSED
```

em vez de utilizar conhecimento inconsistente.

---

# Documents

A plataforma inclui recursos para:

- leitura de documentos;
- extração de texto;
- OCR;
- transformação;
- preenchimento de planilhas;
- normalização;
- revisão de campos;
- workflows longos;
- acompanhamento de estado.

Uma operação cancelada, truncada ou com erro não deve ser apresentada como
sucesso.

---

# Audio

Phoenix possui integrações para:

- STT;
- TTS;
- workflows de áudio;
- document-to-audio.

A aceleração disponível depende do runtime e do hardware.

---

# Release / Update / Recovery

Phoenix trabalha com atualização transacional.

Fluxo esperado:

```text
release
  ↓
validation
  ↓
preflight
  ↓
state preservation
  ↓
apply
  ↓
migration
  ↓
smoke
  ↓
integrity
  ↓
commit
```

Ferramentas disponíveis no Windows incluem:

```text
Atualizar_Phoenix.bat
Rollback_Phoenix.bat
Recuperar_Phoenix.bat
Certificar_Phoenix.bat
Verificar_Integridade_Phoenix.bat
Reparar_Phoenix_Diffusion.bat
Migrar_RAG.bat
```

Uma atualização incompleta não deve ser aceita silenciosamente.

## Release Integrity

O processo de release pode incluir:

- hashes do payload;
- provenance;
- verificação de arquivos;
- startup integrity;
- rollback protection;
- channel policy;
- sequência monotônica;
- assinatura Ed25519 quando configurada;
- trust store;
- rotação e revogação de chaves.

Chaves privadas não fazem parte da distribuição pública.

---

# Windows Evidence Promotion

Phoenix Forge possui uma linha específica para promover evidência obtida no Windows
sem confundir diferentes níveis de confiança.

Exemplos:

```text
UNVERIFIED
VERIFIED_SYNTHETIC
WINDOWS_VERIFIED
HARDWARE_VERIFIED
```

A promoção deve depender da origem da prova.

Exemplo:

```text
selftest em software
    ↓
VERIFIED_SYNTHETIC
```

não equivale automaticamente a:

```text
hardware counter real
    ↓
HARDWARE_VERIFIED
```

Windows Evidence Promotion existe para tornar explícita essa diferença.

---

# WDK / Privileged Providers

Algumas evidências de baixo nível podem depender de acesso privilegiado,
drivers, WDK ou providers específicos do sistema operacional.

Phoenix trata isso como capability separada.

Estados possíveis incluem:

```text
AVAILABLE
UNAVAILABLE
NOT_INSTALLED
NOT_PRIVILEGED
UNVERIFIED
VERIFIED
```

Ausência de provider privilegiado não deve gerar evidência falsa.

Quando a fonte de baixo nível não está disponível, a Phoenix deve informar o
estado real e utilizar providers alternativos quando apropriado.

A linha do Forge também trabalha com contratos para fontes como:

```text
WDK diagnostics
privileged providers
APERF/MPERF
```

sem promover automaticamente uma fonte ausente ou simulada para hardware real.

---

# Fail-Closed

A Phoenix adota fail-closed em operações onde continuar com estado inconsistente
seria pior do que interromper.

Para releases:

```text
erro obrigatório
→ exit != 0

selftest ausente
→ FAIL

manifest mismatch
→ FAIL

traceback
→ FAIL

gate obrigatório não passou
→ FAIL
```

O mesmo princípio se aplica a outras áreas críticas:

```text
integrity unknown
→ do not promote

artifact incomplete
→ do not register

hardware evidence insufficient
→ do not claim verified

RAG inconsistent
→ do not expose as valid knowledge
```

---

# Privacy / Telemetry

Phoenix é **local-first**.

A execução principal pode acontecer localmente, mas alguns recursos podem utilizar
rede quando o usuário habilita ou solicita:

- downloads;
- atualização;
- pesquisa web;
- provedores externos;
- suporte;
- sincronização;
- telemetria técnica.

Telemetria não deve derrubar:

```text
chat
runtime
diffusion
RAG
```

Credenciais, chaves privadas, bancos RAG, documentos privados, estado de runtime
e informações específicas da máquina não devem fazer parte do repositório público.

---

# Serviços padrão

| Componente | Endereço |
|---|---|
| Phoenix Aviary | `http://localhost:3000` |
| Phoenix Engine | `http://localhost:8000` |
| Phoenix Forge | `http://127.0.0.1:8787` |
| Phoenix Llama Runtime | `http://localhost:8081` |
| Runtime secundário / qualification | `http://localhost:8082` |

Serviços adicionais podem ser ativados conforme a instalação.

---

# Installation

## Windows 10 / 11

Clone o repositório:

```powershell
git clone https://github.com/aivisionslab-studios/phoenix-platform.git
cd phoenix-platform
```

Execute:

```powershell
.\INSTALAR_PHOENIX.ps1
```

ou utilize:

```text
INSTALAR_PHOENIX.bat
```

Depois:

```text
Iniciar_Phoenix.bat
```

## Linux

```bash
git clone https://github.com/aivisionslab-studios/phoenix-platform.git
cd phoenix-platform
sudo pwsh ./install_phoenix.ps1
```

Inicie com:

```bash
./Iniciar_Phoenix.sh
```

> A compatibilidade prática depende do sistema operacional, driver, backend,
> packages e capabilities disponíveis.

---

# Project Structure

```text
phoenix-platform/
├── Engine/
├── PUBLIC_GUARD/
├── TESTS/
├── TEST_FIXTURES/
├── assets/
├── catalog/
├── config/
├── core/
├── data/
├── docs/
├── hardware_engine/
├── install/
├── institutional/
├── phoenix-forge/
├── platform_source/
├── searxng-docker/
├── src/
├── tools/
├── INSTALAR_PHOENIX.ps1
├── Iniciar_Phoenix.bat
├── Iniciar_Phoenix.sh
├── README.md
├── MANUAL_PHOENIX_4.5.md
└── LICENSE.md
```

Arquivos locais, credenciais, modelos, caches, logs, bancos privados e artefatos
temporários são controlados pelo `.gitignore` e pela política de release.

Detalhes de auditoria, contagens de selftests, resultados intermediários e logs de
cada post-release pertencem a:

```text
docs/
reports/
release evidence
```

e não devem sobrecarregar o README principal.

---

# Engineering Philosophy

Phoenix segue quatro princípios:

```text
PRIMEIRO PROVAR
DEPOIS PROMOVER
DEPOIS REORGANIZAR
SÓ DEPOIS AMPLIAR
```

Para hardware:

```text
não assumir
não inventar
não esconder fallback
não confundir OOM com defeito físico
não confundir stream failure com GPU failure
não confundir arquivo GGUF existente com modelo válido
não declarar capability completa apenas porque existe código
```

Para execução:

```text
requested_mode
≠
effective_mode
```

Para releases:

```text
erro obrigatório
→ exit != 0

selftest ausente
→ FAIL

manifest mismatch
→ FAIL

traceback
→ FAIL

gate obrigatório não passou
→ FAIL
```

A Phoenix deve sempre informar o **modo efetivo** de execução, não apenas o modo
solicitado.

---

# Objetivo

O objetivo da Phoenix não é funcionar apenas em uma combinação específica de
hardware.

É construir uma plataforma capaz de receber uma máquina desconhecida, descobrir
o que ela realmente consegue fazer e escolher uma estratégia de execução baseada
em evidência.

```text
hardware diferente
       ↓
mesma Phoenix
       ↓
qualification
       ↓
execution strategy
       ↓
runtime observation
       ↓
validated local AI
```

---

# Documentação

## Manual oficial — Phoenix 4.5

O manual de uso da Phoenix 4.5 está disponível diretamente na raiz do repositório:

**[📘 Abrir MANUAL_PHOENIX_4.5.md](./MANUAL_PHOENIX_4.5.md)**

Caminho no projeto:

```text
phoenix-platform/
├── README.md
└── MANUAL_PHOENIX_4.5.md
```

No checkout local:

```text
<raiz-do-projeto>\MANUAL_PHOENIX_4.5.md
```

O manual cobre instalação, inicialização, interfaces e serviços, chat e modelos,
modos CPU/GPU/HYBRID/AUTO, RAG, documentos, imagens, voz, busca web, Arena,
Mission Control, updates, rollback, recovery, integridade, privacidade,
telemetria e solução de problemas.

Outras documentações técnicas estão organizadas em:

```text
docs/
institutional/
phoenix-forge/
```

Detalhes de auditoria, qualification, release engineering, Windows evidence,
benchmarks e desenvolvimento interno devem permanecer na documentação técnica,
sem sobrecarregar o README principal.

---

# Licença

O código original da Phoenix está sujeito aos termos descritos em:

```text
LICENSE.md
```

Componentes de terceiros permanecem sujeitos às suas respectivas licenças.

---

**Phoenix Platform 4.5**  
**AIVisionsLab Studio Group · Creative & Tech Solutions**

**Copyright © 2026 AIVisionsLab Studio Group**
