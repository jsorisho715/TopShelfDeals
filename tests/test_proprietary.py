"""Tests for the proprietary (JointCommerce) adapter's pure parser + hand-off.

These exercise the network-free path only: load a trimmed, realistic JointCommerce
``_search`` Elasticsearch envelope (captured live from a Scottsdale-area Sol Flower
menu) and confirm it parses into ``MenuItem`` dicts via :func:`parse_menu` and that a
normalized deal comes out the other side. No real network calls are made.

The fixture deliberately captures the platform's quirks: products live at
``hits.hits[]._source``; the real category is the SHOUTY ``category`` (``FLOWER`` /
``EDIBLES`` / ``VAPORIZERS``); each product carries a ``variants`` list with
``option`` / ``price`` / ``specialPrice`` (a product expands to one item per
recreational variant); ounce options (``1/2oz``) are normalized to grams; and a
``TINCTURES`` row is included to confirm non-canonical categories are dropped.
"""

from __future__ import annotations

import json
from pathlib import Path

from app.adapters.proprietary import _host, _normalize_option, parse_menu
from app.pipeline.normalize import normalize_item

_FIXTURE = Path(__file__).parent / "fixtures" / "proprietary_menu.json"


def _load_fixture() -> dict:
    with open(_FIXTURE, "r", encoding="utf-8") as fh:
        return json.load(fh)


def test_host_extraction():
    assert _host("https://www.livewithsol.com/menu/") == "https://www.livewithsol.com"
    assert _host("https://yilo.com/categories/flower/") == "https://yilo.com"
    assert _host("") is None
    assert _host("not-a-url") is None


def test_normalize_option_oz_to_grams():
    assert _normalize_option("3.5g") == "3.5g"
    assert _normalize_option("100mg") == "100mg"
    assert _normalize_option("1/2oz") == "14g"
    assert _normalize_option("1/8oz") == "3.5g"
    assert _normalize_option("1oz") == "28g"
    assert _normalize_option(None) is None


def test_parse_menu_basic_shape():
    items = parse_menu(_load_fixture())
    # 4 source rows: flower (2 rec variants), edible (1), vape (1), tincture (dropped).
    cats = {it["category"] for it in items}
    assert "Flower" in cats and "Edibles" in cats and "Vapes" in cats
    # TINCTURES is not a canonical category -> dropped entirely.
    assert all(it["category"] in {"Flower", "Edibles", "Vapes"} for it in items)
    for it in items:
        assert it.get("orig") is not None and it.get("sale") is not None
        assert it["sale"] <= it["orig"]


def test_flower_expands_per_recreational_variant():
    items = parse_menu(_load_fixture())
    flower = [it for it in items if it["category"] == "Flower"]
    # Two RECREATIONAL variants (3.5g + 1/2oz); the MEDICAL twin is de-duped out.
    sizes = sorted(it["size"] for it in flower)
    assert sizes == ["14g", "3.5g"]
    eighth = next(it for it in flower if it["size"] == "3.5g")
    assert eighth["brand"] == "Alien Labs"
    assert eighth["orig"] == 60.0
    assert eighth["sale"] == 38.0  # specialPrice applied
    assert eighth["type"] == "Indica"
    assert eighth["thc"] == 31.40
    assert eighth["img"].startswith("https://images.dutchie.com/")
    assert eighth["effects"] == ["Happy", "Relaxed", "Sleepy"]  # title-cased


def test_edible_special_pricing():
    items = parse_menu(_load_fixture())
    gummy = next(it for it in items if it["category"] == "Edibles")
    assert gummy["brand"] == "CAM"
    assert gummy["orig"] == 30.0
    assert gummy["sale"] == 10.0
    assert gummy["size"] == "100mg"


def test_normalize_item_produces_valid_deal():
    items = parse_menu(_load_fixture())
    eighth = next(
        it for it in items if it["category"] == "Flower" and it["size"] == "3.5g"
    )
    deal = normalize_item(eighth, shop="Sol Flower - Scottsdale Airpark")
    assert deal is not None
    assert deal["brand"] == "Alien Labs"  # canonical, allowlisted
    assert deal["cat"] == "Flower"
    assert deal["orig"] == 60.0
    assert deal["sale"] == 38.0
    assert deal["off"] == 37  # round((60-38)/60*100)
    assert deal["unitLabel"] == "/g"
    assert deal["unit"] == 10.9  # round(38 / 3.5, 1)
    assert deal["tier"] == "S"


def test_edible_normalizes_to_per_10mg_unit():
    items = parse_menu(_load_fixture())
    gummy = next(it for it in items if it["category"] == "Edibles")
    deal = normalize_item(gummy, shop="Sol Flower - Scottsdale Airpark")
    assert deal is not None
    assert deal["unitLabel"] == "/10mg"
    assert deal["unit"] == 1.0  # round(10 / (100/10), 1)
    assert deal["off"] == 67  # round((30-10)/30*100)


def test_parse_menu_tolerates_bare_hits_and_list():
    full = _load_fixture()
    bare_hits = {"hits": {"hits": full["hits"]["hits"]}}
    raw_list = full["hits"]["hits"]
    assert len(parse_menu(bare_hits)) == len(parse_menu(full))
    assert len(parse_menu(raw_list)) == len(parse_menu(full))
    assert parse_menu({}) == []
    assert parse_menu(None) == []


def test_fetch_without_business_id_returns_empty():
    from app.adapters.proprietary import ProprietaryAdapter

    ad = ProprietaryAdapter()
    # No business_id -> cannot query -> [] (never raises).
    assert ad.fetch({"name": "x", "menu": "https://www.livewithsol.com/menu/"}) == []
    # No menu host -> [].
    assert ad.fetch({"name": "x", "business_id": "5797"}) == []
