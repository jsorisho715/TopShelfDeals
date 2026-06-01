"""Tests for the Dutchie adapter's pure parser + pipeline hand-off.

These exercise the network-free path only: load a captured ``FilteredProducts``
GraphQL response from a fixture, parse it into ``MenuItem`` dicts, and confirm a
normalized deal comes out the other side. No real Dutchie calls are made (the
live endpoint may be Cloudflare-gated / slow).
"""

from __future__ import annotations

import json
from pathlib import Path

from app.adapters.dutchie import parse_filtered_products, slug_from_menu_url
from app.pipeline.normalize import normalize_item

_FIXTURE = Path(__file__).parent / "fixtures" / "dutchie_filtered_products.json"


def _load_fixture() -> dict:
    with open(_FIXTURE, "r", encoding="utf-8") as fh:
        return json.load(fh)


def test_slug_from_menu_url():
    assert (
        slug_from_menu_url("https://dutchie.com/dispensary/the-mint-cannabis-tempe")
        == "the-mint-cannabis-tempe"
    )
    assert (
        slug_from_menu_url("https://dutchie.com/dispensary/sunday-goods-scottsdale/")
        == "sunday-goods-scottsdale"
    )
    assert slug_from_menu_url("") is None


def test_parse_filtered_products_basic_shape():
    items = parse_filtered_products(_load_fixture())
    # Fixture has 3 products; all should parse.
    assert len(items) == 3

    # At least one fully-priced item with an image (the contract for the UI/bot).
    priced = [
        it
        for it in items
        if it.get("orig") is not None
        and it.get("sale") is not None
        and it.get("img")
    ]
    assert len(priced) >= 1

    stiiizy = next(it for it in items if it["product"].startswith("Blue Burst"))
    assert stiiizy["brand"] == "STIIIZY"
    assert stiiizy["category"] == "Vapes"
    assert stiiizy["orig"] == 40.0
    assert stiiizy["sale"] == 30.0  # special price applied
    assert stiiizy["size"] == "1g"
    assert stiiizy["type"] == "Hybrid"
    assert stiiizy["thc"] == 87.1  # high end of the potency range
    assert stiiizy["img"].endswith("stiiizy-blue-burst-1g.jpg")


def test_no_special_falls_back_to_standard_price():
    items = parse_filtered_products(_load_fixture())
    flower = next(it for it in items if it["product"].startswith("House Blend"))
    # Empty specialPrices -> sale should equal the standard price.
    assert flower["orig"] == 45.0
    assert flower["sale"] == 45.0


def test_normalize_item_produces_valid_deal():
    items = parse_filtered_products(_load_fixture())
    stiiizy = next(it for it in items if it["brand"] == "STIIIZY")

    deal = normalize_item(stiiizy, shop="The Mint")
    assert deal is not None
    assert deal["brand"] == "STIIIZY"  # canonical
    assert deal["shop"] == "The Mint"
    assert deal["cat"] == "Vapes"
    assert deal["orig"] == 40.0
    assert deal["sale"] == 30.0
    assert deal["off"] == 25  # round((40-30)/40*100)
    assert deal["unit"] == 30.0  # $/g at 1g
    assert deal["unitLabel"] == "/g"
    assert deal["img"].endswith("stiiizy-blue-burst-1g.jpg")
    assert deal["tier"] == "A"  # STIIIZY tier from the allowlist


def test_allowlisted_alias_resolves():
    items = parse_filtered_products(_load_fixture())
    jeeter = next(it for it in items if "Jeeter" in it["product"])
    assert jeeter["category"] == "Prerolls"
    deal = normalize_item(jeeter, shop="Story Cannabis")
    # "Baby Jeeter" is an allowlisted alias of canonical "Jeeter".
    assert deal is not None
    assert deal["brand"] == "Jeeter"


def test_non_allowlisted_brand_is_dropped():
    items = parse_filtered_products(_load_fixture())
    generic = next(it for it in items if it["brand"].startswith("Generic"))
    # Intentionally not on the allowlist -> normalize returns None.
    assert normalize_item(generic, shop="The Mint") is None
