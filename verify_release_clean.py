"""
verify_release_clean.py
========================
PHX-NEW (Rodada 11 — resposta ao padrão que se repetiu nas Rodadas 9 e 10):
duas auditorias externas seguidas apontaram os MESMOS dois caminhos ainda
presentes no ZIP entregue para auditoria (`Engine/Bootstrap/` e
`data/engine_preference.json`), apesar do LEIA-ME de cada rodada instruir
"apague X" em prosa. O código-fonte nunca regrediu - conferi a cada vez que
a cópia de referência usada pra testar as correções já estava sem esses
dois caminhos. O problema real é de processo: uma instrução em texto,
aplicada manualmente numa árvore de projeto diferente da que eu tenho
acesso direto, é fácil de esquecer entre uma rodada e a próxima geração de
ZIP pra auditoria.

PHX-FIX (Rodada 12 — achado da 3ª auditoria externa, sobre o
`PHOENIX 3.0(6).zip`): o script existia e funcionava (a própria auditoria
confirmou rodando ele manualmente), mas **não tinha sido executado antes
de gerar aquele ZIP específico** - ou seja, o mecanismo de limpeza e o
gatilho "rodar antes de zipar" ainda eram dois passos manuais separados.
Passos 4 e 5 abaixo (limpar cache Python e checar a exceção de
`.env.example` no .gitignore) são novos nesta rodada, adicionados porque a
mesma auditoria trouxe esses dois achados secundários.

Este script substitui a instrução em prosa por um passo executável e
verificável. Rode ele DENTRO da pasta raiz do projeto (`PHOENIX 3.0/`)
ANTES de gerar qualquer ZIP para auditoria externa:

    python3 verify_release_clean.py

Ele faz 7 coisas, nesta ordem (as 2 últimas são novas da Rodada 15 - ver
PHX-FIX abaixo):
  1. APAGA de verdade (não só avisa) os caminhos legados conhecidos que já
     foram classificados como lixo/órfão em rodadas anteriores.
  2. LIMPA de verdade os diretórios de cache/build do Python
     (`__pycache__/`, `.pytest_cache/`, `*.egg-info/`) espalhados pela
     árvore - não quebram nada se ficarem, mas sujam um ZIP de release.
  3. CONFERE que o .gitignore continua bloqueando os arquivos de
     preferência de engine (pra eles não ressuscitarem via um commit/merge
     futuro).
  4. CONFERE que o .gitignore tem a exceção `!platform_source/.env.example`
     (sem ela, o padrão `.env.*` acima também esconde o template de
     exemplo, que não é segredo nenhum).
  5. CONFERE (se o build da Platform existir) que o `dist/server.cjs` não
     contém o hardcode antigo de `model_hint || "flux"` e contém a defesa
     de SSRF `resolveAllowedProxyTarget` - os dois marcadores que as
     auditorias externas já usaram três vezes pra flagar build stale.

Sai com código 0 só se tudo passar. Sai com código 1 e imprime exatamente
o que falhou, caso contrário - pra dar pra rodar isso num script de build/
release e travar a geração do ZIP se algo continuar sujo, em vez de
descobrir isso de novo só depois de outra auditoria externa.

PHX-FIX (Rodada 15 — achado GRAVE de auditoria externa real: um ZIP
entregue continha `data/config/firestore_credentials.json` com uma chave
privada REAL de service account do Firebase/Google Cloud). As checagens
1-5 acima (Rodadas 11/12) cobriam "lixo órfão conhecido" e "build
desatualizado" - nenhuma delas checava CONTEÚDO de arquivo pra segredo
real, e o processo de gerar o ZIP até então era "pasta inteira menos uns
excludes manuais na hora do `tar`/`zip`" - uma lista de exclusão manual
sempre vai ficar incompleta (foi assim que o achado #2 do
`data/machine_id.json` - variante SEM "config/" no meio, faltando no
.gitignore - também escapou). Duas mudanças estruturais:

  6. NOVA CHECAGEM (nunca apaga, só FALHA e lista): varre a árvore atrás
     de arquivos com nome de segredo conhecido (`*firestore_credentials*`
     exceto `*.example.json`, `*service_account*.json` exceto
     `*.example.json`, `*.pem`, `*.key`) E varre o CONTEÚDO de todo
     arquivo texto pequeno atrás de marcadores de chave privada real
     (`-----BEGIN PRIVATE KEY-----`, `"private_key"` com valor não-vazio,
     `firebase-adminsdk`). Isso é uma rede de segurança: mesmo que a
     lista de exclusão do empacotamento tenha um buraco (como o achado
     #2), este script barra a geração do ZIP.
  7. NOVA CHECAGEM (informativa, nunca apaga): lista arquivos de estado
     local/instância que não pertencem a um release (banco de hardware,
     IDs de máquina, logs de instalação) - eles são legítimos na árvore
     de trabalho de quem RODA a Phoenix (não são lixo, não dá pra
     simplesmente apagar sem quebrar a instalação local de alguém), mas
     não podem ir pro ZIP entregue. Ver `build_release_zip.py` (novo
     nesta rodada) - ele resolve isso de vez, gerando o ZIP a partir de
     uma cópia allowlist (`git add -A` + `git ls-files` num repo git
     descartável, respeitando o .gitignore de verdade em vez de uma
     lista de exclusão mantida à mão) em vez de "pasta inteira menos
     excludes". Rodar verify_release_clean.py sozinho continua útil como
     checagem rápida, mas o gerador de ZIP oficial agora é
     build_release_zip.py.
"""

