"""
tarkov.dev item database: fetch once, cache to data/items.json, and provide
name-based matching. This is the authoritative source for item identity, size,
grid layout (for containers) and price.
"""
import concurrent.futures
import json
import os
import re
import urllib.request
from difflib import SequenceMatcher

API = "https://api.tarkov.dev/graphql"
DATA_DIR = os.path.join(os.path.dirname(__file__), "data")
CACHE = os.path.join(DATA_DIR, "items.json")
ICONS = os.path.join(DATA_DIR, "icons")
UA = {"User-Agent": "money2"}

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
    gridImageLink
    sellFor { priceRUB vendor { name } }
    properties {
      __typename
      ... on ItemPropertiesChestRig { capacity grids { width height } }
      ... on ItemPropertiesBackpack { capacity grids { width height } }
      ... on ItemPropertiesContainer { capacity grids { width height } }
    }
  }
}
"""


def _fetch():
    req = urllib.request.Request(
        API, data=json.dumps({"query": QUERY}).encode(),
        headers={"Content-Type": "application/json", "User-Agent": "money2"})
    with urllib.request.urlopen(req, timeout=90) as r:
        payload = json.loads(r.read())
    if "errors" in payload:
        raise RuntimeError(payload["errors"])
    return payload["data"]["items"]


def load(refresh=False):
    """Return the item list, fetching + caching on first use."""
    if refresh or not os.path.exists(CACHE):
        os.makedirs(DATA_DIR, exist_ok=True)
        items = _fetch()
        with open(CACHE, "w", encoding="utf-8") as f:
            json.dump(items, f)
        return items
    with open(CACHE, encoding="utf-8") as f:
        return json.load(f)


def icon_path(item):
    return os.path.join(ICONS, item["id"] + ".webp")


def _download_one(item):
    url = item.get("gridImageLink")
    if not url:
        return False
    path = icon_path(item)
    if os.path.exists(path) and os.path.getsize(path) > 0:
        return True
    try:
        with urllib.request.urlopen(urllib.request.Request(url, headers=UA),
                                    timeout=60) as r:
            blob = r.read()
        with open(path, "wb") as f:
            f.write(blob)
        return True
    except Exception:
        return False


def download_icons(items, workers=16):
    """Download every item's grid icon to data/icons/<id>.webp (cached)."""
    os.makedirs(ICONS, exist_ok=True)
    todo = [it for it in items if it.get("gridImageLink")]
    ok = 0
    with concurrent.futures.ThreadPoolExecutor(max_workers=workers) as ex:
        for i, success in enumerate(ex.map(_download_one, todo), 1):
            ok += success
            if i % 500 == 0:
                print(f"  {i}/{len(todo)} ({ok} ok)")
    print(f"icons: {ok}/{len(todo)} present in {ICONS}")
    return ok


def best_price(item):
    """Best realistic sell value: highest vendor offer, else flea avg, else base."""
    offers = [s["priceRUB"] for s in (item.get("sellFor") or []) if s.get("priceRUB")]
    return max(offers) if offers else (item.get("avg24hPrice")
                                       or item.get("basePrice") or 0)


def _norm(s):
    return re.sub(r"[^a-z0-9]", "", (s or "").lower())


class Matcher:
    """Match OCR text to items by short name / name."""

    def __init__(self, items):
        self.items = items
        self.by_short = {}
        self.by_name = {}
        for it in items:
            self.by_short.setdefault(_norm(it.get("shortName")), it)
            self.by_name.setdefault(_norm(it.get("name")), it)

    def match(self, text, threshold=0.82):
        """Return (item, score) for the best match, or (None, 0) if weak.
        Exact short/long name hits score 1.0; otherwise fuzzy on short names.
        Tries a few OCR-confusion variants of the query (e.g. roman 'II' often
        reads as '11') so a digit misread doesn't sink an otherwise exact hit."""
        q = _norm(text)
        if not q or len(q) < 2:
            return None, 0.0
        variants = {q}
        if "11" in q:                 # 'II' misread as '11'
            variants.add(q.replace("11", "ii"))
        for v in variants:            # exact wins on any variant
            if v in self.by_short:
                return self.by_short[v], 1.0
            if v in self.by_name:
                return self.by_name[v], 1.0
        best, score = None, 0.0
        for v in variants:
            for key, it in self.by_short.items():
                if not key:
                    continue
                r = SequenceMatcher(None, v, key).ratio()
                if r > score:
                    best, score = it, r
        return (best, score) if score >= threshold else (None, score)


if __name__ == "__main__":
    items = load()
    print(f"{len(items)} items cached at {CACHE}")
    m = Matcher(items)
    for t in ("L7AWM", "ComTac II", "ULACH", "Defender-2", "RedRebel"):
        it, sc = m.match(t)
        print(f"  {t!r:14} -> {it['name'] if it else '(no match)'} "
              f"[{sc:.2f}]  {best_price(it) if it else 0:,}₽")
