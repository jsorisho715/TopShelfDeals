"""Leafly menu adapter (free, public).

Strategy: Leafly is a Next.js site that **server-side renders** each dispensary
menu and embeds the full page state — including the product list — in a
``<script id="__NEXT_DATA__" type="application/json">`` blob. Unlike Dutchie,
Leafly does NOT gate this behind Cloudflare and does NOT require a network XHR to
load the first page of products, so the fast path is a plain ``httpx`` GET of the
menu URL followed by a regex extract + ``json.loads`` of that blob.

The product array lives at ``props.pageProps.menuData.menuItems``. Each item
carries ``name`` (e.g. ``"Connected - Flower - Jack of Diamonds (S) (3.5g)"``),
``brandName``, ``productCategory``, ``price`` (regular), ``sortPrice``
(effective/discounted), ``thcContent``/``cbdContent``, ``imageUrl``, and a
``variants`` list. Strain type and weight are encoded in the trailing ``(H)``/
``(I)``/``(S)`` and ``(3.5g)`` tokens of ``name``.

The JSON → ``MenuItem`` mapping is the pure, network-free :func:`parse_menu` so
it can be unit-tested against a fixture.

Coverage: Leafly SSRs only ~18 items per page, so :meth:`LeaflyAdapter.fetch`
requests the **Flower-filtered** menu (``?product_category=Flower``) across a few
pages and combines them — this is how we surface allowlisted top-shelf flower
that would otherwise be buried below the default popularity sort. It also pulls
the unfiltered first page so prerolls/edibles/concentrates/vapes are represented.

Robustness (PRD FR2 / Adapter protocol): every request is bounded by a timeout
and a global ~40s/store budget, requests are sequential with a polite delay, and
on ANY failure :meth:`fetch` returns ``[]`` instead of raising. If httpx somehow
yields no ``__NEXT_DATA__`` at all (e.g. a future block), it falls back ONCE to a
headless Playwright render that is always closed via a context manager + finally
(never leak browsers). Set ``SCRAPE_NO_BROWSER=1`` to disable that fallback.
"""

from __future__ import annotations

import json
import os
import re
import time
from typing import Any, Optional
from urllib.parse import urlencode, urlparse, urlunparse

import httpx

from . import promo as _promo
from .base import MenuItem

_TIMEOUT_SEC = 20.0
# Per-store wall-clock budget across all page requests (politeness/bound).
_STORE_BUDGET_SEC = 40.0
# Polite gap between sequential page requests to one host.
_POLITE_DELAY_SEC = float(os.getenv("LEAFLY_DELAY_SEC", "1.2"))
# How many Flower-filtered pages to page through (18 items each).
_FLOWER_PAGES = int(os.getenv("LEAFLY_FLOWER_PAGES", "3"))
_PW_NAV_TIMEOUT_MS = 30000

_DEFAULT_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
)

# Pull the embedded Next.js state blob out of a rendered menu page.
_NEXT_DATA_RE = re.compile(
    r'<script id="__NEXT_DATA__" type="application/json">(.*?)</script>',
    re.S,
)

# Trailing weight token in a Leafly product name, e.g. "(3.5g)" / "(100mg)" / "(1.0g)".
_SIZE_RE = re.compile(r"\(\s*([\d.]+\s*(?:mg|g|oz))\s*\)", re.I)
# Strain-type token in a Leafly product name, e.g. "(H)" / "(I)" / "(S)".
_STRAIN_TOKEN_RE = re.compile(r"\(\s*(H|I|S)\s*\)")

# Leafly ``productCategory`` strings -> our canonical category names. Anything
# not mapped here (e.g. "Accessory", "Topical", "Tincture") is dropped.
_CATEGORY_MAP = {
    "flower": "Flower",
    "preroll": "Prerolls",
    "pre-roll": "Prerolls",
    "prerolls": "Prerolls",
    "pre-rolls": "Prerolls",
    "edible": "Edibles",
    "edibles": "Edibles",
    "concentrate": "Concentrates",
    "concentrates": "Concentrates",
    "extract": "Concentrates",
    "extracts": "Concentrates",
    "cartridge": "Vapes",
    "cartridges": "Vapes",
    "vaporizer": "Vapes",
    "vaporizers": "Vapes",
    "vape": "Vapes",
    "vapes": "Vapes",
    "disposable": "Vapes",
}

