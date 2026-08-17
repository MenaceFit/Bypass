"""Turns a `RawListing` into a clean, typed `NormalizedListing`.

Two normalization rules matter enough to call out explicitly:

- Price (spec section 41): "$120", "USD 120", "$120.00", or a bare number
  all become `price=120.0, currency="USD"`.
- Timestamps (spec section 11): `created_at_source` is only ever set when
  the raw payload contained something that parses as a real, plausible
  date. Anything absent, malformed, or implausible (in the future, or
  before Mercari US existed) becomes `None` — never guessed, never left as
  the scrape time in disguise.
"""

from __future__ import annotations

import re
from datetime import UTC, datetime, timedelta

from pydantic import BaseModel

from app.mercari.parser import RawListing
from app.utils.logger import get_logger
from app.utils.time import to_utc, utc_now

logger = get_logger(__name__)

_CURRENCY_CODE_RE = re.compile(r"\b([A-Z]{3})\b")
_AMOUNT_RE = re.compile(r"(\d+(?:\.\d{1,2})?)")

# Mercari US did not exist before this; used only to reject obviously
# corrupt/misparsed timestamps, never to invent a real one.
_EARLIEST_PLAUSIBLE_YEAR = 2013


class NormalizedListing(BaseModel):
    external_id: str
    title: str | None = None
    description: str | None = None
    price: float | None = None
    currency: str = "USD"
    brand: str | None = None
    category: str | None = None
    size: str | None = None
    condition: str | None = None
    item_status: str | None = None
    seller_username: str | None = None
    seller_id: str | None = None
    image_url: str | None = None
    listing_url: str
    created_at_source: datetime | None = None


def normalize_price(
    raw: str | int | float | None, currency_hint: str | None = None
) -> tuple[float | None, str]:
    currency = (currency_hint or "USD").upper().strip() or "USD"
    if raw is None:
        return None, currency
    if isinstance(raw, bool):
        return None, currency
    if isinstance(raw, (int, float)):
        return float(raw), currency

    text = str(raw).strip().replace(",", "")
    if not text:
        return None, currency

    currency_match = _CURRENCY_CODE_RE.search(text)
    if currency_match:
        currency = currency_match.group(1)

    amount_match = _AMOUNT_RE.search(text)
    if not amount_match:
        logger.debug("Could not extract a numeric amount from price text %r", raw)
        return None, currency
    return float(amount_match.group(1)), currency


def normalize_timestamp(raw: str | int | float | None) -> datetime | None:
    if raw is None:
        return None

    dt: datetime | None = None
    try:
        if isinstance(raw, bool):
            return None
        if isinstance(raw, (int, float)):
            value = float(raw)
            # Heuristic: 13-digit values are milliseconds, 10-digit are
            # seconds. Anything else is too ambiguous to trust.
            if value > 10**12:
                value /= 1000
            dt = datetime.fromtimestamp(value, tz=UTC)
        elif isinstance(raw, str):
            text = raw.strip()
            if not text:
                return None
            dt = to_utc(datetime.fromisoformat(text.replace("Z", "+00:00")))
    except (ValueError, OverflowError, OSError):
        logger.debug("Could not parse source timestamp %r", raw)
        return None

    if dt is None:
        return None

    if dt > utc_now() + timedelta(minutes=5) or dt.year < _EARLIEST_PLAUSIBLE_YEAR:
        logger.debug("Rejecting implausible source timestamp %r -> %s", raw, dt)
        return None
    return dt


def normalize_listing(raw: RawListing) -> NormalizedListing:
    price, currency = normalize_price(raw.price_raw, raw.currency_raw)
    created_at_source = normalize_timestamp(raw.created_at_raw)
    listing_url = raw.listing_url_raw or f"https://www.mercari.com/item/{raw.external_id}/"

    return NormalizedListing(
        external_id=raw.external_id,
        title=raw.title,
        description=raw.description,
        price=price,
        currency=currency,
        brand=raw.brand_raw,
        category=raw.category_raw,
        size=raw.size_raw,
        condition=raw.condition_raw,
        item_status=raw.item_status_raw,
        seller_username=raw.seller_username_raw,
        seller_id=raw.seller_id_raw,
        image_url=raw.image_url_raw,
        listing_url=listing_url,
        created_at_source=created_at_source,
    )
