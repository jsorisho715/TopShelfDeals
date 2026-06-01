"""I Heart Jane menu adapter.

Strategy: Jane powers embedded dispensary menus, and every Jane storefront
hydrates its product grid from a single **Algolia** index, ``menu-products-production``
(app id ``VFM4X0N23A``), filtered by ``store_id``. So rather than scrape rendered
HTML we resolve the ``store_id``/``slug`` from the menu URL and query that index.

Authentication quirk learned from a live probe (so it's documented, not magic):

* The public search key is embedded in the store page's
  ``<script id="jane-app-secrets" type="application/json">`` blob
  (``algoliaApiKey``); the app id is the constant ``VFM4X0N23A``.
* That key is HTTP-referrer / custom-domain bound: Jane routes search through its
  own Algolia custom domain ``search.iheartjane.com`` and the key is rejected
  ("Invalid Application-ID or API key") when called from plain ``httpx`` against
  ``VFM4X0N23A-dsn.algolia.net``, and the custom domain itself is Cloudflare-gated
  to non-browser clients. So in practice live products come back only from a real
  browser context (the Playwright fallback below), while the cheap ``httpx`` path
  is still attempted first (it succeeds from some networks / may in future).

Schema (Algolia ``hits``): each hit carries ``name``, ``brand``, ``kind``
(``flower`` / ``vape`` / ``edible`` / ``extract`` / ``pre-roll``) + ``root_types``,
``category`` (the strain type — ``indica``/``sativa``/``hybrid``), ``available_weights``
(``["eighth_ounce", ...]``) keyed to ``price_<weight>`` / ``discounted_price_<weight>``
/ ``special_price_<weight>`` price fields, ``amount`` (``"1000mg"``),
``percent_thc``/``percent_cbd``, ``image_urls`` / ``product_photos``, and
``product_id`` / ``url_slug`` for the deep link.

The JSON -> ``MenuItem`` mapping is the pure, network-free :func:`parse_menu` so it
can be unit-tested against a fixture.

Robustness (Adapter protocol / PRD FR2): every request is bounded and on ANY
failure :meth:`JaneAdapter.fetch` returns ``[]`` instead of raising. The Playwright
fallback runs ONCE, headless, with the browser ALWAYS closed via
``sync_playwright``'s context manager plus a ``finally`` (we never leak Chromium
processes and never loop launching browsers), under a ~40s/store budget. Set
``SCRAPE_NO_BROWSER=1`` to disable that fallback.
"""

from __future__ import annotations

import json
import os
import re
import time
from typing import Any, Optional
from urllib.parse import urlparse

import httpx

from .base import MenuItem

_ALGOLIA_APP_ID = "VFM4X0N23A"
_ALGOLIA_INDEX = "menu-products-production"
# Jane's Algolia custom domain (what the real site uses); the raw DSN host is the
# fallback. The public search key is referrer-bound to the custom domain.
_ALGOLIA_PROXY_HOST = "search.iheartjane.com"
_ALGOLIA_DSN_HOST = f"{_ALGOLIA_APP_ID}-dsn.algolia.net"

_TIMEOUT_SEC = 20.0
_STORE_BUDGET_SEC = 40.0
_POLITE_DELAY_SEC = float(os.getenv("JANE_DELAY_SEC", "1.0"))
_PAGE_SIZE = 100
_MAX_PAGES = int(os.getenv("JANE_PAGES", "3"))
_PW_NAV_TIMEOUT_MS = 35000

_DEFAULT_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
)

# Pull the embedded secrets blob (carries ``algoliaApiKey``) out of a store page.
_APP_SECRETS_RE = re.compile(
    r'<script id="jane-app-secrets"[^>]*>(.*?)</script>', re.S
)

# Jane ``kind`` / ``root_types`` / ``custom_product_type`` -> our canonical cats.
_CATEGORY_MAP = {
    "flower": "Flower",
    "pre-roll": "Prerolls",
    "pre-rolls": "Prerolls",
    "preroll": "Prerolls",
    "prerolls": "Prerolls",
    "edible": "Edibles",
    "edibles": "Edibles",
    "extract": "Concentrates",
    "extracts": "Concentrates",
    "concentrate": "Concentrates",
    "concentrates": "Concentrates",
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
    "i": "Indica",
    "s": "Sativa",
    "h": "Hybrid",
}

