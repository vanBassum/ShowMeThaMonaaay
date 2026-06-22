"""
Auto-label real item crops for classifier fine-tuning -- no manual work.

For each detected box on a screenshot:
  * OCR the item name the game prints on the crop,
  * fuzzy-match it against the classifier's top-K candidates,
  * if OCR and the classifier AGREE on an item, save the crop as a real,
    high-precision training example under data/labeled/<id>/.

The agreement cross-check is the trick: OCR alone is noisy and the classifier
alone is under-confident, but where they concur the label is trustworthy. Crops
where they don't agree are skipped (left for manual review / a later pass).

Run:  python autolabel.py "test screenshot 1.png" [more.png ...]
"""
import os
import sys
import difflib
import numpy as np
import cv2
from PIL import Image

import detect_items as D
import cls
import ocr as ocrmod

LABELED = os.path.join(D.DATA, "labeled")


def norm(s):
    return "".join(c for c in s.lower() if c.isalnum())


def match(ocr_text, cands):
    """Return the candidate item whose name agrees with OCR text, else None.
    cands = [(item, prob)] from the classifier (top-K)."""
    q = norm(ocr_text)
    if len(q) < 2:
        return None
    best, best_r = None, 0.0
    for it, _ in cands:
        for field in (it["shortName"], it["name"]):
            t = norm(field)
            if not t:
                continue
            r = difflib.SequenceMatcher(None, q, t).ratio()
            if q in t or t in q:
                r = max(r, 0.9)
            if r > best_r:
                best, best_r = it, r
    return best if best_r >= 0.7 else None


def autolabel(path):
    pil = Image.open(path).convert("RGB")
    gray = cv2.cvtColor(np.array(pil), cv2.COLOR_RGB2GRAY)
    W, H = pil.size
    dets = D.nms(D.tiled_detect(D.get_model(), pil, 0.25))
    dets = [d for d in dets if D.keep_box(gray, *d[:4], W, H)]
    stem = os.path.splitext(os.path.basename(path))[0]
    saved = 0
    for j, (x0, y0, x1, y1, sc) in enumerate(dets):
        crop = pil.crop((int(x0), int(y0), int(x1), int(y1)))
        ba = (x1 - x0) / max(1.0, (y1 - y0))
        cands = cls.classify(crop, topn=10, box_aspect=ba)
        text = ocrmod.ocr(ocrmod.prep(crop))
        it = match(text, cands)
        if not it:
            continue
        d = os.path.join(LABELED, it["id"])
        os.makedirs(d, exist_ok=True)
        crop.save(os.path.join(d, f"{stem}_{j:03d}.png"))
        saved += 1
        print(f"  [{it['shortName']:<16}] ~ocr='{text.strip()[:18]}'")
    print(f"{os.path.basename(path)}: auto-labeled {saved}/{len(dets)} crops")
    return saved


def main():
    paths = [a for a in sys.argv[1:] if not a.startswith("--")]
    if not paths:
        print(__doc__)
        return
    total = sum(autolabel(p) for p in paths)
    n_items = len(os.listdir(LABELED)) if os.path.exists(LABELED) else 0
    print(f"\ntotal {total} crops -> data/labeled/ ({n_items} item folders)")


if __name__ == "__main__":
    main()
