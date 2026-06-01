"""Trulieve menu adapter (covers Trulieve **and** Harvest — Trulieve owns Harvest's
Arizona stores).

Investigated source of truth (live, May 2026)
---------------------------------------------
``trulieve.com`` is a Next.js site, but it does **not** run its own product
ecommerce: each Arizona store page
(``https://www.trulieve.com/dispensaries/arizona/<location>``) is plain ``httpx``
-readable (HTTP 200, no Cloudflare) and embeds a **Dutchie** storefront. The store
record in the page's ``__NEXT_DATA__`` carries:

    "dutchie_embed_script_url": "https://dutchie.com/api/v2/embedded-menu/<retailerId>.js"

where ``<retailerId>`` is a 24-hex Dutchie ObjectId (e.g.
``5eaf489fa8a61801212577cc`` for Scottsdale). That embed script
(also ``httpx``-readable) contains the Dutchie storefront config, including the
``cName`` — which for these stores is a **Harvest** slug
(``"cName":"harvest-of-scottsdale"``), confirming the Trulieve↔Harvest ownership.

So the real product data lives on **Dutchie**, behind the consumer GraphQL
``filteredProducts`` operation. Dutchie gates ``/graphql`` and
``/api/v2/embedded-menu/<id>`` behind **Cloudflare**, so plain ``httpx`` against
Dutchie returns ``403`` (an "Attention Required!" challenge page). The
trulieve.com pages themselves are NOT gated — only the downstream Dutchie API is.

Strategy (httpx-first, bounded Playwright fallback)
---------------------------------------------------
1. ``httpx`` GET the Trulieve store URL (``store_ref['menu']``) → scrape the Dutchie
   ``<retailerId>``; then ``httpx`` GET the embed ``.js`` → scrape the Dutchie
   ``cName``. Both are ungated and cheap.
2. Try ``httpx`` against Dutchie's GraphQL (``filteredProducts`` by retailer id).
   This usually 403s (Cloudflare) and yields nothing — but it's the cheap path and
   may work from some networks / in future.
3. Fall back to **ONE** headless Playwright render of the Dutchie storefront
   (``https://dutchie.com/dispensary/<cName>``), intercepting the menu GraphQL/XHR
   via ``page.on('response')``. The browser is **ALWAYS** closed via
   ``sync_playwright``'s context manager **plus** a ``finally`` — we never leak
   Chromium (a prior agent leaked 39). The render is bounded (~40s/store) and never
   loops launching browsers.

On ANY failure every layer returns ``[]`` — :meth:`TrulieveAdapter.fetch` never
raises. Set ``SCRAPE_NO_BROWSER=1`` to disable the Playwright fallback.

The JSON → ``MenuItem`` mapping is the pure, network-free :func:`parse_menu` so it
can be unit-tested against a fixture (Dutchie ``filteredProducts`` product shape).
"""

from __future__ import annotations

import os
import re
import time
from typing import Any, Optional
from urllib.parse import urlparse

import httpx

from .base import MenuItem

_DUTCHIE_GRAPHQL_URL = "https://dutchie.com/graphql"
_DUTCHIE_BASE = "https://dutchie.com"
_TIMEOUT_SEC = 15.0
# Per-store wall-clock budget for the Playwright fallback (politeness / bound).
_STORE_BUDGET_SEC = 40.0
_PW_NAV_TIMEOUT_MS = 30000
# Bounded wait for the product GraphQL to fire inside the rendered storefront.
_PW_WAIT_DEADLINE_MS = 30000

_DEFAULT_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
)

# Pulls the Dutchie retailer ObjectId out of the Trulieve store page's
# ``dutchie_embed_script_url`` (``.../embedded-menu/<24-hex>.js``).
_RETAILER_ID_RE = re.compile(r"embedded-menu/([a-f0-9]{24})", re.I)
# Pulls the Dutchie storefront ``cName`` out of the embed ``.js`` config blob
# (``...,"cName":"harvest-of-scottsdale",...``).
_CNAME_RE = re.compile(r'"cName"\s*:\s*"([a-z0-9\-]+)"', re.I)

