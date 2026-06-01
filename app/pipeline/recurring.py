"""Recurring-deal (weekday cadence) detection.

Best-effort per CLAUDE §5.3 / PRD FR8: from a product's ``price_observations``,
find whether its on-sale days cluster on a single weekday. If a clear dominant
weekday emerges across multiple weeks, the deal is "recurring" and we return the
3-letter weekday (``Mon``..``Sun``) the prototype uses.
"""

from __future__ import annotations

from collections import Counter
from datetime import datetime
from typing import Optional

_DOW = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]


def _parse_dt(value) -> Optional[datetime]:
    if isinstance(value, datetime):
        return value
    if not value:
        return None
    s = str(value).replace("Z", "+00:00")
    try:
        return datetime.fromisoformat(s)
    except ValueError:
        for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d", "%Y/%m/%d"):
            try:
                return datetime.strptime(str(value), fmt)
            except ValueError:
                continue
    return None


def _is_on_sale(obs: dict) -> bool:
    if obs.get("is_sale"):
        return True
    sale = obs.get("sale_price")
    price = obs.get("price")
    return sale is not None and price is not None and float(sale) < float(price)


def detect_recurring(
    observations: list[dict], min_weeks: int = 2
) -> tuple[bool, Optional[str]]:
    """Return ``(is_recurring, dow)``.

    Looks at the weekdays on which the product was on sale. If one weekday accounts
    for the majority of sale events and appears in at least ``min_weeks`` distinct
    calendar weeks, that weekday is reported as the recurrence day.
    """
    sale_days: list[int] = []
    weeks_for_day: dict[int, set] = {}
    for obs in observations:
        if not _is_on_sale(obs):
            continue
        dt = _parse_dt(obs.get("observed_at"))
        if dt is None:
            continue
        wd = dt.weekday()
        sale_days.append(wd)
        iso = dt.isocalendar()
        weeks_for_day.setdefault(wd, set()).add((iso[0], iso[1]))

    if not sale_days:
        return False, None

    counts = Counter(sale_days)
    top_day, top_count = counts.most_common(1)[0]
    distinct_weeks = len(weeks_for_day.get(top_day, set()))

    # Dominant weekday: majority of sale events AND seen across enough weeks.
    if distinct_weeks >= min_weeks and top_count >= max(min_weeks, len(sale_days) * 0.5):
        return True, _DOW[top_day]
    return False, None
