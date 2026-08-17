"""Global rate limiting shared across every keyword (spec section 13).

Two independent controls:
- `asyncio.Semaphore(MAX_CONCURRENT_REQUESTS)` caps how many Mercari fetches
  can be in flight at once, no matter how many keywords are active.
- A minimum interval between the *start* of consecutive fetches prevents a
  burst even when concurrency would technically allow one (e.g. twenty
  keywords all becoming due in the same second).

Every keyword scan goes through this single choke point — none bypass it
based on its own configured `scan_interval`. This is what keeps "5 keywords
at 5s each" from turning into a de facto 1 request/second hammering pattern.
"""

from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass, field

from app.config.settings import settings


@dataclass
class RequestMetrics:
    """In-memory (reset on restart) counters for the Observability panel
    (spec section 60). Durable per-run history lives in `scan_runs`; this
    is the fast "since the process started" view."""

    total_requests: int = 0
    successful_requests: int = 0
    failed_requests: int = 0
    http_429_count: int = 0
    _response_times_ms: list[int] = field(default_factory=list)

    def record(self, *, success: bool, duration_ms: int, was_429: bool = False) -> None:
        self.total_requests += 1
        if success:
            self.successful_requests += 1
        else:
            self.failed_requests += 1
        if was_429:
            self.http_429_count += 1
        self._response_times_ms.append(duration_ms)
        if len(self._response_times_ms) > 500:
            self._response_times_ms.pop(0)

    @property
    def average_response_time_ms(self) -> int | None:
        if not self._response_times_ms:
            return None
        return round(sum(self._response_times_ms) / len(self._response_times_ms))

    def snapshot(self) -> dict:
        return {
            "total_requests": self.total_requests,
            "successful_requests": self.successful_requests,
            "failed_requests": self.failed_requests,
            "http_429_count": self.http_429_count,
            "average_response_time_ms": self.average_response_time_ms,
        }


metrics = RequestMetrics()


class RateLimiter:
    def __init__(self, *, max_concurrent: int | None = None, min_interval_ms: int | None = None) -> None:
        self._max_concurrent = max_concurrent or settings.max_concurrent_requests
        self._min_interval_s = (
            min_interval_ms if min_interval_ms is not None else settings.min_request_interval_ms
        ) / 1000
        self._semaphore = asyncio.Semaphore(self._max_concurrent)
        self._lock = asyncio.Lock()
        self._last_start = 0.0

    async def acquire(self) -> None:
        await self._semaphore.acquire()
        async with self._lock:
            now = time.monotonic()
            wait = self._last_start + self._min_interval_s - now
            if wait > 0:
                await asyncio.sleep(wait)
            self._last_start = time.monotonic()

    def release(self) -> None:
        self._semaphore.release()

    def __call__(self) -> "_RateLimiterContext":
        return _RateLimiterContext(self)


class _RateLimiterContext:
    def __init__(self, limiter: RateLimiter) -> None:
        self._limiter = limiter

    async def __aenter__(self) -> None:
        await self._limiter.acquire()

    async def __aexit__(self, exc_type, exc, tb) -> None:
        self._limiter.release()


rate_limiter = RateLimiter()
