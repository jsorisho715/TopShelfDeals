"""Dutchie menu adapter.

Strategy: hit the same consumer GraphQL endpoint (``https://dutchie.com/graphql``)
that the public dispensary menu page calls in the browser, rather than scraping
rendered HTML. Two operations:

1. ``ConsumerDispensaries`` — resolve the dispensary ``id``/``cName`` from the URL
   slug (last path segment of the menu URL).
2. ``FilteredProducts`` — page of products for that dispensary id, including name,
   brand, type/category, prices, special prices, option weights, THC potency, and
   image URLs.

The JSON → ``MenuItem`` mapping is factored into the pure, network-free
:func:`parse_filtered_products` so it can be unit-tested against a fixture.

Robustness: every network call is wrapped and bounded by a ~15s timeout. On ANY
failure (Cloudflare 403, connection error, schema drift) :meth:`DutchieAdapter.fetch`
returns ``[]`` instead of raising — the orchestrator keeps polling other stores.

Cloudflare fallback (PRD FR2): Dutchie increasingly gates ``/graphql`` behind
Cloudflare, in which case the httpx path returns 403 and yields ``[]``. When that
happens :meth:`DutchieAdapter.fetch` automatically falls back to
:func:`fetch_via_playwright`, which drives the real menu page in a Chromium
browser (headless first, then headed) and reads the same GraphQL/API responses
off the network. Captured bodies are parsed with the tolerant
:func:`parse_menu_response`. Set ``SCRAPE_NO_BROWSER=1`` to disable the fallback.
"""

from __future__ import annotations

import json
import os
from typing import Any, Optional
from urllib.parse import urlparse

import httpx

from . import promo as _promo
from .base import MenuItem

# Dutchie day-of-week schedules sometimes use integer codes (0=Sun .. 6=Sat).
_DUTCHIE_INT_DOW = {0: "Sun", 1: "Mon", 2: "Tue", 3: "Wed", 4: "Thu", 5: "Fri", 6: "Sat"}

_GRAPHQL_URL = "https://dutchie.com/graphql"
_TIMEOUT_SEC = 15.0
# Playwright fallback bounds (ms).
_PW_NAV_TIMEOUT_MS = 45000
_PW_SETTLE_MS = 6000
_DEFAULT_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
)

