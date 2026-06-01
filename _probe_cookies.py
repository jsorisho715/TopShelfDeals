import httpx, json

urls = [
    "https://cookies.co/products.json?limit=5",
    "https://cookies.co/collections/all/products.json?limit=5",
    "https://cookiesphoenix.com/products.json?limit=5",
]
for url in urls:
    try:
        r = httpx.get(url, timeout=15, follow_redirects=True,
                      headers={"User-Agent": "Mozilla/5.0", "Accept": "application/json"})
        print(url, "->", r.status_code, "len", len(r.text))
        if r.status_code == 200 and r.text.strip().startswith("{"):
            d = r.json()
            prods = d.get("products", [])
            print("  products:", len(prods))
            if prods:
                p = prods[0]
                print("  sample:", p.get("vendor"), "/", p.get("product_type"), "/", p.get("title"))
    except Exception as e:
        print(url, "EXC", repr(e))
