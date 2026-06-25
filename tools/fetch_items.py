"""
Fetch all Tarkov items from the tarkov.dev GraphQL API and cache:
  - data/items.json        : metadata (id, name, sizes, prices)
  - data/icons/<id>.webp   : the grid icon (in-stash representation, background baked in)

PvE note: tarkov.dev prices are flea-market based. PvE flea differs, but the item
identity + relative price-per-slot ranking is what we care about first.
"""
import json
import os
import sys
import time
import urllib.request
import concurrent.futures

API = "https://api.tarkov.dev/graphql"
UA = "Mozilla/5.0 tarkov-inv-tool"
DATA = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data")
ICONS = os.path.join(DATA, "icons")

# avg24hPrice = flea avg; basePrice = trader base; sellFor = best sell option per vendor
QUERY = """
{
  items(gameMode: pve) {
    id
    name
    shortName
    width
    height
    types
    basePrice
    avg24hPrice
    lastLowPrice
    gridImageLink
    sellFor { priceRUB vendor { name } }
  }
}
"""


def gql(query):
    req = urllib.request.Request(
        API,
        data=json.dumps({"query": query}).encode(),
        headers={"Content-Type": "application/json", "User-Agent": UA},
    )
    with urllib.request.urlopen(req, timeout=60) as r:
        payload = json.loads(r.read())
    if "errors" in payload:
        raise RuntimeError(payload["errors"])
    return payload["data"]


def fetch_items():
    """Query the API and return the raw items list (prices + metadata)."""
    return gql(QUERY)["items"]


def write_items(items, path=None):
    """Persist the items list to data/items.json (the price/metadata cache)."""
    path = path or os.path.join(DATA, "items.json")
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(items, f)
    return path


def download_icon(item):
    url = item.get("gridImageLink")
    if not url:
        return item["id"], False
    path = os.path.join(ICONS, item["id"] + ".webp")
    if os.path.exists(path) and os.path.getsize(path) > 0:
        return item["id"], True
    try:
        req = urllib.request.Request(url, headers={"User-Agent": UA})
        with urllib.request.urlopen(req, timeout=60) as r:
            blob = r.read()
        with open(path, "wb") as f:
            f.write(blob)
        return item["id"], True
    except Exception as e:
        print(f"  ! {item['id']} {url}: {e}", file=sys.stderr)
        return item["id"], False


def main():
    os.makedirs(ICONS, exist_ok=True)
    print("Querying GraphQL ...")
    items = fetch_items()
    print(f"  {len(items)} items")

    write_items(items)

    todo = [it for it in items if it.get("gridImageLink")]
    print(f"Downloading {len(todo)} icons (cached ones skipped) ...")
    ok = 0
    t0 = time.time()
    with concurrent.futures.ThreadPoolExecutor(max_workers=16) as ex:
        for i, (_id, success) in enumerate(ex.map(download_icon, todo), 1):
            ok += success
            if i % 200 == 0:
                print(f"  {i}/{len(todo)} ({ok} ok)")
    print(f"Done: {ok}/{len(todo)} icons in {time.time()-t0:.1f}s -> {ICONS}")


if __name__ == "__main__":
    main()
