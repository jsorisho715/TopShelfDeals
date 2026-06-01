"""Scrape orchestrator.

Walks the Dutchie dispensaries in ``app/seed/dispensaries.json``, pulls each
menu via :class:`app.adapters.dutchie.DutchieAdapter`, normalizes rows into
canonical deals (``app.pipeline.normalize.normalize_item``), dedups, optionally
persists to SQLite (``products`` / ``price_observations`` / ``deals``), and
returns the fully-augmented deals (``app.pipeline.serialize.augment_deals``) for
the API/bot to blend with the seed.

Politeness (PRD FR2): stores are hit sequentially with a jittered delay between
them. Delay bounds and the browser User-Agent come from the environment
(``SCRAPE_MIN_DELAY_SEC`` / ``SCRAPE_MAX_DELAY_SEC`` / ``SCRAPE_USER_AGENT``),
loaded via ``python-dotenv``. Defaults: 2–5 s.
"""

from __future__ import annotations

import hashlib
import json
import os
import random
import time
from datetime import datetime
from pathlib import Path
from typing import Any, Optional

try:
    from dotenv import load_dotenv

    load_dotenv()
except Exception:  # pragma: no cover - dotenv is a soft dependency here
    pass

try:
    from zoneinfo import ZoneInfo

    _PHX = ZoneInfo("America/Phoenix")
except Exception:  # pragma: no cover
    _PHX = None  # type: ignore[assignment]

from . import db
from .adapters.dutchie import DutchieAdapter
from .pipeline import geocode, pricememory, specials
from .pipeline import score as score_mod
from .pipeline.dedup import build_store_groups, dedup
from .pipeline.normalize import normalize_item
from .pipeline.pricememory import FIRE_PCT_THRESHOLD
from .pipeline.serialize import augment_deals

# A deal needs at least this many distinct daily observations before fire/price-
# memory is trusted; until then it is provisional (fire suppressed) — UNLESS it
# carries authoritative promo evidence (a labeled special), which is trusted
# immediately. Lowered 5 -> 2 so history-based fire turns on after a couple of
# scheduled scrapes rather than nearly a week.
_MIN_HISTORY_DAYS = 2

_SEED_DIR = Path(__file__).resolve().parent / "seed"
_DISPENSARIES_PATH = _SEED_DIR / "dispensaries.json"

_DATA_DIR = Path(__file__).resolve().parent.parent / "data"
_LIVE_CACHE_PATH = _DATA_DIR / "live_deals.json"

# Reliability: a store that transiently fails/times out must NOT silently drop to
# 0. We keep each store's last-good result and bounded-retry stores that failed.
_STORE_CACHE_PATH = _DATA_DIR / "store_deals.json"
_SCRAPE_REPORT_PATH = _DATA_DIR / "scrape_report.json"
_STORE_RETRIES = 2          # extra attempts for a store that produced deals before
_RETRY_DELAY_SEC = 3.0
# Playwright-backed platforms transiently time out / hit Cloudflare under a long
# sequential run -> always give them the retries (not just when they had data).
_BROWSER_PLATFORMS = {"Trulieve", "Dutchie", "Jane", "Weedmaps"}

_DEFAULT_MIN_DELAY = 2.0
_DEFAULT_MAX_DELAY = 5.0


# ---------------------------------------------------------------------------
# Config / seed helpers
# ---------------------------------------------------------------------------
def _delay_bounds() -> tuple[float, float]:
    def _f(key: str, default: float) -> float:
        try:
            return float(os.getenv(key, ""))
        except (TypeError, ValueError):
            return default

    lo = _f("SCRAPE_MIN_DELAY_SEC", _DEFAULT_MIN_DELAY)
    hi = _f("SCRAPE_MAX_DELAY_SEC", _DEFAULT_MAX_DELAY)
    if hi < lo:
        hi = lo
    return lo, hi


def _load_dispensaries() -> list[dict]:
    with open(_DISPENSARIES_PATH, "r", encoding="utf-8") as fh:
        return json.load(fh).get("dispensaries", [])


def _active_dispensaries() -> list[dict]:
    return [d for d in _load_dispensaries() if d.get("active", True)]


