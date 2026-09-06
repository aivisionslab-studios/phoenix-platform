# Phoenix V6 — Documentos sem limite artificial de tokens

Alterados:
- phoenix_kernel/resident/resident_manager.py
- phoenix_kernel/runtime/drivers/llama_cpp.py

Revisado, sem alteração necessária:
- platform_source/server.ts (já usa 31 min para /api/documents/create)

Regra:
- Document Composer envia `unlimited_output=True`.
- LlamaCppDriver remove `max_tokens` do payload apenas nesse fluxo.
- Chat comum mantém seu comportamento anterior.
- Timeouts de 20/30 min permanecem como proteção contra travamento, não como limite de tokens.
- A saída ainda está sujeita aos limites físicos do modelo/context window/KV cache/RAM/VRAM.

Validação local do patch:
- resident_manager.py: py_compile OK
- llama_cpp.py: py_compile OK
- create_document_direct sem max_tokens=4096
- unlimited_output presente
- llama.cpp remove max_tokens quando unlimited_output=True
- server.ts já possui 1_860_000 ms (31 min) em /api/documents/create
