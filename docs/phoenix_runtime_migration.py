"""
phoenix_runtime_migration.py
Idempotent script to migrate Phoenix Kernel to the new decoupled Runtime Architecture.
"""

import os
import re
import shutil
from pathlib import Path
from datetime import datetime

PROJECT_ROOT = Path.cwd()
KERNEL_DIR = PROJECT_ROOT / "phoenix_kernel"
RUNTIME_DIR = KERNEL_DIR / "runtime"
REPORT_FILE = PROJECT_ROOT / "migration_report.md"

report_data = {
    "created": [],
    "altered": [],
    "moved": [],
    "backups": [],
    "imports_fixed": [],
    "errors": [],
    "warnings": []
}

def log(category, message):
    report_data[category].append(message)
    print(f"[{category.upper()}] {message}")

def backup_file(file_path: Path):
    if file_path.exists() and file_path.is_file():
        backup_path = file_path.with_suffix(file_path.suffix + ".bak")
        if not backup_path.exists():
            shutil.copy2(file_path, backup_path)
            log("backups", f"Backup created: {backup_path.name}")

def ensure_dir(path: Path):
    path.mkdir(parents=True, exist_ok=True)

def write_file(path: Path, content: str):
    backup_file(path)
    ensure_dir(path.parent)
    with open(path, 'w', encoding='utf-8') as f:
        f.write(content.strip() + "\n")
    log("created", f"File generated: {path.relative_to(PROJECT_ROOT)}")

# ==========================================
# 1. RENAME NUMBERED DIRECTORIES
# ==========================================
def rename_numbered_dirs():
    if not KERNEL_DIR.exists():
        log("errors", "phoenix_kernel/ directory not found!")
        return

    for item in KERNEL_DIR.iterdir():
        if item.is_dir() and re.match(r'^\d{2}_[a-zA-Z_]+$', item.name):
            new_name = re.sub(r'^\d{2}_', '', item.name)
            new_path = KERNEL_DIR / new_name
            
            if new_path.exists():
                # Merge contents if new path already exists (idempotency)
                for child in item.iterdir():
                    shutil.move(str(child), str(new_path / child.name))
                item.rmdir()
                log("moved", f"Merged {item.name} into {new_name}/")
            else:
                item.rename(new_path)
                log("moved", f"Renamed: {item.name} -> {new_name}/")

# ==========================================
# 2. FIX IMPORTS IN ALL .PY FILES
# ==========================================
def fix_imports():
    for root, _, files in os.walk(PROJECT_ROOT):
        if ".venv" in root or "node_modules" in root:
            continue
        for file in files:
            if file.endswith(".py"):
                file_path = Path(root) / file
                try:
                    with open(file_path, 'r', encoding='utf-8') as f:
                        content = f.read()
                    
                    original_content = content
                    
                    # Fix absolute imports: phoenix_kernel.runtime -> phoenix_kernel.runtime
                    content = re.sub(
                        r'phoenix_kernel\.\d{2}_([a-zA-Z_]+)', 
                        r'phoenix_kernel.\1', 
                        content
                    )
                    
                    # Fix importlib: "phoenix_kernel.models..." -> "phoenix_kernel.models..."
                    content = re.sub(
                        r'"phoenix_kernel\.\d{2}_([a-zA-Z_]+)', 
                        r'"phoenix_kernel.\1', 
                        content
                    )
                    
                    if content != original_content:
                        backup_file(file_path)
                        with open(file_path, 'w', encoding='utf-8') as f:
                            f.write(content)
                        log("imports_fixed", f"Updated imports in: {file_path.relative_to(PROJECT_ROOT)}")
                except Exception as e:
                    log("errors", f"Failed to process {file_path}: {e}")

