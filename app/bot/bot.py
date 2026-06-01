"""TopShelf Telegram bot — python-telegram-bot v21, async long-polling.

Every reply is a ranked list best -> worst (``render_ranked_html``) with per-row
Special (menu) + Route (Google Maps) links, followed by up to the top ~3 product
photos so the user sees what they're buying.

Run with::

    .\\.venv\\Scripts\\python.exe -m app.bot.bot

If ``TELEGRAM_BOT_TOKEN`` is unset, prints a friendly message and exits cleanly.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import socket
import time
from html import escape
from io import BytesIO
from pathlib import Path

import httpx
from dotenv import load_dotenv

from .. import db
from ..pipeline.serialize import bootstrap_payload
from ..seed.seed_data import TS_LOCATIONS
from .queries import describe_query, parse_query, rank
from .render import (
    deal_buttons,
    deal_caption,
    photo_items,
    render_ranked_html,
    shop_groups,
    shop_header_html,
)

load_dotenv()
log = logging.getLogger("topshelf.bot")

TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "").strip()

DEFAULT_LOC = "oldtown"

# Per-chat "measure distances from here" preference, persisted as {chat_id: loc_id}.
_PREFS_PATH = Path(__file__).resolve().parents[2] / "data" / "bot_prefs.json"
_VALID_LOCS = {loc["id"] for loc in TS_LOCATIONS}


def _load_prefs() -> dict:
    try:
        return json.loads(_PREFS_PATH.read_text(encoding="utf-8"))
    except Exception:
        return {}


def _get_loc(chat_id) -> str:
    """The chat's chosen location id (falls back to ``DEFAULT_LOC``)."""
    loc = _load_prefs().get(str(chat_id))
    return loc if loc in _VALID_LOCS else DEFAULT_LOC


def _set_loc(chat_id, loc: str) -> None:
    """Persist a chat's location choice to ``data/bot_prefs.json``."""
    if loc not in _VALID_LOCS:
        return
    prefs = _load_prefs()
    prefs[str(chat_id)] = loc
    try:
        _PREFS_PATH.parent.mkdir(parents=True, exist_ok=True)
        _PREFS_PATH.write_text(json.dumps(prefs, indent=2), encoding="utf-8")
    except Exception as exc:  # noqa: BLE001 - never crash a handler over prefs IO
        log.warning("could not persist bot prefs: %s", exc)


MAX_PHOTOS = 3
# Grouped-card reply caps (avoid flooding the chat).
MAX_SHOPS = 4
MAX_PER_SHOP = 3
MAX_TOTAL_CARDS = 10

# Manual /refresh hits live dispensary menus, so it's rate-limited across ALL
# allowlisted users (be a polite scraper, PRD FR2). The owner bypasses the
# cooldown. State is process-local (the bot is a single long-polling process).
REFRESH_COOLDOWN_SEC = 300  # 5 minutes shared
_last_refresh_monotonic = 0.0
_refresh_in_progress = False

# Map a slash command -> (category | None, count). None category == all deals.
_CATEGORY_COMMANDS = {
    "flower": ("Flower", 6),
    "prerolls": ("Prerolls", 6),
    "edibles": ("Edibles", 6),
    "hash": ("Concentrates", 6),
    "concentrates": ("Concentrates", 6),
    "vapes": ("Vapes", 6),
}

INTRO = (
    "🌿 <b>Welcome to TopShelf Bot!</b> 👋\n"
    "Your pocket dealfinder for Scottsdale top-shelf deals — ranked best → worst and "
    "grouped by the shop nearest you, with tap-through <b>Open menu</b> and "
    "<b>Directions</b> buttons on every card.\n\n"
    "You're on the list, so ask away anytime.\n\n"
    "<b>Commands</b>\n"
    "• /deals — the top deals right now\n"
    "• /flower · /prerolls · /edibles · /hash · /concentrates · /vapes — best in a category\n"
    "• /location — set where distances are measured from\n"
    "• /refresh — pull fresh prices from the live menus now (about once every 5 min)\n"
    "• /digest — this week's best + upcoming recurring drops\n"
    "• /help — show this again\n\n"
    "<b>Or just ask in plain English</b>\n"
    "• <i>hash under $25</i>\n"
    "• <i>flower near old town</i>\n"
    "• <i>edibles</i>\n\n"
    "<b>Behind the scenes</b>\n"
    "🔔 a morning round-up of new 🔥 fire deals\n"
    "⏰ a heads-up the night before recurring deals\n"
    "📊 a weekly digest every Sunday evening\n\n"
    "<i>All times America/Phoenix.</i>"
)