def _adapter_registry() -> dict:
    """Platform -> adapter instance. Leafly is added lazily if available."""
    registry: dict = {"Dutchie": DutchieAdapter()}
    try:
        from .adapters.leafly import LeaflyAdapter

        registry["Leafly"] = LeaflyAdapter()
    except Exception:
        pass
    try:
        from .adapters.weedmaps import WeedmapsAdapter

        registry["Weedmaps"] = WeedmapsAdapter()
    except Exception:
        pass
    try:
        from .adapters.jane import JaneAdapter

        registry["Jane"] = JaneAdapter()
    except Exception:
        pass
    try:
        from .adapters.trulieve import TrulieveAdapter

        registry["Trulieve"] = TrulieveAdapter()
    except Exception:
        pass
    try:
        from .adapters.proprietary import ProprietaryAdapter

        # Shared white-label JointCommerce ("joint-ecommerce") platform that powers
        # Sol Flower (livewithsol.com) and YiLo (yilo.com), selected by business_id.
        registry["JointCommerce"] = ProprietaryAdapter()
    except Exception:
        pass
    try:
        from .adapters.cookies import CookiesAdapter

        registry["Cookies.co"] = CookiesAdapter()
    except Exception:
        pass
    try:
        from .adapters.trumed import TruMedAdapter

        # TruMed (trumedaz.com) is a Dutchie embedded storefront.
        registry["TruMed"] = TruMedAdapter()
    except Exception:
        pass
    return registry


def _shop_to_addr() -> dict:
    """Map dispensary name -> street address (for geocoding + distances)."""
    return {d.get("name"): d.get("addr", "") for d in _load_dispensaries() if d.get("name")}


def warm_geocode_cache() -> int:
    """Pre-geocode every active store address (+ all anchors) into the on-disk
    cache so distance/radius math is complete and fast.

    Without this, only the shops that produced deals on a given run get geocoded
    (and the 1 req/sec Nominatim limit can leave some without ``distByAnchor``).
    Warming up front guarantees every active store has coordinates the first time
    it surfaces. Cached addresses never re-hit the network. Returns the count of
    addresses with known coordinates.
    """
    try:
        geocode.anchor_coords()  # warm the 5 anchors once
    except Exception:
        pass
    ok = 0
    for d in _active_dispensaries():
        addr = d.get("addr")
        if not addr:
            continue
        try:
            if geocode.geocode(addr) is not None:
                ok += 1
        except Exception:
            pass
    return ok


def _apply_geocoded_distances(deals: list[dict]) -> None:
    """Set each deal's geocoded miles to every anchor (``distByAnchor``) and the
    nearest-anchor ``dist``, so the location dropdown radius is accurate."""
    shop_addr = _shop_to_addr()
    cache: dict[str, dict] = {}
    for d in deals:
        shop = d.get("shop")
        if shop not in cache:
            addr = shop_addr.get(shop)
            cache[shop] = geocode.anchor_distances(addr) if addr else {}
        ad = cache[shop]
        if ad:
            d["distByAnchor"] = ad
            d["dist"] = round(min(ad.values()), 1)


def _now_iso() -> str:
    now = datetime.now(_PHX) if _PHX is not None else datetime.now()
    return now.isoformat(timespec="seconds")


def _scraped_id(shop: str, deal: dict) -> str:
    """Stable synthetic id for a scraped deal.

    Seed deals ship an ``id`` (e.g. ``"fl1"``) that downstream augmentation relies
    on (``pricememory.synth_history`` seeds its deterministic trail off the id's
    char codes). Scraped Dutchie items have no such id, so we derive a stable one
    from shop + product + size; the same product yields the same id (and thus a
    stable price-history trail) across scrapes.
    """
    key = f"{shop}|{deal.get('product')}|{deal.get('size')}".lower()
    digest = hashlib.sha1(key.encode("utf-8")).hexdigest()[:10]
    return f"sc-{digest}"


def _fallback_dist(store_ref: dict) -> Optional[float]:
    """Closest home-location distance for a store (used when an item has none)."""
    dist = store_ref.get("dist")
    if isinstance(dist, dict) and dist:
        try:
            return min(float(v) for v in dist.values())
        except (TypeError, ValueError):
            return None
    return None


