"""SQLAlchemy ORM models — the single source of truth for the database
schema. See `migrations.py` for how this schema is created/evolved.

Every datetime column is conceptually UTC. SQLite has no native
timezone-aware timestamp type, so plain `UTCDateTime()` silently
round-trips values as naive — see `UTCDateTime` below, which is what every
timestamp column actually uses, so a value read back from the database is
always timezone-aware and safe to use in arithmetic against `utc_now()`.
"""

from __future__ import annotations

from datetime import UTC, datetime
from enum import StrEnum

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    TypeDecorator,
    UniqueConstraint,
)
from sqlalchemy.engine import Dialect
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship

from app.utils.time import utc_now


class UTCDateTime(TypeDecorator):
    """A DateTime column that is always timezone-aware UTC on the Python
    side, regardless of what the underlying DB dialect can actually store.

    SQLite has no native tz-aware timestamp type: a plain `DateTime` stores
    whatever it's given and hands back a naive value on read, which breaks
    arithmetic against `utc_now()` the moment a value survives a round
    trip. This type strips tzinfo before writing (asserting UTC first) and
    re-attaches `tzinfo=UTC` after reading, so every datetime that leaves
    the database is safe to compare/subtract without callers remembering
    to convert it themselves.
    """

    impl = DateTime
    cache_ok = True

    def process_bind_param(self, value: datetime | None, dialect: Dialect) -> datetime | None:
        if value is None:
            return None
        if value.tzinfo is not None:
            value = value.astimezone(UTC).replace(tzinfo=None)
        return value

    def process_result_value(self, value: datetime | None, dialect: Dialect) -> datetime | None:
        if value is None:
            return None
        return value.replace(tzinfo=UTC)


class Base(DeclarativeBase):
    pass


class KeywordStatus(StrEnum):
    ACTIVE = "ACTIVE"
    PAUSED = "PAUSED"
    THROTTLED = "THROTTLED"
    DEGRADED = "DEGRADED"
    BACKOFF = "BACKOFF"
    ERROR = "ERROR"


class NotificationStatus(StrEnum):
    PENDING = "PENDING"
    SENT = "SENT"
    FAILED = "FAILED"


class ScanStatus(StrEnum):
    SUCCESS = "SUCCESS"
    FAILED = "FAILED"
    THROTTLED = "THROTTLED"
    ERROR = "ERROR"


class Keyword(Base):
    __tablename__ = "keywords"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    keyword: Mapped[str] = mapped_column(String(200), nullable=False)
    active: Mapped[bool] = mapped_column(default=True, nullable=False)
    status: Mapped[str] = mapped_column(
        String(20), default=KeywordStatus.ACTIVE.value, nullable=False
    )

    scan_interval: Mapped[int] = mapped_column(Integer, nullable=False)
    discord_enabled: Mapped[bool] = mapped_column(default=True, nullable=False)

    min_price: Mapped[float | None] = mapped_column(Float, nullable=True)
    max_price: Mapped[float | None] = mapped_column(Float, nullable=True)

    category: Mapped[str | None] = mapped_column(String(120), nullable=True)
    brand: Mapped[str | None] = mapped_column(String(120), nullable=True)
    size: Mapped[str | None] = mapped_column(String(60), nullable=True)
    condition: Mapped[str | None] = mapped_column(String(60), nullable=True)
    location: Mapped[str | None] = mapped_column(String(120), nullable=True)
    sort: Mapped[str] = mapped_column(String(30), default="newest", nullable=False)

    # Comma-separated, case-insensitive substrings. Kept as simple text
    # rather than a related table: this is a small, user-edited list, not a
    # relational entity.
    include_keywords: Mapped[str | None] = mapped_column(Text, nullable=True)
    exclude_keywords: Mapped[str | None] = mapped_column(Text, nullable=True)

    # --- Scheduler state (persisted so it survives restarts/crashes) -----
    consecutive_failures: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    last_scan_at: Mapped[datetime | None] = mapped_column(UTCDateTime(), nullable=True)
    next_scan_at: Mapped[datetime | None] = mapped_column(UTCDateTime(), nullable=True)
    last_scan_duration_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)
    backoff_until: Mapped[datetime | None] = mapped_column(UTCDateTime(), nullable=True)
    last_error_message: Mapped[str | None] = mapped_column(Text, nullable=True)

    created_at: Mapped[datetime] = mapped_column(
        UTCDateTime(), default=utc_now, nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        UTCDateTime(), default=utc_now, onupdate=utc_now, nullable=False
    )

    listing_links: Mapped[list[ListingKeyword]] = relationship(
        back_populates="keyword", cascade="all, delete-orphan"
    )
    scan_runs: Mapped[list[ScanRun]] = relationship(
        back_populates="keyword", cascade="all, delete-orphan"
    )

    __table_args__ = (
        UniqueConstraint("keyword", name="uq_keywords_keyword"),
        CheckConstraint("scan_interval > 0", name="ck_keywords_scan_interval_positive"),
        CheckConstraint(
            "min_price IS NULL OR max_price IS NULL OR min_price <= max_price",
            name="ck_keywords_price_range",
        ),
    )


