"""
phoenix_kernel/ahde/telemetry_bridge.py

Ponte de contrato entre hardware_engine (produtor de telemetria com
filtro de ruido ja resolvido) e o AHDE (EventBus/SnapshotEngine).

Existe por causa dos achados #5 e #6 da auditoria de integracao AHDE:

  #5 - SnapshotComparer.compare_hardware() faz igualdade exata de dict,
       sem tolerancia. Ligar telemetria continua direto nisso inunda o
       EventBus a cada 0.1 grau de variacao de sensor.
  #6 - hardware_engine.telemetry.change_detection.ChangeDetectionEngine
       ja resolve isso (thresholds de 1.0 grau / 64MB), e ja produz
       eventos finos por metrica (TelemetryEvent) que os 6 EventType
       coarse do AHDE nao conseguem representar sozinhos.

Este modulo NAO reimplementa deteccao de mudanca nem cria um segundo
EventBus. Ele so traduz. hardware_engine continua sendo a unica fonte
de filtro de ruido; phoenix_kernel.ahde continua sendo o unico
barramento de eventos vivo (ver comparacao linha a linha na secao 2,
achado #6, de phoenix_ahde_integration_spec.md).

Direcao da dependencia: este arquivo (phoenix_kernel) importa
hardware_engine - nunca o contrario. Isso preserva o hardware_engine
como pacote instalavel independente (tem pyproject.toml proprio,
"aivisions-hardware-discovery-core", sem depender de phoenix_kernel).

GAP conhecido e deliberadamente NAO resolvido aqui: EventPublisher do
hardware_engine tem get_events(since=, name=) - historico/replay por
metrica. O EventBus do AHDE nao tem equivalente. Isso fica registrado
como pendencia (ver spec, secao 2, achado #6) ate um consumidor real
precisar - nao e resolvido por este bridge de proposito.
"""
from __future__ import annotations

from typing import Iterable, List

from hardware_engine.telemetry.change_detection import ChangeDetectionEngine
from hardware_engine.models.schemas import TelemetryEvent

from phoenix_kernel.ahde.contracts import DiscoveryEvent, EventType, EventPriority


# PHX-NEW: qual EventType coarse do AHDE cada evento fino do
# hardware_engine deve disparar, alem do TELEMETRY_UPDATED que o
# SnapshotEngine.capture_telemetry() ja publica sozinho quando chamado.
# Temperatura/throttling/driver/storage viram HARDWARE_CHANGED (o
# Resident Manager precisa reagir rapido a isso); VRAM/RAM ficam em
# TELEMETRY_UPDATED. Usa só as 6 categorias que ja existem em
# contracts.py - nao inventa EventType novo.
_FINE_EVENT_TO_COARSE_TYPE = {
    "cpu.temperature.changed": EventType.HARDWARE_CHANGED,
    "gpu.temperature.changed": EventType.HARDWARE_CHANGED,
    "cpu.throttling.changed": EventType.HARDWARE_CHANGED,
    "driver.changed": EventType.HARDWARE_CHANGED,
    "storage.health.changed": EventType.HARDWARE_CHANGED,
    "gpu.vram.changed": EventType.TELEMETRY_UPDATED,
    "memory.used.changed": EventType.TELEMETRY_UPDATED,
}

_HIGH_PRIORITY_EVENTS = {
    "cpu.temperature.changed",
    "gpu.temperature.changed",
    "cpu.throttling.changed",
    "driver.changed",
    "storage.health.changed",
}


class TelemetryBridge:
    """
    Encapsula um ChangeDetectionEngine (hardware_engine) e traduz a
    saida dele pro contrato do AHDE (DiscoveryEvent/EventType).

    Um bridge por processo/maquina monitorada: o ChangeDetectionEngine
    guarda a amostra anterior internamente (`_previous`), entao nao
    instanciar mais de um TelemetryBridge pra mesma fonte de amostras,
    ou a deteccao de mudanca fica inconsistente.
    """

    def __init__(self) -> None:
        self._detector = ChangeDetectionEngine()

    def detect_changes(self, sample: dict) -> List[TelemetryEvent]:
        """
        Repassa direto pro ChangeDetectionEngine do hardware_engine -
        zero logica de filtro de ruido reimplementada aqui. Retorna
        lista vazia na primeira amostra (nada pra comparar ainda) ou
        quando nenhuma metrica mudou alem do threshold.
        """
        return self._detector.detect(sample)

    def to_discovery_events(
        self, telemetry_events: Iterable[TelemetryEvent], machine_id: str
    ) -> List[DiscoveryEvent]:
        """
        Traduz TelemetryEvent (hardware_engine) -> DiscoveryEvent (AHDE).
        O TelemetryEvent inteiro (name/old_value/new_value/delta) vira o
        payload - nada e perdido na traducao, so embrulhado no formato
        que o EventBus do AHDE espera.
        """
        discovery_events: List[DiscoveryEvent] = []
        for event in telemetry_events:
            event_type = _FINE_EVENT_TO_COARSE_TYPE.get(event.name, EventType.TELEMETRY_UPDATED)
            priority = EventPriority.HIGH if event.name in _HIGH_PRIORITY_EVENTS else EventPriority.NORMAL
            discovery_events.append(DiscoveryEvent(
                event_type=event_type,
                payload=event,
                timestamp=event.timestamp,
                priority=priority,
                machine_id=machine_id,
                source="hardware_engine.ChangeDetectionEngine",
            ))
        return discovery_events
