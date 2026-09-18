from __future__ import annotations
import logging
from core.contracts.engine import IEngine
from core.domain.engine import HealthStatus
from .registry import ServiceRegistry

logger = logging.getLogger(__name__)

class LifecycleManager:
    def __init__(self, registry: ServiceRegistry) -> None:
        self._registry = registry
        self._initialized: list[str] = []
        self._shutdown_order: list[str] = []

    async def initialize_all(self, skip_initialized: bool = False) -> None:
        for key in list(self._registry.list_engines().keys()):
            if skip_initialized and key in self._initialized:
                continue
            engine = self._registry.resolve(key)
            if engine is None: continue
            try:
                logger.info('Lifecycle: initializing ''%s''...', key)
                await engine.initialize()
                self._initialized.append(key)
                self._shutdown_order.insert(0, key)
            except Exception as exc:
                logger.error('Lifecycle: failed to initialize ''%s'': %s', key, exc)

    async def shutdown_all(self) -> None:
        for key in self._shutdown_order:
            engine = self._registry.resolve(key)
            if engine is None: continue
            try:
                logger.info('Lifecycle: shutting down ''%s''...', key)
                await engine.shutdown()
            except Exception as exc:
                logger.error('Lifecycle: error shutting down ''%s'': %s', key, exc)
        self._initialized.clear()
        self._shutdown_order.clear()

    async def health_check_all(self) -> dict[str, HealthStatus]:
        results: dict[str, HealthStatus] = {}
        for key in self._initialized:
            engine = self._registry.resolve(key)
            if engine is None: continue
            try:
                results[key] = await engine.health()
            except Exception:
                results[key] = HealthStatus.UNHEALTHY
        return results
