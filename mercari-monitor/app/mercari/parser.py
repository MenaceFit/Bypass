"""Turns a raw Mercari payload into `RawListing` objects.

Two input shapes are supported, matching the two fetch strategies in
`client.py`:
- `parse_search_api_payload(data)` — the structured JSON from Mercari's
  internal search API (rich fields).
- `parse_listing_card_dom(card)` — a single pre-extracted rendered
  search-result card (id/title/price/image only), used as a fallback when
  the API response could not be intercepted.

Every extractor is defensive: an absent/null field never raises, it just
produces `None` on that field (spec section 18). The only thing that must
always be present is a usable unique id — every downstream guarantee
(deduplication, "never use the title as an identifier") depends on it — so
its absence raises `ParserError` and is logged explicitly rather than
silently skipped or, worse, falling back to the title.

If Mercari changes its page/API structure, this is the file that should
need to change — `client.py` and everything downstream should not (spec
section 59). Field name candidates are grouped in small tuples right below
this docstring specifically so that adapting to a real structural change is
a matter of editing a tuple, not rewriting the extraction logic.
"""

from __future__ import annotations

import re
from typing import Any, Literal

from pydantic import BaseModel

from app.utils.logger import get_logger

logger = get_logger(__name__)

# --- Best-effort field name candidates (see module docstring) --------------
_ID_KEYS = ("id", "itemId", "item_id", "productId")
_TITLE_KEYS = ("name", "title", "itemName")
_DESCRIPTION_KEYS = ("description", "itemDescription")
_PRICE_KEYS = ("price", "priceUsd", "sellingPrice", "priceValue")
_PRICE_FORMATTED_KEYS = ("priceFormatted", "price_text", "displayPrice", "formattedPrice")
_CURRENCY_KEYS = ("currency", "priceCurrency")
_CONDITION_KEYS = ("condition", "itemConditionName", "conditionName")
_ITEM_STATUS_KEYS = ("status", "itemStatus")
_URL_KEYS = ("url", "itemUrl", "canonicalUrl", "permalink")
_CREATED_KEYS = ("created", "createdAt", "created_at", "createdTime")
_BRAND_CONTAINER_KEYS = ("brand", "itemBrand")
_CATEGORY_CONTAINER_KEYS = ("category", "itemCategory")
_SIZE_CONTAINER_KEYS = ("size", "itemSize")
_SELLER_CONTAINER_KEYS = ("seller", "owner", "sellerInfo")
_IMAGE_LIST_KEYS = ("photos", "thumbnails", "images")
_IMAGE_SCALAR_KEYS = ("photoUrl", "thumbnail", "imageUrl", "image_url")

_ITEM_URL_ID_RE = re.compile(r"/item/(m[\w-]+)")


class ParserError(Exception):
    """Raised when a raw payload cannot yield a usable listing — i.e. no
    reliable unique id could be extracted. Never raised for merely-missing
    optional fields."""


class RawListing(BaseModel):
    """Loosely-typed, pre-normalization extraction result. Every field
    besides `external_id` may be `None` — `normalizer.py` is responsible
    for turning this into a clean, typed `NormalizedListing`."""

    external_id: str
    title: str | None = None
    description: str | None = None
    price_raw: str | int | float | None = None
    currency_raw: str | None = None
    brand_raw: str | None = None
    category_raw: str | None = None
    size_raw: str | None = None
    condition_raw: str | None = None
    item_status_raw: str | None = None
    seller_username_raw: str | None = None
    seller_id_raw: str | None = None
    image_url_raw: str | None = None
    listing_url_raw: str | None = None
    created_at_raw: str | int | float | None = None
    source: Literal["api", "dom"] = "api"


def parse_search_api_payload(payload: dict[str, Any]) -> list[RawListing]:
    items = _extract_items(payload)
    listings: list[RawListing] = []
    for item in items:
        if not isinstance(item, dict):
            continue
        try:
            listings.append(_parse_one_api_item(item))
        except ParserError as exc:
            logger.error("Skipping unparseable listing: %s", exc)
    return listings


