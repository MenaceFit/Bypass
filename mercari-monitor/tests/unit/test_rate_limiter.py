"""Unit tests for app/mercari/rate_limiter.py — the global concurrency cap
and minimum-interval gate (spec section 13) that every keyword's scan must
share regardless of its own configured interval.
"""

from __future__ import annotations

import asyncio
import time

from app.mercari.rate_limiter import RateLimiter, RequestMetrics


async def test_semaphore_caps_concurrent_requests():
    limiter = RateLimiter(max_concurrent=2, min_interval_ms=0)
    concurrent = 0
    max_seen = 0
    lock = asyncio.Lock()

    async def worker():
        nonlocal concurrent, max_seen
        async with limiter():
            async with lock:
                concurrent += 1
                max_seen = max(max_seen, concurrent)
            await asyncio.sleep(0.05)
            async with lock:
                concurrent -= 1

    await asyncio.gather(*(worker() for _ in range(6)))
    assert max_seen == 2


async def test_min_interval_spaces_out_request_starts():
    limiter = RateLimiter(max_concurrent=10, min_interval_ms=40)
    starts: list[float] = []

    async def worker():
        async with limiter():
            starts.append(time.monotonic())

    await asyncio.gather(*(worker() for _ in range(4)))
    starts.sort()
    gaps = [b - a for a, b in zip(starts, starts[1:])]
    assert all(gap >= 0.035 for gap in gaps)  # small tolerance below 40ms for scheduler jitter


async def test_zero_min_interval_does_not_serialize_requests():
    limiter = RateLimiter(max_concurrent=10, min_interval_ms=0)
    started = time.monotonic()

    async def worker():
        async with limiter():
            pass

    await asyncio.gather(*(worker() for _ in range(20)))
    assert time.monotonic() - started < 0.5


def test_request_metrics_tracks_counts_and_average():
    metrics = RequestMetrics()
    metrics.record(success=True, duration_ms=100)
    metrics.record(success=True, duration_ms=200)
    metrics.record(success=False, duration_ms=50, was_429=True)

    snapshot = metrics.snapshot()
    assert snapshot["total_requests"] == 3
    assert snapshot["successful_requests"] == 2
    assert snapshot["failed_requests"] == 1
    assert snapshot["http_429_count"] == 1
    assert snapshot["average_response_time_ms"] == round((100 + 200 + 50) / 3)


def test_request_metrics_empty_has_no_average():
    assert RequestMetrics().average_response_time_ms is None
