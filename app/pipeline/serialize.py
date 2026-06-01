"""THE CONTRACT BOUNDARY: raw deal dicts -> fully-augmented Deal JSON.

``augment_deals`` is the Python port of ``tsAugment`` in ``topshelf/app/shared.jsx``.
It takes raw deals (like ``seed_data.TS_DEALS``) and returns deals carrying every
field in CLAUDE.md §3.1 — all raw fields PLUS the derived ones (``hist``, ``factors``,
``median``, ``priorAvg``, ``priorMin``, ``isLowest``, ``pctBelowAvg``, ``fire``,
``isTrap``, ``fireReason``), with ``img`` always present (default ``None``) and
``hot`` kept == ``fire`` for safety (per the §3.1 contract note).

``bootstrap_payload`` assembles the full ``GET /api/bootstrap`` response.

Keep this module's output byte-compatible with the prototype: the SPA renders
straight off these field names.
"""

from __future__ import annotations

import os
from datetime import datetime
from typing import Any, Optional

try:
    from zoneinfo import ZoneInfo
    _PHX = ZoneInfo("America/Phoenix")
except Exception:  # pragma: no cover - zoneinfo data always present on 3.13
    _PHX = None  # type: ignore[assignment]

from ..seed.seed_data import TS_CATS, TS_DEALS, TS_DIST, TS_LOCATIONS, TS_SHOPS
from . import pricememory, score


def augment_deals(raw_deals: list[dict]) -> list[dict]:
    """Augment raw deals exactly like ``tsAugment``.

    Returns NEW dicts (inputs are not mutated). Each output contains all original
    fields plus the derived ones, with ``img`` guaranteed present and ``hot == fire``.
    """
    area_median = score.area_medians(raw_deals)

    out: list[dict] = []
    for d in raw_deals:
        hist = pricememory.synth_history(d)
        mem = pricememory.price_memory(d, hist)
        median = area_median.get(d["cat"], d["unit"]) or d["unit"]
        factors = score.scaled_factors(d, area_median)

        # Full-price items (off <= 0) are regular top-shelf products, not deals.
        # Override the deal-centric "Validated drop" copy with a neutral line.
        fire_reason = mem["fireReason"]
        if not d.get("off"):
            fire_reason = "At its regular menu price \u2014 top-shelf staple"

        augmented: dict[str, Any] = {
            **d,
            "hist": hist,
            "factors": factors,
            "median": median,
            "priorAvg": mem["priorAvg"],
            "priorMin": mem["priorMin"],
            "isLowest": mem["isLowest"],
            "pctBelowAvg": mem["pctBelowAvg"],
            "fire": mem["fire"],
            "isTrap": mem["isTrap"],
            "fireReason": fire_reason,
        }
        # Contract guarantees (CLAUDE §3.1): img always present; hot mirrors fire.
        augmented["img"] = d.get("img")
        augmented["url"] = d.get("url")  # per-product deep link (may be None)
        augmented["hot"] = mem["fire"]
        out.append(augmented)

    return out


def _generated_at() -> str:
    """Current time as ISO8601 in America/Phoenix (no DST)."""
    now = datetime.now(_PHX) if _PHX is not None else datetime.now()
    return now.isoformat(timespec="seconds")


def _radius_miles() -> float:
    """Configured search radius (``RADIUS_MILES`` env), defaulting to 20 mi."""
    try:
        return float(os.getenv("RADIUS_MILES", "20"))
    except (TypeError, ValueError):
        return 20.0


def bootstrap_payload() -> dict:
    """Full ``GET /api/bootstrap`` response (CLAUDE §3) built off the seed data."""
    return {
        "deals": augment_deals(TS_DEALS),
        "shops": TS_SHOPS,
        "locations": TS_LOCATIONS,
        "dist": TS_DIST,
        "cats": TS_CATS,
        "radiusMiles": _radius_miles(),
        "generatedAt": _generated_at(),
    }
