"""
Build a perceptual-hash database from the cached grid icons.

For each item: pHash, dHash, aHash (overlay-masked, see iconlib) + an 8x8 colour
signature + its cell footprint (w, h). identify.py filters candidates by
footprint then ranks by combined distance.

Output: data/hashes.json

Usage:
  python build_hashes.py            # downloads icons if missing, then hashes
"""
import json
import os

import tarkov
import iconlib

OUT = os.path.join(tarkov.DATA_DIR, "hashes.json")


def main():
    items = tarkov.load()
    tarkov.download_icons(items)

    db = []
    n = 0
    for it in items:
        path = tarkov.icon_path(it)
        if not os.path.exists(path):
            continue
        try:
            prepped = iconlib.prep(iconlib.load_icon(path),
                                   it["width"], it["height"])
        except Exception as e:
            print("skip", it["id"], e)
            continue
        db.append({"id": it["id"], "name": it["name"],
                   "shortName": it["shortName"],
                   "width": it["width"], "height": it["height"],
                   **iconlib.hashes(prepped)})
        n += 1
        if n % 500 == 0:
            print(f"  hashed {n}")
    json.dump({"hash_size": iconlib.HASH_SIZE, "items": db},
              open(OUT, "w", encoding="utf-8"))
    print(f"Done: {n} items -> {OUT}")


if __name__ == "__main__":
    main()
