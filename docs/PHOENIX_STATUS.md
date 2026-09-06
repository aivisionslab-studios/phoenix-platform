# Phoenix 3.0 — Status da Auditoria Contínua

**Última atualização:** 2026-08-28, incorporando a "auditoria completa" (correção crítica de
NameError em leitura de documentos, correções de RAG, achado de privacidade RAG+nuvem e organização
de todo o histórico em commits locais) — ver seção dedicada logo abaixo.

Este documento é o **changelog canônico** da auditoria em andamento do Phoenix 3.0. Cada rodada é
verificada por execução real (`py_compile`, `tsc --noEmit`, `npm run build`, suíte `pytest`/`.mjs`,
testes de integração ponta a ponta, controle negativo ao vivo — reverter a correção e confirmar que o
teste realmente falha antes de restaurar), nunca por revisão visual isolada ou acordo entre modelos.
Isso substitui/consolida os `LEIA-ME.txt` individuais de cada pacote `PHOENIX_3.0_vNN.zip`.

> Os documentos `ARCHITECTURE_TARGET_V5.md`, `VISION.md`, `DOMAIN_MODEL.md` e `TERMINOLOGY.md` nesta pasta
> descrevem a visão-alvo **"Phoenix Engine 5.0"** (pipeline Knowledge → Policy → Reasoning → Planning →
> Provisioning → Execution, com `Mission`/`Blueprint`/`Capability`) — **congelada para implementação
> futura, ainda não construída**. Tudo abaixo descreve o código que roda hoje (linha Phoenix 3.0).

---

## Auditoria completa — 2026-08-28

Rodada de "corrigir tudo" sobre o relatório `AUDITORIA_COMPLETA_2026-08-28.md`, executada com
autorização direta do usuário. Cada item abaixo foi verificado por teste real antes de ser
considerado concluído; suíte completa ao final: **199/199** (`pytest TESTS/`) + **50/50** (dois
scripts standalone da raiz) + **128/128** checagens nos 9 arquivos `.mjs` do frontend, `tsc`/`vite
build`/`esbuild` limpos. Organizado em 7 commits locais (nenhum `git push`).

- **Correção crítica**: `resident_manager.py::read_document_direct()` (usada por
  `POST /api/documents/read` — resumir/analisar PDF/DOCX/XLSX/TXT) tinha um `NameError` numa variável
  (`model_hint`) nunca declarada como parâmetro — um refactor já aplicado corretamente em
  `describe_image_direct()`/`generate_image_direct()`/`ocr_image_direct()` nunca chegou a esta função
  irmã. **Toda** leitura de documento quebrava antes de processar o arquivo. Corrigido adicionando o
  mesmo parâmetro `model_hint: str = ""` das outras três funções.
- **RAG — normalização de ID / reindexação**: frontend (`RagDrawer.tsx`) decidia "é reindexação?"
  comparando títulos com `.toLowerCase()`; backend (`chroma_rag_backend.py::manual_document_id()`) só
  fazia `.strip()`. Um título com capitalização diferente do original podia ser aprovado como
  reindexação livre na tela e rejeitado como documento novo (gastando cota) no servidor. Unificado:
  o backend agora normaliza com `.lower()` também.
- **RAG — ordem de exclusão**: `delete_document()` apagava primeiro os chunks físicos no ChromaDB e só
  depois desautorizava no registry/ledger/consenso. Invertido — desautoriza primeiro. Mais seguro: uma
  falha no meio do processo já deixa o documento ilegível, mesmo que a limpeza física fique pendente
  (`_authorized_user_ids()` deriva de `_user_consensus.validate()`, não do que existe fisicamente no
  Chroma).
- **RAG — privacidade com provedores de nuvem** (achado do usuário durante a revisão desta rodada):
  o chat injetava o contexto do RAG no prompt em toda mensagem, pra qualquer provedor — inclusive o
  Gemini (nuvem), sem aviso nem opção de desligar. Corrigido com uma trava nova
  (`blockRagOnCloudProviders`, ligada por padrão): quando o provedor ativo é de nuvem, a consulta ao
  RAG nem é feita — a proteção é não fazer a chamada de rede, não só descartar o resultado depois.
  Indicador visual permanente ("RAG bloqueado (nuvem)") ao lado do seletor de modelo; toggle em
  Parâmetros pra quem quiser desligar essa proteção conscientemente. Provedores locais (Ollama,
  llama-server, LM Studio) nunca são afetados.
