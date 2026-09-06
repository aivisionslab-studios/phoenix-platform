---
memory_type: procedural
procedure_id: run_llm_llama_cpp_vulkan
triggers: ["rodar llm", "llama-server", "qwen", "modelo de texto", "gguf de linguagem"]
platform: [windows, linux]
prerequisite_check: ["gpu_vulkan_detected", "llama_cpp_compiled", "model_file_present"]
---

# Procedimento: Executar LLM via llama.cpp (Vulkan) nesta máquina

## Passo 1 — Localizar o binário real (não o stub)
No Windows já ocorreu confusão entre `llama.cpp\llama-server.exe` (stub de 9KB)
e `llama.cpp\build\bin\Release\llama-server.exe` (executável real ~7.5MB). Sempre
confirmar com:
```
Get-ChildItem -Path E:\ -Recurse -Filter "llama-server.exe"
```

## Passo 2 — Comando padrão
```
llama-server.exe -m "<caminho>/modelo.gguf" --host 0.0.0.0 --port 8081
```
NÃO forçar `-ngl` manualmente em modelos MoE grandes (35B+): o fitting automático
do llama.cpp resolveu a distribuição GPU/RAM sozinho em 1.15s e superou qualquer
configuração manual testada (ver `machine/qwen35b_moe_deep_dive.json`).

## Passo 3 — Se o modelo for MoE grande (30B+) com thinking mode
Adicionar sempre `--ctx-size 8192`. O padrão de fitting automático reduz o
contexto para 4096, o que é insuficiente quando o thinking mode está ativo
(consome 3000+ tokens sozinho antes de qualquer resposta visível).
```
llama-server.exe -m "<modelo>.gguf" --host 0.0.0.0 --port 8081 --ctx-size 8192
```

## Passo 4 — Escolha de quantização
Nesta máquina, para a família Qwen3.5 35B, **Q4_K_M é superior a Q6_K**:
mais rápido (6.4-6.65 vs 5.57-5.64 tok/s), mais frio (74°C vs 80°C), menos
swap em HDD. Preferir Q4_K_M salvo indicação contrária do usuário.

## Passo 5 — Não combinar com web search em sessões longas
Web search injeta muitos tokens de contexto. Combinado com thinking mode e
contexto de 4096, estoura rapidamente (`truncated=1`). Se o usuário quiser
usar ambos, garantir `--ctx-size 8192` ou maior antes.

## Passo 6 — Testar via curl antes de culpar o hardware
Se a interface (OpenWebUI) parecer travar ou dar timeout, testar direto:
```
curl.exe -X POST http://localhost:8081/v1/chat/completions \
  -H "Content-Type: application/json" --max-time 600 \
  -d "@prompt.json"
```
Na maioria dos casos observados aqui, o servidor continuava gerando
normalmente em background — o timeout era do CLIENTE, não do llama-server.

## Passo 7 — Plataforma
Se a tarefa for LLM puro (sem geração de imagem), preferir **Linux nativo**
(Mesa RADV): ~2x mais rápido que Windows para modelos que cabem inteiros
na GPU. Nunca usar WSL2 para isso (não expõe GPU via Vulkan).

## Passo 8 — Após execução
Registrar tokens/s, temperatura, VRAM/RAM usada em
`machine/model_compatibility_matrix.json`.
