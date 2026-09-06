"""
hardware_engine.models.schemas

Schemas de dados para eventos de telemetria de hardware.
Usado pelo TelemetryBridge (phoenix_kernel/ahde/telemetry_bridge.py) para
traduzir eventos finos de hardware para o formato do AHDE EventBus.
"""
from __future__ import annotations
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Optional


@dataclass
class TelemetryEvent:
    """Evento de mudança de telemetria gerado pelo ChangeDetectionEngine.
    
    Representa uma mudança detectada numa métrica específica de hardware
    (temperatura, VRAM, CPU, etc) que ultrapassou o threshold de ruído.
    """
    name: str
    """Nome da métrica que mudou. Ex: 'gpu.temperature.changed', 'gpu.vram.changed'"""
    
    old_value: Any
    """Valor anterior da métrica."""
    
    new_value: Any
    """Valor novo da métrica."""
    
    delta: float = 0.0
    """Variação absoluta (new_value - old_value)."""
    
    timestamp: str = field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )
    """Timestamp ISO 8601 do momento da detecção."""
    
    source: str = "hardware_engine.ChangeDetectionEngine"
    """Origem do evento."""
    
    metadata: dict = field(default_factory=dict)
    """Metadados adicionais do evento (unidade, sensor_id, etc)."""
