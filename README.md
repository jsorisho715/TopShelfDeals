# TopShelf 🌿

**Find the best top-shelf cannabis deals around Phoenix — ranked best to worst, with the fakes filtered out.**

TopShelf scrapes ~46 live dispensary menus around the Valley, keeps only allowlisted top-shelf
brands, and ranks every deal with a transparent, explainable score. It remembers each product's price
history so it can flag genuine **🔥 fire deals** — real record-lows — and call out fake **⚠ markup**
"sales" where the "original" price was quietly inflated first. A Telegram bot answers questions with
shop-grouped cards that link straight to the special and to driving directions.

> 👋 **Hey, welcome!** This is my first real public little app. I built it to find good weed deals in
> Phoenix and figured other people might find it useful too. It's early and rough in places — if you
> want to **jump in, help out, or expand how it works, please do!** PRs, ideas, and issues are all
> welcome. Thanks for being here. 🙏

---

## What it does

- **Aggregates** real, live deals from ~46 dispensary menus across the Phoenix metro (Scottsdale,
  Tempe, Phoenix and out toward Mesa/Glendale/Chandler) on a slow, polite cadence. Every active menu
  is scraped regardless of distance; *you* control how near/far with a per-location distance filter.
- **Filters to top-shelf** — only allowlisted quality brands above a per-category price/quality floor.
- **Ranks every deal best → worst** with a transparent score (you can see *why* each deal scored the
  way it did — discount depth, $/unit vs the area, brand tier, distance, freshness).
- **Remembers prices** over a ~14-day window to spot **real** lows (🔥) and ignore **fake** sales (⚠).
- **Talks over Telegram** — command replies come as cards grouped by nearest shop (product, brand,
  price, %off, strain type, THC, distance) with tap-through **Open menu** + **Directions** buttons;
  alerts and the digest come as ranked best→worst tables. Plus on-demand `/refresh`, daily fire-deal
  alerts, evening recurring reminders, and a Sunday digest.

It started as a personal Scottsdale tool, but the goal now is a friendly, open project anyone in the
Valley can use and improve.

> **Status:** the backend is live. The web dashboard and the bot both serve **real scraped deals**,
> and fall back to the bundled sample data only when there's no fresh scrape cached yet.

---

## 🔞 Responsible use first

- **21+ only.** This is for adults in a state where cannabis is legal. Please respect your local laws.
- **Be a polite scraper.** TopShelf reads *public* menu pages on a slow cadence (every ~3–5 h) with
  jittered delays and low concurrency. Please keep it that way — don't hammer dispensary sites.
  Aggressive scraping is bad for everyone and sits in a ToS gray area.
- **Prices change fast.** Always confirm the deal on the dispensary's own menu before you drive out.
- Not affiliated with, endorsed by, or sponsored by any dispensary or platform.

---

## Try it in 30 seconds (front end only)

The front end is **vanilla**: no npm, no bundler, no build step — React 18 + Babel straight from a
CDN. With no backend running it renders fully on the bundled sample data in `topshelf/data/deals.js`.

```bash
# from the repo root — serve over HTTP (don't just double-click the file)
python -m http.server 8000
# then open http://localhost:8000/TopShelf.html
```

Any static server works (`npx serve`, `php -S`, VS Code Live Server, etc.).

What you'll see:

- Dashboard with tilt/glare glass cards, a #1 hero, category tabs, sort, and distance/%off filters.
- **Location switcher** — recomputes distances + the radius live, persists to `localStorage`.
- **Saved filters** — a default applies on load; "Save filter" adds your own (persisted).
- **Deal detail** — product image, description, strain type, THC/CBD, lineage, effects, a transparent
  **score breakdown**, and a 14-day **price-memory** sparkline.
- **🔥 fire / ⚠ markup** badges driven by the price-memory engine.
- **Telegram view** — a phone-framed preview of the bot's `/commands` and free-text replies.

---

## Run the full stack (web + bot + scheduler)

Everything runs as **one process on one event loop** — the FastAPI web app, the Telegram bot
(long-polling), and the APScheduler jobs.

```bash
# 1. install deps (Python 3.13)
uv venv && uv pip install -r requirements.txt
#    or:  python -m venv .venv && .venv\Scripts\pip install -r requirements.txt

# 2. configure secrets
copy .env.example .env        # then fill in TELEGRAM_BOT_TOKEN + TELEGRAM_CHAT_ID

# 3. run the whole stack
.\.venv\Scripts\python.exe run.py
#    open http://localhost:8000/TopShelf.html
```

`run.py` serves the app on `:8000`, starts the bot, and runs the scheduler (scrape every ~3–5 h, a
09:00 fire-deal alert, evening recurring reminders, a Sunday 18:00 digest — all `America/Phoenix`).
It's **single-instance safe**: it holds a localhost socket lock (`:8765`) and the bot holds its own
(`:49217`), so you can't accidentally start two web servers or two bot pollers.