- **RAG — validação do `min_score: 0.15`**: não foi possível validar numericamente com embeddings
  reais nesta rodada (ambiente de auditoria bloqueia o download do modelo `all-MiniLM-L6-v2`, tanto
  pela fonte padrão do ChromaDB quanto pelo Hugging Face Hub). Em vez disso: (a) logs de
  observabilidade (`console.debug`) no chat, distinguindo hit encontrado / 0 hits / falha de rede /
  erro de status, pra calibrar com dados reais de uso; (b) testes que validam o *mecanismo* do filtro
  (`score >= min_score`, caso de borda, proteção contra valor negativo) sem depender de nenhum modelo
  de embeddings. **Ainda em aberto**: confirmar empiricamente, com uso real, se 0.15 é o corte certo.
- **Achado fora do escopo original, encontrado ao organizar os commits**: `catalog/assets/flux.json`,
  `flux1-schnell-Q4_K_M.json` e `sdxl.json` tinham uma modificação local não commitada que revertia um
  bug já corrigido (`target_dir` hardcoded de volta pra `J:\Phoenix\Workstations\Models\Image`).
  Descartada via `git checkout --`, restaurando o caminho relativo correto.
- **Limpeza**: removidos módulos órfãos/duplicados (`piper.py`, `discovery_engine.py`,
  `install_target.py`, `hardware_provider.py`), a cópia antiga e sem patches de segurança de
  `raiz/setup_environment.py`, `PATCH_FILES/` (10 arquivos já idênticos ao código aplicado), backups
  soltos e dois arquivos de teste contaminados de outro pacote (nomes de variável/função que não
  existem neste código-base). 14 artefatos de sessões de patch anteriores arquivados em
  `docs/archive/patches_2026-08/`. `requirements.txt` passou a declarar `cryptography` e
  `huggingface_hub` (usadas de verdade, nunca declaradas). Documentação de gap: setup do
  `GEMINI_API_KEY` não estava documentado em nenhum lugar do projeto — corrigido nesta rodada (ver
  README e `institutional/docs/INSTALLATION.md`).
- **Decisão de produto confirmada com o usuário**: a propagação de cancelamento/downgrade de licença
  Pro continua **offline-first** de propósito (token assinado vale até a própria expiração mesmo sem
  internet) — não é bug pendente, é trade-off assumido. Ver `README.md`, seção "RAG Knowledge
  Repository — planos e limites".

---

## Estado atual (pacote entregue mais recente: v56)

- Suíte oficial acumulada: **176/183 passando**, as mesmas **7 falhas pré-existentes** (documentadas
  desde antes da v47, sem relação com nenhuma correção desta auditoria) — nenhuma regressão nova
  introduzida em nenhuma das ~30 rodadas.
- Todos os 6 pipelines multimodais confirmados em produção (documento, imagem, áudio-texto,
  texto-imagem, texto-voz, colaboração entre modelos).
- Motor de voz único: **Kokoro-82M (ONNX)**, CPU por padrão (GPU/DirectML testada e descartada na RX
  580 — falha reprodutível de driver, não de código).
- Busca web real (SearXNG) disponível tanto na Arena quanto no chat normal.
- Contexto do `llama-server`: 16384 tokens.
- **RAG multi-documento no chat normal:** entregue (v57) e com trava de privacidade pra provedores de
  nuvem desde 2026-08-28 — ver seção dedicada abaixo. Único item ainda em aberto: calibrar o
  `min_score: 0.15` com dados reais de uso (não dá pra validar com embeddings reais no ambiente de
  auditoria).

**Status global (visão rápida):**

