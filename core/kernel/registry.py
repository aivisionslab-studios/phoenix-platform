from __future__ import annotations
import logging
from typing import Any
from core.contracts.engine import IEngine
from core.domain.engine import EngineDescriptor

logger = logging.getLogger(__name__)

class ServiceRegistry:
    def __init__(self) -> None:
        self._engines: dict[str, IEngine] = {}
        self._descriptors: dict[str, EngineDescriptor] = {}

    def register_engine(self, key: str, engine: IEngine, descriptor: EngineDescriptor) -> None:
        self._engines[key] = engine
        self._descriptors[key] = descriptor
        logger.info('Registry: Engine ''%s'' v%s registered', key, descriptor.version)

    def resolve(self, key: str) -> IEngine | None:
        return self._engines.get(key)

    def get_descriptor(self, key: str) -> EngineDescriptor | None:
        return self._descriptors.get(key)

    def list_engines(self) -> dict[str, EngineDescriptor]:
        return dict(self._descriptors)

    def unregister_engine(self, key: str) -> None:
        self._engines.pop(key, None)
        self._descriptors.pop(key, None)
