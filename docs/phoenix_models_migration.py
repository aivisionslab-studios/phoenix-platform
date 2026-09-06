"""
phoenix_models_migration.py
===========================
Expande a estrutura Workstations/Models da Phoenix 3.0 para multi-modal.
Cria Chat, Image, Audio, Vision, Embeddings com descoberta dinâmica.
Zero caminhos hardcoded. Idempotente. Apenas biblioteca padrão.
"""

import json
import os
import shutil
import hashlib
import platform
from pathlib import Path
from datetime import datetime, timezone

PROJECT_ROOT = Path(__file__).resolve().parent
REPORT_FILE = PROJECT_ROOT / "models_migration_report.md"

report = {
    "created": [], "altered": [], "moved": [], "backups": [],
    "errors": [], "warnings": [], "scanned": 0
}

def log(cat, msg):
    report[cat].append(msg)
    print(f"[{cat.upper()}] {msg}")

def backup_file(f: Path):
    if f.exists() and f.is_file():
        bak = f.with_suffix(f.suffix + ".bak")
        if not bak.exists():
            shutil.copy2(f, bak)
            log("backups", f"Backup: {bak.name}")

# ============================================================
# FASE 1 — phoenix_kernel/paths.py
# ============================================================

PATHS_PY = '''"""
PhoenixPaths — Resolução dinâmica de caminhos.
Nenhum código Python deve conter C:\\, D:\\, E:\\ ou /opt.
Tudo passa por aqui.
"""
from __future__ import annotations
import json
import platform
from pathlib import Path


class PhoenixPaths:
    _manifest = None

    @classmethod
    def _load_manifest(cls) -> dict:
        if cls._manifest is not None:
            return cls._manifest
        if platform.system() == "Windows":
            p = Path("C:/ProgramData/Phoenix/storage.json")
        else:
            p = Path("/etc/phoenix/storage.json")
        if p.exists():
            with open(p, "r", encoding="utf-8") as f:
                cls._manifest = json.load(f)
        else:
            cls._manifest = {"workspace": str(Path("data/workstations").resolve())}
        return cls._manifest

    @classmethod
    def get_workspace(cls) -> Path:
        ws = Path(cls._load_manifest().get("workspace", "."))
        return ws if ws.is_absolute() else Path("data/workstations").resolve()

    @classmethod
    def get_models_base(cls) -> Path:
        return cls.get_workspace() / "Models"

    @classmethod
    def get_category_path(cls, category: str, subcategory: str = None) -> Path:
        base = cls.get_models_base() / category
        return base / subcategory if subcategory else base

    @classmethod
    def get_model_path(cls, category: str, subcategory: str, filename: str) -> Path:
        return cls.get_category_path(category, subcategory) / filename

    @classmethod
    def get_cache_dir(cls) -> Path:
        return cls.get_workspace().parent / "Cache"

    @classmethod
    def get_temp_dir(cls) -> Path:
        return cls.get_workspace().parent / "Temp"

    @classmethod
    def get_downloads_dir(cls) -> Path:
        return cls.get_workspace().parent / "Downloads"

    @classmethod
    def get_outputs_dir(cls) -> Path:
        return cls.get_workspace().parent / "Outputs"

    @classmethod
    def get_inventory_db(cls) -> Path:
        return cls.get_workspace().parent / "data" / "models_inventory.json"
'''

# ============================================================
# FASE 2 — ModelScanner
# ============================================================

