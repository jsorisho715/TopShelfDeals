"""Cross-platform same-product dedup + cross-platform store MERGE.

Two collapsing behaviours live here (CLAUDE §5.3):

1. **Same product, same shop** across multiple sources (Leafly / Weedmaps / the
   dispensary's own menu) -> one deal: keep the **lowest price** and merge in the
   **richest metadata**.

2. **Same physical store under different shop names/platforms** (e.g. "The Mint"
   via Dutchie and "The Mint Cannabis - Scottsdale" via Leafly). The parent
   geocodes each shop's address, clusters by rounded coords into a canonical
   store key, and passes the resulting ``store_groups`` map (shop name ->
   canonical key). Deals at shops that share a canonical key are treated as the
   same store for identity purposes, so the same product at both names collapses
   to a single row carrying the union of source platforms (``platforms``) under a
   single canonical ``shop`` name.

Identity key = (normalized product name, store-identity, normalized brand) where
``store-identity`` is the canonical store key when ``store_groups`` is supplied,
else the normalized shop name (today's behaviour). DISTINCT products stay
distinct; distinct shops with no shared store key stay distinct.
"""

from __future__ import annotations

import re
from typing import Optional

_WS_RE = re.compile(r"\s+")


def _norm(s: Optional[str]) -> str:
    """Lowercase, collapse internal whitespace, strip surrounding punctuation, so
    near-identical strings ('Blue  Dream ' vs 'blue dream') compare equal."""
    s = _WS_RE.sub(" ", (s or "").strip().lower())
    return s.strip(" -·.,")


def _store_identity(deal: dict, store_groups: Optional[dict[str, str]]) -> str:
    """Canonical store key for a deal's shop.

    With ``store_groups`` (shop name -> canonical key), shops mapped to the same
    key share an identity. Falls back to the normalized shop name when the shop
    isn't in the map or no map was given.
    """
    shop = deal.get("shop")
    if store_groups:
        canonical = store_groups.get(shop) or store_groups.get(_norm(shop))
        if canonical:
            return f"store::{canonical}"
    return _norm(shop)


def _key(deal: dict, store_groups: Optional[dict[str, str]]) -> tuple[str, str, str]:
    return (_norm(deal.get("product")), _store_identity(deal, store_groups), _norm(deal.get("brand")))


def _price(deal: dict) -> float:
    sale = deal.get("sale")
    if sale is None:
        sale = deal.get("orig")
    return float(sale) if sale is not None else float("inf")


def _richness(deal: dict) -> int:
    """Count populated metadata fields — used to pick the richer record."""
    fields = (
        "type", "lineage", "thc", "cbd", "desc", "effects", "img",
        "size", "tier", "area", "unit",
    )
    return sum(1 for f in fields if deal.get(f) not in (None, "", [], 0))


def _platforms_of(deal: dict) -> list[str]:
    """Source platforms already on a deal (``platforms`` list or single ``platform``)."""
    plats = deal.get("platforms")
    if isinstance(plats, list):
        return [p for p in plats if p]
    p = deal.get("platform")
    return [p] if p else []


def _merge(primary: dict, other: dict) -> dict:
    """Fill any missing/empty fields on ``primary`` from ``other`` (richest wins),
    and union the source platforms into a ``platforms`` list."""
    merged = dict(primary)
    for k, v in other.items():
        if merged.get(k) in (None, "", []) and v not in (None, "", []):
            merged[k] = v

    union: list[str] = []
    for p in _platforms_of(primary) + _platforms_of(other):
        if p not in union:
            union.append(p)
    if union:
        merged["platforms"] = union
    return merged


def dedup(deals: list[dict], store_groups: Optional[dict[str, str]] = None) -> list[dict]:
    """Collapse duplicate deals, keeping the lowest price and richest metadata.

    With ``store_groups`` (shop name -> canonical store key), deals whose shops
    share a canonical key are merged when they're the same product, producing one
    row under a single canonical ``shop`` and a unioned ``platforms`` list. Without
    it, behaves like the original (group by normalized product + shop). Order of
    first appearance is preserved.
    """
    chosen: dict[tuple[str, str, str], dict] = {}
    order: list[tuple[str, str, str]] = []

    for d in deals:
        k = _key(d, store_groups)
        if k not in chosen:
            base = dict(d)
            plats = _platforms_of(base)
            if plats:
                base["platforms"] = plats
            chosen[k] = base
            order.append(k)
            continue
        cur = chosen[k]
        # Pick the lower price as the base; merge richer metadata from the other.
        if _price(d) < _price(cur):
            base, extra = d, cur
        elif _price(d) > _price(cur):
            base, extra = cur, d
        else:
            # Same price: keep the richer record as base.
            base, extra = (d, cur) if _richness(d) >= _richness(cur) else (cur, d)
        merged = _merge(base, extra)
        # Keep a single canonical shop name (the one already chosen first wins, so
        # the output is stable regardless of which record won on price).
        merged["shop"] = cur.get("shop")
        chosen[k] = merged

    return [chosen[k] for k in order]


def build_store_groups(
    shop_to_coords: dict[str, tuple[float, float]], precision: int = 3
) -> dict[str, str]:
    """Cluster shops sharing (rounded) lat/lng into a canonical store key.

    ``shop_to_coords`` maps shop name -> ``(lat, lng)``. Shops whose coordinates
    round to the same cell (``precision`` decimal places, ~110m at 3dp) are
    assigned the same canonical key (the alphabetically-first shop name in the
    cluster, for a stable, human-readable key). Shops with no/invalid coords are
    omitted. The returned map feeds straight into :func:`dedup`.
    """
    cells: dict[tuple[float, float], list[str]] = {}
    for shop, coords in (shop_to_coords or {}).items():
        if not coords:
            continue
        try:
            cell = (round(float(coords[0]), precision), round(float(coords[1]), precision))
        except (TypeError, ValueError, IndexError):
            continue
        cells.setdefault(cell, []).append(shop)

    groups: dict[str, str] = {}
    for shops in cells.values():
        canonical = sorted(shops)[0]
        for shop in shops:
            groups[shop] = canonical
    return groups
