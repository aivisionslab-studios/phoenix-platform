import logging
from collections import defaultdict

logger = logging.getLogger(__name__)

class EventBus:
    def __init__(self):
        self._subscribers = defaultdict(list)
        self._history = []

    def subscribe(self, event_type: str, handler):
        self._subscribers[event_type].append(handler)

    def publish(self, event_type: str, data: dict = None):
        event = {"type": event_type, "data": data or {}}
        self._history.append(event)
        logger.info(f"EventBus: Published {event_type}")
        for handler in self._subscribers.get(event_type, []):
            try:
                handler(event)
            except Exception as e:
                logger.error(f"EventBus: Error in handler for {event_type}: {e}")