```text
Python 3.12 privado Linux ............ ✅
Kokoro 0.6.1 ......................... ✅
PX002/PX007 .......................... ✅
Document create/transform ............ ✅
PDF sem limite artificial de tokens .. ✅
Port recreate policy .................. ✅
llama-server Linux path ............... 🟡 corrigido/testado localmente
storage.json recovery Linux ........... 🟡 corrigido/testado localmente
.venv auto-repair Linux ............... 🟡 corrigido/testado localmente
Windows (regressão) ................... ✅ comportamento preservado
Web grounding / fontes ................ ⚠️ P0 atual
```

`🟡` = correção aplicada e verificada por teste automatizado/simulado nesta máquina de auditoria,
mas **ainda não validada rodando de ponta a ponta em Ubuntu real** — ver seção dedicada abaixo.

---

## Linux — Runtime / Storage Recovery (auditoria 2026-08-27)

Contexto: um log real de reinstalação no Linux (fim de semana de 2026-08-26) expôs dois problemas de
plataforma que não tinham equivalente de correção no Linux, apesar de já resolvidos no Windows em
rodadas anteriores. Uma revisão externa (ChatGPT) propôs a correção; o código foi auditado aqui
(leitura do código-fonte real, não apenas a afirmação) e depois testado com simulações locais.

### `llama-server` path (Linux)

**Status: 🟡 CORRIGIDO / TESTADO LOCALMENTE / PENDENTE HARDWARE REAL**

Correção aplicada em: `phoenix_kernel/runtime/drivers/llama_cpp.py`

Antes, `_find_executable()` só verificava dois caminhos, ambos exclusivos do Windows
(`bin/Release/llama-server.exe` e `bin/llama-server.exe`), caindo direto para `shutil.which()` em
qualquer outro caso — que só encontra o binário se ele estiver no `PATH` do sistema, o que o
instalador nunca garante. Resultado real observado no log: "BINARIO llama-server NAO ENCONTRADO"
mesmo após compilação bem-sucedida.

O driver agora procura explicitamente, nesta ordem:
- `repos/llama.cpp/build/bin/Release/llama-server.exe` (Windows MSBuild)
- `repos/llama.cpp/build/bin/llama-server.exe` (Windows Ninja)
- `repos/llama.cpp/build/bin/llama-server` (Linux — confirmado contra `install/common.ps1` linha 657)
- `repos/llama.cpp/build/bin/Release/llama-server` (candidato defensivo; não corresponde a nenhum
  layout de build real produzido pelo `common.ps1` hoje — código morto inofensivo, não é bug, mas
  candidato a limpeza numa rodada futura)
- `PATH` do sistema, como último fallback

No Linux, também valida permissão de execução com `os.access(candidate, os.X_OK)` antes de aceitar o
binário — cobre o cenário real de um binário presente no disco mas sem `+x` (comum após `git clone`
ou cópia entre sistemas de arquivo com permissões diferentes).

**Testes realizados (simulados, nesta máquina de auditoria):**
- binário Linux inexistente → rejeitado corretamente, cai no fallback de `PATH`
- binário existente sem `+x` → rejeitado corretamente (`os.access` retorna falso)
- binário existente e executável → detectado corretamente no caminho certo

**Validação ainda pendente:**
- executar no Ubuntu real após um build de verdade do `llama.cpp`
- confirmar descoberta automática do binário compilado, sem symlink manual nem `PATH` global

---

### `storage.json` — auto-recuperação no Linux

**Status: 🟡 CORRIGIDO / TESTADO LOCALMENTE / PENDENTE HARDWARE REAL**

Correção aplicada em: `Iniciar_Phoenix.sh`

Esse mecanismo já existia no `Iniciar_Phoenix.bat` (Windows) desde a auditoria de 2026-08-04, mas
nunca tinha sido portado pro launcher Linux — o `.sh` só validava a existência do `.venv`. Foi
exatamente essa lacuna que apareceu no log real de reinstalação (2026-08-26): o aviso de
`storage.json` inválido só surgia rodando o instalador manualmente, nunca de forma automática pelo
launcher do dia a dia.

A cada inicialização, o launcher agora valida, nesta ordem:
1. `.venv/bin/python` existe e roda (`--version` responde) — se não, tenta reparar via instalador
2. `/etc/phoenix/storage.json` existe, é JSON válido, tem campo `workspace`, o caminho é um diretório
   real e está acessível (`os.access(path, os.R_OK | os.X_OK)`)