# ---------------------------------------------------------------------------
# Augment prep — fill the fields tsAugment/score expect on a scraped deal
# ---------------------------------------------------------------------------
def _prepare_for_augment(deals: list[dict], store_ref: dict) -> list[dict]:
    """Ensure each scraped deal carries the keys the scorer/serializer require.

    ``score.score_components`` reads ``unit``/``off``/``dist`` and ``scaled_factors``
    reads ``score``/``seen``. Seed deals ship these; scraped deals don't, so we
    fill sensible values here and compute a real score. Deals without a usable
    ``unit`` (unparseable size) can't be ranked $/unit and are dropped.
    """
    fallback_dist = _fallback_dist(store_ref)
    prepared: list[dict] = []
    for d in deals:
        if d.get("unit") is None:
            continue
        d = dict(d)
        if d.get("dist") is None:
            d["dist"] = fallback_dist if fallback_dist is not None else 5.0
        d.setdefault("seen", "just now")
        d.setdefault("area", store_ref.get("area") or "Scottsdale")
        if not d.get("id"):
            d["id"] = _scraped_id(store_ref.get("name") or d.get("shop") or "", d)
        prepared.append(d)

    if not prepared:
        return []

    medians = score_mod.area_medians(prepared)
    for d in prepared:
        s, _factors = score_mod.compute_score(d, medians)
        d["score"] = s
    return prepared


# ---------------------------------------------------------------------------
# DB persistence
# ---------------------------------------------------------------------------
def _ensure_dispensary(conn, shop: str):
    """Get-or-create a dispensary row by name; returns its id (or None)."""
    if not shop:
        return None
    row = db.get_dispensary_by_name(conn, shop)
    if row:
        return row["id"]
    try:
        return db.insert_dispensary(conn, name=shop, active=1)
    except Exception:
        row = db.get_dispensary_by_name(conn, shop)
        return row["id"] if row else None


def _get_or_create_product(conn, dispensary_id, d: dict) -> int:
    """Reuse a product row across scrapes (stable identity) so observations
    accumulate into real price history. Keyed by (dispensary, name, unitLabel)."""
    name = d.get("product") or ""
    unit_label = d.get("unitLabel")
    row = conn.execute(
        "SELECT id FROM products WHERE dispensary_id IS ? AND name = ? AND unit_label IS ? ORDER BY id LIMIT 1;",
        (dispensary_id, name, unit_label),
    ).fetchone()
    if row:
        return row["id"]
    return db.insert_product(
        conn,
        dispensary_id=dispensary_id,
        name=name,
        category=d.get("cat"),
        strain_type=d.get("type"),
        lineage=d.get("lineage"),
        thc_pct=d.get("thc"),
        cbd_pct=d.get("cbd"),
        unit=d.get("unit"),
        unit_label=unit_label,
        description=d.get("desc"),
        effects_json=json.dumps(d.get("effects") or []),
        image_url=d.get("img"),
    )


