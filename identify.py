"""
Identify an item-icon crop against the hash DB (data/hashes.json).

Candidates are filtered by cell footprint (w, h) when given — this removes
almost all false matches — then ranked by combined Hamming distance
(pHash + dHash + 0.5*aHash) plus a colour L1 term.

Usage:
  python identify.py <crop.png> [--w N --h M]
  python identify.py --selftest [K]     # match K random DB icons against the DB
"""
import json
import os
import random
import sys

import numpy as np
import imagehash

import tarkov
import iconlib

DB_PATH = os.path.join(tarkov.DATA_DIR, "hashes.json")
_DB = None


def _bits(hexstr):
    return imagehash.hex_to_hash(hexstr).hash.flatten().astype(np.uint8)


def db():
    """Load the hash DB once, pre-stacked into numpy arrays for a single
    vectorized scoring pass."""
    global _DB
    if _DB is None:
        raw = json.load(open(DB_PATH, encoding="utf-8"))
        items = raw["items"]
        _DB = {
            "hash_size": raw["hash_size"], "items": items,
            "P": np.stack([_bits(it["p"]) for it in items]),
            "D": np.stack([_bits(it["d"]) for it in items]),
            "A": np.stack([_bits(it["a"]) for it in items]),
            "C": np.array([it["c"] for it in items], dtype=np.int16),
            "W": np.array([it["width"] for it in items]),
            "H": np.array([it["height"] for it in items]),
        }
    return _DB


def identify(img, w=None, h=None, topn=5):
    """img is a whole-item RGB crop. Returns [(distance, item), ...] best first."""
    d = db()
    pr = iconlib.prep(img, w or 1, h or 1)
    qp = imagehash.phash(pr, hash_size=d["hash_size"]).hash.flatten().astype(np.uint8)
    qd = imagehash.dhash(pr, hash_size=d["hash_size"]).hash.flatten().astype(np.uint8)
    qa = imagehash.average_hash(pr, hash_size=d["hash_size"]).hash.flatten().astype(np.uint8)
    qc = np.array(iconlib.color_sig(pr), dtype=np.int16)

    dist = (np.count_nonzero(d["P"] != qp, axis=1)
            + np.count_nonzero(d["D"] != qd, axis=1)
            + 0.5 * np.count_nonzero(d["A"] != qa, axis=1)
            + 4.0 * np.abs(d["C"] - qc).mean(axis=1))

    idx = np.arange(len(dist))
    if w and h:
        mask = (d["W"] == w) & (d["H"] == h)
        if mask.any():
            idx, dist = idx[mask], dist[mask]
    keep = np.argsort(dist)[:topn]
    return [(float(dist[k]), d["items"][idx[k]]) for k in keep]


def selftest(k=20):
    d = db()
    have = [it for it in d["items"]
            if os.path.exists(os.path.join(tarkov.ICONS, it["id"] + ".webp"))]
    sample = random.sample(have, min(k, len(have)))
    hits = 0
    for it in sample:
        img = iconlib.load_icon(os.path.join(tarkov.ICONS, it["id"] + ".webp"))
        res = identify(img, it["width"], it["height"], topn=1)
        ok = bool(res) and res[0][1]["id"] == it["id"]
        hits += ok
        print(f"  [{'OK ' if ok else 'MISS'}] {it['shortName'][:18]:18} -> "
              f"{(res[0][1]['shortName'] if res else '-')[:18]:18} "
              f"(d={res[0][0]:.1f})")
    print(f"\nself-test: {hits}/{len(sample)} exact top-1")


def main():
    if len(sys.argv) >= 2 and sys.argv[1] == "--selftest":
        selftest(int(sys.argv[2]) if len(sys.argv) > 2 else 20)
        return
    if len(sys.argv) < 2:
        print(__doc__)
        return
    w = int(sys.argv[sys.argv.index("--w") + 1]) if "--w" in sys.argv else None
    h = int(sys.argv[sys.argv.index("--h") + 1]) if "--h" in sys.argv else None
    from PIL import Image
    for dist, it in identify(Image.open(sys.argv[1]).convert("RGB"), w, h):
        print(f"  d={dist:7.1f}  {it['shortName']:<18} {it['name']}")


if __name__ == "__main__":
    main()
