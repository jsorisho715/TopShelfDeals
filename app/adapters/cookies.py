"""Cookies (cookies.co) menu adapter — Shopify storefront.

Strategy: cookies.co is a Shopify store, and every Shopify storefront exposes a
public, unauthenticated products feed at ``/<host>/products.json`` (optionally
``/collections/<handle>/products.json``) paginated by ``?limit=&page=``. Each
product carries ``title``, ``vendor`` (the brand — "Cookies"), ``product_type``
(our category hint), ``handle`` (deep link), ``images[].src`` and a ``variants``
list with ``title`` (size), ``price`` and ``compare_at_price`` (the regular price
when on sale). No Cloudflare gate, so the fast path is a plain ``httpx`` GET — no
browser required.

The JSON -> ``MenuItem`` mapping is the pure, network-free :func:`parse_products`
so it can be unit-tested against a fixture. On ANY failure :meth:`fetch` returns
``[]`` (Adapter protocol / PRD FR2).
"""

from __future__ import annotations

import os
import re
from typing import Any, Optional
from urllib.parse import urlparse, urlunparse

import httpx

from . import promo as _promo
from .base import MenuItem

_TIMEOUT_SEC = 20.0
_MAX_PAGES = int(os.getenv("COOKIES_PAGES", "4"))
_PAGE_SIZE = 250  # Shopify hard cap per page

_DEFAULT_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
)

# Shopify ``product_type`` (and title keyword fallback) -> our canonical category.
_CATEGORY_MAP = {
    "flower": "Flower",
    "pre-roll": "Prerolls",
    "pre-rolls": "Prerolls",
    "preroll": "Prerolls",
    "prerolls": "Prerolls",
    "edible": "Edibles",
    "edibles": "Edibles",
    "gummies": "Edibles",
    "concentrate": "Concentrates",
    "concentrates": "Concentrates",
    "extract": "Concentrates",
    "extracts": "Concentrates",
    "rosin": "Concentrates",
    "vape": "Vapes",
    "vapes": "Vapes",
    "cartridge": "Vapes",
    "cartridges": "Vapes",
    "disposable": "Vapes",
}

_STRAIN_RE = re.compile(r"\b(indica|sativa|hybrid)\b", re.I)
_SIZE_RE = re.compile(r"([\d.]+\s*(?:mg|g|oz))", re.I)


def _to_float(value: Any) -> Optional[float]:
    if value is None or value == "":
        return None
    if isinstance(value, (int, float)):
        return float(value)
    try:
        return float(str(value).replace("$", "").replace(",", "").strip())
    except (ValueError, TypeError):
        return None


def _map_category(product_type: Optional[str], title: Optional[str], tags: Any) -> Optional[str]:
    for raw in (product_type, title):
        if not raw:
            continue
        # whole-string match first, then keyword scan
        mapped = _CATEGORY_MAP.get(str(raw).strip().lower())
        if mapped:
            return mapped
        for token in re.findall(r"[a-z\-]+", str(raw).lower()):
            if token in _CATEGORY_MAP:
                return _CATEGORY_MAP[token]
    if isinstance(tags, (list, tuple)):
        for t in tags:
            mapped = _CATEGORY_MAP.get(str(t).strip().lower())
            if mapped:
                return mapped
    return None


def _strain_type(title: Optional[str], tags: Any) -> Optional[str]:
    blob = title or ""
    if isinstance(tags, (list, tuple)):
        blob += " " + " ".join(str(t) for t in tags)
    m = _STRAIN_RE.search(blob)
    return m.group(1).capitalize() if m else None


def _image(product: dict) -> Optional[str]:
    images = product.get("images")
    if isinstance(images, list):
        for img in images:
            if isinstance(img, dict):
                src = img.get("src")
                if isinstance(src, str) and src.startswith("http"):
                    return src
            elif isinstance(img, str) and img.startswith("http"):
                return img
    img = product.get("image")
    if isinstance(img, dict) and isinstance(img.get("src"), str):
        return img["src"]
    return None


