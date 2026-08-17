"""Unit tests for app/notifications/discord.py using respx to mock the
webhook HTTP call — spec section 57 explicitly requires never sending a
real Discord message during tests. Covers: success, timeout, HTTP error,
rate limiting.
"""

from __future__ import annotations

import httpx
import pytest
import respx

from app.notifications.discord import DiscordDeliveryError, send_new_listing_embed, send_test_embed
from app.services.listing_service import ListingEventPayload
from app.utils.time import utc_now

WEBHOOK_URL = "https://discord.com/api/webhooks/123456789/token"


def _payload(**overrides) -> ListingEventPayload:
    base = dict(
        id=1,
        external_id="m123",
        title="Nike ACG Jacket",
        price=120.0,
        currency="USD",
        brand="Nike",
        size="M",
        condition="Good",
        seller_username="seller1",
        image_url="https://static.mercdn.net/photo.jpg",
        listing_url="https://www.mercari.com/item/m123/",
        keyword="Nike ACG",
        keyword_id=1,
        matched_keywords=["Nike ACG"],
        created_at_source=None,
        detected_at=utc_now(),
        detection_latency_ms=None,
    )
    base.update(overrides)
    return ListingEventPayload(**base)


@respx.mock
async def test_send_new_listing_embed_success():
    route = respx.post(WEBHOOK_URL).mock(return_value=httpx.Response(204))
    await send_new_listing_embed(_payload(), webhook_url=WEBHOOK_URL)
    assert route.called
    body = route.calls.last.request.content
    assert b"Nike ACG Jacket" in body
    assert b"NEW MERCARI US LISTING" in body


@respx.mock
async def test_send_new_listing_embed_includes_image_and_url():
    route = respx.post(WEBHOOK_URL).mock(return_value=httpx.Response(204))
    await send_new_listing_embed(_payload(), webhook_url=WEBHOOK_URL)
    import json

    body = json.loads(route.calls.last.request.content)
    embed = body["embeds"][0]
    assert embed["url"] == "https://www.mercari.com/item/m123/"
    assert embed["thumbnail"]["url"] == "https://static.mercdn.net/photo.jpg"


@respx.mock
async def test_send_new_listing_embed_omits_thumbnail_when_no_image():
    route = respx.post(WEBHOOK_URL).mock(return_value=httpx.Response(204))
    await send_new_listing_embed(_payload(image_url=None), webhook_url=WEBHOOK_URL)
    import json

    body = json.loads(route.calls.last.request.content)
    assert "thumbnail" not in body["embeds"][0]


@respx.mock
async def test_send_raises_on_timeout():
    respx.post(WEBHOOK_URL).mock(side_effect=httpx.TimeoutException("timed out"))
    with pytest.raises(DiscordDeliveryError, match="timed out"):
        await send_new_listing_embed(_payload(), webhook_url=WEBHOOK_URL)


@respx.mock
async def test_send_raises_on_invalid_webhook_404():
    respx.post(WEBHOOK_URL).mock(return_value=httpx.Response(404, text="Unknown Webhook"))
    with pytest.raises(DiscordDeliveryError, match="404"):
        await send_new_listing_embed(_payload(), webhook_url=WEBHOOK_URL)


@respx.mock
async def test_send_raises_on_server_error():
    respx.post(WEBHOOK_URL).mock(return_value=httpx.Response(500))
    with pytest.raises(DiscordDeliveryError, match="server error"):
        await send_new_listing_embed(_payload(), webhook_url=WEBHOOK_URL)


@respx.mock
async def test_send_raises_on_discord_rate_limit():
    respx.post(WEBHOOK_URL).mock(
        return_value=httpx.Response(429, headers={"retry-after": "3"}, json={"message": "rate limited"})
    )
    with pytest.raises(DiscordDeliveryError, match="rate limited"):
        await send_new_listing_embed(_payload(), webhook_url=WEBHOOK_URL)


@respx.mock
async def test_send_test_embed_success():
    route = respx.post(WEBHOOK_URL).mock(return_value=httpx.Response(204))
    await send_test_embed(webhook_url=WEBHOOK_URL)
    assert route.called
    assert b"Webhook connected" in route.calls.last.request.content