def _write_deals(deals: list[dict]) -> None:
    """Persist deals and compute REAL price-memory from accumulated observations.

    Mutates each deal in place with real hist/fire/priorAvg/etc. (so the cache and
    return value reflect real history, not the synthetic trail). Fire stays
    suppressed/provisional until a product has >= _MIN_HISTORY_DAYS distinct days.
    """
    db.run_migrations()
    conn = db.get_conn()
    observed_at = _now_iso()
    today = observed_at[:10]
    try:
        with conn:
            for d in deals:
                # Retained/stale deals were NOT re-observed this run -> don't record
                # a price observation for them (would fabricate history).
                if d.get("stale"):
                    continue
                dispensary_id = _ensure_dispensary(conn, d.get("shop", ""))
                product_id = _get_or_create_product(conn, dispensary_id, d)

                orig = d.get("orig")
                sale = d.get("sale")
                is_sale = 1 if (sale is not None and orig is not None and sale < orig) else 0

                # Source platform: prefer the single ``platform`` tag, else the
                # first of the ``platforms`` list that dedup unions across sources,
                # else fall back to Dutchie. (Fixes the old hard-coded default that
                # mislabeled every row "Dutchie".)
                source_platform = d.get("platform")
                if not source_platform:
                    plats = d.get("platforms")
                    source_platform = plats[0] if isinstance(plats, list) and plats else "Dutchie"

                # Observations BEFORE recording today (the trailing window).
                prior_obs = db.list_price_observations(conn, product_id)
                db.insert_price_observation(
                    conn,
                    product_id=product_id,
                    observed_at=observed_at,
                    price=orig,
                    sale_price=sale,
                    is_sale=is_sale,
                    source_platform=source_platform,
                    in_stock=1 if d.get("stock", True) else 0,
                )

                sale_f = float(sale) if sale is not None else 0.0
                mem = pricememory.price_memory_from_observations(prior_obs, sale_f)

                # Real sparkline from observed effective prices (oldest -> today).
                all_obs = prior_obs + [{"price": orig, "sale_price": sale, "is_sale": is_sale}]
                hist = [int(round(pricememory._effective_price(o))) for o in all_obs]

                distinct_days = len({(o.get("observed_at") or "")[:10] for o in prior_obs} | {today})
                has_promo = specials.has_promo_evidence(d)
                # Authoritative promo evidence is trusted immediately; only deals
                # WITHOUT it are provisional while history accrues.
                provisional = (distinct_days < _MIN_HISTORY_DAYS) and not has_promo
                off = int(d.get("off") or 0)

                if not specials.fire_eligible_from_promo(d):
                    # First-time-patient / industry-only: never fire (PRD FR8).
                    mem["fire"] = False
                    mem["fireReason"] = (
                        "Heads-up: first-time/industry-only special \u2014 not counted as fire"
                    )
                elif has_promo and not mem["isTrap"] and off >= FIRE_PCT_THRESHOLD:
                    # A labeled, generally-redeemable special with a deep discount
                    # earns fire on promo evidence alone (no history wait).
                    title = d.get("promo_title") or "Special"
                    dow = d.get("dow")
                    mem["fire"] = True
                    mem["fireReason"] = (
                        f"{title} \u00b7 {off}% off" + (f" \u00b7 every {dow}" if dow else "")
                    )
                elif provisional:
                    mem["fire"] = False
                    mem["fireReason"] = (
                        f"Building price history \u2014 {distinct_days}/{_MIN_HISTORY_DAYS} days tracked"
                    )

                # Surface the labeled special in the price-memory line even when it
                # doesn't earn fire (and isn't a trap), so the detail panel/bot show
                # the real promo + its weekday cadence.
                if (
                    has_promo
                    and not mem["fire"]
                    and not mem["isTrap"]
                    and specials.fire_eligible_from_promo(d)
                ):
                    title = d.get("promo_title") or "Special"
                    dow = d.get("dow")
                    mem["fireReason"] = title + (f" \u00b7 every {dow}" if dow else "")

                # Reflect real memory back onto the deal (cache + API + bot use this).
                d["hist"] = hist
                d["priorAvg"] = mem["priorAvg"]
                d["priorMin"] = mem["priorMin"]
                d["isLowest"] = mem["isLowest"]
                d["pctBelowAvg"] = mem["pctBelowAvg"]
                d["fire"] = mem["fire"]
                d["isTrap"] = mem["isTrap"]
                d["fireReason"] = mem["fireReason"]
                d["hot"] = mem["fire"]
                d["provisional"] = provisional

                db.insert_deal(
                    conn,
                    product_id=product_id,
                    dispensary_id=dispensary_id,
                    original_price=orig,
                    sale_price=sale,
                    discount_pct_validated=d.get("off"),
                    unit_price=d.get("unit"),
                    score=d.get("score"),
                    score_factors_json=json.dumps(d.get("factors") or []),
                    prior_avg=mem["priorAvg"],
                    prior_min=mem["priorMin"],
                    is_lowest=1 if mem["isLowest"] else 0,
                    pct_below_avg=mem["pctBelowAvg"],
                    is_fire=1 if mem["fire"] else 0,
                    is_markup_trap=1 if mem["isTrap"] else 0,
                    first_seen=observed_at,
                    last_seen=observed_at,
                    is_recurring=1 if d.get("recurring") else 0,
                    recurrence_dow=d.get("dow"),
                    in_stock=1 if d.get("stock", True) else 0,
                )
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# Reliability helpers: per-store keep-last-good cache + bounded retries
# ---------------------------------------------------------------------------
def _load_store_cache() -> dict:
    try:
        with open(_STORE_CACHE_PATH, "r", encoding="utf-8") as fh:
            return json.load(fh)
    except (FileNotFoundError, ValueError, OSError):
        return {}


def _save_store_cache(cache: dict) -> None:
    try:
        _DATA_DIR.mkdir(parents=True, exist_ok=True)
        with open(_STORE_CACHE_PATH, "w", encoding="utf-8") as fh:
            json.dump(cache, fh)
    except Exception:
        pass


