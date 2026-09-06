# Fusão auditada da Phoenix Aviary — 2026-09-02

## Decisão de integração

O pacote entregue pelo Gemini foi tratado como uma proposta de interface, não
como substituto do Phoenix Engine. Ele continha essencialmente `platform_source/`
e não incluía o runtime Python, o RAG real, o instalador ou o fork nativo de
Phoenix Diffusion. A fusão preserva o Engine 4.5 como fonte de verdade e conecta
a plataforma web às APIs reais.

## Incorporado

- Hardware Drawer e System Report como superfícies visuais.
- Rotas reais `/api/ahde/sensors`, `/api/ahde/events`,
  `/api/ahde/snapshot`, `/api/ahde/scan` e `/api/system/report`.
- Proxy explícito dessas rotas entre a Aviary (porta 3000) e o Engine
  (porta 8000), com erro HTTP real quando o Engine está indisponível.
- Histórico limitado a 100 eventos no EventBus do AHDE.
- Comandos `report`, `license`, `ports`, `vulkan`, `aviary` e `rag` no
  terminal do Engine.

## Rejeitado ou substituído

- Hardware, temperaturas, serviços, tarefas, agentes e resultados gerados
  por constantes ou `Math.random()`.
- Contagem fixa de 46 documentos RAG e embeddings declarados como 1536.
- Health score fixo em 100. Até existir cálculo real, a API retorna
  `health_score: null` e `health_status: not_calculated`.
- Resposta 200 de fallback quando o Engine está offline.
- Troca do Kokoro por nomes ou fluxos Piper; identificadores legados só
  permanecem onde são necessários para compatibilidade interna.

## Segurança e operação

- A plataforma escuta em `127.0.0.1:3000` por padrão. Para LAN, configure
  `PHOENIX_PLATFORM_HOST` conscientemente.
- CORS aceita somente localhost por padrão; origens adicionais devem ser
  declaradas em `PHOENIX_ALLOWED_ORIGINS`.
- O relatório não expõe o identificador persistente da máquina.
- Licenças MIT do Phoenix Diffusion/GGML e componentes terceiros continuam
  preservadas no pacote; `LICENSE.md` não afirma mais que não há código
  externo vendorizado.

## Limites honestos

- O HealthEngine atual ainda não calcula saúde real.
- A execução final de uma geração Vulkan numa RX 580 exige a máquina de
  destino, driver e modelo local; o pipeline/ABI pode ser validado sem isso,
  mas o resultado visual não pode ser garantido neste ambiente.
- RAG Free: até 10 documentos lógicos, 25 MB e 500.000 caracteres por
  arquivo. RAG Pro: sem limite numérico de documentos, 100 MB e 5.000.000
  de caracteres por arquivo, condicionado a capability válida.

## Correção pós-teste na máquina real

O primeiro teste com um prompt visual cru em inglês revelou uma disputa de
roteamento: o frontend reconhecia prompts em tags, mas o Execution Arbiter os
classificava como `chat`; como a decisão do árbitro é autoritativa, a requisição
seguia para o Qwen e nunca chamava `/api/generate-image`. A regra equivalente foi
movida para o árbitro. O prompt exato do teste agora retorna
`intent=image_generation`, `executor=image_pipeline` e `resource_policy=gpu`.
Perguntas sobre como gerar imagens continuam classificadas como chat.

### Segundo teste: bridge nativa ausente

O segundo teste confirmou a correção anterior: houve
`POST /api/generate-image`, portanto o prompt chegou ao pipeline de imagem.
A execução parou antes de carregar o modelo com
`Bridge Phoenix Diffusion ausente`/`Failed to start runtime 'sdxl'`. O modelo
Flux de 6,9 GB estar no disco não implica que a DLL C ABI esteja compilada.

A causa de instalação também foi localizada: `Iniciar_Phoenix.bat` considerava
a presença da `.venv` suficiente para pular o instalador. Ao extrair uma versão
nova sobre uma pasta já usada, a `.venv` antiga sobrevivia, mas o ZIP não contém
uma DLL Windows pré-compilada. Além disso, falhas no bloco de compilação da
Phoenix Diffusion não entravam nos warnings do relatório `Common`.

Correções aplicadas:

- preflight da bridge no launcher antes de iniciar a API;
- reparo automático isolado, sem apagar `.venv`, modelos ou dados;
- remoção do cache CMake específico da bridge quando ela está ausente;
- detecção dinâmica do gerador Visual Studio e do Vulkan SDK;
- promoção de `phoenix_sd_bridge.dll` para o caminho estável `bin/`;
- warnings explícitos no relatório de instalação;
- reparador manual `Reparar_Phoenix_Diffusion.bat`;
- mensagem do runtime aponta para o launcher real, não para o inexistente
  `install.ps1`.

### Terceiro teste: FTK1011 no gerador de shaders Vulkan

O log completo do reparo revelou que CMake 4.4, Visual Studio 2022 Build Tools,
MSVC 19.44 e Vulkan SDK 1.4.357 foram encontrados corretamente. A configuração
principal terminou, mas o sub-build `vulkan-shaders-gen` falhou em um teste de
link com `FileTracker : error FTK1011: could not create the new file tracking
log file`. O caminho do `.tlog` tinha 260 caracteres.

O build temporário foi movido de dentro da árvore profunda do projeto para
`%SystemDrive%\pxb\phxsd`, reduzindo o mesmo caminho representativo para cerca
de 188 caracteres. O preset CMake, o reparador e o instalador usam agora esse
diretório curto. A DLL continua sendo promovida para
`bin\phoenix_sd_bridge.dll`; modelos e dados permanecem em suas pastas normais.
As mensagens de geração/erro da interface também passaram a ser atribuídas a
`Phoenix Diffusion`, em vez de aparecerem incorretamente como resposta do Qwen.
