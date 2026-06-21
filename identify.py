"""
Match a single item-icon image against the hash DB.

Usage:
  python identify.py <image.png> [--w N --h M]   # identify one crop
  python identify.py --selftest [K]              # sanity check on K random icons

Footprint (--w/--h) is optional but strongly recommended: filtering candidates
to the same cell shape removes almost all false matches.
"""
import json
import os
import sys
import random
import numpy as np
import imagehash
from PIL import Image

import iconlib

DATA = os.path.join(os.path.dirname(__file__), "data")
ICONS = os.path.join(DATA, "icons")
_DB = None


def _bits(hexstr):
    """Flatten an imagehash hex string to a 1D uint8 bit array."""
    return imagehash.hex_to_hash(hexstr).hash.flatten().astype(np.uint8)


def db():
    """Load the hash DB once and pre-stack everything into numpy arrays so a
    query scores all candidates in a single vectorized pass (no Python loop)."""
    global _DB
    if _DB is None:
        raw = json.load(open(os.path.join(DATA, "hashes.json")))
        items = raw["items"]
        _DB = {
            "hash_size": raw["hash_size"],
            "items": items,
            "P": np.stack([_bits(it["p"]) for it in items]),
            "D": np.stack([_bits(it["d"]) for it in items]),
            "A": np.stack([_bits(it["a"]) for it in items]),
            "C": np.array([it["c"] for it in items], dtype=np.int16),
            "W": np.array([it["width"] for it in items]),
            "H": np.array([it["height"] for it in items]),
        }
    return _DB


def load_rgb(path):
    return iconlib.load_icon(path)


def identify(img, w=None, h=None, topn=5):
    d = db()
    prepped = iconlib.prep(img, w or 1, h or 1)
    qp = imagehash.phash(prepped, hash_size=d["hash_size"]).hash.flatten().astype(np.uint8)
    qd = imagehash.dhash(prepped, hash_size=d["hash_size"]).hash.flatten().astype(np.uint8)
    qa = imagehash.average_hash(prepped, hash_size=d["hash_size"]).hash.flatten().astype(np.uint8)
    qc = np.array(iconlib.color_sig(prepped), dtype=np.int16)

    # vectorized distance over all candidates: Hamming (pHash/dHash/aHash) +
    # color L1 (per-channel mean, weighted up because colour discriminates well)
    dist = (np.count_nonzero(d["P"] != qp, axis=1)
            + np.count_nonzero(d["D"] != qd, axis=1)
            + 0.5 * np.count_nonzero(d["A"] != qa, axis=1)
            + 4.0 * np.abs(d["C"] - qc).mean(axis=1))

    idx = np.arange(len(dist))
    if w and h:
        mask = (d["W"] == w) & (d["H"] == h)
        if mask.any():
            idx = idx[mask]
            dist = dist[mask]

    items = d["items"]
    keep = np.argsort(dist)[:topn]  # positions into the (possibly filtered) arrays
    return [(float(dist[k]), items[idx[k]]) for k in keep]


def selftest(k=15):
    d = db()
    items = [it for it in d["items"]
             if os.path.exists(os.path.join(ICONS, it["id"] + ".webp"))]
    sample = random.sample(items, min(k, len(items)))
    hits = 0
    for it in sample:
        img = load_rgb(os.path.join(ICONS, it["id"] + ".webp"))
        res = identify(img, it["width"], it["height"], topn=1)
        ok = res and res[0][1]["id"] == it["id"]
        hits += ok
        flag = "OK " if ok else "MISS"
        got = res[0][1]["shortName"] if res else "-"
        print(f"  [{flag}] {it['shortName']:<18} -> {got:<18} (d={res[0][0]:.1f})")
    print(f"\nself-test: {hits}/{len(sample)} exact top-1")


def main():
    if len(sys.argv) >= 2 and sys.argv[1] == "--selftest":
        k = int(sys.argv[2]) if len(sys.argv) > 2 else 15
        selftest(k)
        return
    if len(sys.argv) < 2:
        print(__doc__)
        return
    path = sys.argv[1]
    w = h = None
    if "--w" in sys.argv:
        w = int(sys.argv[sys.argv.index("--w") + 1])
    if "--h" in sys.argv:
        h = int(sys.argv[sys.argv.index("--h") + 1])
    for dist, it in identify(load_rgb(path), w, h):
        print(f"  d={dist:7.1f}  {it['shortName']:<18} {it['name']}")


if __name__ == "__main__":
    main()
