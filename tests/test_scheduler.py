"""Scheduler / proactive-alert tests — no network, no Telegram, fake deal source.

Covers the two pieces of the alert pipeline that matter:

* ``job_daily_alert`` only alerts **fire** deals that match an **active**
  ``telegram_alerts_on`` saved filter, and **dedups** — a second run with the
  same prices sends nothing, while a *deeper* price re-alerts.
* ``job_weekly_digest`` builds and sends a non-empty ranked message.

Plus a unit test for ``run.acquire_single_instance_lock`` (the single-instance
guard) without ever starting the supervisor.

Everything is monkeypatched: the deal source (``_blended_deals``), the Telegram
sender (``notify.send_message``), and the SQLite path (a temp DB).
"""

from __future__ import annotations

import importlib

import pytest

from app import db
from app import notify
from app import scheduler


# --------------------------------------------------------------------------- #
# Fixtures
# --------------------------------------------------------------------------- #
@pytest.fixture()
def temp_db(tmp_path, monkeypatch):
    """Point the DAL at a fresh migrated SQLite file for the duration of a test."""
    path = tmp_path / "topshelf_test.db"
    monkeypatch.setattr(db, "DB_PATH", path)
    db.run_migrations()
    return path


@pytest.fixture()
def captured_sends(monkeypatch):
    """Capture every ``notify.send_message`` call instead of hitting Telegram."""
    calls: list[str] = []

    def _fake_send_message(html: str) -> bool:
        calls.append(html)
        return True

    def _fake_send_photo(img_url: str, caption_html: str) -> bool:
        return True

    monkeypatch.setattr(notify, "send_message", _fake_send_message)
    monkeypatch.setattr(notify, "send_photo", _fake_send_photo)
    return calls


def _deal(**over) -> dict:
    """A fully-formed augmented deal with sane defaults for the matcher/renderer."""
    base = {
        "id": "x1",
        "cat": "Flower",
        "product": "Test Product",
        "brand": "Test Brand",
        "shop": "Test Shop",
        "area": "Scottsdale",
        "dist": 2.0,
        "sale": 30,
        "orig": 50,
        "off": 40,
        "unit": 10.0,
        "unitLabel": "/g",
        "score": 90,
        "stock": True,
        "fire": True,
        "fireReason": "Lowest in 14 days",
        "recurring": False,
    }
    base.update(over)
    return base


def _set_deals(monkeypatch, deals: list[dict]) -> None:
    monkeypatch.setattr(scheduler, "_blended_deals", lambda: list(deals))


def _make_active_flower_filter() -> None:
    conn = db.get_conn()
    try:
        db.create_filter(
            conn,
            name="Flower fire",
            criteria={"cat": "Flower", "minOff": 20, "maxDist": 10, "inStock": True},
            active=True,
            telegram_alerts_on=True,
        )
    finally:
        conn.close()


# --------------------------------------------------------------------------- #
# job_daily_alert: matching + dedup
# --------------------------------------------------------------------------- #
def test_daily_alert_only_matching_fire_deals(temp_db, captured_sends, monkeypatch):
    _make_active_flower_filter()

    match = _deal(id="match", cat="Flower", product="Atomic Apple", off=40, sale=30)
    wrong_cat = _deal(id="wrongcat", cat="Edibles", product="Gummy Bears")  # filter is Flower-only
    not_fire = _deal(id="cold", cat="Flower", product="Boring Bud", fire=False)
    _set_deals(monkeypatch, [match, wrong_cat, not_fire])

    scheduler.job_daily_alert()

    assert len(captured_sends) == 1
    body = captured_sends[0]
    assert "Atomic Apple" in body          # the matching fire deal is alerted
    assert "Gummy Bears" not in body       # wrong category filtered out
    assert "Boring Bud" not in body        # non-fire filtered out


def test_daily_alert_dedups_second_run_sends_nothing(temp_db, captured_sends, monkeypatch):
    _make_active_flower_filter()
    deal = _deal(id="match", cat="Flower", product="Atomic Apple", sale=30)
    _set_deals(monkeypatch, [deal])

    scheduler.job_daily_alert()
    assert len(captured_sends) == 1  # first run alerts

    scheduler.job_daily_alert()
    assert len(captured_sends) == 1  # same price -> deduped, NO second alert


def test_daily_alert_reissues_only_on_deeper_drop(temp_db, captured_sends, monkeypatch):
    _make_active_flower_filter()
    deal = _deal(id="match", cat="Flower", product="Atomic Apple", sale=30)
    _set_deals(monkeypatch, [deal])

    scheduler.job_daily_alert()
    assert len(captured_sends) == 1

    # Same price again: still deduped.
    scheduler.job_daily_alert()
    assert len(captured_sends) == 1

    # A strictly deeper drop re-alerts.
    deeper = _deal(id="match", cat="Flower", product="Atomic Apple", sale=22)
    _set_deals(monkeypatch, [deeper])
    scheduler.job_daily_alert()
    assert len(captured_sends) == 2


def test_daily_alert_respects_inactive_filter(temp_db, captured_sends, monkeypatch):
    """An inactive (or alerts-off) filter must not authorize alerts."""
    conn = db.get_conn()
    try:
        db.create_filter(
            conn,
            name="Flower fire (off)",
            criteria={"cat": "Flower", "minOff": 20},
            active=False,            # inactive -> not an alert preset
            telegram_alerts_on=True,
        )
    finally:
        conn.close()

    _set_deals(monkeypatch, [_deal(id="match", cat="Flower", product="Atomic Apple")])
    scheduler.job_daily_alert()
    assert len(captured_sends) == 0  # no active preset -> nothing matches


# --------------------------------------------------------------------------- #
# job_weekly_digest
# --------------------------------------------------------------------------- #
def test_weekly_digest_builds_and_sends_message(temp_db, captured_sends, monkeypatch):
    deals = [
        _deal(id="a", product="Top One", score=98),
        _deal(id="b", product="Top Two", score=80, recurring=True, dow="Fri"),
    ]
    _set_deals(monkeypatch, deals)

    scheduler.job_weekly_digest()

    assert len(captured_sends) == 1
    body = captured_sends[0]
    assert "Weekly digest" in body
    assert "Top One" in body
    # The recurring footer is appended when recurring deals are present.
    assert "Upcoming recurring deals" in body


# --------------------------------------------------------------------------- #
# Single-instance lock (run.py) — verified in-process, supervisor never starts
# --------------------------------------------------------------------------- #
def test_single_instance_lock_blocks_second_acquire():
    run = importlib.import_module("run")
    port = 8799  # a fixed, unlikely-in-use port for the test

    first = run.acquire_single_instance_lock(port)
    try:
        assert first is not None, "first acquire should obtain the lock"
        second = run.acquire_single_instance_lock(port)
        assert second is None, "second acquire on the same port must fail"
    finally:
        if first is not None:
            first.close()
        # Reset the module global so we don't leak the held socket across tests.
        run._lock_socket = None
