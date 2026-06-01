# CLAUDE.md — TopShelf backend build guide

Project instructions for Claude Code. Read this fully before writing code.

## What this repo is

A **finished hi-fi front end** for TopShelf — a personal Scottsdale top-shelf dispensary deal
aggregator + Telegram bot. The UI is done and works on bundled sample data. **Your job is to wire up
the Python backend** so the same UI runs on real, live data, then build the Telegram bot and
scheduler. Full product spec: `docs/PRD.md`.

### Guardrails (important)
- **Do not rewrite or restyle the front end.** It's a no-build React-via-CDN SPA (`TopShelf.html` +
  `TopShelf/app/*.jsx`). Touch it only for the one tiny data-loading swap in §4.
- **Match the existing JSON shapes exactly** (§3). The UI renders straight off these fields; if a
  field is missing or renamed, the UI breaks silently.
- Single-user, personal-use. No auth, no multi-tenant, no cloud. Runs on an always-on Windows PC.
- All scheduling in **`America/Phoenix`** (no DST). Be a polite scraper (see PRD FR2).

---

## 1. Stack & setup

Python 3.13. Suggested deps:

```bash
uv venv && uv pip install \
  fastapi "uvicorn[standard]" httpx apscheduler python-telegram-bot \
  selectolax playwright python-dotenv
# optional: playwright install chromium   (only for JS-gated/Cloudflare sites)
uvicorn app.main:app --reload --port 8000
# open http://localhost:8000/TopShelf.html
```

DB: stdlib `sqlite3` + a thin DAL (see PRD §4 for schema). Add a tiny migration runner
(`schema_version` table + ordered `.sql` files).

---

## 2. Backend structure to create

```
app/
  main.py            # FastAPI: serve SPA + static, mount /api router, start scheduler + bot
  api.py             # /api/bootstrap, /api/deals, /api/filters CRUD
  db.py              # sqlite connection, migrations, DAL helpers
  models.py          # dataclasses / TypedDicts mirroring the JSON shapes in §3
  pipeline/
    normalize.py     # raw menu item -> canonical Product/PriceObservation
    dedup.py         # cross-platform same-product dedup (keep lowest price, richest metadata)
    score.py         # scoring + factor breakdown (port §5.1 verbatim)
    pricememory.py   # priorAvg/min, isLowest, pctBelowAvg, fire, markup-trap (port §5.2)
    recurring.py     # weekday-cadence detection
    serialize.py     # DB rows -> the exact deal JSON in §3.1 (the contract boundary)
  adapters/
    base.py          # Adapter protocol: fetch(store_ref) -> list[MenuItem]
    dutchie.py  leafly.py  weedmaps.py  proprietary.py
  scrape.py          # orchestrates adapters with polite delays, caching, backoff
  scheduler.py       # APScheduler jobs (America/Phoenix): scrape / reminders / digest
  bot/
    bot.py           # python-telegram-bot long-polling app
    queries.py       # /command + free-text -> filtered, ranked deals
    render.py        # deals -> ranked-row message (Type, $/u, %off, shop, mi, Special, Route)
  seed/
    dispensaries.json  brands_allowlist.json   # editable config (PRD FR1/FR4)
data/topshelf.db     # sqlite (gitignored)
migrations/*.sql
.env                 # secrets (see §9)
```

---

## 3. API contract (the SPA depends on these exact shapes)

### `GET /api/bootstrap` → one call powers first paint
```json
{
  "deals":     [ <Deal>, ... ],          // fully augmented (see §3.1)
  "shops":     { "<shopName>": { "addr": "...", "platform": "Dutchie", "menu": "https://..." } },
  "locations": [ { "id": "oldtown", "label": "Old Town", "sub": "85251", "icon": "🏠" }, ... ],
  "dist":      { "<locId>": { "<shopName>": 2.3, ... }, ... },   // straight-line miles matrix
  "cats":      ["All","Flower","Prerolls","Edibles","Concentrates","Vapes"],
  "generatedAt": "2026-05-31T21:00:00-07:00"
}
```
- `GET /api/deals?location=<id>` → `{ "deals": [...], "generatedAt": ... }` (refresh).
- `GET /api/filters` → `[ { "id","name","c": {cat,sort,maxDist,minOff,inStock} }, ... ]`
- `POST /api/filters` (body = one preset) · `PATCH /api/filters/:id` · `DELETE /api/filters/:id`.
- `GET /` → serve `TopShelf.html`; mount `/TopShelf/**` as static.

### 3.1 The `Deal` object — produce these fields EXACTLY (names + types)

