from __future__ import annotations
from abc import ABC, abstractmethod
from core.kernel.plugin_context import PluginContext

class AIVisionsPlugin(ABC):
    """Classe base para todos os plugins da AIVisions Platform."""
    
    @property
    @abstractmethod
    def id(self) -> str: ...
    
    @property
    @abstractmethod
    def name(self) -> str: ...
    
    @property
    def version(self) -> str:
        return "1.0.0"
        
    @property
    def author(self) -> str:
        return "Unknown"
        
    @abstractmethod
    async def initialize(self, ctx: PluginContext) -> None:
        """Chamado quando o plugin é carregado."""
        pass
        
    @abstractmethod
    async def shutdown(self) -> None:
        """Chamado quando o plugin é descarregado ou a plataforma desliga."""
        pass
