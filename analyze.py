"""
Full inventory analysis:
  grid -> occupancy -> greedy multi-cell segmentation -> OCR name re-rank
       -> price join -> value-per-slot table + overlay.

Two ideas baked in (user-suggested):
  * Cut everything 1x1; cells that don't match well get merged with neighbours
    and re-matched at the larger footprint. A REAL multi-cell item matches its
    true icon with a low distance; gluing unrelated 1x1s together matches
    nothing well -> an absolute "good match" gate (ACCEPT) decides merges.
  * OCR the name the game prints (top-right of the cell) and use it to re-rank
    the icon hash's top-N candidates -> disambiguates reused icons (keys, etc.).

Usage:
  python analyze.py screenshots/stash.png --cell 84 --origin 1685 273 --cols 10 [--no-ocr]
"""
import json
import os
import sys
import difflib
import numpy as np
import cv2
from PIL import Image, ImageOps

import identify
import griddetect

OUT = os.path.join(os.path.dirname(__file__), "out")
DATA = os.path.join(os.path.dirname(__file__), "data")

GOOD_1x1 = 160      # 1x1 this good & occupied -> standalone item, skip merge search
MERGE_ACCEPT = 196  # a grown footprint must match a real item at least this well
RECORD_CAP = 238    # above this distance the 1x1 match is too unsure -> drop the cell
MAX_W, MAX_H = 6, 3  # largest footprint a single item can be (covers 5x2 weapons)
OCC_STD = 10.0      # per-cell std above this == has real content
MIN_COVER = 0.6     # a grown footprint must have >= this fraction of content cells
WEAPON_TYPES = {"gun", "preset"}  # excluded from the value report (custom builds)


def arg(name, n=1, cast=int):
    if name in sys.argv:
        i = sys.argv.index(name)
        v = [cast(sys.argv[i + 1 + k]) for k in range(n)]
        return v if n > 1 else v[0]
    return None