_STRAIN_TYPE_MAP = {
    "h": "Hybrid",
    "i": "Indica",
    "s": "Sativa",
    "hybrid": "Hybrid",
    "indica": "Indica",
    "sativa": "Sativa",
}


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


def _map_category(raw: Optional[str]) -> Optional[str]:
    if not raw:
        return None
    return _CATEGORY_MAP.get(str(raw).strip().lower())


def _map_strain_type(raw: Optional[str]) -> Optional[str]:
    if not raw:
        return None
    return _STRAIN_TYPE_MAP.get(str(raw).strip().lower())


def _extract_brand(item: dict) -> Optional[str]:
    brand = item.get("brandName")
    if isinstance(brand, str) and brand.strip():
        return brand
    b = item.get("brand")
    if isinstance(b, dict):
        return b.get("name") or b.get("Name")
    if isinstance(b, str):
        return b
    return None


def _extract_image(item: dict) -> Optional[str]:
    """First usable image URL. Leafly exposes a clean ``imageUrl`` plus an imgix
    ``formattedThumbnailUrl``/``thumbnailUrl`` fallback."""
    for key in ("imageUrl", "formattedThumbnailUrl", "thumbnailUrl"):
        val = item.get(key)
        if isinstance(val, str) and val.startswith("http"):
            return val
    return None


def _extract_size(item: dict) -> Optional[str]:
    """Weight/size label. Leafly buries it in the trailing ``(3.5g)`` token of
    ``name`` (``displayQuantity`` is just ``"1each"``)."""
    name = item.get("name") or ""
    matches = _SIZE_RE.findall(name)
    if matches:
        return matches[-1].replace(" ", "")
    # Fallback: a normalized label like "3.5g" if Leafly ever provides one.
    for key in ("normalizedQuantityLabel", "displayQuantity"):
        val = item.get(key)
        if isinstance(val, str) and re.search(r"\d", val) and "each" not in val.lower():
            return val
    return None


def _extract_strain_type(item: dict) -> Optional[str]:
    """Strain type from the ``(H)``/``(I)``/``(S)`` token in ``name``, falling
    back to a leading word in ``strainName`` (e.g. ``"Indica (I)"``)."""
    name = item.get("name") or ""
    m = _STRAIN_TOKEN_RE.search(name)
    if m:
        return _map_strain_type(m.group(1))
    strain = item.get("strainName")
    if isinstance(strain, str) and strain:
        first = strain.strip().split()[0].lower()
        mapped = _map_strain_type(first)
        if mapped:
            return mapped
    return None


def _variant_discounted_price(variant: dict) -> Optional[float]:
    """A variant's effective price: ``deal.discountedPrice`` is in cents."""
    deal = variant.get("deal")
    if isinstance(deal, dict):
        cents = deal.get("discountedPrice")
        f = _to_float(cents)
        if f is not None and f > 0:
            return round(f / 100.0, 2)
    return None


def _extract_prices(item: dict) -> tuple[Optional[float], Optional[float]]:
    """Return ``(orig, sale)``.

    ``price`` is the regular price; ``sortPrice`` is Leafly's effective
    (discount-applied) price. When neither resolves at the top level we fall back
    to the first variant's ``price`` and its ``deal.discountedPrice``. ``sale`` is
    always clamped to ``<= orig``.
    """
    orig = _to_float(item.get("price"))
    sale = _to_float(item.get("sortPrice"))

    variants = item.get("variants")
    if isinstance(variants, list) and variants:
        first = variants[0] if isinstance(variants[0], dict) else {}
        if orig is None:
            orig = _to_float(first.get("price"))
        disc = _variant_discounted_price(first)
        if disc is not None:
            sale = disc if sale is None else min(sale, disc)

    if sale is None:
        sale = orig
    if orig is not None and sale is not None and sale > orig:
        sale = orig
    return orig, sale


def _extract_in_stock(item: dict) -> bool:
    stock = item.get("stockQuantity")
    if isinstance(stock, (int, float)):
        return stock > 0
    val = item.get("inStock")
    if isinstance(val, bool):
        return val
    return True