SCANNER_PY = '''"""
ModelScanner — Varre Models/ e constrói inventário.
"""
from __future__ import annotations
import hashlib
from pathlib import Path
from datetime import datetime, timezone

try:
    from phoenix_kernel.paths import PhoenixPaths
except ImportError:
    PhoenixPaths = None

SUPPORTED = {
    ".gguf": "GGUF",
    ".safetensors": "Safetensors",
    ".onnx": "ONNX",
    ".mlx": "MLX",
    ".bin": "Bin",
    ".pt": "PyTorch",
    ".ckpt": "Checkpoint",
}


class ModelScanner:

    @staticmethod
    def scan_all(models_base: Path = None) -> list[dict]:
        if models_base is None:
            if PhoenixPaths:
                models_base = PhoenixPaths.get_models_base()
            else:
                models_base = Path("data/workstations/Models")
        if not models_base.exists():
            return []

        inventory = []
        for cat_dir in sorted(models_base.iterdir()):
            if not cat_dir.is_dir() or cat_dir.name.startswith("."):
                continue
            category = cat_dir.name
            for sub_dir in sorted(cat_dir.iterdir()):
                if not sub_dir.is_dir() or sub_dir.name.startswith("."):
                    continue
                subcategory = sub_dir.name
                for f in sub_dir.rglob("*"):
                    if f.is_file() and f.suffix.lower() in SUPPORTED:
                        inventory.append(ModelScanner._record(f, category, subcategory))
        return inventory

    @staticmethod
    def _record(f: Path, category: str, subcategory: str) -> dict:
        st = f.stat()
        return {
            "name": f.stem,
            "filename": f.name,
            "relative_path": str(f.relative_to(PhoenixPaths.get_models_base())) if PhoenixPaths else str(f),
            "category": category,
            "subcategory": subcategory,
            "format": SUPPORTED.get(f.suffix.lower(), "Unknown"),
            "size_bytes": st.st_size,
            "size_mb": round(st.st_size / (1024 * 1024), 2),
            "modified_at": datetime.fromtimestamp(st.st_mtime, tz=timezone.utc).isoformat(),
            "sha256_prefix": ModelScanner._hash(f),
        }

    @staticmethod
    def _hash(f: Path) -> str:
        h = hashlib.sha256()
        try:
            with open(f, "rb") as fh:
                for _ in range(8):  # Apenas primeiros 64KB para velocidade
                    chunk = fh.read(8192)
                    if not chunk:
                        break
                    h.update(chunk)
            return h.hexdigest()[:16]
        except OSError:
            return "unreadable"
'''

# ============================================================
# FASE 3 — Inventory
# ============================================================

INVENTORY_PY = '''"""
ModelInventory — Persiste o inventário em disco.
"""
from __future__ import annotations
import json
from pathlib import Path
from datetime import datetime, timezone

try:
    from phoenix_kernel.paths import PhoenixPaths
    from phoenix_kernel.models.model_scanner import ModelScanner
except ImportError:
    PhoenixPaths = None
    ModelScanner = None


class ModelInventory:

    @staticmethod
    def get_db_path() -> Path:
        if PhoenixPaths:
            return PhoenixPaths.get_inventory_db()
        return Path("data/models_inventory.json")

    @staticmethod
    def refresh() -> int:
        records = ModelScanner.scan_all() if ModelScanner else []
        db = ModelInventory.get_db_path()
        db.parent.mkdir(parents=True, exist_ok=True)
        with open(db, "w", encoding="utf-8") as f:
            json.dump({
                "total": len(records),
                "models": records,
                "scanned_at": datetime.now(timezone.utc).isoformat(),
            }, f, indent=2, ensure_ascii=False)
        return len(records)

    @staticmethod
    def load() -> dict:
        db = ModelInventory.get_db_path()
        if not db.exists():
            return {"total": 0, "models": []}
        with open(db, "r", encoding="utf-8") as f:
            return json.load(f)

    @staticmethod
    def find(name: str = None, category: str = None, fmt: str = None) -> list[dict]:
        db = ModelInventory.load()
        results = db.get("models", [])
        if name:
            results = [m for m in results if name.lower() in m["name"].lower()]
        if category:
            results = [m for m in results if m["category"] == category]
        if fmt:
            results = [m for m in results if m["format"] == fmt]
        return results
'''

# ============================================================
# FASE 4 — Estrutura de Pastas
# ============================================================

FOLDER_STRUCTURE = {
    "Models": {
        "Chat": ["GGUF", "MLX", "ONNX", "Safetensors", "GPTQ", "AWQ", "EXL2"],
        "Image": ["StableDiffusion", "Flux", "SDXL", "SD3", "Wan",
                  "ControlNet", "VAE", "CLIP", "LoRA"],
        "Audio": ["Whisper", "XTTS", "Bark", "RVC"],
        "Vision": ["Florence", "CLIP", "SAM", "OCR"],
        "Embeddings": [],
        "Rerank": [],
    }
}