def std_grid(gray, ox, oy, cell, ncols, nrows):
    """Per-cell pixel std-dev: a proxy for 'this cell has real content'."""
    g = np.zeros((nrows, ncols), float)
    m = max(3, cell // 8)
    for r in range(nrows):
        for c in range(ncols):
            y0, x0 = oy + r * cell + m, ox + c * cell + m
            patch = gray[y0:y0 + cell - 2 * m, x0:x0 + cell - 2 * m]
            if patch.size:
                g[r, c] = patch.std()
    return g


def ocr_rerank(candidates, ocr_text):
    """Re-rank (dist,item) candidates using fuzzy match of OCR text to names."""
    q = "".join(ch for ch in ocr_text.lower() if ch.isalnum())
    if len(q) < 2:
        return candidates[0]
    best, best_score = candidates[0], -1
    for dist, it in candidates:
        for field in (it["shortName"], it["name"]):
            t = "".join(ch for ch in field.lower() if ch.isalnum())
            if not t:
                continue
            ratio = difflib.SequenceMatcher(None, q, t).ratio()
            # also reward substring hits (OCR often truncates: "GoldenSt"->"goldenstar")
            if q in t or t in q:
                ratio = max(ratio, 0.85)
            score = ratio - dist / 2000.0  # icon distance as a mild tiebreaker
            if score > best_score:
                best, best_score = (dist, it), score
    return best if best_score > 0.45 else candidates[0]


# default grid for a 2560x1440 stash screenshot (auto-detect not yet wired in)
GRID = dict(cell=84, ox=1685, oy=273, ncols=10, region_bottom=1030)


def analyze_pil(pil, cell=84, ox=1685, oy=273, ncols=10, region_bottom=1030,
                use_ocr=True):
    """Segment + identify + price a stash screenshot. Returns (items, overlay).
    Each item: r,c,w,h,id,name,full,ocr,dist,price,perslot,weapon."""
    ocrmod = None
    if use_ocr:
        try:
            import ocr as ocrmod
        except Exception:
            ocrmod = None
            use_ocr = False

    pil = pil.convert("RGB")
    gray = cv2.cvtColor(np.array(pil), cv2.COLOR_RGB2GRAY)
    nrows = (region_bottom - oy) // cell

    sgrid = std_grid(gray, ox, oy, cell, ncols, nrows)
    occ = sgrid > OCC_STD
    assigned = np.zeros(occ.shape, bool)

    def coverage(r, c, w, h):
        block = sgrid[r:r + h, c:c + w]
        return float((block > OCC_STD).mean()) if block.size else 0.0

    def crop_cells(r, c, w, h, inset=4):
        x0, y0 = ox + c * cell + inset, oy + r * cell + inset
        x1, y1 = ox + (c + w) * cell - inset, oy + (r + h) * cell - inset
        return pil.crop((x0, y0, x1, y1))

    def name_region(r, c, w):
        # name is right-aligned in the item's top-right cell
        x0 = ox + (c + w) * cell - cell
        y0 = oy + r * cell
        return pil.crop((x0 + 2, y0 + 1, ox + (c + w) * cell, y0 + 22))

    def ocr_prep(crop, scale=6, thr=115):
        g = ImageOps.autocontrast(ImageOps.grayscale(crop), cutoff=2)
        g = g.resize((g.width * scale, g.height * scale), Image.LANCZOS)
        return g.point(lambda p: 255 if p > thr else 0).convert("RGBA")

    items = []

    def record(r, c, w, h, cands):
        chosen = cands[0]
        ocr_text = ""
        if use_ocr:
            try:
                ocr_text = ocrmod.ocr(ocr_prep(name_region(r, c, w)))
            except Exception:
                ocr_text = ""
            chosen = ocr_rerank(cands, ocr_text)
        assigned[r:r + h, c:c + w] = True
        items.append({"r": r, "c": c, "w": w, "h": h,
                      "dist": round(chosen[0], 1),
                      "id": chosen[1]["id"], "name": chosen[1]["shortName"],
                      "full": chosen[1]["name"], "ocr": ocr_text})

    # Greedy region growing, row-major so an item's top-left cell anchors it.
    # At each anchor we TRY EVERY rectangular footprint (items are rectangles) and
    # keep only the ones that match a real item well. We then pick the LOWEST-
    # distance match (tie-break: larger area). Because a "two Lions" 6x2 crop
    # matches no real item, only the single 3x2 wins -> adjacent identical items
    # stay separate. The merge fires when a bigger footprint matches BETTER than
    # the cell's own 1x1 -- which is the reliable signal, not per-cell certainty.
    for r in range(nrows):
        for c in range(ncols):
            if assigned[r, c]:
                continue
            cands1 = identify.identify(crop_cells(r, c, 1, 1), 1, 1, topn=8)
            d1 = cands1[0][0]
            options = []  # (dist, area, w, h, cands)
            if occ[r, c] and d1 < RECORD_CAP:
                options.append((d1, 1, 1, 1, cands1))
            # grow into multi-cell footprints unless the 1x1 is already a clean hit
            if not (occ[r, c] and d1 < GOOD_1x1):
                for h in range(1, MAX_H + 1):
                    for w in range(1, MAX_W + 1):
                        if (w == 1 and h == 1) or r + h > nrows or c + w > ncols:
                            continue
                        if assigned[r:r + h, c:c + w].any():
                            continue  # don't steal another item's cells
                        if coverage(r, c, w, h) < MIN_COVER:
                            continue
                        cand = identify.identify(crop_cells(r, c, w, h), w, h, topn=8)
                        if cand[0][0] < MERGE_ACCEPT:
                            options.append((cand[0][0], w * h, w, h, cand))
            if not options:
                continue  # empty gap / nothing matches well -> leave unassigned
            dmin = min(o[0] for o in options)
            _, _, w, h, cands = max((o for o in options if o[0] <= dmin + 8),
                                    key=lambda o: o[1])
            record(r, c, w, h, cands)

    # prices (PvE flea avg) + types
    raw = json.load(open(os.path.join(DATA, "items.json"), encoding="utf-8"))
    price_of = {it["id"]: (it.get("avg24hPrice") or it.get("lastLowPrice")
                           or it.get("basePrice") or 0) for it in raw}
    types_of = {it["id"]: set(it.get("types") or []) for it in raw}

    overlay = np.array(pil).copy()
    for x in items:
        slots = x["w"] * x["h"]
        x["price"] = price_of.get(x["id"], 0)
        x["perslot"] = x["price"] // slots
        x["weapon"] = bool(types_of.get(x["id"], set()) & WEAPON_TYPES)
        x["icon"] = os.path.join(DATA, "icons", x["id"] + ".webp")
        x0, y0 = ox + x["c"] * cell, oy + x["r"] * cell
        x1, y1 = ox + (x["c"] + x["w"]) * cell, oy + (x["r"] + x["h"]) * cell
        col = (120, 120, 120) if x["weapon"] else (0, 220, 0)
        cv2.rectangle(overlay, (x0, y0), (x1, y1), col, 2)
        tag = (x["name"] + " [gun]") if x["weapon"] else x["name"]
        cv2.putText(overlay, tag[:13], (x0 + 2, y0 + 15),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.4, (60, 255, 255), 1, cv2.LINE_AA)
    return items, overlay


def main():
    if len(sys.argv) < 2:
        print(__doc__)
        return
    use_ocr = "--no-ocr" not in sys.argv
    g = dict(GRID)
    if arg("--cell"):
        g["cell"] = arg("--cell")
    if arg("--origin", 2):
        g["ox"], g["oy"] = arg("--origin", 2)
    if arg("--cols"):
        g["ncols"] = arg("--cols")
    if arg("--bottom"):
        g["region_bottom"] = arg("--bottom")

    os.makedirs(OUT, exist_ok=True)
    pil = Image.open(sys.argv[1])
    items, overlay = analyze_pil(pil, g["cell"], g["ox"], g["oy"], g["ncols"],
                                 g["region_bottom"], use_ocr)
    Image.fromarray(overlay).save(os.path.join(OUT, "overlay.png"))
    json.dump(items, open(os.path.join(OUT, "items.json"), "w"))

    shown = sorted((x for x in items if not x["weapon"]),
                   key=lambda x: x["perslot"], reverse=True)
    guns = [x for x in items if x["weapon"]]
    print(f"\n{'pos':<7}{'item':<17}{'WxH':<5}{'RUB/slot':>11}{'total':>11}  ocr")
    grand = 0
    for x in shown:
        grand += x["price"]
        ocrtag = f'  ~{x["ocr"]}' if x["ocr"] else ""
        wh = f"{x['w']}x{x['h']}"
        pos = f"r{x['r']}c{x['c']}"
        print(f"{pos:<7}{x['name']:<17}{wh:<5}{x['perslot']:>11,}{x['price']:>11,}{ocrtag}")
    print(f"\n{len(shown)} items | est. total ~{grand:,} RUB (PvE flea, guns excluded) "
          f"| {len(guns)} weapon(s) skipped -> {OUT}/overlay.png")


if __name__ == "__main__":
    main()
