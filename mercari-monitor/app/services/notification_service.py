"""Discord notification orchestration: a dedicated queue + worker so a slow
or failing webhook can never block scraping or DB writes (spec section
30/68).

    event bus (DISCORD_NOTIFICATION_REQUIRED)
        -> asyncio.Queue
        -> worker task
        -> notifications/discord.py (HTTP call)
        -> DB status update (PENDING -> SENT | FAILED)
        -> event bus (DISCORD_NOTIFICATION_SENT | DISCORD_NOTIFICATION_FAILED)
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass

from app.config.defaults import DISCORD_MAX_ATTEMPTS
from app.config.settings import settings
from app.database.database import session_scope
from app.database.repositories import NotificationRepository
from app.events.bus import Event, EventType, event_bus
from app.notifications.discord import DiscordDeliveryError, send_new_listing_embed, send_test_embed
from app.services.listing_service import ListingEventPayload
from app.utils.logger import get_logger
from app.utils.retry import compute_backoff_delay

logger = get_logger(__name__)


@dataclass
class QueuedNotification:
    notification_id: int
    payload: ListingEventPayload


class NotificationService:
    def __init__(self) -> None:
        self._queue: asyncio.Queue[QueuedNotification] = asyncio.Queue()
        self._worker_task: asyncio.Task | None = None

    def start(self) -> None:
        if self._worker_task is None:
            self._worker_task = asyncio.create_task(self._worker_loop())
        event_bus.subscribe(EventType.DISCORD_NOTIFICATION_REQUIRED, self._on_notification_required)
        logger.info("Discord notification worker started")

    async def stop(self) -> None:
        if self._worker_task is None:
            return
        self._worker_task.cancel()
        try:
            await self._worker_task
        except asyncio.CancelledError:
            pass
        self._worker_task = None

    async def _on_notification_required(self, event: Event) -> None:
        notification_id = event.payload.get("notification_id")
        if notification_id is None:
            logger.error("DISCORD_NOTIFICATION_REQUIRED event missing notification_id, dropping")
            return
        payload = ListingEventPayload.model_validate(event.payload)
        await self._queue.put(QueuedNotification(notification_id=notification_id, payload=payload))

    async def _worker_loop(self) -> None:
        while True:
            item = await self._queue.get()
            try:
                await self._deliver(item)
            except Exception:
                logger.exception(
                    "Unexpected error in Discord worker for notification %s", item.notification_id
                )
            finally:
                self._queue.task_done()

    async def _deliver(self, item: QueuedNotification) -> None:
        if not settings.has_discord:
            await self._mark_failed(item.notification_id, "Discord webhook not configured", final=True)
            return

        attempts = await self._mark_attempt(item.notification_id)

        try:
            await send_new_listing_embed(item.payload, webhook_url=settings.discord_webhook_url)
        except DiscordDeliveryError as exc:
            await self._handle_delivery_failure(item, attempts, str(exc))
            return

        async with session_scope() as session:
            await NotificationRepository(session).mark_sent(item.notification_id)
        await event_bus.publish(
            Event(EventType.DISCORD_NOTIFICATION_SENT, {"notification_id": item.notification_id})
        )

    async def _handle_delivery_failure(
        self, item: QueuedNotification, attempts: int, error: str
    ) -> None:
        final = attempts >= DISCORD_MAX_ATTEMPTS
        await self._mark_failed(item.notification_id, error, final=final)
        await event_bus.publish(
            Event(
                EventType.DISCORD_NOTIFICATION_FAILED,
                {"notification_id": item.notification_id, "error": error, "final": final},
            )
        )
        if not final:
            delay = compute_backoff_delay(attempts, base_delay_ms=2000, max_delay_ms=60_000)
            await asyncio.sleep(delay)
            await self._queue.put(item)

    async def _mark_attempt(self, notification_id: int) -> int:
        async with session_scope() as session:
            repo = NotificationRepository(session)
            await repo.mark_attempt(notification_id)
            notification = await repo.get(notification_id)
            return notification.attempts if notification else 1

    async def _mark_failed(self, notification_id: int, error: str, *, final: bool) -> None:
        async with session_scope() as session:
            await NotificationRepository(session).mark_failed(notification_id, error, final=final)

    async def send_test_message(self) -> None:
        """Backs `POST /api/discord/test` — bypasses the queue/DB entirely,
        a direct synchronous send so the UI gets an immediate result."""
        if not settings.has_discord:
            raise DiscordDeliveryError("No Discord webhook is configured.")
        await send_test_embed(webhook_url=settings.discord_webhook_url)


notification_service = NotificationService()
