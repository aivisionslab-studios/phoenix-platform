# Cinebench 2026 — observações aplicadas à Phoenix Forge

## Arquitetura observada

- Aplicação modular com componentes de renderização CPU/GPU e bibliotecas de paralelismo.
- Modos de execução incluem CPU single-core, CPU multi-core, SMT, GPU e conjuntos combinados.
- Resultados mantêm amostras, médias e picos, e a duração mínima controla a janela útil do ensaio.

## Lição para benchmark real

Um único número rápido não prova capacidade sustentada. Resultado publicável precisa conter duração, repetição, dispersão, correção da saída, temperatura e razão de interrupção. Média e pico devem ser derivados das amostras preservadas, não fornecidos como números soltos.

## Aplicação própria na Forge

A v0.8 adiciona perfis repetidos para CPU, memória e cache. Cada conjunto registra amostras, média, pico e coeficiente de variação. O score só é válido se todas as execuções forem corretas e apresentarem variação máxima de 10%. A implementação não inclui cenas, engines, bibliotecas ou assets proprietários do Cinebench.

## Próxima maturação

- workloads de render próprios com checksum de imagem;
- single-thread e multi-thread separados;
- curva desempenho/temperatura/energia;
- comparação contra baseline da própria máquina;
- validação visual/OCR da saída renderizada.
