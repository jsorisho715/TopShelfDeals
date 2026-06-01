"""Throwaway: probe candidate Dutchie menu URLs. httpx-only (fast) slug resolution."""
import os, sys
os.environ["SCRAPE_NO_BROWSER"] = "1"  # fast pass: no playwright
from app.adapters.dutchie import DutchieAdapter, slug_from_menu_url
import httpx

adapter = DutchieAdapter()

candidates = [
    ("Story Cannabis Scottsdale", "https://dutchie.com/dispensary/story-cannabis-scottsdale"),
    ("Sunday Goods Tempe A", "https://dutchie.com/dispensary/sunday-goods-tempe"),
    ("Sunday Goods Tempe B", "https://dutchie.com/embedded-menu/sunday-goods-tempe"),
    ("Sunday Goods Tempe C", "https://dutchie.com/dispensary/sunday-goods-dispensary-tempe"),
    ("AZ Organix", "https://dutchie.com/dispensary/az-organix"),
    ("Oasis Cannabis Scottsdale", "https://dutchie.com/dispensary/oasis-cannabis-scottsdale"),
    ("Nature's Medicines Phoenix", "https://dutchie.com/dispensary/natures-medicines-phoenix"),
    ("Local Joint Scottsdale", "https://dutchie.com/dispensary/local-joint-scottsdale"),
    ("YiLo Superstore", "https://dutchie.com/dispensary/yilo-superstore"),
    ("Ponderosa Releaf", "https://dutchie.com/dispensary/ponderosa"),
]

for name, url in candidates:
    slug = slug_from_menu_url(url)
    try:
        with httpx.Client(timeout=12.0, follow_redirects=True) as client:
            did = adapter._resolve_dispensary_id(client, slug)
        if did:
            items = adapter.fetch({"name": name, "menu": url})
            brands = sorted({str(i.get("brand")) for i in items if i.get("brand")})
            print(f"OK   {name}: id={did} items={len(items)} brands={brands[:12]}")
        else:
            print(f"NULL {name}: slug={slug} resolved no dispensary id")
    except Exception as e:
        print(f"ERR  {name}: {type(e).__name__}: {e}")