# Jane weight keys -> the matching ``price_<key>`` field and a parseable size label.
_WEIGHT_SIZE = {
    "half_gram": "0.5g",
    "gram": "1g",
    "two_gram": "2g",
    "eighth_ounce": "3.5g",
    "quarter_ounce": "7g",
    "half_ounce": "14g",
    "ounce": "28g",
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


def _map_category(item: dict) -> Optional[str]:
    """Resolve our canonical category from a Jane hit.

    Prefers ``kind`` (the cleanest signal), then ``custom_product_type``, then the
    leaf of ``root_types`` (``"vape:Cartridges"`` -> ``"vape"``), then ``type``.
    """
    candidates = [item.get("kind"), item.get("custom_product_type"), item.get("type")]
    roots = item.get("root_types")
    if isinstance(roots, list):
        for r in roots:
            if isinstance(r, str):
                candidates.append(r.split(":", 1)[0])
    for raw in candidates:
        mapped = _CATEGORY_MAP.get(str(raw or "").strip().lower())
        if mapped:
            return mapped
    return None


def _map_strain_type(raw: Any) -> Optional[str]:
    if raw is None:
        return None
    return _STRAIN_TYPE_MAP.get(str(raw).strip().lower())


def _extract_image(item: dict) -> Optional[str]:
    """First usable PRODUCT image URL (always captured when present).

    ``image_urls`` is the clean list; ``product_photos[].urls`` is the imgix
    fallback (prefer the full-size ``original``).
    """
    urls = item.get("image_urls")
    if isinstance(urls, list):
        for u in urls:
            if isinstance(u, str) and u.startswith("http"):
                return u
    photos = item.get("product_photos") or item.get("photos")
    if isinstance(photos, list):
        for p in photos:
            if isinstance(p, dict):
                d = p.get("urls")
                if isinstance(d, dict):
                    for key in ("original", "extraLarge", "medium", "small"):
                        v = d.get(key)
                        if isinstance(v, str) and v.startswith("http"):
                            return v
                pid = p.get("id")
                if isinstance(pid, str) and pid.startswith("http"):
                    return pid
            elif isinstance(p, str) and p.startswith("http"):
                return p
    return None


def _available_weights(item: dict) -> list[str]:
    w = item.get("available_weights")
    if isinstance(w, list):
        return [str(x) for x in w if x]
    return []


def _price_for_weight(item: dict, weight: str, prefix: str) -> Optional[float]:
    """``price_<weight>`` / ``discounted_price_<weight>`` / ``special_price_<weight>``."""
    return _to_float(item.get(f"{prefix}_{weight}"))


def _extract_prices(item: dict) -> tuple[Optional[float], Optional[float]]:
    """Return ``(orig, sale)`` for the representative (first available) weight.

    ``orig`` is ``price_<weight>``; ``sale`` is the discounted/special price for
    that weight when present. Falls back to the per-hit ``bucket_price`` /
    ``sort_price`` summary when no per-weight price is set. ``sale`` is clamped
    to ``<= orig``.
    """
    orig = sale = None
    for weight in _available_weights(item):
        o = _price_for_weight(item, weight, "price")
        if o is None:
            continue
        disc = _price_for_weight(item, weight, "discounted_price")
        if disc is None or disc <= 0:
            disc = _price_for_weight(item, weight, "special_price")
        orig = o
        sale = disc if (disc is not None and disc > 0) else o
        break

    if orig is None:
        # Summary fallbacks: bucket_price is the regular bucket, sort_price the
        # effective (possibly discounted) representative price.
        bucket = _to_float(item.get("bucket_price"))
        sort_p = _to_float(item.get("sort_price"))
        orig = bucket if bucket is not None else sort_p
        sale = sort_p if sort_p is not None else orig

    if sale is None:
        sale = orig
    if orig is not None and sale is not None and sale > orig:
        sale = orig
    return orig, sale


def _extract_size(item: dict, category: Optional[str]) -> Optional[str]:
    """Weight/size label the pipeline can parse ("3.5g" / "100mg").

    For weight categories the representative weight key maps to a clean gram
    label (``eighth_ounce`` -> ``"3.5g"``). Edibles (and anything else) fall back
    to ``amount`` (``"100mg"``) and finally ``net_weight_grams``.
    """
    weights = _available_weights(item)
    if category != "Edibles":
        for weight in weights:
            label = _WEIGHT_SIZE.get(weight)
            if label:
                return label
    amount = item.get("amount")
    if isinstance(amount, str) and re.search(r"\d", amount):
        return amount.replace(" ", "")
    net = _to_float(item.get("net_weight_grams"))
    if net and net > 0:
        return f"{net:g}g"
    # Last resort for weight cats: map whatever weight key we have.
    for weight in weights:
        label = _WEIGHT_SIZE.get(weight)
        if label:
            return label
    return None


def _extract_potency(item: dict, code: str) -> Optional[float]:
    """THC/CBD percent. Jane exposes ``percent_thc`` / ``product_percent_thc``."""
    for key in (f"percent_{code}", f"product_percent_{code}"):
        val = _to_float(item.get(key))
        if val is not None:
            return val
    return None


def _extract_in_stock(item: dict) -> bool:
    if item.get("available_for_pickup") or item.get("available_for_delivery"):
        return True
    mcq = item.get("max_cart_quantity")
    if isinstance(mcq, (int, float)):
        return mcq > 0
    return True


def _product_url(
    item: dict, store_id: Optional[str], slug: Optional[str]
) -> Optional[str]:
    """Deep link to THIS product.

    Prefers the store-scoped menu deep link
    ``/stores/<storeId>/<slug>/menu?product_id=<id>`` when the store context is
    known, else the global product page ``/products/<id>/<url_slug>`` (fully
    derivable from the hit, keeping :func:`parse_menu` pure).
    """
    pid = item.get("product_id") or item.get("objectID")
    if pid is None:
        return None
    if store_id and slug:
        return (
            f"https://www.iheartjane.com/stores/{store_id}/{slug}"
            f"/menu?product_id={pid}"
        )
    url_slug = item.get("url_slug") or item.get("searchable_slug")
    if url_slug:
        return f"https://www.iheartjane.com/products/{pid}/{url_slug}"
    return None


# ---------------------------------------------------------------------------
# Pure parser (network-free, unit-tested against a fixture)
# ---------------------------------------------------------------------------
def _parse_one(
    item: dict, store_id: Optional[str] = None, slug: Optional[str] = None
) -> Optional[MenuItem]:
    name = item.get("name") or item.get("product_name")
    if not name:
        return None
    category = _map_category(item)
    if category is None:
        # Skip tinctures / topicals / gear / anything outside our 5 cats.
        return None

    orig, sale = _extract_prices(item)

    parsed: MenuItem = {
        "product": str(name),
        "brand": item.get("brand") or None,
        "category": category,
        "orig": orig,
        "sale": sale,
        "size": _extract_size(item, category),
        "thc": _extract_potency(item, "thc"),
        "cbd": _extract_potency(item, "cbd"),
        "type": _map_strain_type(item.get("category") or item.get("strain")),
        "img": _extract_image(item),
        "url": _product_url(item, store_id, slug),
        "in_stock": _extract_in_stock(item),
    }
    # Jane exposes per-product "special" objects (name + applies-to). Capture the
    # label so promo_* fields populate; kind/audience/weekday are inferred from it.
    try:
        from . import promo as _promo

        specials = item.get("specials") or item.get("applicable_specials")
        if isinstance(specials, dict):
            specials = [specials]
        if isinstance(specials, list) and specials:
            sp = next((s for s in specials if isinstance(s, dict)), None)
            if sp:
                title = sp.get("name") or sp.get("title") or sp.get("description")
                if title:
                    parsed.update(_promo.build_promo(
                        title=title,
                        description=sp.get("description"),
                    ))
    except Exception:
        pass
    return parsed


def _find_menu_items(data: Any) -> list[dict]:
    """Locate the product list inside a Jane/Algolia payload, tolerantly.

    Accepts a raw list of hits, an Algolia single-index response
    (``{"hits": [...]}``), a multi-index response (``{"results": [{"hits": [...]}]}``),
    or those nested under ``data``.
    """
    if isinstance(data, list):
        return [x for x in data if isinstance(x, dict)]
    if not isinstance(data, dict):
        return []

    candidates: list[Any] = [data.get("hits")]
    results = data.get("results")
    if isinstance(results, list) and results and isinstance(results[0], dict):
        candidates.append(results[0].get("hits"))
    inner = data.get("data")
    if isinstance(inner, dict):
        candidates.append(inner.get("hits"))
        candidates.append(inner.get("menu_products"))
    candidates.append(data.get("menu_products"))

    for cand in candidates:
        if isinstance(cand, list) and cand:
            return [x for x in cand if isinstance(x, dict)]
    return []


def parse_menu(
    data: Any, store_id: Optional[str] = None, slug: Optional[str] = None
) -> list[MenuItem]:
    """Parse a Jane Algolia ``hits`` payload into ``MenuItem`` dicts.

    Pure and network-free. ``store_id``/``slug`` are optional context used only to
    build the store-scoped deep link ``url``; when omitted the parser still emits
    a usable per-product page link derived from the hit. Unparseable rows and
    non-canonical categories (tinctures, topicals, gear, …) are skipped.
    """
    items: list[MenuItem] = []
    for raw in _find_menu_items(data):
        try:
            parsed = _parse_one(raw, store_id, slug)
        except Exception:
            parsed = None
        if parsed is not None:
            items.append(parsed)
    return items


# ---------------------------------------------------------------------------
# URL / store-ref helpers
# ---------------------------------------------------------------------------
def store_ref_from_menu_url(menu_url: str) -> tuple[Optional[str], Optional[str]]:
    """Resolve ``(store_id, slug)`` from a Jane menu URL.

    Handles ``/stores/<id>/<slug>/menu``, ``/embed/menu/<id>``,
    ``/embed/stores/<id>/...`` and a ``?store_id=`` query param.
    """
    if not menu_url:
        return None, None
    parsed = urlparse(menu_url)
    path = parsed.path or ""

    m = re.search(r"/stores/(\d+)(?:/([^/?#]+))?", path)
    if m:
        return m.group(1), m.group(2)
    m = re.search(r"/embed/menu/(\d+)", path)
    if m:
        return m.group(1), None
    m = re.search(r"/embed/stores/(\d+)", path)
    if m:
        return m.group(1), None
    m = re.search(r"[?&]store_id=(\d+)", menu_url)
    if m:
        return m.group(1), None
    return None, None


def canonical_menu_url(store_id: str, slug: Optional[str]) -> str:
    """The canonical Jane storefront menu page for a store id."""
    if slug:
        return f"https://www.iheartjane.com/stores/{store_id}/{slug}/menu"
    return f"https://www.iheartjane.com/stores/{store_id}/menu"


def _extract_algolia_key(html: str) -> Optional[str]:
    """Pull ``algoliaApiKey`` from the page's ``jane-app-secrets`` blob."""
    m = _APP_SECRETS_RE.search(html or "")
    if m:
        try:
            secrets = json.loads(m.group(1))
            key = secrets.get("algoliaApiKey")
            if isinstance(key, str) and key:
                return key
        except Exception:
            pass
    # Fallback: a bare ``"algoliaApiKey":"<32 hex>"`` anywhere in the bundle.
    m = re.search(r'"algoliaApiKey"\s*:\s*"([0-9a-f]{16,})"', html or "")
    return m.group(1) if m else None


def _algolia_body(store_id: str, page: int) -> dict:
    return {
        "params": (
            f"filters=store_id = {store_id}"
            f"&hitsPerPage={_PAGE_SIZE}&page={page}&query="
        )
    }


# ---------------------------------------------------------------------------
# Playwright fallback (live key is browser/Cloudflare bound) — never leaks
# ---------------------------------------------------------------------------
def _fetch_via_playwright(
    store_id: str, slug: Optional[str], user_agent: str
) -> list[MenuItem]:
    """Load the store menu in Chromium, then call the Algolia proxy in-page.

    The key in ``jane-app-secrets`` is bound to Jane's Algolia custom domain
    (``search.iheartjane.com``), which only answers from a real browser context.
    We navigate to the storefront once (establishing origin/key) and ``fetch`` the
    index in-page across a few pages. The browser is ALWAYS closed via the context
    manager + ``finally``. Returns ``[]`` on any failure.
    """
    try:
        from playwright.sync_api import sync_playwright  # local import: optional dep
    except Exception:
        return []

    js = """
    async ({ appId, index, host, storeId, page, pageSize }) => {
      let key = null;
      try {
        const el = document.getElementById('jane-app-secrets');
        if (el) key = JSON.parse(el.textContent).algoliaApiKey;
      } catch (e) {}
      if (!key) return { status: -1, items: [], error: 'no-key' };
      try {
        const r = await fetch(`https://${host}/1/indexes/${index}/query`, {
          method: 'POST',
          headers: {
            'x-algolia-application-id': appId,
            'x-algolia-api-key': key,
            'Content-Type': 'application/json',
          },
          body: JSON.stringify({ params: `filters=store_id = ${storeId}&hitsPerPage=${pageSize}&page=${page}&query=` }),
        });
        if (!r.ok) return { status: r.status, items: [] };
        const j = await r.json();
        return { status: r.status, items: (j && j.hits) || [], nbPages: j && j.nbPages };
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
                        canonical_menu_url(store_id, slug),
                        wait_until="domcontentloaded",
                        timeout=_PW_NAV_TIMEOUT_MS,
                    )
                except Exception:
                    # A partial load still establishes the origin + secrets.
                    pass
                try:
                    page.wait_for_timeout(1500)
                except Exception:
                    pass
                for page_no in range(_MAX_PAGES):
                    if time.monotonic() - start > _STORE_BUDGET_SEC:
                        break
                    try:
                        res = page.evaluate(
                            js,
                            {
                                "appId": _ALGOLIA_APP_ID,
                                "index": _ALGOLIA_INDEX,
                                "host": _ALGOLIA_PROXY_HOST,
                                "storeId": store_id,
                                "page": page_no,
                                "pageSize": _PAGE_SIZE,
                            },
                        )
                    except Exception:
                        break
                    items = res.get("items") if isinstance(res, dict) else None
                    if not items:
                        break
                    out.extend(parse_menu({"hits": items}, store_id, slug))
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
class JaneAdapter:
    """Best-effort I Heart Jane Algolia adapter (see module docstring).

    Implements the :class:`app.adapters.base.Adapter` protocol. ``fetch`` reads
    ``store_ref['menu']``, resolves the ``store_id``/``slug``, and queries the
    ``menu-products-production`` Algolia index. Tries an httpx query first (cheap),
    then a single headless-Playwright fallback that calls the same index from a
    real browser context (Jane's search key is browser/Cloudflare bound). Any
    failure yields ``[]``.
    """

    def __init__(self, user_agent: Optional[str] = None) -> None:
        self._user_agent = user_agent or os.getenv("SCRAPE_USER_AGENT") or _DEFAULT_UA

    def _page_headers(self) -> dict[str, str]:
        return {
            "User-Agent": self._user_agent,
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Accept-Language": "en-US,en;q=0.9",
        }

    def _algolia_headers(self, key: str) -> dict[str, str]:
        return {
            "x-algolia-application-id": _ALGOLIA_APP_ID,
            "x-algolia-api-key": key,
            "Content-Type": "application/json",
            "Accept": "application/json",
            "Origin": "https://www.iheartjane.com",
            "Referer": "https://www.iheartjane.com/",
            "User-Agent": self._user_agent,
        }

    def _fetch_via_httpx(
        self, store_id: str, slug: Optional[str]
    ) -> list[MenuItem]:
        """GET the store page for the search key, then query Algolia by httpx.

        Returns ``[]`` if the key can't be read or Algolia rejects the request
        (the common case: the key is bound to Jane's Cloudflare-gated custom
        domain — see module docstring — so this path usually defers to Playwright).
        """
        out: list[MenuItem] = []
        start = time.monotonic()
        try:
            with httpx.Client(
                timeout=_TIMEOUT_SEC,
                follow_redirects=True,
                headers=self._page_headers(),
            ) as client:
                try:
                    resp = client.get(canonical_menu_url(store_id, slug))
                except Exception:
                    return out
                key = _extract_algolia_key(resp.text if resp.status_code == 200 else "")
                if not key:
                    return out

                headers = self._algolia_headers(key)
                for host in (_ALGOLIA_PROXY_HOST, _ALGOLIA_DSN_HOST):
                    page_no = 0
                    host_items: list[MenuItem] = []
                    ok = False
                    while page_no < _MAX_PAGES:
                        if time.monotonic() - start > _STORE_BUDGET_SEC:
                            break
                        if page_no > 0:
                            time.sleep(_POLITE_DELAY_SEC)
                        url = f"https://{host}/1/indexes/{_ALGOLIA_INDEX}/query"
                        try:
                            r = client.post(
                                url, headers=headers, json=_algolia_body(store_id, page_no)
                            )
                        except Exception:
                            break
                        if r.status_code != 200:
                            break
                        try:
                            payload = r.json()
                        except Exception:
                            break
                        raw_items = _find_menu_items(payload)
                        if not raw_items:
                            break
                        ok = True
                        host_items.extend(parse_menu({"hits": raw_items}, store_id, slug))
                        if len(raw_items) < _PAGE_SIZE:
                            break
                        page_no += 1
                    if ok and host_items:
                        return host_items
        except Exception:
            return out
        return out

    def fetch(self, store_ref: dict[str, Any]) -> list[MenuItem]:
        """Return the store's menu as ``MenuItem`` dicts (``[]`` on any failure)."""
        menu_url = store_ref.get("menu") or store_ref.get("menu_ref") or ""
        store_id, slug = store_ref_from_menu_url(menu_url)
        if not store_id:
            return []

        items = self._fetch_via_httpx(store_id, slug)
        if items:
            return items

        if os.getenv("SCRAPE_NO_BROWSER"):
            return []
        return _fetch_via_playwright(store_id, slug, self._user_agent)
