"""
Per-container-type detectors.

Header OCR reliably gives each container's NAME + position. Each container type
has a STATIC geometry (offset + size relative to its header) at a given
resolution, so we look it up instead of detecting bounds from pixels.

GEOM[name] = (dx, dy, w, h)  -- content box = header.xy + (dx,dy), size (w,h).
Calibrated @ 2560x1440. Add/adjust entries per slot type as we measure them.
"""

# (dx, dy, w, h) relative to the OCR header top-left, calibrated @ 2560x1440
GEOM = {
    # primary weapon slots
    "ON SLING": (-15, 16, 423, 155),
    "ON BACK":  (-15, 16, 423, 155),
    # equipment slots (left panel) -- first-pass measurements, refine by render
    "EARPIECE":   (-19, 13, 228, 120),
    "HEADWEAR":   (-16, 13, 250, 205),
    "FACE COVER": (-16, 13, 250, 205),
    "ARMBAND":    (-18, 13, 228, 90),
    "BODY ARMOR": (-16, 13, 250, 220),
    "EYEWEAR":    (-18, 13, 228, 120),
    "DOGTAG":     (-19, 13, 228, 90),
    "HOLSTER":    (-15, 22, 188, 158),
    "SHEATH":     (-15, 22, 188, 150),
}


import numpy as np

# grid containers: their height depends on the equipped item, so the box runs
# from this header's text down to the NEXT header's text. dx = left offset.
GRID_NAMES = {"TACTICAL RIG", "BACKPACK", "POCKETS", "SPECIAL SLOTS", "STASH"}
GRID_DX = -5


def panels(gray, headers):
    """Split the screen into vertical panels (your idea: 3 columns first).
    The middle|right divider is the one strong dark gutter; the equipment|gear
    divider has no brightness signal, so we derive it from where the grid
    containers start. Returns a sorted list of (x0, x1) panel spans."""
    W = gray.shape[1]
    band = gray[200:1000, :].astype(float).mean(0)
    strong = []
    for i in np.argsort(band):
        if band[i] > 12:
            break
        if all(abs(i - j) > 200 for j in strong):
            strong.append(int(i))
    right_div = min([g for g in strong if 1300 < g < 2000], default=int(W * 0.64))
    grid_xs = [hx for (n, hx, hy, w, h) in headers
               if n in GRID_NAMES and hx < right_div]
    left_div = (min(grid_xs) - 35) if grid_xs else int(W * 0.33)
    bounds = sorted({0, left_div, right_div, W})
    return [(bounds[i], bounds[i + 1]) for i in range(len(bounds) - 1)]


def panel_of(x, pans):
    for x0, x1 in pans:
        if x0 <= x < x1:
            return (x0, x1)
    return (0, pans[-1][1])


def detect(name, hx, hy):
    """Static slot box, or None if this is a grid / uncalibrated type."""
    g = GEOM.get(name)
    if not g:
        return None
    dx, dy, w, h = g
    return (hx + dx, hy + dy, hx + dx + w, hy + dy + h)


def detect_all(headers, gray, W, H):
    """All container boxes, each clamped to its panel.
    headers = [(name, x, y, w, h)]. Returns [(name, box, type)]."""
    pans = panels(gray, headers)
    out = []
    for name, hx, hy, hw, hh in headers:
        px0, px1 = panel_of(hx, pans)
        box = detect(name, hx, hy)
        if box:                                   # static equipment slot
            x0, y0, x1, y1 = box
            out.append((name, (x0, y0, min(x1, px1 - 4), y1), "SLOT"))
            continue
        if name not in GRID_NAMES:
            continue
        # grid: width to the next header in the same row (side-by-side) or panel
        # edge; height from this header's text to the next header below in-panel.
        rights = [x2 for (n2, x2, y2, w2, h2) in headers
                  if hx + 30 < x2 < px1 and abs(y2 - hy) < 45]
        belows = [y2 for (n2, x2, y2, w2, h2) in headers
                  if y2 > hy + 25 and px0 <= x2 < px1]
        x0 = hx + GRID_DX
        x1 = (min(rights) - 14) if rights else px1 - 6
        y0 = hy - 2
        y1 = (min(belows) - 4) if belows else H - 4
        out.append((name, (x0, y0, x1, y1), "GRID"))
    return out
