"""Tests for the Leafly adapter's pure parser + pipeline hand-off.

These exercise the network-free path only: load a trimmed, REAL Leafly
``__NEXT_DATA__`` payload from a fixture (3 allowlisted flower products captured
live from Scottsdale-area menus), parse it into ``MenuItem`` dicts via
:func:`parse_menu`, and confirm a normalized deal comes out the other side. No
real Leafly calls are made.
"""

from __future__ import annotations

import json
from pathlib import Path

from app.adapters.leafly import parse_menu
from app.pipeline.normalize import normalize_item

_FIXTURE = Path(__file__).parent / "fixtures" / "leafly_menu.json"


def _load_fixture() -> dict:
    with open(_FIXTURE, "r", encoding="utf-8") as fh:
        return json.load(fh)


def test_parse_menu_basic_shape():
    items = parse_menu(_load_fixture())
    # Fixture has 3 flower products; all should parse.
    assert len(items) == 3
    assert all(it["category"] == "Flower" for it in items)

    # Every product must carry an image + usable prices — the UI/bot contract.
    priced_with_img = [
        it
        for it in items
        if it.get("img")
        and it.get("orig") is not None
        and it.get("sale") is not None
    ]
    assert len(priced_with_img) == 3
    for it in priced_with_img:
        assert isinstance(it["img"], str) and it["img"].startswith("http")
        assert it["sale"] <= it["orig"]


def test_parse_menu_field_mapping():
    items = parse_menu(_load_fixture())

    red = next(it for it in items if it["brand"] == "22Red")
    assert red["category"] == "Flower"
    assert red["orig"] == 35.0
    assert red["sale"] == 35.0  # no deal -> sale falls back to standard price
    assert red["size"] == "3.5g"
    assert red["type"] == "Sativa"  # parsed from the "(S)" token in the name
    assert red["thc"] == 26.07

    gs = next(it for it in items if it["brand"] == "Grow Sciences")
    # Deal applied: standard 50, effective 30 (sortPrice / variant discountedPrice).
    assert gs["orig"] == 50.0
    assert gs["sale"] == 30.0
    # Weight comes from displayQuantity when the name has no "(3.7g)" token.
    assert gs["size"] == "3.7g"


def test_normalize_item_produces_valid_deal():
    items = parse_menu(_load_fixture())
    gs = next(it for it in items if it["brand"] == "Grow Sciences")

    deal = normalize_item(gs, shop="JARS Cannabis - Phoenix/Arcadia")
    assert deal is not None
    assert deal["brand"] == "Grow Sciences"  # canonical
    assert deal["shop"] == "JARS Cannabis - Phoenix/Arcadia"
    assert deal["cat"] == "Flower"
    assert deal["orig"] == 50.0
    assert deal["sale"] == 30.0
    assert deal["off"] == 40  # round((50-30)/50*100)
    assert deal["unitLabel"] == "/g"
    assert deal["unit"] == 8.1  # round(30 / 3.7, 1)
    assert deal["tier"] == "S"  # Grow Sciences tier from the allowlist
    assert deal["img"] and deal["img"].startswith("http")


def test_allowlisted_alias_resolves():
    items = parse_menu(_load_fixture())
    # "Mohave Cannabis Co." is an allowlisted alias of canonical "Mohave".
    mohave = next(it for it in items if it["brand"] == "Mohave Cannabis Co.")
    deal = normalize_item(mohave, shop="JARS Cannabis - Phoenix/Arcadia")
    assert deal is not None
    assert deal["brand"] == "Mohave"


def test_non_canonical_categories_and_brands_dropped():
    # Accessories / topicals are skipped by the parser; non-allowlisted brands
    # are dropped by normalize_item.
    payload = {
        "props": {
            "pageProps": {
                "menuData": {
                    "menuItems": [
                        {
                            "id": 1,
                            "name": "Generic House Battery 510",
                            "brandName": "House Hardware",
                            "productCategory": "Accessory",
                            "price": 15,
                            "sortPrice": 15,
                            "imageUrl": "https://example.com/a.jpg",
                        },
                        {
                            "id": 2,
                            "name": "Bulk Smalls (I) (28g)",
                            "brandName": "No Name Greenhouse",
                            "productCategory": "Flower",
                            "price": 60,
                            "sortPrice": 60,
                            "imageUrl": "https://example.com/b.jpg",
                        },
                    ]
                }
            }
        }
    }
    items = parse_menu(payload)
    # Accessory dropped at parse time; only the flower row survives.
    assert len(items) == 1
    assert items[0]["category"] == "Flower"
    # ...but its brand isn't allowlisted, so normalize drops it.
    assert normalize_item(items[0], shop="Test") is None


def test_parse_menu_tolerates_bare_menudata_and_list():
    full = _load_fixture()
    bare_menu_data = full["props"]["pageProps"]["menuData"]
    raw_list = bare_menu_data["menuItems"]
    assert len(parse_menu(bare_menu_data)) == 3
    assert len(parse_menu(raw_list)) == 3
    assert parse_menu({}) == []
    assert parse_menu(None) == []
