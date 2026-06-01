"""Typed shapes for the TopShelf backend.

Two layers are modeled here:

1. The **Deal contract** (``Deal`` / ``Factor``) — the exact augmented JSON the SPA
   consumes (see CLAUDE.md §3.1). These are ``TypedDict``s because the data crosses
   the API boundary as plain JSON dicts; using TypedDicts keeps the camelCase field
   names intact (``unitLabel``, ``priorAvg``, ``pctBelowAvg``, ``fireReason`` …).

2. The **DB rows** (dataclasses) — mirror the SQLite tables defined in
   ``migrations/0001_init.sql`` / PRD §4. These are convenience containers for the
   DAL; ``db.py`` can return either dataclasses or raw ``sqlite3.Row`` mappings.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional, TypedDict


# ===========================================================================
# Deal contract (augmented JSON shape consumed by the SPA — CLAUDE §3.1)
# ===========================================================================
class Factor(TypedDict):
    """One transparent score component. ``v`` values sum (approximately) to score."""
    key: str
    v: int
    hint: str


class Deal(TypedDict, total=False):
    """A fully-augmented deal. ``total=False`` because raw seed deals omit the
    derived keys until ``pipeline.serialize.augment_deals`` fills them in."""

    # identity / classification
    id: str
    cat: str           # one of TS_CATS minus "All"
    product: str
    brand: str
    tier: str          # S | A | B
    type: str          # Indica | Sativa | Hybrid
    lineage: str
    thc: float         # for edibles this is mg total
    cbd: float
    desc: str
    effects: list[str]

    # location / store
    shop: str
    area: str
    dist: float        # fallback miles (UI prefers dist[loc][shop])
    size: str

    # pricing
    orig: float
    sale: float
    unit: float
    unitLabel: str     # "/g" | "/10mg"
    off: int           # integer % off

    # ranking + memory (computed server-side)
    score: int
    factors: list[Factor]
    median: float      # per-category median unit used for the "vs area" factor
    hist: list[int]    # ~14 daily prices, oldest -> today; last = sale
    priorAvg: float
    priorMin: float
    isLowest: bool
    pctBelowAvg: int
    fire: bool
    isTrap: bool
    fireReason: str

    # freshness / availability / recurrence
    seen: str          # humanized last_seen
    stock: bool
    recurring: bool
    dow: Optional[str]
    hot: bool          # legacy; kept == fire for safety

    # media
    img: Optional[str]


class BootstrapPayload(TypedDict):
    """Shape returned by ``GET /api/bootstrap`` (CLAUDE §3)."""
    deals: list[Deal]
    shops: dict[str, dict]
    locations: list[dict]
    dist: dict[str, dict[str, float]]
    cats: list[str]
    generatedAt: str


# ===========================================================================
# DB rows (mirror migrations/0001_init.sql / PRD §4)
# ===========================================================================
@dataclass
class Dispensary:
    name: str
    address: str = ""
    lat: Optional[float] = None
    lng: Optional[float] = None
    dist_85251: Optional[float] = None
    dist_85255: Optional[float] = None
    platform: str = ""
    menu_ref: str = ""
    active: bool = True
    id: Optional[int] = None


@dataclass
class Brand:
    canonical_name: str
    aliases_json: str = "[]"
    tier: str = "B"
    allowlisted: bool = True
    id: Optional[int] = None


@dataclass
class Product:
    name: str
    dispensary_id: Optional[int] = None
    brand_id: Optional[int] = None
    category: str = ""
    strain_type: str = ""
    lineage: str = ""
    size_g: Optional[float] = None
    thc_pct: Optional[float] = None
    cbd_pct: Optional[float] = None
    unit: Optional[float] = None
    unit_label: str = ""
    description: str = ""
    effects_json: str = "[]"
    image_url: Optional[str] = None
    menu_url: Optional[str] = None
    id: Optional[int] = None


@dataclass
class PriceObservation:
    product_id: int
    observed_at: str               # ISO8601
    price: float
    sale_price: Optional[float] = None
    is_sale: bool = False
    source_platform: str = ""
    in_stock: bool = True
    id: Optional[int] = None


@dataclass
class DealRow:
    """Persisted, ranked deal (mirrors the ``deals`` table)."""
    product_id: int
    dispensary_id: Optional[int] = None
    original_price: Optional[float] = None
    sale_price: Optional[float] = None
    discount_pct_validated: Optional[int] = None
    unit_price: Optional[float] = None
    score: Optional[int] = None
    score_factors_json: str = "[]"
    prior_avg: Optional[float] = None
    prior_min: Optional[float] = None
    is_lowest: bool = False
    pct_below_avg: Optional[int] = None
    is_fire: bool = False
    is_markup_trap: bool = False
    first_seen: Optional[str] = None
    last_seen: Optional[str] = None
    is_recurring: bool = False
    recurrence_dow: Optional[str] = None
    in_stock: bool = True
    id: Optional[int] = None


@dataclass
class Filter:
    """Saved filter preset. ``json_criteria`` holds the ``c`` object the UI uses:
    ``{cat, sort, maxDist, minOff, inStock}``."""
    name: str
    json_criteria: str = "{}"
    active: bool = True
    telegram_alerts_on: bool = True
    id: Optional[int] = None


@dataclass
class NotificationSent:
    deal_id: int
    filter_id: Optional[int] = None
    sent_at: str = ""
    alerted_price: Optional[float] = None
    id: Optional[int] = None


@dataclass
class Digest:
    period_start: str
    sent_at: str = ""
    id: Optional[int] = None