Se qualquer uma dessas validações falhar:
1. executa `sudo pwsh ./install_phoenix.ps1` uma única vez (reaproveitando o `storage_scanner.ps1`
   oficial como fonte única da política de disco — o launcher não duplica lógica de escolha de disco)
2. revalida o estado
3. aborta com mensagem clara se continuar inválido, **sem loop infinito** (a estrutura é linear:
   `repair_once` só pode ser chamado no máximo uma vez por bloco de validação nesta execução)
4. usa `[ -t 0 ]` antes de qualquer `read -rp`, evitando travar esperando Enter caso o script seja
   chamado de forma não-interativa (systemd, cron, CI)

**Testes realizados (simulados, nesta máquina de auditoria, com Python real — não um stub):**
- `storage.json` ausente, sem instalador disponível → detectado, tenta reparar, falha limpo, sem loop
- `workspace` válido → pula reparo, inicializa direto
- `workspace` apontando para diretório/disco inexistente (cenário exato do log real de 2026-08-26) →
  detectado corretamente, aciona reparo
- execução não-interativa (`< /dev/null`) → não trava esperando `read`

**Validação ainda pendente:**
- rodar `repair_once` completo (chamando `sudo pwsh ./install_phoenix.ps1` de verdade) em Ubuntu real
- desmontar/remover deliberadamente o disco do workspace atual e confirmar a recuperação de ponta a
  ponta: novo `storage.json` gravado, reinicialização bem-sucedida

---

### `.venv` — auto-reparo no Linux

**Status: 🟡 CORRIGIDO / TESTADO EM SIMULAÇÃO / PENDENTE HARDWARE REAL**

Correção aplicada em: `Iniciar_Phoenix.sh` (mesma função `repair_once()` do item anterior)

Antes, se `.venv/bin/python` estivesse ausente ou quebrado (ex.: Python-base usado pra criar o venv
foi removido/atualizado depois), o launcher só avisava e orientava rodar o instalador manualmente.
Agora ele tenta reparar sozinho primeiro, chamando o mesmo `repair_once()` usado pelo `storage.json` —
mesma filosofia aplicada nos dois casos, sem duas lógicas de reparo diferentes convivendo no script.

**Testes realizados (simulados, nesta máquina de auditoria):**
- `.venv` ausente → detectado, aciona `repair_once`
- `.venv/bin/python` presente mas não executa (`--version` falha) → detectado, aciona `repair_once`
- reparo falha (instalador ausente no ambiente de simulação) → aborta limpo, sem loop, mensagem clara

**Validação ainda pendente:**
- confirmar `repair_once` completo com `sudo`/`pwsh` reais recriando um `.venv` de verdade em Ubuntu

---

### Windows — regressão

**Status: ✅ comportamento preservado**

Os caminhos de busca do `llama-server` no Windows (`bin/Release/llama-server.exe` e
`bin/llama-server.exe`) não foram alterados, só reordenados como primeiros candidatos da lista. O
`Iniciar_Phoenix.bat` não foi tocado nesta rodada — as correções desta seção são exclusivas dos
arquivos `llama_cpp.py` (compartilhado, mas aditivo) e `Iniciar_Phoenix.sh` (exclusivo do Linux).

---

## Antes da v31 (contexto herdado da memória de sessões anteriores, resumido)

Bugs encontrados e corrigidos em rodadas anteriores a esta linha de versão (v24 e anteriores),
confirmados por execução real:

- Descompasso de timeout entre o proxy Node (300s) e o driver llama.cpp (600s).
- `ensure_docker_running()` descartando o valor de retorno.
- Painéis do frontend simulando telemetria/latência/indexação RAG com `Math.random()`/`setTimeout` em
  vez de chamar rotas reais do backend.
- "Transcrição fantasma" — o LLM alucinava transcrição plausível quando nenhum áudio era anexado.
- `ModelManager` não encontrava o catálogo de downloads correto (`catalog/models.json`) vs. o
  `ModelRegistry`, que é só de roteamento.
