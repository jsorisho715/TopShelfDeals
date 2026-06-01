import time, json
from app.scrape import scrape_all

t0 = time.time()
deals = scrape_all(write_db=True)
dt = time.time() - t0

shops = sorted({d.get("shop") for d in deals if d.get("shop")})
fire = [d for d in deals if d.get("fire")]
promo = [d for d in deals if d.get("promo_title")]
on_sale = [d for d in deals if (d.get("off") or 0) > 0]
recurring = [d for d in deals if d.get("recurring")]
with_desc = [d for d in deals if d.get("desc")]
with_eff = [d for d in deals if d.get("effects")]
with_lin = [d for d in deals if d.get("lineage")]
with_dist = [d for d in deals if d.get("distByAnchor")]

print(f"=== SCRAPE COMPLETE in {dt:.0f}s ===")
print(f"deals:        {len(deals)}")
print(f"shops:        {len(shops)}")
print(f"fire:         {len(fire)}")
print(f"with promo:   {len(promo)}")
print(f"on sale:      {len(on_sale)}")
print(f"recurring:    {len(recurring)}")
print(f"with desc:    {len(with_desc)}")
print(f"with effects: {len(with_eff)}")
print(f"with lineage: {len(with_lin)}")
print(f"distByAnchor: {len(with_dist)}")
print("\nshops:")
for s in shops:
    print("  -", s)

from collections import Counter
plats = Counter(p for d in deals for p in (d.get("platforms") or ([d.get("platform")] if d.get("platform") else [])))
print("\nplatforms on deals:", dict(plats))

print("\nsample fire/promo deals:")
for d in (fire or promo)[:6]:
    print(f"  {d.get('shop')}: {d.get('brand')} {d.get('product')[:40]} off={d.get('off')} fire={d.get('fire')} :: {d.get('fireReason')}")
