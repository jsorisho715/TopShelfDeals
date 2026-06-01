# PRD v2 — "TopShelf" · Scottsdale Top-Shelf Dispensary Deal Aggregator + Telegram Bot

> v2 supersedes the original PRD. It folds in every product decision made while building the
> hi-fi prototype (this repo) and re-points the architecture at that prototype as the real
> front end. Personal-use, single-user, runs on an always-on home Windows PC.

---

## 0. What changed since v1 (read this first)

| Area | v1 plan | v2 decision (shipped in prototype) |
|---|---|---|
| Front end | FastAPI + Jinja2 + htmx | **Standalone HTML/React SPA** (`TopShelf.html`, React 18 via CDN + in-browser Babel). Dark "top-shelf" luxe aesthetic, 3D depth. This is the real UI; the backend just feeds it JSON. |
| "Deal is real?" | price-history idea | **Built.** Price-memory engine flags **🔥 FIRE** (validated record-low, deep vs its own 14-day average) vs ordinary "validated drop", and catches **⚠ MARKUP** traps (marked-up-then-discounted) so they never earn fire. |
| Ranking | scoring formula | **Built** + transparent factor breakdown shown in the deal detail. |
| Telegram tables | compact monospace | **Ranked rows** (best→worst) with a **Type** column and per-row **Special** (menu) + **Route** (Google Maps directions) links. |
| Alerts | proactive on new deal | **Once-a-day batched** 9 AM alert (no per-deal spam), deduped, re-alert only on a deeper drop. |
| Location | distance from the two zips | **Location switcher** (Old Town 85251 / N. Scottsdale 85255 / Tempe / Phoenix / "use my location") — radius + distances recompute live. |
| Filters | named presets | **Saved filter presets** (default applied on load, "Save filter" to add your own, persisted). |
| Product info | name/brand/price | **Rich detail**: product image (real photo or branded placeholder), full description, strain **type** (Indica/Sativa/Hybrid), THC/CBD, lineage, effects, score breakdown, 14-day price sparkline w/ average line. |

Everything else from v1 (polite scraping, dedup, recurring-deal memory, weekly digest, `America/Phoenix`)
still stands.

---

## 1. Context & goals

A personal tool that continuously scours nearby dispensary menus for the best specials on
**top-shelf brands** within a **7-mi radius of 85251 / 85255**, ranks them best→worst, lets you
filter, and pushes alerts + answers questions over **Telegram**. Personal-use → scrapes public
consumer menu pages (Dutchie / Leafly / Weedmaps + a few proprietary sites).

**Goals:** aggregate current specials → restrict to a top-shelf allowlist above a quality floor →
rank with a transparent score → filterable dashboard → Telegram alerts + ranked-table answers →
deal memory (recurring detection, reminders, weekly digest).

**Non-goals (v1):** multi-user/public product, accounts/billing, in-app checkout, native mobile
(Telegram is the mobile surface).

---

## 2. Architecture (v2)

```
                 ┌──────────────────────────────┐
  public menus → │  Scrapers (per-platform adapters)
  (Dutchie,      │     httpx (JSON/GraphQL) → Playwright fallback
   Leafly,       └───────────────┬──────────────┘
   Weedmaps,                     │ normalized MenuItems
   proprietary)                  ▼
                 ┌──────────────────────────────┐
                 │  Pipeline: normalize · dedup ·│
                 │  price history · score · fire │
                 │  detection · recurring memory │
                 └───────┬───────────────┬───────┘
                         ▼               ▼
                   SQLite (DAL)    APScheduler (America/Phoenix)
                         │           scrape / reminders / digest
              ┌──────────┴───────────┐
              ▼                      ▼
   FastAPI JSON API          python-telegram-bot
   (serves the SPA +         (long-polling: alerts,
    /api/* endpoints)         /commands, ranked tables)
              │
              ▼
   TopShelf.html  (React SPA — this repo's prototype)
```

- **Front end** = the prototype in this repo. Today it reads static globals from
  `TopShelf/data/deals.js`. To go live it fetches the **same shapes** from the API (see §5).
- **Backend** = Python 3.13, FastAPI serving both the static SPA and `/api/*`, plus a Telegram
  long-polling process and an APScheduler instance. SQLite via stdlib `sqlite3` + a thin DAL.

---

## 3. Functional requirements (delta from v1 — see v1 for FR1–FR8 basics)

- **FR4 Top-shelf filter** — brand allowlist (editable) + per-category price/quality floor. A deal
  qualifies if `brand ∈ allowlist AND passes floor AND has a validated discount`.
- **FR5 Ranking** — transparent **deal score** = `discount_depth + $/g-vs-area-median +
  brand_tier_weight + distance_penalty + freshness`, stored and **explainable** (the UI shows the
  per-factor breakdown). Everything sorts by score desc by default. See §6 for the exact formula the
  prototype uses — port it verbatim so the UI keeps working.
- **FR5b Fire / price-memory (NEW)** — using `price_observations`:
  - `priorAvg`, `priorMin` over the trailing ~14 days (excluding today).
  - `isLowest` = today's sale ≤ priorMin.
  - `pctBelowAvg` = how far today is under its own average.
  - **fire** = `not markup-trap AND isLowest AND pctBelowAvg ≥ ~36%` → 🔥 badge + daily alert.
  - **markup trap** = price sat low for weeks, was raised to "original", then "discounted" → flagged
    ⚠ MARKUP and **excluded** from fire / alerts.