> Running just the web app for development (no bot/scheduler):
> `uvicorn app.main:app --reload --port 8000`. Set `ENABLE_SCHEDULER=0` to skip the in-process jobs.

### Windows desktop launcher (optional)

For an always-on PC there's a one-click system-tray launcher (`tray_app.py`): it cleans up any prior
instance, starts the web server + bot in the background, opens the dashboard, and sits in the tray
with Open / Restart / Quit. Install the desktop icon with
`scripts/install_desktop_icon.ps1`. See [`README_LAUNCHER.md`](README_LAUNCHER.md) for details.

### Refresh the deals yourself

```bash
# run one polite scrape of every active store and print per-store coverage
.\.venv\Scripts\python.exe -m app.scrape
#   --no-db   don't persist to SQLite (price history won't accumulate)
#   --json    print the augmented deals as JSON instead of a report
```

---

## How it's built

```
TopShelf.html              ← the app (open this). React 18 + Babel via CDN, no build step.
topshelf/
  app/
    shared.jsx             ← tilt/glare, count-up, score ring, sparkline, icons,
                             tsAugment() = scoring + fire/price-memory engine, location helpers
    dashboard.jsx          ← deal grid, hero, tabs, filters, location switcher, saved filters
    detail.jsx             ← deal detail modal: image, specs, score breakdown, price memory
    telegram.jsx           ← phone-framed bot chat preview
  data/deals.js            ← sample data the API replaces with live scrapes in production
app/
  main.py                  ← FastAPI: serve the SPA + static, mount /api, start scheduler
  api.py                   ← /api/bootstrap, /api/deals, /api/filters, /api/users, /api/health, /api/ping
  db.py                    ← sqlite connection, migration runner, DAL helpers
  scrape.py                ← orchestrates the adapters (polite delays, retries, per-store report)
  scheduler.py             ← APScheduler jobs (scrape / daily alert / recurring / weekly digest)
  notify.py                ← Telegram sender used by the scheduler + /api/ping
  adapters/                ← one fetcher per menu platform (see below)
  pipeline/                ← normalize · dedup · score · pricememory · specials · serialize · geocode
  bot/                     ← bot.py (long-polling) · queries.py (parser+rank) · render.py (cards)
  seed/                    ← dispensaries.json + brands_allowlist.json (editable config)
migrations/*.sql           ← ordered schema migrations
data/                      ← sqlite db, live-deal cache, scrape report, geocode cache (gitignored bits)
run.py                     ← single-process supervisor (web + bot + scheduler)
tray_app.py                ← Windows system-tray launcher
docs/PRD.md                ← the product spec — read this to understand the "why"
CLAUDE.md                  ← backend build guide / architecture notes
```

**Stack:** Python 3.13 · FastAPI · `httpx` (+ Playwright fallback for JS-gated/Cloudflare menus) ·
stdlib `sqlite3` + a thin DAL · APScheduler (`America/Phoenix`) · `python-telegram-bot` (long-polling).
Designed to run as one process on an always-on machine. Full dependency pins are in
[`requirements.txt`](requirements.txt).

### Dispensary coverage & adapters

~46 active menus are wired across five live platforms (the platform counts below: Leafly 26 ·
Trulieve 9 · JointCommerce 6 · Dutchie 4 · TruMed 1), with three more adapters (Weedmaps,
Cookies/Shopify, Jane) registered and ready for stores that resolve:

| Platform | Adapter | Notes |
| --- | --- | --- |
| Leafly | `adapters/leafly.py` | httpx, no browser — the broadest coverage |
| Trulieve | `adapters/trulieve.py` | resolves the embedded Dutchie storefront |
| JointCommerce | `adapters/proprietary.py` | livewithsol.com / yilo.com `_search` API |
| Dutchie | `adapters/dutchie.py` | GraphQL, Playwright fallback |
| TruMed | `adapters/trumed.py` | embedded Dutchie menu |
| Weedmaps | `adapters/weedmaps.py` | registered; many routes are Akamai-gated |
| Cookies / Shopify | `adapters/cookies.py` | registered for any Shopify `products.json` menu |

`adapters/jane.py` is a full I Heart Jane adapter (Algolia index + Playwright fallback, unit-tested),
wired and ready — there's just no active Jane store in the seed right now. `adapters/promo.py` helps
extract labeled specials. Stores live in `app/seed/dispensaries.json` (flip `active` to
enable/disable one); the brand allowlist + per-category floors live in `app/seed/brands_allowlist.json`.

---

## The pipeline (why a "deal" is trustworthy)

Each raw menu item flows through `app/pipeline/`:

1. **normalize** — canonical brand (via the allowlist + aliases), `$/unit` (`$/g`, `$/10mg`), strain
   type, THC/CBD. Items whose brand isn't allowlisted or that fail the price/quality floor are dropped.
2. **dedup** — the same product at the same shop across platforms collapses to one (lowest price,
   richest metadata).
