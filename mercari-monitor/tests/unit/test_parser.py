import json
from pathlib import Path

from app.mercari.parser import parse_listing_card_dom, parse_search_api_payload

FIXTURES = Path(__file__).resolve().parent.parent / "fixtures"


def _load(name: str) -> dict:
    return json.loads((FIXTURES / name).read_text())


def test_parse_search_api_payload_extracts_all_listings():
    payload = _load("mercari_search_response.json")
    listings = parse_search_api_payload(payload)
    assert len(listings) == 3
    assert [listing.external_id for listing in listings] == [
        "m12345678901",
        "m22222222222",
        "m33333333333",
    ]


def test_parse_search_api_payload_full_fields():
    payload = _load("mercari_search_response.json")
    listing = parse_search_api_payload(payload)[0]

    assert listing.title == "Nike ACG Jacket - Size M - Excellent Condition"
    assert listing.price_raw == 120
    assert listing.currency_raw == "USD"
    assert listing.brand_raw == "Nike"
    assert listing.category_raw == "Men's Jackets"
    assert listing.size_raw == "M"
    assert listing.condition_raw == "Good"
    assert listing.item_status_raw == "for_sale"
    assert listing.seller_username_raw == "gearhead_99"
    assert listing.seller_id_raw == "u123"
    assert listing.image_url_raw == "https://static.mercdn.net/item/photo1.jpg"
    assert listing.listing_url_raw == "https://www.mercari.com/item/m12345678901/"
    assert listing.created_at_raw == 1755417161
    assert listing.source == "api"


def test_parse_search_api_payload_handles_formatted_price_string():
    payload = _load("mercari_search_response.json")
    listing = parse_search_api_payload(payload)[1]
    assert listing.price_raw == "$85.00"
    assert listing.brand_raw == "Nike"
    assert listing.size_raw == "L"
    # No explicit currency on this entry -> extractor must not invent one.
    assert listing.currency_raw is None


def test_parse_search_api_payload_tolerates_minimal_listing():
    """A listing with almost nothing but id + title must still parse
    without raising — every other field is optional (spec section 18)."""
    payload = _load("mercari_search_response.json")
    listing = parse_search_api_payload(payload)[2]
    assert listing.external_id == "m33333333333"
    assert listing.price_raw is None
    assert listing.brand_raw is None
    assert listing.seller_username_raw is None
    assert listing.image_url_raw is None


def test_parse_search_api_payload_skips_listing_without_id_but_keeps_others():
    payload = {
        "data": [
            {"name": "No id here, must be skipped"},
            {"id": "m99999999999", "name": "Has an id, must survive"},
        ]
    }
    listings = parse_search_api_payload(payload)
    assert len(listings) == 1
    assert listings[0].external_id == "m99999999999"


def test_parse_search_api_payload_unknown_shape_returns_empty_not_raise():
    listings = parse_search_api_payload({"somethingElse": []})
    assert listings == []


def test_parse_listing_card_dom_extracts_id_from_href():
    cards = _load("mercari_dom_cards.json")["cards"]
    listing = parse_listing_card_dom(cards[0])
    assert listing is not None
    assert listing.external_id == "m44444444444"
    assert listing.title == "Nike ACG Trail Running Shoes"
    assert listing.price_raw == "$95"
    assert listing.source == "dom"
    assert listing.listing_url_raw == "https://www.mercari.com/item/m44444444444/"


def test_parse_listing_card_dom_handles_absolute_href_and_missing_title():
    cards = _load("mercari_dom_cards.json")["cards"]
    listing = parse_listing_card_dom(cards[1])
    assert listing is not None
    assert listing.external_id == "m55555555555"
    assert listing.title is None
    assert listing.listing_url_raw == "https://www.mercari.com/item/m55555555555/"


def test_parse_listing_card_dom_rejects_non_item_link():
    cards = _load("mercari_dom_cards.json")["cards"]
    listing = parse_listing_card_dom(cards[2])
    assert listing is None
