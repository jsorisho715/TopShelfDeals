import json, time, sys
disps = {d["name"]: d for d in json.load(open("app/seed/dispensaries.json", encoding="utf-8"))["dispensaries"]}


def t(name, adapter):
    s = disps.get(name)
    if not s:
        print(name, "MISSING from seed")
        return
    t0 = time.time()
    try:
        items = adapter.fetch(s)
    except Exception as e:
        items = []
        print(name, "EXC", repr(e))
    promo = sum(1 for i in items if i.get("promo_title"))
    print(f"{name}: {len(items)} items, {promo} with promo, {time.time()-t0:.1f}s")


if __name__ == "__main__":
    from app.adapters.proprietary import ProprietaryAdapter
    from app.adapters.cookies import CookiesAdapter
    which = sys.argv[1] if len(sys.argv) > 1 else "all"
    if which in ("all", "joint"):
        t("Sol Flower - Scottsdale Airpark", ProprietaryAdapter())
        t("YiLo Superstore - Arcadia", ProprietaryAdapter())
    if which in ("all", "cookies"):
        t("Cookies on Camelback", CookiesAdapter())
    if which in ("all", "trumed"):
        from app.adapters.trumed import TruMedAdapter
        t("TruMed", TruMedAdapter())
    if which in ("all", "trulieve"):
        from app.adapters.trulieve import TrulieveAdapter
        t("Trulieve - Scottsdale", TrulieveAdapter())
    if which == "trulieve2":
        from app.adapters.trulieve import TrulieveAdapter
        t("Trulieve - Phoenix Tatum", TrulieveAdapter())
        t("Trulieve - Guadalupe", TrulieveAdapter())
    if which in ("all", "weedmaps"):
        from app.adapters.weedmaps import WeedmapsAdapter
        t("Local Joint", WeedmapsAdapter())
