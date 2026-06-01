"""FastAPI routes for the TopShelf SPA (see CLAUDE.md §3)."""
from __future__ import annotations

import json
import os
import sqlite3
from pathlib import Path

from fastapi import APIRouter, Body, HTTPException

from app import db, notify
from app.bot.render import photo_items, render_ranked_html
from app.pipeline.serialize import bootstrap_payload

router = APIRouter(prefix="/api")

_DISP_PATH = Path(__file__).resolve().parent / "seed" / "dispensaries.json"


def _owner_chat_id() -> str | None:
    """The .env owner chat id (implicitly allowed, never stored in allowed_users)."""
    return (os.getenv("TELEGRAM_CHAT_ID") or "").strip() or None


def _live_store_index() -> dict[str, dict]:
    """Map dispensary name -> its dispensaries.json record (addr/menu/platform/dist)."""
    try:
        data = json.loads(_DISP_PATH.read_text(encoding="utf-8"))
    except Exception:
        return {}
    return {d.get("name"): d for d in data.get("dispensaries", [])}


def _payload_with_live() -> dict:
    """Bootstrap payload, preferring real live scraped deals (with product photos).

    When a fresh live cache exists, its deals replace the seed deals and the live
    stores are merged into ``shops``/``dist`` so the cards' Special/Route links and
    distances resolve. Falls back to seed-only when there's no live cache yet.
    """
    payload = bootstrap_payload()
    try:
        from app.scrape import load_cached_live_deals

        live = load_cached_live_deals(max_age_hours=12)
    except Exception:
        live = []
    if not live:
        return payload

    shops = dict(payload["shops"])
    dist = {loc: dict(m) for loc, m in payload["dist"].items()}
    idx = _live_store_index()
    for d in live:
        shop = d.get("shop")
        if not shop or shop in shops:
            continue
        rec = idx.get(shop) or {}
        shops[shop] = {
            "addr": rec.get("addr", ""),
            "platform": rec.get("platform", "Dutchie"),
            "menu": rec.get("menu", "#"),
        }
        for loc, miles in (rec.get("dist") or {}).items():
            dist.setdefault(loc, {})[shop] = miles

    # Overlay the authoritative geocoded per-anchor distances from the live deals
    # (every shop, every anchor incl North Phoenix) so the dropdown radius is exact.
    for d in live:
        shop = d.get("shop")
        ad = d.get("distByAnchor")
        if shop and isinstance(ad, dict):
            for loc, miles in ad.items():
                dist.setdefault(loc, {})[shop] = miles

    payload["deals"] = live
    payload["shops"] = shops
    payload["dist"] = dist
    return payload


@router.get("/bootstrap")
def get_bootstrap() -> dict:
    """One call that powers first paint: deals + shops + locations + dist + cats."""
    return _payload_with_live()


@router.get("/health")
def get_health() -> dict:
    """Per-adapter / per-store scrape telemetry + live-deal summary.

    Surfaces the last scrape's per-store status (fresh / retained-stale / empty /
    no-adapter) so a zero-coverage regression is visible instead of silent, plus
    rollups by platform and a snapshot of the live cache (totals, fire, promo).
    """
    try:
        from app.scrape import load_scrape_report, load_cached_live_deals
    except Exception:
        return {"ok": False, "reason": "scrape module unavailable"}

    report = load_scrape_report()
    stores = report.get("stores", []) or []

    by_status: dict[str, int] = {}
    by_platform: dict[str, dict] = {}
    for s in stores:
        status = s.get("status", "unknown")
        by_status[status] = by_status.get(status, 0) + 1
        plat = s.get("platform") or "?"
        agg = by_platform.setdefault(plat, {"stores": 0, "producing": 0, "kept": 0})
        agg["stores"] += 1
        agg["kept"] += int(s.get("kept") or 0)
        if (s.get("kept") or 0) > 0:
            agg["producing"] += 1

    try:
        live = load_cached_live_deals() or []
    except Exception:
        live = []
    live_shops = {d.get("shop") for d in live if d.get("shop")}
    summary = {
        "deals": len(live),
        "shops": len(live_shops),
        "fire": sum(1 for d in live if d.get("fire")),
        "with_promo": sum(1 for d in live if d.get("promo_title")),
        "on_sale": sum(1 for d in live if (d.get("off") or 0) > 0),
        "stale": sum(1 for d in live if d.get("stale")),
    }
    return {
        "ok": True,
        "generatedAt": report.get("generatedAt"),
        "summary": summary,
        "by_status": by_status,
        "by_platform": by_platform,
        "stores": stores,
    }


@router.get("/deals")
def get_deals(location: str | None = None) -> dict:
    """Refresh endpoint: returns the augmented deals + generatedAt."""
    payload = _payload_with_live()
    return {"deals": payload["deals"], "generatedAt": payload["generatedAt"]}


@router.get("/filters")
def get_filters() -> list[dict]:
    conn = db.get_conn()
    try:
        return db.list_filters(conn)
    finally:
        conn.close()


