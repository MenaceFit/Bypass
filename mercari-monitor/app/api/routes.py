"""REST API. FastAPI generates OpenAPI docs from this automatically (spec
section 50) — visit /docs once the server is running.

Every handler opens its own `session_scope()` rather than relying on a
FastAPI dependency that defers the commit to request teardown: several
handlers trigger a `MonitoringService` side effect (spawning/cancelling a
scan task) that immediately re-reads the keyword from the database, so the
write has to be committed *before* that happens, not after the response is
built.
"""

from __future__ import annotations

import csv
import io
from collections.abc import AsyncIterator
from datetime import datetime, timedelta
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import StreamingResponse
from sqlalchemy import delete as sql_delete
from sqlalchemy import text

from app.config.defaults import DEFAULT_PAGE_SIZE
from app.config.settings import settings
from app.database.database import session_scope
from app.database.models import Keyword, Listing, ListingKeyword, Notification, NotificationStatus, ScanRun
from app.database.repositories import (
    AppSettingRepository,
    KeywordRepository,
    ListingFilter,
    ListingKeywordRepository,
    ListingRepository,
    NotificationRepository,
)
from app.mercari.rate_limiter import metrics
from app.notifications.discord import DiscordDeliveryError
from app.services.keyword_service import DuplicateKeywordError, KeywordInput, KeywordService
from app.services.monitoring_service import MonitoringService
from app.services.notification_service import notification_service
from app.utils.logger import get_recent_logs
from app.utils.time import isoformat, utc_now
from app.utils.validation import split_terms

from .schemas import (
    ArchiveListingsRequest,
    DatabaseResetRequest,
    DiscordTestResponse,
    HealthResponse,
    KeywordResponse,
    KeywordWriteRequest,
    ListingResponse,
    LogEntryResponse,
    MessageResponse,
    PaginatedListingsResponse,
    SearchesImportRequest,
    SearchExportItem,
    SettingsResponse,
    SettingsUpdateRequest,
    StatsResponse,
    SystemStatusResponse,
)

router = APIRouter(prefix="/api")

_RESET_CONFIRMATION_PHRASE = "DELETE ALL DATA"
_CSV_HEADER = [
    "ID", "Title", "Price", "Currency", "Brand", "Category", "Size", "Condition",
    "Seller", "Keyword", "Created At", "Detected At", "Detection Latency (ms)", "URL",
]


def get_monitoring_service(request: Request) -> MonitoringService:
    return request.app.state.monitoring_service


MonitoringServiceDep = Annotated[MonitoringService, Depends(get_monitoring_service)]


def _to_keyword_input(body: KeywordWriteRequest) -> KeywordInput:
    return KeywordInput(
        keyword=body.keyword,
        scan_interval=body.scan_interval,
        discord_enabled=body.discord_enabled,
        min_price=body.min_price,
        max_price=body.max_price,
        category=body.category,
        brand=body.brand,
        size=body.size,
        condition=body.condition,
        location=body.location,
        sort=body.sort,
        include_keywords=body.include_keywords,
        exclude_keywords=body.exclude_keywords,
    )


def _start_of_today() -> datetime:
    # UTC day boundary, consistent with "storage is always UTC" (spec
    # section 42) — a deliberate simplification for a local single-user
    # tool rather than per-user local-midnight bucketing.
    return utc_now().replace(hour=0, minute=0, second=0, microsecond=0)


# --- Health -----------------------------------------------------------------
@router.get("/health", response_model=HealthResponse)
async def health(monitoring: MonitoringServiceDep) -> HealthResponse:
    database_ok = await _check_database()
    status_info = await monitoring.system_status()
    return HealthResponse(
        status="ok" if database_ok else "degraded",
        database=database_ok,
        mercari=status_info["source_available"],
        discord=settings.has_discord,
        websocket=True,
    )


async def _check_database() -> bool:
    try:
        async with session_scope() as session:
            await session.execute(text("SELECT 1"))
        return True
    except Exception:
        return False


