"""Adapter protocol and the shared ``MenuItem`` shape.

A ``MenuItem`` is the platform-agnostic raw menu row each adapter emits. It is
intentionally close to (but looser than) the canonical deal: the pipeline's
``normalize_item(raw_menu_item, shop)`` is responsible for brand-allowlisting,
unit normalization, and discount math. Adapters should do the platform-specific
parsing and nothing more.

MenuItem shape
--------------
``{
    "product":  str,            # product / item name
    "brand":    str | None,     # raw brand string (normalize resolves to canonical)
    "category": str | None,     # one of Flower | Prerolls | Edibles | Concentrates | Vapes
    "orig":     float | None,   # original / standard price (USD)
    "sale":     float | None,   # special / current price (== orig when not on special)
    "size":     str | None,     # option/weight label, e.g. "3.5g", "1g", "100mg"
    "thc":      float | None,   # THC potency % (or total mg for edibles)
    "cbd":      float | None,   # CBD potency %
    "type":     str | None,     # strain type: Indica | Sativa | Hybrid
    "img":      str | None,     # product image URL (always captured when present)
    "url":      str | None,     # deep link to THIS product/special (not the store menu)
    "in_stock": bool,           # availability

    # --- Promo / special metadata (Phase 1: specials accuracy) ----------------
    # When the platform exposes the actual special (not just a discounted price),
    # adapters fill these so the pipeline can validate the deal, compute %off from
    # the promo, tag weekday recurrence, and exclude FTP/industry-only offers from
    # fire/alerts. All optional; absent == "no labeled special on this item".
    "promo_title":      str | None,        # human label, e.g. "Wax Wednesday 30% off"
    "promo_kind":       str | None,        # percent | dollar | bogo | bundle | price | other
    "promo_dow":        list,              # weekday codes it runs, e.g. ["Wed"] (Mon..Sun)
    "promo_valid_from": str | None,        # ISO date/datetime the special starts
    "promo_valid_to":   str | None,        # ISO date/datetime the special ends
    "promo_audience":   str | None,        # all | ftp | vet | senior | patient | industry
    "promo_stackable":  bool,              # may stack with other discounts
    "promo_terms":      str | None,        # free-text terms/description
}``

``normalize_item`` reads ``product``/``brand``/``category``/``orig``/``sale``/
``size``/``thc``/``cbd``/``type``/``img``/``in_stock`` (with fallbacks) plus the
``promo_*`` keys, so these key names are the contract between an adapter and the
pipeline.
"""

from __future__ import annotations

from typing import Any, List, Optional, Protocol, TypedDict, runtime_checkable

# Canonical promo-audience buckets. Anything an adapter can't confidently map
# should be left as ``None`` (treated as "all") rather than guessed.
PROMO_AUDIENCES = ("all", "ftp", "vet", "senior", "patient", "industry")
# Promo audiences excluded from fire/daily-alert eligibility (one-time / not
# generally redeemable). See PRD FR8.
PROMO_AUDIENCES_EXCLUDED_FROM_FIRE = ("ftp", "industry")
# Canonical 3-letter weekday codes (match datetime.strftime("%a") and the seed's
# ``dow`` field) used in ``promo_dow``.
WEEKDAY_CODES = ("Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun")


class MenuItem(TypedDict, total=False):
    """A single raw menu row emitted by an adapter (see module docstring)."""

    product: str
    brand: Optional[str]
    category: Optional[str]
    orig: Optional[float]
    sale: Optional[float]
    size: Optional[str]
    thc: Optional[float]
    cbd: Optional[float]
    type: Optional[str]
    img: Optional[str]
    url: Optional[str]
    in_stock: bool

    # Rich product metadata (populated when the platform exposes it).
    desc: Optional[str]
    effects: List[str]
    lineage: Optional[str]

    # Promo / special metadata (see module docstring).
    promo_title: Optional[str]
    promo_kind: Optional[str]
    promo_dow: List[str]
    promo_valid_from: Optional[str]
    promo_valid_to: Optional[str]
    promo_audience: Optional[str]
    promo_stackable: bool
    promo_terms: Optional[str]


@runtime_checkable
class Adapter(Protocol):
    """Pulls a dispensary's live menu from one platform.

    Implementations must be defensive: on ANY failure (network error, 403 /
    Cloudflare gate, schema change) ``fetch`` returns ``[]`` rather than raising,
    so the scrape orchestrator can keep polling other stores.
    """

    def fetch(self, store_ref: dict[str, Any]) -> list[MenuItem]:
        """Return the store's menu as ``MenuItem`` dicts.

        ``store_ref`` is a dispensary record from ``app/seed/dispensaries.json``
        (keys: ``name``, ``addr``, ``platform``, ``menu``, ``dist`` …).
        """
        ...