def create_folder_structure(workspace: Path):
    """Cria toda a árvore de pastas dinamicamente."""
    models_base = workspace / "Models"
    for category, subcats in FOLDER_STRUCTURE.items():
        cat_dir = models_base / category
        cat_dir.mkdir(parents=True, exist_ok=True)
        log("created", f"Pasta: Models/{category}/")

        for sub in subcats:
            sub_dir = cat_dir / sub
            sub_dir.mkdir(parents=True, exist_ok=True)
            log("created", f"  └── {sub}/")

        # Garante que cada subpasta tenha um __init__.py vazio
        init_file = cat_dir / "__init__.py"
        if not init_file.exists():
            init_file.write_text("")
            log("created", f"  └── __init__.py")

    # Pastas auxiliares
    for aux in ["Cache", "Temp", "Downloads", "Outputs"]:
        d = workspace.parent / aux
        d.mkdir(parents=True, exist_ok=True)
        log("created", f"{aux}/")

    # Garante que Models/ também tenha __init__.py
    init = models_base / "__init__.py"
    if not init.exists():
        init.write_text("")

# ============================================================
# FASE 5 — Migração de Modelos Existentes
# ============================================================

def migrate_existing_models(workspace: Path):
    """Move modelos soltos em Models/ para Models/Image/ (compatibilidade)."""
    models_base = workspace / "Models"
    if not models_base.exists():
        log("warnings", "Models/ não existe ainda. Pulando migração.")
        return

    image_dir = models_base / "Image"
    moved = 0

    for f in models_base.iterdir():
        if not f.is_file():
            continue
        if f.suffix.lower() not in {".gguf", ".safetensors", ".onnx", ".bin", ".pt"}:
            continue

        # Se é um modelo de imagem (FLUX, SD, etc.)
        name_lower = f.name.lower()
        is_image = any(kw in name_lower for kw in [
            "flux", "sd", "sdxl", "dreamshaper", "anything",
            "vae", "clip", "t5xxl", "ae.", "controlnet", "lora"
        ])

        if is_image:
            # Tenta mover para subcategoria apropriada
            subcat = "Flux" if "flux" in name_lower else "StableDiffusion"
            dest_dir = image_dir / subcat
            dest_dir.mkdir(parents=True, exist_ok=True)
            dest = dest_dir / f.name

            if dest.exists():
                log("warnings", f"Já existe em Image/{subcat}/{f.name}. Pulando.")
                continue

            try:
                shutil.move(str(f), str(dest))
                log("moved", f"Models/{f.name} → Models/Image/{subcat}/{f.name}")
                moved += 1
            except Exception as e:
                log("errors", f"Falha ao mover {f.name}: {e}")

    if moved == 0:
        log("warnings", "Nenhum modelo solto encontrado em Models/ para migrar.")

# ============================================================
# FASE 6 — Atualizar catalog/models.json
# ============================================================