from __future__ import annotations
import re
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent

# PHX-NEW (Rodada 15): nomes de arquivo que são SEMPRE segredo real se
# existirem (nunca comitar/empacotar) - os .example.json equivalentes são
# templates sem segredo e não devem disparar isto.
SECRET_FILENAME_PATTERNS = [
    "*firestore_credentials*.json",
    "*firebase_service_account*.json",
    "*service_account*.json",
    "*.pem",
    "*.key",
]
SECRET_FILENAME_ALLOW_SUFFIXES = (".example.json",)

# Marcadores de CONTEÚDO que só aparecem em credenciais reais (não em
# templates/exemplos, que sempre têm esses campos vazios ou ausentes).
SECRET_CONTENT_MARKERS = [
    "-----BEGIN PRIVATE KEY-----",
    "firebase-adminsdk",
]

# Extensões de arquivo texto que vale a pena varrer por conteúdo - varrer
# binários/imagens/modelos .gguf seria lento e sem sentido.
SECRET_SCAN_TEXT_EXTENSIONS = {".json", ".env", ".txt", ".yml", ".yaml", ".ps1", ".py", ".ts", ".tsx", ".js"}
SECRET_SCAN_MAX_FILE_BYTES = 2 * 1024 * 1024  # 2MB - nenhum arquivo de config/credencial real passa disso

# Diretórios que este script nunca deve varrer (grandes, irrelevantes, ou
# já cobertos por outra checagem).
#
# PHX-FIX (2026-08-28, achado do usuário rodando isto na árvore de
# desenvolvimento real): faltava .venv/venv/env aqui. Sem isso, todo run
# varria .venv/Lib/site-packages inteiro e denunciava arquivos de
# bibliotecas de terceiros já instaladas (certifi/cacert.pem,
# grpc/_cython/_credentials/roots.pem, google/auth/crypt/_python_rsa.py
# etc.) como se fossem segredo do projeto - são apenas código-fonte de
# pacote pip, nunca vão pro git nem pro ZIP de release (.venv não é
# rastreado de propósito), e o script "gritava lobo" em toda execução por
# causa deles, escondendo os achados reais no meio do ruído.
SECRET_SCAN_SKIP_DIR_NAMES = {
    "node_modules", ".git", "__pycache__", ".pytest_cache", "repos", "dist",
    ".venv", "venv", "env", ".env_dir",
}

