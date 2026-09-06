# Troubleshooting — AIVisions Phoenix Engine

**Dashboard não sobe em `localhost:8000`**
Confirme que `api_server.py` está rodando e que a porta não está em uso.

**"Sistema operacional não suportado" logo no início, no Windows**
Sintoma de o upgrade automático pro PowerShell 7 não ter completado (ex.: winget do PS7 falhou silenciosamente). O `install_phoenix.ps1` atual já trata esse caso — se ainda estiver no PS 5.1 depois da tentativa, segue em modo degradado em vez de travar. Se persistir: `winget install Microsoft.PowerShell` e rode `pwsh ./install_phoenix.ps1` direto.

**GPU não aparece no System Tuner (Windows)**
O processo precisa ser executado como Administrador — sensores de GPU via LibreHardwareMonitor exigem elevação. Rode `Iniciar_Phoenix.bat` como Admin. Se a instalação do LibreHardwareMonitor falhar, o instalador para com erro (componente primordial, não apenas aviso).

**GPU não aparece no System Tuner (Linux)**
Confirme que o driver Mesa RADV está instalado: `vulkaninfo --summary`. Para temperatura, verifique se `lm-sensors` está configurado: `sensors`.

**`ModuleNotFoundError: No module named 'phoenix_kernel.logs'` (ou qualquer outro submódulo)**
Confirme se essa pasta não está sendo capturada por engano pelo `.gitignore`. Um padrão como `logs/` (sem `/` na frente) ignora qualquer pasta chamada `logs` no repositório inteiro — inclusive `phoenix_kernel/logs/`. Rode `git check-ignore -v phoenix_kernel/logs/engine.py` para confirmar, e ancore o padrão com `/logs/` no `.gitignore` se for o caso.

**RAG mostrando 0 documentos**
O arquivo `data/knowledge_base.json` precisa existir. O índice vetorial (`data/chroma_db/`) é gerado localmente a partir dele e não vem no clone.

**Ícone de Desktop não aparece (Linux)**
O instalador roda como root via `sudo`, então precisa resolver o usuário real via `$SUDO_USER` — se você rodou como root "de verdade" (não via sudo), o instalador usa `$HOME` atual e avisa no log. Confirme rodando `sudo pwsh ./install_phoenix.ps1` como usuário normal, não logado direto como root.

**Docker não consegue alcançar llama-server ou sd-server**
Windows Defender bloqueia a subnet Docker (172.x.x.x) por padrão. O instalador já libera as portas oficiais da Phoenix automaticamente; se precisar liberar manualmente:

```powershell
New-NetFirewallRule -DisplayName "Phoenix AI Services" `
  -Direction Inbound -Protocol TCP -LocalPort 8081,7860 -Action Allow
```

**Geração de imagem falha com "violação de acesso" / `0xC0000005`**
Isso acontecia com o modelo **Flux**, que foi removido da distribuição por
crashar o processo nativo Vulkan na RX 580 em todos os placements. Use **SDXL**
(default) ou **SD 1.5** — ambos rodam sem crash nesse hardware. Se você tem um
projeto antigo apontando para Flux, troque o modelo de imagem no seletor.

**Preencher planilha demora muito / parece travar**
O caminho determinístico (`POST /api/documents/pipeline-fill`, usado pela
interface) preenche um catálogo de centenas de produtos em **segundos**. Se
estiver lento, confirme que está na versão com a auditoria de setembro/2026
aplicada — a versão antiga usava o LLM chunk a chunk e podia passar de 90
minutos. Ver [DOCUMENT_PIPELINE.md](./DOCUMENT_PIPELINE.md).

**Planilha preenchida sai "vazia" (sem nome de produto)**
O nome do produto vai para a coluna **Descrição**. Se o seu documento nomeia
produtos por título numerado ("63. Produto X"), a versão atual já reconhece
isso. Se ainda vier vazio, o formato de nome do seu documento pode ser
diferente — os campos que não existem no documento (ex.: NCM/CEST de bebidas)
ficam vazios de propósito (guarda-fiscal não inventa dado fiscal).

**Detecção de modelos "some" ao reiniciar de outra pasta**
Corrigido na auditoria de setembro/2026 — os resolvedores de storage agora usam
caminho absoluto (raiz do projeto), não o diretório de onde a Phoenix foi
iniciada. Se persistir numa versão antiga, sempre inicie a Phoenix a partir da
raiz do projeto.

**Texto→áudio trava com texto longo digitado**
Corrigido — o texto livre agora usa o mesmo particionamento do audiolivro
(quebra em blocos). Se travar numa versão antiga, gere o áudio a partir de um
arquivo em vez de texto colado.

**Resposta do modelo vem cortada ou incompleta, sem nenhum erro na tela**
Duas causas possíveis, dependendo do provedor (ver
[INVESTIGACAO_RESPOSTA_CORTADA.md](./INVESTIGACAO_RESPOSTA_CORTADA.md) para
o diagnóstico completo):
- **Modelo local** (Qwen3 e outros "thinking models"): o raciocínio interno
  (`<think>...</think>`) pode vir misturado com a resposta se a geração for
  cortada enquanto o modelo ainda está "pensando". Corrigido com `--jinja`
  explícito na inicialização do `llama-server` + leitura do campo
  `reasoning_content` separado.
- **Gemini**: modelos 2.5+/3.x pensam por padrão, e o raciocínio consome o
  mesmo orçamento de tokens da resposta visível — sem configurar
  `thinkingConfig`, o raciocínio pode comer o orçamento inteiro. Corrigido
  com `thinkingConfig` explícito + reserva de tokens extra só pro
  raciocínio.
- Separadamente, se a resposta for cortada **com um erro de timeout visível**
  numa conversa longa, isso é o contexto do `llama-server` (`-c`, atualmente
  32768) esgotando — cada mensagem reenvia a conversa inteira, então uma
  conversa longa o suficiente sempre volta a esbarrar nesse teto.

## Onde buscar mais ajuda

Consulte os logs locais da Phoenix (comando `logs` no Terminal Deck) e, se necessário, abra uma issue no [repositório oficial](https://github.com/aivisionslab-studios/phoenix-engine) com os detalhes do ambiente (SO, hardware, versão da Phoenix).
