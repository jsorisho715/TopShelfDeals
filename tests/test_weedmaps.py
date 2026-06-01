"""Tests for the Weedmaps adapter's pure parser + pipeline hand-off.

These exercise the network-free path only: load a trimmed, REAL Weedmaps
``menu_items`` payload from a fixture (captured live from a Scottsdale-area Sol
Flower menu) and confirm it parses into ``MenuItem`` dicts via :func:`parse_menu`
and that a normalized deal comes out the other side. No real Weedmaps calls are
made (the live endpoint is Akamai-gated and needs a browser).

The fixture deliberately captures Weedmaps' schema quirks: the real brand lives
in ``brand_endorsement.brand_name`` (top-level ``brand`` is null), the product
category is the ``edge_category`` taxonomy node (``Big Buds`` → ``Flower``), and
the priced weight comes from ``price.compliance_net_mg`` (3500 → 3.5g).
"""

from __future__ import annotations

import json
from pathlib import Path

from app.adapters.weedmaps import parse_menu, slug_from_menu_url
from app.pipeline.normalize import normalize_item

_FIXTURE = Path(__file__).parent / "fixtures" / "weedmaps_menu.json"


def _load_fixture() -> dict:
    with open(_FIXTURE, "r", encoding="utf-8") as fh:
        return json.load(fh)


def test_slug_from_menu_url():
    assert slug_from_menu_url("https://weedmaps.com/dispensaries/sol-flower-1/menu") == "sol-flower-1"
    assert slug_from_menu_url("https://weedmaps.com/dispensaries/the-mint-cannabis-scottsdale") == "the-mint-cannabis-scottsdale"
    assert slug_from_menu_url("https://weedmaps.com/dispensaries/jars-cannabis-9/deals") == "jars-cannabis-9"
    assert slug_from_menu_url("") is None


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

    # Brand resolves from brand_endorsement (top-level `brand` is null).
    alien = next(it for it in items if it["brand"] == "Alien Labs")
    assert alien["category"] == "Flower"  # mapped from edge_category Big Buds -> Flower
    assert alien["orig"] == 50.0
    assert alien["sale"] == 50.0  # not on sale -> sale == standard price
    # Priced weight from compliance_net_mg (1/8 = 3.5g), not the "10g" in the name.
    assert alien["size"] == "3.5g"
    assert alien["type"] == "Indica"  # from the `category` strain-type field
    assert alien["thc"] == 25.23
    assert alien["img"].startswith("https://images.weedmaps.com/products/")

    # On-sale item: orig is the original_price, sale is the discounted price.
    pg = next(it for it in items if it["brand"] == "Preferred Gardens")
    assert pg["orig"] == 45.0
    assert pg["sale"] == 30.0


def test_normalize_item_produces_valid_deal():
    items = parse_menu(_load_fixture())
    alien = next(it for it in items if it["brand"] == "Alien Labs")

    deal = normalize_item(alien, shop="Sol Flower")
    assert deal is not None
    assert deal["brand"] == "Alien Labs"  # canonical
    assert deal["shop"] == "Sol Flower"
    assert deal["cat"] == "Flower"
    assert deal["orig"] == 50.0
    assert deal["sale"] == 50.0
    assert deal["off"] == 0  # not on sale
    assert deal["unitLabel"] == "/g"
    assert deal["unit"] == 14.3  # round(50 / 3.5, 1)
    assert deal["tier"] == "S"  # Alien Labs tier from the allowlist
    assert deal["img"] and deal["img"].startswith("http")


def test_on_sale_item_normalizes_with_discount():
    # Preferred Gardens is on sale in the fixture; if it were allowlisted the
    # discount math would flow through. It is NOT allowlisted, so it is dropped —
    # which also exercises the brand-allowlist gate (below). Here we just confirm
    # the raw parse captured the discount.
    items = parse_menu(_load_fixture())
    pg = next(it for it in items if it["brand"] == "Preferred Gardens")
    assert pg["sale"] < pg["orig"]


def test_allowlisted_brand_resolves_to_canonical():
    items = parse_menu(_load_fixture())
    wizard = next(it for it in items if it["brand"] == "Wizard Trees")
    deal = normalize_item(wizard, shop="Sol Flower")
    assert deal is not None
    assert deal["brand"] == "Wizard Trees"
    assert deal["tier"] == "S"


def test_non_allowlisted_brand_is_dropped():
    items = parse_menu(_load_fixture())
    pg = next(it for it in items if it["brand"] == "Preferred Gardens")
    # Preferred Gardens is intentionally not on the allowlist -> normalize drops.
    assert normalize_item(pg, shop="Sol Flower") is None


def test_parse_menu_tolerates_bare_data_and_list():
    full = _load_fixture()
    bare_data = full["data"]
    raw_list = bare_data["menu_items"]
    assert len(parse_menu(bare_data)) == 3
    assert len(parse_menu(raw_list)) == 3
    assert parse_menu({}) == []
    assert parse_menu(None) == []
