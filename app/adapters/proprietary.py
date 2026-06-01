"""Proprietary menu adapter for JointCommerce-powered dispensary sites.

Strategy: a number of Arizona dispensaries (Sol Flower / ``livewithsol.com``,
YiLo / ``yilo.com``) run a WordPress storefront whose product grid is hydrated
client-side from the **JointCommerce** ("joint-ecommerce") Elasticsearch proxy:

    POST https://<host>/wp-json/joint-ecommerce/v1/products/ecommerce-production/_search

The POST body is an Elasticsearch query; the response is the standard ES envelope
``{"hits": {"hits": [ { "_source": <product> }, ... ]}}``. Each ``_source`` carries
``name``, ``category`` (``FLOWER`` / ``EDIBLES`` / ``VAPORIZERS`` / ``PRE_ROLLS`` /
``CONCENTRATES``), ``strainType``, ``brandName``, ``primaryImage``, ``effects``,
``potencyThc*`` and a ``variants`` list (each ``{option, price, specialPrice,
menuType}``). A store is selected purely by its numeric ``businessId`` (resolved
once from the site's ``stores/closest`` endpoint and pinned in
``app/seed/dispensaries.json`` as ``business_id``).

Unlike Dutchie/Weedmaps this endpoint is **not** edge-gated, so the fast path is a
plain ``httpx`` POST — no browser required. The JSON -> ``MenuItem`` mapping is the
pure, network-free :func:`parse_menu` so it can be unit-tested against a fixture.

Robustness (Adapter protocol / PRD FR2): every request is bounded by a timeout and
a per-store wall-clock budget, requests are sequential with a polite delay, and on
ANY failure :meth:`fetch` returns ``[]`` instead of raising. If httpx ever yields
nothing (a future block), it falls back ONCE to a headless Playwright session that
issues the same ``_search`` from the site origin; the browser is ALWAYS closed via
``sync_playwright``'s context manager + ``finally`` (never leak Chromium). Set
``SCRAPE_NO_BROWSER=1`` to disable that fallback.
"""

from __future__ import annotations

import os
import re
import time
from typing import Any, Optional
from urllib.parse import urlparse

import httpx

from . import promo as _promo
from .base import MenuItem

_SEARCH_PATH = "/wp-json/joint-ecommerce/v1/products/ecommerce-production/_search"
_TIMEOUT_SEC = 20.0
# Per-store wall-clock budget across all page requests (politeness/bound).
_STORE_BUDGET_SEC = 40.0
_POLITE_DELAY_SEC = float(os.getenv("JOINT_DELAY_SEC", "0.8"))
_PAGE_SIZE = 50
_MAX_PAGES = int(os.getenv("JOINT_PAGES", "6"))
_PW_NAV_TIMEOUT_MS = 30000

_DEFAULT_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
)

# Only the fields we actually consume (keeps the response small + stable).
_SOURCE_INCLUDES = [
    "globalProductId", "jointId", "businessId", "name", "nameText", "category",
    "subCategory", "description", "effects", "primaryImage", "images", "menuType",
    "strainType", "urlFragment", "brandName", "variants", "lowestPrice",
    "potencyThcDisplayValue", "potencyThcRangeHigh", "potencyCbdDisplayValue",
    "potencyCbdRangeHigh", "applicableSpecials",
]

# JointCommerce ``category`` (uppercase) -> our canonical category names.
_CATEGORY_MAP = {
    "flower": "Flower",
    "pre_rolls": "Prerolls",
    "pre-rolls": "Prerolls",
    "prerolls": "Prerolls",
    "preroll": "Prerolls",
    "edibles": "Edibles",
    "edible": "Edibles",
    "drinks": "Edibles",
    "beverages": "Edibles",
    "concentrates": "Concentrates",
    "concentrate": "Concentrates",
    "extracts": "Concentrates",
    "vaporizers": "Vapes",
    "vaporizer": "Vapes",
    "vapes": "Vapes",
    "vape": "Vapes",
    "cartridges": "Vapes",
    "cartridge": "Vapes",
}

_STRAIN_TYPE_MAP = {
    "indica": "Indica",
    "sativa": "Sativa",
    "hybrid": "Hybrid",
    "indica_dominant": "Indica",
    "sativa_dominant": "Sativa",
    "hybrid_indica": "Hybrid",
    "hybrid_sativa": "Hybrid",
    "cbd": "Hybrid",
}

# Ounce-based option labels -> grams (the pipeline's size parser only reads "<n>g").
_OZ_TO_GRAMS = {
    "1/8oz": 3.5, "1/8 oz": 3.5, "eighth": 3.5,
    "1/4oz": 7.0, "1/4 oz": 7.0, "quarter": 7.0,
    "1/2oz": 14.0, "1/2 oz": 14.0, "half": 14.0,
    "1oz": 28.0, "1 oz": 28.0, "oz": 28.0, "ounce": 28.0,
}
_OZ_FRACTION_RE = re.compile(r"(\d+(?:\.\d+)?)\s*/\s*(\d+(?:\.\d+)?)\s*oz", re.I)
_OZ_WHOLE_RE = re.compile(r"(\d+(?:\.\d+)?)\s*oz", re.I)


