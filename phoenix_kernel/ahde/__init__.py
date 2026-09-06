"""
phoenix_kernel/ahde/ (Agregacao de Hardware, Discovery e Estado)

Camada de agregacao/coordenacao de eventos da Phoenix Engine - nao
escaneia nada sozinha. Recebe dados ja coletados por
phoenix_kernel.discovery, phoenix_kernel.telemetry e
hardware_engine.scanners (via facade.py + telemetry_bridge.py), e
distribui mudancas relevantes atraves do EventBus pros consumidores:
Resident Manager, RAG/Knowledge, Aviary Platform.

Ponto de entrada: a classe AHDE (facade.py). Nao instanciar
SnapshotEngine/EventBus/HealthEngine diretamente fora deste pacote -
usar o facade, pra nao duplicar a fiacao entre eles.

Ver phoenix_ahde_integration_spec.md para o mapa completo de
componentes, as 6 descobertas da auditoria de integracao, as regras
absolutas (Golden Baseline, Ollama como provider opcional, Health nao
confiavel ate implementado) e o plano de fases.
"""
from phoenix_kernel.ahde.facade import AHDE
from phoenix_kernel.ahde.contracts import EventType, EventPriority

__all__ = ["AHDE", "EventType", "EventPriority"]
