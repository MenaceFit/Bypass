"""WebSocket connection management + event-bus bridge.

Every event published on the internal event bus (spec section 31) that is
relevant to the dashboard gets translated here into the smaller,
frontend-facing event surface (spec section 21) and broadcast to every
connected client. The scraper/monitor never imports this module — it only
ever talks to `event_bus.publish(...)` (spec: "le scraper ne doit pas
connaître Discord ou React").

Connections are tracked in a plain set; a connection that fails a send is
dropped immediately rather than through separate heartbeat bookkeeping —
simple and sufficient for a single-user local dashboard.
"""

from __future__ import annotations

import asyncio
from typing import Any

from fastapi import WebSocket, WebSocketDisconnect

from app.events.bus import Event, EventType, event_bus
from app.utils.logger import get_logger

logger = get_logger(__name__)

_WS_EVENT_MAP: dict[EventType, str] = {
    EventType.LISTING_DISCOVERED: "new_listing",
    EventType.SCAN_STARTED: "scan_started",
    EventType.SCAN_FINISHED: "scan_finished",
    EventType.KEYWORD_UPDATED: "keyword_updated",
    EventType.SCRAPER_ERROR: "error",
    EventType.SYSTEM_STATUS_CHANGED: "system_status",
}


class ConnectionManager:
    def __init__(self) -> None:
        self._connections: set[WebSocket] = set()
        self._lock = asyncio.Lock()

    async def connect(self, websocket: WebSocket) -> None:
        await websocket.accept()
        async with self._lock:
            self._connections.add(websocket)
        logger.info("WebSocket client connected (%d total)", len(self._connections))

    async def disconnect(self, websocket: WebSocket) -> None:
        async with self._lock:
            self._connections.discard(websocket)
        logger.info("WebSocket client disconnected (%d total)", len(self._connections))

    async def broadcast(self, message: dict[str, Any]) -> None:
        async with self._lock:
            connections = list(self._connections)
        for connection in connections:
            try:
                await connection.send_json(message)
            except Exception:
                await self.disconnect(connection)

    @property
    def connection_count(self) -> int:
        return len(self._connections)


connection_manager = ConnectionManager()


async def _on_event(event: Event) -> None:
    ws_type = _WS_EVENT_MAP.get(event.type)
    if ws_type is None:
        return
    if ws_type == "new_listing":
        message = {"type": ws_type, "listing": event.payload}
    else:
        message = {"type": ws_type, **event.payload}
    await connection_manager.broadcast(message)


def register_event_bridge() -> None:
    event_bus.subscribe(None, _on_event)


async def handle_websocket(websocket: WebSocket) -> None:
    await connection_manager.connect(websocket)
    try:
        while True:
            # The dashboard is a passive listener — we don't act on inbound
            # messages, but must keep receiving to detect a client-side
            # disconnect (and to answer ping/pong frames).
            await websocket.receive_text()
    except WebSocketDisconnect:
        pass
    finally:
        await connection_manager.disconnect(websocket)
