"""
PHX-FIX (31/08, achado durante a investigacao da recorrencia do crash
0xC0000005 no flux1-schnell): rodar `pytest -q` na RAIZ do projeto (como
o LEIA-ME do patch anterior instrui) quebrava a COLETA inteira da suite
com "import file mismatch" - nao um teste falhando, a colecao INTEIRA
sendo interrompida antes de rodar qualquer coisa. Causa: pastas de
backup/patch deixadas dentro da arvore do projeto por processos
anteriores de aplicar patch (`backup_patch_vulkan_router_20260830-125800/`,
`PATCH_FILES/`) tem suas PROPRIAS copias de `TESTS/test_llama_cpp_launch_policy.py`
e `TESTS/test_source_contracts.py` - o pytest tenta importar os dois
arquivos com o mesmo nome de modulo Python e colide. Essas pastas ja
tinham sido excluidas manualmente de UM teste especifico
(`test_telemetry_consent_gating.py`, ver PHX-FIX la), mas nada excluia
elas da COLETA em si - o problema so aparecia rodando a suite inteira,
nao rodando so `TESTS/`, o que mascarou o bug nas rodadas anteriores de
auditoria (rodadas anteriores usaram `pytest -q TESTS`, nao `pytest -q`
puro).

Tambem exclui os scripts manuais de diagnostico (`*_smoke_test.py`,
`*_benchmark_run.py`) espalhados em `phoenix_kernel/documents/` e
`TESTS/` - o proprio docstring deles (ver `document_llm_worker_smoke_test.py`)
documenta a intencao de NAO rodar sob pytest ("nao comeca com test_"),
mas o pytest por padrao tambem coleta qualquer `*_test.py`, entao o nome
escolhido nao bloqueava a colecao como o autor pretendia - so por sorte
nenhum deles tinha erro de import ate agora (`document_llm_worker_smoke_test.py`
importava `DOCUMENT_GPU_PORT`, que nunca existiu em `document_llm_worker.py`
- so `DOCUMENT_GPU_PORT_START`/`DOCUMENT_GPU_PORT_END` - corrigido
separadamente no proprio arquivo, mas a colecao continua excluida aqui
por ser a intencao explicita e documentada desses scripts).
"""
collect_ignore_glob = [
    "backup_patch_*/**",
    "PATCH_FILES/**",
    "*_smoke_test.py",
    "**/*_smoke_test.py",
    "*_benchmark_run.py",
    "**/*_benchmark_run.py",
]
