"""
Compare classification methods per detected crop, and fuse them.

Four independent signals name each item; their AGREEMENT gives the most probable
answer (and high-precision labels to train the CNN further):

  CNN    - the trained classifier (cls.py)            -> top-K by prob
  OCR    - the name the game prints (ocr.py)           -> fuzzy match to DB
  pHash  - perceptual-hash global similarity           -> top-K by 1-hamming
  ORB    - ORB local-feature inliers (verifier)        -> re-ranks the shortlist

Each method scores candidates in [0,1]; a weighted vote picks the consensus.

Run:  python compare.py "test screenshot 1.png" [--save]   (--save writes
      consensus crops to data/labeled/ when >=2 methods agree)
"""
import os
import sys
import json
import difflib
import numpy as np
import cv2
import imagehash
from PIL import Image

import detect_items as D
import cls
import ocr as ocrmod

DATA = D.DATA
ICONS = os.path.join(DATA, "icons")
LABELED = os.path.join(DATA, "labeled")
NORM = 64
WEIGHTS = {"cnn": 1.0, "ocr": 1.2, "phash": 0.8, "orb": 0.8}
_PH = None
_ORB = cv2.ORB_create(nfeatures=300)


def norm_alnum(s):
    return "".join(c for c in s.lower() if c.isalnum())


def prep_match(img):
    """64x64, mask the name strip (top) + count corner (br) so the crop's
    overlays don't fight the clean DB icon."""
    g = img.convert("RGB").resize((NORM, NORM))
    px = g.load()
    for y in range(11):
        for x in range(NORM):
            px[x, y] = (25, 25, 25)
    for y in range(NORM - 14, NORM):
        for x in range(NORM - 20, NORM):
            px[x, y] = (25, 25, 25)
    return g


def phash_db():
    """Cache (ids, phash-bit-matrix) over all icons once."""
    global _PH
    if _PH is None:
        ids, bits = [], []
        for it in cls.model()["meta"]:
            p = os.path.join(ICONS, it["id"] + ".webp")
            if not os.path.exists(p):
                continue
            try:
                h = imagehash.phash(prep_match(Image.open(p)), hash_size=16)
            except Exception:
                continue
            ids.append(it["id"])
            bits.append(h.hash.flatten())
        _PH = {"ids": ids, "bits": np.array(bits, bool),
               "byid": {it["id"]: it for it in cls.model()["meta"]}}
    return _PH


def cnn_scores(crop, aspect, k=10):
    return {it["id"]: p for it, p in cls.classify(crop, topn=k, box_aspect=aspect)}


def phash_scores(crop, k=10):
    db = phash_db()
    q = imagehash.phash(prep_match(crop), hash_size=16).hash.flatten()
    dist = np.count_nonzero(db["bits"] != q, axis=1)
    order = np.argsort(dist)[:k]
    nbits = db["bits"].shape[1]
    return {db["ids"][i]: 1.0 - dist[i] / nbits for i in order}


def ocr_scores(crop, allitems):
    text = ocrmod.ocr(ocrmod.prep(crop))
    q = norm_alnum(text)
    if len(q) < 2:
        return {}, ""
    out = {}
    for it in allitems:
        r = max(difflib.SequenceMatcher(None, q, norm_alnum(it["shortName"])).ratio(),
                difflib.SequenceMatcher(None, q, norm_alnum(it["name"])).ratio())
        if q in norm_alnum(it["name"]) or norm_alnum(it["shortName"]) in q:
            r = max(r, 0.9)
        if r >= 0.6:
            out[it["id"]] = r
    return out, text.strip()


def orb_score(crop, icon_path):
    """ORB inlier ratio between crop and an icon (0..1). Verifier only."""
    try:
        a = cv2.cvtColor(np.array(crop.resize((96, 96))), cv2.COLOR_RGB2GRAY)
        b = cv2.cvtColor(np.array(Image.open(icon_path).convert("RGB").resize((96, 96))),
                         cv2.COLOR_RGB2GRAY)
    except Exception:
        return 0.0
    k1, d1 = _ORB.detectAndCompute(a, None)
    k2, d2 = _ORB.detectAndCompute(b, None)
    if d1 is None or d2 is None or len(k1) < 8 or len(k2) < 8:
        return 0.0
    bf = cv2.BFMatcher(cv2.NORM_HAMMING, crossCheck=True)
    good = [m for m in bf.match(d1, d2) if m.distance < 64]
    return len(good) / max(8, min(len(k1), len(k2)))


def fuse(crop, aspect):
    """Run all methods, return (ranked [(item, combined, per_method)], ocr_text)."""
    byid = phash_db()["byid"]
    allitems = list(byid.values())
    cnn = cnn_scores(crop, aspect)
    ph = phash_scores(crop)
    oc, text = ocr_scores(crop, allitems)
    shortlist = set(cnn) | set(ph) | set(oc)
    orb = {i: orb_score(crop, os.path.join(ICONS, i + ".webp")) for i in shortlist}
    rows = []
    for i in shortlist:
        per = {"cnn": cnn.get(i, 0.0), "ocr": oc.get(i, 0.0),
               "phash": ph.get(i, 0.0), "orb": orb.get(i, 0.0)}
        combined = sum(WEIGHTS[m] * per[m] for m in per)
        rows.append((byid[i], combined, per))
    rows.sort(key=lambda r: r[1], reverse=True)
    return rows, text


def agree_count(per, thr=0.45):
    return sum(1 for m, v in per.items() if v >= thr)


def main():
    paths = [a for a in sys.argv[1:] if not a.startswith("--")]
    save = "--save" in sys.argv
    if not paths:
        print(__doc__)
        return
    phash_db()  # warm cache
    for path in paths:
        pil = Image.open(path).convert("RGB")
        gray = cv2.cvtColor(np.array(pil), cv2.COLOR_RGB2GRAY)
        W, H = pil.size
        dets = D.nms(D.tiled_detect(D.get_model(), pil, 0.25))
        dets = [d for d in dets if D.keep_box(gray, *d[:4], W, H)]
        print(f"\n=== {os.path.basename(path)}: {len(dets)} crops ===")
        print(f"{'CNN':<14}{'OCR':<14}{'pHash':<14}{'ORB':<14}{'=CONSENSUS':<16}{'agree'}")
        stem = os.path.splitext(os.path.basename(path))[0]
        saved = 0
        for j, (x0, y0, x1, y1, sc) in enumerate(dets):
            crop = pil.crop((int(x0), int(y0), int(x1), int(y1)))
            aspect = (x1 - x0) / max(1.0, (y1 - y0))
            rows, text = fuse(crop, aspect)
            if not rows:
                continue
            top, comb, per = rows[0]

            def best(m):
                r = max(rows, key=lambda r: r[2][m])
                return f"{r[0]['shortName'][:11]}{'' if r[2][m] else '-'}" if r[2][m] else "-"
            na = agree_count(per)
            print(f"{best('cnn'):<14}{best('ocr'):<14}{best('phash'):<14}"
                  f"{best('orb'):<14}{top['shortName'][:14]:<16}{na}/4")
            if save and na >= 2:
                d = os.path.join(LABELED, top["id"])
                os.makedirs(d, exist_ok=True)
                crop.save(os.path.join(d, f"{stem}_{j:03d}.png"))
                saved += 1
        if save:
            print(f"saved {saved} consensus crops -> data/labeled/")


if __name__ == "__main__":
    main()
