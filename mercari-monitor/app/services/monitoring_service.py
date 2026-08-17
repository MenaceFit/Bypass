"""The orchestrator: one background asyncio task per active keyword, each
running the loop from spec section 7:

    search -> extract IDs -> compare with DB -> new listings -> persist
        -> event bus -> dashboard + Discord

`mercari/monitor.py` supplies the pure "when should this run next" state
machine; this module is the async, side-effecting glue around it — DB
sessions, the event bus, the Discord queue, and the scan_runs audit trail.

Global concurrency/rate limiting is NOT duplicated here: every keyword
shares the same `MercariClient` (via the injected `MarketplaceSource`),
which already funnels all traffic through one `RateLimiter` (spec section
64). This module only decides *when* each keyword is due; the shared
limiter decides how many requests may actually be in flight at once.
"""

from __future__ import annotations

import asyncio
import contextlib
from datetime import datetime

from app.config.settings import settings
from app.database.database import session_scope
from app.database.models import Keyword, Listing
from app.database.repositories import (
    AppSettingRepository,
    KeywordRepository,
    ListingRepository,
    NotificationRepository,
    ScanRunRepository,
)
from app.events.bus import Event, EventType, event_bus
from app.mercari.client import MercariFetchStatus
from app.mercari.monitor import ScanOutcome, decide_next_run
from app.mercari.normalizer import NormalizedListing
from app.mercari.search import MarketplaceSource, MercariSourceError, SearchQuery
from app.services.listing_service import ListingService, build_listing_event_payload
from app.utils.logger import get_logger
from app.utils.time import latency_ms, utc_now

logger = get_logger(__name__)


