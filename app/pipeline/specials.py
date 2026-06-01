"""Promo-aware pipeline helpers (Phase 1: specials accuracy).

These bridge the adapter-captured ``promo_*`` fields (see ``app/adapters/base.py``)
into the canonical deal so the dashboard/bot and the fire/alert logic reflect the
ACTUAL special, not just a sale-vs-original price delta:

* :func:`apply_promo` — tag weekday recurrence (``recurring``/``dow``) from
  ``promo_dow`` and lift ``off`` to the promo's headline percent when the menu
  only exposed a labeled "% off" (not a discounted price).
* :func:`fire_eligible_from_promo` — gate fire on promo audience: first-time-
  patient and industry-only offers are excluded from fire/alerts (PRD FR8).
* :func:`has_promo_evidence` — True when a deal carries an authoritative labeled
  special, so the scraper can treat it as non-provisional immediately instead of
  waiting for days of price history to accrue.

All functions are pure and defensive; unknown/missing promo data is a no-op.
"""

from __future__ import annotations

from typing import Any

from ..adapters.base import PROMO_AUDIENCES_EXCLUDED_FROM_FIRE
from ..adapters.promo import percent_from_text
from .score import js_round


def has_promo_evidence(deal: dict) -> bool:
    """True if the deal carries a labeled special (authoritative promo metadata)."""
    return bool(deal.get("promo_title") or deal.get("promo_kind") or deal.get("promo_dow"))


def fire_eligible_from_promo(deal: dict) -> bool:
    """Whether a deal's promo audience permits it to earn fire / daily alerts.

    First-time-patient and industry-only deals are one-time / not generally
    redeemable, so they're excluded (PRD FR8). Any other audience (incl. none)
    is eligible.
    """
    audience = (deal.get("promo_audience") or "all").strip().lower()
    return audience not in PROMO_AUDIENCES_EXCLUDED_FROM_FIRE


def apply_promo(deal: dict) -> dict:
    """Fold promo metadata into a canonical deal (mutates and returns it).

    * ``recurring``/``dow`` set from ``promo_dow`` (first listed day powers the
      single-day ``dow`` the UI/bot read; full list stays in ``promo_dow``).
    * ``off`` lifted to the promo's headline ``NN% off`` when that exceeds the
      price-derived discount (covers storewide "% off" specials whose per-item
      sale price isn't separately exposed).
    * ``recurring`` left untouched when there's no weekday schedule.
    """
    dow_list = deal.get("promo_dow")
    if isinstance(dow_list, list) and dow_list:
        deal["recurring"] = True
        # Keep the existing single-day dow if already set & still valid, else first.
        if deal.get("dow") not in dow_list:
            deal["dow"] = dow_list[0]

    # Lift %off from an explicit headline percent ONLY when the per-item sale
    # price wasn't exposed (sale ~ orig, so the price-derived discount is ~0).
    # A real discounted price is authoritative and must not be inflated by copy.
    current_off = int(deal.get("off") or 0)
    if current_off <= 0:
        promo_pct = percent_from_text(deal.get("promo_title"), deal.get("promo_terms"))
        if promo_pct:
            orig = deal.get("orig")
            sale = deal.get("sale")
            if orig is not None and (sale is None or sale >= orig):
                deal["off"] = promo_pct
                deal["sale"] = round(float(orig) * (1 - promo_pct / 100.0), 2)
                # Recompute $/unit from the derived sale so ranking stays coherent.
                _recompute_unit(deal)

    return deal


def _recompute_unit(deal: dict) -> None:
    """Recompute ``unit`` from the (possibly promo-derived) sale, in place."""
    try:
        from .normalize import normalize_unit

        unit, label = normalize_unit(
            deal.get("cat") or "", float(deal.get("sale") or 0.0),
            deal.get("size"), deal.get("thc"),
        )
        if unit is not None:
            deal["unit"] = unit
            deal["unitLabel"] = label
    except Exception:
        pass