# ---------------------------------------------------------------------------
# Small parse helpers
# ---------------------------------------------------------------------------
def _to_float(value: Any) -> Optional[float]:
    if value is None or value == "":
        return None
    if isinstance(value, (int, float)):
        return float(value)
    try:
        return float(str(value).replace("$", "").replace(",", "").replace("%", "").strip())
    except (ValueError, TypeError):
        return None


def _map_category(raw: Optional[str]) -> Optional[str]:
    if not raw:
        return None
    return _CATEGORY_MAP.get(str(raw).strip().lower())


def _map_strain_type(raw: Optional[str]) -> Optional[str]:
    if not raw:
        return None
    return _STRAIN_TYPE_MAP.get(str(raw).strip().lower())


def _normalize_option(option: Optional[str]) -> Optional[str]:
    """Normalize a variant ``option`` into a size string the pipeline can parse.

    Grams/mg labels pass through; ounce labels (``1/2oz``, ``1oz``, ``1/8oz``)
    are converted to grams since ``normalize._parse_size_grams`` only reads
    ``"<n>g"``.
    """
    if not option:
        return None
    opt = str(option).strip()
    low = opt.lower()
    if "g" in low and "oz" not in low:  # already gram/mg labelled
        return opt
    if low in _OZ_TO_GRAMS:
        return f"{_OZ_TO_GRAMS[low]:g}g"
    m = _OZ_FRACTION_RE.search(low)
    if m:
        num, den = float(m.group(1)), float(m.group(2))
        if den:
            return f"{num / den * 28.0:g}g"
    m = _OZ_WHOLE_RE.search(low)
    if m:
        return f"{float(m.group(1)) * 28.0:g}g"
    return opt


def _extract_image(src: dict) -> Optional[str]:
    img = src.get("primaryImage")
    if isinstance(img, str) and img.startswith("http"):
        return img
    images = src.get("images")
    if isinstance(images, list):
        for entry in images:
            if isinstance(entry, str) and entry.startswith("http"):
                return entry
    return None


def _effects(src: dict) -> list[str]:
    """Title-case the SHOUTY effect tokens (``HAPPY`` -> ``Happy``)."""
    out = []
    for e in src.get("effects") or []:
        if isinstance(e, str) and e.strip():
            out.append(e.strip().title())
    return out


def _rec_variants(src: dict) -> list[dict]:
    """Variants to surface: prefer RECREATIONAL (adult-use); fall back to all.

    De-dupes by ``option`` so the MEDICAL/RECREATIONAL twins of one size don't
    both surface.
    """
    variants = [v for v in (src.get("variants") or []) if isinstance(v, dict)]
    rec = [v for v in variants if str(v.get("menuType", "")).upper() == "RECREATIONAL"]
    chosen = rec or variants
    seen: set = set()
    out: list[dict] = []
    for v in chosen:
        opt = v.get("option")
        if opt in seen:
            continue
        seen.add(opt)
        out.append(v)
    return out


def _variant_prices(variant: dict) -> tuple[Optional[float], Optional[float]]:
    """Return ``(orig, sale)`` for a variant. ``specialPrice`` (when present and
    below ``price``) is the sale; otherwise sale == orig."""
    orig = _to_float(variant.get("price"))
    special = _to_float(variant.get("specialPrice"))
    sale = special if (special is not None and special > 0) else orig
    if orig is not None and sale is not None and sale > orig:
        sale = orig
    if orig is None:
        orig = sale
    return orig, sale


def _extract_promo(src: dict) -> dict:
    """Promo/special metadata from a JointCommerce product's ``applicableSpecials``.

    Each special carries a ``name``/``title`` and sometimes a ``daysOfWeek`` /
    ``schedule`` and validity window; we read those and let
    :func:`promo.build_promo` infer kind/audience/weekday from the text. Returns
    ``{}`` when the product has no applicable special.
    """
    specials = src.get("applicableSpecials") or src.get("specials")
    if isinstance(specials, dict):
        specials = [specials]
    if not isinstance(specials, list) or not specials:
        return {}

    title = description = valid_from = valid_to = None
    days: list[str] = []
    for sp in specials:
        if not isinstance(sp, dict):
            continue
        title = title or sp.get("name") or sp.get("title") or sp.get("displayName")
        description = description or sp.get("description") or sp.get("terms")
        valid_from = valid_from or sp.get("startDate") or sp.get("startStamp") or sp.get("validFrom")
        valid_to = valid_to or sp.get("endDate") or sp.get("endStamp") or sp.get("validTo")
        if not days:
            sched = sp.get("daysOfWeek") or sp.get("days") or sp.get("schedule")
            if isinstance(sched, (list, tuple)):
                days = _promo.parse_dow(" ".join(str(x) for x in sched))
            elif isinstance(sched, str):
                days = _promo.parse_dow(sched)
            elif isinstance(sched, dict):
                days = _promo.parse_dow(" ".join(sched.keys()))
    if not (title or description):
        return {}
    return _promo.build_promo(
        title=title,
        description=description,
        dow=days or None,
        valid_from=str(valid_from) if valid_from else None,
        valid_to=str(valid_to) if valid_to else None,
    )


