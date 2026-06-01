"""Scoring + transparent factor breakdown.

Ported from ``topshelf/app/shared.jsx`` (``tsAugment``) and CLAUDE.md §5.1.

Two entry points:

* ``area_medians(deals)`` — per-category median of ``unit`` (the "$/g vs area"
  baseline). Matches the JS median exactly: sort ascending, take ``a[len//2]``
  (upper-middle element for even-length lists).
* ``compute_score(deal, area_median_by_cat)`` — returns ``(score, factors)`` per
  CLAUDE §5.1: ``score = clamp(0,100, depth+vsArea+tierW+distPen+fresh)`` and
  ``factors`` whose ``v`` values are the raw components (summing to that score).

The serializer reproduces ``tsAugment`` exactly (it keeps the *authored* score and
scales the factor ``v`` values by ``k = authored_score / raw``). It does that via
``score_components`` so the math lives in one place.

NOTE on rounding: JavaScript ``Math.round`` rounds halves toward +Infinity, while
Python ``round`` uses banker's rounding. We use ``js_round`` everywhere to stay
bit-for-bit identical to the prototype.
"""

from __future__ import annotations

import math
from typing import Any, Optional

# Brand-tier weights (CLAUDE §5.1).
TIER_WEIGHT = {"S": 24, "A": 18, "B": 12}


def js_round(x: float) -> int:
    """Replicate JavaScript ``Math.round`` (round half toward +Infinity)."""
    return math.floor(x + 0.5)


def _clamp(v: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, v))


def area_medians(deals: list[dict]) -> dict[str, float]:
    """Per-category median ``unit`` ($/unit). Mirrors ``tsAugment``'s areaMedian:
    sort ascending then take the element at index ``floor(len/2)``."""
    by_cat: dict[str, list[float]] = {}
    for d in deals:
        by_cat.setdefault(d["cat"], []).append(d["unit"])
    medians: dict[str, float] = {}
    for cat, vals in by_cat.items():
        a = sorted(vals)
        medians[cat] = a[len(a) // 2]
    return medians


def score_components(deal: dict, area_median_by_cat: dict[str, float]) -> dict[str, Any]:
    """Compute the raw score components + per-factor hints for a deal.

    Returns a dict with: ``depth``, ``vsArea``, ``tierW``, ``distPen``, ``fresh``,
    ``raw`` (their sum), ``median`` (the category baseline used), and ``hints``
    (a dict keyed by factor name). This is the shared primitive used by both
    ``compute_score`` and the serializer.
    """
    cat = deal["cat"]
    unit = deal["unit"]
    median = area_median_by_cat.get(cat, unit) or unit

    vs_area = int(_clamp(js_round((median - unit) / median * 60) + 8, 0, 24))
    tier_w = TIER_WEIGHT.get(deal.get("tier"), 10)
    depth = js_round(deal["off"] * 0.7)
    dist_pen = max(2, js_round(18 - deal["dist"] * 2))
    seen = deal.get("seen", "")
    fresh = 14 if "m" in seen else (10 if "1h" in seen else 6)
    raw = depth + vs_area + tier_w + dist_pen + fresh

    hints = {
        "Discount depth": f"{deal['off']}% off, validated vs history",
        "$/g vs area": f"median ${median:.1f}{deal.get('unitLabel', '')} nearby",
        "Brand tier": f"{deal.get('tier')}-tier top-shelf",
        "Distance": f"{deal['dist']} mi away",
        "Freshness": f"confirmed {seen}",
    }
    return {
        "depth": depth,
        "vsArea": vs_area,
        "tierW": tier_w,
        "distPen": dist_pen,
        "fresh": fresh,
        "raw": raw,
        "median": median,
        "hints": hints,
    }


def compute_score(
    deal: dict, area_median_by_cat: dict[str, float]
) -> tuple[int, list[dict]]:
    """Compute ``(score, factors)`` per CLAUDE §5.1.

    ``score = clamp(0, 100, depth + vsArea + tierW + distPen + fresh)``.
    ``factors`` is a list of ``{key, v, hint}`` whose ``v`` are the raw components
    (so they sum to ``raw``; ``score`` only differs if ``raw`` exceeds 100).
    """
    c = score_components(deal, area_median_by_cat)
    score = int(_clamp(c["raw"], 0, 100))
    factors = [
        {"key": "Discount depth", "v": c["depth"], "hint": c["hints"]["Discount depth"]},
        {"key": "$/g vs area", "v": c["vsArea"], "hint": c["hints"]["$/g vs area"]},
        {"key": "Brand tier", "v": c["tierW"], "hint": c["hints"]["Brand tier"]},
        {"key": "Distance", "v": c["distPen"], "hint": c["hints"]["Distance"]},
        {"key": "Freshness", "v": c["fresh"], "hint": c["hints"]["Freshness"]},
    ]
    return score, factors


def scaled_factors(deal: dict, area_median_by_cat: dict[str, float]) -> list[dict]:
    """Factor breakdown scaled to the deal's *authored* ``score`` — exactly as
    ``tsAugment`` produces it (``v = round(component * score / raw)``).

    Used by the serializer so the SPA's per-factor numbers match the prototype.
    """
    c = score_components(deal, area_median_by_cat)
    raw = c["raw"] or 1
    k = deal["score"] / raw
    return [
        {"key": "Discount depth", "v": js_round(c["depth"] * k), "hint": c["hints"]["Discount depth"]},
        {"key": "$/g vs area", "v": js_round(c["vsArea"] * k), "hint": c["hints"]["$/g vs area"]},
        {"key": "Brand tier", "v": js_round(c["tierW"] * k), "hint": c["hints"]["Brand tier"]},
        {"key": "Distance", "v": js_round(c["distPen"] * k), "hint": c["hints"]["Distance"]},
        {"key": "Freshness", "v": js_round(c["fresh"] * k), "hint": c["hints"]["Freshness"]},
    ]