- **FR6 Dashboard** — category tabs, sort (score/price/%off/distance), filters (max distance, min %off,
  in-stock-only), **location switcher**, **saved filter presets**, hero #1 spotlight, glass deal
  grid, deal-detail modal with the full spec + score + price-memory panels.
- **FR7 Telegram** — every answer is a **ranked table best→worst** with **Type**, `$/u`, `%off`,
  shop, distance, and per-row **Special** + **Route** links. Commands: `/deals /flower /prerolls
  /edibles /hash|/concentrates /vapes /digest`, plus free text ("hash under $25/g near old town").
  Proactive alerts **once a day** (9 AM), deduped. `/filters`, `/mute`, `/snooze`.
- **FR8 Memory** — recurring-deal detection (weekday cadence), pre-recurrence reminders, **Sunday
  weekly digest**. First-time-patient deals tagged one-time and excluded from digests. All schedules
  pinned to `America/Phoenix`.

---

## 4. Data model (SQLite) — unchanged from v1, with explicit fire columns

```
dispensaries (id, name, address, lat, lng, dist_85251, dist_85255, platform, menu_ref, active)
brands       (id, canonical_name, aliases_json, tier, allowlisted)
products     (id, dispensary_id, brand_id, name, category, strain_type, lineage,
              size_g, thc_pct, cbd_pct, unit, unit_label, description, effects_json,
              image_url, menu_url)
price_observations (id, product_id, observed_at, price, sale_price, is_sale, source_platform, in_stock)
deals        (id, product_id, dispensary_id, original_price, sale_price, discount_pct_validated,
              unit_price, score, score_factors_json, prior_avg, prior_min, is_lowest,
              pct_below_avg, is_fire, is_markup_trap, first_seen, last_seen,
              is_recurring, recurrence_dow, in_stock)
filters      (id, name, json_criteria, active, telegram_alerts_on)
notifications_sent (id, deal_id, filter_id, sent_at, alerted_price)   -- dedup ledger
digests      (id, period_start, sent_at)
```

---

## 5. API contract (what the SPA expects) — see CLAUDE.md §3 for exact JSON

- `GET /api/bootstrap` → `{ deals[], shops, locations, dist, cats, generatedAt }` (one call powers
  first paint; `deals` are fully augmented).
- `GET /api/deals?location=<id>` → refreshed augmented deals.
- `GET /api/filters` · `POST /api/filters` · `PATCH/DELETE /api/filters/:id` (saved presets).
- Static: `GET /` serves `TopShelf.html`; `/TopShelf/**` serves assets.
- Telegram runs as its own process; no inbound HTTP needed (long-polling).

The **deal JSON must match the prototype's object shape exactly** (CLAUDE.md §3.1) so the UI renders
unchanged.

---

## 6. Scoring & fire — exact logic to port (from `TopShelf/app/shared.jsx → tsAugment`)

```
median   = per-category median of unit price across the current qualifying deals
vsArea   = clamp(0, 24, round((median - unit) / median * 60) + 8)
tierW    = {S:24, A:18, B:12}[tier]  (default 10)
depth    = round(off * 0.7)
distPen  = max(2, round(18 - dist * 2))
fresh    = 14 if seen<1h(minutes) else 10 if seen≈1h else 6
score    = clamp(0, 100, depth + vsArea + tierW + distPen + fresh)   # was authored in mock; COMPUTE it
factors  = [Discount depth, $/g vs area, Brand tier, Distance, Freshness] with each component value

# price memory (per product, from price_observations)
prior        = observations excluding today
priorAvg     = mean(prior.effective_price)
priorMin     = min(prior.effective_price)
isLowest     = sale <= priorMin
pctBelowAvg  = max(0, round((priorAvg - sale) / priorAvg * 100))
isMarkupTrap = price sat ≤ ~sale*1.05 for most of the window, then jumped to "original" within ~2 days
fire         = (not isMarkupTrap) and isLowest and (pctBelowAvg >= 36)   # threshold is tunable
```

---

## 7. Milestones (re-scoped for "wire the backend tonight")

- **M0 — Static integration (tonight, first):** stand up FastAPI, serve `TopShelf.html`, implement
  `GET /api/bootstrap` returning the **current seed data** (port `deals.js`) in the exact shape →
  flip the SPA from `deals.js` to the API (one-line loader swap). App runs end-to-end on live wiring.
- **M1 — Core pipeline:** dispensary seed + geocode, Dutchie + Leafly adapters, normalization,
  SQLite, scoring + fire. `/api/bootstrap` now returns real scraped data.
- **M2 — Persistence & memory:** price history, dedup, recurring detection, allowlist + floor,
  APScheduler scrape cadence.
- **M3 — Telegram:** alerts (daily), `/commands` → ranked tables with Type + links, free-text query.
- **M4 — Reminders & digest:** recurring reminders + Sunday digest; Weedmaps + proprietary adapters.

---

## 8. Risks / open questions (unchanged)

Scraping fragility (thin adapters, JSON-first, alert on adapter failure) · Cloudflare/bot walls
(Playwright + low cadence) · geocoding source (one-time, cacheable) · personal-use ToS gray area
(keep volume low/private). Future: drive-time vs straight-line; loyalty/stacking; brand vendor days.
