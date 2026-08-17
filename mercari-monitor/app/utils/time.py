"""Time helpers.

Every timestamp stored in the database or passed between layers is
timezone-aware UTC. Conversion to a human display timezone happens only at
the presentation boundary (API serialization / frontend), never internally.
"""

from __future__ import annotations

from datetime import datetime, timezone
from zoneinfo import ZoneInfo

from app.config.settings import settings


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def to_utc(dt: datetime) -> datetime:
    """Return `dt` as timezone-aware UTC.

    A naive datetime is assumed to already be UTC rather than guessed as
    local time — guessing would silently shift timestamps whose origin
    timezone is genuinely unknown.
    """
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def to_display_timezone(dt: datetime) -> datetime:
    tz_name = settings.display_timezone
    if tz_name.upper() == "UTC":
        return to_utc(dt)
    try:
        return to_utc(dt).astimezone(ZoneInfo(tz_name))
    except Exception:
        return to_utc(dt)


def isoformat(dt: datetime) -> str:
    return to_utc(dt).isoformat()


def latency_ms(start: datetime, end: datetime) -> int:
    """Whole milliseconds between two timezone-aware instants, never negative."""
    delta = to_utc(end) - to_utc(start)
    return max(0, round(delta.total_seconds() * 1000))
