"""Shared, pure helpers for parsing platform special/promo metadata.

Adapters call these to turn a platform's free-form special (title + description +
schedule) into the canonical ``promo_*`` ``MenuItem`` fields (see
``app/adapters/base.py``). Kept network-free and dependency-free so they're
trivially unit-testable and reusable by every adapter and the pipeline.

The four things every platform expresses differently and we normalize here:

* **day-of-week** the special runs (``promo_dow`` -> ``["Wed"]``),
* **audience** it targets (``promo_audience`` -> ``"ftp"`` etc.),
* **discount kind** (``promo_kind`` -> ``"percent"``/``"bogo"``/...),
* **percent off** implied by the title when no price math is available.
"""

from __future__ import annotations

import re
from typing import Optional

from .base import WEEKDAY_CODES

# Map every common spelling/abbreviation of a weekday to its canonical 3-letter
# code. Order-independent; matched as whole words against lowered text.
_DOW_ALIASES: dict[str, str] = {
    "mon": "Mon", "monday": "Mon",
    "tue": "Tue", "tues": "Tue", "tuesday": "Tue",
    "wed": "Wed", "weds": "Wed", "wednesday": "Wed",
    "thu": "Thu", "thur": "Thu", "thurs": "Thu", "thursday": "Thu",
    "fri": "Fri", "friday": "Fri",
    "sat": "Sat", "saturday": "Sat",
    "sun": "Sun", "sunday": "Sun",
}

# Audience keyword -> canonical bucket. First match wins (most-specific first).
_AUDIENCE_PATTERNS: list[tuple[re.Pattern, str]] = [
    (re.compile(r"first[\s-]*time|ftp|new\s+patient|new\s+customer|welcome", re.I), "ftp"),
    (re.compile(r"\bvet(eran)?s?\b|military", re.I), "vet"),
    (re.compile(r"senior|\b55\+|\b65\+|elder", re.I), "senior"),
    (re.compile(r"industry|budtender|employee", re.I), "industry"),
    (re.compile(r"\bmed(ical)?\b|patient", re.I), "patient"),
]

_PERCENT_RE = re.compile(r"(\d{1,2})\s*%\s*(?:off)?", re.I)
_DOLLAR_OFF_RE = re.compile(r"\$\s*(\d{1,3}(?:\.\d{1,2})?)\s*off", re.I)
_BOGO_RE = re.compile(r"\bbogo\b|buy\s*one|buy\s*1|b1g1|2\s*for\s*\$?\d", re.I)
_BUNDLE_RE = re.compile(r"\bbundle\b|\bmix\s*(?:and|&|n)\s*match\b|\bdeal\b", re.I)


def parse_dow(*texts: Optional[str]) -> list[str]:
    """Extract canonical weekday codes mentioned across any of ``texts``.

    Returns them in week order (Mon..Sun), de-duplicated. ``"Wax Wednesday"`` ->
    ``["Wed"]``; ``"Fri-Sun happy hour"`` -> ``["Fri", "Sat", "Sun"]`` only if the
    individual days are named (no range expansion — ranges are ambiguous and rare
    in dispensary copy).
    """
    found: set[str] = set()
    for text in texts:
        if not text:
            continue
        for token in re.findall(r"[a-z]+", str(text).lower()):
            code = _DOW_ALIASES.get(token)
            if code:
                found.add(code)
    return [d for d in WEEKDAY_CODES if d in found]


def classify_audience(*texts: Optional[str]) -> Optional[str]:
    """Detect the targeted audience from any of ``texts`` (None == general/all)."""
    blob = " ".join(t for t in texts if t)
    if not blob:
        return None
    for pattern, bucket in _AUDIENCE_PATTERNS:
        if pattern.search(blob):
            return bucket
    return None


def classify_kind(*texts: Optional[str]) -> Optional[str]:
    """Best-effort discount-kind label from any of ``texts``.

    Returns ``percent`` | ``dollar`` | ``bogo`` | ``bundle`` | ``other`` (None when
    nothing is recognizable). Cheap heuristic on the human copy; the authoritative
    %off is still computed from price math in the pipeline when available.
    """
    blob = " ".join(t for t in texts if t)
    if not blob:
        return None
    if _BOGO_RE.search(blob):
        return "bogo"
    if _PERCENT_RE.search(blob):
        return "percent"
    if _DOLLAR_OFF_RE.search(blob):
        return "dollar"
    if _BUNDLE_RE.search(blob):
        return "bundle"
    return "other"


def percent_from_text(*texts: Optional[str]) -> Optional[int]:
    """Largest explicit ``NN% off`` found in any of ``texts`` (None if none).

    Used as a fallback %off when the platform gives a labeled special but no
    discounted price to compute against (e.g. a storewide ``"30% off vapes"``).
    """
    best: Optional[int] = None
    for text in texts:
        if not text:
            continue
        for m in _PERCENT_RE.finditer(str(text)):
            try:
                val = int(m.group(1))
            except (TypeError, ValueError):
                continue
            if 0 < val < 100 and (best is None or val > best):
                best = val
    return best


def build_promo(
    *,
    title: Optional[str] = None,
    description: Optional[str] = None,
    dow: Optional[list[str]] = None,
    valid_from: Optional[str] = None,
    valid_to: Optional[str] = None,
    audience: Optional[str] = None,
    stackable: Optional[bool] = None,
    kind: Optional[str] = None,
) -> dict:
    """Assemble the canonical ``promo_*`` fields from a platform special.

    Any field not supplied is inferred from ``title``/``description`` text where
    possible (dow, audience, kind). Returns a dict of only the populated
    ``promo_*`` keys so callers can ``deal.update(build_promo(...))`` cleanly.
    """
    title = (title or "").strip() or None
    description = (description or "").strip() or None

    dow = dow if dow else parse_dow(title, description)
    audience = audience or classify_audience(title, description)
    kind = kind or classify_kind(title, description)

    out: dict = {}
    if title:
        out["promo_title"] = title
    if kind:
        out["promo_kind"] = kind
    if dow:
        out["promo_dow"] = dow
    if valid_from:
        out["promo_valid_from"] = valid_from
    if valid_to:
        out["promo_valid_to"] = valid_to
    if audience:
        out["promo_audience"] = audience
    if stackable is not None:
        out["promo_stackable"] = bool(stackable)
    if description and description != title:
        out["promo_terms"] = description
    return out
