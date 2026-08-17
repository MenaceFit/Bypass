"""Pure scheduling logic (spec section 65, "Smart Scheduler").

Given a keyword's current scan state and the outcome of the scan that just
ran, decide when it should run next and what its operational status should
be. No I/O, no DB, no network — `services/monitoring_service.py` drives
this state machine and persists its decisions; keeping it pure makes it
trivial to unit test every transition (spec section 55/56).

Status ladder:
    ACTIVE --(consecutive failures)--> DEGRADED --(more failures)--> BACKOFF
    any status --(a 429 / Retry-After)--> THROTTLED
    any status --(a successful scan)--> ACTIVE
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta

from app.config.defaults import (
    BACKOFF_AFTER_CONSECUTIVE_FAILURES,
    DEGRADED_AFTER_CONSECUTIVE_FAILURES,
    MAX_BACKOFF_SECONDS,
)
from app.database.models import KeywordStatus


@dataclass
class ScanOutcome:
    success: bool
    throttled: bool = False
    retry_after_seconds: float | None = None
    error_message: str | None = None


@dataclass
class SchedulerDecision:
    status: str
    next_scan_at: datetime
    consecutive_failures: int
    backoff_until: datetime | None


def decide_next_run(
    *,
    now: datetime,
    scan_interval_seconds: int,
    consecutive_failures: int,
    outcome: ScanOutcome,
) -> SchedulerDecision:
    if outcome.success:
        return SchedulerDecision(
            status=KeywordStatus.ACTIVE.value,
            next_scan_at=now + timedelta(seconds=scan_interval_seconds),
            consecutive_failures=0,
            backoff_until=None,
        )

    failures = consecutive_failures + 1

    if outcome.throttled:
        delay = outcome.retry_after_seconds if outcome.retry_after_seconds is not None else _backoff_seconds(failures)
        backoff_until = now + timedelta(seconds=delay)
        return SchedulerDecision(
            status=KeywordStatus.THROTTLED.value,
            next_scan_at=backoff_until,
            consecutive_failures=failures,
            backoff_until=backoff_until,
        )

    if failures >= BACKOFF_AFTER_CONSECUTIVE_FAILURES:
        backoff_until = now + timedelta(seconds=_backoff_seconds(failures))
        return SchedulerDecision(
            status=KeywordStatus.BACKOFF.value,
            next_scan_at=backoff_until,
            consecutive_failures=failures,
            backoff_until=backoff_until,
        )

    if failures >= DEGRADED_AFTER_CONSECUTIVE_FAILURES:
        return SchedulerDecision(
            status=KeywordStatus.DEGRADED.value,
            next_scan_at=now + timedelta(seconds=scan_interval_seconds),
            consecutive_failures=failures,
            backoff_until=None,
        )

    return SchedulerDecision(
        status=KeywordStatus.ACTIVE.value,
        next_scan_at=now + timedelta(seconds=scan_interval_seconds),
        consecutive_failures=failures,
        backoff_until=None,
    )


def _backoff_seconds(failures: int) -> float:
    return min(MAX_BACKOFF_SECONDS, 10 * (2 ** min(failures, 10)))
