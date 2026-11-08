"""
Fetch all Tarkov items from the tarkov.dev JSON API and cache:
  - data/items.json        : metadata (id, name, sizes, prices)
  - data/icons/<id>.webp   : the grid icon (in-stash representation, background baked in)

Uses the JSON (REST) API at json.tarkov.dev — tarkov.dev put the GraphQL API into
maintenance mode and recommends the JSON API going forward. Two GETs per refresh:
  /pve/items     items keyed by id; translatable fields (name, shortName) hold keys
  /pve/items_en  English strings for those keys
The result is normalised to the shape the rest of the app reads from items.json (a list
of items with real names and a `sellFor` list), so scan.py / ocr_identify.py are unaware
of the source.

PvE note: tarkov.dev prices are flea-market based. PvE flea differs, but the item
identity + relative price-per-slot ranking is what we care about first.
"""
import json
import os
import sys
import time
import urllib.error
import urllib.request
import concurrent.futures

API = "https://json.tarkov.dev"
GAME_MODE = "pve"
LANG = "en"
UA = "Mozilla/5.0 tarkov-inv-tool"
DATA = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data")
ICONS = os.path.join(DATA, "icons")

# Fields kept in items.json. avg24hPrice = flea avg; lastLowPrice = latest flea low;
# basePrice = trader base; sellFor = per-trader sell prices (JSON API: sellToTrader).
FIELDS = ("id", "name", "shortName", "width", "height", "types", "basePrice",
          "avg24hPrice", "lastLowPrice", "gridImageLink")


def get_json(path):
    """GET {API}{path} and return its `data`. HTTP errors are raised with the server's
    message (e.g. an outage notice), not just the status code."""
    req = urllib.request.Request(API + path, headers={"User-Agent": UA})
    try:
        with urllib.request.urlopen(req, timeout=120) as r:
            payload = json.loads(r.read())
    except urllib.error.HTTPError as e:
        body = e.read().decode("utf-8", "replace").strip()
        try:
            body = "; ".join(map(str, json.loads(body)["errors"]))
        except (ValueError, KeyError, TypeError):
            pass
        raise RuntimeError(f"HTTP {e.code} {path}: {body[:300] or e.reason}") from e
    if payload.get("errors"):
        raise RuntimeError(payload["errors"])
    return payload["data"]


def fetch_items():
    """Fetch items + English strings and return the normalised items list."""
    raw = get_json(f"/{GAME_MODE}/items")["items"]
    text = get_json(f"/{GAME_MODE}/items_{LANG}")
    items = []
    for it in raw.values():
        out = {k: it.get(k) for k in FIELDS}
        out["name"] = text.get(it.get("name"), it.get("name"))
        out["shortName"] = text.get(it.get("shortName"), it.get("shortName"))
        out["sellFor"] = [{"priceRUB": s.get("priceRUB")} for s in (it.get("sellToTrader") or [])]
        items.append(out)
    return items


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
    print(f"Fetching {API}/{GAME_MODE}/items ...")
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