- SDXL exigindo o componente VAE fp16-fix obrigatório (senão gera imagem preta).
- `ModelRegistry` usando paths relativos que quebravam fora da raiz do projeto.
- `_download_components()` não criava diretórios pai antes de escrever.
- Mascaramento silencioso de falha em downloads de componente.
- `ChangeDetectionEngine` com nomes de campo divergentes (`gpu_temperature_celsius` vs. `gpu_temp`),
  fazendo a detecção de mudança nunca disparar.
- AHDE (590 linhas, zero imports externos) integrada ao kernel com ingest no boot, polling de
  telemetria a cada 5s e shutdown gracioso.
- Ver também `CHANGES_GPU_FIX.md` nesta pasta — correção detalhada do caminho de imagem (Flux exigindo
  `--diffusion-model`/`--vae`/`--clip_l`/`--t5xxl` em vez de `-m`, contrato `download_model()` mudando
  de string para `Path | None`, `MissionExecutor` não tratando o novo contrato).

---

## v31 → v56 — changelog rodada a rodada

| Versão | O que mudou |
|---|---|
| **v31** | Arena/`dual_collab.py`: guarda de repetição same-speaker (`difflib`, 80% similaridade / 80+ caracteres) + reforço de prompt contra ecoar as tags `[MODELO-CPU]:`/`[MODELO-GPU]:` como se fossem parte da própria fala. |
| **v32** | Driver de LLM: fallback para `reasoning_content` quando `content` vem vazio (servidores recentes do llama-server separam "pensamento" da resposta final). Confirmado que `patch_verification.py` roda o código proposto de verdade em subprocesso isolado, nunca `exec()` no processo principal. |
| **v33** | `_looks_dangerous()` adicionado ao verificador — recusa rodar código com `import os/subprocess/socket/shutil/ctypes`, `eval`/`exec` ou escrita de arquivo antes de sequer criar o subprocesso (denylist contra alucinação destrutiva de modelo pequeno, não sandbox contra bypass deliberado). |
| **v34** | Fecha bypass real do denylist (`getattr(__builtins__, 'eval')(...)`) flagando tokens de introspecção dunder (`__builtins__`, `__globals__`, `__subclasses__`, `__bases__`). Mensagem de timeout deixou de afirmar "loop infinito" como única explicação. |
| **v35** | `select_next_speaker` como ponto de extensão opcional em `dual_collab.py` (comportamento padrão idêntico quando não usado). `_looks_dangerous()` reescrito para `ast.parse()` em vez de regex — fecha bypass real (`import os as sistema`). |
| **v36** | Causa raiz do veredito objetivo nunca aparecer: o campo de tema da Arena era um `<input>` HTML, incapaz de guardar quebra de linha — o texto multi-linha do usuário chegava tudo grudado no backend, e a regex `^\s*def` (dependia de início de linha) nunca reconhecia a função. Corrigido nas duas pontas: `<input>` → `<textarea>` no `ArenaView.tsx`, e regex `^\s*def` → `\bdef` (fronteira de palavra). |
| **v37** | `formatCollabResultForChat()` (botão "Enviar resultado pro chat") nunca lia `objective_check` — o veredito só aparecia se o modelo reciclasse aquela linha por acaso no histórico. Corrigido para sempre incluir o veredito real (🧪 confirmado / ⚠️ não confirmado/pulado). |
| **v38** | Progresso incremental na Arena — cada rodada aparece na tela assim que termina (polling a cada 1,5s), em vez de só no final das 6 rodadas. |
| **v39** | Instrução explícita de idioma (PT-BR) no início do `base_system_prompt` do `dual_collab.py` — modelo CPU (Qwen3-4B) deslizava para inglês, sobretudo em tarefas de código/performance. Reforço, não garantia. |
| **v40** | **Gate de conclusão da Arena**: `PROJETO_CONCLUIDO` mútuo só vira `✅ Concluída` em tópicos verificáveis (`topic_is_verifiable()`) se o último veredito conhecido foi um `CONFIRMADO` explícito — `FALHOU` e silêncio total não fecham mais a sessão. Fecha o buraco que motivou esta linha de auditoria. |
| **v41–v43** | Merge de `modelsData.ts` (13 modelos novos: Codestral 22B, Command R+, Gemma 2, Llama 3.2 Vision, LLaVA 1.6, SmolLM2, Granite 3.1, família FLUX, SD 3.5 Medium, Juggernaut XL v9, Wan 2.2 — 22 entradas no total). Correção de 2 URLs de catálogo quebradas (DeepSeek-R1 apontava para repo inexistente; Wan-Video → org correta `Wan-AI`) + 1 atualização preventiva (CohereForAI → CohereLabs). |
| **v43** | `AviaryApp.tsx`: as 5 vozes Piper vazavam para o dropdown de modelo de chat como se fossem modelos de texto — exclusão adicionada no início do loop de montagem da lista. |
| **v44** | Favicon/logo da Aviary (antes só um quadrado vermelho genérico) trocado pelo emblema real "Phoenix Aviary Platform". |
| **v45** | Botão de download de áudio no chat + aba dedicada "Texto → Áudio" (rota separada da do chat, sem o limite de 3s pensado para respostas curtas). |
| **v46** | Aba "Documento → Audiolivro": PDF/DOCX/PPTX/TXT/MD → um único MP3/WAV com Kokoro-82M, trocando de voz por trecho conforme o idioma muda no documento. Limite de segurança de 90 min para documentos muito longos. |
| **v47** | **Kokoro-82M vira o motor de voz único e padrão** (chat e "Texto Livre" antes usavam Piper). Seletor de 9 opções (Automático via `py3langid` + 8 idiomas). Timeout do botão de voz no chat sobe de 3s para 15s. Piper permanece no código como motor legado. Quebra de blocos do audiolivro passa a ser por frase, não só por parágrafo. |
| **v48 / v48.1** | Download automático do Kokoro (~340MB) direto pela UI, com validação de tamanho contra o anunciado pelo servidor (fecha bug real: download truncado por queda de conexão era aceito como completo). v48.1: pacotes Python do Kokoro (`kokoro-onnx`, `onnxruntime`, `phonemizer`, `espeakng-loader`, `py3langid`, `soundfile`) estavam no `requirements.txt` desde a v46/47 mas nunca tinham entrado na lista real de `pip install` do instalador (`install/common.ps1`) — corrigido; instalações novas já vêm funcionando. |
| **v49** | Opção de GPU (DirectML) para o Kokoro via `$env:PHOENIX_TTS_DEVICE` no topo do `install_phoenix.ps1`. |
| **v50** | GPU/DirectML testada de verdade na RX 580: falha reprodutível numa camada do vocoder (`ConvTranspose`, erro nativo "Parâmetro incorreto") — limitação de driver, não de código. Padrão revertido para CPU; mensagem de erro nativo malformado passou a ser clara em vez de um "codec" confuso. |
| **v51** | Mensagens de sistema (imagem gerada, resultado de colaboração, documento editado) inseridas no histórico do chat eram reenviadas ao modelo de texto como se fossem a própria fala dele — causava confusão de identidade (ex: qwen3-8b se identificando como "Flux 1-Schnell"). Corrigido: essas mensagens agora são marcadas e filtradas antes de irem ao modelo, continuam aparecendo normalmente na tela. |
| **v52** | Busca web real via SearXNG passa a valer também no **chat normal** (antes só na Arena/`/colaborar`) — mensagens com verbo de busca explícito disparam consulta real antes da resposta do modelo. |
| **v53** | Timeout fixo de 15s da rota `/api/tts/piper` (usada pelo botão de voz do chat) não escalava com o tamanho do texto — respostas longas (favorecidas pela busca web da v52) estouravam o teto de forma intermitente. Corrigido para escalar com o tamanho do texto (piso 15s, teto 120s) + logs reais de duração de síntese. |
| **v54** | Contexto do `llama-server` de 8192 → 16384 tokens (histórico + resultados de busca real cabendo com folga). Frontend deixou de alegar "128000" de contexto fixo para qualquer provedor sem checar o processo real. |
| **v55** | (Detalhes de driver/remoção confirmados por teste real e controle negativo — ver LEIA-ME do pacote no histórico de entregas.) |
| **v56** | **Causa raiz do "Headers Timeout Error" no chat**: a rota `/api/proxy/chat` era a única em `server.ts` que nunca tinha recebido a correção de timeout aplicada a outras 7 rotas numa auditoria anterior (2026-08-21/22) — o `fetch()` nativo do Node (via `undici`) derruba a conexão sozinho aos 300s, e como o chat usa `stream: false`, uma resposta longa em CPU pura (~4,6 tok/s medidos) passava fácil desse teto. Corrigido com `AbortController` dinâmico escalado pelo limite de tokens do pedido (mesmo método já usado no timeout do Kokoro). **Achado de bônus**: a rota de audiolivro tinha timeout próprio de 92 min mas o teto do dispatcher compartilhado só ia até 47 min — mesmo bug, corrigido junto. |