# ---------------------------------------------------------------------------
# Pure parser (network-free, unit-tested against a fixture)
# ---------------------------------------------------------------------------
def _parse_source(src: dict) -> list[MenuItem]:
    """Expand one product ``_source`` into one ``MenuItem`` per (rec) variant."""
    name = src.get("name") or src.get("nameText")
    if not name:
        return []
    category = _map_category(src.get("category"))
    if category is None:
        return []

    thc = _to_float(src.get("potencyThcRangeHigh")) or _to_float(src.get("potencyThcDisplayValue"))
    cbd = _to_float(src.get("potencyCbdRangeHigh")) or _to_float(src.get("potencyCbdDisplayValue"))
    brand = src.get("brandName")
    img = _extract_image(src)
    strain = _map_strain_type(src.get("strainType"))
    desc = src.get("description")
    effects = _effects(src)
    promo = _extract_promo(src)

    items: list[MenuItem] = []
    for variant in _rec_variants(src):
        orig, sale = _variant_prices(variant)
        if orig is None:
            continue
        item: MenuItem = {
            "product": str(name),
            "brand": brand,
            "category": category,
            "orig": orig,
            "sale": sale,
            "size": _normalize_option(variant.get("option")),
            "thc": thc,
            "cbd": cbd,
            "type": strain,
            "img": img,
            "url": None,
            "in_stock": True,
            "desc": desc,
            "effects": effects,
        }
        item.update(promo)
        items.append(item)
    return items


def _find_hits(payload: Any) -> list[dict]:
    """Pull the product ``_source`` dicts out of an ES ``_search`` envelope.

    Tolerant of the full ``{hits: {hits: [...]}}`` envelope, a bare ``hits`` list,
    or a raw list of ``{_source: {...}}`` / product dicts.
    """
    if isinstance(payload, dict):
        hits = payload.get("hits")
        if isinstance(hits, dict):
            hits = hits.get("hits")
        if isinstance(hits, list):
            return [h.get("_source", h) for h in hits if isinstance(h, dict)]
        # Already a list of products under another key?
        if isinstance(payload.get("products"), list):
            return [p for p in payload["products"] if isinstance(p, dict)]
    if isinstance(payload, list):
        return [h.get("_source", h) if isinstance(h, dict) else {} for h in payload]
    return []


def parse_menu(payload: Any) -> list[MenuItem]:
    """Parse a JointCommerce ``_search`` payload into ``MenuItem`` dicts.

    Pure and network-free. Each product is expanded into one item per
    recreational variant (size). Unparseable rows and non-canonical categories
    (accessories, topicals, tinctures, …) are skipped.
    """
    out: list[MenuItem] = []
    for src in _find_hits(payload):
        if not isinstance(src, dict):
            continue
        try:
            out.extend(_parse_source(src))
        except Exception:
            continue
    return out


# ---------------------------------------------------------------------------
# Request helpers
# ---------------------------------------------------------------------------
def _host(menu_url: str) -> Optional[str]:
    parts = urlparse(menu_url or "")
    if not parts.scheme or not parts.netloc:
        return None
    return f"{parts.scheme}://{parts.netloc}"


def _search_body(business_id: str, frm: int, size: int) -> dict:
    return {
        "size": size,
        "from": frm,
        "_source": {"includes": _SOURCE_INCLUDES},
        "query": {"bool": {"filter": [
            {"bool": {"should": [{"term": {"businessId": str(business_id)}}]}},
            {"bool": {"should": [{"term": {"menuType": "RECREATIONAL"}}]}},
        ]}},
        "sort": [{"uniquePurchases": "desc"}],
    }


