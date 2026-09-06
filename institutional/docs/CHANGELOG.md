# Changelog — AIVisions Phoenix Engine

Este arquivo documenta mudanças relevantes do projeto, seguindo a metodologia de **Errata Evolutiva**: correções e mudanças que quebram compatibilidade são registradas de forma transparente, não silenciosamente sobrescritas.

## [Não lançado — 06/09/2026]

### Corrigido
- **Resposta do modelo cortada, sem erro, nos dois provedores (local e
  Gemini)** — investigação completa, incluindo um desvio de raciocínio
  inicial (contexto/timeout) corrigido pelo usuário no meio do processo.
  Ver [INVESTIGACAO_RESPOSTA_CORTADA.md](./INVESTIGACAO_RESPOSTA_CORTADA.md)
  para a linha do tempo completa. Resumo:
  - `llama-server`: sem `--jinja` explícito, a tag `<think>` (raciocínio de
    modelos como Qwen3) podia vir embutida na resposta; se a geração
    cortasse com a tag aberta (nunca fechando), o front-end não conseguia
    separar raciocínio de resposta, vazando texto bruto ou sufocando a
    resposta visível. Corrigido com `--jinja` explícito + leitura do
    campo `reasoning_content` que o servidor já separa corretamente.
  - Gemini: modelos 2.5+/3.x pensam por padrão, e o raciocínio consome o
    mesmo `maxOutputTokens` da resposta visível — sem configurar isso,
    o raciocínio podia comer o orçamento inteiro (resposta vazia/cortada,
    sem erro). Corrigido com `thinkingConfig` explícito + reserva de
    orçamento extra só pro raciocínio.
- Contexto do `llama-server` aumentado de 16384 para **32768** (a pedido
  do usuário, resolvendo separadamente o timeout de rede em conversas
  longas — problema real, mas diferente do acima).
- Checkbox "Sem limite" no painel de parâmetros do chat — replica o
  `unlimited_output` que a criação de documentos já tinha, agora também
  disponível pro chat comum.

## [4.5 — auditoria de setembro/2026]

### Corrigido
- **Flux removido de vez** — o modelo Flux (e SD3.5) crashava em todos os
  placements na RX 580 (violação de acesso `0xC0000005` no caminho nativo
  Vulkan, confirmada em log). Removido de perfis, catálogo, instalador,
  seletor e runtime; **SDXL é o novo default de imagem**. SD 1.5 e SDXL
  permanecem e rodam sem restrição — na prática, resultado superior ao Flux
  nesse hardware.
- **RAG lento (anexar documento demorava demais)** — cada documento era
  vetorizado DUAS vezes (um upsert gravava os chunks, outro re-gravava os
  mesmos só para anexar cross-links). Reordenado para **um upsert único**;
  corta o tempo de ingestão pela metade.
- **Detecção de modelos intermitente ("a pasta some")** — dois resolvedores de
  storage independentes (`StorageManager` e `PhoenixPaths`) procuravam o
  `storage.json` relativo ao diretório de execução e cacheavam para sempre.
  Corrigidos para **caminho absoluto** (raiz do projeto via `__file__`) com
  `reload()`/`reset_cache()`.
- **Texto→áudio só funcionava com arquivo** — o texto livre ia numa chamada
  monolítica; textos longos travavam. Unificado com o **particionamento do
  audiolivro** (quebra em blocos acima de 600 caracteres, com silêncio entre
  eles).
- **Preenchimento de planilha demorava >90min e virava processo órfão** — a
  interface usava o caminho por LLM. Ligado o **caminho determinístico**
  (Pipeline V2 + Smart Filler), que faz o mesmo em segundos e, por não usar
  inferência, não deixa processo preso.
- **Planilha saía "vazia"** — nome de produto por título numerado ("63. Nome")
  não era extraído (coluna Descrição vazia) e ~1000 linhas fantasma de
  meta-conversa poluíam o resultado. Corrigido o detector e adicionado filtro
  de registros sem conteúdo real.

### Adicionado
- **Pipeline de Documentos e Planilhas determinístico** (ver
  [DOCUMENT_PIPELINE.md](./DOCUMENT_PIPELINE.md)): Smart Filler (regras +
  geração + guarda-fiscal), Fiscal RAG (sugere NCM/CEST de base auditada),
  Barcode Finder (pesquisa EAN com auditoria humana obrigatória), LLM Reviewer
  (resolve só os conflitos, allowlist fechada anti-alucinação).
- Rota `POST /api/documents/pipeline-fill` — preenchimento determinístico.

### Removido
- `phoenix_kernel/runtime/drivers/piper.py` (driver morto; Kokoro é o único TTS
  gerenciado).
- Perfis Flux/SD3.5 e seus assets de catálogo.

### Testes
- Suíte: **612 passed, 2 skipped** (`python -m pytest TESTS/ -q`). Mapa
  completo em `MAPA_TESTES_PHOENIX_4_5.md`.

## [Não lançado]

### Corrigido
- Checagem de prontidão do `settings.yml` do SearXNG (chave `server:`/`secret_key:` em vez de `formats:`);
- Patch de configuração do SearXNG usando inserção idempotente de blocos em vez de descomentar linhas inexistentes;
- Substituição regex mal escapada gravando barras invertidas literais no `settings.yml` — corrigido com função lambda de substituição;
- Erro de Execution Policy do Windows bloqueando o instalador — resolvido com lançador `Instalar_Phoenix.bat`;
- Bug do `ProvisioningEngine` restrito a `winget` sem fallback Linux — resolvido com `AptConnector`;
- Bug do `ServicesEngine` sem `event_bus`;
- Regressão no roteamento Ollama/download do `llama_cpp.py` causada por versão externa que melhorava descoberta de caminhos mas removia as regras de roteamento — mesclado mantendo ambas as melhorias.

### Adicionado
- `gpu_split.py` — calculadora de split GPU/CPU/híbrido baseada em header GGUF e VRAM real;
- Agente residente completo (Intent → Research → Decision → Approval → Execute) portado para `intelligence/`;
- `HardwareDiscoveryAdapter` como drop-in para `HardwareBridge`, com fallback automático;
- Integração do `HardwareTelemetryCore` do pacote `hardware_engine` no `HardwareDiscoveryAdapter`.

### Removido
- Código órfão: `phoenix_kernel/core/event_bus.py`, `phoenix_kernel/contracts/`, `13_resident/resident_manager.py` quebrado.

### Segurança
- Incidente identificado: `data/firebase_service_account.json` (chave privada real) incluído indevidamente em um pacote enviado fora do controle de versão. Recomendação: rotacionar a chave no console do Firebase.

## Itens conhecidos em aberto
- API mismatch em `HardwareDiscoveryCore` (modelo de scan contínuo substituindo `discover()`/`load()` discretos);
- Erro `"name 'MissionAction' is not defined"` ao processar comando de missão via `POST /api/command` — import faltando, ainda não investigado.
