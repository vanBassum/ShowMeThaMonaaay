"""
Find ALL items visible on screen, regardless of where they are.

Baseline (no ML): OCR container headers -> per-container box (detectors) ->
detect the cell grid inside each GRID box (gridfinder) -> occupancy ->
connected components -> identify each blob; SLOT/EQUIP boxes are matched whole.
Outputs ONE flat list of every item found + an overlay.

This is the "no-train" half of the YOLO experiment: it tells us whether the
hard part is FINDING items (boxes) or NAMING them (hash DB).

Run:  python findall.py "test screenshot 1.png"
"""
import os
import sys
import json
import numpy as np
import cv2
from PIL import Image

import identify
import containers as cont
import detectors
import gridfinder

OUT = os.path.join(os.path.dirname(__file__), "out")
DATA = os.path.join(os.path.dirname(__file__), "data")
OCC_STD = 11.0


def grid_items(gray, pil, box):
    """Detect the lattice in a GRID box and identify each occupied blob."""
    g = gridfinder.find(gray, box)
    if not g:
        return []
    ox, oy, cell, nc, nr = g
    if nc < 1 or nr < 1:
        return []
    occ = np.zeros((nr, nc), bool)
    for r in range(nr):
        for c in range(nc):
            p = gray[oy + r * cell + 8:oy + r * cell + cell - 8,
                     ox + c * cell + 8:ox + c * cell + cell - 8]
            occ[r, c] = bool(p.size) and p.std() > OCC_STD
    n, lbl = cv2.connectedComponents(occ.astype(np.uint8), connectivity=4)
    out = []
    for i in range(1, n):
        ys, xs = np.where(lbl == i)
        r0, c0, r1, c1 = ys.min(), xs.min(), ys.max(), xs.max()
        w, h = int(c1 - c0 + 1), int(r1 - r0 + 1)
        crop = pil.crop((ox + c0 * cell + 3, oy + r0 * cell + 3,
                         ox + (c1 + 1) * cell - 3, oy + (r1 + 1) * cell - 3))
        res = identify.identify(crop, w, h, topn=1)
        if res:
            d, it = res[0]
            out.append((it, w, h, round(float(d), 1),
                        (ox + c0 * cell, oy + r0 * cell,
                         ox + (c1 + 1) * cell, oy + (r1 + 1) * cell)))
    return out


def slot_item(gray, pil, box):
    """Match a single equipment/slot box whole (no dimension filter)."""
    x0, y0, x1, y1 = box
    p = gray[y0:y1, x0:x1]
    if not p.size or p.std() < OCC_STD:
        return []
    res = identify.identify(pil.crop(box), topn=1)
    if not res:
        return []
    d, it = res[0]
    return [(it, 0, 0, round(float(d), 1), box)]


def main():
    path = sys.argv[1] if len(sys.argv) > 1 else "test screenshot 1.png"
    pil = Image.open(path).convert("RGB")
    rgb = np.array(pil)
    gray = cv2.cvtColor(rgb, cv2.COLOR_RGB2GRAY)
    H, W = gray.shape

    headers = cont.detect(pil)
    boxes = detectors.detect_all(headers, gray, W, H)

    raw = json.load(open(os.path.join(DATA, "items.json"), encoding="utf-8"))
    price_of = {it["id"]: (it.get("avg24hPrice") or it.get("lastLowPrice")
                           or it.get("basePrice") or 0) for it in raw}

    print(f"{len(headers)} headers -> {len(boxes)} containers\n")
    found = []  # (name_or_short, container, w, h, dist, price, box)
    for cname, box, t in boxes:
        items = grid_items(gray, pil, box) if t == "GRID" else slot_item(gray, pil, box)
        for it, w, h, d, ibox in items:
            found.append((it["shortName"], cname, w, h, d, price_of.get(it["id"], 0), ibox))

    found.sort(key=lambda x: x[5], reverse=True)
    print(f"{'item':<18}{'from':<16}{'WxH':<6}{'dist':>6}{'price':>11}")
    print("-" * 57)
    total = 0
    for sn, cname, w, h, d, price, _ in found:
        total += price
        dim = f"{w}x{h}" if w else "slot"
        print(f"{sn:<18}{cname:<16}{dim:<6}{d:>6.0f}{price:>11,}")
    print("-" * 57)
    print(f"{len(found)} items found | est. total ~{total:,} RUB")

    overlay = rgb.copy()
    for sn, cname, w, h, d, price, (x0, y0, x1, y1) in found:
        cv2.rectangle(overlay, (x0, y0), (x1, y1), (0, 220, 0), 2)
        cv2.putText(overlay, sn[:14], (x0 + 2, y0 + 15),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.4, (60, 255, 255), 1, cv2.LINE_AA)
    os.makedirs(OUT, exist_ok=True)
    Image.fromarray(overlay).save(os.path.join(OUT, "findall.png"))
    print(f"-> {OUT}/findall.png")


if __name__ == "__main__":
    main()