# ==========================================
# 3. CREATE NEW RUNTIME ARCHITECTURE FILES
# ==========================================
def create_runtime_architecture():
    if not RUNTIME_DIR.exists():
        ensure_dir(RUNTIME_DIR)

    # Create __init__.py for all subpackages
    sub_dirs = ["builders", "executors", "validators", "contracts", "registry", "pipeline"]
    for d in sub_dirs:
        ensure_dir(RUNTIME_DIR / d)
        init_file = RUNTIME_DIR / d / "__init__.py"
        if not init_file.exists():
            write_file(init_file, "")

    # --- contracts.py ---
    write_file(RUNTIME_DIR / "contracts" / "model_contracts.py", """
from enum import Enum
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, Any, Optional, List

class ModelArchitecture(Enum):
    SD15 = "SD15"
    SDXL = "SDXL"
    SDXL_TURBO = "SDXL-Turbo"
    FLUX = "FLUX"

@dataclass(frozen=True)
class GenerationProfile:
    steps: int = 20
    cfg: float = 7.0
    width: int = 512
    height: int = 512
    seed: int = -1

@dataclass
class ModelDescriptor:
    architecture: ModelArchitecture
    model_path: Path
    components: Dict[str, Path]
    generation_profile: GenerationProfile

@dataclass
class RuntimeCapabilities:
    timeout_seconds: int = 900
    default_backend: str = "vulkan"
    vram_mb: int = 8192

class PhoenixRuntimeError(Exception): pass
class ExecutableNotFound(PhoenixRuntimeError): pass
class ModelNotFound(PhoenixRuntimeError): pass
class MissingComponent(PhoenixRuntimeError): pass
class BuilderNotSupported(PhoenixRuntimeError): pass
class GenerationFailed(PhoenixRuntimeError): pass
class CatalogInconsistency(PhoenixRuntimeError): pass
""")

    # --- catalog_pipeline.py (PathResolver + FileValidator) ---
    write_file(RUNTIME_DIR / "pipeline" / "catalog_pipeline.py", """
import json
from pathlib import Path
from phoenix_kernel.runtime.contracts.model_contracts import (ModelDescriptor, ModelArchitecture, 
    GenerationProfile, ModelNotFound, MissingComponent, CatalogInconsistency)

class CatalogLoader:
    @staticmethod
    def load(catalog_path: Path) -> dict:
        if not catalog_path.exists():
            raise ModelNotFound("Catalog file not found.")
        with open(catalog_path, "r", encoding="utf-8") as f:
            return json.load(f)

class CatalogValidator:
    @staticmethod
    def validate(model_id: str, catalog_data: dict) -> dict:
        info = catalog_data.get(model_id)
        if not info:
            raise ModelNotFound(f"Model '{model_id}' not found in catalog.")
        if "architecture" not in info:
            raise CatalogInconsistency(f"Model '{model_id}' missing 'architecture'.")
        if "filename" not in info:
            raise CatalogInconsistency(f"Model '{model_id}' missing 'filename'.")
        return info

class PathResolver:
    @staticmethod
    def resolve_paths(model_id: str, catalog_info: dict, models_base_dir: Path) -> ModelDescriptor:
        subfolder = catalog_info.get("destination_folder", "StableDiffusion")
        dest_dir = models_base_dir / subfolder
        
        model_path = dest_dir / catalog_info["filename"]
        
        components = {}
        for key, val in catalog_info.get("components", {}).items():
            comp_file = val.get("filename")
            if comp_file:
                components[key] = dest_dir / comp_file
                
        arch_str = catalog_info.get("architecture", "SD15")
        try:
            architecture = ModelArchitecture(arch_str)
        except ValueError:
            raise CatalogInconsistency(f"Unknown architecture '{arch_str}'.")

        gen_data = catalog_info.get("default_generation", {})
        profile = GenerationProfile(
            steps=gen_data.get("steps", 20),
            cfg=gen_data.get("cfg", 7.0),
            width=gen_data.get("width", 512),
            height=gen_data.get("height", 512)
        )
        
        return ModelDescriptor(
            architecture=architecture,
            model_path=model_path,
            components=components,
            generation_profile=profile
        )

class FileValidator:
    @staticmethod
    def validate_disk(desc: ModelDescriptor):
        if not desc.model_path.exists():
            raise MissingComponent(f"Model file '{desc.model_path.name}' not found on disk.")
        # Components are validated by the Builder during command generation
""")

    # --- builders/base_builder.py ---
    write_file(RUNTIME_DIR / "builders" / "base_builder.py", """
from abc import ABC, abstractmethod
from typing import List
from phoenix_kernel.runtime.contracts.model_contracts import ModelDescriptor, GenerationProfile

class ICommandBuilder(ABC):
    @abstractmethod
    def build(self, exe_path: str, desc: ModelDescriptor, profile: GenerationProfile, prompt: str, output_file: str) -> List[str]:
        pass
""")

    # --- builders/flux_builder.py ---
    write_file(RUNTIME_DIR / "builders" / "flux_builder.py", """
from typing import List
from .base_builder import ICommandBuilder
from phoenix_kernel.runtime.contracts.model_contracts import ModelDescriptor, GenerationProfile, MissingComponent

class FluxBuilder(ICommandBuilder):
    def build(self, exe_path: str, desc: ModelDescriptor, profile: GenerationProfile, prompt: str, output_file: str) -> List[str]:
        required = ["vae", "clip_l", "t5xxl"]
        for comp in required:
            if comp not in desc.components or not desc.components[comp].exists():
                raise MissingComponent(f"FLUX requires component '{comp}' which is missing or invalid.")

        return [
            exe_path,
            "--diffusion-model", str(desc.model_path),
            "--vae", str(desc.components["vae"]),
            "--clip_l", str(desc.components["clip_l"]),
            "--t5xxl", str(desc.components["t5xxl"]),
            "-p", prompt,
            "-o", output_file,
            "--steps", str(profile.steps),
            "--cfg-scale", str(profile.cfg),
            "--clip-on-cpu",
            "--vae-on-cpu",
            "--vae-tiling"
        ]
""")

    # --- builders/sd15_builder.py ---
    write_file(RUNTIME_DIR / "builders" / "sd15_builder.py", """
from typing import List
from .base_builder import ICommandBuilder
from phoenix_kernel.runtime.contracts.model_contracts import ModelDescriptor, GenerationProfile

class SD15Builder(ICommandBuilder):
    def build(self, exe_path: str, desc: ModelDescriptor, profile: GenerationProfile, prompt: str, output_file: str) -> List[str]:
        return [
            exe_path,
            "-m", str(desc.model_path),
            "-p", prompt,
            "-o", output_file,
            "-H", str(profile.height),
            "-W", str(profile.width),
            "--steps", str(profile.steps)
        ]
""")

    # --- builders/registry.py ---
    write_file(RUNTIME_DIR / "builders" / "registry.py", """
from typing import Dict, Type
from .base_builder import ICommandBuilder
from phoenix_kernel.runtime.contracts.model_contracts import ModelArchitecture, BuilderNotSupported
from .flux_builder import FluxBuilder
from .sd15_builder import SD15Builder

class BuilderRegistry:
    _builders: Dict[ModelArchitecture, Type[ICommandBuilder]] = {}

    @classmethod
    def register(cls, arch: ModelArchitecture, builder_cls: Type[ICommandBuilder]):
        cls._builders[arch] = builder_cls

    @classmethod
    def get(cls, arch: ModelArchitecture) -> ICommandBuilder:
        builder_cls = cls._builders.get(arch)
        if not builder_cls:
            raise BuilderNotSupported(f"No builder registered for {arch.value}")
        return builder_cls()

# Static registration of built-in builders
BuilderRegistry.register(ModelArchitecture.FLUX, FluxBuilder)
BuilderRegistry.register(ModelArchitecture.SD15, SD15Builder)
""")

    # --- executors/subprocess_executor.py ---
    write_file(RUNTIME_DIR / "executors" / "subprocess_executor.py", """
import asyncio
import logging
from typing import List
from phoenix_kernel.runtime.contracts.model_contracts import GenerationFailed

logger = logging.getLogger(__name__)

class SubprocessExecutor:
    @staticmethod
    async def run(cmd: List[str], timeout: int) -> tuple[bool, str]:
        logger.info(f"Executor running: {' '.join(cmd)}")
        process = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE
        )
        
        try:
            stdout, stderr = await asyncio.wait_for(process.communicate(), timeout=timeout)
            if process.returncode == 0:
                return True, "Success"
            else:
                raise GenerationFailed(f"Process exited {process.returncode}. stderr: {stderr.decode()[-500:]}")
        except asyncio.TimeoutError:
            process.kill()
            await process.wait()
            raise GenerationFailed(f"Timeout ({timeout}s) reached.")
""")

    # --- drivers/sd_cpp.py (The Orchestrator) ---
    drivers_dir = RUNTIME_DIR / "drivers"
    ensure_dir(drivers_dir)
    write_file(drivers_dir / "sd_cpp.py", """
from __future__ import annotations
import logging
import platform
from pathlib import Path
from datetime import datetime, timezone

from core.domain.execution import ExecutionPlan, ExecutionResult, ExecutionStatus
from core.domain.runtime import RuntimeStatus, RuntimeState

from phoenix_kernel.runtime.contracts.model_contracts import (ExecutableNotFound, ModelNotFound, 
    MissingComponent, BuilderNotSupported, GenerationFailed, RuntimeCapabilities)
from phoenix_kernel.runtime.pipeline.catalog_pipeline import CatalogLoader, CatalogValidator, PathResolver, FileValidator
from phoenix_kernel.runtime.builders.registry import BuilderRegistry
from phoenix_kernel.runtime.executors.subprocess_executor import SubprocessExecutor

logger = logging.getLogger(__name__)
_UTC = timezone.utc

class SdCppDriver:
    def __init__(self, capabilities: RuntimeCapabilities = None) -> None:
        self._capabilities = capabilities or RuntimeCapabilities()
        self._project_root = Path(__file__).resolve().parent.parent.parent.parent.parent

    @property
    def name(self) -> str: 
        return "stable-diffusion.cpp"

    def _find_executable(self) -> str:
        repo_dir = self._project_root / "repos" / "stable-diffusion.cpp"
        exe_names = ["sd-cli.exe", "sd.exe"] if platform.system() == "Windows" else ["sd-cli", "sd"]
        for name in exe_names:
            paths = [repo_dir / "build" / "bin" / "Release" / name, repo_dir / "build" / "bin" / name]
            for p in paths:
                if p.exists(): return str(p)
        raise ExecutableNotFound("sd-cli not found.")

    async def start(self, plan: ExecutionPlan | None = None) -> bool:
        try: self._find_executable(); return True
        except: return False

    async def stop(self) -> bool: return True

    async def status(self) -> RuntimeStatus:
        try:
            self._find_executable()
            return RuntimeStatus(name=self.name, state=RuntimeState.RUNNING)
        except:
            return RuntimeStatus(name=self.name, state=RuntimeState.STOPPED)

    async def execute(self, plan: ExecutionPlan) -> ExecutionResult:
        try:
            exe_path = self._find_executable()
            models_base = self._project_root / "data" / "models"
            catalog_path = self._project_root / "catalog" / "models.json"
            
            catalog_data = CatalogLoader.load(catalog_path)
            catalog_info = CatalogValidator.validate(plan.model, catalog_data)
            desc = PathResolver.resolve_paths(plan.model, catalog_info, models_base)
            FileValidator.validate_disk(desc)
            
            output_dir = self._project_root / "output" / "images"
            output_dir.mkdir(parents=True, exist_ok=True)
            output_file = output_dir / f"phoenix_{datetime.now().strftime('%H%M%S')}.png"
            prompt = plan.parameters.get("prompt", "A beautiful cyberpunk city")
            
            builder = BuilderRegistry.get(desc.architecture)
            cmd = builder.build(exe_path, desc, desc.generation_profile, prompt, str(output_file))
            
            success, msg = await SubprocessExecutor.run(cmd, self._capabilities.timeout_seconds)
            
            if success and output_file.exists():
                return ExecutionResult(
                    plan_id=plan.id, status=ExecutionStatus.SUCCESS, 
                    output=f"Image generated at: {output_file}",
                    started_at=datetime.now(_UTC), finished_at=datetime.now(_UTC)
                )
            raise GenerationFailed("Image file not created.")
                
        except (ExecutableNotFound, ModelNotFound, MissingComponent, BuilderNotSupported, GenerationFailed) as e:
            logger.error(f"SdCppDriver Pipeline Failure: {e}")
            return ExecutionResult(plan_id=plan.id, status=ExecutionStatus.FAILED, errors=[str(e)])
        except Exception as e:
            logger.error(f"SdCppDriver Unexpected: {e}")
            return ExecutionResult(plan_id=plan.id, status=ExecutionStatus.FAILED, errors=[str(e)])
""")

