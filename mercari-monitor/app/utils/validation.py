"""Validation helpers for input crossing a system boundary (API requests,
imported config files). Internal code that already trusts its inputs
should not need to re-validate through here.
"""

from __future__ import annotations

import re

from app.config.defaults import MAX_PAGE_SIZE
from app.config.settings import settings

_DISCORD_WEBHOOK_RE = re.compile(
    r"^https://(discord|discordapp)\.com/api/webhooks/\d+/[\w-]+/?$"
)


class ValidationError(ValueError):
    """Raised when user-supplied input fails validation."""


def validate_keyword(keyword: str) -> str:
    cleaned = keyword.strip()
    if not cleaned:
        raise ValidationError("Keyword must not be empty.")
    if len(cleaned) > 200:
        raise ValidationError("Keyword must be 200 characters or fewer.")
    return cleaned


def validate_scan_interval(seconds: int) -> int:
    if seconds < settings.min_scan_interval:
        raise ValidationError(
            f"Scan interval must be at least {settings.min_scan_interval}s."
        )
    if seconds > 3600:
        raise ValidationError("Scan interval must be 3600s or less.")
    return seconds


def validate_price_range(min_price: float | None, max_price: float | None) -> None:
    if min_price is not None and min_price < 0:
        raise ValidationError("Minimum price cannot be negative.")
    if max_price is not None and max_price < 0:
        raise ValidationError("Maximum price cannot be negative.")
    if min_price is not None and max_price is not None and min_price > max_price:
        raise ValidationError("Minimum price cannot exceed maximum price.")


def validate_discord_webhook_url(url: str) -> str:
    cleaned = url.strip()
    if not _DISCORD_WEBHOOK_RE.match(cleaned):
        raise ValidationError("This does not look like a valid Discord webhook URL.")
    return cleaned


def clamp_page_size(page_size: int) -> int:
    return max(1, min(page_size, MAX_PAGE_SIZE))


def split_terms(raw: str | None) -> list[str]:
    """Inverse of `join_terms` — used both to re-expose a keyword's
    include/exclude lists over the API and to match them against a
    listing's text."""
    if not raw:
        return []
    return [term.strip() for term in raw.split(",") if term.strip()]


def join_terms(terms: list[str] | None) -> str | None:
    if not terms:
        return None
    cleaned = [t.strip() for t in terms if t.strip()]
    return ", ".join(cleaned) if cleaned else None