# --- Searches ----------------------------------------------------------------
@router.get("/searches", response_model=list[KeywordResponse])
async def list_searches() -> list[KeywordResponse]:
    today_start = _start_of_today()
    async with session_scope() as session:
        keywords = await KeywordRepository(session).list_all()
        link_repo = ListingKeywordRepository(session)
        responses = []
        for kw in keywords:
            new_today = await link_repo.link_count_for_keyword_since(kw.id, today_start)
            total = await link_repo.link_count_for_keyword(kw.id)
            responses.append(KeywordResponse.from_model(kw, new_today=new_today, total_listings=total))
    return responses


@router.get("/searches/export", response_model=list[SearchExportItem])
async def export_searches() -> list[SearchExportItem]:
    async with session_scope() as session:
        keywords = await KeywordRepository(session).list_all()
    return [
        SearchExportItem(
            keyword=k.keyword,
            scan_interval=k.scan_interval,
            discord_enabled=k.discord_enabled,
            min_price=k.min_price,
            max_price=k.max_price,
            category=k.category,
            brand=k.brand,
            size=k.size,
            condition=k.condition,
            location=k.location,
            sort=k.sort,
            include_keywords=split_terms(k.include_keywords),
            exclude_keywords=split_terms(k.exclude_keywords),
        )
        for k in keywords
    ]


@router.post("/searches/import", response_model=list[KeywordResponse])
async def import_searches(
    body: SearchesImportRequest, monitoring: MonitoringServiceDep
) -> list[KeywordResponse]:
    created_ids: list[int] = []
    async with session_scope() as session:
        service = KeywordService(KeywordRepository(session))
        for item in body.searches:
            try:
                keyword = await service.create(_to_keyword_input(item))
            except DuplicateKeywordError:
                continue  # already exists — importing it again is a no-op, not an error
            created_ids.append(keyword.id)

    for keyword_id in created_ids:
        await monitoring.sync_keyword(keyword_id)

    async with session_scope() as session:
        keyword_repo = KeywordRepository(session)
        return [KeywordResponse.from_model(await keyword_repo.get(kid)) for kid in created_ids]


@router.get("/searches/{search_id}", response_model=KeywordResponse)
async def get_search(search_id: int) -> KeywordResponse:
    today_start = _start_of_today()
    async with session_scope() as session:
        keyword = await KeywordRepository(session).get(search_id)
        if keyword is None:
            raise HTTPException(status_code=404, detail="Search not found.")
        link_repo = ListingKeywordRepository(session)
        new_today = await link_repo.link_count_for_keyword_since(search_id, today_start)
        total = await link_repo.link_count_for_keyword(search_id)
    return KeywordResponse.from_model(keyword, new_today=new_today, total_listings=total)


@router.post("/searches", response_model=KeywordResponse, status_code=201)
async def create_search(body: KeywordWriteRequest, monitoring: MonitoringServiceDep) -> KeywordResponse:
    async with session_scope() as session:
        keyword = await KeywordService(KeywordRepository(session)).create(_to_keyword_input(body))
        keyword_id = keyword.id
    await monitoring.sync_keyword(keyword_id)
    async with session_scope() as session:
        return KeywordResponse.from_model(await KeywordRepository(session).get(keyword_id))


@router.put("/searches/{search_id}", response_model=KeywordResponse)
async def update_search(
    search_id: int, body: KeywordWriteRequest, monitoring: MonitoringServiceDep
) -> KeywordResponse:
    async with session_scope() as session:
        keyword = await KeywordService(KeywordRepository(session)).update(
            search_id, _to_keyword_input(body)
        )
        if keyword is None:
            raise HTTPException(status_code=404, detail="Search not found.")
    await monitoring.sync_keyword(search_id)
    async with session_scope() as session:
        return KeywordResponse.from_model(await KeywordRepository(session).get(search_id))


@router.delete("/searches/{search_id}", response_model=MessageResponse)
async def delete_search(search_id: int, monitoring: MonitoringServiceDep) -> MessageResponse:
    monitoring.remove_keyword(search_id)
    async with session_scope() as session:
        deleted = await KeywordRepository(session).delete(search_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="Search not found.")
    return MessageResponse(success=True, message="Search deleted.")


