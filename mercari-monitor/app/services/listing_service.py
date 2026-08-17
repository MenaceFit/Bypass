"""Listing-level business logic: applying a keyword's filters to freshly
normalized results, and persisting the ones that pass.

Deduplication itself is enforced in the database layer (UNIQUE constraint +
`ON CONFLICT DO NOTHING`, see `database/repositories.py`) — this service
decides what should even be attempted for persistence (price range,
include/exclude keyword filters) and reports what it filtered out
separately, so nothing silently disappears (spec section 38).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime

from pydantic import BaseModel

from app.database.models import Keyword, Listing
from app.database.repositories import ListingRepository
from app.mercari.normalizer import NormalizedListing
from app.utils.time import latency_ms, utc_now
from app.utils.validation import split_terms


class ListingEventPayload(BaseModel):
    """Shape published on the event bus for a discovered/stored listing,
    and reused verbatim for the WebSocket `new_listing` event and the
    Discord embed — one definition, three consumers."""

    id: int
    external_id: str
    title: str | None
    description: str | None = None
    price: float | None
    currency: str
    brand: str | None
    category: str | None = None
    size: str | None
    condition: str | None
    item_status: str | None = None
    seller_username: str | None
    seller_id: str | None = None
    image_url: str | None
    listing_url: str
    keyword: str
    keyword_id: int
    matched_keywords: list[str] = []
    created_at_source: datetime | None
    detected_at: datetime
    detection_latency_ms: int | None


def build_listing_event_payload(
    listing: Listing, keyword: Keyword, matched_keywords: list[str]
) -> ListingEventPayload:
    return ListingEventPayload(
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
        keyword=keyword.keyword,
        keyword_id=keyword.id,
        matched_keywords=matched_keywords,
        created_at_source=listing.created_at_source,
        detected_at=listing.detected_at,
        detection_latency_ms=listing.detection_latency_ms,
    )


@dataclass
class DetectionResult:
    new_listings: list[tuple[Listing, NormalizedListing]] = field(default_factory=list)
    duplicate_count: int = 0
    ignored_price_count: int = 0
    ignored_keyword_filter_count: int = 0
    total_seen: int = 0


def passes_price_filter(listing: NormalizedListing, keyword: Keyword) -> bool:
    if listing.price is None:
        # Can't evaluate a price filter against an unknown price — don't
        # silently discard the listing just because parsing couldn't
        # determine one.
        return True
    if keyword.min_price is not None and listing.price < keyword.min_price:
        return False
    if keyword.max_price is not None and listing.price > keyword.max_price:
        return False
    return True


def passes_keyword_filters(listing: NormalizedListing, keyword: Keyword) -> bool:
    haystack = f"{listing.title or ''} {listing.description or ''}".lower()

    include_terms = [t.lower() for t in split_terms(keyword.include_keywords)]
    if include_terms and not any(term in haystack for term in include_terms):
        return False

    exclude_terms = [t.lower() for t in split_terms(keyword.exclude_keywords)]
    if exclude_terms and any(term in haystack for term in exclude_terms):
        return False

    return True


class ListingService:
    def __init__(self, listing_repo: ListingRepository) -> None:
        self._listing_repo = listing_repo

    async def process_search_results(
        self, keyword: Keyword, normalized_listings: list[NormalizedListing]
    ) -> DetectionResult:
        result = DetectionResult(total_seen=len(normalized_listings))
        detected_at = utc_now()

        for normalized in normalized_listings:
            if not passes_price_filter(normalized, keyword):
                result.ignored_price_count += 1
                continue
            if not passes_keyword_filters(normalized, keyword):
                result.ignored_keyword_filter_count += 1
                continue

            listing, is_new = await self._listing_repo.upsert_listing_and_link(
                keyword_id=keyword.id,
                detected_at=detected_at,
                values=_listing_values(normalized, detected_at),
            )
            if is_new:
                result.new_listings.append((listing, normalized))
            else:
                result.duplicate_count += 1

        return result


def _listing_values(normalized: NormalizedListing, detected_at: datetime) -> dict:
    latency = (
        latency_ms(normalized.created_at_source, detected_at)
        if normalized.created_at_source is not None
        else None
    )
    return {
        "external_id": normalized.external_id,
        "title": normalized.title,
        "description": normalized.description,
        "price": normalized.price,
        "currency": normalized.currency,
        "brand": normalized.brand,
        "category": normalized.category,
        "size": normalized.size,
        "condition": normalized.condition,
        "item_status": normalized.item_status,
        "seller_username": normalized.seller_username,
        "seller_id": normalized.seller_id,
        "image_url": normalized.image_url,
        "listing_url": normalized.listing_url,
        "created_at_source": normalized.created_at_source,
        "detection_latency_ms": latency,
    }
