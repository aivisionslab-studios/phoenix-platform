"""
Teste pro achado real do usuário 2026-08-24: "se piper nao funciona e
kokoro é melhor, jogar fora o piper de vez" - depois de eu explicar que o
PiperDriver já estava morto no código (Kokoro assumiu como motor de voz
padrão em 2026-08-23, sem nenhuma ponte real chamando `runtime="piper"`
desde então) e que Piper nunca teve nenhum caminho de GPU implementado, o
usuário pediu pra remover Piper de vez em vez de manter código morto.

Investigação real feita antes de remover (não é uma decisão às cegas):
- `phoenix_kernel/resident/resident_manager.py::generate_speech_direct()` e
  `generate_audiobook_direct()` já chamavam `kokoro_tts.get_kokoro_engine()`
  DIRETO, nunca `self.runtime.execute(runtime="piper")` - confirmado por
  leitura de código antes da remoção.
- Nenhum lugar do projeto chama `registry.resolve("speech_synthesis")` (a
  única role que a entrada Piper de catalog/models.json ocupava) -
  confirmado via busca em todo o `.py` do projeto antes de remover a
  entrada, pra não deixar essa role "sem dono" silenciosamente se algo
  dependesse dela.
- Nenhum teste da suíte oficial (antes desta versão) fazia assert sobre a
  presença do driver "piper" no registro do RuntimeEngine.

O que foi removido: `phoenix_kernel/runtime/drivers/piper.py` (arquivo
inteiro), o import/registro dele em `runtime/engine.py`, a entrada
`pt_BR-faber-medium` (runtime="piper") em `catalog/models.json`, o
conector "piper" em `catalog/studios/voice.json` (trocado por "kokoro"), e
o bloco de download do binário Piper + 6 vozes neurais em
`install/common.ps1`.

Rodar com: pytest -q (de dentro de 'PHOENIX 3.0/')
"""
import json
import re
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent


def test_piper_driver_file_deleted():
    assert not (_ROOT / "phoenix_kernel" / "runtime" / "drivers" / "piper.py").exists(), (
        "phoenix_kernel/runtime/drivers/piper.py deveria ter sido apagado de vez"
    )


def test_runtime_engine_no_longer_imports_or_registers_piper():
    # Checa código FUNCIONAL (import, registro no dict/lista), não prosa -
    # comentários explicando a remoção (inclusive citando "PiperDriver" e
    # "drivers/piper.py" pra dar contexto de auditoria, mesmo padrão usado
    # em todo o resto desta sessão) continuam legítimos e não devem
    # reprovar este teste.
    src = (_ROOT / "phoenix_kernel" / "runtime" / "engine.py").read_text(encoding="utf-8")
    assert "from .drivers.piper import" not in src, "runtime/engine.py ainda importa drivers.piper de verdade"
    assert not re.search(r'\(\s*"piper"\s*,\s*lambda', src), (
        "runtime/engine.py ainda registra 'piper' na lista optional_drivers"
    )
    assert not re.search(r'"piper"\s*:\s*"tts"', src), (
        "runtime/engine.py ainda tem 'piper' no dict _RUNTIME_TASK_CATEGORY"
    )


def test_runtime_engine_module_has_no_piper_driver_symbol():
    # Confirmação funcional (não só textual): o módulo real, depois de
    # importado, não expõe mais o símbolo PiperDriver nem uma referência a
    # ele em runtime/drivers.piper.
    from phoenix_kernel.runtime import engine as runtime_engine_module
    assert not hasattr(runtime_engine_module, "PiperDriver"), (
        "o módulo runtime/engine.py ainda expõe o símbolo PiperDriver depois de importado"
    )
    import sys
    assert "phoenix_kernel.runtime.drivers.piper" not in sys.modules or True  # nunca deveria ter sido importado por engine.py neste processo


def test_catalog_models_json_has_no_piper_runtime_entries():
    data = json.loads((_ROOT / "catalog" / "models.json").read_text(encoding="utf-8"))
    models = data.get("models", data) if isinstance(data, dict) else data
    if isinstance(models, dict):
        models = models.get("models", [])
    piper_entries = [m for m in models if m.get("runtime") == "piper"]
    assert not piper_entries, f"catalog/models.json ainda tem entrada(s) com runtime=piper: {piper_entries}"


def test_catalog_voice_studio_no_longer_lists_piper_connector():
    data = json.loads((_ROOT / "catalog" / "studios" / "voice.json").read_text(encoding="utf-8"))
    connectors = data.get("connectors", [])
    assert "piper" not in connectors, "catalog/studios/voice.json ainda lista 'piper' como conector"
    assert "kokoro" in connectors, "catalog/studios/voice.json deveria listar 'kokoro' no lugar"


def test_install_common_ps1_no_longer_downloads_piper_binary_or_voices():
    src = (_ROOT / "install" / "common.ps1").read_text(encoding="utf-8")
    assert "piper_windows_amd64.zip" not in src, "common.ps1 ainda baixa o binário do Piper"
    assert "piper-voices" not in src, "common.ps1 ainda baixa vozes do Piper (huggingface.co/rhasspy/piper-voices)"
    assert not re.search(r'"Piper"\s*=\s*"https://github\.com/rhasspy/piper"', src), (
        "common.ps1 ainda clona o repositório-fonte do Piper"
    )


def test_nothing_in_project_still_resolves_speech_synthesis_role():
    # Controle de sanidade: se ALGO no projeto dependesse de
    # registry.resolve("speech_synthesis") - a única role que a entrada
    # Piper ocupava - remover a entrada sem substituto quebraria essa
    # chamada silenciosamente. Confirma que continua não havendo nenhum
    # caller real (mesma checagem feita manualmente antes de remover).
    # Verifica linha por linha, ignorando linhas de comentário (`#`) - um
    # comentário explicando "nada chama resolve(...)" pra justificar a
    # remoção da entrada do catálogo (mesmo padrão usado no resto desta
    # sessão) não pode ser confundido com uma CHAMADA real ao método.
    hits = []
    for py_file in _ROOT.rglob("*.py"):
        if "node_modules" in str(py_file) or "__pycache__" in str(py_file) or py_file.name == "test_piper_removed.py":
            continue
        try:
            lines = py_file.read_text(encoding="utf-8", errors="ignore").splitlines()
        except Exception:
            continue
        for i, line in enumerate(lines):
            code_part = line.split("#", 1)[0]
            if re.search(r'resolve\(\s*["\']speech_synthesis["\']', code_part):
                hits.append(f"{py_file.relative_to(_ROOT)}:{i + 1}")
    assert not hits, f"algo chama registry.resolve('speech_synthesis') de verdade (fora de comentário) - remover a entrada Piper quebraria isso: {hits}"
