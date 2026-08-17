# Mercari US Monitor

A local, professional-grade monitoring tool for [mercari.com](https://www.mercari.com) (Mercari US). You give it keywords; it watches Mercari's search results and tells you — on a live dashboard and, optionally, in Discord — the moment a new matching listing becomes visible, without duplicates and without pretending to guarantee instant, sub-second detection that no polling-based tool can honestly promise.

This is not affiliated with Mercari. It does not bypass CAPTCHAs, Cloudflare, login walls, or any other access control, and it never will — see [Architecture](#architecture) for why that constraint actually shapes how this tool is built, not just a disclaimer bolted on afterward.

## Table of contents

- [Overview](#overview)
- [Features](#features)
- [Requirements](#requirements)
- [Installation](#installation)
- [Configuration](#configuration)
- [Discord](#discord)
- [Adding searches](#adding-searches)
- [Running](#running)
- [Architecture](#architecture)
- [Database](#database)
- [API](#api)
- [Tests](#tests)
- [Troubleshooting](#troubleshooting)
- [Limitations](#limitations)
- [Development](#development)

## Overview

You add a keyword — `Nike ACG`, `Miu Miu`, `Louis Vuitton Keepall` — and the monitor starts polling Mercari's search results for it, at an interval you control, subject to a global rate limit shared across every keyword you configure. When a listing appears that it hasn't seen before, it is:

1. parsed and normalized into a consistent shape,
2. persisted to a local SQLite database with a hard uniqueness guarantee (it cannot be recorded twice, ever, even across restarts or crashes),
3. pushed to the dashboard instantly over WebSocket,
4. optionally sent to a Discord channel via webhook,
5. counted in the statistics page,
6. and never surfaced as "new" again on a later scan.

The one thing this tool will not do is get you information faster than Mercari makes it available, or by means Mercari doesn't intend for a script to use. If that access is ever restricted or slowed, the tool visibly enters a degraded state and backs off — it does not try harder.

## Features

- Multiple independent keyword searches, each with its own scan interval, price range, Discord toggle, and best-effort brand/size/condition/category filters
- Real-time dashboard: system status, live feed, per-search status (`ACTIVE` / `PAUSED` / `THROTTLED` / `DEGRADED` / `BACKOFF` / `ERROR`)
- WebSocket push with automatic reconnect (1s → 2s → 5s → 10s backoff)
- Discord notifications with a dedicated queue and retry-with-backoff, decoupled from scanning so a Discord outage never slows detection
- Deduplication enforced at the database layer (`UNIQUE` constraint + atomic upsert), not just in application logic
- A "first run" choice — import existing results silently, or treat them as new — so turning on a search doesn't dump 50 Discord notifications at once
- Global rate limiting (concurrency cap + minimum interval) shared across every keyword, configurable but never bypassable from the UI
- Automatic exponential backoff with jitter on transient errors, explicit handling of HTTP 429 (`Retry-After` honored)
- Listings browser with filters, sorting, and pagination; CSV export; configurable archiving of old listings
- Statistics page (detection latency, most active keyword/brand, Discord delivery rates, request/429 counts)
- Structured system logs with level filtering, backed by rotating log files on disk
- Settings page for the things that are safe to change at runtime (theme, sound/desktop notifications, first-run behavior) — infrastructure settings (concurrency, timeouts, the Discord webhook itself) live in `.env` on purpose, see [Configuration](#configuration)
- SQLite reset and archival, both behind explicit confirmation

## Requirements

- Python 3.12+
- Node.js 18+ and npm (only needed to build the dashboard)
- A Chromium browser for Playwright (see [Installation](#installation) — this is not optional, and the [Architecture](#architecture) section explains why)

## Installation

```bash
git clone <this-repo>
cd mercari-monitor

python3.12 -m venv .venv
source .venv/bin/activate          # .venv\Scripts\activate on Windows

pip install -r requirements.txt
playwright install chromium        # downloads a managed Chromium build

cd frontend
npm install
npm run build
cd ..

cp .env.example .env               # edit if you want Discord notifications, etc.

python run.py
```

`run.py` starts the backend, serves the built dashboard, and opens `http://127.0.0.1:8000` in your default browser once the server is ready.

## Configuration

All configuration lives in `.env` (copy `.env.example` to start). Nothing here is optional to understand before running this against your own Mercari usage — in particular, `MAX_CONCURRENT_REQUESTS` and `MIN_REQUEST_INTERVAL_MS` are the two knobs that keep this tool from ever hammering Mercari, no matter how many keywords or how short an interval you configure per search.

| Variable | Default | Meaning |
|---|---|---|
| `APP_HOST` / `APP_PORT` | `127.0.0.1` / `8000` | Where the dashboard is served. Keep this on localhost — see [Security](#security). |
| `DATABASE_URL` | `sqlite+aiosqlite:///./data/mercari.db` | SQLite database location. |
| `DEFAULT_SCAN_INTERVAL` | `5` | Seconds between scans for a new search that doesn't specify its own. |
| `MIN_SCAN_INTERVAL` | `3` | Hard floor — no search, however configured, can scan more often than this. |
| `MAX_CONCURRENT_REQUESTS` | `3` | Global cap on simultaneous Mercari fetches across every keyword. |
| `MIN_REQUEST_INTERVAL_MS` | `800` | Minimum gap between the *start* of consecutive fetches, globally. |
| `REQUEST_TIMEOUT` | `10` | Seconds. |
| `NAVIGATION_TIMEOUT_MS` | `15000` | Playwright page-navigation timeout. |
| `BROWSER_HEADLESS` | `true` | Set `false` to watch the browser while debugging locally. |
| `PLAYWRIGHT_EXECUTABLE_PATH` | *(empty)* | Advanced: point at a specific Chromium binary instead of Playwright's managed one. |
| `RETRY_MAX_ATTEMPTS` / `RETRY_BASE_DELAY_MS` / `RETRY_MAX_DELAY_MS` | `4` / `250` / `8000` | Exponential backoff shape for transient failures. |
| `DISCORD_WEBHOOK_URL` | *(empty)* | Leave empty to disable Discord entirely. |
| `LOG_LEVEL` | `INFO` | `DEBUG` \| `INFO` \| `WARNING` \| `ERROR` \| `CRITICAL`. |
| `LOG_DIR`, `LOG_MAX_BYTES`, `LOG_BACKUP_COUNT` | `./logs`, 5MB, 5 | Log rotation. |
| `DISPLAY_TIMEZONE` | `UTC` | Display-only; storage is always UTC. |
| `ARCHIVE_AFTER_DAYS` | `90` | Default suggestion for the archive-old-listings action (Settings page). |
| `FIRST_RUN_MODE` | `import_silent` | Default for the first-run choice; overridable at runtime from the dashboard. |

A handful of *non*-infrastructure preferences (theme, sound/desktop notifications, first-run mode) are instead stored in the database and editable from the Settings page — see the note there about why that split exists.

## Discord

1. In Discord: Server Settings → Integrations → Webhooks → New Webhook, pick a channel, copy the URL.
2. Put it in `.env` as `DISCORD_WEBHOOK_URL` and restart the app. The webhook is never exposed in the UI or logs except as a masked string (`https://discord.com/api/w…xyz`), and it is never written anywhere by the application itself — only you, editing `.env`, can set or change it.
3. On the Settings page, click **Test Webhook** to confirm delivery.
4. Per-search, toggle **Send Discord notifications for this search** in the search's edit form.

If Discord is unreachable or rate-limits you, notifications queue with retries (up to 5 attempts, exponential backoff) and are marked `FAILED` after that — scanning and the dashboard are never affected, because Discord delivery runs on its own queue, completely decoupled from detection.

## Adding searches

From the **Searches** page, **Add Search**, and fill in:

- **Keyword** — required, this is what gets searched.
- **Scan interval** — how often this keyword is checked, subject to the global floor and rate limit above.
- **Minimum / maximum price** — applied after a listing is fetched, so listings outside the range are counted separately rather than silently vanishing (see Statistics).
- **Brand / size / condition / category** — passed through to Mercari's search as filters, best-effort (see [Limitations](#limitations) on why these can't be guaranteed to map to a stable internal ID).
- **Sort** — newest, lowest price, or highest price; this changes what Mercari itself returns, not just local sorting.
- **Include / exclude keywords** — additional substrings a listing's title/description must (or must not) contain.
- **Discord notifications** — on/off for this search specifically.

The first time *any* search actually runs, existing Mercari results are handled according to the first-run choice you're asked for the first time you open the dashboard with zero searches configured (or can change later in Settings): **import silently** (recommended — establishes a baseline with no alerts) or **treat as new** (every existing result fires a normal alert).

## Running

```bash
python run.py
```

For frontend development with hot reload:

```bash
# terminal 1
python run.py

# terminal 2
cd frontend && npm run dev   # http://127.0.0.1:5173, proxies /api and /ws to :8000
```

## Architecture

```
                    MERCARI (real browser session)
                            │
                            ▼
                     mercari/client.py       (Playwright — see below)
                            │
                            ▼
                     mercari/search.py       (MarketplaceSource / SearchQuery)
                            │
                            ▼
                     mercari/parser.py       (raw payload -> RawListing)
                            │
                            ▼
                   mercari/normalizer.py     (RawListing -> NormalizedListing)
                            │
                            ▼
                services/listing_service.py  (price/keyword filters, then persist)
                            │
                            ▼
                        SQLite (dedup enforced by a UNIQUE constraint)
                            │
                            ▼
                      events/bus.py
                       /          \
                      ▼            ▼
              api/websocket.py   services/notification_service.py
                      │                    │
                      ▼                    ▼
                  Dashboard              Discord
```

### Why a real browser, not a plain HTTP client

This is the single most important design decision in the project, and it came out of research done *before* writing `mercari/client.py`, not an afterthought:

Mercari US (`mercari.com`) is a Next.js single-page app. The search page's initial HTML does **not** contain results — they're fetched by the page's own client-side JavaScript from an internal API. That API requires session-bound authentication: a signed, DPoP-style token minted by the page's own script, plus a Cloudflare bot-management cookie (`cf-bm`) issued during a live browser session. A plain HTTP client (`httpx`, `requests`, curl) gets rejected outright — this isn't a missing header, it's a deliberate anti-automation mechanism, and third-party tools exist specifically to reverse-engineer and forge that token.

This project will not do that. Forging that token, or otherwise replicating what Cloudflare's bot management is designed to block, is exactly the kind of protection bypass this tool is built not to perform, on principle and by explicit design brief.

The access path that remains — and the one this tool uses — is a real, unmodified Chromium browser (via Playwright) that loads the actual search page and lets its own JavaScript run normally, exactly as a human visitor's browser would. `mercari/client.py` navigates to the real page, lets the site authenticate itself, and listens for the response its own script legitimately receives (or, if that can't be intercepted, reads whatever rendered in the DOM as a fallback). No fingerprint spoofing, no `navigator.webdriver` masking, no stealth plugins, no CAPTCHA solving, no proxy rotation. **If Cloudflare or Mercari still blocks this traffic, the tool reports `BLOCKED`/`DEGRADED` and backs off — it does not escalate.** That is not a limitation to be fixed later; it is the point.

One consequence worth being explicit about: **this could not be verified against the live mercari.com site during development.** The sandboxed environment this was built in blocks outbound network access to `mercari.com` at the infrastructure level (confirmed via the proxy's own diagnostics, not a guess), for reasons unrelated to Mercari's own protections. The `mercari/parser.py` field-extraction logic was built from public research (Mercari's own engineering blog, public documentation of the search response shape) rather than a captured live payload, and is deliberately defensive — every field except the unique ID is optional, multiple plausible key names are tried per field (see the tuples at the top of `parser.py`), and nothing is invented when data is missing. **You should verify `parser.py` against the real site once you run this locally**, and expect to adjust the field-name candidates or, if Mercari's structure has changed since, the extraction logic itself — that file is deliberately the *only* one that should need to change (see [Limitations](#limitations)).

### Layering

- `mercari/` never imports anything from `services/`, `api/`, or `notifications/` — it only knows how to fetch and parse.
- `services/` contains all business logic (filtering, deduplication orchestration, scheduling side effects) and is the only layer that talks to both `mercari/` and `database/`.
- `events/bus.py` is the only channel between the monitor and anything that reacts to what it finds — the scraper has no idea Discord or the dashboard exist.
- `api/` is a thin presentation layer over `services/` and `database/repositories.py`.

## Database

SQLite, via SQLAlchemy 2.0's async engine (`aiosqlite`). Schema is created and evolved through a small dependency-free migration runner (`app/database/migrations.py`) rather than Alembic — this is a single-database, single-user local tool, so a full migration framework would be more machinery than the problem needs. `run_migrations()` runs on every startup and is idempotent.

Tables: `keywords`, `listings`, `listing_keywords` (many-to-many: which searches found a listing), `notifications` (Discord delivery state), `scan_runs` (per-scan audit trail), `app_settings` (the small set of runtime-editable preferences).

Every timestamp is stored and handled as timezone-aware UTC — SQLite has no native timezone-aware timestamp type, so a custom `UTCDateTime` column type (`app/database/models.py`) strips the offset before writing and re-attaches `UTC` after reading, so nothing downstream has to remember to convert.

Deduplication is enforced by a `UNIQUE` constraint on `listings.external_id` combined with `INSERT ... ON CONFLICT DO NOTHING ... RETURNING`, not by an application-level "check, then insert" — that would race under concurrent keyword scans finding the same listing at nearly the same moment. The database itself is the source of truth for "have we seen this before," which is what makes the dedup guarantee hold across restarts, crashes, and multiple keywords matching the same listing.

Backups: it's a single file (`data/mercari.db`, plus WAL/SHM files while running) — stop the app and copy it. Reset and archival are available from the Settings page, both behind explicit confirmation (reset requires typing the exact phrase `DELETE ALL DATA`).

## API

FastAPI generates interactive OpenAPI documentation automatically — with the app running, visit `http://127.0.0.1:8000/docs`.

Summary of the REST surface (all under `/api`, plus `/ws` for the WebSocket):

```
GET    /health
GET    /searches                    POST /searches
GET    /searches/{id}               PUT  /searches/{id}     DELETE /searches/{id}
POST   /searches/{id}/pause         POST /searches/{id}/resume
GET    /searches/export             POST /searches/import
GET    /monitoring/status           POST /monitoring/pause-all   POST /monitoring/resume-all
GET    /listings                    GET  /listings/{id}
GET    /listings/export             POST /listings/archive
GET    /stats
GET    /logs
POST   /discord/test
GET    /settings                    PUT  /settings
POST   /database/reset
```

WebSocket events pushed on `/ws`: `new_listing`, `scan_started`, `scan_finished`, `keyword_updated`, `system_status`, `error`.

## Tests

```bash
pip install -r requirements-dev.txt
pytest
```

103 tests, split by what they need:

- **Unit tests** (`tests/unit/`) are pure — parser field extraction, price/timestamp normalization, the scheduler's status state machine, retry/backoff math, input validation, the rate limiter's concurrency and interval behavior, and the event-bus→WebSocket translation layer. None of these touch a network or a browser.
- **Integration tests** (`tests/integration/`):
  - `test_pipeline.py` drives the full source→parser→normalizer→database→event-bus pipeline against a fixture-fed fake `MarketplaceSource` (no browser, no network) — this is what proves deduplication, multi-keyword matching, and the first-run silent-import behavior actually work end to end.
  - `test_mercari_client.py` and `test_app_startup.py` launch a **real** headless Chromium via Playwright against fully mocked pages (network-intercepted, not live) to verify the browser-automation mechanics themselves — navigation, response interception, HTTP status classification, DOM fallback extraction, and a full FastAPI app boot including the real Playwright client. These skip automatically (not fail) if no Chromium binary is available in the environment they're run in — verifying real browser behavior needs a real browser, but a missing one shouldn't block `pytest` elsewhere.
  - Discord delivery is tested with `respx`-mocked HTTP (success, timeout, 404, 500, 429) — no real Discord message is ever sent by the test suite.

None of the tests make a network request to `mercari.com`; that's deliberate (see [Limitations](#limitations)).

## Troubleshooting

**No listings appear at all.**
Check the search's status on the Searches page. `DEGRADED`/`BACKOFF`/`ERROR` with a message means the last scan failed — click through to Logs for the full error. If it's stuck on `ACTIVE` with `Last scan: never`, check the Logs page for startup errors (the Mercari browser client failing to launch is the most common cause — see below).

**Discord isn't sending anything.**
Confirm `DISCORD_WEBHOOK_URL` is set in `.env` and the app was restarted after editing it (Settings → Discord shows whether it's configured). Use **Test Webhook**. Check that the search itself has Discord enabled, and check the Statistics page's Discord counts — a growing `Failed` count with a static `Sent` count points at a bad or revoked webhook URL.

**Mercari responds with 429 / a search is `THROTTLED`.**
This is the rate limiter and Mercari agreeing that you're going too fast. It is handled automatically (the search backs off, honoring `Retry-After` when Mercari sends one) — do not lower `MIN_REQUEST_INTERVAL_MS` or raise `MAX_CONCURRENT_REQUESTS` to make this go away faster; that's the opposite of what those settings are for.

**A search is stuck `DEGRADED` or `BACKOFF`.**
Read the search's error message (Searches page) or the Logs page. If it's a real Mercari-side block (Cloudflare challenge, session rejected), this tool will not attempt to force through it — that's by design (see [Architecture](#architecture)). It retries automatically on an increasing backoff and will recover on its own once access is available again; there is nothing to "fix" beyond waiting, unless the error indicates something adjustable (a malformed keyword, an unreachable network).

**WebSocket shows "Disconnected".**
The dashboard reconnects on its own (1s → 2s → 5s → 10s). If it stays disconnected, the backend process likely isn't running or crashed — check the terminal / logs.

**"database is locked".**
SQLite runs in WAL mode specifically to avoid this under normal use (concurrent reads don't block the writer). If you still hit it, you likely have a second process holding the same `data/mercari.db` open (e.g., a second `run.py` instance, or a DB browser tool with a write transaction open) — close it.

**Parser errors in the logs.**
`ParserError` (logged, not raised to the caller) means a listing had no extractable unique ID and was skipped — that listing is lost for that scan, but nothing else is affected. Frequent parser errors, or a search that keeps returning zero results you know should exist, most likely mean Mercari changed its response structure.

**"The site has changed" — how do I fix it.**
By design, only `app/mercari/parser.py` should need edits (see [Architecture](#architecture)). Start with the key-name candidate tuples at the top of the file (`_ID_KEYS`, `_TITLE_KEYS`, `_PRICE_KEYS`, etc.) — add the new key name Mercari is actually using. If the response shape changed more substantially (e.g., results moved out of a top-level `data` array), update `_extract_items`. `tests/fixtures/mercari_search_response.json` is a good place to paste a real captured response shape and adjust the parser tests to match.

## Limitations

Read this before assuming a gap is a bug:

- **Detection latency is polling latency, not push latency.** Mercari does not offer a real-time feed for search results. A 5-second scan interval means "checked at least every 5 seconds, load and processing time on top" — never a guarantee of sub-5-second, let alone sub-second, detection. `detection_latency_ms` is only ever computed when Mercari itself provided a genuine creation timestamp for a listing; if it didn't, `created_at_source` is `NULL` and no latency is invented or estimated.
- **Realistic sustained scan intervals are higher than the floor suggests once you have several keywords.** Every keyword shares one global rate limiter (`MAX_CONCURRENT_REQUESTS`, `MIN_REQUEST_INTERVAL_MS`); browser-based navigation is also inherently heavier than a raw HTTP request. Ten keywords at a 5-second interval will not sustain ten fetches every 5 seconds — they'll queue behind the shared limiter, which is the intended, load-respecting behavior, not a bug.
- **This tool will never bypass a block.** `DEGRADED`, `BLOCKED`, or `THROTTLED` states are correct, expected outcomes when Mercari's own protections engage — not defects to be worked around by adding fingerprint spoofing, CAPTCHA solving, or proxy rotation. That door is intentionally not there.
- **The parser's exact field mapping is best-effort, not verified against a live response**, for the infrastructure reason explained in [Architecture](#architecture). Treat brand/size/condition/category filters and any field beyond id/title/price/URL as "should work, verify against the real site."
- **Brand/size/category filters are passed through to Mercari as-is**, not validated against a curated list — Mercari's internal filter IDs are, per public research, versioned/unstable rather than a small stable enum, so this tool does not pretend to offer a dropdown of "real" Mercari brand IDs it cannot actually verify.
- **Location filtering** is exposed as a pass-through field for parity with the spec that shaped this tool, but there's no confirmed evidence Mercari US's search actually supports filtering by location the way local-marketplace apps do — don't rely on it silently doing something if it appears to have no effect.
- **This is a single-user, localhost tool.** There's no auth on the API/dashboard by design — see [Security](#security). Don't expose it beyond `127.0.0.1`.

### Security

Binds to `127.0.0.1` by default (`APP_HOST`) — do not change this to `0.0.0.0` or put it behind a public reverse proxy without adding your own authentication first; nothing in this app implements auth. The Discord webhook URL is read only from `.env`, is never logged (log lines are redacted defensively even if one somehow tried to), and is only ever shown in the UI masked. Secrets are never written into the database.

## Development

```bash
pip install -r requirements-dev.txt
ruff check app/ run.py
mypy app/
pytest
```

Both `ruff` (E/F/I/UP/B/SIM rule sets) and `mypy` run clean against `app/`. Two conventions worth knowing before contributing:

- Every unit of database work uses `async with session_scope(): ...` (or a repository built on an explicitly-passed session) — never a bare, unmanaged `AsyncSession`.
- Retries only ever apply to transient failures (`RetryableError` / specific retryable HTTP status codes); a 400/401/403/404 or a parsing failure must propagate immediately rather than being retried into a wasted request.

Project layout:

```
mercari-monitor/
├── app/
│   ├── main.py                # FastAPI app + lifespan (startup/shutdown order matters, see comments)
│   ├── config/                 # settings.py (.env-driven), defaults.py (fixed constants)
│   ├── database/                # models, engine/session, repositories, migrations
│   ├── mercari/                # client (Playwright), search, parser, normalizer, monitor (scheduler), rate_limiter
│   ├── services/                # business logic: listing/keyword/monitoring/notification services
│   ├── notifications/           # discord.py — embed construction + HTTP call only
│   ├── api/                     # routes.py, schemas.py, websocket.py
│   ├── events/                  # bus.py — the only channel between the monitor and everything else
│   └── utils/                   # logger, retry, time, validation
├── frontend/                    # React + TypeScript + Vite + Tailwind
├── tests/
│   ├── unit/
│   ├── integration/
│   └── fixtures/
├── data/                        # mercari.db (gitignored)
├── logs/                        # rotating app.log (gitignored)
└── run.py                       # entry point
```