---

## RAG multi-documento no chat normal — entregue (v57, concluído em 2026-08-28)

Trabalho iniciado em 2026-08-24 para permitir que **qualquer LLM no chat normal** (não só o agente
Resident/Missões) consuma documentos indexados via RAG — incluindo documentos grandes (~1000 páginas)
para ensinar um modelo a programar/raciocinar melhor com contexto real. Interrompido por limite
semanal de uso logo depois de editar o backend; retomado e **concluído** na auditoria completa de
2026-08-28 (ver seção dedicada no topo deste documento).

**Escopo original, todo entregue:**
1. ✅ Injeção automática de contexto RAG em **toda mensagem** do chat normal (não só sob demanda) —
   `sendToProvider()` em `AviaryApp.tsx` (PHX-RAG v57).
2. ✅ `RagDrawer.tsx` aceita `PDF`/`DOCX`/`XLSX`/`PPTX`/`TXT`/`MD` (não mais só `.md`/`.txt`).
3. ✅ Chunking real via `_chunk_text()` em `chroma_rag_backend.py` — documentos grandes não são mais
   truncados num único chunk de ~256 tokens.
4. ✅ Proxies das rotas `/api/rag/add-file`, `/api/rag/query` e `/api/rag/delete` em `server.ts`.

**Entregue nesta rodada (2026-08-28), além do escopo original:**
- Consulta ao RAG chega a **qualquer provedor de chat**, local ou de nuvem — corrigido um bug real em
  que só o branch Gemini recebia o contexto do RAG; provedores locais (o caso de uso principal da
  Phoenix) nunca recebiam nada, apesar da consulta rodar.
