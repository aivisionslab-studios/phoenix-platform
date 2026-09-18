# Phoenix Forge 0.8.0 — Platform, Production Benchmark and Archive Integrity

## Resultado desta fase

Esta versão transforma as descobertas dos estudos de CPU-Z, GPU-Z, OCCT e Cinebench em funções próprias e auditáveis. Não copia código, drivers, marcas, recursos ou algoritmos proprietários desses programas.

### Inventário de plataforma

- CPU, fabricante, família, stepping, clocks, núcleos e processadores lógicos via CIM/OS.
- Hierarquia de cache, tamanho, linha, associatividade e compartilhamento quando o provedor expõe esses campos.
- DIMMs, capacidade, velocidade configurada, largura e dados SMBIOS disponíveis.
- Limitação explícita: leitura SPD bruta exige um provedor privilegiado de SMBus; a Forge não inventa SPD.

### Saúde PCIe

- Coleta eventos WHEA no Windows e os classifica em PCIe, memória e CPU/interconexão.
- `DEGRADED` significa evidência no período solicitado; `CLEAR` significa ausência de evidência nesse canal, não prova absoluta de hardware perfeito.

### Benchmark de produção

- Perfis quick, standard e deep.
- CPU, memória e cache são repetidos 2, 3 ou 5 vezes.
- Registra todas as amostras, média, pico e coeficiente de variação.
- Só publica score válido quando todos os kernels passam a verificação e a variação é de até 10%.
- Continua sob o supervisor térmico e de cancelamento introduzido na v0.7.

### Integridade de arquivos ZIP

O tamanho do ZIP não determina se ele é bom. Um ZIP de 6 KB pode estar íntegro ou quebrado; o mesmo vale para 1 GB. A Forge agora verifica:

- abertura e diretório central;
- CRC de cada membro;
- SHA-256 do arquivo completo em streaming, sem carregar 1 GB na RAM;
- nomes duplicados e tentativa de path traversal;
- tamanho descomprimido por membro e proporção de compressão suspeita;
- manifesto detalhado com tamanho, tamanho comprimido e CRC32.

### Comandos novos

```powershell
phoenix-forge system-inventory
phoenix-forge pcie-health --minutes 1440
phoenix-forge production-benchmark --profile standard
phoenix-forge archive-check .\pacote.zip
```

As mesmas funções estão disponíveis em `/api/system-inventory`, `/api/pcie-health`, `/api/benchmark/production` e `/api/archive/check`.

## Limites honestos

- WHEA não substitui os testes ativos.
- Alocações Vulkan continuam sendo janelas lógicas; Vulkan não revela o chip GDDR físico.
- O pacote-fonte não inclui executáveis ou recursos proprietários dos programas estudados.
- A validação final de VRAM e desempenho precisa ser repetida na RX 580 real e comparada com OCCT/Cinebench como controles externos.
