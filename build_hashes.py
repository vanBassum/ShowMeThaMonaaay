"""
Build a perceptual-hash database from the cached grid icons.

For each item we store pHash, dHash and aHash (overlay-masked, see iconlib)
plus its cell footprint (w,h). Matching (identify.py) filters candidates by
footprint first, then ranks by combined Hamming distance.

Output: data/hashes.json
"""
import json
import os
import iconlib

DATA = os.path.join(os.path.dirname(__file__), "data")
ICONS = os.path.join(DATA, "icons")


def main():
    items = json.load(open(os.path.join(DATA, "items.json"), encoding="utf-8"))
    db = []
    n = 0
    for it in items:
        path = os.path.join(ICONS, it["id"] + ".webp")
        if not os.path.exists(path):
            continue
        try:
            img = iconlib.load_icon(path)
            prepped = iconlib.prep(img, it["width"], it["height"])
        except Exception as e:
            print("skip", it["id"], e)
            continue
        db.append({
            "id": it["id"],
            "name": it["name"],
            "shortName": it["shortName"],
            "width": it["width"],
            "height": it["height"],
            **iconlib.hashes(prepped),
        })
        n += 1
        if n % 500 == 0:
            print(f"  hashed {n}")
    out = os.path.join(DATA, "hashes.json")
    json.dump({"hash_size": iconlib.HASH_SIZE, "items": db}, open(out, "w"))
    print(f"Done: {n} items -> {out}")


if __name__ == "__main__":
    main()
