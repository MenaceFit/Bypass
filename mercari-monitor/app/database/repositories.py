"""Repository layer: all raw SQL/ORM query logic lives here so services
never build queries themselves. Each repository is bound to one
`AsyncSession` (typically one per request or one per background task run).

The deduplication guarantee (section 8 of the spec) is enforced here, at
the database level, via `INSERT ... ON CONFLICT DO NOTHING` against the
UNIQUE constraint on `listings.external_id` — not via an application-level
"check then insert", which would race under concurrent keyword scans.
"""

from __future__ import annotations

import math
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime
from typing import Generic, TypeVar

from sqlalchemy import func, select
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.config.defaults import DEFAULT_PAGE_SIZE
from app.database.models import (
    AppSetting,
    Keyword,
    Listing,
    ListingKeyword,
    Notification,
    NotificationStatus,
    ScanRun,
)
from app.utils.time import utc_now
from app.utils.validation import clamp_page_size

T = TypeVar("T")


@dataclass
class Page(Generic[T]):
    items: list[T]
    total: int
    page: int
    page_size: int

    @property
    def total_pages(self) -> int:
        return max(1, math.ceil(self.total / self.page_size)) if self.page_size else 1


@dataclass
class ListingFilter:
    keyword_id: int | None = None
    brand: str | None = None
    size: str | None = None
    condition: str | None = None
    min_price: float | None = None
    max_price: float | None = None
    seller_username: str | None = None
    detected_after: datetime | None = None
    detected_before: datetime | None = None
    discord_status: str | None = None


def _sort_clause(sort: str) -> tuple:
    return {
        "newest": (Listing.detected_at.desc(),),
        "oldest": (Listing.detected_at.asc(),),
        "price_low": (Listing.price.is_(None), Listing.price.asc()),
        "price_high": (Listing.price.is_(None), Listing.price.desc()),
        "detection_fastest": (
            Listing.detection_latency_ms.is_(None),
            Listing.detection_latency_ms.asc(),
        ),
    }.get(sort, (Listing.detected_at.desc(),))


class KeywordRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def create(self, **fields) -> Keyword:
        keyword = Keyword(**fields)
        self.session.add(keyword)
        await self.session.flush()
        return keyword

    async def get(self, keyword_id: int) -> Keyword | None:
        return await self.session.get(Keyword, keyword_id)

    async def get_by_text(self, keyword_text: str) -> Keyword | None:
        result = await self.session.execute(
            select(Keyword).where(func.lower(Keyword.keyword) == keyword_text.lower())
        )
        return result.scalar_one_or_none()

    async def list_all(self) -> list[Keyword]:
        result = await self.session.execute(select(Keyword).order_by(Keyword.created_at.asc()))
        return list(result.scalars().all())

    async def list_active(self) -> list[Keyword]:
        result = await self.session.execute(
            select(Keyword).where(Keyword.active.is_(True)).order_by(Keyword.id.asc())
        )
        return list(result.scalars().all())

    async def update(self, keyword_id: int, **fields) -> Keyword | None:
        keyword = await self.get(keyword_id)
        if keyword is None:
            return None
        for key, value in fields.items():
            setattr(keyword, key, value)
        keyword.updated_at = utc_now()
        await self.session.flush()
        return keyword

    async def delete(self, keyword_id: int) -> bool:
        keyword = await self.get(keyword_id)
        if keyword is None:
            return False
        await self.session.delete(keyword)
        return True

    async def set_active(self, keyword_id: int, active: bool) -> Keyword | None:
        from app.database.models import KeywordStatus

        keyword = await self.get(keyword_id)
        if keyword is None:
            return None
        keyword.active = active
        if not active:
            keyword.status = KeywordStatus.PAUSED.value
        elif keyword.status == KeywordStatus.PAUSED.value:
            keyword.status = KeywordStatus.ACTIVE.value
        keyword.updated_at = utc_now()
        await self.session.flush()
        return keyword

    async def record_scan_start(self, keyword_id: int) -> None:
        keyword = await self.get(keyword_id)
        if keyword is None:
            return
        keyword.last_scan_at = utc_now()

    async def record_scan_result(
        self,
        keyword_id: int,
        *,
        status: str,
        duration_ms: int,
        next_scan_at: datetime,
        consecutive_failures: int,
        backoff_until: datetime | None,
        error_message: str | None,
    ) -> None:
        keyword = await self.get(keyword_id)
        if keyword is None:
            return
        keyword.status = status
        keyword.last_scan_duration_ms = duration_ms
        keyword.next_scan_at = next_scan_at
        keyword.consecutive_failures = consecutive_failures
        keyword.backoff_until = backoff_until
        keyword.last_error_message = error_message
        keyword.updated_at = utc_now()


class ListingRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def filter_known_external_ids(self, external_ids: Sequence[str]) -> set[str]:
        if not external_ids:
            return set()
        result = await self.session.execute(
            select(Listing.external_id).where(Listing.external_id.in_(external_ids))
        )
        return {row[0] for row in result.all()}

    async def upsert_listing_and_link(
        self,
        *,
        keyword_id: int,
        detected_at: datetime,
        values: dict,
    ) -> tuple[Listing, bool]:
        """Insert the listing if `external_id` is unseen, link it to
        `keyword_id`, and report whether the listing itself was new
        (globally, across every keyword) — that flag, not the link, is what
        should gate a notification."""
        insert_stmt = (
            sqlite_insert(Listing)
            .values(detected_at=detected_at, **values)
            .on_conflict_do_nothing(index_elements=["external_id"])
            .returning(Listing.id)
        )
        result = await self.session.execute(insert_stmt)
        inserted_id = result.scalar_one_or_none()
        is_new = inserted_id is not None

        if is_new:
            listing = await self.session.get(Listing, inserted_id)
        else:
            existing = await self.session.execute(
                select(Listing).where(Listing.external_id == values["external_id"])
            )
            listing = existing.scalar_one()

        link_stmt = (
            sqlite_insert(ListingKeyword)
            .values(
                listing_id=listing.id,
                keyword_id=keyword_id,
                first_detected_at=detected_at,
            )
            .on_conflict_do_nothing(index_elements=["listing_id", "keyword_id"])
        )
        await self.session.execute(link_stmt)
        await self.session.flush()
        return listing, is_new

    async def get(self, listing_id: int) -> Listing | None:
        return await self.session.get(Listing, listing_id)

    async def get_recent(self, limit: int) -> list[Listing]:
        result = await self.session.execute(
            select(Listing).order_by(Listing.detected_at.desc()).limit(limit)
        )
        return list(result.scalars().all())

    async def list_paginated(
        self,
        filters: ListingFilter,
        *,
        sort: str = "newest",
        page: int = 1,
        page_size: int = DEFAULT_PAGE_SIZE,
    ) -> Page[Listing]:
        page = max(1, page)
        page_size = clamp_page_size(page_size)

        stmt = select(Listing)
        count_stmt = select(func.count(func.distinct(Listing.id)))

        if filters.keyword_id is not None:
            stmt = stmt.join(ListingKeyword, ListingKeyword.listing_id == Listing.id).where(
                ListingKeyword.keyword_id == filters.keyword_id
            )
            count_stmt = count_stmt.join(
                ListingKeyword, ListingKeyword.listing_id == Listing.id
            ).where(ListingKeyword.keyword_id == filters.keyword_id)

        if filters.discord_status is not None:
            stmt = stmt.join(Notification, Notification.listing_id == Listing.id).where(
                Notification.status == filters.discord_status
            )
            count_stmt = count_stmt.join(
                Notification, Notification.listing_id == Listing.id
            ).where(Notification.status == filters.discord_status)

        for column, value in (
            (Listing.brand, filters.brand),
            (Listing.size, filters.size),
            (Listing.condition, filters.condition),
            (Listing.seller_username, filters.seller_username),
        ):
            if value:
                stmt = stmt.where(column == value)
                count_stmt = count_stmt.where(column == value)

        if filters.min_price is not None:
            stmt = stmt.where(Listing.price >= filters.min_price)
            count_stmt = count_stmt.where(Listing.price >= filters.min_price)
        if filters.max_price is not None:
            stmt = stmt.where(Listing.price <= filters.max_price)
            count_stmt = count_stmt.where(Listing.price <= filters.max_price)
        if filters.detected_after is not None:
            stmt = stmt.where(Listing.detected_at >= filters.detected_after)
            count_stmt = count_stmt.where(Listing.detected_at >= filters.detected_after)
        if filters.detected_before is not None:
            stmt = stmt.where(Listing.detected_at <= filters.detected_before)
            count_stmt = count_stmt.where(Listing.detected_at <= filters.detected_before)

        stmt = stmt.distinct().order_by(*_sort_clause(sort))
        stmt = stmt.offset((page - 1) * page_size).limit(page_size)

        total = (await self.session.execute(count_stmt)).scalar_one()
        items = (await self.session.execute(stmt)).scalars().all()
        return Page(items=list(items), total=total, page=page, page_size=page_size)

    async def keywords_for_listing(self, listing_id: int) -> list[str]:
        result = await self.session.execute(
            select(Keyword.keyword)
            .join(ListingKeyword, ListingKeyword.keyword_id == Keyword.id)
            .where(ListingKeyword.listing_id == listing_id)
        )
        return [row[0] for row in result.all()]

    async def delete_older_than(self, cutoff: datetime) -> int:
        result = await self.session.execute(
            select(Listing.id).where(Listing.detected_at < cutoff)
        )
        ids = [row[0] for row in result.all()]
        if not ids:
            return 0
        for listing_id in ids:
            listing = await self.session.get(Listing, listing_id)
            if listing is not None:
                await self.session.delete(listing)
        return len(ids)

    # --- Statistics ------------------------------------------------------
    async def count_detected_since(self, since: datetime) -> int:
        result = await self.session.execute(
            select(func.count(Listing.id)).where(Listing.detected_at >= since)
        )
        return result.scalar_one()

    async def latency_stats(self) -> dict:
        result = await self.session.execute(
            select(
                func.avg(Listing.detection_latency_ms),
                func.min(Listing.detection_latency_ms),
                func.max(Listing.detection_latency_ms),
            ).where(Listing.detection_latency_ms.is_not(None))
        )
        avg_ms, min_ms, max_ms = result.one()
        return {
            "avg_detection_latency_ms": round(avg_ms) if avg_ms is not None else None,
            "fastest_detection_ms": min_ms,
            "slowest_detection_ms": max_ms,
        }

    async def most_active_keyword(self) -> str | None:
        result = await self.session.execute(
            select(Keyword.keyword, func.count(ListingKeyword.listing_id).label("cnt"))
            .join(ListingKeyword, ListingKeyword.keyword_id == Keyword.id)
            .group_by(Keyword.id)
            .order_by(func.count(ListingKeyword.listing_id).desc())
            .limit(1)
        )
        row = result.first()
        return row[0] if row else None

    async def most_detected_brand(self) -> str | None:
        result = await self.session.execute(
            select(Listing.brand, func.count(Listing.id).label("cnt"))
            .where(Listing.brand.is_not(None))
            .group_by(Listing.brand)
            .order_by(func.count(Listing.id).desc())
            .limit(1)
        )
        row = result.first()
        return row[0] if row else None

    async def average_price(self) -> float | None:
        result = await self.session.execute(
            select(func.avg(Listing.price)).where(Listing.price.is_not(None))
        )
        value = result.scalar_one()
        return round(value, 2) if value is not None else None

    async def total_count(self) -> int:
        result = await self.session.execute(select(func.count(Listing.id)))
        return result.scalar_one()


class ListingKeywordRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def link_count_for_keyword(self, keyword_id: int) -> int:
        result = await self.session.execute(
            select(func.count(ListingKeyword.listing_id)).where(
                ListingKeyword.keyword_id == keyword_id
            )
        )
        return result.scalar_one()

    async def link_count_for_keyword_since(self, keyword_id: int, since: datetime) -> int:
        result = await self.session.execute(
            select(func.count(ListingKeyword.listing_id)).where(
                ListingKeyword.keyword_id == keyword_id,
                ListingKeyword.first_detected_at >= since,
            )
        )
        return result.scalar_one()


class NotificationRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def create_pending(self, listing_id: int, notification_type: str = "discord") -> Notification:
        notification = Notification(
            listing_id=listing_id,
            type=notification_type,
            status=NotificationStatus.PENDING.value,
        )
        self.session.add(notification)
        await self.session.flush()
        return notification

    async def get(self, notification_id: int) -> Notification | None:
        return await self.session.get(Notification, notification_id)

    async def get_pending_or_failed(self, limit: int = 100) -> list[Notification]:
        result = await self.session.execute(
            select(Notification)
            .where(Notification.status != NotificationStatus.SENT.value)
            .order_by(Notification.created_at.asc())
            .limit(limit)
        )
        return list(result.scalars().all())

    async def mark_attempt(self, notification_id: int) -> None:
        notification = await self.get(notification_id)
        if notification is None:
            return
        notification.attempts += 1
        notification.last_attempt_at = utc_now()

    async def mark_sent(self, notification_id: int) -> None:
        notification = await self.get(notification_id)
        if notification is None:
            return
        notification.status = NotificationStatus.SENT.value
        notification.sent_at = utc_now()
        notification.error_message = None

    async def mark_failed(self, notification_id: int, error_message: str, *, final: bool) -> None:
        notification = await self.get(notification_id)
        if notification is None:
            return
        notification.status = (
            NotificationStatus.FAILED.value if final else NotificationStatus.PENDING.value
        )
        notification.error_message = error_message[:1000]

    async def counts_by_status(self) -> dict[str, int]:
        result = await self.session.execute(
            select(Notification.status, func.count(Notification.id)).group_by(Notification.status)
        )
        return {status: count for status, count in result.all()}

    async def latest_status_for_listing(self, listing_id: int) -> str | None:
        result = await self.session.execute(
            select(Notification.status)
            .where(Notification.listing_id == listing_id)
            .order_by(Notification.created_at.desc())
            .limit(1)
        )
        row = result.first()
        return row[0] if row else None


class ScanRunRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def start(self, keyword_id: int, started_at: datetime) -> ScanRun:
        run = ScanRun(keyword_id=keyword_id, started_at=started_at, status="RUNNING")
        self.session.add(run)
        await self.session.flush()
        return run

    async def finish(
        self,
        run_id: int,
        *,
        status: str,
        results_count: int | None,
        new_listings_count: int | None,
        error_message: str | None,
    ) -> None:
        run = await self.session.get(ScanRun, run_id)
        if run is None:
            return
        finished_at = utc_now()
        run.finished_at = finished_at
        run.duration_ms = max(0, round((finished_at - run.started_at).total_seconds() * 1000))
        run.status = status
        run.results_count = results_count
        run.new_listings_count = new_listings_count
        run.error_message = error_message

    async def recent_for_keyword(self, keyword_id: int, limit: int = 20) -> list[ScanRun]:
        result = await self.session.execute(
            select(ScanRun)
            .where(ScanRun.keyword_id == keyword_id)
            .order_by(ScanRun.started_at.desc())
            .limit(limit)
        )
        return list(result.scalars().all())

    async def counts_by_status_since(self, since: datetime) -> dict[str, int]:
        result = await self.session.execute(
            select(ScanRun.status, func.count(ScanRun.id))
            .where(ScanRun.started_at >= since)
            .group_by(ScanRun.status)
        )
        return {status: count for status, count in result.all()}

    async def average_duration_ms(self) -> float | None:
        result = await self.session.execute(
            select(func.avg(ScanRun.duration_ms)).where(ScanRun.duration_ms.is_not(None))
        )
        value = result.scalar_one()
        return round(value) if value is not None else None


class AppSettingRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def get(self, key: str, default: str | None = None) -> str | None:
        setting = await self.session.get(AppSetting, key)
        return setting.value if setting is not None else default

    async def get_all(self) -> dict[str, str]:
        result = await self.session.execute(select(AppSetting))
        return {row.key: row.value for row in result.scalars().all()}

    async def set(self, key: str, value: str) -> None:
        setting = await self.session.get(AppSetting, key)
        if setting is None:
            setting = AppSetting(key=key, value=value)
            self.session.add(setting)
        else:
            setting.value = value
            setting.updated_at = utc_now()