# Dutchie product ``type``/``subcategory`` strings -> our canonical category names.
_CATEGORY_MAP = {
    "flower": "Flower",
    "pre-rolls": "Prerolls",
    "pre-roll": "Prerolls",
    "preroll": "Prerolls",
    "prerolls": "Prerolls",
    "edible": "Edibles",
    "edibles": "Edibles",
    "concentrate": "Concentrates",
    "concentrates": "Concentrates",
    "extract": "Concentrates",
    "extracts": "Concentrates",
    "vaporizers": "Vapes",
    "vaporizer": "Vapes",
    "vape": "Vapes",
    "vapes": "Vapes",
    "cartridge": "Vapes",
    "cartridges": "Vapes",
}

_STRAIN_TYPE_MAP = {
    "indica": "Indica",
    "sativa": "Sativa",
    "hybrid": "Hybrid",
    "indica-dominant": "Indica",
    "sativa-dominant": "Sativa",
    "hybrid-indica": "Hybrid",
    "hybrid-sativa": "Hybrid",
}


# ---------------------------------------------------------------------------
# Small parse helpers
# ---------------------------------------------------------------------------
def _to_float(value: Any) -> Optional[float]:
    """Best-effort float coercion ($, commas, blanks tolerated)."""
    if value is None or value == "":
        return None
    if isinstance(value, (int, float)):
        return float(value)
    try:
        return float(str(value).replace("$", "").replace(",", "").strip())
    except (ValueError, TypeError):
        return None


def _first_price(value: Any) -> Optional[float]:
    """Dutchie prices come as a scalar or a per-option list — take the first."""
    if isinstance(value, (list, tuple)):
        for v in value:
            f = _to_float(v)
            if f is not None:
                return f
        return None
    return _to_float(value)


def _map_category(raw: Optional[str]) -> Optional[str]:
    if not raw:
        return None
    return _CATEGORY_MAP.get(str(raw).strip().lower())


def _map_strain_type(raw: Optional[str]) -> Optional[str]:
    if not raw:
        return None
    return _STRAIN_TYPE_MAP.get(str(raw).strip().lower())


def _extract_brand(product: dict) -> Optional[str]:
    """Brand string. Dutchie exposes ``brand.name`` plus a flat ``brandName``."""
    brand = product.get("brand")
    if isinstance(brand, dict):
        name = brand.get("name") or brand.get("Name")
        if isinstance(name, str) and name.strip():
            return name.strip()
    if isinstance(brand, str) and brand.strip():
        return brand.strip()
    bn = product.get("brandName") or product.get("BrandName")
    if isinstance(bn, str) and bn.strip():
        return bn.strip()
    return None


def _extract_image(product: dict) -> Optional[str]:
    """First usable PRODUCT image URL (always captured when present).

    Dutchie exposes a flat ``Image`` plus an ``images[].url`` list. Deliberately
    ignores ``brandLogo``/``brand.imageUrl`` (those are brand logos, not the
    product photo).
    """
    img = product.get("Image") or product.get("image")
    if isinstance(img, str) and img.startswith("http"):
        return img
    images = product.get("images") or product.get("Images")
    if isinstance(images, list):
        for entry in images:
            if isinstance(entry, str) and entry.startswith("http"):
                return entry
            if isinstance(entry, dict):
                url = entry.get("url") or entry.get("URL") or entry.get("imageUrl")
                if isinstance(url, str) and url.startswith("http"):
                    return url
    return None


def _extract_size(product: dict) -> Optional[str]:
    """Weight/size label normalized to what the pipeline can parse ("3.5g" /
    "100mg").

    Prefers the displayed ``Options``/``rawOptions`` (e.g. ``"1g"`` / ``"3.5g"``),
    then the priced ``measurements.netWeight`` (milligrams → grams), then the flat
    ``weight`` (also milligrams on Dutchie).
    """
    options = product.get("Options") or product.get("options")
    if isinstance(options, list) and options:
        first = options[0]
        if isinstance(first, str) and first.strip():
            return first.strip()
        if isinstance(first, dict):
            label = first.get("option") or first.get("label") or first.get("weight")
            if label:
                return str(label)
    raw_options = product.get("rawOptions")
    if isinstance(raw_options, list) and raw_options and isinstance(raw_options[0], str):
        return raw_options[0].strip()

    # measurements.netWeight: {unit:"MILLIGRAMS", values:[1000]} -> "1g".
    measurements = product.get("measurements")
    if isinstance(measurements, dict):
        net = measurements.get("netWeight")
        if isinstance(net, dict):
            vals = net.get("values")
            unit = str(net.get("unit") or "").upper()
            val = _to_float(vals[0]) if isinstance(vals, list) and vals else None
            if val:
                if unit.startswith("MILLIGRAM"):
                    grams = val / 1000.0
                    return f"{grams:g}g"
                if unit.startswith("GRAM"):
                    return f"{val:g}g"
    weight = _to_float(product.get("weight"))
    if weight:
        # Dutchie's flat ``weight`` is in milligrams.
        return f"{weight / 1000.0:g}g"
    return None


