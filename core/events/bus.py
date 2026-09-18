from __future__ import annotations
import asyncio
import logging
from collections import defaultdict, deque
from typing import Any, Awaitable, Callable
from .base import Event, Command

logger = logging.getLogger(__name__)

EventHandler = Callable[[Event], Awaitable[None]]
CommandHandler = Callable[[Command], Awaitable[Any]]

class EventBus:
    def __init__(self, history_size: int = 100) -> None:
        self._event_subs: dict[str, list[EventHandler]] = defaultdict(list)
        self._command_handlers: dict[str, CommandHandler] = {}
        self._history: deque[Event] = deque(maxlen=history_size)
        self._persistence_callback: Callable[[Event], Awaitable[None]] | None = None
        self._lock = asyncio.Lock()

    def set_persistence_callback(self, callback: Callable[[Event], Awaitable[None]]) -> None:
        self._persistence_callback = callback

    async def publish(self, event: Event) -> None:
        async with self._lock:
            self._history.append(event)
        if self._persistence_callback:
            try:
                await self._persistence_callback(event)
            except Exception as exc:
                logger.error('EventBus: Persistence failed for %s: %s', event.event_type, exc)
        subs = self._event_subs.get(event.event_type, []) + self._event_subs.get('*', [])
        for handler in subs:
            try:
                await handler(event)
            except Exception as exc:
                logger.error('EventBus: handler error for %s: %s', event.event_type, exc)

    def subscribe(self, event_type: str, handler: EventHandler) -> None:
        self._event_subs[event_type].append(handler)

    async def send(self, command: Command) -> Any:
        handler = self._command_handlers.get(command.command_type)
        if handler is None:
            raise ValueError(f'No handler for command: {command.command_type}')
        return await handler(command)

    def register_command(self, command_type: str, handler: CommandHandler) -> None:
        self._command_handlers[command_type] = handler

    def get_history(self, limit: int = 20) -> list[Event]:
        return list(self._history)[-limit:]
