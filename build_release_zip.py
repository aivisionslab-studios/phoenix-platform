"""
build_release_zip.py
=====================
PHX-NEW (Rodada 15 — resposta ao achado GRAVE de uma auditoria externa
real): um ZIP entregue continha `data/config/firestore_credentials.json`
com uma chave privada REAL de service account do Firebase/Google Cloud.
A causa raiz não era o código-fonte - era o PROCESSO de gerar o ZIP:
"copia a pasta inteira, com uma lista de exclusão mantida à mão" (`tar
--exclude=... | tar -x...`). Uma lista de exclusão manual sempre fica
incompleta - foi assim que `data/machine_id.json` (variante sem
"config/" no meio, faltando no .gitignore até esta rodada) também
escapou, junto do próprio segredo real.

Este script substitui esse processo por um allowlist de verdade: usa o
PRÓPRIO MECANISMO do .gitignore do projeto (via um repositório git
descartável, `git add -A` + `git ls-files`) pra decidir exatamente quais
arquivos entram - não uma cópia de pasta com exceções, um allowlist
positivo. Isso significa que qualquer arquivo novo de segredo/estado
local que alguém adicionar no futuro só entra no release se especifi-
camente REMOVIDO do .gitignore - o padrão oposto (seguro por padrão) do
que causou o vazamento desta rodada.

Passos:
  1. Cria um repositório git temporário DESCARTÁVEL dentro de um diretório
     temp (nunca no projeto real - não deixa nenhum `.git/` no projeto).
  2. Copia o projeto inteiro pra lá, roda `git add -A` (respeita o
     .gitignore de verdade) e lê `git ls-files` - essa é a lista exata de
     arquivos que vão pro release.
  3. Copia SÓ esses arquivos (preservando estrutura de pastas) pra um
     diretório de staging limpo.
  4. Roda as checagens de verify_release_clean.py CONTRA O STAGING (não
     contra o projeto real) - se algum segredo real ainda aparecer aqui
     depois do allowlist, é uma falha grave (o .gitignore tem um buraco)
     e o script PARA sem gerar o ZIP.
  5. Zipa o staging.

Rodar de dentro do diretório raiz do Phoenix:
    python3 build_release_zip.py --out /caminho/para/saida.zip

Sai com código 1 (sem gerar ZIP) se a checagem de segredo do staging
falhar - essa é a rede de segurança final antes de qualquer coisa sair
pra fora do ambiente de desenvolvimento.
"""
from __future__ import annotations

import argparse
import shutil
import subprocess
import sys
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent

sys.path.insert(0, str(ROOT))
import verify_release_clean as vrc  # noqa: E402


def _build_allowlisted_staging(staging_dir: Path) -> list[str]:
    """Cria um repo git descartável, calcula o allowlist via .gitignore
    real do projeto, e copia só esses arquivos pro staging. Devolve a
    lista de caminhos relativos copiados."""
    import tempfile

    with tempfile.TemporaryDirectory(prefix="phoenix_release_gitcheck_") as tmp:
        tmp_path = Path(tmp)
        work_copy = tmp_path / "src"
        # PHX-NOTE: copytree aqui copia TUDO (inclusive os segredos/estado
        # local reais) pra uma pasta temporária que nunca sai do disco
        # local e é apagada no fim do `with` - é só matéria-prima pro git
        # calcular o allowlist. Nada daqui é o ZIP final.
        shutil.copytree(
            ROOT,
            work_copy,
            ignore=shutil.ignore_patterns(
                ".git", ".audit-venv", ".venv", "venv", "node_modules",
                "__pycache__", ".pytest_cache", "*.egg-info",
            ),
        )

        subprocess.run(["git", "init", "-q"], cwd=work_copy, check=True)
        subprocess.run(["git", "add", "-A"], cwd=work_copy, check=True)
        result = subprocess.run(
            ["git", "ls-files"], cwd=work_copy, check=True,
            capture_output=True, text=True,
        )
        tracked_files = [line for line in result.stdout.splitlines() if line.strip()]

        if staging_dir.exists():
            shutil.rmtree(staging_dir)
        staging_dir.mkdir(parents=True)

        for rel in tracked_files:
            src = work_copy / rel
            dst = staging_dir / rel
            dst.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(src, dst)

    return tracked_files


