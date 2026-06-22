"""
cut_squares.py — Label-anchored "CSS-grid" layout of the gear screen.

Pipeline:
  1. OCR labels -> Label(name, x, y, w, h); anchor = top-left.
  2. Cluster label X into column lines, then split those columns into the 3 main
     panels (Character Equipment / Tactical Rig+Backpack / Secondary Loadout) by
     minimizing within-group spread (gaps alone fail: a within-panel sub-column
     gap can be wider than the real panel gap).
  3. PER PANEL (column isolation — never mix panels):
       - cluster labels into rows by Y (tol=ytol)
       - sort each row by X
       - rough div for each label:
           left   = label.x
           top    = label.y
           right  = next label.x in same row, else panel right
           bottom = next row.y,              else panel bottom
  4. Classify each label:
       SLOT  - regular equipment slot   -> div from row/col is the answer
       WIDE  - ON SLING / ON BACK        -> wide weapon slot
       GRID  - TACTICAL RIG/BACKPACK/... -> div is only a SEARCH REGION; the
                                            inner slot rectangles are parsed later

Original image is never modified. Outputs to out/:
  01_labels.png  OCR'd labels boxed
  02_panels.png  the 3 main panel columns
  03_divs.png    rough divs, colored by class, with names
  03_divs.txt    the structured layout (panel / row / col / rect / class)

Usage:
  python cut_squares.py
  python cut_squares.py -i "test screenshot 1.png" --eps 20 --ytol 25
"""
import argparse
import os
from itertools import combinations

from PIL import Image, ImageDraw, ImageFont
import numpy as np

from find_items import find_labels

SLOT_LABELS = {"EARPIECE", "HEADWEAR", "FACE COVER", "ARMBAND", "BODY ARMOR",
               "EYEWEAR", "DOGTAG", "HOLSTER", "SHEATH"}
WIDE_SLOT_LABELS = {"ON SLING", "ON BACK"}
GRID_LABELS = {"TACTICAL RIG", "BACKPACK", "POCKETS", "SPECIAL SLOTS"}

# Constraint graph for the equipment layout: each label declares which SPECIFIC
# neighbor anchors its right edge and which anchors its bottom edge. The right
# edge meets the anchor's left edge; the bottom edge meets the anchor's top.
# A None anchor (or an anchor absent from the panel) falls back to flow layout.
# Keyed by label name, so it resolves within whichever panel the label appears
# in (left equipment column and the right loadout column both use it).
EQUIPMENT_ANCHORS = {
    # name:        (right_anchor,  bottom_anchor)
    "EARPIECE":    ("HEADWEAR",    "ARMBAND"),
    "HEADWEAR":    ("FACE COVER",  "BODY ARMOR"),
    "FACE COVER":  (None,          "EYEWEAR"),
    "ARMBAND":     ("BODY ARMOR",  "DOGTAG"),
    "BODY ARMOR":  ("EYEWEAR",     "ON SLING"),
    "EYEWEAR":     (None,          "HOLSTER"),
    "DOGTAG":      ("BODY ARMOR",  "ON SLING"),
    "ON SLING":    ("HOLSTER",     "ON BACK"),
    "HOLSTER":     (None,          "SHEATH"),
    "ON BACK":     ("SHEATH",      None),
    "SHEATH":      (None,          None),
}

CLASS_COLOR = {"SLOT": (0, 255, 0), "WIDE": (60, 160, 255),
               "GRID": (255, 160, 0), "OTHER": (180, 180, 180)}


def classify(name):
    n = name.upper()
    if n in WIDE_SLOT_LABELS:
        return "WIDE"
    if n in GRID_LABELS:
        return "GRID"
    if n in SLOT_LABELS:
        return "SLOT"
    return "OTHER"


def cluster_1d(values, eps):
    """Cluster sorted values: consecutive within eps join. Return cluster means."""
    if not values:
        return []
    values = sorted(values)
    groups = [[values[0]]]
    for v in values[1:]:
        if v - groups[-1][-1] <= eps:
            groups[-1].append(v)
        else:
            groups.append([v])
    return [int(round(sum(g) / len(g))) for g in groups]


def variance(vals):
    if len(vals) < 2:
        return 0.0
    m = sum(vals) / len(vals)
    return sum((v - m) ** 2 for v in vals) / len(vals)


def split_groups(centers, k):
    """Split sorted 1-D `centers` into k contiguous groups minimizing total
    within-group variance (1-D k-means by brute force over split points)."""
    n = len(centers)
    if n <= k:
        return [[c] for c in centers]
    best = None
    for splits in combinations(range(1, n), k - 1):
        idx = [0] + list(splits) + [n]
        groups = [centers[idx[i]:idx[i + 1]] for i in range(k)]
        cost = sum(variance(g) for g in groups)
        if best is None or cost < best[0]:
            best = (cost, groups)
    return best[1]


