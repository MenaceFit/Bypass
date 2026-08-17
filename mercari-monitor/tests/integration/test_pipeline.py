"""End-to-end pipeline test driven by a fixture/fake source — no real
browser or network access, per spec section 56 ("Utiliser des fixtures
pour éviter de dépendre du site réel à chaque test").

Covers: MarketplaceSource -> ListingService -> SQLite (dedup) -> event bus,
including the exact scenarios the spec calls out by name: a listing found
by re-scanning must never alert twice, and the first-run baseline import
must not spam Discord.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import pytest

from app.config.settings import settings
from app.database.database import session_scope
from app.database.models import KeywordStatus, NotificationStatus
from app.database.repositories import KeywordRepository, ListingFilter, ListingRepository, NotificationRepository
from app.events.bus import Event, EventType, event_bus
from app.mercari.client import SourceHealth
from app.mercari.normalizer import NormalizedListing
from app.mercari.search import SearchQuery
from app.services.keyword_service import KeywordInput, KeywordService
from app.services.monitoring_service import MonitoringService


def _listing(external_id: str, title: str, price: float = 100.0) -> NormalizedListing:
    return NormalizedListing(
        external_id=external_id,
        title=title,
        price=price,
        currency="USD",
        brand="Nike",
        listing_url=f"https://www.mercari.com/item/{external_id}/",
    )


class FakeSource:
    """A `MarketplaceSource` fed from an in-test script instead of a real
    browser — this is what makes the monitor/DB/event-bus wiring testable
    without depending on mercari.com being reachable."""

    def __init__(self, batches: list[list[NormalizedListing]]) -> None:
        self._batches = batches
        self.calls = 0

    async def search(self, query: SearchQuery) -> list[NormalizedListing]:
        batch = self._batches[min(self.calls, len(self._batches) - 1)]
        self.calls += 1
        return batch

    async def health_check(self) -> SourceHealth:
        return SourceHealth(available=True, status="ONLINE")


@dataclass
class CapturedEvents:
    events: list[Event] = field(default_factory=list)

    async def handler(self, event: Event) -> None:
        self.events.append(event)

    def of_type(self, event_type: EventType) -> list[Event]:
        return [e for e in self.events if e.type == event_type]


@pytest.fixture
async def captured_events(test_db):
    captured = CapturedEvents()
    event_bus.subscribe(None, captured.handler)
    yield captured
    event_bus.unsubscribe(None, captured.handler)


async def _make_keyword(discord_enabled: bool = True):
    async with session_scope() as session:
        service = KeywordService(KeywordRepository(session))
        return await service.create(
            KeywordInput(keyword="Nike ACG", discord_enabled=discord_enabled, scan_interval=5)
        )


async def test_first_scan_silent_import_suppresses_discord_and_new_listing_event(
    captured_events, monkeypatch
):
    monkeypatch.setattr(settings, "first_run_mode", "import_silent")
    monkeypatch.setattr(settings, "discord_webhook_url", "https://discord.com/api/webhooks/1/abc")

    keyword = await _make_keyword()
    source = FakeSource([[_listing("m1", "Nike ACG Jacket"), _listing("m2", "Nike ACG Pants")]])
    service = MonitoringService(source)

    await service.run_scan_now(keyword.id)

    # Both listings are persisted (they must be, so future scans recognize
    # them as already-known) but a first-run baseline must not alert.
    assert len(captured_events.of_type(EventType.LISTING_STORED)) == 2
    assert captured_events.of_type(EventType.LISTING_DISCOVERED) == []
    assert captured_events.of_type(EventType.DISCORD_NOTIFICATION_REQUIRED) == []

    async with session_scope() as session:
        refreshed = await KeywordRepository(session).get(keyword.id)
        assert refreshed.status == KeywordStatus.ACTIVE.value
        assert refreshed.consecutive_failures == 0
        assert refreshed.last_scan_at is not None


async def test_second_scan_detects_only_the_new_listing(captured_events, monkeypatch):
    monkeypatch.setattr(settings, "first_run_mode", "import_silent")
    monkeypatch.setattr(settings, "discord_webhook_url", "https://discord.com/api/webhooks/1/abc")

    keyword = await _make_keyword()
    source = FakeSource(
        [
            [_listing("m1", "Nike ACG Jacket")],
            [_listing("m1", "Nike ACG Jacket"), _listing("m2", "Nike ACG Pants - brand new")],
        ]
    )
    service = MonitoringService(source)

    await service.run_scan_now(keyword.id)  # baseline, silent (first ever scan)
    await service.run_scan_now(keyword.id)  # m2 is genuinely new this time

    discovered = captured_events.of_type(EventType.LISTING_DISCOVERED)
    assert len(discovered) == 1
    assert discovered[0].payload["external_id"] == "m2"

    async with session_scope() as session:
        pending = await NotificationRepository(session).get_pending_or_failed()
    assert len(pending) == 1
    assert pending[0].status == NotificationStatus.PENDING.value


async def test_rescanning_same_listing_never_fires_a_second_alert(captured_events, monkeypatch):
    monkeypatch.setattr(settings, "first_run_mode", "treat_as_new")

    keyword = await _make_keyword(discord_enabled=False)
    source = FakeSource([[_listing("m1", "Nike ACG Jacket")]])
    service = MonitoringService(source)

    await service.run_scan_now(keyword.id)
    await service.run_scan_now(keyword.id)
    await service.run_scan_now(keyword.id)

    discovered = captured_events.of_type(EventType.LISTING_DISCOVERED)
    assert len(discovered) == 1, "the same listing must only ever be announced once"
    assert source.calls == 3


async def test_multi_keyword_match_stores_once_but_links_both_keywords(captured_events, monkeypatch):
    monkeypatch.setattr(settings, "first_run_mode", "treat_as_new")

    async with session_scope() as session:
        kw_service = KeywordService(KeywordRepository(session))
        nike = await kw_service.create(KeywordInput(keyword="Nike", discord_enabled=False))
        nike_acg = await kw_service.create(KeywordInput(keyword="Nike ACG", discord_enabled=False))

    shared_listing = _listing("m1", "Nike ACG Jacket")
    service_a = MonitoringService(FakeSource([[shared_listing]]))
    service_b = MonitoringService(FakeSource([[shared_listing]]))

    await service_a.run_scan_now(nike.id)
    await service_b.run_scan_now(nike_acg.id)

    async with session_scope() as session:
        listing_repo = ListingRepository(session)
        total = await listing_repo.total_count()
        assert total == 1
        page = await listing_repo.list_paginated(ListingFilter())
        matched = await listing_repo.keywords_for_listing(page.items[0].id)
        assert set(matched) == {"Nike", "Nike ACG"}

    discovered = captured_events.of_type(EventType.LISTING_DISCOVERED)
    assert len(discovered) == 1, "one listing matched by two keywords is still exactly one alert"
