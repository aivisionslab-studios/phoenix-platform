# Investigação: "resposta do modelo fica cortada" — duas causas, um desvio de raciocínio no meio

**Data:** 06/09/2026
**Escopo:** investigação completa do sintoma "qualquer resposta do modelo na Phoenix fica cortada após alguns caracteres", do primeiro relato até a causa raiz real.
**Metodologia:** Errata Evolutiva (mesmo espírito do `CHANGELOG.md` e do `RECUPERACAO_FUNCIONALIDADES_PHOENIX.md`) — inclusive o **desvio de raciocínio no meio da investigação**, porque a correção do usuário e o motivo dela são dados tão importantes quanto a causa raiz final. Nada aqui foi silenciosamente reescrito para parecer que acertamos de primeira.

---

## Linha do tempo (o raciocínio completo, não só o resultado)

### 1. Pedido original

> "qualquer resposta do modelo na phoenix fica cortada após alguns caracteres. aumentar contexto de caracteres ou deixar livre pra modelo ter liberdade de escrita"

### 2. Primeira hipótese (que acabou sendo sobre OUTRO problema)

A investigação inicial mapeou candidatos: `max_tokens` na geração, corte no proxy Node, truncamento de exibição no front-end. Achado real no caminho:

- `max_tokens` tinha default de **1024** em `llama_cpp.py` para qualquer chamada, a menos que `unlimited_output=True` fosse passado — já corrigido pra criação de documentos (30/08), nunca pro chat comum.
- O front-end (`AviaryApp.tsx`) já mandava `maxTokens: 4096` por padrão — não parecia ser o culpado direto.
- O tamanho de contexto do `llama-server` (`-c`) estava em **16384** — e havia um comentário no código descrevendo **literalmente o mesmo sintoma relatado agora**, já resolvido uma vez em 24/08 (8192→16384) para o mesmo tipo de queixa.
- Achado adicional: **não existe corte de histórico de conversa em lugar nenhum do projeto** — cada mensagem reenvia a conversa inteira (`sendToProvider()`). Uma conversa longa o suficiente sempre volta a esbarrar no teto de contexto, não importa o quão alto.

Com base nisso, foram implementadas duas mudanças:
- Contexto do `llama-server` aumentado de 16384 para **32768** (a pedido explícito do usuário, depois de confirmar o trade-off de RAM — a máquina tem 32GB).
- Checkbox "Sem limite" adicionado ao painel de parâmetros do chat, replicando o `unlimited_output` que a criação de documentos já tinha.

Essas mudanças foram implementadas, testadas (**731 passed** no Python + testes de integração real em Node/TypeScript) e entregues.

### 3. A correção do usuário — o ponto de virada

> "Esse contexto estava alto porque LLM demorou muito tempo pra responder e estourou timeout. Era outra demanda"

Isso identificou corretamente que a rodada de 24/08 (8192→16384) resolvia um problema **diferente**: um erro de **timeout de rede** (`Headers Timeout Error`, conexão derrubada enquanto o modelo ainda gerava) — um problema que **dá erro visível**. A queixa atual ("resposta cortada, sem erro nenhum") não tinha necessariamente a mesma causa, mesmo que os dois sintomas envolvessem "resposta grande" superficialmente.

**Isso é uma correção que vale registrar por si só:** duas mudanças (contexto 32768 + checkbox "sem limite") continuaram sendo boas melhorias, mas **não eram a explicação completa** do sintoma relatado. O passo certo, a essa altura, foi **parar de inferir e perguntar o sintoma exato** em vez de continuar ajustando números.

### 4. Perguntas de diagnóstico (em vez de mais suposição)

Três perguntas fecharam o espaço de causas possíveis:

| Pergunta | Resposta | O que isso descarta / aponta |
|---|---|---|
| Corta no meio da frase, ou termina "normal" mas curta? | **As duas coisas, em contextos diferentes** | Duas causas técnicas diferentes coexistindo, não uma só |
| Acontece com qual provedor? | **Os dois** (local e Gemini) | Descarta qualquer causa específica do `llama-server` sozinho — precisa ser algo ou compartilhado, ou duplicado em cada provedor |
| Aparece erro na tela? | **Não, nenhum** | Descarta timeout de rede, descarta qualquer exceção não tratada — o "término" é limpo do ponto de vista de rede/HTTP |

