# TESTS/test_telemetry_consent_gating.py
#
# PHX-NEW (verificação pedida pelo usuário 2026-08-28: "telemetria/
# escaner manda pro firestore a cada 60s dados desses sensores pra
# atualizarmos phoenix automaticamente e sem autorização do usuario").
#
# Não é um teste de comportamento em runtime (não sobe um FirestoreSync
# de verdade nem precisa de credencial/rede) - é uma bateria de
# verificação ESTÁTICA sobre o código-fonte real de
# phoenix_kernel/cloud_sync.py e do resto do repositório, seguindo a
# mesma filosofia de test_proxy_backend_timeout_alignment.py e
# verify_release_clean.py: transformar uma alegação de segurança em algo
# checável automaticamente, em vez de confiar em prosa/memória.
#
# Cobre a conclusão da auditoria registrada em
# institutional/docs/SECURITY.md ("Telemetria remota (Firestore) —
# verificação de consentimento"):
#   1. O loop de sincronização roda de fato a cada 60s
#      (CLOUD_SYNC_INTERVAL_SEC) - confirma o "a cada 60s" da pergunta.
#   2. TODO método de FirestoreSync que efetivamente manda/pede algo pro
#      Firestore verifica has_consent() ANTES de fazer qualquer trabalho
#      de rede - nenhuma exceção.
#   3. grant_consent() (o único jeito de o flag de consentimento passar a
#      existir) só é chamado a partir da rota HTTP dedicada
#      /api/telemetry/consent/accept - nenhum script de instalação, setup
#      ou outro módulo cria/"pré-aceita" esse consentimento sozinho.
#
# Rodar com: pytest -q (de dentro de 'PHOENIX 3.0/')

import inspect
import re
import sys
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

import phoenix_kernel.cloud_sync as cloud_sync  # noqa: E402


# Métodos públicos de FirestoreSync que de fato tentam falar com o
# Firestore (excluindo __init__ e _get_client, que só preparam o
# cliente, e os helpers privados _*_blocking, cobertos indiretamente
# porque só são chamados pelos métodos públicos abaixo).
_NETWORK_METHODS = [
    "sync_knowledge_base",
    "sync_machine_state",
    "add_log",
    "shutdown",
    "push_model_run",
    "sync_install_reports",
    "push_to_shared_pool",
    "pull_shared_knowledge_base",
]


def test_cloud_sync_loop_interval_is_60_seconds():
    """Confirma o "a cada 60s" da pergunta do usuário - CLOUD_SYNC_INTERVAL_SEC
    é o valor real usado no asyncio.sleep() do loop, não só uma constante
    solta sem uso."""
    kernel_src = (PROJECT_ROOT / "phoenix_kernel" / "kernel.py").read_text(encoding="utf-8")

    m = re.search(r"CLOUD_SYNC_INTERVAL_SEC\s*=\s*(\d+)", kernel_src)
    assert m, "não achei CLOUD_SYNC_INTERVAL_SEC em phoenix_kernel/kernel.py"
    assert int(m.group(1)) == 60, "o intervalo real não é 60s - a pergunta do usuário citava 60s"

    assert "await asyncio.sleep(CLOUD_SYNC_INTERVAL_SEC)" in kernel_src, (
        "CLOUD_SYNC_INTERVAL_SEC existe mas não é usado no asyncio.sleep() do loop de sync"
    )


@pytest.mark.parametrize("method_name", _NETWORK_METHODS)
def test_network_method_checks_consent_before_any_work(method_name):
    """Cada método público de FirestoreSync que manda ou pede algo ao
    Firestore precisa começar checando has_consent() e devolvendo cedo
    (return/return False/return []/return 0) se não houver consentimento
    - antes de qualquer chamada de executor/cliente."""
    method = getattr(cloud_sync.FirestoreSync, method_name)
    source = inspect.getsource(method)

    consent_match = re.search(r"if\s+not\s+has_consent\(\)\s*:\s*return", source)
    assert consent_match, (
        f"FirestoreSync.{method_name} não tem 'if not has_consent(): return...' "
        f"logo no início - método fonte:\n{source}"
    )

    # A checagem de consentimento precisa vir ANTES de qualquer chamada que
    # de fato inicia trabalho de rede (run_in_executor ou _get_client
    # direto) - garante que não é uma checagem solta depois do trabalho
    # já ter começado.
    work_indicators = ["run_in_executor", "self._get_client("]
    work_positions = [source.find(w) for w in work_indicators if w in source]
    if work_positions:
        first_work_pos = min(p for p in work_positions if p != -1)
        assert consent_match.start() < first_work_pos, (
            f"FirestoreSync.{method_name}: a checagem de has_consent() aparece DEPOIS "
            f"do trabalho de rede já ter começado, não antes."
        )


