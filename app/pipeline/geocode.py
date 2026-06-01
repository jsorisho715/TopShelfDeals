"""Free geocoding + distance helpers for TopShelf.

Deals never carry an address; the parent maps ``shop -> addr`` via
``app/seed/dispensaries.json`` and feeds those addresses here. We geocode with
the free OpenStreetMap Nominatim endpoint, persist every lookup to
``data/geocode_cache.json`` (so a given address is fetched at most once, ever),
and rate-limit ourselves to <= 1 request/second per Nominatim's usage policy.

Everything here is defensive: a network failure, a bad address, or a malformed
cache must never raise. Callers get ``None`` / ``{}`` and move on.
"""

from __future__ import annotations

import json
import math
import threading
import time
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Optional

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------
_DATA_DIR = Path(__file__).resolve().parent.parent.parent / "data"
_CACHE_PATH = _DATA_DIR / "geocode_cache.json"

_NOMINATIM_URL = "https://nominatim.openstreetmap.org/search"
# Descriptive User-Agent is required by Nominatim's usage policy.
_USER_AGENT = "TopShelfDeals/1.0 (personal Scottsdale dispensary deal aggregator)"
_MIN_INTERVAL_SEC = 1.0  # <= 1 req/sec

# Home anchors (Scottsdale / Tempe / Phoenix AZ) keyed by zip.
ANCHORS: dict[str, str] = {
    "oldtown": "85251",
    "north": "85255",
    "tempe": "85281",
    "phx": "85015",
    "nphx": "85050",
}

_lock = threading.Lock()
_last_request_ts = 0.0
_cache: Optional[dict[str, Optional[list]]] = None


# ---------------------------------------------------------------------------
# Cache (JSON on disk; address string -> [lat, lng] or null)
# ---------------------------------------------------------------------------
def _norm_key(address: str) -> str:
    return " ".join((address or "").strip().lower().split())


def _load_cache() -> dict[str, Optional[list]]:
    global _cache
    if _cache is not None:
        return _cache
    try:
        with open(_CACHE_PATH, "r", encoding="utf-8") as fh:
            data = json.load(fh)
        _cache = data if isinstance(data, dict) else {}
    except (FileNotFoundError, ValueError, OSError):
        _cache = {}
    return _cache


def _save_cache() -> None:
    if _cache is None:
        return
    try:
        _DATA_DIR.mkdir(parents=True, exist_ok=True)
        with open(_CACHE_PATH, "w", encoding="utf-8") as fh:
            json.dump(_cache, fh, indent=2, sort_keys=True)
    except OSError:
        pass


def _cache_get(key: str) -> tuple[bool, Optional[tuple[float, float]]]:
    """Return ``(hit, coords)``. A cached ``null`` is a hit with ``None`` coords
    (we remember failed lookups too, so we never re-hit the network for them)."""
    cache = _load_cache()
    if key not in cache:
        return False, None
    val = cache[key]
    if isinstance(val, (list, tuple)) and len(val) == 2:
        try:
            return True, (float(val[0]), float(val[1]))
        except (TypeError, ValueError):
            return True, None
    return True, None


def _cache_put(key: str, coords: Optional[tuple[float, float]]) -> None:
    cache = _load_cache()
    cache[key] = [coords[0], coords[1]] if coords else None
    _save_cache()


# ---------------------------------------------------------------------------
# Network
# ---------------------------------------------------------------------------
def _throttle() -> None:
    """Block until at least ``_MIN_INTERVAL_SEC`` has elapsed since the last call."""
    global _last_request_ts
    now = time.monotonic()
    wait = _MIN_INTERVAL_SEC - (now - _last_request_ts)
    if wait > 0:
        time.sleep(wait)
    _last_request_ts = time.monotonic()


def _fetch(address: str) -> Optional[tuple[float, float]]:
    """Hit Nominatim once for ``address``. Returns coords or ``None``. Never raises."""
    params = urllib.parse.urlencode(
        {"format": "json", "q": address, "limit": 1, "countrycodes": "us"}
    )
    url = f"{_NOMINATIM_URL}?{params}"
    req = urllib.request.Request(url, headers={"User-Agent": _USER_AGENT})
    try:
        _throttle()
        with urllib.request.urlopen(req, timeout=15) as resp:
            payload = json.loads(resp.read().decode("utf-8"))
    except Exception:
        return None
    if not payload:
        return None
    try:
        first = payload[0]
        return (float(first["lat"]), float(first["lon"]))
    except (KeyError, IndexError, TypeError, ValueError):
        return None


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------
def geocode(address: Optional[str]) -> Optional[tuple[float, float]]:
    """Return ``(lat, lng)`` for ``address`` or ``None``.

    Cached results (including remembered failures) never re-hit the network.
    Defensive: returns ``None`` on any error.
    """
    if not address or not str(address).strip():
        return None
    key = _norm_key(str(address))
    with _lock:
        hit, coords = _cache_get(key)
        if hit:
            return coords
        coords = _fetch(str(address).strip())
        _cache_put(key, coords)
        return coords


def haversine_miles(a: tuple[float, float], b: tuple[float, float]) -> float:
    """Great-circle distance between two ``(lat, lng)`` points, in miles."""
    lat1, lon1 = float(a[0]), float(a[1])
    lat2, lon2 = float(b[0]), float(b[1])
    radius_mi = 3958.7613  # mean Earth radius in miles
    p1 = math.radians(lat1)
    p2 = math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlmb = math.radians(lon2 - lon1)
    h = math.sin(dphi / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dlmb / 2) ** 2
    return 2 * radius_mi * math.asin(min(1.0, math.sqrt(h)))


def anchor_coords() -> dict[str, tuple[float, float]]:
    """Geocode each anchor zip once (cached). Ungeocodable anchors are omitted."""
    out: dict[str, tuple[float, float]] = {}
    for anchor_id, zip_code in ANCHORS.items():
        coords = geocode(f"{zip_code}, AZ, USA")
        if coords is not None:
            out[anchor_id] = coords
    return out


def anchor_distances(address: Optional[str]) -> dict[str, float]:
    """Straight-line miles from ``address`` to each anchor.

    Returns ``{anchor_id: miles}`` rounded to 1 decimal, or ``{}`` if the address
    can't be geocoded.
    """
    coords = geocode(address)
    if coords is None:
        return {}
    out: dict[str, float] = {}
    for anchor_id, anchor_pt in anchor_coords().items():
        out[anchor_id] = round(haversine_miles(coords, anchor_pt), 1)
    return out


def nearest_anchor_miles(address: Optional[str]) -> Optional[float]:
    """Miles to the closest anchor, or ``None`` if ungeocodable."""
    dists = anchor_distances(address)
    if not dists:
        return None
    return min(dists.values())


def shop_distance_matrix(shop_to_addr: dict[str, str]) -> dict[str, dict[str, float]]:
    """Build the ``dist`` matrix the API/UI expect: ``{anchor_id: {shop: miles}}``.

    Shops whose address fails to geocode are simply absent from each anchor's map.
    """
    matrix: dict[str, dict[str, float]] = {anchor_id: {} for anchor_id in ANCHORS}
    for shop, addr in (shop_to_addr or {}).items():
        dists = anchor_distances(addr)
        for anchor_id, miles in dists.items():
            matrix.setdefault(anchor_id, {})[shop] = miles
    return matrix