Copy a real example from `TopShelf/data/deals.js` (raw fields) and `TopShelf/app/shared.jsx`
(`tsAugment` adds the derived fields). Full list:

```jsonc
{
  // identity / classification
  "id": "fl1",
  "cat": "Flower",                 // one of cats (not "All")
  "product": "Atomic Apple",
  "brand": "Alien Labs",
  "tier": "S",                     // S | A | B  (from brand allowlist)
  "type": "Hybrid",               // Indica | Sativa | Hybrid
  "lineage": "Sour Apple × Triangle Kush",
  "thc": 31.4,                    // number; for edibles this is mg total
  "cbd": 0.1,
  "desc": "Loud, gassy hybrid …", // 1–3 sentence description
  "effects": ["Euphoric","Creative","Relaxed"],

  // location / store
  "shop": "Sol Flower",           // must match a key in `shops` and in every `dist[loc]`
  "area": "Scottsdale",
  "dist": 2.3,                    // fallback miles (UI prefers dist[loc][shop])
  "size": "3.5g",

  // pricing
  "orig": 60, "sale": 38,
  "unit": 10.9, "unitLabel": "/g",   // "/g" | "/10mg"  (normalized $/unit)
  "off": 37,                          // integer % off

  // ranking + memory (compute server-side — see §5)
  "score": 96,
  "factors": [ { "key": "Discount depth", "v": 26, "hint": "37% off, validated vs history" }, … ],
  "hist": [60,58,61,…,38],            // ~14 daily prices, oldest→today; last = sale
  "priorAvg": 59, "priorMin": 57,
  "isLowest": true, "pctBelowAvg": 37,
  "fire": true, "isTrap": false,
  "fireReason": "Lowest in 14 days · 37% under its own average",

  // freshness / availability / recurrence
  "seen": "12m ago",              // humanized from last_seen
  "stock": true,
  "recurring": true, "dow": "Fri",
  "hot": true                     // legacy; UI uses `fire` now. keep present (= fire) for safety.
}
```
The UI's `getDist(deal, locId)` reads `dist[locId][deal.shop]` and falls back to `deal.dist`. The
sparkline/price-memory panel read `hist`, `priorAvg`, `priorMin`, `isLowest`, `pctBelowAvg`, `fire`,
`isTrap`, `fireReason`. The detail specs read `type`, `thc`, `cbd`, `size`, `lineage`, `shop`.
For the real product photo, add `"img": "<scraped image URL>"` — the cards/detail will use it.

---

## 4. Flip the front end from static data → API (one change)

In `TopShelf.html`: **remove** the `deals.js` script tag…
```html
<script src="TopShelf/data/deals.js"></script>          <!-- DELETE this line -->
```
…and change the final render block to fetch first, then render. Also drop the client-side
`tsAugment` call since the backend now augments:
```html
<script type="text/babel">
  // …App component unchanged…
  // was: const [deals] = useState(() => window.tsAugment(window.TS_DEALS));
  // now: const [deals] = useState(() => window.TS_DEALS);    // already augmented by the API
  fetch('/api/bootstrap').then(r => r.json()).then(b => {
    window.TS_DEALS = b.deals; window.TS_CATS = b.cats; window.TS_SHOPS = b.shops;
    window.TS_LOCATIONS = b.locations; window.TS_DIST = b.dist;
    ReactDOM.createRoot(document.getElementById('root')).render(<App />);
  });
</script>
```
Keep `TopShelf/data/deals.js` around as the canonical example of the shapes (and as an offline
fallback). `shared.jsx`'s `tsAugment` is your reference implementation — port its math to Python in
`pipeline/score.py` + `pipeline/pricememory.py` so server output is identical.

---

## 5. Pipeline logic to port (from `TopShelf/app/shared.jsx → tsAugment`)

### 5.1 Score (compute it; the mock authored it)
```
median   = per-category median of `unit` across the current qualifying deals
vsArea   = clamp(0, 24, round((median - unit)/median*60) + 8)
tierW    = {S:24, A:18, B:12}.get(tier, 10)
depth    = round(off * 0.7)
distPen  = max(2, round(18 - dist*2))
fresh    = 14 if last_seen < 1h else (10 if < ~2h else 6)
score    = clamp(0, 100, depth + vsArea + tierW + distPen + fresh)
factors  = [("Discount depth",depth), ("$/g vs area",vsArea), ("Brand tier",tierW),
            ("Distance",distPen), ("Freshness",fresh)]  # include a human `hint` each
```