# ---------------------------------------------------------------------------
# Playwright fallback (only if httpx ever returns nothing) — never leaks browsers
# ---------------------------------------------------------------------------
def _fetch_via_playwright(host: str, business_id: str, user_agent: str) -> list[MenuItem]:
    """Issue the ``_search`` from the site origin in a real browser and parse it.

    The endpoint is normally httpx-readable, so this only runs if the fast path
    yields nothing. The browser is ALWAYS closed via the context manager +
    ``finally``. Returns ``[]`` on any failure.
    """
    try:
        from playwright.sync_api import sync_playwright  # local import: optional dep
    except Exception:
        return []

    url = f"{host}{_SEARCH_PATH}"
    js = """
    async ({url, businessId, includes, pages, pageSize}) => {
      const out = [];
      for (let p = 0; p < pages; p++) {
        const body = {
          size: pageSize, from: p * pageSize,
          _source: { includes },
          query: { bool: { filter: [
            { bool: { should: [{ term: { businessId: String(businessId) } }] } },
            { bool: { should: [{ term: { menuType: "RECREATIONAL" } }] } },
          ] } },
          sort: [{ uniquePurchases: "desc" }],
        };
        try {
          const r = await fetch(url, {
            method: "POST",
            headers: { "Content-Type": "application/json", "Accept": "application/json" },
            body: JSON.stringify(body),
          });
          if (!r.ok) break;
          const j = await r.json();
          const hits = (j && j.hits && j.hits.hits) || [];
          if (!hits.length) break;
          out.push(...hits);
          if (hits.length < pageSize) break;
        } catch (e) { break; }
      }
      return out;
    }
    """
    out: list[MenuItem] = []
    try:
        with sync_playwright() as pw:
            browser = pw.chromium.launch(
                headless=True, args=["--disable-blink-features=AutomationControlled"]
            )
            try:
                context = browser.new_context(
                    user_agent=user_agent, locale="en-US",
                    viewport={"width": 1366, "height": 900},
                )
                page = context.new_page()
                try:
                    page.goto(host + "/", wait_until="domcontentloaded", timeout=_PW_NAV_TIMEOUT_MS)
                except Exception:
                    pass
                try:
                    hits = page.evaluate(js, {
                        "url": url, "businessId": str(business_id),
                        "includes": _SOURCE_INCLUDES, "pages": _MAX_PAGES, "pageSize": _PAGE_SIZE,
                    })
                except Exception:
                    hits = None
                if hits:
                    out = parse_menu(hits)
            finally:
                browser.close()
    except Exception:
        return out
    return out


# ---------------------------------------------------------------------------
# Adapter
# ---------------------------------------------------------------------------
class ProprietaryAdapter:
    """Best-effort JointCommerce ("joint-ecommerce") menu adapter (see module
    docstring).

    Implements the :class:`app.adapters.base.Adapter` protocol. ``fetch`` reads
    ``store_ref['menu']`` (for the site host) and ``store_ref['business_id']``,
    pages the ``_search`` endpoint over httpx, and parses each page via
    :func:`parse_menu`. Falls back to a single headless-Playwright pass only if
    httpx returns nothing. Any failure yields ``[]``.
    """

    def __init__(self, user_agent: Optional[str] = None) -> None:
        self._user_agent = user_agent or os.getenv("SCRAPE_USER_AGENT") or _DEFAULT_UA

    def _headers(self, host: str) -> dict[str, str]:
        return {
            "User-Agent": self._user_agent,
            "Content-Type": "application/json",
            "Accept": "application/json",
            "Origin": host,
            "Referer": host + "/",
        }

    def _business_id(self, store_ref: dict[str, Any]) -> Optional[str]:
        bid = store_ref.get("business_id") or store_ref.get("businessId")
        return str(bid) if bid not in (None, "") else None

    def fetch(self, store_ref: dict[str, Any]) -> list[MenuItem]:
        """Return the store's menu as ``MenuItem`` dicts (``[]`` on any failure)."""
        host = _host(store_ref.get("menu") or store_ref.get("menu_ref") or "")
        business_id = self._business_id(store_ref)
        if not host or not business_id:
            return []

        items: list[MenuItem] = []
        start = time.monotonic()
        try:
            with httpx.Client(
                timeout=_TIMEOUT_SEC, follow_redirects=True, headers=self._headers(host)
            ) as client:
                for page_no in range(_MAX_PAGES):
                    if time.monotonic() - start > _STORE_BUDGET_SEC:
                        break
                    if page_no > 0:
                        time.sleep(_POLITE_DELAY_SEC)
                    try:
                        resp = client.post(
                            host + _SEARCH_PATH,
                            json=_search_body(business_id, page_no * _PAGE_SIZE, _PAGE_SIZE),
                        )
                    except Exception:
                        break
                    if resp.status_code != 200:
                        break
                    try:
                        payload = resp.json()
                    except Exception:
                        break
                    hits = _find_hits(payload)
                    if not hits:
                        break
                    items.extend(parse_menu(payload))
                    if len(hits) < _PAGE_SIZE:
                        break
        except Exception:
            items = []

        if items:
            return items

        if os.getenv("SCRAPE_NO_BROWSER"):
            return []
        # httpx came back empty (future block) -> single browser fallback.
        return _fetch_via_playwright(host, business_id, self._user_agent)
