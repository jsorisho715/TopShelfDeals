"""APScheduler jobs for TopShelf (CLAUDE.md §7).

All scheduling is pinned to ``America/Phoenix`` (no DST). An ``AsyncIOScheduler``
runs four jobs:

* ``job_scrape``             — refresh live deals every ~3-5h (jittered, polite).
* ``job_daily_alert``        — 09:00, batched fire-deal alert (deduped).
* ``job_recurring_reminders``— 18:30, evening-before heads-up for tomorrow's
  recurring deals.
* ``job_weekly_digest``      — Sunday 18:00, the week's best + upcoming recurring.

Jobs are plain sync functions (so they compose with the synchronous
``app.notify`` sender); ``AsyncIOScheduler`` runs them in its default thread-pool
executor. Every job is defensive — it logs and swallows exceptions so a single
failure never tears down the scheduler.

The web app calls :func:`start_scheduler` / :func:`shutdown_scheduler`;
:func:`build_scheduler` wires the jobs without starting (handy for tests), and
:func:`run_job_now` invokes a job by name synchronously for manual verification.
"""

from __future__ import annotations

import logging
import os
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.interval import IntervalTrigger

try:
    from dotenv import load_dotenv

    load_dotenv()
except Exception:  # pragma: no cover - dotenv is a soft dependency
    pass

from . import db, notify
from .bot.queries import dist_for
from .bot.render import render_ranked_html
from .pipeline.serialize import bootstrap_payload
from .scrape import get_live_deals, scrape_all

log = logging.getLogger("topshelf.scheduler")

TIMEZONE = os.getenv("TIMEZONE", "America/Phoenix")
try:
    _TZ = ZoneInfo(TIMEZONE)
except Exception:  # pragma: no cover - bad env value
    _TZ = ZoneInfo("America/Phoenix")

_ALERT_LOC = "oldtown"


# ---------------------------------------------------------------------------
# Small helpers
# ---------------------------------------------------------------------------
def _now() -> datetime:
    return datetime.now(_TZ)


def _now_iso() -> str:
    return _now().isoformat(timespec="seconds")


def _conn():
    """Open a working connection with FK enforcement OFF.

    ``notifications_sent.deal_id`` references ``deals(id)`` (an integer PK), but
    the augmented deals we alert on carry the seed/string id (e.g. ``"fl1"``)
    that may not exist in the ``deals`` table. We store that string id for dedup
    matching, so foreign-key checks must be relaxed on this connection.
    """
    conn = db.get_conn()
    try:
        conn.execute("PRAGMA foreign_keys = OFF;")
    except Exception:  # pragma: no cover
        pass
    return conn


def _blended_deals() -> list[dict]:
    """Live deals blended over the seed payload; live wins, deduped by id."""
    live: list[dict] = []
    try:
        live = get_live_deals() or []
    except Exception as exc:  # noqa: BLE001
        log.warning("get_live_deals failed: %s", exc)
        live = []

    seed: list[dict] = []
    try:
        seed = bootstrap_payload().get("deals", []) or []
    except Exception as exc:  # noqa: BLE001
        log.warning("bootstrap_payload failed: %s", exc)
        seed = []

    by_id: dict = {}
    for d in seed:
        by_id[d.get("id")] = d
    for d in live:  # live takes priority
        by_id[d.get("id")] = d
    return list(by_id.values())


def _deal_matches_filter(deal: dict, c: dict, loc: str = _ALERT_LOC) -> bool:
    """Port of the dashboard.jsx preset matcher.

    ``(cat == 'All' || d.cat == cat) && getDist(d, loc) <= maxDist
      && d.off >= minOff && (!inStock || d.stock)``
    """
    cat = c.get("cat", "All")
    if cat not in (None, "All") and deal.get("cat") != cat:
        return False

    max_dist = c.get("maxDist")
    if max_dist is not None:
        d = dist_for(deal, loc)
        if d is not None and d > max_dist:
            return False

    min_off = c.get("minOff")
    if min_off is not None and (deal.get("off") or 0) < min_off:
        return False

    if c.get("inStock") and not deal.get("stock", True):
        return False

    return True


def _active_alert_presets(conn) -> list[dict]:
    """Saved presets that are both ``active`` and have ``telegram_alerts_on``."""
    try:
        return [
            f
            for f in db.list_filters(conn)
            if f.get("active") and f.get("telegram_alerts_on")
        ]
    except Exception as exc:  # noqa: BLE001
        log.warning("list_filters failed: %s", exc)
        return []


