import logging
from collections import deque
from datetime import datetime, timezone

logger = logging.getLogger(__name__)

VALID_LEVELS = {"INFO", "WARNING", "ERROR", "DEBUG"}


class LogsEngine:
    """
    Motor de eventos da Phoenix - guarda um histórico recente em memória
    (ring buffer) e também repassa pro logging padrão do Python, pra
    aparecer no console/transcript da sessão.

    Reconstruído a partir do uso real já existente no código:
      - kernel.py:      self.logs.add_event("INFO", "Kernel", "...")
      - api/engine.py:  self.logs.get_recent_logs(10)
                         -> itera l['timestamp'], l['source'], l['message']

    NOTA: esse arquivo foi recriado do zero porque a pasta original
    phoenix_kernel/logs/ ficou presa num padrão do .gitignore e nunca
    chegou a ser commitada. Se você tiver a versão original em outro
    lugar (outra máquina/branch), prefira ela e descarte esse arquivo -
    essa é uma reconstrução best-effort baseada só na interface observada.
    """

    def __init__(self, max_events: int = 500):
        self._events = deque(maxlen=max_events)

    def add_event(self, level: str, source: str, message: str) -> dict:
        level_norm = (level or "INFO").upper()
        if level_norm not in VALID_LEVELS:
            level_norm = "INFO"

        entry = {
            "timestamp": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S"),
            "level": level_norm,
            "source": source or "Unknown",
            "message": message or "",
        }
        self._events.append(entry)

        log_fn = {
            "ERROR": logger.error,
            "WARNING": logger.warning,
            "DEBUG": logger.debug,
        }.get(level_norm, logger.info)
        log_fn(f"[{entry['source']}] {entry['message']}")

        return entry

    def get_recent_logs(self, count: int = 10) -> list:
        if count <= 0:
            return []
        return list(self._events)[-count:]

    def clear(self) -> None:
        self._events.clear()
