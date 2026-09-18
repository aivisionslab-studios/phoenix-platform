# Phoenix Forge 0.9.0 — GPU Health Ledger e Workload Trust Matrix

## O problema resolvido

Os testes reais da RX 580 2048SP produziram um `MEMORY_ERROR` com dois mismatches idênticos, seguido por dois full scans limpos. A versão 0.9 preserva essa sequência: um `PASS` posterior nunca apaga evidência histórica.

## GPU Health Ledger

O ledger agrega testes ativos, validações de saída e evidências externas por identidade da GPU. Ele distingue:

- `OBSERVED_OK_NOT_CERTIFIED`;
- `VRAM_UNSTABLE_SUSPECTED`;
- `VRAM_INTERMITTENT_SUSPECTED`;
- `GPU_COMPUTE_UNRELIABLE`;
- `AI_COMPUTE_UNSAFE`.

O armazenamento continua atômico e limitado, e cada placa mantém identidade e autorizações independentes.

## Matriz de confiança

Quando há erro de memória histórico:

| Workload | Rota automática | Validação |
| --- | --- | --- |
| LLM | CPU | Text Gate |
| Imagem | GPU monitorada | OCR + Vision Gate |
| OCR | CPU | texto de referência |
| Visão | CPU | controle CPU |
| Vídeo IA | GPU monitorada | amostragem de frames |

Uma escolha manual por GPU pode ser sobreposta por segurança nos workloads restritos. Escolhas por CPU permanecem respeitadas.

## Comandos

```powershell
phoenix-forge gpu-ledger --device-name "AMD Radeon RX 580 2048SP"
phoenix-forge route llm --device-name "AMD Radeon RX 580 2048SP" --mode AUTO
phoenix-forge route image --device-name "AMD Radeon RX 580 2048SP" --mode AUTO
phoenix-forge ledger-ingest .\resultado-vram-full.json
phoenix-forge ledger-external --device-name "AMD Radeon RX 580 2048SP" --tool OCCT --status MEMORY_ERROR --errors 1191355
```

## Correção do shader

A Forge procura `stress.spv` ao lado do helper, na pasta pai do build e no build nativo do projeto. O instalador também copia o shader para a pasta `Release`, eliminando a falha observada na v0.8 ao usar `--native` explicitamente.

## Migração da evidência v0.8

`MIGRAR_RESULTADOS_V08.ps1` importa os full scans, bandwidth, compute e a evidência externa do OCCT. Cada relatório recebe SHA-256; importar novamente o mesmo arquivo retorna `DUPLICATE_SKIPPED` e não infla a contagem histórica.

## Compute correctness

O kernel agora parte de um padrão determinístico, executa o workload Vulkan, lê o buffer de volta e recalcula na CPU 64 posições distribuídas do início ao fim da alocação. Qualquer divergência retorna `COMPUTE_MISMATCH`, registra índices de amostra defeituosos e aciona o ledger. Esta verificação amostrada complementa — e não substitui — o full scan de VRAM.
