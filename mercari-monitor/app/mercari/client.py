"""Real-browser transport for Mercari US.

Mercari's search results are not available through a plain HTTP request.
Research into the public site (see README -> Architecture; this could not
be verified live from the development sandbox, whose egress policy blocks
mercari.com — see Limitations) indicates the internal search endpoint
requires session-bound authentication: a signed token minted by the page's
own client-side JavaScript, plus a Cloudflare bot-management cookie. A
cookieless/scriptless request is rejected outright.

The only access path that does not involve reverse-engineering or spoofing
that mechanism is a real, unmodified browser that loads the actual page and
lets its own script run normally — exactly like a human visitor's browser.
This module owns exactly that: a single persistent Playwright/Chromium
browser context, reused across scans so legitimately-issued cookies persist
the way they would in a normal browsing session.

Hard boundaries, on purpose:
- No fake/spoofed User-Agent or fingerprint patching.
- No `navigator.webdriver` masking or stealth plugins.
- No CAPTCHA solving.
- No proxy/IP rotation to dodge rate limiting.
If Mercari's bot protection blocks this traffic anyway, `fetch_search`
reports `BLOCKED`/`RATE_LIMITED`/etc. so the caller can degrade gracefully
(spec section 15/27) — it never escalates countermeasures in response.
"""

from __future__ import annotations

import json
import re
import time
from dataclasses import dataclass
from enum import StrEnum
from typing import Any

from playwright.async_api import (
    Browser,
    BrowserContext,
    Page,
    Playwright,
    Response,
    TimeoutError as PlaywrightTimeoutError,
    async_playwright,
)

from app.config.settings import settings
from app.mercari.rate_limiter import metrics, rate_limiter
from app.utils.logger import get_logger

logger = get_logger(__name__)

# Best-effort: the path segment Mercari's SPA calls for search results. If
# Mercari changes this, update the pattern here — parser.py and everything
# above it stay untouched.
SEARCH_API_PATTERN = re.compile(r"/v1/api/search")

# Markers indicating a bot-management challenge page rather than the real
# app shell. Kept short and specific to avoid false positives on ordinary
# error pages.
_CHALLENGE_MARKERS = (
    "just a moment",
    "attention required",
    "access denied",
    "cf-chl",
    'id="challenge-',
)

_POLL_INTERVAL_MS = 250
_MAX_POLL_MS = 10_000


class MercariFetchStatus(StrEnum):
    OK = "OK"
    BLOCKED = "BLOCKED"
    UNAUTHORIZED = "UNAUTHORIZED"
    RATE_LIMITED = "RATE_LIMITED"
    SERVER_ERROR = "SERVER_ERROR"
    NETWORK_ERROR = "NETWORK_ERROR"
    UNEXPECTED = "UNEXPECTED"


@dataclass
class MercariFetchResult:
    status: MercariFetchStatus
    api_payload: dict[str, Any] | None = None
    dom_cards: list[dict[str, Any]] | None = None
    http_status: int | None = None
    reason: str | None = None
    retry_after_seconds: float | None = None
    response_time_ms: int | None = None


@dataclass
class SourceHealth:
    available: bool
    status: str  # ONLINE | THROTTLED | DEGRADED
    reason: str | None = None
    retry_after_seconds: float | None = None


