"""In-process async event bus decoupling the scraper/monitor from anything
that reacts to what it finds.

Publishers (the monitor/scheduler, services) only ever know about
`EventType` + a payload dict — they never import `notifications/discord.py`
or `api/websocket.py` directly. Consumers (the WebSocket connection manager,
the Discord queue feeder) subscribe independently. This is what lets a
Discord outage never touch the scraper, and lets the frontend stay decoupled
from Mercari-specific internals.
"""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from datetime import datetime
from enum import StrEnum
from typing import Any

from app.utils.logger import get_logger
from app.utils.time import utc_now

logger = get_logger(__name__)


class EventType(StrEnum):
    LISTING_DISCOVERED = "LISTING_DISCOVERED"
    LISTING_STORED = "LISTING_STORED"
    DISCORD_NOTIFICATION_REQUIRED = "DISCORD_NOTIFICATION_REQUIRED"
    DISCORD_NOTIFICATION_SENT = "DISCORD_NOTIFICATION_SENT"
    DISCORD_NOTIFICATION_FAILED = "DISCORD_NOTIFICATION_FAILED"
    SCAN_STARTED = "SCAN_STARTED"
    SCAN_FINISHED = "SCAN_FINISHED"
    SCRAPER_ERROR = "SCRAPER_ERROR"
    RATE_LIMITED = "RATE_LIMITED"
    KEYWORD_UPDATED = "KEYWORD_UPDATED"
    SYSTEM_STATUS_CHANGED = "SYSTEM_STATUS_CHANGED"


@dataclass(slots=True)
class Event:
    type: EventType
    payload: dict[str, Any] = field(default_factory=dict)
    timestamp: datetime = field(default_factory=utc_now)


Handler = Callable[[Event], Awaitable[None]]


class EventBus:
    """Simple async pub/sub. `subscribe(None, handler)` fans every event to
    `handler` (used by the WebSocket broadcaster)."""

    def __init__(self) -> None:
        self._subscribers: dict[EventType | None, list[Handler]] = {}

    def subscribe(self, event_type: EventType | None, handler: Handler) -> None:
        self._subscribers.setdefault(event_type, []).append(handler)

    def unsubscribe(self, event_type: EventType | None, handler: Handler) -> None:
        handlers = self._subscribers.get(event_type, [])
        if handler in handlers:
            handlers.remove(handler)

    async def publish(self, event: Event) -> None:
        handlers = [*self._subscribers.get(event.type, []), *self._subscribers.get(None, [])]
        if not handlers:
            return
        results = await asyncio.gather(
            *(handler(event) for handler in handlers), return_exceptions=True
        )
        for result in results:
            if isinstance(result, Exception):
                logger.error(
                    "Event handler failed for %s: %s", event.type, result, exc_info=result
                )


event_bus = EventBus()
