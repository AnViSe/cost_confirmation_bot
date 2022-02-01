from typing import List, Type

from app.domain.common.events.event import Event
from app.domain.common.events.observer import Handler, Observer


class EventDispatcher:
    def __init__(self, **kwargs):
        self.domain_events = Observer()
        self.notifies = Observer()
        self.data = kwargs

    async def publish_events(self, events: List[Event]):
        await self.domain_events.notify(events, data=self.data.copy())

    async def publish_notifies(self, events: List[Event]):
        await self.notifies.notify(events, data=self.data.copy())

    def register_domain_event(self, event_type: Type[Event], handler: Handler):
        self.domain_events.register(event_type, handler)

    def register_notify(self, event_type: Type[Event], handler: Handler):
        self.notifies.register(event_type, handler)