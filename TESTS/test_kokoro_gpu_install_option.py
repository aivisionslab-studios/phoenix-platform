"""
Teste de regressão pra um pedido real do usuário (2026-08-23): ele viu o
audiolivro sintetizando em CPU pura (Gerenciador de Tarefas mostrando GPU em
2% e CPU em 50%) e perguntou "podemos pensar em rodar via gpu, nao?".

Pesquisa real feita nesta sessão (lendo o código-fonte instalado de
kokoro_onnx/session.py, não documentação de terceiros): o pacote
kokoro-onnx já escolhe sozinho, em runtime, entre CPU e GPU dependendo de
QUAL distribuição onnxruntime está instalada (resolve_providers() checa
`onnxruntime-directml` via importlib.metadata) - nosso
phoenix_kernel/runtime/drivers/kokoro_tts.py não precisa saber nada sobre
isso. A única peça que precisava mudar era o INSTALADOR (install/common.ps1
+ install_phoenix.ps1), pra dar ao usuário uma forma de escolher qual
onnxruntime instalar, sem quebrar quem não pediu GPU.

Como install/*.ps1 é PowerShell (não dá pra executar de verdade neste
sandbox Linux), os testes aqui validam o TEXTO do script - a mesma
abordagem já usada por test_asset_catalog_download_errors.py pros arquivos
.ps1 daquela auditoria. Cobre: (1) o switch PHOENIX_TTS_DEVICE existe e é
"CPU" por padrão (não muda o comportamento de quem não pediu nada), (2) o
instalador realmente ramifica em cima dessa variável, (3) o caminho GPU
usa onnxruntime-directml e desinstala o outro pacote primeiro (evita
metadados de dois pacotes conflitantes), (4) o caminho CPU (default)
continua exatamente como estava na v48.1, (5) pedir GPU fora do Windows
cai pra CPU com aviso, em vez de tentar instalar um pacote que não existe
pra essa plataforma (confirmado nesta sessão via
'pip download onnxruntime-directml --platform manylinux2014_x86_64' -> não
existe wheel Linux/Mac de verdade).

Rodar com: pytest -q (de dentro de 'PHOENIX 3.0/')
"""
import re
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent
_INSTALL_PHOENIX = (_ROOT / "install_phoenix.ps1").read_text(encoding="utf-8")
_COMMON = (_ROOT / "install" / "common.ps1").read_text(encoding="utf-8")


def test_tts_device_env_var_defaults_to_cpu():
    m = re.search(r'\$env:PHOENIX_TTS_DEVICE\s*=\s*"(\w+)"', _INSTALL_PHOENIX)
    assert m, "esperava achar '$env:PHOENIX_TTS_DEVICE = \"...\"' em install_phoenix.ps1"
    assert m.group(1) == "CPU", (
        "PHOENIX_TTS_DEVICE precisa ser CPU por padrão - o ganho de GPU pra um modelo "
        "de 82M parâmetros é incerto (não testado de verdade nesta auditoria, só em teoria), "
        "então não pode ser o comportamento automático sem o usuário pedir."
    )


def test_common_ps1_branches_on_tts_device_env_var():
    assert 'env:PHOENIX_TTS_DEVICE -eq "GPU"' in _COMMON, (
        "install/common.ps1 precisa checar PHOENIX_TTS_DEVICE pra decidir qual onnxruntime instalar"
    )


def test_gpu_path_installs_directml_and_uninstalls_plain_onnxruntime():
    # Acha o bloco do "if GPU" e confere que instala a variante certa E
    # remove a outra primeiro (evita os dois pacotes coexistindo com
    # metadados furados - eles compartilham o mesmo módulo Python).
    gpu_block_match = re.search(
        r'if \(\$env:PHOENIX_TTS_DEVICE -eq "GPU" -and \$IsWindows\) \{(.*?)\} else \{',
        _COMMON, re.DOTALL,
    )
    assert gpu_block_match, "esperava um bloco 'if ($env:PHOENIX_TTS_DEVICE -eq \"GPU\" -and $IsWindows) { ... } else {' em common.ps1"
    gpu_block = gpu_block_match.group(1)
    assert "pip uninstall -y onnxruntime " in gpu_block or "pip uninstall -y onnxruntime\"" in gpu_block or "pip uninstall -y onnxruntime\n" in gpu_block, (
        f"bloco GPU precisa desinstalar 'onnxruntime' (a variante CPU) antes de instalar a DirectML. Bloco: {gpu_block}"
    )
    assert "onnxruntime-directml" in gpu_block


def test_cpu_path_is_unchanged_default_behavior():
    # O caminho ELSE (comportamento pra quem NUNCA mexeu em PHOENIX_TTS_DEVICE,
    # ou seja, todo mundo hoje) continua instalando onnxruntime normal - a
    # v48.1 já garantia isso, este teste é a prova de que a v49 não regrediu
    # o caso comum ao adicionar a opção de GPU.
    else_block_match = re.search(
        r'if \(\$env:PHOENIX_TTS_DEVICE -eq "GPU" -and \$IsWindows\) \{.*?\} else \{(.*?)\n\}',
        _COMMON, re.DOTALL,
    )
    assert else_block_match, "esperava achar o bloco 'else { ... }' que segue o 'if PHOENIX_TTS_DEVICE -eq GPU' em common.ps1"
    else_block = else_block_match.group(1)
    assert 'onnxruntime>=1.29.0"' in else_block
    assert "onnxruntime-directml" not in gpu_free_installs(else_block)


def gpu_free_installs(block: str) -> str:
    # Remove a linha do uninstall (que MENCIONA onnxruntime-directml de
    # propósito, pra limpar instalação anterior) antes de checar que o
    # bloco CPU não INSTALA a variante GPU.
    return "\n".join(line for line in block.splitlines() if "pip install" in line)


def test_requesting_gpu_outside_windows_falls_back_to_cpu_with_warning():
    # onnxruntime-directml não tem wheel Linux/Mac (confirmado via
    # 'pip download' real nesta sessão) - pedir GPU fora do Windows não pode
    # tentar instalar um pacote que vai falhar, tem que avisar e cair pra CPU.
    assert 'PHOENIX_TTS_DEVICE -eq "GPU" -and -not $IsWindows' in _COMMON, (
        "esperava um aviso específico pra quem pede GPU fora do Windows (onnxruntime-directml não existe lá)"
    )


def test_requirements_txt_documents_the_gpu_alternative():
    req = (_ROOT / "requirements.txt").read_text(encoding="utf-8")
    assert "onnxruntime-directml" in req
    assert "onnxruntime>=1.25.0" in req


def test_kokoro_engine_logs_active_execution_providers():
    # phoenix_kernel/runtime/drivers/kokoro_tts.py: confirma de verdade
    # (não só assume) qual provider está ativo depois de carregar o modelo -
    # essencial pro usuário confirmar se a troca pra GPU funcionou de fato,
    # já que a troca em si é silenciosa (decidida pelo pacote instalado).
    src = (_ROOT / "phoenix_kernel" / "runtime" / "drivers" / "kokoro_tts.py").read_text(encoding="utf-8")
    assert "get_providers()" in src
    assert "execution providers" in src.lower()
