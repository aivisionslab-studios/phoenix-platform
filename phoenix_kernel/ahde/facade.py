"""
phoenix_kernel/ahde/facade.py

Ponto de entrada unico do AHDE para o resto da Phoenix Engine.

Nao reimplementa nada do SnapshotEngine/EventBus/HealthEngine - so os
instancia, conecta entre si, e expoe uma API pequena e estavel pro
kernel.py, pro ResidentManager (Fase 3) e pro endpoint /api/system/panel
(Fase 6) consumirem sem precisar conhecer a estrutura interna do pacote
ahde/.

Esta e uma das duas pecas que nao existiam em lugar nenhum antes desta
integracao (a outra e telemetry_bridge.py) - por isso e a unica parte
deste pacote que e codigo genuinamente novo, nao reaproveitado. Todo o
resto (contracts, event_bus, snapshot_engine, analytics) continua
exatamente como estava.

IMPORTANTE: este arquivo NAO esta conectado ao kernel.py ainda. Instanciar
o AHDE aqui nao muda o boot da Phoenix - isso e trabalho da Fase 2 da
especificacao, que so acontece depois do baseline (Fase 0) ser registrado
na maquina real. Este arquivo e seguro de existir no repo sem risco de
regressao porque nada o importa ainda.
"""
from __future__ import annotations

import logging
from typing import Optional

from phoenix_kernel.ahde.contracts import HardwareSnapshot, TelemetrySnapshot
from phoenix_kernel.ahde.event_bus import EventBus
from phoenix_kernel.ahde.snapshot_engine import SnapshotEngine
from phoenix_kernel.ahde.repository.base import SnapshotRepository
from phoenix_kernel.ahde.health.engine import HealthEngine
from phoenix_kernel.ahde.telemetry_bridge import TelemetryBridge

logger = logging.getLogger(__name__)


class AHDE:
    """
    Facade do AHDE. Uso pretendido a partir da Fase 2 (kernel.py):

        ahde = AHDE(machine_id=machine_id)

        # discovery + hardware_engine/scanners alimentam isto (Fase 2):
        await ahde.ingest_hardware(raw_hardware_dict)

        # telemetry alimenta isto a cada tick (Fase 2) - so publica
        # evento quando o ChangeDetectionEngine acusa mudanca real:
        await ahde.ingest_telemetry(raw_telemetry_dict)

        snapshot = ahde.get_latest_hardware_snapshot()

        # Fase 4 em diante - ainda placeholder (ver evaluate_health):
        health = await ahde.evaluate_health()

    O facade NAO faz polling sozinho e NAO decide nada. So agrega e
    distribui. Quem chama ingest_*() e com que cadencia e
    responsabilidade de quem conecta o kernel (Fase 2), nao deste facade.
    """

    def __init__(self, machine_id: str, repository: Optional[SnapshotRepository] = None):
        self.machine_id = machine_id
        self.event_bus = EventBus()
        self.snapshot_engine = SnapshotEngine(
            machine_id=machine_id, event_bus=self.event_bus, repository=repository
        )
        self.health_engine = HealthEngine()

        # PHX-NEW: filtra ruido antes de qualquer amostra de telemetria
        # chegar no SnapshotEngine - resolve o achado #5 (SnapshotComparer
        # nao tem tolerancia; ChangeDetectionEngine do hardware_engine ja
        # tem). Ver telemetry_bridge.py.
        self._telemetry_bridge = TelemetryBridge()

        self._latest_hardware_snapshot: Optional[HardwareSnapshot] = None
        self._latest_telemetry_snapshot: Optional[TelemetrySnapshot] = None

    async def ingest_hardware(self, raw_hardware_data: dict) -> HardwareSnapshot:
        """
        raw_hardware_data deve seguir o shape esperado por HardwareSnapshot
        (contracts.py): {"hardware": {...}, "drivers": {...},
        "services": {...}, "models": [...]}. Montar esse dict a partir de
        discovery/ + hardware_engine/scanners e trabalho da Fase 2, nao
        deste facade - ele so repassa pro SnapshotEngine.
        """
        snapshot = await self.snapshot_engine.capture_hardware(raw_hardware_data)
        self._latest_hardware_snapshot = snapshot
        return snapshot

    async def ingest_telemetry(self, raw_telemetry_data: dict) -> Optional[TelemetrySnapshot]:
        """
        Filtra ruido via ChangeDetectionEngine (hardware_engine) ANTES de
        tocar no SnapshotEngine. Se nada mudou alem do limiar (1.0 grau,
        64MB etc.), retorna None e NAO chama capture_telemetry() - por
        design, evita publicar TELEMETRY_UPDATED a toa a cada tick.
        """
        changed_events = self._telemetry_bridge.detect_changes(raw_telemetry_data)
        if not changed_events:
            return None

        snapshot = await self.snapshot_engine.capture_telemetry(raw_telemetry_data)
        self._latest_telemetry_snapshot = snapshot

        # PHX-NEW: alem do TELEMETRY_UPDATED coarse que capture_telemetry()
        # ja disparou sozinho, publica tambem os eventos finos (ex.:
        # gpu.temperature.changed com old/new/delta) - resolve o achado #6
        # (EventPublisher do hardware_engine tinha granularidade que o
        # EventBus do AHDE nao tinha; agora o EventBus recebe as duas,
        # sem precisar de um segundo bus).
        for discovery_event in self._telemetry_bridge.to_discovery_events(
            changed_events, machine_id=self.machine_id
        ):
            await self.event_bus.publish(discovery_event.event_type, discovery_event)

        return snapshot

    def get_latest_hardware_snapshot(self) -> Optional[HardwareSnapshot]:
        return self._latest_hardware_snapshot

    def get_latest_telemetry_snapshot(self) -> Optional[TelemetrySnapshot]:
        return self._latest_telemetry_snapshot

    async def evaluate_health(self):
        """
        PHX-NOTE (Regra absoluta #2 da especificacao): HealthEngine.evaluate()
        ainda retorna 100 hardcoded - a Fase 4 (Health real + testes de
        degradacao) nao comecou. NENHUM consumidor deste metodo pode tomar
        decisao automatica com o valor atual. Ele existe aqui so pra manter
        a forma final da API estavel desde ja, nao porque o calculo real ja
        exista.
        """
        if self._latest_hardware_snapshot is None:
            logger.warning(
                "AHDE.evaluate_health() chamado sem nenhum snapshot de hardware "
                "capturado ainda - resultado nao e confiavel."
            )
        return await self.health_engine.evaluate(self._latest_hardware_snapshot)

    async def shutdown(self) -> None:
        await self.event_bus.shutdown()
