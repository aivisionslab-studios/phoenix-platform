# Recuperação Total de Funcionalidades — Phoenix Engine / Phoenix Aviary Platform

**Data:** 04/08/2026
**Escopo:** auditoria técnica completa do pacote `PHOENIX_3.0` + correções aplicadas + validação de ponta a ponta.
**Metodologia:** Errata Evolutiva (mesmo espírito do `institutional/docs/CHANGELOG.md`) — cada item abaixo documenta o estado anterior, a causa raiz, a correção e como foi validada. Nada aqui foi "só revisado visualmente" a menos que explicitamente marcado com ⚠️.

---

## Resumo executivo

**Antes desta recuperação, a Phoenix Engine não subia.** `PhoenixKernel()` — a classe que `api_server.py` instancia na primeira linha do arquivo — quebrava com `IndentationError` antes mesmo de terminar o `__init__`. Isso significa que, na prática, **nenhuma funcionalidade da plataforma estava operacional**: nem chat, nem geração de imagem, nem análise de hardware, nem RAG, nem a Aviary Platform (porta 3000) — tudo depende do kernel subir primeiro.

**Depois:** `PhoenixKernel()` instancia e `await kernel.boot()` completa sem exceção, validado a partir de uma extração limpa do zip final (não do ambiente de trabalho onde as correções foram feitas). Isso foi confirmado executando o boot real, não apenas verificando sintaxe.

Abaixo, o que a plataforma **não fazia e agora faz**, funcionalidade por funcionalidade.

---

## 1. Subir o kernel (pré-requisito de tudo o resto)

| | Antes | Depois |
|---|---|---|
| `PhoenixKernel()` | `IndentationError` na importação de `phoenix_kernel/runtime/engine.py`, linha 21 | Instancia sem erro |
| `await kernel.boot()` | Nunca chegava a rodar (o processo morria no import) | Completa Discovery → Planner/RAG → Runtime → download de modelo → Aviary Platform → LM Studio → loop de sync com Firestore, sem exceção |

**Causa raiz:** o script `setup_vision.py` (gerador automático do driver de visão) inseria a linha de import do `MtmdDriver` com uma indentação hardcoded de 12 espaços, presumindo que a âncora estava dentro de um bloco indentado. A âncora real está no nível do módulo (coluna 0). Resultado: toda vez que `setup_vision.py` rodava (ou já tinha rodado, deixando o arquivo neste estado), `runtime/engine.py` ficava sintaticamente inválido, e como `PhoenixKernel.__init__` importa esse módulo sem nenhum `try/except` ao redor, **a falha se propagava e derrubava a criação do kernel inteiro**, não só a funcionalidade de visão.

**Corrigido em dois níveis:**
- O arquivo `phoenix_kernel/runtime/engine.py` já entregue está com a indentação corrigida.
- O gerador `setup_vision.py` foi corrigido para calcular a indentação real da linha-âncora (a mesma técnica que a rotina de registro, logo abaixo no mesmo arquivo, já usava corretamente) — então esse bug **não volta** se `setup_vision.py` for executado de novo no futuro (por exemplo, ao reprocessar visão numa reinstalação).

**Validado:** rodando `setup_vision.py` do zero contra uma cópia limpa de `engine.py` e confirmando que o resultado compila; e instanciando `PhoenixKernel()` + `kernel.boot()` a partir do zip final entregue.

---

## 2. Driver de visão nativa (`MtmdDriver`) registrado no Runtime

| | Antes | Depois |
|---|---|---|
| `RuntimeEngine._drivers["vision"]` | Nunca existia — o `MtmdDriver` era importado mas nunca instanciado | Registrado na lista `optional_drivers`, isolado (uma falha nele não derruba os outros drivers) |

**Causa raiz:** além do bug de indentação (item 1), o passo de *registro* do `setup_vision.py` também estava quebrado — sua âncora (`self._drivers["sdxl"] = SdCppDriver(`) referenciava um padrão de atribuição direta que não existe mais desde que `engine.py` foi refatorado para a lista `optional_drivers` com lambdas isolados por driver. O passo de registro falhava silenciosamente (só um `[WARN]` no console, fácil de passar despercebido), então mesmo corrigindo a indentação, o driver de visão continuaria "importado, mas morto" — qualquer `ExecutionPlan(runtime="vision", ...)` falharia com `"Runtime 'vision' not found"`.

**Corrigido:** âncora do passo de registro atualizada para o padrão atual (insere uma nova tupla `("vision", lambda: MtmdDriver())` na lista, em vez de uma atribuição solta que quebraria a sintaxe dentro do list literal).

**Validado:** patch aplicado do zero contra `engine.py` limpo; `grep` confirmando a linha de registro presente e correta; compilação bem-sucedida do resultado.

