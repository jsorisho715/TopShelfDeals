"""Query parsing + ranking + link helpers for the Telegram bot.

Python port of ``parseQuery`` / ``rankRows`` and the ``menuFor`` / ``mapsDirUrl`` /
``getDist`` helpers from ``topshelf/app/telegram.jsx`` + ``shared.jsx``. Operates on
the fully-augmented deal dicts produced by ``app.pipeline.serialize.bootstrap_payload``.
"""

from __future__ import annotations

import json
import re
from functools import lru_cache
from pathlib import Path
from urllib.parse import quote

from ..seed.seed_data import TS_DIST, TS_SHOPS

_DISP_PATH = Path(__file__).resolve().parent.parent / "seed" / "dispensaries.json"
_ALLOWLIST_PATH = Path(__file__).resolve().parent.parent / "seed" / "brands_allowlist.json"


@lru_cache(maxsize=1)
def _disp_index() -> dict[str, dict]:
    """Map dispensary name -> record from dispensaries.json (addr/menu/platform/dist)."""
    try:
        data = json.loads(_DISP_PATH.read_text(encoding="utf-8"))
    except Exception:
        return {}
    return {d.get("name"): d for d in data.get("dispensaries", [])}


def _shop_entry(shop: str) -> dict:
    """Merged directory entry for a shop: seed TS_SHOPS first, then dispensaries.json.

    Lets live shops (e.g. 'The Mint Scottsdale') that aren't in the seed still
    resolve a menu URL, address, and per-location distances.
    """
    entry = dict(TS_SHOPS.get(shop) or {})
    rec = _disp_index().get(shop)
    if rec:
        entry.setdefault("addr", rec.get("addr", ""))
        entry.setdefault("menu", rec.get("menu", ""))
        entry.setdefault("platform", rec.get("platform", ""))
        if "dist" not in entry and isinstance(rec.get("dist"), dict):
            entry["dist"] = rec["dist"]
    return entry

# Category keyword map (ported verbatim from telegram.jsx parseQuery).
_CAT_MAP = {
    "flower": "Flower",
    "bud": "Flower",
    "preroll": "Prerolls",
    "prerolls": "Prerolls",
    "joint": "Prerolls",
    "edible": "Edibles",
    "edibles": "Edibles",
    "gummy": "Edibles",
    "gummies": "Edibles",
    "hash": "Concentrates",
    "concentrate": "Concentrates",
    "concentrates": "Concentrates",
    "rosin": "Concentrates",
    "dab": "Concentrates",
    "vape": "Vapes",
    "vapes": "Vapes",
    "cart": "Vapes",
    "carts": "Vapes",
}

# A "$/unit" cap reads as a price followed by a per-unit suffix (/g, a gram,
# /10mg, …). A bare "under $40" with no suffix is an absolute sale-price cap.
_UNIT_SUFFIX = r"/?\s*(?:gram|grams|g|10\s*mg|10mg)\b|a\s+gram|per\s+gram|a\s+g\b|per\s+g\b"
_UNDER_RE = re.compile(
    r"under\s*\$?\s*(\d+(?:\.\d+)?)\s*(?P<suffix>" + _UNIT_SUFFIX + r")?"
)

# "over 25% thc" / "25%+ thc" / ">25 thc" / "25% thc" — a number tied to THC.
_MIN_THC_RES = [
    re.compile(r"(\d+(?:\.\d+)?)\s*%?\s*\+?\s*thc"),
    re.compile(r"thc\s*(?:over|above|of|>=?|min(?:imum)?)?\s*(\d+(?:\.\d+)?)"),
]

_STRAINS = ("indica", "sativa", "hybrid")

# Flag keywords -> only deals that satisfy the flag.
_SALE_WORDS = ("on sale", "deal", "special")


@lru_cache(maxsize=1)
def _brand_aliases() -> list[tuple[str, str]]:
    """``(alias_lower, canonical)`` pairs sorted longest-first for greedy matching."""
    try:
        data = json.loads(_ALLOWLIST_PATH.read_text(encoding="utf-8"))
    except Exception:
        return []
    pairs: list[tuple[str, str]] = []
    for b in data.get("brands", []):
        canon = b.get("canonical", "")
        if not canon:
            continue
        pairs.append((canon.lower(), canon))
        for alias in b.get("aliases", []):
            if alias:
                pairs.append((str(alias).lower(), canon))
    pairs.sort(key=lambda p: len(p[0]), reverse=True)
    return pairs


def _match_brand(s: str) -> str | None:
    """First allowlist canonical/alias appearing as a whole word in ``s``."""
    for alias, canon in _brand_aliases():
        if re.search(r"\b" + re.escape(alias) + r"\b", s):
            return canon
    return None


def _match_shop(s: str, deals: list[dict]) -> str | None:
    """A known shop name (from the current deals) appearing in ``s``."""
    shops = sorted(
        {d.get("shop") for d in deals if d.get("shop")}, key=len, reverse=True
    )
    for shop in shops:
        if shop.lower() in s:
            return shop
    return None


def _match_min_thc(s: str) -> float | None:
    for rx in _MIN_THC_RES:
        m = rx.search(s)
        if m:
            return float(m.group(1))
    return None


def _money(v) -> str:
    """Trim a trailing ``.0`` so ``10.0`` -> ``'10'`` but ``9.5`` stays ``'9.5'``."""
    try:
        f = float(v)
    except (TypeError, ValueError):
        return str(v)
    return str(int(f)) if f == int(f) else f"{f:g}"


