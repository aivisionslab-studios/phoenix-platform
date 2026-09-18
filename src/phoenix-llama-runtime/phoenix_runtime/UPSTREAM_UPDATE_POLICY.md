# Política de atualização do upstream

1. Nunca substituir o snapshot Stable por `git pull` em produção.
2. Atualizações entram primeiro no canal `next`.
3. Comparar `common/arg.cpp`, model loader, scheduler, server e backend Vulkan.
4. Executar `verify_cli_contract.py` no novo binário.
5. Executar correctness gate com modelos de referência.
6. Validar pelo menos CPU estrito, GPU full, híbrido, Polaris safe/conservative e MoE hybrid.
7. Só publicar nova Stable depois de os testes Phoenix passarem.
8. Preservar copyright e licença MIT do llama.cpp.