# Slash-command menu shown in Telegram's UI (the blue Menu button + autocomplete).
_BOT_COMMANDS = [
    ("deals", "Top deals right now"),
    ("flower", "Top flower deals"),
    ("prerolls", "Top preroll deals"),
    ("edibles", "Top edible deals"),
    ("hash", "Top hash / concentrate deals"),
    ("concentrates", "Top concentrate deals"),
    ("vapes", "Top vape deals"),
    ("location", "Set the location distances are measured from"),
    ("refresh", "Refresh the feed from live menus"),
    ("digest", "This week's best + upcoming recurring"),
    ("help", "What I can do"),
]


def _load_deals() -> list[dict]:
    """Prefer real live scraped deals (which carry real product photos).

    Falls back to the seed data only when there's no fresh live cache yet.
    """
    try:
        from ..scrape import load_cached_live_deals

        live = load_cached_live_deals(max_age_hours=12)
    except Exception:
        live = []
    if live:
        return live
    return bootstrap_payload()["deals"]


def _category_rows(deals: list[dict], cat: str) -> list[dict]:
    return [d for d in deals if d.get("cat") == cat]


# --------------------------------------------------------------------------- #
# Telegram glue (imported lazily inside handlers-free zone for testability).
# --------------------------------------------------------------------------- #


def _authorized(update) -> bool:
    """True if the update comes from the owner or an active allowlisted chat.

    The ``.env`` owner (``TELEGRAM_CHAT_ID``) is always allowed, even if the DB is
    unreachable. Additional inbound-only users live in the ``allowed_users`` table
    (managed from the web UI). A DB failure degrades safely to owner-only.

    When no owner is configured at all (dev), behaviour is unchanged: open access.
    """
    chat = update.effective_chat
    if chat is None:
        return False
    cid = str(chat.id)
    if not TELEGRAM_CHAT_ID:
        return True
    if cid == TELEGRAM_CHAT_ID:
        return True
    try:
        conn = db.get_conn()
        try:
            return db.is_allowed_chat_id(conn, cid)
        finally:
            conn.close()
    except Exception:  # noqa: BLE001 - DB trouble -> owner-only (safe default)
        return False


async def _photo_bytes(url: str):
    """Download an image as bytes (so Telegram doesn't have to fetch the URL).

    Handles extensionless/webp S3 images that ``reply_photo(photo=url)`` often
    rejects. Returns a BytesIO or None on any failure (never raises).
    """
    if not url:
        return None
    try:
        async with httpx.AsyncClient(follow_redirects=True, timeout=15) as client:
            r = await client.get(url)
        if r.status_code == 200 and r.content:
            buf = BytesIO(r.content)
            buf.name = "deal.jpg"
            return buf
    except Exception as exc:  # noqa: BLE001
        log.warning("image download failed (%s): %s", url, exc)
    return None


async def _send_card(message, deal: dict, loc: str = DEFAULT_LOC) -> None:
    """Send one deal as a rich photo card with [Open menu] [Directions] buttons."""
    from telegram import InlineKeyboardButton, InlineKeyboardMarkup

    caption = deal_caption(deal, loc=loc)
    btns = deal_buttons(deal)
    markup = (
        InlineKeyboardMarkup([[InlineKeyboardButton(text, url=url) for text, url in btns]])
        if btns
        else None
    )

    photo = await _photo_bytes(deal.get("img"))
    if photo is not None:
        try:
            await message.reply_photo(
                photo=photo, caption=caption, parse_mode="HTML", reply_markup=markup
            )
            return
        except Exception as exc:  # noqa: BLE001
            log.warning("reply_photo failed for %s: %s", deal.get("product"), exc)
    # Fallback: text card (still carries the buttons).
    try:
        await message.reply_html(caption, reply_markup=markup, disable_web_page_preview=True)
    except Exception as exc:  # noqa: BLE001
        log.warning("reply_html card failed for %s: %s", deal.get("product"), exc)


async def _reply_grouped(
    update, deals: list[dict], header: str | None, loc: str = DEFAULT_LOC
) -> None:
    """Reply grouped by nearest shop -> furthest; specials best->worst within each."""
    message = update.effective_message
    groups = shop_groups(deals, loc=loc)
    if not groups:
        await message.reply_text(
            "No qualifying deals match that right now. Try loosening the price or distance."
        )
        return

    if header:
        await message.reply_html(
            f"<b>{escape(header)}</b> \u2014 by nearest shop", disable_web_page_preview=True
        )

    sent = 0
    for group in groups[:MAX_SHOPS]:
        await message.reply_html(shop_header_html(group), disable_web_page_preview=True)
        for deal in group["items"][:MAX_PER_SHOP]:
            await _send_card(message, deal, loc=loc)
            sent += 1
            if sent >= MAX_TOTAL_CARDS:
                return


