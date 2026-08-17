"""Discord webhook delivery: embed construction + the actual HTTP call.

This module has no idea a queue, a database, or retries-with-backoff exist
— `services/notification_service.py` owns that. This file only knows how
to turn a listing into a Discord embed and POST it, and to classify the
result as success or `DiscordDeliveryError`.
"""

from __future__ import annotations

import httpx

from app.config.defaults import DISCORD_EMBED_COLOR_NEW_LISTING
from app.services.listing_service import ListingEventPayload
from app.utils.logger import get_logger
from app.utils.time import isoformat

logger = get_logger(__name__)

_TIMEOUT = httpx.Timeout(10.0)


class DiscordDeliveryError(Exception):
    """Any failure to deliver a Discord message — timeout, HTTP error,
    invalid webhook. The caller decides whether/how to retry."""


def _build_new_listing_embed(payload: ListingEventPayload) -> dict:
    fields = []
    if payload.brand:
        fields.append({"name": "Brand", "value": payload.brand, "inline": True})
    if payload.size:
        fields.append({"name": "Size", "value": payload.size, "inline": True})
    if payload.condition:
        fields.append({"name": "Condition", "value": payload.condition, "inline": True})
    fields.append({"name": "Search", "value": payload.keyword, "inline": True})
    if payload.detection_latency_ms is not None:
        fields.append(
            {
                "name": "Detection",
                "value": f"{payload.detection_latency_ms / 1000:.2f}s",
                "inline": True,
            }
        )
    if payload.seller_username:
        fields.append({"name": "Seller", "value": payload.seller_username, "inline": True})

    price_text = f"${payload.price:,.2f}" if payload.price is not None else "Unknown"

    embed: dict = {
        "title": payload.title or "New Mercari listing",
        "url": payload.listing_url,
        "color": DISCORD_EMBED_COLOR_NEW_LISTING,
        "description": f"💰 **{price_text} {payload.currency}**",
        "fields": fields,
        "timestamp": isoformat(payload.detected_at),
        "footer": {"text": "Mercari US Monitor"},
    }
    if payload.image_url:
        embed["thumbnail"] = {"url": payload.image_url}
    return embed


async def send_new_listing_embed(payload: ListingEventPayload, *, webhook_url: str) -> None:
    embed = _build_new_listing_embed(payload)
    body = {"content": "🚨 **NEW MERCARI US LISTING**", "embeds": [embed]}
    await _post(webhook_url, body)


async def send_test_embed(*, webhook_url: str) -> None:
    body = {
        "content": "✅ Mercari US Monitor — test notification",
        "embeds": [
            {
                "title": "Webhook connected",
                "description": "If you can see this, Discord notifications are working.",
                "color": DISCORD_EMBED_COLOR_NEW_LISTING,
            }
        ],
    }
    await _post(webhook_url, body)


async def _post(webhook_url: str, body: dict) -> None:
    try:
        async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
            response = await client.post(webhook_url, json=body)
    except httpx.TimeoutException as exc:
        raise DiscordDeliveryError("Discord request timed out") from exc
    except httpx.HTTPError as exc:
        raise DiscordDeliveryError(f"Discord request failed: {exc}") from exc

    if response.status_code == 429:
        retry_after = response.headers.get("retry-after")
        raise DiscordDeliveryError(f"Discord rate limited us (retry-after={retry_after})")
    if response.status_code >= 500:
        raise DiscordDeliveryError(f"Discord server error: HTTP {response.status_code}")
    if response.status_code >= 400:
        raise DiscordDeliveryError(
            f"Discord rejected the request: HTTP {response.status_code} {response.text[:200]}"
        )
