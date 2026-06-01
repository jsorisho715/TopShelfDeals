"""Render deals into Telegram messages.

Mirrors the ``RankRow`` column layout + ``TYPE_ABBR`` from ``topshelf/app/telegram.jsx``.
Output is Telegram HTML (parse_mode="HTML"): ranked best -> worst, each row carrying a
Special (menu) link and a Route (Google Maps) link. ``photo_items`` produces per-deal
photo payloads so the bot can ``send_photo`` for the top deals.
"""

from __future__ import annotations

from html import escape

from .queries import dist_for, maps_dir_url, menu_for

TYPE_ABBR = {
    "Flower": "FLW",
    "Prerolls": "PRE",
    "Edibles": "EDI",
    "Concentrates": "CONC",
    "Vapes": "VAPE",
}


def _abbr(cat: str) -> str:
    return TYPE_ABBR.get(cat, cat or "")


def _fmt_unit(deal: dict) -> str:
    unit = deal.get("unit")
    label = deal.get("unitLabel", "")
    if unit is None:
        return ""
    return f"${unit:.1f}{label}"


def _links(shop: str) -> str:
    menu = menu_for(shop)
    route = maps_dir_url(shop)
    parts = []
    if menu:
        parts.append(f'<a href="{escape(menu, quote=True)}">Special</a>')
    if route:
        parts.append(f'<a href="{escape(route, quote=True)}">Route</a>')
    return " · ".join(parts)


def _row_html(deal: dict, rank: int, loc: str) -> str:
    cat = deal.get("cat", "")
    product = escape(str(deal.get("product", "")))
    brand = escape(str(deal.get("brand", "")))
    abbr = escape(_abbr(cat))
    sale = deal.get("sale")
    off = deal.get("off")
    shop = deal.get("shop", "")
    dist = dist_for(deal, loc)
    unit = _fmt_unit(deal)

    # Line 1: rank · TYPE · product · brand · price (−off%)
    # Only show the discount when there is one; full-price items are not "deals".
    price = f"${sale}" if sale is not None else ""
    if off:
        price += f" (−{off}%)"
    head = f"<b>{rank}.</b> <code>{abbr}</code> <b>{product}</b> · {brand}"
    if price:
        head += f" — <b>{escape(price)}</b>"

    # Line 2: shop · mi · $unit
    meta_bits = [escape(str(shop))]
    if dist is not None:
        meta_bits.append(f"{dist} mi")
    if unit:
        meta_bits.append(escape(unit))
    meta = " · ".join(meta_bits)

    links = _links(shop)
    line2 = meta
    if links:
        line2 += f"\n   {links}"
    return f"{head}\n   {line2}"


def render_ranked_html(deals: list[dict], loc: str = "oldtown", header: str | None = None) -> str:
    """Ranked best -> worst HTML table for Telegram (parse_mode='HTML')."""
    if not deals:
        return (header + "\n\n" if header else "") + "No top-shelf items match that right now. Try loosening the price or distance."

    lines: list[str] = []
    if header:
        lines.append(f"<b>{escape(header)}</b>")
        lines.append("")
    for i, d in enumerate(deals, start=1):
        lines.append(_row_html(d, i, loc))
        lines.append("")
    lines.append("<i>Tap “Special” for the menu, “Route” for directions.</i>")
    return "\n".join(lines)


def _money(v) -> str:
    """Format a price without a trailing .0 (e.g. 30.0 -> '30', 12.5 -> '12.5')."""
    try:
        f = float(v)
    except (TypeError, ValueError):
        return str(v)
    return str(int(f)) if f == int(f) else f"{f:g}"


def _price_line(deal: dict) -> str:
    sale = deal.get("sale")
    orig = deal.get("orig")
    off = deal.get("off")
    unit = deal.get("unit")
    label = deal.get("unitLabel", "")
    parts = []
    if sale is not None:
        seg = f"<b>${_money(sale)}</b>"
        if orig is not None and orig != sale:
            seg += f" <s>${_money(orig)}</s>"
        parts.append(seg)
    if off:
        parts.append(f"\u2212{off}%")
    if unit is not None:
        parts.append(f"${unit:.1f}{label}")
    return " · ".join(parts)