# ---------------------------------------------------------------------------
# Pure parser (network-free, unit-tested against a fixture)
# ---------------------------------------------------------------------------
def _deal_node(item: dict) -> Optional[dict]:
    """The item-level Leafly ``deal`` object, if present (top-level or first variant)."""
    deal = item.get("deal")
    if isinstance(deal, dict):
        return deal
    variants = item.get("variants")
    if isinstance(variants, list) and variants and isinstance(variants[0], dict):
        d = variants[0].get("deal")
        if isinstance(d, dict):
            return d
    return None


def _extract_promo(item: dict) -> dict:
    """Promo/special metadata from a Leafly menu item.

    Leafly attaches a ``deal`` object (``dealLabel``/``label``/``title`` +
    ``dealDescription``) to discounted items. We read the human label/description
    and let :func:`promo.build_promo` infer kind/audience/weekday from the text.
    Returns ``{}`` when the item carries no labeled deal.
    """
    deal = _deal_node(item)
    if not deal:
        return {}
    title = (
        deal.get("dealLabel")
        or deal.get("label")
        or deal.get("title")
        or deal.get("name")
        or deal.get("dealTitle")
    )
    description = deal.get("dealDescription") or deal.get("description") or deal.get("terms")
    valid_from = deal.get("startDate") or deal.get("validFrom") or deal.get("startsAt")
    valid_to = deal.get("endDate") or deal.get("validTo") or deal.get("expiresAt") or deal.get("endsAt")
    if not (title or description):
        return {}
    return _promo.build_promo(
        title=title,
        description=description,
        valid_from=str(valid_from) if valid_from else None,
        valid_to=str(valid_to) if valid_to else None,
    )


def _extract_description(item: dict) -> Optional[str]:
    for key in ("description", "productDescription", "shortDescription"):
        val = item.get(key)
        if isinstance(val, str) and val.strip():
            return val.strip()
    strain = item.get("strain")
    if isinstance(strain, dict):
        val = strain.get("description")
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
                name = e.get("name") or e.get("effect")
                if isinstance(name, str) and name.strip():
                    out.append(name.strip())
    strain = item.get("strain")
    if not out and isinstance(strain, dict):
        eff = strain.get("effects")
        if isinstance(eff, list):
            for e in eff:
                if isinstance(e, str) and e.strip():
                    out.append(e.strip())
                elif isinstance(e, dict) and isinstance(e.get("name"), str):
                    out.append(e["name"].strip())
    return out


def _extract_lineage(item: dict) -> Optional[str]:
    strain = item.get("strain")
    if isinstance(strain, dict):
        for key in ("lineage", "genetics", "parents"):
            val = strain.get(key)
            if isinstance(val, str) and val.strip():
                return val.strip()
    for key in ("lineage", "genetics"):
        val = item.get(key)
        if isinstance(val, str) and val.strip():
            return val.strip()
    return None


def _parse_one(item: dict) -> Optional[MenuItem]:
    name = item.get("name") or item.get("productName")
    if not name:
        return None
    category = _map_category(item.get("productCategory") or item.get("category"))
    if category is None:
        # Skip accessories / topicals / anything outside our 5 canonical cats.
        return None

    orig, sale = _extract_prices(item)

    parsed: MenuItem = {
        "product": str(name),
        "brand": _extract_brand(item),
        "category": category,
        "orig": orig,
        "sale": sale,
        "size": _extract_size(item),
        "thc": _to_float(item.get("thcContent")),
        "cbd": _to_float(item.get("cbdContent")),
        "type": _extract_strain_type(item),
        "img": _extract_image(item),
        "in_stock": _extract_in_stock(item),
        "desc": _extract_description(item),
        "effects": _extract_effects(item),
        "lineage": _extract_lineage(item),
    }
    parsed.update(_extract_promo(item))
    return parsed