def _run_secret_check_against(staging_dir: Path) -> tuple[bool, list[str]]:
    """Reusa a mesma lógica de verify_release_clean.py, mas apontada pro
    staging em vez do projeto real (ROOT) - via monkeypatch do módulo."""
    original_root = vrc.ROOT
    try:
        vrc.ROOT = staging_dir
        return vrc._check_no_leaked_secrets()
    finally:
        vrc.ROOT = original_root


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", required=True, help="Caminho do .zip de saída")
    parser.add_argument("--staging-dir", default=None, help="Diretório de staging (default: temp descartável)")
    parser.add_argument("--keep-staging", action="store_true", help="Não apaga o staging no final (debug)")
    args = parser.parse_args()

    out_path = Path(args.out).resolve()
    import tempfile
    staging_root = Path(args.staging_dir).resolve() if args.staging_dir else Path(tempfile.mkdtemp(prefix="phoenix_release_staging_"))
    staging_dir = staging_root / "PHOENIX 4.5"

    print("=" * 60)
    print(" build_release_zip.py — allowlist via .gitignore (Rodada 15)")
    print("=" * 60)

    print(f"\n[1/4] Calculando allowlist real via .gitignore (repo git descartável)...")
    tracked = _build_allowlisted_staging(staging_dir)
    print(f"  [OK] {len(tracked)} arquivos no allowlist, copiados pro staging.")

    print(f"\n[2/4] Confirmando que arquivos conhecidos de segredo/estado local NÃO entraram...")
    known_bad = [
        "data/config/firestore_credentials.json",
        "data/hardware.db",
        "data/machine_id.json",
        "data/config/machine.json",
        "data/config/machine_id.json",
    ]
    leaked = [p for p in known_bad if (staging_dir / p).exists()]
    if leaked:
        print("  [FALHA] Estes arquivos deveriam ter sido bloqueados pelo .gitignore mas entraram no staging:")
        for p in leaked:
            print(f"    - {p}")
        print("\n  ABORTANDO — corrija o .gitignore antes de gerar o ZIP.")
        if not args.keep_staging:
            shutil.rmtree(staging_root, ignore_errors=True)
        return 1
    print("  [OK] nenhum dos arquivos conhecidos de segredo/estado local entrou no staging.")

    print(f"\n[3/4] Varredura final de segredo (nome + conteúdo) no staging...")
    secrets_ok, secret_problems = _run_secret_check_against(staging_dir)
    if not secrets_ok:
        print("  [FALHA] Segredo real encontrado MESMO DEPOIS do allowlist (.gitignore tem um buraco novo):")
        for p in secret_problems:
            print(f"    - {p}")
        print("\n  ABORTANDO — não gerando ZIP com segredo real dentro.")
        if not args.keep_staging:
            shutil.rmtree(staging_root, ignore_errors=True)
        return 1
    print("  [OK] nenhum segredo real no staging.")

    print(f"\n[4/4] Gerando {out_path.name}...")
    out_path.parent.mkdir(parents=True, exist_ok=True)
    if out_path.exists():
        out_path.unlink()
    with zipfile.ZipFile(out_path, "w", zipfile.ZIP_DEFLATED) as zf:
        for rel in tracked:
            zf.write(staging_dir / rel, arcname=f"PHOENIX 4.5/{rel}")
    print(f"  [OK] ZIP gerado: {out_path} ({out_path.stat().st_size / 1e6:.1f} MB, {len(tracked)} arquivos)")

    if not args.keep_staging:
        shutil.rmtree(staging_root, ignore_errors=True)

    print("\n" + "=" * 60)
    print(" ZIP gerado a partir de um allowlist real (.gitignore), não de exclusão manual.")
    print("=" * 60)
    return 0


if __name__ == "__main__":
    sys.exit(main())
