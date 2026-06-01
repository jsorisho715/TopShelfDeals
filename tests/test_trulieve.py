"""Tests for the Trulieve adapter's pure parser + pipeline hand-off.

These exercise the network-free path only: load a trimmed, REAL Trulieve menu
payload from a fixture and confirm a normalized deal comes out the other side.
No real Trulieve/Dutchie calls are made.

Trulieve's Arizona menus are served by an embedded **Dutchie** storefront (the
stores trade under **Harvest** cNames, e.g. ``harvest-of-scottsdale`` — Trulieve
owns Harvest). The fixture is the Dutchie ``filteredProducts`` GraphQL body that a
bounded Playwright render captures off the live storefront, wrapped with the
``storeCName`` the adapter injects so per-product deep links resolve purely.
"""

from __future__ import annotations

import json
from pathlib import Path

from app.adapters.trulieve import parse_menu
from app.pipeline.normalize import normalize_item

_FIXTURE = Path(__file__).parent / "fixtures" / "trulieve_menu.json"


def _load_fixture() -> dict:
    with open(_FIXTURE, "r", encoding="utf-8") as fh:
        return json.load(fh)


def test_parse_menu_basic_shape():
    items = parse_menu(_load_fixture())
    # Fixture has 3 concentrate products; all should parse.
    assert len(items) == 3
    assert all(it["category"] == "Concentrates" for it in items)

    # At least one fully-priced item carrying an image + a per-product deep link
    # (the contract for the UI / bot).
    priced_with_img = [
        it
        for it in items
        if it.get("img")
        and it.get("orig") is not None
        and it.get("sale") is not None
        and it.get("url")
    ]
    assert len(priced_with_img) >= 1
    for it in priced_with_img:
        assert isinstance(it["img"], str) and it["img"].startswith("http")
        assert it["sale"] <= it["orig"]
        # Deep link points at the embedded Dutchie product page.
        assert it["url"].startswith("https://dutchie.com/dispensary/harvest-of-scottsdale/product/")


def test_parse_menu_field_mapping():
    items = parse_menu(_load_fixture())

    gs = next(it for it in items if it["brand"] == "Grow Sciences")
    assert gs["category"] == "Concentrates"
    assert gs["orig"] == 39.0
    assert gs["sale"] == 27.3  # rec special price applied
    assert gs["size"] == "1g"
    assert gs["type"] == "Hybrid"
    assert gs["thc"] == 74.56  # high end of the potency range
    assert gs["img"].endswith("7f8726388aa1da94c13cc2b810f12b59")
    assert gs["url"].endswith("/product/topanga-x-mike-larry-live-resin-badder-11894")
    assert gs["in_stock"] is True


def test_no_special_falls_back_to_standard_price():
    items = parse_menu(_load_fixture())
    monet = next(it for it in items if it["product"].startswith("Monet"))
    # Empty recSpecialPrices -> sale should equal the standard price.
    assert monet["orig"] == 36.0
    assert monet["sale"] == 36.0


def test_normalize_item_produces_valid_deal():
    items = parse_menu(_load_fixture())
    gs = next(it for it in items if it["brand"] == "Grow Sciences")

    deal = normalize_item(gs, shop="Trulieve - Scottsdale")
    assert deal is not None
    assert deal["brand"] == "Grow Sciences"  # canonical
    assert deal["shop"] == "Trulieve - Scottsdale"
    assert deal["cat"] == "Concentrates"
    assert deal["orig"] == 39.0
    assert deal["sale"] == 27.3
    assert deal["off"] == 30  # round((39 - 27.3) / 39 * 100)
    assert deal["unit"] == 27.3  # $/g at 1g
    assert deal["unitLabel"] == "/g"
    assert deal["tier"] == "S"  # Grow Sciences tier from the allowlist
    assert deal["img"] and deal["img"].startswith("http")
    assert deal["url"].endswith("/product/topanga-x-mike-larry-live-resin-badder-11894")


def test_allowlisted_alias_resolves():
    items = parse_menu(_load_fixture())
    # "drip" is an allowlisted alias of canonical "Drip".
    drip = next(it for it in items if it["brand"] == "drip")
    deal = normalize_item(drip, shop="Trulieve - Scottsdale")
    assert deal is not None
    assert deal["brand"] == "Drip"


def test_non_allowlisted_brand_is_dropped():
    items = parse_menu(_load_fixture())
    # Take a real parsed item and force a brand that is NOT on the allowlist;
    # normalize must drop it (the brand-allowlist gate). Using a synthetic brand
    # keeps this independent of which fixture brands happen to be allowlisted.
    item = dict(items[0])
    item["brand"] = "Totally Not A Real Allowlisted Brand"
    assert normalize_item(item, shop="Trulieve - Scottsdale") is None


def test_parse_menu_tolerates_bare_list_and_envelopes():
    full = _load_fixture()
    products = full["data"]["filteredProducts"]["products"]
    # Bare product list and a bare ``{filteredProducts: {...}}`` envelope both work.
    assert len(parse_menu(products)) == 3
    assert len(parse_menu({"filteredProducts": {"products": products}})) == 3
    # Without a storeCName the parser still works; url is just absent.
    bare = parse_menu(products)
    assert all(it.get("url") is None for it in bare)
    # Empty / junk inputs never raise.
    assert parse_menu({}) == []
    assert parse_menu(None) == []
    assert parse_menu([]) == []