@router.post("/searches/{search_id}/pause", response_model=KeywordResponse)
async def pause_search(search_id: int, monitoring: MonitoringServiceDep) -> KeywordResponse:
    async with session_scope() as session:
        keyword = await KeywordRepository(session).set_active(search_id, False)
    if keyword is None:
        raise HTTPException(status_code=404, detail="Search not found.")
    await monitoring.sync_keyword(search_id)
    return KeywordResponse.from_model(keyword)


@router.post("/searches/{search_id}/resume", response_model=KeywordResponse)
async def resume_search(search_id: int, monitoring: MonitoringServiceDep) -> KeywordResponse:
    async with session_scope() as session:
        keyword = await KeywordRepository(session).set_active(search_id, True)
    if keyword is None:
        raise HTTPException(status_code=404, detail="Search not found.")
    await monitoring.sync_keyword(search_id)
    return KeywordResponse.from_model(keyword)


# --- Monitoring (global controls) --------------------------------------------
@router.get("/monitoring/status", response_model=SystemStatusResponse)
async def monitoring_status(monitoring: MonitoringServiceDep) -> SystemStatusResponse:
    from app.api.websocket import connection_manager

    status_info = await monitoring.system_status()
    return SystemStatusResponse(
        source_available=status_info["source_available"],
        source_status=status_info["source_status"],
        source_reason=status_info["source_reason"],
        active_workers=status_info["active_workers"],
        globally_paused=status_info["globally_paused"],
        websocket_connections=connection_manager.connection_count,
    )


@router.post("/monitoring/pause-all", response_model=MessageResponse)
async def pause_all(monitoring: MonitoringServiceDep) -> MessageResponse:
    await monitoring.pause_all()
    return MessageResponse(success=True, message="Monitoring paused for all searches.")


@router.post("/monitoring/resume-all", response_model=MessageResponse)
async def resume_all(monitoring: MonitoringServiceDep) -> MessageResponse:
    await monitoring.resume_all()
    return MessageResponse(success=True, message="Monitoring resumed for all searches.")


# --- Listings ------------------------------------------------------------
@router.get("/listings", response_model=PaginatedListingsResponse)
async def list_listings(
    keyword_id: int | None = None,
    brand: str | None = None,
    size: str | None = None,
    condition: str | None = None,
    min_price: float | None = None,
    max_price: float | None = None,
    seller: str | None = None,
    discord_status: str | None = None,
    date_from: datetime | None = None,
    date_to: datetime | None = None,
    sort: str = "newest",
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=DEFAULT_PAGE_SIZE, ge=1, le=100),
) -> PaginatedListingsResponse:
    filters = ListingFilter(
        keyword_id=keyword_id,
        brand=brand,
        size=size,
        condition=condition,
        min_price=min_price,
        max_price=max_price,
        seller_username=seller,
        discord_status=discord_status,
        detected_after=date_from,
        detected_before=date_to,
    )
    async with session_scope() as session:
        listing_repo = ListingRepository(session)
        notification_repo = NotificationRepository(session)
        page_result = await listing_repo.list_paginated(filters, sort=sort, page=page, page_size=page_size)
        items = [
            ListingResponse.from_model(
                listing,
                matched_keywords=await listing_repo.keywords_for_listing(listing.id),
                discord_status=await notification_repo.latest_status_for_listing(listing.id),
            )
            for listing in page_result.items
        ]
    return PaginatedListingsResponse(
        items=items,
        total=page_result.total,
        page=page_result.page,
        page_size=page_result.page_size,
        total_pages=page_result.total_pages,
    )


@router.get("/listings/export")
async def export_listings_csv(
    keyword_id: int | None = None,
    brand: str | None = None,
    min_price: float | None = None,
    max_price: float | None = None,
) -> StreamingResponse:
    filters = ListingFilter(keyword_id=keyword_id, brand=brand, min_price=min_price, max_price=max_price)
    return StreamingResponse(
        _stream_listings_csv(filters),
        media_type="text/csv",
        headers={"Content-Disposition": "attachment; filename=mercari-listings.csv"},
    )