class MonitoringService:
    def __init__(self, source: MarketplaceSource) -> None:
        self._source = source
        self._tasks: dict[int, asyncio.Task] = {}
        self._running_pause = asyncio.Event()
        self._running_pause.set()  # set = running, cleared = globally paused

    # --- Lifecycle -----------------------------------------------------
    async def start(self) -> None:
        async with session_scope() as session:
            keywords = await KeywordRepository(session).list_active()
        for keyword in keywords:
            self._spawn_task(keyword.id)
        logger.info("Monitoring service started with %d active keyword(s)", len(keywords))

    async def stop(self) -> None:
        for task in list(self._tasks.values()):
            task.cancel()
        for task in list(self._tasks.values()):
            with contextlib.suppress(asyncio.CancelledError):
                await task
        self._tasks.clear()
        logger.info("Monitoring service stopped")

    async def pause_all(self) -> None:
        self._running_pause.clear()
        logger.info("Monitoring paused globally")

    async def resume_all(self) -> None:
        self._running_pause.set()
        logger.info("Monitoring resumed globally")

    @property
    def is_globally_paused(self) -> bool:
        return not self._running_pause.is_set()

    def active_worker_count(self) -> int:
        return len(self._tasks)

    # --- Reacting to keyword CRUD (called from the API layer) -----------
    async def sync_keyword(self, keyword_id: int) -> None:
        async with session_scope() as session:
            keyword = await KeywordRepository(session).get(keyword_id)
        if keyword is None or not keyword.active:
            self._cancel_task(keyword_id)
            return
        if keyword_id not in self._tasks:
            self._spawn_task(keyword_id)

    def remove_keyword(self, keyword_id: int) -> None:
        self._cancel_task(keyword_id)

    async def run_scan_now(self, keyword_id: int) -> None:
        """Run a single scan cycle immediately, outside the keyword's own
        schedule. Used by tests (fixture-driven, no real browser needed)
        and available for a future manual "scan now" trigger."""
        await self._scan_once(keyword_id)

    def _spawn_task(self, keyword_id: int) -> None:
        if keyword_id in self._tasks:
            return
        self._tasks[keyword_id] = asyncio.create_task(self._run_keyword_loop(keyword_id))

    def _cancel_task(self, keyword_id: int) -> None:
        task = self._tasks.pop(keyword_id, None)
        if task is not None:
            task.cancel()

    # --- The per-keyword loop -------------------------------------------
    async def _run_keyword_loop(self, keyword_id: int) -> None:
        try:
            while True:
                await self._running_pause.wait()

                async with session_scope() as session:
                    keyword = await KeywordRepository(session).get(keyword_id)
                if keyword is None or not keyword.active:
                    return

                wait_seconds = _seconds_until(keyword.next_scan_at)
                if wait_seconds > 0:
                    await asyncio.sleep(wait_seconds)
                    continue

                await self._scan_once(keyword_id)
        except asyncio.CancelledError:
            raise

    # --- One scan cycle for one keyword ---------------------------------
    async def _scan_once(self, keyword_id: int) -> None:
        async with session_scope() as session:
            keyword = await KeywordRepository(session).get(keyword_id)
        if keyword is None or not keyword.active:
            return

        is_first_scan = keyword.last_scan_at is None
        scan_started_at = utc_now()
        async with session_scope() as session:
            await KeywordRepository(session).record_scan_start(keyword_id)

        await event_bus.publish(
            Event(EventType.SCAN_STARTED, {"keyword_id": keyword_id, "keyword": keyword.keyword})
        )
        scan_run_id = await self._start_scan_run(keyword_id)

        results_count, new_count, outcome, error_message = await self._execute_scan(
            keyword, is_first_scan=is_first_scan
        )
        duration_ms = latency_ms(scan_started_at, utc_now())

        await self._finish_scan_run(
            scan_run_id, outcome=outcome, results_count=results_count, new_count=new_count,
            error_message=error_message,
        )
        await self._apply_scheduler_decision(keyword, outcome, error_message, duration_ms)
        await self._publish_scan_finished(keyword_id, outcome, results_count, new_count)
        await event_bus.publish(Event(EventType.SYSTEM_STATUS_CHANGED, await self.system_status()))

    async def _execute_scan(
        self, keyword: Keyword, *, is_first_scan: bool
    ) -> tuple[int, int, ScanOutcome, str | None]:
        try:
            query = _build_search_query(keyword)
            normalized_listings = await self._source.search(query)
        except MercariSourceError as exc:
            await self._report_scraper_error(keyword.id, exc)
            outcome = ScanOutcome(
                success=False,
                throttled=exc.status is MercariFetchStatus.RATE_LIMITED,
                retry_after_seconds=exc.retry_after_seconds,
                error_message=str(exc),
            )
            return 0, 0, outcome, str(exc)
        except Exception as exc:  # defensive: a scan must never crash the loop
            logger.exception("Unexpected error scanning keyword %s", keyword.id)
            await event_bus.publish(
                Event(EventType.SCRAPER_ERROR, {"keyword_id": keyword.id, "reason": str(exc)})
            )
            return 0, 0, ScanOutcome(success=False, error_message=str(exc)), str(exc)

        detection = await self._persist_results(keyword, normalized_listings)
        first_run_mode = await _get_first_run_mode()
        should_notify = not (is_first_scan and first_run_mode == "import_silent")
        for listing, normalized in detection.new_listings:
            await self._handle_new_listing(keyword, listing, normalized, notify=should_notify)

        return len(normalized_listings), len(detection.new_listings), ScanOutcome(success=True), None

    async def _persist_results(self, keyword: Keyword, normalized_listings: list[NormalizedListing]):
        async with session_scope() as session:
            listing_service = ListingService(ListingRepository(session))
            return await listing_service.process_search_results(keyword, normalized_listings)

    async def _report_scraper_error(self, keyword_id: int, exc: MercariSourceError) -> None:
        await event_bus.publish(
            Event(EventType.SCRAPER_ERROR, {"keyword_id": keyword_id, "reason": str(exc), "status": exc.status.value})
        )
        if exc.status is MercariFetchStatus.RATE_LIMITED:
            await event_bus.publish(
                Event(
                    EventType.RATE_LIMITED,
                    {"keyword_id": keyword_id, "retry_after_seconds": exc.retry_after_seconds},
                )
            )

    async def _handle_new_listing(
        self, keyword: Keyword, listing: Listing, normalized: NormalizedListing, *, notify: bool
    ) -> None:
        async with session_scope() as session:
            matched_keywords = await ListingRepository(session).keywords_for_listing(listing.id)

        payload = build_listing_event_payload(listing, keyword, matched_keywords)
        payload_dict = payload.model_dump(mode="json")

        await event_bus.publish(Event(EventType.LISTING_STORED, payload_dict))

        if not notify:
            return

        await event_bus.publish(Event(EventType.LISTING_DISCOVERED, payload_dict))

        if keyword.discord_enabled and settings.has_discord:
            async with session_scope() as session:
                notification = await NotificationRepository(session).create_pending(listing.id)
            await event_bus.publish(
                Event(
                    EventType.DISCORD_NOTIFICATION_REQUIRED,
                    {**payload_dict, "notification_id": notification.id},
                )
            )

    async def _start_scan_run(self, keyword_id: int) -> int:
        async with session_scope() as session:
            run = await ScanRunRepository(session).start(keyword_id, utc_now())
            return run.id

    async def _finish_scan_run(
        self,
        scan_run_id: int,
        *,
        outcome: ScanOutcome,
        results_count: int,
        new_count: int,
        error_message: str | None,
    ) -> None:
        status = "SUCCESS" if outcome.success else ("THROTTLED" if outcome.throttled else "ERROR")
        async with session_scope() as session:
            await ScanRunRepository(session).finish(
                scan_run_id,
                status=status,
                results_count=results_count,
                new_listings_count=new_count,
                error_message=error_message,
            )

    async def _apply_scheduler_decision(
        self, keyword: Keyword, outcome: ScanOutcome, error_message: str | None, duration_ms: int
    ) -> None:
        decision = decide_next_run(
            now=utc_now(),
            scan_interval_seconds=keyword.scan_interval,
            consecutive_failures=keyword.consecutive_failures,
            outcome=outcome,
        )
        async with session_scope() as session:
            await KeywordRepository(session).record_scan_result(
                keyword.id,
                status=decision.status,
                duration_ms=duration_ms,
                next_scan_at=decision.next_scan_at,
                consecutive_failures=decision.consecutive_failures,
                backoff_until=decision.backoff_until,
                error_message=error_message,
            )
        await event_bus.publish(
            Event(
                EventType.KEYWORD_UPDATED,
                {"keyword_id": keyword.id, "status": decision.status, "next_scan_at": decision.next_scan_at.isoformat()},
            )
        )

    async def _publish_scan_finished(
        self, keyword_id: int, outcome: ScanOutcome, results_count: int, new_count: int
    ) -> None:
        await event_bus.publish(
            Event(
                EventType.SCAN_FINISHED,
                {
                    "keyword_id": keyword_id,
                    "success": outcome.success,
                    "results_count": results_count,
                    "new_listings_count": new_count,
                },
            )
        )

    async def system_status(self) -> dict:
        source_health = await self._source.health_check()
        return {
            "source_available": source_health.available,
            "source_status": source_health.status,
            "source_reason": source_health.reason,
            "active_workers": self.active_worker_count(),
            "globally_paused": self.is_globally_paused,
        }


def _build_search_query(keyword: Keyword) -> SearchQuery:
    return SearchQuery(
        keyword=keyword.keyword,
        min_price=keyword.min_price,
        max_price=keyword.max_price,
        category=keyword.category,
        brand=keyword.brand,
        size=keyword.size,
        condition=keyword.condition,
        location=keyword.location,
        sort=keyword.sort,
    )


def _seconds_until(target: datetime | None) -> float:
    if target is None:
        return 0.0
    return max(0.0, (target - utc_now()).total_seconds())


async def _get_first_run_mode() -> str:
    """The UI (spec section 33's first-run dialog) can override this at
    runtime via PUT /api/settings; `settings.first_run_mode` (.env) is only
    the default until it does."""
    async with session_scope() as session:
        stored = await AppSettingRepository(session).get("first_run_mode")
    return stored or settings.first_run_mode
