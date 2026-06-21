"""
Container-aware scanner (the in-raid pipeline).

  screenshot
    -> OCR container headers (POCKETS / BACKPACK / TACTICAL RIG / LOOT / STASH ...)
    -> for each header, find its cell grid nearby (local grid-line detection, so
       scrolling/position doesn't matter; phases differ per container)
    -> occupancy -> connected occupied cells -> bounding boxes -> dimensions
    -> dimension-filtered icon match (identify) -> price -> sort by RUB/slot

Run:  python scan.py out/last_scan.png
Writes out/scan_overlay.png and prints the item table.
"""
import json
import os
import sys
import numpy as np
import cv2
from PIL import Image

import identify

OUT = os.path.join(os.path.dirname(__file__), "out")
DATA = os.path.join(os.path.dirname(__file__), "data")

# headers that sit above a CELL GRID (not single-item slots like HOLSTER/SLING)
GRID_HEADERS = {"POCKETS", "BACKPACK", "RIG", "STASH", "LOOT", "SECURE",
                "SPECIAL", "SLOTS", "CONTAINER", "EQUIPMENT"}
OCC_STD = 11.0
WEAPON_TYPES = {"gun", "preset"}


def global_cell(gray):
    """Dominant fine grid pitch via autocorrelation of the vertical-edge profile."""
    sx = np.abs(cv2.Sobel(gray.astype(np.float32), cv2.CV_32F, 1, 0))
    col = (sx > 40).sum(0).astype(float)
    c = col - col.mean()
    ac = np.correlate(c, c, "full")[len(c) - 1:]
    return 45 + int(np.argmax(ac[45:120]))


def comb_lines(profile, pitch, frac=0.33):
    """Best evenly-spaced run of grid lines in an edge profile (origin, count)."""
    n = len(profile)
    best_off, best = 0, -1.0
    for off in range(pitch):
        idx = np.arange(off, n, pitch)
        s = profile[idx].sum()
        if s > best:
            best_off, best = off, s
    teeth = np.arange(best_off, n, pitch)
    vals = profile[teeth]
    strong = vals >= vals.max() * frac
    runs, i = [], 0
    while i < len(strong):
        if strong[i]:
            j = i
            while j < len(strong) and strong[j]:
                j += 1
            runs.append((i, j - i))
            i = j
        else:
            i += 1
    if not runs:
        return None, 0
    s, ln = max(runs, key=lambda r: r[1])
    return int(teeth[s]), ln


def grid_phase(gray, region, cell):
    """Find the cell-lattice PHASE inside a region (the gridline positions).
    Items break gridline runs, so we only use the lines to lock the phase, then
    tile the whole region at that phase. Returns (first_x, first_y) or None."""
    x0, y0, x1, y1 = region
    sub = gray[y0:y1, x0:x1].astype(np.float32)
    if sub.size == 0:
        return None
    gx = (np.abs(cv2.Sobel(sub, cv2.CV_32F, 1, 0)) > 40).sum(0).astype(float)
    gy = (np.abs(cv2.Sobel(sub, cv2.CV_32F, 0, 1)) > 40).sum(1).astype(float)
    cx, _ = comb_lines(gx, cell)
    cy, _ = comb_lines(gy, cell)
    if cx is None or cy is None:
        return None
    return x0 + cx, y0 + cy


def tile(region, phase, cell):
    """All cell top-left corners filling region, aligned to the phase."""
    x0, y0, x1, y1 = region
    px, py = phase
    sx = px - cell * ((px - x0) // cell + 1)   # first line <= x0
    sy = py - cell * ((py - y0) // cell + 1)
    xs = [x for x in range(sx, x1 - cell // 2, cell) if x >= x0 - 2]
    ys = [y for y in range(sy, y1 - cell // 2, cell) if y >= y0 - 2]
    return xs, ys


def main():
    path = sys.argv[1] if len(sys.argv) > 1 else os.path.join(OUT, "last_scan.png")
    import ocr as ocrmod
    pil = Image.open(path).convert("RGB")
    rgb = np.array(pil)
    gray = cv2.cvtColor(rgb, cv2.COLOR_RGB2GRAY)
    H, W = gray.shape
    cell = 84  # fixed for 2560x1440 (autocorrelation was unreliable); only positions scroll
    print(f"image {W}x{H}  cell={cell}px")

    headers = [(t.upper(), x, y, w, h) for (t, x, y, w, h) in ocrmod.ocr_words(pil)
               if t.upper() in GRID_HEADERS]
    print(f"grid headers: {[(t, x, y) for t, x, y, _, _ in headers]}")

    raw = json.load(open(os.path.join(DATA, "items.json"), encoding="utf-8"))
    price_of = {it["id"]: (it.get("avg24hPrice") or it.get("lastLowPrice")
                           or it.get("basePrice") or 0) for it in raw}
    types_of = {it["id"]: set(it.get("types") or []) for it in raw}

    # grid sits at a STATIC offset from its header (and scrolls with it)
    DX, DY = -5, 18
    overlay = rgb.copy()
    found = []
    for name, hx, hy, hw, hh in headers:
        ox, oy = hx + DX, hy + DY
        # bottom bound = the next header below this one in the same panel column
        below = [yy for (nm, xx, yy, ww, hh2) in headers
                 if yy > hy + DY and abs(xx - hx) < 4 * cell]
        bottom = min(below) - 6 if below else min(H, oy + 8 * cell)
        right = min(W, ox + 10 * cell)
        for y in range(oy, bottom - cell // 2, cell):
            for x in range(ox, right - cell // 2, cell):
                patch = gray[y + 8:y + cell - 8, x + 8:x + cell - 8]
                occupied = patch.size and patch.std() > OCC_STD
                col = (0, 220, 0) if occupied else (70, 70, 70)
                cv2.rectangle(overlay, (x, y), (x + cell, y + cell), col, 1)
                if occupied:
                    crop = pil.crop((x + 3, y + 3, x + cell - 3, y + cell - 3))
                    res = identify.identify(crop, 1, 1, topn=1)
                    if res:
                        d, it = res[0]
                        found.append({"name": it["shortName"], "id": it["id"],
                                      "dist": round(d, 1),
                                      "price": price_of.get(it["id"], 0),
                                      "container": name})

    Image.fromarray(overlay).save(os.path.join(OUT, "scan_overlay.png"))
    found.sort(key=lambda x: x["price"], reverse=True)
    print(f"\n{'item':<16}{'container':<12}{'price':>10}{'dist':>7}")
    for x in found:
        print(f"{x['name']:<16}{x['container']:<12}{x['price']:>10,}{x['dist']:>7.0f}")
    print(f"\n{len(found)} occupied cells matched -> {OUT}/scan_overlay.png")


if __name__ == "__main__":
    main()