### 5.2 Price memory / fire (from `price_observations`)
```
prior        = observations for this product excluding today
priorAvg     = mean(effective_price(prior))          # effective = sale_price if is_sale else price
priorMin     = min(effective_price(prior))
isLowest     = sale <= priorMin
pctBelowAvg  = max(0, round((priorAvg - sale)/priorAvg * 100))
isMarkupTrap = price sat ≤ ~sale*1.05 for most of the window, then jumped to `orig` within ~2 days
               (i.e. the "original" is inflated vs the trailing typical price)
fire         = (not isMarkupTrap) and isLowest and (pctBelowAvg >= 36)   # tune threshold on real data
fireReason   = fire   -> f"Lowest in 14 days · {pctBelowAvg}% under its own average"
               isTrap -> f"Heads-up: it sat at ${priorMin} for weeks before this “sale”"
               else   -> f"Validated drop · {pctBelowAvg}% under its 14-day average"
```

### 5.3 Normalize / dedup / recurring
- **Brand normalize:** raw brand string → canonical via `brands_allowlist.json` aliases; drop deals
  whose brand isn't allowlisted or that fail the per-category price/quality floor.
- **Unit normalize:** compute `unit` + `unitLabel` (`$/g` flower/concentrate/preroll/vape,
  `$/10mg` edibles).
- **Dedup:** same product at same dispensary across Leafly/Weedmaps/own site → keep lowest price +
  richest metadata.
- **Recurring:** from `price_observations`, detect weekday cadence → `recurring`, `dow`.

---

## 6. Telegram bot (mirror the prototype's behavior)

- Long-polling (`python-telegram-bot`), no inbound HTTP. Token in `.env`.
- **Every reply is a ranked table best→worst** with columns **Rank · Type · Item·Brand · $/u ·
  %off · Shop · Mi** and per-row links **Special** (`shops[shop].menu`) and **Route**
  (`https://www.google.com/maps/dir/?api=1&destination=<urlencoded addr>`). See
  `TopShelf/app/telegram.jsx` (`RankRow`, `buildTable`→`rankRows`, `parseQuery`) for exact columns,
  ordering, and the free-text parser to port.
- Commands: `/deals /flower /prerolls /edibles /hash /concentrates /vapes /digest`,
  plus `/filters /mute /snooze`. Free text → `parseQuery` (category keywords, `under $N`, "near old
  town").
- **Proactive alerts once a day** (9:00 AM `America/Phoenix`): the day's new **fire** deals matching
  any active saved filter, batched into one message; dedup via `notifications_sent` (re-alert only on
  a deeper price). Never per-deal spam.
- **Reminders:** evening-before heads-up for known recurring deals.
- **Weekly digest:** Sunday evening — week's best + upcoming recurring.

---

## 7. Scheduler (APScheduler, tz=America/Phoenix)
- `scrape_all` every 3–6 h (jittered, polite).
- `daily_alert` 09:00 — batched fire-deal alert.
- `recurring_reminders` evenings — pre-recurrence heads-ups.
- `weekly_digest` Sunday ~18:00.
Use a fake clock in tests to assert fire times.

---

## 8. Config / secrets (`.env`)
```
TELEGRAM_BOT_TOKEN=...
TELEGRAM_CHAT_ID=...          # your personal chat id
HOME_ZIPS=85251,85255
RADIUS_MILES=7
GEOCODER=...                  # one-time geocode of dispensary addresses, cache results
SCRAPE_MIN_INTERVAL_H=3
```

---

## 9. Tonight — order of operations (definition of done)

1. **M0 (do first):** FastAPI serving `TopShelf.html`; `GET /api/bootstrap` returns the **current
   seed** (port `TopShelf/data/deals.js` straight into Python dicts, including the `dist` matrix and
   `shops`). Apply the §4 swap. → The app loads end-to-end from the API. ✅ This alone is "running."
2. **DB + DAL + migrations**; load `seed/dispensaries.json` + `brands_allowlist.json`.
3. **Dutchie + Leafly adapters** + `scrape.py`; normalize → SQLite `price_observations` + `products`.
4. **score.py + pricememory.py + serialize.py** → `/api/bootstrap` now returns real augmented deals.
5. **Telegram bot** (`/deals`, `/flower`, free text) returning ranked rows with links.
6. **Scheduler**: scrape cadence + 09:00 daily alert.
7. Weedmaps + proprietary adapters, recurring reminders, Sunday digest.

Verify each step against the prototype: same field names, ranked best→worst everywhere, fire only on
validated record-lows, markup traps excluded.
