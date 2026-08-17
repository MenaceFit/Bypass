"""Spec section 43: CSV export. Exercises the streaming generator directly
(no browser/app boot needed — it only touches the database) against a
couple of seeded listings, checking the header and row shape survive a
real csv.reader round-trip.
"""

from __future__ import annotations

import csv
import io

from app.api.routes import _stream_listings_csv
from app.database.database import session_scope
from app.database.repositories import KeywordRepository, ListingFilter, ListingRepository
from app.services.keyword_service import KeywordInput, KeywordService
from app.utils.time import utc_now


async def _seed_two_listings():
    async with session_scope() as session:
        keyword = await KeywordService(KeywordRepository(session)).create(
            KeywordInput(keyword="Nike ACG", discord_enabled=False)
        )
        listing_repo = ListingRepository(session)
        for i in range(2):
            await listing_repo.upsert_listing_and_link(
                keyword_id=keyword.id,
                detected_at=utc_now(),
                values={
                    "external_id": f"m_csv_{i}",
                    "title": f"Nike ACG Item {i}",
                    "description": None,
                    "price": 100.0 + i,
                    "currency": "USD",
                    "brand": "Nike",
                    "category": None,
                    "size": "M",
                    "condition": "Good",
                    "item_status": None,
                    "seller_username": "seller1",
                    "seller_id": None,
                    "image_url": None,
                    "listing_url": f"https://www.mercari.com/item/m_csv_{i}/",
                    "created_at_source": None,
                    "detection_latency_ms": None,
                },
            )


async def test_csv_export_contains_header_and_all_rows(test_db):
    await _seed_two_listings()

    chunks = [chunk async for chunk in _stream_listings_csv(ListingFilter())]
    content = "".join(chunks)

    rows = list(csv.reader(io.StringIO(content)))
    header, *data_rows = rows

    assert header == [
        "ID", "Title", "Price", "Currency", "Brand", "Category", "Size", "Condition",
        "Seller", "Keyword", "Created At", "Detected At", "Detection Latency (ms)", "URL",
    ]
    assert len(data_rows) == 2
    titles = {row[1] for row in data_rows}
    assert titles == {"Nike ACG Item 0", "Nike ACG Item 1"}
    for row in data_rows:
        assert row[9] == "Nike ACG"  # Keyword column
        assert row[7] == "Good"  # Condition column


async def test_csv_export_respects_filters(test_db):
    await _seed_two_listings()

    chunks = [
        chunk async for chunk in _stream_listings_csv(ListingFilter(min_price=100.5))
    ]
    content = "".join(chunks)
    rows = list(csv.reader(io.StringIO(content)))
    _, *data_rows = rows
    assert len(data_rows) == 1
    assert data_rows[0][1] == "Nike ACG Item 1"


async def test_csv_export_empty_still_has_header(test_db):
    chunks = [chunk async for chunk in _stream_listings_csv(ListingFilter())]
    content = "".join(chunks)
    rows = list(csv.reader(io.StringIO(content)))
    assert len(rows) == 1  # header only