def _size_from(variant: dict, title: str) -> Optional[str]:
    vt = variant.get("title")
    if isinstance(vt, str) and vt and vt.lower() != "default title":
        m = _SIZE_RE.search(vt)
        if m:
            return m.group(1).replace(" ", "").lower()
        return vt
    m = _SIZE_RE.search(title or "")
    return m.group(1).replace(" ", "").lower() if m else None


def _parse_one(product: dict, host: str) -> list[MenuItem]:
    title = product.get("title") or product.get("name")
    if not title:
        return []
    category = _map_category(product.get("product_type"), title, product.get("tags"))
    if category is None:
        return []

    brand = product.get("vendor") or "Cookies"
    img = _image(product)
    strain = _strain_type(title, product.get("tags"))
    handle = product.get("handle")
    url = None
    if host and handle:
        url = f"{host}/products/{handle}"

    variants = product.get("variants")
    if not isinstance(variants, list) or not variants:
        return []

    out: list[MenuItem] = []
    for v in variants:
        if not isinstance(v, dict):
            continue
        price = _to_float(v.get("price"))
        compare = _to_float(v.get("compare_at_price"))
        if price is None:
            continue
        if compare is not None and compare > price:
            orig, sale = compare, price
        else:
            orig = sale = price
        available = v.get("available")
        item: MenuItem = {
            "product": str(title),
            "brand": brand,
            "category": category,
            "orig": orig,
            "sale": sale,
            "size": _size_from(v, title),
            "thc": None,
            "cbd": None,
            "type": strain,
            "img": img,
            "url": url,
            "in_stock": bool(available) if isinstance(available, bool) else True,
        }
        # Shopify exposes no structured special; infer a promo only from copy.
        promo = _promo.build_promo(title=None, description=None)
        if promo:
            item.update(promo)
        out.append(item)
    return out


def parse_products(payload: Any, host: str = "") -> list[MenuItem]:
    """Parse a Shopify ``products.json`` payload into ``MenuItem`` dicts.

    Pure and network-free. Accepts the ``{"products": [...]}`` envelope or a bare
    list. Each product expands into one item per variant; non-canonical categories
    and priceless rows are skipped.
    """
    if isinstance(payload, dict):
        products = payload.get("products") or []
    elif isinstance(payload, list):
        products = payload
    else:
        products = []

    out: list[MenuItem] = []
    for product in products:
        if not isinstance(product, dict):
            continue
        try:
            out.extend(_parse_one(product, host))
        except Exception:
            continue
    return out


def _origin(menu_url: str) -> str:
    parts = urlparse(menu_url or "")
    if parts.scheme and parts.netloc:
        return urlunparse((parts.scheme, parts.netloc, "", "", "", ""))
    return "https://cookies.co"


class CookiesAdapter:
    """Shopify-storefront menu adapter for cookies.co (see module docstring)."""

    def __init__(self, user_agent: Optional[str] = None) -> None:
        self._user_agent = user_agent or os.getenv("SCRAPE_USER_AGENT") or _DEFAULT_UA

    def _headers(self) -> dict[str, str]:
        return {"User-Agent": self._user_agent, "Accept": "application/json"}

    def fetch(self, store_ref: dict[str, Any]) -> list[MenuItem]:
        menu_url = store_ref.get("menu") or store_ref.get("menu_ref") or ""
        host = _origin(menu_url)
        out: list[MenuItem] = []
        try:
            with httpx.Client(
                timeout=_TIMEOUT_SEC, follow_redirects=True, headers=self._headers()
            ) as client:
                for page in range(1, _MAX_PAGES + 1):
                    url = f"{host}/products.json?limit={_PAGE_SIZE}&page={page}"
                    try:
                        resp = client.get(url)
                    except Exception:
                        break
                    if resp.status_code != 200:
                        break
                    try:
                        payload = resp.json()
                    except Exception:
                        break
                    items = parse_products(payload, host=host)
                    if not items:
                        break
                    out.extend(items)
                    # Stop when the page wasn't full (last page).
                    products = payload.get("products") if isinstance(payload, dict) else None
                    if not isinstance(products, list) or len(products) < _PAGE_SIZE:
                        break
        except Exception:
            return out
        return out