# Arquivos que legitimamente contêm os MARCADORES de segredo como texto
# (definição de padrão/documentação, não segredo de verdade) - excluídos
# do próprio scan de conteúdo pra não se autodenunciar como falso positivo.
#
# PHX-FIX (2026-08-28, achado do usuário rodando isto de verdade após
# copiar o teste novo pra árvore): test_release_hygiene_skips_venv.py
# escreve os marcadores falsos ('-----BEGIN PRIVATE KEY-----',
# '"private_key": "..."') como literais de string no próprio
# código-fonte, pra simular o conteúdo de um arquivo de biblioteca dentro
# de .venv/ - mesma categoria de "contém o marcador como texto de
# definição/teste, não segredo real" que já justificava excluir este
# próprio script.
SECRET_SCAN_SELF_EXCLUDE_FILES = {
    "verify_release_clean.py", "build_release_zip.py",
    "test_release_hygiene_skips_venv.py",
}

# PHX-NEW (Rodada 15, achado #2 da auditoria externa): arquivos de estado
# local/instância que NUNCA pertencem a um release, mas que também não
# podem ser apagados cegamente da árvore de trabalho (são estado real de
# quem já rodou a Phoenix aqui) - só reportados, nunca removidos por este
# script.
LOCAL_STATE_PATHS_TO_FLAG = [
    "data/hardware.db",
    "data/knowledge.db",
    "data/machine_id.json",
    "data/machine_id.txt",
    "data/config/machine.json",
    "data/config/machine_id.json",
    "data/telemetry_consent.flag",
    "data/license_accepted.flag",
    "data/chroma_db",
    "logs",
]

# Caminhos legados que já foram classificados como órfãos/lixo em rodadas
# anteriores desta auditoria e que precisam ficar ausentes num release.
LEGACY_PATHS_TO_DELETE = [
    ROOT / "Engine" / "Bootstrap",
    ROOT / "data" / "engine_preference.json",
]

# PHX-NEW (auditoria 2026-08-28, achado GRAVE do usuário no repositório
# público real): `private_server_reference/` e o backup órfão
# `plans.py.before_hotfix_20260827_194334` foram publicados em
# github.com/aivisionslab-studios/phoenix-engine, e a checagem de segredo
# por CONTEÚDO (Rodada 15, `_check_no_leaked_secrets` abaixo) não pegou
# nenhum dos dois: o primeiro porque não tinha credencial embutida (só o
# DESENHO do esquema de licenciamento - claims, issuer/audience, endpoint
# - sensível por motivo de negócio, não por conter uma chave), o segundo
# porque não é credencial nenhuma, só um backup de hotfix esquecido. São
# PASTAS/PADRÕES DE NOME inteiros que nunca deveriam ir pra um release,
# mesmo sem nenhum segredo dentro. Ao contrário de LOCAL_STATE_PATHS_TO_FLAG
# (informativo, nunca falha - é estado real de instância local, legítimo
# na árvore de trabalho), isto FALHA de verdade: não existe cenário
# legítimo de "isto precisa estar no ZIP/no repo público".
#
# PHX-NEW (achado do usuário 2026-08-28, segunda rodada - navegando o
# repositório público de verdade): `_archive_patches_antigos/` também foi
# publicada. Sem credencial embutida (mesmo critério acima), mas dois
# problemas: (1) é bastidor de desenvolvimento - scripts de aplicar/testar
# hotfixes antigos, sem utilidade pra quem baixa um release; (2)
# `LEIA-ME_CAPABILITY_V4_INTEGRADO.md`, em especial, documenta em detalhe
# a arquitetura do esquema de licenciamento/anti-pirataria (nomes de
# módulo, o papel de cada um, e a matriz de teste "tentativa de burlar X
# -> continua Free") - não vaza a chave privada, mas facilita quem quiser
# tentar quebrar o Free/Pro sabendo exatamente o que precisa driblar e que
# já foi validado que funciona. Mesmo tratamento de
# private_server_reference: nunca pertence a um release público,
# independente do conteúdo.
NEVER_PUBLISH_DIR_NAMES = {"private_server_reference", "_archive_patches_antigos"}
NEVER_PUBLISH_GLOB_PATTERNS = ["*.before_hotfix_*"]

