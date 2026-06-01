"""Throwaway: probe candidate menu URLs via the full adapter (playwright fallback)."""
import sys, time
from collections import Counter
from app.adapters.dutchie import DutchieAdapter
from app.pipeline.normalize import normalize_item, resolve_brand

adapter = DutchieAdapter()

# Candidates passed as CLI args index into this list (keeps each run bounded).
CANDS = {
    "sg-shop":  ("Sunday Goods (shop)", "https://sundaygoods.com/shop/"),
    "sg-loc":   ("Sunday Goods (loc)", "https://sundaygoods.com/location/dispensary-tempe-az/"),
    "sg-dutch": ("Sunday Goods (dutchie)", "https://dutchie.com/dispensary/sunday-goods-tempe"),
    "story":    ("Story Cannabis Scottsdale", "https://dutchie.com/dispensary/story-cannabis-scottsdale"),
    "mint-sc":  ("The Mint Scottsdale", "https://mintdeals.com/scottsdale-az/menu/"),
    "oasis":    ("Oasis Cannabis Scottsdale", "https://dutchie.com/dispensary/oasis-cannabis-scottsdale"),
    "azorganix":("AZ Organix", "https://dutchie.com/dispensary/az-organix"),
    "yilo":     ("YiLo Superstore", "https://dutchie.com/dispensary/yilo-superstore"),
}

keys = sys.argv[1:] or list(CANDS.keys())
for k in keys:
    name, url = CANDS[k]
    t0 = time.time()
    try:
        items = adapter.fetch({"name": name, "menu": url})
    except Exception as e:
        print(f"ERR  [{k}] {name}: {type(e).__name__}: {e}")
        continue
    dt = time.time() - t0
    allow = []
    disc_allow = []
    for it in items:
        rec = resolve_brand(it.get("brand"))
        if rec:
            allow.append(it)
            orig, sale = it.get("orig"), it.get("sale")
            if orig and sale is not None and sale < orig:
                disc_allow.append((rec["canonical"], it.get("product"), orig, sale,
                                   round((orig-sale)/orig*100)))
    all_brands = Counter(str(i.get("brand")) for i in items if i.get("brand"))
    print(f"\n==== [{k}] {name}  ({dt:.0f}s)  captured={len(items)} allowlisted={len(allow)} discounted_allow={len(disc_allow)}")
    print(f"  ALL BRANDS: {dict(all_brands.most_common(25))}")
    if disc_allow:
        print("  DISCOUNTED ALLOWLISTED:")
        for c, p, o, s, off in disc_allow[:15]:
            print(f"    {off:>3}%  {c:<18} {o}->{s}  {str(p)[:42]}")