async def _stream_listings_csv(filters: ListingFilter) -> AsyncIterator[str]:
    buffer = io.StringIO()
    writer = csv.writer(buffer)
    writer.writerow(_CSV_HEADER)
    yield buffer.getvalue()

    page = 1
    chunk_size = 1000
    while True:
        buffer.seek(0)
        buffer.truncate(0)
        async with session_scope() as session:
            listing_repo = ListingRepository(session)
            result = await listing_repo.list_paginated(filters, sort="newest", page=page, page_size=chunk_size)
            for listing in result.items:
                matched = await listing_repo.keywords_for_listing(listing.id)
                writer.writerow(
                    [
                        listing.id,
                        listing.title,
                        listing.price,
                        listing.currency,
                        listing.brand,
                        listing.category,
                        listing.size,
                        listing.condition,
                        listing.seller_username,
                        ", ".join(matched),
                        isoformat(listing.created_at_source) if listing.created_at_source else "",
                        isoformat(listing.detected_at),
                        listing.detection_latency_ms,
                        listing.listing_url,
                    ]
                )
            has_more = page < result.total_pages
        yield buffer.getvalue()
        if not has_more:
            break
        page += 1


@router.post("/listings/archive", response_model=MessageResponse)
async def archive_listings(body: ArchiveListingsRequest) -> MessageResponse:
    cutoff = utc_now() - timedelta(days=body.older_than_days)
    async with session_scope() as session:
        deleted = await ListingRepository(session).delete_older_than(cutoff)
    return MessageResponse(
        success=True, message=f"Deleted {deleted} listing(s) older than {body.older_than_days} days."
    )


@router.get("/listings/{listing_id}", response_model=ListingResponse)
async def get_listing(listing_id: int) -> ListingResponse:
    async with session_scope() as session:
        listing_repo = ListingRepository(session)
        listing = await listing_repo.get(listing_id)
        if listing is None:
            raise HTTPException(status_code=404, detail="Listing not found.")
        matched = await listing_repo.keywords_for_listing(listing.id)
        discord_status = await NotificationRepository(session).latest_status_for_listing(listing.id)
    return ListingResponse.from_model(listing, matched_keywords=matched, discord_status=discord_status)


# --- Statistics ----------------------------------------------------------
@router.get("/stats", response_model=StatsResponse)
async def get_stats() -> StatsResponse:
    today_start = _start_of_today()
    week_start = today_start - timedelta(days=today_start.weekday())
    month_start = today_start.replace(day=1)

    async with session_scope() as session:
        listing_repo = ListingRepository(session)
        notification_repo = NotificationRepository(session)

        listings_today = await listing_repo.count_detected_since(today_start)
        listings_week = await listing_repo.count_detected_since(week_start)
        listings_month = await listing_repo.count_detected_since(month_start)
        total_listings = await listing_repo.total_count()
        latency = await listing_repo.latency_stats()
        most_active_keyword = await listing_repo.most_active_keyword()
        most_detected_brand = await listing_repo.most_detected_brand()
        average_price = await listing_repo.average_price()
        discord_counts = await notification_repo.counts_by_status()

    request_metrics = metrics.snapshot()

    return StatsResponse(
        listings_today=listings_today,
        listings_this_week=listings_week,
        listings_this_month=listings_month,
        total_listings=total_listings,
        avg_detection_latency_ms=latency["avg_detection_latency_ms"],
        fastest_detection_ms=latency["fastest_detection_ms"],
        slowest_detection_ms=latency["slowest_detection_ms"],
        most_active_keyword=most_active_keyword,
        most_detected_brand=most_detected_brand,
        average_price=average_price,
        discord_sent=discord_counts.get(NotificationStatus.SENT.value, 0),
        discord_failed=discord_counts.get(NotificationStatus.FAILED.value, 0),
        discord_pending=discord_counts.get(NotificationStatus.PENDING.value, 0),
        total_requests=request_metrics["total_requests"],
        successful_requests=request_metrics["successful_requests"],
        failed_requests=request_metrics["failed_requests"],
        http_429_count=request_metrics["http_429_count"],
        average_response_time_ms=request_metrics["average_response_time_ms"],
    )


