# Phoenix 4.5 — modos de execução do LLM local

Data: 2026-09-07

## Objetivo

Permitir ao usuário escolher explicitamente como o LLM compartilhado do chat via llama.cpp usa CPU/GPU, sem retirar a política automática padrão da Phoenix e sem interferir nos workers dedicados da Arena ou de documentos.

## Modos

- **PADRÃO**: preserva a política Phoenix anterior (`PHOENIX_LLM_NGL`, atualmente CPU por default).
- **CPU**: `-ngl 0`, GPU preservada.
- **GPU**: `-ngl all`, device Vulkan configurado, op-offload habilitado; falha real é exibida, sem fallback silencioso.
- **HÍBRIDO**: `-ngl auto --fit on --fit-target 0 --fit-ctx 8192`; o contexto não é fixado com `-c`, permitindo ao fitter do Phoenix Llama Runtime ajustar placement/contexto à memória disponível sem reservar 1536 MB de VRAM artificialmente.

A preferência é persistida em `data/text_execution_preference.json`, arquivo local ignorado pelo Git/release.

## Isolamento

Instâncias de `LlamaCppDriver` criadas com `force_ngl` são consideradas workers dedicados e ignoram a preferência global. Isso preserva a Arena GPU e o worker documental.

## API e UI

- `GET /api/engine/text-execution`
- `POST /api/engine/text-execution`
- Painel INFERENCE: `PADRÃO | CPU | GPU | HÍBRIDO`, com indicador `PERFIL: PADRÃO/MODIFICADO`.
- A troca reinicia o llama.cpp ativo com o mesmo modelo quando possível.
- Em Ollama, os botões ficam desabilitados porque o placement é responsabilidade do próprio Ollama.

## Catálogo oficial adicional

Adicionados aos downloads recomendados, sem torná-los defaults:

- `Qwen/Qwen3-30B-A3B-GGUF` — `Qwen3-30B-A3B-Q4_K_M.gguf`, 18.6 GB, recomendado HÍBRIDO.
- `Qwen/Qwen3-32B-GGUF` — `Qwen3-32B-Q4_K_M.gguf`, 19.8 GB, recomendado HÍBRIDO; 24 GB de RAM total é um cenário apertado.

Nenhum modelo de terceiros foi rotulado como “oficial” ou “uncensored”.

## Validação

Suíte Python completa após as alterações: **818 passed, 2 skipped, 0 failed**.

Testes novos verificam os quatro modos, isolamento dos workers dedicados, wiring API/Node/UI e presença dos modelos oficiais com hashes conhecidos.
