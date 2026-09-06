# Manual de Uso — Phoenix 3.0

Guia completo, passo a passo, de todas as funcionalidades da Phoenix. Cobre as duas interfaces do
sistema: a **Phoenix Aviary** (chat, porta 3000) e o **Phoenix Engine Mission Control** (dashboard de
hardware, porta 8000).

---

## Sumário

1. [Visão geral](#1-visão-geral)
2. [Como iniciar a Phoenix](#2-como-iniciar-a-phoenix)
3. [As duas interfaces](#3-as-duas-interfaces)
4. [Chat de texto](#4-chat-de-texto)
5. [Configurando o Gemini (provedor de nuvem)](#5-configurando-o-gemini-provedor-de-nuvem)
6. [Parâmetros do chat](#6-parâmetros-do-chat)
7. [Gerenciando provedores (Stack)](#7-gerenciando-provedores-stack)
8. [RAG — Base de Conhecimento](#8-rag--base-de-conhecimento)
9. [Privacidade do RAG com provedores de nuvem](#9-privacidade-do-rag-com-provedores-de-nuvem)
10. [Geração de imagem](#10-geração-de-imagem)
11. [Descrever uma imagem](#11-descrever-uma-imagem)
12. [Extrair texto de uma imagem (OCR)](#12-extrair-texto-de-uma-imagem-ocr)
13. [Ler e resumir documentos](#13-ler-e-resumir-documentos)
14. [Criar e transformar documentos](#14-criar-e-transformar-documentos)
15. [Voz — Texto para Áudio](#15-voz--texto-para-áudio)
16. [Voz — Documento para Audiolivro](#16-voz--documento-para-audiolivro)
17. [Transcrever um áudio](#17-transcrever-um-áudio)
18. [Busca web integrada](#18-busca-web-integrada)
19. [Arena — colaboração entre dois modelos](#19-arena--colaboração-entre-dois-modelos)
20. [Calculadora de VRAM](#20-calculadora-de-vram)
21. [Model Hub — benchmark e modelos instalados](#21-model-hub--benchmark-e-modelos-instalados)
22. [Mission Control — dashboard de hardware](#22-mission-control--dashboard-de-hardware)
23. [Missões autônomas e aprovação de ações](#23-missões-autônomas-e-aprovação-de-ações)
24. [App Store — missões prontas](#24-app-store--missões-prontas)
25. [Planos Free x Pro](#25-planos-free-x-pro)
26. [Privacidade e segurança — resumo prático](#26-privacidade-e-segurança--resumo-prático)
27. [Solução de problemas comuns](#27-solução-de-problemas-comuns)

---

## 1. Visão geral

A Phoenix é uma plataforma de IA que roda no seu próprio computador. Ela orquestra modelos de
linguagem, imagem, voz e busca — locais (Ollama, LM Studio, llama.cpp/Vulkan) ou na nuvem (Gemini,
quando você configura) — e organiza tudo isso numa interface única, com uma base de conhecimento
própria (RAG) alimentada pelos seus documentos.

Dois processos rodam ao mesmo tempo:

- **Phoenix Engine** (Python, porta **8000**) — o núcleo: gerencia hardware, modelos, missões
  autônomas e a base de conhecimento.
- **Phoenix Aviary** (Node, porta **3000**) — a interface de chat onde você efetivamente conversa,
  gera imagem, ouve voz e roda comparações entre modelos.

---

## 2. Como iniciar a Phoenix

**Windows:** dê dois cliques em `Iniciar_Phoenix.bat` (ou clique com o botão direito → "Executar como
Administrador"). Na primeira vez, ele instala tudo sozinho; nas próximas, só sobe os serviços.

**Linux:** rode `./Iniciar_Phoenix.sh` no terminal, dentro da pasta do projeto.

Depois de subir, abra o navegador em `http://localhost:3000` para o chat, ou
`http://localhost:8000` para o painel de hardware.

---

## 3. As duas interfaces

| Interface | Endereço | Pra que serve |
|---|---|---|
| **Aviary** | `localhost:3000` | Chat, geração de imagem, voz, Arena, RAG |
| **Mission Control** | `localhost:8000` | Hardware, missões automáticas, RAG (também acessível daqui) |

Você pode alternar entre elas pela barra superior da aplicação (ícones de processo).

---

## 4. Chat de texto

**Onde:** aba **Chat** da Aviary (aberta por padrão).

1. No topo, no seletor **"MODELO:"**, escolha um modelo. Cada opção mostra `[PROVEDOR] nome-do-modelo`
   — por exemplo `[OLLAMA] qwen3:8b` ou `[GEMINI] gemini-3.6-flash`.
2. Digite sua mensagem na caixa de texto na parte inferior e envie.
3. A resposta aparece no chat, com um indicador de "Processando com [modelo]..." enquanto gera.
4. Se quiser ouvir a resposta em voz alta, use o botão de volume ao lado da mensagem (usa o motor de
   voz Kokoro).

Modelos **locais** (Ollama, LM Studio, llama-server) só aparecem no seletor depois de confirmados
online — use o botão de detecção automática (ícone de radar/scan) pra escanear o que está rodando na
sua máquina.

---

## 5. Configurando o Gemini (provedor de nuvem)

O Gemini **não usa login/senha** dentro da Phoenix — é uma chave de API que você gera uma vez e cola
num arquivo de configuração.

1. Acesse [aistudio.google.com/apikey](https://aistudio.google.com/apikey) com sua conta Google e
   clique em **"Create API key"**. Se for a primeira vez, o Google cria um projeto padrão
   automaticamente, sem pedir configuração de faturamento.
2. Dentro da pasta `platform_source`, copie o arquivo `.env.example` para um novo arquivo chamado
   `.env` (se ainda não existir um).
3. Abra o `.env` e troque a linha `GEMINI_API_KEY="MY_GEMINI_API_KEY"` colando sua chave no lugar de
   `MY_GEMINI_API_KEY`.
4. Reinicie o processo da Aviary (feche e abra de novo o `Iniciar_Phoenix`, ou reinicie o `npm run
   dev`/`npm start` se estiver rodando manualmente) — a chave só é lida quando o servidor sobe.
5. Pronto: os modelos Gemini aparecem no seletor de modelo automaticamente.

Sem essa chave configurada, tentar usar o Gemini mostra um erro claro (não trava nem finge sucesso), e
todo o resto da Phoenix continua funcionando normalmente com provedores locais.

---

## 6. Parâmetros do chat

**Onde:** ícone de controles deslizantes (sliders) no topo da aba Chat.

- **Instrução de sistema (System Prompt):** escolha um preset pronto (Assistente Geral, Código,
  Criativo etc.) ou escreva o seu próprio, no campo de texto.
- **Temperatura:** controla o quão "criativa" vs "precisa" é a resposta (0 = mais preciso, 2 = mais
  criativo).
- **Máximo de Tokens:** limite de tamanho da resposta gerada.
- **Bloquear RAG em provedores de nuvem:** ligado por padrão — ver seção 9 para detalhes completos.

O botão de resetar (ícone circular) volta todos os parâmetros ao padrão de fábrica, mantendo a
proteção de RAG ligada.

---

## 7. Gerenciando provedores (Stack)

**Onde:** aba **Stack** (ícone de servidor/ecossistema).

Aqui você vê o status de cada provedor configurado (Ollama, LM Studio, llama-server, Gemini):

- **Testar conexão:** botão que faz um ping real no provedor e atualiza a lista de modelos disponíveis
  com o que de fato está instalado — nunca mostra um modelo que não foi confirmado.
- **Editar configuração:** endereço (`baseUrl`) e, se aplicável, chave de API de cada provedor.
- **Status:** `connected` (conectado, pronto pra uso) ou `disconnected` (ainda não confirmado — os
  modelos dele não aparecem no seletor do chat até você testar a conexão).

---

## 8. RAG — Base de Conhecimento

O RAG é a base de conhecimento pessoal da Phoenix: documentos que você indexa ficam disponíveis para
qualquer modelo consultar automaticamente durante o chat.

**Onde:** ícone de banco de dados (RAG Knowledge Repository), acessível tanto pela Aviary quanto pelo
Mission Control.

### Adicionar um documento

1. Clique em "Adicionar documento" ou arraste o arquivo pra dentro do painel.
2. Formatos aceitos: `PDF`, `DOCX`, `XLSX`, `PPTX`, `TXT`, `MD`. Formatos incompatíveis num lote misto
   são ignorados, sem cancelar os arquivos compatíveis do mesmo lote.
3. O documento é extraído, dividido em pedaços (chunks) e indexado localmente — sem sair da sua
   máquina.
4. Se você subir um lote com vários arquivos e algum falhar, os outros continuam sendo processados; ao
   final você vê um resumo tipo "3 de 5 indexado(s). Falha em: arquivo.pdf: ...".

### Consultar automaticamente

Você não precisa fazer nada especial: a partir do momento que um documento está indexado, qualquer
pergunta no chat que tenha relação com ele já traz o contexto relevante automaticamente, citando a
fonte e o grau de similaridade.

### Reindexar um documento já existente

Subir de novo um arquivo com o mesmo título (mesmo com maiúsculas/minúsculas diferentes) é tratado como
**atualização** do mesmo documento — não consome uma vaga nova.

### Apagar um documento

Clique no ícone de lixeira ao lado do documento na lista. A remoção é imediata: o documento para de
ser retornado nas buscas assim que você confirma a exclusão.

---

## 9. Privacidade do RAG com provedores de nuvem

Por padrão, o conteúdo dos seus documentos indexados **nunca é enviado a um provedor de nuvem** (hoje,
o Gemini) — mesmo que você escolha conversar com ele.

- Quando o modelo ativo é de nuvem, um badge verde **"RAG bloqueado (nuvem)"** aparece ao lado do
  seletor de modelo, indicando que a proteção está ativa.
- Se quiser usar RAG com um provedor de nuvem mesmo assim (por exemplo, para documentos que você
  considera não sensíveis), desligue a opção **"Bloquear RAG em provedores de nuvem"** em Parâmetros
  (seção 6).
- Provedores locais (Ollama, LM Studio, llama-server) nunca são afetados por essa proteção — o RAG
  sempre funciona neles normalmente, porque o conteúdo já fica inteiramente na sua máquina.

---

## 10. Geração de imagem

**Onde:** aba Chat — não precisa de botão especial, basta pedir na própria mensagem.

Exemplos de como pedir:
- `Gere uma imagem de um pôr do sol em uma praia tropical.`
- Ou um prompt "cru" no estilo Stable Diffusion: `sunset on tropical beach, digital art, highly detailed`

A Phoenix detecta a intenção de gerar imagem automaticamente, escolhe o modelo local instalado (SD1.5,
SDXL ou FLUX.1-schnell, conforme disponível) e mostra a imagem gerada direto no chat, junto com o nome
do modelo usado.

---

## 11. Descrever uma imagem

**Onde:** aba Chat → ícone de clipe (anexo) → selecione uma imagem → escreva sua pergunta.

Exemplo: anexe uma foto e pergunte `O que tem nesta imagem?` ou `Descreva esta cena em detalhes`. A
Phoenix usa um modelo de visão local (minicpmv) para gerar uma descrição real do conteúdo.

---

## 12. Extrair texto de uma imagem (OCR)

**Onde:** mesmo fluxo de anexar imagem, mas pedindo para transcrever o texto.

Exemplo: anexe uma captura de tela ou foto de um documento e peça `Transcreva o texto desta imagem`. A
Phoenix reconhece a intenção de OCR e extrai o texto real via Tesseract/MiniCPM-V, em vez de apenas
descrever a imagem.

---

## 13. Ler e resumir documentos

**Onde:** aba Chat → anexe um PDF, DOCX, XLSX ou TXT → faça sua pergunta sobre o conteúdo.

Exemplos:
- `Resuma este documento em 5 pontos principais.`
- `Quais são os valores totais mencionados neste PDF?`

A Phoenix extrai o conteúdo real do arquivo (com OCR automático quando necessário, para PDFs
escaneados) e responde com base nele, sem limite artificial de tamanho de resposta.

---

## 14. Criar e transformar documentos

**Onde:** aba Chat, pedindo a criação de um documento.

Exemplos:
- `Crie um documento DOCX com um resumo sobre energia renovável.`
- `Pesquise as notícias mais recentes sobre carros elétricos e crie um PDF com os principais pontos.`

Formatos de saída suportados: PDF, DOCX, XLSX, PPTX, TXT, MD. Você também pode enviar um documento
existente e pedir para transformá-lo em outro formato.

**Preencher uma planilha usando outro documento como fonte.** Anexe dois arquivos na mesma mensagem —
um `.xlsx` (o template a preencher) e outro documento não-imagem (`.pdf`, `.docx`, `.pptx`, `.md` ou
`.txt`, o documento-fonte com os dados) — e escreva uma instrução dizendo o que mapear, por exemplo:

> `Leia a conversa anexada e preencha a planilha do template com os produtos, preços e demais dados
> mencionados nela. Uma linha por produto/item, usando as colunas já existentes na planilha.`

A Phoenix detecta sozinha essa combinação (dois documentos, exatamente um `.xlsx`) e usa o modelo de
texto pra extrair os dados do documento-fonte e preencher a planilha, mantendo formatação e fórmulas já
existentes no template. Pra fontes de dados atuais (preço de mercado, cotação etc.), inclua palavras
como "pesquise" ou "dados atuais" na instrução — isso liga uma busca web real antes do preenchimento.

> **Catálogo/planilha grande e lento demais?** Veja a dica de GPU+CPU juntas na seção 27 (Solução de
> problemas comuns) — em hardware com GPU ociosa, ligar isso pode acelerar bastante esse tipo de tarefa.

---

## 15. Voz — Texto para Áudio

**Onde:** aba **Voz** → sub-aba "Texto → Áudio".

1. Cole ou digite o texto que você quer transformar em áudio.
2. Escolha uma voz (ou deixe em "Automático" para detecção de idioma).
3. Clique em gerar — o áudio (Kokoro-82M, motor neural local) fica disponível para ouvir e baixar.

Suporta 8 idiomas, com detecção automática de qual idioma está sendo falado a cada trecho.

---

## 16. Voz — Documento para Audiolivro

**Onde:** aba Voz → sub-aba "Documento → Audiolivro (Kokoro)".

1. Suba um PDF, DOCX, PPTX, TXT ou MD.
2. A Phoenix narra o documento inteiro, gerando um único arquivo MP3/WAV.
3. Se o documento tiver trechos em idiomas diferentes, a voz troca automaticamente por frase, conforme
   o idioma muda.

---

## 17. Transcrever um áudio

**Onde:** aba Chat → ícone de clipe → selecione um arquivo de áudio (`.mp3`, `.wav`, `.m4a`, `.ogg`,
`.flac`, `.webm`) → peça a transcrição.

Exemplo: `Transcreva este áudio.` A Phoenix usa Whisper para gerar a transcrição real. Se você pedir
uma transcrição sem anexar nenhum áudio na mensagem, a Phoenix avisa que precisa do arquivo, em vez de
inventar um resultado.

---

## 18. Busca web integrada

**Onde:** aba Chat, começando a mensagem com um verbo de busca explícito.

Exemplos:
- `pesquisar as tendências de inteligência artificial em 2026`
- `busca o preço médio de uma placa de vídeo RX 580 usada`

A Phoenix consulta o SearXNG (motor de busca privado, local) antes de responder, mostra os resultados
na tela e usa esse contexto para formular uma resposta atualizada.

---

## 19. Arena — colaboração entre dois modelos

**Onde:** aba **Arena**.

1. Selecione dois modelos (por exemplo, um rodando em CPU e outro em GPU).
2. Descreva a tarefa — por exemplo, `Escrevam uma função Python que valida CPF, revisando a solução um
   do outro`.
3. Os dois modelos debatem e revisam a proposta em rodadas, com progresso aparecendo em tempo real.
4. Um verificador automático roda o código proposto de verdade (isolado, com timeout de segurança)
   antes de aceitar a tarefa como concluída — a Arena não aceita simplesmente a opinião de um modelo
   sobre o outro.
5. Use o botão **"Enviar resultado pro chat"** para levar a conclusão da Arena pro chat principal, já
   com o veredito real (confirmado ou não) incluído.

---

## 20. Calculadora de VRAM

**Onde:** aba **VRAM**.

Ferramenta pra estimar quanta memória de vídeo um modelo específico vai consumir antes de você baixá-lo
ou carregá-lo — útil pra planejar o que cabe na sua GPU sem precisar testar por tentativa e erro.

---

## 21. Model Hub — benchmark e modelos instalados

**Onde:** aba **Hub**.

- Veja todos os modelos instalados, organizados por categoria (chat, imagem, voz, visão).
- Rode um **benchmark** de tokens por segundo num modelo específico, para comparar desempenho real no
  seu hardware.
- Modelos que demorarem demais têm um teto de segurança (a Phoenix devolve um erro controlado em vez
  de travar indefinidamente).

---

## 22. Mission Control — dashboard de hardware

**Onde:** `localhost:8000` (aba "dashboard" dentro do Mission Control).

Painel com o estado do seu hardware em tempo real: uso de CPU, GPU, memória, temperatura, containers
ativos. É a central de monitoramento do sistema, atualizada continuamente.

Outras abas do Mission Control:
- **Ports:** status das portas/serviços da Phoenix (SearXNG, Ollama, etc.).
- **Vulkan:** informações da camada gráfica usada pela GPU.
- **RAG:** o mesmo painel de Base de Conhecimento descrito na seção 8, acessível também por aqui.

---

## 23. Missões autônomas e aprovação de ações

**Onde:** aba **Swarm** do Mission Control.

Aqui você pode instruir agentes autônomos da Phoenix a executar tarefas mais longas ou de sistema —
por exemplo, `Execute um benchmark de memória Vulkan na porta 8000`.

Regra de segurança: qualquer ação classificada como risco médio ou alto (instalar algo, mudar
configuração de sistema, etc.) **fica pendente até você aprovar explicitamente** — nada é executado
sozinho. Ações simples e reversíveis (como gerar uma imagem direto no chat) não passam por esse fluxo
de aprovação, porque já são iniciadas por você em tempo real.

---

## 24. App Store — missões prontas

**Onde:** aba **App Store**, dentro da Aviary.

Em vez de configurar tudo manualmente, você pode instalar um "pacote" pronto para um objetivo
específico:

| Missão | O que instala |
|---|---|
| 🧠 Assistente Pessoal | LLM + RAG para estudos e produtividade |
| 💬 Conversar com IA | Stack completa de chat local |
| 🖥️ Modo CPU Only | Para máquinas sem GPU dedicada |
| 💻 Ambiente Dev | Ferramentas de programação + IA |
| 🎨 Criar Imagens | Geração de imagens + workflows |
| 🔍 Pesquisa Inteligente | Busca privada + RAG local |
| 🎙️ Studio de Voz Offline | STT, TTS e clonagem de voz |
| 🚀 Plataforma Completa | Tudo que o hardware suportar |
| ⚡ RX 580 Revival | Otimizado pra GPUs AMD Polaris/GCN4 |

Clique em "Instalar" na missão desejada e acompanhe o progresso — pode ser cancelado a qualquer
momento sem deixar o sistema em estado inconsistente.

---

## 25. Planos Free x Pro

| Recurso | Free | Pro |
|---|---:|---:|
| Documentos no RAG | 10 | Sem limite |
| Upload máximo por arquivo | 25 MB | 100 MB |
| Texto extraído por documento | 500.000 caracteres | 5.000.000 caracteres |

O plano Pro exige uma licença assinada digitalmente. Sem uma licença válida, a Phoenix opera como Free
automaticamente — nunca trava nem exige cadastro pra uso básico.

> Se você cancelar ou rebaixar uma licença Pro, o acesso Pro pode continuar ativo até a expiração do
> token assinado, mesmo offline — é uma escolha de design para manter a Phoenix funcional sem
> depender de internet o tempo todo.

A verificação da licença é feita por assinatura criptográfica: a Phoenix só guarda localmente a chave
**pública** usada para conferir se um token é válido. A chave **privada** que assina os tokens nunca
sai da infraestrutura da AIVisionsLab — não existe, em nenhuma cópia da Phoenix distribuída a
clientes, nenhum arquivo capaz de gerar uma licença Pro válida.

---

## 26. Privacidade e segurança — resumo prático

- Por padrão, **tudo roda local** — nada é enviado à AIVisionsLab.
- Documentos do RAG **nunca vão para um provedor de nuvem**, a menos que você desligue essa proteção
  manualmente (seção 9).
- Se você escolher conversar com o Gemini, o texto da sua mensagem (não o conteúdo do RAG, por padrão)
  vai para os servidores do Google, sob a política de privacidade deles.
- Telemetria remota (uso agregado de hardware) é **opt-in** — desligada por padrão.
- Ações de sistema de risco médio/alto sempre pedem sua aprovação explícita antes de executar.
- A verificação de licença Pro (seção 25) usa assinatura Ed25519; só a chave pública de verificação
  circula com o cliente, nunca a chave privada de emissão.

---

## 27. Solução de problemas comuns

**O modelo Gemini não aparece no seletor.**
Confirme que configurou `GEMINI_API_KEY` no `.env` (seção 5) e reiniciou o servidor da Aviary depois.

**Um provedor local aparece mas não consigo selecioná-lo.**
Ele precisa estar com status `connected` — use o botão de teste de conexão na aba Stack (seção 7).

**Erro ao pedir para transcrever um áudio.**
Confirme que você anexou o arquivo de áudio na própria mensagem — a Phoenix não reaproveita um áudio
de mensagens anteriores.

**Upload de documento no RAG recusado por limite.**
Você atingiu o limite do seu plano (10 documentos no Free). Apague um documento existente ou use um
plano com mais capacidade.

**Quero ligar a proteção de RAG de volta depois de ter desligado.**
Vá em Parâmetros do chat (seção 6) e marque novamente "Bloquear RAG em provedores de nuvem".

**Tarefa com documentos grandes (ex: preencher planilha/catálogo a partir de outro documento, seção 14)
demorando muito.**
Por padrão, o motor de texto local (llama.cpp) roda 100% em CPU — em hardware com GPU disponível e
ociosa (confirme na aba VRAM/Mission Control, seção 20/22, se a sua tem folga de memória de vídeo), dá
pra acelerar bastante ligando GPU e CPU trabalhando juntas (offload parcial de camadas do modelo pra
GPU). Pra isso:

1. Feche a Phoenix se ela já estiver rodando.
2. Abra um PowerShell **novo** e rode, nessa ordem, **no mesmo terminal** (ajuste o caminho pro seu
   projeto se for diferente):
   ```powershell
   $env:PHOENIX_LLM_NGL = "20"
   cd "C:\PHOENIX 3.0" (caminho real no seu disco)
   .\Iniciar_Phoenix.bat
   ```
3. Pra confirmar que pegou, rode num terminal separado (com a Phoenix já de pé):
   ```powershell
   (Get-CimInstance Win32_Process -Filter "Name='llama-server.exe'").CommandLine
   ```
   Se aparecer `-ngl 20` (em vez de `-ngl 0`) no final da linha, funcionou.

O número (`20` no exemplo) é quantas camadas do modelo vão pra GPU — o resto continua na CPU
automaticamente, então isso já É o "CPU e GPU juntas", não uma escolha entre uma coisa ou outra. Comece
com um valor conservador e vá subindo enquanto sobrar memória de vídeo livre (acompanhe pelo Gerenciador
de Tarefas do Windows, aba Desempenho → GPU, durante uma tarefa real) — um valor alto demais pra sua
placa pode travar ou fazer o carregamento do modelo falhar. Essa variável vale pra toda a sessão da
Phoenix (chat normal incluído), não só pra preenchimento de planilha; pra não precisar setar toda vez
que abrir um terminal novo, crie `PHOENIX_LLM_NGL` como variável de ambiente permanente do Windows
(Painel de Controle → Sistema → Configurações avançadas do sistema → Variáveis de Ambiente).

**Atualização (28/08/2026): preenchimento de planilha agora processa o documento-fonte inteiro.**
Antes, um documento-fonte grande (seção 14) era cortado num limite fixo de caracteres antes de chegar
ao modelo — o restante era descartado em silêncio, sem aviso nenhum, então uma planilha "preenchida com
sucesso" podia na prática ter capturado só uma fração pequena dos itens do documento. Isso foi
corrigido: o documento inteiro agora é dividido em pedaços de ~22 mil caracteres (calculado contra o
contexto real de 16384 tokens do llama-server), cada pedaço é processado pelo mesmo modelo, e as linhas
de todos os pedaços são juntadas no final. Como uma conversa longa costuma repetir o mesmo produto
várias vezes ao longo de revisões, também há deduplicação: quando dois pedaços descrevem o mesmo item
(mesmo código de barras, ou mesmo nome numa coluna tipo "Descrição"/"Nome"), fica a versão mais tardia
(a revisão mais recente). Há um teto de segurança de 60 pedaços (~1,3 milhão de caracteres) para evitar
que um documento patologicamente grande gere chamadas sem fim ao modelo — se um documento ultrapassar
esse teto, isso agora aparece de forma explícita na resposta, em vez de ser cortado sem aviso como
antes. A resposta da API também passou a informar sempre quantos pedaços existiam e quantos foram
processados com sucesso, para que "sucesso" nunca mais pareça igual entre capturar poucos itens e
capturar o documento inteiro. Documentos que cabem num pedaço só (a maioria dos casos do dia a dia)
continuam se comportando exatamente como antes — só documentos realmente grandes usam esse novo
caminho, e por isso podem demorar bem mais (múltiplos minutos por pedaço, multiplicado pelo número de
pedaços) — vale a pena deixar rodar até o fim.