# --- Logs ------------------------------------------------------------------
@router.get("/logs", response_model=list[LogEntryResponse])
async def get_logs(limit: int = Query(default=200, ge=1, le=1000), level: str | None = None) -> list[LogEntryResponse]:
    entries = get_recent_logs(limit=limit, level=level)
    return [
        LogEntryResponse(timestamp=e.timestamp, level=e.level, logger=e.logger, message=e.message)
        for e in entries
    ]


# --- Discord -----------------------------------------------------------------
@router.post("/discord/test", response_model=DiscordTestResponse)
async def test_discord() -> DiscordTestResponse:
    try:
        await notification_service.send_test_message()
    except DiscordDeliveryError as exc:
        return DiscordTestResponse(success=False, message=str(exc))
    return DiscordTestResponse(success=True, message="Test message sent successfully.")


# --- Settings ------------------------------------------------------------
@router.get("/settings", response_model=SettingsResponse)
async def get_settings_endpoint() -> SettingsResponse:
    async with session_scope() as session:
        stored = await AppSettingRepository(session).get_all()
    return _settings_response(stored)


@router.put("/settings", response_model=SettingsResponse)
async def update_settings_endpoint(body: SettingsUpdateRequest) -> SettingsResponse:
    if body.theme is not None and body.theme not in ("dark", "light"):
        raise HTTPException(status_code=422, detail="theme must be 'dark' or 'light'.")
    if body.first_run_mode is not None and body.first_run_mode not in ("import_silent", "treat_as_new"):
        raise HTTPException(
            status_code=422, detail="first_run_mode must be 'import_silent' or 'treat_as_new'."
        )
    async with session_scope() as session:
        repo = AppSettingRepository(session)
        if body.theme is not None:
            await repo.set("theme", body.theme)
        if body.sound_notifications_enabled is not None:
            await repo.set(
                "sound_notifications_enabled", "true" if body.sound_notifications_enabled else "false"
            )
        if body.desktop_notifications_enabled is not None:
            await repo.set(
                "desktop_notifications_enabled",
                "true" if body.desktop_notifications_enabled else "false",
            )
        if body.first_run_mode is not None:
            await repo.set("first_run_mode", body.first_run_mode)
        stored = await repo.get_all()
    return _settings_response(stored)


def _settings_response(stored: dict[str, str]) -> SettingsResponse:
    return SettingsResponse(
        app_host=settings.app_host,
        app_port=settings.app_port,
        default_scan_interval=settings.default_scan_interval,
        min_scan_interval=settings.min_scan_interval,
        max_concurrent_requests=settings.max_concurrent_requests,
        min_request_interval_ms=settings.min_request_interval_ms,
        request_timeout=settings.request_timeout,
        retry_max_attempts=settings.retry_max_attempts,
        discord_configured=settings.has_discord,
        discord_webhook_masked=settings.masked_discord_webhook(),
        log_level=settings.log_level,
        database_url=settings.database_url,
        archive_after_days=settings.archive_after_days,
        first_run_mode=stored.get("first_run_mode", settings.first_run_mode),
        theme=stored.get("theme", "dark"),
        sound_notifications_enabled=stored.get("sound_notifications_enabled") == "true",
        desktop_notifications_enabled=stored.get("desktop_notifications_enabled") == "true",
    )


# --- Database maintenance -----------------------------------------------
@router.post("/database/reset", response_model=MessageResponse)
async def reset_database(body: DatabaseResetRequest, monitoring: MonitoringServiceDep) -> MessageResponse:
    if body.confirm != _RESET_CONFIRMATION_PHRASE:
        raise HTTPException(
            status_code=400,
            detail=f"Confirmation phrase must be exactly {_RESET_CONFIRMATION_PHRASE!r}.",
        )
    await monitoring.stop()
    async with session_scope() as session:
        for table in (Notification, ListingKeyword, ScanRun, Listing, Keyword):
            await session.execute(sql_delete(table))
    return MessageResponse(success=True, message="All listings, searches, and history have been deleted.")