A combinação "acontece nos dois provedores" + "sem erro nenhum" foi o que direcionou a investigação pra longe de contexto/timeout (mecanismos específicos do `llama-server`) e pra um problema **conceitualmente compartilhado**, ainda que tecnicamente diferente em cada provedor.

---

## Causa raiz real — parte 1: modelos locais (Qwen3 e outros "thinking models")

**Antes:** modelos como Qwen3 geram um bloco de raciocínio interno (`<think>...</think>`) antes da resposta final. `_build_server_args()` (em `llama_cpp.py`) não passava `--jinja` explicitamente na inicialização do `llama-server` — a separação entre "pensamento" e "resposta" ficava a critério do padrão da build instalada.

**Causa raiz:** quando a separação falha (build sem `--jinja` ativo por padrão, ou template não reconhecido), a tag `<think>` vem **embutida no mesmo campo de texto** da resposta. O front-end (`AviaryApp.tsx`) tentava limpar isso com:

```js
const thinkMatch = responseText.match(/<think>([\s\S]*?)<\/think>/i);
if (thinkMatch) { /* remove o bloco */ }
```

Esse regex **exige que a tag abra E feche**. Se a geração for cortada (por qualquer limite — tokens, tempo, o que for) **enquanto o modelo ainda está "pensando"**, a tag `<think>` nunca fecha. O regex não encontra nada pra remover, e:
- Ou o texto bruto do raciocínio incompleto vaza pra tela (sintoma: **"corta no meio"**, já que o raciocínio em si estava incompleto);
- Ou, quando o raciocínio consome a maior parte do orçamento disponível antes de fechar corretamente, a resposta visível que sobra é genuinamente curta (sintoma: **"termina normal mas é curta"**).

**Confirmado com fonte oficial:** issue #14894 do próprio repositório `ggml-org/llama.cpp` — "`llama-server --jinja` removerá as tags de pensamento e o conteúdo dentro delas" (comportamento correto, condicionado a `--jinja` estar ativo).

**Corrigido:**
1. `--jinja` adicionado explicitamente em `_build_server_args()` — nunca mais depende do padrão da build.
2. `server.ts` passou a **ler o campo `reasoning_content`** que o `llama-server` devolve separadamente quando a separação funciona (`data.choices[0].message.reasoning_content`), repassando como um campo `reasoning` próprio na resposta pro front-end — em vez de forçar o front-end a re-separar um blob de texto único.
3. `AviaryApp.tsx` (os dois caminhos de chat: conversa normal e Arena de comparação) passou a **priorizar esse campo `reasoning`** quando presente. O regex antigo continua existindo como rede de segurança para quando o servidor não faz a separação — mas agora com um terceiro caso tratado: **tag `<think>` sem fechamento correspondente** vira "pensamento incompleto" (nunca mostrado como resposta), preservando como resposta visível só o que veio *antes* da tag.

**Validado:** `test_reasoning_truncation_fix.mjs` (13 testes, incluindo simulação exata do caso "tag sem fechar" que motivou a investigação) + suíte Python completa (**731 passed, 2 skipped**).

---

## Causa raiz real — parte 2: Gemini (mecanismo diferente, mesmo sintoma)

**Antes:** a requisição pro Gemini não configurava nada relacionado a raciocínio (`config` não tinha `thinkingConfig`).

