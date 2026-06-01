"""Tests for the I Heart Jane adapter's pure parser + pipeline hand-off.

These exercise the network-free path only: load a trimmed Jane Algolia
``hits`` payload from a fixture (shaped exactly like a live
``menu-products-production`` response), parse it into ``MenuItem`` dicts via
:func:`parse_menu`, and confirm a normalized deal comes out the other side. No
real Jane / Algolia calls are made.
"""

from __future__ import annotations

import json
from pathlib import Path

from app.adapters.jane import parse_menu, store_ref_from_menu_url
from app.pipeline.normalize import normalize_item

_FIXTURE = Path(__file__).parent / "fixtures" / "jane_menu.json"


def _load_fixture() -> dict:
    with open(_FIXTURE, "r", encoding="utf-8") as fh:
        return json.load(fh)


def test_parse_menu_basic_shape():
    items = parse_menu(_load_fixture())
    # 2 flower + 1 vape all parse (none are outside our 5 cats).
    assert len(items) == 3
    cats = {it["category"] for it in items}
    assert cats == {"Flower", "Vapes"}

    # Every product must carry an image + url + usable prices — the UI/bot contract.
    for it in items:
        assert isinstance(it.get("img"), str) and it["img"].startswith("http")
        assert isinstance(it.get("url"), str) and it["url"].startswith("http")
        assert it["orig"] is not None and it["sale"] is not None
        assert it["sale"] <= it["orig"]


def test_parse_menu_field_mapping():
    items = parse_menu(_load_fixture())

    alien = next(it for it in items if it["brand"] == "Alien Labs")
    assert alien["category"] == "Flower"
    assert alien["orig"] == 60.0
    assert alien["sale"] == 45.0  # discounted_price_eighth_ounce
    assert alien["size"] == "3.5g"  # eighth_ounce -> 3.5g
    assert alien["type"] == "Hybrid"
    assert alien["thc"] == 31.4

    gs = next(it for it in items if it["brand"] == "Grow Sciences")
    assert gs["orig"] == 50.0
    assert gs["sale"] == 50.0  # no discount -> sale falls back to regular price
    assert gs["size"] == "3.5g"
    assert gs["type"] == "Indica"


def test_product_url_store_scoped_and_global():
    data = _load_fixture()

    # With store context -> store-scoped deep link with product_id.
    scoped = parse_menu(data, store_id="1507", slug="cannacruz-santa-cruz")
    alien = next(it for it in scoped if it["brand"] == "Alien Labs")
    assert "/stores/1507/cannacruz-santa-cruz/menu" in alien["url"]
    assert "product_id=2700101" in alien["url"]

    # Without store context -> global product page derived purely from the hit.
    glob = parse_menu(data)
    alien2 = next(it for it in glob if it["brand"] == "Alien Labs")
    assert alien2["url"] == "https://www.iheartjane.com/products/2700101/alien-labs-atomic-apple"


def test_normalize_item_produces_valid_deal():
    items = parse_menu(_load_fixture())
    alien = next(it for it in items if it["brand"] == "Alien Labs")

    deal = normalize_item(alien, shop="CannaCruz - Santa Cruz")
    assert deal is not None
    assert deal["brand"] == "Alien Labs"  # canonical
    assert deal["shop"] == "CannaCruz - Santa Cruz"
    assert deal["cat"] == "Flower"
    assert deal["orig"] == 60.0
    assert deal["sale"] == 45.0
    assert deal["off"] == 25  # round((60-45)/60*100)
    assert deal["unitLabel"] == "/g"
    assert deal["unit"] == 12.9  # round(45 / 3.5, 1)
    assert deal["tier"] == "S"  # Alien Labs tier from the allowlist
    assert deal["img"] and deal["img"].startswith("http")
    assert deal["url"] and deal["url"].startswith("http")


def test_non_allowlisted_brand_dropped():
    items = parse_menu(_load_fixture())
    # 8-BIT parses fine (real Jane vape) but isn't allowlisted -> normalize drops it.
    eight_bit = next(it for it in items if it["brand"] == "8-BIT")
    assert eight_bit["category"] == "Vapes"
    assert normalize_item(eight_bit, shop="CannaCruz - Santa Cruz") is None


def test_store_ref_from_menu_url():
    assert store_ref_from_menu_url(
        "https://www.iheartjane.com/stores/1507/cannacruz-santa-cruz/menu"
    ) == ("1507", "cannacruz-santa-cruz")
    assert store_ref_from_menu_url("https://www.iheartjane.com/embed/menu/1201") == (
        "1201",
        None,
    )
    sid, slug = store_ref_from_menu_url("https://shop.example.com/?store_id=937")
    assert sid == "937"


def test_parse_menu_tolerates_envelopes_and_empty():
    full = _load_fixture()
    hits = full["hits"]
    # Bare list of hits, and an Algolia multi-index envelope.
    assert len(parse_menu(hits)) == 3
    assert len(parse_menu({"results": [{"hits": hits}]})) == 3
    assert parse_menu({}) == []
    assert parse_menu(None) == []
