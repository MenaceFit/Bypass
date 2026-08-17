"""Constants that are not meant to be tuned through the environment.

Anything an operator might reasonably want to change at deploy time belongs
in `settings.py` / `.env` instead. This module holds fixed application
behavior: pagination caps, backoff schedules, and other implementation
constants shared across layers.
"""

from __future__ import annotations

# --- Pagination ---------------------------------------------------------
DEFAULT_PAGE_SIZE = 25
MAX_PAGE_SIZE = 100

# --- Live feed ------------------------------------------------------------
# The dashboard only keeps the most recent N listings in the in-memory live
# feed; the full history always remains queryable from SQLite.
LIVE_FEED_MAX_ITEMS = 100

# --- Retry / backoff ----------------------------------------------------
# Base schedule for HTTP-level retries (see utils/retry.py). Actual delays
# are derived from settings.retry_base_delay_ms with exponential growth and
# jitter; this tuple documents the intended shape at the default settings.
RETRY_BACKOFF_EXAMPLE_MS = (100, 250, 500, 1000)
RETRY_JITTER_RATIO = 0.2  # +/- 20% jitter applied to each computed delay

# Status codes that are safe to retry (transient). Everything else is a
# definitive failure and must not be retried.
RETRYABLE_HTTP_STATUS = frozenset({408, 425, 429, 500, 502, 503, 504})

# Status codes that mean "the caller is being rate limited / must slow down"
# as opposed to a generic server error.
THROTTLE_HTTP_STATUS = frozenset({429})

# --- Scan scheduler -------------------------------------------------------
# Consecutive failures after which an ACTIVE keyword is demoted to DEGRADED,
# and after which a DEGRADED keyword is demoted to BACKOFF.
DEGRADED_AFTER_CONSECUTIVE_FAILURES = 2
BACKOFF_AFTER_CONSECUTIVE_FAILURES = 5
# Backoff ceiling so a permanently broken keyword doesn't get scanned less
# than once every 10 minutes (it should still recover automatically).
MAX_BACKOFF_SECONDS = 600

# --- Discord ----------------------------------------------------------------
DISCORD_MAX_ATTEMPTS = 5
DISCORD_EMBED_COLOR_NEW_LISTING = 0x2ECC71
DISCORD_RETRY_BASE_DELAY_S = 2

# --- Sorting ----------------------------------------------------------------
SORT_OPTIONS = (
    "newest",
    "oldest",
    "price_low",
    "price_high",
    "detection_fastest",
)

# --- HTTP client identity ---------------------------------------------------
# A standard, honest desktop browser User-Agent. This is not fingerprint
# spoofing: the Mercari client only ever runs inside a real Chromium browser
# (see mercari/client.py), and this string simply matches what that real
# browser already sends. No headers are forged to impersonate a different
# client than the one actually making the request.
DEFAULT_NAVIGATION_TIMEOUT_MS = 15000
