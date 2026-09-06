from typing import Dict, Type
from .base_builder import ICommandBuilder
from phoenix_kernel.runtime.contracts.model_contracts import ModelArchitecture, BuilderNotSupported
from .flux_builder import FluxBuilder
from .sd15_builder import SD15Builder

class BuilderRegistry:
    _builders: Dict[ModelArchitecture, Type[ICommandBuilder]] = {}

    @classmethod
    def register(cls, arch: ModelArchitecture, builder_cls: Type[ICommandBuilder]):
        cls._builders[arch] = builder_cls

    @classmethod
    def get(cls, arch: ModelArchitecture) -> ICommandBuilder:
        builder_cls = cls._builders.get(arch)
        if not builder_cls:
            raise BuilderNotSupported(f"No builder registered for {arch.value}")
        return builder_cls()

# Static registration of built-in builders
BuilderRegistry.register(ModelArchitecture.FLUX, FluxBuilder)
BuilderRegistry.register(ModelArchitecture.SD15, SD15Builder)
