"""Weedmaps menu adapter.

Strategy: Weedmaps storefronts are a Next.js SPA whose product grid is hydrated
client-side from the public **discovery API**:

    https://api-g.weedmaps.com/discovery/v1/listings/dispensaries/<slug>/menu_items
        ?sort_by=position&page=1&page_size=100

That endpoint returns ``{"meta": {...}, "data": {"menu_items": [ <item>, ... ]}}``.
The page's ``__NEXT_DATA__`` blob carries no products (``pageProps`` is empty), so
unlike Leafly the fast path is the JSON API rather than an SSR scrape.

Critical schema quirks learned from live captures (Scottsdale-area menus):

* The top-level ``brand`` is almost always ``null``. The real brand lives in
  ``brand_endorsement.brand_name`` (e.g. ``"Alien Labs"``, ``"Wizard Trees"``,
  ``"Mohave Cannabis Co."``). :func:`parse_menu` reads that first.
* ``category`` is the *strain type* for flower (``{"name": "Indica"}``); the actual
  product category is the leaf taxonomy node in ``edge_category`` (``"Flower"`` /
  ``"Big Buds"`` / ``"Smalls"`` / ``"Gummies"`` / ``"Cartridge"`` …) whose
  ``ancestors`` resolve up to one of our five canonical cats.
* The displayed price is the ``price`` object: ``price.price`` is the current
  (sale) price, ``price.original_price`` the regular price, ``price.on_sale`` the
  flag, and ``price.compliance_net_mg`` the *priced* net weight (3500 → 3.5g) —
  more reliable than the weight printed in ``name``.
* The product image is ``avatar_image.large_url``/``original_url`` (NOT
  ``brand_endorsement.brand_avatar_image_url``, which is the brand logo, nor
  ``lab_avatar_image``, which is a Weedmaps placeholder).

The JSON → ``MenuItem`` mapping is the pure, network-free :func:`parse_menu` so it
can be unit-tested against a fixture.

Robustness (Adapter protocol / PRD FR2): Weedmaps fronts ``api-g`` and the site
behind Akamai, which 406s plain ``httpx`` (TLS fingerprint). :meth:`fetch` still
tries httpx **first** (cheap, and may work from some networks / in future), and
only when that yields nothing falls back ONCE to a headless Playwright session
that calls the same API from a real browser context. The browser is ALWAYS closed
via ``sync_playwright``'s context manager plus a ``finally`` — we never leak
Chromium processes. On ANY failure :meth:`fetch` returns ``[]`` instead of raising.
Set ``SCRAPE_NO_BROWSER=1`` to disable the browser fallback.
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

_API_BASE = "https://api-g.weedmaps.com/discovery/v1/listings/dispensaries"
_TIMEOUT_SEC = 20.0
# Per-store wall-clock budget across all page requests (politeness/bound).
_STORE_BUDGET_SEC = 45.0
_POLITE_DELAY_SEC = float(os.getenv("WEEDMAPS_DELAY_SEC", "1.2"))
# Pages of 100 items to pull (covers a full menu without hammering).
_MAX_PAGES = int(os.getenv("WEEDMAPS_PAGES", "3"))
_PAGE_SIZE = 100
_PW_NAV_TIMEOUT_MS = 45000

_DEFAULT_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
)

# Weedmaps taxonomy slugs/names -> our canonical category. Weedmaps uses a deep
# tree (Flower > Big Buds / Smalls / Ground / Infused Flower, etc.), so we map
# both leaf nodes and their parents; :func:`_map_category` also walks ancestors.
_CATEGORY_MAP = {
    # Flower
    "flower": "Flower",
    "smalls": "Flower",
    "big-buds": "Flower",
    "big buds": "Flower",
    "ground": "Flower",
    "shake": "Flower",
    "infused-flower": "Flower",
    "infused flower": "Flower",
    "premium-flower": "Flower",
    # Prerolls
    "pre-rolls": "Prerolls",
    "pre-roll": "Prerolls",
    "prerolls": "Prerolls",
    "preroll": "Prerolls",
    "joints": "Prerolls",
    "infused-pre-roll": "Prerolls",
    "infused-pre-rolls": "Prerolls",
    "infused pre-rolls": "Prerolls",
    "infused-joints": "Prerolls",
    "infused-minis": "Prerolls",
    "blunts": "Prerolls",
    "packs": "Prerolls",
    # Edibles
    "edibles": "Edibles",
    "edible": "Edibles",
    "gummies": "Edibles",
    "chocolates": "Edibles",
    "baked-goods": "Edibles",
    "baked goods": "Edibles",
    "mints": "Edibles",
    "cooking": "Edibles",
    "beverages": "Edibles",
    "drinks": "Edibles",
    "hard-candy": "Edibles",
    "capsules": "Edibles",
    "tablets": "Edibles",
    "lozenges": "Edibles",
    # Concentrates
    "concentrates": "Concentrates",
    "concentrate": "Concentrates",
    "solvent": "Concentrates",
    "badder": "Concentrates",
    "batter": "Concentrates",
    "shatter": "Concentrates",
    "sugar": "Concentrates",
    "crumble": "Concentrates",
    "sauce": "Concentrates",
    "hte": "Concentrates",
    "crystalline": "Concentrates",
    "diamonds": "Concentrates",
    "solvent-diamonds": "Concentrates",
    "solventless": "Concentrates",
    "rosin": "Concentrates",
    "jam": "Concentrates",
    "fresh-press": "Concentrates",
    "cold-cure-badder": "Concentrates",
    "kief": "Concentrates",
    "ice-water-hash": "Concentrates",
    "temple-ball": "Concentrates",
    "live-resin": "Concentrates",
    "wax": "Concentrates",
    "budder": "Concentrates",
    "hash": "Concentrates",
    "extracts": "Concentrates",
    "extract": "Concentrates",
    # Vapes
    "vapes": "Vapes",
    "vape": "Vapes",
    "vape-pens": "Vapes",
    "cartridge": "Vapes",
    "cartridges": "Vapes",
    "disposable": "Vapes",
    "disposables": "Vapes",
    "pods": "Vapes",
    "batteries": "Vapes",
}

_STRAIN_TYPE_MAP = {
    "indica": "Indica",
    "sativa": "Sativa",
    "hybrid": "Hybrid",
    "indica-dominant": "Indica",
    "sativa-dominant": "Sativa",
    "indica dominant": "Indica",
    "sativa dominant": "Sativa",
    "hybrid-indica": "Hybrid",
    "hybrid-sativa": "Hybrid",
    "i": "Indica",
    "s": "Sativa",
    "h": "Hybrid",
}

# Weight/size token in a product name, e.g. "3.5g" / "14g" / "1g" / "100mg" / "1/8 oz".
_SIZE_RE = re.compile(r"([\d.]+\s*(?:mg|g|oz))", re.I)

_PER_DOSE_CATS = {"Edibles"}


# ---------------------------------------------------------------------------
# Small parse helpers
# ---------------------------------------------------------------------------
def _to_float(value: Any) -> Optional[float]:
    if value is None or value == "":
        return None
    if isinstance(value, (int, float)):
        return float(value)
    try:
        return float(str(value).replace("$", "").replace(",", "").strip())
    except (ValueError, TypeError):
        return None


def _map_category(item: dict) -> Optional[str]:
    """Resolve our canonical category from a Weedmaps item.

    Prefers ``edge_category`` (the leaf taxonomy node), checking its ``slug`` /
    ``name`` then walking up its ``ancestors`` (so ``Big Buds`` → ``Flower``).
    Falls back to the legacy ``category``/``category_name`` strings.
    """
    edge = item.get("edge_category")
    if isinstance(edge, dict):
        for key in ("slug", "name"):
            mapped = _CATEGORY_MAP.get(str(edge.get(key) or "").strip().lower())
            if mapped:
                return mapped
        for anc in edge.get("ancestors") or []:
            if isinstance(anc, dict):
                for key in ("slug", "name"):
                    mapped = _CATEGORY_MAP.get(str(anc.get(key) or "").strip().lower())
                    if mapped:
                        return mapped
    # Fallbacks: some payloads carry a flat category string.
    cat = item.get("category")
    if isinstance(cat, dict):
        # NB: for flower this is the strain type ("Indica") — only useful if it
        # happens to be one of our cats (it usually isn't), so this is a last try.
        mapped = _CATEGORY_MAP.get(str(cat.get("slug") or cat.get("name") or "").strip().lower())
        if mapped:
            return mapped
    flat = item.get("category_name") or (cat if isinstance(cat, str) else None)
    return _CATEGORY_MAP.get(str(flat or "").strip().lower())


def _map_strain_type(raw: Any) -> Optional[str]:
    if raw is None:
        return None
    if isinstance(raw, dict):
        raw = raw.get("name") or raw.get("slug")
    return _STRAIN_TYPE_MAP.get(str(raw or "").strip().lower())


def _extract_brand(item: dict) -> Optional[str]:
    """Brand string. Weedmaps leaves ``brand`` null and puts the real brand in
    ``brand_endorsement.brand_name``; try that first, then any ``brand`` shape."""
    endo = item.get("brand_endorsement")
    if isinstance(endo, dict):
        name = endo.get("brand_name") or endo.get("name")
        if isinstance(name, str) and name.strip():
            return name.strip()
    brand = item.get("brand")
    if isinstance(brand, dict):
        name = brand.get("name") or brand.get("Name")
        if isinstance(name, str) and name.strip():
            return name.strip()
    if isinstance(brand, str) and brand.strip():
        return brand.strip()
    return item.get("brand_name")


def _extract_image(item: dict) -> Optional[str]:
    """First usable PRODUCT image URL (always captured when present).

    Uses ``avatar_image`` (the product photo). Deliberately ignores
    ``brand_endorsement.brand_avatar_image_url`` (brand logo) and
    ``lab_avatar_image`` (Weedmaps placeholder).
    """
    avatar = item.get("avatar_image")
    if isinstance(avatar, dict):
        for key in ("large_url", "original_url", "small_url", "url"):
            val = avatar.get(key)
            if isinstance(val, str) and val.startswith("http"):
                return val
    for key in ("image_url", "imageUrl"):
        val = item.get(key)
        if isinstance(val, str) and val.startswith("http"):
            return val
    images = item.get("images")
    if isinstance(images, list):
        for entry in images:
            if isinstance(entry, str) and entry.startswith("http"):
                return entry
            if isinstance(entry, dict):
                for key in ("large_url", "original_url", "url", "image_url"):
                    val = entry.get(key)
                    if isinstance(val, str) and val.startswith("http"):
                        return val
    return None


def _grams_from_net_mg(price: dict) -> Optional[float]:
    mg = _to_float(price.get("compliance_net_mg"))
    if mg and mg > 0:
        return round(mg / 1000.0, 3)
    return None


def _size_from_name(name: str) -> Optional[str]:
    matches = _SIZE_RE.findall(name or "")
    if matches:
        return matches[-1].replace(" ", "").lower()
    return None


def _extract_size(item: dict, category: Optional[str]) -> Optional[str]:
    """Weight/size label normalized to what the pipeline can parse ("3.5g" /
    "100mg").

    For weight categories the priced net weight (``compliance_net_mg`` →
    grams) is preferred because it reflects the *selected* price option (a "10g"
    jar sold by the 1/8 prices out at 3.5g). Edibles fall back to a mg token in
    the name. Both then fall back to a size token parsed from the name.
    """
    price = item.get("price") if isinstance(item.get("price"), dict) else {}
    if category in _PER_DOSE_CATS:
        from_name = _size_from_name(item.get("name") or "")
        if from_name and from_name.endswith("mg"):
            return from_name
        mg = _to_float(price.get("compliance_net_mg"))
        if mg and mg > 0:
            return f"{mg:g}mg"
        return from_name
    grams = _grams_from_net_mg(price) if price else None
    if grams:
        return f"{grams:g}g"
    return _size_from_name(item.get("name") or "")


def _extract_prices(item: dict) -> tuple[Optional[float], Optional[float]]:
    """Return ``(orig, sale)`` from the displayed ``price`` object.

    ``price.price`` is the current/sale price; ``price.original_price`` the
    regular price (used as ``orig`` only when ``on_sale`` and it exceeds sale).
    Falls back to the first entry of the ``prices`` per-unit map.
    """
    price = item.get("price")
    sale = orig = None
    if isinstance(price, dict):
        sale = _to_float(price.get("price"))
        on_sale = bool(price.get("on_sale"))
        op = _to_float(price.get("original_price"))
        if on_sale and op is not None and sale is not None and op > sale:
            orig = op
        else:
            orig = sale if op is None else max(op, sale) if sale is not None else op

    if sale is None:
        # Fallback: prices is a map of unit -> [ {price, ...} ] or a list.
        prices = item.get("prices")
        first = None
        if isinstance(prices, dict):
            for val in prices.values():
                if isinstance(val, list) and val:
                    first = val[0]
                    break
        elif isinstance(prices, list) and prices:
            first = prices[0]
        if isinstance(first, dict):
            sale = _to_float(first.get("price"))
            op = _to_float(first.get("original_price"))
            orig = op if (op is not None and (sale is None or op > sale)) else sale

    if orig is None:
        orig = sale
    if orig is not None and sale is not None and sale > orig:
        sale = orig
    return orig, sale


def _extract_potency(item: dict, code: str) -> Optional[float]:
    """THC/CBD percent from ``metrics.aggregates`` (or the cannabinoids list)."""
    metrics = item.get("metrics")
    if not isinstance(metrics, dict):
        return None
    agg = metrics.get("aggregates")
    if isinstance(agg, dict) and agg.get(code) is not None:
        val = _to_float(agg.get(code))
        if val is not None:
            return val
    for c in metrics.get("cannabinoids") or []:
        if isinstance(c, dict) and str(c.get("code") or "").lower() == code:
            return _to_float(c.get("value"))
    return None


def _extract_description(item: dict) -> Optional[str]:
    for key in ("body", "description", "details"):
        val = item.get(key)
        if isinstance(val, str) and val.strip():
            return val.strip()
    return None


def _extract_effects(item: dict) -> list:
    out: list[str] = []
    node = item.get("effects")
    if isinstance(node, list):
        for e in node:
            if isinstance(e, str) and e.strip():
                out.append(e.strip())
            elif isinstance(e, dict):
                name = e.get("name") or e.get("label")
                if isinstance(name, str) and name.strip():
                    out.append(name.strip())
    return out


def _extract_lineage(item: dict) -> Optional[str]:
    gen = item.get("genetics")
    if isinstance(gen, dict):
        val = gen.get("lineage") or gen.get("parents")
        if isinstance(val, str) and val.strip():
            return val.strip()
    if isinstance(gen, str) and gen.strip():
        return gen.strip()
    val = item.get("lineage")
    return val.strip() if isinstance(val, str) and val.strip() else None


def _extract_in_stock(item: dict) -> bool:
    if isinstance(item.get("is_online_orderable"), bool):
        if item["is_online_orderable"]:
            return True
    vis = item.get("price_visibility")
    if isinstance(vis, str):
        return vis.lower() == "visible"
    if isinstance(item.get("is_online_orderable"), bool):
        return item["is_online_orderable"]
    return True


def _extract_promo(item: dict) -> dict:
    """Promo/special metadata from a Weedmaps item's ``applicable_specials``.

    Each applicable special carries a ``title``/``name`` and often a
    ``scheduled_specials``/``schedule`` block with weekday windows; we read the
    title + any schedule and let :func:`promo.build_promo` infer kind/audience/
    weekday. Returns ``{}`` when the item has no applicable special.
    """
    specials = item.get("applicable_specials") or item.get("specials")
    if isinstance(specials, dict):
        specials = [specials]
    if not isinstance(specials, list) or not specials:
        return {}

    title = description = valid_from = valid_to = None
    days: list[str] = []
    for sp in specials:
        if not isinstance(sp, dict):
            continue
        title = title or sp.get("title") or sp.get("name") or sp.get("label")
        description = description or sp.get("description") or sp.get("subtitle")
        valid_from = valid_from or sp.get("start_date") or sp.get("starts_at") or sp.get("valid_from")
        valid_to = valid_to or sp.get("end_date") or sp.get("ends_at") or sp.get("valid_to")
        if not days:
            sched = sp.get("scheduled_specials") or sp.get("schedule") or sp.get("days")
            if isinstance(sched, dict):
                # e.g. {"monday": {...}, "wednesday": {...}}
                days = _promo.parse_dow(" ".join(k for k in sched.keys()))
            elif isinstance(sched, list):
                days = _promo.parse_dow(" ".join(str(x) for x in sched))
            elif isinstance(sched, str):
                days = _promo.parse_dow(sched)
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
def _parse_one(item: dict) -> Optional[MenuItem]:
    name = item.get("name") or item.get("title")
    if not name:
        return None
    category = _map_category(item)
    if category is None:
        # Skip accessories / gear / anything outside our 5 canonical cats.
        return None

    orig, sale = _extract_prices(item)

    parsed: MenuItem = {
        "product": str(name),
        "brand": _extract_brand(item),
        "category": category,
        "orig": orig,
        "sale": sale,
        "size": _extract_size(item, category),
        "thc": _extract_potency(item, "thc"),
        "cbd": _extract_potency(item, "cbd"),
        "type": _map_strain_type(item.get("category")),
        "img": _extract_image(item),
        "url": item.get("web_url") or item.get("url") or None,
        "in_stock": _extract_in_stock(item),
        "desc": _extract_description(item),
        "effects": _extract_effects(item),
        "lineage": _extract_lineage(item),
    }
    parsed.update(_extract_promo(item))
    return parsed


def _find_menu_items(data: Any) -> list[dict]:
    """Locate the product list inside a Weedmaps payload, tolerantly.

    Accepts the full ``{meta, data: {menu_items: [...]}}`` envelope, a bare
    ``data`` dict, or a raw list of items. Looks under ``data.menu_items`` first,
    then ``menu_items``/``menuItems``/``products``/``listings`` at either level.
    """
    if isinstance(data, list):
        return [x for x in data if isinstance(x, dict)]
    if not isinstance(data, dict):
        return []

    candidates: list[Any] = []
    inner = data.get("data")
    if isinstance(inner, dict):
        candidates += [
            inner.get("menu_items"),
            inner.get("menuItems"),
            inner.get("products"),
            inner.get("listings"),
        ]
    candidates += [
        data.get("menu_items"),
        data.get("menuItems"),
        data.get("products"),
        data.get("listings"),
    ]
    for cand in candidates:
        if isinstance(cand, list) and cand:
            return [x for x in cand if isinstance(x, dict)]
    return []


def parse_menu(json_dict: Any) -> list[MenuItem]:
    """Parse a Weedmaps ``menu_items`` payload into ``MenuItem`` dicts.

    Pure and network-free. Tolerant of where the product array lives (see
    :func:`_find_menu_items`) and of Weedmaps' schema variance (brand in
    ``brand_endorsement``, category in ``edge_category``, price in ``price``).
    Unparseable rows and non-canonical categories (accessories, gear, …) are
    skipped.
    """
    items: list[MenuItem] = []
    for raw in _find_menu_items(json_dict):
        try:
            parsed = _parse_one(raw)
        except Exception:
            parsed = None
        if parsed is not None:
            items.append(parsed)
    return items


# ---------------------------------------------------------------------------
# URL / slug helpers
# ---------------------------------------------------------------------------
def slug_from_menu_url(menu_url: str) -> Optional[str]:
    """Return the dispensary slug from a Weedmaps menu URL.

    ``https://weedmaps.com/dispensaries/sol-flower-1/menu`` -> ``sol-flower-1``.
    Drops a trailing ``/menu`` (or ``/deals`` / ``/reviews`` …) segment.
    """
    if not menu_url:
        return None
    path = urlparse(menu_url).path
    segments = [s for s in path.split("/") if s]
    if not segments:
        return None
    # .../dispensaries/<slug>[/menu|/deals|...]
    if "dispensaries" in segments:
        i = segments.index("dispensaries")
        if i + 1 < len(segments):
            return segments[i + 1]
    last = segments[-1]
    if last in ("menu", "deals", "reviews", "about", "info") and len(segments) >= 2:
        return segments[-2]
    return last


def menu_items_api_url(slug: str, page: int = 1, page_size: int = _PAGE_SIZE) -> str:
    # ``include[]=applicable_specials`` asks Weedmaps to embed the active special
    # objects (title/schedule/audience) on each item so we can capture promos.
    return (
        f"{_API_BASE}/{slug}/menu_items"
        f"?sort_by=position&page={page}&page_size={page_size}"
        f"&include[]=applicable_specials"
    )


# ---------------------------------------------------------------------------
# Playwright fallback (Akamai 406s plain httpx) — never leaks browsers
# ---------------------------------------------------------------------------
def _fetch_via_playwright(slug: str, user_agent: str) -> list[MenuItem]:
    """Call the menu_items API from a real Chromium context and parse it.

    Weedmaps' edge 406s non-browser TLS, but the same API is freely readable from
    a page on the ``weedmaps.com`` origin. We navigate there once (to establish
    origin/cookies), then ``fetch`` the JSON for a few pages in-page. The browser
    is ALWAYS closed via the context manager + ``finally``. Returns ``[]`` on any
    failure.
    """
    try:
        from playwright.sync_api import sync_playwright  # local import: optional dep
    except Exception:
        return []

    js = """
    async ({slug, page, pageSize}) => {
      const url = `https://api-g.weedmaps.com/discovery/v1/listings/dispensaries/${slug}/menu_items?sort_by=position&page=${page}&page_size=${pageSize}&include[]=applicable_specials`;
      try {
        const r = await fetch(url, { headers: { 'Accept': 'application/json' } });
        if (!r.ok) return { status: r.status, items: [] };
        const j = await r.json();
        const items = (j && j.data && (j.data.menu_items || j.data.products)) || [];
        return { status: r.status, items };
      } catch (e) {
        return { status: -1, items: [], error: String(e) };
      }
    }
    """

    out: list[MenuItem] = []
    start = time.monotonic()
    try:
        with sync_playwright() as pw:
            browser = pw.chromium.launch(
                headless=True,
                args=["--disable-blink-features=AutomationControlled"],
            )
            try:
                context = browser.new_context(
                    user_agent=user_agent,
                    locale="en-US",
                    viewport={"width": 1366, "height": 900},
                )
                page = context.new_page()
                try:
                    page.goto(
                        f"https://weedmaps.com/dispensaries/{slug}/menu",
                        wait_until="domcontentloaded",
                        timeout=_PW_NAV_TIMEOUT_MS,
                    )
                except Exception:
                    # Even a partial load establishes the origin for fetch().
                    pass
                try:
                    page.wait_for_timeout(1500)
                except Exception:
                    pass
                for page_no in range(1, _MAX_PAGES + 1):
                    if time.monotonic() - start > _STORE_BUDGET_SEC:
                        break
                    try:
                        res = page.evaluate(
                            js, {"slug": slug, "page": page_no, "pageSize": _PAGE_SIZE}
                        )
                    except Exception:
                        break
                    items = res.get("items") if isinstance(res, dict) else None
                    if not items:
                        break
                    out.extend(parse_menu({"data": {"menu_items": items}}))
                    if len(items) < _PAGE_SIZE:
                        break
            finally:
                browser.close()
    except Exception:
        return out
    return out


# ---------------------------------------------------------------------------
# Adapter
# ---------------------------------------------------------------------------
class WeedmapsAdapter:
    """Best-effort Weedmaps discovery-API adapter (see module docstring).

    Implements the :class:`app.adapters.base.Adapter` protocol. ``fetch`` reads
    ``store_ref['menu']``, resolves the dispensary slug, pulls the ``menu_items``
    API across a few pages, and parses each page via :func:`parse_menu`. Tries
    httpx first, then a single headless-Playwright fallback (Akamai usually 406s
    httpx). Any failure yields ``[]``.
    """

    def __init__(self, user_agent: Optional[str] = None) -> None:
        self._user_agent = user_agent or os.getenv("SCRAPE_USER_AGENT") or _DEFAULT_UA

    def _headers(self) -> dict[str, str]:
        return {
            "User-Agent": self._user_agent,
            "Accept": "application/json, text/plain, */*",
            "Accept-Language": "en-US,en;q=0.9",
            "Origin": "https://weedmaps.com",
            "Referer": "https://weedmaps.com/",
        }

    def _fetch_via_httpx(self, slug: str) -> list[MenuItem]:
        out: list[MenuItem] = []
        by_id: dict[Any, bool] = {}
        start = time.monotonic()
        try:
            with httpx.Client(
                timeout=_TIMEOUT_SEC, follow_redirects=True, headers=self._headers()
            ) as client:
                for page_no in range(1, _MAX_PAGES + 1):
                    if time.monotonic() - start > _STORE_BUDGET_SEC:
                        break
                    if page_no > 1:
                        time.sleep(_POLITE_DELAY_SEC)
                    try:
                        resp = client.get(menu_items_api_url(slug, page=page_no))
                    except Exception:
                        break
                    if resp.status_code != 200:
                        break
                    try:
                        payload = resp.json()
                    except Exception:
                        break
                    raw_items = _find_menu_items(payload)
                    if not raw_items:
                        break
                    for raw in raw_items:
                        key = raw.get("id")
                        if key is not None and key in by_id:
                            continue
                        try:
                            parsed = _parse_one(raw)
                        except Exception:
                            parsed = None
                        if parsed is None:
                            continue
                        if key is not None:
                            by_id[key] = True
                        out.append(parsed)
                    if len(raw_items) < _PAGE_SIZE:
                        break
        except Exception:
            return out
        return out

    def fetch(self, store_ref: dict[str, Any]) -> list[MenuItem]:
        """Return the store's menu as ``MenuItem`` dicts (``[]`` on any failure)."""
        menu_url = store_ref.get("menu") or store_ref.get("menu_ref") or ""
        slug = slug_from_menu_url(menu_url)
        if not slug:
            return []

        items = self._fetch_via_httpx(slug)
        if items:
            return items

        if os.getenv("SCRAPE_NO_BROWSER"):
            return []
        # httpx came back empty (almost always Akamai 406) -> browser fallback.
        return _fetch_via_playwright(slug, self._user_agent)