def _extract_potency(product: dict, keys: tuple[str, ...]) -> Optional[float]:
    """THC/CBD percent. Dutchie nests this as ``{unit, range:[hi]}`` under
    ``THCContent``/``CBDContent`` (also tolerates flat ``THC``/``thc`` scalars)."""
    for key in keys:
        node = product.get(key)
        if node is None:
            continue
        if isinstance(node, (int, float, str)):
            f = _to_float(node)
            if f is not None:
                return f
        if isinstance(node, dict):
            if node.get("value") is not None:
                return _to_float(node.get("value"))
            rng = node.get("range")
            if isinstance(rng, list) and rng:
                # The labeled potency is the high end of the range.
                return _to_float(rng[-1])
    return None


def _store_cname(data: Any) -> Optional[str]:
    """The Dutchie storefront ``cName`` if the parsed envelope carries it.

    The live capture path wraps each GraphQL body with a top-level ``storeCName``
    (it isn't present inside the GraphQL response itself) so :func:`parse_menu`
    can build per-product deep links purely. Tolerates a few key spellings.
    """
    if not isinstance(data, dict):
        return None
    for key in ("storeCName", "store_cname", "cName", "dispensaryCName"):
        val = data.get(key)
        if isinstance(val, str) and val.strip():
            return val.strip()
    return None


def _product_url(store_cname: Optional[str], product: dict) -> Optional[str]:
    """Deep link to THIS product on the Dutchie storefront (always set when the
    store ``cName`` and product ``cName`` are both known):
    ``https://dutchie.com/dispensary/<storeCName>/product/<productCName>``."""
    pcn = product.get("cName") or product.get("productCName")
    if store_cname and isinstance(pcn, str) and pcn:
        return f"{_DUTCHIE_BASE}/dispensary/{store_cname}/product/{pcn}"
    # Some payloads carry an explicit url already.
    for key in ("url", "Url", "productUrl"):
        val = product.get(key)
        if isinstance(val, str) and val.startswith("http"):
            return val
    return None


def _extract_in_stock(product: dict) -> bool:
    status = product.get("Status") or product.get("status")
    if isinstance(status, str):
        return status.strip().lower() == "active"
    val = product.get("inStock", product.get("InStock"))
    if isinstance(val, bool):
        return val
    return True


# ---------------------------------------------------------------------------
# Pure parser (network-free, unit-tested against a fixture)
# ---------------------------------------------------------------------------
def _parse_one(product: dict, store_cname: Optional[str] = None) -> Optional[MenuItem]:
    name = product.get("Name") or product.get("name") or product.get("productName")
    if not name:
        return None

    orig = _first_price(
        product.get("Prices")
        or product.get("recPrices")
        or product.get("medicalPrices")
        or product.get("price")
    )
    special = _first_price(
        product.get("recSpecialPrices")
        or product.get("specialPrices")
        or product.get("medicalSpecialPrices")
        or product.get("specialPrice")
    )
    sale = special if special is not None else orig
    if orig is not None and sale is not None and sale > orig:
        sale = orig

    category = _map_category(
        product.get("type") or product.get("category") or product.get("subcategory")
    )

    parsed: MenuItem = {
        "product": str(name),
        "brand": _extract_brand(product),
        "category": category,
        "orig": orig,
        "sale": sale,
        "size": _extract_size(product),
        "thc": _extract_potency(product, ("THCContent", "THC", "thc", "potencyThc")),
        "cbd": _extract_potency(product, ("CBDContent", "CBD", "cbd", "potencyCbd")),
        "type": _map_strain_type(product.get("strainType") or product.get("StrainType")),
        "img": _extract_image(product),
        "url": _product_url(store_cname, product),
        "in_stock": _extract_in_stock(product),
    }
    # Trulieve menus are Dutchie storefronts, so the special + metadata schema is
    # identical; reuse the Dutchie extractors for consistent promo_* / desc /
    # effects / lineage fields.
    try:
        from .dutchie import (
            _extract_description as _d_desc,
            _extract_effects as _d_eff,
            _extract_lineage as _d_lin,
            _extract_promo as _dutchie_promo,
        )

        parsed["desc"] = _d_desc(product)
        parsed["effects"] = _d_eff(product)
        parsed["lineage"] = _d_lin(product)
        parsed.update(_dutchie_promo(product))
    except Exception:
        pass
    return parsed


