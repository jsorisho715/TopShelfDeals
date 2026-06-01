"""Tests for cross-source product dedup + cross-platform store merge."""
from app.pipeline.dedup import dedup, build_store_groups


def test_collapses_same_product_same_shop_keeping_lowest_price_and_richest():
    deals = [
        {"product": "Blue  Dream ", "shop": "The Mint", "brand": "Alien Labs", "sale": 40, "img": None, "thc": 28},
        {"product": "blue dream", "shop": "The Mint", "brand": "Alien Labs", "sale": 32, "img": "http://x/y.jpg"},
    ]
    out = dedup(deals)
    assert len(out) == 1
    d = out[0]
    assert d["sale"] == 32                 # lowest price wins as base
    assert d["img"] == "http://x/y.jpg"    # richer metadata merged in
    assert d["thc"] == 28                  # filled from the other record


def test_keeps_distinct_strains_and_distinct_shops():
    deals = [
        {"product": "Cinco Infused 5pk - Bubba Berry", "shop": "The Mint", "brand": "WTF Extracts", "sale": 25},
        {"product": "Cinco Infused 5pk - GG4", "shop": "The Mint", "brand": "WTF Extracts", "sale": 25},
        {"product": "Marionberry Gummies", "shop": "The Mint", "brand": "Wyld", "sale": 30},
        {"product": "Marionberry Gummies", "shop": "The Mint Scottsdale", "brand": "Wyld", "sale": 30},
    ]
    out = dedup(deals)
    # different strains stay separate; same product at two different shops stays separate
    assert len(out) == 4


# ---------------------------------------------------------------------------
# Cross-platform store MERGE (same physical store, different names/platforms)
# ---------------------------------------------------------------------------
def test_cross_platform_merge_same_store_same_product():
    deals = [
        {"product": "Atomic Apple", "shop": "The Mint", "brand": "Alien Labs",
         "sale": 38, "platform": "Dutchie", "img": None, "thc": 31},
        {"product": "Atomic Apple", "shop": "The Mint Cannabis - Scottsdale", "brand": "Alien Labs",
         "sale": 34, "platform": "Leafly", "img": "http://x/y.jpg"},
    ]
    # Both names geocode to (nearly) the same coords -> same canonical store key.
    groups = build_store_groups({
        "The Mint": (33.49291, -111.91706),
        "The Mint Cannabis - Scottsdale": (33.49293, -111.91704),
    })
    out = dedup(deals, store_groups=groups)
    assert len(out) == 1
    d = out[0]
    assert d["sale"] == 34                         # lowest price wins
    assert d["img"] == "http://x/y.jpg"            # richer metadata merged
    assert d["thc"] == 31                          # filled from the other record
    assert set(d["platforms"]) == {"Dutchie", "Leafly"}  # union of sources
    assert d["shop"]                               # single canonical shop name
    assert isinstance(d["shop"], str)


def test_cross_platform_keeps_distinct_products_at_merged_store():
    deals = [
        {"product": "Atomic Apple", "shop": "The Mint", "brand": "Alien Labs", "sale": 38, "platform": "Dutchie"},
        {"product": "Biskante", "shop": "The Mint Cannabis - Scottsdale", "brand": "Alien Labs", "sale": 40, "platform": "Leafly"},
    ]
    groups = build_store_groups({
        "The Mint": (33.49291, -111.91706),
        "The Mint Cannabis - Scottsdale": (33.49293, -111.91704),
    })
    out = dedup(deals, store_groups=groups)
    # Same store, but two different products -> stay separate.
    assert len(out) == 2


def test_different_stores_not_merged_even_with_same_product():
    deals = [
        {"product": "Atomic Apple", "shop": "The Mint", "brand": "Alien Labs", "sale": 38, "platform": "Dutchie"},
        {"product": "Atomic Apple", "shop": "Curaleaf - Scottsdale", "brand": "Alien Labs", "sale": 40, "platform": "Leafly"},
    ]
    # Far-apart coords -> distinct canonical keys.
    groups = build_store_groups({
        "The Mint": (33.49291, -111.91706),
        "Curaleaf - Scottsdale": (33.62000, -111.90000),
    })
    out = dedup(deals, store_groups=groups)
    assert len(out) == 2


def test_build_store_groups_clusters_by_rounded_coords():
    groups = build_store_groups({
        "A": (33.49291, -111.91706),
        "B": (33.49299, -111.91699),   # rounds to same cell as A at precision=3
        "C": (33.60000, -112.00000),   # different cell
    })
    assert groups["A"] == groups["B"]
    assert groups["C"] != groups["A"]


def test_dedup_without_store_groups_unchanged():
    # Same product, two distinct shop names, no store_groups -> stays separate.
    deals = [
        {"product": "Atomic Apple", "shop": "The Mint", "brand": "Alien Labs", "sale": 38, "platform": "Dutchie"},
        {"product": "Atomic Apple", "shop": "The Mint Cannabis - Scottsdale", "brand": "Alien Labs", "sale": 34, "platform": "Leafly"},
    ]
    out = dedup(deals)
    assert len(out) == 2
