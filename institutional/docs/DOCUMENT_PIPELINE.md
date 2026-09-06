# Pipeline de Documentos e Planilhas — AIVisions Phoenix Engine

A Phoenix lê documentos (PDF, DOCX, PPTX, TXT, MD, XLSX) e produz planilhas
preenchidas de forma **determinística** — sem depender do LLM para colar cada
dado na célula. O LLM entra só onde há julgamento de verdade (conflitos), e
nada fiscal ou de código de barras é inventado. Esta página descreve as quatro
peças que compõem esse sistema.

## Visão geral do fluxo

```
Documento-fonte ──► Pipeline V2 (determinístico) ──► Planilha preenchida
                    ├─ parser / candidate engine       + aba _PHOENIX_AUDIT
                    ├─ record segmenter                  (decisões duvidosas)
                    ├─ identity engine (dedupe)
                    └─ output writer (Fase 10)
                          │
                          ├─► Smart Filler   (regras + geração + guarda-fiscal)
                          ├─► Fiscal RAG      (sugere NCM/CEST de base auditada)
                          ├─► Barcode Finder  (pesquisa EAN + auditoria humana)
                          └─► LLM Reviewer    (resolve só os conflitos)
```

Tudo é **CPU-bound e rápido**: no hardware de referência (Xeon E5-2690 v3), um
catálogo real de ~300 produtos é preenchido em **segundos**. O caminho antigo
por LLM (mantido só para pesquisa web) chegava a passar de 90 minutos.

## 1. Pipeline determinístico (Document Pipeline V2)

Encadeia parser → candidate engine → record segmenter → identity engine →
output writer. Casa cada dado na coluna certa por **igualdade de cabeçalho**,
nunca por aproximação. Deduplica registros, preserva fórmulas/formatação/abas
do template, nunca sobrescreve o original, e registra na aba `_PHOENIX_AUDIT`
cada campo que ficou em conflito ou inválido — em vez de escolher errado em
silêncio.

Detalhes importantes:
- **Nome de produto por título numerado**: catálogos que nomeiam produtos como
  "63. Cachaça São Francisco 970ml" (em vez de um rótulo "Nome do Produto:")
  são reconhecidos — o nome vai para a coluna Descrição.
- **Filtro de linhas fantasma**: trechos de meta-conversa sem produto real não
  viram linha na planilha; só entra o registro com nome ou algum campo real.

Rota: `POST /api/documents/pipeline-fill` (determinística, timeout curto).
Ver `phoenix_kernel/documents/pipeline_orchestrator.py`.

## 2. Smart Filler — raciocínio de preenchimento

Depois da extração, completa os campos vazios em três camadas:
- **Derivação (regra)**: valor dedutível de outro campo, padrão sequencial ou
  dominante — Origem→NACIONAL, Categoria PDV←Categoria na Loja Virtual, Código
  Interno→próximo da série. Nunca inventa, só propaga o que já é verdade.
- **Geração por categoria**: Tags, Especificações, Itens Inclusos, Modelo,
  construídos do nome + categoria + atributos (marca, tamanho, dimensões).
- **Guarda-fiscal**: NCM/CFOP/CEST NUNCA recebem chute (errar gera imposto
  errado; um CEST vazio pode ser correto). Produtos sem nome real não são
  categorizados. Esses casos viram pendência, nunca valor inventado.

Ver `phoenix_kernel/documents/smart_filler.py`.

## 3. Fiscal RAG — NCM/CEST consultável

Base construída a partir dos produtos que a empresa **já classificou
corretamente**. Para um produto novo, recupera o código fiscal de produtos
semelhantes já auditados — é recuperação, não invenção. Cada sugestão vem com a
descrição de origem e um score; consenso entre várias referências reforça a
confiança; formato inválido nunca entra na base. Toda sugestão sai como
`suggested` (nunca `confirmed`): continua indo para auditoria humana.

Ver `phoenix_kernel/documents/fiscal_rag.py`.

## 4. Barcode Finder — EAN com auditoria humana

Código de barras errado quebra o PDV, então este fluxo é **assistido**: pesquisa
na web pelo nome do produto, extrai candidatos de 13 dígitos, **valida o dígito
verificador EAN-13** (filtra números-lixo), e monta uma fila de conferência com
nome + tipo do produto + candidatos + fontes. **Nada é aplicado sem aprovação
humana** — mesmo um único candidato válido entra como `pending_review`.

Ver `phoenix_kernel/documents/barcode_finder.py`.

## 5. LLM Reviewer — só os conflitos

Quando o pipeline marca um campo como `conflict` (dois valores válidos
competindo), o LLM entra como revisor sênior — mas só nesses poucos casos, com
uma **allowlist fechada**: escolhe entre os valores que o pipeline achou, nunca
inventa. Resposta fora da lista é rejeitada e o campo segue para auditoria.

Ver `phoenix_kernel/documents/llm_reviewer.py`.

## Garantias de projeto

- Determinístico: mesma entrada, mesma saída.
- Preserva o template (fórmulas, formatação, outras abas); nunca sobrescreve o
  original.
- Nunca inventa dado fiscal ou de EAN — tudo sensível passa por sugestão +
  auditoria.
- Trilha de auditoria (`_PHOENIX_AUDIT`) com cada decisão duvidosa.
