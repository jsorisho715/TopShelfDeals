"""Freshness + specials helpers.

Pure, side-effect-free helpers the parent wires into the scrape/serialize path:

* :func:`humanize_seen` — turn an ISO timestamp into the ``seen`` string the UI
  shows ("just now", "12m ago", "3h ago", "2d ago").
* :func:`is_stale` — was a deal last seen too long before this scrape started?
* :func:`real_specials` — keep only genuine discounts (drop non-deals where the
  sale isn't actually below the original).
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional


def _parse(ts: Optional[str]) -> Optional[datetime]:
    """Parse an ISO-8601 timestamp defensively. Returns ``None`` on failure."""
    if not ts:
        return None
    if isinstance(ts, datetime):
        return ts
    try:
        return datetime.fromisoformat(str(ts))
    except (TypeError, ValueError):
        return None


def _as_aware(dt: datetime, ref: datetime) -> datetime:
    """Align naive/aware-ness of ``dt`` to ``ref`` so subtraction never throws."""
    if dt.tzinfo is None and ref.tzinfo is not None:
        return dt.replace(tzinfo=ref.tzinfo)
    if dt.tzinfo is not None and ref.tzinfo is None:
        return dt.replace(tzinfo=None)
    return dt


def humanize_seen(observed_at_iso: Optional[str], now: Optional[datetime] = None) -> str:
    """Humanize how long ago something was observed.

    Buckets: ``< 60s`` -> "just now", ``< 60m`` -> "Nm ago", ``< 24h`` -> "Nh ago",
    else "Nd ago". Unparseable / future timestamps degrade to "just now".
    """
    observed = _parse(observed_at_iso)
    if observed is None:
        return "just now"
    if now is None:
        now = datetime.now(observed.tzinfo) if observed.tzinfo else datetime.now()
    observed = _as_aware(observed, now)

    seconds = (now - observed).total_seconds()
    if seconds < 60:
        return "just now"
    if seconds < 3600:
        return f"{int(seconds // 60)}m ago"
    if seconds < 86400:
        return f"{int(seconds // 3600)}h ago"
    return f"{int(seconds // 86400)}d ago"


def is_stale(
    last_seen_iso: Optional[str],
    scrape_started_iso: Optional[str],
    max_age_hours: float = 12,
) -> bool:
    """True if ``last_seen`` is more than ``max_age_hours`` before the scrape start.

    A missing/unparseable ``last_seen`` is treated as stale (we can't confirm it's
    fresh). A missing/unparseable ``scrape_started`` falls back to "now".
    """
    last_seen = _parse(last_seen_iso)
    if last_seen is None:
        return True
    started = _parse(scrape_started_iso)
    if started is None:
        started = datetime.now(last_seen.tzinfo) if last_seen.tzinfo else datetime.now()
    last_seen = _as_aware(last_seen, started)

    age_hours = (started - last_seen).total_seconds() / 3600.0
    return age_hours > max_age_hours


def _is_real_special(deal: dict) -> bool:
    off = deal.get("off")
    if off is not None:
        try:
            if float(off) <= 0:
                return False
        except (TypeError, ValueError):
            return False

    orig = deal.get("orig")
    sale = deal.get("sale")
    if orig is not None and sale is not None:
        try:
            if float(sale) >= float(orig):
                return False
        except (TypeError, ValueError):
            return False
    return True


def real_specials(deals: list[dict]) -> list[dict]:
    """Keep only genuine discounts: drop deals with ``off <= 0`` or ``sale >= orig``.

    Order is preserved. Deals with no price info but a positive ``off`` are kept;
    deals with neither usable ``off`` nor a sale-below-orig are dropped.
    """
    return [d for d in (deals or []) if _is_real_special(d)]
