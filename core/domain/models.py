from __future__ import annotations
from dataclasses import dataclass, field
from pathlib import Path

@dataclass(frozen=True, slots=True, kw_only=True)
class ModelDescriptor:
    name: str
    format: str = 'gguf'
    size_gb: float = 0.0
    min_vram_mb: int = 0
    min_ram_gb: int = 0
    supported_backends: tuple[str, ...] = field(default_factory=tuple)
    source: str = 'ollama'
    source_url: str = ''
    hash: str = ''

@dataclass(frozen=True, slots=True, kw_only=True)
class InstalledModel:
    descriptor: ModelDescriptor
    path: Path
    installed_at: str = ''
    verified: bool = False