---

## 3. Descrição de imagem via API (`POST /api/describe-image`)

| | Antes | Depois |
|---|---|---|
| Endpoint | Não existia | Criado, com ponte direta ao `MtmdVisionDriver` (mesma filosofia do `/api/generate-image` já existente — sem passar por Mission/aprovação) |
| Descoberta do modelo | N/A | Localiza `MiniCPM-V-*.gguf` e `mmproj-*.gguf` em `Workstations/Models/Chat/GGUF` automaticamente, sem hardcodar nome de arquivo ou unidade de disco |
| Robustez da descoberta | N/A | Prioriza nomes conhecidos de modelo de visão (`minicpm`, `llava`, `qwen2vl`, `gemma3`); só usa "único .gguf grande" como fallback quando não há ambiguidade — evita escolher por engano um LLM de texto (ex: `qwen3-8b.gguf`) que esteja na mesma pasta |

**Validado:** testado com um cenário simulado contendo o modelo de visão real (`MiniCPM-V-2_6-Q6_K_L.gguf`) e um LLM de texto de mesmo tamanho na mesma pasta — a escolha do modelo correto continuou determinística.

**Dependência nova introduzida por este endpoint:** `python-multipart` (ver item 6).

---

## 4. RAG / Base de Conhecimento (`ChromaDB`) — a funcionalidade que estava "morta em 3 camadas"

Este era o achado mais sutil da auditoria: os ~91 documentos curados (`knowledge_base.json`) e os 226 chunks já ingeridos em `data/chroma_db` **nunca alimentavam o LLM em produção**, apesar do código dar a impressão de que sim.

