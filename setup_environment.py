"""
setup_environment.py (STUB DE SEGURANÇA)
=========================================
PHX-FIX (Rodada 10 — achado A4 de duas auditorias externas independentes,
2026-08-20): este arquivo era um gerador de scaffold de 217 linhas de uma
versão antiga do projeto (imprimia literalmente "CONFIGURANDO AMBIENTE
PHOENIX 5.0" - uma versão que não é esta). Se executado, ele:

  1. Sobrescrevia `catalog/models.json` (o catálogo REAL, lido por
     phoenix_kernel/models/registry.py) com um formato antigo e
     incompatível - Qwen via `ollama://` em vez de llama.cpp, e um FLUX
     apontando pra uma URL do Hugging Face que já nem é a usada hoje
     (ver catalog/assets/flux.json). Isso teria destruído a Golden
     Baseline (llama.cpp/Vulkan como default) silenciosamente.
  2. Gerava `phoenix_kernel/07_services/provisioning.py` e
     `phoenix_kernel/08_models/model_manager.py` - caminhos com prefixo
     numérico que não existem mais na estrutura atual do projeto
     (hoje é `phoenix_kernel/services/` e `phoenix_kernel/models/`, sem
     prefixo) - ou seja, nem geraria código no lugar certo.
  3. O `ModelManager` gerado tinha `C:/ProgramData/Phoenix/storage.json`
     e `E:/Phoenix/Models` hardcoded, violando o princípio explícito de
     phoenix_kernel/paths.py ("nenhum código deve conter C:\\, D:\\,
     E:\\ ou /opt").

Confirmado (grep no projeto inteiro) que nada em kernel.py, nos
instaladores (.bat/.sh/.ps1) ou em qualquer rota de boot importa ou
chama este arquivo - era código morto, não um caminho de execução
ativo. Mas "morto" não é o mesmo que "inofensivo": bastava alguém rodar
`python setup_environment.py` manualmente (por exemplo, atrás de uma
instrução desatualizada em algum README ou anotação pessoal) pra
corromper o catálogo real. Por isso virou este stub em vez de continuar
como gerador funcional. Se algum dia fizer sentido um scaffold pra uma
"Phoenix 5.0" de verdade, escreva um script novo do zero, contra a
estrutura atual do projeto - não reative este.
"""

import sys

sys.exit(
    "setup_environment.py legado desativado (Rodada 10, achado A4). "
    "Este script sobrescrevia catalog/models.json com um formato antigo "
    "(Ollama como engine de texto, caminhos C:/E: hardcoded) e não é "
    "usado por nenhum caminho de boot real. Se você precisa preparar o "
    "ambiente, use install/common.ps1 (setup completo) ou "
    "setup_platform.py (só a Platform React/Node)."
)