def _save_scrape_report(rows: list[dict]) -> None:
    try:
        _DATA_DIR.mkdir(parents=True, exist_ok=True)
        with open(_SCRAPE_REPORT_PATH, "w", encoding="utf-8") as fh:
            json.dump({"generatedAt": _now_iso(), "stores": rows}, fh, indent=2)
    except Exception:
        pass


def load_scrape_report() -> dict:
    """Last per-store scrape report (status fresh / retained-stale / empty)."""
    try:
        with open(_SCRAPE_REPORT_PATH, "r", encoding="utf-8") as fh:
            return json.load(fh)
    except (FileNotFoundError, ValueError, OSError):
        return {"generatedAt": None, "stores": []}


def _fetch_store_items(adapter, store: dict, expect_data: bool) -> list:
    """Fetch a store's menu with bounded retries.

    Retries only when we expected data (the store produced deals on a prior
    scrape), so genuinely-empty stores don't waste time. Targets transient
    timeouts / Cloudflare hiccups on productive stores (the Playwright-backed
    Trulieve / Dutchie path that returned 0 under a long sequential run).
    """
    attempts = 1 + (_STORE_RETRIES if expect_data else 0)
    for attempt in range(attempts):
        try:
            items = adapter.fetch(store) or []
        except Exception:
            items = []
        if items:
            return items
        if attempt < attempts - 1:
            time.sleep(_RETRY_DELAY_SEC * (attempt + 1))
    return []


# ---------------------------------------------------------------------------
# Public entry points
# ---------------------------------------------------------------------------
def scrape_all(write_db: bool = True) -> list[dict]:
    """Scrape every active dispensary (any platform) and return augmented deals.

    Resilient by design: each store is fetched with bounded retries, and a store
    that transiently fails / times out KEEPS its last-good result (flagged
    ``stale``) instead of silently dropping to 0. A per-store report is written to
    ``data/scrape_report.json`` for full visibility.
    """
    registry = _adapter_registry()
    lo, hi = _delay_bounds()
    stores = [s for s in _active_dispensaries() if s.get("platform") in registry]

    # Pre-warm geocoding for every active store so distByAnchor is complete even
    # for stores that return 0 this run (cached lookups never re-hit the network).
    try:
        warm_geocode_cache()
    except Exception:
        pass

    store_cache = _load_store_cache()
    report: list[dict] = []
    raw_deals: list[dict] = []

    for i, store in enumerate(stores):
        if i > 0:
            time.sleep(random.uniform(lo, hi))

        shop = store.get("name") or ""
        platform = store.get("platform")
        adapter = registry.get(platform)
        if adapter is None:
            report.append({"shop": shop, "platform": platform, "raw": 0, "kept": 0, "status": "no-adapter"})
            continue

        had_before = bool((store_cache.get(shop) or {}).get("deals"))
        expect_data = had_before or (platform in _BROWSER_PLATFORMS)
        items = _fetch_store_items(adapter, store, expect_data=expect_data)

        normalized: list[dict] = []
        for item in items:
            deal = normalize_item(item, shop)
            if deal is None:
                continue
            # Tag the source platform so DB price-observations record it accurately.
            if platform:
                deal["platform"] = platform
            # Fold any captured special into recurring/dow + headline %off.
            specials.apply_promo(deal)
            # Free online image fallback only when the menu gave us no photo.
            if not deal.get("img"):
                try:
                    from .pipeline.imagesearch import find_product_image

                    deal["img"] = find_product_image(deal.get("brand"), deal.get("product"), deal.get("cat"))
                except Exception:
                    pass
            normalized.append(deal)

        prepared = _prepare_for_augment(normalized, store)
        if prepared:
            for d in prepared:
                d["_fresh"] = True
            store_cache[shop] = {"deals": prepared, "at": _now_iso()}
            raw_deals.extend(prepared)
            report.append({"shop": shop, "platform": platform, "raw": len(items), "kept": len(prepared), "status": "fresh"})
        else:
            prev = store_cache.get(shop) or {}
            retained = prev.get("deals") or []
            if retained:
                # Keep last-good so the store never silently disappears.
                raw_deals.extend(dict(d, _fresh=False) for d in retained)
                report.append({"shop": shop, "platform": platform, "raw": len(items), "kept": len(retained), "status": "retained-stale", "since": prev.get("at")})
            else:
                report.append({"shop": shop, "platform": platform, "raw": len(items), "kept": 0, "status": "empty"})

    _save_store_cache(store_cache)
    _save_scrape_report(report)

    # Cross-platform store merge: cluster shops by geocoded coordinates so the
    # same physical store listed on multiple platforms collapses to one.
    shop_addr = _shop_to_addr()
    shop_coords: dict[str, tuple] = {}
    for shop in {d.get("shop") for d in raw_deals if d.get("shop")}:
        c = geocode.geocode(shop_addr.get(shop, ""))
        if c:
            shop_coords[shop] = c
    store_groups = build_store_groups(shop_coords) if shop_coords else {}

    # Robustness: also merge shops that share an IDENTICAL street address even if
    # one failed to geocode (e.g. the Dutchie + Leafly "Mint Scottsdale" pair at
    # 8729 E Manzanita Dr). Address-keyed groups deterministically collapse them.
    addr_groups: dict[str, list[str]] = {}
    for shop in {d.get("shop") for d in raw_deals if d.get("shop")}:
        norm_addr = " ".join((shop_addr.get(shop, "") or "").lower().split())
        if norm_addr:
            addr_groups.setdefault(norm_addr, []).append(shop)
    store_groups = dict(store_groups or {})
    for shops in addr_groups.values():
        if len(shops) > 1:
            canonical = sorted(shops)[0]
            for shop in shops:
                store_groups.setdefault(shop, canonical)
    store_groups = store_groups or None

    deduped = dedup(raw_deals, store_groups=store_groups)
    # NOTE: we keep full-price allowlisted top-shelf items too (so every dispensary
    # shows up); the web "On sale" toggle + min-%-off slider and the bot's "on sale"
    # query narrow to genuine specials on demand (real_specials helper is available).
    if not deduped:
        return []

    augmented = augment_deals(deduped)
    # Accurate geocoded distance to every anchor (powers the dropdown radius).
    _apply_geocoded_distances(augmented)

    # Flag retained (unconfirmed this run) deals as stale and suppress their fire
    # so we never present unverified data as a hot record-low.
    for d in augmented:
        d["stale"] = not d.pop("_fresh", True)
        if d["stale"]:
            d["fire"] = False
            d["hot"] = False

    # Persist to the DB first: this records today's observations and rewrites each
    # deal's price-memory/fire from REAL accumulated history (mutates in place).
    if write_db:
        try:
            _write_deals(augmented)
        except Exception:
            # Persistence is best-effort; never fail a scrape because of the DB.
            pass

    # Then cache for fast reads by the API/bot (now reflecting real price-memory).
    # Only overwrite when we actually got deals — a transient empty scrape must
    # not wipe a good cache.
    if augmented:
        _write_live_cache(augmented)

    return augmented