NEW_CATALOG = {
    "qwen3:8b": {
        "name": "Qwen3 8B Instruct",
        "url": "https://huggingface.co/Qwen/Qwen3-8B-GGUF/resolve/main/Qwen3-8B-Q4_K_M.gguf",
        "type": "llm",
        "category": "Chat",
        "format": "GGUF",
        "backend": ["llama.cpp", "ollama"],
        "destination_folder": "Chat/GGUF/Qwen",
        "filename": "Qwen3-8B-Q4_K_M.gguf",
        "ollama_tag": "qwen3:8b"
    },
    "qwen3:4b": {
        "name": "Qwen3 4B Instruct",
        "url": "ollama://qwen3:4b",
        "type": "llm",
        "category": "Chat",
        "format": "GGUF",
        "backend": ["ollama"],
        "destination_folder": "Chat/GGUF/Qwen",
        "filename": "qwen3-4b.gguf"
    },
    "mistral7b": {
        "name": "Mistral 7B Instruct",
        "url": "ollama://mistral:7b",
        "type": "llm",
        "category": "Chat",
        "format": "GGUF",
        "backend": ["ollama", "llama.cpp"],
        "destination_folder": "Chat/GGUF/Mistral",
        "filename": "mistral-7b.gguf"
    },
    "tinyllama": {
        "name": "TinyLlama 1.1B Chat",
        "url": "ollama://tinyllama:1.1b",
        "type": "llm",
        "category": "Chat",
        "format": "GGUF",
        "backend": ["ollama", "llama.cpp"],
        "destination_folder": "Chat/GGUF/TinyLlama",
        "filename": "tinyllama-1.1b.gguf"
    },
    "flux": {
        "name": "FLUX.1-schnell (GGUF Q4)",
        "url": "https://huggingface.co/leejet/FLUX.1-schnell-gguf/resolve/main/flux1-schnell-Q4_0.gguf",
        "type": "image",
        "category": "Image",
        "format": "GGUF",
        "backend": ["stable-diffusion.cpp"],
        "destination_folder": "Image/Flux",
        "filename": "flux1-schnell-Q4_0.gguf",
        "components": {
            "vae": {"destination_folder": "Image/VAE", "filename": "ae.safetensors",
                    "url": "https://huggingface.co/leejet/FLUX.1-schnell-gguf/resolve/main/ae.safetensors"},
            "clip_l": {"destination_folder": "Image/CLIP", "filename": "clip_l.safetensors",
                       "url": "https://huggingface.co/leejet/FLUX.1-schnell-gguf/resolve/main/clip_l.safetensors"},
            "t5xxl": {"destination_folder": "Image/Embeddings", "filename": "t5xxl_fp16.safetensors",
                      "url": "https://huggingface.co/leejet/FLUX.1-schnell-gguf/resolve/main/t5xxl_fp16.safetensors"}
        },
        "default_generation": {"steps": 4, "cfg": 1.0, "width": 1024, "height": 1024}
    },
    "sd15": {
        "name": "Stable Diffusion 1.5 (GGUF Q4)",
        "url": "https://huggingface.co/legegenki/sd_gguf/resolve/main/sd-v1-5-q4_0.gguf",
        "type": "image",
        "category": "Image",
        "format": "GGUF",
        "backend": ["stable-diffusion.cpp"],
        "destination_folder": "Image/StableDiffusion",
        "filename": "sd-v1-5-q4_0.gguf",
        "default_generation": {"steps": 20, "cfg": 7.0, "width": 512, "height": 512}
    },
    "sdxl": {
        "name": "Stable Diffusion XL (GGUF Q4)",
        "url": "https://huggingface.co/legegenki/sd_gguf/resolve/main/sdxl-1.0-q4_0.gguf",
        "type": "image",
        "category": "Image",
        "format": "GGUF",
        "backend": ["stable-diffusion.cpp"],
        "destination_folder": "Image/StableDiffusion",
        "filename": "sdxl-1.0-q4_0.gguf",
        "default_generation": {"steps": 20, "cfg": 7.0, "width": 1024, "height": 1024}
    }
}

def update_catalog():
    """Atualiza catalog/models.json com a nova estrutura."""
    catalog_dir = PROJECT_ROOT / "catalog"
    catalog_dir.mkdir(parents=True, exist_ok=True)
    catalog_path = catalog_dir / "models.json"

    backup_file(catalog_path)

    with open(catalog_path, "w", encoding="utf-8") as f:
        json.dump(NEW_CATALOG, f, indent=2, ensure_ascii=False)
    log("altered", "catalog/models.json atualizado com nova estrutura multi-modal.")

# ============================================================
# FASE 7 — Patch Drivers
# ============================================================

LLAMA_CPP_PATCH = '''
    def _find_model_file(self, model_name: str) -> Path | None:
        from phoenix_kernel.paths import PhoenixPaths
        clean = model_name.split(":")[0].replace("/", "-").lower()
        models_dir = PhoenixPaths.get_category_path("Chat", "GGUF")
        if not models_dir.exists():
            models_dir = PhoenixPaths.get_models_base()
            if not models_dir.exists():
                return None
        matches = list(models_dir.glob(f"*{clean}*.gguf"))
        for m in matches:
            if m.stat().st_size >= 50 * 1024 * 1024:
                return m
        return matches[0] if matches else None
'''

SD_CPP_PATCH = '''
    def _find_model_file(self, model_name: str) -> Path | None:
        from phoenix_kernel.paths import PhoenixPaths
        clean = model_name.split(":")[0].replace("/", "-").lower()
        image_dir = PhoenixPaths.get_category_path("Image")
        if not image_dir.exists():
            return None
        matches = list(image_dir.rglob(f"*{clean}*.gguf"))
        return matches[0] if matches else None

    def _find_component(self, comp_name: str) -> Path | None:
        from phoenix_kernel.paths import PhoenixPaths
        image_dir = PhoenixPaths.get_category_path("Image")
        if not image_dir.exists():
            return None
        matches = list(image_dir.rglob(f"*{comp_name}*"))
        return matches[0] if matches else None
'''