async def cmd_start(update, context) -> None:
    if not _authorized(update):
        return
    await update.effective_message.reply_html(INTRO, disable_web_page_preview=True)


async def cmd_deals(update, context) -> None:
    if not _authorized(update):
        return
    loc = _get_loc(update.effective_chat.id)
    deals = _load_deals()
    await _reply_grouped(update, deals, header="Top deals", loc=loc)


async def cmd_category(update, context) -> None:
    if not _authorized(update):
        return
    loc = _get_loc(update.effective_chat.id)
    cmd = (update.effective_message.text or "").lstrip("/").split()[0].split("@")[0].lower()
    cat, n = _CATEGORY_COMMANDS.get(cmd, (None, 6))
    deals = _load_deals()
    rows = _category_rows(deals, cat) if cat else deals
    await _reply_grouped(update, rows, header=f"Top {cat or 'deals'}", loc=loc)


def _fmt_secs(seconds: float) -> str:
    """Humanize a short duration, e.g. ``'4m 12s'`` / ``'45s'``."""
    total = max(0, int(round(seconds)))
    minutes, secs = divmod(total, 60)
    if minutes and secs:
        return f"{minutes}m {secs}s"
    if minutes:
        return f"{minutes}m"
    return f"{secs}s"


async def cmd_refresh(update, context) -> None:
    """Refresh the live feed on demand (rate-limited; owner bypasses the cooldown)."""
    global _last_refresh_monotonic, _refresh_in_progress
    if not _authorized(update):
        return

    message = update.effective_message
    chat = update.effective_chat
    is_owner = chat is not None and str(chat.id) == TELEGRAM_CHAT_ID

    if _refresh_in_progress:
        await message.reply_text(
            "A refresh is already running — hang tight, fresh deals are on the way."
        )
        return

    if not is_owner and _last_refresh_monotonic:
        elapsed = time.monotonic() - _last_refresh_monotonic
        if elapsed < REFRESH_COOLDOWN_SEC:
            wait = REFRESH_COOLDOWN_SEC - elapsed
            await message.reply_text(
                f"The feed was just refreshed. Try again in {_fmt_secs(wait)} — "
                "meanwhile /deals shows the latest set."
            )
            return

    _refresh_in_progress = True
    try:
        await message.reply_text(
            "🔄 Refreshing the feed from live menus — this can take a moment…"
        )
        deals: list[dict] = []
        try:
            from ..scrape import scrape_all

            deals = await asyncio.to_thread(scrape_all, True)
        except Exception as exc:  # noqa: BLE001 - never crash the handler
            log.exception("manual /refresh failed: %s", exc)
            await message.reply_text(
                "Refresh hit a snag — showing the latest cached deals instead."
            )
            deals = _load_deals()

        # Mark the attempt so the shared cooldown holds even on a partial/failed run.
        _last_refresh_monotonic = time.monotonic()

        if not deals:
            await message.reply_text(
                "Refresh finished but no live deals came back (menus may be gated right "
                "now). Try /deals for the latest cached set."
            )
            return

        await _reply_grouped(
            update,
            deals,
            header=f"Refreshed · {len(deals)} live deals",
            loc=_get_loc(update.effective_chat.id),
        )
    finally:
        _refresh_in_progress = False


async def cmd_digest(update, context) -> None:
    if not _authorized(update):
        return
    loc = _get_loc(update.effective_chat.id)
    deals = _load_deals()
    top = rank(deals, 4)
    text = render_ranked_html(top, loc=loc, header="📊 Weekly digest — this week's best")

    # Upcoming recurring footer (next themed drops we know about).
    recurring = [d for d in deals if d.get("recurring") and d.get("dow")]
    if recurring:
        upcoming = " · ".join(
            f"{d['brand']} {d['dow']}" for d in rank(recurring, 4)
        )
        text += f"\n\n<b>Upcoming recurring:</b> {upcoming}"
    await update.effective_message.reply_html(text, disable_web_page_preview=True)
    for item in photo_items(top, loc=loc)[:MAX_PHOTOS]:
        try:
            await update.effective_message.reply_photo(
                photo=item["img"], caption=item["caption_html"], parse_mode="HTML"
            )
        except Exception:
            continue