def _write_live_cache(deals: list[dict]) -> None:
    try:
        _DATA_DIR.mkdir(parents=True, exist_ok=True)
        payload = {"generatedAt": _now_iso(), "deals": deals}
        with open(_LIVE_CACHE_PATH, "w", encoding="utf-8") as fh:
            json.dump(payload, fh)
    except Exception:
        pass


def load_cached_live_deals(max_age_hours: Optional[float] = None) -> list[dict]:
    """Return the augmented live deals from the on-disk cache (``[]`` if none).

    The cache is written by :func:`scrape_all`. ``max_age_hours`` optionally
    discards a stale cache. Never raises.
    """
    try:
        with open(_LIVE_CACHE_PATH, "r", encoding="utf-8") as fh:
            payload = json.load(fh)
    except (FileNotFoundError, ValueError, OSError):
        return []
    deals = payload.get("deals") or []
    if max_age_hours is not None:
        try:
            gen = datetime.fromisoformat(payload.get("generatedAt", ""))
            now = datetime.now(gen.tzinfo) if gen.tzinfo else datetime.now()
            if (now - gen).total_seconds() > max_age_hours * 3600:
                return []
        except (TypeError, ValueError):
            pass
    return deals


def get_live_deals() -> list[dict]:
    """Convenience: augmented live deals for the API/bot to blend with the seed.

    Never raises and never writes the DB — returns ``[]`` if scraping yields
    nothing (e.g. every store is Cloudflare-gated).
    """
    try:
        return scrape_all(write_db=False)
    except Exception:
        return []
