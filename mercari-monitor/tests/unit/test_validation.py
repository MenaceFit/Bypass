"""Unit tests for app/utils/validation.py."""

from __future__ import annotations

import pytest

from app.utils.validation import (
    ValidationError,
    clamp_page_size,
    join_terms,
    split_terms,
    validate_discord_webhook_url,
    validate_keyword,
    validate_price_range,
    validate_scan_interval,
)


def test_validate_keyword_strips_whitespace():
    assert validate_keyword("  Nike ACG  ") == "Nike ACG"


def test_validate_keyword_rejects_empty():
    with pytest.raises(ValidationError):
        validate_keyword("   ")


def test_validate_keyword_rejects_too_long():
    with pytest.raises(ValidationError):
        validate_keyword("x" * 201)


def test_validate_scan_interval_rejects_below_minimum():
    with pytest.raises(ValidationError):
        validate_scan_interval(1)  # below settings.min_scan_interval (3)


def test_validate_scan_interval_accepts_valid_value():
    assert validate_scan_interval(10) == 10


def test_validate_price_range_rejects_min_greater_than_max():
    with pytest.raises(ValidationError):
        validate_price_range(100, 10)


def test_validate_price_range_accepts_none_values():
    validate_price_range(None, None)
    validate_price_range(10, None)
    validate_price_range(None, 100)


def test_validate_price_range_rejects_negative():
    with pytest.raises(ValidationError):
        validate_price_range(-5, None)


def test_validate_discord_webhook_url_accepts_valid():
    url = "https://discord.com/api/webhooks/123456789/abcDEF-123_xyz"
    assert validate_discord_webhook_url(url) == url


@pytest.mark.parametrize(
    "bad_url",
    ["https://evil.com/webhooks/123/abc", "not a url", "https://discord.com/api/webhooks/abc/abc"],
)
def test_validate_discord_webhook_url_rejects_invalid(bad_url):
    with pytest.raises(ValidationError):
        validate_discord_webhook_url(bad_url)


def test_clamp_page_size_bounds():
    assert clamp_page_size(0) == 1
    assert clamp_page_size(10) == 10
    assert clamp_page_size(9999) <= 100


def test_split_and_join_terms_roundtrip():
    joined = join_terms(["Nike ACG", "  Jacket ", ""])
    assert joined == "Nike ACG, Jacket"
    assert split_terms(joined) == ["Nike ACG", "Jacket"]


def test_split_terms_handles_none_and_empty():
    assert split_terms(None) == []
    assert split_terms("") == []


def test_join_terms_handles_empty_list():
    assert join_terms([]) is None
    assert join_terms(None) is None