- Trava de privacidade `blockRagOnCloudProviders` (ligada por padrão) — ver seção "Auditoria completa
  — 2026-08-28" no topo deste documento.
- Observabilidade (`console.debug`) da consulta RAG, distinguindo hit / 0 hits / falha / erro.
- Correções de dedup (normalização de título) e ordem de exclusão no `ChromaRagBackend`.

**Ainda em aberto (não é bloqueio técnico, é limitação do ambiente de auditoria):** validar
empiricamente se `min_score: 0.15` é o corte certo entre relevante/irrelevante com embeddings reais —
o ambiente onde esta auditoria roda bloqueia o download do modelo `all-MiniLM-L6-v2` (ChromaDB e
Hugging Face Hub, 403 nos dois). Os logs de observabilidade acima existem exatamente pra permitir essa
calibração com dados de uso reais numa máquina com rede normal.

Suíte completa (`pytest TESTS/`, os dois scripts standalone, os 9 arquivos `.mjs`) e
`tsc`/`vite build`/`esbuild` verificados na auditoria de 2026-08-28 — ver seção no topo.

---

## Observações gerais confirmadas nesta auditoria (não são bugs)

- **Limpeza pendente (não urgente):** o candidato `build_bin / "Release" / "llama-server"` (sem
  `.exe`) em `_find_executable()` nunca corresponde a nenhum layout de build real produzido pelo
  `common.ps1` — nem Windows nem Linux geram esse caminho. Inofensivo, mas confirmado como remoção
  segura numa próxima rodada de limpeza de código.
