# TopShelf 🌿

A personal Scottsdale **top-shelf dispensary deal aggregator** + Telegram bot. It scours nearby
dispensary menus within 7 mi of 85251 / 85255, keeps only top-shelf brands above a quality floor,
ranks every deal **best → worst** with a transparent score, remembers each product's price history
to flag genuine **🔥 fire deals** (and catch fake **⚠ markup** "sales"), and answers questions over
Telegram with ranked tables that link straight to the special and to directions.

This repo currently contains the **finished hi-fi front end** (a working prototype with realistic
sample data) plus the docs to wire up the Python backend. See [`docs/PRD.md`](docs/PRD.md) for the
full spec and [`CLAUDE.md`](CLAUDE.md) for the step-by-step backend build guide.

---

## What's here

```
TopShelf.html              ← the app (open this). React 18 + Babel via CDN, no build step.
TopShelf/
  app/
    shared.jsx             ← tilt/glare, count-up, score ring, sparkline, icons,
                              tsAugment() = scoring + fire/price-memory engine, location helpers
    dashboard.jsx          ← deal grid, hero, tabs, filters, location switcher, saved filters
    detail.jsx             ← deal detail modal: image, specs, score breakdown, price memory
    telegram.jsx           ← phone-framed bot chat: ranked rows w/ Type + Special + Route links
    image-slot.js          ← drag-to-fill product image component (prototype affordance)
  data/
    deals.js               ← seed data: deals, shops (addresses + menu links), locations,
                              distance matrix, categories  ← THIS is what the API will replace
  directions/              ← the 3 explored visual directions (Vault / Arcade / Gallery), for reference
  Directions.html          ← side-by-side canvas of those directions
docs/PRD.md                ← product spec (v2)
CLAUDE.md                  ← backend build guide for Claude Code
```

The front end is **vanilla**: no npm, no bundler. Everything loads from CDN with pinned versions.

---

## Run the front end locally

The app uses `fetch()` for a couple of sidecar files, so serve it over HTTP (don't just
double-click the file).

```bash
# from the repo root
python -m http.server 8000
# then open:
#   http://localhost:8000/TopShelf.html
```

Any static server works (`npx serve`, `php -S`, VS Code Live Server, etc.). That's it — the
prototype runs fully on the bundled sample data in `TopShelf/data/deals.js`.

What works right now (all on sample data):
- Dashboard with tilt/glare glass cards, #1 hero, category tabs, sort, distance/%off filters.
- **Location switcher** — recomputes distances + the 7-mi radius live, persists to `localStorage`.
- **Saved filters** — a default is applied on load; "Save filter" adds your own (persisted).
- **Deal detail** — product image (drag a real photo in), description, strain type, THC/CBD,
  lineage, effects, transparent **score breakdown**, 14-day **price-memory** sparkline.
- **🔥 fire / ⚠ markup** badges driven by the price-memory engine.
- **Telegram view** — live `/commands` + free text → ranked tables (Type · $/u · %off · shop · mi)
  with per-row **Special** (menu) and **Route** (Google Maps) links; once-a-day alert + digest.
- Web → bot **Ping**: hit Ping on a card → it arrives in the Telegram chat.

---

## Wire up the backend (tonight)

Full instructions in [`CLAUDE.md`](CLAUDE.md). The short version:

1. **Stand up FastAPI**, serve `TopShelf.html` + assets, and implement `GET /api/bootstrap` that
   returns the **exact same shapes** currently in `TopShelf/data/deals.js`
   (`deals`, `shops`, `locations`, `dist`, `cats`).
2. **Flip the front end from static data to the API** — one small change in `TopShelf.html`
   (replace the `deals.js` script tag with a fetch that sets `window.TS_*` then renders). The
   exact snippet is in CLAUDE.md §4.
3. Now the app is running on live wiring with the seed data. From there, replace the seed with the
   real pipeline: scrapers → normalize/dedup → SQLite → score + fire → API. Then the Telegram
   process and the scheduler.

**Planned stack:** Python 3.13 · FastAPI · `httpx` (+ Playwright fallback) · `sqlite3` + thin DAL ·
APScheduler (`America/Phoenix`) · `python-telegram-bot` (long-polling). Target host: always-on
Windows PC (Task Scheduler / `nssm`).

```bash
# planned backend bootstrap (see CLAUDE.md for the full scaffold)
uv venv && uv pip install fastapi "uvicorn[standard]" httpx apscheduler python-telegram-bot
uvicorn app.main:app --reload --port 8000
```

---

## Run it (production)

Once the backend is wired up, run the **whole stack in one process** — the FastAPI web app, the
Telegram bot (long-polling), and the APScheduler jobs all share a single event loop:

```powershell
.\.venv\Scripts\python.exe run.py
```

That's it. `run.py` serves the app on `:8000` (override with `PORT`), starts the bot, and starts the
scheduler (scrape every ~3–6 h, the 09:00 fire-deal alert, evening recurring reminders, and the
Sunday 18:00 digest — all `America/Phoenix`). Press **Ctrl+C** for a clean shutdown of all three.

**Single-instance safe.** Before doing anything, `run.py` grabs a process-wide lock by binding a
localhost socket (`127.0.0.1:8765`, override with `RUN_LOCK_PORT`). If a second copy starts while the
first is alive, the bind fails, it prints a notice, and exits `0` — so you can never accidentally
start a duplicate Telegram poller (the cause of `Conflict: terminated by other getUpdates`). Don't
run `python -m app.bot.bot` *and* `run.py` at the same time; `run.py` is the one entrypoint.

> The embedded web app is launched with `ENABLE_SCHEDULER=0` so the scheduler is owned solely by
> `run.py` and never double-starts.

### Auto-start on the always-on Windows PC

**Option A — Task Scheduler (built in).** Create a task that runs at logon / startup:

- *Program/script:* `C:\Users\<you>\..PROJECTS\Active\TopShelfDeals\.venv\Scripts\python.exe`
- *Arguments:* `run.py`
- *Start in:* `C:\Users\<you>\..PROJECTS\Active\TopShelfDeals`
- Settings: **Run whether user is logged on or not**, and **If the task is already running, do not
  start a new instance** (the socket lock is a second line of defense anyway).

Or from an elevated PowerShell:

```powershell
$dir = "C:\Users\<you>\..PROJECTS\Active\TopShelfDeals"
$act = New-ScheduledTaskAction -Execute "$dir\.venv\Scripts\python.exe" -Argument "run.py" -WorkingDirectory $dir
$trg = New-ScheduledTaskTrigger -AtStartup
Register-ScheduledTask -TaskName "TopShelf" -Action $act -Trigger $trg -RunLevel Highest
```

**Option B — [nssm](https://nssm.cc/) (run as a Windows service, auto-restart on crash).**

```powershell
nssm install TopShelf "C:\...\TopShelfDeals\.venv\Scripts\python.exe" run.py
nssm set TopShelf AppDirectory "C:\...\TopShelfDeals"
nssm start TopShelf
```

Either way the single-instance lock guarantees that a restart, a stray manual launch, or an
overlapping Task Scheduler trigger can't produce two bots.

---

## Notes

- **Product images**: in the prototype each card shows a branded procedural placeholder; the detail
  view lets you drag in a real photo. In production, set each deal's `img` to the **scraped product
  image URL** and the same components render it automatically.
- **Times**: everything is `America/Phoenix` (no DST).
- **Legal**: personal-use scraping of public menu pages sits in a ToS gray area — keep volume low,
  cadence slow (every 3–6 h), and the tool private.