def deal_caption(deal: dict, loc: str = "oldtown") -> str:
    """Rich photo-card caption (Telegram HTML, <=1024 chars)."""
    fire = "\U0001F525 " if deal.get("fire") else ""
    product = escape(str(deal.get("product", "")))
    brand = escape(str(deal.get("brand", "")))
    lines = [f"{fire}<b>{product}</b> · {brand}"]

    price = _price_line(deal)
    if price:
        lines.append(price)

    specs = []
    if deal.get("type"):
        specs.append(escape(str(deal["type"])))
    thc = deal.get("thc")
    if thc and deal.get("unitLabel") != "/10mg":
        specs.append(f"{thc}% THC")
    dist = dist_for(deal, loc)
    if dist is not None:
        specs.append(f"{dist} mi")
    if specs:
        lines.append(" · ".join(specs))

    reason = deal.get("fireReason")
    if deal.get("fire") and reason:
        lines.append(f"\U0001F525 {escape(str(reason))}")

    return "\n".join(lines)[:1024]


def deal_buttons(deal: dict) -> list[tuple[str, str]]:
    """(label, url) pairs for a deal's inline buttons: the special + Directions.

    Prefers the per-product deep link (``deal['url']``) so the button opens the
    actual special; falls back to the dispensary menu when no product link exists.
    """
    shop = deal.get("shop", "")
    out: list[tuple[str, str]] = []
    special = deal.get("url") or menu_for(shop)
    if special and special != "#":
        label = "\U0001F525 View special" if deal.get("url") else "\U0001F6D2 Open menu"
        out.append((label, special))
    route = maps_dir_url(shop)
    if route:
        out.append(("\U0001F4CD Directions", route))
    return out


def shop_groups(deals: list[dict], loc: str = "oldtown") -> list[dict]:
    """Group deals by shop, nearest -> furthest; specials best -> worst within each."""
    groups: dict[str, list[dict]] = {}
    for d in deals:
        groups.setdefault(d.get("shop", "?"), []).append(d)
    out = []
    for shop, items in groups.items():
        items = sorted(items, key=lambda d: d.get("score", 0), reverse=True)
        d0 = items[0]
        dist = dist_for(d0, loc)
        out.append({"shop": shop, "dist": dist, "items": items})
    out.sort(key=lambda g: g["dist"] if g["dist"] is not None else 9999)
    return out


def shop_header_html(group: dict) -> str:
    """Header line shown before a shop's cards."""
    shop = escape(str(group.get("shop", "")))
    dist = group.get("dist")
    n = len(group.get("items", []))
    bits = [f"\U0001F4CD <b>{shop}</b>"]
    if dist is not None:
        bits.append(f"{dist} mi")
    bits.append(f"{n} special" + ("" if n == 1 else "s"))
    return " · ".join(bits)


def photo_items(deals: list[dict], loc: str = "oldtown") -> list[dict]:
    """Per-deal photo payloads: ``{img, caption_html}``.

    Skips deals without an ``img`` (the text row still represents them).
    """
    items: list[dict] = []
    for d in deals:
        img = d.get("img")
        if not img:
            continue
        product = escape(str(d.get("product", "")))
        brand = escape(str(d.get("brand", "")))
        sale = d.get("sale")
        off = d.get("off")
        fire = "🔥 " if d.get("fire") else ""
        price = f"${sale}" if sale is not None else ""
        if off:
            price += f" (−{off}%)"
        links = _links(d.get("shop", ""))
        caption = f"{fire}<b>{product}</b> · {brand}"
        if price:
            caption += f"\n<b>{escape(price)}</b>"
        if links:
            caption += f"\n{links}"
        items.append({"img": img, "caption_html": caption})
    return items