# Padrões de cache/build do Python que não pertencem a um ZIP de release
# (achado secundário da 3ª auditoria externa, Rodada 12).
CACHE_DIR_PATTERNS = ["__pycache__", ".pytest_cache", "*.egg-info"]

GITIGNORE_PATTERNS_REQUIRED = [
    "data/text_engine_preference.json",
    "data/engine_preference.json",
]

GITIGNORE_EXCEPTION_REQUIRED = "!platform_source/.env.example"

SERVER_CJS = ROOT / "platform_source" / "dist" / "server.cjs"


def _remove_legacy_paths() -> list[str]:
    actions = []
    for path in LEGACY_PATHS_TO_DELETE:
        if path.is_dir():
            shutil.rmtree(path)
            actions.append(f"[REMOVIDO] {path.relative_to(ROOT)} (pasta)")
        elif path.is_file():
            path.unlink()
            actions.append(f"[REMOVIDO] {path.relative_to(ROOT)} (arquivo)")
        else:
            actions.append(f"[OK] {path.relative_to(ROOT)} já estava ausente")
    return actions


def _clean_cache_dirs() -> list[str]:
    actions = []
    removed_count = 0
    for pattern in CACHE_DIR_PATTERNS:
        for match in sorted(ROOT.rglob(pattern)):
            if match.is_dir():
                shutil.rmtree(match, ignore_errors=True)
                removed_count += 1
    if removed_count:
        actions.append(f"[REMOVIDO] {removed_count} diretório(s) de cache/build (__pycache__/.pytest_cache/*.egg-info)")
    else:
        actions.append("[OK] nenhum diretório de cache/build encontrado")
    return actions


def _check_gitignore() -> tuple[bool, list[str]]:
    gitignore = ROOT / ".gitignore"
    problems = []
    if not gitignore.exists():
        return False, [".gitignore não encontrado na raiz do projeto"]
    content = gitignore.read_text(encoding="utf-8", errors="replace")
    for pattern in GITIGNORE_PATTERNS_REQUIRED:
        if pattern not in content:
            problems.append(f"'{pattern}' não está no .gitignore")
    if GITIGNORE_EXCEPTION_REQUIRED not in content:
        problems.append(f"'{GITIGNORE_EXCEPTION_REQUIRED}' não está no .gitignore (o padrão .env.* esconde o .env.example)")
    return (len(problems) == 0), problems


def _check_server_cjs() -> tuple[bool, list[str]]:
    if not SERVER_CJS.exists():
        # Build ainda não foi gerado - não é uma falha deste script, é só
        # "rode npm run build antes de reempacotar".
        return True, ["platform_source/dist/server.cjs não existe ainda (build não gerado) - pulei esta checagem"]
    content = SERVER_CJS.read_text(encoding="utf-8", errors="replace")
    problems = []
    if re.search(r'model_hint\s*\|\|\s*"flux"', content):
        problems.append('dist/server.cjs ainda contém o hardcode antigo: model_hint || "flux" - rode "npm run build" de novo')
    if "resolveAllowedProxyTarget" not in content:
        problems.append("dist/server.cjs NÃO contém resolveAllowedProxyTarget (proteção de SSRF) - build está desatualizado, rode \"npm run build\" de novo")
    return (len(problems) == 0), problems


def _is_allowed_example_file(path: Path) -> bool:
    name = path.name.lower()
    return any(name.endswith(suffix) for suffix in SECRET_FILENAME_ALLOW_SUFFIXES)


