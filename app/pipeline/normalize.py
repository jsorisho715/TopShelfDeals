"""Normalize a raw scraped menu item into canonical TopShelf fields.

Responsibilities (CLAUDE §5.3):

* Brand normalize via ``brands_allowlist.json`` aliases (case-insensitive). Items
  whose brand is not allowlisted return ``None`` (dropped upstream).
* Unit normalize: ``$/g`` for flower / concentrate / preroll / vape, ``$/10mg`` for
  edibles → ``unit`` + ``unitLabel``.
* Discount: ``off = round((orig - sale) / orig * 100)``.

The output dict uses the same camelCase field names as the seed deals so it can flow
straight into ``serialize.augment_deals``. Missing fields are left absent (the
serializer fills derived/defaulted keys).
"""

from __future__ import annotations

import json
import re
from functools import lru_cache
from pathlib import Path
from typing import Any, Optional

from .score import js_round

_SEED_DIR = Path(__file__).resolve().parent.parent / "seed"
_ALLOWLIST_PATH = _SEED_DIR / "brands_allowlist.json"

# Categories that price by weight ($/g). Edibles price by dose ($/10mg).
_PER_GRAM_CATS = {"flower", "prerolls", "concentrates", "vapes", "preroll", "concentrate", "vape"}
_PER_DOSE_CATS = {"edibles", "edible"}


@lru_cache(maxsize=1)
def _load_allowlist() -> list[dict]:
    with open(_ALLOWLIST_PATH, "r", encoding="utf-8") as fh:
        return json.load(fh).get("brands", [])


@lru_cache(maxsize=1)
def _alias_index() -> dict[str, dict]:
    """Map a lowercased alias/canonical -> brand record for fast resolution."""
    index: dict[str, dict] = {}
    for b in _load_allowlist():
        index[b["canonical"].lower()] = b
        for a in b.get("aliases", []):
            index[a.lower()] = b
    return index


def resolve_brand(raw_brand: Optional[str]) -> Optional[dict]:
    """Return the allowlist record for a raw brand string, or ``None`` if not
    allowlisted. Matching is case-insensitive against canonical + aliases."""
    if not raw_brand:
        return None
    return _alias_index().get(raw_brand.strip().lower())


def _parse_size_grams(size: Optional[str]) -> Optional[float]:
    """Parse a flower/concentrate size string into grams (e.g. '3.5g' -> 3.5,
    '7g' -> 7). Returns None if unparseable."""
    if not size:
        return None
    m = re.search(r"([\d.]+)\s*g", str(size).lower())
    if m:
        return float(m.group(1))
    return None


def _parse_total_mg(size: Optional[str], thc: Optional[float]) -> Optional[float]:
    """Parse an edible's total mg (e.g. '100mg' -> 100). Falls back to ``thc``
    (which for edibles is total mg per the Deal contract)."""
    if size:
        m = re.search(r"([\d.]+)\s*mg", str(size).lower())
        if m:
            return float(m.group(1))
    if thc is not None:
        return float(thc)
    return None


def compute_off(orig: float, sale: float) -> int:
    """Integer percent off: ``round((orig - sale) / orig * 100)``."""
    if not orig:
        return 0
    return js_round((orig - sale) / orig * 100)


def normalize_unit(
    cat: str, sale: float, size: Optional[str], thc: Optional[float] = None
) -> tuple[Optional[float], str]:
    """Return ``(unit, unitLabel)``. ``$/g`` for weight categories, ``$/10mg`` for
    edibles. ``unit`` is rounded to 1 decimal (matches the seed data precision)."""
    c = (cat or "").lower()
    if c in _PER_DOSE_CATS:
        total_mg = _parse_total_mg(size, thc)
        if total_mg:
            return round(sale / (total_mg / 10.0), 1), "/10mg"
        return None, "/10mg"
    # default: weight-priced
    grams = _parse_size_grams(size)
    if grams:
        return round(sale / grams, 1), "/g"
    return None, "/g"


def normalize_item(raw_menu_item: dict, shop: str) -> Optional[dict]:
    """Map a scraped menu item to canonical deal fields.

    ``raw_menu_item`` is adapter output; recognized keys (with fallbacks):
    ``product``/``name``, ``brand``, ``cat``/``category``, ``orig``/``price``,
    ``sale``/``sale_price``, ``size``, ``type``/``strain_type``, ``lineage``,
    ``thc``, ``cbd``, ``desc``/``description``, ``effects``, ``img``/``image_url``,
    ``dist``, ``area``, ``stock``/``in_stock``.

    Returns the canonical dict, or ``None`` if the brand isn't allowlisted.
    """
    brand_rec = resolve_brand(raw_menu_item.get("brand"))
    if brand_rec is None:
        return None

    cat = raw_menu_item.get("cat") or raw_menu_item.get("category") or ""
    orig = raw_menu_item.get("orig", raw_menu_item.get("price"))
    sale = raw_menu_item.get("sale", raw_menu_item.get("sale_price", orig))
    orig = float(orig) if orig is not None else None
    sale = float(sale) if sale is not None else orig
    size = raw_menu_item.get("size")
    thc = raw_menu_item.get("thc")

    unit, unit_label = normalize_unit(cat, sale if sale is not None else 0.0, size, thc)
    off = compute_off(orig, sale) if (orig is not None and sale is not None) else 0

    out: dict[str, Any] = {
        "cat": cat,
        "product": raw_menu_item.get("product") or raw_menu_item.get("name"),
        "brand": brand_rec["canonical"],
        "tier": brand_rec.get("tier"),
        "type": raw_menu_item.get("type") or raw_menu_item.get("strain_type"),
        "lineage": raw_menu_item.get("lineage"),
        "thc": thc,
        "cbd": raw_menu_item.get("cbd"),
        "desc": raw_menu_item.get("desc") or raw_menu_item.get("description"),
        "effects": raw_menu_item.get("effects") or [],
        "shop": shop,
        "area": raw_menu_item.get("area"),
        "dist": raw_menu_item.get("dist"),
        "size": size,
        "orig": orig,
        "sale": sale,
        "unit": unit,
        "unitLabel": unit_label,
        "off": off,
        "img": raw_menu_item.get("img") or raw_menu_item.get("image_url"),
        "url": raw_menu_item.get("url"),
        "stock": raw_menu_item.get("stock", raw_menu_item.get("in_stock", True)),
    }
    if "id" in raw_menu_item:
        out["id"] = raw_menu_item["id"]

    # Carry through any promo/special metadata the adapter captured (Phase 1).
    # These power promo-validated %off, weekday recurrence, and fire eligibility
    # downstream (see pipeline.specials.apply_promo). Only copy populated keys.
    for pk in (
        "promo_title", "promo_kind", "promo_dow", "promo_valid_from",
        "promo_valid_to", "promo_audience", "promo_stackable", "promo_terms",
    ):
        if raw_menu_item.get(pk) not in (None, "", []):
            out[pk] = raw_menu_item[pk]
    return out