def patch_drivers():
    """Insere métodos de descoberta dinâmica nos drivers."""
    drivers_dir = PROJECT_ROOT / "phoenix_kernel" / "runtime" / "drivers"
    if not drivers_dir.exists():
        # Tenta caminho antigo
        drivers_dir = PROJECT_ROOT / "phoenix_kernel" / "04_runtime" / "drivers"
        if not drivers_dir.exists():
            log("warnings", "Pasta de drivers não encontrada. Pulando patch.")
            return

    # Patch llama_cpp.py
    llama_file = drivers_dir / "llama_cpp.py"
    if llama_file.exists():
        backup_file(llama_file)
        content = llama_file.read_text(encoding="utf-8")
        if "_find_model_file" not in content:
            # Insere antes da classe ou no final
            if "class LlamaCppDriver" in content:
                idx = content.find("class LlamaCppDriver")
                insert_pos = content.find("\n", idx) + 1
                content = content[:insert_pos] + LLAMA_CPP_PATCH + content[insert_pos:]
            else:
                content += LLAMA_CPP_PATCH
            llama_file.write_text(content, encoding="utf-8")
            log("altered", "llama_cpp.py: _find_model_file adicionado (PhoenixPaths).")
        else:
            log("warnings", "llama_cpp.py já possui _find_model_file.")

    # Patch sd_cpp.py
    sd_file = drivers_dir / "sd_cpp.py"
    if sd_file.exists():
        backup_file(sd_file)
        content = sd_file.read_text(encoding="utf-8")
        if "_find_model_file" not in content:
            if "class SdCppDriver" in content:
                idx = content.find("class SdCppDriver")
                insert_pos = content.find("\n", idx) + 1
                content = content[:insert_pos] + SD_CPP_PATCH + content[insert_pos:]
            else:
                content += SD_CPP_PATCH
            sd_file.write_text(content, encoding="utf-8")
            log("altered", "sd_cpp.py: _find_model_file e _find_component adicionados.")
        else:
            log("warnings", "sd_cpp.py já possui _find_model_file.")

# ============================================================
# FASE 8 — Relatório
# ============================================================

def generate_report():
    lines = [
        "# Phoenix 3.0 — Migração Multi-Modal",
        f"**Data:** {datetime.now(timezone.utc).isoformat()}",
        f"**Workspace:** Descoberto dinamicamente via storage.json",
        "",
        "## Resumo",
        f"- Arquivos criados: {len(report['created'])}",
        f"- Arquivos alterados: {len(report['altered'])}",
        f"- Modelos movidos: {len(report['moved'])}",
        f"- Backups: {len(report['backups'])}",
        f"- Erros: {len(report['errors'])}",
        f"- Avisos: {len(report['warnings'])}",
        f"- Modelos no inventário: {report['scanned']}",
        "",
    ]
    if report["created"]:
        lines.append("## Pastas Criadas")
        for c in report["created"]:
            lines.append(f"- {c}")
        lines.append("")
    if report["moved"]:
        lines.append("## Modelos Migrados")
        for m in report["moved"]:
            lines.append(f"- {m}")
        lines.append("")
    if report["altered"]:
        lines.append("## Arquivos Alterados")
        for a in report["altered"]:
            lines.append(f"- {a}")
        lines.append("")
    if report["errors"]:
        lines.append("## Erros")
        for e in report["errors"]:
            lines.append(f"- {e}")
        lines.append("")
    if report["warnings"]:
        lines.append("## Avisos")
        for w in report["warnings"]:
            lines.append(f"- {w}")
        lines.append("")

    REPORT_FILE.write_text("\n".join(lines), encoding="utf-8")
    print(f"\n[INFO] Relatório: {REPORT_FILE}")

# ============================================================
# EXECUÇÃO PRINCIPAL
# ============================================================

