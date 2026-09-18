"""
hardware_engine.telemetry.change_detection

ChangeDetectionEngine — filtra ruído de telemetria comparando amostras
sucessivas contra thresholds configuráveis.

Problema que resolve: sensores de hardware variam continuamente em ~0.1-0.3
unidades (temperatura, carga, VRAM). Sem filtro, cada tick de telemetria
geraria um evento, inundando o AHDE EventBus com mudanças irrelevantes.

Thresholds default (calibrados pra hardware AIVisions/Phoenix):
  - Temperatura: 1.0°C de variação mínima pra gerar evento
  - VRAM usada: 64 MB de variação mínima pra gerar evento  
  - RAM usada: 128 MB de variação mínima pra gerar evento
  - Carga CPU/GPU: 5.0% de variação mínima pra gerar evento
  - Clock: 50 MHz de variação mínima pra gerar evento

Usado por: phoenix_kernel/ahde/telemetry_bridge.py
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional

from hardware_engine.models.schemas import TelemetryEvent


# Thresholds de ruído por nome de métrica (baseado nos achados de auditoria
# do SnapshotComparer.compare_hardware() que fazia igualdade exata de dict
# sem tolerância — ver telemetry_bridge.py, seção de contexto no docstring).
_DEFAULT_THRESHOLDS: Dict[str, float] = {
    "gpu.temperature": 1.0,       # °C
    "cpu.temperature": 1.0,       # °C
    "gpu.vram.used": 64.0,        # MB
    "memory.ram.used": 128.0,     # MB
    "gpu.load": 5.0,              # %
    "cpu.load": 5.0,              # %
    "gpu.clock": 50.0,            # MHz
    "cpu.clock": 50.0,            # MHz
    "gpu.power": 5.0,             # W
}

_DEFAULT_THRESHOLD = 1.0  # fallback pra qualquer métrica não listada


def _event_name_from_metric(metric: str) -> str:
    """Mapeia nome de métrica do sample para nome de evento TelemetryEvent."""
    mapping = {
        "gpu_temp": "gpu.temperature.changed",
        "gpu_temperature": "gpu.temperature.changed",
        "cpu_temp": "cpu.temperature.changed",
        "cpu_temperature": "cpu.temperature.changed",
        "gpu_vram_used": "gpu.vram.changed",
        "vram_used_mb": "gpu.vram.changed",
        "ram_used_mb": "memory.used.changed",
        "gpu_load": "gpu.load.changed",
        "cpu_usage": "cpu.load.changed",
        "cpu.throttling": "cpu.throttling.changed",
        "driver.version": "driver.changed",
        "storage.health": "storage.health.changed",
    }
    return mapping.get(metric, f"{metric}.changed")


def _get_threshold(metric: str) -> float:
    """Threshold de ruído para uma métrica específica."""
    for pattern, threshold in _DEFAULT_THRESHOLDS.items():
        if pattern in metric.lower().replace("_", "."):
            return threshold
    return _DEFAULT_THRESHOLD


class ChangeDetectionEngine:
    """
    Compara amostras de telemetria sucessivas e gera TelemetryEvent apenas
    para métricas que mudaram além do threshold de ruído.
    
    Um ChangeDetectionEngine por fonte de amostras — guarda a amostra
    anterior internamente, então não instanciar mais de um por pipeline.
    
    Uso:
        detector = ChangeDetectionEngine()
        events = detector.detect(sample_dict)  # vazio na 1a chamada
        for event in events:
            print(event.name, event.old_value, event.new_value)
    """

    def __init__(self, thresholds: Optional[Dict[str, float]] = None) -> None:
        self._previous: Optional[Dict[str, Any]] = None
        self._thresholds = thresholds or _DEFAULT_THRESHOLDS

    def detect(self, sample: Dict[str, Any]) -> List[TelemetryEvent]:
        """
        Detecta mudanças entre a amostra atual e a anterior.
        
        Retorna lista vazia na primeira chamada (nada pra comparar),
        ou quando nenhuma métrica numérica mudou além do threshold.
        
        Métricas não numéricas (strings, bools) são comparadas por igualdade
        direta (ex: 'driver.version' que muda de "22.11.1" pra "23.1.0").
        """
        if self._previous is None:
            self._previous = dict(sample)
            return []

        events: List[TelemetryEvent] = []

        for key, new_value in sample.items():
            old_value = self._previous.get(key)
            if old_value is None:
                # Métrica nova que não existia antes — reporta como mudança
                events.append(TelemetryEvent(
                    name=_event_name_from_metric(key),
                    old_value=None,
                    new_value=new_value,
                    delta=0.0,
                ))
                continue

            if isinstance(new_value, (int, float)) and isinstance(old_value, (int, float)):
                delta = abs(float(new_value) - float(old_value))
                threshold = _get_threshold(key)
                if delta >= threshold:
                    events.append(TelemetryEvent(
                        name=_event_name_from_metric(key),
                        old_value=old_value,
                        new_value=new_value,
                        delta=delta,
                    ))
            else:
                # Comparação direta para não-numéricos
                if str(new_value) != str(old_value):
                    events.append(TelemetryEvent(
                        name=_event_name_from_metric(key),
                        old_value=old_value,
                        new_value=new_value,
                        delta=0.0,
                    ))

        self._previous = dict(sample)
        return events

    def reset(self) -> None:
        """Descarta a amostra anterior — próxima chamada a detect() volta a ser a primeira."""
        self._previous = None
