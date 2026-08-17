"""Search orchestration: builds a Mercari query, drives the browser client,
and turns the result into `NormalizedListing`s.

`MarketplaceSource` is the abstraction the rest of the application depends
on (spec section 6) — services and the monitor talk to this Protocol, never
to Mercari specifics directly. Swapping in another marketplace later means
writing one more class shaped like `MercariUSSource`, nothing else changes.

Price/keyword-include-exclude filtering is deliberately NOT done here: the
spec (section 38) calls for the source to return everything it legitimately
found and the *service* layer to filter, so ignored listings can be counted
separately instead of silently vanishing.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol
from urllib.parse import urlencode

from app.mercari.client import MercariClient, MercariFetchResult, MercariFetchStatus, SourceHealth
from app.mercari.normalizer import NormalizedListing, normalize_listing
from app.mercari.parser import (
    ParserError,
    RawListing,
    parse_listing_card_dom,
    parse_search_api_payload,
)
from app.utils.logger import get_logger

logger = get_logger(__name__)

SEARCH_BASE_URL = "https://www.mercari.com/search/"

# Best-effort mapping to Mercari's actual sort parameter values. `keyword`
# itself is the one parameter we're confident about; the rest mirror what
# the search UI exposes but may need adjustment against the live site (see
# README -> Limitations) since exact ids/names were not independently
# verifiable from the development sandbox.
_SORT_MAP = {
    "newest": "created_time",
    "price_low": "price",
    "price_high": "price_desc",
}


@dataclass
class SearchQuery:
    keyword: str
    min_price: float | None = None
    max_price: float | None = None
    category: str | None = None
    brand: str | None = None
    size: str | None = None
    condition: str | None = None
    location: str | None = None
    sort: str = "newest"

    def to_url(self) -> str:
        params: dict[str, str] = {"keyword": self.keyword}
        if self.min_price is not None:
            params["price_min"] = str(int(self.min_price))
        if self.max_price is not None:
            params["price_max"] = str(int(self.max_price))
        if self.category:
            params["category_id"] = self.category
        if self.brand:
            params["brand_id"] = self.brand
        if self.size:
            params["size_id"] = self.size
        if self.condition:
            params["item_condition_id"] = self.condition
        sort_param = _SORT_MAP.get(self.sort)
        if sort_param:
            params["sort"] = sort_param
        return f"{SEARCH_BASE_URL}?{urlencode(params)}"


class MarketplaceSource(Protocol):
    async def search(self, query: SearchQuery) -> list[NormalizedListing]: ...

    async def health_check(self) -> SourceHealth: ...


class MercariSourceError(Exception):
    """Raised when a scan could not complete. Carries enough detail for the
    monitor/scheduler to decide whether to back off, mark THROTTLED, or
    just log and retry next cycle."""

    def __init__(self, status: MercariFetchStatus, reason: str | None, retry_after_seconds: float | None) -> None:
        super().__init__(reason or status.value)
        self.status = status
        self.reason = reason
        self.retry_after_seconds = retry_after_seconds


class MercariUSSource:
    """`MarketplaceSource` implementation for mercari.com. See
    `client.py` for why this is browser-based rather than plain HTTP."""

    def __init__(self, client: MercariClient) -> None:
        self._client = client

    async def search(self, query: SearchQuery) -> list[NormalizedListing]:
        url = query.to_url()
        result = await self._client.fetch_search(url)

        if result.status is not MercariFetchStatus.OK:
            raise MercariSourceError(result.status, result.reason, result.retry_after_seconds)

        raw_listings = self._parse(result)
        return _normalize_all(raw_listings)

    def _parse(self, result: MercariFetchResult) -> list[RawListing]:
        if result.api_payload is not None:
            try:
                return parse_search_api_payload(result.api_payload)
            except ParserError as exc:
                logger.error("Parser error on API payload: %s", exc)
                return []
        if result.dom_cards is not None:
            parsed = (parse_listing_card_dom(card) for card in result.dom_cards)
            return [listing for listing in parsed if listing is not None]
        return []

    async def health_check(self) -> SourceHealth:
        return await self._client.health_check()


def _normalize_all(raw_listings: list[RawListing]) -> list[NormalizedListing]:
    normalized: list[NormalizedListing] = []
    for raw in raw_listings:
        try:
            normalized.append(normalize_listing(raw))
        except Exception as exc:  # one bad row must never lose the rest of the batch
            logger.error("Failed to normalize listing %s: %s", raw.external_id, exc)
    return normalized