class Listing(Base):
    __tablename__ = "listings"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    external_id: Mapped[str] = mapped_column(String(120), nullable=False)

    # Nullable: a title is virtually always present in practice, but the
    # parser never fabricates one when the source genuinely omits it (see
    # app/mercari/normalizer.py) — a display fallback belongs in the UI,
    # not in the stored record.
    title: Mapped[str | None] = mapped_column(String(500), nullable=True)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    price: Mapped[float | None] = mapped_column(Float, nullable=True)
    currency: Mapped[str] = mapped_column(String(8), default="USD", nullable=False)
    brand: Mapped[str | None] = mapped_column(String(120), nullable=True)
    category: Mapped[str | None] = mapped_column(String(120), nullable=True)
    size: Mapped[str | None] = mapped_column(String(60), nullable=True)
    condition: Mapped[str | None] = mapped_column(String(60), nullable=True)
    # Mercari's own sale status (e.g. "for_sale", "sold", "on_hold") when the
    # source exposes it. Kept distinct from our own pipeline status.
    item_status: Mapped[str | None] = mapped_column(String(30), nullable=True)

    seller_username: Mapped[str | None] = mapped_column(String(120), nullable=True)
    seller_id: Mapped[str | None] = mapped_column(String(120), nullable=True)

    image_url: Mapped[str | None] = mapped_column(Text, nullable=True)
    listing_url: Mapped[str] = mapped_column(Text, nullable=False)

    # NULL unless the source genuinely provided a creation timestamp — never
    # invented (see app/mercari/normalizer.py).
    created_at_source: Mapped[datetime | None] = mapped_column(
        UTCDateTime(), nullable=True
    )
    detected_at: Mapped[datetime] = mapped_column(UTCDateTime(), nullable=False)
    detection_latency_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)

    created_at_db: Mapped[datetime] = mapped_column(
        UTCDateTime(), default=utc_now, nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        UTCDateTime(), default=utc_now, onupdate=utc_now, nullable=False
    )

    keyword_links: Mapped[list[ListingKeyword]] = relationship(
        back_populates="listing", cascade="all, delete-orphan"
    )
    notifications: Mapped[list[Notification]] = relationship(
        back_populates="listing", cascade="all, delete-orphan"
    )

    __table_args__ = (
        UniqueConstraint("external_id", name="uq_listings_external_id"),
        Index("ix_listings_detected_at", "detected_at"),
        Index("ix_listings_created_at_source", "created_at_source"),
        Index("ix_listings_price", "price"),
        Index("ix_listings_brand", "brand"),
    )


class ListingKeyword(Base):
    """Which searches matched a given listing (many-to-many). A listing is
    stored once; every keyword that found it gets a row here."""

    __tablename__ = "listing_keywords"

    listing_id: Mapped[int] = mapped_column(
        ForeignKey("listings.id", ondelete="CASCADE"), primary_key=True
    )
    keyword_id: Mapped[int] = mapped_column(
        ForeignKey("keywords.id", ondelete="CASCADE"), primary_key=True
    )
    first_detected_at: Mapped[datetime] = mapped_column(
        UTCDateTime(), default=utc_now, nullable=False
    )

    listing: Mapped[Listing] = relationship(back_populates="keyword_links")
    keyword: Mapped[Keyword] = relationship(back_populates="listing_links")

    __table_args__ = (Index("ix_listing_keywords_keyword_id", "keyword_id"),)


class Notification(Base):
    __tablename__ = "notifications"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    listing_id: Mapped[int] = mapped_column(
        ForeignKey("listings.id", ondelete="CASCADE"), nullable=False
    )
    type: Mapped[str] = mapped_column(String(30), default="discord", nullable=False)
    status: Mapped[str] = mapped_column(
        String(20), default=NotificationStatus.PENDING.value, nullable=False
    )
    attempts: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    last_attempt_at: Mapped[datetime | None] = mapped_column(UTCDateTime(), nullable=True)
    sent_at: Mapped[datetime | None] = mapped_column(UTCDateTime(), nullable=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        UTCDateTime(), default=utc_now, nullable=False
    )

    listing: Mapped[Listing] = relationship(back_populates="notifications")

    __table_args__ = (Index("ix_notifications_status", "status"),)


class ScanRun(Base):
    __tablename__ = "scan_runs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    keyword_id: Mapped[int] = mapped_column(
        ForeignKey("keywords.id", ondelete="CASCADE"), nullable=False
    )
    started_at: Mapped[datetime] = mapped_column(UTCDateTime(), nullable=False)
    finished_at: Mapped[datetime | None] = mapped_column(UTCDateTime(), nullable=True)
    duration_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)
    results_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    new_listings_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    status: Mapped[str] = mapped_column(String(20), nullable=False)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)

    keyword: Mapped[Keyword] = relationship(back_populates="scan_runs")

    __table_args__ = (
        Index("ix_scan_runs_keyword_id_started_at", "keyword_id", "started_at"),
    )


class AppSetting(Base):
    """Small key/value store for runtime-editable UI preferences only
    (theme, sound/desktop notification toggles, ...).

    Infrastructure-level configuration (webhook URL, ports, concurrency,
    timeouts) is owned by `.env` / `Settings` and intentionally NOT stored
    here — see `app/api/routes.py` settings endpoints for the read-only vs
    mutable split, and the README for why.
    """

    __tablename__ = "app_settings"

    key: Mapped[str] = mapped_column(String(80), primary_key=True)
    value: Mapped[str] = mapped_column(Text, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        UTCDateTime(), default=utc_now, onupdate=utc_now, nullable=False
    )