def parse_listing_card_dom(card: dict[str, Any]) -> RawListing | None:
    """`card` is a plain dict produced by `client.py`'s DOM fallback
    extraction — kept as a dict (not a Playwright handle) so this stays a
    pure, browser-free function that unit tests can call directly."""
    href = card.get("href") or ""
    match = _ITEM_URL_ID_RE.search(href)
    if not match:
        logger.error("Skipping DOM card with no parseable item id in href=%r", href)
        return None

    listing_url = href if href.startswith("http") else f"https://www.mercari.com{href}"
    return RawListing(
        external_id=match.group(1),
        title=_clean_str(card.get("title")),
        price_raw=card.get("price_text"),
        image_url_raw=card.get("image_url"),
        listing_url_raw=listing_url,
        source="dom",
    )


def _extract_items(payload: dict[str, Any]) -> list[Any]:
    for key in ("data", "items", "results", "listings"):
        value = payload.get(key)
        if isinstance(value, list):
            return value
    logger.warning(
        "Unexpected search payload shape: no known results key found (top-level keys=%s)",
        list(payload.keys()),
    )
    return []


def _parse_one_api_item(item: dict[str, Any]) -> RawListing:
    external_id = _first_present(item, _ID_KEYS)
    if not external_id:
        raise ParserError(f"listing payload has no usable id (keys={list(item.keys())})")

    price_raw = _first_present(item, _PRICE_KEYS)
    if price_raw is None:
        price_raw = _first_present(item, _PRICE_FORMATTED_KEYS)

    return RawListing(
        external_id=str(external_id),
        title=_clean_str(_first_present(item, _TITLE_KEYS)),
        description=_clean_str(_first_present(item, _DESCRIPTION_KEYS)),
        price_raw=price_raw,
        currency_raw=_clean_str(_first_present(item, _CURRENCY_KEYS)),
        brand_raw=_clean_str(_first_nested_name(item, _BRAND_CONTAINER_KEYS)),
        category_raw=_clean_str(_first_nested_name(item, _CATEGORY_CONTAINER_KEYS)),
        size_raw=_clean_str(_first_nested_name(item, _SIZE_CONTAINER_KEYS)),
        condition_raw=_clean_str(_first_present(item, _CONDITION_KEYS)),
        item_status_raw=_clean_str(_first_present(item, _ITEM_STATUS_KEYS)),
        seller_username_raw=_clean_str(
            _first_nested(item, _SELLER_CONTAINER_KEYS, ("username", "name"))
        ),
        seller_id_raw=_clean_str(_first_nested(item, _SELLER_CONTAINER_KEYS, ("id",))),
        image_url_raw=_first_image_url(item),
        listing_url_raw=_clean_str(_first_present(item, _URL_KEYS)),
        created_at_raw=_first_present(item, _CREATED_KEYS),
        source="api",
    )


def _first_present(d: dict[str, Any], keys: tuple[str, ...]) -> Any | None:
    for key in keys:
        value = d.get(key)
        if value is not None and value != "":
            return value
    return None


def _first_nested(
    d: dict[str, Any], container_keys: tuple[str, ...], field_keys: tuple[str, ...]
) -> Any | None:
    for container_key in container_keys:
        container = d.get(container_key)
        if isinstance(container, dict):
            value = _first_present(container, field_keys)
            if value is not None:
                return value
        elif isinstance(container, str) and container:
            return container
    return None


def _first_nested_name(d: dict[str, Any], container_keys: tuple[str, ...]) -> Any | None:
    return _first_nested(d, container_keys, ("name", "label", "title"))


def _first_image_url(item: dict[str, Any]) -> str | None:
    for key in _IMAGE_LIST_KEYS:
        value = item.get(key)
        if isinstance(value, list) and value:
            first = value[0]
            if isinstance(first, str):
                return first
            if isinstance(first, dict):
                url = first.get("url") or first.get("uri") or first.get("src")
                if url:
                    return url
    for key in _IMAGE_SCALAR_KEYS:
        value = item.get(key)
        if isinstance(value, str) and value:
            return value
    return None


def _clean_str(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None