def _last_alerted_price(conn, deal_id) -> float | None:
    """Most recent ``alerted_price`` recorded for a deal id (None if never)."""
    row = conn.execute(
        "SELECT alerted_price FROM notifications_sent WHERE deal_id = ? "
        "ORDER BY id DESC LIMIT 1;",
        (str(deal_id),),
    ).fetchone()
    if row is None:
        return None
    val = row["alerted_price"] if isinstance(row, dict) or hasattr(row, "keys") else row[0]
    try:
        return float(val) if val is not None else None
    except (TypeError, ValueError):
        return None


# ---------------------------------------------------------------------------
# Jobs
# ---------------------------------------------------------------------------
def job_scrape() -> None:
    """Refresh live deals (persisting to SQLite). Logs counts; never crashes."""
    try:
        deals = scrape_all(write_db=True)
        log.info("job_scrape: scraped %d deals", len(deals or []))
    except Exception as exc:  # noqa: BLE001
        log.exception("job_scrape failed: %s", exc)


def job_daily_alert() -> None:
    """09:00 batched alert of today's fire deals matching active presets.

    Dedup: a deal already in ``notifications_sent`` is skipped unless its current
    ``sale`` is strictly lower than the last ``alerted_price`` (re-alert only on a
    deeper drop). Survivors go out as ONE ranked message, then each is recorded.
    """
    try:
        deals = _blended_deals()
        fire = [d for d in deals if d.get("fire")]
        if not fire:
            log.info("job_daily_alert: no fire deals today")
            return

        conn = _conn()
        try:
            presets = _active_alert_presets(conn)
            if not presets:
                # Alerts are gated on saved filters (CLAUDE.md §6): with no active
                # ``telegram_alerts_on`` preset there is nothing to match, so we
                # stay silent rather than broadcasting every fire deal.
                log.info("job_daily_alert: no active alert presets; nothing to alert")
                return
            fire = [
                d
                for d in fire
                if any(_deal_matches_filter(d, p.get("c") or {}) for p in presets)
            ]
            if not fire:
                log.info("job_daily_alert: no fire deals match active presets")
                return

            survivors: list[dict] = []
            for d in fire:
                sale = d.get("sale")
                last = _last_alerted_price(conn, d.get("id"))
                if last is None:
                    survivors.append(d)
                elif sale is not None and sale < last:
                    survivors.append(d)  # deeper drop -> re-alert

            if not survivors:
                log.info("job_daily_alert: all fire deals already alerted (no deeper drops)")
                return

            survivors.sort(key=lambda x: x.get("score", 0), reverse=True)

            html = render_ranked_html(
                survivors,
                loc=_ALERT_LOC,
                header="🔔 Daily alert · today's fire deals",
            )
            sent = notify.send_message(html)
            log.info("job_daily_alert: %d deals, send=%s", len(survivors), sent)

            now = _now_iso()
            with conn:
                for d in survivors:
                    conn.execute(
                        "INSERT INTO notifications_sent (deal_id, filter_id, sent_at, alerted_price) "
                        "VALUES (?, ?, ?, ?);",
                        (str(d.get("id")), None, now, d.get("sale")),
                    )
        finally:
            conn.close()
    except Exception as exc:  # noqa: BLE001
        log.exception("job_daily_alert failed: %s", exc)


def job_recurring_reminders() -> None:
    """18:30 heads-up for deals recurring TOMORROW (Phoenix weekday). Silent if none."""
    try:
        tomorrow_dow = (_now() + timedelta(days=1)).strftime("%a")  # Mon/Tue/.../Sun
        deals = _blended_deals()
        upcoming = [
            d
            for d in deals
            if d.get("recurring") and d.get("dow") == tomorrow_dow
        ]
        if not upcoming:
            log.info("job_recurring_reminders: nothing recurring for %s", tomorrow_dow)
            return

        upcoming.sort(key=lambda x: x.get("score", 0), reverse=True)
        html = render_ranked_html(
            upcoming,
            loc=_ALERT_LOC,
            header=f"⏰ Tomorrow's recurring deals ({tomorrow_dow}):",
        )
        sent = notify.send_message(html)
        log.info("job_recurring_reminders: %d deals, send=%s", len(upcoming), sent)
    except Exception as exc:  # noqa: BLE001
        log.exception("job_recurring_reminders failed: %s", exc)


