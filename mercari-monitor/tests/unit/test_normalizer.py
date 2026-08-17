from datetime import datetime, timedelta, timezone

import pytest

from app.mercari.normalizer import normalize_listing, normalize_price, normalize_timestamp
from app.mercari.parser import RawListing


@pytest.mark.parametrize(
    ("raw", "currency_hint", "expected_price", "expected_currency"),
    [
        ("$120", None, 120.0, "USD"),
        ("USD 120", None, 120.0, "USD"),
        ("$120.00", None, 120.0, "USD"),
        ("$1,299.99", None, 1299.99, "USD"),
        (120, None, 120.0, "USD"),
        (120.5, None, 120.5, "USD"),
        (None, None, None, "USD"),
        ("", None, None, "USD"),
        ("Free", None, None, "USD"),
        ("85", "USD", 85.0, "USD"),
    ],
)
def test_normalize_price(raw, currency_hint, expected_price, expected_currency):
    price, currency = normalize_price(raw, currency_hint)
    assert price == expected_price
    assert currency == expected_currency


def test_normalize_timestamp_epoch_seconds():
    dt = normalize_timestamp(1755417161)
    assert dt is not None
    assert dt.tzinfo is not None
    assert dt.year == 2025


def test_normalize_timestamp_epoch_millis():
    dt = normalize_timestamp(1755417161000)
    assert dt is not None
    assert dt.year == 2025


def test_normalize_timestamp_iso_string():
    dt = normalize_timestamp("2025-08-17T08:12:41Z")
    assert dt is not None
    assert dt.tzinfo == timezone.utc
    assert dt.hour == 8


def test_normalize_timestamp_none_stays_none():
    assert normalize_timestamp(None) is None


def test_normalize_timestamp_garbage_string_returns_none():
    assert normalize_timestamp("not-a-date") is None


def test_normalize_timestamp_rejects_future_timestamp():
    future = (datetime.now(timezone.utc) + timedelta(days=30)).isoformat()
    assert normalize_timestamp(future) is None


def test_normalize_timestamp_rejects_implausibly_old_timestamp():
    assert normalize_timestamp("2001-01-01T00:00:00Z") is None


def test_normalize_listing_full():
    raw = RawListing(
        external_id="m12345",
        title="Nike ACG Jacket",
        price_raw="$120.00",
        currency_raw=None,
        brand_raw="Nike",
        size_raw="M",
        condition_raw="Good",
        seller_username_raw="seller1",
        image_url_raw="https://static.mercdn.net/photo.jpg",
        listing_url_raw="https://www.mercari.com/item/m12345/",
        created_at_raw=1755417161,
    )
    normalized = normalize_listing(raw)
    assert normalized.external_id == "m12345"
    assert normalized.price == 120.0
    assert normalized.currency == "USD"
    assert normalized.brand == "Nike"
    assert normalized.created_at_source is not None


def test_normalize_listing_never_invents_url_falls_back_to_canonical_pattern():
    raw = RawListing(external_id="m99999", title="No URL provided")
    normalized = normalize_listing(raw)
    assert normalized.listing_url == "https://www.mercari.com/item/m99999/"


def test_normalize_listing_never_invents_created_at_source():
    raw = RawListing(external_id="m1", title="No timestamp available")
    normalized = normalize_listing(raw)
    assert normalized.created_at_source is None
