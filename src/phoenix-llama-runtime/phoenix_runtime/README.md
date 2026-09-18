# Phoenix Runtime Compatibility Layer

Leia `../PHOENIX_LLAMA_RUNTIME.md`.

Arquivos principais:

- `upstream.lock.json`: revisão upstream permitida.
- `compatibility_contract.json`: flags que o Phoenix exige do `llama-server`.
- `source_integrity.json`: hashes de arquivos upstream críticos.
- `phoenix_llama_runtime.py`: launcher de perfis e correctness gate.
- `profiles/`: políticas de execução sem patches profundos no core.
- `scripts/`: builds reproduzíveis.
- `tests/`: regressões da camada Phoenix.