def _check_no_leaked_secrets() -> tuple[bool, list[str]]:
    """Rede de segurança contra segredo real (achado GRAVE, Rodada 15):
    varre por nome de arquivo E por conteúdo. NUNCA apaga nada - só
    reporta [FALHA] com o caminho exato, porque apagar um segredo real
    da árvore de trabalho de alguém sem ser pedido é destrutivo (pode ser
    a credencial que a instância local de Firebase Sync dessa pessoa usa
    de verdade)."""
    problems = []
    seen = set()

    def _skip_dir(d: Path) -> bool:
        return d.name in SECRET_SCAN_SKIP_DIR_NAMES

    # 1) Por nome de arquivo
    for pattern in SECRET_FILENAME_PATTERNS:
        for match in ROOT.rglob(pattern):
            if any(_skip_dir(p) for p in match.relative_to(ROOT).parents):
                continue
            if _is_allowed_example_file(match):
                continue
            if match in seen:
                continue
            seen.add(match)
            problems.append(f"arquivo com nome de segredo conhecido: {match.relative_to(ROOT)}")

    # 2) Por conteúdo (pega credenciais com nome de arquivo não-óbvio)
    for path in ROOT.rglob("*"):
        if not path.is_file():
            continue
        if path.name in SECRET_SCAN_SELF_EXCLUDE_FILES:
            continue
        if path.suffix.lower() not in SECRET_SCAN_TEXT_EXTENSIONS:
            continue
        if any(_skip_dir(p) for p in path.relative_to(ROOT).parents):
            continue
        if _is_allowed_example_file(path):
            continue
        try:
            if path.stat().st_size > SECRET_SCAN_MAX_FILE_BYTES:
                continue
            content = path.read_text(encoding="utf-8", errors="ignore")
        except Exception:
            continue
        for marker in SECRET_CONTENT_MARKERS:
            if marker in content:
                if path in seen:
                    break
                seen.add(path)
                problems.append(f"conteúdo com marcador de credencial real ('{marker}'): {path.relative_to(ROOT)}")
                break
        else:
            # "private_key" com valor não-vazio (evita casar com os
            # .example.json, que sempre têm "private_key": "")
            m = re.search(r'"private_key"\s*:\s*"([^"]+)"', content)
            if m and m.group(1).strip():
                if path not in seen:
                    seen.add(path)
                    problems.append(f"conteúdo com \"private_key\" não-vazio: {path.relative_to(ROOT)}")

    return (len(problems) == 0), problems


def _check_never_publish_paths() -> tuple[bool, list[str]]:
    """FALHA de verdade (nunca só informa) se uma pasta/arquivo da lista
    NEVER_PUBLISH_* estiver presente - ver comentário completo na
    declaração das duas listas acima."""
    problems = []

    def _skip_dir(d: Path) -> bool:
        return d.name in SECRET_SCAN_SKIP_DIR_NAMES

    for path in ROOT.rglob("*"):
        if not path.is_dir():
            continue
        if any(_skip_dir(p) for p in path.relative_to(ROOT).parents):
            continue
        if path.name in NEVER_PUBLISH_DIR_NAMES:
            problems.append(f"pasta que nunca deve ir pro release/repo público: {path.relative_to(ROOT)}")

    for pattern in NEVER_PUBLISH_GLOB_PATTERNS:
        for match in ROOT.rglob(pattern):
            if any(_skip_dir(p) for p in match.relative_to(ROOT).parents):
                continue
            problems.append(f"arquivo que nunca deve ir pro release/repo público: {match.relative_to(ROOT)}")

    return (len(problems) == 0), problems


def _check_local_state_absent() -> tuple[bool, list[str]]:
    """Informativo (Rodada 15, achado #2): flags arquivos de estado local
    que não pertencem num release, sem apagar nada."""
    found = []
    for rel in LOCAL_STATE_PATHS_TO_FLAG:
        p = ROOT / rel
        if p.exists():
            kind = "pasta" if p.is_dir() else "arquivo"
            found.append(f"{rel} ({kind}) presente - estado local, não deve ir pro ZIP de release")
    return (len(found) == 0), found


