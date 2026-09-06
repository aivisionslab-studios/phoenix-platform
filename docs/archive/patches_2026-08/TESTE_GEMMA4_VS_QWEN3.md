# Phoenix — Gemma 4 12B vs Qwen3 8B

## Download automático
No Model Hub, baixe:
**Gemma 4 12B IT QAT Q4_0 — 6.98 GB**

A Phoenix usa o downloader já existente:
POST /api/models/download
key: gemma4-12b-qat-q4_0

Destino:
Models/Chat/GGUF via PhoenixPaths.

## Comparativo lado a lado
Depois do download:
1. Clique em **Detectar Locais**.
2. Abra **Model Arena**.
3. Slot 1: `qwen3-8b-q4_k_m.gguf`.
4. Slot 2: `gemma-4-12b-it-qat-q4_0.gguf`.
5. Envie exatamente o mesmo prompt.

### Prompt de teste
Pesquise na web os principais modelos de IA local disponíveis em 2026 e produza
um relatório técnico comparativo. Diferencie claramente modelos de linguagem,
runtimes e interfaces. Não invente dados ausentes. Cite as fontes consultadas.
Inclua introdução, tabela comparativa, requisitos de hardware, vantagens,
limitações e conclusão.

### Compare
- qualidade factual;
- organização;
- aderência às fontes;
- completude;
- alucinações;
- tempo total;
- tokens/s;
- total de tokens.

## Nota de hardware
Gemma 4 12B Q4_0 tem ~6.98 GB apenas em pesos. Não considerar isso como
"cabe com folga" em 8 GB de VRAM: KV cache, buffers e reserva do sistema também
consomem memória. A Phoenix deve manter sua política conservadora.