def _find_menu_items(data: Any) -> list[dict]:
    """Locate the product list inside a Leafly payload, tolerantly.

    Accepts the full ``__NEXT_DATA__`` dict, a bare ``pageProps``/``menuData``
    dict, or a raw list of items. Looks under ``menuData.menuItems`` first, then
    ``menuData.items``/``menuData.products``, then top-level ``menuItems``/
    ``items``/``products``.
    """
    if isinstance(data, list):
        return [x for x in data if isinstance(x, dict)]
    if not isinstance(data, dict):
        return []

    # Drill into the Next.js envelope if present.
    node: Any = data
    props = node.get("props")
    if isinstance(props, dict):
        page_props = props.get("pageProps")
        if isinstance(page_props, dict):
            node = page_props

    candidates: list[Any] = []
    menu_data = node.get("menuData") if isinstance(node, dict) else None
    if isinstance(menu_data, dict):
        candidates += [
            menu_data.get("menuItems"),
            menu_data.get("items"),
            menu_data.get("products"),
        ]
    if isinstance(node, dict):
        candidates += [node.get("menuItems"), node.get("items"), node.get("products")]
    # Last resort: the raw dict might itself carry the keys.
    candidates += [data.get("menuItems"), data.get("items"), data.get("products")]

    for cand in candidates:
        if isinstance(cand, list) and cand:
            return [x for x in cand if isinstance(x, dict)]
    return []


def parse_menu(data: Any) -> list[MenuItem]:
    """Parse a Leafly ``__NEXT_DATA__``/``menuData`` payload into ``MenuItem`` dicts.

    Pure and network-free. Tolerant of where the product array lives (see
    :func:`_find_menu_items`). Unparseable rows and non-canonical categories
    (accessories, topicals, …) are skipped.
    """
    items: list[MenuItem] = []
    for raw in _find_menu_items(data):
        try:
            parsed = _parse_one(raw)
        except Exception:
            parsed = None
        if parsed is not None:
            items.append(parsed)
    return items


# ---------------------------------------------------------------------------
# URL helpers
# ---------------------------------------------------------------------------
def _menu_base_url(menu_url: str) -> str:
    """Normalize a stored dispensary URL to its ``/menu`` page (no query)."""
    parts = urlparse(menu_url)
    path = parts.path.rstrip("/")
    if not path.endswith("/menu"):
        path = path + "/menu"
    return urlunparse((parts.scheme or "https", parts.netloc, path, "", "", ""))


def _page_url(base_menu_url: str, category: Optional[str], page: int) -> str:
    params: dict[str, Any] = {}
    if category:
        params["product_category"] = category
    if page > 1:
        params["page"] = page
    parts = urlparse(base_menu_url)
    query = urlencode(params)
    return urlunparse((parts.scheme, parts.netloc, parts.path, "", query, ""))


def _extract_next_data(html: str) -> Optional[dict]:
    m = _NEXT_DATA_RE.search(html or "")
    if not m:
        return None
    try:
        return json.loads(m.group(1))
    except Exception:
        return None


def _dispensary_slug(menu_url: str) -> Optional[str]:
    """The ``<slug>`` from a ``/dispensary-info/<slug>/menu`` URL."""
    segs = [s for s in urlparse(menu_url).path.split("/") if s]
    if "dispensary-info" in segs:
        i = segs.index("dispensary-info")
        if i + 1 < len(segs):
            return segs[i + 1]
    return None


def _product_url(base_menu_url: str, raw: dict) -> Optional[str]:
    """Deep link to a specific Leafly menu item: ``/dispensary-info/<slug>/p/<id>[?variant=<vid>]``."""
    slug = _dispensary_slug(base_menu_url)
    pid = raw.get("id") or raw.get("menuItemId") or raw.get("externalKey")
    if not slug or pid is None:
        return None
    url = f"https://www.leafly.com/dispensary-info/{slug}/p/{pid}"
    variants = raw.get("variants")
    if isinstance(variants, list) and variants and isinstance(variants[0], dict):
        vid = variants[0].get("id")
        if vid is not None:
            url += f"?variant={vid}"
    return url


