# Phoenix Llama Runtime Stable 1.0.0

Este diretório contém um snapshot **pinado** do `ggml-org/llama.cpp` e uma camada de compatibilidade da Phoenix.

- Upstream: `https://github.com/ggml-org/llama.cpp`
- Commit congelado: `e71b80510c848c00175924ecf3c40333ccae8eb5`
- Canal: `stable`
- Atualização automática do upstream: **desativada por projeto**
- Licença do upstream: MIT (preservada no repositório)

## Objetivo

O Phoenix Llama Runtime não reescreve o ggml/llama do zero. Ele congela uma revisão conhecida e transforma a interface instável do upstream em um **contrato de execução controlado** para Phoenix Engine/Aviary.

A primeira versão mantém o núcleo upstream intacto e acrescenta:

1. versão upstream travada (`phoenix_runtime/upstream.lock.json`);
2. perfis CPU/GPU/Híbrido/Polaris/MoE;
3. resolução do device via `llama-server --list-devices`;
4. `CPU` estrito (`-ngl 0 --device none --no-op-offload`);
5. GPU usando a semântica nativa `-ngl all` em vez de `999`;
6. híbrido usando `-ngl auto` + fitter nativo;
7. perfis Polaris com correctness gate para impedir que HTTP 200 + saída corrompida seja aceito como sucesso;
8. contrato automático das flags CLI que a Phoenix depende;
9. hashes dos arquivos críticos do snapshot upstream;
10. scripts de build Vulkan para Windows/Linux.

## Perfis oficiais Phoenix

| Perfil | Política |
|---|---|
| `cpu` | `-ngl 0 --device none --no-op-offload --fit off` |
| `gpu` | `-ngl all --device <detectado> --op-offload --fit off` |
| `hybrid` | `-ngl auto --device <detectado> --fit on --fit-target 1536 --fit-ctx 8192` |
| `polaris-safe` | `-ngl 1 --device <detectado> -ot output.weight=CPU --op-offload` |
| `polaris-conservative` | `-ngl 1 --device <detectado> -ot output.weight=CPU --no-op-offload` |
| `moe-hybrid` | híbrido + `--cpu-moe` |
| `polaris-safe-nommap` | perfil de benchmark com `--load-mode none` |

`<detectado>` não é hardcoded como `Vulkan0`: o launcher pergunta ao runtime com `--list-devices` e prefere Vulkan quando disponível.

## Build Windows / Vulkan

PowerShell, a partir da raiz:

```powershell
powershell -ExecutionPolicy Bypass -File .\phoenix_runtime\scripts\build_windows_vulkan.ps1
```

O build de distribuição usa `GGML_NATIVE=OFF` por padrão para não ficar preso à CPU da máquina que compilou. Para um build local otimizado:

```powershell
.\phoenix_runtime\scripts\build_windows_vulkan.ps1 -NativeCpu
```

## Build Linux / Vulkan

```bash
./phoenix_runtime/scripts/build_linux_vulkan.sh
```

## Uso

Listar devices reais:

```powershell
py .\phoenix_runtime\phoenix_llama_runtime.py devices --server .\build-phoenix-vulkan\bin\Release\llama-server.exe
```

Ver comando sem executar:

```powershell
py .\phoenix_runtime\phoenix_llama_runtime.py command --model C:\modelos\qwen.gguf --profile hybrid
```

Executar com correctness gate:

```powershell
py .\phoenix_runtime\phoenix_llama_runtime.py run --model C:\modelos\qwen.gguf --profile polaris-safe --self-test
```

Se o modelo responder com corrupção típica (`????????...`) o runtime não considera a GPU válida apenas porque o servidor retornou HTTP 200.

## Política de atualização

`master` do llama.cpp **nunca** entra automaticamente numa release Phoenix.

Fluxo obrigatório:

```text
upstream novo
→ branch/runtime-next
→ verificar source/CLI contract
→ build CPU/Vulkan
→ correctness tests
→ CPU/GPU/Híbrido/Polaris/Arena
→ benchmarks
→ só então nova versão stable
```

O arquivo `phoenix_runtime/source_integrity.json` representa o snapshot upstream da versão Stable 1.0.0. O código upstream crítico não foi modificado nesta primeira versão; as mudanças Phoenix estão isoladas em `phoenix_runtime/`.

## PHASE7B — Windows ready bundle

Build trees are repair/development state, not distribution artifacts. A validated Windows build is promoted by `phoenix_runtime/package_windows_runtime.py` to `bin/phoenix-llama-runtime/windows-x64/`. The bundle is hash-manifested and is preferred by the Phoenix launcher/drivers. The vendored source remains the automatic repair fallback.
