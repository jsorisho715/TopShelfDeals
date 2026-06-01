"""Tests for the bot's free-text query parser (``app.bot.queries.parse_query``)."""
from app.bot.queries import describe_query, parse_query

# Small, deterministic fixture covering the facets parse_query detects.
DEALS = [
    {
        "id": "a", "cat": "Flower", "product": "Atomic Apple", "brand": "Alien Labs",
        "type": "Hybrid", "thc": 31.4, "shop": "Sol Flower", "area": "Scottsdale",
        "sale": 38, "unit": 10.9, "unitLabel": "/g", "off": 37, "fire": True, "score": 96,
    },
    {
        "id": "b", "cat": "Flower", "product": "Banana OG", "brand": "Grow Sciences",
        "type": "Indica", "thc": 29.7, "shop": "TruMed", "area": "Phoenix",
        "sale": 45, "unit": 12.9, "unitLabel": "/g", "off": 31, "fire": False, "score": 90,
    },
    {
        "id": "c", "cat": "Flower", "product": "Frosted Cake", "brand": "Aeriz",
        "type": "Indica", "thc": 22.0, "shop": "Sunday Goods", "area": "Scottsdale",
        "sale": 30, "unit": 8.6, "unitLabel": "/g", "off": 0, "fire": False, "score": 89,
    },
    {
        "id": "d", "cat": "Edibles", "product": "Sour Apple Gummies", "brand": "Wyld",
        "type": "Sativa", "thc": 100, "shop": "Sunday Goods", "area": "Scottsdale",
        "sale": 15, "unit": 1.5, "unitLabel": "/10mg", "off": 40, "fire": True, "score": 95,
    },
]


def _ids(rows):
    return {r["id"] for r in rows}


def test_strain_filters_type():
    p = parse_query("indica flower", DEALS)
    assert p["type"] == "Indica"
    assert p["cat"] == "Flower"
    assert _ids(p["rows"]) == {"b", "c"}


def test_min_thc_variants():
    for q in ("over 25% thc", "25%+ thc", ">25 thc", "25% thc"):
        p = parse_query(q, DEALS)
        assert p["minThc"] == 25.0, q
        # All flower at/above 25% THC plus the 100mg edible.
        assert _ids(p["rows"]) == {"a", "b", "d"}, q


def test_unit_cap_vs_price_cap():
    unit = parse_query("flower under $10/g", DEALS)
    assert unit["maxUnit"] == 10.0
    assert unit["maxUnitLabel"] == "/g"
    assert unit["maxPrice"] is None
    assert _ids(unit["rows"]) == {"c"}  # only 8.6 /g qualifies among flower

    gram_words = parse_query("flower under $10 a gram", DEALS)
    assert gram_words["maxUnit"] == 10.0
    assert gram_words["maxPrice"] is None

    price = parse_query("flower under $40", DEALS)
    assert price["maxPrice"] == 40.0
    assert price["maxUnit"] is None
    assert _ids(price["rows"]) == {"a", "c"}  # sale 38 and 30, not 45


def test_brand_match():
    p = parse_query("alien labs deals", DEALS)
    assert p["brand"] == "Alien Labs"
    assert _ids(p["rows"]) == {"a"}


def test_shop_match():
    p = parse_query("anything at sunday goods", DEALS)
    assert p["shop"] == "Sunday Goods"
    assert _ids(p["rows"]) == {"c", "d"}


def test_fire_flag():
    p = parse_query("fire deals", DEALS)
    assert p["fire"] is True
    assert _ids(p["rows"]) == {"a", "d"}


def test_on_sale_flag():
    p = parse_query("flower on sale", DEALS)
    assert p["onSale"] is True
    # Frosted Cake has off == 0, so it's excluded.
    assert _ids(p["rows"]) == {"a", "b"}


def test_combined_query_and_describe():
    p = parse_query("indica flower under $10/g over 25% thc", DEALS)
    assert p["type"] == "Indica"
    assert p["cat"] == "Flower"
    assert p["maxUnit"] == 10.0
    assert p["minThc"] == 25.0
    desc = describe_query(p)
    assert "Indica" in desc and "Flower" in desc
    assert "under $10/g" in desc
    assert "25%+ THC" in desc