def discover_workspace() -> Path:
    """Lê storage.json para descobrir workspace dinamicamente."""
    if platform.system() == "Windows":
        storage = Path("C:/ProgramData/Phoenix/storage.json")
    else:
        storage = Path("/etc/phoenix/storage.json")

    if storage.exists():
        with open(storage, "r", encoding="utf-8") as f:
            data = json.load(f)
        ws = Path(data.get("workspace", ""))
        if ws and ws.exists():
            print(f"[INFO] Workspace descoberto: {ws}")
            return ws

    # Fallback: procura por Workstations no projeto
    local = PROJECT_ROOT / "data" / "workstations"
    local.mkdir(parents=True, exist_ok=True)
    print(f"[INFO] Workspace fallback: {local}")
    return local

def main():
    print("=" * 60)
    print("  PHOENIX 3.0 — MIGRAÇÃO MULTI-MODAL")
    print("=" * 60)

    # --- FASE 1: Criar paths.py ---
    print("\n[FASE 1] Criando phoenix_kernel/paths.py...")
    kernel_dir = PROJECT_ROOT / "phoenix_kernel"
    kernel_dir.mkdir(exist_ok=True)
    paths_file = kernel_dir / "paths.py"
    backup_file(paths_file)
    paths_file.write_text(PATHS_PY, encoding="utf-8")
    log("created", "phoenix_kernel/paths.py (PhoenixPaths)")

    # __init__.py do kernel
    init = kernel_dir / "__init__.py"
    if not init.exists():
        init.write_text("")
        log("created", "phoenix_kernel/__init__.py")

    # --- FASE 2: Descobrir workspace ---
    print("\n[FASE 2] Descobrindo workspace...")
    workspace = discover_workspace()

    # --- FASE 3: Criar estrutura de pastas ---
    print("\n[FASE 3] Criando estrutura de pastas...")
    create_folder_structure(workspace)

    # --- FASE 4: Migrar modelos existentes ---
    print("\n[FASE 4] Migrando modelos existentes...")
    migrate_existing_models(workspace)

    # --- FASE 5: Criar model_scanner.py ---
    print("\n[FASE 5] Criando model_scanner.py...")
    models_dir = kernel_dir / "models"
    models_dir.mkdir(exist_ok=True)
    scanner_file = models_dir / "model_scanner.py"
    backup_file(scanner_file)
    scanner_file.write_text(SCANNER_PY, encoding="utf-8")
    log("created", "phoenix_kernel/models/model_scanner.py")

    # --- FASE 6: Criar inventory.py ---
    print("\n[FASE 6] Criando inventory.py...")
    inv_file = models_dir / "inventory.py"
    backup_file(inv_file)
    inv_file.write_text(INVENTORY_PY, encoding="utf-8")
    log("created", "phoenix_kernel/models/inventory.py")

    # __init__.py de models
    models_init = models_dir / "__init__.py"
    if not models_init.exists():
        models_init.write_text("")

    # --- FASE 7: Atualizar catalog/models.json ---
    print("\n[FASE 7] Atualizando catalog/models.json...")
    update_catalog()

    # --- FASE 8: Patch drivers ---
    print("\n[FASE 8] Aplicando patch nos drivers...")
    patch_drivers()

    # --- FASE 9: Scan inicial ---
    print("\n[FASE 9] Executando scan inicial...")
    try:
        import sys
        sys.path.insert(0, str(PROJECT_ROOT))
        from phoenix_kernel.models.model_scanner import ModelScanner
        from phoenix_kernel.paths import PhoenixPaths

        # Força o PhoenixPaths a usar o workspace descoberto
        PhoenixPaths._manifest = {"workspace": str(workspace)}

        records = ModelScanner.scan_all(PhoenixPaths.get_models_base())
        report["scanned"] = len(records)

        # Persiste inventário
        from phoenix_kernel.models.inventory import ModelInventory
        ModelInventory.refresh()
        log("altered", f"models_inventory.json: {len(records)} modelo(s) catalogado(s).")

        if records:
            print("\n  Modelos encontrados:")
            for r in records:
                print(f"    [{r['category']}/{r['subcategory']}] {r['name']} ({r['format']}, {r['size_mb']:.1f} MB)")
        else:
            print("  Nenhum modelo encontrado ainda. Use o painel para baixar.")

    except Exception as e:
        log("errors", f"Falha no scan inicial: {e}")

    # --- RELATÓRIO ---
    print("\n" + "=" * 60)
    generate_report()
    print("=" * 60)
    print("  MIGRAÇÃO CONCLUÍDA!")
    print("=" * 60)

if __name__ == "__main__":
    main()