import json, collections, time
from pathlib import Path
from app import scrape

DATA = Path("data")
store_cache_path = DATA / "store_deals.json"
live = DATA / "live_deals.json"

# Seed per-store keep-last-good cache from the current live cache (one-time) so
# no currently-working store can drop to 0 on this run.
if not store_cache_path.exists() and live.exists():
    deals = json.load(open(live, encoding="utf-8")).get("deals", [])
    by_shop = collections.defaultdict(list)
    for d in deals:
        by_shop[d.get("shop")].append(d)
    seed = {shop: {"deals": ds, "at": "seed"} for shop, ds in by_shop.items() if shop}
    json.dump(seed, open(store_cache_path, "w", encoding="utf-8"))
    print(f"seeded store cache from {len(deals)} live deals across {len(seed)} shops")

t0 = time.time()
deals = scrape.scrape_all(write_db=True)
print(f"=== scrape_all -> {len(deals)} deals in {time.time()-t0:.0f}s ===")
rep = scrape.load_scrape_report()
status = collections.Counter(r["status"] for r in rep["stores"])
print("store status:", dict(status))
print("--- non-fresh stores ---")
for r in rep["stores"]:
    if r["status"] != "fresh":
        print(f"  {r['status']:<16} {r.get('platform','?'):<13} kept={r.get('kept',0):<4} {r['shop']}")
print("distinct shops in result:", len({d.get('shop') for d in deals}))
print("stale deals:", sum(1 for d in deals if d.get('stale')))