async def on_text(update, context) -> None:
    if not _authorized(update):
        return
    loc = _get_loc(update.effective_chat.id)
    q = update.effective_message.text or ""
    deals = _load_deals()
    parsed = parse_query(q, deals)
    rows = rank(parsed["rows"], 6)
    if not rows:
        await update.effective_message.reply_text(
            "No qualifying deals match that right now. Try loosening the price or distance."
        )
        return
    header = describe_query(parsed)
    await _reply_grouped(update, parsed["rows"], header=header, loc=loc)


async def cmd_location(update, context) -> None:
    """Show a one-tap location picker (distances are measured from the choice)."""
    if not _authorized(update):
        return
    from telegram import InlineKeyboardButton, InlineKeyboardMarkup

    current = _get_loc(update.effective_chat.id)
    rows = [
        [
            InlineKeyboardButton(
                f"{loc['icon']} {loc['label']} · {loc['sub']}",
                callback_data=f"setloc:{loc['id']}",
            )
        ]
        for loc in TS_LOCATIONS
    ]
    here = next((l for l in TS_LOCATIONS if l["id"] == current), None)
    label = f"{here['label']} ({here['sub']})" if here else current
    await update.effective_message.reply_text(
        f"📍 Measuring deals from {label}. Pick where to measure distances from:",
        reply_markup=InlineKeyboardMarkup(rows),
    )


async def on_set_location(update, context) -> None:
    """Persist the tapped location and confirm in place."""
    query = update.callback_query
    if query is None:
        return
    await query.answer()
    if not _authorized(update):
        return
    data = query.data or ""
    loc_id = data.split(":", 1)[1] if ":" in data else ""
    chat = update.effective_chat
    if chat is not None and loc_id in _VALID_LOCS:
        _set_loc(chat.id, loc_id)
    here = next((l for l in TS_LOCATIONS if l["id"] == loc_id), None)
    label = f"{here['label']} ({here['sub']})" if here else loc_id
    try:
        await query.edit_message_text(f"Measuring deals from {label}. Try /deals.")
    except Exception:  # noqa: BLE001 - confirmation is best-effort
        pass


async def _post_init(application) -> None:
    """On startup: register the slash-command menu and greet the owner."""
    from telegram import BotCommand

    try:
        await application.bot.set_my_commands(
            [BotCommand(c, desc) for c, desc in _BOT_COMMANDS]
        )
    except Exception:
        pass

    if TELEGRAM_CHAT_ID:
        try:
            await application.bot.send_message(
                chat_id=int(TELEGRAM_CHAT_ID),
                text=INTRO,
                parse_mode="HTML",
                disable_web_page_preview=True,
            )
        except Exception:
            pass


def build_application():
    """Construct the python-telegram-bot Application with all handlers wired."""
    from telegram.ext import (
        Application,
        CallbackQueryHandler,
        CommandHandler,
        MessageHandler,
        filters,
    )

    app = Application.builder().token(TELEGRAM_BOT_TOKEN).post_init(_post_init).build()
    app.add_handler(CommandHandler(["start", "help"], cmd_start))
    app.add_handler(CommandHandler("deals", cmd_deals))
    app.add_handler(
        CommandHandler(
            ["flower", "prerolls", "edibles", "hash", "concentrates", "vapes"],
            cmd_category,
        )
    )
    app.add_handler(CommandHandler("location", cmd_location))
    app.add_handler(CallbackQueryHandler(on_set_location, pattern="^setloc:"))
    app.add_handler(CommandHandler("refresh", cmd_refresh))
    app.add_handler(CommandHandler("digest", cmd_digest))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, on_text))
    return app


# Cross-process singleton: only ONE bot may poll getUpdates at a time, or
# Telegram returns "Conflict: terminated by other getUpdates request". Binding a
# fixed localhost port is an atomic, OS-backed mutex — the port is released the
# instant the process dies, so restarts are clean. This guards against the venv
# launcher double-spawning and against accidental duplicate launches.
_SINGLETON_PORT = 49217


def _acquire_singleton() -> socket.socket | None:
    """Return a bound socket holding the singleton lock, or None if taken."""
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        s.bind(("127.0.0.1", _SINGLETON_PORT))
        s.listen(1)
        return s  # caller keeps a reference for the process lifetime
    except OSError:
        s.close()
        return None


def main() -> None:
    if not TELEGRAM_BOT_TOKEN:
        print("Set TELEGRAM_BOT_TOKEN in .env to run the bot.")
        return

    lock = _acquire_singleton()
    if lock is None:
        print(
            "Another TopShelf bot instance is already running "
            f"(singleton port {_SINGLETON_PORT} is held). Exiting."
        )
        return

    try:
        app = build_application()
        print("TopShelf bot starting (long-polling). Ctrl+C to stop.")
        app.run_polling()
    finally:
        lock.close()


if __name__ == "__main__":
    main()
