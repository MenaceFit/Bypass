"""Unit tests for the event-bus -> WebSocket translation layer (spec
section 58: new_listing / scan_started / scan_finished / keyword_updated /
system_status / error).

Exercises `_on_event` directly against the real `connection_manager`
singleton with a throwaway fake socket, rather than going through
`event_bus.publish` — `register_event_bridge()` subscribes the same
module-level handler function to the process-wide event bus, and calling
it more than once (once per test) would register duplicate subscriptions
and double-broadcast. Connect/disconnect/broadcast-to-many are covered
directly against `ConnectionManager`, which needs no such care.
"""

from __future__ import annotations

from app.api.websocket import ConnectionManager, _on_event, connection_manager
from app.events.bus import Event, EventType


class FakeWebSocket:
    def __init__(self) -> None:
        self.sent: list[dict] = []
        self.accepted = False

    async def accept(self) -> None:
        self.accepted = True

    async def send_json(self, data: dict) -> None:
        self.sent.append(data)


class DeadWebSocket(FakeWebSocket):
    async def send_json(self, data: dict) -> None:
        raise RuntimeError("connection already closed")


async def test_connect_accepts_and_tracks_connection():
    manager = ConnectionManager()
    ws = FakeWebSocket()
    await manager.connect(ws)
    assert ws.accepted
    assert manager.connection_count == 1
    await manager.disconnect(ws)
    assert manager.connection_count == 0


async def test_broadcast_reaches_every_connection():
    manager = ConnectionManager()
    a, b = FakeWebSocket(), FakeWebSocket()
    await manager.connect(a)
    await manager.connect(b)

    await manager.broadcast({"type": "system_status", "source_status": "ONLINE"})

    assert a.sent == [{"type": "system_status", "source_status": "ONLINE"}]
    assert b.sent == a.sent


async def test_broadcast_drops_dead_connections_without_raising():
    manager = ConnectionManager()
    good, dead = FakeWebSocket(), DeadWebSocket()
    await manager.connect(good)
    await manager.connect(dead)

    await manager.broadcast({"type": "ping"})

    assert manager.connection_count == 1
    assert good.sent == [{"type": "ping"}]


async def test_new_listing_event_wraps_payload_under_listing_key():
    ws = FakeWebSocket()
    await connection_manager.connect(ws)
    try:
        await _on_event(
            Event(EventType.LISTING_DISCOVERED, {"external_id": "m1", "title": "Nike ACG Jacket"})
        )
        assert ws.sent == [
            {"type": "new_listing", "listing": {"external_id": "m1", "title": "Nike ACG Jacket"}}
        ]
    finally:
        await connection_manager.disconnect(ws)


async def test_scan_lifecycle_events_translate_flat():
    ws = FakeWebSocket()
    await connection_manager.connect(ws)
    try:
        await _on_event(Event(EventType.SCAN_STARTED, {"keyword_id": 1, "keyword": "Nike ACG"}))
        await _on_event(
            Event(EventType.SCAN_FINISHED, {"keyword_id": 1, "success": True, "results_count": 5})
        )
        assert ws.sent[0] == {"type": "scan_started", "keyword_id": 1, "keyword": "Nike ACG"}
        assert ws.sent[1] == {"type": "scan_finished", "keyword_id": 1, "success": True, "results_count": 5}
    finally:
        await connection_manager.disconnect(ws)


async def test_scraper_error_translates_to_error_event():
    ws = FakeWebSocket()
    await connection_manager.connect(ws)
    try:
        await _on_event(Event(EventType.SCRAPER_ERROR, {"keyword_id": 1, "reason": "HTTP 500"}))
        assert ws.sent == [{"type": "error", "keyword_id": 1, "reason": "HTTP 500"}]
    finally:
        await connection_manager.disconnect(ws)


async def test_system_status_changed_translates_to_system_status_event():
    ws = FakeWebSocket()
    await connection_manager.connect(ws)
    try:
        await _on_event(
            Event(EventType.SYSTEM_STATUS_CHANGED, {"source_available": True, "active_workers": 2})
        )
        assert ws.sent == [{"type": "system_status", "source_available": True, "active_workers": 2}]
    finally:
        await connection_manager.disconnect(ws)


async def test_events_not_in_the_ws_surface_are_not_broadcast():
    ws = FakeWebSocket()
    await connection_manager.connect(ws)
    try:
        await _on_event(Event(EventType.LISTING_STORED, {"external_id": "m1"}))
        await _on_event(Event(EventType.DISCORD_NOTIFICATION_SENT, {"notification_id": 1}))
        assert ws.sent == []
    finally:
        await connection_manager.disconnect(ws)
