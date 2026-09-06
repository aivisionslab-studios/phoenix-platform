from abc import ABC, abstractmethod
from typing import Any

class IValidationService(ABC):
    @abstractmethod
    async def validate_system(self) -> dict[str, Any]:
        # PHX-FIX (varredura 2026-08-21 rodada 2, achado #1): o docstring
        # antigo alegava "integrity and sensor redundancy" - nenhuma das
        # duas coisas jamais existiu na implementação (não há conceito de
        # redundância de sensor no projeto). Corrigido pra descrever o que
        # a checagem real faz.
        """Confirms basic hardware counters (RAM, CPU cores, free disk
        space) can actually be read via psutil/shutil. Does not enforce
        any minimum specification - only reports whether the read itself
        succeeded ("ok") or failed ("fail"), with the specific issues."""
        pass
