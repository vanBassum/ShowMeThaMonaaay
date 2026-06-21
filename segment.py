"""
Segment a Tarkov stash screenshot into cells, identify each occupied cell, and
report. Emits out/overlay.png so we can see how it did.

Usage:
  python segment.py screenshots/stash.png
  python segment.py screenshots/stash.png --region 1680 250 2545 990
  python segment.py screenshots/stash.png --cell 84 --origin 1685 273 --cols 10

Approach (v1): per-cell identification. The stash grid is found from the
periodicity of its gridlines inside the stash region; each occupied cell is
matched as a 1x1 icon. Multi-cell items (guns/armor) therefore show up as a few
adjacent cells -- connected components are reported so we can see those blobs.
Multi-cell reconstruction is the next iteration.
"""
import json
import os
import sys
import numpy as np
import cv2
from PIL import Image

import identify

OUT = os.path.join(os.path.dirname(__file__), "out")


def arg(name, n=1, cast=int):
    if name in sys.argv:
        i = sys.argv.index(name)
        vals = [cast(sys.argv[i + 1 + k]) for k in range(n)]
        return vals if n > 1 else vals[0]
    return None


def gridlines(sig, mind, maxn):
    """Greedy non-max-suppressed peaks of an edge-energy signal."""
    idx = []
    for i in np.argsort(sig)[::-1]:
        if all(abs(i - j) > mind for j in idx):
            idx.append(int(i))
        if len(idx) > maxn:
            break
    return sorted(idx)


def detect_grid(gray, region):
    """Return (origin_x, origin_y, cell, ncols, nrows) within region."""
    x0, y0, x1, y1 = region
    sub = gray[y0:y1, x0:x1].astype(np.float32)
    gx = np.abs(cv2.Sobel(sub, cv2.CV_32F, 1, 0)).mean(axis=0)
    gy = np.abs(cv2.Sobel(sub, cv2.CV_32F, 0, 1)).mean(axis=1)
    cols = gridlines(gx, mind=60, maxn=14)
    rows = gridlines(gy, mind=60, maxn=14)
    # cell pitch = median spacing between detected lines
    pitch = int(np.median(np.diff(cols + rows and sorted(set(np.diff(cols).tolist()
              + np.diff(rows).tolist())))) ) if False else None
    diffs = np.diff(cols).tolist() + np.diff(rows).tolist()
    cell = int(round(np.median([d for d in diffs if 40 < d < 140])))
    ox = x0 + cols[0]
    oy = y0 + rows[0]
    ncols = round((cols[-1] - cols[0]) / cell)
    return ox, oy, cell, ncols, region


def occupancy(gray, ox, oy, cell, ncols, nrows, thresh=12.0):
    occ = np.zeros((nrows, ncols), bool)
    m = max(3, cell // 8)
    for r in range(nrows):
        for c in range(ncols):
            y0, x0 = oy + r * cell + m, ox + c * cell + m
            patch = gray[y0:y0 + cell - 2 * m, x0:x0 + cell - 2 * m]
            if patch.size and patch.std() > thresh:
                occ[r, c] = True
    return occ


def main():
    if len(sys.argv) < 2:
        print(__doc__)
        return
    path = sys.argv[1]
    os.makedirs(OUT, exist_ok=True)
    pil = Image.open(path).convert("RGB")
    rgb = np.array(pil)
    gray = cv2.cvtColor(rgb, cv2.COLOR_RGB2GRAY)
    H, W = gray.shape

    region = arg("--region", 4) or [1680, 250, 2545, 990]
    if arg("--cell"):
        cell = arg("--cell")
        ox, oy = arg("--origin", 2)
        ncols = arg("--cols")
    else:
        ox, oy, cell, ncols, region = detect_grid(gray, region)
    nrows = (region[3] - oy) // cell
    print(f"image {W}x{H}  region={region}  cell={cell}px  origin=({ox},{oy})  grid={ncols}x{nrows}")

    occ = occupancy(gray, ox, oy, cell, ncols, nrows)
    print(f"occupied cells: {int(occ.sum())}/{occ.size}")

    # connected components just for reporting blob structure
    n_comp, lbl = cv2.connectedComponents(occ.astype(np.uint8), connectivity=4)

    # price lookup by item id (flea avg, falling back to trader base)
    items = json.load(open(os.path.join(os.path.dirname(__file__), "data", "items.json"),
                           encoding="utf-8"))
    price_of = {it["id"]: (it.get("avg24hPrice") or it.get("basePrice") or 0) for it in items}

    overlay = rgb.copy()
    inset = 4
    results = []
    for r in range(nrows):
        for c in range(ncols):
            if not occ[r, c]:
                continue
            x0, y0 = ox + c * cell + inset, oy + r * cell + inset
            crop = pil.crop((x0, y0, x0 + cell - 2 * inset, y0 + cell - 2 * inset))
            res = identify.identify(crop, 1, 1, topn=1)
            if res:
                dist, it = res[0]
                name, iid, price = it["shortName"], it["id"], price_of.get(it["id"], 0)
            else:
                name, iid, price, dist = "?", None, 0, 999
            results.append({"r": r, "c": c, "name": name, "id": iid,
                            "dist": round(dist, 1), "price": price, "blob": int(lbl[r, c])})
            cv2.rectangle(overlay, (ox + c * cell, oy + r * cell),
                          (ox + (c + 1) * cell, oy + (r + 1) * cell), (0, 200, 0), 1)
            cv2.putText(overlay, name[:9], (ox + c * cell + 2, oy + r * cell + 14),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.36, (60, 255, 255), 1, cv2.LINE_AA)

    Image.fromarray(overlay).save(os.path.join(OUT, "overlay.png"))
    json.dump(results, open(os.path.join(OUT, "cells.json"), "w"))

    # value-per-slot table (each cell = 1 slot in this v1 per-cell pass)
    results.sort(key=lambda x: x["price"], reverse=True)
    print(f"\n{'cell':<7}{'item':<16}{'RUB/slot':>11}  {'dist':>5}")
    total = 0
    for x in results:
        total += x["price"]
        print(f"r{x['r']}c{x['c']:<4}{x['name']:<16}{x['price']:>11,}  {x['dist']:>5.0f}")
    print(f"\n{len(results)} occupied cells | est. total ~{total:,} RUB "
          f"(flea avg) -> {OUT}/overlay.png")


if __name__ == "__main__":
    main()
