"""Spec section 35: unsent Discord notifications from a previous run (most
notably one that crashed mid-delivery) must be resumable on the next
startup, not silently forgotten. Covers `NotificationService.requeue_pending`.
"""

from __future__ import annotations

from app.database.database import session_scope
from app.database.models import NotificationStatus
from app.database.repositories import KeywordRepository, ListingRepository, NotificationRepository
from app.services.keyword_service import KeywordInput, KeywordService
from app.services.notification_service import NotificationService
from app.utils.time import utc_now


async def _seed_listing_with_notification(status: str, *, attempts: int = 0):
    async with session_scope() as session:
        keyword = await KeywordService(KeywordRepository(session)).create(
            KeywordInput(keyword="Nike ACG", discord_enabled=True)
        )
        listing_repo = ListingRepository(session)
        listing, _ = await listing_repo.upsert_listing_and_link(
            keyword_id=keyword.id,
            detected_at=utc_now(),
            values={
                "external_id": "m_crash_test",
                "title": "Nike ACG Jacket",
                "description": None,
                "price": 120.0,
                "currency": "USD",
                "brand": "Nike",
                "category": None,
                "size": "M",
                "condition": "Good",
                "item_status": None,
                "seller_username": "seller1",
                "seller_id": None,
                "image_url": None,
                "listing_url": "https://www.mercari.com/item/m_crash_test/",
                "created_at_source": None,
                "detection_latency_ms": None,
            },
        )
        notification_repo = NotificationRepository(session)
        notification = await notification_repo.create_pending(listing.id)
        notification.status = status
        notification.attempts = attempts
    return listing.id, notification.id


async def test_pending_notification_is_requeued_on_startup(test_db):
    _, notification_id = await _seed_listing_with_notification(NotificationStatus.PENDING.value)

    service = NotificationService()
    requeued = await service.requeue_pending()

    assert requeued == 1
    assert service._queue.qsize() == 1
    item = service._queue.get_nowait()
    assert item.notification_id == notification_id
    assert item.payload.title == "Nike ACG Jacket"
    assert item.payload.keyword == "Nike ACG"


async def test_finally_failed_notification_is_not_resurrected(test_db):
    await _seed_listing_with_notification(NotificationStatus.FAILED.value, attempts=5)

    service = NotificationService()
    requeued = await service.requeue_pending()

    assert requeued == 0
    assert service._queue.qsize() == 0


async def test_sent_notification_is_not_requeued(test_db):
    await _seed_listing_with_notification(NotificationStatus.SENT.value)

    service = NotificationService()
    requeued = await service.requeue_pending()

    assert requeued == 0