@router.post("/filters")
def post_filter(preset: dict = Body(...)) -> dict:
    conn = db.get_conn()
    try:
        created = db.create_filter(
            conn,
            name=preset.get("name", ""),
            criteria=preset.get("c"),
            active=preset.get("active", True),
            telegram_alerts_on=preset.get("telegram_alerts_on", True),
        )
        return created
    finally:
        conn.close()


@router.patch("/filters/{fid}")
def patch_filter(fid: str, preset: dict = Body(...)) -> dict:
    conn = db.get_conn()
    try:
        if db.get_filter(conn, fid) is None:
            raise HTTPException(status_code=404, detail="filter not found")
        fields = {}
        if "name" in preset:
            fields["name"] = preset["name"]
        if "c" in preset:
            fields["criteria"] = preset["c"]
        if "active" in preset:
            fields["active"] = preset["active"]
        if "telegram_alerts_on" in preset:
            fields["telegram_alerts_on"] = preset["telegram_alerts_on"]
        updated = db.update_filter(conn, fid, **fields)
        return updated
    finally:
        conn.close()


@router.delete("/filters/{fid}")
def delete_filter(fid: str) -> dict:
    conn = db.get_conn()
    try:
        ok = db.delete_filter(conn, fid)
        if not ok:
            raise HTTPException(status_code=404, detail="filter not found")
        return {"ok": True}
    finally:
        conn.close()


@router.post("/ping")
def post_ping(body: dict = Body(...)) -> dict:
    """Send a single deal (or list) to the user's Telegram chat.

    Body shape: ``{"deal": <Deal>}`` or ``{"deals": [<Deal>, ...], "loc": "oldtown"}``.
    Returns ``{"ok": bool, "configured": bool}``. Never raises on Telegram
    failure — ``notify.*`` swallows errors and returns False.
    """
    if not notify.is_configured():
        return {"ok": False, "configured": False, "reason": "TELEGRAM_BOT_TOKEN or TELEGRAM_CHAT_ID missing"}

    deal = body.get("deal")
    deals = body.get("deals") or ([deal] if deal else [])
    if not deals:
        raise HTTPException(status_code=400, detail="body must include 'deal' or 'deals'")
    loc = body.get("loc") or "oldtown"

    sent_any = False
    # Prefer rich photo+caption when the deal has an image.
    photos = photo_items(deals, loc=loc)
    photo_ids = {id(d) for d in deals if d.get("img")}
    text_deals = [d for d in deals if id(d) not in photo_ids]

    for p in photos:
        if notify.send_photo(p["img"], p["caption_html"]):
            sent_any = True

    if text_deals:
        html = render_ranked_html(text_deals, loc=loc, header="Pinned from TopShelf")
        if notify.send_message(html):
            sent_any = True

    return {"ok": sent_any, "configured": True}


# ---------------------------------------------------------------------------
# Allowlist (inbound-only Telegram users who may talk to the bot)
# ---------------------------------------------------------------------------
@router.get("/users/owner")
def get_users_owner() -> dict:
    """The .env owner row + whether Telegram is configured (for the UI header)."""
    owner = _owner_chat_id()
    return {"chat_id": owner, "configured": bool(owner)}


@router.get("/users")
def get_users() -> list[dict]:
    """All allowlisted users (the owner is returned separately via /users/owner)."""
    conn = db.get_conn()
    try:
        return db.list_allowed_users(conn)
    finally:
        conn.close()


@router.post("/users")
def post_user(body: dict = Body(...)) -> dict:
    """Add a chat id to the allowlist. Rejects the owner id and duplicates."""
    chat_id = str(body.get("chat_id") or "").strip()
    label = str(body.get("label") or "").strip()
    if not chat_id:
        raise HTTPException(status_code=400, detail="chat_id is required")
    if chat_id == _owner_chat_id():
        raise HTTPException(status_code=400, detail="That chat id is the owner (already allowed).")

    conn = db.get_conn()
    try:
        try:
            return db.add_allowed_user(conn, chat_id=chat_id, label=label)
        except sqlite3.IntegrityError:
            raise HTTPException(status_code=409, detail="That chat id is already on the allowlist.")
    finally:
        conn.close()


@router.patch("/users/{uid}")
def patch_user(uid: int, body: dict = Body(...)) -> dict:
    conn = db.get_conn()
    try:
        if db.get_allowed_user(conn, uid) is None:
            raise HTTPException(status_code=404, detail="user not found")
        fields = {}
        if "label" in body:
            fields["label"] = str(body["label"] or "")
        if "active" in body:
            fields["active"] = bool(body["active"])
        return db.update_allowed_user(conn, uid, **fields)
    finally:
        conn.close()


@router.delete("/users/{uid}")
def delete_user(uid: int) -> dict:
    conn = db.get_conn()
    try:
        ok = db.delete_allowed_user(conn, uid)
        if not ok:
            raise HTTPException(status_code=404, detail="user not found")
        return {"ok": True}
    finally:
        conn.close()
