"""Unit tests for the pure scheduler state machine in app/mercari/monitor.py
(spec section 65: ACTIVE -> DEGRADED -> BACKOFF, THROTTLED on 429, reset to
ACTIVE on success)."""

from __future__ import annotations

from datetime import datetime, timezone

from app.config.defaults import BACKOFF_AFTER_CONSECUTIVE_FAILURES, DEGRADED_AFTER_CONSECUTIVE_FAILURES
from app.database.models import KeywordStatus
from app.mercari.monitor import ScanOutcome, decide_next_run

NOW = datetime(2026, 1, 1, 12, 0, 0, tzinfo=timezone.utc)


def test_successful_scan_resets_to_active_and_schedules_next_interval():
    decision = decide_next_run(
        now=NOW, scan_interval_seconds=5, consecutive_failures=3, outcome=ScanOutcome(success=True)
    )
    assert decision.status == KeywordStatus.ACTIVE.value
    assert decision.consecutive_failures == 0
    assert decision.backoff_until is None
    assert (decision.next_scan_at - NOW).total_seconds() == 5


def test_single_failure_stays_active_below_degraded_threshold():
    decision = decide_next_run(
        now=NOW, scan_interval_seconds=5, consecutive_failures=0, outcome=ScanOutcome(success=False)
    )
    assert decision.consecutive_failures == 1
    assert decision.status == KeywordStatus.ACTIVE.value


def test_reaching_degraded_threshold_sets_degraded_status():
    decision = decide_next_run(
        now=NOW,
        scan_interval_seconds=5,
        consecutive_failures=DEGRADED_AFTER_CONSECUTIVE_FAILURES - 1,
        outcome=ScanOutcome(success=False),
    )
    assert decision.consecutive_failures == DEGRADED_AFTER_CONSECUTIVE_FAILURES
    assert decision.status == KeywordStatus.DEGRADED.value
    assert decision.backoff_until is None  # degraded still runs on the normal interval


def test_reaching_backoff_threshold_sets_backoff_and_delays_next_run():
    decision = decide_next_run(
        now=NOW,
        scan_interval_seconds=5,
        consecutive_failures=BACKOFF_AFTER_CONSECUTIVE_FAILURES - 1,
        outcome=ScanOutcome(success=False),
    )
    assert decision.consecutive_failures == BACKOFF_AFTER_CONSECUTIVE_FAILURES
    assert decision.status == KeywordStatus.BACKOFF.value
    assert decision.backoff_until is not None
    assert decision.next_scan_at == decision.backoff_until
    assert decision.next_scan_at > NOW


def test_backoff_delay_grows_with_more_failures():
    small = decide_next_run(
        now=NOW, scan_interval_seconds=5, consecutive_failures=4, outcome=ScanOutcome(success=False)
    )
    large = decide_next_run(
        now=NOW, scan_interval_seconds=5, consecutive_failures=10, outcome=ScanOutcome(success=False)
    )
    small_delay = (small.next_scan_at - NOW).total_seconds()
    large_delay = (large.next_scan_at - NOW).total_seconds()
    assert large_delay > small_delay


def test_backoff_delay_is_capped():
    decision = decide_next_run(
        now=NOW, scan_interval_seconds=5, consecutive_failures=50, outcome=ScanOutcome(success=False)
    )
    delay = (decision.next_scan_at - NOW).total_seconds()
    assert delay <= 600  # MAX_BACKOFF_SECONDS


def test_429_sets_throttled_and_honors_retry_after():
    decision = decide_next_run(
        now=NOW,
        scan_interval_seconds=5,
        consecutive_failures=0,
        outcome=ScanOutcome(success=False, throttled=True, retry_after_seconds=42.0),
    )
    assert decision.status == KeywordStatus.THROTTLED.value
    assert (decision.next_scan_at - NOW).total_seconds() == 42.0
    assert decision.backoff_until == decision.next_scan_at


def test_429_without_retry_after_falls_back_to_computed_backoff():
    decision = decide_next_run(
        now=NOW,
        scan_interval_seconds=5,
        consecutive_failures=0,
        outcome=ScanOutcome(success=False, throttled=True, retry_after_seconds=None),
    )
    assert decision.status == KeywordStatus.THROTTLED.value
    assert decision.next_scan_at > NOW


def test_success_after_backoff_immediately_returns_to_active():
    decision = decide_next_run(
        now=NOW, scan_interval_seconds=5, consecutive_failures=20, outcome=ScanOutcome(success=True)
    )
    assert decision.status == KeywordStatus.ACTIVE.value
    assert decision.consecutive_failures == 0
    assert (decision.next_scan_at - NOW).total_seconds() == 5