def test_grant_consent_called_only_from_the_dedicated_accept_route():
    """grant_consent() é o único jeito de data/telemetry_consent.flag
    passar a existir - confirma que ele só é invocado a partir da rota
    HTTP dedicada, e não de algum script de instalação/setup que
    "pré-aceitaria" telemetria sem o usuário pedir."""
    callers = []
    for path in PROJECT_ROOT.rglob("*.py"):
        if "TESTS" in path.parts or "__pycache__" in path.parts or "node_modules" in path.parts:
            continue
        # PHX-FIX (31/08): pastas de backup/payload de patch (criadas pelos
        # próprios scripts de aplicação de patch desta auditoria, ex.
        # `backup_patch_vulkan_router_20260830-125800/` e `PATCH_FILES/`)
        # guardam cópias ANTIGAS de arquivos como `api_server.py` - não são
        # código-fonte real em uso, e escaneá-las conta a mesma chamada
        # várias vezes como se fossem "lugares inesperados" diferentes.
        # PHX-FIX (2026-09-03): mesma lógica para `_LIXO_LIMPEZA/` (pasta de
        # limpeza que guarda arquivos movidos, incluindo cópias antigas do
        # projeto) e `repos/` (clones/cópias de outros repositórios) - nenhuma
        # das duas é código-fonte em uso.
        _IGNORED_ROOTS = ("PATCH_FILES", "_LIXO_LIMPEZA", "repos")
        if any(
            part in _IGNORED_ROOTS or part.startswith("backup_patch_")
            for part in path.parts
        ):
            continue
        try:
            text = path.read_text(encoding="utf-8", errors="ignore")
        except Exception:
            continue
        for match in re.finditer(r"\bgrant_consent\s*\(", text):
            line_no = text.count("\n", 0, match.start()) + 1
            # Ignora a própria definição da função em cloud_sync.py.
            line_text = text.splitlines()[line_no - 1]
            if re.match(r"\s*def\s+grant_consent\b", line_text):
                continue
            callers.append((str(path.relative_to(PROJECT_ROOT)), line_no))

    assert callers == [("api_server.py", callers[0][1] if callers else None)] or (
        len(callers) == 1 and callers[0][0] == "api_server.py"
    ), f"grant_consent() é chamado de lugar(es) inesperado(s): {callers}"


def test_no_install_or_setup_script_writes_telemetry_consent_flag_directly():
    """Nenhum script de instalação/setup deveria criar o arquivo de
    consentimento diretamente (bypassando a rota HTTP e, com isso, a
    decisão explícita do usuário via /api/telemetry/consent/accept)."""
    suspects = [
        PROJECT_ROOT / "install_phoenix.ps1",
        PROJECT_ROOT / "setup_environment.py",
        PROJECT_ROOT / "setup_platform.py",
        PROJECT_ROOT / "organizar_pasta_phoenix.ps1",
    ]
    install_dir = PROJECT_ROOT / "install"
    if install_dir.is_dir():
        suspects.extend(install_dir.glob("*.ps1"))

    offenders = []
    for path in suspects:
        if not path.exists():
            continue
        text = path.read_text(encoding="utf-8", errors="ignore")
        if "telemetry_consent" in text or "grant_consent" in text:
            offenders.append(str(path.relative_to(PROJECT_ROOT)))

    assert offenders == [], f"script(s) de instalação/setup mexendo em consentimento de telemetria: {offenders}"


def test_has_consent_checks_the_real_flag_file_not_a_hardcoded_true():
    """Rede de segurança contra uma regressão boba mas real: alguém trocar
    `return CONSENT_FLAG.exists()` por `return True` sem querer, o que
    ligaria telemetria remota pra todo mundo silenciosamente."""
    source = inspect.getsource(cloud_sync.has_consent)
    assert "CONSENT_FLAG.exists()" in source
    assert re.search(r"return\s+True\b", source) is None
