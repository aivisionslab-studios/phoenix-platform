import logging
from typing import Any
from .interfaces import IBudgetService

logger = logging.getLogger(__name__)

class BudgetEngine(IBudgetService):
    def __init__(self):
        pass

    async def evaluate_machine(self, hardware_data: dict[str, Any]) -> dict[str, Any]:
        gpu = hardware_data.get("gpus", [{}])[0] if hardware_data.get("gpus") else {}
        vram_mb = gpu.get('vram_mb', 0)
        
        # Lógica de Score (0-100)
        score = min(100, int((vram_mb / 8192) * 80 + 15)) if vram_mb > 0 else 10
        
        # Lógica de Classificação
        if vram_mb >= 24000:
            machine_class = "Extreme"
        elif vram_mb >= 12000:
            machine_class = "Large"
        elif vram_mb >= 8000:
            machine_class = "Medium"
        elif vram_mb >= 4000:
            machine_class = "Small"
        else:
            machine_class = "Tiny"
            
        logger.info(f"Kernel Budget: Machine Class -> {machine_class} (Score: {score}%)")
        
        return {
            "score": score,
            "class": machine_class
        }