# ==========================================
# 4. GENERATE REPORT
# ==========================================
def generate_report():
    with open(REPORT_FILE, 'w', encoding='utf-8') as f:
        f.write("# Phoenix Runtime Migration Report\n\n")
        f.write(f"**Timestamp:** {datetime.now().isoformat()}\n\n")
        
        for category, items in report_data.items():
            if items:
                f.write(f"## {category.replace('_', ' ').title()} ({len(items)})\n")
                for item in items:
                    f.write(f"- {item}\n")
                f.write("\n")
        
        f.write("## Next Steps\n")
        f.write("1. Review the backup files (.bak) to ensure no custom logic was lost.\n")
        f.write("2. Update `kernel.py` to inject `RuntimeCapabilities` into `SdCppDriver`.\n")
        f.write("3. Ensure `catalog/models.json` contains the `components` and `default_generation` blocks for FLUX.\n")
    print(f"\n[INFO] Migration report generated at: {REPORT_FILE}")

# ==========================================
# MAIN EXECUTION
# ==========================================
if __name__ == "__main__":
    print("Starting Phoenix Runtime Migration...\n")
    
    # Step 1: Rename numbered directories
    rename_numbered_dirs()
    
    # Step 2: Fix imports across all Python files
    fix_imports()
    
    # Step 3: Create new Runtime Architecture files
    create_runtime_architecture()
    
    # Step 4: Generate Report
    generate_report()
    
    print("\nMigration completed successfully!")