def job_weekly_digest() -> None:
    """Sunday 18:00 digest: top ~6 by score + upcoming recurring footer."""
    try:
        deals = _blended_deals()
        if not deals:
            log.info("job_weekly_digest: no deals to digest")
            return

        top = sorted(deals, key=lambda x: x.get("score", 0), reverse=True)[:6]
        html = render_ranked_html(top, loc=_ALERT_LOC, header="📊 Weekly digest")

        recurring = [d for d in deals if d.get("recurring")]
        if recurring:
            recurring.sort(key=lambda x: (x.get("dow") or "", -x.get("score", 0)))
            bits = []
            seen = set()
            for d in recurring:
                key = (d.get("product"), d.get("shop"), d.get("dow"))
                if key in seen:
                    continue
                seen.add(key)
                bits.append(f"• {d.get('dow', '?')}: {d.get('product', '?')} @ {d.get('shop', '?')}")
            html += "\n\n<b>Upcoming recurring deals:</b>\n" + "\n".join(bits)

        sent = notify.send_message(html)

        now = _now_iso()
        period_start = (_now() - timedelta(days=_now().weekday())).date().isoformat()
        conn = _conn()
        try:
            with conn:
                conn.execute(
                    "INSERT INTO digests (period_start, sent_at) VALUES (?, ?);",
                    (period_start, now),
                )
        finally:
            conn.close()

        log.info("job_weekly_digest: %d top deals, send=%s", len(top), sent)
    except Exception as exc:  # noqa: BLE001
        log.exception("job_weekly_digest failed: %s", exc)


# ---------------------------------------------------------------------------
# Scheduler wiring
# ---------------------------------------------------------------------------
_JOBS = {
    "job_scrape": job_scrape,
    "job_daily_alert": job_daily_alert,
    "job_recurring_reminders": job_recurring_reminders,
    "job_weekly_digest": job_weekly_digest,
}

_scheduler: AsyncIOScheduler | None = None


def build_scheduler() -> AsyncIOScheduler:
    """Create a scheduler with all four jobs registered (NOT started)."""
    sched = AsyncIOScheduler(timezone=_TZ)

    # ~3-6h cadence (4h base ± up to 1h jitter, polite per PRD FR2). max_instances
    # + coalesce guarantee a slow scrape can never overlap or pile up duplicate
    # runs. An initial run is kicked off shortly after start so price history
    # starts accumulating immediately (fire only becomes real once it has).
    sched.add_job(
        job_scrape,
        trigger=IntervalTrigger(hours=4, jitter=3600, timezone=_TZ),
        id="job_scrape",
        name="Scrape live deals (~3-5h, jittered)",
        next_run_time=_now() + timedelta(seconds=30),
        replace_existing=True,
        max_instances=1,
        coalesce=True,
    )
    sched.add_job(
        job_daily_alert,
        trigger=CronTrigger(hour=9, minute=0, timezone=_TZ),
        id="job_daily_alert",
        name="Daily fire-deal alert (09:00)",
        replace_existing=True,
        max_instances=1,
        coalesce=True,
    )
    sched.add_job(
        job_recurring_reminders,
        trigger=CronTrigger(hour=18, minute=30, timezone=_TZ),
        id="job_recurring_reminders",
        name="Recurring reminders (18:30)",
        replace_existing=True,
        max_instances=1,
        coalesce=True,
    )
    sched.add_job(
        job_weekly_digest,
        trigger=CronTrigger(day_of_week="sun", hour=18, minute=0, timezone=_TZ),
        id="job_weekly_digest",
        name="Weekly digest (Sun 18:00)",
        replace_existing=True,
        max_instances=1,
        coalesce=True,
    )
    return sched


def start_scheduler() -> AsyncIOScheduler | None:
    """Build + start the module-level scheduler (idempotent). Never raises."""
    global _scheduler
    try:
        if _scheduler is not None and _scheduler.running:
            return _scheduler
        _scheduler = build_scheduler()
        _scheduler.start()
        log.info(
            "scheduler started (tz=%s) jobs=%s",
            TIMEZONE,
            [j.id for j in _scheduler.get_jobs()],
        )
        return _scheduler
    except Exception as exc:  # noqa: BLE001 - app startup must not fail on this
        log.exception("start_scheduler failed: %s", exc)
        return None


def shutdown_scheduler() -> None:
    """Stop the module-level scheduler if running. Never raises."""
    global _scheduler
    try:
        if _scheduler is not None and _scheduler.running:
            _scheduler.shutdown(wait=False)
            log.info("scheduler shut down")
    except Exception as exc:  # noqa: BLE001
        log.warning("shutdown_scheduler error: %s", exc)
    finally:
        _scheduler = None


def run_job_now(name: str) -> None:
    """Invoke a job function by name synchronously (manual testing helper)."""
    fn = _JOBS.get(name)
    if fn is None:
        raise KeyError(f"unknown job: {name!r} (choices: {sorted(_JOBS)})")
    fn()
