"""Tests for freshness + specials helpers."""
from datetime import datetime, timedelta, timezone

from app.pipeline.freshness import humanize_seen, is_stale, real_specials


_NOW = datetime(2026, 5, 31, 22, 0, 0, tzinfo=timezone.utc)


def _ago(**kw):
    return (_NOW - timedelta(**kw)).isoformat()


def test_humanize_just_now():
    assert humanize_seen(_ago(seconds=5), now=_NOW) == "just now"
    assert humanize_seen(_ago(seconds=59), now=_NOW) == "just now"


def test_humanize_minutes():
    assert humanize_seen(_ago(minutes=12), now=_NOW) == "12m ago"
    assert humanize_seen(_ago(minutes=1), now=_NOW) == "1m ago"


def test_humanize_hours():
    assert humanize_seen(_ago(hours=3), now=_NOW) == "3h ago"
    assert humanize_seen(_ago(hours=23), now=_NOW) == "23h ago"


def test_humanize_days():
    assert humanize_seen(_ago(days=2), now=_NOW) == "2d ago"


def test_humanize_bad_input_degrades():
    assert humanize_seen(None, now=_NOW) == "just now"
    assert humanize_seen("not-a-date", now=_NOW) == "just now"
    # Future timestamps shouldn't blow up.
    assert humanize_seen((_NOW + timedelta(hours=1)).isoformat(), now=_NOW) == "just now"


def test_humanize_naive_timestamp():
    naive_now = datetime(2026, 5, 31, 22, 0, 0)
    observed = (naive_now - timedelta(hours=2)).isoformat()
    assert humanize_seen(observed, now=naive_now) == "2h ago"


def test_is_stale_within_window():
    started = _NOW.isoformat()
    assert is_stale(_ago(hours=2), started, max_age_hours=12) is False


def test_is_stale_beyond_window():
    started = _NOW.isoformat()
    assert is_stale(_ago(hours=20), started, max_age_hours=12) is True


def test_is_stale_missing_last_seen_is_stale():
    assert is_stale(None, _NOW.isoformat()) is True
    assert is_stale("garbage", _NOW.isoformat()) is True


def test_is_stale_default_threshold_boundary():
    started = _NOW.isoformat()
    # 11h59m old at a 12h threshold -> fresh.
    assert is_stale(_ago(hours=11, minutes=59), started) is False
    # 12h01m old -> stale.
    assert is_stale(_ago(hours=12, minutes=1), started) is True


def test_real_specials_drops_non_discounts():
    deals = [
        {"product": "Real Deal", "off": 37, "orig": 60, "sale": 38},
        {"product": "No Discount", "off": 0, "orig": 50, "sale": 50},
        {"product": "Negative", "off": -5, "orig": 40, "sale": 42},
        {"product": "Sale >= Orig", "off": 10, "orig": 30, "sale": 35},
    ]
    out = real_specials(deals)
    names = [d["product"] for d in out]
    assert names == ["Real Deal"]


def test_real_specials_keeps_positive_off_without_prices():
    deals = [{"product": "Pct only", "off": 20}]
    assert real_specials(deals) == deals


def test_real_specials_empty_and_none():
    assert real_specials([]) == []
    assert real_specials(None) == []
