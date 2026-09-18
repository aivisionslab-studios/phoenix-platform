from __future__ import annotations
import logging
from typing import Any
from core.events.bus import EventBus
from core.kernel.registry import ServiceRegistry

class PluginContext:
    """Contexto seguro fornecido aos plugins para interagir com a plataforma."""
    def __init__(self, event_bus: EventBus, registry: ServiceRegistry, logger: logging.Logger):
        self.event_bus = event_bus
        self._registry = registry
        self.logger = logger
        
    def resolve(self, key: str) -> Any:
        """Resolve um SDK pelo nome (ex: 'ahde', 'runtime')."""
        return self._registry.resolve(key)