# Field names that strongly signal "this dict is a Dutchie menu product".
_PRODUCT_NAME_KEYS = ("Name", "name", "productName")
_PRODUCT_PRICE_KEYS = (
    "Prices",
    "prices",
    "recPrices",
    "medicalPrices",
    "recSpecialPrices",
    "medicalSpecialPrices",
    "specialPrices",
)


def _looks_like_product(obj: Any) -> bool:
    if not isinstance(obj, dict):
        return False
    has_name = any(obj.get(k) for k in _PRODUCT_NAME_KEYS)
    has_price = any(k in obj for k in _PRODUCT_PRICE_KEYS)
    return bool(has_name and has_price)


def _find_products(data: Any, depth: int = 0) -> list[dict]:
    """Locate the product list inside a Trulieve/Dutchie payload, tolerantly.

    Prefers the canonical ``data.filteredProducts.products`` path, then a bare
    ``filteredProducts``/``products`` list, then a recursive scan for the first
    product-shaped list anywhere in the tree (handles schema drift / arbitrary
    captured GraphQL bodies).
    """
    if isinstance(data, list):
        return [x for x in data if isinstance(x, dict)]
    if not isinstance(data, dict):
        return []

    node: Any = data
    if isinstance(node.get("data"), dict):
        node = node["data"]
    fp = node.get("filteredProducts") if isinstance(node, dict) else None
    if isinstance(fp, dict):
        products = fp.get("products") or fp.get("Products")
        if isinstance(products, list) and products:
            return [x for x in products if isinstance(x, dict)]
    elif isinstance(fp, list) and fp:
        return [x for x in fp if isinstance(x, dict)]

    for key in ("products", "menuItems", "menu_items", "items"):
        cand = node.get(key) if isinstance(node, dict) else None
        if isinstance(cand, list) and cand and any(_looks_like_product(x) for x in cand):
            return [x for x in cand if isinstance(x, dict)]

    # Last resort: recurse to find the first product-shaped list.
    if depth < 8:
        if isinstance(node, dict):
            for v in node.values():
                found = _find_products(v, depth + 1)
                if found and any(_looks_like_product(x) for x in found):
                    return found
    return []


def parse_menu(data: Any) -> list[MenuItem]:
    """Parse a Trulieve/Dutchie ``filteredProducts`` payload into ``MenuItem`` dicts.

    Pure and network-free. ``data`` may be the full GraphQL body
    (``{"data": {"filteredProducts": {"products": [...]}}}``), a bare product list,
    or any captured body containing a product-shaped list (see
    :func:`_find_products`). When the envelope carries a top-level ``storeCName``
    (the live capture path adds it), each row gets a per-product Dutchie deep link.
    Unparseable rows and non-canonical categories are skipped.
    """
    store_cname = _store_cname(data)
    items: list[MenuItem] = []
    for raw in _find_products(data):
        try:
            parsed = _parse_one(raw, store_cname)
        except Exception:
            parsed = None
        if parsed is not None:
            items.append(parsed)
    return items