class MercariClient:
    def __init__(self) -> None:
        self._playwright: Playwright | None = None
        self._browser: Browser | None = None
        self._context: BrowserContext | None = None
        self._last_health = SourceHealth(available=True, status="ONLINE")

    async def start(self) -> None:
        if self._browser is not None:
            return
        self._playwright = await async_playwright().start()
        launch_kwargs: dict[str, Any] = {"headless": settings.browser_headless}
        if settings.playwright_executable_path:
            launch_kwargs["executable_path"] = settings.playwright_executable_path
        self._browser = await self._playwright.chromium.launch(**launch_kwargs)
        # One persistent context: legitimately-issued cookies (e.g.
        # Cloudflare's cf-bm) carry over between scans instead of forcing a
        # fresh "first visit" negotiation every single request.
        self._context = await self._browser.new_context(viewport={"width": 1440, "height": 900}, locale="en-US")
        self._context.set_default_navigation_timeout(settings.navigation_timeout_ms)
        logger.info("Mercari browser client started (headless=%s)", settings.browser_headless)

    async def stop(self) -> None:
        if self._context is not None:
            await self._context.close()
            self._context = None
        if self._browser is not None:
            await self._browser.close()
            self._browser = None
        if self._playwright is not None:
            await self._playwright.stop()
            self._playwright = None
        logger.info("Mercari browser client stopped")

    @property
    def is_running(self) -> bool:
        return self._context is not None

    async def fetch_search(self, url: str) -> MercariFetchResult:
        if self._context is None:
            raise RuntimeError("MercariClient.start() must be called before fetch_search()")

        started = time.monotonic()
        async with rate_limiter():
            page = await self._context.new_page()
            try:
                result = await self._fetch_with_page(page, url)
            except PlaywrightTimeoutError:
                result = MercariFetchResult(
                    status=MercariFetchStatus.NETWORK_ERROR, reason="Navigation or response timed out"
                )
            except Exception as exc:  # network loss, DNS failure, connection reset, ...
                logger.error("Unexpected error fetching %s: %s", url, exc)
                result = MercariFetchResult(status=MercariFetchStatus.UNEXPECTED, reason=str(exc))
            finally:
                await page.close()

        duration_ms = round((time.monotonic() - started) * 1000)
        result.response_time_ms = duration_ms
        metrics.record(
            success=result.status is MercariFetchStatus.OK,
            duration_ms=duration_ms,
            was_429=result.status is MercariFetchStatus.RATE_LIMITED,
        )
        self._update_health(result)
        return result

    async def _fetch_with_page(self, page: Page, url: str) -> MercariFetchResult:
        captured: dict[str, Response] = {}

        async def _on_response(response: Response) -> None:
            if "response" not in captured and SEARCH_API_PATTERN.search(response.url):
                captured["response"] = response

        page.on("response", _on_response)

        response = await page.goto(url, wait_until="domcontentloaded")
        if response is None:
            return MercariFetchResult(status=MercariFetchStatus.NETWORK_ERROR, reason="No response from navigation")

        early = self._classify_http_status(response.status, await _retry_after(response))
        if early is not None:
            return early

        elapsed_ms = 0
        while "response" not in captured and elapsed_ms < _MAX_POLL_MS:
            await page.wait_for_timeout(_POLL_INTERVAL_MS)
            elapsed_ms += _POLL_INTERVAL_MS

        if _looks_like_challenge(await page.content()):
            return MercariFetchResult(
                status=MercariFetchStatus.BLOCKED,
                http_status=response.status,
                reason="Bot-management challenge page detected",
            )

        if "response" in captured:
            api_result = await self._read_api_response(captured["response"])
            if api_result is not None:
                return api_result

        dom_cards = await _extract_dom_cards(page)
        if dom_cards:
            return MercariFetchResult(status=MercariFetchStatus.OK, dom_cards=dom_cards, http_status=response.status)

        return MercariFetchResult(
            status=MercariFetchStatus.UNEXPECTED,
            http_status=response.status,
            reason="No search API response intercepted and no result cards found in the DOM "
            "(the page structure may have changed — see README -> Troubleshooting)",
        )

    async def _read_api_response(self, api_response: Response) -> MercariFetchResult | None:
        classified = self._classify_http_status(api_response.status, await _retry_after(api_response))
        if classified is not None:
            return classified
        try:
            payload = await api_response.json()
        except json.JSONDecodeError:
            logger.warning("Mercari search API response was not valid JSON")
            return MercariFetchResult(
                status=MercariFetchStatus.UNEXPECTED,
                http_status=api_response.status,
                reason="Search API response was not valid JSON",
            )
        except Exception as exc:
            logger.warning("Could not read intercepted API response: %s", exc)
            return None
        return MercariFetchResult(status=MercariFetchStatus.OK, api_payload=payload, http_status=api_response.status)

    @staticmethod
    def _classify_http_status(status_code: int, retry_after: float | None) -> MercariFetchResult | None:
        if status_code == 401:
            return MercariFetchResult(
                status=MercariFetchStatus.UNAUTHORIZED,
                http_status=status_code,
                reason="Mercari rejected the session (unauthorized) — see README -> Architecture",
            )
        if status_code == 429:
            return MercariFetchResult(
                status=MercariFetchStatus.RATE_LIMITED,
                http_status=status_code,
                reason="HTTP 429 from Mercari",
                retry_after_seconds=retry_after,
            )
        if status_code == 403:
            return MercariFetchResult(
                status=MercariFetchStatus.BLOCKED,
                http_status=status_code,
                reason="HTTP 403 — likely a bot-management challenge",
            )
        if status_code in (400, 404, 405, 408):
            return MercariFetchResult(
                status=MercariFetchStatus.UNEXPECTED,
                http_status=status_code,
                reason=f"Mercari returned HTTP {status_code}",
            )
        if status_code >= 500:
            return MercariFetchResult(
                status=MercariFetchStatus.SERVER_ERROR,
                http_status=status_code,
                reason=f"Mercari returned HTTP {status_code}",
            )
        return None

    def _update_health(self, result: MercariFetchResult) -> None:
        status_map = {
            MercariFetchStatus.OK: "ONLINE",
            MercariFetchStatus.RATE_LIMITED: "THROTTLED",
        }
        self._last_health = SourceHealth(
            available=result.status is MercariFetchStatus.OK,
            status=status_map.get(result.status, "DEGRADED"),
            reason=result.reason,
            retry_after_seconds=result.retry_after_seconds,
        )

    async def health_check(self) -> SourceHealth:
        return self._last_health


async def _retry_after(response: Response) -> float | None:
    try:
        value = await response.header_value("retry-after")
    except Exception:
        return None
    if not value:
        return None
    try:
        return float(value)
    except ValueError:
        return None


def _looks_like_challenge(html: str) -> bool:
    lowered = html[:5000].lower()
    return any(marker in lowered for marker in _CHALLENGE_MARKERS)


async def _extract_dom_cards(page: Page) -> list[dict[str, Any]]:
    """Fallback extraction when no search-API response was intercepted.
    Reads only what's already rendered — no additional requests, no
    interaction with the page beyond a read-only DOM query."""
    try:
        return await page.eval_on_selector_all(
            "a[href*='/item/']",
            """
            (elements) => elements.slice(0, 120).map(el => {
                const img = el.querySelector('img');
                const priceEl = el.querySelector('[data-testid*="price" i], [class*="price" i]');
                return {
                    href: el.getAttribute('href'),
                    title: img ? img.getAttribute('alt') : (el.textContent || '').trim().slice(0, 200),
                    image_url: img ? img.getAttribute('src') : null,
                    price_text: priceEl ? priceEl.textContent.trim() : null,
                };
            })
            """,
        )
    except Exception as exc:
        logger.warning("DOM fallback extraction failed: %s", exc)
        return []