def parse_query(q: str, deals: list[dict]) -> dict:
    """Parse a free-text query into a filtered, multi-facet result set.

    Detects (and filters by) category, strain ``type``, minimum THC, a ``$/unit``
    cap vs an absolute sale-price cap, brand, shop, the Scottsdale area, and the
    ``fire`` / on-sale flags. Returns every facet key plus ``rows`` filtered by all
    of them and ``maxUnitLabel`` for rendering.
    """
    s = (q or "").lower()

    cat = None
    for k, v in _CAT_MAP.items():
        if k in s:
            cat = v
            break

    strain = next(
        (t.capitalize() for t in _STRAINS if re.search(r"\b" + t + r"\b", s)), None
    )

    min_thc = _match_min_thc(s)

    # Price cap: "$/unit" when a per-unit suffix follows, else an absolute price.
    max_unit = None
    max_unit_label = None
    max_price = None
    m = _UNDER_RE.search(s)
    if m:
        n = float(m.group(1))
        suffix = (m.group("suffix") or "").strip()
        if suffix:
            max_unit = n
            max_unit_label = "/10mg" if "10" in suffix else "/g"
        else:
            max_price = n

    brand = _match_brand(s)
    shop = _match_shop(s, deals)
    area = "Scottsdale" if ("old town" in s or "scottsdale" in s) else None
    fire = "fire" in s
    on_sale = any(w in s for w in _SALE_WORDS)

    rows: list[dict] = []
    for d in deals:
        if cat is not None and d.get("cat") != cat:
            continue
        if strain is not None and d.get("type") != strain:
            continue
        if min_thc is not None and not (
            d.get("thc") is not None and d.get("thc") >= min_thc
        ):
            continue
        if max_unit is not None and not (
            d.get("unit") is not None and d.get("unit") <= max_unit
        ):
            continue
        if max_price is not None and not (
            d.get("sale") is not None and d.get("sale") <= max_price
        ):
            continue
        if brand is not None and d.get("brand") != brand:
            continue
        if shop is not None and d.get("shop") != shop:
            continue
        if area is not None and d.get("area") != area:
            continue
        if fire and not d.get("fire"):
            continue
        if on_sale and not (d.get("off") or 0) > 0:
            continue
        rows.append(d)

    return {
        "rows": rows,
        "cat": cat,
        "type": strain,
        "minThc": min_thc,
        "maxUnit": max_unit,
        "maxUnitLabel": max_unit_label,
        "maxPrice": max_price,
        "brand": brand,
        "shop": shop,
        "area": area,
        "fire": fire,
        "onSale": on_sale,
    }


def describe_query(parsed: dict) -> str:
    """Readable header for a parsed query, e.g. ``"Indica Flower under $10/g, 25%+ THC"``."""
    lead: list[str] = []
    if parsed.get("fire"):
        lead.append("\U0001F525 Fire")
    if parsed.get("type"):
        lead.append(str(parsed["type"]))
    if parsed.get("brand"):
        lead.append(str(parsed["brand"]))
    lead.append(str(parsed.get("cat") or "Top-shelf"))

    head = " ".join(lead)

    extras: list[str] = []
    if parsed.get("maxUnit") is not None:
        label = parsed.get("maxUnitLabel") or "/g"
        extras.append(f"under ${_money(parsed['maxUnit'])}{label}")
    elif parsed.get("maxPrice") is not None:
        extras.append(f"under ${_money(parsed['maxPrice'])}")
    if parsed.get("minThc") is not None:
        extras.append(f"{_money(parsed['minThc'])}%+ THC")
    if parsed.get("shop"):
        extras.append(f"at {parsed['shop']}")
    if parsed.get("area"):
        extras.append(str(parsed["area"]))
    if parsed.get("onSale") and not parsed.get("fire"):
        extras.append("on sale")

    if extras:
        head += " " + ", ".join(extras)
    return head


def rank(rows: list[dict], n: int = 6) -> list[dict]:
    """Sort by ``score`` descending and take the top ``n``."""
    return sorted(rows, key=lambda d: d.get("score", 0), reverse=True)[:n]


def dist_for(deal: dict, loc: str = "oldtown") -> float:
    """Straight-line miles for a deal from a saved location.

    Reads ``TS_DIST[loc][shop]``, then the shop's dispensaries.json ``dist[loc]``,
    then falls back to the deal's own ``dist`` field (matches ``getDist`` plus the
    merged live directory).
    """
    shop = deal.get("shop")
    loc_map = TS_DIST.get(loc) or {}
    if shop in loc_map:
        return loc_map[shop]
    entry = _shop_entry(shop)
    disp_dist = entry.get("dist")
    if isinstance(disp_dist, dict) and loc in disp_dist:
        return disp_dist[loc]
    return deal.get("dist")


def menu_for(shop: str) -> str:
    """Live menu URL for a shop (empty string if unknown)."""
    return _shop_entry(shop).get("menu", "") or ""


def maps_dir_url(shop: str) -> str:
    """Google Maps directions URL to the shop's street address (or its name)."""
    entry = _shop_entry(shop)
    dest = entry.get("addr") or shop or ""
    return "https://www.google.com/maps/dir/?api=1&destination=" + quote(dest)