# ---------------------------------------------------------------------------
# Trulieve → Dutchie identity resolution (httpx, ungated)
# ---------------------------------------------------------------------------
def _resolve_dutchie_identity(
    client: httpx.Client, menu_url: str
) -> tuple[Optional[str], Optional[str]]:
    """From a Trulieve store URL, scrape the embedded Dutchie ``(retailerId, cName)``.

    The Trulieve store page is ungated (HTTP 200) and embeds
    ``dutchie_embed_script_url`` → the retailer id; the embed ``.js`` (also ungated)
    carries the storefront ``cName``. Best effort — returns ``(None, None)`` on any
    failure.
    """
    retailer_id: Optional[str] = None
    cname: Optional[str] = None
    try:
        resp = client.get(menu_url)
        if resp.status_code == 200:
            m = _RETAILER_ID_RE.search(resp.text)
            if m:
                retailer_id = m.group(1)
    except Exception:
        return None, None

    if retailer_id:
        try:
            js = client.get(
                f"{_DUTCHIE_BASE}/api/v2/embedded-menu/{retailer_id}.js"
            )
            if js.status_code == 200:
                cm = _CNAME_RE.search(js.text)
                if cm:
                    cname = cm.group(1)
        except Exception:
            cname = None
    return retailer_id, cname


def _dutchie_storefront_url(cname: Optional[str], retailer_id: Optional[str]) -> Optional[str]:
    """The Dutchie page to render: prefer the ``cName`` storefront (verified to
    fire ``filteredProducts``), else the retailer-id embedded menu."""
    if cname:
        return f"{_DUTCHIE_BASE}/dispensary/{cname}"
    if retailer_id:
        return f"{_DUTCHIE_BASE}/embedded-menu/{retailer_id}"
    return None


def _fetch_products_via_httpx(
    client: httpx.Client, retailer_id: str, store_cname: Optional[str]
) -> list[MenuItem]:
    """Cheap Dutchie GraphQL ``filteredProducts`` by retailer id (usually 403s
    behind Cloudflare → ``[]``)."""
    payload = {
        "operationName": "FilteredProducts",
        "variables": {
            "productsFilter": {
                "dispensaryId": retailer_id,
                "Status": "Active",
                "isDefaultSort": True,
            },
            "page": 0,
            "perPage": 100,
        },
        "query": (
            "query FilteredProducts($productsFilter: ProductFilter, $page: Int,"
            " $perPage: Int) { filteredProducts(productsFilter: $productsFilter,"
            " page: $page, perPage: $perPage) { products { id Name brand { name }"
            " brandName type subcategory strainType Prices recPrices recSpecialPrices"
            " medicalSpecialPrices Options rawOptions weight measurements THCContent"
            " CBDContent Image images cName Status } } }"
        ),
    }
    try:
        resp = client.post(
            _DUTCHIE_GRAPHQL_URL,
            json=payload,
            headers={
                "Content-Type": "application/json",
                "Accept": "application/json",
                "Origin": _DUTCHIE_BASE,
                "Referer": f"{_DUTCHIE_BASE}/",
            },
        )
        if resp.status_code != 200:
            return []
        body = resp.json()
    except Exception:
        return []
    return parse_menu(_wrap_body(body, store_cname))


def _wrap_body(body: Any, store_cname: Optional[str]) -> Any:
    """Inject the known store ``cName`` at the top level so :func:`parse_menu` can
    build per-product deep links (the raw GraphQL body has no store cName)."""
    if isinstance(body, dict) and store_cname:
        wrapped = dict(body)
        wrapped["storeCName"] = store_cname
        return wrapped
    return body


