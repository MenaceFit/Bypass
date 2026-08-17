"""Integration test for `MercariClient` against a fully mocked page — no
real network access, per spec section 56/59 ("fixtures instead of
depending on the real site", "tests to catch structural drift").

This validates the actual Playwright orchestration (navigation, response
interception, HTTP status classification, DOM fallback) mechanically with
a real Chromium instance. It does NOT and cannot validate against
mercari.com's real structure — this development sandbox's egress policy
blocks that domain outright (see README -> Limitations). The mocked
payload shape mirrors `tests/fixtures/mercari_search_response.json`.

Skips automatically if no Chromium binary is available, since launching a
real browser is inherently environment-dependent.
"""

from __future__ import annotations

import json

import pytest
from playwright.async_api import Route, async_playwright

from app.config.settings import settings
from app.mercari import client as client_module
from app.mercari.client import MercariClient, MercariFetchStatus

_FAKE_API_PAYLOAD = {
    "data": [
        {"id": "m00000000001", "name": "Mocked Nike ACG Jacket", "price": 77, "brand": {"name": "Nike"}}
    ]
}

# The real Mercari SPA fires its own client-side fetch to the search API
# (see client.py's module docstring / README -> Architecture); this mock
# shell does the same on a minimal scale so the test exercises the real
# "navigate, then wait for the page's own XHR" flow rather than faking it.
_FAKE_SHELL_HTML = """
<html><head><title>Mercari</title></head>
<body>
<div id="root"></div>
<script>fetch('/v1/api/search?keyword=test').catch(() => {});</script>
</body></html>
"""

_DOM_ONLY_HTML = (
    "<html><body>"
    "<a href='/item/m22222222222/'><img alt='DOM Fallback Item' src='https://x/y.jpg'>"
    '<span class="price">$33</span></a>'
    "</body></html>"
)


async def _browser_available() -> bool:
    try:
        async with async_playwright() as p:
            kwargs = {"executable_path": settings.playwright_executable_path} if settings.playwright_executable_path else {}
            browser = await p.chromium.launch(headless=True, **kwargs)
            await browser.close()
        return True
    except Exception:
        return False


@pytest.fixture
async def mercari_client():
    if not await _browser_available():
        pytest.skip("No Chromium binary available in this environment")
    instance = MercariClient()
    await instance.start()
    yield instance
    await instance.stop()


@pytest.fixture(autouse=True)
def _fast_poll(monkeypatch):
    # client.py polls in _POLL_INTERVAL_MS steps up to _MAX_POLL_MS waiting
    # for an intercepted API response. Our mocks resolve near-instantly
    # except the DOM-fallback case, which has nothing to wait for by
    # design — shrink the ceiling so that test doesn't take 10 real seconds.
    monkeypatch.setattr(client_module, "_MAX_POLL_MS", 800)


async def _mock_search_api(context, *, status: int = 200, body: dict | None = None, headers: dict | None = None) -> None:
    async def handle(route: Route) -> None:
        if "/v1/api/search" in route.request.url:
            await route.fulfill(
                status=status,
                content_type="application/json",
                headers=headers or {},
                body=json.dumps(body if body is not None else _FAKE_API_PAYLOAD),
            )
        else:
            await route.fulfill(status=200, content_type="text/html", body=_FAKE_SHELL_HTML)

    await context.route("**/*", handle)


async def _mock_dom_only(context) -> None:
    async def handle(route: Route) -> None:
        await route.fulfill(status=200, content_type="text/html", body=_DOM_ONLY_HTML)

    await context.route("**/*", handle)


async def test_fetch_search_intercepts_api_response(mercari_client: MercariClient):
    await _mock_search_api(mercari_client._context)

    result = await mercari_client.fetch_search("https://www.mercari.com/search/?keyword=nike")

    assert result.status is MercariFetchStatus.OK
    assert result.api_payload is not None
    assert result.api_payload["data"][0]["id"] == "m00000000001"
    assert result.response_time_ms is not None


async def test_fetch_search_classifies_429_with_retry_after(mercari_client: MercariClient):
    await _mock_search_api(
        mercari_client._context,
        status=429,
        body={"error": "rate limited"},
        headers={"retry-after": "7"},
    )

    result = await mercari_client.fetch_search("https://www.mercari.com/search/?keyword=nike")

    assert result.status is MercariFetchStatus.RATE_LIMITED
    assert result.retry_after_seconds == 7.0


async def test_fetch_search_falls_back_to_dom_when_no_api_response(mercari_client: MercariClient):
    await _mock_dom_only(mercari_client._context)

    result = await mercari_client.fetch_search("https://www.mercari.com/search/?keyword=nike")

    assert result.status is MercariFetchStatus.OK
    assert result.dom_cards is not None
    assert result.dom_cards[0]["href"] == "/item/m22222222222/"
    assert result.dom_cards[0]["title"] == "DOM Fallback Item"


async def test_health_check_reflects_last_fetch(mercari_client: MercariClient):
    await _mock_search_api(mercari_client._context)
    await mercari_client.fetch_search("https://www.mercari.com/search/?keyword=nike")

    health = await mercari_client.health_check()
    assert health.available is True
    assert health.status == "ONLINE"
