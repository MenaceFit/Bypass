"""Retry / backoff helpers shared by every outbound call (Mercari browser
client, Discord webhook worker).

`compute_backoff_delay` is a pure function so callers that need to honor a
server-provided `Retry-After` (HTTP 429) can special-case it; `retry_async`
is a small tenacity-based wrapper for the common case of "retry a coroutine
on transient failure with exponential backoff + jitter".

Retries only ever apply to `RetryableError`. Definitive failures
(`DefinitiveError`, or any exception not explicitly marked retryable) must
propagate immediately — retrying a 401/403/404 or a parser error wastes
requests and hides real bugs.
"""

from __future__ import annotations

import random
from collections.abc import Awaitable, Callable

from tenacity import (
    AsyncRetrying,
    RetryCallState,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential_jitter,
)

from app.config.defaults import RETRYABLE_HTTP_STATUS
from app.config.settings import settings
from app.utils.logger import get_logger

logger = get_logger(__name__)


class RetryableError(Exception):
    """A transient failure that is safe to retry (timeout, 5xx, 429, ...)."""

    def __init__(self, message: str, *, retry_after_seconds: float | None = None) -> None:
        super().__init__(message)
        self.retry_after_seconds = retry_after_seconds


class DefinitiveError(Exception):
    """A failure that must NOT be retried (4xx other than 408/429, malformed
    input that retrying cannot fix, etc.)."""


def is_retryable_status(status_code: int) -> bool:
    return status_code in RETRYABLE_HTTP_STATUS


def compute_backoff_delay(
    attempt: int,
    *,
    base_delay_ms: int | None = None,
    max_delay_ms: int | None = None,
    retry_after_seconds: float | None = None,
) -> float:
    """Seconds to wait before retry number `attempt` (1-indexed).

    Honors an explicit `Retry-After` when the server provided one;
    otherwise full exponential backoff with +/-20% jitter, capped.
    """
    if retry_after_seconds is not None:
        return max(0.0, retry_after_seconds)

    base = base_delay_ms if base_delay_ms is not None else settings.retry_base_delay_ms
    cap = max_delay_ms if max_delay_ms is not None else settings.retry_max_delay_ms

    raw_ms = min(base * (2 ** (attempt - 1)), cap)
    jitter_ms = raw_ms * random.uniform(-0.2, 0.2)
    return max(0.0, (raw_ms + jitter_ms) / 1000)


def _log_retry(retry_state: RetryCallState) -> None:
    exc = retry_state.outcome.exception() if retry_state.outcome else None
    logger.warning(
        "Retry attempt %s scheduled after %s: %s",
        retry_state.attempt_number,
        type(exc).__name__ if exc else "unknown error",
        exc,
    )


async def retry_async[T](
    func: Callable[[], Awaitable[T]],
    *,
    max_attempts: int | None = None,
    retry_on: tuple[type[BaseException], ...] = (RetryableError,),
) -> T:
    """Run `func` with exponential backoff + jitter, retrying only on
    `retry_on` exception types. Re-raises the final exception on exhaustion."""
    attempts = max_attempts if max_attempts is not None else settings.retry_max_attempts

    async for attempt in AsyncRetrying(
        stop=stop_after_attempt(attempts),
        wait=wait_exponential_jitter(
            initial=settings.retry_base_delay_ms / 1000,
            max=settings.retry_max_delay_ms / 1000,
        ),
        retry=retry_if_exception_type(retry_on),
        reraise=True,
        before_sleep=_log_retry,
    ):
        with attempt:
            return await func()
    raise AssertionError("unreachable")  # pragma: no cover
