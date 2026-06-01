# Contributing to TopShelf 🌿

Thanks for being here! This is a learning-in-public project, so **beginners are genuinely welcome**.
Whether you're fixing a typo, filing a bug, adding a dispensary scraper, or rethinking how scoring
works — it all helps. No contribution is too small.

If anything below is confusing, that's a docs bug. [Open an issue](https://github.com/jsorisho715/TopShelfDeals/issues)
and tell us.

---

## Ground rules (the short version)

- **Be kind and patient.** Assume good intent.
- **21+ and legal-first.** This project is for adults in places where cannabis is legal.
- **Be a polite scraper.** Any code that touches dispensary menus must keep slow delays, low
  concurrency, and a reasonable cadence (every 3–6 h). No aggressive scraping — it hurts the sites and
  everyone who relies on this tool. PRs that crank up request volume won't be merged.
- **Never commit secrets.** `.env` is gitignored — keep it that way. Use `.env.example` for new config
  keys (with placeholder values only).

---

## Getting started

1. **Fork** the repo and clone your fork.
2. **Run the front end** — no build step needed:

   ```bash
   python -m http.server 8000
   # open http://localhost:8000/TopShelf.html
   ```

3. **Set up the backend** (optional, for pipeline/bot work):

   ```bash
   uv venv
   uv pip install -r requirements.txt   # or see CLAUDE.md for the dependency list
   cp .env.example .env                 # then fill in values as needed
   uvicorn app.main:app --reload --port 8000
   ```

4. Read [`docs/PRD.md`](docs/PRD.md) for the "why" and [`CLAUDE.md`](CLAUDE.md) for the backend build
   guide and architecture.

---

## The one firm rule: don't break the data shapes

The front end renders **straight off** the JSON shapes produced by the API / seed data. If you rename
or drop a field, the UI breaks silently. So:

- Match the existing `Deal` object shape exactly (field names + types). The canonical example lives in
  `topshelf/data/deals.js`, and the derived fields are documented in `CLAUDE.md §3.1`.
- The scoring + price-memory math has a reference implementation in `topshelf/app/shared.jsx`
  (`tsAugment`). The Python pipeline must produce identical output.
- Please **don't restyle or rewrite the front end** unless an issue/PR is specifically about that.

---

## Good first contributions

- 🏪 **New dispensary adapters** — add a scraper for a menu/platform we don't cover yet
  (`app/adapters/`). Keep it polite.
- 🎯 **Scoring & fire-deal tuning** — improve thresholds against real price history.
- 🔁 **Deduping** — match the same product across platforms more reliably.
- 🌎 **More cities** — the logic isn't Phoenix-specific; help generalize it.
- 📝 **Docs, screenshots, examples, bug reports** — always appreciated.

---

## Submitting changes

1. Create a branch: `git checkout -b my-change`.
2. Make focused commits with clear messages.
3. Make sure the app still loads and (if you touched Python) tests pass: `pytest`.
4. Open a pull request describing **what** changed and **why**. Screenshots help for anything visual.

We'll review, suggest tweaks if needed, and merge. Thanks again for helping out! 🙏
