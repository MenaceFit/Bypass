"""Pydantic request/response models for the REST API. Kept separate from
`routes.py` so the wire format is easy to scan without wading through
handler logic, and from the database models so a schema change doesn't
have to mean a DB migration (and vice versa)."""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field

from app.database.models import Keyword, Listing
from app.utils.validation import split_terms


class KeywordWriteRequest(BaseModel):
    keyword: str
    scan_interval: int | None = None
    discord_enabled: bool = True
    min_price: float | None = None
    max_price: float | None = None
    category: str | None = None
    brand: str | None = None
    size: str | None = None
    condition: str | None = None
    location: str | None = None
    sort: str = "newest"
    include_keywords: list[str] = Field(default_factory=list)
    exclude_keywords: list[str] = Field(default_factory=list)


class KeywordResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    keyword: str
    active: bool
    status: str
    scan_interval: int
    discord_enabled: bool
    min_price: float | None
    max_price: float | None
    category: str | None
    brand: str | None
    size: str | None
    condition: str | None
    location: str | None
    sort: str
    include_keywords: list[str]
    exclude_keywords: list[str]
    consecutive_failures: int
    last_scan_at: datetime | None
    next_scan_at: datetime | None
    last_scan_duration_ms: int | None
    backoff_until: datetime | None
    last_error_message: str | None
    created_at: datetime
    updated_at: datetime
    new_today: int = 0
    total_listings: int = 0

    @classmethod
    def from_model(cls, keyword: Keyword, *, new_today: int = 0, total_listings: int = 0) -> KeywordResponse:
        return cls(
            id=keyword.id,
            keyword=keyword.keyword,
            active=keyword.active,
            status=keyword.status,
            scan_interval=keyword.scan_interval,
            discord_enabled=keyword.discord_enabled,
            min_price=keyword.min_price,
            max_price=keyword.max_price,
            category=keyword.category,
            brand=keyword.brand,
            size=keyword.size,
            condition=keyword.condition,
            location=keyword.location,
            sort=keyword.sort,
            include_keywords=split_terms(keyword.include_keywords),
            exclude_keywords=split_terms(keyword.exclude_keywords),
            consecutive_failures=keyword.consecutive_failures,
            last_scan_at=keyword.last_scan_at,
            next_scan_at=keyword.next_scan_at,
            last_scan_duration_ms=keyword.last_scan_duration_ms,
            backoff_until=keyword.backoff_until,
            last_error_message=keyword.last_error_message,
            created_at=keyword.created_at,
            updated_at=keyword.updated_at,
            new_today=new_today,
            total_listings=total_listings,
        )


class ListingResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    external_id: str
    title: str | None
    description: str | None
    price: float | None
    currency: str
    brand: str | None
    category: str | None
    size: str | None
    condition: str | None
    item_status: str | None
    seller_username: str | None
    seller_id: str | None
    image_url: str | None
    listing_url: str
    created_at_source: datetime | None
    detected_at: datetime
    detection_latency_ms: int | None
    created_at_db: datetime
    matched_keywords: list[str] = Field(default_factory=list)
    discord_status: str | None = None

    @classmethod
    def from_model(
        cls, listing: Listing, *, matched_keywords: list[str], discord_status: str | None
    ) -> ListingResponse:
        return cls(
            id=listing.id,
            external_id=listing.external_id,
            title=listing.title,
            description=listing.description,
            price=listing.price,
            currency=listing.currency,
            brand=listing.brand,
            category=listing.category,
            size=listing.size,
            condition=listing.condition,
            item_status=listing.item_status,
            seller_username=listing.seller_username,
            seller_id=listing.seller_id,
            image_url=listing.image_url,
            listing_url=listing.listing_url,
            created_at_source=listing.created_at_source,
            detected_at=listing.detected_at,
            detection_latency_ms=listing.detection_latency_ms,
            created_at_db=listing.created_at_db,
            matched_keywords=matched_keywords,
            discord_status=discord_status,
        )


class PaginatedListingsResponse(BaseModel):
    items: list[ListingResponse]
    total: int
    page: int
    page_size: int
    total_pages: int


class StatsResponse(BaseModel):
    listings_today: int
    listings_this_week: int
    listings_this_month: int
    total_listings: int
    avg_detection_latency_ms: int | None
    fastest_detection_ms: int | None
    slowest_detection_ms: int | None
    most_active_keyword: str | None
    most_detected_brand: str | None
    average_price: float | None
    discord_sent: int
    discord_failed: int
    discord_pending: int
    total_requests: int
    successful_requests: int
    failed_requests: int
    http_429_count: int
    average_response_time_ms: int | None


class LogEntryResponse(BaseModel):
    timestamp: datetime
    level: str
    logger: str
    message: str


class SettingsResponse(BaseModel):
    # Environment-managed (read-only through this API — see README).
    app_host: str
    app_port: int
    default_scan_interval: int
    min_scan_interval: int
    max_concurrent_requests: int
    min_request_interval_ms: int
    request_timeout: int
    retry_max_attempts: int
    discord_configured: bool
    discord_webhook_masked: str | None
    log_level: str
    database_url: str
    archive_after_days: int
    first_run_mode: str
    # Stored in `app_settings`, mutable through PUT /api/settings.
    theme: str = "dark"
    sound_notifications_enabled: bool = False
    desktop_notifications_enabled: bool = False


class SettingsUpdateRequest(BaseModel):
    theme: str | None = None
    sound_notifications_enabled: bool | None = None
    desktop_notifications_enabled: bool | None = None
    first_run_mode: str | None = None


class HealthResponse(BaseModel):
    status: str
    database: bool
    mercari: bool
    discord: bool
    websocket: bool


class SystemStatusResponse(BaseModel):
    source_available: bool
    source_status: str
    source_reason: str | None
    active_workers: int
    globally_paused: bool
    websocket_connections: int


class DiscordTestResponse(BaseModel):
    success: bool
    message: str


class MessageResponse(BaseModel):
    success: bool
    message: str


class SearchExportItem(BaseModel):
    keyword: str
    scan_interval: int
    discord_enabled: bool
    min_price: float | None
    max_price: float | None
    category: str | None
    brand: str | None
    size: str | None
    condition: str | None
    location: str | None
    sort: str
    include_keywords: list[str]
    exclude_keywords: list[str]


class SearchesImportRequest(BaseModel):
    searches: list[KeywordWriteRequest]


class DatabaseResetRequest(BaseModel):
    confirm: str


class ArchiveListingsRequest(BaseModel):
    older_than_days: int = Field(gt=0, le=3650)