# Dutchie product ``type``/category strings -> our canonical category names.
_CATEGORY_MAP = {
    "flower": "Flower",
    "pre-rolls": "Prerolls",
    "preroll": "Prerolls",
    "prerolls": "Prerolls",
    "pre-roll": "Prerolls",
    "edible": "Edibles",
    "edibles": "Edibles",
    "concentrate": "Concentrates",
    "concentrates": "Concentrates",
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
# Slug + small parse helpers
# ---------------------------------------------------------------------------
def slug_from_menu_url(menu_url: str) -> Optional[str]:
    """Return the dispensary slug — the last non-empty path segment of the menu URL.

    ``https://dutchie.com/dispensary/the-mint-cannabis-tempe`` -> ``the-mint-cannabis-tempe``.
    """
    if not menu_url:
        return None
    path = urlparse(menu_url).path
    segments = [s for s in path.split("/") if s]
    return segments[-1] if segments else None


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
    """Prices on Dutchie come as a scalar or a per-option list — take the first."""
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
    brand = product.get("brand")
    if isinstance(brand, dict):
        return brand.get("name") or brand.get("Name")
    if isinstance(brand, str):
        return brand
    return product.get("brandName") or product.get("BrandName")


def _extract_image(product: dict) -> Optional[str]:
    """First usable image URL. Dutchie exposes ``Image`` and/or ``images[].url``."""
    img = product.get("Image") or product.get("image")
    if isinstance(img, str) and img:
        return img
    images = product.get("images") or product.get("Images")
    if isinstance(images, list):
        for entry in images:
            if isinstance(entry, str) and entry:
                return entry
            if isinstance(entry, dict):
                url = entry.get("url") or entry.get("URL") or entry.get("imageUrl")
                if url:
                    return url
    return None


def _extract_size(product: dict) -> Optional[str]:
    """Option/weight label, e.g. '3.5g'. Dutchie uses ``Options``/``weight``."""
    options = product.get("Options") or product.get("options")
    if isinstance(options, list) and options:
        first = options[0]
        if isinstance(first, str):
            return first
        if isinstance(first, dict):
            return first.get("option") or first.get("label") or first.get("weight")
    for key in ("weight", "Weight", "size", "Size"):
        val = product.get(key)
        if val:
            return str(val)
    return None


def _extract_thc(product: dict) -> Optional[float]:
    """THC potency %. Dutchie nests this under ``THCContent``/``THC``/potency."""
    for key in ("THCContent", "THC", "thc", "potencyThc"):
        node = product.get(key)
        if node is None:
            continue
        if isinstance(node, (int, float, str)):
            f = _to_float(node)
            if f is not None:
                return f
        if isinstance(node, dict):
            # {range:[lo,hi], unit:"PERCENTAGE"} or {value: 24.1}
            if node.get("value") is not None:
                return _to_float(node.get("value"))
            rng = node.get("range")
            if isinstance(rng, list) and rng:
                # Prefer the high end of the range (the labeled potency).
                return _to_float(rng[-1])
    return None


def _extract_description(product: dict) -> Optional[str]:
    for key in ("Description", "description", "productDescription", "body"):
        val = product.get(key)
        if isinstance(val, str) and val.strip():
            return val.strip()
    return None


def _extract_effects(product: dict) -> list:
    """List of effect names. Dutchie uses ``effects``/``Effects`` (list of str or
    ``{name}`` dicts)."""
    out: list[str] = []
    for key in ("effects", "Effects"):
        node = product.get(key)
        if isinstance(node, list):
            for e in node:
                if isinstance(e, str) and e.strip():
                    out.append(e.strip())
                elif isinstance(e, dict):
                    name = e.get("name") or e.get("Name") or e.get("effect")
                    if isinstance(name, str) and name.strip():
                        out.append(name.strip())
            if out:
                return out
    return out


def _extract_lineage(product: dict) -> Optional[str]:
    """Genetics/lineage string, e.g. "Sour Apple × Triangle Kush"."""
    for key in ("lineage", "Lineage", "genetics", "Genetics"):
        val = product.get(key)
        if isinstance(val, str) and val.strip():
            return val.strip()
    strain = product.get("strainData") or product.get("strain")
    if isinstance(strain, dict):
        for key in ("lineage", "genetics", "parents"):
            val = strain.get(key)
            if isinstance(val, str) and val.strip():
                return val.strip()
    return None


def _extract_cbd(product: dict) -> Optional[float]:
    for key in ("CBDContent", "CBD", "cbd", "potencyCbd"):
        node = product.get(key)
        if node is None:
            continue
        if isinstance(node, (int, float, str)):
            return _to_float(node)
        if isinstance(node, dict):
            if node.get("value") is not None:
                return _to_float(node.get("value"))
            rng = node.get("range")
            if isinstance(rng, list) and rng:
                return _to_float(rng[-1])
    return None


def _coerce_dow_list(value: Any) -> list[str]:
    """Normalize a Dutchie days-of-week value into canonical 3-letter codes.

    Accepts a list of day names (``["Wednesday"]``), integer codes
    (``[3]`` -> Wed), or a free-text string ("Mon/Wed/Fri").
    """
    if value is None:
        return []
    if isinstance(value, str):
        return _promo.parse_dow(value)
    if isinstance(value, (int, float)):
        code = _DUTCHIE_INT_DOW.get(int(value))
        return [code] if code else []
    if isinstance(value, (list, tuple)):
        out: list[str] = []
        for v in value:
            if isinstance(v, (int, float)):
                code = _DUTCHIE_INT_DOW.get(int(v))
                if code and code not in out:
                    out.append(code)
            elif isinstance(v, str):
                for code in _promo.parse_dow(v):
                    if code not in out:
                        out.append(code)
        # keep week order
        from .base import WEEKDAY_CODES
        return [d for d in WEEKDAY_CODES if d in out]
    return []


def _extract_promo(product: dict) -> dict:
    """Best-effort promo/special metadata from a Dutchie product row.

    Reads the special containers Dutchie attaches to a product
    (``specialData`` / ``specials`` / ``saleSpecials`` etc.) for a title, weekday
    schedule, validity window and stackability, then lets
    :func:`promo.build_promo` infer kind/audience/dow from the title. Returns only
    populated ``promo_*`` keys (``{}`` when the product isn't on a labeled special).
    """
    containers: list[dict] = []
    for key in ("specialData", "specials", "saleSpecials", "specialsData", "Special", "special"):
        v = product.get(key)
        if isinstance(v, dict):
            containers.append(v)
        elif isinstance(v, list):
            containers.extend([x for x in v if isinstance(x, dict)])

    title = None
    days: list[str] = []
    valid_from = valid_to = None
    stackable = None
    for c in containers:
        title = title or c.get("specialName") or c.get("menuDisplayName") or c.get("name") or c.get("title")
        if not days:
            days = _coerce_dow_list(
                c.get("daysOfWeek") or c.get("days") or c.get("recurringDays") or c.get("schedule")
            )
        valid_from = valid_from or c.get("startStamp") or c.get("startDate") or c.get("validFrom")
        valid_to = valid_to or c.get("endStamp") or c.get("endDate") or c.get("validTo")
        if stackable is None:
            st = c.get("stackable")
            if st is None:
                st = c.get("canStackWithOtherDiscounts")
            if st is not None:
                stackable = bool(st)

    on_special = bool(title) or bool(product.get("special"))
    if not on_special:
        return {}
    return _promo.build_promo(
        title=title or "Special",
        dow=days or None,
        valid_from=str(valid_from) if valid_from else None,
        valid_to=str(valid_to) if valid_to else None,
        stackable=stackable,
    )


# ---------------------------------------------------------------------------
# Pure parser (network-free, unit-tested against a fixture)
# ---------------------------------------------------------------------------
def _parse_one_product(product: dict) -> Optional[MenuItem]:
    name = product.get("Name") or product.get("name")
    if not name:
        return None

    orig = _first_price(
        product.get("Prices")
        or product.get("recPrices")
        or product.get("medicalPrices")
        or product.get("price")
    )
    # Real Dutchie special prices live under rec/medicalSpecialPrices; the older
    # ``specialPrices`` key is kept for the legacy fixture/schema.
    special = _first_price(
        product.get("recSpecialPrices")
        or product.get("specialPrices")
        or product.get("medicalSpecialPrices")
        or product.get("specialPrice")
    )
    sale = special if special is not None else orig

    category = _map_category(product.get("type") or product.get("category") or product.get("subcategory"))

    item: MenuItem = {
        "product": str(name),
        "brand": _extract_brand(product),
        "category": category,
        "orig": orig,
        "sale": sale,
        "size": _extract_size(product),
        "thc": _extract_thc(product),
        "cbd": _extract_cbd(product),
        "type": _map_strain_type(product.get("strainType") or product.get("StrainType")),
        "img": _extract_image(product),
        "url": product.get("url") or product.get("Url") or product.get("productUrl") or None,
        "in_stock": bool(product.get("inStock", product.get("InStock", True))),
        "desc": _extract_description(product),
        "effects": _extract_effects(product),
        "lineage": _extract_lineage(product),
    }
    item.update(_extract_promo(product))
    return item


def parse_filtered_products(json_dict: dict) -> list[MenuItem]:
    """Parse a Dutchie ``FilteredProducts`` GraphQL response into ``MenuItem`` dicts.

    Pure and network-free. Tolerant of the exact nesting Dutchie uses:
    ``data.filteredProducts.products`` (also accepts ``filteredProducts`` /
    ``products`` at the top level). Unparseable rows are skipped.
    """
    if not isinstance(json_dict, dict):
        return []

    node: Any = json_dict
    if "data" in node and isinstance(node["data"], dict):
        node = node["data"]
    fp = node.get("filteredProducts") if isinstance(node, dict) else None
    if isinstance(fp, dict):
        products = fp.get("products") or fp.get("Products") or []
    elif isinstance(fp, list):
        products = fp
    else:
        products = node.get("products") if isinstance(node, dict) else None
        products = products or []

    items: list[MenuItem] = []
    for product in products:
        if not isinstance(product, dict):
            continue
        try:
            parsed = _parse_one_product(product)
        except Exception:
            parsed = None
        if parsed is not None:
            items.append(parsed)
    return items


# ---------------------------------------------------------------------------
# Tolerant parser for arbitrary captured GraphQL bodies (Playwright path)
# ---------------------------------------------------------------------------
# Field names that strongly signal "this dict is a menu product".
_PRODUCT_NAME_KEYS = ("Name", "name", "productName")
_PRODUCT_PRICE_KEYS = (
    "Prices",
    "prices",
    "recPrices",
    "medicalPrices",
    "medPrices",
    "recSpecialPrices",
    "medicalSpecialPrices",
    "specialPrices",
)


def _looks_like_product(obj: Any) -> bool:
    """A real menu product carries a name AND a price array (``Prices`` / rec /
    medical). Requiring a price key keeps tax/fee/config rows (which also have a
    ``Name``) out of the recursively-discovered product lists."""
    if not isinstance(obj, dict):
        return False
    has_name = any(obj.get(k) for k in _PRODUCT_NAME_KEYS)
    has_price = any(k in obj for k in _PRODUCT_PRICE_KEYS)
    return bool(has_name and has_price)


def _find_product_lists(node: Any, depth: int = 0) -> list[list[dict]]:
    """Recursively collect lists whose members look like menu products.

    Real Dutchie responses bury the product array at varying depths and under
    varying operation/field names; rather than hard-coding the path we scan the
    whole JSON tree for the first product-shaped lists.
    """
    found: list[list[dict]] = []
    if depth > 8:
        return found
    if isinstance(node, list):
        product_members = [m for m in node if _looks_like_product(m)]
        if product_members and len(product_members) >= max(1, len(node) // 2):
            found.append(product_members)
        else:
            for m in node:
                found.extend(_find_product_lists(m, depth + 1))
    elif isinstance(node, dict):
        for v in node.values():
            found.extend(_find_product_lists(v, depth + 1))
    return found


def parse_menu_response(json_dict: Any) -> list[MenuItem]:
    """Tolerantly parse ANY captured Dutchie GraphQL body into ``MenuItem`` dicts.

    First tries the canonical ``filteredProducts`` path
    (:func:`parse_filtered_products`); if that yields nothing it falls back to a
    recursive scan for product-shaped lists anywhere in the tree. Each candidate
    row goes through the same defensive :func:`_parse_one_product` mapper, so the
    output contract (name / brand / category / prices / size / thc / img /
    in_stock) is identical to the httpx path.
    """
    items = parse_filtered_products(json_dict)
    if items:
        return items

    seen_names: set[str] = set()
    out: list[MenuItem] = []
    for product_list in _find_product_lists(json_dict):
        for product in product_list:
            try:
                parsed = _parse_one_product(product)
            except Exception:
                parsed = None
            if parsed is None:
                continue
            # Recursively-found rows with no price aren't sellable products
            # (tax/fee/config noise) — drop them.
            if parsed.get("orig") is None:
                continue
            key = f"{parsed.get('product')}|{parsed.get('size')}|{parsed.get('orig')}"
            if key in seen_names:
                continue
            seen_names.add(key)
            out.append(parsed)
    return out


# ---------------------------------------------------------------------------
# Playwright fallback (Cloudflare-gated stores) — PRD FR2
# ---------------------------------------------------------------------------
def _body_has_products(body: Any) -> bool:
    return bool(parse_menu_response(body))


def _run_playwright_capture(
    menu_url: str,
    user_agent: str,
    headless: bool,
    nav_timeout_ms: int,
    capture_sink: Optional[list[dict]] = None,
) -> tuple[list[MenuItem], bool, str]:
    """Drive the real menu page once and read its GraphQL/API responses.

    Returns ``(items, cloudflare_cleared, note)``. Never raises — any failure
    yields ``([], False, "<reason>")`` so the adapter can degrade gracefully.

    ``capture_sink`` (if provided) collects the raw product-bearing JSON bodies
    so callers can persist a live fixture.
    """
    try:
        from playwright.sync_api import sync_playwright  # local import: optional dep
    except Exception as exc:  # pragma: no cover - only when playwright missing
        return [], False, f"playwright unavailable: {exc}"

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
            if _body_has_products(body):
                captured_bodies.append(body)
        except Exception:
            return

    note = ""
    cloudflare_cleared = False
    try:
        with sync_playwright() as pw:
            browser = pw.chromium.launch(
                headless=headless,
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
                    # domcontentloaded (not networkidle): a Cloudflare challenge
                    # page keeps the network busy and never reaches networkidle.
                    page.goto(menu_url, wait_until="domcontentloaded", timeout=nav_timeout_ms)
                except Exception as exc:
                    note = f"goto: {type(exc).__name__}"
                # Give Cloudflare time to auto-solve its JS challenge + the product
                # grid time to lazy-load. Stops early once products are captured.
                _wait_for_products(page, captured_bodies)
                # Detect whether we are still staring at a Cloudflare challenge.
                still_challenged = _is_cloudflare_challenge(page)
                cloudflare_cleared = not still_challenged
                try:
                    title = page.title() or ""
                except Exception:
                    title = ""
                if captured_bodies:
                    note = "products captured"
                elif still_challenged:
                    note = f"cloudflare challenge persisted (title={title!r})"
                else:
                    note = f"cleared but no product responses (title={title!r})"
            finally:
                browser.close()
    except Exception as exc:
        return [], False, f"playwright error: {type(exc).__name__}: {exc}"

    items: list[MenuItem] = []
    for body in captured_bodies:
        items.extend(parse_menu_response(body))
    if capture_sink is not None:
        capture_sink.extend(captured_bodies)
    return items, cloudflare_cleared or bool(items), note


def _is_cloudflare_challenge(page: Any) -> bool:
    try:
        title = (page.title() or "").lower()
    except Exception:
        title = ""
    if "just a moment" in title or "attention required" in title:
        return True
    try:
        content = (page.content() or "").lower()
    except Exception:
        return False
    return (
        "cf-challenge" in content
        or "checking your browser" in content
        or "challenge-platform" in content
    )


def _wait_for_products(page: Any, captured_bodies: list[dict]) -> None:
    """Bounded wait: stop as soon as we have a product body, else settle + scroll.

    Waits up to ~38s — enough for Cloudflare to auto-solve its JS challenge in a
    real browser and for the product grid's GraphQL call to fire — but never
    loops indefinitely.
    """
    deadline_ms = 38000
    waited = 0
    step = 1000
    while waited < deadline_ms:
        if captured_bodies:
            break
        try:
            page.wait_for_timeout(step)
        except Exception:
            break
        waited += step
        # Nudge lazy loading / Cloudflare JS along.
        try:
            page.mouse.wheel(0, 1200)
        except Exception:
            pass


def fetch_via_playwright(
    store_ref: dict[str, Any], capture_sink: Optional[list[dict]] = None
) -> list[MenuItem]:
    """Cloudflare-gated fallback: render the menu page and read its GraphQL.

    Tries headless Chromium first; if nothing is captured (typical when
    Cloudflare blocks headless), retries headed (the host is a Windows PC with a
    display). Always returns ``[]`` on failure — never raises.
    """
    menu_url = store_ref.get("menu") or store_ref.get("menu_ref") or ""
    if not menu_url:
        return []

    user_agent = os.getenv("SCRAPE_USER_AGENT") or _DEFAULT_UA
    last_note = ""
    for headless in (True, False):
        items, cleared, note = _run_playwright_capture(
            menu_url,
            user_agent=user_agent,
            headless=headless,
            nav_timeout_ms=_PW_NAV_TIMEOUT_MS,
            capture_sink=capture_sink,
        )
        last_note = note
        if items:
            return items
        # If headless cleared Cloudflare but simply found no products, a headed
        # retry won't help — bail to stay polite/bounded.
        if cleared:
            break
    if os.getenv("SCRAPE_DEBUG"):
        print(f"[dutchie playwright] {menu_url}: {last_note}")
    return []


# ---------------------------------------------------------------------------
# Adapter
# ---------------------------------------------------------------------------
class DutchieAdapter:
    """Best-effort Dutchie consumer-GraphQL adapter.

    Implements the :class:`app.adapters.base.Adapter` protocol. ``fetch`` resolves
    the dispensary id from the menu-URL slug, queries products, and parses them
    with :func:`parse_filtered_products`. Any failure yields ``[]``.
    """

    def __init__(self, user_agent: Optional[str] = None) -> None:
        self._user_agent = user_agent or os.getenv("SCRAPE_USER_AGENT") or _DEFAULT_UA

    def _headers(self) -> dict[str, str]:
        return {
            "User-Agent": self._user_agent,
            "Content-Type": "application/json",
            "Accept": "application/json",
            "Origin": "https://dutchie.com",
            "Referer": "https://dutchie.com/",
        }

    def _resolve_dispensary_id(self, client: httpx.Client, slug: str) -> Optional[str]:
        """``ConsumerDispensaries`` by slug -> dispensary ``id`` (best effort)."""
        payload = {
            "operationName": "ConsumerDispensaries",
            "variables": {"dispensaryFilter": {"cNameOrID": slug}},
            "query": (
                "query ConsumerDispensaries($dispensaryFilter: DispensaryFilter) {"
                " filteredDispensaries(dispensaryFilter: $dispensaryFilter) {"
                " id cName name } }"
            ),
        }
        resp = client.post(_GRAPHQL_URL, json=payload, headers=self._headers())
        resp.raise_for_status()
        data = resp.json().get("data", {})
        disps = data.get("filteredDispensaries") or []
        if isinstance(disps, list) and disps:
            return disps[0].get("id") or disps[0].get("cName")
        if isinstance(disps, dict):
            return disps.get("id") or disps.get("cName")
        return None

    def _fetch_products_json(self, client: httpx.Client, dispensary_id: str) -> dict:
        """``FilteredProducts`` page for a dispensary id -> raw GraphQL JSON."""
        payload = {
            "operationName": "FilteredProducts",
            "variables": {
                "productsFilter": {
                    "dispensaryId": dispensary_id,
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
                " type strainType Prices specialPrices Options THCContent CBDContent"
                " Image images } } }"
            ),
        }
        resp = client.post(_GRAPHQL_URL, json=payload, headers=self._headers())
        resp.raise_for_status()
        return resp.json()

    def fetch(self, store_ref: dict[str, Any]) -> list[MenuItem]:
        """Return the store's menu as ``MenuItem`` dicts (``[]`` on any failure).

        Tries the fast httpx GraphQL path first; if that yields 0 items (Cloudflare
        403 / network / schema drift), automatically falls back to the Playwright
        browser path (PRD FR2) unless explicitly disabled via ``SCRAPE_NO_BROWSER``.
        """
        menu_url = store_ref.get("menu") or store_ref.get("menu_ref") or ""
        slug = slug_from_menu_url(menu_url)

        items: list[MenuItem] = []
        if slug:
            try:
                with httpx.Client(timeout=_TIMEOUT_SEC, follow_redirects=True) as client:
                    dispensary_id = self._resolve_dispensary_id(client, slug)
                    if dispensary_id:
                        products_json = self._fetch_products_json(client, dispensary_id)
                        items = parse_filtered_products(products_json)
            except Exception:
                items = []

        if items:
            return items

        if os.getenv("SCRAPE_NO_BROWSER"):
            return []
        # httpx came back empty (almost always Cloudflare) -> browser fallback.
        return fetch_via_playwright(store_ref)