# ---------------------------------------------------------------------------
# Playwright fallback (only if httpx ever returns no __NEXT_DATA__ at all)
# ---------------------------------------------------------------------------
def _fetch_html_via_playwright(url: str, user_agent: str) -> Optional[str]:
    """Render ``url`` once headless and return its HTML, or ``None`` on failure.

    The browser is ALWAYS closed via ``sync_playwright``'s context manager plus a
    ``finally`` — we never leak Chromium processes.
    """
    try:
        from playwright.sync_api import sync_playwright  # local import: optional dep
    except Exception:
        return None

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
                    page.goto(url, wait_until="domcontentloaded", timeout=_PW_NAV_TIMEOUT_MS)
                except Exception:
                    pass
                try:
                    return page.content()
                except Exception:
                    return None
            finally:
                browser.close()
    except Exception:
        return None


# ---------------------------------------------------------------------------
# Adapter
# ---------------------------------------------------------------------------
class LeaflyAdapter:
    """Best-effort Leafly menu adapter (see module docstring).

    Implements the :class:`app.adapters.base.Adapter` protocol. ``fetch`` reads
    ``store_ref['menu']``, pulls the Flower-filtered menu across a few pages plus
    the unfiltered first page, parses each via :func:`parse_menu`, and dedups by
    product id. Any failure yields ``[]``.
    """

    def __init__(self, user_agent: Optional[str] = None) -> None:
        self._user_agent = user_agent or os.getenv("SCRAPE_USER_AGENT") or _DEFAULT_UA

    def _headers(self) -> dict[str, str]:
        return {
            "User-Agent": self._user_agent,
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Accept-Language": "en-US,en;q=0.9",
            "Referer": "https://www.leafly.com/",
        }

    def _get_next_data(self, client: httpx.Client, url: str) -> Optional[dict]:
        try:
            resp = client.get(url)
        except Exception:
            return None
        if resp.status_code != 200:
            return None
        return _extract_next_data(resp.text)

    def fetch(self, store_ref: dict[str, Any]) -> list[MenuItem]:
        """Return the store's menu as ``MenuItem`` dicts (``[]`` on any failure)."""
        menu_url = store_ref.get("menu") or store_ref.get("menu_ref") or ""
        if not menu_url:
            return []
        base = _menu_base_url(menu_url)

        # Page plan: Flower pages first (the coverage goal), then the unfiltered
        # first page to represent the other categories.
        plan: list[tuple[Optional[str], int]] = [
            ("Flower", p) for p in range(1, _FLOWER_PAGES + 1)
        ]
        plan.append((None, 1))

        start = time.monotonic()
        by_id: dict[Any, MenuItem] = {}
        ordered: list[MenuItem] = []
        any_next_data = False

        try:
            with httpx.Client(
                timeout=_TIMEOUT_SEC, follow_redirects=True, headers=self._headers()
            ) as client:
                for idx, (category, page) in enumerate(plan):
                    if time.monotonic() - start > _STORE_BUDGET_SEC:
                        break
                    if idx > 0:
                        time.sleep(_POLITE_DELAY_SEC)
                    url = _page_url(base, category, page)
                    data = self._get_next_data(client, url)
                    if data is None:
                        continue
                    any_next_data = True
                    raw_items = _find_menu_items(data)
                    self._merge(raw_items, by_id, ordered, base)
        except Exception:
            pass

        # Fallback: only if httpx never saw an embedded blob (possible future
        # block). One headless render of the Flower page, browser always closed.
        if not any_next_data and not os.getenv("SCRAPE_NO_BROWSER"):
            html = _fetch_html_via_playwright(_page_url(base, "Flower", 1), self._user_agent)
            data = _extract_next_data(html or "")
            if data is not None:
                self._merge(_find_menu_items(data), by_id, ordered, base)

        return ordered

    @staticmethod
    def _merge(
        raw_items: list[dict], by_id: dict[Any, MenuItem], ordered: list[MenuItem], base: str = ""
    ) -> None:
        for raw in raw_items:
            key = raw.get("id") or raw.get("menuItemId") or raw.get("externalKey")
            if key is not None and key in by_id:
                continue
            try:
                parsed = _parse_one(raw)
            except Exception:
                parsed = None
            if parsed is None:
                continue
            # Deep link straight to the product/special (not the store menu).
            parsed["url"] = _product_url(base, raw)
            if key is not None:
                by_id[key] = parsed
            ordered.append(parsed)
