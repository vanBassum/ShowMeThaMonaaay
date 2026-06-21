"""
Locate the containers/slots on screen and draw a clean labelled map.

Pure header-based (your idea): OCR line text gives each container's name + box;
we cluster headers into panel columns and give each container the region from
its header down to the next header in the same column. No grid/line detection.

Run:  python containers.py [out/last_scan.png]  ->  out/containers.png
"""
import os
import sys
import difflib
import numpy as np
import cv2
from PIL import Image

import ocr as ocrmod

OUT = os.path.join(os.path.dirname(__file__), "out")

NAMES = ["EARPIECE", "HEADWEAR", "FACE COVER", "ARMBAND", "BODY ARMOR", "EYEWEAR",
         "DOGTAG", "ON SLING", "ON BACK", "HOLSTER", "SHEATH", "TACTICAL RIG",
         "POCKETS", "BACKPACK", "SPECIAL SLOTS", "SECURED CONTAINER", "STASH",
         "LOOT", "SCABBARD", "POUCH"]


def match_name(text):
    u = text.upper().strip()
    if u in NAMES:
        return u
    m = difflib.get_close_matches(u, NAMES, n=1, cutoff=0.82)
    return m[0] if m else None


def detect(pil):
    """Return [(name, x, y, w, h)] for every container header found."""
    out = []
    for text, x, y, w, h in ocrmod.ocr_lines(pil):
        name = match_name(text)
        if name:
            out.append((name, x, y, w, h))
    return out


GRID_NAMES = {"BACKPACK", "POCKETS", "TACTICAL RIG", "LOOT", "STASH",
              "SPECIAL SLOTS", "SECURED CONTAINER"}
EQUIP_NAMES = {"ON SLING", "ON BACK", "HOLSTER", "SHEATH"}


def ctype(name):
    if name in GRID_NAMES:
        return "GRID"
    if name in EQUIP_NAMES:
        return "EQUIP"
    return "SLOT"


def panel_bounds(gray):
    """Vertical panel-gutter x positions: very dark full-height columns that
    separate the equipment / your-gear / loot panels."""
    band = gray[200:1000, :].astype(float).mean(0)
    guts = []
    for i in np.argsort(band):
        if band[i] > 12:
            break
        if all(abs(i - j) > 150 for j in guts):
            guts.append(int(i))
    return sorted(guts)


def regions(headers, W, H, gray=None, cell=84):
    """Bound each container by its ADJACENT headers, sized by type:
       right edge = nearest header to the right that vertically overlaps,
       clamped to the next panel gutter so boxes never cross panels."""
    guts = panel_bounds(gray) if gray is not None else []
    out = []
    for name, hx, hy, hw, hh in headers:
        gut_right = min([g for g in guts if g > hx + 40] + [W])
        t = ctype(name)
        # nearest header to the right (same row) -- but not across a panel gutter
        rights = [x2 for (n2, x2, y2, w2, h2) in headers
                  if hx + 30 < x2 < gut_right and abs(y2 - hy) < cell // 2]
        # nearest header below whose x-band overlaps this container
        belows = [y2 for (n2, x2, y2, w2, h2) in headers
                  if y2 > hy + 30 and x2 < hx + 6 * cell and x2 + 40 > hx - 12]

        if t == "SLOT":     # small fixed equipment slot (~2x2 cells)
            right = hx + 2 * cell + 20
            bottom = hy + 2 * cell + 30
        elif t == "EQUIP":  # weapon/knife slot, wide (clamp to panel gutter)
            right = (min(rights) - 14) if rights else min(gut_right - 8, hx + 6 * cell)
            bottom = (min(belows) - 8) if belows else min(H - 4, hy + 3 * cell)
        else:               # GRID: extend to neighbours/gutter, cap height
            right = (min(rights) - 14) if rights else min(gut_right - 8, hx + 9 * cell)
            bottom = min((min(belows) - 8) if belows else H - 4, hy + 5 * cell)
        out.append((name, max(0, hx - 12), max(0, hy - 4),
                    min(W - 1, right), min(H - 1, bottom), t))
    return out


def main():
    import detectors
    path = sys.argv[1] if len(sys.argv) > 1 else os.path.join(OUT, "last_scan.png")
    pil = Image.open(path).convert("RGB")
    rgb = np.array(pil)
    H, W = rgb.shape[:2]
    gray = cv2.cvtColor(rgb, cv2.COLOR_RGB2GRAY)
    headers = detect(pil)
    pans = detectors.panels(gray, headers)
    boxes = detectors.detect_all(headers, gray, W, H)
    print(f"found {len(boxes)} containers in {len(pans)} panels:")
    for x0, x1 in pans:                       # panel dividers (magenta)
        cv2.line(rgb, (x1 - 1, 0), (x1 - 1, H), (255, 0, 255), 2)
    colors = {"GRID": (255, 150, 0), "SLOT": (0, 220, 0)}
    for name, (x0, y0, x1, y1), t in boxes:
        print(f"  {name:<16} {t:<5} ({x0},{y0}) -> ({x1},{y1})")
        cv2.rectangle(rgb, (x0, y0), (x1, y1), colors[t], 2)
        cv2.putText(rgb, name, (x0 + 4, y0 + 17), cv2.FONT_HERSHEY_SIMPLEX,
                    0.5, (0, 255, 255), 1, cv2.LINE_AA)
    Image.fromarray(rgb).save(os.path.join(OUT, "containers.png"))
    print(f"\n-> {OUT}/containers.png  (green=slot, orange=grid, magenta=panel divider)")


if __name__ == "__main__":
    main()