def main() -> int:
    print("=" * 60)
    print(" verify_release_clean.py — release hygiene checks")
    print("=" * 60)

    print("\n[1/7] Removendo caminhos legados conhecidos...")
    for line in _remove_legacy_paths():
        print(f"  {line}")

    print("\n[2/7] Limpando cache/build do Python (__pycache__, .pytest_cache, *.egg-info)...")
    for line in _clean_cache_dirs():
        print(f"  {line}")

    print("\n[3/7] Conferindo .gitignore (bloqueios de preferência de engine)...")
    gitignore_ok, gitignore_problems = _check_gitignore()
    if gitignore_ok:
        print("  [OK] .gitignore bloqueia os arquivos de preferência de engine e preserva .env.example")
    else:
        for p in gitignore_problems:
            print(f"  [FALHA] {p}")

    print("\n[4/7] Conferindo platform_source/dist/server.cjs...")
    server_cjs_ok, server_cjs_notes = _check_server_cjs()
    if server_cjs_ok and not server_cjs_notes:
        print("  [OK] sem model_hint || \"flux\" e resolveAllowedProxyTarget presente")
    for n in server_cjs_notes:
        prefix = "[OK]" if server_cjs_ok else "[FALHA]"
        print(f"  {prefix} {n}")

    print("\n[5/7] Varrendo por segredo real (nome de arquivo + conteúdo)...")
    secrets_ok, secret_problems = _check_no_leaked_secrets()
    if secrets_ok:
        print("  [OK] nenhum segredo real encontrado")
    else:
        for p in secret_problems:
            print(f"  [FALHA] {p}")
        print("  [AÇÃO] NUNCA apague isso às cegas - pode ser um segredo real em uso local.")
        print("         Gere o ZIP com build_release_zip.py (allowlist via .gitignore), que")
        print("         nunca copia esses arquivos pro pacote pra começo de conversa.")

    print("\n[6/7] Conferindo pastas/arquivos que NUNCA podem ir pro release (private_server_reference, backups de hotfix)...")
    never_publish_ok, never_publish_problems = _check_never_publish_paths()
    if never_publish_ok:
        print("  [OK] nenhum caminho da lista NEVER_PUBLISH_* encontrado")
    else:
        for p in never_publish_problems:
            print(f"  [FALHA] {p}")
        print("  [AÇÃO] NÃO apague às cegas se for private_server_reference/ - é referência legítima")
        print("         pra manter LOCAL. Só não pode ir pro repo público/ZIP. Adicione ao")
        print("         .gitignore e rode 'git rm -r --cached <caminho>' se já foi commitado.")

    print("\n[7/7] Conferindo estado local que não deve ir pro release (informativo)...")
    local_state_ok, local_state_found = _check_local_state_absent()
    if local_state_ok:
        print("  [OK] nenhum estado local encontrado na árvore")
    else:
        for f in local_state_found:
            print(f"  [INFO] {f}")
        print("  [AÇÃO] Normal existir na sua árvore de trabalho - só não pode ir pro ZIP.")
        print("         Use build_release_zip.py em vez de zipar a pasta inteira.")

    all_ok = gitignore_ok and server_cjs_ok and secrets_ok and never_publish_ok
    print("\nResultado final")
    if all_ok:
        print("  [OK] tudo limpo")
    else:
        print("  [FALHA] ver itens acima")

    print("\n" + "=" * 60)
    if all_ok:
        print(" TUDO LIMPO — pode gerar o ZIP a partir desta árvore agora.")
    else:
        print(" AINDA HÁ PROBLEMAS — corrija antes de gerar o ZIP (veja [FALHA] acima).")
    print("=" * 60)

    return 0 if all_ok else 1


if __name__ == "__main__":
    sys.exit(main())
