"""
tarkov.dev item database: fetch once, cache to data/items.json, and provide
name-based matching. This is the authoritative source for item identity, size,
grid layout (for containers) and price.
"""
import json
import os
import re
import urllib.request
from difflib import SequenceMatcher

API = "https://api.tarkov.dev/graphql"
DATA_DIR = os.path.join(os.path.dirname(__file__), "data")
CACHE = os.path.join(DATA_DIR, "items.json")

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
        Exact short/long name hits score 1.0; otherwise fuzzy on short names."""
        q = _norm(text)
        if not q or len(q) < 2:
            return None, 0.0
        if q in self.by_short:
            return self.by_short[q], 1.0
        if q in self.by_name:
            return self.by_name[q], 1.0
        best, score = None, 0.0
        for key, it in self.by_short.items():
            if not key:
                continue
            r = SequenceMatcher(None, q, key).ratio()
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
