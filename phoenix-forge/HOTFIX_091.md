# Phoenix Forge 0.9.1 — Ledger confiável

Esta versão corrige problemas observados no teste real da RX 580 2048SP sem apagar nenhuma evidência da v0.9.0.

## O que muda

- A chave do dispositivo deixa de ser apenas `pci`. O identificador combina IDs PCI e um hash da instância PNP completa; duas GPUs idênticas em slots diferentes ficam isoladas.
- Ao primeiro carregamento, entradas antigas são reindexadas e gravadas atomicamente. `identity_history` registra a chave anterior.
- `ledger-ingest` reconhece JSON UTF-8, UTF-8 com BOM, UTF-16 LE e UTF-16 BE, incluindo a saída criada pelo Windows PowerShell.
- O hash de deduplicação passa a representar o JSON canônico. Alterar apenas a codificação não cria um segundo teste.
- `gpu-ledger` separa erro de VRAM detectado pela Phoenix, evidência externa (por exemplo OCCT), erro de setup, full-scan aprovado, compute apenas operacional e compute com correção validada.

## Interpretação da máquina testada

Um erro repetido no mesmo bit durante duas passagens da Phoenix, somado à evidência independente do OCCT, permanece latched. Um full-scan posterior aprovado e um compute aprovado demonstram que a falha é intermitente; não anulam a evidência anterior.

Por isso, LLM/OCR/visão continuam em CPU. Imagem e vídeo podem usar `GPU_MONITORED`, com validação da entrega. O Forge não declara qual chip GDDR físico falhou, porque Vulkan expõe janelas lógicas e o driver controla o mapeamento físico.

## Atualização

Execute `BUILD_WINDOWS.ps1` na raiz. O estado existente em `%LOCALAPPDATA%\Phoenix\Forge\state\gpu-safety.json` será migrado quando qualquer comando de ledger ou segurança for executado.

Para importar arquivos antigos:

```powershell
.\.venv\Scripts\phoenix-forge.exe ledger-ingest ".\resultado-vram-full.json" --device-name "AMD Radeon RX 580 2048SP"
```

Arquivos já registrados serão identificados como duplicados. Preserve uma cópia do diretório de estado antes da atualização como prática operacional.
