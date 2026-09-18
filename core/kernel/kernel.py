from __future__ import annotations
import asyncio
import logging
from typing import Any
from core.contracts.engine import IEngine
from core.domain.engine import EngineDescriptor, HealthStatus
from core.events.bus import EventBus
from .registry import ServiceRegistry
from .lifecycle import LifecycleManager

logger = logging.getLogger(__name__)

class PlatformKernel:
    def __init__(self, config: dict | None = None) -> None:
        self.config = config or {}
        self.registry = ServiceRegistry()
        self.event_bus = EventBus()
        self.lifecycle = LifecycleManager(self.registry)
        self._started = False

    def register_engine(self, key: str, engine: IEngine, descriptor: EngineDescriptor) -> None:
        self.registry.register_engine(key, engine, descriptor)

    def resolve(self, key: str) -> IEngine | None:
        return self.registry.resolve(key)

    def get_config(self, section: str) -> dict:
        return self.config.get(section, {})

    async def initialize(self, skip_initialized: bool = False) -> None:
        logger.info("Kernel: initializing platform...")
        await self.lifecycle.initialize_all(skip_initialized=skip_initialized)
        self._started = True
        logger.info("Kernel: platform ready. Engines: %s",
                     list(self.registry.list_engines().keys()))

    async def shutdown(self) -> None:
        logger.info("Kernel: shutting down platform...")
        await self.lifecycle.shutdown_all()
        self._started = False
        logger.info("Kernel: shutdown complete.")

    async def health(self) -> dict[str, HealthStatus]:
        return await self.lifecycle.health_check_all()

    @property
    def is_running(self) -> bool:
        return self._started