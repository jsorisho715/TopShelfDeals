"""Diagnostic: which brand strings are we dropping (not on the allowlist)?

Runs every active store's adapter (httpx-only by default for speed/politeness),
collects the raw brand strings, and reports those that DON'T resolve against
``app/seed/brands_allowlist.json`` — sorted by frequency. Use this to decide,
with evidence, which real top-shelf brands/aliases to add (CLAUDE §5.3 / Phase
3c) rather than guessing.

Usage (from repo root):
    .venv\\Scripts\\python.exe scripts/dropped_brands.py            # httpx-only, fast
    set SCRAPE_NO_BROWSER=&& .venv\\Scripts\\python.exe scripts/dropped_brands.py  # allow browser

Writes ``data/dropped_brands.json`` and prints the top entries.
"""

from __future__ import annotations

import json
import os
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.pipeline.normalize import resolve_brand  # noqa: E402
from app.scrape import _active_dispensaries, _adapter_registry  # noqa: E402

_DATA = Path(__file__).resolve().parent.parent / "data"


def main() -> None:
    os.environ.setdefault("SCRAPE_NO_BROWSER", "1")  # fast/polite by default
    registry = _adapter_registry()
    dropped: Counter = Counter()
    kept: Counter = Counter()
    per_store: dict[str, dict] = {}

    for store in _active_dispensaries():
        platform = store.get("platform")
        adapter = registry.get(platform)
        name = store.get("name") or "?"
        if adapter is None:
            continue
        try:
            items = adapter.fetch(store) or []
        except Exception as exc:  # noqa: BLE001
            per_store[name] = {"error": repr(exc)}
            continue
        d = k = 0
        for it in items:
            brand = (it.get("brand") or "").strip()
            if not brand:
                continue
            if resolve_brand(brand):
                kept[brand] += 1
                k += 1
            else:
                dropped[brand] += 1
                d += 1
        per_store[name] = {"platform": platform, "items": len(items), "kept": k, "dropped": d}
        print(f"{name:40} {platform:14} items={len(items):4} kept={k:4} dropped={d:4}")

    report = {
        "dropped_brands": dropped.most_common(),
        "kept_brands": kept.most_common(),
        "per_store": per_store,
    }
    _DATA.mkdir(parents=True, exist_ok=True)
    (_DATA / "dropped_brands.json").write_text(json.dumps(report, indent=2), encoding="utf-8")

    print("\n=== TOP DROPPED BRAND STRINGS (candidates to allowlist) ===")
    for brand, n in dropped.most_common(40):
        print(f"  {n:4}  {brand}")


if __name__ == "__main__":
    main()