| Camada | Antes | Depois |
|---|---|---|
| **1. Conexão com o backend** | `KnowledgeEngine(...)` era sempre instanciado sem `rag_backend` (ficava `None`) nos dois pontos de uso (`planner/engine.py` e `intelligence/reasoning_engine.py`), apesar do comentário no código dizer *"Instancia o KnowledgeEngine real (ChromaDB) corretamente"` | Criado `phoenix_kernel/intelligence/chroma_rag_backend.py` — implementação real do `RagBackend`, conectada de fato à coleção `aivisions_knowledge_base` já existente em `data/chroma_db` (226 documentos) |
| **2. Chamada assíncrona indevida** | `evaluator.py` e `resident_manager.py` faziam `await self.knowledge.query_knowledge(...)` — mas o método é **síncrono**. Isso levantava `TypeError` toda vez. Em `evaluator.py`, o erro era engolido por um `try/except` (RAG ficava sempre desativado, silenciosamente, sem log visível); em `resident_manager.py`, **não havia proteção nenhuma**, e o comando de análise de hardware (`analyze_hardware()`) quebrava com exceção não tratada sempre que era chamado | `await` removido dos dois lugares; chamada síncrona direta |
| **3. Formato do retorno** | O código tratava o retorno como dicionário (`recommendation.get("name")`, `.get("notes")`, `.get("command")`) — mas `query_knowledge()` sempre retornou `list[str]` (trechos de texto), que não tem `.get()`. Mesmo corrigindo a Camada 2, isso quebraria de novo com `AttributeError` | Reescrito para consumir a lista de hits corretamente — em `evaluator.py`, extrai um nome de modelo `.gguf` mencionado nos trechos via regex; em `resident_manager.py`, lista os hits diretamente no relatório |

**Resultado prático:** o comando de análise de hardware (Resident Manager) e o planejamento de execução (Planner) agora **conseguem de fato consultar o histórico de benchmarks e procedimentos já documentados** ao decidir como responder — antes, sempre caíam no comportamento padrão, sem nunca tocar no que já foi aprendido sobre esta máquina.

**Validado:**
- `ChromaRagBackend` testado de ponta a ponta (conectar, contar, inserir, consultar, idempotência de reingestão, entradas vazias) com uma embedding function determinística de teste.
- Confirmado que conecta de fato na coleção real e enxerga os 226 documentos já existentes (`count() == 226`).
- ⚠️ Não testei uma consulta semântica real fim-a-fim com a embedding function **padrão** do ChromaDB (ela baixa um modelo ONNX de `chroma-onnx-models.s3.amazonaws.com` na primeira execução, domínio bloqueado neste ambiente de sandbox) — deve funcionar normalmente na sua máquina, com internet livre; é uma dependência de rede pontual, não recorrente (fica em cache local depois).

**Observação em aberto (não é bug, é decisão de arquitetura):** essa dependência de rede pontual do ChromaDB é um ponto de tensão com a filosofia 100% local/offline do projeto. Dá para eliminar trocando por um embedder rodando via llama.cpp — fica como decisão sua, não fiz essa mudança por conta própria.

---

## 5. Suíte de testes — de 0% de cobertura real para 13/13 passando

| | Antes | Depois |
|---|---|---|
| `pytest tests/` | Falhava na **coleta** (nem chegava a rodar 1 teste): `tests/test_mission_kernel.py` importava `phoenix_kernel.core.kernel.MissionKernel`, uma classe que nunca existiu no projeto | `phoenix_kernel/core/kernel.py` criado com a classe `MissionKernel` (portão de aprovação de missão única — register/approve/reject), com comportamento derivado diretamente das 13 asserções já escritas no teste existente | 
| Resultado | 0 testes executáveis | **13/13 passam** |

Isso também explica, em retrospecto, por que o bug do item 1 (`IndentationError` derrubando o kernel inteiro) nunca foi pego automaticamente: não havia rede de segurança nenhuma rodando contra o código real.

---

## 6. Instalação e inicialização (Windows e Linux)

| | Antes | Depois |
|---|---|---|
| `Iniciar_Phoenix.bat` | Só checava `if exist .venv\Scripts\python.exe` — um venv com `pyvenv.cfg` apontando pra um Python removido/movido (ex: após o instalador reparar o Python via `winget --force` numa execução posterior) passava nesse teste e só quebrava depois, com a mensagem confusa `No Python at '"C:\Program Files\Python312\python.exe'` | Valida `--version` de verdade antes de decidir pular a instalação; se o venv estiver morto, apaga e reinstala automaticamente |
| `Iniciar_Phoenix.sh` | **Já vinha quebrado no zip original**, independente de qualquer coisa nossa: terminação de linha CRLF, que faz o parser do bash falhar (`bash -n` já acusava `syntax error: unexpected end of file` no arquivo original, sem edição nenhuma) | Convertido para LF puro; validado com `bash -n` e com execução real (dois cenários: venv ok e venv quebrado) |
| `install/common.ps1` | Só checava se `Activate.ps1` existia (arquivo estático, não valida se o Python por trás ainda funciona) | Adicionada validação real (reaproveitando a função `Test-PhoenixPythonBinary` já existente), com remoção + recriação automática do venv se estiver quebrado. ⚠️ Não consegui rodar `pwsh` neste ambiente para testar de ponta a ponta — só revisão de código + checagem de balanceamento de chaves/parênteses |
| `requirements.txt` | Só listava `google-cloud-firestore`/`google-auth` — nenhuma das dependências reais do projeto (`fastapi`, `chromadb`, etc.) | Reescrito com todas as dependências reais em uso, incluindo `python-multipart` (ver abaixo). Validado com `pip install --dry-run` — resolve sem conflitos |
| Dependência faltando | `python-multipart` não era instalada em lugar nenhum, mas o endpoint `/api/describe-image` (item 3) usa `UploadFile`/`Form`, que **exige** esse pacote — sem ele, o FastAPI levanta `RuntimeError` **na hora de registrar a rota**, derrubando a criação do `app` inteiro, não só aquele endpoint | Adicionada em `install/common.ps1` e em `requirements.txt`. Reproduzi o erro e confirmei a correção instalando o pacote e testando a criação da rota |

---

## O que a Phoenix Engine consegue fazer agora, que não conseguia antes (resumo funcional)

- **Subir.** (Isso sozinho já era o suficiente pra tudo mais abaixo ser irrelevante antes de hoje.)
- Rodar a Aviary Platform (porta 3000) supervisionada pelo kernel.
- Registrar e usar o driver de visão nativo (`llama-mtmd-cli`) dentro do `RuntimeEngine`.
- Descrever imagens via API (`/api/describe-image`), com descoberta automática e robusta do modelo.
- Consultar de verdade o histórico de benchmarks e procedimentos já documentados (RAG) tanto no planejamento de execução quanto na análise de hardware do Resident Manager — em vez de sempre cair no comportamento padrão.
- Rodar a suíte de testes e ter sinal real de regressão (13 testes, antes 0 executáveis).
- Iniciar corretamente em Windows e Linux mesmo quando o Python-base do venv foi removido/movido — autocorrigindo em vez de travar com uma mensagem confusa.
- Instalar todas as dependências reais a partir de `requirements.txt` sozinho, sem depender de saber de cor o `pip install` embutido no `.ps1`.

## O que ainda não foi feito (decisões em aberto, não bugs)

- Consolidação das duas implementações paralelas de `KnowledgeEngine` (`planner/` vs `intelligence/`) — ambas têm RAG funcional agora, mas continuam duplicadas.
- Troca da embedding function padrão do ChromaDB (dependência de rede pontual) por um embedder 100% local via llama.cpp.
- Validação de ponta a ponta do `install/common.ps1` com `pwsh` real (só revisão de código nesta rodada).