- As 7 falhas pré-existentes da suíte oficial são conhecidas desde antes da v47 e não têm relação com
  nenhuma correção desta linha de versões — seguem documentadas, não corrigidas de propósito nesta
  rodada (fora de escopo).
- 37 repositórios de terceiros estavam clonados no ambiente do usuário; a Phoenix efetivamente usa
  apenas `llama.cpp`, `stable-diffusion.cpp`, `Piper` (legado) e `whisper.cpp` (driver existia, repo
  não estava clonado — adicionado ao `common.ps1` ao final da auditoria, substituindo `faster-whisper`,
  que é uma biblioteca Python incompatível com o `WhisperDriver` atual). `LibreHardwareMonitor` é usado
  pela AHDE no Windows. O restante (`anything-llm`, `AutoGen`, `ComfyUI`, `CrewAI`, `LangGraph`,
  `OpenHands`, `SillyTavern`, etc.) não é consumido pelo código da Phoenix.

---

## Criação/transformação de documentos — confirmado em produção (auditoria 2026-08-27)

Achado desta rodada: a rota `/api/documents/create` (linha 941 de `api_server.py`) **já existe e é
real**, não uma pendência. Aceita instrução em texto, formato de saída (PDF/DOCX/XLSX/PPTX/TXT/MD),
arquivo-fonte opcional (transforma um documento existente em outro formato), e opção de busca web
antes de compor o conteúdo. Verifica que o arquivo final foi materializado no disco com tamanho > 0
antes de responder — mesmo padrão de "nunca aceitar sem confirmar" usado no resto do projeto.

Confirmado por teste real do usuário: pesquisa web → XLSX, pesquisa web → PDF, geração completa via
Qwen e via Gemma, ambos sem truncamento após a remoção do limite artificial de `max_tokens` no fluxo
documental (`unlimited_output=True`, confirmado no código de `resident_manager.py`).

**Este item estava incorretamente listado como pendência (`❌`) num resumo de sessão anterior — já
não é.** Serve de lembrete: qualquer item marcado como resolvido por uma sessão de IA diferente desta
auditoria deve ser reconferido contra o código real antes de atualizar este documento — o que foi
feito aqui.

---

## Próxima prioridade real: grounding da busca web (P0)

Com plataforma Linux e criação de documento resolvidos (ou corrigidos e pendentes só de validação em
hardware real), o gargalo mais importante do projeto deixou de ser "falta função" e passa a ser
"funções existentes não são verificáveis o suficiente" — especificamente, nada impede hoje que Qwen ou
Gemma citem uma fonte que não veio da busca real (URL inventada, atribuição cruzada errada, benchmark
não sustentado por nenhuma fonte real) dentro de um documento gerado.

Não existe hoje, em nenhum lugar do código, um sistema de ID de fonte (`[S1]`, `[S2]`...) nem uma
allowlist que rejeite citação de URL fora do que a busca real (SearXNG) retornou. Confirmado por busca
no código (`grounding`, `source_id`, `allowed_urls`, `citation` — nenhuma ocorrência relevante fora do
RAG interno, que é outro sistema).

Proposta de escopo pra próxima rodada:
```text
SearXNG retorna fontes reais
↓
Phoenix cria IDs [S1]...[S8]
↓
LLM só pode citar essas fontes
↓
URLs fora da lista são rejeitadas
↓
reprompt automático
↓
documento final
```

Depois, em ordem de prioridade: roteador de intenção mais robusto (hoje geração de imagem depende da
palavra literal "imagem" no prompt — achado do log de 2026-08-27), testes E2E Windows/Linux, boot
totalmente idempotente, UX de progresso pra tarefas longas.

---

## Nota do projeto (2026-08-27)

**8,7 – 8,8**, revisada pra cima em relação à rodada anterior (8,3–8,5) porque os dois bugs de
plataforma que seguravam o teto (`llama-server` path e `storage.json` no Linux) agora têm correção
testada — não apenas declarada — nesta auditoria. Não sobe além disso porque ainda falta a validação
final em Ubuntu real (item mais barato de fechar) e porque o grounding de busca web segue em aberto
(item estrutural, não custa nada de código já escrito).