# ---------------------------------------------------------------------------
# Playwright fallback (Dutchie is Cloudflare-gated) — NEVER leaks browsers
# ---------------------------------------------------------------------------
def _fetch_via_playwright(target_url: str, store_cname: Optional[str]) -> list[MenuItem]:
    """Render the Dutchie storefront ONCE (headless) and read its GraphQL/XHR.

    Intercepts JSON responses whose URL contains ``graphql`` / ``/api/`` and keeps
    those that parse into products. The browser is ALWAYS closed via
    ``sync_playwright``'s context manager PLUS a ``finally`` — no leaked Chromium,
    no relaunch loop. Bounded by ``_STORE_BUDGET_SEC``. Returns ``[]`` on any
    failure (never raises).
    """
    try:
        from playwright.sync_api import sync_playwright  # local import: optional dep
    except Exception:
        return []

    user_agent = os.getenv("SCRAPE_USER_AGENT") or _DEFAULT_UA
    captured_bodies: list[dict] = []

    def _on_response(response: Any) -> None:
        try:
            url = response.url or ""
            if "graphql" not in url and "/api/" not in url:
                return
            ctype = (response.headers or {}).get("content-type", "")
            if "json" not in ctype.lower():
                return
            body = response.json()
        except Exception:
            return
        try:
            if parse_menu(body):
                captured_bodies.append(body)
        except Exception:
            return

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
                page.on("response", _on_response)
                try:
                    page.goto(
                        target_url,
                        wait_until="domcontentloaded",
                        timeout=_PW_NAV_TIMEOUT_MS,
                    )
                except Exception:
                    pass
                _wait_for_products(page, captured_bodies, start)
            finally:
                browser.close()
    except Exception:
        pass

    items: list[MenuItem] = []
    for body in captured_bodies:
        items.extend(parse_menu(_wrap_body(body, store_cname)))
    # Dedup by (name|size|orig) — the same GraphQL page can be captured twice.
    out: list[MenuItem] = []
    seen: set[str] = set()
    for it in items:
        key = f"{it.get('product')}|{it.get('size')}|{it.get('orig')}"
        if key in seen:
            continue
        seen.add(key)
        out.append(it)
    return out


def _wait_for_products(page: Any, captured_bodies: list[dict], start: float) -> None:
    """Bounded wait: stop as soon as a product body is captured, else settle +
    scroll. Never loops past ``_STORE_BUDGET_SEC`` / ``_PW_WAIT_DEADLINE_MS``."""
    waited = 0
    step = 1000
    while waited < _PW_WAIT_DEADLINE_MS:
        if captured_bodies:
            break
        if time.monotonic() - start > _STORE_BUDGET_SEC:
            break
        try:
            page.wait_for_timeout(step)
        except Exception:
            break
        waited += step
        try:
            page.mouse.wheel(0, 1400)
        except Exception:
            pass


# ---------------------------------------------------------------------------
# Adapter
# ---------------------------------------------------------------------------
class TrulieveAdapter:
    """Best-effort Trulieve/Harvest adapter (see module docstring).

    Implements the :class:`app.adapters.base.Adapter` protocol. ``fetch`` reads
    ``store_ref['menu']`` (a ``trulieve.com`` store URL), resolves the embedded
    Dutchie ``(retailerId, cName)`` via ``httpx``, tries the cheap Dutchie GraphQL
    path, then falls back to ONE bounded headless-Playwright render of the Dutchie
    storefront. Any failure yields ``[]``.
    """

    def __init__(self, user_agent: Optional[str] = None) -> None:
        self._user_agent = user_agent or os.getenv("SCRAPE_USER_AGENT") or _DEFAULT_UA

    def _headers(self) -> dict[str, str]:
        return {
            "User-Agent": self._user_agent,
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Accept-Language": "en-US,en;q=0.9",
            "Referer": "https://www.trulieve.com/",
        }

    def fetch(self, store_ref: dict[str, Any]) -> list[MenuItem]:
        """Return the store's menu as ``MenuItem`` dicts (``[]`` on any failure)."""
        menu_url = store_ref.get("menu") or store_ref.get("menu_ref") or ""
        if not menu_url:
            return []

        retailer_id: Optional[str] = None
        cname: Optional[str] = None
        items: list[MenuItem] = []
        try:
            with httpx.Client(
                timeout=_TIMEOUT_SEC, follow_redirects=True, headers=self._headers()
            ) as client:
                retailer_id, cname = _resolve_dutchie_identity(client, menu_url)
                if retailer_id:
                    items = _fetch_products_via_httpx(client, retailer_id, cname)
        except Exception:
            items = []

        if items:
            return items

        if not retailer_id and not cname:
            # Couldn't even resolve the Dutchie identity — nothing to render.
            return []
        if os.getenv("SCRAPE_NO_BROWSER"):
            return []

        target = _dutchie_storefront_url(cname, retailer_id)
        if not target:
            return []
        return _fetch_via_playwright(target, cname)
