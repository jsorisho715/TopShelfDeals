"""Deterministic price history + price-memory / fire logic.

Ported verbatim from ``topshelf/app/shared.jsx`` (``tsAugment``) and CLAUDE.md §5.2.

For seed/demo data we don't have real history, so ``synth_history`` regenerates the
exact same deterministic 14-point trail the prototype uses (same seed = sum of the
id's char codes, same wobble, same markup-trap branch). ``price_memory`` then
derives priorAvg / priorMin / isLowest / pctBelowAvg / fire from that trail.

For real scraped data, ``price_memory_from_observations`` runs the same memory math
over actual ``price_observations`` rows (effective price = sale_price when is_sale
else price).

JS ``Math.round`` is half-toward-+Infinity; we reuse ``score.js_round`` to match.
"""

from __future__ import annotations

import math
from typing import Any, Optional

from .score import js_round

# Deals that are "markup-then-discount" traps — they must NOT earn the fire badge.
# (Matches the MARKUP set in shared.jsx.)
MARKUP = {"pr3", "va3"}

# Fire threshold (CLAUDE §5.2 — tune on real data).
FIRE_PCT_THRESHOLD = 36


def synth_history(deal: dict) -> list[int]:
    """Deterministic trailing 14 daily prices (oldest -> today), == shared.jsx.

    ``today`` (last element) is always ``sale``. The ``hot`` flag pins yesterday to
    full ``orig`` (a "confirmed at full price just yesterday" signal). Trap ids sit
    near sale price for weeks, get marked up to ``orig``, then "discount" back.
    """
    seed = sum(ord(c) for c in deal["id"])
    is_trap = deal["id"] in MARKUP
    hist: list[int] = []
    for i in range(13, -1, -1):
        wob = math.sin((seed + i) * 1.3) * 0.05 + math.cos((seed * 0.7 + i)) * 0.02
        if is_trap:
            if i >= 3:
                p = js_round(deal["sale"] * (1.03 + abs(wob)))
            elif i >= 1:
                p = deal["orig"]
            else:
                p = deal["sale"]
        else:
            p = js_round(deal["orig"] * (1 + wob))
            if i == 1 and deal.get("hot"):
                p = deal["orig"]
            if i == 0:
                p = deal["sale"]
        hist.append(int(p))
    return hist


def _memory(prior: list[float], sale: float, is_trap: bool) -> dict[str, Any]:
    """Shared price-memory math (used by both the synth and observation paths)."""
    prior_avg = sum(prior) / len(prior) if prior else float(sale)
    prior_min = min(prior) if prior else float(sale)
    is_lowest = sale <= prior_min
    pct_below_avg = max(0, js_round((prior_avg - sale) / prior_avg * 100)) if prior_avg else 0
    fire = (not is_trap) and is_lowest and pct_below_avg >= FIRE_PCT_THRESHOLD
    if fire:
        fire_reason = f"Lowest in 14 days · {pct_below_avg}% under its own average"
    elif is_trap:
        # Curly quotes around "sale" match shared.jsx exactly.
        fire_reason = f"Heads-up: it sat at ${int(prior_min)} for weeks before this \u201csale\u201d"
    else:
        fire_reason = f"Validated drop · {pct_below_avg}% under its 14-day average"
    return {
        "priorAvg": prior_avg,
        "priorMin": prior_min,
        "isLowest": is_lowest,
        "pctBelowAvg": pct_below_avg,
        "fire": fire,
        "isTrap": is_trap,
        "fireReason": fire_reason,
    }


def price_memory(deal: dict, hist: list[int]) -> dict[str, Any]:
    """Price-memory dict from a 14-point history (last point = today's sale).

    Returns: priorAvg, priorMin, isLowest, pctBelowAvg, fire, isTrap, fireReason —
    exactly the keys/strings ``tsAugment`` produces.
    """
    is_trap = deal["id"] in MARKUP
    prior = hist[:-1]
    return _memory([float(p) for p in prior], float(deal["sale"]), is_trap)


def _effective_price(obs: dict) -> float:
    """Effective price for an observation: sale_price when on sale, else price."""
    is_sale = obs.get("is_sale")
    sale_price = obs.get("sale_price")
    if is_sale and sale_price is not None:
        return float(sale_price)
    price = obs.get("price")
    if price is not None:
        return float(price)
    # Fall back to whatever is present.
    return float(sale_price if sale_price is not None else 0.0)


def _detect_markup_trap(prior: list[float], sale: float) -> bool:
    """Best-effort markup-trap detection (CLAUDE §5.2).

    Flags the deal when it sat near its sale price (<= ~sale*1.05) for most of the
    trailing window, then jumped up within the last ~2 days (i.e. the "original" is
    inflated versus the typical trailing price).
    """
    if len(prior) < 4:
        return False
    threshold = sale * 1.05
    near = sum(1 for p in prior if p <= threshold)
    older = prior[:-2]
    recent = prior[-2:]
    older_near = older and all(p <= threshold for p in older)
    jumped = any(p > threshold for p in recent)
    return bool(near >= len(prior) * 0.5 and older_near and jumped)


def price_memory_from_observations(
    observations: list[dict], sale: float, is_trap: Optional[bool] = None
) -> dict[str, Any]:
    """Price-memory dict computed from real ``price_observations`` rows.

    ``observations`` should be the trailing window EXCLUDING today (oldest -> newest).
    Each row needs ``price``, ``sale_price``, ``is_sale``. Effective price =
    sale_price when ``is_sale`` else ``price``. If ``is_trap`` is None it is detected
    heuristically. Returns the same keys as ``price_memory``.
    """
    prior = [_effective_price(o) for o in observations]
    trap = _detect_markup_trap(prior, float(sale)) if is_trap is None else bool(is_trap)
    return _memory(prior, float(sale), trap)