**Causa raiz:** modelos Gemini 2.5+/3.x vêm com "pensamento" **ligado por padrão** quando nenhum `thinkingConfig` é enviado — e os tokens de raciocínio contam contra o **mesmo** `maxOutputTokens` da resposta visível. Isso é documentado oficialmente pelo Google e foi reproduzido de forma idêntica por múltiplos outros projetos (ex.: issue #609 do `ha-llmvision`, issue #782 do `python-genai`): com um `maxOutputTokens` "razoável", o raciocínio pode consumir o orçamento inteiro sozinho, terminando a chamada com `finishReason: MAX_TOKENS` e **texto de resposta vazio ou cortado — sem nenhum erro**, porque do ponto de vista da API a chamada terminou normalmente.

Isso explica por que o sintoma "sem erro nenhum" acontecia **nos dois provedores**, apesar de ser, tecnicamente, dois bugs completamente diferentes — um de parsing de texto (local), outro de orçamento de token genuinamente compartilhado (Gemini).

**Corrigido:**
1. `thinkingConfig: { includeThoughts: true }` adicionado explicitamente à requisição — nunca mais deixa a critério do padrão do Google.
2. Quando o usuário define um `maxTokens` específico, o valor enviado como `maxOutputTokens` pro Gemini passou a ser `maxTokens + 4096` (constante `GEMINI_THINKING_BUDGET_RESERVE`) — uma reserva de folga só pro raciocínio, **sem tirar espaço** do que o usuário pediu pra resposta visível. Com "Sem limite" (`maxTokens === 0`), `maxOutputTokens` não é definido de jeito nenhum.
3. `server.ts` extrai os "thought parts" da resposta (`candidates[0].content.parts` filtrando `part.thought === true`) e repassa como o mesmo campo `reasoning` usado no caminho do `llama-server` — dando ao front-end uma interface consistente entre os dois provedores.

**Validado:** mesmo arquivo `test_reasoning_truncation_fix.mjs`, seção dedicada ao Gemini (4 checagens: `thinkingConfig` presente, reserva de orçamento presente, extração de `thought parts`, campo `reasoning` na resposta).

---

## O que fica registrado como decisão, não como bug

- **Contexto 32768 e o checkbox "Sem limite"** continuam válidos e entregues — não foram revertidos. Eles resolvem um problema real (timeout de rede em conversas longas / teto artificial de tokens de saída), só que **não eram, sozinhos, a explicação completa** do sintoma "corta sem erro nos dois provedores".
- **Corte de histórico de conversa** — identificado como ausente, e como o próximo passo mais robusto se o sintoma de contexto (não o de raciocínio) voltar a acontecer no futuro. Não implementado nesta rodada; registrado para referência.
- **`_SPREADSHEET_FILL_CHUNK_CHAR_BUDGET`** (orçamento de caracteres por pedaço no preenchimento de planilha) foi deliberadamente **não recalibrado** junto com o aumento de contexto — é uma funcionalidade já testada extensivamente à parte, e mudar esse número exigiria testes dedicados próprios.

## Arquivos alterados nesta investigação

    phoenix_kernel/runtime/drivers/llama_cpp.py      (context_size=32768, --jinja explícito)
    phoenix_kernel/resident/resident_manager.py       (comentários atualizados, orçamento de chunk deliberadamente não recalibrado)
    platform_source/server.ts                         (checkbox "sem limite", timeout em cadeia recalibrado, reasoning_content do llama-server, thinkingConfig + extração de thoughts do Gemini)
    platform_source/src/components/aviary/AviaryApp.tsx (prioriza campo `reasoning`, fallback do regex corrigido pra tag sem fechamento)
    platform_source/src/components/aviary/ParametersDrawer.tsx (slider até 32768, checkbox "Sem limite")
    platform_source/src/components/aviary/VramCalculatorView.tsx (default cosmético)
    TESTS/test_llama_server_context_size.py           (reescrito, mantendo a narrativa histórica 8192→16384→32768)
    TESTS/test_llama_cpp_launch_policy.py             (asserção de contexto atualizada)
    platform_source/test_chat_headers_timeout.mjs     (fórmula de timeout atualizada pro novo teto e pro caso "sem limite")
    platform_source/test_reasoning_truncation_fix.mjs (novo — 13 testes dedicados a esta investigação)

## Validação final

- Suíte Python: **731 passed, 2 skipped**.
- `test_reasoning_truncation_fix.mjs`: **13 passed, 0 failed**.
- `test_chat_headers_timeout.mjs`: **16 passed, 0 failed** (inclui integração real: servidor de verdade, backend lento simulado, controle negativo).
- `test_rag_context_reaches_local_providers.mjs` e `test_image_intent_double_meaning.mjs`: sem regressão (13/13 e 14/14).
