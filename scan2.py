"""
Container-aware item extraction -> grouped list.

  OCR headers -> Container{name, rect, type}     (type from the name)
  GRID  : detect cell size per-container, build occupancy, connected-component
          the occupied cells into items (w x h), dimension-filtered icon match
  SLOT  : one small item, match 1x1
  EQUIP : one big item (weapon/armour), match against all sizes

Output: items grouped by container.

Run:  python scan2.py [out/last_scan.png]
"""
import os
import sys
import json
import numpy as np
import cv2
from PIL import Image

import identify
import containers as cont

OUT = os.path.join(os.path.dirname(__file__), "out")
DATA = os.path.join(os.path.dirname(__file__), "data")

GRID_NAMES = {"BACKPACK", "POCKETS", "TACTICAL RIG", "LOOT", "STASH",
              "SPECIAL SLOTS", "SECURED CONTAINER"}
EQUIP_NAMES = {"ON SLING", "ON BACK", "HOLSTER", "SHEATH"}
OCC_STD = 11.0


def ctype(name):
    if name in GRID_NAMES:
        return "GRID"
    if name in EQUIP_NAMES:
        return "EQUIP"
    return "SLOT"


def dark_lines(mask_sum, frac=0.55):
    """Positions where a row/col is mostly dark-border (a gridline)."""
    th = mask_sum.max() * frac
    return [i for i in range(len(mask_sum)) if mask_sum[i] > th]


def group_lines(idxs, cell, tol=0.4):
    """Collapse clusters of adjacent line pixels to single line centers, then
    keep the longest ~cell-spaced run. Returns sorted line centers."""
    if not idxs:
        return []
    centers, run = [], [idxs[0]]
    for i in idxs[1:]:
        if i - run[-1] <= 4:
            run.append(i)
        else:
            centers.append(int(np.mean(run)))
            run = [i]
    centers.append(int(np.mean(run)))
    return centers


def detect_grid(gray, rect, cell_hint=84):
    """Find the cell lattice inside a container rect from its dark border mesh.
    Returns (ox, oy, cell, ncols, nrows) in full-image coords, or None."""
    x0, y0, x1, y1 = rect
    sub = gray[y0:y1, x0:x1]
    if sub.size == 0 or min(sub.shape) < cell_hint:
        return None
    dark = (sub < 50).astype(np.uint8)
    vlines = group_lines(dark_lines(dark.sum(0)), cell_hint)
    hlines = group_lines(dark_lines(dark.sum(1)), cell_hint)
    # keep only lines spaced ~cell apart (the grid), from the densest run
    def grid_axis(lines):
        best = []
        for i in range(len(lines)):
            run = [lines[i]]
            for j in range(i + 1, len(lines)):
                gap = lines[j] - run[-1]
                if abs(gap - cell_hint) <= cell_hint * 0.35:
                    run.append(lines[j])
                elif gap > cell_hint * 1.4:
                    break
            if len(run) > len(best):
                best = run
        return best
    vx, hy = grid_axis(vlines), grid_axis(hlines)
    if len(vx) < 2 or len(hy) < 2:
        return None
    cell = int(np.median(np.diff(vx + hy and (np.diff(vx).tolist() + np.diff(hy).tolist()))))
    return (x0 + vx[0], y0 + hy[0], cell, len(vx) - 1, len(hy) - 1)


def extract_grid(gray, pil, rect, name):
    g = detect_grid(gray, rect)
    if not g:
        return []
    ox, oy, cell, nc, nr = g
    occ = np.zeros((nr, nc), bool)
    for r in range(nr):
        for c in range(nc):
            p = gray[oy + r * cell + 8:oy + r * cell + cell - 8,
                     ox + c * cell + 8:ox + c * cell + cell - 8]
            occ[r, c] = p.size and p.std() > OCC_STD
    # connected components -> item bounding boxes
    n, lbl = cv2.connectedComponents(occ.astype(np.uint8), connectivity=4)
    items = []
    for i in range(1, n):
        ys, xs = np.where(lbl == i)
        r0, c0, r1, c1 = ys.min(), xs.min(), ys.max(), xs.max()
        w, h = int(c1 - c0 + 1), int(r1 - r0 + 1)
        crop = pil.crop((ox + c0 * cell + 3, oy + r0 * cell + 3,
                         ox + (c1 + 1) * cell - 3, oy + (r1 + 1) * cell - 3))
        res = identify.identify(crop, w, h, topn=1)
        if res:
            d, it = res[0]
            items.append((it["shortName"], it["id"], w, h, round(d, 1)))
    return items


def extract_single(gray, pil, rect):
    x0, y0, x1, y1 = rect
    p = gray[y0:y1, x0:x1]
    if not p.size or p.std() < OCC_STD:
        return []
    res = identify.identify(pil.crop(rect), topn=1)  # no dimension filter
    if not res:
        return []
    d, it = res[0]
    return [(it["shortName"], it["id"], 0, 0, round(d, 1))]


def main():
    path = sys.argv[1] if len(sys.argv) > 1 else os.path.join(OUT, "last_scan.png")
    pil = Image.open(path).convert("RGB")
    rgb = np.array(pil)
    gray = cv2.cvtColor(rgb, cv2.COLOR_RGB2GRAY)
    H, W = gray.shape

    headers = cont.detect(pil)
    boxes = cont.regions(headers, W, H)  # (name, x0, y0, x1, y1)
    raw = json.load(open(os.path.join(DATA, "items.json"), encoding="utf-8"))
    price_of = {it["id"]: (it.get("avg24hPrice") or it.get("lastLowPrice")
                           or it.get("basePrice") or 0) for it in raw}

    print(f"{len(boxes)} containers\n")
    for name, x0, y0, x1, y1 in boxes:
        t = ctype(name)
        rect = (x0, y0, x1, y1)
        if t == "GRID":
            items = extract_grid(gray, pil, rect, name)
        else:
            items = extract_single(gray, pil, rect)
        if not items:
            continue
        print(f"{name} [{t}]")
        for sn, iid, w, h, d in items:
            dim = f"{w}x{h}" if w else "slot"
            print(f"    {sn:<16} {dim:<5} {price_of.get(iid,0):>9,}  (d={d:.0f})")


if __name__ == "__main__":
    main()
