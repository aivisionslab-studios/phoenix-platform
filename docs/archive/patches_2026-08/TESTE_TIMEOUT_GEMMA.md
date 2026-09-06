# Phoenix V5 — Timeout adaptativo para documentos

Corrige três tetos que precisavam ficar alinhados:

- llama.cpp HTTP: 600s normal; 1140s documento >=2048 tokens; 1740s modelo >=12B + documento longo.
- ResidentManager CREATE: 1200s modelos menores; 1800s modelos >=12B.
- Aviary/Node proxy: 1860s (31min), permitindo o Engine devolver primeiro um erro controlado.

O timeout de leitura/edição existente permanece inalterado.

Teste principal:

Pesquise na web os principais modelos de IA local disponíveis em 2026 e produza um relatório técnico comparativo. Diferencie claramente modelos de linguagem, runtimes e interfaces. Não invente dados ausentes. Cite as fontes consultadas. Inclua introdução, tabela comparativa, requisitos de hardware, vantagens, limitações e conclusão. Criar PDF.
