"""Unit tests for app/utils/retry.py — exponential backoff + jitter, and
the retry_async wrapper's retry/no-retry boundary (spec section 14/55:
timeout, 429, 500, 503 retried; definitive errors are not)."""

from __future__ import annotations

import pytest

from app.utils.retry import (
    DefinitiveError,
    RetryableError,
    compute_backoff_delay,
    is_retryable_status,
    retry_async,
)


@pytest.mark.parametrize("status", [408, 425, 429, 500, 502, 503, 504])
def test_retryable_status_codes(status):
    assert is_retryable_status(status) is True


@pytest.mark.parametrize("status", [400, 401, 403, 404, 405])
def test_non_retryable_status_codes(status):
    assert is_retryable_status(status) is False


def test_backoff_delay_grows_exponentially_before_cap():
    delays = [
        compute_backoff_delay(attempt, base_delay_ms=100, max_delay_ms=100_000) for attempt in (1, 2, 3, 4)
    ]
    # Jitter is +/-20%, so compare midpoints loosely: each attempt's ceiling
    # (delay + 20%) must exceed the previous attempt's floor (delay - 20%).
    raw = [100, 200, 400, 800]
    for (delay, expected) in zip(delays, raw):
        assert expected * 0.8 <= delay * 1000 <= expected * 1.2


def test_backoff_delay_is_capped_at_max():
    delay = compute_backoff_delay(20, base_delay_ms=100, max_delay_ms=1000)
    assert delay * 1000 <= 1000 * 1.2  # cap + jitter headroom


def test_backoff_delay_never_negative():
    for attempt in range(1, 10):
        assert compute_backoff_delay(attempt, base_delay_ms=100, max_delay_ms=1000) >= 0


def test_retry_after_overrides_computed_backoff():
    delay = compute_backoff_delay(1, base_delay_ms=100, max_delay_ms=100_000, retry_after_seconds=7.5)
    assert delay == 7.5


async def test_retry_async_retries_until_success():
    attempts = {"count": 0}

    async def flaky():
        attempts["count"] += 1
        if attempts["count"] < 3:
            raise RetryableError("transient")
        return "ok"

    result = await retry_async(flaky, max_attempts=5)
    assert result == "ok"
    assert attempts["count"] == 3


async def test_retry_async_gives_up_after_max_attempts():
    attempts = {"count": 0}

    async def always_fails():
        attempts["count"] += 1
        raise RetryableError("still failing")

    with pytest.raises(RetryableError):
        await retry_async(always_fails, max_attempts=3)
    assert attempts["count"] == 3


async def test_retry_async_does_not_retry_definitive_errors():
    attempts = {"count": 0}

    async def definitive_failure():
        attempts["count"] += 1
        raise DefinitiveError("do not retry this")

    with pytest.raises(DefinitiveError):
        await retry_async(definitive_failure, max_attempts=5)
    assert attempts["count"] == 1