def nearest_idx(centers, v):
    return min(range(len(centers)), key=lambda i: abs(centers[i] - v))


def column_density(img, k=21):
    """Smoothed per-column edge density. Panels (UI) are high; the background
    gaps between panels are near-zero."""
    g = np.asarray(img.convert("L"), dtype=float)
    gx = np.abs(np.diff(g, axis=1)).mean(axis=0)
    gx = np.concatenate([gx, gx[-1:]])  # pad back to full width
    kernel = np.ones(k) / k
    return np.convolve(gx, kernel, mode="same")


def gap_separator(density, lo, hi):
    """X of minimum density within (lo, hi) — the real gap between two panels."""
    lo, hi = int(lo), int(hi)
    if hi <= lo + 1:
        return (lo + hi) // 2
    seg = density[lo:hi]
    return lo + int(np.argmin(seg))


def load_font(size):
    for name in ("arialbd.ttf", "arial.ttf", "DejaVuSans-Bold.ttf"):
        try:
            return ImageFont.truetype(name, size)
        except OSError:
            continue
    return ImageFont.load_default()


def build_layout(img, eps=20, ytol=25, offset=8, panels=3, scale=2, verbose=True):
    """Run the full label -> panel -> div pipeline and return the layout:
        {"labels", "col_centers", "panel_cols", "panel_x", "divs"}
    Each div is {"name","panel","rect"=(x0,y0,x1,y1),"class","layout"}.
    Shared by the CLI here and by the per-slot masking stage (slot_mask.py)."""
    def log(*a):
        if verbose:
            print(*a)

    W, H = img.size

    # --- Step 1: labels ---
    labels = [(t, int(x), int(y), int(bw), int(bh))
              for (t, x, y, bw, bh) in find_labels(img, scale=scale)]
    log(f"Step 1: {len(labels)} labels")

    # --- Step 2: column lines -> split into main panels ---
    col_centers = cluster_1d([x for (_, x, *_ ) in labels], eps)
    panel_cols = split_groups(col_centers, panels)
    log(f"Step 2: columns {col_centers}")
    for i, g in enumerate(panel_cols):
        log(f"         panel {i}: columns {g}")

    # Panel x-bounds: separators at the minimum-density column in the gap
    # between each adjacent pair of panels (labels aren't centered in panels,
    # so a column midpoint lands at the panel edge, not the real gap).
    density = column_density(img)
    seps = [0]
    for i in range(len(panel_cols) - 1):
        seps.append(gap_separator(density, panel_cols[i][-1],
                                  panel_cols[i + 1][0]))
    seps.append(W)
    log(f"Step 2: panel separators at x={seps[1:-1]}")
    # panel index -> (x_left_bound, x_right_bound)
    panel_x = {i: (seps[i], seps[i + 1]) for i in range(len(panel_cols))}
    # which panel does a given column center belong to
    col_panel = {}
    for i, g in enumerate(panel_cols):
        for c in g:
            col_panel[c] = i

    def panel_of(x):
        return col_panel[col_centers[nearest_idx(col_centers, x)]]

    # --- Step 3: resolve each label's rectangle via constraint graph + flow ---
    # Equipment labels (in EQUIPMENT_ANCHORS) resolve their right/bottom edges
    # from SPECIFIC named neighbors. Anything else — inventory grids, and any
    # equipment anchor that's None or missing — falls back to flow layout:
    #   right  = next label to the right in the same row, else panel right
    #   bottom = next label below in the same column, else next label below
    #            anywhere in the panel, else panel bottom
    off = offset
    divs = []
    for pi in range(len(panel_cols)):
        members = [lab for lab in labels if panel_of(lab[1]) == pi]
        if not members:
            continue
        pl, pr = panel_x[pi]

        # panel-bottom estimate = last row + median row gap
        row_ys = sorted(cluster_1d([y for (_, x, y, *_ ) in members], ytol))
        gaps = [row_ys[i + 1] - row_ys[i] for i in range(len(row_ys) - 1)]
        med_gap = sorted(gaps)[len(gaps) // 2] if gaps else (H - row_ys[0])
        panel_bottom = min(H, row_ys[-1] + med_gap)

        by_name = {}
        for lab in members:
            by_name.setdefault(lab[0].upper(), lab)

        def flow_right(lab):
            _, x, y, _, _ = lab
            same_row = [m for m in members if m[1] > x + 5 and abs(m[2] - y) <= ytol]
            return (min(m[1] for m in same_row) - off) if same_row else pr

        def flow_bottom(lab):
            _, x, y, _, _ = lab
            same_col = [m for m in members if abs(m[1] - x) <= eps and m[2] > y + 5]
            if same_col:
                return min(m[2] for m in same_col) - off
            below = [m for m in members if m[2] > y + ytol]
            if below:
                return min(m[2] for m in below) - off
            return panel_bottom

        for lab in members:
            name, x, y, bw, bh = lab
            rule = EQUIPMENT_ANCHORS.get(name.upper())
            left = max(pl, x - off)
            top = max(0, y - off)

            # RIGHT: constraint anchor if available, else flow
            if rule and rule[0] and rule[0] in by_name:
                right = by_name[rule[0]][1] - off
            else:
                right = flow_right(lab)
            # BOTTOM: constraint anchor if available, else flow
            if rule and rule[1] and rule[1] in by_name:
                bottom = by_name[rule[1]][2] - off
            else:
                bottom = flow_bottom(lab)

            divs.append({
                "name": name, "panel": pi,
                "rect": (left, top, right, bottom),
                "class": classify(name),
                "layout": "constraint" if rule else "flow",
            })

    divs.sort(key=lambda d: (d["panel"], d["rect"][1], d["rect"][0]))
    n_con = sum(1 for d in divs if d["layout"] == "constraint")
    log(f"Step 3: {len(divs)} divs ({n_con} constraint, {len(divs) - n_con} flow)")

    return {"labels": labels, "col_centers": col_centers,
            "panel_cols": panel_cols, "panel_x": panel_x, "divs": divs}


def main():
    p = argparse.ArgumentParser()
    p.add_argument("-i", "--input", default="test screenshot 1.png")
    p.add_argument("-o", "--outdir", default="out")
    p.add_argument("--eps", type=int, default=20, help="X cluster tolerance.")
    p.add_argument("--ytol", type=int, default=25, help="Row cluster tolerance.")
    p.add_argument("--offset", type=int, default=8,
                   help="Shift each div's top-left out by this many px so the "
                        "container fits inside (label sits inset from corner).")
    p.add_argument("--panels", type=int, default=3, help="Number of main columns.")
    p.add_argument("--scale", type=int, default=2, help="OCR upscale factor.")
    args = p.parse_args()

    img = Image.open(args.input).convert("RGB")
    W, H = img.size

    layout = build_layout(img, eps=args.eps, ytol=args.ytol, offset=args.offset,
                          panels=args.panels, scale=args.scale)
    labels = layout["labels"]
    panel_x = layout["panel_x"]
    panel_cols = layout["panel_cols"]
    divs = layout["divs"]

    os.makedirs(args.outdir, exist_ok=True)

    def out(n):
        return os.path.join(args.outdir, n)

    font = load_font(max(12, W // 110))

    # 01: labels
    lab_img = img.copy()
    dl = ImageDraw.Draw(lab_img)
    for (t, x, y, bw, bh) in labels:
        dl.rectangle([x, y, x + bw, y + bh], outline=(0, 255, 0), width=2)
    lab_img.save(out("01_labels.png"))

    # 02: panels
    pan_img = img.copy()
    dp = ImageDraw.Draw(pan_img)
    pan_colors = [(255, 80, 80), (80, 220, 80), (80, 160, 255)]
    pan_names = ["Character Equipment", "Tactical Rig / Backpack",
                 "Secondary Loadout"]
    for pi, (xl, xr) in panel_x.items():
        col = pan_colors[pi % len(pan_colors)]
        dp.rectangle([xl, 0, xr, H - 1], outline=col, width=4)
        if pi < len(pan_names):
            dp.text((xl + 8, 8), pan_names[pi], fill=col, font=font)
    pan_img.save(out("02_panels.png"))

    # 03: divs colored by class
    div_img = img.copy()
    dd = ImageDraw.Draw(div_img)
    for d in divs:
        x0, y0, x1, y1 = d["rect"]
        col = CLASS_COLOR[d["class"]]
        dd.rectangle([x0, y0, x1, y1], outline=col, width=3)
        dd.text((x0 + 4, y0 + 4), f"{d['name']} ({d['class']})", fill=col, font=font)
    div_img.save(out("03_divs.png"))

    # 03 text structure
    lines = [f"panel x-bounds: {panel_x}", ""]
    for pi in range(len(panel_cols)):
        lines.append(f"== Panel {pi}: {pan_names[pi] if pi < len(pan_names) else ''} ==")
        for d in [d for d in divs if d["panel"] == pi]:
            x0, y0, x1, y1 = d["rect"]
            lines.append(f"  {d['layout']:<10} {d['class']:<5} "
                         f"{d['name']:<14} rect=({x0},{y0},{x1},{y1}) "
                         f"{x1 - x0}x{y1 - y0}")
        lines.append("")
    with open(out("03_divs.txt"), "w", encoding="utf-8") as f:
        f.write("\n".join(lines))

    print("\n".join(lines))
    print(f"Wrote 01_labels.png, 02_panels.png, 03_divs.png, 03_divs.txt to {args.outdir}/")


if __name__ == "__main__":
    main()
