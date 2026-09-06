# phoenix_kernel/ahde/event_bus.py
import asyncio
import logging
from collections import deque
from dataclasses import asdict
from typing import Callable, Dict, List, Set, Tuple
from phoenix_kernel.ahde.contracts import EventType, EventPriority, DiscoveryEvent

logger = logging.getLogger(__name__)

class EventBus:
    """Barramento de eventos assíncrono, não-bloqueante, com ciclo de vida e DI."""
    def __init__(self):
        self._subscribers: Dict[EventType, List[Tuple[EventPriority, Callable]]] = {}
        self._active_tasks: Set[asyncio.Task] = set()
        self._recent_events = deque(maxlen=100)

    def subscribe(self, event_type: EventType, callback: Callable, priority: EventPriority = EventPriority.NORMAL):
        if event_type not in self._subscribers:
            self._subscribers[event_type] = []
        self._subscribers[event_type].append((priority, callback))
        logger.info(f"EventBus: Assinante registrado para {event_type.name} (Prioridade: {priority.name})")

    def unsubscribe(self, event_type: EventType, callback: Callable):
        if event_type in self._subscribers:
            self._subscribers[event_type] = [
                (p, cb) for p, cb in self._subscribers[event_type] if cb != callback
            ]

    async def publish(self, event_type: EventType, event: DiscoveryEvent):
        self._recent_events.appendleft(asdict(event))
        if event_type in self._subscribers:
            subs = sorted(self._subscribers[event_type], key=lambda x: x[0].value)
            for priority, callback in subs:
                try:
                    if asyncio.iscoroutinefunction(callback):
                        # Não-bloqueante: cria task isolada e rastreia
                        task = asyncio.create_task(callback(event))
                        self._active_tasks.add(task)
                        task.add_done_callback(self._active_tasks.discard)
                    else:
                        callback(event)
                except Exception as e:
                    logger.error(f"EventBus: Erro ao disparar assinante de {event_type.name}: {e}")

    def recent_events(self, limit: int = 50) -> List[dict]:
        """Retorna os eventos mais recentes sem expor o buffer interno."""
        safe_limit = max(0, min(int(limit), self._recent_events.maxlen or 100))
        return list(self._recent_events)[:safe_limit]

    async def shutdown(self):
        """Aguarda tarefas pendentes e cancela o barramento de forma segura."""
        logger.info("EventBus: Iniciando shutdown. Aguardando tasks pendentes...")
        if self._active_tasks:
            await asyncio.gather(*self._active_tasks, return_exceptions=True)
        self._active_tasks.clear()
        self._subscribers.clear()
        logger.info("EventBus: Shutdown concluído.")
