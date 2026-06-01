# TopShelf 🌿

**Find the best top-shelf cannabis deals around Phoenix — ranked best to worst, with the fakes filtered out.**

TopShelf scours nearby dispensary menus, keeps only quality top-shelf brands, and ranks every deal
with a transparent score. It remembers each product's price history so it can flag genuine **🔥 fire
deals** — real record-lows — and call out fake **⚠ markup** "sales" where the "original" price was
quietly inflated first. There's also a Telegram bot that answers questions with ranked tables that
link straight to the special and to driving directions.

> 👋 **Hey, welcome!** This is my first real public little app. I built it to find good weed deals in
> Phoenix and figured other people might find it useful too. It's early and rough in places — if you
> want to **jump in, help out, or expand how it works, please do!** PRs, ideas, and issues are all
> welcome. Thanks for being here. 🙏

---

## What it does

- **Aggregates** deals from nearby dispensary menus (within ~7 mi of Scottsdale/Phoenix zips).
- **Filters to top-shelf** — only allowlisted quality brands above a price/quality floor.
- **Ranks every deal best → worst** with a transparent, explainable score (you can see *why* each
  deal scored the way it did).
- **Remembers prices** over a ~14-day window to spot **real** lows (🔥) and ignore **fake** sales (⚠).
- **Talks over Telegram** — ranked tables with `Type · $/u · %off · shop · mi` plus **Special** (menu)
  and **Route** (Google Maps) links, daily fire-deal alerts, and a weekly digest.

It started as a personal Scottsdale tool, but the goal now is a friendly, open project anyone in the
Valley can use and improve.

---

## 🔞 Responsible use first

- **21+ only.** This is for adults in a state where cannabis is legal. Please respect your local laws.
- **Be a polite scraper.** TopShelf reads *public* menu pages on a slow cadence (every 3–6 h) with
  delays and low concurrency. Please keep it that way — don't hammer dispensary sites. Aggressive
  scraping is bad for everyone and sits in a ToS gray area.
- **Prices change fast.** Always confirm the deal on the dispensary's own menu before you drive out.
- Not affiliated with, endorsed by, or sponsored by any dispensary or platform.

---

## Try it in 30 seconds (front end only)

The front end is **vanilla**: no npm, no bundler, no build step — React 18 + Babel straight from a
CDN. The prototype runs fully on the bundled sample data in `topshelf/data/deals.js`.

```bash
# from the repo root — serve over HTTP (don't just double-click the file)
python -m http.server 8000
# then open http://localhost:8000/TopShelf.html
```

Any static server works (`npx serve`, `php -S`, VS Code Live Server, etc.).

What works right now (all on sample data):

- Dashboard with tilt/glare glass cards, a #1 hero, category tabs, sort, and distance/%off filters.
- **Location switcher** — recomputes distances + the radius live, persists to `localStorage`.
- **Saved filters** — a default applies on load; "Save filter" adds your own (persisted).
- **Deal detail** — product image, description, strain type, THC/CBD, lineage, effects, a transparent
  **score breakdown**, and a 14-day **price-memory** sparkline.
- **🔥 fire / ⚠ markup** badges driven by the price-memory engine.
- **Telegram view** — live `/commands` + free text → ranked tables with **Special** and **Route** links.

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
    telegram.jsx           ← phone-framed bot chat: ranked rows w/ Type + Special + Route links
  data/
    deals.js               ← seed data the API replaces in production
app/                       ← the Python backend (FastAPI + pipeline + bot + scheduler)
docs/PRD.md                ← the product spec — read this to understand the "why"
CLAUDE.md                  ← step-by-step backend build guide
```

**Planned/active stack:** Python 3.13 · FastAPI · `httpx` (+ Playwright fallback) · `sqlite3` + a thin
DAL · APScheduler (`America/Phoenix`) · `python-telegram-bot` (long-polling). Designed to run as one
process on an always-on machine.

```bash
# backend (see CLAUDE.md for the full scaffold)
uv venv && uv pip install fastapi "uvicorn[standard]" httpx apscheduler python-telegram-bot
uvicorn app.main:app --reload --port 8000
```

Run the whole stack (web + bot + scheduler in one event loop):

```powershell
.\.venv\Scripts\python.exe run.py
```

`run.py` serves the app on `:8000`, starts the bot, and runs the scheduler (scrape every ~3–6 h, a
09:00 fire-deal alert, evening recurring reminders, a Sunday 18:00 digest — all `America/Phoenix`).
It's single-instance safe via a localhost socket lock, so you can't accidentally start two bots.
See [`docs/PRD.md`](docs/PRD.md) and [`CLAUDE.md`](CLAUDE.md) for the full details.

---

## 🤝 Want to help?

Yes please! This is a learning-in-public project, so beginners are genuinely welcome — see
[`CONTRIBUTING.md`](CONTRIBUTING.md) for how to get started. A few ideas if you're looking for
something to pick up:

- **More dispensary adapters** — add scrapers for menus/platforms TopShelf doesn't cover yet.
- **Smarter scoring / fire detection** — tune the thresholds against real price data.
- **Better deduping** — match the same product across platforms more reliably.
- **More cities** — the logic isn't Phoenix-specific; help it work elsewhere.
- **Docs, examples, screenshots, bug reports** — all hugely appreciated.

The one firm rule: **don't change the front end's data shapes** — the UI renders straight off them.
Details are in [`CONTRIBUTING.md`](CONTRIBUTING.md) and `CLAUDE.md`.

Found a bug or have an idea? [Open an issue](https://github.com/jsorisho715/TopShelfDeals/issues) —
no idea is too small.

---

## Notes

- **Times** are all `America/Phoenix` (Arizona doesn't observe DST).
- **Product images**: set each deal's `img` to the scraped product image URL and the cards/detail
  render it automatically.
- **License**: [MIT](LICENSE) — use it, fork it, build on it.
