"""Free, no-key online image fallback for deals that have no scraped photo.

Uses DuckDuckGo's public image endpoint (no API key). This is best-effort: it can
return a slightly off image and is rate-limited / brittle, so it is only used when
a deal genuinely lacks an ``img`` (scraped deals almost always have one). Results
are cached to ``data/image_cache.json`` to avoid repeat lookups.

Everything here is defensive: any failure returns ``None`` and never raises.
"""

from __future__ import annotations

import json
import re
import threading
from pathlib import Path
from typing import Optional

import httpx

_DATA_DIR = Path(__file__).resolve().parent.parent.parent / "data"
_CACHE_PATH = _DATA_DIR / "image_cache.json"
_UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0 Safari/537.36"
_TIMEOUT = 12.0
_VQD_RE = re.compile(r"vqd=['\"]?([\d-]+)['\"]?")

_lock = threading.Lock()
_cache: Optional[dict] = None


def _load_cache() -> dict:
    global _cache
    if _cache is None:
        try:
            _cache = json.loads(_CACHE_PATH.read_text(encoding="utf-8"))
        except Exception:
            _cache = {}
    return _cache


def _save_cache() -> None:
    try:
        _DATA_DIR.mkdir(parents=True, exist_ok=True)
        _CACHE_PATH.write_text(json.dumps(_cache or {}), encoding="utf-8")
    except Exception:
        pass


def _ddg_image(query: str) -> Optional[str]:
    """First image result URL for a query via DuckDuckGo (no key). None on failure."""
    headers = {"User-Agent": _UA, "Referer": "https://duckduckgo.com/"}
    try:
        with httpx.Client(timeout=_TIMEOUT, headers=headers, follow_redirects=True) as client:
            # 1) get the vqd token DDG requires for the image endpoint
            tok = client.get("https://duckduckgo.com/", params={"q": query})
            m = _VQD_RE.search(tok.text)
            if not m:
                return None
            vqd = m.group(1)
            # 2) query the image endpoint
            r = client.get(
                "https://duckduckgo.com/i.js",
                params={"l": "us-en", "o": "json", "q": query, "vqd": vqd, "f": ",,,", "p": "1"},
            )
            data = r.json()
        results = data.get("results") or []
        for item in results:
            url = item.get("image")
            if url and url.startswith("http"):
                return url
    except Exception:
        return None
    return None


def find_product_image(brand: Optional[str], product: Optional[str], category: Optional[str] = None) -> Optional[str]:
    """Best-effort online image URL for a product (cached). None if nothing found."""
    brand = (brand or "").strip()
    product = (product or "").strip()
    if not (brand or product):
        return None
    key = f"{brand}|{product}".lower()

    with _lock:
        cache = _load_cache()
        if key in cache:
            return cache[key] or None

    query = " ".join(p for p in [brand, product, "cannabis"] if p)
    url = _ddg_image(query)

    with _lock:
        cache = _load_cache()
        cache[key] = url or ""
        _save_cache()
    return url