3. **score** — discount depth + $/unit vs the category median + brand tier + distance + freshness,
   each surfaced as an explainable factor.
4. **pricememory** — `priorAvg`/`priorMin`, `isLowest`, `pctBelowAvg`, and the **fire** vs
   **markup-trap** call from the ~14-day observation window.
5. **serialize** — emits the exact `Deal` JSON shape the SPA renders (see `CLAUDE.md §3.1`).

---

## Telegram bot

Long-polling, no inbound HTTP. Deal/category/free-text replies come as cards grouped by the shop
nearest you (best → worst within each), each with **Open menu** + **Directions** buttons; `/digest`
and the proactive alerts come as ranked best → worst tables.

- **Commands:** `/deals` · `/flower` `/prerolls` `/edibles` `/hash` `/concentrates` `/vapes` ·
  `/location` (set where distances are measured from) · `/refresh` (pull fresh prices now, rate-limited)
  · `/digest` · `/help`.
- **Free text:** e.g. *"hash under $25"*, *"flower near old town"*, *"edibles"*.
- **Proactive, never spammy:** a 09:00 batched alert of the day's new 🔥 fire deals matching your
  active saved filters (deduped, re-alerts only on a deeper drop), evening reminders the night before
  recurring deals, and a Sunday 18:00 weekly digest.
- **Access:** only the owner (`TELEGRAM_CHAT_ID`) and chats you add to the allowlist may talk to the
  bot. The allowlist is managed from the web app (`/api/users`).

---

## API

The SPA loads from `/api/bootstrap`; the rest power refresh, saved filters, the allowlist, and
ops visibility.

| Endpoint | Purpose |
| --- | --- |
| `GET /api/bootstrap` | one call powers first paint: deals + shops + locations + dist matrix + cats |
| `GET /api/deals` | refreshed deals + `generatedAt` |
| `GET /api/filters` · `POST` · `PATCH /:id` · `DELETE /:id` | saved filter presets |
| `GET /api/users` · `POST` · `PATCH /:id` · `DELETE /:id` | Telegram allowlist |
| `GET /api/users/owner` | the `.env` owner + whether Telegram is configured |
| `POST /api/ping` | push a deal (or list) to your Telegram chat |
| `GET /api/health` | per-store / per-platform scrape telemetry + live-deal summary |

---

## Configuration

Copy `.env.example` → `.env` (gitignored) and fill in:

| Key | What it's for |
| --- | --- |
| `TELEGRAM_BOT_TOKEN` | from @BotFather — needed to run the bot |
| `TELEGRAM_CHAT_ID` | your personal chat id (the only chat allowed by default) |
| `SCRAPE_MIN_DELAY_SEC` / `SCRAPE_MAX_DELAY_SEC` | the jittered delay between stores (default 2–5 s). Stores are fetched **sequentially** — concurrency is fixed at 1 by design |
| `SCRAPE_USER_AGENT` | the browser UA used for requests |
| `RADIUS_MILES` | default for the UI distance **filter** (mi), not a scrape boundary — every active store is scraped regardless (default 20) |
| `TIMEZONE` | all scheduling (default `America/Phoenix` — Arizona has no DST) |

> Geocoding uses the free OpenStreetMap **Nominatim** endpoint (≤1 req/s, cached to
> `data/geocode_cache.json`) — no API key needed. `SCRAPE_MAX_CONCURRENCY`, `GEOCODE_PROVIDER`, and
> `GEOCODE_API_KEY` appear in `.env.example` but are **not read by any code yet** (reserved).

---

## 🤝 Want to help?

Yes please! This is a learning-in-public project, so beginners are genuinely welcome — see
[`CONTRIBUTING.md`](CONTRIBUTING.md) for how to get started. A few ideas if you're looking for
something to pick up:

- **More dispensary adapters** — add scrapers for menus/platforms TopShelf doesn't cover yet
  (`app/adapters/`). `python -m app.scrape` prints per-store coverage so you can verify a new one.
- **Smarter scoring / fire detection** — tune the thresholds against real price data.
- **Better deduping** — match the same product across platforms more reliably.
- **More cities** — the logic isn't Phoenix-specific; help it work elsewhere.
- **Docs, examples, screenshots, bug reports** — all hugely appreciated.

The one firm rule: **don't change the front end's data shapes** — the UI renders straight off them.
Details are in [`CONTRIBUTING.md`](CONTRIBUTING.md) and `CLAUDE.md`. Tests run with `pytest`.

Found a bug or have an idea? [Open an issue](https://github.com/jsorisho715/TopShelfDeals/issues) —
no idea is too small.

---

## Notes

- **Times** are all `America/Phoenix` (Arizona doesn't observe DST).
- **Product images**: each deal's `img` is the scraped product image URL; the cards/detail render it
  automatically.
- **License**: [MIT](LICENSE) — use it, fork it, build on it.
