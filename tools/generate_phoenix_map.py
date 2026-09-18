from pathlib import Path
import ast
import datetime


# PHX-FIX (auditoria 2026-08-28): o caminho absoluto do Windows local do
# autor (`E:\PHOENIX\AIVisions Platform\PHOENIX 3.0`) estava hardcoded
# aqui e foi parar publicado no GitHub dentro do próprio
# docs/PHOENIX_PROJECT_MAP.md gerado por este script (achado secundário
# de baixo risco - não é segredo, mas expõe a estrutura de pastas da
# máquina do desenvolvedor sem necessidade, e quebra o script pra
# qualquer outra pessoa/máquina que tentasse rodá-lo). ROOT agora é
# resolvido de forma relativa a este arquivo (tools/generate_phoenix_map.py
# -> raiz do projeto é o diretório pai de "tools"), funcionando em
# qualquer máquina/SO, igual ao padrão já usado em phoenix_kernel/paths.py.
ROOT = Path(__file__).resolve().parent.parent
OUTPUT = ROOT / "docs" / "PHOENIX_PROJECT_MAP.md"


IGNORE = {
    ".git",
    "__pycache__",
    "venv",
    ".venv",
    "node_modules",
    "cache",
    "logs"
}


def scan_files():
    files = []

    for path in ROOT.rglob("*"):
        if any(part in IGNORE for part in path.parts):
            continue

        if path.is_file():
            files.append(path)

    return files


def extract_python_info(file):
    result = {
        "imports": [],
        "classes": [],
        "functions": []
    }

    try:
        tree = ast.parse(
            file.read_text(
                encoding="utf-8",
                errors="ignore"
            )
        )

        for node in ast.walk(tree):

            if isinstance(node, ast.Import):
                for name in node.names:
                    result["imports"].append(name.name)

            elif isinstance(node, ast.ImportFrom):
                if node.module:
                    result["imports"].append(node.module)

            elif isinstance(node, ast.ClassDef):
                result["classes"].append(node.name)

            elif isinstance(node, ast.FunctionDef):
                result["functions"].append(node.name)

    except Exception:
        pass

    return result


def create_markdown():

    files = scan_files()

    with OUTPUT.open(
        "w",
        encoding="utf-8"
    ) as md:

        md.write("# PHOENIX PROJECT MAP\n\n")
        md.write(
            f"Gerado em: {datetime.datetime.now()}\n\n"
        )

        md.write("## Estrutura de arquivos\n\n")

        for file in files:
            relative = file.relative_to(ROOT)
            md.write(f"- `{relative}`\n")


        md.write("\n\n# Python Analysis\n\n")


        for file in files:

            if file.suffix != ".py":
                continue

            info = extract_python_info(file)

            md.write(
                f"\n## {file.relative_to(ROOT)}\n\n"
            )

            if info["imports"]:
                md.write("### Imports\n")
                for item in sorted(set(info["imports"])):
                    md.write(f"- {item}\n")

            if info["classes"]:
                md.write("\n### Classes\n")
                for item in info["classes"]:
                    md.write(f"- {item}\n")

            if info["functions"]:
                md.write("\n### Functions\n")
                for item in info["functions"]:
                    md.write(f"- {item}\n")


    print(
        f"Mapa criado: {OUTPUT}"
    )


if __name__ == "__main__":
    create_markdown()