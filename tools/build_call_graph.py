#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Phoenix Call Graph Analyzer
===========================
Percorre recursivamente todos os arquivos .py do projeto, usando o módulo ast
para extrair imports, classes, funções, chamadas e dependências.

Gera:
1. PHOENIX_CALL_GRAPH.md  - Relatório legível de quem chama quem.
2. PHOENIX_DEPENDENCY_GRAPH.json - Estrutura crua para consumo de IA.

Uso:
    python build_call_graph.py
"""

import ast
import json
import os
import sys
from pathlib import Path
from collections import defaultdict

# Configurações
ROOT_DIR = Path(__file__).resolve().parent
IGNORE_DIRS = {
    ".venv", "venv", "__pycache__", ".git", "build", "dist", 
    "logs", "node_modules", "backup", ".idea", ".vscode", "repos"
}
IGNORE_SUFFIXES = {".bak", ".pyc"}

# Alvos específicos para detectar
TARGET_KEYWORDS = {
    "llama.cpp", "llama-server", "sd-cli", "sd-server", "ollama",
    "comfyui", "whisper", "piper", "vulkan", "cuda", "opencl",
    "gguf", "ggml", "executionplan", "executionresult",
    "residentmanager", "runtimeengine", "plannerengine",
    "kernel", "apiengine", "mission"
}

HTTP_LIBS = {"requests", "httpx", "urllib", "socket"}
SUBPROCESS_LIBS = {"subprocess", "asyncio.create_subprocess_exec", "asyncio.create_subprocess_shell"}


class FileAnalysis:
    def __init__(self, filepath: Path):
        self.filepath = filepath
        self.relative_path = str(filepath.relative_to(ROOT_DIR)).replace("\\", "/")
        self.imports = []
        self.classes = []
        self.functions = []
        self.calls = []
        self.instantiates = []
        self.inherits = []
        self.http_calls = []
        self.subprocess_calls = []
        self.targets_hit = set()
        self.parse_file()

    def parse_file(self):
        try:
            source = self.filepath.read_text(encoding="utf-8")
            tree = ast.parse(source, filename=str(self.filepath))
        except SyntaxError:
            return
        except Exception:
            return

        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    self.imports.append(alias.name)
                    self._check_targets(alias.name)

            elif isinstance(node, ast.ImportFrom):
                module = node.module or ""
                self.imports.append(module)
                self._check_targets(module)

            elif isinstance(node, ast.ClassDef):
                self.classes.append(node.name)
                self._check_targets(node.name)
                for base in node.bases:
                    if isinstance(base, ast.Name):
                        self.inherits.append(base.id)
                    elif isinstance(base, ast.Attribute):
                        self.inherits.append(base.attr)

            elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                self.functions.append(node.name)

            elif isinstance(node, ast.Call):
                func = node.func
                if isinstance(func, ast.Name):
                    self.calls.append(func.id)
                    if func.id[0].isupper():
                        self.instantiates.append(func.id)
                    self._check_targets(func.id)

                elif isinstance(func, ast.Attribute):
                    attr = func.attr
                    self.calls.append(attr)
                    self._check_targets(attr)
                    if isinstance(func.value, ast.Name):
                        mod = func.value.id
                        if mod in HTTP_LIBS:
                            self.http_calls.append(f"{mod}.{attr}")
                        if "subprocess" in str(func.value):
                            self.subprocess_calls.append(f"subprocess.{attr}")

    def _check_targets(self, name: str):
        name_lower = name.lower()
        for target in TARGET_KEYWORDS:
            if target in name_lower:
                self.targets_hit.add(target)


def scan_project():
    """Percorre o projeto e analisa todos os arquivos .py válidos."""
    analyses = []
    
    for item in ROOT_DIR.rglob("*.py"):
        if any(part in IGNORE_DIRS for part in item.parts):
            continue
        if item.suffix in IGNORE_SUFFIXES:
            continue
        if item.name == Path(__file__).name:
            continue
            
        analyses.append(FileAnalysis(item))
        
    return analyses


def build_reverse_index(analyses):
    """Cria um índice: para cada classe/função, quem a chama."""
    reverse_calls = defaultdict(list)
    all_defined_symbols = set()
    
    for analysis in analyses:
        for cls in analysis.classes:
            all_defined_symbols.add(cls)
        for func in analysis.functions:
            all_defined_symbols.add(func)
            
    for analysis in analyses:
        for call in analysis.calls:
            if call in all_defined_symbols:
                reverse_calls[call].append(analysis.relative_path)
                
    return reverse_calls, all_defined_symbols


def generate_json(analyses, output_path: Path):
    """Gera o JSON com a estrutura crua."""
    data = []
    for analysis in analyses:
        data.append({
            "file": analysis.relative_path,
            "imports": analysis.imports,
            "classes": analysis.classes,
            "functions": analysis.functions,
            "calls": analysis.calls,
            "instantiates": analysis.instantiates,
            "inherits": analysis.inherits,
            "http_calls": analysis.http_calls,
            "subprocess": analysis.subprocess_calls,
            "drivers": list(analysis.targets_hit)
        })
    
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)


def generate_markdown(analyses, reverse_calls, all_defined_symbols, output_path: Path):
    """Gera o relatório Markdown legível."""
    lines = []
    lines.append("# PHOENIX CALL GRAPH\n")
    lines.append("Documento gerado automaticamente via análise AST do código-fonte.\n")
    lines.append("Nenhuma hipótese. Apenas fatos extraídos do parse do Python.\n\n")
    
    # 1. Arquivos Analisados
    lines.append("## 1. Arquivos Analisados\n")
    for analysis in analyses:
        lines.append(f"- `{analysis.relative_path}`")
    lines.append("\n---\n\n")
    
    # 2. Grafo de Imports (Quem importa quem)
    lines.append("## 2. Grafo de Imports\n")
    for analysis in analyses:
        if not analysis.imports:
            continue
        lines.append(f"### `{analysis.relative_path}`")
        for imp in analysis.imports:
            lines.append(f"  - Importa: `{imp}`")
        lines.append("")
    lines.append("\n---\n\n")
    
    # 3. Classes e Herança
    lines.append("## 3. Classes e Herança\n")
    for analysis in analyses:
        if not analysis.classes:
            continue
        lines.append(f"### `{analysis.relative_path}`")
        for cls in analysis.classes:
            lines.append(f"  - Classe: `{cls}`")
        lines.append("")
    lines.append("\n---\n\n")
    
    # 4. Código Morto (Classes/Funções nunca chamadas)
    lines.append("## 4. Código Morto (Símbolos definidos mas nunca chamados no projeto)\n")
    called_symbols = set(reverse_calls.keys())
    dead_symbols = all_defined_symbols - called_symbols
    
    if dead_symbols:
        for sym in sorted(dead_symbols):
            lines.append(f"- `{sym}`")
    else:
        lines.append("Nenhum símbolo órfão detectado.")
    lines.append("\n---\n\n")
    
    # 5. Instanciações (Quem cria quem)
    lines.append("## 5. Instanciações (Quem cria quem)\n")
    for analysis in analyses:
        if not analysis.instantiates:
            continue
        lines.append(f"### `{analysis.relative_path}`")
        for inst in analysis.instantiates:
            lines.append(f"  - Instancia: `{inst}`")
        lines.append("")
    lines.append("\n---\n\n")
    
    # 6. Chamadas de Sistema (HTTP / Subprocess)
    lines.append("## 6. Chamadas de Sistema (HTTP e Subprocess)\n")
    found_system_calls = False
    for analysis in analyses:
        if analysis.http_calls or analysis.subprocess_calls:
            found_system_calls = True
            lines.append(f"### `{analysis.relative_path}`")
            if analysis.http_calls:
                lines.append("  - **HTTP:**")
                for http in analysis.http_calls:
                    lines.append(f"    - `{http}`")
            if analysis.subprocess_calls:
                lines.append("  - **Subprocess:**")
                for sub in analysis.subprocess_calls:
                    lines.append(f"    - `{sub}`")
            lines.append("")
    if not found_system_calls:
        lines.append("Nenhuma chamada HTTP ou Subprocess explícita detectada.")
    lines.append("\n---\n\n")
    
    # 7. Alvos Específicos Detectados (llama.cpp, ollama, etc)
    lines.append("## 7. Alvos Específicos Detectados (llama.cpp, ollama, vulkan, etc)\n")
    target_map = defaultdict(list)
    for analysis in analyses:
        for target in analysis.targets_hit:
            target_map[target].append(analysis.relative_path)
            
    if target_map:
        for target, files in sorted(target_map.items()):
            lines.append(f"### `{target}`")
            for f in files:
                lines.append(f"  - Encontrado em: `{f}`")
            lines.append("")
    else:
        lines.append("Nenhum alvo específico detectado.")
    lines.append("\n---\n\n")
    
    # 8. Índice Reverso (Quem chama um símbolo)
    lines.append("## 8. Índice Reverso de Chamadas\n")
    lines.append("Para cada símbolo (classe ou função) definido no projeto, lista quem o chama.\n")
    if reverse_calls:
        for symbol, callers in sorted(reverse_calls.items()):
            lines.append(f"### `{symbol}`")
            for caller in callers:
                lines.append(f"  - Chamado por: `{caller}`")
            lines.append("")
    else:
        lines.append("Nenhuma chamada interna detectada.")
    
    with open(output_path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))


def main():
    print("=" * 60)
    print(" PHOENIX CALL GRAPH ANALYZER ")
    print("=" * 60)
    print(f"Analisando diretório: {ROOT_DIR}\n")
    
    analyses = scan_project()
    print(f"[OK] {len(analyses)} arquivos Python analisados.")
    
    reverse_calls, all_defined_symbols = build_reverse_index(analyses)
    print(f"[OK] {len(all_defined_symbols)} símbolos (classes/funcs) indexados.")
    
    md_path = ROOT_DIR / "PHOENIX_CALL_GRAPH.md"
    json_path = ROOT_DIR / "PHOENIX_DEPENDENCY_GRAPH.json"
    
    generate_json(analyses, json_path)
    print(f"[OK] JSON gerado: {json_path.name}")
    
    generate_markdown(analyses, reverse_calls, all_defined_symbols, md_path)
    print(f"[OK] Markdown gerado: {md_path.name}")
    
    print("\n[✓] Análise concluída com sucesso.")


if __name__ == "__main__":
    main()